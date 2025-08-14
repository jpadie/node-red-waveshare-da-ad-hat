import { createWaveshareDANode } from './nodes/waveshare-da';
import { createWaveshareADNode } from './nodes/waveshare-ad';

module.exports = function(RED: any) {
  RED.nodes.registerType('waveshare-da', createWaveshareDANode(RED));
  RED.nodes.registerType('waveshare-ad', createWaveshareADNode(RED));
};

export { createWaveshareDANode, createWaveshareADNode };
