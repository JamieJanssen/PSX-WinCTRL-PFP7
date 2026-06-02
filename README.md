# PSX ↔ WinCTRL PFP7 Bridge

A Python bridge that connects the WinCTRL PFP7 CDU to the Aerowinx PSX Boeing 747 simulator.

The bridge provides:

* PFP7 CDU keyboard input to PSX
* PSX CDU display output to the Winwing/MobiFlight LCD
* PSX CDU annunciator support
* Automatic Left, Center and Right CDU switching
* Automatic Next Generation / Legacy FMC detection
* Automatic LCD / CRT CDU detection
* Per-character LCD color support
* Automatic MobiFlight detection and startup
* Configurable ATC / ALTN key behavior

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

The WINCTRL PFP7 has a ALTN key where the PFP4 (B747) FMC has an ATC key.
The ATC key behavior can be configured in:

```ini
[FMC]
ATC_KEY=ALTN
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

If the required Winwing interface is unavailable, the bridge will display an advisory message suggesting an update or reinstall of MobiFlight Connector.

---

## Configuration

Example:

```ini
[PSX]
HOST=127.0.0.1
PORT=10747

[FMC]
VID=0x4098
PID=0xBB37
ATC_KEY=ALTN

[MOBIFLIGHT]
PATH=C:\Users\<username>\AppData\Local\MobiFlight\MobiFlight Connector
```

Normally the MobiFlight path does not need to be configured because it is detected automatically.

---

## Startup

Run:

```bash
python psx_pfp7.py
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
