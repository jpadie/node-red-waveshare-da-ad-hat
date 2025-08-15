import { createWaveshareDANode } from './nodes/waveshare-da';
import { createWaveshareADNode } from './nodes/waveshare-ad';

module.exports = function(RED: any) {
  // Register the DAC node
  RED.nodes.registerType('waveshare-da', createWaveshareDANode(RED));
  
  // Register the ADC node
  RED.nodes.registerType('waveshare-ad', createWaveshareADNode(RED));
};

export { createWaveshareDANode, createWaveshareADNode };
