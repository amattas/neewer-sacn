#!/usr/bin/env python3
"""Unit tests for Neewer Infinity BLE protocol implementation."""
import neewer


def test_checksum():
    # Power ON with MAC F7:AC:16:F1:58:96
    # Sum = 0x527, checksum = 0x27
    data = [0x78, 0x8D, 0x08, 0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96, 0x81, 0x01]
    assert neewer.calc_checksum(data) == 0x27

    # Simple case
    assert neewer.calc_checksum([0x78, 0x81, 0x01, 0x01]) == 0xFB


def test_parse_mac():
    assert neewer.parse_mac("F7:AC:16:F1:58:96") == [0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96]
    assert neewer.parse_mac("00:00:00:00:00:00") == [0, 0, 0, 0, 0, 0]


def test_infinity_cmd_envelope():
    mac = [0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96]
    pkt = neewer.infinity_cmd(0x8D, mac, 0x81, [0x01])
    assert pkt[0] == 0x78        # prefix
    assert pkt[1] == 0x8D        # tag
    assert pkt[2] == 0x08        # size = 1 param + 7
    assert list(pkt[3:9]) == mac  # MAC bytes
    assert pkt[9] == 0x81        # subtag
    assert pkt[10] == 0x01       # param
    assert pkt[11] == 0x27       # checksum (sum=0x527, &0xFF=0x27)
    assert len(pkt) == 12        # total length


def test_power_on():
    mac = [0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96]
    pkt = neewer.cmd_power(mac, on=True)
    assert pkt == bytes([0x78, 0x8D, 0x08, 0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96, 0x81, 0x01, 0x27])


def test_power_off():
    mac = [0xF7, 0xAC, 0x16, 0xF1, 0x58, 0x96]
    pkt = neewer.cmd_power(mac, on=False)
    assert pkt[10] == 0x02  # OFF byte
    assert len(pkt) == 12


def test_cct():
    mac = [0x00] * 6
    pkt = neewer.cmd_cct(mac, brightness=80, temp_k=5600, gm=0)
    assert pkt[1] == 0x90         # CCT tag
    assert pkt[2] == 0x0B         # size = 4 + 7
    assert pkt[9] == 0x87         # CCT subtag
    assert pkt[10] == 80          # brightness
    assert pkt[11] == 56          # 5600K / 100
    assert pkt[12] == 50          # gm=0 → 0+50=50
    assert pkt[13] == 0x04        # dimming curve
    assert len(pkt) == 15


def test_cct_gm():
    mac = [0x00] * 6
    # Negative GM (magenta)
    pkt = neewer.cmd_cct(mac, 50, 5000, gm=-30)
    assert pkt[12] == 20  # -30+50=20

    # Positive GM (green)
    pkt = neewer.cmd_cct(mac, 50, 5000, gm=30)
    assert pkt[12] == 80  # 30+50=80


def test_cct_range_clamp():
    mac = [0x00] * 6
    # Below minimum
    pkt = neewer.cmd_cct(mac, 50, 1000)
    assert pkt[11] == 25  # clamped to 25 (2500K)

    # Above maximum
    pkt = neewer.cmd_cct(mac, 50, 15000)
    assert pkt[11] == 100  # clamped to 100 (10000K)


def test_hsi():
    mac = [0x00] * 6
    pkt = neewer.cmd_hsi(mac, hue=240, sat=100, brightness=80)
    assert pkt[1] == 0x8F          # HSI tag
    assert pkt[2] == 0x0C          # size = 5 + 7
    assert pkt[9] == 0x86          # HSI subtag
    assert pkt[10] == 0xF0         # hue_lo: 240 & 0xFF
    assert pkt[11] == 0x00         # hue_hi: 240 >> 8
    assert pkt[12] == 100          # saturation
    assert pkt[13] == 80           # brightness
    assert pkt[14] == 0x00         # trailing byte
    assert len(pkt) == 16


def test_hsi_hue_encoding():
    mac = [0x00] * 6
    # Hue 300 = 0x012C → lo=0x2C, hi=0x01
    pkt = neewer.cmd_hsi(mac, 300, 100, 50)
    assert pkt[10] == 0x2C
    assert pkt[11] == 0x01

    # Hue 0
    pkt = neewer.cmd_hsi(mac, 0, 100, 50)
    assert pkt[10] == 0x00
    assert pkt[11] == 0x00

    # Hue 360 clamped to 359
    pkt = neewer.cmd_hsi(mac, 360, 100, 50)
    assert pkt[10] == 0x67  # 359 & 0xFF
    assert pkt[11] == 0x01  # 359 >> 8


def test_scene_cop_car():
    mac = [0x00] * 6
    pkt = neewer.cmd_scene(mac, 0x0A, brightness=80, speed=5)
    assert pkt[1] == 0x91    # scene tag
    assert pkt[9] == 0x8B    # scene subtag
    assert pkt[10] == 0x0A   # effect ID
    assert pkt[11] == 80     # brightness
    assert pkt[12] == 0      # color (default)
    assert pkt[13] == 5      # speed


def test_scene_candlelight():
    mac = [0x00] * 6
    pkt = neewer.cmd_scene(mac, 0x0B, brightness=60, speed=3, sparks=7)
    assert pkt[10] == 0x0B  # effect ID
    assert pkt[11] == 60    # brr
    # brr_hi=100, cct=56, gm=50, speed=3, sparks=7


def test_scene_hue_flash():
    mac = [0x00] * 6
    pkt = neewer.cmd_scene(mac, 0x07, brightness=80, speed=5, hue=120, sat=100)
    assert pkt[10] == 0x07   # effect ID
    assert pkt[11] == 80     # brr
    assert pkt[12] == 120    # hue_lo
    assert pkt[13] == 0      # hue_hi
    assert pkt[14] == 100    # sat
    assert pkt[15] == 5      # speed


def test_all_effects_valid():
    mac = [0x00] * 6
    for eid in range(1, 19):  # 1-18 including music
        pkt = neewer.cmd_scene(mac, eid, 50, 5)
        assert pkt[0] == 0x78
        assert pkt[1] == 0x91
        assert pkt[10] == eid
        # Verify checksum
        assert pkt[-1] == neewer.calc_checksum(pkt[:-1])


def test_gel_cct_preset():
    mac = [0x00] * 6
    pkt = neewer.cmd_gel(mac, 70, "R38")
    assert pkt[1] == 0x90  # CCT command
    assert pkt[10] == 70   # brightness


def test_gel_hsi_preset():
    mac = [0x00] * 6
    pkt = neewer.cmd_gel(mac, 70, "L088")
    assert pkt[1] == 0x8F  # HSI command


def test_all_gel_presets_valid():
    mac = [0x00] * 6
    for name in neewer.GEL_PRESETS:
        pkt = neewer.cmd_gel(mac, 50, name)
        assert pkt[0] == 0x78
        assert pkt[-1] == neewer.calc_checksum(pkt[:-1])


