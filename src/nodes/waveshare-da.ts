import { spawn } from 'child_process';
import { WaveshareDAProperties, PythonScriptResult } from '../../types/node-red';

export function createWaveshareDANode(RED: any) {
  return function WaveshareDANode(this: any, config: WaveshareDAProperties) {
    RED.nodes.createNode(this, config);
    
    const node = this;
    let updateTimer: NodeJS.Timeout | undefined;
    
    // Set up auto-update if enabled
    if (config.autoUpdate && config.updateInterval > 0) {
      setupAutoUpdate(config.updateInterval);
    }
    
    node.on('input', handleInput);
    node.on('close', handleClose);
    
    async function handleInput(msg: any, send: (msg: any) => void, done: () => void): Promise<void> {
      try {
        const port = msg.payload?.port ?? config.port ?? 0;
        const value = msg.payload?.value;
        const voltage = msg.payload?.voltage;
        const vref = msg.payload?.vref ?? config.vref ?? 3.3;
        
        if (typeof port !== 'number' || port < 0 || port > 1) {
          throw new Error('Port must be 0 or 1');
        }
        
        if (typeof vref !== 'number' || vref <= 0 || vref > 10) {
          throw new Error('VREF must be a positive number between 0 and 10V');
        }
        
        // Validate that either value or voltage is provided, but not both
        if (value !== undefined && voltage !== undefined) {
          throw new Error('Provide either value OR voltage, not both');
        }
        
        if (value === undefined && voltage === undefined) {
          throw new Error('Must provide either value or voltage');
        }
        
        let result: PythonScriptResult;
        
        if (value !== undefined) {
          // Set by raw DAC value
          if (typeof value !== 'number' || value < 0 || value > 65535) {
            throw new Error('Value must be between 0 and 65535 (16-bit DAC)');
          }
          result = await executePythonScript(port, value, undefined, vref);
        } else {
          // Set by voltage
          if (typeof voltage !== 'number' || voltage < 0 || voltage > vref) {
            throw new Error(`Voltage must be between 0 and ${vref}V`);
          }
          result = await executePythonScript(port, undefined, voltage, vref);
        }
        
        if (result.success) {
          const outputMsg = {
            ...msg,
            payload: {
              port,
              value: result.value,
              voltage: result.voltage,
              vref,
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
        node.error(`DAC Error: ${error}`, msg);
        done();
      }
    }

    async function executePythonScript(port: number, value?: number, voltage?: number, vref: number = 3.3): Promise<PythonScriptResult> {
      return new Promise((resolve) => {
        const args = ['python/da.py', '--port', port.toString(), '--vref', vref.toString()];
        
        if (value !== undefined) {
          args.push('--value', value.toString());
        } else if (voltage !== undefined) {
          args.push('--voltage', voltage.toString());
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
          if (code === 0) { // Success exit code from our refactored Python script
            // Parse the output to extract voltage and value information
            const voltageMatch = stdout.match(/= ([\d.]+)V/);
            const valueMatch = stdout.match(/DAC value: (\d+)/);
            
            const result: PythonScriptResult = {
              success: true,
              value: valueMatch ? parseInt(valueMatch[1], 10) : value,
              voltage: voltageMatch ? parseFloat(voltageMatch[1]) : voltage,
              output: stdout.trim()
            };
            
            resolve(result);
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

    function setupAutoUpdate(interval: number): void {
      updateTimer = setInterval(() => {
        const msg = {
          payload: {
            port: config.port,
            value: config.value,
            voltage: config.voltage,
            vref: config.vref
          }
        };
        node.emit('input', msg, node.send.bind(node), () => {});
      }, interval);
    }

    function handleClose(): void {
      if (updateTimer) {
        clearInterval(updateTimer);
      }
    }
  };
}
