type: module

module.exports = function(RED: any) {
    'use strict';

    function WaveshareADNode(this: any, config: any) {
        RED.nodes.createNode(this, config);
        
        const node = this;
        const hatConfig = RED.nodes.getNode(config.hatConfig);
        
        if (!hatConfig) {
            node.error('Waveshare HAT Config node not found');
            return;
        }

        const workerManager = hatConfig.workerManager;
        if (!workerManager) {
            node.error('Worker manager not available');
            return;
        }

        // Add reference to worker manager
        workerManager.addRef();

        // Handle node removal
        node.on('close', () => {
            workerManager.removeRef();
        });

        // Handle incoming messages
        node.on('input', async function(msg: any) {
            try {
                // Get configuration values with payload override priority
                const channel = parseInt(msg.payload?.channel) || parseInt(config.channel) || 0;
                const differential = (msg.payload?.differential ?? config.differential) ? true : false;
                const negChannel = parseInt(msg.payload?.negChannel) || parseInt(config.negChannel) || 1;
                const gain = parseInt(msg.payload?.gain) || parseInt(config.gain) || 1;
                const bufferedRaw = (msg.payload?.buffered ?? config.buffered);
                const buffered = (() => {
                    if (typeof bufferedRaw === 'boolean') return bufferedRaw;
                    if (typeof bufferedRaw === 'number') return bufferedRaw !== 0;
                    if (typeof bufferedRaw === 'string') return ['1', 'true', 'on', 'yes'].includes(bufferedRaw.toLowerCase());
                    return false;
                })();
                const drate = parseFloat(msg.payload?.drate) || parseFloat(config.drate) || 10.0;
                const vref = parseFloat(msg.payload?.vref) || parseFloat(config.vref) || 5.0;
                
                // Debug: Log configuration values
                node.log(`ADC Node Config - channel: ${channel}, ${differential ? `- channel: ${negChannel}, `: ''}gain: ${gain}, buffered: ${buffered}, drate: ${drate}, vref: ${vref} (diff: ${differential})`);
                
                // Validate inputs
                if (channel < 0 || channel > 7) {
                    throw new Error('Channel must be between 0 and 7');
                }

                if (differential) {
                    if (negChannel < 0 || negChannel > 7) {
                        throw new Error('Negative channel must be between 0 and 7');
                    }
                    if (negChannel === channel) {
                        throw new Error('Positive and negative channels must differ');
                    }
                }

                if (![1, 2, 4, 8, 16, 32, 64].includes(gain)) {
                    throw new Error('Gain must be 1, 2, 4, 8, 16, 32, or 64');
                }

                if (![2.5, 5, 10, 15, 30, 60, 100, 500, 1000, 2000, 3750, 7500, 15000, 30000].includes(drate)) {
                    throw new Error('Invalid data rate');
                }

                // Send request to worker
                const result = await workerManager.request({
                    jsonrpc: '2.0',
                    method: 'read_adc',
                    params: {
                        channel: channel,
                        differential: differential,
                        negChannel: negChannel,
                        buffered: buffered,
                        gain: gain,
                        drate: drate,
                        vref: vref
                    }
                });

                // Update message with result
                msg.payload = {
                    success: true,
                    channel: result.channel,
                    negChannel: result.negChannel,
                    differential: !!result.differential,
                    buffered: !!result.buffered,
                    raw: result.raw,
                    voltage_mv: result.voltage_mv,
                    gain: result.gain,
                    drate: result.drate,
                    vref: result.vref,
                    timestamp: new Date().toISOString()
                };

                // Update node status
                node.status({
                    fill: 'green',
                    shape: 'dot',
                    text: `${differential ? `Ch${channel}-Ch${negChannel}` : `Ch${channel}`}: ${result.voltage_mv}mV`
                });

                node.send(msg);

            } catch (error: any) {
                const errorMessage = error?.message || 'Unknown error';
                node.error(`ADC operation failed: ${errorMessage}`, msg);
                
                // Update message with error
                msg.payload = {
                    success: false,
                    error: errorMessage,
                    timestamp: new Date().toISOString()
                };

                // Update node status
                node.status({
                    fill: 'red',
                    shape: 'ring',
                    text: `Error: ${errorMessage}`
                });

                node.send(msg);
            }
        });

        // Initial status
        node.status({
            fill: 'grey',
            shape: 'ring',
            text: 'Ready'
        });
    }

    RED.nodes.registerType('waveshare-ad', WaveshareADNode);
};
