type: module

import {WorkerManager} from "./worker-manager.js";
module.exports = function(RED: any) {
    'use strict';

    function WaveshareHATConfigNode(this: any, config: any) {
        RED.nodes.createNode(this, config);
        
        const node = this;
        
        // Initialize worker manager with minimal config (pins are hard-coded in Python)
        const workerManager = new WorkerManager({});

        // Store worker manager on the node instance
        node.workerManager = workerManager;

        // Handle node removal
        node.on('close', () => {
            if (workerManager) {
                workerManager.close();
            }
        });

        // Log configuration
        node.log(`Waveshare HAT Config initialized with hard-coded pins: ADC_CS=22, ADC_RST=18, ADC_DRDY=17, DAC_CS=23`);
    }

    // Register the config node type
    RED.nodes.registerType('waveshare-hat-config', WaveshareHATConfigNode);
};