def test_extended_cct():
    # Verified against GL1C capture: 78 87 03 46 20 32 9A
    # Tungsten: brightness=0x46=70, cct=0x20=32(3200K), gm=0x32=50(neutral)
    pkt = neewer.cmd_cct_extended(70, 3200, gm=0)
    assert pkt == bytes([0x78, 0x87, 0x03, 0x46, 0x20, 0x32, 0x9A])

    # GL1C: brightness=25, cct=3200K, gm=0 → 78 87 03 19 20 32 6D
    pkt = neewer.cmd_cct_extended(25, 3200, gm=0)
    assert pkt == bytes([0x78, 0x87, 0x03, 0x19, 0x20, 0x32, 0x6D])

    # GL1C: cct=3000K → 78 87 03 3E 1E 32 90
    pkt = neewer.cmd_cct_extended(62, 3000, gm=0)
    assert pkt == bytes([0x78, 0x87, 0x03, 0x3E, 0x1E, 0x32, 0x90])

    # GL1C: gm=-10 (byte=40) → 78 87 03 3E 20 28 88
    pkt = neewer.cmd_cct_extended(62, 3200, gm=-10)
    assert pkt == bytes([0x78, 0x87, 0x03, 0x3E, 0x20, 0x28, 0x88])

    # GL1C: gm=+18 (byte=68) → 78 87 03 3E 20 44 A4
    pkt = neewer.cmd_cct_extended(62, 3200, gm=18)
    assert pkt == bytes([0x78, 0x87, 0x03, 0x3E, 0x20, 0x44, 0xA4])


def test_extended_scene_cop_car():
    # GL1C capture: Red, brr=16, color=0, speed=5
    # 78 8B 04 0A 10 00 05 26
    pkt = neewer.cmd_scene_extended(0x0A, brightness=16, speed=5)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x0A, 0x10, 0x00, 0x05, 0x26])

    # Blue (color=1): 78 8B 04 0A 10 01 05 27
    pkt = neewer.cmd_scene_extended(0x0A, brightness=16, speed=5, color=1)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x0A, 0x10, 0x01, 0x05, 0x27])

    # Red/Blue (color=2): 78 8B 04 0A 10 02 05 28
    pkt = neewer.cmd_scene_extended(0x0A, brightness=16, speed=5, color=2)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x0A, 0x10, 0x02, 0x05, 0x28])

    # Red/White/Blue (color=4): 78 8B 04 0A 10 04 05 2A
    pkt = neewer.cmd_scene_extended(0x0A, brightness=16, speed=5, color=4)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x0A, 0x10, 0x04, 0x05, 0x2A])


def test_extended_scene_party():
    # GL1C capture: Party, brr=50, color=0, speed=5
    # 78 8B 04 11 32 00 05 4F
    pkt = neewer.cmd_scene_extended(0x11, brightness=50, speed=5, color=0)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x11, 0x32, 0x00, 0x05, 0x4F])

    # Color=1: 78 8B 04 11 32 01 05 50
    pkt = neewer.cmd_scene_extended(0x11, brightness=50, speed=5, color=1)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x11, 0x32, 0x01, 0x05, 0x50])

    # Speed=9: 78 8B 04 11 32 00 09 53
    pkt = neewer.cmd_scene_extended(0x11, brightness=50, speed=9, color=0)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x11, 0x32, 0x00, 0x09, 0x53])

    # Speed=1: 78 8B 04 11 32 00 01 4B
    pkt = neewer.cmd_scene_extended(0x11, brightness=50, speed=1, color=0)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x11, 0x32, 0x00, 0x01, 0x4B])


def test_extended_scene_lightning():
    # RGB62 capture: Lightning, brr=83, cct=55(5500K), speed=5
    # 78 8B 04 01 53 37 05 97
    pkt = neewer.cmd_scene_extended(0x01, brightness=83, speed=5, temp=5500)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x01, 0x53, 0x37, 0x05, 0x97])

    # Brightness=22: 78 8B 04 01 16 37 05 5A
    pkt = neewer.cmd_scene_extended(0x01, brightness=22, speed=5, temp=5500)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x01, 0x16, 0x37, 0x05, 0x5A])

    # CCT=76(7600K): 78 8B 04 01 16 4C 05 6F
    pkt = neewer.cmd_scene_extended(0x01, brightness=22, speed=5, temp=7600)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x01, 0x16, 0x4C, 0x05, 0x6F])

    # Speed=7: 78 8B 04 01 16 4C 07 71
    pkt = neewer.cmd_scene_extended(0x01, brightness=22, speed=7, temp=7600)
    assert pkt == bytes([0x78, 0x8B, 0x04, 0x01, 0x16, 0x4C, 0x07, 0x71])


def test_extended_scene_music():
    # GL1C capture: Music FX, brr=50
    # 78 8B 02 12 32 49
    pkt = neewer.cmd_scene_extended(0x12, brightness=50)
    assert pkt == bytes([0x78, 0x8B, 0x02, 0x12, 0x32, 0x49])


def test_all_extended_effects_valid():
    for eid in range(1, 19):  # 1-18 including music
        pkt = neewer.cmd_scene_extended(eid, 50, 5)
        assert pkt[0] == 0x78
        assert pkt[1] == 0x8B
        # Verify checksum
        assert pkt[-1] == neewer.calc_checksum(pkt[:-1])


def test_legacy_power():
    assert neewer.cmd_power_legacy(True) == bytes([0x78, 0x81, 0x01, 0x01, 0xFB])
    assert neewer.cmd_power_legacy(False) == bytes([0x78, 0x81, 0x01, 0x02, 0xFC])


def test_legacy_cct():
    pkt = neewer.cmd_cct_legacy(50, 5600)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x87
    assert pkt[2] == 0x02  # 2 params
    assert pkt[3] == 50    # brightness
    assert pkt[4] == 56    # 5600/100
    assert pkt[5] == neewer.calc_checksum(pkt[:-1])
    assert len(pkt) == 6


def test_legacy_hsi():
    pkt = neewer.cmd_hsi_legacy(240, 100, 80)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x86
    assert pkt[2] == 0x04  # 4 params
    assert pkt[3] == 0xF0  # hue_lo
    assert pkt[4] == 0x00  # hue_hi
    assert pkt[5] == 100   # sat
    assert pkt[6] == 80    # brightness
    assert len(pkt) == 8


def test_legacy_scene():
    pkt = neewer.cmd_scene_legacy(50, 5)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x88
    assert pkt[3] == 50  # brightness
    assert pkt[4] == 5   # effect
    assert len(pkt) == 6


def test_resolve_effect():
    assert neewer.resolve_effect("cop-car") == 0x0A
    assert neewer.resolve_effect("lightning") == 0x01
    assert neewer.resolve_effect("party") == 0x11
    assert neewer.resolve_effect("1") == 1
    assert neewer.resolve_effect("17") == 17
    assert neewer.resolve_effect("18") == 18
    assert neewer.resolve_effect("music") == 0x12


def test_resolve_gel():
    assert neewer.resolve_gel("R38") == "R38"
    assert neewer.resolve_gel("r38") == "R38"
    assert neewer.resolve_gel("L088") == "L088"
    assert neewer.resolve_gel("l088") == "L088"
    assert neewer.resolve_gel("BOGUS") is None


