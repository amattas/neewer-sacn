#!/usr/bin/env python3
"""Probe unknown BLE command TAGs on Neewer Infinity-protocol lights.

Sends commands with various TAG values and monitors the notify characteristic
for responses. Used to discover undocumented commands like channel assignment
and master/slave pairing.

Usage:
  python probe_tags.py                      # scan, probe all unknown TAGs
  python probe_tags.py --light 0            # probe specific light by index
  python probe_tags.py --range 0x92 0x9F    # probe specific TAG range
  python probe_tags.py --subtags            # also vary subtag byte
"""

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

import neewer

# TAGs we already know (don't probe these)
KNOWN_TAGS = {
    0x8D,  # Power
    0x8E,  # Power query
    0x8F,  # HSI
    0x90,  # CCT
    0x91,  # Scene
    0x95,  # HW info query
    0x96,  # Channel query
    0x9E,  # Device info query
}

# Legacy TAGs (also known)
KNOWN_LEGACY = {0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8B}


async def probe_light(address, name, tag_range, try_subtags=False, try_params=False):
    """Connect to a light and probe unknown TAGs."""
    print(f"\nConnecting to {name} ({address})...")

    client = BleakClient(address, timeout=10.0)
    await client.connect()

    # Resolve protocol and MAC
    proto = neewer.detect_protocol(name)
    import platform
    if platform.system() == "Darwin":
        mac_str = await neewer._resolve_mac_from_profiler(name)
        mac_bytes = neewer.parse_mac(mac_str) if mac_str else [0] * 6
    else:
        mac_bytes = neewer.parse_mac(address)

    print(f"  Protocol: {proto}, MAC: {':'.join(f'{b:02X}' for b in mac_bytes)}")

    # Set up notification handler
    responses = []
    fragments = bytearray()

    def on_notify(sender, data):
        nonlocal fragments
        # Handle fragmentation
        if fragments:
            fragments.extend(data)
            if len(fragments) >= 3:
                expected = fragments[2] + 4
                if len(fragments) >= expected:
                    responses.append(bytes(fragments))
                    fragments = bytearray()
            return
        if len(data) >= 3 and data[0] == 0x78:
            expected = data[2] + 4
            if len(data) < expected:
                fragments.extend(data)
                return
        responses.append(bytes(data))

    await client.start_notify(neewer.NOTIFY_UUID, on_notify)
    await asyncio.sleep(0.5)

    # Drain any initial unsolicited notifications
    initial = list(responses)
    if initial:
        print(f"  Unsolicited on connect: {len(initial)} notification(s)")
        for r in initial:
            print(f"    RX: {neewer.fmt_hex(r)}")
    responses.clear()

    # Probe TAGs
    tag_start, tag_end = tag_range
    found = []

    print(f"\n  Probing TAGs 0x{tag_start:02X}-0x{tag_end:02X}...")
    print(f"  {'TAG':<8s} {'Sent':<45s} {'Response'}")
    print(f"  {'-'*8} {'-'*45} {'-'*40}")

    for tag in range(tag_start, tag_end + 1):
        if tag in KNOWN_TAGS or tag in KNOWN_LEGACY:
            continue

        subtags_to_try = [0x00]
        if try_subtags:
            # Also try the tag itself as subtag, and common subtags
            subtags_to_try = [0x00, tag & 0xFF, 0x01, 0x02, 0x84]

        for subtag in subtags_to_try:
            params_list = [[]]
            if try_params:
                # Try with common param patterns
                params_list = [[], [0x00], [0x01], [0x01, 0x01], [0x01, 0x00]]

            for params in params_list:
                responses.clear()

                # Build and send probe command
                pkt = neewer.infinity_cmd(tag, mac_bytes, subtag, params)
                await client.write_gatt_char(neewer.WRITE_UUID, pkt, response=False)
                await asyncio.sleep(0.3)

                sent_hex = neewer.fmt_hex(pkt)
                tag_label = f"0x{tag:02X}"
                if subtag != 0x00:
                    tag_label += f"/0x{subtag:02X}"
                if params:
                    tag_label += f" p={params}"

                if responses:
                    for resp in responses:
                        resp_hex = neewer.fmt_hex(resp)
                        # Check if it's a "unsupported" response (0x7F)
                        is_7f = len(resp) >= 2 and resp[1] == 0x7F
                        marker = "  (unsupported)" if is_7f else " *** VALID ***"
                        print(f"  {tag_label:<8s} {sent_hex:<45s} {resp_hex}{marker}")
                        if not is_7f:
                            found.append((tag, subtag, params, resp))
                else:
                    print(f"  {tag_label:<8s} {sent_hex:<45s} (no response)")

    await client.stop_notify(neewer.NOTIFY_UUID)
    await client.disconnect()

    # Summary
    print(f"\n{'='*60}")
    if found:
        print(f"DISCOVERED {len(found)} valid response(s):")
        for tag, subtag, params, resp in found:
            print(f"  TAG 0x{tag:02X} subtag 0x{subtag:02X} params={params}")
            print(f"    Response: {neewer.fmt_hex(resp)}")
    else:
        print("No new valid TAGs found in this range.")
    print(f"{'='*60}")

    return found


async def main():
    parser = argparse.ArgumentParser(
        description="Probe unknown BLE TAGs on Neewer Infinity lights")
    parser.add_argument("--light", "-l", default="0",
                        help="light index or name (default: 0)")
    parser.add_argument("--range", "-r", nargs=2, default=["0x80", "0xAF"],
                        help="TAG range to probe (hex, default: 0x80 0xAF)")
    parser.add_argument("--subtags", action="store_true",
                        help="also vary the subtag byte")
    parser.add_argument("--params", action="store_true",
                        help="also try common param patterns")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="BLE scan timeout (default: 5)")
    args = parser.parse_args()

    tag_start = int(args.range[0], 0)
    tag_end = int(args.range[1], 0)

    # Scan
    neewer._load_cache()
    lights = await neewer.scan_lights(timeout=args.timeout)
    if not lights:
        print("No lights found.")
        return

    # Resolve light
    try:
        idx = int(args.light)
        if idx >= len(lights):
            print(f"Light index {idx} out of range (found {len(lights)} lights)")
            return
        device, adv = lights[idx]
    except ValueError:
        # Match by name
        for device, adv in lights:
            dname = device.name or adv.local_name or ""
            if args.light.lower() in dname.lower():
                break
        else:
            print(f"No light matching '{args.light}'")
            return

    name = device.name or adv.local_name or device.address
    await probe_light(
        device.address, name, (tag_start, tag_end),
        try_subtags=args.subtags, try_params=args.params)


if __name__ == "__main__":
    asyncio.run(main())
