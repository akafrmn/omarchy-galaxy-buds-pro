# Galaxy Buds — Omarchy plugin

Noise control for Samsung Galaxy Buds in the Omarchy bar. Click the ear icon to
switch noise modes, see the battery of each earbud as a bar, and toggle
**360 Audio**, **touch controls** and **quick connect**.

The icon follows the earbuds, not the other way around: change the mode by
touching an earbud or from your phone and the bar updates immediately.

Controls the model does not have are hidden rather than shown dead — a Buds+
has no ANC and no 360 Audio, so it gets an ambient-sound switch and nothing
about spatial audio.

It also picks the **Bluetooth codec** (the A2DP profiles PipeWire offers for
that card), shows a bolt on whatever is charging, and — when two pairs are
connected at once — controls the pair sound is actually going to, saying so
when the pair on screen is not the audio output.

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

## Translating the labels

Every visible string is English by default and can be replaced from this
widget's entry in `~/.config/omarchy/shell.json`:

```json
{
  "id": "aislandener.galaxy-buds",
  "labels": {
    "noiseControl": "Controle de ruído",
    "settings": "Ajustes",
    "off": "Desligado",
    "ambient": "Som ambiente",
    "spatial": "Áudio 360",
    "touch": "Controles de toque",
    "seamless": "Conexão rápida",
    "case": "Estojo",
    "disconnected": "Desconectado. Tire os fones do estojo para reconectar."
  }
}
```

Every key is optional; anything you leave out keeps its English text.

| Key | Default |
|---|---|
| `noiseControl` | Noise control |
| `settings` | Settings |
| `off` / `anc` / `ambient` / `adaptive` | Off / ANC / Ambient / Adaptive |
| `codec` | Codec |
| `spatial` | 360 Audio |
| `touch` | Touch controls |
| `seamless` | Quick connect |
| `left` / `right` / `case` | L / R / Case |
| `notOutput` | Not the audio output |
| `disconnected` | Disconnected. Take them out of the case to reconnect. |
| `notPaired` | No Galaxy Buds paired. |
| `serviceOff` | The plugin service is not running. |

## Models

| Model | Noise control | 360 Audio | Touch | Quick connect | Charging |
|---|---|---|---|---|---|
| Buds (original) | ambient on/off | — | yes | — | — |
| Buds+ | ambient on/off | — | yes | firmware 11+ | — |
| Buds Live | ANC on/off | firmware 9+ | yes | yes | — |
| Buds Pro | off / ANC / ambient | firmware 2+ | yes | yes | — |
| Buds2, Buds2 Pro, Buds FE, Buds Core | off / ANC / ambient | most | yes | yes | yes |
| Buds3, Buds3 Pro, Buds3 FE | off / ANC / ambient | most | yes | yes | yes |

Battery is reported by every model; the case only reports its own charge while
the earbuds are sitting in it, so that bar comes and goes. Which earbud is
charging is only reported from Buds2 on — on older models that byte means
something else, so no bolt is shown rather than a guessed one.

The codec list comes from PipeWire, not from the earbuds, so it works the same
on every model. If you already run the `bt.codecs` plugin, this replaces it.

Tested on **Galaxy Buds2 Pro** and **Galaxy Buds+**. The rest come from the
protocol layout and have not been exercised on real hardware.

What differs per model lives in the `PROFILES` table in `bin/galaxy-buds`:
which service UUID to connect on (each generation uses a different one), which
command changes the noise mode, where each field sits in the status message,
and which firmware revision started reporting it. Adding a model is a row.

A model the table does not know still gets noise control and battery — those
bytes have not moved since Buds Live — and hides 360 Audio rather than reading
a byte that means something else on that firmware.

## Tests

```bash
/usr/bin/python3 tests/test_protocol.py
```

Framing, CRC, status parsing and command encoding, all without earbuds.
