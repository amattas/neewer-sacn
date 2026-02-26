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

    def _get_config(self, name):
        if name not in self.configs:
            raise ValueError(f"Config '{name}' not found")
        return self.configs[name]
