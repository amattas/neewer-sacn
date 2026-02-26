# Custom Scenes, TUI, and Audio-Reactive Lighting — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent multi-group configurations, a scripted+generative scene engine, a Textual TUI, and sound-reactive lighting driven by microphone input.

**Architecture:** Sibling modules alongside `neewer.py`. `neewer_config.py` handles configs/persistence, `neewer_scenes.py` runs scenes, `neewer_tui.py` provides the TUI, `neewer_audio.py` provides audio analysis. All use `neewer.py` protocol functions. Single BLE connection via channel mode for multi-light control.

**Tech Stack:** Python 3.10+, bleak (BLE), PyYAML (scenes), Textual (TUI), numpy + sounddevice (audio)

**Design doc:** `docs/plans/2026-02-25-custom-scenes-tui-audio-design.md`

**File size budget:** 500-800 lines per file, hard max 1000.

---

## Phase A: Configuration System + Scene Engine

### Task 1: Configuration data model and persistence

**Files:**
- Create: `neewer_config.py`
- Create: `test_config.py`

This task builds the core config data model: create, delete, list, show, set active, add/remove lights, channel auto-assignment, and JSON persistence. No BLE commands yet — pure data operations.

**Step 1: Write failing tests for config CRUD**

In `test_config.py`:

```python
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
    os.unlink(path)


def test_add_light():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C-1")
    cfg = store.configs["studio"]
    assert cfg["lights"]["key"]["device"] == "NW-2022"
    assert cfg["lights"]["key"]["alias"] == "PL60C-1"
    assert cfg["channels"]["key"] == 1  # auto-assigned
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
    os.unlink(path)


def test_network_id_is_random():
    store, path = _tmp_store()
    store.create("a")
    store.create("b")
    assert store.configs["a"]["network_id"] != store.configs["b"]["network_id"]
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neewer_config'`

**Step 3: Implement `neewer_config.py` — ConfigStore class**

Create `neewer_config.py` (~200 lines for this task):

```python
"""Configuration management for Neewer lights.

Persistent multi-group configs with role-based light assignments,
channel auto-management, and state snapshots.
"""
import json
import os
import random

DEFAULT_PATH = ".neewer_config.json"


class ConfigStore:
    """Manages named lighting configurations with persistence."""

    def __init__(self, path=DEFAULT_PATH):
        self.path = path
        self.active = None
        self.configs = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                data = json.load(f)
            self.active = data.get("active")
            self.configs = data.get("configs", {})

    def save(self):
        data = {"active": self.active, "configs": self.configs}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def create(self, name):
        if name in self.configs:
            raise ValueError(f"Config '{name}' already exists")
        self.configs[name] = {
            "network_id": random.randint(1, 0xFFFFFFFF),
            "lights": {},
            "channels": {},
            "snapshots": {},
        }
        self.save()

    def delete(self, name):
        if name not in self.configs:
            raise ValueError(f"Config '{name}' not found")
        del self.configs[name]
        if self.active == name:
            self.active = None
        self.save()

    def list_configs(self):
        return list(self.configs.keys())

    def set_active(self, name):
        if name not in self.configs:
            raise ValueError(f"Config '{name}' not found")
        self.active = name
        self.save()

    def get_active(self):
        if self.active and self.active in self.configs:
            return self.configs[self.active]
        return None

    def add_light(self, config_name, role, device, alias=None):
        cfg = self._get_config(config_name)
        cfg["lights"][role] = {"device": device, "alias": alias or device}
        # Auto-assign next available channel
        used = set(cfg["channels"].values())
        ch = 1
        while ch in used:
            ch += 1
        cfg["channels"][role] = ch
        self.save()

    def remove_light(self, config_name, role):
        cfg = self._get_config(config_name)
        cfg["lights"].pop(role, None)
        cfg["channels"].pop(role, None)
        self.save()

    def _get_config(self, name):
        if name not in self.configs:
            raise ValueError(f"Config '{name}' not found")
        return self.configs[name]
```

**Step 4: Run tests to verify they pass**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add neewer_config.py test_config.py
git commit -m "feat: add config data model with CRUD, channel auto-assign, persistence"
```

---

### Task 2: Snapshot save/recall

**Files:**
- Modify: `neewer_config.py`
- Modify: `test_config.py`

Add snapshot operations: save a named state per role, recall it, delete it, list them.

**Step 1: Write failing tests**

Append to `test_config.py`:

```python
def test_snapshot_save():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022")
    state = {"key": {"mode": "cct", "brightness": 80, "temp": 5600, "gm": 0}}
    store.snapshot_save("studio", "interview", state)
    snaps = store.configs["studio"]["snapshots"]
    assert "interview" in snaps
    assert snaps["interview"]["key"]["brightness"] == 80
    os.unlink(path)


def test_snapshot_recall():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022")
    state = {"key": {"mode": "cct", "brightness": 80, "temp": 5600, "gm": 0}}
    store.snapshot_save("studio", "interview", state)
    recalled = store.snapshot_recall("studio", "interview")
    assert recalled["key"]["temp"] == 5600
    os.unlink(path)


def test_snapshot_recall_missing_raises():
    store, path = _tmp_store()
    store.create("studio")
    try:
        store.snapshot_recall("studio", "nope")
        assert False, "Should have raised"
    except ValueError:
        pass
    os.unlink(path)


def test_snapshot_delete():
    store, path = _tmp_store()
    store.create("studio")
    state = {"key": {"mode": "cct", "brightness": 80, "temp": 5600}}
    store.snapshot_save("studio", "interview", state)
    store.snapshot_delete("studio", "interview")
    assert "interview" not in store.configs["studio"]["snapshots"]
    os.unlink(path)


def test_snapshot_list():
    store, path = _tmp_store()
    store.create("studio")
    store.snapshot_save("studio", "a", {"key": {"mode": "cct", "brightness": 50}})
    store.snapshot_save("studio", "b", {"key": {"mode": "hsi", "hue": 120}})
    names = store.snapshot_list("studio")
    assert sorted(names) == ["a", "b"]
    os.unlink(path)
```

**Step 2: Run tests to verify new tests fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v -k snapshot`
Expected: FAIL — `AttributeError: 'ConfigStore' object has no attribute 'snapshot_save'`

**Step 3: Implement snapshot methods**

Add to `ConfigStore` in `neewer_config.py`:

```python
def snapshot_save(self, config_name, snap_name, state):
    cfg = self._get_config(config_name)
    cfg["snapshots"][snap_name] = state
    self.save()

def snapshot_recall(self, config_name, snap_name):
    cfg = self._get_config(config_name)
    if snap_name not in cfg["snapshots"]:
        raise ValueError(f"Snapshot '{snap_name}' not found in '{config_name}'")
    return cfg["snapshots"][snap_name]

def snapshot_delete(self, config_name, snap_name):
    cfg = self._get_config(config_name)
    cfg["snapshots"].pop(snap_name, None)
    self.save()

def snapshot_list(self, config_name):
    cfg = self._get_config(config_name)
    return list(cfg["snapshots"].keys())
```

**Step 4: Run tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add neewer_config.py test_config.py
git commit -m "feat: add snapshot save/recall/delete/list to configs"
```

---

### Task 3: Config resolution helpers

**Files:**
- Modify: `neewer_config.py`
- Modify: `test_config.py`

Add helper methods the CLI and scene engine need: resolve a config target string (e.g., `"studio"`, `"studio:key"`) to a list of `(role, device, channel)` tuples. Also add a `get_relay_role()` to identify which light should be the relay.

**Step 1: Write failing tests**

Append to `test_config.py`:

```python
def test_resolve_all_roles():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C")
    store.add_light("studio", "fill", "NW-2024", "TL120")
    targets = store.resolve_targets("studio")
    assert len(targets) == 2
    roles = [t[0] for t in targets]
    assert "key" in roles
    assert "fill" in roles
    os.unlink(path)


def test_resolve_single_role():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022", "PL60C")
    store.add_light("studio", "fill", "NW-2024", "TL120")
    targets = store.resolve_targets("studio", role="key")
    assert len(targets) == 1
    assert targets[0][0] == "key"
    assert targets[0][1] == "NW-2022"
    os.unlink(path)


