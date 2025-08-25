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

        const workerManager = hatConfig.getWorkerManager();
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
                // Get configuration values
                const channel = parseInt(config.channel) || 0;
                const gain = parseInt(config.gain) || 1;
                const drate = parseFloat(config.drate) || 10.0;
                const vref = parseFloat(config.vref) || 5.0;

                // Validate inputs
                if (channel < 0 || channel > 7) {
                    throw new Error('Channel must be between 0 and 7');
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
                        gain: gain,
                        drate: drate
                    }
                });

                // Update message with result
                msg.payload = {
                    success: true,
                    channel: result.channel,
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
                    text: `Ch${channel}: ${result.voltage_mv}mV`
                });

                node.send(msg);
                node.done();

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
                node.done();
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
