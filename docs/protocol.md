# Neewer Infinity BLE Protocol Specification

Documented from NeewerLite (Swift), NeewerLite-Python, and Neewer DMX specifications.
Covers the "Infinity" protocol used by newer Neewer lights: TL60 RGB, TL90C, TL120C, PL60C, RL45C.

## BLE Service & Characteristics

| UUID | Type | Usage |
|------|------|-------|
| `69400001-B5A3-F393-E0A9-E50E24DCCA99` | Service | Primary BLE service |
| `69400002-B5A3-F393-E0A9-E50E24DCCA99` | Write (no response) | Send commands to light |
| `69400003-B5A3-F393-E0A9-E50E24DCCA99` | Notify | Receive status from light |

Write characteristic supports both WRITE and WRITE NO RESPONSE. Prefer WRITE NO RESPONSE.

## Command Envelope

All Infinity protocol commands follow this format:

```
Byte 0:     0x78              (prefix, always)
Byte 1:     TAG               (command type)
Byte 2:     SIZE              (= len(PARAMS) + 7)
Bytes 3-8:  MAC[0..5]         (hardware MAC address, 6 bytes)
Byte 9:     SUBTAG            (sub-command identifier)
Bytes 10+:  PARAMS            (variable length)
Last byte:  CHECKSUM          (sum of all preceding bytes & 0xFF)
```

**SIZE** = number of PARAMS bytes + 7 (6 MAC bytes + 1 SUBTAG byte).

**Total packet length** = len(PARAMS) + 11 (prefix + tag + size + 6 MAC + subtag + checksum).

## Checksum

Sum all bytes except the checksum byte itself, take lowest 8 bits:

```python
checksum = sum(packet[:-1]) & 0xFF
```

Example: Power ON with MAC `F7:AC:16:F1:58:96`
```
78 8D 08 F7 AC 16 F1 58 96 81 01 ??
Sum = 0x78+0x8D+0x08+0xF7+0xAC+0x16+0xF1+0x58+0x96+0x81+0x01 = 0x527
Checksum = 0x27
Packet: 78 8D 08 F7 AC 16 F1 58 96 81 01 27
```

## MAC Address

The Infinity protocol embeds the device's hardware Bluetooth MAC in every command.

**On macOS:** CoreBluetooth exposes UUIDs, not MACs. Resolve the real MAC via:
```bash
system_profiler SPBluetoothDataType
```
Search output for device name, then extract `Address: XX:XX:XX:XX:XX:XX`.

**On Linux/Windows:** The BLE address is the hardware MAC.

**Encoding:** Parse `"AA:BB:CC:DD:EE:FF"` into bytes `[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]`.

## Commands

### Power On/Off

| Field | Value |
|-------|-------|
| TAG | `0x8D` |
| SUBTAG | `0x81` |
| PARAMS | `[state]` — `0x01`=ON, `0x02`=OFF |
| SIZE | `0x08` (1 + 7) |

```
Power ON:  78 8D 08 [MAC×6] 81 01 [CS]    (12 bytes)
Power OFF: 78 8D 08 [MAC×6] 81 02 [CS]    (12 bytes)
```

### CCT (Color Temperature)

| Field | Value |
|-------|-------|
| TAG | `0x90` |
| SUBTAG | `0x87` |
| PARAMS | `[brightness, cct_value, gm_byte, 0x04]` |
| SIZE | `0x0B` (4 + 7) |

```
78 90 0B [MAC×6] 87 [BRI] [CCT] [GM] 04 [CS]    (15 bytes)
```

**Brightness:** 0–100 (percentage)

**CCT value:** `temperature_K / 100` — range depends on model:
- Standard models: 32–56 (3200K–5600K)
- Extended models: 25–100 (2500K–10000K)
- TL60 RGB, TL90C, TL120C, PL60C: 25–100 (per DMX specs)

**GM (green-magenta):** stored as `value + 50` — input range -50..+50, byte range 0..100.
- 0x00 = -50 (max magenta)
- 0x32 = 0 (neutral)
- 0x64 = +50 (max green)

**Dimming curve:** `0x04` (fixed constant).

### HSI (Hue-Saturation-Intensity)

| Field | Value |
|-------|-------|
| TAG | `0x8F` |
| SUBTAG | `0x86` |
| PARAMS | `[hue_lo, hue_hi, saturation, brightness, 0x00]` |
| SIZE | `0x0C` (5 + 7) |

