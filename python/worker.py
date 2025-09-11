# @version @jpadie/waveshare-da-ad-hat v1.0.54 2025-09-11T10:04:12.611Z commit 68b7dbb

"""
Waveshare DA-AD HAT Worker (JSON-RPC over stdio)
- ADC (ADS1256) flow aligned to the working one-shot ad.py paradigm
- Robust watchdog (doesn't kill mid-request), per-request timeout, clear stdout replies
- Manual GPIO CS with spidev.no_cs=True to avoid kernel CE contention
"""

from __future__ import annotations

import json
import sys
import time
import logging
import signal
import threading
import os
import types
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

try:
    import spidev
    import RPi.GPIO as GPIO
except Exception:  # Allow local dev on non-RPi hosts with mocks
    if os.environ.get("WS_MOCK_GPIO") == "1":
        class _MockSpiDev:
            def __init__(self):
                self.max_speed_hz = 0
                self.mode = 0
                self.lsbfirst = False
                self.cshigh = False
                self.no_cs = False
            def open(self, bus, dev):
                pass
            def writebytes(self, arr):
                pass
            def readbytes(self, n):
                return [0] * n
            def close(self):
                pass

        spidev = types.SimpleNamespace(SpiDev=_MockSpiDev)

        class _MockGPIO:
            BCM = 11
            OUT = 1
            IN = 0
            HIGH = 1
            LOW = 0
            PUD_UP = 2
            def setmode(self, *_a, **_kw):
                pass
            def setwarnings(self, *_a, **_kw):
                pass
            def setup(self, *_a, **_kw):
                pass
            def output(self, *_a, **_kw):
                pass
            def input(self, *_a, **_kw):
                return 0
            def cleanup(self, *_a, **_kw):
                pass

        GPIO = _MockGPIO()
    else:
        raise

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

    # Lazily set up GPIO on first use
    def _setup_gpio(self) -> bool:
        if self.gpio_ready:
            return True
        attempts = max(1, int(self.cfg.gpio_init_retries))
        for attempt in range(1, attempts + 1):
            try:
                try:
                    GPIO.cleanup()
                except Exception:
                    pass
                time.sleep(self.cfg.gpio_retry_delay_s)
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)

                # ADC pins
                GPIO.setup(self.cfg.adc_cs_pin, GPIO.OUT, initial=GPIO.HIGH)
                GPIO.setup(self.cfg.adc_rst_pin, GPIO.OUT, initial=GPIO.HIGH)
                GPIO.setup(self.cfg.adc_drdy_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                # DAC pin
                GPIO.setup(self.cfg.dac_cs_pin, GPIO.OUT, initial=GPIO.HIGH)

                self.gpio_ready = True
                log.info(
                    f"GPIO init OK (ADC_CS={self.cfg.adc_cs_pin}, ADC_RST={self.cfg.adc_rst_pin}, "
                    f"DRDY={self.cfg.adc_drdy_pin}, DAC_CS={self.cfg.dac_cs_pin})"
                )
                return True
            except Exception as e:
                log.warning(f"GPIO init attempt {attempt}/{attempts} failed: {e}")
                self.gpio_ready = False
        log.error("GPIO init failed after retries")
        return False

    def ensure_gpio_ready(self) -> None:
        """Ensure GPIO is initialized, with a forced cleanup+retry before failing."""
        if self._setup_gpio():
            return
        # one forced cleanup and final attempt
        try:
            GPIO.cleanup()
        except Exception:
            pass
        time.sleep(self.cfg.gpio_retry_delay_s)
        if not self._setup_gpio():
            raise RuntimeError("GPIO unavailable after retries")

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
            if self.spi is not None:
                try:
                    self.spi.close()
                except Exception:
                    pass
                self.spi = None
            if self.gpio_ready:
                try:
                    GPIO.cleanup()
                except Exception:
                    pass
                self.gpio_ready = False
            log.info("SPI/GPIO cleaned up")


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

    def set_voltage(self, port: int, voltage: float, vref: float = 3.3) -> Dict[str, Any]:
        if not (0.0 <= voltage <= vref):
            raise ValueError(f"voltage must be 0..{vref}V")
        value = int(round((voltage / vref) * 65535))
        out = self.set_value(port, value)
        out["voltage_mv"] = int(voltage * 1000)
        out["vref"] = vref
        return out


class ADS1256:
    # Commands
    CMD_SDATAC = 0x0F
    CMD_RDATA  = 0x01
    CMD_WREG   = 0x50
    CMD_RREG   = 0x10
    CMD_SYNC   = 0xFC
    CMD_WAKEUP = 0x00

    # Registers
    REG_STATUS = 0x00
    REG_MUX    = 0x01
    REG_ADCON  = 0x02
    REG_DRATE  = 0x03

    DRATE_VALUES = {
        2.5: 0x03, 5: 0x13, 10: 0x20, 15: 0x33, 25: 0x43, 30: 0x53, 50: 0x63,
        60: 0x72, 100: 0x82, 500: 0x92, 1000: 0xA1, 2000: 0xB0, 3750: 0xC0,
        7500: 0xD0, 15000: 0xE0, 30000: 0xF0,
    }
    GAIN_VALUES = {1:0x00, 2:0x01, 4:0x02, 8:0x03, 16:0x04, 32:0x05, 64:0x06}

    # Optional alpha/beta lookup from datasheet Table 18 (user-provided values).
    # Key: (drate_sps: float, gain: int, buffered: int, differential: int) -> (alpha_mv_per_code: float, beta_mv: float)
    # If no entry is found, a mathematically derived default is used.
    ALPHA_BETA_TABLE: Dict[Tuple[float, int, int, int], Tuple[float, float]] = {}

    def __init__(self, rm: SPIResourceManager, cfg: WorkerConfig):
        self.rm = rm
        self.cfg = cfg
        self.initialized = False

    def _write_cmd(self, cmd: int) -> None:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
        try:
            self.rm.spi.writebytes([cmd])
            time.sleep(0.0002)
        finally:
            GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

    def _write_reg(self, reg: int, val: int) -> None:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
        try:
            self.rm.spi.writebytes([self.CMD_WREG | (reg & 0x0F), 0x00, val & 0xFF])
            time.sleep(0.0002)
        finally:
            GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

    def _read_reg(self, reg: int) -> int:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
        try:
            # RREG command: 0x10 | reg, then count-1 (0 for one byte), then read one byte
            self.rm.spi.writebytes([self.CMD_RREG | (reg & 0x0F), 0x00])
            time.sleep(0.0002)
            data = self.rm.spi.readbytes(1)
            if not data or len(data) != 1:
                raise RuntimeError("RREG read failed")
            return data[0] & 0xFF
        finally:
            GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

    def _wait_drdy(self, timeout_s: float = 10.0) -> bool:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if GPIO.input(self.cfg.adc_drdy_pin) == GPIO.LOW:
                return True
            time.sleep(0.0005)
        return False

    def _reset(self) -> None:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        # Align with the working ad.py timing (100 ms pulses)
        GPIO.output(self.cfg.adc_rst_pin, GPIO.LOW)
        time.sleep(0.1)
        GPIO.output(self.cfg.adc_rst_pin, GPIO.HIGH)
        time.sleep(0.1)

    def _ensure_init(self) -> None:
        if self.initialized:
            return
        with self.rm.lock:
            self.rm._setup_gpio()
            self.rm._setup_spi()
            self._reset()
            self.initialized = True
            log.info("ADS1256 initialized")

    def _configure(self, channel: int, gain: int, buffered: bool, drate: float,
                   differential: bool, neg_channel: int) -> None:
        # 1) Leave any continuous mode (critical)
        self._write_cmd(self.CMD_SDATAC)
        # 2) STATUS: enable AUTOCAL (ACAL=1). Buffer bit per request.
        # ACAL bit assumed at 0x04 per ADS1256 datasheet; BUFEN bit at 0x02.
        status_val = 0x04 | (0x02 if buffered else 0x00)
        self._write_reg(self.REG_STATUS, status_val)
        # 3) MUX selection (AINp = channel, AINn = neg or AINCOM=8)
        ain_n = neg_channel if differential else 0x08
        mux = ((channel & 0x0F) << 4) | (ain_n & 0x0F)
        self._write_reg(self.REG_MUX, mux)
        # 4) ADCON gain (clock bits default)
        if gain not in self.GAIN_VALUES:
            raise ValueError("Invalid gain")
        self._write_reg(self.REG_ADCON, self.GAIN_VALUES[gain])
        # 5) DRATE
        if drate not in self.DRATE_VALUES:
            raise ValueError("Invalid data rate")
        self._write_reg(self.REG_DRATE, self.DRATE_VALUES[drate])
        log.info(f"ADC cfg: CH={channel}, NEG={'AINCOM' if not differential else neg_channel}, "
                 f"GAIN={gain}, BUF={buffered}, DRATE={drate}SPS")
        # Note: AUTOCAL (ACAL) is enabled in STATUS; skip manual SELFCAL here

    def read_channel(self, channel: int, *, gain: int = 1, drate: float = 10.0,
                     differential: bool = False, neg_channel: int = 8,
                     buffered: bool = False, debugStatusReadback: bool = False) -> Dict[str, Any]:
        """Read a single conversion from the specified ADC channel.
        Performs a configuration step, discards the first conversion after SYNC/WAKEUP,
        then returns the next valid conversion result.
        """

        if not (0 <= channel <= 7):
            raise ValueError("channel 0..7")
        if differential:
            if not (0 <= neg_channel <= 7):
                raise ValueError("neg_channel 0..7 in differential mode")
            if neg_channel == channel:
                raise ValueError("pos and neg must differ")

        # init once
        self._ensure_init()

        with self.rm.lock:
            # configure registers
            self._configure(channel, gain, buffered, drate, differential, neg_channel)

            status_reg_val: Optional[int] = None
            if debugStatusReadback:
                try:
                    status_reg_val = self._read_reg(self.REG_STATUS)
                    log.info(f"STATUS readback: 0x{status_reg_val:02X} (BUFEN={(status_reg_val>>1)&1}, ACAL={(status_reg_val>>2)&1})")
                except Exception as e:
                    log.warning(f"STATUS readback failed: {e}")

            # initial DRDY (timeout derived from drate)
            dyn_timeout = max(0.1, (3.0 / float(drate)) + 0.01)
            if not self._wait_drdy(timeout_s=dyn_timeout):
                raise TimeoutError("initial DRDY timeout")

            # SYNC/WAKEUP (kick conversion)
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_SYNC])
                time.sleep(0.0002)
                self.rm.spi.writebytes([self.CMD_WAKEUP])
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

            # wait for DRDY, then discard first conversion
            if not self._wait_drdy(timeout_s=dyn_timeout):
                raise TimeoutError("discard DRDY timeout")
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_RDATA])
                _ = self.rm.spi.readbytes(3)  # discard
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

            # wait for DRDY again for the valid conversion
            if not self._wait_drdy(timeout_s=dyn_timeout):
                raise TimeoutError("valid conversion DRDY timeout")

            # now read the valid result
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_RDATA])
                data = self.rm.spi.readbytes(3)
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

        if len(data) != 3:
            raise RuntimeError(f"expected 3 bytes, got {len(data)}")
                
        raw = (data[0] << 16) | (data[1] << 8) | data[2]
        if raw & 0x800000:
            raw -= 0x1000000  # signed 24-bit
            
        # Raw-only payload; conversion moved to Node worker
        return {
            "channel": channel,
            "negChannel": None if (not differential) else neg_channel,
            "differential": differential,
            "buffered": buffered,
            "raw": raw,
            "gain": gain,
            "drate": drate,
            "ts": time.time(),
            **({"statusReg": status_reg_val} if debugStatusReadback and (status_reg_val is not None) else {}),
        }



