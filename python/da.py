#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Waveshare DA-AD HAT DAC Control Script
Controls the DAC8532 dual-channel 16-bit DAC
"""

import spidev
import RPi.GPIO as GPIO
import argparse
import sys
import logging
from typing import Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DAC8532Controller:
    """DAC8532 DAC Controller for Waveshare DA-AD HAT"""
    
    # DAC8532 Commands
    CMD_WRITE_DAC_A = 0x30  # Write to DAC A
    CMD_WRITE_DAC_B = 0x34  # Write to DAC B
    
    # GPIO Configuration
    CS_DAC_PIN = 23
    
    # Default VREF (can be overridden)
    DEFAULT_VREF = 3.3  # Volts
    
    def __init__(self, vref: float = DEFAULT_VREF):
        """
        Initialize DAC controller
        
        Args:
            vref: Reference voltage in volts (default: 3.3V)
        """
        self.spi = None
        self.gpio_initialized = False
        self.vref = vref
        self.dac_resolution = 65536  # 16-bit DAC
        
        # Calculate voltage per LSB
        self.voltage_per_lsb = self.vref / self.dac_resolution
        
        logger.info(f"DAC8532 initialized with VREF={self.vref}V, "
                   f"Resolution={self.dac_resolution} LSB, "
                   f"Voltage/LSB={self.voltage_per_lsb:.8f}V")
    
    def initialize_gpio(self):
        """Initialize GPIO pins"""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.CS_DAC_PIN, GPIO.OUT)
            GPIO.output(self.CS_DAC_PIN, GPIO.HIGH)  # CS high = inactive
            self.gpio_initialized = True
            logger.debug("GPIO initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            raise
    
    def initialize_spi(self):
        """Initialize SPI interface"""
        try:
            self.spi = spidev.SpiDev(0,0)
            self.spi.max_speed_hz = 20000
            self.spi.mode = 0b01
            logger.debug("SPI initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SPI: {e}")
            raise
    
    def set_dac_value(self, port: int, value: int) -> bool:
        """
        Set DAC output value (raw 16-bit value)
        
        Args:
            port: DAC channel (0 or 1)
            value: 16-bit value (0-65535)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._validate_inputs(port, value):
            return False
            
        try:
            # Select command based on port
            if port == 0:
                command = self.CMD_WRITE_DAC_A
            else:
                command = self.CMD_WRITE_DAC_B
            
            # DAC8532 expects 24-bit data: [command, high_byte, low_byte]
            # The 16-bit value is split into high and low bytes
            high_byte = (value >> 8) & 0xFF
            low_byte = value & 0xFF
            
            # Send data via SPI
            GPIO.output(self.CS_DAC_PIN, GPIO.LOW)  # CS low = active
            self.spi.writebytes([command, high_byte, low_byte])
            GPIO.output(self.CS_DAC_PIN, GPIO.HIGH)  # CS high = inactive
            
            # Calculate actual voltage output
            voltage = value * self.voltage_per_lsb
            
            logger.info(f"DAC8532 Port {port} set to value {value} (0x{value:04X}) = {voltage:.6f}V")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set DAC value: {e}")
            return False
    
    def set_dac_voltage(self, port: int, voltage: float) -> bool:
        """
        Set DAC output voltage
        
        Args:
            port: DAC channel (0 or 1)
            voltage: Target voltage in volts (0 to VREF)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._validate_voltage(voltage):
            return False
        
        # Convert voltage to DAC value
        dac_value = round(voltage / self.voltage_per_lsb)
        
        # Clamp to valid range
        dac_value = max(0, min(dac_value, self.dac_resolution - 1))
        
        logger.info(f"Setting DAC8532 Port {port} to {voltage:.6f}V (DAC value: {dac_value})")
        
        return self.set_dac_value(port, dac_value)
    
    def get_voltage_for_value(self, value: int) -> float:
        """Get voltage output for a given DAC value"""
        return value * self.voltage_per_lsb
    
    def get_value_for_voltage(self, voltage: float) -> int:
        """Get DAC value for a given voltage"""
        return round(voltage / self.voltage_per_lsb)
    
    def _validate_inputs(self, port: int, value: int) -> bool:
        """Validate input parameters"""
        if port not in [0, 1]:
            logger.error(f"Invalid port: {port}. Must be 0 or 1.")
            return False
            
        if not isinstance(value, int) or value < 0 or value > 65535:
            logger.error(f"Invalid value: {value}. Must be integer 0-65535 (16-bit DAC).")
            return False
            
        return True
    
    def _validate_voltage(self, voltage: float) -> bool:
        """Validate voltage input"""
        if not isinstance(voltage, (int, float)) or voltage < 0 or voltage > self.vref:
            logger.error(f"Invalid voltage: {voltage}V. Must be 0 to {self.vref}V.")
            return False
        return True
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.spi:
                self.spi.close()
                logger.debug("SPI closed")
            if self.gpio_initialized:
                GPIO.cleanup()
                logger.debug("GPIO cleaned up")
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Control Waveshare DA-AD HAT DAC8532 DAC output',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --port 0 --value 32768                    # Set DAC A to mid-scale (raw value)
  %(prog)s --port 1 --value 65535                    # Set DAC B to full-scale (raw value)
  %(prog)s --port 0 --voltage 1.65                   # Set DAC A to 1.65V
  %(prog)s --port 1 --voltage 3.3                    # Set DAC B to 3.3V
  %(prog)s --port 0 --value 0                        # Set DAC A to zero
  %(prog)s --vref 5.0 --port 0 --voltage 2.5         # Use 5V VREF, set to 2.5V
        """
    )
    
    # VREF configuration
    parser.add_argument('--vref', type=float, default=3.3,
                       help='Reference voltage in volts (default: 3.3V)')
    
    # DAC control (either value or voltage, not both)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--value', type=int,
                      help='16-bit DAC value (0-65535)')
    group.add_argument('--voltage', type=float,
                      help='Target voltage in volts (0 to VREF)')
    
    # Other parameters
    parser.add_argument('--port', type=int, choices=[0, 1], required=True,
                       help='DAC channel (0=DAC A, 1=DAC B)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create DAC controller with specified VREF
    dac = DAC8532Controller(vref=args.vref)
    
    try:
        # Initialize hardware
        dac.initialize_gpio()
        dac.initialize_spi()
        
        # Set DAC output
        if args.value is not None:
            success = dac.set_dac_value(args.port, args.value)
        else:  # args.voltage is not None
            success = dac.set_dac_voltage(args.port, args.voltage)
        
        if success:
            if args.value is not None:
                voltage = dac.get_voltage_for_value(args.value)
                logger.info(f"Successfully set DAC8532 port {args.port} to value {args.value} = {voltage:.6f}V")
            else:
                dac_value = dac.get_value_for_voltage(args.voltage)
                logger.info(f"Successfully set DAC8532 port {args.port} to {args.voltage:.6f}V (DAC value: {dac_value})")
            sys.exit(0)  # Success
        else:
            logger.error("Failed to set DAC value")
            sys.exit(1)  # Failure
            
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(130)  # SIGINT
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)  # Failure
    finally:
        dac.cleanup()

if __name__ == "__main__":
    main()
