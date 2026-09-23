# Contributing

Thanks for helping. The most valuable contribution right now is a
**compatibility report** from anyone with a Buds Pro, Buds2 Pro or Buds4 Pro,
because only Buds3 Pro is verified by the maintainer. Use the
[compatibility template](https://github.com/akafrmn/omarchy-galaxy-buds-pro/issues/new?template=compatibility.yml).

## Layout

| Path | What |
|---|---|
| `manifest.json` | Omarchy plugin manifest (id, kinds, settings schema) |
| `Service.qml` | Mounted once per session: runs the helper, low battery warning, IPC |
| `Panel.qml` | The bar widget and popover, once per monitor; reads the service |
| `bin/galaxy-buds` | Python helper: Samsung SPP over RFCOMM via BlueZ Profile1, JSON lines in and out |
| `tests/test_protocol.py` | Protocol tests, no earbuds needed |
| `tests/check_manifest.py` | Mirrors `omarchy plugin validate`, plus id/credit consistency |
| `tests/check_qml.py` | Catches a property or handler bound twice, which qmllint misses but the shell refuses to load |
| `tools/eq-probe.py` | Asks a pair whether it accepts equalizer messages |

## Dev loop

```bash
make check          # tests, manifest checks, validator (if Omarchy is installed), lint
make dev-install    # copy into ~/.config/omarchy/plugins/<id> and rescan
```

- `make dev-install` copies rather than symlinks, because the Omarchy
  validator rejects symlinks. If you installed with `omarchy plugin add`,
  either work in that checkout or remove it first.
- Check the shell log after every QML change:
  `journalctl --user -f | grep galaxy-buds-pro`. A widget that fails to load
  says so there and nowhere else. The engine caches components, so after a
  load error run `omarchy-restart-shell` before trusting the next result.
- Saving a QML file under the plugins folder hot-reloads it. The service is
  `keepLoaded`, so **changes to `Service.qml` or the helper need
  `omarchy-restart-shell`**.
- See what the earbuds send: stop the plugin
  (`omarchy plugin disable io.github.akafrmn.galaxy-buds-pro`), then run
  `GALAXY_BUDS_DEBUG=1 /usr/bin/python3 bin/galaxy-buds` and watch the `<<`
  lines on stderr. Only one program can hold the link, so the plugin, GalaxyBudsClient
  and other Buds plugins must be stopped.
- Control messages are ignored while a bud sits in the case (placement 3). Take
  them out before testing noise modes.

## Adding or fixing a model

Everything model-specific is one row in `PROFILES` in `bin/galaxy-buds`:

- `ids`: Samsung device ids (the tail of the `d908aab5-…` UUID the earbuds
  publish; see `bluetoothctl info`).
- `match`: name fragments, for models that publish no id. **Order matters**:
  put "Buds4 Pro" before "Buds4".
- `uuid`: SPP service (`SPP_NEW` from Buds2 on).
- `noise`, `touch`, `seamless`, `spatial`: where each field sits in the
  extended status message, as `(offset, since_revision)`.
- Quirk flags such as `noise_ack_receipt`.

- `fw_model`: the model name the firmware build list uses
  (`https://fw.timschneeberger.me/v3/firmware/<fw_model>`).

Firmware comes from msg 104 on connect: two prefix bytes, then the left and
right build as NUL-padded ASCII (`R630XXU0AZD2`). Never add flashing: see the
README FAQ.

Every row change needs a test in `tests/test_protocol.py`, ideally with a real
payload captured through `GALAXY_BUDS_DEBUG=1`.

GalaxyBudsClient is GPL-3.0 and this project is MIT. Read it for protocol
facts (offsets, ids, message numbers), but **do not copy its code**.

## Commits and pull requests

- [Conventional commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- One logical change per commit, and a `CHANGELOG.md` entry under `## [Unreleased]`.
- Signed commits are welcome but not required.
- Keep the plugin free of new dependencies. It should run on a stock Omarchy
  install with nothing extra.

## Releasing (maintainers)

1. Bump `version` in `manifest.json` and move the Unreleased entries to a new
   `CHANGELOG.md` heading. `make check` enforces that they match.
2. Commit, then `git tag -s vX.Y.Z -m vX.Y.Z && git push --follow-tags`.
3. `gh release create vX.Y.Z --notes-from-tag` or paste the changelog section.

Users get the update through `omarchy plugin update`, which fast-forwards the
default branch, so `main` must always be releasable.