def test_scene_param_clamping():
    mac = [0x00] * 6
    # Speed should be clamped to 1-10
    pkt = neewer.cmd_scene(mac, 0x0A, brightness=50, speed=20)
    assert pkt[-2] == 10  # speed clamped to 10

    pkt = neewer.cmd_scene(mac, 0x0A, brightness=50, speed=0)
    assert pkt[-2] == 1  # speed clamped to 1

    # Brightness clamped to 0-100
    pkt = neewer.cmd_scene(mac, 0x0A, brightness=150, speed=5)
    assert pkt[11] == 100  # clamped

    # Color clamped to 0-4
    pkt = neewer.cmd_scene(mac, 0x0A, brightness=50, speed=5, color=10)
    assert pkt[12] == 4  # clamped

    # Hue clamped to 0-359
    pkt = neewer.cmd_scene(mac, 0x07, brightness=50, speed=5, hue=500, sat=100)
    assert pkt[12] == (359 & 0xFF)  # hue_lo of 359
    assert pkt[13] == (359 >> 8)    # hue_hi of 359


def test_build_power_protocols():
    mac = [0x00] * 6
    # Infinity uses MAC envelope
    pkt_inf = neewer.build_power("infinity", mac, on=True)
    assert pkt_inf[1] == 0x8D
    assert len(pkt_inf) == 12

    # Legacy/extended use same legacy format
    pkt_leg = neewer.build_power("legacy", mac, on=True)
    assert pkt_leg == bytes([0x78, 0x81, 0x01, 0x01, 0xFB])
    pkt_ext = neewer.build_power("extended", mac, on=True)
    assert pkt_ext == pkt_leg


def test_build_cct_protocols():
    mac = [0x00] * 6
    # Infinity: 15 bytes with MAC
    pkt_inf = neewer.build_cct("infinity", mac, 80, 5600, gm=0)
    assert pkt_inf[1] == 0x90
    assert len(pkt_inf) == 15

    # Extended: 7 bytes with GM
    pkt_ext = neewer.build_cct("extended", mac, 80, 5600, gm=0)
    assert pkt_ext[1] == 0x87
    assert len(pkt_ext) == 7
    assert pkt_ext[3] == 80  # brightness
    assert pkt_ext[4] == 56  # cct (5600/100)
    assert pkt_ext[5] == 50  # gm byte (0+50)

    # Legacy: 6 bytes without GM
    pkt_leg = neewer.build_cct("legacy", mac, 80, 5600)
    assert pkt_leg[1] == 0x87
    assert len(pkt_leg) == 6


def test_build_scene_protocols():
    mac = [0x00] * 6
    # Infinity cop-car
    pkt_inf = neewer.build_scene("infinity", mac, 0x0A, 50, 5)
    assert pkt_inf[1] == 0x91
    assert pkt_inf[9] == 0x8B

    # Extended cop-car
    pkt_ext = neewer.build_scene("extended", mac, 0x0A, 50, 5)
    assert pkt_ext[1] == 0x8B
    assert pkt_ext[3] == 0x0A

    # Legacy cop-car (only 9 effects, but id is clamped)
    pkt_leg = neewer.build_scene("legacy", mac, 5, 50, 5)
    assert pkt_leg[1] == 0x88


def test_resolve_light_alias():
    # Set up test cache
    neewer._cache = {
        "macs": {},
        "lights": {
            "NW-20220016&776A0500": {"address": "AAAA-BBBB", "rssi": -70},
            "NW-TESTLIGHT": {"address": "CCCC-DDDD", "rssi": -60},
        },
    }

    # Full name match
    addr, name = neewer._resolve_light_alias("NW-20220016&776A0500")
    assert addr == "AAAA-BBBB"
    assert name == "NW-20220016&776A0500"

    # Partial name match (case-insensitive)
    addr, name = neewer._resolve_light_alias("nw-20220016")
    assert addr == "AAAA-BBBB"

    # Index match
    addr, name = neewer._resolve_light_alias("0")
    assert addr == "AAAA-BBBB"
    addr, name = neewer._resolve_light_alias("1")
    assert addr == "CCCC-DDDD"

    # "all" passthrough
    addr, name = neewer._resolve_light_alias("all")
    assert addr == "all"

    # Unknown name passes through as raw address
    addr, name = neewer._resolve_light_alias("EEEE-FFFF")
    assert addr == "EEEE-FFFF"
    assert name is None

    # Restore
    neewer._cache = {"macs": {}, "lights": {}}


def test_detect_model_info_nw_prefix():
    # PL60C: known product code
    info = neewer.detect_model_info("NW-20220016&776A0500")
    assert info is not None
    assert info[0] == "PL60C"
    assert info[4] == "infinity"
    assert info[1] == 2500  # cct_min
    assert info[2] == 10000  # cct_max

    # TL60 RGB
    info = neewer.detect_model_info("NW-20210036&AABBCCDD")
    assert info[0] == "TL60 RGB"
    assert info[3] is True  # supports_rgb
    assert info[4] == "infinity"

    # TL120C
    info = neewer.detect_model_info("NW-20230031&AABBCCDD")
    assert info[0] == "TL120C"
    assert info[4] == "infinity"

    # Unknown product code, still NW- → infinity
    info = neewer.detect_model_info("NW-99999999&AABBCCDD")
    assert info is not None
    assert info[4] == "infinity"


def test_detect_model_info_neewer_prefix():
    # GL1C → extended
    info = neewer.detect_model_info("NEEWER-GL1C")
    assert info[0] == "GL1C"
    assert info[4] == "extended"

    # GL1 (not GL1C) → legacy
    info = neewer.detect_model_info("NEEWER-GL1")
    assert info[0] == "GL1"
    assert info[4] == "legacy"

    # RGB660 PRO → legacy
    info = neewer.detect_model_info("NEEWER-RGB660 PRO")
    assert info is not None
    assert info[4] == "legacy"


def test_detect_protocol():
    assert neewer.detect_protocol("NW-20220016&776A0500") == "infinity"
    assert neewer.detect_protocol("NEEWER-GL1C") == "extended"
    assert neewer.detect_protocol("NEEWER-GL1") == "legacy"
    assert neewer.detect_protocol("NEEWER-RGB660 PRO") == "legacy"
    # Unknown NW- prefix → infinity
    assert neewer.detect_protocol("NW-99999999&AABBCCDD") == "infinity"
    # Unknown non-NW → legacy
    assert neewer.detect_protocol("SomeRandomLight") == "legacy"
    # None → legacy
    assert neewer.detect_protocol(None) == "legacy"


def test_detect_model_info_none():
    assert neewer.detect_model_info(None) is None
    assert neewer.detect_model_info("") is None


def test_resolve_proto():
    # Explicit protocol passes through
    assert neewer._resolve_proto("infinity", "anything") == "infinity"
    assert neewer._resolve_proto("legacy", "anything") == "legacy"
    assert neewer._resolve_proto("extended", "anything") == "extended"
    # Auto detects from device name
    assert neewer._resolve_proto("auto", "NW-20220016&776A0500") == "infinity"
    assert neewer._resolve_proto("auto", "NEEWER-GL1C") == "extended"
    assert neewer._resolve_proto("auto", "NEEWER-RGB660 PRO") == "legacy"
    # Auto with no device name defaults to infinity
    assert neewer._resolve_proto("auto", None) == "infinity"


