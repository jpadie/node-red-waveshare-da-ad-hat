#!/usr/bin/env node

/**
 * Test script for the new worker architecture
 * Tests the WorkerManager class and Python worker communication
 */

import { WorkerManager } from './lib/worker-manager.js';

async function testWorker() {
    console.log('Testing Waveshare HAT Worker Architecture...\n');

    // Create worker manager with test config
    const config = {
        spiBus: 0,
        spiDevice: 0,
        spiSpeed: 1000000,
        csPin: 8,
        rstPin: 18,
        drdyPin: 7,
        dacVref: 5.0,
        adcVref: 5.0
    };

    const workerManager = new WorkerManager(config);

    try {
        console.log('1. Starting worker manager...');
        workerManager.addRef();

        // Wait a moment for worker to start
        await new Promise(resolve => setTimeout(resolve, 2000));

        console.log('2. Testing ping...');
        const pingResult = await workerManager.ping();
        console.log(`   Ping result: ${pingResult}`);

        if (pingResult) {
            console.log('3. Testing DAC operations...');
            
            // Test DAC value setting
            const dacValueResult = await workerManager.request({
                jsonrpc: '2.0',
                method: 'set_dac_value',
                params: { port: 0, value: 32768 }
            });
            console.log(`   DAC value result:`, dacValueResult);

            // Test DAC voltage setting
            const dacVoltageResult = await workerManager.request({
                jsonrpc: '2.0',
                method: 'set_dac_voltage',
                params: { port: 1, voltage: 2.5 }
            });
            console.log(`   DAC voltage result:`, dacVoltageResult);

            console.log('4. Testing ADC operations...');
            
            // Test ADC reading
            const adcResult = await workerManager.request({
                jsonrpc: '2.0',
                method: 'read_adc',
                params: { channel: 0, gain: 1, drate: 10.0 }
            });
            console.log(`   ADC result:`, adcResult);

        } else {
            console.log('   Worker not responding, skipping operations');
        }

        console.log('5. Testing multiple concurrent requests...');
        
        // Test multiple requests (they should be queued)
        const promises = [];
        for (let i = 0; i < 3; i++) {
            promises.push(
                workerManager.request({
                    jsonrpc: '2.0',
                    method: 'ping',
                    params: {}
                })
            );
        }
        
        const results = await Promise.all(promises);
        console.log(`   Concurrent requests completed: ${results.length}`);

        console.log('6. Testing worker cleanup...');
        workerManager.removeRef();
        
        // Wait for cleanup
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        console.log('   Worker cleanup completed');

    } catch (error) {
        console.error('Test failed:', error);
    }

    console.log('\nTest completed.');
}

// Handle process termination
process.on('SIGINT', () => {
    console.log('\nReceived SIGINT, exiting...');
    process.exit(0);
});

process.on('SIGTERM', () => {
    console.log('\nReceived SIGTERM, exiting...');
    process.exit(0);
});

// Run the test
testWorker().catch(console.error);
