PLUGIN_ID := $(shell jq -r .id manifest.json)
PLUGIN_DIR := $(HOME)/.config/omarchy/plugins/$(PLUGIN_ID)
PYTHON ?= /usr/bin/python3
QMLLINT ?= $(firstword $(wildcard /usr/lib/qt6/bin/qmllint) $(shell command -v qmllint))

.PHONY: check test manifest validate lint dev-install

check: test manifest validate lint

test:
	$(PYTHON) tests/test_protocol.py

manifest:
	$(PYTHON) tests/check_manifest.py
	$(PYTHON) tests/check_qml.py

# The real validator, when Omarchy is installed.
validate:
	@if command -v omarchy >/dev/null; then omarchy plugin validate .; else echo "skip validate: no omarchy"; fi

lint:
	$(PYTHON) -m py_compile bin/galaxy-buds tools/eq-probe.py tests/*.py
	@if command -v ruff >/dev/null; then ruff check .; else echo "skip ruff: not installed"; fi
	@if [ -n "$(QMLLINT)" ]; then $(QMLLINT) Service.qml Panel.qml 2>&1 | grep -iE 'syntax error|Expected token' && exit 1 || true; fi

# Copy (never symlink: the validator rejects symlinks) into the plugins folder.
dev-install:
	rsync -a --delete --exclude .git --exclude __pycache__ ./ $(PLUGIN_DIR)/
	omarchy-shell shell rescanPlugins
