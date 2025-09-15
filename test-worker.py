#!/usr/bin/env python3
"""
Test script to verify worker functionality without hardware dependencies
"""

import json
import sys
import time

def simulate_worker():
    """Simulate the worker responses"""
    print("Simulated worker started", file=sys.stderr)
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
                
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
                print(json.dumps(response))
                sys.stdout.flush()
                continue
            
            method = request.get("method")
            params = request.get("params", {})
            _id = request.get("id")
            
            if method == "ping":
                response = {"jsonrpc": "2.0", "id": _id, "result": {"status": "ok", "ts": time.time()}}
            elif method == "init_adc":
                response = {"jsonrpc": "2.0", "id": _id, "result": {"status": "ok", "message": "ADC initialized successfully"}}
            elif method == "set_dac_value":
                port = int(params.get("port", 0))
                value = int(params.get("value", 0))
                response = {"jsonrpc": "2.0", "id": _id, "result": {"port": port, "value": value}}
            elif method == "set_dac_voltage":
                port = int(params.get("port", 0))
                voltage = float(params.get("voltage", 0.0))
                vref = float(params.get("vref", 2.5))
                value = int(round((voltage / vref) * 65535))
                response = {"jsonrpc": "2.0", "id": _id, "result": {"port": port, "value": value, "voltage_mv": int(voltage * 1000), "vref": vref}}
            elif method == "read_adc":
                channel = int(params.get("channel", 0))
                gain = int(params.get("gain", 1))
                drate = float(params.get("drate", 10.0))
                differential = bool(params.get("differential", False))
                neg_channel = int(params.get("negChannel", 8))
                buffered = bool(params.get("buffered", False))
                
                # Simulate a reading
                raw_value = 1000000 + (channel * 100000)
                voltage_mv = (raw_value * 5.0 / 0x7fffff) / gain * 1000
                
                response = {
                    "jsonrpc": "2.0", 
                    "id": _id, 
                    "result": {
                        "channel": channel,
                        "negChannel": neg_channel if differential and neg_channel < 8 else None,
                        "differential": differential,
                        "buffered": buffered,
                        "raw": raw_value,
                        "voltage_mv": voltage_mv,
                        "gain": gain,
                        "drate": drate,
                        "ts": time.time()
                    }
                }
            else:
                response = {"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
            
            print(json.dumps(response))
            sys.stdout.flush()
            
        except Exception as e:
            print(f"Error processing request: {e}", file=sys.stderr)
            response = {"jsonrpc": "2.0", "id": _id if '_id' in locals() else None, "error": {"code": -32603, "message": str(e)}}
            print(json.dumps(response))
            sys.stdout.flush()

if __name__ == "__main__":
    simulate_worker()
