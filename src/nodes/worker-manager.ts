type: module

import { spawn, ChildProcess } from 'child_process';
import { WorkerRequest, WorkerResponse, WorkerManager as IWorkerManager } from '../../types/node-red.js';
import { EventEmitter } from 'events';
import * as path from 'node:path';

class WorkerManager extends EventEmitter implements IWorkerManager {
    private worker: ChildProcess | null = null;
    private requestQueue: Array<{
        request: WorkerRequest;
        resolve: (value: any) => void;
        reject: (error: Error) => void;
        timeout?: NodeJS.Timeout; // (6) optional; no placeholder timer
    }> = [];
    private inFlight: Map<string, {
        request: WorkerRequest;
        resolve: (value: any) => void;
        reject: (error: Error) => void;
        timeout?: NodeJS.Timeout;
    }> = new Map();
    private isProcessing = false; // (10) keep strictly serial for SPI
    private correlationId = 0;
    private config: any;
    private refCount = 0;

    // (5) stdout line buffer to handle chunking
    private stdoutBuffer = '';

    // Linger keep-alive across deploys
    // Linger disabled temporarily to avoid redeploy races
    private lingerTimer: NodeJS.Timeout | null = null;
    private lingerMs: number = 0;

    constructor(config: any) {
        super();
        this.config = config;
    }

    /**
     * Add a reference to this worker manager
     */
    addRef(): void {
        this.refCount++;
        this.debug(`Worker manager reference count: ${this.refCount}`);
        // Cancel pending linger stop if a new reference arrives
        // linger disabled
        // Don't start worker here - only start when first request comes in
    }

    /**
     * Remove a reference from this worker manager
     */
    removeRef(): void {
        this.refCount--;
        this.debug(`Worker manager reference count: ${this.refCount}`);
        if (this.refCount <= 0) {
            this.stopWorker();
        }
    }

    /**
     * Start the Python worker process
     */
    private startWorker(): void {
        if (this.worker) {
            this.debug('Worker already running');
            return;
        }

        try {
            const p = path.join(__dirname, '..', 'python', 'worker.py');
            this.debug(`path: ${p}`);
            const args = ['-u', p];

            this.worker = spawn('python3', args, {
                stdio: ['pipe', 'pipe', 'pipe']
                // (2) cwd intentionally left default per user note
            });

            this.log('Python worker started');

            // Handle stdout (responses from worker) with buffering (5)
            this.worker.stdout?.on('data', (data) => {
                this.handleWorkerOutput(data.toString());
            });

            // Handle stderr (logging from worker)
            this.worker.stderr?.on('data', (data) => {
                this.debug(`Worker stderr: ${data.toString().trim()}`);
            });

            // Handle worker exit
            this.worker.on('exit', (code, signal) => {
                this.log(`Worker exited with code ${code}, signal ${signal}`);
                this.worker = null;
                this.emit('workerExit', { code, signal });

                // Reject all pending requests
                this.rejectAllPending('Worker process exited');
            });

            this.worker.on('error', (error) => {
                this.log(`Worker error: ${error.message}`);
                this.emit('workerError', error);
                this.rejectAllPending(`Worker error: ${error.message}`);
            });
        } catch (error) {
            this.log(`Failed to start worker: ${error}`);
            throw error;
        }
    }

    /**
     * Stop the Python worker process
     * (3) Don't null the ref before we may force-kill
     */
    private stopWorker(): void {
        const proc = this.worker;
        if (!proc) return;

        this.log('Stopping Python worker');

        // Send SIGTERM first
        proc.kill('SIGTERM');

        // Force kill after 2 seconds if still running
        setTimeout(() => {
            if (proc.exitCode === null) {
                this.log('Force killing worker');
                proc.kill('SIGKILL');
            }
        }, 2000);

        this.worker = null;
    }