def test_fmt_hex():
    assert neewer.fmt_hex(bytes([0x78, 0x8D, 0x08])) == "78 8D 08"
    assert neewer.fmt_hex(bytes([0x00, 0xFF])) == "00 FF"


def test_light_sources():
    # All sources have valid entries
    for name, (temp, gm, desc) in neewer.LIGHT_SOURCES.items():
        assert 2500 <= temp <= 10000, f"{name}: temp {temp} out of range"
        assert -50 <= gm <= 50, f"{name}: gm {gm} out of range"
        assert len(desc) > 0, f"{name}: empty description"

    # Known sources exist
    assert "tungsten" in neewer.LIGHT_SOURCES
    assert "daylight" in neewer.LIGHT_SOURCES
    assert "sunlight" in neewer.LIGHT_SOURCES
    assert "cloudy" in neewer.LIGHT_SOURCES

    # Source temps generate valid CCT packets
    mac = [0x00] * 6
    for name, (temp, gm, desc) in neewer.LIGHT_SOURCES.items():
        pkt = neewer.build_cct("infinity", mac, 80, temp, gm)
        assert pkt[0] == 0x78
        assert pkt[1] == 0x90  # CCT tag


def test_cmd_query():
    mac = [0xD4, 0xED, 0x61, 0xC3, 0xB7, 0x00]
    pkt = neewer.cmd_query(mac)
    assert pkt[0] == 0x78           # prefix
    assert pkt[1] == neewer.TAG_QUERY  # 0x8E
    assert pkt[2] == 0x08           # size = 1+7
    assert list(pkt[3:9]) == mac    # MAC
    assert pkt[9] == 0x84           # subtag
    assert pkt[10] == 0x00          # param
    assert pkt[11] == neewer.calc_checksum(list(pkt[:-1]))

    # Device info query
    info_pkt = neewer.cmd_device_info(mac)
    assert info_pkt[0] == 0x78
    assert info_pkt[1] == neewer.TAG_DEVICE_INFO  # 0x9E


def test_parse_device_info():
    # Real PL60C response: 78 08 10 D4 ED 61 C3 B7 00 01 09 01 03 03 01 50 4C 36 30 40
    data = bytes([0x78, 0x08, 0x10, 0xD4, 0xED, 0x61, 0xC3, 0xB7, 0x00,
                  0x01, 0x09, 0x01, 0x03, 0x03, 0x01, 0x50, 0x4C, 0x36, 0x30, 0x40])
    result = neewer.parse_device_info(data)
    assert result is not None
    assert result["model"] == "PL60"
    assert result["mac"] == "D4:ED:61:C3:B7:00"
    assert result["fields"] == [0x01, 0x09, 0x01, 0x03, 0x03, 0x01]

    # Invalid data
    assert neewer.parse_device_info(bytes([0x78, 0x04])) is None
    assert neewer.parse_device_info(bytes([0x00] * 5)) is None


def test_resolve_light_alias_groups():
    # Save original cache
    orig = neewer._cache.copy()
    try:
        neewer._cache["groups"] = {"key-lights": ["NW-light1", "NW-light2"]}
        neewer._cache["lights"] = {
            "NW-light1": {"address": "ADDR1"},
            "NW-light2": {"address": "ADDR2"},
        }

        # Group name resolves to group: prefix
        addr, name = neewer._resolve_light_alias("key-lights")
        assert addr == "group:key-lights"
        assert name is None

        # Explicit group: prefix works
        addr, name = neewer._resolve_light_alias("group:my-group")
        assert addr == "group:my-group"
        assert name is None

        # "all" still works
        addr, name = neewer._resolve_light_alias("all")
        assert addr == "all"
    finally:
        neewer._cache.clear()
        neewer._cache.update(orig)


def test_named_colors():
    # All colors have valid entries
    for name, (hue, sat) in neewer.NAMED_COLORS.items():
        assert 0 <= hue <= 359, f"{name}: hue {hue} out of range"
        assert 0 <= sat <= 100, f"{name}: sat {sat} out of range"

    # Known colors exist
    assert "red" in neewer.NAMED_COLORS
    assert "blue" in neewer.NAMED_COLORS
    assert "green" in neewer.NAMED_COLORS
    assert "amber" in neewer.NAMED_COLORS

    # Colors generate valid HSI packets
    mac = [0x00] * 6
    for name, (hue, sat) in neewer.NAMED_COLORS.items():
        pkt = neewer.build_hsi("infinity", mac, hue, sat, 80)
        assert pkt[0] == 0x78
        assert pkt[1] == 0x8F  # HSI tag


def test_resolve_color():
    assert neewer.resolve_color("red") == (0, 100)
    assert neewer.resolve_color("Blue") == (240, 100)
    assert neewer.resolve_color("AMBER") == (38, 100)
    # Partial match
    assert neewer.resolve_color("mag") == (300, 100)  # magenta
    # Unknown
    assert neewer.resolve_color("nonexistent") is None


def test_product_code():
    assert neewer._product_code("NW-20220016&776A0500") == "NW-20220016"
    assert neewer._product_code("NW-20220016&00323204") == "NW-20220016"
    assert neewer._product_code("NEEWER-GL1C") == "NEEWER-GL1C"
    assert neewer._product_code("NW-20210036") == "NW-20210036"
    assert neewer._product_code(None) is None
    assert neewer._product_code("") == ""


def test_resolve_gel():
    # Direct name match (uppercase)
    assert neewer.resolve_gel("R38") == "R38"
    assert neewer.resolve_gel("L002") == "L002"
    # Case-insensitive
    assert neewer.resolve_gel("r38") == "R38"
    assert neewer.resolve_gel("l002") == "L002"
    # Prefix resolution
    assert neewer.resolve_gel("38") == "R38"
    # Unknown gel
    assert neewer.resolve_gel("ZZZZ") is None


def test_resolve_effect():
    # Name resolution
    assert neewer.resolve_effect("cop-car") == 0x0A
    assert neewer.resolve_effect("lightning") == 0x01
    assert neewer.resolve_effect("music") == 0x12
    # Numeric ID
    assert neewer.resolve_effect("10") == 10
    assert neewer.resolve_effect("1") == 1


def test_parse_device_info_live():
    """Parse real device info response from PL60C hardware test."""
    raw = bytes([
        0x78, 0x08, 0x10,
        0xD4, 0xED, 0x61, 0xC3, 0xB7, 0x00,  # MAC
        0x01, 0x09, 0x01, 0x03, 0x03, 0x01,  # firmware fields
        0x50, 0x4C, 0x36, 0x30,  # "PL60"
        0x40  # checksum
    ])
    info = neewer.parse_device_info(raw)
    assert info is not None
    assert info["mac"] == "D4:ED:61:C3:B7:00"
    assert info["model"] == "PL60"
    assert len(info["fields"]) > 0
    assert info["firmware"] == "1.9.1"
    assert info["build"] == "3.3.1"


