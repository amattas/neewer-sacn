#!/usr/bin/env python3
"""Neewer sACN (E1.31) Bridge — control BLE lights as DMX fixtures.

Receives sACN/E1.31 data on a universe and translates DMX channel values
to BLE commands for Neewer lights. Each light gets a 10-channel DMX footprint
matching the Neewer DMX spec:

  Offset  Name        CCT (0-31)      HSI (32-63)     FX (64-95)
  ------  ----------  --------------  --------------  --------------
  0       Mode        0-31            32-63           64-95
  1       Dimmer      0-255 → 0-100%  0-255 → 0-100%  0-255 → 0-100%
  2       Param A     CCT temp        Hue             Effect ID
  3       Param B     G/M             Saturation      Speed/Pace
  4-9     FX subs     (unused)        (unused)        Effect sub-params

  Mode 128-255 = blackout/power off.

Usage:
  python neewer_sacn.py                         # scan, auto-assign from ch 1
  python neewer_sacn.py -u 2 -s 11             # universe 2, start at ch 11
  python neewer_sacn.py --list-channels         # show channel map and exit
"""

import argparse
import asyncio
import platform
import sys
import threading
import time

import sacn
from bleak import BleakClient, BleakScanner

# Import protocol layer from neewer.py
import neewer

# -- Constants ---------------------------------------------------------------

CHANNELS_PER_LIGHT = 10
DEFAULT_FPS = 20
MIN_SEND_INTERVAL = 0.03  # 30ms min between BLE writes to same light


# -- DMX value mapping -------------------------------------------------------

def dmx_to_pct(val):
    """DMX 0-255 → 0-100 percent."""
    return round(val * 100 / 255)


def dmx_to_cct_k(val):
    """DMX 0-255 → 2500-10000K (linear)."""
    return 2500 + round(val * 7500 / 255)


def dmx_to_hue(val):
    """DMX 0-255 → 0-359 degrees."""
    return round(val * 359 / 255)


def dmx_to_gm(val):
    """DMX 0-255 → -50 to +50 (green-magenta)."""
    return round(val * 100 / 255) - 50


def dmx_to_speed(val):
    """DMX 0-255 → 1-10 (effect speed)."""
    return 1 + round(val * 9 / 255)


