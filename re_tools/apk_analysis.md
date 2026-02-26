# Neewer Studio APK — Complete BLE Protocol Analysis

Decompiled from: `NEEWER Studio Tablet_1.0.6_APKPure.apk`
Package: `com.neewerpro.neewerapp`
Key source: `com.neewerpro.control.BleDeviceControl.java`

## Overview

The Neewer app supports **three addressing modes** for BLE commands:

| Mode | Address Field | Bytes | Use Case |
|------|--------------|-------|----------|
| **MAC** | Hardware MAC (6 bytes) | `MAC[6]` | Direct control of single light |
| **Channel** | NetworkId (4B) + Channel (1B) | `NETID[4] CH` | Group broadcast via one BLE connection |
| **Bluetooth** | None | — | Legacy simple commands |

The **Channel mode** is the "master/slave" feature seen in the iOS app. One light acts as the BLE relay — you connect to it and send channel-addressed commands. All lights assigned to that channel respond.

### NetworkId

A 32-bit integer stored per-user in `UserKV.getNetworkId()`. Serialized as **4 bytes little-endian** in channel commands. Think of it as a "group network" identifier — all lights in a user's setup share the same NetworkId.

### Channel

A 1-byte value (0-255) representing the channel number within a network. Lights assigned to the same channel respond to channel-addressed commands.

---

## Command Reference

### Notation
- `78` = packet header (0x78)
- `CS` = checksum: `sum(all_bytes_except_last) & 0xFF`
- `LEN` = byte count after LEN byte, excluding checksum
- `NETID[4]` = NetworkId as 4 bytes LE: `[id & 0xFF, (id>>8) & 0xFF, (id>>16) & 0xFF, (id>>24) & 0xFF]`
- `MAC[6]` = hardware MAC: `[AA, BB, CC, DD, EE, FF]`
- Signed Java bytes: `-115` = `0x8D`, `-110` = `0x92`, etc.

---

## 1. Power Commands

### Direct (MAC-addressed) — TAG 0x8D
```
ON:  78 8D 08 MAC[6] 81 01 CS    (12 bytes)
OFF: 78 8D 08 MAC[6] 81 02 CS    (12 bytes)
```

### Channel-addressed — TAG 0x98
```
ON:  78 98 07 NETID[4] CH 81 01 CS    (11 bytes)
OFF: 78 98 07 NETID[4] CH 81 02 CS    (11 bytes)
```

### Legacy (no address) — TAG 0x81
```
ON:  78 81 01 01 FB    (5 bytes)
OFF: 78 81 01 02 FC    (5 bytes)
```

---

## 2. CCT Commands

### MAC-addressed — TAG 0x90
```
78 90 LEN MAC[6] 87 BRI CCT GM CURVE DBRI CS
```
- LEN = 0x0C (12 = 6 MAC + 1 subtag + 5 params)
- BRI: 0-100
- CCT: color temp value (model-dependent range)
- GM: green-magenta + 50 (0-100, where 50 = neutral)
- CURVE: dimming curve type (typically 0x04)
- DBRI: decimal brightness (sub-percent, for smooth fading)

### Channel-addressed — TAG 0x93
```
78 93 LEN NETID[4] CH 87 BRI CCT GM CURVE DBRI CS
```
- LEN = 0x0B (11 = 4 NETID + 1 CH + 1 subtag + 5 params)
- Built via: `setRGB1GroupLightValue(147, 5, 135, ch, [bri, cct, gm, curve, dbri])`
- oldOrder/SUBTAG = 135 (0x87)

---

## 3. HSI Commands

### MAC-addressed — TAG 0x8F
```
78 8F LEN MAC[6] 86 HUE_LO HUE_HI SAT BRI 00 CS
```
- SUBTAG = 0x86
- HUE: 16-bit LE (0-359)
- SAT: 0-100
- BRI: 0-100

### Channel-addressed — TAG 0x92
```
78 92 LEN NETID[4] CH 86 PARAMS CS
```
- Built via: `setRGB1GroupLightValue(146, 5, 134, ch, data)`
- oldOrder/SUBTAG = 134 (0x86)

---

## 4. Scene/Effect Commands

### MAC-addressed — TAG 0x91
```
78 91 LEN MAC[6] 8B SCENE_PARAMS CS
```
- Built via: `setRGB1EffectValue(145, len, 139, params, mac)`
- oldOrder/SUBTAG = 139 (0x8B)

### Channel-addressed — TAG 0x94
```
78 94 LEN NETID[4] CH 8B SCENE_PARAMS CS
```
- Built via: `setRGB1GroupLightValue(148, len, 139, ch, params)`
- oldOrder/SUBTAG = 139 (0x8B)

---

## 5. Network Management

### Assign light to channel — TAG 0x9F, action=1
```
78 9F 0C MAC[6] 01 CH NETID[4] CS    (16 bytes)
```
Assigns the light (identified by MAC) to channel CH with network NETID.

### Remove light from channel — TAG 0x9F, action=2
```
78 9F 0C MAC[6] 02 CH 00 00 00 00 CS    (16 bytes)
```