```
78 8F 0C [MAC×6] 86 [HUE_LO] [HUE_HI] [SAT] [BRI] 00 [CS]    (16 bytes)
```

**Hue:** 16-bit little-endian, 0–359 degrees (360 is equivalent to 0).
- `hue_lo = hue & 0xFF`
- `hue_hi = (hue >> 8) & 0xFF`
- Example: hue 240° → `hue_lo=0xF0, hue_hi=0x00`
- Example: hue 300° → `hue_lo=0x2C, hue_hi=0x01`

**Saturation:** 0–100 (percentage)

**Brightness:** 0–100 (percentage)

**Trailing byte:** `0x00` (reserved/unknown)

### Scene/Effect

| Field | Value |
|-------|-------|
| TAG | `0x91` |
| SUBTAG | `0x8B` |
| PARAMS | `[effect_id, ...effect_params]` |
| SIZE | `8 + param_byte_count` |

```
78 91 [SIZE] [MAC×6] 8B [EFFECT_ID] [PARAMS...] [CS]
```

**Important:** Scene commands require a power cycle before sending:
1. Send Power OFF, wait 50ms
2. Send Power ON, wait 50ms
3. Send scene command

## Scene Effects

### Effect IDs

| ID | Name | Parameters |
|----|------|-----------|
| 0x01 | Lightning | BRR, CCT, Speed |
| 0x02 | Paparazzi | BRR, CCT, GM, Speed |
| 0x03 | Defective Bulb | BRR, CCT, GM, Speed |
| 0x04 | Explosion | BRR, CCT, GM, Speed, Sparks |
| 0x05 | Welding | BRR_lo, BRR_hi, CCT, GM, Speed |
| 0x06 | CCT Flash | BRR, CCT, GM, Speed |
| 0x07 | Hue Flash | BRR, HUE (2B LE), SAT, Speed |
| 0x08 | CCT Pulse | BRR, CCT, GM, Speed |
| 0x09 | Hue Pulse | BRR, HUE (2B LE), SAT, Speed |
| 0x0A | Cop Car | BRR, Color, Speed |
| 0x0B | Candlelight | BRR_lo, BRR_hi, CCT, GM, Speed, Sparks |
| 0x0C | Hue Loop | BRR, HUE1 (2B LE), HUE2 (2B LE), Speed |
| 0x0D | CCT Loop | BRR, CCT1, CCT2, Speed |
| 0x0E | INT Loop | Submode, BRR_lo, BRR_hi, (varies), Speed — see below |
| 0x0F | TV Screen | BRR, CCT, GM, Speed |
| 0x10 | Firework | BRR, Color, Speed, Sparks |
| 0x11 | Party | BRR, Color, Speed |
| 0x12 | Music | BRR |

### INT Loop Sub-Modes (Effect 0x0E)

INT Loop has two sub-modes selected by a byte immediately after the effect ID:

**CCT sub-mode** (submode=`0x00`):
```
PARAMS: [0x0E, 0x00, BRR_lo, BRR_hi, 0x00, 0x00, CCT, Speed]
```
Sweeps brightness between BRR_lo and BRR_hi at the given CCT temperature.

**HSI sub-mode** (submode=`0x01`):
```
PARAMS: [0x0E, 0x01, BRR_lo, BRR_hi, HUE_lo, HUE_hi, 0x00, Speed]
```
Sweeps brightness between BRR_lo and BRR_hi at the given hue color (16-bit LE).

The sub-mode byte determines which color space is used. If no `hue` is specified, CCT sub-mode is used by default.

### Parameter Types

| Parameter | Bytes | Range | Encoding |
|-----------|-------|-------|----------|
| BRR (brightness) | 1 | 0–100 | Direct percentage |
| BRR_lo / BRR_hi | 1 each | 0–100 | Brightness range bounds |
| CCT | 1 | 25–100 | temp_K / 100 |
| GM | 1 | 0–100 | value + 50 (input: -50 to +50) |
| HUE | 2 | 0–360 | 16-bit little-endian degrees |
| SAT | 1 | 0–100 | Direct percentage |
| Color | 1 | 0–4 | Preset index (effect-dependent) |
| Speed | 1 | 1–10 | Effect speed/pace |
| Sparks | 1 | 1–10 | Ember/spark intensity |

### Cop Car Color Presets

| Value | Colors |
|-------|--------|
| 0 | Red |
| 1 | Blue |
| 2 | Red/Blue |
| 3 | White/Blue |
| 4 | Red/White/Blue |

