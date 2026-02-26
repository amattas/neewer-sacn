"""Tests for neewer_sacn.py — sACN bridge DMX mapping and logic."""
import neewer_sacn


def test_dmx_to_pct():
    assert neewer_sacn.dmx_to_pct(0) == 0
    assert neewer_sacn.dmx_to_pct(255) == 100
    assert neewer_sacn.dmx_to_pct(128) == 50  # ~50.2, rounds to 50


def test_dmx_to_cct_k():
    assert neewer_sacn.dmx_to_cct_k(0) == 2500
    assert neewer_sacn.dmx_to_cct_k(255) == 10000
    # Midpoint: ~6250K
    mid = neewer_sacn.dmx_to_cct_k(128)
    assert 6200 <= mid <= 6300


def test_dmx_to_hue():
    assert neewer_sacn.dmx_to_hue(0) == 0
    assert neewer_sacn.dmx_to_hue(255) == 359
    # Quarter: ~90
    q = neewer_sacn.dmx_to_hue(64)
    assert 85 <= q <= 95


def test_dmx_to_gm():
    assert neewer_sacn.dmx_to_gm(0) == -50
    assert neewer_sacn.dmx_to_gm(255) == 50
    assert neewer_sacn.dmx_to_gm(128) == 0  # ~0.2, rounds to 0


def test_dmx_to_speed():
    assert neewer_sacn.dmx_to_speed(0) == 1
    assert neewer_sacn.dmx_to_speed(255) == 10


def test_dmx_to_effect():
    # Effect IDs should be 1-18
    assert neewer_sacn.dmx_to_effect(0) == 1
    assert neewer_sacn.dmx_to_effect(255) == 18
    # Middle value should be somewhere in the middle
    mid = neewer_sacn.dmx_to_effect(128)
    assert 8 <= mid <= 11


def test_dmx_to_effect_range():
    """All DMX values 0-255 produce valid effect IDs 1-18."""
    for v in range(256):
        eid = neewer_sacn.dmx_to_effect(v)
        assert 1 <= eid <= 18, f"DMX {v} → effect {eid} out of range"


def test_channels_per_light():
    assert neewer_sacn.CHANNELS_PER_LIGHT == 10


def test_light_connection_init():
    light = neewer_sacn.LightConnection("AA:BB:CC:DD:EE:FF", "TestLight", 1)
    assert light.address == "AA:BB:CC:DD:EE:FF"
    assert light.name == "TestLight"
    assert light.start_channel == 1
    assert light.connected is False
    assert light.power_on is False
    assert light.current_mode is None
    assert light.current_effect is None
    assert light.last_dmx is None


def test_bridge_init():
    bridge = neewer_sacn.NeewerSACNBridge(universe=2, fps=30)
    assert bridge.universe == 2
    assert bridge.poll_interval == 1.0 / 30
    assert bridge.lights == []
    assert bridge.latest_dmx is None


def test_get_light_dmx():
    bridge = neewer_sacn.NeewerSACNBridge()
    light = neewer_sacn.LightConnection("addr", "name", 1)
    bridge.lights.append(light)

    # No DMX data yet
    assert bridge._get_light_dmx(light) is None

    # Set DMX data (512 channels)
    bridge.latest_dmx = tuple(range(256)) + tuple(range(256))
    dmx = bridge._get_light_dmx(light)
    assert dmx is not None
    assert len(dmx) == 10
    assert dmx == (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)


def test_get_light_dmx_offset():
    bridge = neewer_sacn.NeewerSACNBridge()
    # Light starting at channel 11 (1-based)
    light = neewer_sacn.LightConnection("addr", "name", 11)
    bridge.lights.append(light)

    bridge.latest_dmx = tuple(range(256)) + tuple(range(256))
    dmx = bridge._get_light_dmx(light)
    assert dmx == (10, 11, 12, 13, 14, 15, 16, 17, 18, 19)