def dmx_to_effect(val):
    """DMX 0-255 → effect ID 1-18."""
    return 1 + min(17, val * 18 // 256)


# -- Light connection --------------------------------------------------------

class LightConnection:
    """Manages a persistent BLE connection to a single Neewer light."""

    def __init__(self, address, name, start_channel):
        self.address = address
        self.name = name
        self.start_channel = start_channel  # 1-based DMX address
        self.client = None
        self.mac_bytes = None
        self.proto = None
        self.connected = False
        self.last_dmx = None          # last-sent DMX slice (tuple)
        self.last_send_time = 0.0
        self.current_mode = None      # "cct", "hsi", "fx", "off"
        self.current_effect = None    # effect ID when in fx mode
        self.power_on = False

    async def connect(self):
        try:
            self.client = BleakClient(self.address, timeout=10.0)
            await self.client.connect()
            self.connected = True

            # Resolve protocol from device name
            self.proto = neewer.detect_protocol(self.name)

            # Resolve hardware MAC
            if platform.system() == "Darwin":
                mac_str = await neewer._resolve_mac_from_profiler(self.name)
                if mac_str:
                    self.mac_bytes = neewer.parse_mac(mac_str)
                else:
                    self.mac_bytes = [0] * 6
            else:
                # Linux: BLE address is the hardware MAC
                self.mac_bytes = neewer.parse_mac(self.address)

            return True
        except Exception as e:
            print(f"  WARN: connect failed for {self.name}: {e}", file=sys.stderr)
            self.connected = False
            return False

    async def disconnect(self):
        if self.client and self.connected:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.connected = False

    async def send(self, pkt):
        if not self.connected or not self.client:
            return False
        try:
            await self.client.write_gatt_char(neewer.WRITE_UUID, pkt, response=False)
            self.last_send_time = time.monotonic()
            return True
        except Exception as e:
            print(f"  WARN: BLE write failed ({self.name}): {e}", file=sys.stderr)
            self.connected = False
            return False


# -- Bridge ------------------------------------------------------------------

class NeewerSACNBridge:

    def __init__(self, universe=1, fps=DEFAULT_FPS):
        self.universe = universe
        self.poll_interval = 1.0 / fps
        self.lights = []
        self.latest_dmx = None
        self.dmx_lock = threading.Lock()
        self.receiver = None
        self.running = False
        self.verbose = False
        self.frame_count = 0

    # -- sACN callback (runs in receiver thread) --

    def _on_dmx(self, packet):
        with self.dmx_lock:
            self.latest_dmx = packet.dmxData
            self.frame_count += 1

    # -- Setup --

    async def scan_and_setup(self, start_channel=1, timeout=5.0):
        print(f"Scanning for Neewer lights ({timeout}s)...")

        found = await BleakScanner.discover(timeout=timeout, return_adv=True)

        candidates = []
        for device, adv in found.values():
            name = device.name or adv.local_name or ""
            if name.startswith("NEEWER") or name.startswith("NW-"):
                candidates.append((device, adv, name))

        if not candidates:
            print("No Neewer lights found.")
            return False

        # Deduplicate by name (keep strongest RSSI)
        seen = {}
        for device, adv, name in candidates:
            rssi = adv.rssi if adv.rssi is not None else -100
            if name not in seen or rssi > seen[name][1]:
                seen[name] = (device, rssi, name)

        ch = start_channel
        for dname in sorted(seen.keys()):
            device, rssi, name = seen[dname]
            light = LightConnection(device.address, name, ch)
            self.lights.append(light)
            ch += CHANNELS_PER_LIGHT

        return True

    async def connect_all(self):
        print(f"Connecting to {len(self.lights)} light(s)...")
        for light in self.lights:
            ok = await light.connect()
            status = f"proto={light.proto}" if ok else "FAILED"
            print(f"  {light.name} ch {light.start_channel}-"
                  f"{light.start_channel + CHANNELS_PER_LIGHT - 1}  {status}")
            await asyncio.sleep(0.3)

    # -- DMX → BLE translation --

    def _get_light_dmx(self, light):
        if self.latest_dmx is None:
            return None
        start = light.start_channel - 1  # DMX 1-based → 0-based
        end = start + CHANNELS_PER_LIGHT
        if end > len(self.latest_dmx):
            return None
        return tuple(self.latest_dmx[start:end])

    async def _send_dmx_to_light(self, light, dmx):
        mode_byte = dmx[0]
        bri = dmx_to_pct(dmx[1])

        # -- Blackout / power off --
        if mode_byte >= 128 or (mode_byte == 0 and dmx[1] == 0):
            if light.power_on:
                await light.send(
                    neewer.build_power(light.proto, light.mac_bytes, on=False))
                light.power_on = False
                light.current_mode = "off"
                if self.verbose:
                    print(f"  {light.name}: OFF")
            return

        # -- Ensure power on --
        if not light.power_on:
            await light.send(
                neewer.build_power(light.proto, light.mac_bytes, on=True))
            light.power_on = True
            await asyncio.sleep(0.02)

        # -- CCT mode (mode byte 0-31) --
        if mode_byte <= 31:
            temp = dmx_to_cct_k(dmx[2])
            gm = dmx_to_gm(dmx[3])
            pkt = neewer.build_cct(light.proto, light.mac_bytes, bri, temp, gm)
            await light.send(pkt)
            light.current_mode = "cct"
            light.current_effect = None
            if self.verbose:
                print(f"  {light.name}: CCT bri={bri}% temp={temp}K gm={gm}")

        # -- HSI mode (mode byte 32-63) --
        elif mode_byte <= 63:
            hue = dmx_to_hue(dmx[2])
            sat = dmx_to_pct(dmx[3])
            pkt = neewer.build_hsi(light.proto, light.mac_bytes, hue, sat, bri)
            await light.send(pkt)
            light.current_mode = "hsi"
            light.current_effect = None
            if self.verbose:
                print(f"  {light.name}: HSI hue={hue} sat={sat}% bri={bri}%")

        # -- FX mode (mode byte 64-95) --
        elif mode_byte <= 95:
            effect_id = dmx_to_effect(dmx[2])
            speed = dmx_to_speed(dmx[3])

            if light.current_mode == "fx" and light.current_effect == effect_id:
                # Same effect — just resend to update brightness/speed
                pkt = neewer.build_scene(
                    light.proto, light.mac_bytes, effect_id, bri, speed)
                await light.send(pkt)
            else:
                # New effect — power cycle required
                await light.send(
                    neewer.build_power(light.proto, light.mac_bytes, on=False))
                await asyncio.sleep(0.05)
                await light.send(
                    neewer.build_power(light.proto, light.mac_bytes, on=True))
                await asyncio.sleep(0.05)
                pkt = neewer.build_scene(
                    light.proto, light.mac_bytes, effect_id, bri, speed)
                await light.send(pkt)
                light.power_on = True

            light.current_mode = "fx"
            light.current_effect = effect_id
            if self.verbose:
                ename = next(
                    (k for k, v in neewer.EFFECTS.items() if v == effect_id),
                    f"#{effect_id}")
                print(f"  {light.name}: FX {ename} bri={bri}% speed={speed}")

    # -- Main loop --

    async def bridge_loop(self):
        connected = sum(1 for l in self.lights if l.connected)
        print(f"\nBridge running: universe {self.universe}, "
              f"{connected}/{len(self.lights)} light(s) connected")
        self._print_channel_map()
        print("\nWaiting for sACN data... (Ctrl+C to stop)\n")

        reconnect_timer = 0.0
        status_timer = 0.0

        while self.running:
            now = time.monotonic()

            # Periodic reconnect (every 10s)
            if now - reconnect_timer > 10.0:
                for light in self.lights:
                    if not light.connected:
                        print(f"  Reconnecting {light.name}...", file=sys.stderr)
                        await light.connect()
                reconnect_timer = now

            # Periodic status (every 30s)
            if now - status_timer > 30.0 and self.frame_count > 0:
                connected = sum(1 for l in self.lights if l.connected)
                print(f"  [{self.frame_count} frames received, "
                      f"{connected}/{len(self.lights)} connected]")
                status_timer = now

            # Get latest DMX snapshot
            with self.dmx_lock:
                dmx_snapshot = self.latest_dmx

            if dmx_snapshot is not None:
                for light in self.lights:
                    if not light.connected:
                        continue

                    dmx = self._get_light_dmx(light)
                    if dmx is None:
                        continue

                    # Skip if unchanged
                    if dmx == light.last_dmx:
                        continue

                    # Rate limit per light
                    if now - light.last_send_time < MIN_SEND_INTERVAL:
                        continue

                    await self._send_dmx_to_light(light, dmx)
                    light.last_dmx = dmx

            await asyncio.sleep(self.poll_interval)

    def _print_channel_map(self):
        print("\n  DMX Channel Map:")
        print(f"  {'Light':<30s} {'Channels':<15s} {'Protocol':<10s}")
        print(f"  {'-'*30} {'-'*15} {'-'*10}")
        for light in self.lights:
            ch_start = light.start_channel
            ch_end = ch_start + CHANNELS_PER_LIGHT - 1
            proto = light.proto or "?"
            status = "" if light.connected else " (disconnected)"
            print(f"  {light.name:<30s} {ch_start:>3d}-{ch_end:<3d}        "
                  f"{proto:<10s}{status}")
        print()
        print("  Per-light channels (10 per fixture):")
        print("    +0  Mode        0-31=CCT  32-63=HSI  64-95=FX  128+=Off")
        print("    +1  Dimmer      0-255 brightness")
        print("    +2  Param A     CCT: temp | HSI: hue | FX: effect")
        print("    +3  Param B     CCT: G/M  | HSI: sat | FX: speed")
        print("    +4  FX sub 1    (effect-specific)")
        print("    +5  FX sub 2    (effect-specific)")
        print("    +6  FX sub 3    (effect-specific)")
        print("    +7  FX sub 4    (effect-specific)")
        print("    +8  FX sub 5    (effect-specific)")
        print("    +9  FX sub 6    (effect-specific)")

    # -- Entry point --

    async def run(self, start_channel=1, timeout=5.0):
        if not await self.scan_and_setup(start_channel, timeout):
            return

        await self.connect_all()

        connected = sum(1 for l in self.lights if l.connected)
        if connected == 0:
            print("No lights connected. Exiting.")
            return

        # Start sACN receiver
        self.receiver = sacn.sACNreceiver()
        self.receiver.register_listener(
            'universe', self._on_dmx, universe=self.universe)
        self.receiver.start()
        print(f"sACN receiver listening on universe {self.universe}")

        self.running = True
        try:
            await self.bridge_loop()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.running = False
            if self.receiver:
                self.receiver.stop()
            for light in self.lights:
                await light.disconnect()
            print("Bridge stopped.")


# -- CLI ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Neewer sACN (E1.31) Bridge — BLE lights as DMX fixtures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Channel layout (10 per light, matching Neewer DMX specs):
  +0 Mode      0-31=CCT, 32-63=HSI, 64-95=FX, 128+=Off
  +1 Dimmer    0-255 (brightness)
  +2 Param A   CCT: color temp | HSI: hue | FX: effect number
  +3 Param B   CCT: G/M tint   | HSI: saturation | FX: speed

Examples:
  %(prog)s                           # auto-scan, universe 1, start ch 1
  %(prog)s -u 2 -s 11               # universe 2, first light at ch 11
  %(prog)s --fps 30 --verbose        # 30Hz update rate with debug output
""")
    parser.add_argument("--universe", "-u", type=int, default=1,
                        help="sACN universe (default: 1)")
    parser.add_argument("--start-channel", "-s", type=int, default=1,
                        help="DMX start address for first light (default: 1)")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"bridge update rate in Hz (default: {DEFAULT_FPS})")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="BLE scan timeout in seconds (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print every DMX→BLE translation")
    parser.add_argument("--list-channels", action="store_true",
                        help="scan, print channel map, and exit")
    args = parser.parse_args()

    bridge = NeewerSACNBridge(universe=args.universe, fps=args.fps)
    bridge.verbose = args.verbose

    if args.list_channels:
        async def list_only():
            if await bridge.scan_and_setup(args.start_channel, args.timeout):
                bridge._print_channel_map()
        asyncio.run(list_only())
    else:
        asyncio.run(bridge.run(
            start_channel=args.start_channel, timeout=args.timeout))


if __name__ == "__main__":
    main()