### Firework/Party Mode Selection

| Value | Mode |
|-------|------|
| 0 | Single Color |
| 1 | Colored |
| 2 | Mixed Color |

## Legacy Protocol

Older Neewer lights use a simpler format without MAC addressing:

| Command | Bytes |
|---------|-------|
| Power ON | `78 81 01 01 FB` |
| Power OFF | `78 81 01 02 FC` |
| CCT | `78 87 02 [BRI] [CCT] [CS]` |
| HSI | `78 86 04 [HUE_LO] [HUE_HI] [SAT] [BRI] [CS]` |
| Scene (9 FX) | `78 88 02 [BRI] [EFFECT_ID] [CS]` |

Legacy TAG values: Power=`0x81`, CCT=`0x87`, HSI=`0x86`, Scene=`0x88`.

## Extended Legacy Protocol

Mid-generation lights (GL1C, RGB62) use a variant that adds GM correction to CCT and supports all 18 effects without the Infinity MAC envelope. Discovered from BLE packet captures in the NeewerLite research notes.

### Extended CCT

```
78 87 03 [BRI] [CCT] [GM] [CS]    (7 bytes)
```

Same tag as legacy CCT (`0x87`) but with 3 params instead of 2 (adds GM byte). CCT range extended to 25–100 (2500K–10000K).

**Verified captures (GL1C):**
```
78 87 03 46 20 32 9A   (brightness=70, CCT=3200K, GM=0)
78 87 03 3E 1E 32 90   (brightness=62, CCT=3000K, GM=0)
78 87 03 3E 20 28 88   (brightness=62, CCT=3200K, GM=-10)
78 87 03 3E 20 44 A4   (brightness=62, CCT=3200K, GM=+18)
```

### Extended Scene

```
78 8B [SIZE] [EFFECT_ID] [PARAMS...] [CS]
```

Uses tag `0x8B` (same as Infinity scene subtag) as the main tag. No MAC envelope. Same effect IDs and parameter layouts as Infinity protocol. Supports all 18 effects including Music (0x12).

**Verified captures:**
```
GL1C Cop Car:  78 8B 04 0A 10 00 05 26   (brr=16, color=Red, speed=5)
GL1C Cop Car:  78 8B 04 0A 10 01 05 27   (brr=16, color=Blue, speed=5)
GL1C Party:    78 8B 04 11 32 00 05 4F   (brr=50, color=0, speed=5)
GL1C Music:    78 8B 02 12 32 49          (brr=50)
RGB62 Light:   78 8B 04 01 53 37 05 97   (brr=83, cct=55, speed=5)
RGB62 Light:   78 8B 04 01 16 4C 07 71   (brr=22, cct=76, speed=7)
```

### Known Extended Legacy Models

| Model | BLE Name Prefix | Source |
|-------|----------------|--------|
| GL1C | `NEEWER-GL1C` | NeewerLite packet captures |
| RGB62 | Unknown | NeewerLite packet captures |

## Protocol Tags Reference

| Tag | Hex | Usage |
|-----|-----|-------|
| PREFIX | `0x78` | All commands and responses |
| Power (Infinity) | `0x8D` | TAG for power with MAC |
| Power SubTag | `0x81` | SUBTAG (reuses legacy power tag) |
| Query (Infinity) | `0x8E` | TAG for power status query |
| HSI (Infinity) | `0x8F` | TAG for HSI with MAC |
| HSI SubTag | `0x86` | SUBTAG (reuses legacy HSI tag) |
| CCT (Infinity) | `0x90` | TAG for CCT with MAC |
| CCT SubTag | `0x87` | SUBTAG (reuses legacy CCT tag) |
| Scene (Infinity) | `0x91` | TAG for scene with MAC |
| Scene SubTag | `0x8B` | SUBTAG for scene effects |
| Device Val | `0x95` | TAG for hardware revision query |
| Device Ch | `0x96` | TAG for channel/group query |
| Device Flag | `0x9D` | TAG for unknown flag query |
| Device Info | `0x9E` | TAG for model name + firmware query |
| Extended Scene | `0x8B` | TAG for extended legacy scenes (no MAC) |

## DMX-to-BLE Parameter Mapping

DMX channel values (0–255) map to BLE byte values (0–100) for most parameters.
The DMX specs confirm all four lights share the same channel layout:

