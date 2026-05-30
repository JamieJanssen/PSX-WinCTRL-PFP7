# PSX ↔ WinCTRL PFP7 Bridge

A Python bridge that connects the **WinCTRL PFP7 CDU** to the **Aerowinx PSX Boeing 747 simulator**.

The bridge provides:

* PFP7 CDU keyboard input to PSX
* PSX CDU display output to the Winwing/MobiFlight LCD
* PSX CDU annunciator lights to PFP7 LEDs
* Automatic support for Left, Center and Right CDU
* Automatic NextGen FMC detection
* Automatic CRT/LCD CDU detection
* Per-character LCD color support
* Automatic MobiFlight detection and startup

---

## Features

### CDU Keyboard

All PFP7 CDU keys are mapped directly to the active PSX CDU.

Supported:

* LSK keys
* Alphanumeric keys
* FMC function keys
* CLR
* EXEC
* MENU
* PREV / NEXT PAGE
* BRT+ / BRT-

### CDU Switching

The active CDU can be selected from the scratchpad:

| Command | Function   |
| ------- | ---------- |
| CDU-L   | Left CDU   |
| CDU-C   | Center CDU |
| CDU-R   | Right CDU  |

The switch is immediate and does not require any CDU reload sequence.

---

## LCD Display Support

The bridge receives all CDU screen data from PSX and maintains a cache of:

* Qs62 - Qs103 (all CDU screen lines)
* Qs500 - Qs541 (all CDU color lines)

This allows instant switching between:

* Left CDU
* Center CDU
* Right CDU

without forcing a screen refresh in PSX.

---

## LCD Color Support

Supported PSX colors:

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

Mapped automatically to the corresponding MobiFlight LCD colors.

Example:

```text
Qs530=mmmmmw
```

Results in:

```text
MMMMMWWWWWWWWWWWWWWWWWWW
```

The final color continues for the remainder of the row.

---

## CDU Lights

The following PFP7 annunciators are supported:

* EXEC
* DSPY
* FAIL
* MSG
* OFST

Lights are driven directly from PSX:

| CDU    | PSX Variable |
| ------ | ------------ |
| Left   | Qi86         |
| Center | Qi87         |
| Right  | Qi88         |

---

## Automatic FMC Detection

The bridge monitors:

```text
Qi248
```

and automatically detects:

### Next Generation FMC

Uses:

* White LCD colors
* ATC key alternate mode

### Legacy FMC

Uses:

* Green CRT display mode
* Original ATC key behavior

---

## Automatic MobiFlight Detection

The bridge first attempts to locate MobiFlight using:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\MobiFlight Connector
```

If the registry lookup fails or the required DLL is missing:

```text
MobiFlightWwFcu.dll
```

the bridge falls back to the path configured in:

```ini
[MOBIFLIGHT]
PATH=
```

---

## Automatic MobiFlight Startup

If the MobiFlight websocket is not available:

```text
127.0.0.1:8320
```

the bridge will automatically start:

```text
MFConnector.exe
```

from the configured MobiFlight installation directory.

---

## Requirements

### Software

* Aerowinx PSX
* MobiFlight Connector
* Python 3.11 or newer

### Python Packages

```bash
pip install hidapi
pip install websockets
pip install pythonnet
```

---

## Configuration

Edit:

```text
psx_pfp7.ini
```

Example:

```ini
[PSX]
HOST=127.0.0.1
PORT=10747

[FMC]
VID=0x4098
PID=0xBB37

[MOBIFLIGHT]
PATH=C:\Users\<username>\AppData\Local\MobiFlight\MobiFlight Connector
```

Normally the MobiFlight path does not need to be configured because it is detected automatically.

---

## Startup

Run:

```bash
python psx_pfp7_bridge.py
```

Example startup:

```text
PSX ↔ WinCTRL PFP7 Bridge v0.996

[MOBIFLIGHT] install dir from registry
[MOBIFLIGHT] started
[MOBIFLIGHT] connected

[PSX] connected
[PFP7 LED] connected
```

---

## Version History

### v0.991

* CDU screen caching
* Removed CDU reload sequence

### v0.995

* Full LCD color support
* Qs500-Qs541 support

### v0.996

* Automatic MobiFlight detection
* Registry lookup
* INI fallback
* Automatic MobiFlight startup

---

## Author

Jamie Janssen

Developed for the WinCTRL PFP7 CDU and Aerowinx PSX community.