def test_resolve_target_string():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022")
    store.add_light("studio", "fill", "NW-2024")
    # "studio:key" syntax
    config_name, role = store.parse_target("studio:key")
    assert config_name == "studio"
    assert role == "key"
    # "studio" without role
    config_name2, role2 = store.parse_target("studio")
    assert config_name2 == "studio"
    assert role2 is None
    os.unlink(path)


def test_get_relay_role():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022")
    store.add_light("studio", "fill", "NW-2024")
    relay = store.get_relay_role("studio")
    assert relay in ("key", "fill")
    os.unlink(path)


def test_get_network_id():
    store, path = _tmp_store()
    store.create("studio")
    nid = store.get_network_id("studio")
    assert isinstance(nid, int)
    assert 1 <= nid <= 0xFFFFFFFF
    os.unlink(path)


def test_get_channel_map():
    store, path = _tmp_store()
    store.create("studio")
    store.add_light("studio", "key", "NW-2022")
    store.add_light("studio", "fill", "NW-2024")
    cmap = store.get_channel_map("studio")
    assert cmap == {"key": 1, "fill": 2}
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v -k resolve`
Expected: FAIL

**Step 3: Implement resolution helpers**

Add to `ConfigStore`:

```python
def resolve_targets(self, config_name, role=None):
    cfg = self._get_config(config_name)
    lights = cfg["lights"]
    channels = cfg["channels"]
    if role:
        if role not in lights:
            raise ValueError(f"Role '{role}' not found in '{config_name}'")
        info = lights[role]
        return [(role, info["device"], channels.get(role))]
    return [(r, info["device"], channels.get(r))
            for r, info in lights.items()]

def parse_target(self, target_str):
    if ":" in target_str:
        config_name, role = target_str.split(":", 1)
        return config_name, role
    return target_str, None

def get_relay_role(self, config_name):
    cfg = self._get_config(config_name)
    if not cfg["lights"]:
        raise ValueError(f"Config '{config_name}' has no lights")
    return next(iter(cfg["lights"]))

def get_network_id(self, config_name):
    cfg = self._get_config(config_name)
    return cfg["network_id"]

def get_channel_map(self, config_name):
    cfg = self._get_config(config_name)
    return dict(cfg["channels"])
```

**Step 4: Run all tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add neewer_config.py test_config.py
git commit -m "feat: add config resolution helpers (targets, relay, channel map)"
```

---

### Task 4: CLI integration — `config` subcommand

**Files:**
- Modify: `neewer.py` (lines ~1896 for parser, ~3103+ for handler)
- Modify: `neewer_config.py` (add display helpers)

Wire up `neewer.py config create|delete|list|show|use|active|add-light|remove-light|snapshot` subcommands. These are thin CLI wrappers that call into `ConfigStore`.

**Step 1: Add `config` subcommand to `build_parser()`**

In `neewer.py`, after the existing `channel` subparser (around line 2047), add:

```python
# --- Config management ---
p_cfg = sub.add_parser("config", help="manage light configurations")
cfg_sub = p_cfg.add_subparsers(dest="config_cmd")

cfg_sub.add_parser("list", help="list all configs")
cfg_sub.add_parser("active", help="show active config")

p_cfg_create = cfg_sub.add_parser("create", help="create a new config")
p_cfg_create.add_argument("name", help="config name")

p_cfg_delete = cfg_sub.add_parser("delete", help="delete a config")
p_cfg_delete.add_argument("name", help="config name")

p_cfg_use = cfg_sub.add_parser("use", help="set active config")
p_cfg_use.add_argument("name", help="config name")

p_cfg_show = cfg_sub.add_parser("show", help="show config details")
p_cfg_show.add_argument("name", help="config name")

p_cfg_add = cfg_sub.add_parser("add-light", help="assign a light to a config role")
p_cfg_add.add_argument("config", help="config name")
p_cfg_add.add_argument("role", help="role name (e.g. key, fill, hair)")
p_cfg_add.add_argument("--light", required=True, help="device identifier")

p_cfg_rm = cfg_sub.add_parser("remove-light", help="remove a role from config")
p_cfg_rm.add_argument("config", help="config name")
p_cfg_rm.add_argument("role", help="role name")

p_cfg_snap = cfg_sub.add_parser("snapshot", help="manage state snapshots")
snap_sub = p_cfg_snap.add_subparsers(dest="snap_cmd")

p_snap_save = snap_sub.add_parser("save", help="save current state as snapshot")
p_snap_save.add_argument("config", help="config name")
p_snap_save.add_argument("name", help="snapshot name")

p_snap_recall = snap_sub.add_parser("recall", help="recall a saved snapshot")
p_snap_recall.add_argument("config", help="config name")
p_snap_recall.add_argument("name", help="snapshot name")
_add_light_args(p_snap_recall, light_required=False)

p_snap_delete = snap_sub.add_parser("delete", help="delete a snapshot")
p_snap_delete.add_argument("config", help="config name")
p_snap_delete.add_argument("name", help="snapshot name")

p_snap_list = snap_sub.add_parser("list", help="list snapshots")
p_snap_list.add_argument("config", help="config name")

# --- Connection visibility ---
p_conn = sub.add_parser("connections", help="show BLE connections and channel map")
p_conn.add_argument("--scan", action="store_true", help="scan and show live channel assignments")
```

**Step 2: Add handler in `main()`**

After the existing `channel` handler (around line 3167), add:

```python
elif args.command == "config":
    import neewer_config
    store = neewer_config.ConfigStore()

    if args.config_cmd == "create":
        store.create(args.name)
        print(f"Created config '{args.name}' (network ID: 0x{store.configs[args.name]['network_id']:08X})")

    elif args.config_cmd == "delete":
        store.delete(args.name)
        print(f"Deleted config '{args.name}'")

    elif args.config_cmd == "list":
        configs = store.list_configs()
        if not configs:
            print("No configurations.")
        else:
            for name in sorted(configs):
                marker = " (active)" if name == store.active else ""
                n_lights = len(store.configs[name]["lights"])
                n_snaps = len(store.configs[name]["snapshots"])
                print(f"  {name}{marker}  [{n_lights} lights, {n_snaps} snapshots]")

    elif args.config_cmd == "active":
        if store.active:
            print(f"Active config: {store.active}")
        else:
            print("No active config set. Use: neewer.py config use <name>")

    elif args.config_cmd == "use":
        store.set_active(args.name)
        print(f"Active config set to '{args.name}'")

    elif args.config_cmd == "show":
        neewer_config.print_config(store, args.name)

    elif args.config_cmd == "add-light":
        addr, dname = _resolve_light_alias(args.light)
        alias = dname or args.light
        store.add_light(args.config, args.role, args.light, alias)
        ch = store.configs[args.config]["channels"][args.role]
        print(f"Added '{args.role}' → {alias} (channel {ch})")

    elif args.config_cmd == "remove-light":
        store.remove_light(args.config, args.role)
        print(f"Removed '{args.role}' from '{args.config}'")

    elif args.config_cmd == "snapshot":
        if args.snap_cmd == "save":
            # For now, save an empty snapshot — full capture requires BLE queries
            state = {}
            store.snapshot_save(args.config, args.name, state)
            print(f"Saved snapshot '{args.name}' in '{args.config}'")

        elif args.snap_cmd == "recall":
            state = store.snapshot_recall(args.config, args.name)
            print(f"Recalling snapshot '{args.name}'...")
            # Apply each role's state via BLE
            for role, params in state.items():
                targets = store.resolve_targets(args.config, role=role)
                if not targets:
                    continue
                _, device, ch = targets[0]
                mode = params.get("mode", "cct")
                if mode == "cct":
                    bri = params.get("brightness", 50)
                    temp = params.get("temp", 5000)
                    gm = params.get("gm", 0)
                    async def do_cct(client, mac_bytes, verbose, proto,
                                     _b=bri, _t=temp, _g=gm):
                        pkt = build_cct(proto, mac_bytes, _b, _t, _g)
                        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
                    addr, dname = _resolve_light_alias(device)
                    await run_command(addr, dname, do_cct, args.verbose,
                                     proto_arg=proto_arg)
                elif mode == "hsi":
                    hue = params.get("hue", 0)
                    sat = params.get("sat", 100)
                    bri = params.get("brightness", 50)
                    async def do_hsi(client, mac_bytes, verbose, proto,
                                     _h=hue, _s=sat, _b=bri):
                        pkt = build_hsi(proto, mac_bytes, _h, _s, _b)
                        await client.write_gatt_char(WRITE_UUID, pkt, response=False)
                    addr, dname = _resolve_light_alias(device)
                    await run_command(addr, dname, do_hsi, args.verbose,
                                     proto_arg=proto_arg)
                print(f"  {role}: {mode} applied")

        elif args.snap_cmd == "delete":
            store.snapshot_delete(args.config, args.name)
            print(f"Deleted snapshot '{args.name}'")

        elif args.snap_cmd == "list":
            snaps = store.snapshot_list(args.config)
            if not snaps:
                print("No snapshots.")
            else:
                for s in sorted(snaps):
                    print(f"  {s}")
        else:
            print("Usage: neewer.py config snapshot {save|recall|delete|list}")
    else:
        print("Usage: neewer.py config {create|delete|list|show|use|active|add-light|remove-light|snapshot}")

elif args.command == "connections":
    import neewer_config
    store = neewer_config.ConfigStore()
    neewer_config.print_connections(store)
```