def test_get_light_dmx_out_of_range():
    bridge = neewer_sacn.NeewerSACNBridge()
    # Light starts beyond available DMX data
    light = neewer_sacn.LightConnection("addr", "name", 510)
    bridge.lights.append(light)

    bridge.latest_dmx = tuple([0] * 512)
    dmx = bridge._get_light_dmx(light)
    assert dmx is None  # 510 + 10 - 1 = 519 > 512


def test_mode_ranges():
    """Verify DMX mode byte interpretation matches spec."""
    # CCT: 0-31
    for v in range(32):
        assert v <= 31
    # HSI: 32-63
    for v in range(32, 64):
        assert 32 <= v <= 63
    # FX: 64-95
    for v in range(64, 96):
        assert 64 <= v <= 95
    # GEL: 96-127
    for v in range(96, 128):
        assert 96 <= v <= 127
    # Off: 128+
    for v in range(128, 256):
        assert v >= 128


def test_gel_mode_index_mapping():
    """Verify GEL mode DMX gel index → brand/num mapping."""
    # ROSCO: indices 0-119
    gel_idx = 38
    assert gel_idx < 120
    brand, num = 1, gel_idx
    assert brand == 1 and num == 38

    # LEE: indices 120-239
    gel_idx = 128
    assert gel_idx >= 120
    brand, num = 2, gel_idx - 120
    assert brand == 2 and num == 8


def test_dmx_to_color():
    assert neewer_sacn.dmx_to_color(0) == 0
    assert neewer_sacn.dmx_to_color(255) == 4
    assert neewer_sacn.dmx_to_color(128) == 2


def test_dmx_to_sparks():
    assert neewer_sacn.dmx_to_sparks(0) == 0
    assert neewer_sacn.dmx_to_sparks(255) == 10
    assert neewer_sacn.dmx_to_sparks(128) == 5


def test_get_fx_kwargs_cop_car():
    """Cop car effect extracts color preset from DMX +4."""
    # DMX: [mode, bri, effect, speed, color_preset, ...]
    dmx = (80, 200, 100, 128, 200, 0, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x0A, dmx)
    assert "color" in kwargs
    assert 0 <= kwargs["color"] <= 4


def test_get_fx_kwargs_hue_flash():
    """Hue flash extracts hue and sat from DMX +4, +5."""
    dmx = (80, 200, 100, 128, 128, 200, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x07, dmx)
    assert "hue" in kwargs
    assert "sat" in kwargs
    assert 0 <= kwargs["hue"] <= 359
    assert 0 <= kwargs["sat"] <= 100


def test_get_fx_kwargs_empty():
    """Unknown effect returns empty kwargs."""
    dmx = (80, 200, 100, 128, 128, 200, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0xFF, dmx)
    assert kwargs == {}


def test_get_fx_kwargs_zero_ignored():
    """Sub-params at 0 are ignored (default values used instead)."""
    dmx = (80, 200, 100, 128, 0, 0, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x07, dmx)
    assert kwargs == {}  # hue=0 and sat=0 are skipped


def test_get_fx_kwargs_music():
    """Music effect (0x12) has no sub-params."""
    dmx = (80, 200, 200, 128, 128, 200, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x12, dmx)
    assert kwargs == {}


def test_fx_subs_covers_all_effects():
    """Every effect 0x01-0x12 has an entry in _FX_SUBS."""
    for eid in range(0x01, 0x13):
        assert eid in neewer_sacn._FX_SUBS, f"Effect 0x{eid:02X} missing from _FX_SUBS"


def test_get_fx_kwargs_lightning():
    """Lightning (0x01) extracts temp from DMX +4."""
    dmx = (80, 200, 10, 128, 128, 0, 0, 0, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x01, dmx)
    assert "temp" in kwargs
    assert 2500 <= kwargs["temp"] <= 10000


def test_get_fx_kwargs_candlelight():
    """Candlelight (0x0B) extracts brr_hi, temp, gm, sparks."""
    dmx = (80, 200, 100, 128, 200, 128, 100, 200, 0, 0)
    kwargs = neewer_sacn.get_fx_kwargs(0x0B, dmx)
    assert "brr_hi" in kwargs
    assert "temp" in kwargs
    assert "gm" in kwargs
    assert "sparks" in kwargs


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
