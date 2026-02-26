# Design: Custom Scenes, TUI, and Sound-Reactive Lighting

## Overview

Three features that build on the existing Neewer BLE control tool:

1. **Phase A — Configurations + Scene Engine**: persistent multi-group configs with role-based light assignments, scripted YAML scenes, and generative Python scenes
2. **Phase B — Terminal UI**: Textual-based TUI with dashboard, scene designer, and performance console views
3. **Phase C — Audio-Reactive Scenes**: pluggable audio source abstraction with mic input, beat detection, frequency band analysis

## Architecture: Sibling Modules

New files alongside existing `neewer.py` and `neewer_sacn.py`. No refactoring of working code. Each module stays within 500-800 lines.

```
neewer.py              # protocol + CLI (add thin dispatch for new subcommands)
neewer_config.py       # config data model, persistence, channel management
neewer_scenes.py       # scene engine (scripted YAML + generative Python)
neewer_audio.py        # mic analysis, AudioFrame abstraction
neewer_tui.py          # Textual TUI app
neewer_sacn.py         # existing sACN bridge (unchanged)
scenes/                # example scene files
```

## Phase A: Configuration System (`neewer_config.py`)

### Data Model

A **config** maps role names to lights, with optional state snapshots. Stored in `.neewer_config.json` (separate from `.neewer_cache.json`).

```json
{
  "active": "studio",
  "configs": {
    "studio": {
      "network_id": "0x7A3F0012",
      "lights": {
        "key":  {"device": "NW-2022", "alias": "PL60C-1"},
        "fill": {"device": "NW-2024", "alias": "TL120"},
        "hair": {"device": "0", "alias": "TL90C"}
      },
      "channels": {
        "key": 1,
        "fill": 2,
        "hair": 3
      },
      "snapshots": {
        "interview": {
          "key":  {"mode": "cct", "brightness": 80, "temp": 5600, "gm": 0},
          "fill": {"mode": "cct", "brightness": 40, "temp": 4200, "gm": 5},
          "hair": {"mode": "hsi", "hue": 220, "sat": 60, "brightness": 30}
        },
        "product": {
          "key":  {"mode": "cct", "brightness": 100, "temp": 5000, "gm": 0},
          "fill": {"mode": "cct", "brightness": 70, "temp": 5000, "gm": 0}
        }
      }
    }
  }
}
```

### Channel Management

- Each config gets a randomly generated 4-byte NETID on creation (collision isolation)
- Roles auto-assigned to channels (role 1 → ch 1, role 2 → ch 2)
- On `config activate`: connects to each light, sends channel-assign with the config's NETID, designates first light as relay
- Channel query (TAG 0x96) used to detect existing assignments and warn on conflicts
- `neewer.py connections` shows all BLE connections and channel assignments

### CLI Commands

```bash
# Config management
neewer.py config create <name>
neewer.py config delete <name>
neewer.py config list
neewer.py config show <name>
neewer.py config use <name>              # set active
neewer.py config active                  # show current active

# Light assignments
neewer.py config add-light <config> <role> --light <device>
neewer.py config remove-light <config> <role>

# Snapshots
neewer.py config snapshot save <config> <snapshot>
neewer.py config snapshot recall <config> <snapshot>
neewer.py config snapshot delete <config> <snapshot>

# Targeting
neewer.py --config studio cct --brightness 80 --temp 5600       # all lights
neewer.py --config studio:key cct --brightness 80 --temp 5600   # specific role
neewer.py cct --brightness 80 --temp 5600                       # uses active config

# Connection visibility
neewer.py connections
neewer.py connections --scan              # scan + show all channel assignments
```

## Phase A: Scene Engine (`neewer_scenes.py`)

### Scripted Scenes (YAML)

Timed sequences with per-role choreography:

```yaml
name: Sunset Fade
duration: 30s
loop: true
targets: [key, fill, hair]

steps:
  - at: 0s
    key:  {mode: cct, brightness: 80, temp: 5600}
    fill: {mode: cct, brightness: 40, temp: 4200}
    hair: {mode: hsi, hue: 30, sat: 80, brightness: 30}
  - at: 10s
    key:  {fade: {brightness: 60, temp: 3200}}
    fill: {fade: {brightness: 30, temp: 3000}}
  - at: 20s
    all:  {fade: {brightness: 20, temp: 2700}}
  - at: 28s
    hair: {scene: hue-pulse, brightness: 50, speed: 3}
```

Between steps, `fade` targets interpolate at ~20fps. Non-fade steps are instant.

### Generative Scenes (Python)

Python files with a `render()` callback:

```python
name = "Rainbow Chase"
fps = 20

def render(tick, lights, params, audio=None):
    offset = params.get("speed", 2)
    result = {}
    for i, role in enumerate(lights):
        hue = (tick * offset + i * 60) % 360
        result[role] = {"mode": "hsi", "hue": hue, "sat": 100,
                        "brightness": params.get("brightness", 70)}
    return result
```

