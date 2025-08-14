# Development Guide

This guide covers how to develop, test, and contribute to the Node-RED Waveshare DA-AD HAT package.

## Development Setup

### Prerequisites
- Node.js 16+ and npm
- TypeScript 5.0+
- Python 3.7+ with spidev and RPi.GPIO
- Raspberry Pi or compatible SBC for hardware testing

### Installation
```bash
# Clone the repository
git clone https://github.com/jpadie/node-red-waveshare-da-ad-hat.git
cd node-red-waveshare-da-ad-hat

# Install dependencies
npm install

# Build the project
npm run build
```

## Project Structure

```
├── src/                    # TypeScript source files
│   ├── nodes/             # Node implementations
│   │   ├── waveshare-da.ts # DAC node
│   │   └── waveshare-ad.ts # ADC node
│   └── index.ts           # Main entry point
├── nodes/                  # HTML editor files
│   ├── waveshare-da.html  # DAC node editor
│   └── waveshare-ad.html  # ADC node editor
├── python/                 # Python driver scripts
│   ├── da.py              # DAC control script
│   └── ad.py              # ADC reading script
├── types/                  # TypeScript type definitions
├── lib/                    # Compiled JavaScript (generated)
├── examples/               # Example flows and usage
└── package.json           # Package configuration
```

## Development Workflow

### 1. Development Mode
```bash
# Watch for changes and rebuild automatically
npm run dev
```

### 2. Building
```bash
# Build once
npm run build

# Clean and rebuild
npm run clean && npm run build
```

### 3. Testing
```bash
# Test Python integration
npm run test

# Build and test
npm run test:build
```

## Node Development

### Creating a New Node

1. **Create TypeScript file** in `src/nodes/`
2. **Create HTML editor file** in `nodes/`
3. **Add to main index** in `src/index.ts`
4. **Update package.json** node-red section
5. **Add types** to `types/node-red.d.ts`

### Node Structure

```typescript
export function createNodeName(RED: any) {
  return function NodeName(this: any, config: NodeConfig) {
    RED.nodes.createNode(this, config);
    
    const node = this;
    
    node.on('input', handleInput);
    node.on('close', handleClose);
    
    async function handleInput(msg: any, send: (msg: any) => void, done: () => void) {
      // Input handling logic
    }
    
    function handleClose() {
      // Cleanup logic
    }
  };
}
```

### HTML Editor Structure

```html
<script type="text/javascript">
  RED.nodes.registerType('node-name', {
    category: 'Category',
    color: '#C0DEED',
    defaults: {
      // Configuration defaults
    },
    inputs: 1,
    outputs: 1,
    icon: "icon.png",
    label: function() {
      return this.name || "Node Name";
    },
    oneditprepare: function() {
      // Editor setup logic
    }
  });
</script>

<script type="text/html" data-template-name="node-name">
  <!-- Configuration form -->
</script>

<script type="text/html" data-help-name="node-name">
  <!-- Help documentation -->
</script>
```

## Python Integration

### Script Requirements
- **Exit Codes**: Use exit code 1 for success, 0 for failure
- **Output Format**: Consistent output format for parsing
- **Error Handling**: Proper error messages to stderr
- **Arguments**: Use argparse for command-line arguments

### Testing Python Scripts
```bash
# Test DAC script
python3 python/da.py --port 0 --value 32768

# Test ADC script
python3 python/ad.py --channel 0 --gain 16 --buffered 0 --drate 1000
```

## TypeScript Best Practices

### Type Safety
- Use strict TypeScript configuration
- Define interfaces for all data structures
- Avoid `any` types where possible
- Use proper error handling

### Code Style
- Follow existing naming conventions
- Use async/await for asynchronous operations
- Implement proper error handling
- Add JSDoc comments for complex functions

## Testing

### Unit Testing
- Test individual functions
- Mock external dependencies
- Test error conditions
- Verify input validation

### Integration Testing
- Test Python script execution
- Verify Node-RED integration
- Test configuration options
- Validate message flow

### Hardware Testing
- Test on actual Raspberry Pi
- Verify SPI communication
- Test GPIO operations
- Validate timing requirements

## Debugging

### Node-RED Debug
```bash
# Start Node-RED with verbose logging
node-red --verbose

# Check Node-RED logs
tail -f ~/.node-red/logs/node-red.log
```

### TypeScript Debug
```bash
# Build with source maps
npm run build

# Use source maps in debugger
# Set breakpoints in TypeScript files
```

### Python Debug
```bash
# Add debug output to Python scripts
import logging
logging.basicConfig(level=logging.DEBUG)

# Test individual components
python3 -c "import spidev; print('SPI available')"
```

## Contributing

### Code Review Process
1. Create feature branch
2. Implement changes
3. Add tests
4. Update documentation
5. Submit pull request

### Commit Guidelines
- Use descriptive commit messages
- Reference issues in commits
- Keep commits focused and atomic
- Test before committing

### Pull Request Checklist
- [ ] Code compiles without errors
- [ ] Tests pass
- [ ] Documentation updated
- [ ] No breaking changes
- [ ] Follows project style

## Deployment

### Local Installation
```bash
# Build the package
npm run build

# Install locally in Node-RED
cd ~/.node-red
npm install /path/to/package
```

### Publishing to npm
```bash
# Login to npm
npm login

# Publish package
npm publish

# Verify publication
npm view node-red-contrib-waveshare-da-ad-hat
```

## Troubleshooting

### Common Issues

#### Build Errors
- Check TypeScript version compatibility
- Verify all dependencies installed
- Check for syntax errors in source files

#### Runtime Errors
- Verify Python scripts are executable
- Check file paths and permissions
- Validate Node-RED configuration

#### Hardware Issues
- Verify SPI is enabled
- Check GPIO permissions
- Test with simple Python scripts first

### Getting Help
- Check existing issues on GitHub
- Review Node-RED documentation
- Consult Python hardware libraries
- Ask in Node-RED community forums

## Resources

### Documentation
- [Node-RED Documentation](https://nodered.org/docs/)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
- [Python SPI Documentation](https://pypi.org/project/spidev/)
- [RPi.GPIO Documentation](https://pypi.org/project/RPi.GPIO/)

### Community
- [Node-RED Forum](https://discourse.nodered.org/)
- [Node-RED Slack](https://nodered.org/slack/)
- [Python Hardware Community](https://pythonhosted.org/py-spidev/)

### Hardware
- [Waveshare DA-AD HAT](https://www.waveshare.com/wiki/DA-AD_HAT)
- [Raspberry Pi Documentation](https://www.raspberrypi.org/documentation/)
- [SPI Interface Guide](https://www.raspberrypi.org/documentation/hardware/raspberrypi/spi/)