**Step 3: Add display helpers to `neewer_config.py`**

```python
def print_config(store, name):
    cfg = store._get_config(name)
    marker = " (active)" if name == store.active else ""
    print(f"Config: {name}{marker}")
    print(f"Network ID: 0x{cfg['network_id']:08X}")
    print()
    if cfg["lights"]:
        print("  Role       Light               Channel")
        print("  " + "-" * 45)
        for role, info in cfg["lights"].items():
            ch = cfg["channels"].get(role, "?")
            print(f"  {role:<10s} {info['alias']:<20s} ch {ch}")
    else:
        print("  No lights assigned.")
    print()
    snaps = cfg["snapshots"]
    if snaps:
        print(f"  Snapshots: {', '.join(sorted(snaps.keys()))}")
    else:
        print("  No snapshots.")


def print_connections(store):
    active = store.get_active()
    if not active:
        print("No active config. Use: neewer.py config use <name>")
        return
    name = store.active
    cfg = active
    nid = cfg["network_id"]
    print(f"Active config: {name}")
    print(f"Network ID: 0x{nid:08X}")
    print()
    print("  Channel assignments:")
    for role, info in cfg["lights"].items():
        ch = cfg["channels"].get(role, "?")
        relay = " (relay)" if role == next(iter(cfg["lights"])) else ""
        print(f"    ch {ch}: {info['alias']} ({role}){relay}")
```

**Step 4: Verify existing tests still pass, then test CLI manually**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py test_protocol.py test_sacn_bridge.py -v`
Expected: All PASS

Test CLI:
```bash
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py config create studio
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py config list
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py config use studio
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py config active
```

**Step 5: Commit**

```bash
git add neewer.py neewer_config.py
git commit -m "feat: wire config and connections CLI subcommands into neewer.py"
```

---

### Task 5: `--config` flag on existing commands

**Files:**
- Modify: `neewer.py` (parser global args ~line 1891, `main()` dispatch logic ~line 2181+)

Add `--config` as a global argument (like `--protocol`). When set, resolve the config target to lights and dispatch commands accordingly. This means `neewer.py --config studio cct --brightness 80 --temp 5600` sends CCT to all lights in the "studio" config via channel mode.

**Step 1: Add `--config` to parser**

In `build_parser()`, after the `--protocol` arg (line ~1893):

```python
parser.add_argument("--config", default=None,
                    help="config target (name or name:role). Uses active config if omitted.")
```

**Step 2: Add config dispatch to `main()`**

Near the top of `main()`, after `_load_cache()` (line ~2181), add config resolution logic:

```python
# Resolve --config flag
config_target = getattr(args, "config", None)
if config_target is None and hasattr(args, "light") and not getattr(args, "light", None):
    # No --light and no --config: try active config
    import neewer_config
    store = neewer_config.ConfigStore()
    if store.active:
        config_target = store.active

if config_target and args.command not in ("scan", "config", "connections",
        "effects", "gels", "sources", "colors", "interactive", "tui",
        "scene-list", "audio-test"):
    import neewer_config
    store = neewer_config.ConfigStore()
    config_name, config_role = store.parse_target(config_target)
    targets = store.resolve_targets(config_name, role=config_role)
    nid = store.get_network_id(config_name)
    # Override --light processing: iterate over config targets
    for role, device, ch in targets:
        address, device_name = _resolve_light_alias(device)
        # ... dispatch command to each light
```

This is a significant integration point. The exact implementation depends on how the existing command handlers work — each `do_*` closure captures `args` in its scope. The cleanest approach is:

1. If `--config` is set, build a list of `(address, device_name, channel)` from the config
2. For each target, call `run_command()` the same way `--light` does today
3. If only one role, use channel-addressed commands via `--ch` automatically

**Step 3: Run all tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py test_protocol.py test_sacn_bridge.py -v`
Expected: All PASS

**Step 4: Manual test**

```bash
python neewer.py config create test
python neewer.py config add-light test key --light 0
python neewer.py config use test
python neewer.py --config test on
```

**Step 5: Commit**

```bash
git add neewer.py
git commit -m "feat: add --config global flag for config-targeted commands"
```

---

### Task 6: Scene engine — YAML scripted scenes

**Files:**
- Create: `neewer_scenes.py`
- Modify: `test_config.py` (or create `test_scenes.py` if approaching 300 lines)
- Create: `scenes/sunset-fade.yaml`
- Create: `scenes/alert.yaml`
- Create: `scenes/interview.yaml`

**Step 1: Add `pyyaml` to requirements**

```bash
echo "pyyaml>=6.0" >> requirements.txt
pip install pyyaml
```

**Step 2: Write failing tests for scene loading**

Create `test_scenes.py`:

```python
"""Tests for neewer_scenes.py — scene engine."""
import os
import tempfile
import yaml
import neewer_scenes


def _write_yaml(content):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(content, f)
    return path


def test_load_yaml_scene():
    data = {
        "name": "Test Scene",
        "duration": "10s",
        "loop": False,
        "targets": ["all"],
        "steps": [
            {"at": "0s", "all": {"mode": "cct", "brightness": 80, "temp": 5600}},
            {"at": "5s", "all": {"fade": {"brightness": 20, "temp": 3200}}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)
    assert scene.name == "Test Scene"
    assert scene.duration == 10.0
    assert scene.loop is False
    assert len(scene.steps) == 2
    assert scene.steps[0].time == 0.0
    assert scene.steps[1].time == 5.0
    os.unlink(path)


def test_parse_duration():
    assert neewer_scenes.parse_duration("10s") == 10.0
    assert neewer_scenes.parse_duration("1.5s") == 1.5
    assert neewer_scenes.parse_duration("2m") == 120.0
    assert neewer_scenes.parse_duration("0.5m") == 30.0
    assert neewer_scenes.parse_duration("30") == 30.0


def test_load_generative_scene():
    code = '''
name = "Test Gen"
fps = 20

def render(tick, lights, params, audio=None):
    return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
'''
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    scene = neewer_scenes.load_scene(path)
    assert scene.name == "Test Gen"
    assert scene.fps == 20
    assert scene.generative is True
    result = scene.render(0, ["key", "fill"], {})
    assert result["all"]["brightness"] == 50
    os.unlink(path)


def test_interpolate_values():
    a = {"brightness": 80, "temp": 5600}
    b = {"brightness": 20, "temp": 3200}
    mid = neewer_scenes.interpolate(a, b, 0.5)
    assert mid["brightness"] == 50
    assert mid["temp"] == 4400


def test_interpolate_hue_wraps():
    a = {"hue": 350, "sat": 100, "brightness": 80}
    b = {"hue": 10, "sat": 100, "brightness": 80}
    mid = neewer_scenes.interpolate(a, b, 0.5)
    assert mid["hue"] == 0  # shortest path wraps through 360


def test_step_targets():
    data = {
        "name": "Multi",
        "duration": "5s",
        "targets": ["key", "fill"],
        "steps": [
            {"at": "0s", "key": {"mode": "cct", "brightness": 80, "temp": 5600},
                         "fill": {"mode": "cct", "brightness": 40, "temp": 4200}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)
    step = scene.steps[0]
    assert "key" in step.targets
    assert "fill" in step.targets
    assert step.targets["key"]["brightness"] == 80
    os.unlink(path)
```

