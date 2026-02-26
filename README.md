# neewer-ble

BLE protocol library and CLI for Neewer LED lights. Control brightness, color temperature, HSI, RGB, scenes, and effects over Bluetooth Low Energy.

Built by reverse engineering the Neewer app's BLE protocol (permitted under DMCA interoperability exemptions). The official app is unreliable — this project provides a working alternative.

## Features

- **Full protocol support** — CCT, HSI, RGBCW, CIE xy color, gel filters, 18 built-in effects
- **Three protocol variants** — Infinity (NW-series), Extended Legacy, and Legacy, auto-detected per light
- **Channel grouping** — assign lights to channels for single-connection group control
- **Configuration system** — named multi-light setups with role assignments and state snapshots
- **Scene engine** — scripted YAML timelines and generative Python scenes with fade interpolation
- **Audio-reactive** — beat detection, frequency-band mapping, BPM estimation for live scenes
- **sACN/E1.31 bridge** — control lights as DMX fixtures from any lighting console
- **Terminal UI** — dashboard, scene designer, and performance console with faders and hotkeys
- **CLI with 35+ commands** — scan, control, batch, interactive REPL, presets, and more

## Supported Lights

Verified on hardware:

| Light | Type | Protocol |
|-------|------|----------|
| PL60C | Bi-color panel | Infinity |
| TL120 RGB-2 | RGB tube | Infinity |

Should work with any Neewer light that advertises as `NW-*` or `NEEWER-*` over BLE. The model database includes entries for GL1C, RGB168, CL124, RGB660, TL60 RGB, TL90C, RL45C, and many others.

## Installation

Requires Python 3.10+ and a Bluetooth adapter.

```bash
# Core library — protocol, config, scenes, audio framework
pip install neewer-ble

# With audio-reactive scene support (numpy + sounddevice)
pip install neewer-ble[audio]

# With sACN/DMX bridge
pip install neewer-ble[sacn]

# With terminal UI
pip install neewer-ble[tui]

# Everything
pip install neewer-ble[full]
```

For development:

```bash
git clone https://github.com/amattas/neewer-sacn.git
cd neewer-sacn
pip install -e ".[dev]"
pytest
```

## Quick Start

### CLI

```bash
# Discover lights
neewer scan

# Control by scan index, partial name, or "all"
neewer on --light 0
neewer cct --light NW-2022 --brightness 80 --temp 5600
neewer hsi --light all --hue 240 --sat 100 --brightness 80

# Built-in effects
neewer scene --light 0 --effect "cop car" --brightness 50 --speed 7

# Gel filters (ROSCO and LEE libraries)
neewer gel --light 0 --brightness 80 --gel R02

# RGB and CIE xy color
neewer rgbcw --light 0 --brightness 80 --red 255 --green 0 --blue 128
neewer xy --light 0 --brightness 80 --x 0.3127 --y 0.3290

# Named colors
neewer color --light 0 --color "warm white"
neewer color --light 0 --color "#FF6B35"

# Interactive REPL session
neewer interactive --light 0
```

### Python API

```python
import asyncio
from bleak import BleakClient
from neewer import protocol

# Build BLE command packets
mac = protocol.parse_mac("D4:ED:61:C3:B7:00")
pkt = protocol.cmd_cct(mac, brightness=80, temp_k=5600)
# → bytes ready to write to the BLE characteristic

# Auto-detect protocol from device name
proto = protocol.detect_protocol("NW-20220016&00323204")
pkt = protocol.build_cct(proto, mac, brightness=80, temp_k=5600)

# Channel-addressed group control
network_id = 0xDEADBEEF
pkt = protocol.ch_cmd_cct(network_id, ch=1, brightness=80, temp_k=5600)

# Scenes
pkt = protocol.cmd_scene(mac, effect_id=1, brightness=50, speed=7)

# All protocol functions are pure — they return bytes, no side effects
```

### Configuration & Groups

