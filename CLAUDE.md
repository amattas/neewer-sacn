# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

BLE (Bluetooth Low Energy) protocol library for Neewer LED lights. The official Neewer app is unreliable, so this project provides a working alternative control interface.

## Project Structure

```
src/neewer/          # Package source
    __init__.py      # Re-exports protocol layer
    __main__.py      # python -m neewer support
    protocol.py      # Core BLE protocol + CLI (~3300 lines)
    config.py        # Multi-group configuration management
    sacn.py          # sACN (E1.31) DMX bridge
    scenes.py        # Scene engine (YAML scripted + Python generative)
    tui.py           # Textual-based terminal UI
    audio.py         # Audio analysis (RMS, FFT, beat detection)
    probe_tags.py    # BLE tag probing utility
tests/               # Pytest test suite
    test_protocol.py # 110 tests
    test_sacn.py     # 25 tests
    test_config.py   # 26 tests
    test_scenes.py   # 10 tests
    test_audio.py    # 7 tests
docs/                # Documentation
    protocol.md      # Full protocol spec
scenes/              # Example scene files (YAML + Python)
examples/            # Batch command files
pyproject.toml       # Package config, deps, pytest config
```

## Setup & Running

```bash
# Install in editable mode (from repo root)
/opt/homebrew/Caskroom/miniforge/base/bin/pip install -e ".[dev,audio,tui]"

# Run CLI
neewer <command>                  # via console script
python -m neewer <command>       # via module

# Run sACN bridge
neewer-sacn                      # via console script

# Run tests
pytest                           # uses pyproject.toml [tool.pytest.ini_options]
pytest tests/ -v                 # verbose
```

## CLI Commands

Commands verified on PL60C and TL120 RGB-2 hardware.

```bash
neewer scan                                              # find lights
neewer on --light 0                                      # use scan index
neewer cct --light NW-2022 --brightness 80 --temp 5600   # partial name match
neewer hsi --light all --hue 240 --sat 100 --brightness 80

# Auto-detect protocol (default) or explicit override
neewer --protocol extended cct --light 0 --brightness 80 --temp 5600
neewer --protocol legacy on --light 0

# Channel-addressed group control (--ch flag)
neewer channel assign --light 0 --ch 1
neewer cct --light 0 --ch 1 --brightness 80 --temp 5600
neewer on --ch 1 --light 0

# Commands from APK discovery
neewer find --light 0                          # flash light to locate
neewer battery --light 0                       # query battery level
neewer rgbcw --light 0 --brightness 80 --red 255 --green 0 --blue 128
neewer xy --light 0 --brightness 80 --x 0.3127 --y 0.3290
neewer fan --light 0                           # query temp/fan
neewer fan --light 0 --mode 2                  # set fan mode

# All 35 CLI subcommands
scan, on, off, cct, hsi, scene, gel, source, color, fade, strobe, status, demo,
interactive, batch, raw, info, preset, group, monitor, effects, gels, sources,
colors, channel, find, battery, fan, booster, rgbcw, xy, config, connections,
scene-run, scene-list, tui, audio-test
```

## sACN Bridge

`neewer.sacn` bridges sACN (E1.31) DMX data to BLE lights. Each light gets a 10-channel DMX footprint matching the Neewer DMX specs. Supports 4 modes: CCT (0-31), HSI (32-63), FX (64-95), GEL (96-127), and blackout (128+).

```bash
neewer-sacn                             # auto-scan, universe 1, start ch 1
neewer-sacn -u 2 -s 11                 # universe 2, first light at ch 11
neewer-sacn --channel-mode             # use channel broadcasting (1 BLE conn)
neewer-sacn --list-channels            # show channel map and exit
neewer-sacn --verbose                  # debug output for every DMX→BLE translation
```

## Configuration System

`neewer.config` manages persistent multi-group configurations with role-based light assignments, channel auto-management, and state snapshots. Stored in `.neewer_config.json`.

```bash
neewer config create studio           # create config with random NETID
neewer config add-light studio key --light 0  # assign role
neewer config use studio              # set active
neewer config show studio             # display details
neewer connections                    # show BLE connections and channel map
neewer --config studio cct --brightness 80 --temp 5600  # target via config
```

## Scene Engine

`neewer.scenes` supports scripted YAML scenes (timed steps with fade interpolation) and generative Python scenes (render() callback). Example scenes in `scenes/`.

```bash
neewer scene-list                     # list available scenes
neewer scene-run scenes/sunset-fade.yaml --config studio
neewer scene-run scenes/rainbow_chase.py --config studio
neewer scene-run scenes/beat_flash.py --config studio --mic  # audio-reactive
```

## Terminal UI

`neewer.tui` provides a Textual-based TUI with three views: Dashboard (light cards), Scene Designer (timeline viewer), Performance Console (faders, hotkeys, audio meter).

```bash
neewer tui                            # launch TUI
```

## Audio System

`neewer.audio` provides audio analysis: RMS amplitude, 3-band FFT (bass/mid/treble), energy-based beat detection with BPM estimation.

```bash
neewer audio-test                     # live mic level display
neewer audio-test --device 2          # specific audio device
```

## Tests

```bash
pytest                    # run all 178 tests
pytest tests/ -v          # verbose output
pytest tests/test_protocol.py -v   # single module
```

178 tests across 5 test files:
- `tests/test_protocol.py` (110 tests): protocol builders, checksums, model detection, all 3 variants
- `tests/test_sacn.py` (25 tests): sACN-to-BLE translation, channel mode, FX sub-params
- `tests/test_config.py` (26 tests): config CRUD, snapshots, resolution, channel maps
- `tests/test_scenes.py` (10 tests): YAML/generative loading, interpolation, scene runner
- `tests/test_audio.py` (7 tests): RMS, frequency bands, beat detection

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

## Internal Imports

```python
# From within the package (src/neewer/*.py):
from neewer import protocol as neewer    # protocol functions
from neewer import config as neewer_config
from neewer import scenes as neewer_scenes
from neewer import audio as neewer_audio

# From tests or external code:
from neewer import protocol as neewer    # direct module access (incl. private names)
import neewer                            # via __init__.py re-exports (public names only)
```

## Prior Art

- **NeewerLite** (macOS Swift): https://github.com/keefo/NeewerLite (cloned in `***REMOVED***`)
- **NeewerLite-Python**: https://github.com/taburineagle/NeewerLite-Python (cloned in `***REMOVED***`)
- DMX Specs in repo root: `TL60 RGB DMX-EN.pdf`, `TL90C DMXEN.pdf`, `TL120C DMXEN.pdf`, `PL60C DMXEN.pdf`

## Environment

- Use fully qualified conda path: `/opt/homebrew/Caskroom/miniforge/base/bin/conda` or activate the environment before running Python scripts.
- Do not assume `conda` or `python` are on the default PATH.
- Dependencies managed via `pyproject.toml`: core (`bleak`, `sacn`, `pyyaml`), optional extras `[tui]`, `[audio]`, `[dev]`

## Key Patterns

- BLE max packet size is 20 bytes
- Neewer lights advertise with "NEEWER" or "NW-" prefix in device name
- PL60C advertises on two CoreBluetooth UUIDs simultaneously (same device); scan deduplicates by product code, keeping the UUID with stronger RSSI (the one that responds to status queries)
- `bleak>=2.1.1` requires `return_adv=True` for RSSI in `BleakScanner.discover()`
- On macOS, CoreBluetooth UUIDs ≠ hardware MACs. Resolve via `system_profiler SPBluetoothDataType` while connected.
- Protocol auto-detected per-light from device name; overridable with `--protocol`