**Step 3: Run tests to verify they fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_scenes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neewer_scenes'`

**Step 4: Implement `neewer_scenes.py`**

```python
"""Scene engine for Neewer lights.

Supports two scene types:
- Scripted (YAML): timed steps with per-role targets and fade interpolation
- Generative (Python): render() callback called each frame
"""
import importlib.util
import os
import re
import yaml


def parse_duration(s):
    """Parse duration string like '10s', '2m', '30' to float seconds."""
    s = str(s).strip()
    m = re.match(r'^([\d.]+)(s|m)?$', s)
    if not m:
        raise ValueError(f"Invalid duration: {s}")
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return val * 60.0
    return val


class SceneStep:
    """A single timed step in a scripted scene."""

    def __init__(self, time, targets):
        self.time = time          # seconds from start
        self.targets = targets    # {role: {mode/brightness/fade/...}}


class Scene:
    """Loaded scene (scripted or generative)."""

    def __init__(self):
        self.name = "Untitled"
        self.duration = 0.0
        self.loop = False
        self.target_roles = []    # which roles this scene addresses
        self.steps = []           # SceneStep list (scripted only)
        self.generative = False
        self.fps = 20
        self.render = None        # render function (generative only)
        self.source_path = None


def load_scene(path):
    """Load a scene from YAML or Python file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        return _load_yaml(path)
    elif ext == ".py":
        return _load_generative(path)
    else:
        raise ValueError(f"Unknown scene file type: {ext}")


def _load_yaml(path):
    with open(path) as f:
        data = yaml.safe_load(f)

    scene = Scene()
    scene.source_path = path
    scene.name = data.get("name", os.path.basename(path))
    scene.duration = parse_duration(data.get("duration", "10s"))
    scene.loop = data.get("loop", False)
    scene.target_roles = data.get("targets", ["all"])

    for step_data in data.get("steps", []):
        time = parse_duration(step_data.pop("at", "0s"))
        targets = {}
        for role, params in step_data.items():
            targets[role] = params
        scene.steps.append(SceneStep(time, targets))

    scene.steps.sort(key=lambda s: s.time)
    return scene


def _load_generative(path):
    spec = importlib.util.spec_from_file_location("_scene", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    scene = Scene()
    scene.source_path = path
    scene.generative = True
    scene.name = getattr(mod, "name", os.path.basename(path))
    scene.fps = getattr(mod, "fps", 20)
    scene.render = mod.render
    scene.loop = True  # generative scenes loop by default
    return scene


def interpolate(a, b, t):
    """Interpolate between two param dicts. Handles hue wrap-around."""
    result = {}
    for key in set(list(a.keys()) + list(b.keys())):
        va = a.get(key, 0)
        vb = b.get(key, va)
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            result[key] = vb if t >= 0.5 else va
            continue
        if key == "hue":
            # Shortest path around 360
            diff = (vb - va + 540) % 360 - 180
            result[key] = int(va + diff * t) % 360
        else:
            result[key] = int(va + (vb - va) * t)
    return result


def list_scenes(dirs=None):
    """List available scene files from the given directories."""
    if dirs is None:
        dirs = ["scenes"]
        home_scenes = os.path.expanduser("~/.neewer/scenes")
        if os.path.isdir(home_scenes):
            dirs.append(home_scenes)

    scenes = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.endswith((".yaml", ".yml", ".py")) and not fname.startswith("_"):
                scenes.append(os.path.join(d, fname))
    return scenes
```

**Step 5: Run tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_scenes.py -v`
Expected: All PASS

**Step 6: Create example scenes**

Create `scenes/sunset-fade.yaml`:
```yaml
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

Create `scenes/alert.yaml`:
```yaml
name: Alert
duration: 4s
loop: true
targets: [all]

steps:
  - at: 0s
    all: {mode: hsi, hue: 0, sat: 100, brightness: 100}
  - at: 0.5s
    all: {fade: {brightness: 0}}
  - at: 1s
    all: {fade: {brightness: 100}}
  - at: 1.5s
    all: {fade: {brightness: 0}}
  - at: 2s
    all: {fade: {brightness: 100, hue: 0}}
  - at: 3.5s
    all: {fade: {brightness: 0}}
```

Create `scenes/interview.yaml`:
```yaml
name: Interview Setup
duration: 2s
loop: false
targets: [key, fill, hair]

steps:
  - at: 0s
    key:  {mode: cct, brightness: 80, temp: 5600, gm: 0}
    fill: {mode: cct, brightness: 40, temp: 4200, gm: 5}
    hair: {mode: hsi, hue: 220, sat: 60, brightness: 30}
```

**Step 7: Commit**

```bash
git add neewer_scenes.py test_scenes.py scenes/ requirements.txt
git commit -m "feat: add scene engine with YAML scripted and Python generative scenes"
```

---

### Task 7: Scene runner — async execution loop

**Files:**
- Modify: `neewer_scenes.py` (add `SceneRunner` class)
- Modify: `test_scenes.py`

The scene runner connects to lights (via channel mode through a relay), then executes the scene timeline or render loop.

**Step 1: Write failing test for SceneRunner**

Append to `test_scenes.py`:

```python
import asyncio


class FakeLight:
    """Mock light for testing scene runner."""
    def __init__(self, role):
        self.role = role
        self.commands = []

    async def send(self, mode, params):
        self.commands.append((mode, dict(params)))


def test_scene_runner_scripted():
    data = {
        "name": "Quick Test",
        "duration": "0.3s",
        "loop": False,
        "targets": ["all"],
        "steps": [
            {"at": "0s", "all": {"mode": "cct", "brightness": 80, "temp": 5600}},
            {"at": "0.15s", "all": {"mode": "cct", "brightness": 40, "temp": 3200}},
        ],
    }
    path = _write_yaml(data)
    scene = neewer_scenes.load_scene(path)

    light = FakeLight("key")
    runner = neewer_scenes.SceneRunner(scene, {"key": light})
    asyncio.get_event_loop().run_until_complete(runner.run())

    assert len(light.commands) >= 2
    # First command should be near 80 brightness
    assert light.commands[0][1]["brightness"] >= 70
    os.unlink(path)


def test_scene_runner_generative():
    code = '''
name = "Gen Test"
fps = 30

def render(tick, lights, params, audio=None):
    return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
'''
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    scene = neewer_scenes.load_scene(path)

    light = FakeLight("key")
    runner = neewer_scenes.SceneRunner(scene, {"key": light}, max_ticks=5)
    asyncio.get_event_loop().run_until_complete(runner.run())

    assert len(light.commands) == 5
    assert all(c[1]["brightness"] == 50 for c in light.commands)
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_scenes.py::test_scene_runner_scripted -v`
Expected: FAIL — `AttributeError: module 'neewer_scenes' has no attribute 'SceneRunner'`

**Step 3: Implement `SceneRunner`**

Add to `neewer_scenes.py`:

