import type { NodeAPI } from 'node-red';
import { WaveshareDANode } from './nodes/waveshare-da';
import { WaveshareADNode } from './nodes/waveshare-ad';

module.exports = (RED: NodeAPI): void => {
  RED.nodes.registerType('waveshare-da', WaveshareDANode);
  RED.nodes.registerType('waveshare-ad', WaveshareADNode);
};
