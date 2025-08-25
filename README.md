# Node-RED Waveshare DA-AD HAT

Custom Node-RED nodes for the Waveshare DA-AD HAT with a robust worker architecture for reliable SPI communication and resource management.

## Features

- **Digital-to-Analog Converter (DAC)**: 16-bit resolution (0-65535) with voltage control
- **Analog-to-Digital Converter (ADC)**: 8 single-ended channels with configurable gain and data rates
- **Worker Architecture**: Long-lived Python worker process with request queuing and exclusive SPI access
- **Resource Management**: Automatic cleanup and reference counting for multiple nodes
- **JSON-RPC Communication**: Structured communication between Node-RED and Python worker
- **Config Node**: Centralized configuration for hardware settings

## Architecture Overview

This package implements a **worker architecture** that addresses the key concerns of SPI contention, blocking access, and GPIO cleanup:

### Key Components

1. **Config Node** (`waveshare-hat-config`): Manages the Python worker process and hardware configuration
2. **Worker Manager**: Handles communication, request queuing, and resource lifecycle
3. **Python Worker**: Long-lived process that manages SPI and GPIO resources exclusively
4. **DAC/ADC Nodes**: Lightweight nodes that communicate with the worker via the config node

### Benefits

- **No Contention**: Single worker process ensures exclusive SPI access
- **Efficient**: No process spawning overhead for each operation
- **Reliable**: Automatic cleanup and watchdog timeout (5 seconds)
- **Scalable**: Multiple DAC/ADC nodes can share the same worker
- **Robust**: Request queuing and error handling

## Installation

```bash
npm install @jpadie/waveshare-da-ad-hat
```

## Hardware Requirements

- Waveshare DA-AD HAT
- Raspberry Pi (or compatible SBC)
- Python 3 with `spidev` and `RPi.GPIO` packages

## Usage

### 1. Configuration Node

First, add a **Waveshare HAT Config** node to your flow:

- **SPI Bus**: SPI bus number (usually 0)
- **SPI Device**: SPI device number (usually 0)  
- **SPI Speed**: Clock frequency in Hz (default: 1MHz)
- **CS Pin**: Chip select pin in BCM numbering (default: 8)
- **RST Pin**: Reset pin in BCM numbering (default: 18)
- **DRDY Pin**: Data ready pin in BCM numbering (default: 7)
- **DAC VREF**: Reference voltage for DAC (1.0V to 10.0V)
- **ADC VREF**: Reference voltage for ADC (0.1V to 10.0V)

### 2. DAC Node

Add a **Waveshare DA** node:

- **HAT Config**: Select the config node from step 1
- **DAC Port**: Choose DAC0 (Port 0) or DAC1 (Port 1)

**Input**: Send a message with `payload` containing:
- **Integer (0-65535)**: Raw DAC value
- **Float**: Target voltage (0 to VREF)

**Output**: Message with operation results:
```json
{
  "success": true,
  "port": 0,
  "value": 32768,
  "voltage_mv": 2500,
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

### 3. ADC Node

Add a **Waveshare AD** node:

- **HAT Config**: Select the config node from step 1
- **ADC Channel**: Choose from 8 channels (0-7)
- **Gain**: Programmable gain (1x to 64x)
- **Data Rate**: Sampling rate (2.5 to 30,000 SPS)

**Input**: Any message triggers a reading

**Output**: Message with reading results:
```json
{
  "success": true,
  "channel": 0,
  "raw": 8388607,
  "voltage_mv": 5000,
  "gain": 1,
  "drate": 10.0,
  "vref": 5.0,
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

## Example Flow

See `examples/worker-architecture-flow.json` for a complete example demonstrating:
- Config node setup
- DAC control (both value and voltage modes)
- ADC reading with periodic triggers
- Multiple nodes sharing the same worker

## Data Rate Guidelines

- **Low rates (2.5-100 SPS)**: High precision, low noise
- **Medium rates (500-2000 SPS)**: Balanced precision and speed  
- **High rates (3750-30000 SPS)**: High speed, lower precision

## Voltage Calculation

ADC voltage is calculated using:
```
voltage_mv = (raw_value / 8388607) × VREF × 1000
```

## Development

### Building

```bash
npm run build          # Build TypeScript to JavaScript
npm run build:watch    # Watch mode for development
npm run clean          # Clean build artifacts
```

### Testing

```bash
npm test               # Test Python integration
npm run test:worker    # Test worker architecture
```

### Project Structure

```
src/
├── nodes/
│   ├── waveshare-hat-config.ts  # Config node
│   ├── waveshare-da.ts          # DAC node
│   └── waveshare-ad.ts          # ADC node
├── worker-manager.ts             # Worker management
types/
├── node-red.d.ts                # TypeScript definitions
python/
├── worker.py                    # Python worker process
nodes/                          # Compiled JavaScript + HTML
examples/                        # Example flows
```

## Troubleshooting

### Worker Not Starting
- Check Python path (`python3` command available)
- Verify `spidev` and `RPi.GPIO` packages installed
- Check GPIO pin permissions

### SPI Communication Issues
- Verify SPI is enabled in `raspi-config`
- Check CS, RST, and DRDY pin connections
- Confirm SPI bus/device numbers

### Performance Issues
- Lower SPI speed for stability
- Use appropriate data rates for your application
- Monitor worker process resource usage

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please ensure:
- TypeScript compilation succeeds
- Tests pass
- Code follows existing patterns
- Documentation is updated