```python
import asyncio


class SceneRunner:
    """Executes a scene against a set of lights."""

    def __init__(self, scene, lights, max_ticks=None, audio_source=None):
        self.scene = scene
        self.lights = lights          # {role: light_object}
        self.max_ticks = max_ticks    # for testing; None = run full duration
        self.audio_source = audio_source
        self.running = False

    async def run(self):
        self.running = True
        if self.scene.generative:
            await self._run_generative()
        else:
            await self._run_scripted()

    async def stop(self):
        self.running = False

    async def _run_generative(self):
        interval = 1.0 / self.scene.fps
        tick = 0
        while self.running:
            if self.max_ticks is not None and tick >= self.max_ticks:
                break

            audio = None
            if self.audio_source:
                audio = await self.audio_source.read_frame()

            result = self.scene.render(tick, list(self.lights.keys()), {}, audio)
            if result:
                await self._apply(result)

            tick += 1
            await asyncio.sleep(interval)

    async def _run_scripted(self):
        fps = 20
        interval = 1.0 / fps
        elapsed = 0.0
        step_idx = 0
        prev_state = {}   # {role: params} — last applied state per role
        fade_start = {}   # {role: params} — state at fade start
        fade_target = {}  # {role: params} — fade destination

        while self.running:
            # Check if we've passed the next step
            while (step_idx < len(self.scene.steps) and
                   elapsed >= self.scene.steps[step_idx].time):
                step = self.scene.steps[step_idx]
                for role_key, params in step.targets.items():
                    roles = list(self.lights.keys()) if role_key == "all" else [role_key]
                    for role in roles:
                        if "fade" in params:
                            fade_start[role] = dict(prev_state.get(role, {}))
                            fade_target[role] = params["fade"]
                        else:
                            prev_state[role] = dict(params)
                            fade_start.pop(role, None)
                            fade_target.pop(role, None)
                            if role in self.lights:
                                mode = params.get("mode", "cct")
                                await self.lights[role].send(mode, params)
                step_idx += 1

            # Interpolate active fades
            if fade_target:
                next_time = (self.scene.steps[step_idx].time
                             if step_idx < len(self.scene.steps)
                             else self.scene.duration)
                prev_time = (self.scene.steps[step_idx - 1].time
                             if step_idx > 0 else 0.0)
                span = next_time - prev_time
                if span > 0:
                    t = min(1.0, (elapsed - prev_time) / span)
                    for role, target in list(fade_target.items()):
                        start = fade_start.get(role, {})
                        current = interpolate(start, target, t)
                        mode = current.pop("mode", start.get("mode", "cct"))
                        prev_state[role] = dict(current)
                        prev_state[role]["mode"] = mode
                        if role in self.lights:
                            await self.lights[role].send(mode, current)

            elapsed += interval
            if elapsed >= self.scene.duration:
                if self.scene.loop:
                    elapsed = 0.0
                    step_idx = 0
                    fade_start.clear()
                    fade_target.clear()
                else:
                    break

            await asyncio.sleep(interval)

    async def _apply(self, result):
        """Apply a render result {role_or_all: {mode, params...}} to lights."""
        for role_key, params in result.items():
            roles = list(self.lights.keys()) if role_key == "all" else [role_key]
            for role in roles:
                if role in self.lights:
                    mode = params.get("mode", "cct")
                    await self.lights[role].send(mode, params)
```

**Step 4: Run tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_scenes.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add neewer_scenes.py test_scenes.py
git commit -m "feat: add SceneRunner with scripted timeline and generative render loop"
```

---

### Task 8: `scene-run` and `scene-list` CLI commands

**Files:**
- Modify: `neewer.py` (add subcommands + handler)
- Modify: `neewer_scenes.py` (add `BLELight` adapter that bridges `SceneRunner` to `neewer.py` protocol functions)

**Step 1: Add subcommands to `build_parser()` in `neewer.py`**

After the `config` subparser:

```python
p_scene_run = sub.add_parser("scene-run", help="run a scripted or generative scene")
p_scene_run.add_argument("file", help="path to .yaml or .py scene file")
p_scene_run.add_argument("--config", dest="scene_config", default=None,
                         help="config to target (default: active)")
p_scene_run.add_argument("--mic", action="store_true", help="enable audio input")
p_scene_run.add_argument("--device", type=int, default=None, help="audio device index")

p_scene_list = sub.add_parser("scene-list", help="list available scenes")
```

**Step 2: Add `BLELight` adapter to `neewer_scenes.py`**

This bridges the scene runner's abstract `send(mode, params)` to actual BLE commands:

```python
class BLELight:
    """Adapter: scene runner → BLE protocol commands via channel mode."""

    def __init__(self, client, nid, ch, proto, mac_bytes, write_uuid):
        self.client = client
        self.nid = nid
        self.ch = ch
        self.proto = proto
        self.mac_bytes = mac_bytes
        self.write_uuid = write_uuid

    async def send(self, mode, params):
        import neewer
        bri = params.get("brightness", 50)

        if mode == "cct":
            temp = params.get("temp", 5000)
            gm = params.get("gm", 0)
            if self.ch is not None:
                pkt = neewer.ch_cmd_cct(self.nid, self.ch, bri, temp, gm)
            else:
                pkt = neewer.build_cct(self.proto, self.mac_bytes, bri, temp, gm)
        elif mode == "hsi":
            hue = params.get("hue", 0)
            sat = params.get("sat", 100)
            if self.ch is not None:
                pkt = neewer.ch_cmd_hsi(self.nid, self.ch, hue, sat, bri)
            else:
                pkt = neewer.build_hsi(self.proto, self.mac_bytes, hue, sat, bri)
        elif mode == "scene":
            effect = params.get("effect", "lightning")
            import neewer
            eid = neewer.EFFECTS.get(effect, 0x01) if isinstance(effect, str) else effect
            speed = params.get("speed", 5)
            if self.ch is not None:
                pkt = neewer.ch_cmd_scene(self.nid, self.ch, eid, bri, speed)
            else:
                pkt = neewer.build_scene(self.proto, self.mac_bytes, eid, bri, speed)
        else:
            return

        await self.client.write_gatt_char(self.write_uuid, pkt, response=False)
```

**Step 3: Add handler in `neewer.py` `main()`**

```python
elif args.command == "scene-run":
    import neewer_scenes
    scene = neewer_scenes.load_scene(args.file)
    print(f"Scene: {scene.name}")
    print(f"  Type: {'generative' if scene.generative else 'scripted'}")
    print(f"  Duration: {scene.duration}s, loop: {scene.loop}")

    # Resolve config
    import neewer_config
    store = neewer_config.ConfigStore()
    cfg_name = args.scene_config or store.active
    if not cfg_name:
        print("ERROR: No config specified and no active config set.")
        print("Use: neewer.py config create <name> && neewer.py config use <name>")
        sys.exit(1)

    targets = store.resolve_targets(cfg_name)
    nid = store.get_network_id(cfg_name)
    relay_role = store.get_relay_role(cfg_name)
    relay_device = store.configs[cfg_name]["lights"][relay_role]["device"]
    relay_addr, relay_dname = _resolve_light_alias(relay_device)

    print(f"  Config: {cfg_name} ({len(targets)} lights)")
    print(f"  Relay: {relay_role}")
    print("Connecting...")

    async def run_scene(client, mac_bytes, verbose, proto):
        lights = {}
        for role, device, ch in targets:
            lights[role] = neewer_scenes.BLELight(
                client, nid, ch, proto, mac_bytes, WRITE_UUID)

        audio_source = None
        if getattr(args, "mic", False):
            import neewer_audio
            audio_source = neewer_audio.MicSource(device=args.device)
            await audio_source.start()

        runner = neewer_scenes.SceneRunner(scene, lights,
                                           audio_source=audio_source)
        print("Running... (Ctrl+C to stop)")
        try:
            await runner.run()
        except asyncio.CancelledError:
            pass
        finally:
            if audio_source:
                await audio_source.stop()
            await runner.stop()

    await run_command(relay_addr, relay_dname, run_scene, args.verbose,
                     proto_arg=proto_arg)

elif args.command == "scene-list":
    import neewer_scenes
    scenes = neewer_scenes.list_scenes()
    if not scenes:
        print("No scenes found. Create .yaml or .py files in scenes/")
    else:
        for path in scenes:
            try:
                s = neewer_scenes.load_scene(path)
                stype = "gen" if s.generative else "yaml"
                print(f"  {os.path.basename(path):<30s} {s.name:<20s} [{stype}]")
            except Exception as e:
                print(f"  {os.path.basename(path):<30s} (error: {e})")
```

**Step 4: Run all tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_config.py test_scenes.py test_protocol.py test_sacn_bridge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add neewer.py neewer_scenes.py
git commit -m "feat: add scene-run and scene-list CLI commands with BLELight adapter"
```