### Set/Query channel — TAG 0x8C
```
78 8C 0B MAC[6] CH NETID[4] CS    (15 bytes)
```

### Delete from network — TAG 0x9B
```
78 9B 09 MAC[6] 02 01 00 CS    (12 bytes)
```

---

## 6. RGBCW (Direct RGB + Cold/Warm White)

### Direct BLE — TAG 0xA8
```
78 A8 07 BRI R G B C W DBRI CS    (11 bytes)
```
- BRI: master brightness
- R, G, B: 0-255 RGB values
- C: cold white 0-255
- W: warm white 0-255
- DBRI: decimal brightness

### MAC-addressed — TAG 0xA9
```
78 A9 0E MAC[6] A8 BRI R G B C W DBRI CS    (18 bytes)
```
Note: SUBTAG = 0xA8

### Channel-addressed — TAG 0xAA
```
78 AA 0D NETID[4] CH A8 BRI R G B C W DBRI CS    (17 bytes)
```
Note: SUBTAG = 0xA8

---

## 7. Color Paper (Native Gel)

### MAC-addressed — TAG 0xAD
```
78 AD 0D MAC[6] HUE_HI HUE_LO SAT BRI DBRI BRAND GEL_NUM CS    (17 bytes)
```
- HUE: 16-bit (high byte first, then low byte — note: reversed from HSI!)
- SAT: 0-100
- BRI: 0-100
- DBRI: decimal brightness
- BRAND: 1=ROSCO, 2=LEE
- GEL_NUM: gel preset number

### Direct BLE — TAG 0xAF
```
78 AF 07 HUE_HI HUE_LO SAT BRI DBRI BRAND GEL_NUM CS    (11 bytes)
```

### Channel-addressed — TAG 0xAE
```
78 AE 0C NETID[4] CH HUE_HI HUE_LO SAT BRI DBRI BRAND GEL_NUM CS    (16 bytes)
```

---

## 8. Color Coordinate (XY Chromaticity)

### MAC-addressed — TAG 0xB7
```
78 B7 0C MAC[6] BRI X_HI X_LO Y_HI Y_LO DBRI CS    (16 bytes)
```
- X, Y: CIE 1931 chromaticity coordinates
- Encoded as: strip "0." prefix, pad to 4 digits, split into 2 bytes (big-endian)
- Example: x=0.3127 → "3127" → [0x0C, 0x37] (3127 as 16-bit BE)

### Direct BLE — TAG 0xB9
```
78 B9 06 BRI X_HI X_LO Y_HI Y_LO DBRI CS    (10 bytes)
```

### Channel-addressed — TAG 0xB8
```
78 B8 0B NETID[4] CH BRI X_HI X_LO Y_HI Y_LO DBRI CS    (15 bytes)
```

---

## 9. Pixel Effect Commands

### MAC-addressed — TAG 0xB0
```
78 B0 LEN MAC[6] PIXEL_DATA CS
```

### Channel-addressed — TAG 0xB1
```
78 B1 LEN NETID[4] CH PIXEL_DATA CS
```

### Direct BLE — TAG 0xB2
```
78 B2 LEN PIXEL_DATA CS
```

---

## 10. Utility Commands

### Find/Locate device — TAG 0x99
```
78 99 06 MAC[6] CS    (10 bytes)
```
Makes the light flash to help locate it.

### Battery query — TAG 0x95
```
78 95 06 MAC[6] CS    (10 bytes)
```
Response: byte[9] = battery level (0-100, or 0xF0 = charging)

### Device info — TAG 0x9E
```
78 9E 06 MAC[6] CS    (10 bytes)
```

### Power state query — TAG 0x8E
```
78 8E 08 MAC[6] 84 00 CS    (12 bytes)
```

### HW info / Battery (Infinity) — TAG 0x95
```
78 95 06 MAC[6] CS    (10 bytes)
```

### Booster enable/disable — TAG 0xAB
```
78 AB 07 MAC[6] 01 CS    (enable, 11 bytes)
78 AB 07 MAC[6] 02 CS    (disable, 11 bytes)
```

### Booster state query — TAG 0xAC
```
78 AC 06 MAC[6] CS    (10 bytes)
```

### Temperature & Fan mode query — TAG 0xB3
```
78 B3 06 MAC[6] CS    (10 bytes)
```

### Fan mode set — TAG 0xB4
```
78 B4 07 MAC[6] FAN_MODE CS    (11 bytes)
```

### BLE switch — TAG 0x9A
Toggles Bluetooth discoverability on the light.

### Online query — TAG 0x9D
Checks if light is responsive.

### RGBW (simple) — TAG 0xD9
```
78 D9 08 MAC[6] BRI COLOR_IDX CS    (12 bytes)
```

### Double light query — TAG 0xBD
For dual-panel lights (e.g., lights with two independent zones).

### Double light set — TAG 0xBE
Sets parameters for dual-panel lights.

---

## 11. Firmware Update

### Start update — TAG 0x96
```
78 96 LEN VERSION[3] SIZE[4] CHECK[4] PROJECT_NAME CS
```

### Send firmware packet — TAG 0x97
```
78 97 LEN DATA CS
```

