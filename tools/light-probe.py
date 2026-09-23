#!/usr/bin/env python3
"""Find out how Galaxy Buds3 Pro report and switch their blade lights.

No open client documents the command that switches the lights, so this asks
the earbuds directly, in two modes:

  --watch SECONDS   send nothing; log every frame. For each extended status
                    (msg 97) print byte 50, the lighting byte, with placement
                    and battery; print every msg 142 (BUDS_LIGHTING_SYNC).
                    Pinch and hold both earbuds (out of the case, not worn) to
                    turn the lights on and off while it runs.
  --probe 1,0       send ONLY msg 142 with each single-byte payload in turn,
                    waiting --gap seconds between them so you can watch the
                    LEDs. Payloads are limited to 0-3; no other message id is
                    ever sent.

The plugin's helper holds the single SPP link, so stop it first:

    omarchy plugin disable io.github.akafrmn.galaxy-buds-pro
    python3 tools/light-probe.py --watch 90
    omarchy plugin enable  io.github.akafrmn.galaxy-buds-pro --section right

Usage: light-probe.py [--address AA:BB:CC:DD:EE:FF]
                      (--watch SECONDS [--until-events N] | --probe 1,0 [--gap 8] [--settle 3])
"""

import importlib.machinery
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The helper has no .py suffix, so load it by path and reuse its framing/CRC.
_spec = importlib.util.spec_from_loader(
    "budshelper", importlib.machinery.SourceFileLoader("budshelper", os.path.join(REPO, "bin", "galaxy-buds")))
buds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buds)

MSG_LIGHTING_SYNC = 142      # BUDS_LIGHTING_SYNC, per GalaxyBudsClient's message list
LIGHTING_OFFSET = 50         # LightingControl in the Buds3 Pro extended status
PROFILE_PATH = "/omarchy/galaxybuds_lightprobe"
ALLOWED_PAYLOADS = (0, 1, 2, 3)


def arg(name, fallback):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else fallback


