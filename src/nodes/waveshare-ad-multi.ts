type: module

const { workerManager } = require('./worker-manager.js');

interface ComparisonConfig {
    name: string;
    channel: number;
    differential: boolean;
    negChannel: number;
    gain: number;
    buffered: boolean;
    sps: number;
    // Optional per-comparison pair read toggle (present via HTML UI)
    // Kept optional to avoid breaking existing flows
    readPair?: boolean;
    selfcalBefore?: boolean;
}

interface WaveshareADMultiConfig {
    name: string;
    comparisons: ComparisonConfig[];
    emissionFrequency: number;
    outputFormat: 'aggregated' | 'individual';
}

interface ComparisonResult {
    name: string;
    channel: number;
    raw: number;
    mV: number;
    config: {
        vref: number;
        pga: number;
        sps: number;
        buffered: boolean;
        differential: boolean;
        negChannel?: number | null;
        timestamp: string;
    };
}

interface AggregatedPayload {
    timestamp: string;
    measurements: ComparisonResult[];
    cycleStats: {
        totalCycleTime: number;
        samplesPerComparison: number;
        emissionFrequency: number;
    };
}

module.exports = function (RED: any) {
    'use strict';

    function WaveshareADMultiNode(this: any, config: WaveshareADMultiConfig) {
        RED.nodes.createNode(this, config);
        const node = this;
        
        let streamingActive = false;
        let emissionTimer: NodeJS.Timeout | null = null;
        let measurementBuffer: ComparisonResult[] = [];
        let lastEmissionTime = 0;
        
        // Validate configuration
        if (!config.comparisons || config.comparisons.length === 0) {
            node.error("No comparisons configured");
            node.status({ fill: "red", shape: "dot", text: "No comparisons configured" });
            return;
        }
        
        // Validate comparison configurations
        for (const comp of config.comparisons) {
            if (comp.channel < 0 || comp.channel > 7) {
                node.error(`Invalid channel ${comp.channel} in comparison "${comp.name}"`);
                return;
            }
            if (comp.differential && (comp.negChannel < 0 || comp.negChannel > 7)) {
                node.error(`Invalid negative channel ${comp.negChannel} in comparison "${comp.name}" - must be 0-7 in differential mode`);
                return;
            }
            if (![1, 2, 4, 8, 16, 32, 64].includes(comp.gain)) {
                node.error(`Invalid gain ${comp.gain} in comparison "${comp.name}"`);
                return;
            }
            if (![2.5, 5, 10, 15, 25, 30, 50, 60, 100, 500, 1000, 2000, 3750, 7500, 15000, 30000].includes(comp.sps)) {
                node.error(`Invalid sample rate ${comp.sps} in comparison "${comp.name}"`);
                return;
            }
        }
        
        // Start streaming function
        const startStreaming = async () => {
            if (streamingActive) return;
            
            try {
                streamingActive = true;
                measurementBuffer = [];
                lastEmissionTime = Date.now();
                
                // Subscribe to worker manager for streaming
                workerManager.addRef();
                
                // Set up emission timer
                const emissionIntervalMs = 1000 / config.emissionFrequency;
                emissionTimer = setInterval(() => {
                    emitResults();
                }, emissionIntervalMs);
                
                // Start the round-robin measurement cycle
                startMeasurementCycle();
                
                node.status({ 
                    fill: "green", 
                    shape: "dot", 
                    text: `Streaming ${config.comparisons.length} comparisons @ ${config.emissionFrequency}Hz` 
                });
                
                node.log(`Started multi-ADC streaming with ${config.comparisons.length} comparisons at ${config.emissionFrequency}Hz`);
                
            } catch (error: any) {
                node.error(`Failed to start streaming: ${error.message}`);
                node.status({ fill: "red", shape: "dot", text: "Streaming failed" });
                stopStreaming();
            }
        };
        
        // Stop streaming function
        const stopStreaming = () => {
            if (!streamingActive) return;
            
            streamingActive = false;
            
            if (emissionTimer) {
                clearInterval(emissionTimer);
                emissionTimer = null;
            }
            
            try {
                workerManager.removeRef();
            } catch (error: any) {
                node.warn(`Error removing worker manager reference: ${error.message}`);
            }
            
            node.status({ fill: "grey", shape: "dot", text: "Stopped" });
            node.log("Stopped multi-ADC streaming");
        };
        
        // Round-robin measurement cycle
        const startMeasurementCycle = async () => {
            while (streamingActive) {
                const cycleStartTime = Date.now();
                const cycleMeasurements: ComparisonResult[] = [];
                
                try {
                    // Process each comparison in sequence
                    for (const comparison of config.comparisons) {
                        if (!streamingActive) break;
                        
                        const usePair: boolean = !!comparison.differential && !!(comparison as any).readPair;
                        let comparisonResult: any;
                        if (usePair) {
                            const rpcReq = {
                                jsonrpc: '2.0',
                                method: 'read_pair',
                                params: {
                                    a: comparison.channel,
                                    b: comparison.negChannel,
                                    gain: comparison.gain,
                                    sps: comparison.sps,
                                    buffered: comparison.buffered,
                                    selfcal_before: !!(comparison as any).selfcalBefore
                                }
                            };
                            const pair = await workerManager.request(rpcReq);
                            comparisonResult = {
                                name: comparison.name,
                                mode: 'read_pair',
                                pair: pair,
                                params: rpcReq.params
                            };
                        } else {
                            const result = await workerManager.readADC(comparison.channel, {
                                gain: comparison.gain,
                                drate: comparison.sps,
                                differential: comparison.differential,
                                negChannel: comparison.negChannel,
                                buffered: comparison.buffered
                            });
                            comparisonResult = {
                                name: comparison.name,
                                channel: result.channel,
                                raw: result.raw,
                                mV: result.mV,
                                config: result.config
                            } as ComparisonResult;
                        }
                        
                        cycleMeasurements.push(comparisonResult);
                        
                        // Add to buffer for aggregated output
                        measurementBuffer.push(comparisonResult);
                        
                        // For individual output format, emit immediately
                        if (config.outputFormat === 'individual') {
                            const msg: any = {
                                payload: {
                                    success: true,
                                    comparison: comparisonResult,
                                    timestamp: new Date().toISOString()
                                }
                            };
                            node.send(msg);
                        }
                    }
                    
                    const cycleTime = Date.now() - cycleStartTime;
                    
                    // Brief pause between cycles to prevent overwhelming the system
                    const minCycleTime = 10; // minimum 10ms between cycles
                    if (cycleTime < minCycleTime) {
                        await new Promise(resolve => setTimeout(resolve, minCycleTime - cycleTime));
                    }
                    
                } catch (error: any) {
                    node.error(`Error in measurement cycle: ${error.message}`);
                    // Continue with next cycle after brief delay
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
            }
        };
        
        // Emit aggregated results
        const emitResults = () => {
            if (config.outputFormat !== 'aggregated' || measurementBuffer.length === 0) {
                return;
            }
            
            const now = Date.now();
            const timeSinceLastEmission = now - lastEmissionTime;
            
            // Group measurements by comparison name to get latest values
            const latestMeasurements: { [name: string]: ComparisonResult } = {};
            measurementBuffer.forEach(measurement => {
                latestMeasurements[measurement.name] = measurement;
            });
            
            const measurements = Object.values(latestMeasurements);
            
            if (measurements.length > 0) {
                const payload: AggregatedPayload = {
                    timestamp: new Date().toISOString(),
                    measurements: measurements,
                    cycleStats: {
                        totalCycleTime: timeSinceLastEmission,
                        samplesPerComparison: Math.floor(measurementBuffer.length / config.comparisons.length),
                        emissionFrequency: config.emissionFrequency
                    }
                };
                
                const msg: any = {
                    payload: payload
                };
                
                node.send(msg);
            }
            
            // Clear buffer and reset timer
            measurementBuffer = [];
            lastEmissionTime = now;
        };
        
        // Handle input messages
        node.on('input', async (msg: any) => {
            const command = (msg.payload && msg.payload.command) ? msg.payload.command : 'toggle';
            
            try {
                switch (command) {
                    case 'start':
                        await startStreaming();
                        break;
                        
                    case 'stop':
                        stopStreaming();
                        break;
                        
                    case 'toggle':
                        if (streamingActive) {
                            stopStreaming();
                        } else {
                            await startStreaming();
                        }
                        break;
                        
                    case 'status':
                        const statusMsg: any = {
                            payload: {
                                active: streamingActive,
                                comparisons: config.comparisons.length,
                                emissionFrequency: config.emissionFrequency,
                                outputFormat: config.outputFormat,
                                bufferSize: measurementBuffer.length
                            }
                        };
                        node.send(statusMsg);
                        break;
                        
                    default:
                        // Default behavior: toggle streaming
                        if (streamingActive) {
                            stopStreaming();
                        } else {
                            await startStreaming();
                        }
                        break;
                }
            } catch (error: any) {
                node.error(`Command '${command}' failed: ${error.message}`, msg);
                node.status({ fill: "red", shape: "dot", text: `Error: ${error.message}` });
            }
        });
        
        // Handle node close
        node.on('close', (done: () => void) => {
            stopStreaming();
            done();
        });
        
        // Initialize with stopped status
        node.status({ fill: "grey", shape: "dot", text: "Ready" });
        
        // Auto-start if configured (could add this as an option)
        // await startStreaming();
    }

    RED.nodes.registerType("waveshare-ad-multi", WaveshareADMultiNode);
};
