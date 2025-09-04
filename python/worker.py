#!/usr/bin/env python3
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
    spi_speed_hz: int = 1_000_000  # match ad.py (1 MHz)

    # Watchdog & timeouts
    idle_shutdown_s: int = 300      # generous; worker stays alive while busy
    request_timeout_s: int = 10     # per-request guard


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
        try:
            try:
                GPIO.cleanup()
            except Exception:
                pass
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
            log.error(f"GPIO init failed: {e}")
            self.gpio_ready = False
            return False

    # Lazily set up SPI on first use
    def _setup_spi(self) -> None:
        if self.spi is not None:
            return
        try:
            s = spidev.SpiDev()
            s.open(self.cfg.spi_bus, self.cfg.spi_dev)
            # Default to ADC-friendly speed; individual ops may override
            s.max_speed_hz = self.cfg.spi_speed_hz
            s.mode = 0b01
            s.lsbfirst = False
            s.cshigh = False
            s.no_cs = True  # we drive CS on GPIO to avoid CE0 auto toggling
            self.spi = s
            log.info(
                f"SPI open bus={self.cfg.spi_bus}, dev={self.cfg.spi_dev}, "
                f"speed={self.cfg.spi_speed_hz}Hz, mode=1, no_cs=True"
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
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
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

    def _wait_drdy(self, timeout_s: float = 10.0) -> bool:
        if not self.rm._setup_gpio():
            raise RuntimeError("GPIO unavailable")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if GPIO.input(self.cfg.adc_drdy_pin) == GPIO.LOW:
                return True
            time.sleep(0.001)
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
        # 6) Self-calibrate after config changes for offset/gain
        self._write_cmd(0xF0)  # SELFCAL
        if not self._wait_drdy(timeout_s=2.0):
            log.warning("SELFCAL DRDY timeout")

    def read_channel(self, channel: int, *, gain: int = 1, drate: float = 10.0,
                     differential: bool = False, neg_channel: int = 8,
                     buffered: bool = False) -> Dict[str, Any]:
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
        
        ADC_VREF = 2.5  # fixed by HAT

        # init once
        self._ensure_init()

        with self.rm.lock:
            # configure registers
            self._configure(channel, gain, buffered, drate, differential, neg_channel)

            # initial DRDY
            log.info("Waiting initial DRDY...")
            if not self._wait_drdy(timeout_s=10.0):
                raise TimeoutError("initial DRDY timeout")

            # SYNC/WAKEUP (kick conversion)
            log.info("SYNC/WAKEUP")
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_SYNC])
                time.sleep(0.0002)
                self.rm.spi.writebytes([self.CMD_WAKEUP])
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

            # wait for DRDY, then discard first conversion
            log.info("Discarding first conversion...")
            if not self._wait_drdy(timeout_s=10.0):
                raise TimeoutError("discard DRDY timeout")
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_RDATA])
                time.sleep(0.01)
                _ = self.rm.spi.readbytes(3)  # discard
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

            # wait for DRDY again for the valid conversion
            log.info("Waiting for valid conversion DRDY...")
            if not self._wait_drdy(timeout_s=10.0):
                raise TimeoutError("valid conversion DRDY timeout")

            # now read the valid result
            log.info("RDATA + readbytes(3)")
            GPIO.output(self.cfg.adc_cs_pin, GPIO.LOW)
            try:
                self.rm.spi.writebytes([self.CMD_RDATA])
                time.sleep(0.01)
                data = self.rm.spi.readbytes(3)
            finally:
                GPIO.output(self.cfg.adc_cs_pin, GPIO.HIGH)

        if len(data) != 3:
            raise RuntimeError(f"expected 3 bytes, got {len(data)}")
                
        raw = (data[0] << 16) | (data[1] << 8) | data[2]
        if raw & 0x800000:
            raw -= 0x1000000  # signed 24-bit
            
        voltage = (float(raw) * 2 * ADC_VREF / (float(gain) * 0x7FFFFF))    
        voltage_mv = voltage * 1000
        log.info(f"ADC raw={raw}, mv={voltage_mv:.3f}")
        return {
            "channel": channel,
            "negChannel": None if (not differential) else neg_channel,
            "differential": differential,
            "buffered": buffered,
            "raw": raw,
            "voltage_mv": float(f"{voltage_mv:.3f}"),
            "voltage" : float(f"{voltage:.5f})"),
            "gain": gain,
            "drate": drate,
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

            raise ValueError("Method not found")
            
        except Exception as e:
            log.error(f"Request error: {e}")
            return {"jsonrpc": "2.0", "id": _id, "error": {"code": -32000, "message": str(e)}}
            
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
