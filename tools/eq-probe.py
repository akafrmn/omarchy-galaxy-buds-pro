#!/usr/bin/env python3
"""Probe whether a Galaxy Buds Pro pair accepts the EQUALIZER message over SPP.

Neither this plugin's upstream, nor BudsLink, nor GalaxyBudsClient's
Buds3ProDeviceSpec lists an equalizer feature for Buds3 Pro, even though the
Galaxy Wearable app offers presets. So before building any EQ UI, ask the
earbuds directly: send EQUALIZER (0x86) with each preset index and watch what
comes back.

The earbuds accept control messages only while they are OUT of the case --
placement nibble 3 means "in case" and the firmware ignores changes there.

The plugin's own helper holds the single SPP link, so stop it first:

    omarchy plugin disable io.github.akafrmn.galaxy-buds-pro
    python3 tools/eq-probe.py
    omarchy plugin enable  io.github.akafrmn.galaxy-buds-pro --section right

Usage: eq-probe.py [--address AA:BB:CC:DD:EE:FF] [--msg 134] [--presets 0,1,2,3,4,5]
"""

import importlib.machinery
import importlib.util
import os
import sys
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The helper has no .py suffix, so load it by path and reuse its framing/CRC.
_spec = importlib.util.spec_from_loader(
    "budshelper", importlib.machinery.SourceFileLoader("budshelper", os.path.join(REPO, "bin", "galaxy-buds")))
buds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buds)

MSG_EQUALIZER = 134          # 0x86, per GalaxyBudsClient MsgIds
PROFILE_PATH = "/omarchy/galaxybuds_eqprobe"


def arg(name, fallback):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else fallback


class Probe:
    def __init__(self, address, msg_id, presets):
        self.address, self.msg_id, self.presets = address, msg_id, presets
        self.socket = None
        self.buffer = b""
        self.seen = []
        self.loop = GLib.MainLoop()

    # ---- wire ----------------------------------------------------------
    def on_readable(self, *_):
        try:
            chunk = self.socket.recv(4096)
        except OSError:
            return False
        if not chunk:
            return False
        self.buffer += chunk
        messages, self.buffer = buds.decode(self.buffer)
        for msg_id, payload in messages:
            self.seen.append((msg_id, bytes(payload)))
            if msg_id == buds.MSG_ACK:
                print(f"    <- ACK  payload={bytes(payload).hex(' ') or '(empty)'}")
            elif msg_id == self.msg_id:
                print(f"    <- EQ echo payload={bytes(payload).hex(' ')}")
            elif msg_id not in (buds.MSG_STATUS, buds.MSG_EXTENDED_STATUS):
                print(f"    <- msg {msg_id} (0x{msg_id:02x}) payload={bytes(payload).hex(' ')}")
        return True

    def send(self, msg_id, payload):
        self.socket.send(buds.encode(msg_id, payload))

    # ---- run -----------------------------------------------------------
    def on_new_connection(self, fd):
        import socket
        self.socket = socket.socket(fileno=fd)
        GLib.io_add_watch(self.socket.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                          self.on_readable)
        print("SPP connected.\n")
        GLib.timeout_add_seconds(1, self.run_presets)

    def run_presets(self):
        print(f"Sending EQUALIZER msg {self.msg_id} (0x{self.msg_id:02x}) with each preset.")
        print("Listen for a change in the audio as each one goes out.\n")
        for preset in self.presets:
            before = len(self.seen)
            print(f"  preset {preset}:")
            self.send(self.msg_id, bytes([preset]))
            deadline = time.time() + 2.0
            while time.time() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.02)
            if len(self.seen) == before:
                print("    <- (no reply)")
        self.report()
        self.loop.quit()
        return False

    def report(self):
        acks = [p for i, p in self.seen if i == buds.MSG_ACK]
        print("\n--- result ---")
        if not self.seen:
            print("No reply to any preset. The earbuds ignored msg "
                  f"{self.msg_id}: EQ is most likely not exposed over SPP on this model.")
        else:
            print(f"{len(acks)} ACK(s) across {len(self.presets)} presets.")
            print("If the sound changed, EQ works -- wire it into the buds3pro profile row.")
            print("If it did not, the earbuds ACKed an unknown id without acting on it.")

    def run(self):
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

        adapter = "/org/bluez/hci0/dev_" + self.address.upper().replace(":", "_")
        device = dbus.Interface(bus.get_object("org.bluez", adapter), "org.bluez.Device1")
        props = dbus.Interface(bus.get_object("org.bluez", adapter), "org.freedesktop.DBus.Properties")
        uuids = [str(u).lower() for u in props.Get("org.bluez.Device1", "UUIDs")]
        name = str(props.Get("org.bluez.Device1", "Alias"))
        profile = buds.profile_for(uuids, name)
        print(f"Device : {name} ({self.address})")
        print(f"Model  : {profile['name']}")

        try:
            manager.UnregisterProfile(PROFILE_PATH)
        except dbus.DBusException:
            pass
        try:
            manager.RegisterProfile(PROFILE_PATH, profile["uuid"],
                                    {"Role": "client", "Service": profile["uuid"], "Name": "eq-probe"})
        except dbus.DBusException as error:
            print(f"RegisterProfile failed: {error}\n"
                  "Another client holds the link -- disable the plugin first.")
            return 1

        device.ConnectProfile(profile["uuid"],
                              reply_handler=lambda: None,
                              error_handler=lambda e: print(f"ConnectProfile: {e}"))
        GLib.timeout_add_seconds(20, lambda: (print("Timed out waiting for the SPP link."), self.loop.quit())[0])
        self.loop.run()
        return 0


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__.strip())
        raise SystemExit(0)
    address = arg("--address", os.environ.get("GALAXY_BUDS_ADDRESS", "E4:92:82:EF:D5:AB"))
    msg = int(arg("--msg", MSG_EQUALIZER))
    presets = [int(x) for x in arg("--presets", "0,1,2,3,4,5").split(",")]
    raise SystemExit(Probe(address, msg, presets).run())
