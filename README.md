# PSX ↔ WinCTRL PFP7 Bridge

A Python bridge that connects the WinCTRL PFP7 CDU to the Aerowinx PSX Boeing 747 simulator.

The bridge provides:

* PFP7 CDU keyboard input to PSX
* PSX CDU display output to the WINCTRL/MobiFlight LCD
* PSX CDU screen blanking support
* PSX CDU annunciator support
* Automatic Left, Center and Right CDU switching
* Automatic Next Generation / Legacy FMC detection
* Automatic LCD / CRT CDU detection
* Per-character LCD color support
* Automatic MobiFlight detection and startup
* Configurable WINCTRL PID / DID device selection
* Configurable ATC / ALTN key behavior
* Comment-preserving INI updates
* PyInstaller EXE support with INI next to the EXE
* Clean WINCTRL HID not-found error handling
* Quiet default logging with extended `--debug` diagnostics

---

# Features

## CDU Keyboard

All supported PFP7 CDU keys are mapped directly to the active PSX CDU.

Supported:

* LSK keys
* Alphanumeric keys
* EXEC
* CLR
* MENU
* PREV PAGE
* NEXT PAGE
* BRT+
* BRT-

---

## Key Hold Behaviour

Most CDU keys are sent to PSX as a single key press.

The following keys support hold functionality:

| Key        | Behaviour                                                   |
| ---------- | ----------------------------------------------------------- |
| BRT+       | Repeats brightness increase while held                      |
| BRT-       | Repeats brightness decrease while held                      |
| CLR        | Sends a key press on push and a release event when released |
| ATC / ALTN | Sends a key press on push and a release event when released |

### CLR Hold

The bridge uses a held CLR key to clear scratchpad commands entered directly into the CDU scratchpad, such as:

* CDU-L
* CDU-C
* CDU-R
* CDU-ATC
* CDU-ALTN

After a command is detected, the bridge briefly holds CLR and then releases it automatically to remove the command from the scratchpad.

### Other Keys

All remaining CDU keys are transmitted as momentary key presses only, including:

* LSK keys
* EXEC
* MENU
* PREV PAGE
* NEXT PAGE
* Alphanumeric keys
* Numeric keys

Holding these keys currently has no special behaviour within the bridge.

---

## ATC / ALTN Key Configuration

The WINCTRL PFP7 has an ALTN key where the PFP4 (B747) FMC has an ATC key.
The ATC key behavior can be configured in:

```ini
[FMC]
atc_key = ALTN
```

Available options:

* ATC = Original PSX ATC key
* ALTN = FMC COMM + LSK 2L (777-style ALTN page)

The behavior can also be changed from the CDU scratchpad:

* CDU-ATC  -> the ALTN key on the PFP7 = ATC page
* CDU-ALTN -> the ALTN key on the PFP7 = ALTN page

Changes are saved automatically to:

```text
psx_pfp7.ini
```

### Legacy FMC Behavior

When PSX reports that the Next Generation FMC is not active, the bridge automatically forces the original ATC key behavior at runtime.

The saved INI setting is preserved and becomes active again automatically when the Next Generation FMC is re-enabled.

---

## CDU Switching

The active CDU can be selected directly from the scratchpad:

* CDU-L
* CDU-C
* CDU-R

The bridge maintains a complete cache of all CDU screens and color information, allowing instant switching without requiring a PSX screen reload.

---

## LCD Display Support

The bridge continuously caches:

* Qs62 – Qs103 (CDU screen data)
* Qs500 – Qs541 (CDU color data)

This allows immediate display updates when switching between:

* Left CDU
* Center CDU
* Right CDU

---

## CDU Screen Blanking

The bridge supports PSX CDU screen blanking.

Data source:

* Qi89 – BlankTimeCduL, Left CDU
* Qi90 – BlankTimeCduC, Center CDU
* Qi91 – BlankTimeCduR, Right CDU

Behaviour:

* Value = 0 → CDU display visible
* Value ≠ 0 → CDU display blanked

This reproduces the FMC/CDU blanking behaviour used after certain key presses, during FMC warm-up, or when CDU power is unavailable.

The bridge continues to cache CDU screen and color data while the display is blanked. When the blanking timer returns to zero, the most recent CDU page is displayed immediately.

---

## LCD Color Support

Supported PSX CDU colors:

| PSX | Color   |
| --- | ------- |
| a   | Amber   |
| b   | Blue    |
| c   | Cyan    |
| g   | Green   |
| m   | Magenta |
| r   | Red     |
| w   | White   |
| y   | Grey    |

Color definitions are received from PSX and applied per character on the MobiFlight LCD.

---

## CDU Annunciators

The bridge supports the CDU annunciator lights through PSX:

* EXEC
* DSPY
* FAIL
* MSG
* OFST

Data source:

* Qi86 (Left CDU)
* Qi87 (Center CDU)
* Qi88 (Right CDU)

---

## FMC Detection

The bridge automatically evaluates Qi248.

Detected information:

### FMC Type

* Next Generation FMC
* Legacy FMC

### CDU Display Type

* LCD CDU (color)
* CRT CDU (green)

---

## Automatic MobiFlight Detection

The bridge first attempts to locate MobiFlight through:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MobiFlight Connector
```

If the registry lookup fails, or the required DLL is missing, the path configured in:

```ini
[MOBIFLIGHT]
PATH=
```

is used as a fallback.

---

## Automatic MobiFlight Startup

If MobiFlight is not running, the bridge automatically starts:

```text
MFConnector.exe
```

before connecting to the LCD display.

The bridge also displays the detected MobiFlight version at startup.

---

## MobiFlight Requirements

This bridge requires:

* MobiFlight Connector v11.1.0 or newer

If the required WINCTRL interface is unavailable, the bridge will display an advisory message suggesting an update or reinstall of MobiFlight Connector.

---

## Configuration

Example default configuration:

```ini
# ------------------------------------------------------------
# PSX PFP7 Bridge configuration
# ------------------------------------------------------------

[PSX]
# Aerowinx PSX TCP server
host = 127.0.0.1
port = 10747


# ------------------------------------------------------------
# WINCTRL CDU device identification
#
# VID is hardcoded in the bridge as 0x4098.
#
# PID = USB Product ID.
# DID = WINCTRL Destination ID used for LED/backlight messages.
#
# The bridge uses PID to find the CDU hardware and to initialize
# the MobiFlight WINCTRL sender.
#
# DID is used by the MobiFlight DLL when sending LED and
# backlight commands to the device.
#
# +-----------+--------+--------+
# | Device    | PID    | DID    |
# +-----------+--------+--------+
# | PFP3N CPT | BB35   | 31BB   |
# | PFP3N OBS | BB39   | 31BB   |
# | PFP3N FO  | BB3D   | 31BB   |
# +-----------+--------+--------+
# | MCDU CPT  | BB36   | 32BB   |
# | MCDU OBS  | BB3A   | 32BB   |
# | MCDU FO   | BB3E   | 32BB   |
# +-----------+--------+--------+
# | PFP7 CPT  | BB37   | 33BB   |
# | PFP7 OBS  | BB3B   | 33BB   |
# | PFP7 FO   | BB3F   | 33BB   |
# +-----------+--------+--------+
# | PFP4 CPT  | BB38   | 34BB   |
# | PFP4 OBS  | BB3C   | 34BB   |
# | PFP4 FO   | BB40   | 34BB   |
# +-----------+--------+--------+
#
# Example:
# PFP7 Captain -> PID = BB37, DID = 33BB
# PFP4 Captain -> PID = BB38, DID = 34BB
# ------------------------------------------------------------

[FMC]
pid = BB37
did = 33BB


# ------------------------------------------------------------
# ATC key behavior
#
# The PFP7 hardware key is labeled "ALTN".
#
# ATC  = sends the original PSX ATC key.
# ALTN = the ALTN key opens the ALTN page by sending
#        FMC COMM + LSK2L automatically.
#
# This setting is only used when a Next Generation FMC is active.
# When a Legacy FMC is active, the bridge automatically forces
# the original ATC key regardless of this setting.
#
# Scratchpad commands:
# CDU-ATC  = switch to ATC mode and save to ini
# CDU-ALTN = switch to ALTN mode and save to ini
# ------------------------------------------------------------

atc_key = ATC


# ------------------------------------------------------------
# MobiFlight Connector
#
# Optional fallback path to MobiFlight Connector.
# The bridge first tries to find MobiFlight via the Windows registry.
#
# Usually installed in:
# C:\Users\<username>\AppData\Local\MobiFlight\MobiFlight Connector
# ------------------------------------------------------------

[MOBIFLIGHT]
path = C:\Users\<username>\AppData\Local\MobiFlight\MobiFlight Connector
```

Normally the MobiFlight path does not need to be configured because it is detected automatically.

### WINCTRL Device Selection

The WINCTRL USB Vendor ID is fixed in the bridge:

```text
VID = 0x4098
```

The Product ID and Destination ID are read from `psx_pfp7.ini`:

```ini
[FMC]
pid = BB37
did = 33BB
```

`pid` is used for both HID device detection and the MobiFlight WINCTRL sender initialization.

`did` is used for LED and backlight messages.

The `pid` value may be written with or without `0x`:

```ini
pid = BB37
```

or:

```ini
pid = 0xBB37
```

Both are interpreted as hexadecimal values.

### WINCTRL CDU Not Found

If the configured CDU is not found, the bridge now shows a clean error message instead of a Python/PyInstaller traceback.

Example:

```text
[ERROR] WINCTRL CDU not found.
[ERROR] Expected VID=4098 PID=BB38

