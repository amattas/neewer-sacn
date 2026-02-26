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
