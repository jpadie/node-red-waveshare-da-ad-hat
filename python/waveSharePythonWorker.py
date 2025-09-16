import spidev
import RPi.GPIO as GPIO
import time
import signal
import sys
import atexit
import json
import logging
import threading
import subprocess
import os
from typing import Dict, Any, Optional, List, Tuple
from queue import Queue, Empty
from dataclasses import dataclass
import io
import contextlib

# Optional libgpiod for edge events (Bookworm)
try:
    import gpiod  # type: ignore
except Exception:
    gpiod = None  # Fallback to polling if unavailable

# Import the working ADS1256 class
from waveSharePython import ADS1256 as WorkingADS1256


# Pin definitions and SPI device removed - using imported ADS1256 class

# Global cleanup function
def _global_gpio_cleanup():
    """Global GPIO cleanup function"""
    try:
        GPIO.cleanup()
    except:
        pass  # Ignore cleanup errors

# Register cleanup handlers
atexit.register(_global_gpio_cleanup)


# -----------------------------
# Logging to STDERR (Node reads responses from STDOUT)
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger(__name__)

# -----------------------------
# Config / Constants
# -----------------------------
@dataclass
class WorkerConfig:
    # GPIO (BCM numbering) as per Waveshare High-Precision AD/DA HAT silk
    adc_cs_pin: int = 22
    adc_rst_pin: int = 18
    adc_drdy_pin: int = 17
    dac_cs_pin: int = 23

    spi_bus: int = 0
    spi_dev: int = 0
    spi_speed_hz: int = 1_200_000  # Pi 4B-friendly default; overridable via WS_SPI_HZ

    # Watchdog & timeouts
    idle_shutdown_s: int = 300      # generous; worker stays alive while busy
    request_timeout_s: int = 10     # per-request guard

    # GPIO init retry policy
    gpio_init_retries: int = 3
    gpio_retry_delay_s: float = 0.05


