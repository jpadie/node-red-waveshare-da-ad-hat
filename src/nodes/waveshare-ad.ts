import type { Node } from 'node-red';
import { spawn } from 'child_process';

interface WaveshareADProperties {
  name: string;
  channel: number;
  gain: number;
  buffered: boolean;
  dataRate: number;
  id: string;
  type: string;
  z: string;
}

interface PythonScriptResult {
  success: boolean;
  output?: string;
  error?: string;
}

export default function(RED: any) {
  RED.nodes.registerType('waveshare-ad', function WaveshareADNode(this: Node, config: WaveshareADProperties) {
    RED.nodes.createNode(this, config);

    this.on('input', async (msg: any, send: any, done: any) => {
      try {
        // Parse inputs from message or config
        const channel = msg.payload?.channel ?? config.channel;
        const gain = msg.payload?.gain ?? config.gain;
        const buffered = msg.payload?.buffered ?? config.buffered;
        const dataRate = msg.payload?.dataRate ?? config.dataRate;

        // Validate inputs
        if (typeof channel !== 'number' || channel < 0 || channel > 7) {
          throw new Error('Channel must be a number between 0 and 7');
        }

        if (typeof gain !== 'number' || ![1, 2, 4, 8, 16, 32, 64].includes(gain)) {
          throw new Error('Gain must be one of: 1, 2, 4, 8, 16, 32, 64');
        }

        if (typeof buffered !== 'boolean') {
          throw new Error('Buffered must be a boolean');
        }

        if (typeof dataRate !== 'number' || ![2.5, 5, 10, 15, 25, 30, 50, 60, 100, 500, 1000, 2000, 3750, 7500, 15000, 30000].includes(dataRate)) {
          throw new Error('Data rate must be one of the supported values');
        }

        const result = await executePythonScript(channel, gain, buffered, dataRate);

        if (result.success) {
          // Parse the output to extract the reading value
          const readingMatch = result.output?.match(/AIN\d+ reading: (-?\d+)/);
          const readingValue = readingMatch ? parseInt(readingMatch[1], 10) : null;

          const outputMsg = {
            ...msg,
            payload: {
              channel,
              gain,
              buffered,
              dataRate,
              reading: readingValue,
              rawOutput: result.output,
              success: true,
              timestamp: Date.now()
            }
          };
          send(outputMsg);
          done();
        } else {
          throw new Error(result.error || 'Unknown error executing Python script');
        }
      } catch (error) {
        this.error(`ADC Error: ${error}`, msg);
        done();
      }
    });

    async function executePythonScript(channel: number, gain: number, buffered: boolean, dataRate: number): Promise<PythonScriptResult> {
      return new Promise((resolve) => {
        const pythonProcess = spawn('python3', [
          'python/ad.py',
          '--channel', channel.toString(),
          '--gain', gain.toString(),
          '--buffered', buffered ? '1' : '0',
          '--drate', dataRate.toString()
        ], {
          cwd: process.cwd()
        });

        let stdout = '';
        let stderr = '';

        pythonProcess.stdout.on('data', (data) => {
          stdout += data.toString();
        });

        pythonProcess.stderr.on('data', (data) => {
          stderr += data.toString();
        });

        pythonProcess.on('close', (code) => {
          if (code === 0) {
            resolve({
              success: true,
              output: stdout.trim()
            });
          } else {
            resolve({
              success: false,
              error: stderr || `Process exited with code ${code}`,
              output: stdout.trim()
            });
          }
        });

        pythonProcess.on('error', (error) => {
          resolve({
            success: false,
            error: error.message
          });
        });
      });
    }
  });
};