def log(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


class Probe:
    def __init__(self, address, watch, payloads, gap, settle):
        self.address, self.watch, self.payloads = address, watch, payloads
        self.gap, self.settle = gap, settle
        self.socket = None
        self.buffer = b""
        self.last_lighting = None
        self.events = 0
        self.until = int(arg("--until-events", 0))
        from gi.repository import GLib
        self.GLib = GLib
        self.loop = GLib.MainLoop()

    # ---- wire ----------------------------------------------------------
    def on_readable(self, *_):
        try:
            chunk = self.socket.recv(4096)
        except OSError:
            log("link error")
            self.loop.quit()
            return False
        if not chunk:
            log("link closed by the earbuds")
            self.loop.quit()
            return False
        self.buffer += chunk
        messages, self.buffer = buds.decode(self.buffer)
        for msg_id, payload in messages:
            self.show(msg_id, bytes(payload))
        return True

    def show(self, msg_id, payload):
        if msg_id == buds.MSG_EXTENDED_STATUS:
            lighting = payload[LIGHTING_OFFSET] if len(payload) > LIGHTING_OFFSET else None
            worn = buds.parse_placement(payload[6], "nibbles") if len(payload) > 6 else {}
            changed = self.last_lighting is not None and lighting != self.last_lighting
            mark = "  <== CHANGED" if changed else ""
            if changed:
                self.lighting_event()
            self.last_lighting = lighting
            log(f"<- 97 extended status  byte50={lighting}  placement={worn}  "
                f"battery L{payload[2]} R{payload[3]}  rev={payload[0]}{mark}")
            log(f"   bytes 44..56: {payload[44:57].hex(' ')}")
        elif msg_id == MSG_LIGHTING_SYNC:
            log(f"<- 142 LIGHTING_SYNC  payload={payload.hex(' ') or '(empty)'}   <== lighting")
            self.seen_sync = getattr(self, "seen_sync", 0) + 1
            if self.seen_sync > 1:      # the first one is the report on connect
                self.lighting_event()
        elif msg_id == buds.MSG_STATUS:
            log(f"<- 96 status  placement={buds.parse_placement(payload[5], 'nibbles')}  "
                f"battery L{payload[1]} R{payload[2]}")
        elif msg_id == buds.MSG_ACK:
            log(f"<- ACK  payload={payload.hex(' ')}")
        else:
            log(f"<- msg {msg_id} (0x{msg_id:02x})  payload={payload[:48].hex(' ')}"
                + (" ..." if len(payload) > 48 else ""))

    def lighting_event(self):
        self.events += 1
        if self.until and self.events >= self.until:
            log(f"saw {self.events} lighting changes; stopping early")
            self.GLib.timeout_add_seconds(3, self.finish)

    def send_lighting(self, value):
        if value not in ALLOWED_PAYLOADS:
            raise SystemExit(f"refusing payload {value}: only {ALLOWED_PAYLOADS} are allowed")
        log(f"-> 142 LIGHTING_SYNC  payload={value:02x}      (watch the LEDs now)")
        self.socket.sendall(buds.encode(MSG_LIGHTING_SYNC, bytes([value])))

    # ---- run -----------------------------------------------------------
    def on_new_connection(self, fd):
        import socket
        GLib = self.GLib
        self.socket = socket.socket(fileno=fd)
        GLib.io_add_watch(self.socket.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                          self.on_readable)
        log("SPP connected")
        if self.watch:
            log(f"watching for {self.watch} s; nothing will be sent")
            GLib.timeout_add_seconds(self.watch, self.finish)
        else:
            GLib.timeout_add_seconds(self.settle, self.next_payload)

    def next_payload(self):
        if not self.payloads:
            self.GLib.timeout_add_seconds(self.gap, self.finish)
            return False
        self.send_lighting(self.payloads.pop(0))
        self.GLib.timeout_add_seconds(self.gap, self.next_payload)
        return False

    def finish(self):
        log("done")
        self.loop.quit()
        return False

    def run(self):
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        GLib = self.GLib
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        probe = self

        class BluezProfile(dbus.service.Object):
            @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
            def Release(self):
                pass

            @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
            def NewConnection(self, path, fd, properties):
                probe.on_new_connection(fd.take())

            @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
            def RequestDisconnection(self, path):
                pass

        BluezProfile(bus, PROFILE_PATH)
        manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
        path = "/org/bluez/hci0/dev_" + self.address.upper().replace(":", "_")
        device = dbus.Interface(bus.get_object("org.bluez", path), "org.bluez.Device1")
        props = dbus.Interface(bus.get_object("org.bluez", path), "org.freedesktop.DBus.Properties")
        uuids = [str(u).lower() for u in props.Get("org.bluez.Device1", "UUIDs")]
        name = str(props.Get("org.bluez.Device1", "Alias"))
        profile = buds.profile_for(uuids, name)
        log(f"device {name} ({self.address}), model {profile['name']}")
        if profile["name"] != "buds3pro" and not self.watch:
            log("only Galaxy Buds3 Pro have blade lights; refusing to probe another model")
            return 1

        try:
            manager.UnregisterProfile(PROFILE_PATH)
        except dbus.DBusException:
            pass
        try:
            manager.RegisterProfile(PROFILE_PATH, profile["uuid"],
                                    {"Role": "client", "Service": profile["uuid"], "Name": "light-probe"})
        except dbus.DBusException as error:
            log(f"RegisterProfile failed: {error} -- disable the plugin first")
            return 1
        device.ConnectProfile(profile["uuid"], reply_handler=lambda: None,
                              error_handler=lambda e: log(f"ConnectProfile: {e}"))
        GLib.timeout_add_seconds(20, lambda: (log("no SPP link after 20 s"), self.loop.quit())[0]
                                 if self.socket is None else False)
        self.loop.run()
        return 0


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv or ("--watch" not in sys.argv and "--probe" not in sys.argv):
        print(__doc__.strip())
        raise SystemExit(0)
    address = arg("--address", os.environ.get("GALAXY_BUDS_ADDRESS", "E4:92:82:EF:D5:AB"))
    watch = int(arg("--watch", 0))
    payloads = [int(x) for x in arg("--probe", "").split(",") if x != ""] if not watch else []
    raise SystemExit(Probe(address, watch, payloads, int(arg("--gap", 8)), int(arg("--settle", 3))).run())