---

### Task 9: Generative example scenes

**Files:**
- Create: `scenes/rainbow_chase.py`
- Create: `scenes/campfire.py`

**Step 1: Create `scenes/rainbow_chase.py`**

```python
"""Rainbow chase — rotating hue offset across lights."""
name = "Rainbow Chase"
fps = 20

def render(tick, lights, params, audio=None):
    speed = params.get("speed", 2)
    bri = params.get("brightness", 70)
    result = {}
    for i, role in enumerate(lights):
        hue = (tick * speed + i * 60) % 360
        result[role] = {"mode": "hsi", "hue": hue, "sat": 100, "brightness": bri}
    return result
```

**Step 2: Create `scenes/campfire.py`**

```python
"""Campfire flicker — warm random brightness and temperature variation."""
import random

name = "Campfire"
fps = 15

def render(tick, lights, params, audio=None):
    base_bri = params.get("brightness", 60)
    result = {}
    for role in lights:
        bri = max(10, base_bri + random.randint(-25, 15))
        temp = 2700 + random.randint(-200, 400)
        result[role] = {"mode": "cct", "brightness": bri, "temp": temp, "gm": 0}
    return result
```

**Step 3: Commit**

```bash
git add scenes/rainbow_chase.py scenes/campfire.py
git commit -m "feat: add rainbow chase and campfire generative scenes"
```

---

## Phase B: Terminal UI

### Task 10: TUI scaffolding and dashboard view

**Files:**
- Create: `neewer_tui.py`
- Create: `requirements-tui.txt`

**Step 1: Create `requirements-tui.txt`**

```
textual>=0.80.0
```

Install: `pip install textual`

**Step 2: Implement TUI app with dashboard**

Create `neewer_tui.py` (~400 lines for this task):

```python
"""Terminal UI for Neewer light control.

Launch: python neewer_tui.py  or  python neewer.py tui
Requires: pip install -r requirements-tui.txt
"""
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import (Header, Footer, Static, Button, Label,
                                  TabbedContent, TabPane, ProgressBar)
    from textual.reactive import reactive
    from textual.css.query import NoMatches
except ImportError:
    import sys
    print("TUI requires textual. Install: pip install -r requirements-tui.txt")
    sys.exit(1)

import asyncio
import neewer_config


class LightCard(Static):
    """Widget showing one light's status."""

    def __init__(self, role, info, channel, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.info = info
        self.channel = channel
        self.power = False
        self.mode = "unknown"
        self.brightness = 0

    def compose(self):
        indicator = "●" if self.power else "○"
        yield Label(f"{indicator} {self.role}: {self.info['alias']}", classes="card-title")
        yield Label(f"  ch {self.channel} | {self.mode} | bri {self.brightness}%",
                    id=f"status-{self.role}")
        yield Horizontal(
            Button("On", id=f"on-{self.role}", variant="success"),
            Button("Off", id=f"off-{self.role}", variant="error"),
            classes="card-buttons",
        )

    def update_status(self, power, mode, brightness):
        self.power = power
        self.mode = mode
        self.brightness = brightness
        try:
            label = self.query_one(f"#status-{self.role}", Label)
            indicator = "●" if power else "○"
            label.update(f"  ch {self.channel} | {mode} | bri {brightness}%")
            title = self.query_one(".card-title", Label)
            title.update(f"{indicator} {self.role}: {self.info['alias']}")
        except NoMatches:
            pass


class DashboardView(Container):
    """Main dashboard showing all lights in active config."""

    def __init__(self, store, **kwargs):
        super().__init__(**kwargs)
        self.store = store

    def compose(self):
        cfg = self.store.get_active()
        if not cfg:
            yield Label("No active config. Run: neewer.py config use <name>")
            return

        name = self.store.active
        nid = cfg["network_id"]
        yield Label(f"Config: {name}  |  Network: 0x{nid:08X}", classes="header-info")

        with Horizontal(classes="light-cards"):
            for role, info in cfg["lights"].items():
                ch = cfg["channels"].get(role, "?")
                yield LightCard(role, info, ch, classes="light-card")

        snaps = cfg.get("snapshots", {})
        if snaps:
            with Horizontal(classes="snapshots-bar"):
                yield Label("Snapshots: ")
                for snap_name in sorted(snaps.keys()):
                    yield Button(snap_name, id=f"snap-{snap_name}", variant="primary")


class NeewerTUI(App):
    """Neewer light control TUI."""

    CSS = """
    .light-card {
        border: solid green;
        padding: 1;
        margin: 1;
        width: 30;
    }
    .card-buttons {
        margin-top: 1;
    }
    .header-info {
        margin: 1;
        text-style: bold;
    }
    .snapshots-bar {
        margin: 1;
    }
    .status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "dashboard", "Dashboard"),
        ("s", "designer", "Designer"),
        ("c", "console", "Console"),
    ]

    def __init__(self):
        super().__init__()
        self.store = neewer_config.ConfigStore()

    def compose(self):
        yield Header()
        with TabbedContent():
            with TabPane("Dashboard", id="tab-dashboard"):
                yield DashboardView(self.store)
            with TabPane("Designer", id="tab-designer"):
                yield Label("Scene Designer — coming soon")
            with TabPane("Console", id="tab-console"):
                yield Label("Performance Console — coming soon")
        yield Footer()
        yield Label(self._status_text(), classes="status-bar")

    def _status_text(self):
        cfg = self.store.get_active()
        if not cfg:
            return "No active config"
        name = self.store.active
        nid = cfg["network_id"]
        parts = [f"Config: {name}", f"Net: 0x{nid:08X}"]
        for role, info in cfg["lights"].items():
            ch = cfg["channels"].get(role, "?")
            relay = " (relay)" if role == next(iter(cfg["lights"])) else ""
            parts.append(f"ch{ch}: {info['alias']}{relay}")
        return " | ".join(parts)

    def on_button_pressed(self, event):
        btn_id = event.button.id or ""
        if btn_id.startswith("on-"):
            role = btn_id[3:]
            self.notify(f"Power ON: {role}")
            # TODO: send BLE command in Phase B refinement
        elif btn_id.startswith("off-"):
            role = btn_id[4:]
            self.notify(f"Power OFF: {role}")
        elif btn_id.startswith("snap-"):
            snap = btn_id[5:]
            self.notify(f"Recall snapshot: {snap}")


def main():
    app = NeewerTUI()
    app.run()


if __name__ == "__main__":
    main()
```

**Step 3: Add `tui` subcommand to `neewer.py`**

In `build_parser()`:
```python
sub.add_parser("tui", help="launch terminal UI")
```

In `main()`:
```python
elif args.command == "tui":
    import neewer_tui
    neewer_tui.main()
    return
```

**Step 4: Test TUI launches**

```bash
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer_tui.py
```
Expected: TUI appears with tabs. Press `q` to quit.

**Step 5: Commit**

```bash
git add neewer_tui.py requirements-tui.txt neewer.py
git commit -m "feat: add TUI scaffolding with dashboard view and light cards"
```

---

### Task 11: TUI — BLE integration and live control

**Files:**
- Modify: `neewer_tui.py` (add BLE worker, wire buttons to commands)

Connect the TUI to actual BLE hardware. A background async task maintains the relay connection and processes a command queue. Button presses and fader changes enqueue commands.

**Step 1: Add BLE worker class**

