"""Tests for neewer_config.py — configuration management."""
import os
import json
import tempfile
import neewer_config


def _tmp_store():
    """Create a ConfigStore with a temp file."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start fresh
    return neewer_config.ConfigStore(path), path


def test_create_config():
    store, path = _tmp_store()
    store.create("studio")
    assert "studio" in store.configs
    cfg = store.configs["studio"]
    assert cfg["lights"] == {}
    assert cfg["channels"] == {}
    assert cfg["snapshots"] == {}
    assert "network_id" in cfg
    assert isinstance(cfg["network_id"], int)
    os.unlink(path)


def test_create_duplicate_raises():
    store, path = _tmp_store()
    store.create("studio")
    try:
        store.create("studio")
        assert False, "Should have raised"
    except ValueError:
        pass
    os.unlink(path)


def test_delete_config():
    store, path = _tmp_store()
    store.create("studio")
    store.delete("studio")
    assert "studio" not in store.configs
    os.unlink(path)


def test_delete_active_clears():
    store, path = _tmp_store()
    store.create("studio")
    store.set_active("studio")
    store.delete("studio")
    assert store.active is None
    os.unlink(path)


def test_list_configs():
    store, path = _tmp_store()
    store.create("studio")
    store.create("live")
    names = store.list_configs()
    assert sorted(names) == ["live", "studio"]
    os.unlink(path)


def test_set_active():
    store, path = _tmp_store()
    store.create("studio")
    store.set_active("studio")
    assert store.active == "studio"
    os.unlink(path)


def test_set_active_invalid_raises():
    store, path = _tmp_store()
    try:
        store.set_active("nonexistent")
        assert False, "Should have raised"
    except ValueError:
        pass
    if os.path.exists(path):
        os.unlink(path)


def test_add_light():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C-1")
    cfg = store.configs["studio"]
    assert cfg["lights"]["key"]["device"] == "NW-2022"
    assert cfg["lights"]["key"]["alias"] == "PL60C-1"
    assert cfg["channels"]["key"] == 1
    os.unlink(path)


def test_add_multiple_lights_channels():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C-1")
    store.add_light("studio", "fill", "NW-2024", "TL120")
    store.add_light("studio", "hair", "NW-2025", "TL90C")
    channels = store.configs["studio"]["channels"]
    assert channels["key"] == 1
    assert channels["fill"] == 2
    assert channels["hair"] == 3
    os.unlink(path)


def test_remove_light():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C-1")
    store.remove_light("studio", "key")
    assert "key" not in store.configs["studio"]["lights"]
    assert "key" not in store.configs["studio"]["channels"]
    os.unlink(path)


def test_persistence():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    store1 = neewer_config.ConfigStore(path)
    store1.create("studio")
    store1.add_light("studio", "key", "NW-2022", "PL60C-1")
    store1.set_active("studio")
    store1.save()

    store2 = neewer_config.ConfigStore(path)
    assert "studio" in store2.configs
    assert store2.active == "studio"
    assert store2.configs["studio"]["lights"]["key"]["device"] == "NW-2022"
    os.unlink(path)


def test_get_active_config():
    store, path = _tmp_store()
    store.create("studio")
    store.set_active("studio")
    cfg = store.get_active()
    assert cfg is store.configs["studio"]
    os.unlink(path)


def test_get_active_none():
    store, path = _tmp_store()
    assert store.get_active() is None
    if os.path.exists(path):
        os.unlink(path)


def test_network_id_is_random():
    store, path = _tmp_store()
    store.create("a")
    store.create("b")
    assert store.configs["a"]["network_id"] != store.configs["b"]["network_id"]
    os.unlink(path)
