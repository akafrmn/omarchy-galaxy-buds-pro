# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.6.0] - 2026-10-16

### Added
- Equalizer presets in the panel: a new Equalizer section, between Settings and Codec, with Off,
  Bass boost, Soft, Dynamic, Clear and Treble boost in two rows, reachable with the keyboard like
  the other chips. The preset is read from the extended status on connect and the panel follows
  the earbuds' acknowledgement. A custom curve set in Galaxy Wearable (value 6, captured on a
  Buds3 Pro; GalaxyBudsClient says 7) shows as `Equalizer · Custom`, and a value the plugin does
  not know lights no preset; picking a preset replaces either. Shown on Buds+ and every later
  model, hidden on the original Buds and unrecognised models. New IPC method `eq <preset>` and labels `eq`,
  `eqOff`, `eqBass`, `eqSoft`, `eqDynamic`, `eqClear`, `eqTreble`, `eqCustom`
  ([#3](https://github.com/akafrmn/omarchy-galaxy-buds-pro/issues/3)).
- **Find earbuds**: a new panel section (after Codec) rings the earbuds so you can find them,
  with per-bud mute toggles, a Stop button and a countdown
  ([#4](https://github.com/akafrmn/omarchy-galaxy-buds-pro/issues/4)). Safer than
  GalaxyBudsClient: a bud in your ear is muted the moment the search starts, and the search stops
  if the earbuds don't confirm that within 2 s; a bud that goes into your ear mid-search is muted
  too, best effort within about 1 s; it refuses to start with both buds in, or until the current
  connection has reported where the buds are; it stops by itself after 90 s and on Stop, panel
  close, helper exit (stdin closed or a signal), audio hand-over to another pair, firmware install
  start and when no bud is left that could ring, and forgets the search when the link drops.
  Never uses "ring while wearing" (166) and never echoes the earbuds' mute report. New IPC methods
  `find` and `findStop`; new labels `find`, `findRing`, `findStop`, `findWarning`, `findMuteLeft`,
  `findMuteRight`, `findWorn`, `findOffline`, `findAutoStop`, and for why a search was refused or
  stopped `findNotConnected`, `findUnsupported`, `findFirmware`, `findFirmwareStarted`,
  `findBothWorn`, `findUnknownPlacement`, `findNoneCanRing`, `findNoConfirm`, `findUnsafeUnmute`,
  `findTimeout`, `findBudsStopped`.

### Changed
- The helper forgets where the buds sit when the link drops or a new one comes up, until the
  earbuds report it again.

## [2.5.0] - 2026-10-16

### Added
- The panel shows the plugin version at the bottom right, on the firmware status line when the
  earbuds are connected, and whether it is the latest release:
  `v2.5.0 · ✓ latest`, or `↑ 2.6.0 available` in the warning colour, which opens the release
  notes when clicked. The helper asks GitHub for this plugin's latest release when the shell starts
  and at most every 12 hours, sending only the plugin version. New setting `updateCheck` (on by
  default) turns the lookup off; the version stays visible. New labels `pluginLatest`,
  `pluginAvailable`, `pluginChecking`.

## [2.4.1] - 2026-10-16

### Fixed
- The panel lost the earbuds for good after bluetoothd restarted (a crash, `systemctl restart
  bluetooth`, an upgrade) and stayed on "connect failed" until the shell was restarted. The helper
  now watches for BlueZ coming back, registers its profile with the new instance and reconnects
  within seconds; a connect that BlueZ rejects for an unknown profile also re-registers it
  ([#1](https://github.com/akafrmn/omarchy-galaxy-buds-pro/issues/1)).

## [2.4.0] - 2026-09-28

### Changed
- Firmware installs are limited to images pinned in the plugin source by build, size and SHA-256
  (`PINNED_FIRMWARE`): Buds Pro R190XXU0AVF1, Buds2 Pro R510XXU0AZD1 and Buds3 Pro R630XXU0AZG2.
  A downloaded image must match its pin byte for byte before anything is sent; any other build
  gets the update notice without an Install button (marketplace review). The pinned images and
  where they came from are listed in the README under Installable builds.
- The image download follows no redirects, only accepts `fw.timschneeberger.me`, stops reading
  past the pinned size, and has a 20 s connect timeout and a 5 minute overall deadline.

### Removed
- The `GALAXY_BUDS_FIRMWARE_DOWNLOAD_URL` override for the image download.

## [2.3.3] - 2026-09-28

### Removed
- `AGENTS.md` and `CLAUDE.md` from the repository root, so the installed plugin tree carries no
  coding-agent instruction files (marketplace review). Their contributor rules now live in
  CONTRIBUTING under Ground rules.

## [2.3.2] - 2026-09-24

### Changed
- README leads with firmware updates, with a three-step image (update found, installing, up to date)
  near the top, and gains a Roadmap: Buds3 Pro blade light control, firmware installs confirmed on
  every Pro model, equalizer presets.
- Manifest description mentions firmware updates first.

## [2.3.1] - 2026-09-24

### Fixed
- After a firmware install the earbuds repeat their result (`185 00 00`) on every connect until it
  is acknowledged; the helper now answers it, as Samsung's app does.
- `tools/eq-probe.py` could never connect: D-Bus object paths may not contain `-`.

### Added
- `tools/light-probe.py` (watch, scan, find, pulse modes) and a write-up in CONTRIBUTING of what the
  Buds3 Pro blade lights do and do not answer. Light control itself is not shipped yet.

### Changed
- New screenshots from a Buds3 Pro on the latest firmware.

## [2.3.0] - 2026-09-24

### Added
- Install firmware updates from the panel, without a phone or Galaxy Wearable: Install, confirm,
  progress, Cancel. Also `firmwareInstall <build>`, `firmwareCancel`, `firmwareDismiss` over IPC.
  Verified on a Galaxy Buds3 Pro: R630XXU0AZD2 to R630XXU0AZG2 in about 3 minutes.
- Enforced in the helper: only the offered build, upgrades only, same model, both buds connected on
  the same build, 30% battery each, not in the closed case. The image stays in memory and must pass
  header, size, per-segment CRC32, model name, and every embedded build string equal to the target.
  Nothing else is sent during a transfer; connection loss, 30 s of silence or Cancel abort it and the
  earbuds keep their firmware. Success is reported only once they return on the new build.

- Firmware status under the version: `✓ Latest version · checked hh:mm`, `Checking…` or
  `Couldn't check for updates`, so "no notice" never has to mean "up to date". A failed check is
  retried at the next connect or hourly tick instead of after 12 hours.
- Live install progress: Download / Send / Install / Restart steps, a smoothly animated bar with
  percent, MB sent and time left, and a sliding bar where the earbuds report no percentage.
  The download itself now reports progress.

### Changed
- The update notice no longer says to use Galaxy Wearable; `firmwareHow` label removed.

## [2.2.0] - 2026-09-24

### Added
- Firmware: the panel shows the build each bud runs (from msg 104, sent on connect) with its
  release month, and warns when the two buds run different builds.
- Firmware update check, on by default (`firmwareCheck`): one HTTPS request with the model name to
  the public build list at fw.timschneeberger.me, at most every 12 hours, TLS verified, silent on
  failure. Shows "Update available: <build> (<month>). Install it with Galaxy Wearable."
  The plugin does not flash firmware; the README explains why.
- Label keys `firmware`, `firmwareUpdate`, `firmwareHow`, `firmwareMismatch`.

## [2.1.1] - 2026-09-24

### Fixed
- Placement 4 (the case with its lid shut) was read as unknown, so a full bud that had stopped
  charging was not shown in the case and could count toward the low battery warning. Seen live on
  a Buds3 Pro when docking both buds.

### Changed
- `preview.png` is a real capture from a Buds3 Pro: one bud worn, one charging in the case.

## [2.1.0] - 2026-09-24

### Added
- Reads the "noise controls with one earbud" setting on Buds3, Buds3 Pro, Buds4 and Buds4 Pro
  (and Buds FE, Buds3 FE, Buds Core), and explains in the panel why ANC is refused with one bud
  worn. Label key: `ancOneBud`. Found live on a Buds3 Pro: the firmware acks ANC with "Off".

### Verified
- End to end on Galaxy Buds3 Pro hardware: model detection by device id, per-bud battery,
  placement, noise mode round-trip (acks read from the earbuds), codec row.

## [2.0.1] - 2026-09-24

### Fixed
- The bar widget failed to load ("Property value set multiple times"): two `onOpenedChanged`
  handlers in `Panel.qml`, inherited from upstream's latest commit. Merged into one.
- A JSON command that is not an object (`[]`, `null`) raised inside the stdin watch, which could
  end command handling for the session.

### Added
- `tests/check_qml.py`, run by `make check` and CI, catches duplicate QML bindings that qmllint
  accepts but the shell refuses to load.

## [2.0.0] - 2026-09-24

First release as `io.github.akafrmn.galaxy-buds-pro`, based on
[aislandener/galaxy-buds-control](https://github.com/aislandener/galaxy-buds-control) 1.0.0.

### Added
- Galaxy Buds4 Pro (SM-R640) and Buds4 (SM-R540) support.
- Low battery desktop notification (`lowBatteryWarning`, `lowBatteryThreshold`), sent once per
  session rather than once per monitor.
- Per-earbud `placement` in the helper's state (`wearing`, `idle`, `case`, `disconnected`).
- `inCase` label key.
- Tests for every Pro model's name and device-id resolution, and for the Buds4 quirks.
- CI, contribution guide, issue templates, security policy.

### Fixed
- A bud in the case, or one that dropped off the link, showed a red 0%. It now reads "In case"
  (with the charge when the case reports one) or "—".
- The low battery warning could fire for a disconnected bud reporting 0.
- Buds4 firmware acks a noise-mode change with 0; that no longer flips the panel to "Off".

### Changed
- Plugin id is now `io.github.akafrmn.galaxy-buds-pro`. Remove `aislandener.galaxy-buds` before
  installing: only one program can hold the earbuds' control link.

[2.6.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.6.0
[2.5.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.5.0
[2.4.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.4.1
[2.4.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.4.0
[2.3.3]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.3.3
[2.3.2]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.3.2
[2.3.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.3.1
[2.3.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.3.0
[2.2.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.2.0
[2.1.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.1.1
[2.1.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.1.0
[2.0.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.1
[2.0.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.0