### Large packet (4096) — TAG 0xCF
```
78 CF LEN_LO LEN_HI DATA CS
```
Uses 2-byte length field for packets > 255 bytes.

### Streamer effect — TAG 0xBF
Multi-step protocol for LED strip effects.

---

## TAG Summary Table

| TAG | Hex | Name | Address Mode |
|-----|-----|------|-------------|
| 0x80 | 128 | Device info | — |
| 0x81 | 129 | Legacy power | Bluetooth |
| 0x82 | 130 | Legacy brightness | Bluetooth |
| 0x83 | 131 | Legacy CCT | Bluetooth |
| 0x84 | 132 | Query channel | — |
| 0x85 | 133 | Query power state | — |
| 0x8C | 140 | Channel setting | MAC |
| 0x8D | 141 | Power (MAC) | MAC |
| 0x8E | 142 | Power query | MAC |
| 0x8F | 143 | HSI (MAC) | MAC |
| 0x90 | 144 | CCT (MAC) | MAC |
| 0x91 | 145 | Scene (MAC) | MAC |
| 0x92 | 146 | HSI (Channel) | Channel |
| 0x93 | 147 | CCT (Channel) | Channel |
| 0x94 | 148 | Scene (Channel) | Channel |
| 0x95 | 149 | Battery query | MAC |
| 0x96 | 150 | FW update start | — |
| 0x97 | 151 | FW data packet | — |
| 0x98 | 152 | Power (Channel) | Channel |
| 0x99 | 153 | Find device | MAC |
| 0x9A | 154 | BT switch | MAC |
| 0x9B | 155 | Network edit | MAC |
| 0x9D | 157 | Online query | MAC |
| 0x9E | 158 | Device info | MAC |
| 0x9F | 159 | Network config | MAC |
| 0xA0 | 160 | Effect query | — |
| 0xA1 | 161 | Effect pick | — |
| 0xA2 | 162 | Effect frame | — |
| 0xA8 | 168 | RGBCW | Bluetooth |
| 0xA9 | 169 | RGBCW (MAC) | MAC |
| 0xAA | 170 | RGBCW (Channel) | Channel |
| 0xAB | 171 | Booster set | MAC |
| 0xAC | 172 | Booster query | MAC |
| 0xAD | 173 | Color Paper (MAC) | MAC |
| 0xAE | 174 | Color Paper (Channel) | Channel |
| 0xAF | 175 | Color Paper | Bluetooth |
| 0xB0 | 176 | Pixel (MAC) | MAC |
| 0xB1 | 177 | Pixel (Channel) | Channel |
| 0xB2 | 178 | Pixel | Bluetooth |
| 0xB3 | 179 | Temp/Fan query | MAC |
| 0xB4 | 180 | Fan mode set | MAC |
| 0xB7 | 183 | XY Color (MAC) | MAC |
| 0xB8 | 184 | XY Color (Channel) | Channel |
| 0xB9 | 185 | XY Color | Bluetooth |
| 0xBD | 189 | Double light query | MAC |
| 0xBE | 190 | Double light set | MAC |
| 0xBF | 191 | Streamer effect | — |
| 0xCF | 207 | FW data 4096 | — |
| 0xD9 | 217 | RGBW (MAC) | MAC |

## SUBTAG (oldOrder) Values

These are the "sub-command" identifiers used as the first payload byte in both MAC and Channel commands:

| SUBTAG | Hex | Mode |
|--------|-----|------|
| 0x81 | 129 | Power |
| 0x86 | 134 | HSI |
| 0x87 | 135 | CCT |
| 0x8B | 139 | Scene |
| 0xA8 | 168 | RGBCW |

## Channel Command Envelope

Channel commands follow this exact layout:
```
78 TAG LEN NETID[4] CH SUBTAG PARAMS CS
 │   │   │    │      │    │      │     └─ sum(all_except_last) & 0xFF
 │   │   │    │      │    │      └─────── variable payload
 │   │   │    │      │    └────────────── old command TAG (0x86/0x87/0x8B/0xA8)
 │   │   │    │      └─────────────────── channel number (1 byte)
 │   │   │    └────────────────────────── NetworkId (4 bytes LE)
 │   │   └─────────────────────────────── len(NETID) + 1(CH) + 1(SUBTAG) + len(PARAMS)
 │   └─────────────────────────────────── command TAG
 └─────────────────────────────────────── 0x78 header
```

vs MAC command:
```
78 TAG LEN MAC[6] SUBTAG PARAMS CS
```

The key difference: MAC commands use 6-byte address, channel commands use 4-byte NetworkId + 1-byte channel = 5 bytes. LEN adjusts accordingly.

## Workflow: Grouping Lights

1. Connect to each light individually via BLE
2. Send channel assign: `78 9F 0C MAC[6] 01 CH NETID[4] CS`
3. Disconnect from all but one light (the "master")
4. Send channel-addressed commands through the master: `78 92/93/94/98 ...`
5. All lights on that channel respond to the broadcast

To remove a light: `78 9F 0C MAC[6] 02 CH 00 00 00 00 CS`
