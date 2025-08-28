type: module

import { spawn, ChildProcess } from 'child_process';
import { WorkerRequest, WorkerResponse, WorkerManager as IWorkerManager } from '../../types/node-red.js';
import { EventEmitter } from 'events';
import * as path from 'node:path';

export class WorkerManager extends EventEmitter implements IWorkerManager {
    private worker: ChildProcess | null = null;
    private requestQueue: Array<{
        request: WorkerRequest;
        resolve: (value: any) => void;
        reject: (error: Error) => void;
        timeout: NodeJS.Timeout;
    }> = [];
    private inFlight: Map<string, {
        request: WorkerRequest;
        resolve: (value: any) => void;
        reject: (error: Error) => void;
        timeout: NodeJS.Timeout;
    }> = new Map();
    private isProcessing = false;
    private correlationId = 0;
    private config: any;
    private refCount = 0;
    private pythonPath: string;

    constructor(config: any) {
        super();
        this.config = config;
        this.pythonPath = '/usr/bin/env python3'; // Use shebang-style path
    }

    /**
     * Add a reference to this worker manager
     */
    addRef(): void {
        this.refCount++;
        this.log(`Worker manager reference count: ${this.refCount}`);
        
        if (this.refCount === 1) {
            this.startWorker();
        }
    }

    /**
     * Remove a reference from this worker manager
     */
    removeRef(): void {
        this.refCount--;
        this.log(`Worker manager reference count: ${this.refCount}`);
        
        if (this.refCount <= 0) {
            this.stopWorker();
        }
    }

    /**
     * Start the Python worker process
     */
    private startWorker(): void {
        if (this.worker) {
            this.log('Worker already running');
            return;
        }

        try {
            let p = path.join( '..', 'python', 'worker.py');
            this.log(`path: ${p}`);
            const args = [
                '-u', // Unbuffered output
                p
            ];
          
            this.worker = spawn(this.pythonPath, args, {
                stdio: ['pipe', 'pipe', 'pipe'],
                cwd: process.cwd()
            });

            this.log('Python worker started');

            // Handle stdout (responses from worker)
            this.worker.stdout?.on('data', (data) => {
                this.handleWorkerOutput(data.toString());
            });

            // Handle stderr (logging from worker)
            this.worker.stderr?.on('data', (data) => {
                this.log(`Worker stderr: ${data.toString().trim()}`);
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
     */
    private stopWorker(): void {
        if (!this.worker) {
            return;
        }

        this.log('Stopping Python worker');
        
        // Send SIGTERM first
        this.worker.kill('SIGTERM');
        
        // Force kill after 2 seconds if still running
        setTimeout(() => {
            if (this.worker && !this.worker.killed) {
                this.log('Force killing worker');
                this.worker.kill('SIGKILL');
            }
        }, 2000);

        this.worker = null;
    }

    /**
     * Handle output from the Python worker
     */
    private handleWorkerOutput(output: string): void {
        const lines = output.trim().split('\n');
        
        for (const line of lines) {
            if (!line.trim()) continue;
            
            try {
                const response: WorkerResponse = JSON.parse(line);
                this.handleWorkerResponse(response);
            } catch (error) {
                this.log(`Failed to parse worker response: ${line}`);
            }
        }
    }

    /**
     * Handle a response from the worker
     */
    private handleWorkerResponse(response: WorkerResponse): void {
        const { id, result, error } = response;
        this.log(`worker response: id: ${id}, result: ${result}, error: ${error}`);
        
        const pending = id ? this.inFlight.get(id) : undefined;
        if (!pending) {
            this.log(`Received response for unknown request ID: ${id}`);
            return;
        }

        clearTimeout(pending.timeout);
        this.inFlight.delete(id!);

        if (error) {
            pending.reject(new Error(`Worker error: ${error.message}`));
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

        this.isProcessing = true;
        const queueItem = this.requestQueue.shift()!;

        try {
            const requestStr = JSON.stringify(queueItem.request) + '\n';
            this.worker.stdin?.write(requestStr);
            
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

        } catch (error) {
            this.log(`Failed to send request to worker: ${error}`);
            queueItem.reject(error as Error);
            this.isProcessing = false;
            this.processNextRequest();
        }
    }

    /**
     * Send a request to the worker
     */
    async request<T>(request: Omit<WorkerRequest, 'id'>): Promise<T> {
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
                reject,
                timeout: setTimeout(() => {}) // Will be set properly in processNextRequest
            };

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
     */
    isConnected(): boolean {
        return this.worker !== null && !this.worker.killed;
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
            clearTimeout(pending.timeout);
            pending.reject(new Error(reason));
        }
        this.inFlight.clear();

        for (const queued of this.requestQueue) {
            clearTimeout(queued.timeout);
            queued.reject(new Error(reason));
        }
        this.requestQueue = [];
        this.isProcessing = false;
    }

    /**
     * Log a message
     */
    private log(message: string): void {
        console.log(`[WorkerManager] ${message}`);
    }
}
