#!/usr/bin/env python3
"""
Test stub for ADS1256_GetDefined method
Tests ADC1 (single-ended) and ADC3 (differential) channels
"""

import json
from waveSharePython import ADS1256

def test_ads1256_defined():
    # Initialize ADC
    ADC = ADS1256()
    if ADC.ADS1256_init() != 0:
        print("Failed to initialize ADC")
        return
    
    print("ADC initialized successfully")
    
    # Test definition for ADC1 (single-ended) and ADC3 (differential)
    definition = [
        {
            "channel": 1,
            "differential": False,
            "buffered": False,
            "SPS": 10,
            "gain": 1
        },
        {
            "channel": 3,
            "differential": True,
            "neg-channel": 1,
            "buffered": False,
            "SPS": 10,
            "gain": 1
        }
    ]
    
    print("Testing ADC1 (single-ended) and ADC3 (differential)...")
    print("Configuration:")
    print(json.dumps(definition, indent=2))
    print()
    print("Starting continuous loop (Ctrl+C to stop)...")
    print()
    
    # Continuous testing loop
    try:
        while True:
            # Test the GetDefined method
            try:
                results = ADC.ADS1256_GetDefined(definition)
                
                if results is None:
                    print("Error: GetDefined returned None")
                    continue
                
                print("Results:")
                for i, result in enumerate(results):
                    print(f"Channel {result['channel']}:")
                    print(f"  Raw value: {result['raw']}")
                    print(f"  Voltage: {result['voltage']:.6f}V")
                    print(f"  Differential: {result['differential']}")
                    if result['differential']:
                        print(f"  Negative channel: {result['negChannel']}")
                    print(f"  Buffered: {result['buffered']}")
                    print(f"  SPS: {result['sps']}")
                    print(f"  Gain: {result['gain']}")
                    print()
                
                print("-" * 50)
                
            except Exception as e:
                print(f"Error during test: {e}")
                import traceback
                traceback.print_exc()
                print("-" * 50)
                
    except KeyboardInterrupt:
        print("\nTest stopped by user")
    finally:
        # Clean up GPIO using the ADC's cleanup method
        ADC.ADS1256_cleanup()
        print("GPIO cleaned up")

if __name__ == "__main__":
    test_ads1256_defined()
