"""Configuration management for Neewer lights.

Persistent multi-group configs with role-based light assignments,
channel auto-management, and state snapshots.

Storage: .neewer_config.json (separate from .neewer_cache.json)
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

    # --- Snapshots ---

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

    # --- Resolution helpers ---

    def resolve_targets(self, config_name, role=None):
        """Resolve config to list of (role, device, channel) tuples."""
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
        """Parse 'config:role' or 'config' → (config_name, role_or_None)."""
        if ":" in target_str:
            config_name, role = target_str.split(":", 1)
            return config_name, role
        return target_str, None

    def get_relay_role(self, config_name):
        """Get the first role (used as relay light for channel mode)."""
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

    # --- Internal ---

    def _get_config(self, name):
        if name not in self.configs:
            raise ValueError(f"Config '{name}' not found")
        return self.configs[name]


# --- Display helpers ---

def print_config(store, name):
    cfg = store._get_config(name)
    marker = " (active)" if name == store.active else ""
    print(f"Config: {name}{marker}")
    print(f"Network ID: 0x{cfg['network_id']:08X}")
    print()
    if cfg["lights"]:
        print(f"  {'Role':<12s} {'Light':<22s} {'Channel'}")
        print("  " + "-" * 45)
        for role, info in cfg["lights"].items():
            ch = cfg["channels"].get(role, "?")
            relay = " (relay)" if role == next(iter(cfg["lights"])) else ""
            print(f"  {role:<12s} {info['alias']:<22s} ch {ch}{relay}")
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
    if cfg["lights"]:
        print("  Channel assignments:")
        for role, info in cfg["lights"].items():
            ch = cfg["channels"].get(role, "?")
            relay = " (relay)" if role == next(iter(cfg["lights"])) else ""
            print(f"    ch {ch}: {info['alias']} ({role}){relay}")
    else:
        print("  No lights assigned.")