- **Mode 1 (CCT):** Mode, Brightness(0-100%), CCT(2500-10000K), G/M(-50 to +50)
- **Mode 2 (HSI):** Mode, Intensity(0-100%), Hue(0-360°), Saturation(0-100%)
- **Mode 3 (FX):** Mode, Brightness(0-100%), Effect(1-17), [effect sub-params]
- **Mode 4 (GEL):** Mode, Brightness(0-100%), Color Gel (ROSCO 0-119 / LEE 120-239)

### GEL Mode

GEL mode is documented in DMX specs but the native BLE command format is unknown. Neither NeewerLite (Swift) nor NeewerLite-Python implement a dedicated GEL BLE command.

DMX gel presets:
- 20 ROSCO presets: R38, R44, R65, R92, R93, G152, G220, G325, G342, G720, G910, G990, E128, E153, E156, E165, E723, E724, R4590, R9406
- 20 LEE presets: 002, 007, 036, 088, 110, 115, 117, 128, 131, 148, 241, 243, 500, 701, 703, 723, 724, 729, 765, 790

**Workaround:** `neewer.py` approximates gel presets by mapping each to CCT+GM or HSI values and sending standard CCT/HSI commands. This provides visually similar results for most gels.

## Protocol Detection

Neewer lights use three protocol variants. The variant can be detected from the BLE device name:

| Name Format | Example | Protocol | Notes |
|-------------|---------|----------|-------|
| `NW-{code}&{suffix}` | `NW-20220016&776A0500` | Infinity | Product code in name |
| `NEEWER-{model}` | `NEEWER-GL1C` | Varies | Match model against DB |
| `NWR-{model}` | `NWR-...` | Varies | Older naming convention |
| `SL{model}` | `SL90` | Infinity | Strip SL prefix |

### Protocol Variants

| Protocol | Power Tag | CCT Tag | HSI Tag | Scene Tag | MAC? | GM? | Effects |
|----------|-----------|---------|---------|-----------|------|-----|---------|
| Infinity | 0x8D | 0x90 | 0x8F | 0x91 | Yes (6 bytes) | Yes | 18 |
| Extended | 0x81 | 0x87 (3 params) | 0x86 | 0x8B | No | Yes | 18 |
| Legacy | 0x81 | 0x87 (2 params) | 0x86 | 0x88 | No | No | 9 |

### Product Code → Model Mapping

From NeewerLite Swift/Python, confirmed by BLE scanning:

| Product Code | Model | CCT Range | RGB | Protocol |
|-------------|-------|-----------|-----|----------|
| 20210036 | TL60 RGB | 2500–10000K | Yes | Infinity |
| 20230064 | TL60 RGB | 2500–10000K | Yes | Infinity |
| 20220016 | PL60C | 2500–10000K | No | Infinity |
| 20230031 | TL120C | 2500–10000K | No | Infinity |
| 20210018 | BH-30S RGB | 2500–10000K | Yes | Infinity |
| 20200015 | RGB1 | 3200–5600K | Yes | Infinity |
| 20200037 | SL90 | 2500–10000K | Yes | Infinity |
| 20200049 | RGB1200 | 2500–10000K | Yes | Infinity |
| 20210007 | RGB C80 | 2500–10000K | Yes | Infinity |
| 20220057 | SL90 Pro | 2500–10000K | Yes | Infinity |

## Known Model IDs (NeewerLite Swift)

| Model | Type ID | CCT Range | Protocol |
|-------|---------|-----------|----------|
| TL60 RGB | 32 | 2500–10000K | Infinity |
| TL120C | 50 | 2500–10000K | Infinity |
| RL45B | 52 | 2500–10000K | Infinity |
| PL60C | 60 | 2500–10000K | Infinity |
| BH-30S RGB | 42 | 2500–10000K | Infinity |
| TL90C | — | 2500–10000K | Infinity (likely) |
| RL45C | — | 2500–10000K | Infinity (likely) |

## Live Testing Results (PL60C)

Verified on PL60C (BLE names: `NW-20220016&00323204` / `NW-20220016&776A0500`, MAC: `D4:ED:61:C3:B7:00`, firmware: 1.9.1):

