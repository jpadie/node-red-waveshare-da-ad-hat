import spidev
import RPi.GPIO as GPIO
import time
import signal
import sys
import atexit

# Pin definition
RST_PIN = 18
CS_PIN = 22
DRDY_PIN = 17

# SPI device, bus = 0, device = 0
SPI = spidev.SpiDev(0, 0)

# Global cleanup function
def _global_gpio_cleanup():
    """Global GPIO cleanup function"""
    try:
        GPIO.cleanup()
    except:
        pass  # Ignore cleanup errors

# Register cleanup handlers
atexit.register(_global_gpio_cleanup)

def _signal_handler(sig, frame):
    """Signal handler for clean shutdown"""
    _global_gpio_cleanup()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
class config:
    RST_PIN = RST_PIN
    CS_PIN = CS_PIN
    DRDY_PIN = DRDY_PIN
    
    def digital_write(pin, value):
        GPIO.output(pin, value)

    def digital_read(pin):
        return GPIO.input(DRDY_PIN)

    def delay_ms(delaytime):
        time.sleep(delaytime // 1000.0)

    def spi_writebyte(data):
        SPI.writebytes(data)
        
    def spi_readbytes(reg):
        return SPI.readbytes(reg)
        

    def module_init():
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(RST_PIN, GPIO.OUT)
        GPIO.setup(CS_PIN, GPIO.OUT)
        #GPIO.setup(DRDY_PIN, GPIO.IN)
        GPIO.setup(DRDY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        SPI.max_speed_hz = 1000000
        SPI.mode = 0b01
        return 0;



ScanMode = 0


# gain channel
ADS1256_GAIN_E = {'ADS1256_GAIN_1' : 0, # GAIN   1
                  'ADS1256_GAIN_2' : 1,	# GAIN   2
                  'ADS1256_GAIN_4' : 2,	# GAIN   4
                  'ADS1256_GAIN_8' : 3,	# GAIN   8
                  'ADS1256_GAIN_16' : 4,# GAIN  16
                  'ADS1256_GAIN_32' : 5,# GAIN  32
                  'ADS1256_GAIN_64' : 6,# GAIN  64
                 }

# data rate
ADS1256_DRATE_E = {'ADS1256_30000SPS' : 0xF0, # reset the default values
                   'ADS1256_15000SPS' : 0xE0,
                   'ADS1256_7500SPS' : 0xD0,
                   'ADS1256_3750SPS' : 0xC0,
                   'ADS1256_2000SPS' : 0xB0,
                   'ADS1256_1000SPS' : 0xA1,
                   'ADS1256_500SPS' : 0x92,
                   'ADS1256_100SPS' : 0x82,
                   'ADS1256_60SPS' : 0x72,
                   'ADS1256_50SPS' : 0x63,
                   'ADS1256_30SPS' : 0x53,
                   'ADS1256_25SPS' : 0x43,
                   'ADS1256_15SPS' : 0x33,
                   'ADS1256_10SPS' : 0x20,
                   'ADS1256_5SPS' : 0x13,
                   'ADS1256_2d5SPS' : 0x03
                  }

# registration definition
REG_E = {'REG_STATUS' : 0,  # x1H
         'REG_MUX' : 1,     # 01H
         'REG_ADCON' : 2,   # 20H
         'REG_DRATE' : 3,   # F0H
         'REG_IO' : 4,      # E0H
         'REG_OFC0' : 5,    # xxH
         'REG_OFC1' : 6,    # xxH
         'REG_OFC2' : 7,    # xxH
         'REG_FSC0' : 8,    # xxH
         'REG_FSC1' : 9,    # xxH
         'REG_FSC2' : 10,   # xxH
        }

# command definition
CMD = {'CMD_WAKEUP' : 0x00,     # Completes SYNC and Exits Standby Mode 0000  0000 (00h)
       'CMD_RDATA' : 0x01,      # Read Data 0000  0001 (01h)
       'CMD_RDATAC' : 0x03,     # Read Data Continuously 0000   0011 (03h)
       'CMD_SDATAC' : 0x0F,     # Stop Read Data Continuously 0000   1111 (0Fh)
       'CMD_RREG' : 0x10,       # Read from REG rrr 0001 rrrr (1xh)
       'CMD_WREG' : 0x50,       # Write to REG rrr 0101 rrrr (5xh)
       'CMD_SELFCAL' : 0xF0,    # Offset and Gain Self-Calibration 1111    0000 (F0h)
       'CMD_SELFOCAL' : 0xF1,   # Offset Self-Calibration 1111    0001 (F1h)
       'CMD_SELFGCAL' : 0xF2,   # Gain Self-Calibration 1111    0010 (F2h)
       'CMD_SYSOCAL' : 0xF3,    # System Offset Calibration 1111   0011 (F3h)
       'CMD_SYSGCAL' : 0xF4,    # System Gain Calibration 1111    0100 (F4h)
       'CMD_SYNC' : 0xFC,       # Synchronize the A/D Conversion 1111   1100 (FCh)
       'CMD_STANDBY' : 0xFD,    # Begin Standby Mode 1111   1101 (FDh)
       'CMD_RESET' : 0xFE,      # Reset to Power-Up Values 1111   1110 (FEh)
       'CMD_WREG' : 0x50,       # Write to register
      }

class ADS1256:
    def __init__(self):
        self.rst_pin = config.RST_PIN
        self.cs_pin = config.CS_PIN
        self.drdy_pin = config.DRDY_PIN
        
        # Test pin availability and perform hardware reset if needed
        if not self._test_pin_availability():
            print("Pins not available, performing hardware reset...")
            self._hardware_reset()
            # Try again after reset
            if not self._test_pin_availability():
                print("Pins still not available after reset")
                raise RuntimeError("GPIO pins not available after hardware reset")

    # Hardware reset
    def ADS1256_reset(self):
        config.digital_write(self.rst_pin, GPIO.HIGH)
        config.delay_ms(200)
        config.digital_write(self.rst_pin, GPIO.LOW)
        config.delay_ms(200)
        config.digital_write(self.rst_pin, GPIO.HIGH)
    
    def ADS1256_WriteCmd(self, reg):
        config.digital_write(self.cs_pin, GPIO.LOW)#cs  0
        config.spi_writebyte([reg])
        config.digital_write(self.cs_pin, GPIO.HIGH)#cs 1
    
    def ADS1256_WriteReg(self, reg, data):
        self.ADS1256_WaitDRDY();
        config.digital_write(self.cs_pin, GPIO.LOW)#cs  0
        config.spi_writebyte([CMD['CMD_WREG'] | reg, 0x00, data])
        config.digital_write(self.cs_pin, GPIO.HIGH)#cs 1
        
    def ADS1256_Read_data(self, reg):
        config.digital_write(self.cs_pin, GPIO.LOW)#cs  0
        config.spi_writebyte([CMD['CMD_RREG'] | reg, 0x00])
        data = config.spi_readbytes(1)
        config.digital_write(self.cs_pin, GPIO.HIGH)#cs 1

        return data
        
    def ADS1256_WaitDRDY(self):
        for i in range(0,400000,1):
            if(config.digital_read(self.drdy_pin) == 0):
                
                break
        if(i >= 400000):
            print ("Time Out ...\r\n")
        
        

    def ADS1256_ReadChipID(self):
        self.ADS1256_WaitDRDY()
        id = self.ADS1256_Read_data(REG_E['REG_STATUS'])
        id = id[0] >> 4
        # print 'ID',id
        return id
        
    #The configuration parameters of ADC, gain and data rate
    def ADS1256_ConfigADC(self, gain, drate):
        self.ADS1256_WaitDRDY()
        buf = [0,0,0,0,0,0,0,0]
        buf[0] = (0<<3) | (1<<2) | (0<<1)
        buf[1] = 0x08
        buf[2] = (0<<5) | (0<<3) | (gain<<0)
        buf[3] = drate
        
        config.digital_write(self.cs_pin, GPIO.LOW)#cs  0
        config.spi_writebyte([CMD['CMD_WREG'] | 0, 0x03])
        config.spi_writebyte(buf)
        
        config.digital_write(self.cs_pin, GPIO.HIGH)#cs 1
        config.delay_ms(1) 



    def ADS1256_SetChannel(self, Channel):
        if Channel > 7:
            return 0
        self.ADS1256_WaitDRDY();
        self.ADS1256_WriteReg(REG_E['REG_MUX'], (Channel<<4) | (1<<3))

    def ADS1256_SetDiffChannel(self, pos_channel, neg_channel):
        """Set differential channel pair - any valid pair per ADS1256 datasheet"""
        # Validate channel ranges (0-7 for ADS1256)
        if not (0 <= pos_channel <= 7) or not (0 <= neg_channel <= 7):
            raise ValueError("Channel numbers must be between 0 and 7")
        
        # MUX register: PSEL[3:0] in bits 7-4, NSEL[3:0] in bits 3-0
        mux_value = (pos_channel << 4) | neg_channel
        print(f"DEBUG: Setting differential pair AIN{pos_channel}-AIN{neg_channel}, MUX=0x{mux_value:02X}")
        self.ADS1256_WaitDRDY();

        self.ADS1256_WriteReg(REG_E['REG_MUX'], mux_value)

    def ADS1256_SetMode(self, Mode):
        ScanMode = Mode

    def ADS1256_init(self):
        # Ensure clean GPIO state before initialization
        GPIO.setwarnings(False)
        GPIO.cleanup()  # Free any existing GPIO allocations
        
        # Test pin availability and perform hardware reset if needed
        if not self._test_pin_availability():
            print("Pins not available, performing hardware reset...")
            self._hardware_reset()
            # Try again after reset
            if not self._test_pin_availability():
                print("Pins still not available after reset")
                return -1
        
        if (config.module_init() != 0):
            return -1
        self.ADS1256_reset()
        id = self.ADS1256_ReadChipID()
        if id == 3 :
            print("ID Read success  ")
        else:
            print("ID Read failed   ")
            return -1
        self.ADS1256_ConfigADC(ADS1256_GAIN_E['ADS1256_GAIN_1'], ADS1256_DRATE_E['ADS1256_30000SPS'])
        return 0
        
    def ADS1256_Read_ADC_Data(self):
        self.ADS1256_WaitDRDY()
        config.digital_write(self.cs_pin, GPIO.LOW)#cs  0
        config.spi_writebyte([CMD['CMD_RDATA']])
        config.delay_ms(15)

        buf = config.spi_readbytes(3)
        config.digital_write(self.cs_pin, GPIO.HIGH)#cs 1
        read = (buf[0]<<16) & 0xff0000
        read |= (buf[1]<<8) & 0xff00
        read |= (buf[2]) & 0xff
        if read & 0x800000:  # negative value
            read -= 1 << 24  # sign extend from 24 bits

        return read
 
    def ADS1256_GetChannelValue(self, Channel, neg_channel=None):
        if neg_channel is not None:
            # Differential mode - follow datasheet sequence
            if Channel >= 8 or neg_channel >= 8:
                return 0
            print(f"DEBUG: Reading differential AIN{Channel}-AIN{neg_channel}")
            
            # Step 2: Use WREG command to change MUX register
            mux_value = (Channel << 4) | neg_channel
            print(f"DEBUG: Setting differential pair AIN{Channel}-AIN{neg_channel}, MUX=0x{mux_value:02X}")
            self.ADS1256_WriteReg(REG_E['REG_MUX'], mux_value)
            
            # Step 3: Issue SYNC command immediately
            self.ADS1256_WriteCmd(CMD['CMD_SYNC'])
            
            # Step 4: Issue WAKEUP command (with timing t11)
            config.delay_ms(1)  # t11 timing
            self.ADS1256_WriteCmd(CMD['CMD_WAKEUP'])
            
            # Step 6: Read data
            Value = self.ADS1256_Read_ADC_Data()
            print(f"DEBUG: Differential raw value: {Value}")
        else:
            # Single-ended mode - similar sequence
            if Channel >= 8:
                return 0
            print(f"DEBUG: Reading single-ended AIN{Channel}")
            
            # Wait for DRDY
            
            # Use WREG to set MUX
            mux_value = (Channel << 4) | 0x08  # Single-ended to AINCOM
            self.ADS1256_WriteReg(REG_E['REG_MUX'], mux_value)
            
            # SYNC/WAKEUP sequence
            self.ADS1256_WriteCmd(CMD['CMD_SYNC'])
            config.delay_ms(1)
            self.ADS1256_WriteCmd(CMD['CMD_WAKEUP'])
            
            Value = self.ADS1256_Read_ADC_Data()
            print(f"DEBUG: Single-ended raw value: {Value}")
        
        
        return Value
        
    def ADS1256_GetAll(self):
        ADC_Value = [0,0,0,0,0,0,0,0]
        for i in range(0,8,1):
            ADC_Value[i] = self.ADS1256_GetChannelValue(i)
        return ADC_Value
        
    def _test_pin_availability(self):
        """Test if CS and DRDY pins are available"""
        GPIO.setmode(GPIO.BCM)
        available = True
        
        # Test CS pin (22)
        try:
            GPIO.setup(self.cs_pin, GPIO.OUT)
            GPIO.cleanup(self.cs_pin)
            print(f"CS pin {self.cs_pin}: OK")
        except Exception as e:
            print(f"CS pin {self.cs_pin}: FAILED - {e}")
            available = False
        
        # Test DRDY pin (17) 
        try:
            GPIO.setup(self.drdy_pin, GPIO.IN)
            GPIO.cleanup(self.drdy_pin)
            print(f"DRDY pin {self.drdy_pin}: OK")
        except Exception as e:
            print(f"DRDY pin {self.drdy_pin}: FAILED - {e}")
            available = False
            
        return available
    
    def _hardware_reset(self):
        """Perform hardware reset by holding RST pin low"""
        try:
            GPIO.setmode(GPIO.BCM)
            # Set RST pin as output and hold low
            GPIO.setup(self.rst_pin, GPIO.OUT)
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.1)  # Hold reset for 100ms
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.1)  # Wait for reset to complete
            GPIO.cleanup(self.rst_pin)
        except Exception as e:
            print(f"Hardware reset failed: {e}")
    
    def ADS1256_cleanup(self):
        """Clean up GPIO pins and SPI resources"""
        GPIO.cleanup()
        
    def ADS1256_GetDefined(self, definition):
        """
        Read ADC channels based on JSON definition
        definition: JSON object with array of channel definitions
        Each definition object contains: {channel, differential, neg-channel (if differential), buffered, SPS, gain}
        """
        import json
        
        # Parse JSON if it's a string, otherwise use as-is
        if isinstance(definition, str):
            definition = json.loads(definition)
        
        results = []
        
        for channel_def in definition:
            channel = channel_def.get('channel', 0)
            differential = channel_def.get('differential', False)
            neg_channel = channel_def.get('neg-channel', 1)
            buffered = channel_def.get('buffered', False)
            sps = channel_def.get('SPS', 10)
            gain = channel_def.get('gain', 1)
            
            # Configure ADC for this channel
            self.ADS1256_ConfigADC(ADS1256_GAIN_E[f'ADS1256_GAIN_{gain}'], ADS1256_DRATE_E[f'ADS1256_{sps}SPS'])
            
            
            # Read the channel using the proven GetChannelValue method
            if differential:
                raw_value = self.ADS1256_GetChannelValue(channel, neg_channel)
            else:
                raw_value = self.ADS1256_GetChannelValue(channel)
            
            # Calculate voltage (using the working formula from the original code)
            # Gain affects the full scale range, so divide by gain
            voltage = (raw_value * 5.0 / 0x7fffff) / gain
            
            result = {
                'channel': channel,
                'differential': differential,
                'negChannel': neg_channel if differential else None,
                'buffered': buffered,
                'sps': sps,
                'gain': gain,
                'raw': raw_value,
                'voltage': voltage
            }
            
            results.append(result)
        
        return results
### END OF FILE ###