```bash
# Create a named configuration
neewer config create studio
neewer config add-light studio key --light 0
neewer config add-light studio fill --light 1
neewer config use studio

# Control by config
neewer --config studio cct --brightness 80 --temp 5600

# Channel grouping (single BLE connection controls all)
neewer channel assign --light 0 --ch 1
neewer channel assign --light 1 --ch 2
neewer cct --light 0 --ch 1 --brightness 80 --temp 5600
```

### Scenes

Scripted YAML scenes with fade interpolation:

```yaml
# scenes/sunset-fade.yaml
name: Sunset Fade
duration: 30s
loop: true
targets: [all]

steps:
  - at: 0s
    all: {mode: cct, brightness: 80, temp: 5600}
  - at: 10s
    all: {fade: {brightness: 60, temp: 3200}}
  - at: 20s
    all: {fade: {brightness: 20, temp: 2700}}
  - at: 28s
    all: {fade: {brightness: 80, temp: 5600}}
```

Generative Python scenes with audio reactivity:

```python
# scenes/rainbow_chase.py
name = "Rainbow Chase"
fps = 20

def render(tick, lights, params, audio=None):
    speed = params.get("speed", 2)
    result = {}
    for i, role in enumerate(lights):
        hue = (tick * speed + i * 60) % 360
        result[role] = {"mode": "hsi", "hue": hue, "sat": 100, "brightness": 70}
    return result
```

```bash
neewer scene-list
neewer scene-run scenes/sunset-fade.yaml --config studio
neewer scene-run scenes/beat_flash.py --config studio --mic
```

### sACN / DMX Bridge

Control lights as standard DMX fixtures from any sACN-compatible lighting console:

```bash
neewer-sacn                         # auto-scan, universe 1
neewer-sacn -u 2 -s 11             # universe 2, start at channel 11
neewer-sacn --channel-mode          # single BLE connection for all lights
```

Each light gets a 10-channel DMX footprint:

| Offset | Name | CCT mode | HSI mode | FX mode | GEL mode |
|--------|------|----------|----------|---------|----------|
| 0 | Mode | 0-31 | 32-63 | 64-95 | 96-127 |
| 1 | Dimmer | 0-255 | 0-255 | 0-255 | 0-255 |
| 2 | Param A | CCT temp | Hue | Effect ID | Gel index |
| 3 | Param B | G/M | Saturation | Speed | — |
| 4-9 | FX subs | — | — | Effect params | — |

### Terminal UI

```bash
neewer tui
```

Three views:
- **Dashboard** — live light cards with status
- **Scene Designer** — timeline viewer
- **Performance Console** — faders, hotkeys, audio meter

## Protocol

Full specification in [`docs/protocol.md`](docs/protocol.md). Three variants auto-detected from the BLE device name:

| Variant | Envelope | Detection |
|---------|----------|-----------|
| **Infinity** | `78 TAG SIZE MAC[6] SUBTAG PARAMS CS` | `NW-` prefix |
| **Extended Legacy** | `78 TAG LEN PARAMS CS` (18 effects, GM) | Model DB |
| **Legacy** | `78 TAG LEN PARAMS CS` (9 effects) | Model DB |

Infinity lights also support channel-addressed commands for group broadcast without individual connections:

```
78 TAG SIZE NETID[4] CH SUBTAG PARAMS CS
```

## Project Structure

```
src/neewer/
    protocol.py      # BLE protocol builders, model DB, CLI
    config.py        # Multi-group configuration management
    sacn.py          # sACN/E1.31 DMX bridge
    scenes.py        # Scene engine (YAML + generative Python)
    tui.py           # Textual terminal UI
    audio.py         # Audio analysis (RMS, FFT, beat detection)
tests/               # 178 pytest tests
docs/protocol.md     # Full protocol specification
scenes/              # Example scenes (YAML + Python)
examples/            # Batch command files
```

## Development

```bash
# Install with all deps + pytest
pip install -e ".[dev]"

# Run tests
pytest

# Run specific test module
pytest tests/test_protocol.py -v
```

## Prior Art

- [NeewerLite](https://github.com/keefo/NeewerLite) — macOS Swift app
- [NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) — Python control tool

## License

This project is for interoperability research purposes under DMCA exemptions.
