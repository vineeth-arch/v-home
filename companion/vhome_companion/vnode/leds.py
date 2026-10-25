"""Wi-Fi signal bars on the pHAT BEAT's APA102 LEDs. Run as: python3 -m vhome_companion.vnode.leds

Separate process from the VNode API: if it dies or the board is missing, nothing else is affected.
The DAC/amp of the pHAT BEAT is never touched (no overlay, no audio); only two GPIO lines are bit-banged:
data GPIO23, clock GPIO24 (Pimoroni phatbeat library). gpiod (v2 API, python3-libgpiod) is imported lazily so
the pure parts import and test anywhere.
"""
import datetime
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from . import contracts

log = logging.getLogger("vhome.leds")

EX_CONFIG = 78                  # no board / no gpiod: systemd must not restart-loop (RestartPreventExitStatus=78)
GPIO_CHIP = "/dev/gpiochip0"
PIN_DATA, PIN_CLOCK = 23, 24
NUM_LEDS = 16                   # 2 x 8 APA102 on the pHAT BEAT
MAX_BRIGHTNESS = 4              # hard cap of the APA102 global brightness (0..31), whatever the config says
DEFAULT_CONFIG = {"enabled": True, "brightness": 2}
LOOP_S = 10.0
THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"
HWMON_GLOB = "/sys/class/hwmon/hwmon*"   # the dir whose `name` is rpi_volt has in0_lcrit_alarm (1 = under-voltage now)
WIRELESS_PATH = "/proc/net/wireless"
THROTTLE_NOW_MASK = 0xF         # bits 0..3 = under-voltage / freq-capped / throttled / soft temp limit, right now

GREEN, AMBER, RED = (0, 40, 0), (40, 20, 0), (40, 0, 0)   # (r, g, b); dim on purpose, brightness is low too


# ---- pure parts ------------------------------------------------------------------------

def rssi_dbm(text):
    """Signal level (dBm) of wlan0 from /proc/net/wireless text, or None.
    Line: ' wlan0: 0000   41.  -69.  -256 ...' -> fields: iface status link level noise."""
    for line in str(text).splitlines():
        iface, sep, rest = line.partition(":")
        if sep and iface.strip() == "wlan0":
            parts = rest.split()
            if len(parts) >= 3:
                try:
                    return int(float(parts[2]))
                except ValueError:
                    return None
    return None


def bars(dbm):
    if dbm is None:
        return 0
    for floor, n in ((-55, 4), (-65, 3), (-75, 2), (-85, 1)):
        if dbm >= floor:
            return n
    return 0


def colour(n):
    return GREEN if n >= 3 else AMBER if n == 2 else RED


def clamp_brightness(value):
    return max(0, min(int(value), MAX_BRIGHTNESS))


def frame(pixels, brightness):
    """APA102 bytes: start frame, one (0xE0|brightness, B, G, R) per pixel, end frame (40 clock pulses > 16 LEDs)."""
    b = 0xE0 | clamp_brightness(brightness)
    out = bytearray(4)
    for r, g, bl in pixels:
        out += bytes((b, bl, g, r))
    out += bytes(5)
    return bytes(out)


def render(n_bars, enabled, thermal_off, brightness):
    """Whole-strip frame: the first n_bars LEDs in one colour, everything else off."""
    pixels = [(0, 0, 0)] * NUM_LEDS
    if enabled and not thermal_off and n_bars > 0:
        pixels = [colour(n_bars) if i < n_bars else (0, 0, 0) for i in range(NUM_LEDS)]
    return frame(pixels, brightness)


