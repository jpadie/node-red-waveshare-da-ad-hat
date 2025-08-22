import type { Node } from 'node-red';
import { spawn } from 'child_process';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

interface WaveshareADProperties {
  name: string;
  channel: number;
  gain: number;
  buffered: boolean;
  dataRate: number;
  vref: number;
  id: string;
  type: string;
  z: string;
}

interface PythonScriptResult {
  success: boolean;
  output?: string;
  error?: string;
}

interface ADCReturnData {
  raw: number;
  voltage_mv: number;
  channel: number;
  gain: number;
  vref: number;
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
        const vref = msg.payload?.vref ?? config.vref;

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

        if (typeof vref !== 'number' || vref <= 0) {
          throw new Error('VREF must be a positive number');
        }

        const result = await executePythonScript(channel, gain, buffered, dataRate, vref);

        if (result.success) {
          // Parse the enhanced output to extract all values
          const adcData = parseADCOutput(result.output || '');
          
          if (adcData) {
            const outputMsg = {
              ...msg,
              payload: {
                ...adcData,
                buffered,
                dataRate,
                success: true,
                timestamp: Date.now()
              }
            };
            send(outputMsg);
            done();
          } else {
            throw new Error('Failed to parse ADC output data');
          }
        } else {
          throw new Error(result.error || 'Unknown error executing Python script');
        }
      } catch (error) {
        this.error(`ADC Error: ${error}`, msg);
        done();
      }
    });

    function parseADCOutput(output: string): ADCReturnData | null {
      try {
        const lines = output.trim().split('\n');
        const data: Partial<ADCReturnData> = {};
        
        for (const line of lines) {
          const [key, value] = line.split(':');
          if (key && value !== undefined) {
            switch (key) {
              case 'RAW':
                data.raw = parseInt(value, 10);
                break;
              case 'VOLTAGE_MV':
                data.voltage_mv = parseFloat(value);
                break;
              case 'CHANNEL':
                data.channel = parseInt(value, 10);
                break;
              case 'GAIN':
                data.gain = parseInt(value, 10);
                break;
              case 'VREF':
                data.vref = parseFloat(value);
                break;
            }
          }
        }
        
        // Verify all required fields are present
        if (data.raw !== undefined && data.voltage_mv !== undefined && 
            data.channel !== undefined && data.gain !== undefined && data.vref !== undefined) {
          return data as ADCReturnData;
        }
        
        return null;
      } catch (error) {
        console.error('Error parsing ADC output:', error);
        return null;
      }
    }

    async function executePythonScript(channel: number, gain: number, buffered: boolean, dataRate: number, vref: number): Promise<PythonScriptResult> {
      return new Promise((resolve) => {
        const pythonProcess = spawn('python3', [
          '../python/ad.py',
          '--channel', channel.toString(),
          '--gain', gain.toString(),
          '--buffered', buffered ? '1' : '0',
          '--drate', dataRate.toString(),
          '--vref', vref.toString()
        ], {
          cwd: __dirname
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
