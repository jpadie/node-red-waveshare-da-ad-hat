import type { Node } from 'node-red';
import { spawn } from 'child_process';

interface WaveshareDAProperties {
  name: string;
  value?: number;
  voltage?: number;
  vref: number;
  controlMode: 'value' | 'voltage';
  id: string;
  type: string;
  z: string;
}

interface PythonScriptResult {
  success: boolean;
  output?: string;
  error?: string;
}

module.exports = function(RED: any) {
  RED.nodes.registerType('waveshare-da', function WaveshareDANode(this: Node, config: WaveshareDAProperties) {
    RED.nodes.createNode(this, config);

    this.on('input', async (msg: any, send: any, done: any) => {
      try {
        // Parse inputs from message or config
        const value = msg.payload?.value ?? config.value;
        const voltage = msg.payload?.voltage ?? config.voltage;
        const vref = msg.payload?.vref ?? config.vref;
        const controlMode = msg.payload?.controlMode ?? config.controlMode;

        // Validate inputs
        if (typeof vref !== 'number' || vref <= 0 || vref > 10) {
          throw new Error('VREF must be a number between 0 and 10V');
        }

        if (controlMode === 'voltage') {
          if (typeof voltage !== 'number' || voltage < 0 || voltage > vref) {
            throw new Error(`Voltage must be a number between 0 and ${vref}V`);
          }
        } else {
          if (typeof value !== 'number' || value < 0 || value > 65535) {
            throw new Error('Value must be a number between 0 and 65535');
          }
        }

        // Execute Python script
        const result = await executePythonScript(value, voltage, vref, controlMode);

        if (result.success) {
          // Parse the output to extract the actual values used
          const valueMatch = result.output?.match(/DAC value: (\d+)/);
          const voltageMatch = result.output?.match(/Output voltage: ([\d.]+)V/);
          
          const actualValue = valueMatch ? parseInt(valueMatch[1], 10) : value;
          const actualVoltage = voltageMatch ? parseFloat(voltageMatch[1]) : voltage;

          const outputMsg = {
            ...msg,
            payload: {
              value: actualValue,
              voltage: actualVoltage,
              vref,
              controlMode,
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
        this.error(`DAC Error: ${error}`, msg);
        done();
      }
    });

    async function executePythonScript(value: number | undefined, voltage: number | undefined, vref: number, controlMode: 'value' | 'voltage'): Promise<PythonScriptResult> {
      return new Promise((resolve) => {
        const args = ['python/da.py', '--vref', vref.toString()];
        
        if (controlMode === 'voltage' && voltage !== undefined) {
          args.push('--voltage', voltage.toString());
        } else if (value !== undefined) {
          args.push('--value', value.toString());
        }

        const pythonProcess = spawn('python3', args, {
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