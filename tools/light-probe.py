#!/usr/bin/env python3
"""Find out how Galaxy Buds3 Pro report and switch their blade lights.

No open client documents the command that switches the lights, so this asks
the earbuds directly, in two modes:

  --watch SECONDS   send nothing; log every frame. For each extended status
                    (msg 97) print byte 50, the lighting byte, with placement
                    and battery; print every msg 142 (BUDS_LIGHTING_SYNC).
                    Pinch and hold both earbuds (out of the case, not worn) to
                    turn the lights on and off while it runs.
  --scan 223,224    send each candidate id (unnamed ids next to 222, never a
                    reset/debug/firmware id) each --values payload in turn and
                    diff every settings frame against the start, so a setter
                    shows up even when nothing lights.
  --find SECONDS    Find My Earbuds for SECONDS, then stop (they beep; Samsung
                    says the blade lights come on too). A known light event.
                    Add --mute to mute both buds (--mute-after S to wait S seconds
                    first), or --wearing to use "ring while wearing" (166).
  --pulse ON,OFF,N  N short Find My Earbuds sessions, ON ms each with OFF ms between.
                    The lights come on at once and the beep only ramps in after
                    about 3 s, so short sessions light the blades silently.
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
MSG_FIND_START = 160         # FIND_MY_EARBUDS_START: beeps, and Samsung says the blade lights come on
MSG_FIND_STOP = 161
MSG_MUTE_EARBUD = 162        # [left, right], 1 = muted; Find My Earbuds' per-bud mute
MSG_FIND_WEARING = 166       # FIND_MY_EARBUDS_ON_WEARING_START ("ring while wearing")
LIGHTING_OFFSET = 50         # LightingControl in the Buds3 Pro extended status
PROFILE_PATH = "/omarchy/galaxybuds_lightprobe"
ALLOWED_PAYLOADS = (0, 1, 2, 3)
# --scan only ever sends to these: unnamed ids next to UASC_SIREN_DETECT (222),
# the Buds3 Pro setting that sits beside LightingControl in the status.
SCAN_CANDIDATES = (220, 221) + tuple(range(223, 233))
# Never sent, whatever the arguments: reset, reboot, power off, RF test,
# hidden factory/debug modes, firmware transfer, and the other write/test ids.
FORBIDDEN = {18, 19, 21, 22, 23, 32, 75, 80, 82, 83, 86, 141, 170, 171, 172, 207} | set(range(176, 191))


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
        self.baseline = None
        self.scan = []
        self.find_seconds = int(arg("--find", 0))
        spec = arg("--pulse", "")
        self.pulse_spec = tuple(int(x) for x in spec.split(",")) if spec else None
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
            if self.baseline is None:
                self.baseline = payload
            else:
                diff = [f"{i}:{self.baseline[i]:02x}->{payload[i]:02x}"
                        for i in range(min(len(payload), len(self.baseline))) if payload[i] != self.baseline[i]
                        and i not in (2, 3, 7)]          # battery bytes move on their own
                if diff:
                    log(f"   SETTINGS CHANGED vs start: {' '.join(diff)}")
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

    def send_scan(self, msg_id, value):
        if msg_id in FORBIDDEN or msg_id not in SCAN_CANDIDATES or value not in ALLOWED_PAYLOADS:
            raise SystemExit(f"refusing msg {msg_id} payload {value}")
        log(f"-> {msg_id} (0x{msg_id:02x})  payload={value:02x}      (watch the LEDs now)")
        self.socket.sendall(buds.encode(msg_id, bytes([value])))

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

    def find(self, seconds):
        start = MSG_FIND_WEARING if "--wearing" in sys.argv else MSG_FIND_START
        log(f"-> {start} FIND START      (the earbuds may beep; watch the LEDs)")
        self.socket.sendall(buds.encode(start))

        def mute():
            log(f"-> {MSG_MUTE_EARBUD} MUTE_EARBUD  payload=01 01   (both muted: lights only?)")
            self.socket.sendall(buds.encode(MSG_MUTE_EARBUD, bytes([1, 1])))
            return False
        if "--mute" in sys.argv:
            delay = float(arg("--mute-after", 0))
            if delay:
                self.GLib.timeout_add(int(delay * 1000), mute)
            else:
                mute()

        def stop():
            log(f"-> {MSG_FIND_STOP} FIND_MY_EARBUDS_STOP")
            self.socket.sendall(buds.encode(MSG_FIND_STOP))
            if "--mute" in sys.argv:
                log(f"-> {MSG_MUTE_EARBUD} MUTE_EARBUD  payload=00 00   (restore)")
                self.socket.sendall(buds.encode(MSG_MUTE_EARBUD, bytes([0, 0])))
            self.GLib.timeout_add_seconds(3, self.finish)
            return False
        self.GLib.timeout_add_seconds(seconds, stop)
        return False

    def pulse(self, on_ms, off_ms, count):
        """Short Find My Earbuds sessions: the lights come on at once, the beep
        only ramps in after ~3 s, so sessions shorter than that stay silent."""
        state = {"left": count}

        def on():
            if state["left"] <= 0:
                self.GLib.timeout_add_seconds(2, self.finish)
                return False
            state["left"] -= 1
            self.socket.sendall(buds.encode(MSG_FIND_START))
            self.GLib.timeout_add(on_ms, off)
            return False

        def off():
            self.socket.sendall(buds.encode(MSG_FIND_STOP))
            self.GLib.timeout_add(off_ms, on)
            return False
        log(f"pulse: {count} x ({on_ms} ms on, {off_ms} ms off)")
        on()
        return False

    def next_payload(self):
        if self.pulse_spec:
            return self.pulse(*self.pulse_spec)
        if self.find_seconds:
            return self.find(self.find_seconds)
        if self.scan:
            self.send_scan(*self.scan.pop(0))
            self.GLib.timeout_add_seconds(self.gap, self.next_payload)
            return False
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
    modes = {"--watch", "--probe", "--scan", "--find", "--pulse"}
    if "-h" in sys.argv or "--help" in sys.argv or not modes & set(sys.argv):
        print(__doc__.strip())
        raise SystemExit(0)
    address = arg("--address", os.environ.get("GALAXY_BUDS_ADDRESS", "E4:92:82:EF:D5:AB"))
    watch = int(arg("--watch", 0))
    scan = []
    if "--scan" in sys.argv:
        # "--scan 220,221 --values 1,0": each id gets each value in turn.
        ids = [int(x) for x in arg("--scan", "").split(",") if x]
        values = [int(x) for x in arg("--values", "1,0").split(",") if x]
        scan = [(i, v) for i in ids for v in values]
    payloads = [int(x) for x in arg("--probe", "").split(",") if x != ""] if not watch else []
    probe = Probe(address, watch, payloads, int(arg("--gap", 8)), int(arg("--settle", 3)))
    for msg_id, value in scan:
        if msg_id in FORBIDDEN or msg_id not in SCAN_CANDIDATES or value not in ALLOWED_PAYLOADS:
            raise SystemExit(f"refusing msg {msg_id} payload {value}; candidates are {SCAN_CANDIDATES}")
    probe.scan = scan
    raise SystemExit(probe.run())
