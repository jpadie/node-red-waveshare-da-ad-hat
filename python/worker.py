#!/usr/bin/env python3
"""
Waveshare DA-AD HAT Worker
Handles JSON-RPC requests over stdio for DAC and ADC operations.
Manages SPI access exclusively and provides clean resource management.
"""

import json
import sys
import time
import logging
import signal
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass
from queue import Queue
import spidev
import RPi.GPIO as GPIO

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

@dataclass
class WorkerConfig:
    """Configuration for the worker"""
    spi_bus: int = 0
    spi_device: int = 0
    spi_speed: int = 1000000
    cs_pin: int = 8
    rst_pin: int = 18
    drdy_pin: int = 7
    dac_vref: float = 5.0
    adc_vref: float = 5.0

class SPIResourceManager:
    """Manages SPI and GPIO resources with exclusive access"""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.spi = None
        self.gpio_initialized = False
        self.lock = threading.Lock()
        # Don't setup GPIO immediately - wait until first use
        
    def _setup_gpio(self):
        """Setup GPIO pins - lazy initialization"""
        if self.gpio_initialized:
            return True
            
        try:
            # First, try to cleanup any existing GPIO state
            try:
                GPIO.cleanup()
            except:
                pass  # Ignore cleanup errors
                
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.cs_pin, GPIO.OUT)
            GPIO.setup(self.config.rst_pin, GPIO.OUT)
            GPIO.setup(self.config.drdy_pin, GPIO.IN)
            
            # Initialize pins
            GPIO.output(self.config.cs_pin, GPIO.HIGH)
            GPIO.output(self.config.rst_pin, GPIO.HIGH)
            
            self.gpio_initialized = True
            logger.info(f"GPIO initialized: CS={self.config.cs_pin}, RST={self.config.rst_pin}, DRDY={self.config.drdy_pin}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            logger.warning("GPIO initialization failed - this may be expected in non-Raspberry Pi environments")
            self.gpio_initialized = False
            return False
        
    def _setup_spi(self):
        """Setup SPI connection"""
        if self.spi is None:
            self.spi = spidev.SpiDev()
            self.spi.open(self.config.spi_bus, self.config.spi_device)
            self.spi.max_speed_hz = self.config.spi_speed
            self.spi.mode = 1  # SPI mode 1
            logger.info("SPI connection established")
            
    def acquire(self):
        """Acquire exclusive access to SPI resources"""
        return self.lock.acquire()
        
    def release(self):
        """Release exclusive access to SPI resources"""
        self.lock.release()
        
    def cleanup(self):
        """Clean up all resources"""
        with self.lock:
            if self.spi:
                self.spi.close()
                self.spi = None
            if self.gpio_initialized:
                try:
                    GPIO.cleanup()
                    self.gpio_initialized = False
                    logger.info("GPIO resources cleaned up")
                except Exception as e:
                    logger.warning(f"Error during GPIO cleanup: {e}")
            logger.info("SPI and GPIO resources cleaned up")

class DAC8532Controller:
    """Controller for DAC8532 chip"""
    
    def __init__(self, spi_manager: SPIResourceManager, config: WorkerConfig):
        self.spi_manager = spi_manager
        self.config = config
        
    def set_dac_value(self, port: int, value: int) -> Dict[str, Any]:
        """Set DAC output value (0-65535)"""
        if not 0 <= port <= 1:
            raise ValueError("Port must be 0 or 1")
        if not 0 <= value <= 65535:
            raise ValueError("Value must be 0-65535")
            
        with self.spi_manager.lock:
            # Ensure GPIO is initialized
            if not self.spi_manager._setup_gpio():
                raise RuntimeError("GPIO not available - cannot control DAC")
                
            self.spi_manager._setup_spi()
            
            # DAC8532 commands: 0x30 for DAC0, 0x34 for DAC1
            command = 0x30 if port == 0 else 0x34
            
            # Prepare data: command + high byte + low byte
            high_byte = (value >> 8) & 0xFF
            low_byte = value & 0xFF
            
            data = [command, high_byte, low_byte]
            
            # Set CS low, send data, set CS high
            GPIO.output(self.config.cs_pin, GPIO.LOW)
            try:
                self.spi_manager.spi.writebytes(data)
                time.sleep(0.001)  # Small delay for stability
            finally:
                GPIO.output(self.config.cs_pin, GPIO.HIGH)
                
        return {
            "port": port,
            "value": value,
            "voltage_mv": int((value / 65535.0) * self.config.dac_vref * 1000)
        }
        
    def set_dac_voltage(self, port: int, voltage: float) -> Dict[str, Any]:
        """Set DAC output voltage"""
        if not 0 <= voltage <= self.config.dac_vref:
            raise ValueError(f"Voltage must be 0-{self.config.dac_vref}V")
            
        # Convert voltage to DAC value
        value = int((voltage / self.config.dac_vref) * 65535)
        return self.set_dac_value(port, value)

class ADS1256Controller:
    """Controller for ADS1256 chip"""
    
    def __init__(self, spi_manager: SPIResourceManager, config: WorkerConfig):
        self.spi_manager = spi_manager
        self.config = config
        self.adc_initialized = False
        # Don't setup ADC immediately - wait until first use
        # ADS1256 commands/registers (subset)
        self.CMD_SDATAC = 0x0F  # Stop read continuous data
        self.CMD_RDATA = 0x01   # Read data
        self.CMD_WREG  = 0x50   # Write register (OR with reg addr)
        self.CMD_SYNC  = 0xFC
        self.CMD_WAKEUP= 0x00
        self.REG_STATUS= 0x00
        self.REG_MUX   = 0x01
        self.REG_ADCON = 0x02
        self.REG_DRATE = 0x03
        
    def _setup_adc(self):
        """Setup ADC chip - lazy initialization"""
        if self.adc_initialized:
            return True
            
        with self.spi_manager.lock:
            # Ensure GPIO is initialized first
            if not self.spi_manager._setup_gpio():
                raise RuntimeError("GPIO not available - cannot initialize ADC")
                
            self.spi_manager._setup_spi()
            
            # Reset ADC
            GPIO.output(self.config.rst_pin, GPIO.LOW)
            time.sleep(0.001)
            GPIO.output(self.config.rst_pin, GPIO.HIGH)
            time.sleep(0.001)
            
            # Configure ADC (basic setup)
            # This can be expanded based on your specific needs
            self.adc_initialized = True
            logger.info("ADC initialized")
            return True

    def _write_register(self, reg: int, value: int):
        """Write single ADS1256 register"""
        # Ensure GPIO is initialized
        if not self.spi_manager._setup_gpio():
            raise RuntimeError("GPIO not available - cannot control ADC")
            
        GPIO.output(self.config.cs_pin, GPIO.LOW)
        try:
            # WREG: 0101 rrrr, then number of registers-1, then value
            self.spi_manager.spi.writebytes([self.CMD_WREG | (reg & 0x0F), 0x00, value & 0xFF])
            time.sleep(0.0002)
        finally:
            GPIO.output(self.config.cs_pin, GPIO.HIGH)

    def _wait_drdy(self, timeout_s: float = 0.1) -> bool:
        """Wait for DRDY to go low with timeout"""
        # Ensure GPIO is initialized
        if not self.spi_manager._setup_gpio():
            raise RuntimeError("GPIO not available - cannot read DRDY")
            
        start = time.time()
        while GPIO.input(self.config.drdy_pin) == GPIO.HIGH:
            if time.time() - start > timeout_s:
                return False
            time.sleep(0.00005)
        return True

    def read_channel(self, channel: int, gain: int = 1, drate: float = 10.0, differential: bool = False, negChannel: int = 8, buffered: bool = False) -> Dict[str, Any]:
        """Read from ADC channel"""
        if not 0 <= channel <= 7:
            raise ValueError("Channel must be 0-7")
        if gain not in [1, 2, 4, 8, 16, 32, 64]:
            raise ValueError("Gain must be 1, 2, 4, 8, 16, 32, or 64")
        if drate not in [2.5, 5, 10, 15, 30, 60, 100, 500, 1000, 2000, 3750, 7500, 15000, 30000]:
            raise ValueError("Invalid data rate")
        if differential:
            if not 0 <= negChannel <= 7:
                raise ValueError("Negative channel must be 0-7 in differential mode")
            if negChannel == channel:
                raise ValueError("Positive and negative channels must differ")
        else:
            # single-ended uses AINCOM which is channel 8 in ADS1256 MUX encoding
            negChannel = 8
            
        with self.spi_manager.lock:
            # Ensure ADC is initialized
            if not self._setup_adc():
                raise RuntimeError("Failed to initialize ADC")
                
            # Stop continuous read mode and configure MUX for requested channels
            self._write_register(self.REG_STATUS, 0x02 if buffered else 0x00)  # set buffer bit accordingly
            # Set MUX: upper nibble = AINp, lower nibble = AINn (8 = AINCOM)
            mux_value = ((channel & 0x0F) << 4) | (negChannel & 0x0F)
            self._write_register(self.REG_MUX, mux_value)

            # Small sync/wakeup to start conversion on new channel selection
            GPIO.output(self.config.cs_pin, GPIO.LOW)
            try:
                self.spi_manager.spi.writebytes([self.CMD_SYNC])
                time.sleep(0.0002)
                self.spi_manager.spi.writebytes([self.CMD_WAKEUP])
            finally:
                GPIO.output(self.config.cs_pin, GPIO.HIGH)

            # Wait for conversion ready
            if not self._wait_drdy(0.1):
                raise TimeoutError("ADC DRDY timeout")
                
            # Read data (simplified)
            GPIO.output(self.config.cs_pin, GPIO.LOW)
            try:
                # Send read command and read 3 bytes
                self.spi_manager.spi.writebytes([self.CMD_RDATA])  # RDATA command
                time.sleep(0.0001)
                data = self.spi_manager.spi.readbytes(3)
            finally:
                GPIO.output(self.config.cs_pin, GPIO.HIGH)
                
            # Convert 3 bytes to 24-bit value
            raw_value = (data[0] << 16) | (data[1] << 8) | data[2]
            
            # Convert to voltage (simplified calculation)
            voltage_mv = (raw_value / 8388607.0) * self.config.adc_vref * 1000
            
        return {
            "channel": channel,
            "negChannel": None if negChannel == 8 else negChannel,
            "differential": differential,
            "buffered": buffered,
            "raw": raw_value,
            "voltage_mv": int(voltage_mv),
            "gain": gain,
            "drate": drate,
            "vref": self.config.adc_vref
        }

class Worker:
    """Main worker class that handles JSON-RPC requests"""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.spi_manager = SPIResourceManager(config)
        self.dac_controller = DAC8532Controller(self.spi_manager, config)
        self.adc_controller = ADS1256Controller(self.spi_manager, config)
        self.running = True
        self.last_activity = time.time()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Start watchdog thread
        self.watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self.watchdog_thread.start()
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down")
        self.running = False
        
    def _watchdog(self):
        """Watchdog thread that shuts down after 5 seconds of inactivity"""
        while self.running:
            time.sleep(1)
            if time.time() - self.last_activity > 5:
                logger.info("No activity for 5 seconds, shutting down")
                self.running = False
                break
                
    def _update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = time.time()
        
    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a JSON-RPC request"""
        try:
            self._update_activity()
            
            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")
            
            if method == "set_dac_value":
                result = self.dac_controller.set_dac_value(
                    params["port"], 
                    params["value"]
                )
            elif method == "set_dac_voltage":
                result = self.dac_controller.set_dac_voltage(
                    params["port"], 
                    params["voltage"]
                )
            elif method == "read_adc":
                result = self.adc_controller.read_channel(
                    params["channel"],
                    params.get("gain", 1),
                    params.get("drate", 10.0),
                    params.get("differential", False),
                    params.get("negChannel", 8),
                    params.get("buffered", False)
                )
            elif method == "ping":
                result = {"status": "ok", "timestamp": time.time()}
            else:
                raise ValueError(f"Unknown method: {method}")
                
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -1,
                    "message": str(e)
                }
            }
            
    def run(self):
        """Main run loop - read JSON-RPC requests from stdin"""
        logger.info("Worker started, waiting for requests")
        
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                    
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    request = json.loads(line)
                    response = self.handle_request(request)
                    print(json.dumps(response), flush=True)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        }
                    }
                    print(json.dumps(error_response), flush=True)
                    
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                break
                
        self.cleanup()
        
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up worker resources")
        self.spi_manager.cleanup()

def main():
    """Main entry point"""
    config = WorkerConfig()
    worker = Worker(config)
    
    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        worker.cleanup()

if __name__ == "__main__":
    main()
