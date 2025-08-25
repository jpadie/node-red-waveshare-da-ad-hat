import type { Node } from 'node-red';
import { spawn } from 'child_process';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

interface WaveshareDAProperties {
  name: string;
  value?: number;
  voltage?: number;
  vref: number;
  controlMode: 'value' | 'voltage';
  id: string;
  type: string;
  z: string;
  port: number;
}

interface PythonScriptResult {
  success: boolean;
  output?: string;
  error?: string;
}

module.exports = function(RED: any) {
    'use strict';

    function WaveshareDANode(this: any, config: any) {
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
                // Determine the value to set
                let value: number;
                let method: string;
                let params: any;

                if (config.controlMode === 'voltage') {
                    // Voltage mode: input should be voltage in volts
                    const voltage = parseFloat(msg.payload) || 0;
                    if (voltage < 0 || voltage > config.vref) {
                        throw new Error(`Voltage must be between 0 and ${config.vref}V`);
                    }
                    
                    method = 'set_dac_voltage';
                    params = {
                        port: parseInt(config.port) || 0,
                        voltage: voltage
                    };
                } else {
                    // Value mode: input should be raw DAC value (0-65535)
                    value = parseInt(msg.payload) || 0;
                    if (value < 0 || value > 65535) {
                        throw new Error('DAC value must be between 0 and 65535');
                    }
                    
                    method = 'set_dac_value';
                    params = {
                        port: parseInt(config.port) || 0,
                        value: value
                    };
                }

                // Send request to worker
                const result = await workerManager.request({
                    jsonrpc: '2.0',
                    method: method,
                    params: params
                });

                // Update message with result
                msg.payload = {
                    success: true,
                    port: result.port,
                    value: result.value,
                    voltage_mv: result.voltage_mv,
                    timestamp: new Date().toISOString()
                };

                // Update node status
                node.status({
                    fill: 'green',
                    shape: 'dot',
                    text: `${method === 'set_dac_voltage' ? 'V' : 'Raw'}: ${result.voltage_mv}mV`
                });

                node.send(msg);
                node.done();

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

    RED.nodes.registerType('waveshare-da', WaveshareDANode);
};