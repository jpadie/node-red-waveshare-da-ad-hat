#!/usr/bin/env python3
"""
Node-RED Waveshare DA/AD HAT Worker Process
Calls proven ad.py and da.py scripts with queuing
"""

import json
import sys
import time
import logging
import threading
import subprocess
import os
from typing import Dict, Any, Optional, List
from queue import Queue, Empty

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

class WorkerManager:
    def __init__(self):
        self.request_queue = Queue()
        self.response_queue = Queue()
        self.worker_thread = None
        self.running = False
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        
    def start(self):
        """Start the worker thread"""
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        log.info("Worker started with ad.py/da.py subprocess calls")
        
    def stop(self):
        """Stop the worker thread"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)
        log.info("Worker stopped")
        
    def _worker_loop(self):
        """Main worker loop that processes requests"""
        while self.running:
            try:
                # Get next request with timeout
                request = self.request_queue.get(timeout=0.1)
                
                try:
                    response = self._process_request(request)
                    self.response_queue.put(response)
                except Exception as e:
                    error_response = {
                        "id": request.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {str(e)}"
                        }
                    }
                    self.response_queue.put(error_response)
                finally:
                    self.request_queue.task_done()
                    
            except Empty:
                continue
            except Exception as e:
                log.error(f"Worker loop error: {e}")
                
    def _process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single JSON-RPC request"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        if method == "read_adc":
            return self._handle_read_adc(params, request_id)
        elif method == "write_dac":
            return self._handle_write_dac(params, request_id)
        elif method == "ping":
            return {"id": request_id, "result": "pong"}
        else:
            return {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
            
    def _handle_read_adc(self, params: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
        """Handle ADC read request by calling ad.py"""
        channel = params.get("channel", 0)
        gain = params.get("gain", 1)
        drate = params.get("drate", 10.0)
        differential = params.get("differential", False)
        neg_channel = params.get("neg_channel", 1)
        buffered = params.get("buffered", False)
        
        # Build ad.py command
        cmd = [
            "python3", 
            os.path.join(self.script_dir, "ad.py"),
            "--channel", str(channel),
            "--gain", str(gain),
            "--drate", str(drate),
            "--differential", "1" if differential else "0",
            "--neg-channel", str(neg_channel),
            "--buffered", "1" if buffered else "0"
        ]
        
        try:
            # Call ad.py and capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10.0,
                cwd=self.script_dir
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"ad.py failed: {result.stderr}")
                
            # Parse ad.py output for raw value
            raw_value = self._parse_ad_output(result.stdout)
            
            # Calculate correct voltage (ad.py uses wrong formula)
            voltage_mv = self._calculate_voltage_mv(raw_value, gain)
            
            return {
                "id": request_id,
                "result": {
                    "channel": channel,
                    "negChannel": neg_channel if differential else None,
                    "differential": differential,
                    "buffered": buffered,
                    "raw": raw_value,
                    "voltage_mv": voltage_mv,
                    "gain": gain,
                    "drate": drate,
                    "ts": time.time()
                }
            }
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("ad.py timeout")
        except Exception as e:
            raise RuntimeError(f"ad.py execution failed: {e}")
            
    def _handle_write_dac(self, params: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
        """Handle DAC write request by calling da.py"""
        channel = params.get("channel", 0)
        voltage = params.get("voltage", 0.0)
        
        # Build da.py command
        cmd = [
            "python3",
            os.path.join(self.script_dir, "da.py"),
            "--channel", str(channel),
            "--voltage", str(voltage)
        ]
        
        try:
            # Call da.py
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                cwd=self.script_dir
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"da.py failed: {result.stderr}")
                
            return {
                "id": request_id,
                "result": {
                    "channel": channel,
                    "voltage": voltage,
                    "ts": time.time()
                }
            }
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("da.py timeout")
        except Exception as e:
            raise RuntimeError(f"da.py execution failed: {e}")
            
    def _parse_ad_output(self, output: str) -> int:
        """Parse raw value from ad.py output"""
        lines = output.strip().split('\n')
        for line in lines:
            if line.startswith('RAW:'):
                try:
                    return int(line.split(':', 1)[1].strip())
                except (ValueError, IndexError):
                    continue
        raise RuntimeError("Could not parse raw value from ad.py output")
        
    def _calculate_voltage_mv(self, raw: int, gain: int) -> float:
        """Calculate voltage in mV using correct formula"""
        ADC_VREF = 2.5  # 2.5V reference
        FSR = 2 * ADC_VREF  # Full Scale Range = +/- VREF = 5.0V
        # Correct formula: mV = (raw / (2^23 - 1)) * (FSR / PGA) * 1000
        return (raw / (2**23 - 1)) * (FSR / gain) * 1000
        
    def submit_request(self, request: Dict[str, Any]) -> None:
        """Submit a request to the worker queue"""
        self.request_queue.put(request)
        
    def get_response(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get a response from the worker queue"""
        try:
            return self.response_queue.get(timeout=timeout)
        except Empty:
            return None

def main():
    """Main entry point"""
    worker = WorkerManager()
    worker.start()
    
    try:
        # JSON-RPC over stdio
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                worker.submit_request(request)
                
                # Wait for response
                response = worker.get_response(timeout=5.0)
                if response:
                    print(json.dumps(response))
                    sys.stdout.flush()
                else:
                    error_response = {
                        "id": request.get("id"),
                        "error": {
                            "code": -32603,
                            "message": "Request timeout"
                        }
                    }
                    print(json.dumps(error_response))
                    sys.stdout.flush()
                    
            except json.JSONDecodeError as e:
                error_response = {
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e}"
                    }
                }
                print(json.dumps(error_response))
                sys.stdout.flush()
            except Exception as e:
                log.error(f"Request processing error: {e}")
                
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        worker.stop()

if __name__ == "__main__":
    main()