```python
class BLEWorker:
    """Background BLE connection manager for the TUI."""

    def __init__(self, store):
        self.store = store
        self.client = None
        self.mac_bytes = None
        self.proto = None
        self.connected = False
        self._queue = asyncio.Queue()

    async def connect(self):
        import neewer
        from bleak import BleakClient
        cfg_name = self.store.active
        cfg = self.store.get_active()
        if not cfg or not cfg["lights"]:
            return False

        relay_role = self.store.get_relay_role(cfg_name)
        device = cfg["lights"][relay_role]["device"]

        # Resolve address
        # (import neewer's _resolve_light_alias or use cache directly)
        lights = {}  # load from neewer._cache
        # ... connect via BleakClient
        self.connected = True
        return True

    async def send(self, role, mode, params):
        await self._queue.put((role, mode, params))

    async def run(self):
        """Process command queue."""
        import neewer
        while True:
            role, mode, params = await self._queue.get()
            if not self.connected:
                continue
            cfg = self.store.get_active()
            nid = cfg["network_id"]
            ch = cfg["channels"].get(role)
            bri = params.get("brightness", 50)

            if mode == "power":
                on = params.get("on", True)
                pkt = neewer.ch_cmd_power(nid, ch, on=on)
            elif mode == "cct":
                pkt = neewer.ch_cmd_cct(nid, ch, bri,
                                         params.get("temp", 5000),
                                         params.get("gm", 0))
            elif mode == "hsi":
                pkt = neewer.ch_cmd_hsi(nid, ch,
                                         params.get("hue", 0),
                                         params.get("sat", 100), bri)
            else:
                continue

            try:
                await self.client.write_gatt_char(
                    neewer.WRITE_UUID, pkt, response=False)
            except Exception:
                self.connected = False
```

**Step 2: Wire into `NeewerTUI.on_button_pressed`**

Replace the notify stubs with actual BLE commands via the worker queue.

**Step 3: Test with hardware**

```bash
python neewer.py config create test
python neewer.py config add-light test key --light 0
python neewer.py config use test
python neewer_tui.py
```
Click On/Off buttons — light should toggle.

**Step 4: Commit**

```bash
git add neewer_tui.py
git commit -m "feat: add BLE worker to TUI for live light control"
```

---

### Task 12: TUI — Scene Designer view

**Files:**
- Modify: `neewer_tui.py` (replace designer placeholder)

Add a basic scene designer view: load a YAML scene, display timeline, edit step parameters with input fields, preview on lights, save.

**Step 1: Implement DesignerView widget**

Replace the placeholder in the Designer tab with:
- Scene file selector (list from `scenes/`)
- Timeline visualization (text-based per-role tracks)
- Step editor with input fields for brightness, temp, hue, sat
- Preview button (runs scene via SceneRunner)
- Save button (writes modified YAML)

**Step 2: Test the designer**

Load `scenes/sunset-fade.yaml`, modify a brightness value, preview, save.

**Step 3: Commit**

```bash
git add neewer_tui.py
git commit -m "feat: add scene designer view to TUI"
```

---

### Task 13: TUI — Performance Console view

**Files:**
- Modify: `neewer_tui.py` (replace console placeholder)

Add the performance console: vertical faders, hotkey triggers, scene status display.

**Step 1: Implement ConsoleView widget**

Replace the Console tab placeholder with:
- Vertical fader widgets per role (brightness and temp)
- Master fader that scales all
- F1-F6 hotkey buttons for scenes/presets
- "Now Playing" panel when a scene is running
- Audio meter placeholder (wired in Phase C)

**Step 2: Test faders**

Move brightness fader — light should change in real-time.

**Step 3: Commit**

```bash
git add neewer_tui.py
git commit -m "feat: add performance console view to TUI with faders and hotkeys"
```

---

## Phase C: Audio System

### Task 14: Audio analysis core

**Files:**
- Create: `neewer_audio.py`
- Create: `test_audio.py`
- Create: `requirements-audio.txt`

**Step 1: Create `requirements-audio.txt`**

```
numpy>=1.24.0
sounddevice>=0.4.6
```

**Step 2: Write failing tests**

Create `test_audio.py`:

```python
"""Tests for neewer_audio.py — audio analysis."""
import numpy as np
import neewer_audio


def test_audio_frame_defaults():
    frame = neewer_audio.AudioFrame()
    assert frame.amplitude == 0.0
    assert frame.beat is False
    assert frame.bands == [0.0, 0.0, 0.0]
    assert frame.bpm == 0.0


def test_rms():
    # Sine wave at full amplitude
    samples = np.sin(np.linspace(0, 2 * np.pi, 1024)).astype(np.float32)
    rms = neewer_audio.compute_rms(samples)
    assert 0.6 < rms < 0.8  # RMS of sine ≈ 0.707


def test_rms_silence():
    samples = np.zeros(1024, dtype=np.float32)
    rms = neewer_audio.compute_rms(samples)
    assert rms == 0.0


def test_frequency_bands():
    sr = 44100
    # Pure 100Hz tone (bass)
    t = np.linspace(0, 2048 / sr, 2048, endpoint=False)
    tone = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    bass, mid, treble = neewer_audio.compute_bands(tone, sr)
    assert bass > mid
    assert bass > treble


def test_frequency_bands_treble():
    sr = 44100
    # Pure 5000Hz tone (treble)
    t = np.linspace(0, 2048 / sr, 2048, endpoint=False)
    tone = np.sin(2 * np.pi * 5000 * t).astype(np.float32)
    bass, mid, treble = neewer_audio.compute_bands(tone, sr)
    assert treble > bass


def test_beat_detector_no_beat_on_silence():
    det = neewer_audio.BeatDetector()
    samples = np.zeros(2048, dtype=np.float32)
    for _ in range(10):
        assert det.process(samples) is False


def test_beat_detector_detects_onset():
    det = neewer_audio.BeatDetector()
    silence = np.zeros(2048, dtype=np.float32)
    # Prime with silence
    for _ in range(5):
        det.process(silence)
    # Sudden loud burst
    burst = np.ones(2048, dtype=np.float32) * 0.8
    result = det.process(burst)
    assert result is True
```

**Step 3: Run tests to verify they fail**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_audio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neewer_audio'`

**Step 4: Implement `neewer_audio.py`**

```python
"""Audio analysis for Neewer sound-reactive scenes.

Provides AudioFrame with amplitude, beat detection, and frequency bands.
Pluggable source abstraction — MicSource implemented, others planned.

Requires: pip install -r requirements-audio.txt (numpy, sounddevice)
"""
try:
    import numpy as np
except ImportError:
    raise ImportError("Audio requires numpy. Install: pip install -r requirements-audio.txt")

import asyncio


class AudioFrame:
    """Single frame of audio analysis results."""

    def __init__(self, amplitude=0.0, beat=False, bands=None, bpm=0.0):
        self.amplitude = amplitude
        self.beat = beat
        self.bands = bands or [0.0, 0.0, 0.0]
        self.bpm = bpm


def compute_rms(samples):
    """Compute RMS (root mean square) amplitude of a sample buffer."""
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def compute_bands(samples, sample_rate=44100):
    """Split audio into bass/mid/treble frequency bands via FFT.

    Returns (bass, mid, treble) each normalized 0.0-1.0.
    Bass: <300Hz, Mid: 300-2000Hz, Treble: >2000Hz
    """
    n = len(samples)
    if n == 0:
        return 0.0, 0.0, 0.0

    fft = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

    bass_mask = freqs < 300
    mid_mask = (freqs >= 300) & (freqs < 2000)
    treble_mask = freqs >= 2000

    total = np.sum(fft) + 1e-10
    bass = float(np.sum(fft[bass_mask]) / total)
    mid = float(np.sum(fft[mid_mask]) / total)
    treble = float(np.sum(fft[treble_mask]) / total)

    return bass, mid, treble


class BeatDetector:
    """Energy-based beat/onset detection."""

    def __init__(self, threshold=1.5, history_size=20):
        self.threshold = threshold
        self.history = []
        self.history_size = history_size
        self.beat_times = []

    def process(self, samples):
        """Process a sample buffer. Returns True if beat detected."""
        energy = float(np.mean(samples ** 2))
        self.history.append(energy)
        if len(self.history) > self.history_size:
            self.history.pop(0)

        if len(self.history) < 3:
            return False

        avg = sum(self.history) / len(self.history)
        if avg < 1e-8:
            return False

        is_beat = energy > avg * self.threshold
        return is_beat

    @property
    def bpm(self):
        if len(self.beat_times) < 2:
            return 0.0
        intervals = [self.beat_times[i] - self.beat_times[i - 1]
                     for i in range(1, len(self.beat_times))]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            return 0.0
        return 60.0 / avg_interval


class AudioSource:
    """Base class for audio sources."""

    async def start(self):
        raise NotImplementedError

    async def read_frame(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError


class MicSource(AudioSource):
    """Microphone audio source via sounddevice."""

    def __init__(self, device=None, sample_rate=44100, block_size=2048):
        self.device = device
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.beat_detector = BeatDetector()
        self._buffer = None
        self._buffer_ready = None

    async def start(self):
        import sounddevice as sd
        self._buffer_ready = asyncio.Event()

        def callback(indata, frames, time_info, status):
            self._buffer = indata[:, 0].copy()
            # Thread-safe event set
            try:
                self._buffer_ready.set()
            except RuntimeError:
                pass

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self.stream.start()

    async def read_frame(self):
        if self._buffer_ready is None:
            return AudioFrame()

        self._buffer_ready.clear()
        try:
            await asyncio.wait_for(self._buffer_ready.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            return AudioFrame()

        samples = self._buffer
        if samples is None:
            return AudioFrame()

        amplitude = min(1.0, compute_rms(samples))
        beat = self.beat_detector.process(samples)
        bands = list(compute_bands(samples, self.sample_rate))

        if beat:
            import time
            self.beat_detector.beat_times.append(time.time())
            if len(self.beat_detector.beat_times) > 20:
                self.beat_detector.beat_times.pop(0)

        return AudioFrame(
            amplitude=amplitude,
            beat=beat,
            bands=bands,
            bpm=self.beat_detector.bpm,
        )

    async def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
```

