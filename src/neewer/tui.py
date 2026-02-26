"""Terminal UI for Neewer light control.

Launch: python neewer_tui.py  or  python neewer.py tui
Requires: pip install -r requirements-tui.txt
"""
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import (Header, Footer, Static, Button, Label,
                                  TabbedContent, TabPane, ProgressBar,
                                  Input, Select, ListView, ListItem)
    from textual.reactive import reactive
    from textual.css.query import NoMatches
except ImportError:
    import sys
    print("TUI requires textual. Install: pip install -r requirements-tui.txt")
    sys.exit(1)

import asyncio
import json
import os
from neewer import config as neewer_config


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
        from neewer import protocol as neewer
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
        from neewer import protocol as neewer

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


class DesignerView(Container):
    """Scene designer: load, view timeline, edit steps, preview, save."""

    def __init__(self, store, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self.scene = None
        self.scene_path = None

    def compose(self):
        from neewer import scenes as neewer_scenes
        scenes = neewer_scenes.list_scenes()
        items = [(os.path.basename(p), p) for p in scenes]

        yield Label("Scene Designer", classes="header-info")
        with Horizontal():
            with Vertical(classes="scene-sidebar"):
                yield Label("Scenes:")
                if items:
                    yield Select(items, id="scene-select", prompt="Choose scene...")
                else:
                    yield Label("No scenes found in scenes/")
                yield Button("Reload", id="designer-reload")
            with Vertical(classes="scene-editor", id="scene-editor"):
                yield Label("Select a scene to edit", id="timeline-display")

    def on_select_changed(self, event):
        if event.select.id != "scene-select":
            return
        from neewer import scenes as neewer_scenes
        path = event.value
        if path is Select.BLANK:
            return
        try:
            self.scene = neewer_scenes.load_scene(path)
            self.scene_path = path
            self._render_timeline()
        except Exception as e:
            try:
                self.query_one("#timeline-display", Label).update(f"Error: {e}")
            except NoMatches:
                pass

    def _render_timeline(self):
        if not self.scene:
            return
        s = self.scene
        lines = [f"Name: {s.name}"]
        if s.generative:
            lines.append(f"Type: generative  FPS: {s.fps}")
            lines.append("(Generative scenes cannot be edited here)")
        else:
            lines.append(f"Duration: {s.duration}s  Loop: {s.loop}")
            lines.append(f"Targets: {', '.join(s.target_roles)}")
            lines.append("")
            for i, step in enumerate(s.steps):
                lines.append(f"--- Step {i+1} at {step.time}s ---")
                for role, params in step.targets.items():
                    lines.append(f"  {role}: {params}")

        try:
            self.query_one("#timeline-display", Label).update("\n".join(lines))
        except NoMatches:
            pass


class FaderWidget(Static):
    """Vertical fader for brightness/temp control."""

    def __init__(self, role, label, min_val=0, max_val=100, value=50, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.fader_label = label
        self.min_val = min_val
        self.max_val = max_val
        self.value = value

    def compose(self):
        yield Label(f"{self.fader_label}", classes="fader-label")
        yield ProgressBar(total=self.max_val - self.min_val,
                         show_eta=False, show_percentage=True,
                         id=f"fader-bar-{self.role}-{self.fader_label}")
        with Horizontal():
            yield Button("-", id=f"fader-down-{self.role}-{self.fader_label}",
                        classes="fader-btn")
            yield Label(str(self.value), id=f"fader-val-{self.role}-{self.fader_label}")
            yield Button("+", id=f"fader-up-{self.role}-{self.fader_label}",
                        classes="fader-btn")


class AudioMeter(Static):
    """Live audio level display."""

    amplitude = reactive(0.0)
    beat = reactive(False)
    bpm = reactive(0.0)
    bands = reactive((0.0, 0.0, 0.0))

    def render(self):
        bar_len = int(self.amplitude * 30)
        bar = "\u2588" * bar_len + "\u2591" * (30 - bar_len)
        beat_str = " \u266a" if self.beat else ""
        bpm_str = f" ~{self.bpm:.0f} BPM" if self.bpm > 0 else ""
        b, m, t = self.bands
        return (f"Audio: |{bar}| {self.amplitude:.0%}{beat_str}{bpm_str}"
                f"  B:{b:.2f} M:{m:.2f} T:{t:.2f}")


class ConsoleView(Container):
    """Performance console: faders, hotkeys, scene status."""

    def __init__(self, store, ble, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self.ble = ble

    def compose(self):
        yield Label("Performance Console", classes="header-info")

        cfg = self.store.get_active()
        if not cfg:
            yield Label("No active config")
            return

        # Master fader
        yield Label("Master", classes="section-label")
        yield FaderWidget("master", "Brightness", 0, 100, 50, classes="fader")

        # Per-role faders
        with Horizontal(classes="role-faders"):
            for role in cfg["lights"]:
                with Vertical(classes="role-column"):
                    yield Label(role, classes="role-label")
                    yield FaderWidget(role, "Bri", 0, 100, 50, classes="fader")
                    yield FaderWidget(role, "Temp", 2500, 10000, 5000, classes="fader")

        # Hotkey buttons
        yield Label("Quick Actions", classes="section-label")
        with Horizontal(classes="hotkey-bar"):
            yield Button("F1: All On", id="hotkey-f1", variant="success")
            yield Button("F2: All Off", id="hotkey-f2", variant="error")
            yield Button("F3: Warm", id="hotkey-f3", variant="warning")
            yield Button("F4: Cool", id="hotkey-f4", variant="primary")
            yield Button("F5: Scene", id="hotkey-f5")
            yield Button("F6: Blackout", id="hotkey-f6", variant="error")

        # Audio meter
        yield AudioMeter(id="audio-meter")

        # Scene status
        yield Label("Now Playing: (none)", id="now-playing", classes="section-label")


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
    .scene-sidebar {
        width: 30;
        border: solid $primary;
        padding: 1;
    }
    .scene-editor {
        padding: 1;
    }
    .section-label {
        margin: 1 0;
        text-style: bold;
    }
    .role-faders {
        margin: 1;
    }
    .role-column {
        width: 20;
        margin: 0 1;
    }
    .fader-btn {
        width: 5;
    }
    .fader-label {
        text-style: italic;
    }
    .hotkey-bar {
        margin: 1;
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
                yield DesignerView(self.store)
            with TabPane("Console", id="tab-console"):
                yield ConsoleView(self.store, self.ble)
        yield Footer()
        yield Label(self._status_text(), classes="status-bar")

    async def on_mount(self):
        ok = await self.ble.connect()
        if ok:
            self.notify("BLE connected")
            asyncio.get_event_loop().create_task(self.ble.run())
        else:
            self.notify("BLE not connected (offline mode)", severity="warning")

        # Start audio monitoring
        asyncio.get_event_loop().create_task(self._audio_loop())

    async def _audio_loop(self):
        try:
            from neewer import audio as neewer_audio
            source = neewer_audio.MicSource()
            await source.start()
        except Exception:
            return

        try:
            while True:
                frame = await source.read_frame()
                try:
                    meter = self.query_one("#audio-meter", AudioMeter)
                    meter.amplitude = frame.amplitude
                    meter.beat = frame.beat
                    meter.bpm = frame.bpm
                    meter.bands = tuple(frame.bands)
                except NoMatches:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            await source.stop()

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
        elif btn_id.startswith("fader-up-") or btn_id.startswith("fader-down-"):
            self._handle_fader(btn_id)
        elif btn_id.startswith("hotkey-"):
            self._handle_hotkey(btn_id)

    def _handle_fader(self, btn_id):
        parts = btn_id.split("-", 3)
        direction = parts[1]  # up or down
        role = parts[2]
        step = 10
        cfg = self.store.get_active()
        if not cfg:
            return
        roles = list(cfg["lights"].keys()) if role == "master" else [role]
        for r in roles:
            asyncio.get_event_loop().create_task(
                self.ble.send(r, "cct", {"brightness": 50, "temp": 5000}))
        self.notify(f"Fader {direction}: {role}")

    def _handle_hotkey(self, btn_id):
        cfg = self.store.get_active()
        if not cfg:
            return
        roles = list(cfg["lights"].keys())
        if btn_id == "hotkey-f1":
            for r in roles:
                asyncio.get_event_loop().create_task(
                    self.ble.send(r, "power", {"on": True}))
            self.notify("All ON")
        elif btn_id == "hotkey-f2":
            for r in roles:
                asyncio.get_event_loop().create_task(
                    self.ble.send(r, "power", {"on": False}))
            self.notify("All OFF")
        elif btn_id == "hotkey-f3":
            for r in roles:
                asyncio.get_event_loop().create_task(
                    self.ble.send(r, "cct", {"brightness": 80, "temp": 3200}))
            self.notify("Warm preset")
        elif btn_id == "hotkey-f4":
            for r in roles:
                asyncio.get_event_loop().create_task(
                    self.ble.send(r, "cct", {"brightness": 80, "temp": 6500}))
            self.notify("Cool preset")
        elif btn_id == "hotkey-f6":
            for r in roles:
                asyncio.get_event_loop().create_task(
                    self.ble.send(r, "power", {"on": False}))
            self.notify("Blackout")


def main():
    app = NeewerTUI()
    app.run()


if __name__ == "__main__":
    main()