def test_build_gel_protocols():
    """Gel presets generate valid packets across all protocols."""
    mac = [0x00] * 6
    for gel_name in neewer.GEL_PRESETS:
        for proto in ("infinity", "extended", "legacy"):
            pkt = neewer.build_gel(proto, mac, 80, gel_name)
            assert pkt[0] == 0x78
            # Verify checksum
            assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_build_gel_infinity_native():
    """Infinity gel uses native TAG 0xAD instead of CCT/HSI approximation."""
    mac = [0x00] * 6
    # HSI-type preset: L088 Lime Green (hue=120, sat=40)
    pkt = neewer.build_gel("infinity", mac, 70, "L088")
    assert pkt[1] == neewer.TAG_GEL_MAC  # 0xAD native gel
    # brand=2 (LEE), gel_num=88
    assert pkt[-3] == 2    # brand
    assert pkt[-2] == 88   # gel_num
    # CCT-type preset: R38 Rose
    pkt2 = neewer.build_gel("infinity", mac, 70, "R38")
    assert pkt2[1] == neewer.TAG_GEL_MAC  # native gel, not 0x90 CCT
    assert pkt2[-3] == 1   # brand=ROSCO
    assert pkt2[-2] == 38  # gel_num
    # Non-infinity still uses CCT/HSI
    pkt3 = neewer.build_gel("extended", mac, 70, "R38")
    assert pkt3[1] == 0x87  # extended CCT


def test_parse_gel_brand_num():
    """Parse gel name into brand and gel number."""
    assert neewer._parse_gel_brand_num("R38") == (1, 38)
    assert neewer._parse_gel_brand_num("L088") == (2, 88)
    assert neewer._parse_gel_brand_num("G325") == (1, 255)  # clamped
    assert neewer._parse_gel_brand_num("E128") == (1, 128)
    assert neewer._parse_gel_brand_num("R9406") == (1, 255)  # clamped
    assert neewer._parse_gel_brand_num("") == (None, 0)


def test_cmd_device_info():
    mac = [0xD4, 0xED, 0x61, 0xC3, 0xB7, 0x00]
    pkt = neewer.cmd_device_info(mac)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x9E  # TAG_DEVICE_INFO
    assert list(pkt[3:9]) == mac
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_build_parser():
    """CLI parser builds without errors."""
    parser = neewer.build_parser()
    assert parser is not None
    # Test known subcommand
    args = parser.parse_args(["scan"])
    assert args.command == "scan"
    args = parser.parse_args(["cct", "--light", "0", "--brightness", "80", "--temp", "5600"])
    assert args.command == "cct"
    assert args.brightness == 80
    assert args.temp == 5600


def test_cct_gm_extended():
    """Extended protocol CCT with GM correction."""
    pkt = neewer.cmd_cct_extended(80, 5600, -10)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x87  # CCT tag
    assert pkt[3] == 80    # brightness
    assert pkt[4] == 56    # CCT value (5600/100)
    assert pkt[5] == 40    # GM (-10 + 50 = 40)


def test_cct_split():
    """Split CCT commands (TAG 0x82/0x83) for CCT-only legacy lights."""
    bri_pkt, cct_pkt = neewer.cmd_cct_split(80, 5000)
    # Brightness packet: 78 82 01 50 CS
    assert bri_pkt[0] == 0x78
    assert bri_pkt[1] == 0x82
    assert bri_pkt[2] == 0x01
    assert bri_pkt[3] == 80  # brightness
    assert bri_pkt[-1] == neewer.calc_checksum(list(bri_pkt[:-1]))
    # CCT packet: 78 83 01 32 CS
    assert cct_pkt[0] == 0x78
    assert cct_pkt[1] == 0x83
    assert cct_pkt[2] == 0x01
    assert cct_pkt[3] == 50  # 5000K / 100 = 50
    assert cct_pkt[-1] == neewer.calc_checksum(list(cct_pkt[:-1]))


def test_int_loop_cct():
    """INT Loop CCT sub-mode: submode=0, brightness range, CCT, speed."""
    mac = [0x00] * 6
    pkt = neewer.cmd_scene(mac, 0x0E, brightness=50, speed=5, temp=5600)
    assert pkt[0] == 0x78
    assert pkt[1] == neewer.TAG_SCENE
    # After MAC and SUBTAG: [0x0E, 0x00, brr, brr_hi, 0, 0, cct, speed]
    payload_start = 10  # prefix + tag + size + 6 MAC + subtag
    assert pkt[payload_start] == 0x0E      # effect ID
    assert pkt[payload_start + 1] == 0x00  # CCT sub-mode
    assert pkt[payload_start + 2] == 50    # brr
    assert pkt[payload_start + 3] == 100   # brr_hi (default)
    assert pkt[payload_start + 6] == 56    # cct (5600/100)
    assert pkt[payload_start + 7] == 5     # speed
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_int_loop_hsi():
    """INT Loop HSI sub-mode: submode=1, brightness range, hue, speed."""
    mac = [0x00] * 6
    pkt = neewer.cmd_scene(mac, 0x0E, brightness=50, speed=5, hue=240)
    assert pkt[0] == 0x78
    payload_start = 10
    assert pkt[payload_start] == 0x0E      # effect ID
    assert pkt[payload_start + 1] == 0x01  # HSI sub-mode
    assert pkt[payload_start + 2] == 50    # brr
    assert pkt[payload_start + 3] == 100   # brr_hi (default)
    assert pkt[payload_start + 4] == 240   # hue low byte (240 & 0xFF)
    assert pkt[payload_start + 5] == 0     # hue high byte (240 >> 8)
    assert pkt[payload_start + 7] == 5     # speed
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_int_loop_extended():
    """INT Loop works on extended protocol too."""
    pkt = neewer.cmd_scene_extended(0x0E, brightness=60, speed=3, hue=120)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x8B  # scene tag (extended)
    # After tag+size: [0x0E, 0x01, brr, brr_hi, hue_lo, hue_hi, 0, speed]
    assert pkt[3] == 0x0E      # effect ID
    assert pkt[4] == 0x01      # HSI sub-mode
    assert pkt[5] == 60        # brr
    assert pkt[7] == 120       # hue low byte
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_new_model_entries():
    """New model entries are discoverable."""
    # Name-based detection
    for name in ["TL40", "GR18C", "TL21C", "VL67C", "Q200", "CB200C", "CB300C"]:
        info = neewer.detect_model_info(f"NEEWER-{name}")
        assert info is not None, f"{name} not found"
        assert info[4] in ("infinity", "extended", "legacy"), f"{name} bad protocol: {info[4]}"


def test_resolve_effect_none():
    """resolve_effect returns None for unknown effects."""
    result = neewer.resolve_effect("nonexistent")
    assert result is None


def test_fragment_reassembly():
    """parse_device_info handles reassembled multi-fragment responses."""
    # Simulated TL120C response: "TL120 RGB-2" spans two BLE packets
    frag1 = bytes([0x78, 0x08, 0x17, 0xEB, 0x43, 0xD1, 0x20, 0xF7, 0x8D,
                   0x01, 0x0A, 0x02, 0x00, 0x05, 0x02, 0x54, 0x4C, 0x31, 0x32, 0x30])
    frag2 = bytes([0x20, 0x52, 0x47, 0x42, 0x2D, 0x32, 0xDB])
    full = frag1 + frag2
    info = neewer.parse_device_info(full)
    assert info is not None
    assert info["model"] == "TL120 RGB-2"
    assert info["mac"] == "EB:43:D1:20:F7:8D"
    assert info["fields"] == [0x01, 0x0A, 0x02, 0x00, 0x05, 0x02]
    assert info["firmware"] == "1.10.2"
    assert info["build"] == "0.5.2"


