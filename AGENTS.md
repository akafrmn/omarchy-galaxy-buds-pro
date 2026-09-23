# AGENTS.md

Omarchy shell plugin `io.github.akafrmn.galaxy-buds-pro`. See CONTRIBUTING.md for layout and the
dev loop.

- Run `make check` before every commit; commit per logical change with a conventional message.
- Model differences live only in `PROFILES` in `bin/galaxy-buds`; every row change gets a test.
- GalaxyBudsClient is GPL-3.0: use it for protocol facts, never copy code.
- After changing `Service.qml` or `bin/galaxy-buds`, `make dev-install && omarchy-restart-shell`
  to see it live; QML-only changes hot-reload.
- Keep the plugin dependency-free (system python, dbus-python, PyGObject only). Never write files
  or elevate.
