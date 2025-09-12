type: module

const { workerManager } = require('./worker-manager.js');

module.exports = function(RED: any) {
    'use strict';

    function WaveshareDANode(this: any, config: any) {
        RED.nodes.createNode(this, config);
        
        const node = this;
        
        // Handle node removal
        node.on('close', () => {
            // Only remove ref if we added one
            if (node.hasRef) {
                workerManager.removeRef();
                node.hasRef = false;
            }
        });

        // Handle incoming messages
        node.on('input', async function(msg: any) {
            // Add reference to worker manager on first use
            if (!node.hasRef) {
                workerManager.addRef();
                node.hasRef = true;
            }
            
            try {
                // Get configuration values with payload override priority
                const port = parseInt(msg.payload?.port) || parseInt(config.port) || 0;
                const controlMode = msg.payload?.controlMode || config.controlMode || 'value';
                
                // Debug: Log configuration values
                node.log(`DAC Node Config - controlMode: ${controlMode}, port: ${port} (from payload: ${!!msg.payload?.controlMode})`);
                
                // Determine the value to set
                let value: number;
                let method: string;
                let params: any;

                let result: any;
                
                if (controlMode === 'voltage') {
                    // Use new writeDAC method for voltage mode
                    const voltage = parseFloat(msg.payload?.value);
                    if (isNaN(voltage)) {
                        throw new Error('Invalid voltage value');
                    }
                    
                    // Use new writeDAC method (handles 2.5V reference and clamping internally)
                    await workerManager.writeDAC(port, voltage);
                    
                    // Create result for backward compatibility
                    result = {
                        port: port,
                        voltage_mv: Math.round(voltage * 1000),
                        value: Math.round(voltage * 65535 / 2.5), // Convert to raw for display
                        vref: 2.5
                    };
                } else {
                    // Value mode: input should be raw DAC value (0-65535) from payload.value
                    value = parseInt(msg.payload?.value) || 0;
                    if (value < 0 || value > 65535) {
                        throw new Error('DAC value must be between 0 and 65535');
                    }
                    
                    method = 'set_dac_value';
                    params = {
                        port: port,
                        value: value
                    };
                    
                    // Send request to worker for raw value mode
                    result = await workerManager.request({
                        jsonrpc: '2.0',
                        method: method,
                        params: params
                    });
                }

                // Update message with result
                msg.payload = {
                    success: true,
                    port: result.port,
                    value: result.value,
                    voltage_mv: result.voltage_mv,
                    vref: result.vref,
                    timestamp: new Date().toISOString()
                };

                // Update node status
                node.status({
                    fill: 'green',
                    shape: 'dot',
                    text: controlMode === 'voltage' ? `V: ${result.voltage_mv ?? ''}mV` : `Raw: ${result.value}`
                });

                node.send(msg);

            } catch (error: any) {
                const errorMessage = error?.message || 'Unknown error';
                node.error(`DAC operation failed: ${errorMessage}`, msg);
                
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

    RED.nodes.registerType('waveshare-da', WaveshareDANode);
};