import { WorkerManager } from '../worker-manager';

module.exports = function(RED: any) {
    'use strict';

    class WaveshareHATConfigNode {
        private workerManager: WorkerManager | null = null;
        private config: any;

        constructor(config: any) {
            RED.nodes.createNode(this, config);
            this.config = config;
            
            // Cast this to access Node-RED methods
            const node = this as any;

            // Initialize worker manager with config
            this.workerManager = new WorkerManager({
                spiBus: parseInt(config.spiBus) || 0,
                spiDevice: parseInt(config.spiDevice) || 0,
                spiSpeed: parseInt(config.spiSpeed) || 1000000,
                csPin: parseInt(config.csPin) || 8,
                rstPin: parseInt(config.rstPin) || 18,
                drdyPin: parseInt(config.drdyPin) || 7,
                dacVref: parseFloat(config.dacVref) || 5.0,
                adcVref: parseFloat(config.adcVref) || 5.0
            });

            // Handle node removal
            node.on('close', () => {
                if (this.workerManager) {
                    this.workerManager.close();
                }
            });

            // Log configuration
            node.log(`Waveshare HAT Config initialized: SPI ${config.spiBus}.${config.spiDevice}, CS:${config.csPin}, RST:${config.rstPin}, DRDY:${config.drdyPin}`);
        }

        /**
         * Get the worker manager instance
         */
        getWorkerManager(): WorkerManager | null {
            return this.workerManager;
        }

        /**
         * Get the configuration
         */
        getConfig(): any {
            return this.config;
        }
    }

    // Register the config node type
    RED.nodes.registerType('waveshare-hat-config', WaveshareHATConfigNode);

    // Store config nodes for access by other nodes
    if (!RED.nodes.configNodes) {
        RED.nodes.configNodes = {};
    }

    // Override the createNode method to store config nodes
    const originalCreateNode = RED.nodes.createNode;
    RED.nodes.createNode = function(config: any) {
        const node = originalCreateNode.call(this, config);
        
        if (config.type === 'waveshare-hat-config') {
            RED.nodes.configNodes[config.id] = node;
        }
        
        return node;
    };
};
