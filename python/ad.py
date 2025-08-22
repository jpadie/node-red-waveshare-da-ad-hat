#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Waveshare DA-AD HAT ADC Control Script
Controls the ADS1256 24-bit ADC with 8 single-ended channels
"""

import spidev
import RPi.GPIO as GPIO
import time
import argparse
import sys
import logging
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ADS1256Controller:
    """ADS1256 ADC Controller for Waveshare DA-AD HAT"""
    
    # ADS1256 Commands
    CMD_RESET = 0xFE        # Reset to power-up values
    CMD_SDATAC = 0x0F       # Stop read continuous mode
    CMD_WREG = 0x50         # Write to register
    CMD_RDATA = 0x01        # Read data
    CMD_SYNC = 0xFC         # Synchronize A/D conversion
    CMD_WAKEUP = 0x00       # Wake up from standby
    
    # ADS1256 Registers
    REG_STATUS = 0x00       # Status register
    REG_MUX = 0x01          # Multiplexer control
    REG_ADCON = 0x02        # A/D control
    REG_DRATE = 0x03        # Data rate control
    
    # Data Rate Values (SPS -> Register Value)
    DRATE_VALUES = {
        2.5: 0x03,      # 2.5 SPS
        5: 0x13,         # 5 SPS
        10: 0x20,        # 10 SPS
        15: 0x33,        # 15 SPS
        25: 0x43,        # 25 SPS
        30: 0x53,        # 30 SPS
        50: 0x63,        # 50 SPS
        60: 0x72,        # 60 SPS
        100: 0x82,       # 100 SPS
        500: 0x92,       # 500 SPS
        1000: 0xA1,      # 1000 SPS
        2000: 0xB0,      # 2000 SPS
        3750: 0xC0,      # 3750 SPS
        7500: 0xD0,      # 7500 SPS
        15000: 0xE0,     # 15000 SPS
        30000: 0xF0      # 30000 SPS
    }
    
    # Gain Values (Gain -> Register Value)
    GAIN_VALUES = {
        1: 0x00,         # 1x gain
        2: 0x01,         # 2x gain
        4: 0x02,         # 4x gain
        8: 0x03,         # 8x gain
        16: 0x04,        # 16x gain
        32: 0x05,        # 32x gain
        64: 0x06         # 64x gain
    }
    
    # GPIO Configuration
    CS_PIN = 22          # Chip Select
    RST_PIN = 18         # Reset
    DRDY_PIN = 17        # Data Ready
    
    def __init__(self):
        """Initialize ADC controller"""
        self.spi = None
        self.gpio_initialized = False
        
    def initialize_gpio(self):
        """Initialize GPIO pins"""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.RST_PIN, GPIO.OUT)
            GPIO.setup(self.CS_PIN, GPIO.OUT)
            GPIO.setup(self.DRDY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            
            # Set initial states
            GPIO.output(self.CS_PIN, GPIO.HIGH)      # CS high = inactive
            GPIO.output(self.RST_PIN, GPIO.HIGH)     # Reset high = normal operation
            
            self.gpio_initialized = True
            logger.debug("GPIO initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            raise
    
    def initialize_spi(self):
        """Initialize SPI interface"""
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)  # Bus 0, Device 0
            self.spi.max_speed_hz = 1000000
            self.spi.mode = 0b01
            logger.debug("SPI initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SPI: {e}")
            raise
    
    def reset_ads(self):
        """Reset ADS1256 to power-up state"""
        try:
            GPIO.output(self.RST_PIN, GPIO.LOW)
            time.sleep(0.1)
            GPIO.output(self.RST_PIN, GPIO.HIGH)
            time.sleep(0.1)
            logger.debug("ADS1256 reset completed")
        except Exception as e:
            logger.error(f"Failed to reset ADS1256: {e}")
            raise
    
    def wait_for_drdy(self, timeout_ms: int = 10000) -> bool:
        """
        Wait for Data Ready signal
        
        Args:
            timeout_ms: Timeout in milliseconds
            
        Returns:
            bool: True if DRDY went low, False if timeout
        """
        try:
            for _ in range(timeout_ms):
                if GPIO.input(self.DRDY_PIN) == 0:
                    return True
                time.sleep(0.001)
            
            logger.warning("DRDY timeout - no data ready signal")
            return False
        except Exception as e:
            logger.error(f"Error waiting for DRDY: {e}")
            return False
    
    def write_command(self, cmd: int):
        """Write command to ADS1256"""
        try:
            GPIO.output(self.CS_PIN, GPIO.LOW)  # CS low = active
            self.spi.writebytes([cmd])
            GPIO.output(self.CS_PIN, GPIO.HIGH)  # CS high = inactive
            logger.debug(f"Command 0x{cmd:02X} sent")
        except Exception as e:
            logger.error(f"Failed to write command 0x{cmd:02X}: {e}")
            raise
    
    def write_register(self, reg: int, data: int):
        """Write data to ADS1256 register"""
        try:
            GPIO.output(self.CS_PIN, GPIO.LOW)  # CS low = active
            self.spi.writebytes([self.CMD_WREG | reg, 0x00, data])
            GPIO.output(self.CS_PIN, GPIO.HIGH)  # CS high = inactive
            logger.debug(f"Register 0x{reg:02X} set to 0x{data:02X}")
        except Exception as e:
            logger.error(f"Failed to write register 0x{reg:02X}: {e}")
            raise
    
    def read_adc_data(self) -> Optional[int]:
        """Read ADC conversion data"""
        try:
            GPIO.output(self.CS_PIN, GPIO.LOW)  # CS low = active
            self.spi.writebytes([self.CMD_RDATA])
            time.sleep(0.01)  # Small delay for data to be ready
            
            # Read 3 bytes (24-bit data)
            raw_data = self.spi.readbytes(3)
            GPIO.output(self.CS_PIN, GPIO.HIGH)  # CS high = inactive
            
            if len(raw_data) != 3:
                logger.error(f"Expected 3 bytes, got {len(raw_data)}")
                return None
            
            # Combine bytes into 24-bit value
            value = (raw_data[0] << 16) | (raw_data[1] << 8) | raw_data[2]
            
            # Handle signed 24-bit value
            if value & 0x800000:  # Negative value
                value -= 0x1000000
            
            logger.debug(f"Raw ADC reading: 0x{value:06X} ({value})")
            return value
            
        except Exception as e:
            logger.error(f"Failed to read ADC data: {e}")
            return None
    
    def configure_adc(self, channel: int, gain: int, buffered: bool, data_rate: float) -> bool:
        """
        Configure ADC for reading
        
        Args:
            channel: ADC channel (0-7)
            gain: Gain setting (1, 2, 4, 8, 16, 32, 64)
            buffered: Enable input buffer
            data_rate: Data rate in SPS
            
        Returns:
            bool: True if configuration successful
        """
        try:
            # Stop continuous read mode
            self.write_command(self.CMD_SDATAC)
            
            # Configure STATUS register (input buffer)
            buffer_value = 0x02 if buffered else 0x00
            self.write_register(self.REG_STATUS, buffer_value)
            
            # Configure MUX register (channel selection)
            # Single-ended mode: AINx vs AINCOM
            mux_value = (channel << 4) | 0x08
            self.write_register(self.REG_MUX, mux_value)
            
            # Configure ADCON register (gain and clock)
            adcon_value = 0x00 | self.GAIN_VALUES[gain]
            self.write_register(self.REG_ADCON, adcon_value)
            
            # Configure DRATE register (data rate)
            drate_value = self.DRATE_VALUES[data_rate]
            self.write_register(self.REG_DRATE, drate_value)
            
            logger.info(f"ADC configured: Channel={channel}, Gain={gain}x, "
                       f"Buffered={buffered}, DataRate={data_rate} SPS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure ADC: {e}")
            return False
    
    def read_channel(self, channel: int, gain: int, buffered: bool, data_rate: float) -> Optional[int]:
        """
        Read from specified ADC channel
        
        Args:
            channel: ADC channel (0-7)
            gain: Gain setting
            buffered: Enable input buffer
            data_rate: Data rate in SPS
            
        Returns:
            Optional[int]: ADC reading value or None if failed
        """
        try:
            # Configure ADC
            if not self.configure_adc(channel, gain, buffered, data_rate):
                return None
            
            # Wait for data ready
            if not self.wait_for_drdy():
                return None
            
            # Start conversion
            self.write_command(self.CMD_SYNC)
            self.write_command(self.CMD_WAKEUP)
            
            # Wait for conversion to complete
            if not self.wait_for_drdy():
                return None
            
            # Read the result
            value = self.read_adc_data()
            return value
            
        except Exception as e:
            logger.error(f"Failed to read channel {channel}: {e}")
            return None
    
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
        description='Read from Waveshare DA-AD HAT ADS1256 ADC',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --channel 0 --gain 16 --buffered 0 --drate 1000
  %(prog)s --channel 2 --gain 8 --buffered 1 --drate 500
  %(prog)s --channel 4 --gain 32 --buffered 1 --drate 2.5
        """
    )
    
    parser.add_argument('--channel', type=int, required=True, 
                       choices=range(8), help='ADC channel (0-7)')
    parser.add_argument('--gain', type=int, required=True,
                       choices=[1, 2, 4, 8, 16, 32, 64], help='Gain setting')
    parser.add_argument('--buffered', type=int, required=True,
                       choices=[0, 1], help='Input buffer: 1=enabled, 0=disabled')
    parser.add_argument('--drate', type=float, required=True,
                       choices=[2.5, 5, 10, 15, 25, 30, 50, 60, 100, 500, 1000, 2000, 3750, 7500, 15000, 30000],
                       help='Data rate in samples per second (SPS)')
    parser.add_argument('--vref', type=float, default=5.0,
                       help='Reference voltage in volts (default: 5.0V)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create ADC controller
    adc = ADS1256Controller()
    
    try:
        # Initialize hardware
        adc.initialize_gpio()
        adc.initialize_spi()
        adc.reset_ads()
        
        # Read from specified channel
        value = adc.read_channel(args.channel, args.gain, bool(args.buffered), args.drate)
        
        if value is not None:
            # Calculate voltage in millivolts
            # Formula: voltage = (raw_value / 2^23) * VREF / PGA_gain
            # Convert to millivolts by multiplying by 1000
            voltage_mv = (value / (2**23)) * args.vref * 1000 / args.gain
            
            # Output both raw value and voltage
            print(f"RAW:{value}")
            print(f"VOLTAGE_MV:{voltage_mv:.3f}")
            print(f"CHANNEL:{args.channel}")
            print(f"GAIN:{args.gain}")
            print(f"VREF:{args.vref}")
            
            logger.info(f"Successfully read channel {args.channel}: raw={value}, voltage={voltage_mv:.3f}mV")
            sys.exit(0)  # Success
        else:
            logger.error("Failed to read ADC value")
            sys.exit(1)  # Failure
            
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(130)  # SIGINT
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)  # Failure
    finally:
        adc.cleanup()

if __name__ == "__main__":
    main()