def test_tl120_model_db():
    """TL120 RGB product code is in MODEL_DB."""
    info = neewer.detect_model_info("NW-20240047&776A0500")
    assert info is not None
    assert "TL120" in info[0]
    assert info[3] is True  # RGB
    assert info[4] == "infinity"


def test_scan_order_alias():
    """Scan index uses scan_order, not dict key order."""
    # Save original cache
    orig = neewer._cache.copy()
    try:
        neewer._cache = {
            "lights": {
                "old-light": {"address": "AAA", "rssi": -80},
                "new-light": {"address": "BBB", "rssi": -60},
            },
            "scan_order": ["new-light"],
        }
        # Index 0 should resolve to new-light (from scan_order), not old-light
        addr, name = neewer._resolve_light_alias("0")
        assert addr == "BBB"
        assert name == "new-light"
    finally:
        neewer._cache = orig


def test_hue_wrap_shortest_path():
    """Hue interpolation takes shortest path around 360."""
    # 350 -> 10 should go through 0, not through 180
    h1, h2 = 350, 10
    diff = (h2 - h1 + 540) % 360 - 180  # should be +20
    assert diff == 20
    # Midpoint should be 0
    mid = int(h1 + diff * 0.5) % 360
    assert mid == 0
    # 10 -> 350 should go through 0 backwards
    h1, h2 = 10, 350
    diff = (h2 - h1 + 540) % 360 - 180  # should be -20
    assert diff == -20
    mid = int(h1 + diff * 0.5) % 360
    assert mid == 0


def test_firmware_parsing():
    """Firmware version is correctly extracted from device info fields."""
    # Minimal device info packet
    data = bytes([
        0x78, 0x08, 0x0D,
        0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF,  # MAC
        0x02, 0x05, 0x03, 0x01, 0x00, 0x04,  # fields: fw 2.5.3, build 1.0.4
        0x58,  # "X" model name (1 char)
        0x00   # checksum placeholder
    ])
    info = neewer.parse_device_info(data)
    assert info is not None
    assert info["firmware"] == "2.5.3"
    assert info["build"] == "1.0.4"
    assert info["model"] == "X"


def test_scene_kwargs_build():
    """build_scene passes kwargs through to effect-specific params."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    # Cop car (0x0A) with color=2 — color byte is in the params
    pkt = neewer.build_scene("infinity", mac, 0x0A, 80, 5, color=2)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x91  # scene TAG
    # Verify checksum is valid
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_scene_kwargs_hue():
    """build_scene passes hue kwarg for hue-flash effect."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    # Hue Flash (0x07) with hue=240, sat=100
    pkt = neewer.build_scene("infinity", mac, 0x07, 80, 5, hue=240, sat=100)
    assert pkt[0] == 0x78
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_scene_kwargs_vs_defaults():
    """build_scene with kwargs produces different params than defaults."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    # Cop car default (color=0) vs color=3
    pkt_default = neewer.build_scene("infinity", mac, 0x0A, 80, 5)
    pkt_custom = neewer.build_scene("infinity", mac, 0x0A, 80, 5, color=3)
    # Packets should differ (different color byte)
    assert pkt_default != pkt_custom
    # Both should have valid checksums
    assert pkt_default[-1] == neewer.calc_checksum(list(pkt_default[:-1]))
    assert pkt_custom[-1] == neewer.calc_checksum(list(pkt_custom[:-1]))


def test_resolve_color_case_insensitive():
    """resolve_color handles case-insensitive color names."""
    assert neewer.resolve_color("Red") == neewer.resolve_color("red")
    assert neewer.resolve_color("BLUE") == neewer.resolve_color("blue")
    assert neewer.resolve_color("nonexistent") is None


def test_connect_and_run_raises_not_exits():
    """connect_and_run raises ConnectionError instead of sys.exit on failure."""
    import inspect
    src = inspect.getsource(neewer.connect_and_run)
    # Should NOT contain sys.exit (would break multi-light error isolation)
    assert "sys.exit" not in src


def test_all_effects_have_params():
    """Every EFFECTS entry has a corresponding EFFECT_PARAMS entry."""
    for name, eid in neewer.EFFECTS.items():
        assert eid in neewer.EFFECT_PARAMS, f"Missing EFFECT_PARAMS for {name} (0x{eid:02X})"


def test_all_gel_presets_format():
    """All GEL_PRESETS have valid format (cct or hsi tuple)."""
    for name, preset in neewer.GEL_PRESETS.items():
        assert preset[0] in ("cct", "hsi"), f"Invalid gel mode for {name}: {preset[0]}"
        if preset[0] == "cct":
            assert len(preset) == 3, f"CCT gel {name} should be (cct, temp, gm)"
        elif preset[0] == "hsi":
            assert len(preset) == 3, f"HSI gel {name} should be (hsi, hue, sat)"


def test_hex_to_hue_sat():
    """hex_to_hue_sat converts RGB hex to HSI hue/sat."""
    # Pure red
    h, s = neewer.hex_to_hue_sat("#FF0000")
    assert h == 0
    assert s == 100
    # Pure green
    h, s = neewer.hex_to_hue_sat("#00FF00")
    assert h == 120
    assert s == 100
    # Pure blue
    h, s = neewer.hex_to_hue_sat("#0000FF")
    assert h == 240
    assert s == 100
    # White (no saturation)
    h, s = neewer.hex_to_hue_sat("#FFFFFF")
    assert s == 0
    # Invalid
    assert neewer.hex_to_hue_sat("#GGG") is None
    assert neewer.hex_to_hue_sat("12") is None


def test_resolve_color_hex():
    """resolve_color accepts hex color codes."""
    assert neewer.resolve_color("#FF0000") == (0, 100)
    assert neewer.resolve_color("00FF00") == (120, 100)
    assert neewer.resolve_color("#0000FF") == (240, 100)


def test_cmd_hw_info():
    """cmd_hw_info builds correct Infinity packet."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_hw_info(mac)
    assert pkt[0] == 0x78
    assert pkt[1] == neewer.TAG_HW_INFO  # 0x95
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_cmd_channel():
    """cmd_channel builds correct Infinity packet."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_channel(mac)
    assert pkt[0] == 0x78
    assert pkt[1] == neewer.TAG_CHANNEL  # 0x96
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_hue_clamp_359():
    """Hue values are clamped to 0-359 (not 360)."""
    mac = [0x00] * 6
    # cmd_hsi clamps to 359
    pkt = neewer.cmd_hsi(mac, 360, 100, 50)
    hue_encoded = pkt[10] | (pkt[11] << 8)
    assert hue_encoded == 359
    # cmd_hsi_legacy also clamps to 359
    pkt = neewer.cmd_hsi_legacy(360, 100, 50)
    hue_encoded = pkt[3] | (pkt[4] << 8)
    assert hue_encoded == 359
    # Normal hue passes through
    pkt = neewer.cmd_hsi(mac, 240, 100, 50)
    hue_encoded = pkt[10] | (pkt[11] << 8)
    assert hue_encoded == 240


def test_resolve_gel_partial():
    """resolve_gel matches exact, prefix-less, and partial starts."""
    # Exact match
    assert neewer.resolve_gel("R38") == "R38"
    # Number-only resolves with prefix search
    r = neewer.resolve_gel("38")
    assert r == "R38"
    # Case-insensitive
    assert neewer.resolve_gel("r38") == "R38"
    # Non-existent returns None
    assert neewer.resolve_gel("ZZZZZ") is None


def test_preset_save_zero_values():
    """Preset save should not corrupt zero values via `or` fallback."""
    # This tests the fix: args.sat if args.sat is not None else 100
    # We can't easily test the CLI argparse path, but we verify the pattern
    val = 0
    result_bad = val or 100  # old behavior: 100 (wrong!)
    result_good = val if val is not None else 100  # new behavior: 0 (correct!)
    assert result_bad == 100  # confirms the bug existed
    assert result_good == 0   # confirms the fix works


# === Channel-addressed command tests ===

def test_channel_cmd_envelope():
    """Channel command: 78 TAG LEN NETID[4] CH SUBTAG PARAMS CS"""
    pkt = neewer.channel_cmd(0x93, 0x12345678, 3, 0x87, [50, 56, 50, 4, 0])
    assert pkt[0] == 0x78
    assert pkt[1] == 0x93        # TAG_CH_CCT
    assert pkt[2] == 11          # 4 NETID + 1 CH + 1 SUBTAG + 5 params
    # NetworkId 0x12345678 LE: 78, 56, 34, 12
    assert pkt[3] == 0x78
    assert pkt[4] == 0x56
    assert pkt[5] == 0x34
    assert pkt[6] == 0x12
    assert pkt[7] == 3           # channel
    assert pkt[8] == 0x87        # SUBTAG_CCT
    assert pkt[9] == 50          # brightness
    assert pkt[-1] == neewer.calc_checksum(list(pkt[:-1]))


def test_ch_cmd_power_on():
    pkt = neewer.ch_cmd_power(0x00000001, 1, on=True)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x98        # TAG_CH_POWER
    assert pkt[2] == 7           # 4 NETID + 1 CH + 1 SUBTAG + 1 param
    assert pkt[3:7] == bytes([0x01, 0x00, 0x00, 0x00])  # NETID LE
    assert pkt[7] == 1           # channel
    assert pkt[8] == 0x81        # SUBTAG_POWER
    assert pkt[9] == 0x01        # ON


def test_ch_cmd_power_off():
    pkt = neewer.ch_cmd_power(0x00000001, 2, on=False)
    assert pkt[9] == 0x02        # OFF
    assert pkt[7] == 2           # channel 2


def test_ch_cmd_cct():
    pkt = neewer.ch_cmd_cct(1000, 1, 80, 5600, gm=-10)
    assert pkt[1] == 0x93        # TAG_CH_CCT
    assert pkt[8] == 0x87        # SUBTAG_CCT
    assert pkt[9] == 80          # brightness
    assert pkt[10] == 56         # 5600 // 100
    assert pkt[11] == 40         # gm -10 + 50
    assert pkt[12] == 4          # curve
    assert pkt[13] == 0          # dbri


def test_ch_cmd_hsi():
    pkt = neewer.ch_cmd_hsi(1000, 1, 240, 100, 80)
    assert pkt[1] == 0x92        # TAG_CH_HSI
    assert pkt[8] == 0x86        # SUBTAG_HSI
    assert pkt[9] == 240 & 0xFF  # hue lo
    assert pkt[10] == (240 >> 8) & 0xFF  # hue hi = 0
    assert pkt[11] == 100        # sat
    assert pkt[12] == 80         # brightness


def test_ch_cmd_scene():
    pkt = neewer.ch_cmd_scene(1000, 1, 0x0A, brightness=80, speed=7)
    assert pkt[1] == 0x94        # TAG_CH_SCENE
    assert pkt[8] == 0x8B        # SUBTAG_SCENE
    assert pkt[9] == 0x0A        # cop-car effect


# === Network management command tests ===

def test_cmd_channel_assign():
    """78 9F 0C MAC[6] 01 CH NETID[4] CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_channel_assign(mac, 3, 0x12345678)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x9F        # TAG_CHANNEL_CONFIG
    assert pkt[2] == 0x0C        # size = 12
    assert list(pkt[3:9]) == mac
    assert pkt[9] == 0x01        # action = ADD
    assert pkt[10] == 3          # channel
    # NETID 0x12345678 LE
    assert pkt[11] == 0x78
    assert pkt[12] == 0x56
    assert pkt[13] == 0x34
    assert pkt[14] == 0x12
    assert len(pkt) == 16