[ERROR] Check the [FMC] pid setting in psx_pfp7.ini.
[ERROR] Also check that the CDU is connected and visible in Windows.

Press ENTER to exit...
```

### Comment-Preserving INI Updates

When the scratchpad commands `CDU-ATC` or `CDU-ALTN` are used, the bridge updates only the `atc_key` line in `psx_pfp7.ini`.

The INI file is no longer rewritten by `configparser`, so comments and layout are preserved.


---

## Logging

By default, startup output is intentionally kept quiet.

Normal mode shows only the most useful status messages, such as:

* bridge startup
* detected MobiFlight version
* PSX connected
* MobiFlight connected
* scratchpad command hints
* important errors and warnings
* `ATC_KEY` save confirmations

Detailed diagnostics are available with:

```bash
python psx_pfp7.py --debug
```

Debug mode shows extra information such as:

* MobiFlight registry / INI path detection
* PSX host and port
* selected PID and DID
* DLL path
* keyboard mapping information
* websocket reconnect attempts
* display frame traffic
* LED and brightness updates

MobiFlight websocket reconnect messages during startup are hidden in normal mode because they can occur while MobiFlight Connector is still starting.

---

## Startup

Run:

```bash
python psx_pfp7.py
```

When using a PyInstaller-built EXE, place `psx_pfp7.ini` in the same folder as the EXE:

```text
psx_pfp7.exe
psx_pfp7.ini
```

The MobiFlight DLL does not need to be placed next to the EXE. It remains in the original MobiFlight installation folder and is located through the Windows registry or the `[MOBIFLIGHT] path` fallback in the INI.

Enable diagnostic logging when needed:

```bash
python psx_pfp7.py --debug
```

Useful scratchpad commands:

* CDU-L
* CDU-C
* CDU-R
* CDU-ATC
* CDU-ALTN

Press CTRL+C to terminate the bridge.

---

## Version History

### v1.05

* Added clean WINCTRL CDU not-found error handling
* Replaced the unhandled HID `RuntimeError` with a user-friendly error message
* Prevents PyInstaller from showing a traceback when the configured CDU PID is wrong or the CDU is not connected
* Shows the expected VID/PID and advises checking the `[FMC] pid` setting and USB connection

### v1.04

* Added PyInstaller EXE path handling
* When running as an EXE, `psx_pfp7.ini` is read from the same folder as the EXE
* When running as a normal Python script, `psx_pfp7.ini` is read from the script folder
* MobiFlight DLL loading still uses the original MobiFlight installation path via registry or `[MOBIFLIGHT] path`
* The MobiFlight DLL does not need to be copied next to the EXE

### v1.03

* Reduced normal startup log output
* Moved routine configuration, mapping, brightness and reconnect diagnostics to `--debug`
* Hid MobiFlight websocket reconnect messages during MobiFlight startup in normal mode
* Kept important connection, error, warning and INI-save messages visible

### v1.02

* Added comment-preserving INI updates
* `CDU-ATC` and `CDU-ALTN` now update only the `atc_key` line
* Existing comments and layout in `psx_pfp7.ini` are preserved when saving ATC/ALTN mode

### v1.01a

* Added configurable WINCTRL PID from `psx_pfp7.ini`
* `PID` is used for HID detection and MobiFlight WINCTRL sender initialization
* Added configurable WINCTRL DID from `psx_pfp7.ini`
* `DID` is used for LED and backlight destination messages
* Hardcoded WINCTRL Vendor ID remains fixed at `0x4098`
* Added support for PFP7/PFP4/PFP3N/MCDU PID/DID selection through the INI

### v1.01

* Added CDU screen blanking support
* Supports BlankTimeCduL (Qi89) for the Left CDU
* Supports BlankTimeCduC (Qi90) for the Center CDU
* Supports BlankTimeCduR (Qi91) for the Right CDU
* Blanks the active PFP7 display whenever the related PSX blanking value is non-zero
* Continues caching CDU screen and color data while blanked
* Added `--debug` command line option
* Moved PSX bulk data request logging to debug output

### v1.00

* Full CDU LCD color support
* CDU screen and color caching
* Automatic MobiFlight detection
* Automatic MobiFlight startup
* MobiFlight version reporting
* Configurable ATC / ALTN behavior
* Scratchpad command support
* Runtime Legacy FMC ATC override
* Improved startup diagnostics
* Cleaner logging with DEBUG support

---

## Disclaimer

This project is an independent community project and is not affiliated with or endorsed by Aerowinx, Winwing, WinCTRL, or MobiFlight.

---

## Author

Jamie Janssen

Developed for the Aerowinx PSX and WinCTRL PFP7 community.
