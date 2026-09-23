# Security policy

This plugin runs unsandboxed inside `omarchy-shell`. It talks to your earbuds over Bluetooth
and runs `pactl`. It never elevates privileges or writes files. Its network access is the optional firmware
update check (one HTTPS GET of a public build list, model name only; `firmwareCheck: false` disables it)
and, when you click Install, the download of that firmware image. It can write firmware to your
earbuds, only after you confirm, and only upgrades that pass every check in the README.

## Reporting a vulnerability

Please **do not open a public issue**. Use
[GitHub private vulnerability reporting](https://github.com/akafrmn/omarchy-galaxy-buds-pro/security/advisories/new)
instead. Expect a first reply within a week.

Only the latest release is supported.