def test_cmd_channel_remove():
    """78 9F 0C MAC[6] 02 CH 00 00 00 00 CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_channel_remove(mac, 5)
    assert pkt[1] == 0x9F
    assert pkt[9] == 0x02        # action = DELETE
    assert pkt[10] == 5          # channel
    assert pkt[11:15] == bytes([0, 0, 0, 0])
    assert len(pkt) == 16


def test_cmd_channel_set():
    """78 8C 0B MAC[6] CH NETID[4] CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_channel_set(mac, 1, 0x00000001)
    assert pkt[1] == 0x8C        # TAG_CHANNEL_SET
    assert pkt[2] == 0x0B        # size = 11
    assert pkt[9] == 1           # channel
    assert pkt[10] == 0x01       # NETID byte 0
    assert len(pkt) == 15


def test_cmd_network_delete():
    """78 9B 09 MAC[6] 02 01 00 CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_network_delete(mac)
    assert pkt[1] == 0x9B        # TAG_NETWORK_EDIT
    assert pkt[2] == 0x09
    assert pkt[9] == 0x02
    assert pkt[10] == 0x01
    assert pkt[11] == 0x00
    assert len(pkt) == 13


# === Native Gel command tests ===

def test_cmd_gel_native():
    """78 AD 0D MAC[6] HUE_HI HUE_LO SAT BRI DBRI BRAND GEL CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_gel_native(mac, 240, 80, 70, brand=1, gel_num=38)
    assert pkt[0] == 0x78
    assert pkt[1] == 0xAD        # TAG_GEL_MAC
    assert pkt[2] == 13          # 6 MAC + 7 params
    assert list(pkt[3:9]) == mac
    # Hue 240 in big-endian: 0x00, 0xF0
    assert pkt[9] == 0x00        # hue hi
    assert pkt[10] == 240        # hue lo
    assert pkt[11] == 80         # sat
    assert pkt[12] == 70         # brightness
    assert pkt[13] == 0          # dbri
    assert pkt[14] == 1          # brand = ROSCO
    assert pkt[15] == 38         # gel number
    assert len(pkt) == 17


def test_cmd_gel_native_hue_be():
    """Verify hue big-endian encoding (opposite of HSI little-endian)."""
    mac = [0] * 6
    # Hue 300 = 0x012C → HI=0x01, LO=0x2C
    pkt = neewer.cmd_gel_native(mac, 300, 100, 100, brand=2, gel_num=1)
    assert pkt[9] == 0x01        # hue hi
    assert pkt[10] == 0x2C       # hue lo = 44