class SPIResourceManager:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.spi: Optional[spidev.SpiDev] = None
        self.gpio_ready = False
        self.lock = threading.Lock()
        # gpiod state
        self._gpiod_chip: Optional["gpiod.Chip"] = None
        self._gpiod_drdy_line: Optional["gpiod.Line"] = None

    # Force GPIO ownership - override any existing allocations
    def _force_gpio_ownership(self) -> None:
        """Force ownership of required GPIO pins by overriding any existing allocations"""
        try:
            # Multiple cleanup attempts to ensure pins are freed
            for _ in range(3):
                try:
                    GPIO.cleanup()
                except:
                    pass
                time.sleep(0.01)
            
            # Set mode and disable warnings
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # Force allocate pins - this will override any existing allocations
            GPIO.setup(self.cfg.adc_cs_pin, GPIO.OUT, initial=GPIO.HIGH)
            GPIO.setup(self.cfg.adc_rst_pin, GPIO.OUT, initial=GPIO.HIGH)
            GPIO.setup(self.cfg.adc_drdy_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.cfg.dac_cs_pin, GPIO.OUT, initial=GPIO.HIGH)

            # Setup gpiod edge line if available
            if gpiod is not None:
                try:
                    if self._gpiod_chip is not None:
                        try:
                            self._gpiod_chip.close()
                        except Exception:
                            pass
                    self._gpiod_chip = gpiod.Chip('gpiochip0')
                    self._gpiod_drdy_line = self._gpiod_chip.get_line(self.cfg.adc_drdy_pin)
                    self._gpiod_drdy_line.request(consumer='waveshare_worker', type=gpiod.LINE_REQ_EV_FALLING)
                    log.info("gpiod DRDY line configured for falling-edge events")
                except Exception as e:
                    self._gpiod_chip = None
                    self._gpiod_drdy_line = None
                    log.warning(f"gpiod setup failed; falling back to polling: {e}")
            
            log.info(f"Forced GPIO ownership: ADC_CS={self.cfg.adc_cs_pin}, ADC_RST={self.cfg.adc_rst_pin}, DRDY={self.cfg.adc_drdy_pin}, DAC_CS={self.cfg.dac_cs_pin}")
            
        except Exception as e:
            log.error(f"Failed to force GPIO ownership: {e}")
            raise RuntimeError(f"Could not claim required GPIO pins: {e}")

    # Lazily set up GPIO on first use
    def _setup_gpio(self) -> bool:
        if self.gpio_ready:
            return True
        try:
            self._force_gpio_ownership()
            self.gpio_ready = True
            return True
        except Exception as e:
            log.error(f"GPIO setup failed: {e}")
            return False

    def ensure_gpio_ready(self) -> None:
        """Ensure GPIO is initialized, forcing ownership if needed."""
        if self._setup_gpio():
            return
        
        # Force ownership - this will override any existing allocations
        try:
            self._force_gpio_ownership()
            self.gpio_ready = True
        except Exception as e:
            raise RuntimeError(f"Could not force GPIO ownership: {e}")

    # Lazily set up SPI on first use
    def _setup_spi(self) -> None:
        if self.spi is not None:
            return
        try:
            s = spidev.SpiDev()
            s.open(self.cfg.spi_bus, self.cfg.spi_dev)
            # Default to ADC-friendly speed; individual ops may override
            try:
                env_hz = int(os.environ.get("WS_SPI_HZ", "0"))
            except Exception:
                env_hz = 0
            s.max_speed_hz = env_hz if env_hz > 0 else self.cfg.spi_speed_hz
            s.mode = 0b01
            s.lsbfirst = False
            s.cshigh = False
            s.no_cs = True  # we drive CS on GPIO to avoid CE0 auto toggling
            self.spi = s
            log.info(
                f"SPI open bus={self.cfg.spi_bus}, dev={self.cfg.spi_dev}, "
                f"speed={self.spi.max_speed_hz}Hz, mode=1, no_cs=True"
            )
        except Exception as e:
            log.error(f"SPI open failed: {e}")
            raise

    def set_speed(self, hz: int) -> None:
        """Set SPI clock for the next operation."""
        if self.spi is None:
            self._setup_spi()
        try:
            self.spi.max_speed_hz = hz
        except Exception as e:
            log.warning(f"Failed to set SPI speed to {hz}: {e}")

    def cleanup(self) -> None:
        with self.lock:
            # Close SPI first
            if self.spi is not None:
                try:
                    self.spi.close()
                except Exception:
                    pass
                self.spi = None
            
            # Ensure CS pins are set high before cleanup
            if self.gpio_ready:
                try:
                    GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)
                    GPIO.output(self.cfg.dac_cs_pin, GPIO.HIGH)
                except Exception:
                    pass
            
            # Cleanup GPIO pins
            if self.gpio_ready:
                try:
                    # Release gpiod line
                    if self._gpiod_drdy_line is not None:
                        try:
                            self._gpiod_drdy_line.release()
                        except Exception:
                            pass
                        self._gpiod_drdy_line = None
                    if self._gpiod_chip is not None:
                        try:
                            self._gpiod_chip.close()
                        except Exception:
                            pass
                        self._gpiod_chip = None
                    GPIO.cleanup()
                except Exception:
                    pass
                self.gpio_ready = False
            
            log.info("SPI/GPIO cleaned up - CS pins freed")


class DAC8532:
    def __init__(self, rm: SPIResourceManager, cfg: WorkerConfig):
        self.rm = rm
        self.cfg = cfg

    def set_value(self, port: int, value: int) -> Dict[str, Any]:
        if port not in (0, 1):
            raise ValueError("port must be 0 or 1")
        if not (0 <= value <= 0xFFFF):
            raise ValueError("value must be 0..65535")
        # Serialize DAC ops with ADC via shared lock
        with self.rm.lock:
            self.rm.ensure_gpio_ready()
            self.rm._setup_spi()

        # Match working da.py: 20kHz, mode=1
        cmd = 0x30 if port == 0 else 0x34
        hi = (value >> 8) & 0xFF
        lo = value & 0xFF
        GPIO.output(self.cfg.dac_cs_pin, GPIO.LOW)
        try:
            self.rm.spi.writebytes([cmd, hi, lo])
        finally:
            GPIO.output(self.cfg.dac_cs_pin, GPIO.HIGH)
        return {"port": port, "value": value}

    def set_voltage(self, port: int, voltage: float, vref: float = 5.0) -> Dict[str, Any]:
        if not (0.0 <= voltage <= vref):
            raise ValueError(f"voltage must be 0..{vref}V")
        value = int(round((voltage / vref) * 65535))
        out = self.set_value(port, value)
        out["voltage_mv"] = int(voltage * 1000)
        out["vref"] = vref
        return out

    def get_voltage_for_value(self, value: int, vref: float = 5.0) -> float:
        """Get voltage output for a given DAC value"""
        if not (0 <= value <= 65535):
            raise ValueError("value must be 0-65535")
        return (value / 65535.0) * vref

    def get_value_for_voltage(self, voltage: float, vref: float = 5.0) -> int:
        """Get DAC value for a given voltage"""
        if not (0.0 <= voltage <= vref):
            raise ValueError(f"voltage must be 0..{vref}V")
        return int(round((voltage / vref) * 65535))


