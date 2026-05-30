import os
import sys
import configparser
import json
import socket
import time
import threading
import queue
import asyncio
import subprocess
import re
from collections import defaultdict

try:
    import winreg
except ImportError:
    winreg = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.add_dll_directory(SCRIPT_DIR)

import hid
import websockets
import clr
import System
from System import Byte, Array, Int32


# ============================================================
# Version / debug
# ============================================================

VERSION = "0.996"
DEBUG = False


# ============================================================
# Paths / config
# ============================================================

CONFIG_FILE = os.path.join(SCRIPT_DIR, "psx_pfp7.ini")


# ============================================================
# HID / timing
# ============================================================

READ_SIZE = 64
BYTE_LIMIT = 17

# Active CDU can be changed at runtime from the scratchpad:
#   CDU-L = Left CDU
#   CDU-C = Center CDU
#   CDU-R = Right CDU
DEFAULT_CDU = "L"

CDU_CONFIGS = {
    "L": {
        "label": "Left",
        "key_qh": "Qh401",
        "screen_qs_lines": list(range(62, 76)),
        "lights_qi": 86,
        "lcd_qi248_bit": 1 << 19,
    },
    "C": {
        "label": "Center",
        "key_qh": "Qh402",
        "screen_qs_lines": list(range(76, 90)),
        "lights_qi": 87,
        "lcd_qi248_bit": 1 << 21,
    },
    "R": {
        "label": "Right",
        "key_qh": "Qh403",
        "screen_qs_lines": list(range(90, 104)),
        "lights_qi": 88,
        "lcd_qi248_bit": 1 << 20,
    },
}

MIN_SEND_INTERVAL = 0.03
STABLE_FRAMES = 2
RISING_COOLDOWN = 0.20

# ============================================================
# MobiFlight / runtime defaults
# ============================================================

MOBIFLIGHT_WS = "ws://localhost:8320/winwing/cdu-captain"

DEFAULT_CDU_COLOR = "w"
DEFAULT_CDU_ATC_ALTN = 1  # 1 = replace ATC key, 0 = keep original ATC key
CDU_ATC_ALTN_SEQUENCE = [65, 42] #Key sequence FMC COMM + LSK2 Left > opens ALTN Page

CDU_SWITCH_CLEAR_SEQUENCE = [39, -1]


class RuntimeConfig:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_cdu = DEFAULT_CDU
        self.cdu_color = DEFAULT_CDU_COLOR
        self.cdu_atc_altn = DEFAULT_CDU_ATC_ALTN
        self.mode = "DEFAULT"

    def set_ng(self):
        with self.lock:
            self.cdu_color = "w"
            self.cdu_atc_altn = 1
            self.mode = "FMC_NG"

    def set_legacy(self):
        with self.lock:
            self.cdu_color = "g"
            self.cdu_atc_altn = 0
            self.mode = "FMC_LEGACY"

    def set_active_cdu(self, cdu):
        cdu = cdu.upper()

        if cdu not in CDU_CONFIGS:
            return False

        with self.lock:
            self.active_cdu = cdu

        return True

    def get_active_cdu(self):
        with self.lock:
            return self.active_cdu

    def get_active_cdu_config(self):
        with self.lock:
            return CDU_CONFIGS[self.active_cdu]

    def set_from_qi248(self, nextgen_fmc, cdu_lcd):
        with self.lock:
            self.cdu_color = "w" if cdu_lcd else "g"
            self.cdu_atc_altn = 1 if nextgen_fmc else 0

            active_cdu = self.active_cdu

            if nextgen_fmc and cdu_lcd:
                self.mode = f"QI248_{active_cdu}_NG_LCD"
            elif nextgen_fmc:
                self.mode = f"QI248_{active_cdu}_NG_CRT"
            elif cdu_lcd:
                self.mode = f"QI248_{active_cdu}_LEGACY_LCD"
            else:
                self.mode = f"QI248_{active_cdu}_LEGACY_CRT"

    def get_cdu_color(self):
        with self.lock:
            return self.cdu_color

    def get_cdu_atc_altn(self):
        with self.lock:
            return self.cdu_atc_altn

    def get_mode(self):
        with self.lock:
            return self.mode


RUNTIME_CONFIG = RuntimeConfig()

FMC_WIDTH = 24
FMC_HEIGHT = 14

# PSX CDU LCD color strings. Each CDU has 14 Qs lines:
#   Ti, 1s, 1b, 2s, 2b, ... 6s, 6b, Sp
# These map directly to the 14 displayed CDU rows.
CDU_COLOR_QS_START = {
    "L": 500,
    "C": 514,
    "R": 528,
}
CDU_COLOR_QS_RANGE = range(500, 542)

# PSX LCD color codes -> MobiFlight color codes.
# PSX b=blue maps to MobiFlight o=blue.
# PSX y is used as grey background; MobiFlight e is grey.
PSX_TO_MOBIFLIGHT_COLOR = {
    "a": "a",  # amber
    "b": "o",  # blue
    "c": "c",  # cyan
    "g": "g",  # green
    "m": "m",  # magenta
    "r": "r",  # red
    "w": "w",  # white
    "y": "e",  # grey / grey background
}

# PSX CDU light bitmask:
# Left CDU / Captain = Qi86
# Center CDU        = Qi87
# Right CDU / FO    = Qi88
#
# PSX FMC/CDU options bitmask:
# Qi248 bit 13 = Next Gen FMC
# Qi248 bit 19 = Left CDU LCD
# Qi248 bit 21 = Center CDU LCD
# Qi248 bit 20 = Right CDU LCD
PSX_FMC_CONFIG_QI = 248
QI248_NEXTGEN_FMC_BIT = 1 << 13

