# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

BLE (Bluetooth Low Energy) protocol library for Neewer LED lights. The official Neewer app is unreliable, so this project provides a working alternative control interface.

## Working Tool

`neewer.py` is the main CLI tool. Commands verified on PL60C and TL120 RGB-2 hardware.

```bash
# Run with conda python (not on default PATH)
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py <command>

# Scan and use aliases
python neewer.py scan                                              # find lights
python neewer.py on --light 0                                      # use scan index
python neewer.py cct --light NW-2022 --brightness 80 --temp 5600   # partial name match
python neewer.py hsi --light all --hue 240 --sat 100 --brightness 80

# Auto-detect protocol (default) or explicit override
python neewer.py cct --light 0 --brightness 80 --temp 5600           # auto-detect
python neewer.py --protocol extended cct --light 0 --brightness 80 --temp 5600
python neewer.py --protocol legacy on --light 0

# Channel-addressed group control (--ch flag)
python neewer.py channel assign --light 0 --ch 1         # assign light to channel
python neewer.py cct --light 0 --ch 1 --brightness 80 --temp 5600  # send via channel
python neewer.py on --ch 1 --light 0                     # power via channel

# New commands from APK discovery
python neewer.py find --light 0                          # flash light to locate
python neewer.py battery --light 0                       # query battery level
python neewer.py rgbcw --light 0 --brightness 80 --red 255 --green 0 --blue 128
python neewer.py xy --light 0 --brightness 80 --x 0.3127 --y 0.3290
python neewer.py fan --light 0                           # query temp/fan
python neewer.py fan --light 0 --mode 2                  # set fan mode

# All 31 CLI subcommands
scan, on, off, cct, hsi, scene, gel, source, color, fade, strobe, status, demo, interactive, batch, raw, info, preset, group, monitor, effects, gels, sources, colors, channel, find, battery, fan, booster, rgbcw, xy
# REPL-only session commands: bri, temp, hue, fade-color, fade-temp, fade-hue, random, find, battery, fan, booster, rgbcw, xy
```

## sACN Bridge

`neewer_sacn.py` bridges sACN (E1.31) DMX data to BLE lights. Each light gets a 10-channel DMX footprint matching the Neewer DMX specs. Supports 4 modes: CCT (0-31), HSI (32-63), FX (64-95), GEL (96-127), and blackout (128+).

```bash
python neewer_sacn.py                           # auto-scan, universe 1, start ch 1
python neewer_sacn.py -u 2 -s 11               # universe 2, first light at ch 11
python neewer_sacn.py --channel-mode            # use channel broadcasting (1 BLE conn)
python neewer_sacn.py --list-channels           # show channel map and exit
python neewer_sacn.py --verbose                 # debug output for every DMX→BLE translation
```

## Tests

```bash
/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_protocol.py -v
```

135 tests (110 protocol + 25 bridge) covering all of the above plus: channel command envelope, channel power/CCT/HSI/scene builders, channel-vs-MAC parity (including gel native), network management (assign/remove/set/delete), native gel (big-endian hue encoding, Infinity native TAG 0xAD, brand/gel_num parsing), RGBCW (direct RGB+CW control with clamping), XY color coordinate encoding, utility commands (find, battery, temp/fan, booster), channel-addressed INT Loop scene, all 18 FX sub-parameter mappings in sACN bridge.

## Protocol

Full spec in `docs/protocol.md`. Three protocol variants auto-detected from BLE device name:

| Variant | Envelope | Detection |
|---------|----------|-----------|
| **Infinity** | `78 TAG SIZE MAC[6] SUBTAG PARAMS CS` | `NW-` prefix BLE name |
| **Extended Legacy** | `78 TAG LEN PARAMS CS` (18 effects, GM) | Model DB (GL1C, RGB168, CL124) |
| **Legacy** | `78 TAG LEN PARAMS CS` (9 effects, no GM) | Model DB (RGB660, etc.) |

Infinity also supports **channel-addressed** commands for group broadcast: `78 TAG SIZE NETID[4] CH SUBTAG PARAMS CS`

Key facts:
- CHECKSUM = sum(all_bytes_except_last) & 0xFF
- MAC not validated by PL60C (any MAC accepted, including all-zeros)
- Scene commands require power cycle: OFF → 50ms → ON → 50ms → scene
- Status query: TAG `0x8E` returns power state (ON/STANDBY) via notify characteristic
- Legacy query commands (`78 84`, `78 85`) do NOT work on Infinity lights
- Model DB maps product codes (from NW-{code}&{suffix} names) to model info
- Channel mode: assign lights to channel via TAG 0x9F, then control all via one BLE connection
- Native Gel (TAG 0xAD) uses big-endian hue (opposite of HSI little-endian)
- RGBCW (TAG 0xA9) provides direct R/G/B/Cold/Warm white control
- XY Color (TAG 0xB7) for CIE 1931 chromaticity coordinates

## Prior Art

- **NeewerLite** (macOS Swift): https://github.com/keefo/NeewerLite (cloned in `***REMOVED***`)
- **NeewerLite-Python**: https://github.com/taburineagle/NeewerLite-Python (cloned in `***REMOVED***`)
- DMX Specs in repo root: `TL60 RGB DMX-EN.pdf`, `TL90C DMXEN.pdf`, `TL120C DMXEN.pdf`, `PL60C DMXEN.pdf`

## Environment

- Use fully qualified conda path: `/opt/homebrew/Caskroom/miniforge/base/bin/conda` or activate the environment before running Python scripts.
- Do not assume `conda` or `python` are on the default PATH.
- Dependencies: `bleak>=0.21.0`, `sacn>=1.9.0` (see `requirements.txt`)

## Key Patterns

- BLE max packet size is 20 bytes
- Neewer lights advertise with "NEEWER" or "NW-" prefix in device name
- PL60C advertises on two CoreBluetooth UUIDs simultaneously (same device); scan deduplicates by product code, keeping the UUID with stronger RSSI (the one that responds to status queries)
- `bleak>=2.1.1` requires `return_adv=True` for RSSI in `BleakScanner.discover()`
- On macOS, CoreBluetooth UUIDs ≠ hardware MACs. Resolve via `system_profiler SPBluetoothDataType` while connected.
- Protocol auto-detected per-light from device name; overridable with `--protocol`
