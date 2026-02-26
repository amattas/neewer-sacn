#!/usr/bin/env python3
"""Neewer Infinity BLE Protocol Control Tool

Controls Neewer LED lights using the Infinity BLE protocol.
Supports: TL60 RGB, TL90C, TL120C, PL60C, RL45C
"""

import argparse
import asyncio
import json
import os
import platform
import sys

from bleak import BleakClient, BleakScanner

# BLE UUIDs
SERVICE_UUID = "69400001-B5A3-F393-E0A9-E50E24DCCA99"
WRITE_UUID = "69400002-B5A3-F393-E0A9-E50E24DCCA99"
NOTIFY_UUID = "69400003-B5A3-F393-E0A9-E50E24DCCA99"

# Infinity protocol tags
PREFIX = 0x78
TAG_POWER = 0x8D
TAG_HSI = 0x8F
TAG_CCT = 0x90
TAG_SCENE = 0x91
SUBTAG_POWER = 0x81
SUBTAG_HSI = 0x86
SUBTAG_CCT = 0x87
SUBTAG_SCENE = 0x8B

# Legacy query commands (no MAC envelope needed)
CMD_READ_REQUEST = bytes([0x78, 0x84, 0x00, 0xFC])
CMD_POWER_QUERY = bytes([0x78, 0x85, 0x00, 0xFD])

# Infinity query tag (discovered via live protocol testing on PL60C)
TAG_QUERY = 0x8E

# 18 scene effects (Infinity + Extended Legacy protocols)
EFFECTS = {
    "lightning": 0x01,
    "paparazzi": 0x02,
    "defective-bulb": 0x03,
    "explosion": 0x04,
    "welding": 0x05,
    "cct-flash": 0x06,
    "hue-flash": 0x07,
    "cct-pulse": 0x08,
    "hue-pulse": 0x09,
    "cop-car": 0x0A,
    "candlelight": 0x0B,
    "hue-loop": 0x0C,
    "cct-loop": 0x0D,
    "int-loop": 0x0E,
    "tv-screen": 0x0F,
    "firework": 0x10,
    "party": 0x11,
    "music": 0x12,
}

# Effect parameter definitions: list of (name, byte_count)
# 'hue' params are 2 bytes (16-bit LE), everything else is 1 byte
EFFECT_PARAMS = {
    0x01: [("brr", 1), ("cct", 1), ("speed", 1)],
    0x02: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x03: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x04: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1), ("sparks", 1)],
    0x05: [("brr", 1), ("brr_hi", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x06: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x07: [("brr", 1), ("hue", 2), ("sat", 1), ("speed", 1)],
    0x08: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x09: [("brr", 1), ("hue", 2), ("sat", 1), ("speed", 1)],
    0x0A: [("brr", 1), ("color", 1), ("speed", 1)],
    0x0B: [("brr", 1), ("brr_hi", 1), ("cct", 1), ("gm", 1), ("speed", 1), ("sparks", 1)],
    0x0C: [("brr", 1), ("hue", 2), ("hue_hi", 2), ("speed", 1)],
    0x0D: [("brr", 1), ("cct", 1), ("cct_hi", 1), ("speed", 1)],
    # INT Loop has 2 sub-modes: CCT (submode=0) and HSI (submode=1).
    # The sub-mode byte goes right after the effect ID.
    # CCT: [0x0E, 0x00, brr, brr_hi, 0x00, 0x00, cct, speed]
    # HSI: [0x0E, 0x01, brr, brr_hi, hue_lo, hue_hi, 0x00, speed]
    # Handled specially in _build_int_loop_params().
    0x0E: [("brr", 1), ("brr_hi", 1), ("hue", 2), ("speed", 1)],
    0x0F: [("brr", 1), ("cct", 1), ("gm", 1), ("speed", 1)],
    0x10: [("brr", 1), ("color", 1), ("speed", 1), ("sparks", 1)],
    0x11: [("brr", 1), ("color", 1), ("speed", 1)],
    0x12: [("brr", 1)],
}

SCENE_DEFAULTS = {
    "brr": 50, "brr_hi": 100, "cct": 56, "cct_hi": 56,
    "gm": 50, "hue": 0, "hue_hi": 180, "sat": 100,
    "color": 0, "speed": 5, "sparks": 5,
}

# Named colors → (hue, saturation) for quick HSI access
NAMED_COLORS = {
    "red": (0, 100),
    "orange": (30, 100),
    "yellow": (60, 100),
    "chartreuse": (90, 100),
    "green": (120, 100),
    "spring": (150, 100),
    "cyan": (180, 100),
    "azure": (210, 100),
    "blue": (240, 100),
    "violet": (270, 100),
    "magenta": (300, 100),
    "rose": (330, 100),
    "white": (0, 0),
    "warm-white": (30, 15),
    "cool-white": (210, 10),
    "pink": (340, 60),
    "lavender": (260, 40),
    "amber": (38, 100),
    "teal": (170, 80),
    "coral": (16, 80),
    "gold": (45, 90),
    "sky": (200, 60),
    "mint": (150, 50),
    "peach": (25, 50),
    "salmon": (10, 60),
    "indigo": (250, 90),
}

# GEL presets: map gel name → (temp_K, gm) or (hue, sat) for colored gels
# From the DMX specs: 20 ROSCO + 20 LEE presets
# Approximated to CCT+GM where possible; colored gels use HSI
# Format: "name": ("cct", temp_K, gm) or ("hsi", hue, sat)
GEL_PRESETS = {
    # ROSCO presets
    "R38":   ("cct", 3200, -5),    # Rose (warm pink tint)
    "R44":   ("cct", 3200, -15),   # Medium Rose (stronger pink)
    "R65":   ("cct", 5600, 0),     # Daylight Blue (CTO to daylight)
    "R92":   ("cct", 3200, -30),   # Flesh Pink
    "R93":   ("cct", 3200, -8),    # Rose (lighter)
    "G152":  ("cct", 4200, 5),     # Pale Gold (warm gold)
    "G220":  ("cct", 3800, 0),     # White Frost (diffusion, neutral)
    "G325":  ("cct", 3200, -3),    # Light Rose
    "G342":  ("cct", 3200, -20),   # Rose Pink
    "G720":  ("cct", 5000, 10),    # Pale Green (slight green tint)
    "G910":  ("cct", 3200, 0),     # Light CTO (warm)
    "G990":  ("cct", 5600, 0),     # Full CTB (cool blue)
    "E128":  ("cct", 3200, -10),   # Bright Pink
    "E153":  ("cct", 4400, 5),     # Pale Gold (amber)
    "E156":  ("cct", 3500, -5),    # Chocolate (warm pink-brown)
    "E165":  ("cct", 5600, 15),    # Daylight Frost (daylight + green)
    "E723":  ("cct", 3500, 0),     # Virgin Amber
    "E724":  ("cct", 3200, 5),     # Ocean Blue
    "R4590": ("cct", 3200, 0),     # CalColor 90 (warm)
    "R9406": ("cct", 3200, -5),    # Rose (classic)
    # LEE presets
    "L002":  ("cct", 3200, -5),    # Rose Pink
    "L007":  ("cct", 4000, 5),     # Pale Yellow
    "L036":  ("cct", 3200, 10),    # Medium Pink (warm-green tint)
    "L088":  ("hsi", 120, 40),     # Lime Green
    "L110":  ("cct", 3200, -15),   # Middle Rose
    "L115":  ("cct", 3000, 0),     # Peacock Blue (deep blue warm)
    "L117":  ("cct", 5600, 0),     # Steel Blue
    "L128":  ("cct", 3200, -10),   # Bright Pink
    "L131":  ("cct", 3800, 10),    # Marine Blue
    "L148":  ("cct", 3200, -5),    # Bright Rose
    "L241":  ("cct", 9000, 15),    # Fluorescent 5700K (green spike)
    "L243":  ("cct", 3200, 20),    # Fluorescent 3600K (green spike)
    "L500":  ("cct", 4500, 0),     # Double CTO + frost
    "L701":  ("cct", 3200, 0),     # Zircon Warm Amber
    "L703":  ("cct", 3200, -3),    # Zircon Warm Rose
    "L723":  ("cct", 3500, 0),     # Virgin Amber
    "L724":  ("cct", 3200, 0),     # Ocean Blue
    "L729":  ("cct", 5200, 0),     # Scuba Blue
    "L765":  ("cct", 5600, 0),     # Lee Blue
    "L790":  ("cct", 2700, 0),     # Moroccan Frost (very warm)
}

# Light source presets: standard industry light types
# From NeewerLite lights.json sourcePatterns. These are CCT presets with
# characteristic color temperatures for different real-world light sources.
LIGHT_SOURCES = {
    "tungsten":       (2700, 0, "Tungsten lamp (~2700K)"),
    "studio-bulb":    (2800, 0, "Studio bulb (~2800K)"),
    "modeling":       (2900, 0, "Modeling lights (~2900K)"),
    "halogen":        (3800, 0, "White halogen (~3800K)"),
    "horizon":        (4500, 0, "Horizon daylight (~4500K)"),
    "daylight":       (5000, 0, "Daylight (~5000K)"),
    "dysprosic":      (5100, 0, "Dysprosic lamp (~5100K)"),
    "hmi":            (5500, 0, "HMI 6000 (~5500K)"),
    "xenon":          (5700, 0, "Xenon short-arc lamp (~5700K)"),
    "sunlight":       (6000, 0, "Sunlight (~6000K)"),
    "cloudy":         (6500, 0, "Cloudy sky (~6500K)"),
}

# Model database: product_code → (name, cct_min, cct_max, supports_rgb, protocol)
# protocol: "infinity", "extended", "legacy"
# Compiled from NeewerLite Swift + NeewerLite-Python + live testing
MODEL_DB = {
    # Infinity protocol lights (NW- prefix, use MAC envelope)
    "20210036": ("TL60 RGB", 2500, 10000, True, "infinity"),
    "20230064": ("TL60 RGB", 2500, 10000, True, "infinity"),
    "20220016": ("PL60C", 2500, 10000, False, "infinity"),
    "20230031": ("TL120C", 2500, 10000, False, "infinity"),
    "20240047": ("TL120 RGB", 2500, 10000, True, "infinity"),
    "20210018": ("BH-30S RGB", 2500, 10000, True, "infinity"),
    "20230021": ("BH-30S RGB", 2500, 10000, True, "infinity"),
    "20200015": ("RGB1", 3200, 5600, True, "infinity"),
    "20200037": ("SL90", 2500, 10000, True, "infinity"),
    "20200049": ("RGB1200", 2500, 10000, True, "infinity"),
    "20230025": ("RGB1200", 2500, 10000, True, "infinity"),
    "20230092": ("RGB1200", 2500, 10000, True, "infinity"),
    "20210007": ("RGB C80", 2500, 10000, True, "infinity"),
    "20210012": ("CB60 RGB", 2500, 6500, True, "infinity"),
    "20210034": ("MS60B", 2700, 6500, False, "infinity"),
    "20210035": ("MS60C", 2500, 10000, False, "infinity"),
    "20210037": ("CB200B", 3200, 5600, False, "infinity"),
    "20220014": ("CB60B", 2500, 10000, False, "infinity"),
    "20220035": ("MS150B", 2700, 6500, False, "infinity"),
    "20220041": ("AS600B", 2700, 6500, False, "infinity"),
    "20220043": ("FS150B", 2700, 6500, False, "infinity"),
    "20220046": ("RP19C", 2500, 10000, False, "infinity"),
    "20220051": ("CB100C", 2500, 10000, False, "infinity"),
    "20220055": ("CB300B", 2700, 6500, False, "infinity"),
    "20220057": ("SL90 Pro", 2500, 10000, True, "infinity"),
    "20230050": ("FS230 5600K", 5600, 5600, False, "infinity"),
    "20230051": ("FS230B", 2700, 6500, False, "infinity"),
    "20230052": ("FS150 5600K", 5600, 5600, False, "infinity"),
    "20230080": ("MS60C", 2500, 10000, False, "infinity"),
    "20230108": ("HB80C", 2500, 7500, True, "infinity"),
}

# Name-based model lookup (for NEEWER- prefix or post-resolution names)
# name_fragment → (cct_min, cct_max, supports_rgb, protocol)
MODEL_BY_NAME = {
    "TL60": (2500, 10000, True, "infinity"),
    "TL90": (2500, 10000, False, "infinity"),
    "TL120C": (2500, 10000, False, "infinity"),
    "TL97C": (2500, 10000, False, "infinity"),
    "PL60C": (2500, 10000, False, "infinity"),
    "RL45": (2500, 10000, False, "infinity"),
    "BH-30S": (2500, 10000, True, "infinity"),
    "BH40C": (2500, 10000, True, "infinity"),
    "SL90": (2500, 10000, True, "infinity"),
    "RGB1200": (2500, 10000, True, "infinity"),
    "RGB1000": (2500, 10000, True, "infinity"),
    "RGB C80": (2500, 10000, True, "infinity"),
    "RGB800": (2500, 10000, True, "infinity"),
    "RGB512": (2500, 10000, True, "infinity"),
    "RGB140": (2500, 10000, True, "infinity"),
    "RGB1": (3200, 5600, True, "infinity"),
    "MS60": (2700, 6500, False, "infinity"),
    "MS150": (2700, 6500, False, "infinity"),
    "CB60": (2500, 6500, True, "infinity"),
    "CB100C": (2500, 10000, False, "infinity"),
    "CB200": (3200, 5600, False, "infinity"),
    "CB300": (2700, 6500, False, "infinity"),
    "HB80C": (2500, 7500, True, "infinity"),
    "HS60B": (2700, 6500, False, "infinity"),
    "FS150": (2700, 6500, False, "infinity"),
    "FS230": (2700, 6500, False, "infinity"),
    "AS600": (2700, 6500, False, "infinity"),
    "CB120B": (2700, 6500, False, "infinity"),
    "CB200C": (2500, 10000, False, "infinity"),
    "CB300C": (2500, 10000, False, "infinity"),
    "MS150C": (2500, 10000, False, "infinity"),
    "GR18C": (2500, 10000, True, "infinity"),
    "TL21C": (2500, 10000, False, "infinity"),
    "TL40": (2900, 7000, False, "infinity"),
    "VL67C": (2500, 10000, False, "infinity"),
    "Q200": (2500, 10000, False, "infinity"),
    "AP150C": (2700, 6500, False, "infinity"),
    "RP19C": (2500, 10000, False, "infinity"),
    # Extended legacy (protocol commands but no MAC envelope)
    "CL124": (2500, 10000, True, "extended"),
    "RGB168": (2500, 8500, True, "extended"),
    "GL1C": (2900, 7000, True, "extended"),
    # Legacy (old protocol)
    "GL1": (2900, 7000, False, "legacy"),
    "RGB660": (3200, 5600, True, "legacy"),
    "RGB530": (3200, 5600, True, "legacy"),
    "RGB480": (3200, 5600, True, "legacy"),
    "RGB450": (3200, 5600, True, "legacy"),
    "RGB650": (3200, 5600, True, "legacy"),
    "RGB190": (3200, 5600, True, "legacy"),
    "RGB176": (3200, 5600, True, "legacy"),
    "RGB18": (3200, 5600, True, "legacy"),
    "RGB960": (3200, 5600, True, "legacy"),
    "SNL": (3200, 5600, False, "legacy"),
    "SRP": (3200, 5600, False, "legacy"),
    "NL140": (3200, 5600, False, "legacy"),
    "Apollo": (5600, 5600, False, "legacy"),
}


def detect_model_info(ble_name):
    """Detect model info from BLE device name.

    Returns: (model_name, cct_min, cct_max, supports_rgb, protocol)
    or None if unknown.
    """
    if not ble_name:
        return None

    # NW- prefix: extract product code (e.g., "NW-20220016&776A0500")
    if ble_name.startswith("NW-") and "&" in ble_name:
        code = ble_name[3:ble_name.index("&")]
        if code in MODEL_DB:
            return MODEL_DB[code]
        # Unknown product code, but NW- prefix → assume Infinity
        return (f"Unknown ({code})", 2500, 10000, False, "infinity")

    # NW- without & separator
    if ble_name.startswith("NW-"):
        code = ble_name[3:]
        # Try numeric product code
        if code.isdigit() and code in MODEL_DB:
            return MODEL_DB[code]
        # Try name match on the rest
        for frag, info in MODEL_BY_NAME.items():
            if frag in code:
                return (frag,) + info
        return (f"Unknown NW ({code})", 2500, 10000, False, "infinity")

    # NEEWER- prefix (e.g., "NEEWER-GL1C", "NEEWER-RGB660 PRO")
    if ble_name.startswith("NEEWER-"):
        model_part = ble_name[7:]
    elif ble_name.startswith("NEEWER "):
        model_part = ble_name[7:]
    elif ble_name.startswith("NWR-"):
        model_part = ble_name[4:]
    else:
        model_part = ble_name

    # Match against name DB (longest match first to avoid GL1 matching GL1C)
    for frag in sorted(MODEL_BY_NAME.keys(), key=len, reverse=True):
        if frag in model_part:
            return (frag,) + MODEL_BY_NAME[frag]

    return None


def detect_protocol(ble_name):
    """Detect the protocol variant for a device.

    Returns: "infinity", "extended", or "legacy"
    """
    info = detect_model_info(ble_name)
    if info:
        return info[4]
    # Default: NW- prefix → infinity, anything else → legacy
    if ble_name and ble_name.startswith("NW-"):
        return "infinity"
    return "legacy"


# Persistent cache file (MAC addresses + light aliases)
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".neewer_cache.json")
_cache = {"macs": {}, "lights": {}}
_mac_override = None  # Set via --mac CLI flag


