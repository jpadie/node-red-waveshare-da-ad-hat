#!/usr/bin/env python3
"""
Debug script for DAC8532 issues
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from python.da import DAC8532Controller
import time

def test_dac_basic():
    """Basic DAC test"""
    print("=== DAC8532 Basic Test ===")
    
    try:
        # Initialize DAC
        dac = DAC8532Controller(vref=3.3)
        dac.initialize_gpio()
        dac.initialize_spi()
        
        print("DAC initialized successfully")
        print(f"VREF: {dac.vref}V")
        print(f"Resolution: {dac.dac_resolution}")
        print(f"Voltage per LSB: {dac.voltage_per_lsb:.8f}V")
        
        # Test DAC0 (Port 0)
        print("\n--- Testing DAC0 (Port 0) ---")
        test_values = [0, 32768, 65535]  # 0V, 1.65V, 3.3V
        
        for value in test_values:
            print(f"Setting DAC0 to value {value} (0x{value:04X})")
            success = dac.set_dac_value(0, value)
            if success:
                voltage = dac.get_voltage_for_value(value)
                print(f"  ✓ DAC0 set to {voltage:.6f}V")
            else:
                print(f"  ✗ Failed to set DAC0")
            time.sleep(1)
        
        # Test DAC1 (Port 1)
        print("\n--- Testing DAC1 (Port 1) ---")
        for value in test_values:
            print(f"Setting DAC1 to value {value} (0x{value:04X})")
            success = dac.set_dac_value(1, value)
            if success:
                voltage = dac.get_voltage_for_value(value)
                print(f"  ✓ DAC1 set to {voltage:.6f}V")
            else:
                print(f"  ✗ Failed to set DAC1")
            time.sleep(1)
        
        dac.cleanup()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def test_dac_commands():
    """Test DAC commands"""
    print("\n=== DAC8532 Command Analysis ===")
    
    # Current commands in the code
    print("Current commands in da.py:")
    print(f"CMD_WRITE_DAC_A = 0x10 (16)")
    print(f"CMD_WRITE_DAC_B = 0x12 (18)")
    print(f"CMD_WRITE_DAC_A_UPDATE_B = 0x11 (17)")
    print(f"CMD_WRITE_DAC_B_UPDATE_A = 0x13 (19)")
    
    # Let's check what the actual DAC8532 commands should be
    print("\nDAC8532 datasheet commands (typical):")
    print("DAC A: 0x10 (16) - Write to DAC A register")
    print("DAC B: 0x12 (18) - Write to DAC B register")
    print("Both: 0x14 (20) - Write to both DACs")
    
    print("\nThe commands look correct, but let's verify the port mapping...")

def test_port_mapping():
    """Test port mapping logic"""
    print("\n=== Port Mapping Test ===")
    
    # Current logic in set_dac_value:
    print("Current port mapping in set_dac_value():")
    print("if port == 0: command = CMD_WRITE_DAC_A (0x10)")
    print("else: command = CMD_WRITE_DAC_B (0x12)")
    
    print("\nThis means:")
    print("Port 0 → DAC A (0x10)")
    print("Port 1 → DAC B (0x12)")
    
    print("\nBut you mentioned 'DAC1 pin' - let's clarify:")
    print("- DAC A (Port 0) = Physical pin 1?")
    print("- DAC B (Port 1) = Physical pin 2?")
    
    print("\nPossible issues:")
    print("1. Port mapping is reversed")
    print("2. Wrong CS pin")
    print("3. SPI configuration issue")
    print("4. Hardware connection issue")

if __name__ == "__main__":
    test_dac_commands()
    test_port_mapping()
    
    # Uncomment to run actual hardware test
    # test_dac_basic()
    
    print("\n=== Debugging Steps ===")
    print("1. Check if DAC0 (Port 0) works")
    print("2. Check if DAC1 (Port 1) works")
    print("3. Verify physical connections")
    print("4. Check SPI bus with oscilloscope/logic analyzer")
    print("5. Verify CS pin is correct")
    print("6. Check if port mapping needs to be reversed")






