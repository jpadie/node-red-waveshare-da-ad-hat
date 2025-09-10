type: module

const { workerManager } = require('./worker-manager.js');

module.exports = function(RED: any) {
    'use strict';

    function WaveshareADNode(this: any, config: any) {
        RED.nodes.createNode(this, config);
        
        const node = this;
        let subscriptionId: string | null = null;
        const getEffectiveConfig = () => {
            // If a config node is provided, prefer its settings
            const cfgNode = config.configRef ? RED.nodes.getNode(config.configRef) : null;
            const cfgFromNode = (() => {
                if (!cfgNode) return null;
                try {
                    const channels = Array.isArray(cfgNode.channels) ? cfgNode.channels : [];
                    // Find entry matching this node's channel or default to first
                    const desiredCh = parseInt(config.channel) || 0;
                    const found = channels.find((c: any) => parseInt(c.ch) === desiredCh) || channels[0];
                    if (!found) return null;
                    return {
                        channel: parseInt(found.ch),
                        differential: !!found.differential,
                        negChannel: parseInt(found.neg ?? 8),
                        gain: parseInt(found.gain ?? 1),
                        buffered: !!found.buffered,
                        drate: parseFloat(found.drate ?? 10.0)
                    };
                } catch {
                    return null;
                }
            })();
            if (cfgFromNode) return cfgFromNode;
            // Fallback to this node's own config
            return {
                channel: parseInt(config.channel) || 0,
                differential: !!config.differential,
                negChannel: parseInt(config.negChannel) || 8,
                gain: parseInt(config.gain) || 1,
                buffered: !!config.buffered,
                drate: parseFloat(config.drate) || 10.0
            };
        };

        const subscribeFromConfig = (baseMsg?: any) => {
            const eff = getEffectiveConfig();
            const subId = subscriptionId || `${node.id}`;
            const handler = (sample: any) => {
                const payload = {
                    success: true,
                    channel: sample.channel,
                    negChannel: sample.negChannel,
                    differential: !!sample.differential,
                    buffered: !!sample.buffered,
                    raw: sample.raw,
                    voltage_mv: sample.voltage_mv,
                    voltage: sample.voltage,
                    gain: sample.gain,
                    drate: sample.drate,
                    ts: sample.ts
                };
                node.status({
                    fill: 'green',
                    shape: 'dot',
                    text: `${payload.differential ? `Ch${payload.channel}-Ch${payload.negChannel}` : `Ch${payload.channel}`}: ${payload.voltage_mv?.toFixed?.(2) ?? ''}mV`
                });
                node.send({ ...(baseMsg || {}), payload });
            };
            workerManager.subscribeAD(subId, {
                ch: eff.channel,
                differential: eff.differential,
                neg: eff.negChannel,
                gain: eff.gain,
                drate: eff.drate,
                buffered: eff.buffered
            }, handler);
            subscriptionId = subId;
        };
        
        // Handle node removal
        node.on('close', () => {
            // Only remove ref if we added one
            if (node.hasRef) {
                workerManager.removeRef();
                node.hasRef = false;
            }
            if (subscriptionId) {
                workerManager.unsubscribeAD(subscriptionId);
                subscriptionId = null;
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
                // Re-subscribe using latest config (or payload overrides if needed)
                // For now, honor the static config; payload can be used to re-deploy node configuration
                subscribeFromConfig(msg);

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

        // Auto-subscribe on deploy using node/config settings
        if (!node.hasRef) {
            workerManager.addRef();
            node.hasRef = true;
        }
        subscribeFromConfig();
    }

    RED.nodes.registerType('waveshare-ad', WaveshareADNode);
};