### Confirmed Working
- **Power ON/OFF**: Both work reliably
- **CCT**: Full range 2500K-10000K with GM correction -50 to +50
- **HSI**: Full hue 0-360, saturation 0-100, brightness 0-100
- **Scene effects**: All 17 effects send successfully (cop-car, candlelight, lightning, party, hue-flash, hue-loop, tv-screen, firework verified visually)
- **Power cycle for scenes**: Required — OFF→50ms→ON→50ms→scene command
- **Status query**: TAG `0x8E` returns power state (ON/STANDBY) via notify characteristic
- **Light source presets**: Standard CCT presets (Tungsten 2700K, Daylight 5000K, etc.) work via CCT command

### MAC Address Validation
Testing with different MAC values in the command envelope:
- Real MAC (from system_profiler): **Works**
- All-zeros MAC (00:00:00:00:00:00): **Works**
- All-FF MAC (FF:FF:FF:FF:FF:FF): **Works**
- Random MAC: **Works**

**Finding:** The PL60C does NOT validate the MAC field in Infinity commands. Commands are accepted regardless of the MAC value. This may be model-specific — other Infinity lights should be tested to confirm.

### Second BLE Service
The PL60C exposes a second BLE service not documented in NeewerLite:

| UUID | Type | Usage |
|------|------|-------|
| `7F510004-B5A3-F393-E0A9-E50E24DCCA9E` | Service | Unknown purpose |
| `7F510005-B5A3-F393-E0A9-E50E24DCCA9E` | Write + Notify | Unknown |
| `7F510006-B5A3-F393-E0A9-E50E24DCCA9E` | Write | Unknown |

This service was tested but did not respond to any commands or produce notifications.

### Notification Characteristic / Status Query

**Legacy query commands** (`78 84 00 FC`, `78 85 00 FD`) do NOT work on Infinity lights — no response.

**Infinity query command** (TAG `0x8E`) was discovered via live protocol testing on PL60C:

Query packet:
```
78 8E 08 {MAC[6]} 84 00 {checksum}
```

Response (via notify characteristic):
```
78 04 08 {MAC[6]} 02 {power_state} {checksum}
```

Where `power_state`:
- `0x01` = ON
- `0x02` = STANDBY/OFF

**Device Info Query** (TAG `0x9E`):

```
TX: 78 9E 07 {MAC[6]} 00 {checksum}
RX: 78 08 10 {MAC[6]} {fields...} {model_ascii} {checksum}
```

PL60C example response: `78 08 10 D4 ED 61 C3 B7 00 01 09 01 03 03 01 50 4C 36 30 40`
- Response type: `0x08` (device info)
- Fields: `01 09 01 03 03 01` (firmware/capability data: likely version 1.9.1, build 3.3.1)
- Model name: `50 4C 36 30` = ASCII "PL60"

**Additional Discovered Query Tags** (TAG sweep 0x80-0x9F on PL60C):

| TAG | Response Type | Response Data | Meaning |
|-----|--------------|---------------|---------|
| `0x8E` | `0x04` | `{MAC} 02 {state}` | Power status (ON=0x01, OFF=0x02) |
| `0x95` | `0x05` | `{MAC} F0` | Hardware info (triggers TAG 0x05 response) |
| `0x96` | `0x06` | `00` | Channel/group assignment (0=unassigned) |
| `0x9D` | `0x07` | `{MAC} 01` | Flag value (always 0x01 on PL60C) |
| `0x9E` | `0x08` | `{MAC} {fields} {model}` | Device info with ASCII model name |
| `0x8C` | `0x7F` | `{MAC} 8C 00` | Unsupported command indicator |
| `0x9B` | `0x7F` | `{MAC} 9B 00` | Unsupported command indicator |
| `0x9F` | `0x7F` | `{MAC} 9F 00` | Unsupported command indicator |

**Key findings:**
- Bare query (`78 8E 00 06` without MAC) also works — the light echoes its own MAC in the response
- Response type `0x7F` indicates "unsupported command"
- Tags `0x80-0x8B`, `0x89`, `0x92-0x94`, `0x98-0x9A` produce no response
- Second BLE service (`7F510004`) does not respond to any known command format

### Dual-UUID Advertisement (Critical)

The PL60C advertises on **two** CoreBluetooth UUIDs simultaneously with different BLE names:
- `NW-20220016&00323204` — **Primary**: responds to status queries (TAG 0x8E, 0x9E) with full data
- `NW-20220016&776A0500` — **Secondary**: only returns generic ACKs (`78 06 01 XX CS`) to queries

**The suffix after `&` distinguishes the BLE interfaces.** Both accept control commands (power, CCT, HSI, scene), but only the primary UUID returns notification data for status/info queries.