MDT_ALL_LIGHTS_BIT = 0x2000  # 8192

PSX_LIGHT_BITS_TO_PFP7 = {
    0x0001: "EXEC",
    0x0002: "DSPY",
    0x0004: "FAIL",
    0x0008: "MSG",
    0x0010: "OFST",
}

NEED_RELEASE = {39, 60}  # CLR, ATC require explicit release on hardware key release

# MobiFlight Winwing DLL
DLL_PATH = None
MOBIFLIGHT_PATH = None

# PFP7 captain
PFP7_PRODUCT_ID = 0xBB37
PFP7_DEST = Array[Byte]([0x33, 0xBB])

# PFP7 LED channels discovered by testing:
# 0x03 = DSPY
# 0x04 = FAIL
# 0x05 = MSG
# 0x06 = OFST
# 0x07 = EXEC
PFP7_LEDS = {
    "DSPY": 0x03,
    "FAIL": 0x04,
    "MSG":  0x05,
    "OFST": 0x06,
    "EXEC": 0x07,
}

PFP7_LED_INTENSITY = 255

# PFP7 screen backlight brightness
# Channel 0x01 controls the screen backlight.
# Brightness uses 22 steps mapped from 10 to 255.
PFP7_SCREEN_BACKLIGHT_CHANNEL = 0x01
PFP7_SCREEN_BRIGHTNESS_MIN = 10
PFP7_SCREEN_BRIGHTNESS_MAX = 255
PFP7_SCREEN_BRIGHTNESS_STEPS = 22
PFP7_SCREEN_BRIGHTNESS_DEFAULT_STEP = 16

# Hold behavior for BRT+/BRT-
# One step is applied immediately on press.
# After 0.5s hold, brightness repeats. Full 22-step range takes ~3 seconds.
PFP7_BRT_HOLD_DELAY = 0.5
PFP7_BRT_FULL_RANGE_SECONDS = 3.0
PFP7_BRT_REPEAT_INTERVAL = PFP7_BRT_FULL_RANGE_SECONDS / (PFP7_SCREEN_BRIGHTNESS_STEPS - 1)


def brightness_value_from_step(step):
    step = max(0, min(PFP7_SCREEN_BRIGHTNESS_STEPS - 1, step))

    span = PFP7_SCREEN_BRIGHTNESS_MAX - PFP7_SCREEN_BRIGHTNESS_MIN
    value = PFP7_SCREEN_BRIGHTNESS_MIN + round(
        span * step / (PFP7_SCREEN_BRIGHTNESS_STEPS - 1)
    )

    return max(0, min(255, value))

PSX_NAME_TO_CODE = {
    "LSKL1": 41, "LSKL2": 42, "LSKL3": 43, "LSKL4": 44, "LSKL5": 45, "LSKL6": 46,
    "LSKR1": 51, "LSKR2": 52, "LSKR3": 53, "LSKR4": 54, "LSKR5": 55, "LSKR6": 56,
    "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15, "G": 16, "H": 17, "I": 18, "J": 19,
    "K": 20, "L": 21, "M": 22, "N": 23, "O": 24, "P": 25, "Q": 26, "R": 27, "S": 28, "T": 29,
    "U": 30, "V": 31, "W": 32, "X": 33, "Y": 34, "Z": 35,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "SP": 36, "DEL": 37, "/": 38, "CLR": 39,
    "+/-": 68, "+": 68, ".": 67,
    "INIT": 57, "INITREF": 57, "INIT REF": 57,
    "ROUTE": 58, "DEPARR": 59, "DEP/ARR": 59, "ATC": 60, "VNAV": 61, "FIX": 62,
    "LEGS": 63, "HOLD": 64, "FMC": 65, "PROG": 66,
    "MENU": 47, "NAVRAD": 48, "NAV/RAD": 48, "PREV": 49, "NEXT": 50,
    "EXEC": 40,
}

os.system("cls" if os.name == "nt" else "clear")

class StatusLog:
    def __init__(self):
        self.lock = threading.Lock()

    def header(self):
        print(f"""
===============================================================
            PSX ↔ WinCTRL PFP7 Bridge  v{VERSION}
---------------------------------------------------------------
                   Jamie Janssen © 2026
===============================================================
""", flush=True)

    def start(self):
        self.header()
        self.log("Starting...")

    def log(self, message):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            print(f"{timestamp}  {message}", flush=True)


STATUS = StatusLog()


def log(message):
    STATUS.log(message)


def log_debug(message):
    if DEBUG:
        log(message)


def connect_with_retry(host, port, name, stop_evt=None, retry_delay=5.0):
    while stop_evt is None or not stop_evt.is_set():
        sock = None

        try:
            log(f"[{name}] connecting {host}:{port}...")

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(1.0)

            log(f"[{name}] connected")
            return sock

        except KeyboardInterrupt:
            log(f"[{name}] stopped during connection retry")

            try:
                if sock:
                    sock.close()
            except Exception:
                pass

            raise

        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            log(f"[{name}] not available: {e}")
            log(f"[{name}] retrying in {retry_delay:.0f} seconds...")

            try:
                if sock:
                    sock.close()
            except Exception:
                pass

            end_time = time.time() + retry_delay

            while time.time() < end_time:
                if stop_evt is not None and stop_evt.is_set():
                    return None

                time.sleep(0.1)

    return None