**Step 5: Run tests**

Run: `/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_audio.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add neewer_audio.py test_audio.py requirements-audio.txt
git commit -m "feat: add audio analysis with RMS, beat detection, frequency bands"
```

---

### Task 15: `audio-test` CLI command

**Files:**
- Modify: `neewer.py`

Add a diagnostic command that shows live audio levels in the terminal.

**Step 1: Add subcommand to `build_parser()`**

```python
p_audio = sub.add_parser("audio-test", help="test microphone input (show live levels)")
p_audio.add_argument("--mic", action="store_true", default=True, help="use microphone")
p_audio.add_argument("--device", type=int, default=None, help="audio device index")
```

**Step 2: Add handler**

```python
elif args.command == "audio-test":
    import neewer_audio
    source = neewer_audio.MicSource(device=args.device)

    async def run_test():
        await source.start()
        print("Listening... (Ctrl+C to stop)\n")
        try:
            while True:
                frame = await source.read_frame()
                bar_len = int(frame.amplitude * 40)
                bar = "█" * bar_len + "░" * (40 - bar_len)
                beat = " BEAT!" if frame.beat else ""
                bass, mid, treble = frame.bands
                bpm_str = f" ~{frame.bpm:.0f} BPM" if frame.bpm > 0 else ""
                print(f"\r  Vol: |{bar}| {frame.amplitude:.2f}{beat}{bpm_str}"
                      f"  B:{bass:.2f} M:{mid:.2f} T:{treble:.2f}    ",
                      end="", flush=True)
        except asyncio.CancelledError:
            pass
        finally:
            await source.stop()
            print("\nDone.")

    await run_test()
```

**Step 3: Test with actual microphone**

```bash
/opt/homebrew/Caskroom/miniforge/base/bin/python neewer.py audio-test
```
Expected: Live volume bar updates. Clap → "BEAT!" appears.

**Step 4: Commit**

```bash
git add neewer.py
git commit -m "feat: add audio-test CLI command for mic diagnostics"
```

---

### Task 16: Audio-reactive example scenes

**Files:**
- Create: `scenes/sound_pulse.py`
- Create: `scenes/beat_flash.py`
- Create: `scenes/frequency_map.py`

**Step 1: Create scenes**

`scenes/sound_pulse.py`:
```python
"""Brightness follows audio amplitude."""
name = "Sound Pulse"
fps = 30

def render(tick, lights, params, audio=None):
    if not audio:
        return {"all": {"mode": "cct", "brightness": 50, "temp": 5000}}
    bri = max(5, int(audio.amplitude * 100))
    temp = params.get("temp", 5000)
    return {"all": {"mode": "cct", "brightness": bri, "temp": temp}}
```

`scenes/beat_flash.py`:
```python
"""Color changes on beat detection."""
name = "Beat Flash"
fps = 30

def render(tick, lights, params, audio=None):
    if not audio or not audio.beat:
        return None  # no update
    hue = (tick * 37) % 360
    return {"all": {"mode": "hsi", "hue": hue, "sat": 100, "brightness": 90}}
```

`scenes/frequency_map.py`:
```python
"""Map frequency bands to light parameters."""
name = "Frequency Map"
fps = 30

def render(tick, lights, params, audio=None):
    if not audio:
        return {"all": {"mode": "hsi", "hue": 0, "sat": 50, "brightness": 30}}
    bass, mid, treble = audio.bands
    hue = int(treble * 360) % 360
    sat = max(20, int(mid * 100))
    bri = max(5, int(bass * 100))
    return {"all": {"mode": "hsi", "hue": hue, "sat": sat, "brightness": bri}}
```

**Step 2: Commit**

```bash
git add scenes/sound_pulse.py scenes/beat_flash.py scenes/frequency_map.py
git commit -m "feat: add sound-reactive example scenes (pulse, beat flash, frequency map)"
```

---

### Task 17: TUI audio integration

**Files:**
- Modify: `neewer_tui.py` (add audio meter to console view)

Wire the audio source into the Performance Console tab: show a live amplitude bar, beat indicator, and BPM readout. The audio source runs as a background task alongside the BLE worker.

**Step 1: Add AudioMeter widget**

```python
class AudioMeter(Static):
    """Live audio level display."""

    amplitude = reactive(0.0)
    beat = reactive(False)
    bpm = reactive(0.0)

    def render(self):
        bar_len = int(self.amplitude * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        beat_str = " ♪" if self.beat else ""
        bpm_str = f" ~{self.bpm:.0f} BPM" if self.bpm > 0 else ""
        return f"Audio: |{bar}| {self.amplitude:.0%}{beat_str}{bpm_str}"
```

**Step 2: Wire into ConsoleView**

Add the AudioMeter widget below the faders. A background task reads from `MicSource` and updates the meter's reactive properties.

**Step 3: Test**

Launch TUI with a config active. Audio meter should show live levels when mic is connected.

**Step 4: Commit**

```bash
git add neewer_tui.py
git commit -m "feat: add audio meter to TUI performance console"
```

---

### Task 18: Final integration test and docs

**Files:**
- Run all tests
- Update `CLAUDE.md`
- Update `docs/protocol.md` if needed

**Step 1: Run full test suite**

```bash
/opt/homebrew/Caskroom/miniforge/base/bin/python -m pytest test_protocol.py test_sacn_bridge.py test_config.py test_scenes.py test_audio.py -v
```
Expected: All PASS

**Step 2: Update CLAUDE.md**

Add sections for:
- Config commands (`config create/use/show/add-light/snapshot`)
- Scene commands (`scene-run`, `scene-list`)
- TUI (`tui` command, requirements-tui.txt)
- Audio (`audio-test`, `--mic` flag, requirements-audio.txt)
- Updated test count
- Updated command count

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with config, scene, TUI, and audio features"
```

---

## Verification Checklist

After all tasks complete:

1. `python neewer.py config create studio` — creates config with random NETID
2. `python neewer.py config add-light studio key --light 0` — assigns role
3. `python neewer.py config use studio` — sets active
4. `python neewer.py config show studio` — displays lights, channels, snapshots
5. `python neewer.py connections` — shows BLE state and channel map
6. `python neewer.py --config studio cct --brightness 80 --temp 5600` — targets config lights
7. `python neewer.py scene-list` — lists scene files
8. `python neewer.py scene-run scenes/sunset-fade.yaml` — runs scripted scene
9. `python neewer.py scene-run scenes/rainbow_chase.py` — runs generative scene
10. `python neewer_tui.py` — TUI launches with dashboard
11. `python neewer.py audio-test` — mic levels display
12. `python neewer.py scene-run scenes/beat_flash.py --mic` — sound-reactive scene
13. All tests pass
