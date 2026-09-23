# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[2.0.1]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.1
[2.0.0]: https://github.com/akafrmn/omarchy-galaxy-buds-pro/releases/tag/v2.0.0
