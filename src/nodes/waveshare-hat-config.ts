type: module

import {WorkerManager} from "./worker-manager.js";
module.exports = function(RED: any) {
    'use strict';

    function WaveshareHATConfigNode(this: any, config: any) {
        RED.nodes.createNode(this, config);
        
        const node = this;
        
        // Initialize worker manager with config
        const workerManager = new WorkerManager({
            spiBus: parseInt(config.spiBus) || 0,
            spiDevice: parseInt(config.spiDevice) || 0,
            spiSpeed: parseInt(config.spiSpeed) || 1000000,
            csPin: parseInt(config.csPin) || 8,
            rstPin: parseInt(config.rstPin) || 18,
            drdyPin: parseInt(config.drdyPin) || 7,
            dacVref: parseFloat(config.dacVref) || 5.0,
            adcVref: parseFloat(config.dacVref) || 5.0
        });

        // Store worker manager on the node instance
        node.workerManager = workerManager;

        // Handle node removal
        node.on('close', () => {
            if (workerManager) {
                workerManager.close();
            }
        });

        // Log configuration
        node.log(`Waveshare HAT Config initialized: SPI ${config.spiBus}.${config.spiDevice}, CS:${config.csPin}, RST:${config.rstPin}, DRDY:${config.drdyPin}`);
    }

    // Register the config node type
    RED.nodes.registerType('waveshare-hat-config', WaveshareHATConfigNode);
};