class Pfp7LedController:
    def __init__(self):
        if not os.path.exists(DLL_PATH):
            raise FileNotFoundError(f"MobiFlightWwFcu.dll not found: {DLL_PATH}")

        clr.AddReference(DLL_PATH)

        asm = System.Reflection.Assembly.LoadFile(DLL_PATH)
        sender_type = asm.GetType("MobiFlightWwFcu.WinwingMessageSender")

        if sender_type is None:
            raise RuntimeError("WinwingMessageSender not found in MobiFlightWwFcu.dll")

        self.sender = System.Activator.CreateInstance(
            sender_type,
            Array[System.Object]([Int32(PFP7_PRODUCT_ID)])
        )

        self.lock = threading.Lock()
        self.last_states = {}
        self.screen_brightness_step = PFP7_SCREEN_BRIGHTNESS_DEFAULT_STEP
        self.connected = False

    def start(self):
        with self.lock:
            self.sender.Connect()
            self.sender.SendHeartBeatMessage()
            self.connected = True
            log("[PFP7 LED] connected")

            # Set initial screen backlight brightness
            self._set_screen_brightness_step_unlocked(
                self.screen_brightness_step,
                force=True
            )

            # Ensure all known PFP7 CDU lights start off
            for led_name in PFP7_LEDS:
                self._set_led_unlocked(led_name, False, force=True)

    def stop(self):
        with self.lock:
            try:
                for led_name in PFP7_LEDS:
                    self._set_led_unlocked(led_name, False, force=True)

                self.sender.SendHeartBeatMessage()
                self.sender.Shutdown()

            except Exception as e:
                log(f"[PFP7 LED] shutdown error: {repr(e)}")

    def set_led(self, name, on, intensity=PFP7_LED_INTENSITY):
        name = name.upper()

        if name not in PFP7_LEDS:
            log(f"[PFP7 LED] unknown LED: {name}")
            return

        with self.lock:
            self._set_led_unlocked(name, on, intensity=intensity)

    def change_screen_brightness_step(self, delta):
        with self.lock:
            new_step = self.screen_brightness_step + delta
            self._set_screen_brightness_step_unlocked(new_step)

    def _set_screen_brightness_step_unlocked(self, step, force=False):
        step = max(0, min(PFP7_SCREEN_BRIGHTNESS_STEPS - 1, step))
        value = brightness_value_from_step(step)

        if not force and step == self.screen_brightness_step:
            return

        self.screen_brightness_step = step

        self.sender.SendHeartBeatMessage()
        self.sender.SendLightControlMessage(
            PFP7_DEST,
            Byte(PFP7_SCREEN_BACKLIGHT_CHANNEL),
            Byte(value)
        )

        if force:
            log(
                f"[PFP7 BRT] screen backlight "
                f"step {step + 1}/{PFP7_SCREEN_BRIGHTNESS_STEPS} value={value}"
            )
        else:
            # Screen brightness change logging
            log_debug(
                f"[PFP7 BRT] screen backlight "
                f"step {step + 1}/{PFP7_SCREEN_BRIGHTNESS_STEPS} value={value}"
            )

    def apply_psx_cdu_lights_bitmask(self, state):
        md_t_all = bool(state & MDT_ALL_LIGHTS_BIT)

        with self.lock:
            self.sender.SendHeartBeatMessage()

            for bit, led_name in PSX_LIGHT_BITS_TO_PFP7.items():
                on = md_t_all or bool(state & bit)
                self._set_led_unlocked(led_name, on)

    def _set_led_unlocked(self, name, on, intensity=PFP7_LED_INTENSITY, force=False):
        name = name.upper()
        value = intensity if on else 0

        if not force and self.last_states.get(name) == value:
            return

        self.last_states[name] = value

        self.sender.SendLightControlMessage(
            PFP7_DEST,
            Byte(PFP7_LEDS[name]),
            Byte(value)
        )

        log(f"[PFP7 LED] {name} {'ON' if on else 'OFF'}")



def _strip_uninstall_exe_from_path(uninstall_string):
    """Return the install directory from a Windows UninstallString."""
    if not uninstall_string:
        return None

    s = uninstall_string.strip()

    # Common case: "C:\...\uninstall.exe" or "C:\...\uninstall.exe" /S
    quoted = re.match(r'^\s*"([^"]+)"', s)
    if quoted:
        exe_path = quoted.group(1)
    else:
        # Unquoted fallback: keep up to uninstall.exe if present.
        m = re.search(r'(?i)(.*?uninstall\.exe)', s)
        exe_path = m.group(1) if m else s.split()[0]

    exe_path = exe_path.strip().strip('"')
    install_dir = os.path.dirname(exe_path)

    return install_dir if install_dir else None


def get_mobiflight_path_from_registry():
    """Try to find the MobiFlight install directory via HKCU uninstall registry key."""
    if winreg is None:
        return None

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MobiFlight Connector"
        ) as key:
            uninstall_string, _ = winreg.QueryValueEx(key, "UninstallString")

        install_dir = _strip_uninstall_exe_from_path(uninstall_string)

        # Only validate the directory here.
        # The DLL check happens in load_config(), so a registry directory
        # without MobiFlightWwFcu.dll can still fall back cleanly to the ini path.
        if install_dir and os.path.isdir(install_dir):
            return install_dir

        log_debug(
            f"[MOBIFLIGHT] registry path invalid: {install_dir}"
        )

    except Exception as e:
        log_debug(f"[MOBIFLIGHT] registry lookup failed: {repr(e)}")

    return None