**Deduplication**: When scanning, devices with the same product code (the `NW-XXXXXXXX` prefix before `&`) should be deduplicated. Keep the one with stronger RSSI — it tends to be the responsive interface.

### Generic ACK Response Format

Some queries return a generic acknowledgment instead of detailed data:
```
78 06 01 {value} {checksum}
```
- TAG `0x06`, length 1, single byte value
- Value `0x00` for channel/numeric queries
- Value `0x01` for flag/boolean queries

This response comes from the secondary BLE interface or for unsupported query types on the primary.

### macOS BLE Notes
- CoreBluetooth exposes UUIDs, not hardware MACs
- BLE devices only appear in `system_profiler SPBluetoothDataType` while **actively connected** via BLE
- Since MAC validation is not enforced, `system_profiler` resolution is optional

## Live Testing Results (TL120 RGB-2)

Verified on TL120 RGB-2 (BLE name: `NW-20240047&776A0500`, MAC: `EB:43:D1:20:F7:8D`, firmware: 1.10.2):

### Confirmed Working
- **Power ON/OFF**: Works
- **CCT**: Full range 2500K-10000K with GM correction
- **HSI**: Full hue 0-360, saturation 0-100, brightness 0-100 (device is RGB despite "TL120C" model name)
- **Scene effects**: cop-car confirmed working
- **Device info query** (TAG `0x9E`): Returns "TL120 RGB-2" — note that this is a multi-fragment response (27 bytes, split across two BLE packets of 20+7 bytes)

### Differences from PL60C
- **No power state query response**: TAG `0x8E` produces no response (PL60C returns `78 04 08 {MAC} 02 {state} CS`)
- **Unsolicited TAG `0x05` on connect**: `78 05 07 {MAC} F0 CS` — sent automatically when BLE connection is established. Value `F0` is consistent regardless of power state, likely a capability/revision byte
- **TAG `0x95`** re-triggers the TAG `0x05` unsolicited response (same as PL60C)
- **TAG `0x97`** returns generic ACK `78 06 01 00 7F` (PL60C doesn't respond to 0x97)
- **Device info response spans two BLE packets**: Model name "TL120 RGB-2" is 11 chars, causing the response to exceed the 20-byte BLE MTU

### BLE Notification Query Sweep Results (TL120C)

| Query TAG | Response TAG | Response Data | Notes |
|-----------|-------------|---------------|-------|
| (connect) | `0x05` | `{MAC} F0` | Unsolicited on BLE connect |
| `0x8C` | `0x7F` | `{MAC} 8C 00` | Unsupported command |
| `0x8E` | — | No response | Power query not supported |
| `0x95` | `0x05` | `{MAC} F0` | Re-triggers unsolicited status |
| `0x96` | `0x06` (short) | `00` | Channel (0 = unassigned) |
| `0x97` | `0x06` (short) | `00` | Unknown query, returns 0 |
| `0x9E` | `0x08` | `{MAC} {firmware} {model_ascii}` | Device info (multi-fragment) |

### Multi-Fragment BLE Responses

Responses exceeding 20 bytes are split across multiple BLE notifications. The expected total size can be calculated from byte 2 (SIZE field) + 4 (prefix + tag + size + checksum).

Example (TL120C device info):
```
Fragment 1 (20b): 78 08 17 EB 43 D1 20 F7 8D 01 0A 02 00 05 02 54 4C 31 32 30
Fragment 2 ( 7b): 20 52 47 42 2D 32 DB
Reassembled (27b): 78 08 17 {MAC} 01 0A 02 00 05 02 "TL120 RGB-2" DB
```

Expected size: `0x17` (23) + 4 = 27 bytes. Fragment 1 is 20 bytes (BLE MTU), fragment 2 carries remaining 7 bytes.

## References

- [NeewerLite (Swift)](https://github.com/keefo/NeewerLite) — `NeewerLight.swift`, `NeewerLightConstant.swift`, `NeewerLightFX.swift`
- [NeewerLite-Python](https://github.com/taburineagle/NeewerLite-Python) — `NeewerLite-Python.py`
- [RGB660 PRO Protocol](https://gist.github.com/JDogHerman/483b4e56537892cb2089a63cc12e5631) — legacy protocol reference
- DMX Specs (in repo): `TL60 RGB DMX-EN.pdf`, `TL90C DMXEN.pdf`, `TL120C DMXEN.pdf`, `PL60C DMXEN.pdf`