def _load_cache():
    global _cache
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
            # Migrate old format (flat dict of name→mac) to new format
            if "macs" not in data:
                _cache = {"macs": data, "lights": {}}
            else:
                _cache = data
    except (FileNotFoundError, json.JSONDecodeError):
        _cache = {"macs": {}, "lights": {}}


def _save_cache():
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(_cache, f, indent=2)
    except OSError:
        pass


def _resolve_light_alias(identifier):
    """Resolve a light alias/name/index to (address, device_name).

    Accepts:
    - "all" → ("all", None)
    - "group:name" → ("group:name", None) — resolved by run_command
    - Group name from cache → ("group:name", None)
    - Full BLE UUID/MAC address (passed through)
    - Scan index (e.g., "0", "1")
    - Light name from cache (e.g., "NW-20220016&776A0500" or partial match)
    """
    if identifier.lower() == "all":
        return "all", None

    # Check for group:name syntax
    if identifier.lower().startswith("group:"):
        return identifier.lower(), None

    # Check if it's a saved group name
    groups = _cache.get("groups", {})
    if identifier.lower() in groups:
        return f"group:{identifier.lower()}", None

    lights = _cache.get("lights", {})

    # Try as scan index first (numbers 0-99) — uses most recent scan order
    try:
        idx = int(identifier)
        if 0 <= idx < 100:
            scan_order = _cache.get("scan_order", list(lights.keys()))
            if 0 <= idx < len(scan_order):
                name = scan_order[idx]
                if name in lights:
                    return lights[name]["address"], name
            # Fallback: index into all cached lights
            indexed = list(lights.items())
            if 0 <= idx < len(indexed):
                name, info = indexed[idx]
                return info["address"], name
    except ValueError:
        pass

    # Check cache for light name/alias (substring match, case-insensitive)
    for name, info in lights.items():
        if identifier.lower() in name.lower():
            return info["address"], name

    # Pass through as raw address
    return identifier, None


def _save_scan_results(lights):
    """Cache scan results for alias resolution.

    Deduplicates by product code — if the same light advertises on multiple
    BLE UUIDs (common on PL60C), only the scan winner is cached.
    """
    # Remove stale entries for product codes being rescanned
    new_codes = set()
    for device, adv in lights:
        name = device.name or adv.local_name or device.address
        new_codes.add(_product_code(name))
    existing = _cache.get("lights", {})
    for cached_name in list(existing.keys()):
        if _product_code(cached_name) in new_codes:
            del existing[cached_name]

    scan_order = []
    for device, adv in lights:
        name = device.name or adv.local_name or device.address
        entry = {
            "address": device.address,
            "rssi": adv.rssi,
        }
        info = detect_model_info(name)
        if info:
            entry["model"] = info[0]
            entry["protocol"] = info[4]
            entry["cct_range"] = [info[1], info[2]]
            entry["rgb"] = info[3]
        else:
            entry["protocol"] = detect_protocol(name)
        _cache.setdefault("lights", {})[name] = entry
        scan_order.append(name)
    _cache["scan_order"] = scan_order
    _save_cache()


# --- Protocol helpers ---

def calc_checksum(data):
    return sum(data) & 0xFF


def parse_mac(mac_str):
    parts = mac_str.split(":")
    if len(parts) != 6:
        raise ValueError(f"Invalid MAC address: {mac_str}")
    return [int(p, 16) for p in parts]


def infinity_cmd(tag, mac_bytes, subtag, params):
    size = len(params) + 7  # 6 MAC bytes + 1 subtag
    data = [PREFIX, tag, size] + mac_bytes + [subtag] + params
    data.append(calc_checksum(data))
    return bytes(data)


def fmt_hex(data):
    return " ".join(f"{b:02X}" for b in data)


# --- Command builders ---

def cmd_power(mac_bytes, on=True):
    return infinity_cmd(TAG_POWER, mac_bytes, SUBTAG_POWER, [0x01 if on else 0x02])


