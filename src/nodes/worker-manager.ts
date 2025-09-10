type: module

import { spawn, ChildProcess } from 'child_process';
import { WorkerRequest, WorkerResponse, WorkerManager as IWorkerManager } from '../../types/node-red.js';
import { EventEmitter } from 'events';
import * as path from 'node:path';

type ChannelConfig = {
    ch: number;
    differential?: boolean;
    neg?: number;
    gain?: number;
    drate?: number;
    buffered?: boolean;
};

type StreamSample = {
    streamId: string;
    seq?: number;
    channel: number;
    negChannel?: number | null;
    differential: boolean;
    buffered: boolean;
    raw: number;
    gain: number;
    drate: number;
    ts: number;
};

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

    // Stop gating to avoid overlapping workers during redeploy
    private stopping: boolean = false;
    private stoppingPromise: Promise<void> | null = null;

    // Streaming/subscriptions
    private subscriptions: Map<string, { cfg: ChannelConfig; handler: (sample: any) => void } > = new Map();
    private streamActive: boolean = false;
    private streamId: string = 'global';

    constructor(config: any) {
        super();
        this.config = config;
        // Dispatch stream samples to subscribers with conversion
        this.on('stream', (params: StreamSample) => {
            this.dispatchStreamSample(params);
        });
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
        if (this.stopping && this.stoppingPromise) {
            this.debug('Worker is stopping; delaying start');
            // Defer start slightly; request() will ensure start before use
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
                this.streamActive = false;
                if (this.stopping && this.stoppingPromise) {
                    this.stopping = false;
                    const done = this.stoppingPromise;
                    this.stoppingPromise = null;
                    // Resolve async on next tick
                    setTimeout(() => {
                        try { (done as any).resolve?.(); } catch {}
                    }, 0);
                }
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

        if (!this.stopping) {
            this.stopping = true;
            let resolveFn: () => void;
            this.stoppingPromise = new Promise<void>((resolve) => { resolveFn = resolve; }) as Promise<void> & { resolve?: () => void };
            (this.stoppingPromise as any).resolve = resolveFn!;
        }

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
    }

    // -----------------------------
    // Streaming & Subscriptions
    // -----------------------------
    subscribeAD(nodeId: string, cfg: ChannelConfig, handler: (sample: any) => void): void {
        const wasEmpty = this.subscriptions.size === 0;
        this.subscriptions.set(nodeId, { cfg, handler });
        if (wasEmpty) {
            this.addRef();
        }
        this.ensureStreamMatchesSubscriptions();
    }

    updateSubscription(nodeId: string, cfg: ChannelConfig): void {
        const existing = this.subscriptions.get(nodeId);
        if (existing) {
            existing.cfg = cfg;
            this.subscriptions.set(nodeId, existing);
            this.ensureStreamMatchesSubscriptions();
        } else {
            // If no existing, treat as new
            // eslint-disable-next-line @typescript-eslint/no-empty-function
            this.subscribeAD(nodeId, cfg, () => {});
        }
    }

    unsubscribeAD(nodeId: string): void {
        this.subscriptions.delete(nodeId);
        this.ensureStreamMatchesSubscriptions();
        if (this.subscriptions.size === 0) {
            // No more subscribers: stop stream and release ref
            (async () => { try { await this.request({ jsonrpc: '2.0', method: 'stop_stream', params: {} }); } catch {} })();
            this.streamActive = false;
            this.removeRef();
        }
    }

    private async ensureStreamMatchesSubscriptions(): Promise<void> {
        // Build unique channel list from subscriptions
        const channels: ChannelConfig[] = [];
        const keySet = new Set<string>();
        for (const [, sub] of this.subscriptions) {
            const cfg = {
                ch: sub.cfg.ch,
                differential: !!sub.cfg.differential,
                neg: sub.cfg.neg ?? 8,
                gain: sub.cfg.gain ?? 1,
                drate: sub.cfg.drate ?? 10.0,
                buffered: !!sub.cfg.buffered,
            } as ChannelConfig;
            const key = `${cfg.ch}|${cfg.differential?'1':'0'}|${cfg.neg}|${cfg.gain}|${cfg.drate}|${cfg.buffered?'1':'0'}`;
            if (!keySet.has(key)) {
                keySet.add(key);
                channels.push(cfg);
            }
        }

        if (channels.length === 0) {
            if (this.streamActive) {
                try { await this.request({ jsonrpc: '2.0', method: 'stop_stream', params: {} }); } catch {}
            }
            this.streamActive = false;
            return;
        }

        // Start or reconfigure stream
        try {
            if (this.streamActive) {
                try { await this.request({ jsonrpc: '2.0', method: 'stop_stream', params: {} }); } catch {}
            }
            await this.request({
                jsonrpc: '2.0',
                method: 'start_stream',
                params: {
                    streamId: this.streamId,
                    mode: 'round_robin',
                    channels: channels.map(c => ({
                        ch: c.ch,
                        differential: !!c.differential,
                        neg: c.neg ?? 8,
                        gain: c.gain ?? 1,
                        drate: c.drate ?? 10.0,
                        buffered: !!c.buffered
                    }))
                }
            });
            this.streamActive = true;
        } catch (error) {
            this.debug(`Failed to start stream: ${(error as Error)?.message ?? String(error)}`);
            this.streamActive = false;
        }
    }

    private dispatchStreamSample(sample: StreamSample): void {
        // Match to subscribers by channel and pairing
        for (const [, sub] of this.subscriptions) {
            const cfg = sub.cfg;
            const neg = cfg.differential ? (cfg.neg ?? 8) : null;
            const sampleNeg = sample.differential ? (sample.negChannel ?? null) : null;
            const channelMatch = sample.channel === cfg.ch;
            const diffMatch = !!sample.differential === !!cfg.differential;
            const negMatch = (neg ?? null) === (sampleNeg ?? null);
            const bufferedMatch = !!sample.buffered === !!cfg.buffered;
            if (channelMatch && diffMatch && negMatch && bufferedMatch) {
                const converted = this.convertSample(sample);
                try {
                    sub.handler(converted);
                } catch (e) {
                    this.debug(`Subscriber handler error: ${(e as Error)?.message ?? String(e)}`);
                }
            }
        }
    }

    private convertSample(sample: StreamSample): any {
        const ADC_VREF = 2.5;
        const denom = Math.pow(2, 23) - 1;
        const gain = sample.gain || 1;
        const voltage = (sample.raw / denom) * ((2 * ADC_VREF) / gain);
        return {
            ...sample,
            voltage,
            voltage_mv: voltage * 1000.0
        };
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
        // If a stop is in progress, wait for it to complete to avoid overlap
        if (this.stopping && this.stoppingPromise) {
            this.debug('Awaiting worker stop before starting new worker');
            try { await this.stoppingPromise; } catch {}
        }
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
