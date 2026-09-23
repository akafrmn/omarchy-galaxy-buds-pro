# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[2.2.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.2.0
[2.1.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.1.1
[2.1.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.1.0
[2.0.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.1
[2.0.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.0