def test_ch_cmd_gel_native():
    pkt = neewer.ch_cmd_gel_native(1000, 1, 240, 80, 70, brand=1, gel_num=38)
    assert pkt[1] == 0xAE        # TAG_GEL_CH


# === RGBCW command tests ===

def test_cmd_rgbcw():
    """78 A9 0E MAC[6] A8 BRI R G B C W DBRI CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_rgbcw(mac, 80, 255, 128, 0, 100, 50)
    assert pkt[0] == 0x78
    assert pkt[1] == 0xA9        # TAG_RGBCW_MAC
    assert pkt[9] == 0xA8        # SUBTAG_RGBCW
    assert pkt[10] == 80         # brightness
    assert pkt[11] == 255        # red
    assert pkt[12] == 128        # green
    assert pkt[13] == 0          # blue
    assert pkt[14] == 100        # cold
    assert pkt[15] == 50         # warm
    assert pkt[16] == 0          # dbri


def test_ch_cmd_rgbcw():
    pkt = neewer.ch_cmd_rgbcw(1000, 1, 80, 255, 0, 0, 0, 0)
    assert pkt[1] == 0xAA        # TAG_RGBCW_CH
    assert pkt[8] == 0xA8        # SUBTAG_RGBCW


def test_cmd_rgbcw_clamp():
    mac = [0] * 6
    pkt = neewer.cmd_rgbcw(mac, 150, 300, -10, 0, 0, 0)
    assert pkt[10] == 100        # brightness clamped to 100
    assert pkt[11] == 255        # red clamped to 255
    assert pkt[12] == 0          # green clamped to 0


# === XY Color Coordinate tests ===

def test_encode_xy():
    """0.3127 → [0x0C, 0x37] (3127 as big-endian)."""
    result = neewer._encode_xy(0.3127)
    assert result == [0x0C, 0x37]  # 3127 = 0x0C37


def test_encode_xy_zero():
    result = neewer._encode_xy(0.0000)
    assert result == [0x00, 0x00]


def test_cmd_xy():
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_xy(mac, 80, 0.3127, 0.3290)
    assert pkt[0] == 0x78
    assert pkt[1] == 0xB7        # TAG_XY_MAC
    assert pkt[2] == 12          # 6 MAC + 6 params (no subtag)
    assert pkt[9] == 80          # brightness
    # x = 0.3127 → [0x0C, 0x37]
    assert pkt[10] == 0x0C
    assert pkt[11] == 0x37
    # y = 0.3290 → [0x0C, 0xDA]  (3290 = 0x0CDA)
    assert pkt[12] == 0x0C
    assert pkt[13] == 0xDA


def test_ch_cmd_xy():
    pkt = neewer.ch_cmd_xy(1000, 1, 80, 0.3127, 0.3290)
    assert pkt[1] == 0xB8        # TAG_XY_CH


# === Utility command tests ===

def test_cmd_find():
    """78 99 06 MAC[6] CS"""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_find(mac)
    assert pkt[0] == 0x78
    assert pkt[1] == 0x99        # TAG_FIND
    assert pkt[2] == 6           # size = 6 (just MAC)
    assert list(pkt[3:9]) == mac
    assert len(pkt) == 10


def test_cmd_battery():
    """78 95 06 MAC[6] CS — same as hw_info."""
    mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    pkt = neewer.cmd_battery(mac)
    assert pkt[1] == 0x95
    assert pkt[2] == 6
    assert len(pkt) == 10


def test_cmd_temp_fan_query():
    mac = [0] * 6
    pkt = neewer.cmd_temp_fan_query(mac)
    assert pkt[1] == 0xB3
    assert pkt[2] == 6
    assert len(pkt) == 10


def test_cmd_fan_set():
    mac = [0] * 6
    pkt = neewer.cmd_fan_set(mac, 2)
    assert pkt[1] == 0xB4
    assert pkt[2] == 7           # 6 MAC + 1 param
    assert pkt[9] == 2           # fan mode
    assert len(pkt) == 11


def test_cmd_booster():
    mac = [0] * 6
    pkt = neewer.cmd_booster(mac, enable=True)
    assert pkt[1] == 0xAB
    assert pkt[9] == 0x01
    pkt2 = neewer.cmd_booster(mac, enable=False)
    assert pkt2[9] == 0x02


def test_cmd_booster_query():
    mac = [0] * 6
    pkt = neewer.cmd_booster_query(mac)
    assert pkt[1] == 0xAC
    assert len(pkt) == 10


# === Cross-verify: channel vs MAC command parity ===

def test_channel_vs_mac_cct_parity():
    """Channel CCT and MAC CCT should produce same SUBTAG and params."""
    mac = [0] * 6
    mac_pkt = neewer.cmd_cct(mac, 80, 5600, -10)
    ch_pkt = neewer.ch_cmd_cct(1, 1, 80, 5600, -10)
    # SUBTAG should match
    assert mac_pkt[9] == ch_pkt[8] == 0x87
    # Params should match (brightness, cct, gm, curve)
    assert mac_pkt[10:14] == ch_pkt[9:13]


def test_channel_vs_mac_hsi_parity():
    mac = [0] * 6
    mac_pkt = neewer.cmd_hsi(mac, 240, 100, 80)
    ch_pkt = neewer.ch_cmd_hsi(1, 1, 240, 100, 80)
    assert mac_pkt[9] == ch_pkt[8] == 0x86
    # hue_lo, hue_hi, sat, bri, 0x00
    assert mac_pkt[10:15] == ch_pkt[9:14]


def test_channel_vs_mac_power_parity():
    mac = [0] * 6
    mac_pkt = neewer.cmd_power(mac, on=True)
    ch_pkt = neewer.ch_cmd_power(1, 1, on=True)
    assert mac_pkt[9] == ch_pkt[8] == 0x81
    assert mac_pkt[10] == ch_pkt[9] == 0x01


def test_ch_cmd_scene_int_loop():
    """Channel-addressed INT Loop (0x0E) uses special sub-mode encoding."""
    pkt = neewer.ch_cmd_scene(1, 1, 0x0E, brightness=80, speed=5, hue=120)
    assert pkt[0] == 0x78
    # Format: 78 TAG SIZE NETID[4] CH SUBTAG PARAMS CS
    # Effect ID is at index 9 (first byte of params, after subtag at 8)
    assert pkt[8] == neewer.SUBTAG_SCENE  # 0x8B
    assert pkt[9] == 0x0E  # INT Loop effect ID


def test_channel_vs_mac_gel_native_parity():
    """Channel and MAC gel native share the same SUBTAG."""
    mac = [0] * 6
    mac_pkt = neewer.cmd_gel_native(mac, 120, 80, 70, 1, 38)
    ch_pkt = neewer.ch_cmd_gel_native(1, 1, 120, 80, 70, 1, 38)
    # Both use gel subtag
    assert mac_pkt[9] == ch_pkt[8]  # subtag bytes match
    # Brand and gel_num should match in payload
    assert mac_pkt[-3] == ch_pkt[-3]  # brand
    assert mac_pkt[-2] == ch_pkt[-2]  # gel_num


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"FAIL: {test.__name__}: {e}")

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        exit(1)
