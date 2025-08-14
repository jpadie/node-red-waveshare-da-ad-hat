#!/usr/bin/env node

const { spawn } = require('child_process');

console.log('Testing Python script integration...\n');

// Test DAC script with raw value
console.log('Testing DAC script (da.py) - Raw Value Mode:');
const dacProcess = spawn('python3', ['python/da.py', '--port', '0', '--value', '32768', '--vref', '3.3'], {
  cwd: process.cwd()
});

dacProcess.stdout.on('data', (data) => {
  console.log('DAC stdout:', data.toString());
});

dacProcess.stderr.on('data', (data) => {
  console.log('DAC stderr:', data.toString());
});

dacProcess.on('close', (code) => {
  console.log(`DAC process exited with code ${code}`);
  
  // Test DAC script with voltage control
  console.log('\nTesting DAC script (da.py) - Voltage Control Mode:');
  const dacVoltageProcess = spawn('python3', ['python/da.py', '--port', '1', '--voltage', '2.5', '--vref', '5.0'], {
    cwd: process.cwd()
  });

  dacVoltageProcess.stdout.on('data', (data) => {
    console.log('DAC Voltage stdout:', data.toString());
  });

  dacVoltageProcess.stderr.on('data', (data) => {
    console.log('DAC Voltage stderr:', data.toString());
  });

  dacVoltageProcess.on('close', (code) => {
    console.log(`DAC Voltage process exited with code ${code}`);
    
    // Test ADC script
    console.log('\nTesting ADC script (ad.py):');
    const adcProcess = spawn('python3', ['python/ad.py', '--channel', '0', '--gain', '1', '--buffered', '0', '--drate', '2.5'], {
      cwd: process.cwd()
    });

    adcProcess.stdout.on('data', (data) => {
      console.log('ADC stdout:', data.toString());
    });

    adcProcess.stderr.on('data', (data) => {
      console.log('ADC stderr:', data.toString());
    });

    adcProcess.on('close', (code) => {
      console.log(`ADC process exited with code ${code}`);
      console.log('\nTest completed!');
    });
  });
});