    /**
     * Handle output from the Python worker (5)
     */
    private handleWorkerOutput(chunk: string): void {
        this.stdoutBuffer += chunk;
        const lines = this.stdoutBuffer.split('\n');
        this.stdoutBuffer = lines.pop() ?? '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            try {
                const response: any = JSON.parse(trimmed);
                // Handle unsolicited stream events
                if (response && !response.id && response.method === 'stream_sample' && response.params) {
                    this.emit('stream', response.params);
                    continue;
                }
                this.handleWorkerResponse(response as WorkerResponse);
            } catch (error) {
                this.debug(`Failed to parse worker response: ${(error as Error)?.message ?? String(error)} | line=${trimmed}`);
            }
        }
    }

    /**
     * Handle a response from the worker
     */
    private handleWorkerResponse(response: WorkerResponse): void {
        const { id, result, error } = response;
        this.debug(`worker response: id=${id}, hasResult=${result !== undefined}, hasError=${!!error}`);

        const pending = id ? this.inFlight.get(id) : undefined;
        if (!pending) {
            this.debug(`Received response for unknown request ID: ${id}`);
            return;
        }

        if (pending.timeout) clearTimeout(pending.timeout);
        this.inFlight.delete(id!);

        if (error) {
            // (8) user controls error format; pass through message if present
            const msg = (error as any)?.message ?? String(error);
            pending.reject(new Error(`Worker error: ${msg}`));
        } else {
            pending.resolve(result);
        }

        // Mark processing complete and process next request in queue
        this.isProcessing = false;
        this.processNextRequest();
    }

    /**
     * Process the next request in the queue
     */
    private processNextRequest(): void {
        if (this.isProcessing || (!this.requestQueue.length && this.inFlight.size > 0) || !this.worker) {
            return;
        }

        if (this.requestQueue.length === 0) {
            // Nothing to send
            return;
        }

        this.isProcessing = true; // (10) serial by design for SPI
        const queueItem = this.requestQueue.shift()!;

        try {
            const requestStr = JSON.stringify(queueItem.request) + '\n';
            const wrote = this.worker.stdin!.write(requestStr); // (9) check backpressure

            // Track as in-flight and set timeout for this request
            const timeout = setTimeout(() => {
                const inflight = this.inFlight.get(queueItem.request.id);
                if (inflight) {
                    this.inFlight.delete(queueItem.request.id);
                    inflight.reject(new Error('Request timeout'));
                }
                this.isProcessing = false;
                this.processNextRequest();
            }, 10000);

            queueItem.timeout = timeout;
            this.inFlight.set(queueItem.request.id, queueItem);

            if (!wrote) {
                this.worker.stdin!.once('drain', () => {
                    // nothing extra; already marked in-flight & timed
                    this.debug('stdin drained after backpressure');
                });
            }
        } catch (error) {
            this.log(`Failed to send request to worker: ${error}`);
            queueItem.reject(error as Error);
            this.isProcessing = false;
            this.processNextRequest();
        }
    }

    /**
     * Send a request to the worker
     * (4) Start worker unconditionally if not running; refCount is lifecycle, not a hard gate
     */
    async request<T>(request: Omit<WorkerRequest, 'id'>): Promise<T> {
        if (!this.worker) {
            this.startWorker();
        }
        if (!this.worker) {
            throw new Error('Worker not running');
        }

        return new Promise<T>((resolve, reject) => {
            const fullRequest: WorkerRequest = {
                ...request,
                id: `req_${++this.correlationId}`
            };

            const queueItem = {
                request: fullRequest,
                resolve,
                reject
            } as typeof this.requestQueue[number];

            this.requestQueue.push(queueItem);
            this.processNextRequest();
        });
    }

    /**
     * Send a ping request to check if worker is alive
     */
    async ping(): Promise<boolean> {
        try {
            const result: any = await this.request({
                jsonrpc: '2.0',
                method: 'ping',
                params: {}
            });
            return result?.status === 'ok';
        } catch (error) {
            return false;
        }
    }

    /**
     * Check if the worker is connected
     * (7) Use exitCode instead of .killed
     */
    isConnected(): boolean {
        return !!(this.worker && this.worker.exitCode === null);
    }

    /**
     * Close the worker manager
     */
    close(): void {
        this.removeRef();
    }

    /**
     * Reject all pending requests
     */
    private rejectAllPending(reason: string): void {
        for (const [, pending] of this.inFlight) {
            if (pending.timeout) clearTimeout(pending.timeout);
            pending.reject(new Error(reason));
        }
        this.inFlight.clear();

        for (const queued of this.requestQueue) {
            if (queued.timeout) clearTimeout(queued.timeout);
            queued.reject(new Error(reason));
        }
        this.requestQueue = [];
        this.isProcessing = false;
    }

    /**
     * Log a message (11) separate log levels
     */
    private log(message: string): void {
        console.log(`[WorkerManager] ${message}`);
    }

    private debug(message: string): void {
        // Toggle with env or config flag if desired
        console.debug(`[WorkerManager:debug] ${message}`);
    }
}

// Export singleton instance - but don't start worker until first use
export const workerManager = new WorkerManager({});
