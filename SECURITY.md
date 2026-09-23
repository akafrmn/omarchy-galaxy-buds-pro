# Security policy

This plugin runs unsandboxed inside `omarchy-shell`. It talks to your earbuds over Bluetooth
and runs `pactl`. It never elevates privileges or writes files. Its only network access is the optional firmware
update check (one HTTPS GET of a public build list, model name only; `firmwareCheck: false` disables it).

## Reporting a vulnerability

Please **do not open a public issue**. Use
[GitHub private vulnerability reporting](https://github.com/akafrmn/omarchy-galaxy-buds-pro/security/advisories/new)
instead. Expect a first reply within a week.

Only the latest release is supported.
