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
import json
import os
import neewer_config


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

        # Resolve address from cache
        cache_path = os.path.expanduser("~/.neewer_cache.json")
        addr = device
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cache = json.load(f)
            for a, info in cache.get("lights", {}).items():
                if info.get("alias") == device or info.get("name") == device:
                    addr = a
                    break

        try:
            self.client = BleakClient(addr)
            await self.client.connect()
            self.mac_bytes = neewer.parse_mac(
                cache.get("macs", {}).get(addr, "00:00:00:00:00:00"))
            dname = cache.get("lights", {}).get(addr, {}).get("name", "")
            self.proto = neewer.detect_protocol(dname)
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

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

            try:
                if mode == "power":
                    on = params.get("on", True)
                    if ch is not None:
                        pkt = neewer.ch_cmd_power(nid, ch, on=on)
                    else:
                        pkt = neewer.build_power(self.proto, self.mac_bytes, on=on)
                elif mode == "cct":
                    temp = params.get("temp", 5000)
                    gm = params.get("gm", 0)
                    if ch is not None:
                        pkt = neewer.ch_cmd_cct(nid, ch, bri, temp, gm)
                    else:
                        pkt = neewer.build_cct(self.proto, self.mac_bytes, bri, temp, gm)
                elif mode == "hsi":
                    hue = params.get("hue", 0)
                    sat = params.get("sat", 100)
                    if ch is not None:
                        pkt = neewer.ch_cmd_hsi(nid, ch, hue, sat, bri)
                    else:
                        pkt = neewer.build_hsi(self.proto, self.mac_bytes, hue, sat, bri)
                else:
                    continue

                await self.client.write_gatt_char(
                    neewer.WRITE_UUID, pkt, response=False)
            except Exception:
                self.connected = False


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
        self.ble = BLEWorker(self.store)

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

    async def on_mount(self):
        ok = await self.ble.connect()
        if ok:
            self.notify("BLE connected")
            asyncio.get_event_loop().create_task(self.ble.run())
        else:
            self.notify("BLE not connected (offline mode)", severity="warning")

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
            asyncio.get_event_loop().create_task(
                self.ble.send(role, "power", {"on": True}))
        elif btn_id.startswith("off-"):
            role = btn_id[4:]
            self.notify(f"Power OFF: {role}")
            asyncio.get_event_loop().create_task(
                self.ble.send(role, "power", {"on": False}))
        elif btn_id.startswith("snap-"):
            snap = btn_id[5:]
            self.notify(f"Recall snapshot: {snap}")


def main():
    app = NeewerTUI()
    app.run()


if __name__ == "__main__":
    main()