# -----------------------------
# Worker (JSON-RPC stdio)
# -----------------------------
class Worker:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.rm = SPIResourceManager(cfg)
        self.dac = DAC8532(self.rm, cfg)
        self.adc = ADS1256(self.rm, cfg)

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
        
    def _sig(self, signum, _frame):
        log.info(f"Signal {signum}; shutting down")
        self.running = False
        
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
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    def handle(self, req: Dict[str, Any]) -> Dict[str, Any]:
        self._tick()
        method = req.get("method")
        params = req.get("params") or {}
        _id = req.get("id")

        try:
            if method == "ping":
                return {"jsonrpc": "2.0", "id": _id, "result": {"status": "ok", "ts": time.time()}}
            
            if method == "set_dac_value":
                ret = self.dac.set_value(int(params["port"]), int(params["value"]))
                return {"jsonrpc": "2.0", "id": _id, "result": ret}

            if method == "set_dac_voltage":
                ret = self.dac.set_voltage(int(params["port"]), float(params["voltage"]), float(params.get("vref", 3.3)))
                return {"jsonrpc": "2.0", "id": _id, "result": ret}

            if method == "read_adc":
                if self.stream_running:
                    raise RuntimeError("read_adc unavailable while streaming is active")
                ch = int(params["channel"])  # required
                ret, err = self._with_timeout(
                    self.adc.read_channel,
                    min(self.cfg.request_timeout_s, 15),  # guard but allow ADC work
                    ch,
                    gain=int(params.get("gain", 1)),
                    drate=float(params.get("drate", 10.0)),
                    differential=bool(params.get("differential", False)),
                    neg_channel=int(params.get("negChannel", 8)),
                    buffered=bool(params.get("buffered", False)),
                )
                if err:
                    raise err
                return {"jsonrpc": "2.0", "id": _id, "result": ret}

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

            raise ValueError("Method not found")
            
        except Exception as e:
            log.error(f"Request error: {e}")
            return {"jsonrpc": "2.0", "id": _id, "error": {"code": -32000, "message": str(e)}}

    def _notify_stream_sample(self, sample: Dict[str, Any]) -> None:
        # Unsolicited event for stream samples
        msg = {"jsonrpc": "2.0", "method": "stream_sample", "params": sample}
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def _stream_loop(self) -> None:
        cfg = self.stream_cfg or {}
        stream_id = cfg.get("streamId", "default")
        channels = cfg.get("channels", [])
        seq = 0
        # Cache last written register state to avoid redundant writes
        last_cfg: Dict[str, Any] = {"ch": None, "neg": None, "gain": None, "drate": None, "buffered": None, "differential": None}
        # Ensure hardware initialized before streaming
        try:
            self.adc._ensure_init()
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

                    # dynamic timeout from drate
                    dyn_timeout = max(0.1, (3.0 / float(drate)) + 0.01)

                    # Configure only when changed (reduces bus traffic)
                    if not (
                        last_cfg["ch"] == ch and
                        last_cfg["neg"] == (neg if differential else 8) and
                        last_cfg["gain"] == gain and
                        last_cfg["drate"] == drate and
                        last_cfg["buffered"] == buffered and
                        last_cfg["differential"] == differential
                    ):
                        with self.rm.lock:
                            self.adc._configure(ch, gain, buffered, drate, differential, neg)
                            last_cfg = {
                                "ch": ch,
                                "neg": neg if differential else 8,
                                "gain": gain,
                                "drate": drate,
                                "buffered": buffered,
                                "differential": differential,
                            }

                    status_reg_val = None
                    if bool(ch_cfg.get("debugStatus", False)):
                        try:
                            status_reg_val = self.adc._read_reg(self.adc.REG_STATUS)
                            log.info(f"[stream {stream_id}] STATUS=0x{status_reg_val:02X} BUFEN={(status_reg_val>>1)&1} ACAL={(status_reg_val>>2)&1}")
                        except Exception as e:
                            log.warning(f"[stream {stream_id}] STATUS readback failed: {e}")

                    # initial DRDY and SYNC/WAKEUP
                    if not self.adc._wait_drdy(timeout_s=dyn_timeout):
                        raise TimeoutError("initial DRDY timeout")
                    with self.rm.lock:
                        GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.LOW)
                        try:
                            self.rm.spi.writebytes([self.adc.CMD_SYNC])
                            time.sleep(0.0002)
                            self.rm.spi.writebytes([self.adc.CMD_WAKEUP])
                        finally:
                            GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.HIGH)

                    # Discard first conversion
                    if not self.adc._wait_drdy(timeout_s=dyn_timeout):
                        raise TimeoutError("discard DRDY timeout")
                    with self.rm.lock:
                        GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.LOW)
                        try:
                            self.rm.spi.writebytes([self.adc.CMD_RDATA])
                            _ = self.rm.spi.readbytes(3)
                        finally:
                            GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.HIGH)

                    # Valid conversion
                    if not self.adc._wait_drdy(timeout_s=dyn_timeout):
                        raise TimeoutError("valid conversion DRDY timeout")
                    with self.rm.lock:
                        GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.LOW)
                        try:
                            self.rm.spi.writebytes([self.adc.CMD_RDATA])
                            data = self.rm.spi.readbytes(3)
                        finally:
                            GPIO.output(self.adc.cfg.adc_cs_pin, GPIO.HIGH)

                    if len(data) != 3:
                        raise RuntimeError("expected 3 bytes")
                    raw = (data[0] << 16) | (data[1] << 8) | data[2]
                    if raw & 0x800000:
                        raw -= 0x1000000
                    sample = {
                        "streamId": stream_id,
                        "seq": seq,
                        "channel": ch,
                        "negChannel": None if (not differential) else neg,
                        "differential": differential,
                        "buffered": buffered,
                        "raw": raw,
                        "gain": gain,
                        "drate": drate,
                        "ts": time.time(),
                    }
                    if status_reg_val is not None:
                        sample["statusReg"] = status_reg_val
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
        log.info("Worker started; awaiting requests")
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
        self.rm.cleanup()


def main():
    cfg = WorkerConfig()
    w = Worker(cfg)
    try:
        w.run()
    finally:
        w.cleanup()


if __name__ == "__main__":
    main()