# -----------------------------
# Worker (JSON-RPC stdio)
# -----------------------------
class Worker:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.rm = SPIResourceManager(cfg)
        self.dac = DAC8532(self.rm, cfg)
        self.adc = None  # Lazy initialize ADS1256 on first use
        self._adc_inited = False

        # Global stdout guard: divert accidental prints away from Node-RED
        # Keep a handle to the real stdout only for JSON responses
        self._real_stdout = sys.stdout
        sys.stdout = io.StringIO()

        self.running = True
        self.last_activity = time.time()
        self.in_progress = threading.Event()
        
        signal.signal(signal.SIGINT, self._sig)
        signal.signal(signal.SIGTERM, self._sig)
        
        self.watchdog_t = threading.Thread(target=self._watchdog, daemon=True)
        self.watchdog_t.start()

        # Streaming state
        self.stream_running = False
        self.stream_cfg: Optional[Dict[str, Any]] = None
        self.stream_thread: Optional[threading.Thread] = None
        
    def _ensure_adc(self) -> None:
        """Lazily construct the ADS1256 instance when first needed."""
        if self.adc is None:
            try:
                # Import already available at module top; instantiate now
                # Ensure shared SPI is opened and configured
                self.rm._setup_spi()
                # Ensure GPIO is ready before ADS1256 uses pins
                self.rm.ensure_gpio_ready()
                # Inject shared SPI into waveSharePython module so ADS1256 uses it
                try:
                    import waveSharePython as _wsp
                    _wsp.SPI = self.rm.spi
                except Exception:
                    pass
                self.adc = WorkingADS1256()
            except Exception as e:
                raise RuntimeError(f"ADC init/import failed: {e}")

    # ---- Error helpers / codes ----
    _ERR = {
        "gpio_unavailable": -32010,
        "spi_busy": -32011,
        "ads_init_failed": -32012,
        "parse_error": -32700,
        "invalid_params": -32602,
        "method_not_found": -32601,
        "internal_error": -32603,
        "timeout": -32013,
        "stream_conflict": -32014,
    }

    def _err_resp(self, _id: Any, code_key: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "error": {
                "code": self._ERR.get(code_key, self._ERR["internal_error"]),
                "message": message,
                **({"data": data} if data else {}),
            },
        }

    @contextlib.contextmanager
    def _suppress_stdout(self):
        """Suppress stdout temporarily to prevent non-JSON prints from leaking.
        This avoids DEBUG prints in imported modules corrupting our JSON-RPC stream.
        """
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            yield
        finally:
            try:
                # Best-effort: capture and log any leaked text to stderr for debugging
                leaked = sys.stdout.getvalue()
                if leaked:
                    for line in leaked.splitlines():
                        log.debug(f"[suppressed stdout] {line}")
            except Exception:
                pass
            sys.stdout = saved_stdout

    def _status(self) -> Dict[str, Any]:
        """Return health/status information."""
        return {
            "pid": os.getpid(),
            "gpioReady": bool(self.rm.gpio_ready),
            "spiOpen": bool(self.rm.spi is not None),
            "hasGpiod": bool(gpiod is not None and self.rm._gpiod_drdy_line is not None),
            "streamRunning": bool(self.stream_running),
        }

    def _sig(self, signum, _frame):
        log.info(f"Signal {signum}; shutting down")
        self.running = False
        # Clean up GPIO on signal
        try:
            self.rm.cleanup()
            # Also cleanup ADC pins directly
            if hasattr(self, 'adc') and self.adc:
                self.adc.ADS1256_cleanup()
        except:
            pass
        
    def _tick(self):
        self.last_activity = time.time()

    def _watchdog(self):
        while self.running:
            time.sleep(1)
            if self.in_progress.is_set():
                self._tick()
                continue
            if time.time() - self.last_activity > self.cfg.idle_shutdown_s:
                log.info(f"No activity for {self.cfg.idle_shutdown_s}s, shutting down")
                self.running = False
                break
                
    def _with_timeout(self, fn, timeout_s: float, *a, **kw) -> Tuple[Any, Optional[Exception]]:
        box: Dict[str, Any] = {}
        err: Dict[str, Exception] = {}

        def target():
            try:
                box["ret"] = fn(*a, **kw)
            except Exception as e:
                err["e"] = e

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout_s)
        if t.is_alive():
            return None, TimeoutError(f"operation timed out after {timeout_s}s")
        if "e" in err:
            return None, err["e"]
        return box.get("ret"), None

    def _write_response(self, resp: Dict[str, Any]) -> None:
        self._real_stdout.write(json.dumps(resp) + "\n")
        self._real_stdout.flush()

    def handle(self, req: Dict[str, Any]) -> Dict[str, Any]:
        self._tick()
        method = req.get("method")
        params = req.get("params") or {}
        _id = req.get("id")

        try:
            if method == "ping":
                return {"jsonrpc": "2.0", "id": _id, "result": {"status": "ok", "ts": time.time()}}
            
            if method == "status":
                return {"jsonrpc": "2.0", "id": _id, "result": self._status()}
            
            if method == "init_adc":
                # Initialize ADC with forced GPIO allocation
                try:
                    self._ensure_adc()
                    with self._suppress_stdout():
                        init_result = self.adc.ADS1256_init()
                    if init_result == 0:
                        self._adc_inited = True
                        return {"jsonrpc": "2.0", "id": _id, "result": {"status": "ok", "message": "ADC initialized successfully"}}
                    return self._err_resp(_id, "ads_init_failed", "ADC initialization failed")
                except Exception as e:
                    return self._err_resp(_id, "ads_init_failed", f"ADC init error: {type(e).__name__}: {e}")
            
            if method == "set_dac_value":
                ret = self.dac.set_value(int(params["port"]), int(params["value"]))
                return {"jsonrpc": "2.0", "id": _id, "result": ret}

            if method == "set_dac_voltage":
                ret = self.dac.set_voltage(int(params["port"]), float(params["voltage"]), float(params.get("vref", 5.0)))
                return {"jsonrpc": "2.0", "id": _id, "result": ret}

            if method == "get_dac_voltage_for_value":
                value = int(params["value"])
                vref = float(params.get("vref", 5.0))
                voltage = self.dac.get_voltage_for_value(value, vref)
                return {"jsonrpc": "2.0", "id": _id, "result": {"value": value, "voltage": voltage, "vref": vref}}

            if method == "get_dac_value_for_voltage":
                voltage = float(params["voltage"])
                vref = float(params.get("vref", 5.0))
                value = self.dac.get_value_for_voltage(voltage, vref)
                return {"jsonrpc": "2.0", "id": _id, "result": {"voltage": voltage, "value": value, "vref": vref}}

            if method == "read_adc":
                if self.stream_running:
                    return self._err_resp(_id, "stream_conflict", "read_adc unavailable while streaming is active")
                
                # Convert single channel request to definition format
                self._ensure_adc()
                # Ensure GPIO is ready before attempting any ADC operation
                try:
                    self.rm.ensure_gpio_ready()
                except Exception as e:
                    return self._err_resp(_id, "gpio_unavailable", f"GPIO not ready: {e}")
                # Ensure ADC is initialized (idempotent)
                try:
                    with self.rm.lock:
                        if not self._adc_inited:
                            with self._suppress_stdout():
                                self.adc.ADS1256_init()
                            self._adc_inited = True
                except Exception as e:
                    return self._err_resp(_id, "ads_init_failed", f"ADC init error: {type(e).__name__}: {e}")
                definition = [{
                    "channel": int(params.get("channel", 0)),
                    "differential": bool(params.get("differential", False)),
                    "neg-channel": int(params.get("negChannel", 8)),
                    "buffered": bool(params.get("buffered", False)),
                    "SPS": int(params.get("drate", 10)),
                    "gain": int(params.get("gain", 1))
                }]
                
                # Use getDefined to handle the actual reading under lock to serialize SPI access
                try:
                    with self.rm.lock:
                        with self._suppress_stdout():
                            results = self.adc.ADS1256_GetDefined(definition)
                except TimeoutError as e:
                    return self._err_resp(_id, "timeout", f"ADC timeout: {e}")
                except Exception as e:
                    return self._err_resp(_id, "internal_error", f"ADC read error: {type(e).__name__}: {e}")
                
                # Return in expected format
                if results and len(results) > 0:
                    result = results[0]
                    return {
                        "jsonrpc": "2.0", 
                        "id": _id, 
                        "result": {
                            "channel": result["channel"],
                            "negChannel": result["negChannel"],
                            "differential": result["differential"],
                            "buffered": result["buffered"],
                            "raw": result["raw"],
                            "voltage": result["voltage"],
                            "gain": result["gain"],
                            "drate": result["sps"],
                            "ts": time.time()
                        }
                    }
                else:
                    return self._err_resp(_id, "internal_error", "No result from getDefined")

            if method == "read_adc_defined":
                if self.stream_running:
                    return self._err_resp(_id, "stream_conflict", "read_adc_defined unavailable while streaming is active")
                
                # Use the working ADS1256 GetDefined method under lock
                self._ensure_adc()
                # Ensure GPIO is ready before attempting any ADC operation
                try:
                    self.rm.ensure_gpio_ready()
                except Exception as e:
                    return self._err_resp(_id, "gpio_unavailable", f"GPIO not ready: {e}")
                # Ensure ADC is initialized (idempotent)
                try:
                    with self.rm.lock:
                        if not self._adc_inited:
                            with self._suppress_stdout():
                                self.adc.ADS1256_init()
                            self._adc_inited = True
                except Exception as e:
                    return self._err_resp(_id, "ads_init_failed", f"ADC init error: {type(e).__name__}: {e}")
                definition = params.get("definition", [])
                try:
                    with self.rm.lock:
                        with self._suppress_stdout():
                            results = self.adc.ADS1256_GetDefined(definition)
                except TimeoutError as e:
                    return self._err_resp(_id, "timeout", f"ADC timeout: {e}")
                except Exception as e:
                    return self._err_resp(_id, "internal_error", f"ADC read error: {type(e).__name__}: {e}")
                
                return {"jsonrpc": "2.0", "id": _id, "result": {"channels": results}}

            if method == "start_stream":
                # params: { streamId: str, mode:"round_robin", channels: [{ch, differential, neg, gain, drate, buffered}] }
                p = params
                if not isinstance(p.get("channels"), list) or not p.get("channels"):
                    raise ValueError("channels list required")
                requested_cfg = {
                    "streamId": p.get("streamId") or "default",
                    "channels": p["channels"],
                    "mode": p.get("mode", "round_robin"),
                }
                if self.stream_running:
                    try:
                        # Idempotent: if same config, acknowledge
                        if json.dumps(requested_cfg, sort_keys=True) == json.dumps(self.stream_cfg or {}, sort_keys=True):
                            return {"jsonrpc": "2.0", "id": _id, "result": {"ok": True}}
                    except Exception:
                        pass
                    # Different config: stop current stream and restart
                    self.stream_running = False
                    t = self.stream_thread
                    if t and t.is_alive():
                        t.join(timeout=1.0)
                    self.stream_thread = None
                    self.stream_cfg = None
                # Start with requested config
                self.stream_cfg = requested_cfg
                self.stream_running = True
                self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
                self.stream_thread.start()
                return {"jsonrpc": "2.0", "id": _id, "result": {"ok": True}}

            if method == "stop_stream":
                self.stream_running = False
                t = self.stream_thread
                if t and t.is_alive():
                    t.join(timeout=1.0)
                self.stream_thread = None
                self.stream_cfg = None
                return {"jsonrpc": "2.0", "id": _id, "result": {"ok": True}}

            return self._err_resp(_id, "method_not_found", f"Method not found: {method}")
            
        except Exception as e:
            log.error(f"Request error: {type(e).__name__}: {e}")
            return self._err_resp(_id, "internal_error", f"Unhandled error: {type(e).__name__}: {e}")

    def _notify_stream_sample(self, sample: Dict[str, Any]) -> None:
        # Unsolicited event for stream samples
        msg = {"jsonrpc": "2.0", "method": "stream_sample", "params": sample}
        self._real_stdout.write(json.dumps(msg) + "\n")
        self._real_stdout.flush()

    def _stream_loop(self) -> None:
        cfg = self.stream_cfg or {}
        stream_id = cfg.get("streamId", "default")
        channels = cfg.get("channels", [])
        seq = 0
        # Cache last written register state to avoid redundant writes
        last_cfg: Dict[str, Any] = {"ch": None, "neg": None, "gain": None, "drate": None, "buffered": None, "differential": None}
        # Ensure hardware initialized before streaming
        try:
            self.adc.ADS1256_init()
        except Exception as e:
            self._notify_stream_sample({
                "streamId": stream_id,
                "error": str(e),
                "ts": time.time(),
            })
            return
        while self.stream_running:
            for ch_cfg in channels:
                if not self.stream_running:
                    break
                try:
                    ch = int(ch_cfg.get("ch"))
                    differential = bool(ch_cfg.get("differential", False))
                    neg = int(ch_cfg.get("neg", 8))
                    gain = int(ch_cfg.get("gain", 1))
                    drate = float(ch_cfg.get("drate", 10.0))
                    buffered = bool(ch_cfg.get("buffered", False))

                    # DRDY pacing: prefer gpiod edge if available, else compute dynamic timeout
                    dyn_timeout = max(0.1, (3.0 / float(drate)) + 0.01)
                    if gpiod is not None and self.rm._gpiod_drdy_line is not None:
                        # Wait for falling edge or small timeout to keep responsive
                        ev = self.rm._gpiod_drdy_line.event_wait(timeout=dyn_timeout)
                        if not ev:
                            raise TimeoutError("DRDY edge timeout")

                    # Use getDefined for streaming - simpler and proven to work
                    definition = [{
                        "channel": ch,
                        "differential": differential,
                        "neg-channel": neg if differential else 8,
                        "buffered": buffered,
                        "SPS": drate,
                        "gain": gain
                    }]
                    
                    with self.rm.lock:
                        results = self.adc.ADS1256_GetDefined(definition)
                    if not results or len(results) == 0:
                        raise RuntimeError("No result from getDefined")
                    
                    result = results[0]
                    raw = result["raw"]
                    sample = {
                        "streamId": stream_id,
                        "seq": seq,
                        "channel": ch,
                        "negChannel": None if (not differential) else neg,
                        "differential": differential,
                        "buffered": buffered,
                        "raw": raw,
                        "voltage": result["voltage"],
                        "gain": gain,
                        "drate": drate,
                        "ts": time.time(),
                    }
                    self._notify_stream_sample(sample)
                    seq += 1
                except Exception as e:
                    self._notify_stream_sample({
                        "streamId": stream_id,
                        "error": str(e),
                        "ts": time.time(),
                    })
            # No pacing: stream at DRDY pace
            
    def run(self):
        log.info(f"Worker started; awaiting requests (pid={os.getpid()})")
        while self.running:
            line = sys.stdin.readline()
            if not line:
                log.info("stdin closed; exiting")
                break
            s = line.strip()
            if not s:
                continue
            try:
                req = json.loads(s)
            except json.JSONDecodeError:
                self._write_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue

            self.in_progress.set()
            try:
                resp = self.handle(req)
            finally:
                self.in_progress.clear()

            self._write_response(resp)
                
        self.cleanup()
        
    def cleanup(self):
        log.info("Cleaning up worker resources")
        try:
            # Stop streaming first
            self.stream_running = False
            if self.stream_thread and self.stream_thread.is_alive():
                self.stream_thread.join(timeout=1.0)
            
            # Cleanup ADC pins
            if hasattr(self, 'adc') and self.adc:
                self.adc.ADS1256_cleanup()
            
            # Cleanup SPI/GPIO resources
            self.rm.cleanup()
            
            # Final GPIO cleanup to ensure pins are freed
            GPIO.cleanup()
            
        except Exception as e:
            log.error(f"Cleanup error: {e}")
            # Force cleanup even if errors occur
            try:
                GPIO.cleanup()
            except:
                pass


def main():
    cfg = WorkerConfig()
    w = Worker(cfg)
    try:
        w.run()
    except KeyboardInterrupt:
        log.info("Received keyboard interrupt")
    except Exception as e:
        log.error(f"Worker error: {e}")
    finally:
        log.info("Shutting down worker...")
        w.cleanup()
        # Final cleanup to ensure pins are freed
        try:
            GPIO.cleanup()
        except:
            pass


if __name__ == "__main__":
    main()