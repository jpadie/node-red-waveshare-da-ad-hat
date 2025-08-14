# Node-RED Contrib Waveshare DA-AD HAT

Custom Node-RED nodes for the Waveshare DA-AD HAT with working drivers. This package provides reliable control of the Digital-to-Analog Converter (DAC) and Analog-to-Digital Converter (ADC) functionality through proven Python drivers.

## Features

### DAC Node (`waveshare-da`)
- **Dual Port Support**: Control both DAC channels (Port 0 and Port 1)
- **16-bit Resolution**: Full 0-65535 value range
- **Auto-update**: Configurable automatic output updates
- **Input Override**: Override configured values via message payload
- **Error Handling**: Comprehensive error reporting and validation

### ADC Node (`waveshare-ad`)
- **8 Single-Ended Channels**: Read from any of the 8 ADC channels (0-7)
- **Configurable Gain**: 1x to 64x gain settings for signal amplification
- **Flexible Data Rates**: 2.5 to 30,000 samples per second (SPS)
- **Input Buffering**: Optional high-impedance buffer (~100 MΩ) for sensitive sensors
- **Auto-read**: Configurable automatic reading intervals
- **Real-time Monitoring**: Ideal for continuous sensor monitoring

## Installation

### Prerequisites
- Node-RED (version 2.0.0 or higher)
- Raspberry Pi (or compatible single-board computer)
- Python 3 with required packages

### Install Python Dependencies
```bash
# Install system packages
sudo apt-get update
sudo apt-get install python3-pip python3-dev

# Install Python packages
pip3 install spidev RPi.GPIO
```

### Install Node-RED Package
```bash
# Navigate to your Node-RED user directory
cd ~/.node-red

# Install the package
npm install node-red-contrib-waveshare-da-ad-hat
```

### Restart Node-RED
After installation, restart Node-RED to load the new nodes.

## Hardware Setup

### Waveshare DA-AD HAT Connection
1. **Power**: Connect the HAT to your Raspberry Pi
2. **SPI Interface**: Ensure SPI is enabled in `raspi-config`
3. **GPIO Pins**: The HAT uses specific GPIO pins for CS, RST, and DRDY

### Enable SPI on Raspberry Pi
```bash
# Enable SPI interface
sudo raspi-config

# Navigate to: Interface Options > SPI > Enable
# Reboot after enabling
sudo reboot

# Verify SPI is enabled
ls /dev/spidev*
```

## Usage

### DAC Node Configuration

#### Basic Setup
1. Drag the "Waveshare DA" node to your flow
2. Configure the DAC port (0 or 1)
3. Set the default output value (0-65535)
4. Optionally enable auto-update with custom interval

#### Message Input
```json
{
  "payload": {
    "port": 0,
    "value": 32768
  }
}
```

#### Output
```json
{
  "payload": {
    "port": 0,
    "value": 32768,
    "success": true,
    "timestamp": 1703123456789
  }
}
```

### ADC Node Configuration

#### Basic Setup
1. Drag the "Waveshare AD" node to your flow
2. Select the ADC channel (0-7)
3. Configure gain, buffering, and data rate
4. Optionally enable auto-read with custom interval

#### Message Input
```json
{
  "payload": {
    "channel": 2,
    "gain": 16,
    "buffered": true,
    "dataRate": 500
  }
}
```

**Data Rate Options:**
- **2.5-30 SPS**: Slow, high precision measurements
- **50-500 SPS**: Medium speed, general purpose
- **1000-30000 SPS**: Fast, real-time monitoring

#### Output
```json
{
  "payload": {
    "channel": 2,
    "gain": 16,
    "buffered": true,
    "dataRate": 500,
    "reading": 12345,
    "rawOutput": "AIN2 reading: 12345",
    "success": true,
    "timestamp": 1703123456789
  }
}
```

## Pool Management System Integration

This package is specifically designed for pool management applications:

### Power Supply Control (DAC)
- **Port 0**: Control variable power supply voltage
- **Port 1**: Control current limiting or secondary power rail
- **Auto-update**: Maintain consistent power levels

### Sensor Monitoring (ADC)
- **Current Sensing**: Hall effect sensors for power monitoring
- **Voltage Monitoring**: Resistor divider bridges for voltage measurement
- **pH Sensing**: Interface with pH sensors for water quality
- **Temperature**: Monitor water and equipment temperature
- **Auto-read**: Continuous monitoring with configurable intervals

## Development

### Project Structure
```
├── src/                    # TypeScript source files
│   ├── nodes/             # Node implementations
│   └── index.ts           # Main entry point
├── nodes/                  # HTML editor files
├── python/                 # Python driver scripts
├── types/                  # TypeScript type definitions
├── lib/                    # Compiled JavaScript (generated)
└── package.json           # Package configuration
```

### Build Commands
```bash
# Install dependencies
npm install

# Build the project
npm run build

# Watch mode for development
npm run dev

# Clean build artifacts
npm run clean
```

### TypeScript Development
The project uses TypeScript with strict type checking:
- Full type safety for Node-RED interfaces
- Proper error handling and validation
- Modern ES2020 features
- Source maps for debugging

## Troubleshooting

### Common Issues

#### SPI Permission Denied
```bash
# Add user to spi group
sudo usermod -a -G spi $USER
# Log out and back in, or reboot
```

#### Python Script Not Found
- Ensure Python scripts are in the `python/` directory
- Check file permissions: `chmod +x python/*.py`
- Verify Python 3 is available: `python3 --version`

#### GPIO Access Denied
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER
# Log out and back in, or reboot
```

### Debug Mode
Enable Node-RED debug mode to see detailed error messages:
```bash
# Start Node-RED with debug logging
node-red --verbose
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/jpadie/node-red-waveshare-da-ad-hat/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jpadie/node-red-waveshare-da-ad-hat/discussions)

## Acknowledgments

- Waveshare for the DA-AD HAT hardware
- Node-RED community for the excellent framework
- Python community for the reliable hardware interface libraries

---

**Note**: This package includes working Python drivers that have been tested and proven reliable. The Node-RED nodes provide a user-friendly interface while maintaining the performance and reliability of the underlying hardware drivers.