def cmd_cct(mac_bytes, brightness, temp_k, gm=0):
    brightness = max(0, min(100, brightness))
    cct_val = max(25, min(100, temp_k // 100))
    gm_byte = max(0, min(100, gm + 50))
    return infinity_cmd(TAG_CCT, mac_bytes, SUBTAG_CCT,
                        [brightness, cct_val, gm_byte, 0x04])


def cmd_hsi(mac_bytes, hue, sat, brightness):
    hue = max(0, min(359, hue))
    sat = max(0, min(100, sat))
    brightness = max(0, min(100, brightness))
    hue_lo = hue & 0xFF
    hue_hi = (hue >> 8) & 0xFF
    return infinity_cmd(TAG_HSI, mac_bytes, SUBTAG_HSI,
                        [hue_lo, hue_hi, sat, brightness, 0x00])


def cmd_gel(mac_bytes, brightness, gel_name):
    """Convert a gel preset to a CCT or HSI command."""
    preset = GEL_PRESETS.get(gel_name)
    if not preset:
        raise ValueError(f"Unknown gel: {gel_name}")
    if preset[0] == "cct":
        _, temp_k, gm = preset
        return cmd_cct(mac_bytes, brightness, temp_k, gm)
    else:
        _, hue, sat = preset
        return cmd_hsi(mac_bytes, hue, sat, brightness)


def cmd_query(mac_bytes):
    """Infinity power status query. Response: 78 04 08 {MAC} 02 {01=ON|02=OFF} CS"""
    return infinity_cmd(TAG_QUERY, mac_bytes, 0x84, [0x00])


# Infinity device info tag (discovered via live protocol testing on PL60C)
TAG_DEVICE_INFO = 0x9E  # Returns model name + firmware info
TAG_HW_INFO = 0x95      # Returns hardware revision byte via TAG 0x05 response
TAG_CHANNEL = 0x96      # Returns channel/group assignment byte


def cmd_device_info(mac_bytes):
    """Query device info. Response: 78 08 10 {MAC} {data} {model_ascii} CS"""
    return infinity_cmd(TAG_DEVICE_INFO, mac_bytes, 0x00, [])


def cmd_hw_info(mac_bytes):
    """Query hardware info. Triggers TAG 0x05 response on some models."""
    return infinity_cmd(TAG_HW_INFO, mac_bytes, 0x00, [])


def cmd_channel(mac_bytes):
    """Query channel/group assignment. Returns single byte (0=unassigned)."""
    return infinity_cmd(TAG_CHANNEL, mac_bytes, 0x00, [])


def parse_device_info(data):
    """Parse device info response from TAG 0x9E.

    Response format: 78 08 SIZE {MAC[6]} {fields...} {model_ascii} CS
    Returns dict with model, firmware fields, etc. or None.
    """
    if len(data) < 12 or data[0] != PREFIX or data[1] != 0x08:
        return None
    mac = data[3:9]
    payload = data[9:-1]  # between MAC and checksum
    # Last bytes are ASCII model name (scan backwards for printable chars)
    model_start = len(payload)
    for i in range(len(payload) - 1, -1, -1):
        if 32 <= payload[i] < 127:
            model_start = i
        else:
            break
    model = bytes(payload[model_start:]).decode("ascii", errors="replace") if model_start < len(payload) else ""
    fields = list(payload[:model_start])
    result = {
        "mac": ":".join(f"{b:02X}" for b in mac),
        "model": model,
        "fields": fields,
    }
    # Parse firmware version: first 3 fields are major.minor.patch
    if len(fields) >= 3:
        result["firmware"] = f"{fields[0]}.{fields[1]}.{fields[2]}"
    if len(fields) >= 6:
        result["build"] = f"{fields[3]}.{fields[4]}.{fields[5]}"
    return result


# --- Legacy protocol commands (for older lights without Infinity/MAC) ---

def legacy_cmd(tag, params):
    data = [PREFIX, tag, len(params)] + params
    data.append(calc_checksum(data))
    return bytes(data)


def cmd_power_legacy(on=True):
    return legacy_cmd(0x81, [0x01 if on else 0x02])


def cmd_cct_legacy(brightness, temp_k):
    brightness = max(0, min(100, brightness))
    cct_val = max(32, min(56, temp_k // 100))
    return legacy_cmd(0x87, [brightness, cct_val])


def cmd_cct_split(brightness, temp_k):
    """Split CCT for CCT-only legacy lights (TAGs 0x82/0x83).

    Some older CCT-only lights (SNL, Apollo, NL140) expect brightness and
    color temperature as two separate packets instead of one combined 0x87 packet.
    Returns a tuple of (brightness_pkt, cct_pkt).
    """
    brightness = max(0, min(100, brightness))
    cct_val = max(27, min(65, temp_k // 100))
    return (legacy_cmd(0x82, [brightness]), legacy_cmd(0x83, [cct_val]))


def cmd_hsi_legacy(hue, sat, brightness):
    hue = max(0, min(359, hue))
    sat = max(0, min(100, sat))
    brightness = max(0, min(100, brightness))
    return legacy_cmd(0x86, [hue & 0xFF, (hue >> 8) & 0xFF, sat, brightness])


def cmd_scene_legacy(brightness, effect_id):
    brightness = max(0, min(100, brightness))
    effect_id = max(1, min(9, effect_id))
    return legacy_cmd(0x88, [brightness, effect_id])


# --- Extended legacy protocol (GL1C, RGB62 — no MAC, but 17 effects + GM) ---
# Discovered from BLE packet captures in NeewerLite research.md

def cmd_cct_extended(brightness, temp_k, gm=0):
    brightness = max(0, min(100, brightness))
    cct_val = max(25, min(100, temp_k // 100))
    gm_byte = max(0, min(100, gm + 50))
    return legacy_cmd(0x87, [brightness, cct_val, gm_byte])


def cmd_scene_extended(effect_id, brightness=50, speed=5, **kwargs):
    """Extended legacy scene: same params as Infinity but no MAC envelope."""
    param_defs = EFFECT_PARAMS.get(effect_id)
    if not param_defs:
        raise ValueError(f"Unknown effect ID: 0x{effect_id:02X}")

    if effect_id == 0x0E:
        params = _build_int_loop_params(brightness, speed, **kwargs)
        return legacy_cmd(0x8B, [effect_id] + params)

    overrides = _clamp_scene_kwargs(brightness, speed, kwargs)
    params = _build_scene_params(param_defs, overrides)
    return legacy_cmd(0x8B, [effect_id] + params)


def build_power(protocol, mac_bytes, on):
    if protocol == "infinity":
        return cmd_power(mac_bytes, on=on)
    return cmd_power_legacy(on=on)


def build_cct(protocol, mac_bytes, brightness, temp_k, gm=0):
    if protocol == "infinity":
        return cmd_cct(mac_bytes, brightness, temp_k, gm)
    if protocol == "extended":
        return cmd_cct_extended(brightness, temp_k, gm)
    return cmd_cct_legacy(brightness, temp_k)


def build_hsi(protocol, mac_bytes, hue, sat, brightness):
    if protocol == "infinity":
        return cmd_hsi(mac_bytes, hue, sat, brightness)
    return cmd_hsi_legacy(hue, sat, brightness)


def build_scene(protocol, mac_bytes, effect_id, brightness=50, speed=5, **kwargs):
    if protocol == "infinity":
        return cmd_scene(mac_bytes, effect_id, brightness, speed, **kwargs)
    if protocol == "extended":
        return cmd_scene_extended(effect_id, brightness, speed, **kwargs)
    return cmd_scene_legacy(brightness, effect_id)


def build_gel(protocol, mac_bytes, brightness, gel_name):
    if protocol == "infinity":
        return cmd_gel(mac_bytes, brightness, gel_name)
    preset = GEL_PRESETS.get(gel_name)
    if not preset:
        raise ValueError(f"Unknown gel: {gel_name}")
    if preset[0] == "cct":
        _, temp_k, gm = preset
        return build_cct(protocol, mac_bytes, brightness, temp_k, gm)
    else:
        _, hue, sat = preset
        return build_hsi(protocol, mac_bytes, hue, sat, brightness)


def _clamp_scene_kwargs(brightness, speed, kwargs):
    """Clamp scene parameters to valid ranges and return overrides dict."""
    overrides = {
        "brr": max(0, min(100, brightness)),
        "speed": max(1, min(10, speed)),
    }
    if "temp" in kwargs and kwargs["temp"] is not None:
        overrides["cct"] = max(25, min(100, kwargs["temp"] // 100))
    if "temp_hi" in kwargs and kwargs["temp_hi"] is not None:
        overrides["cct_hi"] = max(25, min(100, kwargs["temp_hi"] // 100))
    if "hue" in kwargs and kwargs["hue"] is not None:
        overrides["hue"] = max(0, min(359, kwargs["hue"]))
    if "hue_hi" in kwargs and kwargs["hue_hi"] is not None:
        overrides["hue_hi"] = max(0, min(359, kwargs["hue_hi"]))
    if "sat" in kwargs and kwargs["sat"] is not None:
        overrides["sat"] = max(0, min(100, kwargs["sat"]))
    if "gm" in kwargs and kwargs["gm"] is not None:
        overrides["gm"] = max(0, min(100, kwargs["gm"] + 50))
    if "color" in kwargs and kwargs["color"] is not None:
        overrides["color"] = max(0, min(4, kwargs["color"]))
    if "sparks" in kwargs and kwargs["sparks"] is not None:
        overrides["sparks"] = max(1, min(10, kwargs["sparks"]))
    if "brr_hi" in kwargs and kwargs["brr_hi"] is not None:
        overrides["brr_hi"] = max(0, min(100, kwargs["brr_hi"]))
    return overrides


def _build_scene_params(param_defs, overrides):
    """Build the parameter byte list from definitions and overrides."""
    params = []
    for name, byte_count in param_defs:
        val = overrides.get(name, SCENE_DEFAULTS[name])
        if byte_count == 2:
            params.append(val & 0xFF)
            params.append((val >> 8) & 0xFF)
        else:
            params.append(val)
    return params


def _build_int_loop_params(brightness, speed, **kwargs):
    """Build INT Loop (0x0E) params with sub-mode selection.

    CCT sub-mode: [0x00, brr, brr_hi, 0x00, 0x00, cct, speed]
    HSI sub-mode: [0x01, brr, brr_hi, hue_lo, hue_hi, 0x00, speed]
    Uses HSI if 'hue' is set, otherwise CCT.
    """
    brr = max(0, min(100, brightness))
    brr_hi = max(0, min(100, kwargs.get("brr_hi", 100) if kwargs.get("brr_hi") is not None else 100))
    spd = max(1, min(10, speed))

    if "hue" in kwargs and kwargs["hue"] is not None:
        # HSI sub-mode
        hue = max(0, min(359, kwargs["hue"]))
        return [0x01, brr, brr_hi, hue & 0xFF, (hue >> 8) & 0xFF, 0x00, spd]
    else:
        # CCT sub-mode
        cct = max(25, min(100, (kwargs.get("temp") or 5600) // 100))
        return [0x00, brr, brr_hi, 0x00, 0x00, cct, spd]


def cmd_scene(mac_bytes, effect_id, brightness=50, speed=5, **kwargs):
    param_defs = EFFECT_PARAMS.get(effect_id)
    if not param_defs:
        raise ValueError(f"Unknown effect ID: 0x{effect_id:02X}")

    # INT Loop (0x0E) has special sub-mode encoding
    if effect_id == 0x0E:
        params = _build_int_loop_params(brightness, speed, **kwargs)
        return infinity_cmd(TAG_SCENE, mac_bytes, SUBTAG_SCENE, [effect_id] + params)

    overrides = _clamp_scene_kwargs(brightness, speed, kwargs)
    params = _build_scene_params(param_defs, overrides)
    return infinity_cmd(TAG_SCENE, mac_bytes, SUBTAG_SCENE, [effect_id] + params)


# --- MAC address resolution ---
# On macOS, BLE devices only appear in system_profiler while actively connected.
# We must resolve the MAC while holding a BLE connection.

async def _resolve_mac_from_profiler(device_name):
    """Resolve hardware MAC from system_profiler (async, non-blocking)."""
    macs = _cache.get("macs", {})
    if device_name in macs:
        return macs[device_name]

    if platform.system() != "Darwin":
        return None

    try:
        # Use async subprocess to avoid blocking the event loop during BLE operations
        proc = await asyncio.create_subprocess_exec(
            "system_profiler", "SPBluetoothDataType",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode("utf-8", errors="replace")
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return None

    # Parse output: find device section then extract Address field
    search = device_name + ":"
    name_pos = output.find(search)
    if name_pos == -1:
        name_pos = output.find(device_name)
    if name_pos == -1:
        return None

    section = output[name_pos : name_pos + 500]
    addr_pos = section.find("Address: ")
    if addr_pos == -1:
        return None

    mac_str = section[addr_pos + 9 : addr_pos + 26]
    if len(mac_str) == 17 and mac_str.count(":") == 5:
        _cache.setdefault("macs", {})[device_name] = mac_str
        _save_cache()
        return mac_str
    return None


# --- BLE operations ---

def _product_code(ble_name):
    """Extract product code from BLE name for dedup (e.g., 'NW-20220016' from 'NW-20220016&776A0500')."""
    if ble_name and ble_name.startswith("NW-") and "&" in ble_name:
        return ble_name[:ble_name.index("&")]
    return ble_name


async def scan_lights(timeout=5.0, quiet=False):
    if not quiet:
        print(f"Scanning for Neewer lights ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    lights = []
    seen_codes = {}  # product_code → index in lights list
    for addr, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        if not ("NEEWER" in name.upper() or name.upper().startswith("NW-")):
            continue
        code = _product_code(name)
        if code in seen_codes:
            # Same physical light on multiple UUIDs — keep stronger RSSI
            existing_idx = seen_codes[code]
            _, existing_adv = lights[existing_idx]
            if adv.rssi > existing_adv.rssi:
                lights[existing_idx] = (device, adv)
        else:
            seen_codes[code] = len(lights)
            lights.append((device, adv))
    return lights


async def resolve_light(address):
    """Quick scan to find device name for a given address."""
    devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
    for addr, (device, adv) in devices.items():
        if device.address == address:
            return device.name or adv.local_name or None
    return None


def _resolve_proto(proto_arg, device_name):
    """Resolve 'auto' protocol to a concrete variant using device name."""
    if proto_arg != "auto":
        return proto_arg
    if device_name:
        return detect_protocol(device_name)
    return "infinity"


async def connect_and_run(address, device_name, callback, verbose=False, retries=2, proto_arg="auto"):
    """Connect to a light, resolve MAC and protocol, then run callback.

    callback signature: async (client, mac_bytes, verbose, proto)
    """
    # Auto-discover device name if not provided
    if not device_name and platform.system() == "Darwin":
        if verbose:
            print("Auto-discovering device name...")
        device_name = await resolve_light(address)
        if verbose and device_name:
            print(f"Found device: {device_name}")

    # Resolve protocol per-device
    proto = _resolve_proto(proto_arg, device_name)

    last_err = None
    for attempt in range(retries + 1):
        try:
            async with BleakClient(address, timeout=10.0) as client:
                if not client.is_connected:
                    raise ConnectionError("Failed to connect")

                # Resolve hardware MAC while connected (required on macOS)
                mac_str = _mac_override
                if not mac_str and platform.system() == "Darwin":
                    if device_name:
                        mac_str = await _resolve_mac_from_profiler(device_name)
                    if not mac_str:
                        # PL60c (and likely other Infinity lights) accept commands
                        # without MAC validation. Use zeros as fallback.
                        mac_str = "00:00:00:00:00:00"
                        if verbose:
                            print(f"WARNING: Could not resolve MAC, using fallback {mac_str}")
                elif not mac_str:
                    mac_str = address

                try:
                    mac_bytes = parse_mac(mac_str)
                except ValueError:
                    raise ConnectionError(f"Invalid MAC address: {mac_str}")
                if verbose:
                    print(f"Hardware MAC: {mac_str}")
                    print(f"Protocol: {proto}")

                await callback(client, mac_bytes, verbose, proto)
                return  # Success
        except Exception as e:
            last_err = e
            if attempt < retries:
                if verbose:
                    print(f"  Connection attempt {attempt + 1} failed: {e}, retrying...")
                await asyncio.sleep(0.5)

    raise ConnectionError(f"Failed to connect to {address}: {last_err}")


async def connect_and_run_all(callback, verbose=False, proto_arg="auto"):
    """Scan for all lights and send command to each."""
    lights = await scan_lights(timeout=5.0)
    if not lights:
        print("No Neewer lights found.")
        return

    # Deduplicate by name (same light may advertise on multiple UUIDs)
    unique = {}
    for device, adv in lights:
        name = device.name or adv.local_name or device.address
        if name not in unique:
            unique[name] = (device, adv)

    print(f"Sending to {len(unique)} light(s)...")
    for name, (device, adv) in unique.items():
        print(f"  -> {name} ({device.address})")
        try:
            await connect_and_run(device.address, name, callback, verbose, proto_arg=proto_arg)
        except Exception as e:
            print(f"  ERROR: {e}")


# Session state: remembers last-used values for defaults
_session_state = {"bri": 80, "temp": 5000, "hue": 0, "sat": 100, "gm": 0}


async def exec_session_cmd(client, mac_bytes, proto, line, device_name=None):
    """Execute a single REPL/batch command within an active BLE session.

    Returns: "quit" to stop, "continue" to skip to next line, None for normal flow.
    """
    # Strip inline comments (# at end of line)
    if " #" in line:
        line = line[:line.index(" #")]
    parts = line.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower()
    try:
        return await _exec_session_cmd_inner(client, mac_bytes, proto, cmd, parts, device_name)
    except ValueError as e:
        print(f"  Invalid value: {e}")
        return "continue"


async def _exec_session_cmd_inner(client, mac_bytes, proto, cmd, parts, device_name):

    if cmd in ("quit", "exit", "q"):
        return "quit"
    elif cmd == "sleep" and len(parts) >= 2:
        dur = float(parts[1])
        if dur <= 0:
            print("  Sleep duration must be > 0")
            return "continue"
        await asyncio.sleep(dur)
    elif cmd == "on":
        pkt = build_power(proto, mac_bytes, on=True)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print("  Power ON")
    elif cmd == "off":
        pkt = build_power(proto, mac_bytes, on=False)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print("  Power OFF")
    elif cmd == "cct" and len(parts) >= 3:
        b, t = int(parts[1]), int(parts[2])
        g = int(parts[3]) if len(parts) > 3 else 0
        pkt = build_cct(proto, mac_bytes, b, t, g)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        _session_state.update(bri=b, temp=t, gm=g)
        print(f"  CCT: bri={b}%, temp={t}K, gm={g}")
    elif cmd == "hsi" and len(parts) >= 4:
        h, s, b = int(parts[1]), int(parts[2]), int(parts[3])
        pkt = build_hsi(proto, mac_bytes, h, s, b)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        _session_state.update(bri=b, hue=h, sat=s)
        print(f"  HSI: hue={h}, sat={s}%, bri={b}%")
    elif cmd == "scene" and len(parts) >= 2:
        eid = resolve_effect(parts[1])
        if eid is None:
            return "continue"
        b = int(parts[2]) if len(parts) > 2 else 50
        sp = int(parts[3]) if len(parts) > 3 else 5
        # Parse key=value pairs for effect-specific params
        kwargs = {}
        for p in parts[4:] if len(parts) > 4 else []:
            if "=" in p:
                k, v = p.split("=", 1)
                try:
                    kwargs[k] = int(float(v))
                except ValueError:
                    print(f"  Bad kwarg value: {k}={v}")
                    return "continue"
        off_pkt = build_power(proto, mac_bytes, on=False)
        on_pkt = build_power(proto, mac_bytes, on=True)
        s_pkt = build_scene(proto, mac_bytes, eid, b, sp, **kwargs)
        await client.write_gatt_char(WRITE_UUID, off_pkt, response=False)
        await asyncio.sleep(0.05)
        await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)
        await asyncio.sleep(0.05)
        await client.write_gatt_char(WRITE_UUID, s_pkt, response=False)
        name = next((k for k, v in EFFECTS.items() if v == eid), "?")
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        print(f"  Scene: {name}, bri={b}%, speed={sp}" + (f" ({extra})" if extra else ""))
    elif cmd == "gel" and len(parts) >= 3:
        gn = resolve_gel(parts[1])
        if not gn:
            print(f"  Unknown gel: {parts[1]}")
            return "continue"
        b = int(parts[2])
        pkt = build_gel(proto, mac_bytes, b, gn)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  GEL: {gn}, bri={b}%")
    elif cmd == "source" and len(parts) >= 2:
        sn = parts[1].lower()
        if sn not in LIGHT_SOURCES:
            print(f"  Unknown source: {parts[1]}")
            return "continue"
        stemp, sgm, sdesc = LIGHT_SOURCES[sn]
        b = int(parts[2]) if len(parts) > 2 else 80
        pkt = build_cct(proto, mac_bytes, b, stemp, sgm)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  Source: {sdesc}, bri={b}%")
    elif cmd == "color" and len(parts) >= 2:
        cval = resolve_color(parts[1])
        if not cval:
            print(f"  Unknown color: {parts[1]}")
            return "continue"
        h, s = cval
        b = int(parts[2]) if len(parts) > 2 else 80
        pkt = build_hsi(proto, mac_bytes, h, s, b)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  Color: {parts[1]} (hue={h}, sat={s}%), bri={b}%")
    elif cmd == "bri" and len(parts) >= 2:
        b = int(parts[1])
        t = int(parts[2]) if len(parts) > 2 else 5000
        pkt = build_cct(proto, mac_bytes, b, t)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  Brightness: {b}% (CCT {t}K)")
    elif cmd == "temp" and len(parts) >= 2:
        t = int(parts[1])
        b = int(parts[2]) if len(parts) > 2 else 80
        gm = int(parts[3]) if len(parts) > 3 else 0
        pkt = build_cct(proto, mac_bytes, b, t, gm)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  Temp: {t}K, bri={b}%, gm={gm}")
    elif cmd == "hue" and len(parts) >= 2:
        h = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 100
        b = int(parts[3]) if len(parts) > 3 else 80
        pkt = build_hsi(proto, mac_bytes, h, s, b)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        print(f"  Hue: {h}, sat={s}%, bri={b}%")
    elif cmd == "fade" and len(parts) >= 3:
        bri1, bri2 = int(parts[1]), int(parts[2])
        temp = int(parts[3]) if len(parts) > 3 else 5000
        dur = float(parts[4]) if len(parts) > 4 else 2.0
        steps = max(5, int(dur * 20))
        print(f"  Fading {bri1}% -> {bri2}% ({dur}s)...")
        for i in range(steps + 1):
            t = i / steps
            bri = int(bri1 + (bri2 - bri1) * t)
            pkt = build_cct(proto, mac_bytes, bri, temp)
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
            await asyncio.sleep(dur / steps)
        print(f"  Fade complete: {bri2}%")
    elif cmd == "fade-color" and len(parts) >= 3:
        # fade-color <from> <to> [bri] [seconds]
        c1 = resolve_color(parts[1])
        c2 = resolve_color(parts[2])
        if not c1:
            print(f"  Unknown color: {parts[1]}")
            return "continue"
        if not c2:
            print(f"  Unknown color: {parts[2]}")
            return "continue"
        b = int(parts[3]) if len(parts) > 3 else 80
        dur = float(parts[4]) if len(parts) > 4 else 3.0
        h1, s1 = c1
        h2, s2 = c2
        # Shortest-path hue interpolation (wraps around 360)
        diff = (h2 - h1 + 540) % 360 - 180  # range -180..+179
        steps = max(5, int(dur * 20))
        print(f"  Color fade: {parts[1]} -> {parts[2]}, bri={b}% ({dur}s)...")
        for i in range(steps + 1):
            t = i / steps
            hue = int(h1 + diff * t) % 360
            sat = int(s1 + (s2 - s1) * t)
            pkt = build_hsi(proto, mac_bytes, hue, sat, b)
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
            await asyncio.sleep(dur / steps)
        print(f"  Color fade complete: {parts[2]}")
    elif cmd == "fade-temp" and len(parts) >= 3:
        # fade-temp <temp1> <temp2> [bri] [seconds]
        t1, t2 = int(parts[1]), int(parts[2])
        b = int(parts[3]) if len(parts) > 3 else 80
        dur = float(parts[4]) if len(parts) > 4 else 3.0
        steps = max(5, int(dur * 20))
        print(f"  Temp fade: {t1}K -> {t2}K, bri={b}% ({dur}s)...")
        for i in range(steps + 1):
            t = i / steps
            temp = int(t1 + (t2 - t1) * t)
            pkt = build_cct(proto, mac_bytes, b, temp)
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
            await asyncio.sleep(dur / steps)
        print(f"  Temp fade complete: {t2}K")
    elif cmd == "fade-hue" and len(parts) >= 3:
        # fade-hue <hue1> <hue2> [sat] [bri] [seconds]
        h1, h2 = int(parts[1]), int(parts[2])
        s = int(parts[3]) if len(parts) > 3 else 100
        b = int(parts[4]) if len(parts) > 4 else 80
        dur = float(parts[5]) if len(parts) > 5 else 3.0
        # Shortest-path hue interpolation (wraps around 360)
        hdiff = (h2 - h1 + 540) % 360 - 180
        steps = max(5, int(dur * 20))
        print(f"  Hue fade: {h1} -> {h2}, sat={s}%, bri={b}% ({dur}s)...")
        for i in range(steps + 1):
            t = i / steps
            hue = int(h1 + hdiff * t) % 360
            pkt = build_hsi(proto, mac_bytes, hue, s, b)
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
            await asyncio.sleep(dur / steps)
        print(f"  Hue fade complete: {h2}")
    elif cmd == "strobe" and len(parts) >= 1:
        # strobe [bri] [rate_hz] [count] [color|temp]
        b = int(parts[1]) if len(parts) > 1 else 100
        rate = float(parts[2]) if len(parts) > 2 else 4.0
        count = int(parts[3]) if len(parts) > 3 else 10
        color_or_temp = parts[4] if len(parts) > 4 else None
        half = 0.5 / rate
        # Determine on-packet
        if color_or_temp:
            cval = resolve_color(color_or_temp)
            if cval:
                on_pkt = build_hsi(proto, mac_bytes, cval[0], cval[1], b)
            else:
                try:
                    temp = int(color_or_temp)
                    on_pkt = build_cct(proto, mac_bytes, b, temp)
                except ValueError:
                    print(f"  Unknown color/temp: {color_or_temp}")
                    return "continue"
        else:
            on_pkt = build_cct(proto, mac_bytes, b, 5600)
        off_pkt = build_power(proto, mac_bytes, on=False)
        on_power = build_power(proto, mac_bytes, on=True)
        print(f"  Strobe: {count}x at {rate}Hz, bri={b}%...")
        for i in range(count):
            await client.write_gatt_char(WRITE_UUID, on_power, response=False)
            await asyncio.sleep(0.02)
            await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)
            await asyncio.sleep(half)
            await client.write_gatt_char(WRITE_UUID, off_pkt, response=False)
            await asyncio.sleep(half)
        await client.write_gatt_char(WRITE_UUID, on_power, response=False)
        await asyncio.sleep(0.02)
        await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)
        print(f"  Strobe complete.")
    elif cmd == "random":
        import random
        b = int(parts[1]) if len(parts) > 1 else 80
        h = random.randint(0, 359)
        s = random.randint(60, 100)
        pkt = build_hsi(proto, mac_bytes, h, s, b)
        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        name = ""
        # Find closest named color
        min_dist = 999
        for cn, (ch, cs) in NAMED_COLORS.items():
            dist = min(abs(h - ch), 360 - abs(h - ch))
            if dist < min_dist:
                min_dist = dist
                name = cn
        print(f"  Random: hue={h}, sat={s}%, bri={b}% (near {name})")
    elif cmd == "raw" and len(parts) >= 2:
        hex_str = "".join(parts[1:]).replace(":", "")
        try:
            raw_bytes = bytes.fromhex(hex_str)
            await client.write_gatt_char(WRITE_UUID, raw_bytes, response=False)
            print(f"  TX: {fmt_hex(raw_bytes)}")
        except ValueError:
            print(f"  Invalid hex: {' '.join(parts[1:])}")
    elif cmd == "preset" and len(parts) >= 2:
        presets = _cache.get("presets", {})
        subcmd = parts[1]
        # preset save <name> cct <bri> <temp> [gm]
        # preset save <name> hsi <hue> <sat> <bri>
        # preset delete <name>
        # preset <name>  (recall)
        if subcmd == "save" and len(parts) >= 5:
            pn = parts[2]
            mode = parts[3].lower()
            if mode == "cct" and len(parts) >= 6:
                entry = {"mode": "cct", "brightness": int(parts[4]),
                         "temp": int(parts[5]),
                         "gm": int(parts[6]) if len(parts) > 6 else 0}
            elif mode == "hsi" and len(parts) >= 7:
                entry = {"mode": "hsi", "brightness": int(parts[6]),
                         "hue": int(parts[4]), "sat": int(parts[5])}
            elif mode == "scene" and len(parts) >= 5:
                entry = {"mode": "scene", "effect": parts[4],
                         "brightness": int(parts[5]) if len(parts) > 5 else 50,
                         "speed": int(parts[6]) if len(parts) > 6 else 5}
            else:
                print("  Usage: preset save <name> cct <bri> <temp> [gm]")
                print("         preset save <name> hsi <hue> <sat> <bri>")
                print("         preset save <name> scene <effect> [bri] [speed]")
                return "continue"
            presets[pn] = entry
            _cache["presets"] = presets
            _save_cache()
            print(f"  Saved preset '{pn}': {entry}")
            return None
        elif subcmd == "delete" and len(parts) >= 3:
            pn = parts[2]
            if pn in presets:
                del presets[pn]
                _cache["presets"] = presets
                _save_cache()
                print(f"  Deleted preset '{pn}'")
            else:
                print(f"  Unknown preset: {pn}")
            return None
        elif subcmd == "list":
            if not presets:
                print("  No saved presets.")
            else:
                for pn, p in sorted(presets.items()):
                    if p["mode"] == "cct":
                        print(f"  {pn:<16s}  CCT bri={p['brightness']}% temp={p.get('temp', '?')}K gm={p.get('gm', 0)}")
                    elif p["mode"] == "hsi":
                        print(f"  {pn:<16s}  HSI bri={p['brightness']}% hue={p.get('hue', '?')} sat={p.get('sat', '?')}%")
                    elif p["mode"] == "scene":
                        print(f"  {pn:<16s}  Scene {p.get('effect', '?')} bri={p['brightness']}% speed={p.get('speed', 5)}")
                    else:
                        print(f"  {pn:<16s}  {p['mode']} bri={p['brightness']}%")
            return None
        pn = subcmd
        if pn not in presets:
            print(f"  Unknown preset: {pn}")
            return "continue"
        p = presets[pn]
        if p["mode"] == "cct":
            pkt = build_cct(proto, mac_bytes, p["brightness"], p.get("temp", 5000), p.get("gm", 0))
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        elif p["mode"] == "hsi":
            pkt = build_hsi(proto, mac_bytes, p.get("hue", 0), p.get("sat", 100), p["brightness"])
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)
        elif p["mode"] == "scene":
            eid = resolve_effect(p.get("effect", "cop-car"))
            if eid is None:
                return "continue"
            off = build_power(proto, mac_bytes, on=False)
            on = build_power(proto, mac_bytes, on=True)
            s = build_scene(proto, mac_bytes, eid, p["brightness"], p.get("speed", 5))
            await client.write_gatt_char(WRITE_UUID, off, response=False)
            await asyncio.sleep(0.05)
            await client.write_gatt_char(WRITE_UUID, on, response=False)
            await asyncio.sleep(0.05)
            await client.write_gatt_char(WRITE_UUID, s, response=False)
        print(f"  Preset '{pn}': {p}")
    elif cmd == "status":
        status_result = {}
        sbuf = bytearray()
        def _on_status(sender, data):
            nonlocal sbuf
            if sbuf:
                sbuf.extend(data)
                expected = sbuf[2] + 4 if len(sbuf) >= 3 else 999
                if len(sbuf) < expected:
                    return
                data = bytes(sbuf)
                sbuf = bytearray()
            elif len(data) >= 3 and data[0] == PREFIX:
                expected = data[2] + 4
                if len(data) < expected:
                    sbuf.extend(data)
                    return
            if len(data) >= 4:
                if data[1] == 0x04 and len(data) >= 12 and data[9] == 0x02:
                    status_result["power"] = "ON" if data[10] == 0x01 else "STANDBY"
                elif data[1] == 0x05 and len(data) >= 11:
                    status_result["hw_byte"] = f"0x{data[9]:02X}"
                elif data[1] == 0x06 and len(data) >= 4:
                    status_result["channel"] = data[3]
                elif data[1] == 0x08:
                    info = parse_device_info(data)
                    if info:
                        status_result["model"] = info["model"]
                        if "firmware" in info:
                            status_result["firmware"] = info["firmware"]
                elif data[1] == 0x02:
                    status_result["power"] = "ON" if data[3] == 0x01 else "STANDBY"
        await client.start_notify(NOTIFY_UUID, _on_status)
        await asyncio.sleep(0.3)
        if proto == "infinity":
            await client.write_gatt_char(WRITE_UUID, cmd_query(mac_bytes), response=False)
            await asyncio.sleep(0.3)
            await client.write_gatt_char(WRITE_UUID, cmd_device_info(mac_bytes), response=False)
            await asyncio.sleep(0.3)
            await client.write_gatt_char(WRITE_UUID, cmd_channel(mac_bytes), response=False)
            await asyncio.sleep(0.3)
            await client.write_gatt_char(WRITE_UUID, cmd_hw_info(mac_bytes), response=False)
        else:
            await client.write_gatt_char(WRITE_UUID, CMD_POWER_QUERY, response=False)
            await asyncio.sleep(0.3)
            await client.write_gatt_char(WRITE_UUID, CMD_READ_REQUEST, response=False)
        await asyncio.sleep(1.0)
        await client.stop_notify(NOTIFY_UUID)
        if status_result:
            for k, v in status_result.items():
                print(f"  {k}: {v}")
        else:
            print("  No response")
    elif cmd == "effects":
        for ename, eid in sorted(EFFECTS.items(), key=lambda x: x[1]):
            params = EFFECT_PARAMS.get(eid, [])
            extra = [p[0] for p in params if p[0] not in ("brr", "speed")]
            extra_str = f"  [{', '.join(extra)}]" if extra else ""
            print(f"  {eid:2d}  {ename:<20s}{extra_str}")
    elif cmd == "gels":
        for gname in sorted(GEL_PRESETS.keys()):
            preset = GEL_PRESETS[gname]
            if preset[0] == "cct":
                print(f"  {gname:<8s}  CCT {preset[1]}K GM={preset[2]:+d}")
            else:
                print(f"  {gname:<8s}  HSI hue={preset[1]} sat={preset[2]}%")
    elif cmd == "sources":
        for sn in sorted(LIGHT_SOURCES.keys()):
            stemp, sgm, sdesc = LIGHT_SOURCES[sn]
            print(f"  {sn:<14s}  {stemp:5d}K  GM={sgm:+3d}  {sdesc}")
    elif cmd == "colors":
        for cn in sorted(NAMED_COLORS.keys()):
            ch, cs = NAMED_COLORS[cn]
            print(f"  {cn:<14s}  hue={ch:3d}  sat={cs:3d}%")
    elif cmd == "presets":
        presets = _cache.get("presets", {})
        if not presets:
            print("  No saved presets.")
        else:
            for pn, p in sorted(presets.items()):
                if p["mode"] == "cct":
                    print(f"  {pn:<16s}  CCT bri={p['brightness']}% temp={p.get('temp', '?')}K gm={p.get('gm', 0)}")
                elif p["mode"] == "hsi":
                    print(f"  {pn:<16s}  HSI bri={p['brightness']}% hue={p.get('hue', '?')} sat={p.get('sat', '?')}%")
                elif p["mode"] == "scene":
                    print(f"  {pn:<16s}  Scene {p.get('effect', '?')} bri={p['brightness']}% speed={p.get('speed', 5)}")
                else:
                    print(f"  {pn:<16s}  {p['mode']} bri={p['brightness']}%")
    elif cmd == "group" and len(parts) >= 2:
        groups = _cache.get("groups", {})
        subcmd = parts[1]
        if subcmd == "save" and len(parts) >= 4:
            gn = parts[2].lower()
            members = parts[3:]
            groups[gn] = members
            _cache["groups"] = groups
            _save_cache()
            print(f"  Saved group '{gn}': {', '.join(members)}")
        elif subcmd == "delete" and len(parts) >= 3:
            gn = parts[2].lower()
            if gn in groups:
                del groups[gn]
                _cache["groups"] = groups
                _save_cache()
                print(f"  Deleted group '{gn}'")
            else:
                print(f"  Unknown group: {gn}")
        elif subcmd == "list":
            if not groups:
                print("  No saved groups.")
            else:
                for gn, members in sorted(groups.items()):
                    print(f"  {gn:<16s}  {', '.join(members)}")
        else:
            print("  Usage: group save <name> <light1> <light2> ...")
            print("         group delete <name>")
            print("         group list")
    elif cmd == "groups":
        groups = _cache.get("groups", {})
        if not groups:
            print("  No saved groups.")
        else:
            for gn, members in sorted(groups.items()):
                print(f"  {gn:<16s}  {', '.join(members)}")
    elif cmd == "info":
        dn = device_name or "unknown"
        info = detect_model_info(dn)
        print(f"  Device: {dn}")
        print(f"  Protocol: {proto}")
        if info:
            print(f"  Model: {info[0]}")
            print(f"  CCT: {info[1]}-{info[2]}K")
            print(f"  RGB: {'yes' if info[3] else 'no'}")
    elif cmd == "demo":
        b = int(parts[1]) if len(parts) > 1 else 60
        print(f"  Demo at {b}% brightness. Press Ctrl+C to stop.\n")
        try:
            # CCT sweep
            print("  CCT: warm 2500K -> cool 10000K")
            for temp in [2500, 3200, 4000, 5000, 6500, 8000, 10000]:
                await client.write_gatt_char(WRITE_UUID,
                    build_cct(proto, mac_bytes, b, temp), response=False)
                await asyncio.sleep(1.5)
            # HSI color wheel
            print("  HSI: color wheel")
            names = {0: "red", 60: "yellow", 120: "green",
                     180: "cyan", 240: "blue", 300: "magenta"}
            for hue in [0, 60, 120, 180, 240, 300]:
                await client.write_gatt_char(WRITE_UUID,
                    build_hsi(proto, mac_bytes, hue, 100, b), response=False)
                await asyncio.sleep(1.5)
            # Scene effects
            for name, eid in [("cop-car", 0x0A), ("candlelight", 0x0B),
                               ("lightning", 0x01), ("hue-loop", 0x0C)]:
                print(f"  Scene: {name}")
                await client.write_gatt_char(WRITE_UUID,
                    build_power(proto, mac_bytes, on=False), response=False)
                await asyncio.sleep(0.05)
                await client.write_gatt_char(WRITE_UUID,
                    build_power(proto, mac_bytes, on=True), response=False)
                await asyncio.sleep(0.05)
                await client.write_gatt_char(WRITE_UUID,
                    build_scene(proto, mac_bytes, eid, b, 5), response=False)
                await asyncio.sleep(3.0)
            # Return to neutral
            print("  Returning to neutral white...")
            await client.write_gatt_char(WRITE_UUID,
                build_cct(proto, mac_bytes, b, 5000), response=False)
        except KeyboardInterrupt:
            print("\n  Stopped. Returning to neutral...")
            await client.write_gatt_char(WRITE_UUID,
                build_cct(proto, mac_bytes, b, 5000), response=False)
        print("  Demo done.")
    elif cmd == "help":
        print("  on / off / bri / temp / hue / cct / hsi / scene / gel / source / color / random / raw")
        print("  fade / fade-color / fade-temp / fade-hue / strobe / demo / info")
        print("  preset <name> / preset save/delete/list")
        print("  group save/delete/list / groups")
        print("  sleep <s> / status / effects / gels / sources / colors / presets / quit")
    else:
        # Check for known commands with missing args
        usage = {
            "cct": "cct <brightness> <temp> [gm]",
            "hsi": "hsi <hue> <sat> <brightness>",
            "scene": "scene <effect> [brightness] [speed] [key=val ...]",
            "gel": "gel <name> <brightness>",
            "source": "source <name> [brightness]",
            "color": "color <name> [brightness]",
            "fade": "fade <bri1> <bri2> [temp] [seconds]",
            "fade-color": "fade-color <color1> <color2> [brightness] [seconds]",
            "fade-temp": "fade-temp <temp1> <temp2> [brightness] [seconds]",
            "fade-hue": "fade-hue <hue1> <hue2> [sat] [brightness] [seconds]",
            "temp": "temp <temp> [brightness] [gm]",
            "hue": "hue <hue> [sat] [brightness]",
            "sleep": "sleep <seconds>",
            "raw": "raw <hex bytes>",
            "group": "group save <name> <light1> ... | group delete <name> | group list",
            "preset": "preset <name> | preset save <name> cct/hsi ... | preset delete <name>",
        }
        if cmd in usage:
            print(f"  Usage: {usage[cmd]}")
        else:
            print(f"  Unknown command: {cmd}")
            print("  Type 'help' for available commands")
    return None


# --- CLI ---

def _add_light_args(p):
    p.add_argument("--light", required=True,
                   help="BLE address/UUID, or 'all' for all lights")
    p.add_argument("--name", help="BLE device name (from scan)")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Neewer Infinity BLE light controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show raw BLE packets")
    parser.add_argument("--mac", help="override hardware MAC address (XX:XX:XX:XX:XX:XX)")
    parser.add_argument("--protocol", choices=["auto", "infinity", "extended", "legacy"],
                        default="auto",
                        help="protocol variant (default: auto-detect from device name)")
    parser.add_argument("--json", action="store_true",
                        help="output in JSON format (for scripting)")
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", help="scan for Neewer lights")
    p_scan.add_argument("-t", "--timeout", type=float, default=5.0,
                        help="scan duration in seconds (default: 5.0)")

    for cmd_name, cmd_help in [("on", "turn light on"), ("off", "turn light off")]:
        p = sub.add_parser(cmd_name, help=cmd_help)
        _add_light_args(p)

    p_cct = sub.add_parser("cct", help="set CCT mode")
    _add_light_args(p_cct)
    p_cct.add_argument("--brightness", type=int, required=True, help="0-100")
    p_cct.add_argument("--temp", type=int, required=True, help="2500-10000 Kelvin")
    p_cct.add_argument("--gm", type=int, default=0, help="-50 to 50 (green-magenta)")

    p_hsi = sub.add_parser("hsi", help="set HSI color mode")
    _add_light_args(p_hsi)
    p_hsi.add_argument("--hue", type=int, help="0-360 degrees")
    p_hsi.add_argument("--sat", type=int, help="0-100 saturation")
    p_hsi.add_argument("--brightness", type=int, required=True, help="0-100")
    p_hsi.add_argument("--color", help="named color (alternative to --hue/--sat)")

    p_scene = sub.add_parser("scene", help="set scene/effect mode",
        epilog="Effects: " + ", ".join(sorted(EFFECTS.keys())))
    _add_light_args(p_scene)
    p_scene.add_argument("--effect", required=True,
                         help="effect name or ID (1-18)")
    p_scene.add_argument("--brightness", type=int, default=50, help="0-100")
    p_scene.add_argument("--speed", type=int, default=5, help="1-10")
    p_scene.add_argument("--temp", type=int, help="CCT in Kelvin (for CCT effects)")
    p_scene.add_argument("--hue", type=int, help="hue 0-360 (for hue effects)")
    p_scene.add_argument("--sat", type=int, help="saturation 0-100")
    p_scene.add_argument("--gm", type=int, help="-50 to 50 (green-magenta)")
    p_scene.add_argument("--color", type=int, help="color preset 0-4")
    p_scene.add_argument("--sparks", type=int, help="sparks/ember 1-10")
    p_scene.add_argument("--brr-hi", type=int, help="max brightness 0-100 (welding, candlelight, int-loop)")

    p_gel = sub.add_parser("gel", help="set gel/color filter preset",
        epilog="Run 'gels' to see all 40 gel presets with descriptions. Codes: " +
        ", ".join(sorted(GEL_PRESETS.keys())))
    _add_light_args(p_gel)
    p_gel.add_argument("--brightness", type=int, required=True, help="0-100")
    p_gel.add_argument("--color", required=True,
                       help="gel name (e.g., R38, L002, G910)")

    p_status = sub.add_parser("status", help="query light power status")
    _add_light_args(p_status)

    p_demo = sub.add_parser("demo", help="cycle through light modes")
    _add_light_args(p_demo)
    p_demo.add_argument("--brightness", type=int, default=60, help="0-100")

    p_interactive = sub.add_parser("interactive", help="interactive REPL (stay connected)")
    _add_light_args(p_interactive)

    p_fade = sub.add_parser("fade", help="smooth fade (brightness, temp, or hue)")
    _add_light_args(p_fade)
    p_fade.add_argument("--from", dest="bri_from", type=int, required=True, help="start brightness 0-100")
    p_fade.add_argument("--to", dest="bri_to", type=int, required=True, help="end brightness 0-100")
    p_fade.add_argument("--temp", type=int, default=5000, help="color temp in K (or start temp for --temp-to)")
    p_fade.add_argument("--temp-to", type=int, default=None, help="end color temp in K (enables CCT fade)")
    p_fade.add_argument("--hue", type=int, default=None, help="start hue 0-360 (for HSI fade)")
    p_fade.add_argument("--hue-to", type=int, default=None, help="end hue 0-360 (enables hue fade)")
    p_fade.add_argument("--sat", type=int, default=100, help="saturation 0-100 (for HSI fade)")
    p_fade.add_argument("--duration", type=float, default=2.0, help="fade duration in seconds")

    p_strobe = sub.add_parser("strobe", help="strobe/flash effect")
    _add_light_args(p_strobe)
    p_strobe.add_argument("--brightness", type=int, default=100, help="0-100")
    p_strobe.add_argument("--rate", type=float, default=4.0, help="flashes per second (Hz)")
    p_strobe.add_argument("--count", type=int, default=10, help="number of flashes")
    p_strobe.add_argument("--color", help="named color or temp in K (default: 5600K white)")

    p_raw = sub.add_parser("raw", help="send raw hex bytes (for debugging)")
    _add_light_args(p_raw)
    p_raw.add_argument("hex", help="hex bytes to send (e.g., '78 8D 08 ...')")

    p_info = sub.add_parser("info", help="show info about a cached light")
    p_info.add_argument("--light", help="light alias/name/index (optional, shows all if omitted)")

    p_preset = sub.add_parser("preset", help="save/recall light presets")
    p_preset_sub = p_preset.add_subparsers(dest="preset_cmd")
    p_ps = p_preset_sub.add_parser("save", help="save a preset")
    p_ps.add_argument("preset_name", help="preset name")
    p_ps.add_argument("--mode", choices=["cct", "hsi", "scene"], required=True)
    p_ps.add_argument("--brightness", type=int, required=True, help="0-100")
    p_ps.add_argument("--temp", type=int, help="CCT in Kelvin")
    p_ps.add_argument("--gm", type=int, default=0, help="-50 to 50")
    p_ps.add_argument("--hue", type=int, help="0-360")
    p_ps.add_argument("--sat", type=int, help="0-100")
    p_ps.add_argument("--effect", help="effect name or ID")
    p_ps.add_argument("--speed", type=int, default=5, help="1-10")
    p_pr = p_preset_sub.add_parser("recall", help="recall a preset")
    p_pr.add_argument("preset_name", help="preset name")
    _add_light_args(p_pr)
    p_preset_sub.add_parser("list", help="list saved presets")
    p_pd = p_preset_sub.add_parser("delete", help="delete a preset")
    p_pd.add_argument("preset_name", help="preset name")

    p_source = sub.add_parser("source", help="set light to a standard light source preset",
        epilog="Sources: " + ", ".join(sorted(LIGHT_SOURCES.keys())))
    _add_light_args(p_source)
    p_source.add_argument("source_name", help="light source name (e.g., tungsten, daylight)")
    p_source.add_argument("--brightness", type=int, default=80, help="0-100")

    p_group = sub.add_parser("group", help="manage light groups (use --light <groupname> to control)")
    p_group_sub = p_group.add_subparsers(dest="group_cmd")
    p_gs = p_group_sub.add_parser("save", help="save a group of lights")
    p_gs.add_argument("group_name", help="group name")
    p_gs.add_argument("members", nargs="+", help="light names/indices/addresses")
    p_group_sub.add_parser("list", help="list saved groups")
    p_gd = p_group_sub.add_parser("delete", help="delete a group")
    p_gd.add_argument("group_name", help="group name")

    p_monitor = sub.add_parser("monitor", help="monitor BLE notifications (for debugging)")
    _add_light_args(p_monitor)
    p_monitor.add_argument("--duration", type=float, default=30.0, help="monitoring duration in seconds")

    sub.add_parser("effects", help="list all scene effects")
    p_color = sub.add_parser("color", help="set a named or hex color",
        epilog="Colors: " + ", ".join(sorted(NAMED_COLORS.keys())) + ". Also: #RRGGBB hex codes")
    _add_light_args(p_color)
    p_color.add_argument("color_name", help="color name or #hex (e.g., red, #FF8800)")
    p_color.add_argument("--brightness", type=int, default=80, help="0-100")

    p_batch = sub.add_parser("batch", help="run a sequence of commands from a file",
        epilog="File format: one command per line (same as REPL syntax). Lines starting with # are comments. 'sleep <seconds>' pauses.")
    _add_light_args(p_batch)
    p_batch.add_argument("file", help="path to command file")
    p_batch.add_argument("--loop", type=int, default=1, help="repeat N times (0=forever)")

    sub.add_parser("gels", help="list all gel presets")
    sub.add_parser("sources", help="list all light source presets")
    sub.add_parser("colors", help="list all named colors")

    return parser


def hex_to_hue_sat(hex_str):
    """Convert hex color (#RRGGBB or RRGGBB) to (hue, sat) tuple."""
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except ValueError:
        return None
    cmax, cmin = max(r, g, b), min(r, g, b)
    diff = cmax - cmin
    if diff == 0:
        hue = 0
    elif cmax == r:
        hue = 60 * (((g - b) / diff) % 6)
    elif cmax == g:
        hue = 60 * (((b - r) / diff) + 2)
    else:
        hue = 60 * (((r - g) / diff) + 4)
    sat = 0 if cmax == 0 else (diff / cmax) * 100
    return (int(hue) % 360, int(sat))


def resolve_color(name):
    """Resolve named color or hex (#RRGGBB) to (hue, sat) tuple. Returns None if not found."""
    # Try hex color
    if name.startswith("#") or (len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name)):
        return hex_to_hue_sat(name)
    lower = name.lower().replace(" ", "-").replace("_", "-")
    if lower in NAMED_COLORS:
        return NAMED_COLORS[lower]
    # Try partial match
    for cname, val in NAMED_COLORS.items():
        if cname.startswith(lower):
            return val
    return None


def resolve_gel(name):
    """Resolve gel name (case-insensitive, with or without prefix, partial match)."""
    upper = name.upper()
    if upper in GEL_PRESETS:
        return upper
    for prefix in ["R", "L", "G", "E"]:
        candidate = prefix + upper
        if candidate in GEL_PRESETS:
            return candidate
    # Partial prefix match (e.g., "R3" matches "R38")
    matches = [k for k in GEL_PRESETS if k.startswith(upper)]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_effect(name_or_id):
    if name_or_id in EFFECTS:
        return EFFECTS[name_or_id]
    try:
        val = int(name_or_id, 0)
        if 1 <= val <= 18:
            return val
    except ValueError:
        pass
    print(f"Unknown effect: {name_or_id}")
    print(f"Valid effects: {', '.join(sorted(EFFECTS.keys()))}")
    return None


async def run_command(address, device_name, callback, verbose, use_all=False, proto_arg="auto"):
    """Route to single-light, group, or all-lights execution."""
    if use_all:
        await connect_and_run_all(callback, verbose, proto_arg=proto_arg)
    elif address.startswith("group:"):
        group_name = address.split(":", 1)[1]
        groups = _cache.get("groups", {})
        if group_name not in groups:
            print(f"Unknown group: {group_name}")
            print(f"Available groups: {', '.join(sorted(groups.keys())) or '(none)'}")
            return
        members = groups[group_name]
        lights = _cache.get("lights", {})
        print(f"Sending to group '{group_name}' ({len(members)} light(s))...")
        for member in members:
            # Resolve member — could be a name or address
            addr, dname = _resolve_light_alias(member)
            if addr.startswith("group:") or addr == "all":
                print(f"  SKIP: nested group/all not supported: {member}")
                continue
            print(f"  -> {dname or member} ({addr})")
            try:
                await connect_and_run(addr, dname, callback, verbose, proto_arg=proto_arg)
            except Exception as e:
                print(f"  ERROR: {e}")
    else:
        await connect_and_run(address, device_name, callback, verbose, proto_arg=proto_arg)


async def main():
    global _mac_override
    _load_cache()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.mac:
        _mac_override = args.mac

    if args.command == "scan":
        lights = await scan_lights(args.timeout, quiet=args.json)
        if not lights:
            if args.json:
                print(json.dumps([]))
            else:
                print("No Neewer lights found.")
            return
        _save_scan_results(lights)
        if args.json:
            result = []
            for i, (device, adv) in enumerate(lights):
                name = device.name or adv.local_name or "?"
                info = detect_model_info(name)
                entry = {
                    "index": i, "name": name,
                    "address": device.address, "rssi": adv.rssi,
                    "protocol": detect_protocol(name),
                }
                if info:
                    entry["model"] = info[0]
                    entry["cct_min"] = info[1]
                    entry["cct_max"] = info[2]
                    entry["rgb"] = info[3]
                result.append(entry)
            print(json.dumps(result, indent=2))
        else:
            print(f"\nFound {len(lights)} light(s):\n")
            for i, (device, adv) in enumerate(lights):
                name = device.name or adv.local_name or "?"
                info = detect_model_info(name)
                print(f"  [{i}] {name}")
                if info:
                    model, cmin, cmax, rgb, proto = info
                    print(f"      Model:    {model} ({'RGB' if rgb else 'CCT'}, {cmin}-{cmax}K)")
                    print(f"      Protocol: {proto}")
                else:
                    print(f"      Protocol: {detect_protocol(name)} (auto-detected)")
                print(f"      Address:  {device.address}")
                print(f"      RSSI:     {adv.rssi} dBm")
                print()
            print("Usage: neewer.py <command> --light <Address|Name|Index>")
            print("       neewer.py <command> --light all  (control all lights)")
            print("       neewer.py <command> --light 0    (use scan index)")
        return

    # Handle preset commands
    if args.command == "preset":
        presets = _cache.get("presets", {})
        pname = getattr(args, "preset_name", None)
        if args.preset_cmd == "save":
            preset = {"mode": args.mode, "brightness": args.brightness}
            if args.mode == "cct":
                preset["temp"] = args.temp if args.temp is not None else 5000
                preset["gm"] = args.gm
            elif args.mode == "hsi":
                preset["hue"] = args.hue if args.hue is not None else 0
                preset["sat"] = args.sat if args.sat is not None else 100
            elif args.mode == "scene":
                preset["effect"] = args.effect if args.effect is not None else "cop-car"
                preset["speed"] = args.speed
            _cache.setdefault("presets", {})[pname] = preset
            _save_cache()
            print(f"Saved preset '{pname}': {preset}")
            return
        elif args.preset_cmd == "list":
            if not presets:
                print("No saved presets.")
            else:
                print("Saved presets:\n")
                for name, p in sorted(presets.items()):
                    if p["mode"] == "cct":
                        print(f"  {name:<16s}  CCT bri={p['brightness']}% temp={p.get('temp', 5000)}K gm={p.get('gm', 0)}")
                    elif p["mode"] == "hsi":
                        print(f"  {name:<16s}  HSI bri={p['brightness']}% hue={p.get('hue', 0)} sat={p.get('sat', 100)}%")
                    elif p["mode"] == "scene":
                        print(f"  {name:<16s}  Scene {p.get('effect', '?')} bri={p['brightness']}% speed={p.get('speed', 5)}")
            return
        elif args.preset_cmd == "delete":
            if pname in presets:
                del _cache["presets"][pname]
                _save_cache()
                print(f"Deleted preset '{pname}'")
            else:
                print(f"Preset not found: {pname}")
            return
        elif args.preset_cmd == "recall":
            if pname not in presets:
                print(f"Preset not found: {pname}")
                print(f"Available: {', '.join(sorted(presets.keys())) or '(none)'}")
                return
            p = presets[pname]
            raw_light = args.light
            address, device_name_from_cache = _resolve_light_alias(raw_light)
            device_name = getattr(args, "name", None) or device_name_from_cache
            use_all = address.lower() == "all"
            proto_arg = args.protocol

            print(f"Recalling preset '{pname}': {p}")

            async def do_preset(client, mac_bytes, verbose, proto):
                if p["mode"] == "cct":
                    pkt = build_cct(proto, mac_bytes, p["brightness"], p.get("temp", 5000), p.get("gm", 0))
                elif p["mode"] == "hsi":
                    pkt = build_hsi(proto, mac_bytes, p.get("hue", 0), p.get("sat", 100), p["brightness"])
                elif p["mode"] == "scene":
                    eid = resolve_effect(p.get("effect", "cop-car"))
                    if eid is None:
                        return
                    off = build_power(proto, mac_bytes, on=False)
                    on = build_power(proto, mac_bytes, on=True)
                    pkt = build_scene(proto, mac_bytes, eid, p["brightness"], p.get("speed", 5))
                    await client.write_gatt_char(WRITE_UUID, off, response=False)
                    await asyncio.sleep(0.05)
                    await client.write_gatt_char(WRITE_UUID, on, response=False)
                    await asyncio.sleep(0.05)
                else:
                    print(f"  Unknown mode: {p['mode']}")
                    return
                if verbose:
                    print(f"  TX: {fmt_hex(pkt)}")
                await client.write_gatt_char(WRITE_UUID, pkt, response=False)

            await run_command(address, device_name, do_preset, args.verbose, use_all, proto_arg)
            print("Done.")
            return
        else:
            print("Usage: neewer.py preset {save|recall|list|delete}")
            return

    # Handle group commands
    if args.command == "group":
        groups = _cache.get("groups", {})
        gname = getattr(args, "group_name", None)
        if gname:
            gname = gname.lower()
        if args.group_cmd == "save":
            # Resolve each member to a cached light name (for display and recall)
            resolved = []
            for m in args.members:
                addr, dname = _resolve_light_alias(m)
                resolved.append(dname or m)
            _cache.setdefault("groups", {})[gname] = resolved
            _save_cache()
            print(f"Saved group '{gname}': {', '.join(resolved)}")
            return
        elif args.group_cmd == "list":
            if not groups:
                print("No saved groups.")
            else:
                print("Saved groups:\n")
                for name, members in sorted(groups.items()):
                    print(f"  {name:<16s}  {', '.join(members)}")
            return
        elif args.group_cmd == "delete":
            if gname in groups:
                del _cache["groups"][gname]
                _save_cache()
                print(f"Deleted group '{gname}'")
            else:
                print(f"Group not found: {gname}")
            return
        else:
            print("Usage: neewer.py group {save|list|delete}")
            return

    # Handle info-only commands (no --light needed)
    if args.command == "info":
        lights = _cache.get("lights", {})
        if not lights:
            print("No cached lights. Run 'scan' first.")
            return
        if hasattr(args, "light") and args.light:
            addr, name = _resolve_light_alias(args.light)
            if name:
                lights = {name: lights[name]} if name in lights else {}
            else:
                print(f"Light not found in cache: {args.light}")
                return
        if args.json:
            result = {}
            for name, entry in lights.items():
                result[name] = {
                    "address": entry["address"],
                    "model": entry.get("model", "unknown"),
                    "protocol": entry.get("protocol", "unknown"),
                    "rssi": entry.get("rssi"),
                    "cct_range": entry.get("cct_range"),
                    "rgb": entry.get("rgb"),
                }
            print(json.dumps(result, indent=2))
        else:
            print("Cached lights:\n")
            for name, entry in lights.items():
                model = entry.get("model", "unknown")
                proto = entry.get("protocol", "unknown")
                cct = entry.get("cct_range")
                rgb = entry.get("rgb")
                print(f"  {name}")
                print(f"    Model:    {model}")
                print(f"    Protocol: {proto}")
                print(f"    Address:  {entry['address']}")
                print(f"    RSSI:     {entry.get('rssi', '?')} dBm")
                if cct:
                    print(f"    CCT:      {cct[0]}-{cct[1]}K")
                if rgb is not None:
                    print(f"    RGB:      {'yes' if rgb else 'no'}")
                print()
        return

    if args.command == "effects":
        print("Scene Effects:\n")
        print("  Brightness and speed are set via --brightness/--speed (CLI) or positional args (session).")
        print("  Extra params: --temp, --hue, --sat, --gm, --color, --sparks, --brr-hi (CLI)")
        print("  or key=value pairs in session/batch: scene cop-car 80 5 color=2\n")
        for name, eid in sorted(EFFECTS.items(), key=lambda x: x[1]):
            params = EFFECT_PARAMS.get(eid, [])
            param_names = [p[0] for p in params]
            # Show which kwargs are available beyond brr/speed
            extra = [p[0] for p in params if p[0] not in ("brr", "speed")]
            extra_str = f"  kwargs: {', '.join(extra)}" if extra else ""
            print(f"  {eid:2d} (0x{eid:02X})  {name:<20s}  params: {', '.join(param_names)}{extra_str}")
        return

    if args.command == "gels":
        print("Gel Presets:\n")
        print("  ROSCO:")
        for name in sorted(k for k in GEL_PRESETS if k.startswith(("R", "G", "E"))):
            preset = GEL_PRESETS[name]
            if preset[0] == "cct":
                print(f"    {name:<8s}  CCT {preset[1]:5d}K  GM={preset[2]:+3d}")
            else:
                print(f"    {name:<8s}  HSI hue={preset[1]:3d}  sat={preset[2]:3d}%")
        print("\n  LEE:")
        for name in sorted(k for k in GEL_PRESETS if k.startswith("L")):
            preset = GEL_PRESETS[name]
            if preset[0] == "cct":
                print(f"    {name:<8s}  CCT {preset[1]:5d}K  GM={preset[2]:+3d}")
            else:
                print(f"    {name:<8s}  HSI hue={preset[1]:3d}  sat={preset[2]:3d}%")
        return

    if args.command == "sources":
        print("Light Source Presets:\n")
        for name in sorted(LIGHT_SOURCES.keys()):
            temp, gm, desc = LIGHT_SOURCES[name]
            print(f"  {name:<14s}  {temp:5d}K  GM={gm:+3d}  {desc}")
        return

    if args.command == "colors":
        print("Named Colors:\n")
        for name in sorted(NAMED_COLORS.keys()):
            hue, sat = NAMED_COLORS[name]
            print(f"  {name:<14s}  hue={hue:3d}  sat={sat:3d}%")
        return

    # Resolve light alias/name/index to address
    raw_light = args.light
    address, device_name_from_cache = _resolve_light_alias(raw_light)
    device_name = getattr(args, "name", None) or device_name_from_cache
    use_all = address.lower() == "all"

    proto_arg = args.protocol  # "auto" or explicit; resolved per-light in connect_and_run

    if args.command in ("on", "off"):
        on = args.command == "on"
        print(f"Power {'ON' if on else 'OFF'}...")

        async def do_power(client, mac_bytes, verbose, proto):
            pkt = build_power(proto, mac_bytes, on=on)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_power, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "cct":
        print(f"CCT: brightness={args.brightness}%, temp={args.temp}K, gm={args.gm}")

        async def do_cct(client, mac_bytes, verbose, proto):
            pkt = build_cct(proto, mac_bytes, args.brightness, args.temp, args.gm)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_cct, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "hsi":
        hue = args.hue
        sat = args.sat
        if args.color:
            cval = resolve_color(args.color)
            if not cval:
                print(f"Unknown color: {args.color}")
                print(f"Valid colors: {', '.join(sorted(NAMED_COLORS.keys()))}")
                return
            hue, sat = cval
        elif hue is None or sat is None:
            print("Error: --hue and --sat are required (or use --color)")
            return
        bri = args.brightness
        print(f"HSI: hue={hue}, sat={sat}%, brightness={bri}%")

        async def do_hsi(client, mac_bytes, verbose, proto):
            pkt = build_hsi(proto, mac_bytes, hue, sat, bri)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_hsi, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "scene":
        effect_id = resolve_effect(args.effect)
        if effect_id is None:
            return
        effect_name = next((k for k, v in EFFECTS.items() if v == effect_id), "?")
        print(f"Scene: {effect_name}, brightness={args.brightness}%, speed={args.speed}")

        async def do_scene(client, mac_bytes, verbose, proto):
            # Power cycle required before scene on Infinity lights
            off_pkt = build_power(proto, mac_bytes, on=False)
            on_pkt = build_power(proto, mac_bytes, on=True)
            scene_pkt = build_scene(proto, mac_bytes, effect_id, args.brightness, args.speed,
                                    temp=args.temp, hue=args.hue, sat=args.sat,
                                    gm=args.gm, color=args.color, sparks=args.sparks,
                                    brr_hi=getattr(args, "brr_hi", None))
            if verbose:
                print(f"  TX (off):   {fmt_hex(off_pkt)}")
                print(f"  TX (on):    {fmt_hex(on_pkt)}")
                print(f"  TX (scene): {fmt_hex(scene_pkt)}")
            await client.write_gatt_char(WRITE_UUID, off_pkt, response=False)
            await asyncio.sleep(0.05)
            await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)
            await asyncio.sleep(0.05)
            await client.write_gatt_char(WRITE_UUID, scene_pkt, response=False)

        await run_command(address, device_name, do_scene, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "gel":
        gel_name = resolve_gel(args.color)
        if not gel_name:
            print(f"Unknown gel: {args.color}")
            print(f"Valid gels: {', '.join(sorted(GEL_PRESETS.keys()))}")
            return
        preset = GEL_PRESETS[gel_name]
        if preset[0] == "cct":
            print(f"GEL {gel_name}: CCT {preset[1]}K, GM={preset[2]:+d}, brightness={args.brightness}%")
        else:
            print(f"GEL {gel_name}: HSI hue={preset[1]}, sat={preset[2]}%, brightness={args.brightness}%")

        async def do_gel(client, mac_bytes, verbose, proto):
            pkt = build_gel(proto, mac_bytes, args.brightness, gel_name)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_gel, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "source":
        sname = args.source_name.lower()
        if sname not in LIGHT_SOURCES:
            print(f"Unknown light source: {args.source_name}")
            print(f"Valid sources: {', '.join(sorted(LIGHT_SOURCES.keys()))}")
            return
        temp, gm, desc = LIGHT_SOURCES[sname]
        bri = args.brightness
        print(f"Source: {desc}, brightness={bri}%")

        async def do_source(client, mac_bytes, verbose, proto):
            pkt = build_cct(proto, mac_bytes, bri, temp, gm)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_source, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "color":
        cval = resolve_color(args.color_name)
        if not cval:
            print(f"Unknown color: {args.color_name}")
            print(f"Valid colors: {', '.join(sorted(NAMED_COLORS.keys()))}")
            return
        hue, sat = cval
        bri = args.brightness
        print(f"Color: {args.color_name} (hue={hue}, sat={sat}%), brightness={bri}%")

        async def do_color(client, mac_bytes, verbose, proto):
            pkt = build_hsi(proto, mac_bytes, hue, sat, bri)
            if verbose:
                print(f"  TX: {fmt_hex(pkt)}")
            await client.write_gatt_char(WRITE_UUID, pkt, response=False)

        await run_command(address, device_name, do_color, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "status":
        if not args.json:
            print("Querying status...")

        async def do_status(client, mac_bytes, verbose, proto):
            result = {}
            buf = bytearray()  # reassembly buffer for multi-fragment BLE responses

            def on_notify(sender, data):
                if verbose:
                    print(f"  RX: {fmt_hex(data)}")
                nonlocal buf
                # Fragment reassembly: if we have a pending partial packet, append
                if buf:
                    buf.extend(data)
                    # Check if complete: prefix(1) + tag(1) + size(1) + payload(size) + cs(1)
                    expected = buf[2] + 4 if len(buf) >= 3 else 999
                    if len(buf) < expected:
                        return  # still incomplete
                    data = bytes(buf)
                    buf = bytearray()
                elif len(data) >= 3 and data[0] == PREFIX:
                    # Check if this packet is complete
                    expected = data[2] + 4
                    if len(data) < expected:
                        buf.extend(data)
                        return  # wait for more fragments

                if len(data) >= 4:
                    # Infinity power response: 78 04 08 {MAC} 02 {state} CS
                    if data[1] == 0x04 and len(data) >= 12 and data[9] == 0x02:
                        result["power"] = "ON" if data[10] == 0x01 else "STANDBY"
                    # Infinity device info: 78 08 SIZE {MAC} ... {model_ascii} CS
                    elif data[1] == 0x08:
                        info = parse_device_info(data)
                        if info:
                            result["model"] = info["model"]
                            result["device_mac"] = info["mac"]
                            if "firmware" in info:
                                result["firmware"] = info["firmware"]
                            if "build" in info:
                                result["build"] = info["build"]
                    # Unsolicited/triggered hardware info: 78 05 07 {MAC} XX CS
                    elif data[1] == 0x05 and len(data) >= 11:
                        result["hw_byte"] = f"0x{data[9]:02X}"
                    # Channel/group response: 78 06 XX ... (single byte)
                    elif data[1] == 0x06 and len(data) >= 4:
                        result["channel"] = data[3]
                    # Legacy power response
                    elif data[1] == 0x02:
                        result["power"] = "ON" if data[3] == 0x01 else "STANDBY"
                    elif data[1] == 0x01:
                        result["channel"] = data[3] + 1

            await client.start_notify(NOTIFY_UUID, on_notify)
            await asyncio.sleep(0.3)

            if proto == "infinity":
                # Send both queries, then wait for responses
                query_pkt = cmd_query(mac_bytes)
                if verbose:
                    print(f"  TX: {fmt_hex(query_pkt)}")
                await client.write_gatt_char(WRITE_UUID, query_pkt, response=False)
                await asyncio.sleep(0.5)

                info_pkt = cmd_device_info(mac_bytes)
                if verbose:
                    print(f"  TX: {fmt_hex(info_pkt)}")
                await client.write_gatt_char(WRITE_UUID, info_pkt, response=False)
                await asyncio.sleep(0.5)

                ch_pkt = cmd_channel(mac_bytes)
                if verbose:
                    print(f"  TX: {fmt_hex(ch_pkt)}")
                await client.write_gatt_char(WRITE_UUID, ch_pkt, response=False)
                await asyncio.sleep(0.3)

                hw_pkt = cmd_hw_info(mac_bytes)
                if verbose:
                    print(f"  TX: {fmt_hex(hw_pkt)}")
                await client.write_gatt_char(WRITE_UUID, hw_pkt, response=False)
                await asyncio.sleep(0.3)
            else:
                if verbose:
                    print(f"  TX: {fmt_hex(CMD_POWER_QUERY)}")
                await client.write_gatt_char(WRITE_UUID, CMD_POWER_QUERY, response=False)
                await asyncio.sleep(0.5)

                if verbose:
                    print(f"  TX: {fmt_hex(CMD_READ_REQUEST)}")
                await client.write_gatt_char(WRITE_UUID, CMD_READ_REQUEST, response=False)
                await asyncio.sleep(0.5)

            # Give extra time for any late notifications
            if not result:
                await asyncio.sleep(1.0)

            await client.stop_notify(NOTIFY_UUID)

            if args.json:
                print(json.dumps(result if result else {}))
            elif result:
                for k, v in result.items():
                    print(f"  {k}: {v}")
            else:
                print("  No response received (light may not support status queries)")

        await run_command(address, device_name, do_status, args.verbose, use_all, proto_arg)

    elif args.command == "monitor":
        dur = args.duration
        print(f"Monitoring notifications for {dur}s... (Ctrl+C to stop)")

        async def do_monitor(client, mac_bytes, verbose, proto):
            count = [0]
            mbuf = bytearray()

            def on_notify(sender, data):
                nonlocal mbuf
                count[0] += 1
                ascii_safe = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
                print(f"  [{count[0]:3d}] ({len(data):2d}b) {fmt_hex(data)}  |{ascii_safe}|")

                # Fragment reassembly for decoded output
                if mbuf:
                    mbuf.extend(data)
                    expected = mbuf[2] + 4 if len(mbuf) >= 3 else 999
                    if len(mbuf) < expected:
                        print(f"        -> (fragment {len(mbuf)}/{expected}b)")
                        return
                    full = bytes(mbuf)
                    mbuf = bytearray()
                    print(f"        -> Reassembled: ({len(full)}b) {fmt_hex(full)}")
                elif len(data) >= 3 and data[0] == PREFIX:
                    expected = data[2] + 4
                    if len(data) < expected:
                        mbuf.extend(data)
                        print(f"        -> (fragment {len(data)}/{expected}b, buffering...)")
                        return
                    full = data
                else:
                    return

                # Try to decode known response types
                if len(full) >= 4 and full[0] == PREFIX:
                    if full[1] == 0x04 and len(full) >= 12 and full[9] == 0x02:
                        state = "ON" if full[10] == 0x01 else "STANDBY"
                        print(f"        -> Power: {state}")
                    elif full[1] == 0x05 and len(full) >= 11:
                        print(f"        -> HW info: 0x{full[9]:02X}")
                    elif full[1] == 0x06 and len(full) >= 4:
                        print(f"        -> Channel: {full[3]}")
                    elif full[1] == 0x08:
                        info = parse_device_info(full)
                        if info:
                            print(f"        -> Model: {info['model']}, MAC: {info['mac']}")

            await client.start_notify(NOTIFY_UUID, on_notify)
            await asyncio.sleep(0.3)

            # Send all known queries to generate initial data
            if proto == "infinity":
                for query_fn in [cmd_query, cmd_device_info, cmd_channel]:
                    pkt = query_fn(mac_bytes)
                    print(f"  TX: {fmt_hex(pkt)}")
                    await client.write_gatt_char(WRITE_UUID, pkt, response=False)
                    await asyncio.sleep(0.5)

            try:
                await asyncio.sleep(dur)
            except KeyboardInterrupt:
                pass

            await client.stop_notify(NOTIFY_UUID)
            print(f"\nReceived {count[0]} notification(s).")

        await run_command(address, device_name, do_monitor, args.verbose, use_all, proto_arg)

    elif args.command == "demo":
        bri = args.brightness

        async def do_demo(client, mac_bytes, verbose, proto):
            async def send(pkt, label, delay=1.5):
                if verbose:
                    print(f"  TX ({label}): {fmt_hex(pkt)}")
                await client.write_gatt_char(WRITE_UUID, pkt, response=False)
                await asyncio.sleep(delay)

            print(f"Demo at {bri}% brightness. Press Ctrl+C to stop.\n")
            try:
                # CCT sweep
                print("  CCT: warm 2500K -> cool 10000K")
                for temp in [2500, 3200, 4000, 5000, 6500, 8000, 10000]:
                    await send(build_cct(proto, mac_bytes, bri, temp), f"CCT {temp}K")

                # HSI color wheel
                print("  HSI: color wheel")
                hue_names = {0: "red", 60: "yellow", 120: "green",
                             180: "cyan", 240: "blue", 300: "magenta"}
                for hue in [0, 60, 120, 180, 240, 300]:
                    await send(build_hsi(proto, mac_bytes, hue, 100, bri), hue_names.get(hue, ""))

                # Scene effects sample
                for name, eid in [("cop-car", 0x0A), ("candlelight", 0x0B),
                                   ("lightning", 0x01), ("hue-loop", 0x0C)]:
                    print(f"  Scene: {name}")
                    off = build_power(proto, mac_bytes, on=False)
                    on = build_power(proto, mac_bytes, on=True)
                    scene = build_scene(proto, mac_bytes, eid, bri, 5)
                    await client.write_gatt_char(WRITE_UUID, off, response=False)
                    await asyncio.sleep(0.05)
                    await client.write_gatt_char(WRITE_UUID, on, response=False)
                    await asyncio.sleep(0.05)
                    await send(scene, name, delay=3.0)

                # Return to neutral
                print("  Returning to neutral white...")
                await send(build_cct(proto, mac_bytes, bri, 5000), "neutral")
            except KeyboardInterrupt:
                print("\n  Stopped. Returning to neutral...")
                await client.write_gatt_char(WRITE_UUID,
                    build_cct(proto, mac_bytes, bri, 5000), response=False)

        await run_command(address, device_name, do_demo, args.verbose, use_all, proto_arg)
        print("Demo complete.")

    elif args.command == "interactive":
        print("Connecting for interactive session...")

        async def do_interactive(client, mac_bytes, verbose, proto):
            # Enable readline for history and tab completion
            try:
                import readline
                _REPL_CMDS = [
                    "on", "off", "bri", "temp", "hue", "cct", "hsi", "scene", "gel", "source",
                    "color", "fade", "fade-color", "fade-temp", "fade-hue",
                    "strobe", "random", "raw", "preset", "group", "groups",
                    "status", "demo", "info", "sleep", "effects", "gels",
                    "sources", "colors", "presets", "help", "quit",
                ]
                # Add effect names, color names, source names for completion
                _REPL_WORDS = _REPL_CMDS + list(EFFECTS.keys()) + list(NAMED_COLORS.keys()) + \
                    list(LIGHT_SOURCES.keys()) + list(GEL_PRESETS.keys()) + ["save", "delete", "list"]
                def _completer(text, state):
                    matches = [w for w in _REPL_WORDS if w.startswith(text.lower())]
                    return matches[state] if state < len(matches) else None
                readline.set_completer(_completer)
                readline.parse_and_bind("tab: complete")
                # Load history from cache dir
                hist_path = os.path.join(os.path.dirname(_CACHE_FILE), ".neewer_history")
                try:
                    readline.read_history_file(hist_path)
                except FileNotFoundError:
                    pass
            except ImportError:
                hist_path = None

            print(f"Connected! Protocol: {proto}")
            print("Type commands (help for list, quit to exit):\n")
            print("  on / off                      - power control")
            print("  bri <brightness> [temp]       - quick brightness (e.g., bri 80)")
            print("  temp <temp> [bri] [gm]        - quick temp change (e.g., temp 5600)")
            print("  hue <hue> [sat] [bri]         - quick hue change (e.g., hue 240)")
            print("  cct <bri> <temp> [gm]         - CCT mode (e.g., cct 80 5600)")
            print("  hsi <hue> <sat> <bri>         - HSI mode (e.g., hsi 240 100 80)")
            print("  scene <name> [bri] [speed] [k=v] - effect (e.g., scene cop-car 80 5 color=2)")
            print("  gel <name> <bri>              - gel preset (e.g., gel R38 70)")
            print("  source <name> [bri]           - light source preset (e.g., source daylight 80)")
            print("  color <name|#hex> [bri]       - named color or hex (e.g., color red 80, color #FF8800 70)")
            print("  fade <bri1> <bri2> [temp] [s] - fade brightness (e.g., fade 0 100 5000 3)")
            print("  fade-color <c1> <c2> [bri] [s] - fade between colors (e.g., fade-color red blue 80 3)")
            print("  fade-temp <t1> <t2> [bri] [s]  - fade CCT (e.g., fade-temp 2500 6500 80 5)")
            print("  fade-hue <h1> <h2> [sat] [bri] [s] - fade hue (e.g., fade-hue 0 360 100 80 5)")
            print("  strobe [bri] [hz] [count] [color] - strobe (e.g., strobe 100 4 10 red)")
            print("  sleep <seconds>               - pause (e.g., sleep 2)")
            print("  random [bri]                  - random color (e.g., random 80)")
            print("  preset <name>                 - recall saved preset")
            print("  preset save <name> cct <bri> <temp> [gm] - save CCT preset")
            print("  preset save <name> hsi <hue> <sat> <bri> - save HSI preset")
            print("  preset save <name> scene <effect> [bri] [speed] - save scene preset")
            print("  preset delete <name>          - delete preset")
            print("  raw <hex>                     - send raw bytes (e.g., raw 78 81 01 01 FB)")
            print("  status                        - query power state")
            print("  demo [bri]                    - cycle through modes")
            print("  info                          - show device details")
            print("  group save/delete/list        - manage light groups")
            print("  effects / gels / sources / colors / presets / groups - list options")
            print()

            while True:
                try:
                    line = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("neewer> "))
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not line.strip():
                    continue
                try:
                    result = await exec_session_cmd(client, mac_bytes, proto, line, device_name)
                    if result == "quit":
                        break
                except Exception as e:
                    print(f"  Error: {e}")

            # Save readline history
            if hist_path:
                try:
                    readline.set_history_length(500)
                    readline.write_history_file(hist_path)
                except Exception:
                    pass
            print("Disconnecting...")

        await connect_and_run(address, device_name, do_interactive, args.verbose, proto_arg=proto_arg)

    elif args.command == "fade":
        bri1, bri2 = args.bri_from, args.bri_to
        temp1 = args.temp
        temp2 = args.temp_to
        hue1 = args.hue
        hue2 = args.hue_to
        sat = args.sat
        dur = args.duration

        # Determine fade mode
        if hue1 is not None and hue2 is not None:
            print(f"HSI Fade: bri {bri1}%->{bri2}%, hue {hue1}->{hue2}, sat {sat}% ({dur}s)")
        elif temp2 is not None:
            print(f"CCT Fade: bri {bri1}%->{bri2}%, temp {temp1}K->{temp2}K ({dur}s)")
        else:
            print(f"Fade: {bri1}% -> {bri2}% at {temp1}K ({dur}s)")

        async def do_fade(client, mac_bytes, verbose, proto):
            steps = max(5, int(dur * 20))
            for i in range(steps + 1):
                t = i / steps
                bri = int(bri1 + (bri2 - bri1) * t)
                if hue1 is not None and hue2 is not None:
                    hdiff = (hue2 - hue1 + 540) % 360 - 180
                    hue = int(hue1 + hdiff * t) % 360
                    pkt = build_hsi(proto, mac_bytes, hue, sat, bri)
                elif temp2 is not None:
                    temp = int(temp1 + (temp2 - temp1) * t)
                    pkt = build_cct(proto, mac_bytes, bri, temp)
                else:
                    pkt = build_cct(proto, mac_bytes, bri, temp1)
                if verbose and i % 10 == 0:
                    print(f"  TX: {fmt_hex(pkt)}")
                await client.write_gatt_char(WRITE_UUID, pkt, response=False)
                await asyncio.sleep(dur / steps)

        await run_command(address, device_name, do_fade, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "raw":
        hex_str = args.hex.replace(" ", "").replace(":", "")
        try:
            raw_bytes = bytes.fromhex(hex_str)
        except ValueError:
            print(f"Invalid hex: {args.hex}")
            return
        print(f"Sending raw: {fmt_hex(raw_bytes)}")

        async def do_raw(client, mac_bytes, verbose, proto):
            await client.write_gatt_char(WRITE_UUID, raw_bytes, response=False)

        await run_command(address, device_name, do_raw, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "strobe":
        bri = args.brightness
        rate = args.rate
        count = args.count
        color_arg = args.color
        print(f"Strobe: {count}x at {rate}Hz, brightness={bri}%")

        async def do_strobe(client, mac_bytes, verbose, proto):
            half = 0.5 / rate
            if color_arg:
                cval = resolve_color(color_arg)
                if cval:
                    on_pkt = build_hsi(proto, mac_bytes, cval[0], cval[1], bri)
                else:
                    try:
                        temp = int(color_arg)
                        on_pkt = build_cct(proto, mac_bytes, bri, temp)
                    except ValueError:
                        print(f"Unknown color/temp: {color_arg}")
                        return
            else:
                on_pkt = build_cct(proto, mac_bytes, bri, 5600)
            off_pkt = build_power(proto, mac_bytes, on=False)
            on_power = build_power(proto, mac_bytes, on=True)
            for i in range(count):
                await client.write_gatt_char(WRITE_UUID, on_power, response=False)
                await asyncio.sleep(0.02)
                await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)
                await asyncio.sleep(half)
                await client.write_gatt_char(WRITE_UUID, off_pkt, response=False)
                await asyncio.sleep(half)
            # Leave light on
            await client.write_gatt_char(WRITE_UUID, on_power, response=False)
            await asyncio.sleep(0.02)
            await client.write_gatt_char(WRITE_UUID, on_pkt, response=False)

        await run_command(address, device_name, do_strobe, args.verbose, use_all, proto_arg)
        print("Done.")

    elif args.command == "batch":
        filepath = args.file
        try:
            with open(filepath) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"Cannot open batch file: {e}")
            return
        # Filter: skip empty lines and comments
        commands = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        if not commands:
            print("No commands in batch file.")
            return

        loops = args.loop
        print(f"Batch: {len(commands)} commands, {loops if loops else 'infinite'} loop(s)")

        async def do_batch(client, mac_bytes, verbose, proto):
            iteration = 0
            try:
                while loops == 0 or iteration < loops:
                    iteration += 1
                    if loops != 1:
                        print(f"--- Loop {iteration} ---")
                    for i, line in enumerate(commands):
                        if verbose:
                            print(f"  [{i+1}/{len(commands)}] {line}")
                        result = await exec_session_cmd(client, mac_bytes, proto, line, device_name)
                        if result == "quit":
                            return
            except KeyboardInterrupt:
                print("\nBatch interrupted.")

        await run_command(address, device_name, do_batch, args.verbose, use_all, proto_arg)
        print("Batch complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
