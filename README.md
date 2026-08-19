# Galaxy Buds — Omarchy plugin

Noise control for Samsung Galaxy Buds in the Omarchy bar. Click the ear icon to
switch between **off**, **ANC** and **ambient sound**, see the battery of each
earbud, and toggle **360 Audio**, **touch controls** and **quick connect**.

The icon follows the earbuds, not the other way around: change the mode by
touching an earbud or from your phone and the bar updates immediately.

## Install

```bash
git clone https://github.com/aislandener/galaxy-buds-control.git
ln -s "$PWD/galaxy-buds-control" ~/.config/omarchy/plugins/aislandener.galaxy-buds
omarchy-shell shell rescanPlugins
omarchy plugin enable aislandener.galaxy-buds
```

The earbuds must already be paired. Nothing else to configure — the model is
detected from the Bluetooth device id.

## Keybinds

The plugin answers on its own IPC target, so a Hyprland bind can drive it
without opening the popover:

```
bind = SUPER SHIFT, A, exec, omarchy-shell aislandener.galaxy-buds cycle
bind = SUPER SHIFT, N, exec, omarchy-shell aislandener.galaxy-buds set anc
```

`cycle`, `set <off|anc|ambient>`, `open`, `close`, `toggle` and `status` are
available. Never call `bin/galaxy-buds` directly for this — see below.

## How it works

`bin/galaxy-buds` speaks Samsung's SPP protocol over an RFCOMM socket that
BlueZ hands over through the Profile1 API — the same path GalaxyBudsClient
takes on Linux. It prints the earbud state as JSON lines and takes commands as
JSON lines on stdin.

The plugin runs it from `Service.qml`, which the shell mounts once per session,
and every bar reads that one object. Bar widgets are mounted once per monitor,
so owning the process in the widget would start one helper per screen.

**Only one program can hold that connection.** Opening the GalaxyBudsClient GUI
while the widget is running will take the link away from one of the two, and
running a second copy of the helper by hand does the same. Drive the plugin
through its IPC target instead.

Uses the system Python (`/usr/bin/python3`) for `dbus-python` and `PyGObject`.
No extra packages, no daemon to install, no root.

## Models

Tested on **Galaxy Buds2 Pro**. The framing, the commands and the battery
messages are shared across Buds Pro, Buds2, Buds2 Pro, Buds FE, Buds3 and
Buds3 Pro; what differs per model lives in the `PROFILES` table in
`bin/galaxy-buds`: where 360 Audio sits in the status message, whether the
model has an adaptive noise mode, and the shape of the touch-lock message.

An unknown model still gets noise control and battery, and hides the 360 Audio
toggle rather than showing a value read from the wrong byte. Buds (original),
Buds+ and Buds Live are out of scope: their ANC is a plain on/off and their
framing differs.

## Tests

```bash
/usr/bin/python3 tests/test_protocol.py
```

Framing, CRC, status parsing and command encoding, all without earbuds.