def parse_config(text):
    """leds.json -> {"enabled": bool, "brightness": 1..MAX}. Missing / corrupt -> defaults, never an exception."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if isinstance(data.get("enabled"), bool):
                cfg["enabled"] = data["enabled"]
            b = data.get("brightness")
            if isinstance(b, int) and not isinstance(b, bool):
                cfg["brightness"] = max(1, min(b, MAX_BRIGHTNESS))
    except (ValueError, TypeError):
        pass
    return cfg


class ThermalGuard:
    """LEDs off at >= off_at C or while any throttle bit 0..3 is set; back on only below on_below C with those clear."""

    def __init__(self, off_at=70.0, on_below=60.0):
        self.off_at, self.on_below, self.allowed = off_at, on_below, True

    def update(self, temp_c, throttled_hex):
        try:
            bits = int(str(throttled_hex), 16) if throttled_hex is not None else 0
        except ValueError:
            bits = 0
        throttled_now = bool(bits & THROTTLE_NOW_MASK)
        if throttled_now or (temp_c is not None and temp_c >= self.off_at):
            self.allowed = False
        elif temp_c is not None and temp_c < self.on_below:
            self.allowed = True
        return self.allowed


# ---- hardware --------------------------------------------------------------------------

class Apa102:
    """Bit-bangs bytes out through set_pin(pin, 0|1). The injectable setter keeps tests off the hardware."""

    def __init__(self, set_pin):
        self.set_pin = set_pin

    def write(self, data):
        for byte in data:
            for i in range(7, -1, -1):
                self.set_pin(PIN_DATA, (byte >> i) & 1)
                self.set_pin(PIN_CLOCK, 1)
                self.set_pin(PIN_CLOCK, 0)


class GpiodPins:
    """The two output lines through the libgpiod v2 Python API."""

    def __init__(self):
        import gpiod  # lazy: python3-libgpiod is only on the Pi
        from gpiod.line import Direction, Value
        self._value = {0: Value.INACTIVE, 1: Value.ACTIVE}
        self._req = gpiod.request_lines(
            GPIO_CHIP, consumer="vhome-leds",
            config={(PIN_DATA, PIN_CLOCK): gpiod.LineSettings(direction=Direction.OUTPUT,
                                                              output_value=Value.INACTIVE)})

    def set(self, pin, value):
        self._req.set_value(pin, self._value[value])

    def close(self):
        self._req.release()


# ---- readers ---------------------------------------------------------------------------

def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def read_temp(path=THERMAL_PATH):
    raw = _read(path)
    try:
        return int(raw) / 1000.0
    except (TypeError, ValueError):
        return None


def read_throttled(hwmon_glob=HWMON_GLOB):
    """Throttle flags as hex text, like vcgencmd: "0x1" = under-voltage now, "0x0" = fine, None = no rpi_volt hwmon.
    (get_throttled in /sys does not exist on current kernels; vcgencmd needs /dev/vchiq, hidden by the sandbox.)"""
    import glob
    for d in sorted(glob.glob(hwmon_glob)):
        if _read(os.path.join(d, "name")) == "rpi_volt":
            alarm = _read(os.path.join(d, "in0_lcrit_alarm"))
            if alarm in ("0", "1"):
                return "0x1" if alarm == "1" else "0x0"
    return None


# ---- service ---------------------------------------------------------------------------

def _state_dir():
    if os.environ.get("VHOME_COMPANION_DIR"):
        return Path(os.environ["VHOME_COMPANION_DIR"])
    if os.environ.get("STATE_DIRECTORY"):
        return Path(os.environ["STATE_DIRECTORY"].split(":")[0])
    from ..cli import default_state_dir  # heavy import, only as a last resort
    return default_state_dir()


class LedService:
    def __init__(self, driver, state_dir, state_file=contracts.LED_STATE_FILE, wireless_path=WIRELESS_PATH,
                 temp_reader=read_temp, throttled_reader=read_throttled, guard=None):
        self.driver = driver
        self.config_path = Path(state_dir) / contracts.LED_CONFIG_FILE
        self.state_file = Path(state_file)
        self.wireless_path = wireless_path
        self.temp_reader, self.throttled_reader = temp_reader, throttled_reader
        self.guard = guard or ThermalGuard()
        self.last_frame = None

    def _config(self):
        try:
            return parse_config(self.config_path.read_text())
        except OSError:
            return dict(DEFAULT_CONFIG)

    def step(self):
        cfg = self._config()
        dbm = rssi_dbm(_read(self.wireless_path) or "")
        n = bars(dbm)
        temp = self.temp_reader()
        allowed = self.guard.update(temp, self.throttled_reader())
        data = render(n, cfg["enabled"], not allowed, cfg["brightness"])
        if data != self.last_frame:          # APA102 holds its colour; write only on change
            self.last_frame = None
            self.driver.write(data)
            self.last_frame = data
        self._publish({"enabled": cfg["enabled"], "brightness": cfg["brightness"], "bars": n, "dbm": dbm,
                       "thermal_off": not allowed, "temp_c": temp,
                       "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})

    def _publish(self, state):
        tmp = self.state_file.with_name(self.state_file.name + ".tmp")   # tmpfs: no fsync needed
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o644)
            json.dump(state, f)
        os.replace(tmp, self.state_file)

    def all_off(self):
        self.driver.write(render(0, False, False, 0))

    def run(self, stop, period=LOOP_S):
        while not stop.is_set():
            try:
                self.step()
            except Exception as e:  # noqa: BLE001 - keep the loop alive, retry next cycle
                log.warning("led step failed: %s", e)
            stop.wait(period)
        try:
            self.all_off()
        except Exception as e:  # noqa: BLE001
            log.warning("could not clear LEDs on exit: %s", e)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    try:
        pins = GpiodPins()
    except (ImportError, OSError) as e:
        log.error("LED output unavailable (%s: %s); exiting 78 (no restart)", type(e).__name__, e)
        return EX_CONFIG
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        LedService(Apa102(pins.set), _state_dir()).run(stop)
    finally:
        pins.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