The `audio` parameter is `None` unless `--mic` is passed. When present, it's an `AudioFrame` object.

### Scene Runner

1. Load scene (YAML or .py)
2. Resolve targets against active config → device addresses + channels
3. Connect to relay light (single BLE connection via channel mode)
4. Run timeline/render loop
5. Clean exit on Ctrl+C

### CLI

```bash
neewer.py scene-run <file> [--config <name>] [--mic] [--device <id>]
neewer.py scene-list                                # list scenes/ directory
```

### Example Scenes

- `scenes/sunset-fade.yaml` — warm fade-down
- `scenes/rainbow_chase.py` — generative hue rotation
- `scenes/campfire.py` — generative warm flicker
- `scenes/alert.yaml` — red strobe sequence
- `scenes/interview.yaml` — multi-light studio preset

## Phase B: Terminal UI (`neewer_tui.py`)

### Framework

Textual (>=0.80.0). Works over SSH for RPi use.

### Launch

```bash
neewer.py tui
python neewer_tui.py
```

### Connection Architecture

Single BLE connection to relay light. All commands via `ch_cmd_*` channel-addressed functions. Direct connections only for per-light queries (battery, status).

### Three Views

**Dashboard (home screen)**
- Light cards showing state per role (name, mode, brightness, temp/hue, battery)
- Config switcher dropdown
- Snapshot recall buttons
- Scene launcher
- Quick on/off toggle per light

**Scene Designer**
- Visual timeline with per-role tracks
- Slider-based parameter editing for each step
- Live preview on connected lights
- Save/export to YAML

**Performance Console**
- Vertical faders for brightness/temp per role + master
- Hotkey-triggered scenes and effects (F1-F12)
- Running scene display with pause/stop
- Audio level meter when mic active (Phase C integration)

### Status Bar

Always visible at bottom:

```
BLE: 1 conn | Net: 0x7A3F0012 | ch1: PL60C-1 (relay) | ch2: TL120 | ch3: TL90C
```

## Phase C: Audio System (`neewer_audio.py`)

### AudioFrame

```python
class AudioFrame:
    amplitude: float      # 0.0-1.0, RMS volume
    beat: bool            # True on detected beat
    bands: list[float]    # [bass, mid, treble] each 0.0-1.0
    bpm: float            # estimated BPM (rolling average)
```

### Pluggable Sources

```python
class AudioSource:
    async def start(self): ...
    async def read_frame(self) -> AudioFrame: ...
    async def stop(self): ...
```

Phase C implements `MicSource` (sounddevice). Future sources:
- `LoopbackSource` — system audio (macOS CoreAudio, Linux PipeWire)
- `LineInSource` — ALSA line-in
- `StreamSource` — network audio (Snapcast, Icecast)

All sources produce the same `AudioFrame`. Scene code never knows the source.

### Analysis Pipeline

```
Raw PCM → windowed buffer (2048 samples) → RMS → amplitude
                                         → onset detection → beat → bpm
                                         → FFT → 3-band split → bands
```

- Beat detection: energy threshold vs rolling average
- Frequency bands: bass (<300Hz), mid (300-2kHz), treble (>2kHz)
- Dependencies: `numpy`, `sounddevice` (both optional, only imported when used)

### CLI

```bash
neewer.py scene-run scenes/beat_flash.py --mic [--device <id>]
neewer.py audio-test --mic [--device <id>]      # diagnostic: live levels
```

### Built-in Audio Scenes

- `scenes/sound_pulse.py` — brightness follows amplitude
- `scenes/beat_flash.py` — color changes on beat
- `scenes/frequency_map.py` — bass→brightness, mid→saturation, treble→hue

## Dependencies

```
# requirements.txt (core)
bleak>=0.21.0
sacn>=1.9.0
pyyaml>=6.0

# requirements-tui.txt (optional)
textual>=0.80.0

# requirements-audio.txt (optional)
numpy>=1.24.0
sounddevice>=0.4.6
```

Optional deps checked at import time with clear install instructions on failure.

## File Size Budget

| File | Est. Lines | Phase |
|------|-----------|-------|
| `neewer_config.py` | ~500 | A |
| `neewer_scenes.py` | ~600 | A |
| `test_config.py` | ~300 | A |
| `neewer_tui.py` | ~800 | B |
| `neewer_audio.py` | ~500 | C |
| `test_audio.py` | ~200 | C |
| CLI additions to `neewer.py` | ~80 | A |
| `scenes/` (6 examples) | ~200 total | A+C |

## Key Design Decisions

1. **Sibling modules, not package** — matches existing `neewer.py` + `neewer_sacn.py` pattern
2. **Single BLE connection via channel mode** — relay light broadcasts to all, no connection scaling issues
3. **Random NETID per config** — prevents channel collisions between configs/users
4. **Audio source abstraction** — `AudioFrame` interface decouples scenes from mic/loopback/stream sources
5. **Optional deps** — TUI and audio imports are lazy with clear error messages
6. **500-800 lines per file** — enforced file size budget