def is_mobiflight_websocket_available(host="127.0.0.1", port=8320, timeout=0.25):
    """Check whether the MobiFlight websocket TCP port is already reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_mobiflight_if_needed(mobiflight_path):
    """Start MobiFlight Connector when its websocket is not reachable yet."""
    if not mobiflight_path:
        return False

    if is_mobiflight_websocket_available():
        log("[MOBIFLIGHT] already running")
        return True

    exe_candidates = [
        os.path.join(mobiflight_path, "MFConnector.exe"),
    ]

    exe_path = next((p for p in exe_candidates if os.path.exists(p)), None)

    if not exe_path:
        log("[MOBIFLIGHT] executable not found; websocket retry will continue")
        for candidate in exe_candidates:
            log_debug(f"[MOBIFLIGHT] checked: {candidate}")
        return False

    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            [exe_path],
            cwd=mobiflight_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        log(f"[MOBIFLIGHT] started: {exe_path}")
        return True

    except Exception as e:
        log(f"[MOBIFLIGHT] failed to start: {repr(e)}")
        return False


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")

    host = cfg.get("PSX", "host", fallback="127.0.0.1").strip()
    port = cfg.getint("PSX", "port", fallback=10747)
    vid = int(cfg.get("FMC", "VID", fallback="0x4098"), 16)
    pid = int(cfg.get("FMC", "PID", fallback="0xBB37"), 16)

    mobiflight_path = get_mobiflight_path_from_registry()

    if mobiflight_path:
        registry_dll_path = os.path.join(mobiflight_path, "MobiFlightWwFcu.dll")

        if os.path.exists(registry_dll_path):
            log(f"[MOBIFLIGHT] install dir from registry: {mobiflight_path}")
        else:
            log(
                "[MOBIFLIGHT] registry path found but "
                "MobiFlightWwFcu.dll missing, falling back to ini"
            )
            mobiflight_path = None

    if not mobiflight_path:
        mobiflight_path = cfg.get("MOBIFLIGHT", "PATH", fallback=None)

        if mobiflight_path:
            mobiflight_path = mobiflight_path.strip().strip('"')
            log(f"[MOBIFLIGHT] install dir from ini: {mobiflight_path}")

    global DLL_PATH, MOBIFLIGHT_PATH
    MOBIFLIGHT_PATH = mobiflight_path
    DLL_PATH = (
        os.path.join(mobiflight_path, "MobiFlightWwFcu.dll")
        if mobiflight_path
        else None
    )

    if not DLL_PATH:
        log("[ERROR] MobiFlight path not configured.")
        log("[ERROR] Registry lookup failed and [MOBIFLIGHT] PATH is missing in psx_pfp7.ini")
        sys.exit(1)

    if not os.path.exists(DLL_PATH):
        log("[ERROR] MobiFlightWwFcu.dll not found.")
        log(f"[ERROR] Expected: {DLL_PATH}")
        log("[ERROR] Registry lookup failed or the registry path is invalid.")
        log("[ERROR] Check the [MOBIFLIGHT] PATH in psx_pfp7.ini")
        log("[ERROR] Example:")
        log(r"[MOBIFLIGHT]")
        log(r"PATH = C:\User\<username>\AppData\Local\MobiFlight\MobiFlight Connector")
        input("\nPress ENTER to exit...")
        sys.exit(1)

    log(f"[CONFIG] PSX {host}:{port}")
    log(f"[CONFIG] FMC VID={hex(vid)} PID={hex(pid)}")
    log(f"[CONFIG] DLL={DLL_PATH}")

    return host, port, vid, pid


BUILTIN_MAP = {
    "2,4": "INIT REF",
    "2,5": "ROUTE",
    "2,6": "DEPARR",
    "2,7": "ATC",
    "3,0": "VNAV",
    "3,3": "FIX",
    "3,4": "LEGS",
    "3,5": "HOLD",
    "3,7": "PROG",
    "4,0": "EXEC",
    "4,1": "MENU",
    "4,3": "PREV",
    "4,4": "NEXT",
    "6,1": "A",
    "6,2": "B",
    "6,3": "C",
    "6,4": "D",
    "6,5": "E",
    "6,6": "F",
    "6,7": "G",
    "7,0": "H",
    "7,1": "I",
    "7,2": "J",
    "7,3": "K",
    "7,4": "L",
    "7,5": "M",
    "7,6": "N",
    "7,7": "O",
    "4,6": "2",
    "4,7": "3",
    "5,0": "4",
    "5,1": "5",
    "5,2": "6",
    "5,3": "7",
    "5,4": "8",
    "5,5": "9",
    "5,6": ".",
    "5,7": "0",
    "8,0": "P",
    "8,1": "Q",
    "8,2": "R",
    "8,3": "S",
    "8,4": "T",
    "8,5": "U",
    "8,6": "V",
    "8,7": "W",
    "9,0": "X",
    "9,1": "Y",
    "9,2": "Z",
    "9,3": "SP",
    "9,4": "DEL",
    "9,5": "/",
    "9,6": "CLR",
    "6,0": "+",
    "1,0": "LSKL1",
    "1,1": "LSKL2",
    "1,2": "LSKL3",
    "1,3": "LSKL4",
    "1,4": "LSKL5",
    "1,5": "LSKL6",
    "1,6": "LSKR1",
    "1,7": "LSKR2",
    "2,0": "LSKR3",
    "2,1": "LSKR4",
    "2,2": "LSKR5",
    "2,3": "LSKR6",
    "3,6": "FMC",
    "4,5": "1",
    "4,2": "NAVRAD",
    "3,2": "BRT+",
    "3,1": "BRT-"
}


def load_map():
    mapping = {}

    for k, v in BUILTIN_MAP.items():
        by, bi = map(int, k.split(","))

        if by < BYTE_LIMIT:
            mapping[(by, bi)] = str(v).strip()

    log(f"[MAP] loaded {len(mapping)} built-in bitpos (<{BYTE_LIMIT})")
    return mapping


def pressed_from_mapping(frame, mapped_bps):
    pressed = set()
    flen = min(len(frame), BYTE_LIMIT)

    for by, bi in mapped_bps:
        if by < flen and (frame[by] & (1 << bi)):
            pressed.add((by, bi))

    return pressed


class MobiFlightSender:
    def __init__(self, url):
        self.url = url
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        self.q.put(None)
        self.thread.join(timeout=1.0)

    def send_lines(self, lines, color_lines=None):
        # Debug: MobiFlight display frame queued
        log_debug("[MOBIFLIGHT] queued display frame")
        self.q.put((lines, color_lines))

    def _thread_main(self):
        asyncio.run(self._async_main())

    async def _async_main(self):
        ws = None

        while not self.stop_evt.is_set():
            try:
                if ws is None:
                    log(f"[MOBIFLIGHT] connecting {self.url}")
                    ws = await websockets.connect(self.url)
                    log("[MOBIFLIGHT] connected")

                try:
                    item = await asyncio.to_thread(self.q.get, True, 0.1)
                except queue.Empty:
                    continue

                if item is None:
                    break

                payload = {
                    "Target": "Display",
                    "Data": self._lines_to_data(item),
                }

                await ws.send(json.dumps(payload, ensure_ascii=False))
                # Debug: MobiFlight display frame sent
                log_debug("[MOBIFLIGHT] display frame sent")

            except Exception as e:
                log(f"[MOBIFLIGHT] error: {repr(e)}")
                try:
                    if ws:
                        await ws.close()
                except Exception:
                    pass
                ws = None
                await asyncio.sleep(1.0)

    def _lines_to_data(self, item):
        data = []
        default_cdu_color = RUNTIME_CONFIG.get_cdu_color()

        # Backwards compatible: item may be only lines, or (lines, color_lines).
        if isinstance(item, tuple):
            lines, color_lines = item
        else:
            lines = item
            color_lines = None

        clean_lines = list(lines)[:FMC_HEIGHT]
        while len(clean_lines) < FMC_HEIGHT:
            clean_lines.append("")

        clean_color_lines = list(color_lines or [])[:FMC_HEIGHT]
        while len(clean_color_lines) < FMC_HEIGHT:
            clean_color_lines.append("")

        for row_index, line in enumerate(clean_lines):
            line = line.rstrip("\r\n")

            text_part = line[:FMC_WIDTH]
            text_part = text_part.ljust(FMC_WIDTH)

            size_part = line[FMC_WIDTH:FMC_WIDTH * 2]

            if size_part:
                last_size = size_part[-1]
                size_part = size_part.ljust(FMC_WIDTH, last_size)
            else:
                # PSX default sizes if no size info exists:
                # title line, six LSK lines, and scratchpad line = large
                if row_index in (0, 2, 4, 6, 8, 10, 12, 13):
                    size_part = "+" * FMC_WIDTH
                else:
                    size_part = "-" * FMC_WIDTH

            color_part = clean_color_lines[row_index].strip()

            if color_part:
                # PSX sends compact color strings. The final color continues
                # across the rest of the row, e.g. mmmmmw = first 5 magenta,
                # remaining characters white.
                last_color = color_part[-1]
                color_part = color_part.ljust(FMC_WIDTH, last_color)
            else:
                color_part = default_cdu_color * FMC_WIDTH

            for ch, size_symbol, psx_color in zip(text_part, size_part, color_part):
                ch = normalize_psx_display_char(ch)

                if ch in ("_", " "):
                    data.append([])
                else:
                    size = 0 if size_symbol == "+" else 1
                    cdu_color = PSX_TO_MOBIFLIGHT_COLOR.get(
                        psx_color.lower(),
                        default_cdu_color
                    )
                    data.append([ch, cdu_color, size])

        while len(data) < FMC_WIDTH * FMC_HEIGHT:
            data.append([])

        return data[:FMC_WIDTH * FMC_HEIGHT]


PSX_CHAR_MAP = {
    "o": "\u00b0",
    "b": "\u2610",
    "l": "\u2190",
    "r": "\u2192",
}

def normalize_psx_display_char(ch):
    return PSX_CHAR_MAP.get(ch, ch)

class PsxSender:
    def __init__(self, host, port, mobiflight, pfp7_leds, min_interval_s=0.03):
        self.host = host
        self.port = port
        self.mobiflight = mobiflight
        self.pfp7_leds = pfp7_leds
        self.min_interval = float(min_interval_s)

        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.sock = None
        self.sock_lock = threading.Lock()
        self.connect_lock = threading.Lock()

        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self.rx_thread = threading.Thread(target=self._rx_drain, daemon=True)

        self.last_send = 0.0
        self.tx_count = 0

        self.rx_buffer = ""

        # Cache all three PSX CDU screens.
        # PSX normally sends Qs62-Qs103 on connect; keeping these values
        # lets us switch CDU screens without using a reload key sequence.
        self.all_fmc_lines = {q: "" for q in range(62, 104)}
        self.all_fmc_color_lines = {q: "" for q in CDU_COLOR_QS_RANGE}
        self.fmc_lines = self.all_fmc_lines
        self.fmc_dirty = False
        self.fmc_timer = None
        self.fmc_lock = threading.Lock()

        self.cdu_lights_state = {}
        self.qi248_state = None

    def _active_config(self):
        return RUNTIME_CONFIG.get_active_cdu_config()

    def _active_qs_lines(self):
        return self._active_config()["screen_qs_lines"]

    def _active_color_qs_lines(self):
        active_cdu = RUNTIME_CONFIG.get_active_cdu()
        start = CDU_COLOR_QS_START[active_cdu]
        return list(range(start, start + FMC_HEIGHT))

    def _active_qh_name(self):
        return self._active_config()["key_qh"]

    def _active_lights_qi(self):
        return self._active_config()["lights_qi"]

    def _reset_fmc_lines_for_active_cdu(self):
        # Kept for compatibility, but no longer clears the screen.
        # The active CDU display is now selected from self.all_fmc_lines.
        self.fmc_lines = self.all_fmc_lines

    def _request_active_cdu_data(self):
        with self.sock_lock:
            s = self.sock

        if not s:
            return

        cfg = self._active_config()

        try:
            for q in cfg["screen_qs_lines"]:
                s.sendall(f"Qs{q}\n".encode("ascii"))

            for q in self._active_color_qs_lines():
                s.sendall(f"Qs{q}\n".encode("ascii"))

            s.sendall(f"Qi{cfg['lights_qi']}\n".encode("ascii"))
            s.sendall(f"Qi{PSX_FMC_CONFIG_QI}\n".encode("ascii"))

            log(
                f"[CONFIG] Active CDU {cfg['label']}: "
                f"{cfg['key_qh']}, Qs{cfg['screen_qs_lines'][0]}-Qs{cfg['screen_qs_lines'][-1]}, "
                f"Qi{cfg['lights_qi']}"
            )

        except Exception as e:
            log(f"[PSX] failed to request active CDU data: {repr(e)}")
            self._close()

    def set_active_cdu(self, cdu):
        cdu = cdu.upper()

        if not RUNTIME_CONFIG.set_active_cdu(cdu):
            return False

        self.cdu_lights_state = {}
        self._request_active_cdu_data()

        # Re-apply the last known Qi248 value for the newly selected CDU.
        # Qi248 itself may not change when switching CDU, but the relevant
        # LCD bit does change:
        #   Left   = bit 19
        #   Center = bit 21
        #   Right  = bit 20
        if self.qi248_state is not None:
            self._apply_qi248_state(self.qi248_state, force_log=True)

        # Immediately draw the newly selected CDU from the cached Qs lines.
        with self.fmc_lock:
            self.fmc_dirty = True

        self._send_fmc_frame()

        return True


    def clear_command_from_source_cdu(self, source_qh_name):
        for code in CDU_SWITCH_CLEAR_SEQUENCE:
            self.send_raw_psx_line(f"{source_qh_name}={code}")
            time.sleep(0.03)

    def start(self):
        self.rx_thread.start()
        self.tx_thread.start()

    def stop(self):
        self.stop_evt.set()
        self.q.put(None)
        self.tx_thread.join(timeout=1.0)
        self.rx_thread.join(timeout=1.0)
        self._close()

    def send_code(self, code):
        self.q.put(code)

    def send_codes(self, codes):
        for code in codes:
            self.q.put(code)

    def send_raw_psx_line(self, line):
        with self.sock_lock:
            s = self.sock

        if not s:
            return False

        if not line.endswith("\n"):
            line += "\n"

        try:
            s.sendall(line.encode("ascii", errors="ignore"))
            return True
        except Exception:
            self._close()
            return False

    def _connect(self):
        with self.sock_lock:
            if self.sock:
                return True

        with self.connect_lock:
            with self.sock_lock:
                if self.sock:
                    return True

            s = connect_with_retry(
                self.host,
                self.port,
                "PSX",
                stop_evt=self.stop_evt,
                retry_delay=5.0
            )

            if s is None:
                return False

            try:
                s.sendall(b"clientName=PSX WinCTRL PFP7 Bridge\n")

                # Request all CDU screen and LCD color lines on connect.
                # PSX sends these values immediately, so the bridge starts with
                # a filled cache for left, center, and right CDU.
                for q in range(62, 104):
                    s.sendall(f"Qs{q}\n".encode("ascii"))

                for q in CDU_COLOR_QS_RANGE:
                    s.sendall(f"Qs{q}\n".encode("ascii"))

                for qi in (86, 87, 88, PSX_FMC_CONFIG_QI):
                    s.sendall(f"Qi{qi}\n".encode("ascii"))

                log(
                    "[PSX] requested all CDU screen Qs62-Qs103, "
                    "LCD color Qs500-Qs541, lights Qi86-Qi88, and Qi248"
                )

            except Exception as e:
                log(f"[PSX] setup failed after connect: {repr(e)}")
                try:
                    s.close()
                except Exception:
                    pass
                return False

            with self.sock_lock:
                if self.sock:
                    try:
                        s.close()
                    except Exception:
                        pass
                    return True

                self.sock = s

            return True

    def _close(self):
        with self.sock_lock:
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _rx_drain(self):
        while not self.stop_evt.is_set():
            try:
                if not self._connect():
                    continue

                with self.sock_lock:
                    s = self.sock

                if not s:
                    time.sleep(0.1)
                    continue

                data = s.recv(4096)

                if not data:
                    # Debug: PSX disconnect without exception
                    log_debug("[PSX RX] disconnected")
                    self._close()
                    continue

                text = data.decode("utf-8", errors="replace")
                self._handle_psx_text(text)

            except socket.timeout:
                continue

            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
                if not self.stop_evt.is_set():
                    log(f"[PSX RX] connection lost: {repr(e)}")
                self._close()
                time.sleep(1.0)

            except Exception as e:
                if not self.stop_evt.is_set():
                    log(f"[PSX RX] error: {repr(e)}")
                self._close()
                time.sleep(1.0)

    def _handle_psx_text(self, text):
        self.rx_buffer += text

        while "\n" in self.rx_buffer:
            line, self.rx_buffer = self.rx_buffer.split("\n", 1)
            line = line.rstrip("\r")

            if not line:
                continue

            if line.startswith(f"Qi{self._active_lights_qi()}="):
                self._handle_cdu_lights(line)
                continue

            if line.startswith(f"Qi{PSX_FMC_CONFIG_QI}="):
                self._handle_qi248(line)
                continue

            if line.startswith("Qs") and "=" in line:
                self._handle_fmc_line(line)

    def _handle_cdu_lights(self, line):
        _, value = line.split("=", 1)

        try:
            state = int(value.strip())
        except ValueError:
            return

        lights_qi = self._active_lights_qi()

        if state == self.cdu_lights_state.get(lights_qi):
            return

        self.cdu_lights_state[lights_qi] = state

        log(f"[CDU LIGHTS] Qi{lights_qi}={state} / 0x{state:04X}")
        self.pfp7_leds.apply_psx_cdu_lights_bitmask(state)

    def _apply_qi248_state(self, state, force_log=False):
        cfg = self._active_config()

        nextgen_fmc = bool(state & QI248_NEXTGEN_FMC_BIT)
        cdu_lcd = bool(state & cfg["lcd_qi248_bit"])

        RUNTIME_CONFIG.set_from_qi248(nextgen_fmc, cdu_lcd)

        color = "w" if cdu_lcd else "g"
        atc_altn = 1 if nextgen_fmc else 0

        if force_log:
            log(
                f"[CONFIG] Qi248={state} / 0x{state:08X} -> "
                f"CDU {cfg['label']}, CDU_COLOR={color}, CDU_ATC_ALTN={atc_altn}"
            )
        else:
            log_debug(
                f"[CONFIG] Qi248 reapplied: CDU {cfg['label']}, "
                f"CDU_COLOR={color}, CDU_ATC_ALTN={atc_altn}"
            )

    def _handle_qi248(self, line):
        _, value = line.split("=", 1)

        try:
            state = int(value.strip())
        except ValueError:
            return

        if state == self.qi248_state:
            return

        self.qi248_state = state
        self._apply_qi248_state(state, force_log=True)

        # Redraw because Qi248 can switch the active CDU between CRT and LCD.
        # That changes the default color and whether PSX LCD color strings matter.
        with self.fmc_lock:
            self.fmc_dirty = True

        self._send_fmc_frame()

    def _send_fmc_frame(self):
        with self.fmc_lock:
            if not self.fmc_dirty:
                return

            self.fmc_dirty = False

        ordered_lines = [self.fmc_lines.get(q, "") for q in self._active_qs_lines()]
        if RUNTIME_CONFIG.get_cdu_color() == "w":
            # LCD mode: use PSX per-character LCD color strings.
            ordered_color_lines = [
                self.all_fmc_color_lines.get(q, "")
                for q in self._active_color_qs_lines()
            ]
        else:
            # CRT/legacy mode: keep the existing all-green behavior.
            ordered_color_lines = None

        # Debug: FMC frame queued for MobiFlight
        log_debug("[FMC] frame queued")
        self.mobiflight.send_lines(ordered_lines, ordered_color_lines)

    def _handle_fmc_line(self, line):
        left, value = line.split("=", 1)

        try:
            qnum = int(left[2:])
        except ValueError:
            return

        if qnum in CDU_COLOR_QS_RANGE:
            self.all_fmc_color_lines[qnum] = value

            # Only redraw MobiFlight when the color update belongs to active CDU.
            if qnum in self._active_color_qs_lines():
                with self.fmc_lock:
                    self.fmc_dirty = True

                    if self.fmc_timer:
                        self.fmc_timer.cancel()

                    self.fmc_timer = threading.Timer(0.05, self._send_fmc_frame)
                    self.fmc_timer.daemon = True
                    self.fmc_timer.start()

            return

        if qnum < 62 or qnum > 103:
            return

        # Scratchpad command line for active CDU selection:
        #   CDU L -> Left CDU
        #   CDU C -> Center CDU
        #   CDU R -> Right CDU
        if qnum == self._active_qs_lines()[-1]:
            command = value.strip().upper()

            target_cdu = None

            if command in ("CDU-L", "CDU LEFT"):
                target_cdu = "L"

            elif command in ("CDU-C", "CDU CENTER", "CDU CENTRE"):
                target_cdu = "C"

            elif command in ("CDU-R", "CDU RIGHT"):
                target_cdu = "R"

            if target_cdu:
                source_qh_name = self._active_qh_name()
                self.clear_command_from_source_cdu(source_qh_name)
                self.set_active_cdu(target_cdu)
                return

        # Store every CDU line, even when it is not the currently displayed CDU.
        self.all_fmc_lines[qnum] = value

        # Only redraw MobiFlight when the updated line belongs to the active CDU.
        if qnum in self._active_qs_lines():
            with self.fmc_lock:
                self.fmc_dirty = True

                if self.fmc_timer:
                    self.fmc_timer.cancel()

                self.fmc_timer = threading.Timer(0.05, self._send_fmc_frame)
                self.fmc_timer.daemon = True
                self.fmc_timer.start()

    def _tx_loop(self):
        while not self.stop_evt.is_set():
            code = self.q.get()
            if code is None:
                break

            now = time.monotonic()
            dt = now - self.last_send
            if dt < self.min_interval:
                time.sleep(self.min_interval - dt)

            line = f"{self._active_qh_name()}={code}\n".encode("ascii", errors="ignore")

            try:
                if not self._connect():
                    continue

                with self.sock_lock:
                    s = self.sock

                if not s:
                    continue

                self.tx_count += 1
                # Debug: raw PSX keyboard output
                log_debug(f"[PSX] TX#{self.tx_count} -> {line!r}")
                s.sendall(line)
                self.last_send = time.monotonic()

            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
                if not self.stop_evt.is_set():
                    log(f"[PSX] send connection lost: {repr(e)} -> reconnect")
                self._close()

            except Exception as e:
                if not self.stop_evt.is_set():
                    log(f"[PSX] send error: {repr(e)} -> reconnect")
                self._close()


def main():
    STATUS.start()

    psx_host, psx_port, VID, PID = load_config()
    start_mobiflight_if_needed(MOBIFLIGHT_PATH)
    mapping = load_map()

    lsk_bps = {bp for bp, name in mapping.items() if name.upper().startswith("LSK")}
    log(f"[MAP] LSK bitpos: {sorted(lsk_bps)}")

    bp_to_code = {}
    for bp, name in mapping.items():
        code = PSX_NAME_TO_CODE.get(name.upper())
        if code is not None:
            bp_to_code[bp] = code

    log(f"[MAP] resolvable to PSX codes: {len(bp_to_code)}")
    # Use all mapped HID buttons, including BRT+/BRT- which have no PSX code
    mapped_bps = set(mapping.keys())

    devs = hid.enumerate(VID, PID)
    if not devs:
        raise RuntimeError(f"CDU HID not found VID={hex(VID)} PID={hex(PID)}")

    d = devs[0]
    # Debug: selected HID device details
    log_debug(
        f"[HID] Using '{d.get('product_string')}' "
        f"if={d.get('interface_number')} "
        f"usage_page={d.get('usage_page')} "
        f"usage={d.get('usage')}"
    )

    h = hid.device()
    h.open_path(d["path"])

    try:
        h.set_nonblocking(True)
    except Exception:
        try:
            h.nonblocking = True
        except Exception:
            pass

    pfp7_leds = Pfp7LedController()
    pfp7_leds.start()

    mobiflight = MobiFlightSender(MOBIFLIGHT_WS)
    mobiflight.start()

    psx = PsxSender(psx_host, psx_port, mobiflight, pfp7_leds, MIN_SEND_INTERVAL)
    psx.start()

    log("[RUN] HID keys -> active PSX CDU, active PSX CDU screen -> MobiFlight, active PSX CDU lights -> PFP7 LEDs. Ctrl+C to quit.")
    log("[CONFIG] Scratchpad commands: CDU-L = Left, CDU-C = Center, CDU-R = Right")
    
    prev_pressed = set()
    stable_count = defaultdict(int)
    last_rise_time = {}

    brt_hold_direction = 0
    brt_hold_start_time = None
    brt_last_repeat_time = 0.0

    try:
        while True:
            data = h.read(READ_SIZE)

            if not data:
                time.sleep(0.001)
                continue

            frame = bytes(data)

            if len(frame) < 1 or frame[0] != 0x01:
                continue

            cur_pressed_raw = pressed_from_mapping(frame, mapped_bps)

            cur_pressed = set()
            for bp in cur_pressed_raw:
                if bp in lsk_bps:
                    cur_pressed.add(bp)
                    continue

                stable_count[bp] += 1
                if stable_count[bp] >= STABLE_FRAMES:
                    cur_pressed.add(bp)

            for bp in list(stable_count):
                if bp not in cur_pressed_raw:
                    stable_count.pop(bp, None)

            rising = cur_pressed - prev_pressed
            falling = prev_pressed - cur_pressed
            prev_pressed = cur_pressed

            now = time.monotonic()

            if (
                brt_hold_direction != 0
                and brt_hold_start_time is not None
                and now - brt_hold_start_time >= PFP7_BRT_HOLD_DELAY
                and now - brt_last_repeat_time >= PFP7_BRT_REPEAT_INTERVAL
            ):
                pfp7_leds.change_screen_brightness_step(brt_hold_direction)
                brt_last_repeat_time = now

            # Hardware key release handling.
            # PSX automatically releases most CDU keys internally, but CLR (39)
            # and ATC (60) must be explicitly released by sending -1 when the
            # physical key is released.
            for bp in falling:
                name = mapping.get(bp, "").upper()

                if name in ("BRT+", "BRT-"):
                    brt_hold_direction = 0
                    brt_hold_start_time = None
                    brt_last_repeat_time = 0.0
                    continue

                code = bp_to_code.get(bp)

                if code in NEED_RELEASE:
                    # Debug: HID release for keys requiring explicit PSX release
                    log_debug(f"[HID] release {mapping.get(bp)} -> -1")
                    psx.send_code(-1)

            # Hardware key press handling.
            for bp in rising:
                if (now - last_rise_time.get(bp, 0.0)) < RISING_COOLDOWN:
                    continue

                last_rise_time[bp] = now

                name = mapping.get(bp, "").upper()

                if name == "BRT+":
                    pfp7_leds.change_screen_brightness_step(+1)
                    brt_hold_direction = +1
                    brt_hold_start_time = now
                    brt_last_repeat_time = now
                    continue

                if name == "BRT-":
                    pfp7_leds.change_screen_brightness_step(-1)
                    brt_hold_direction = -1
                    brt_hold_start_time = now
                    brt_last_repeat_time = now
                    continue

                code = bp_to_code.get(bp)
                if code is None:
                    # Debug: mapped HID key has no PSX keycode
                    log_debug(f"[HID] {bp} {mapping.get(bp)} -> NO PSX CODE")
                    continue

                # Debug: keyboard output to PSX
                log_debug(f"[HID] {bp} {mapping.get(bp)} -> {code}")

                if code == 60 and RUNTIME_CONFIG.get_cdu_atc_altn() == 1:
                    # Debug: ATC alternate translation
                    log_debug("[ATC ALTN] ATC key replaced by FMC COMM, LSKL2")
                    psx.send_codes(CDU_ATC_ALTN_SEQUENCE)
                else:
                    psx.send_code(code)

    except KeyboardInterrupt:
        pass

    finally:
        try:
            h.close()
        except Exception:
            pass

        psx.stop()
        mobiflight.stop()
        pfp7_leds.stop()
        log("[END]")


if __name__ == "__main__":
    main()
