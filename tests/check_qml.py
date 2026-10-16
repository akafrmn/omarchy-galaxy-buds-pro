#!/usr/bin/python3
"""Catch QML that qmllint accepts but the engine refuses to load: the same
property or handler bound twice on one object ("Property value set multiple
times"). Also require every Text to bind `textFormat: Text.PlainText`: the
default AutoText renders markup, so an advertised Bluetooth name, a firmware
build or a release tag containing <img src=...> would make Qt fetch and decode
remote images inside the shared shell.
Run: /usr/bin/python3 tests/check_qml.py [files...]"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINDING = re.compile(r"^(\s*)(?:readonly\s+)?(?:property\s+\S+\s+)?([A-Za-z_][\w.]*)\s*:(?!:)")
OPEN = re.compile(r"^(\s*)(?:[A-Z][\w.]*|[a-z]\w*\s*:\s*[A-Z][\w.]*)\s*\{\s*$")
TEXT = re.compile(r"^\s*Text\s*\{\s*$")


def duplicates(path):
    problems = []
    # One frame per open object: its indent and the bindings seen so far.
    stack = [(-1, {})]
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("//", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        if OPEN.match(line):
            stack.append((indent, {}))
            continue
        match = BINDING.match(line)
        if not match or len(match.group(1)) != stack[-1][0] + 2:
            continue
        name = match.group(2)
        if name in ("case", "default"):
            continue
        seen = stack[-1][1]
        if name in seen:
            problems.append(f"{path.name}:{number}: {name} already bound on line {seen[name]}")
        else:
            seen[name] = number
    return problems


def rich_text(path):
    problems = []
    # One frame per open Text object: its indent, line and whether it is plain.
    stack = []
    lines = path.read_text().splitlines()
    for number, raw in enumerate(lines + ["}"], 1):
        line = raw.split("//", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while stack and indent <= stack[-1][0]:
            _, opened, plain = stack.pop()
            if not plain:
                problems.append(f"{path.name}:{opened}: Text without textFormat: Text.PlainText")
        if TEXT.match(line):
            stack.append([indent, number, False])
        elif stack and indent == stack[-1][0] + 2 and line.strip() == "textFormat: Text.PlainText":
            stack[-1][2] = True
    return problems


files = [pathlib.Path(arg) for arg in sys.argv[1:]] or sorted(ROOT.glob("*.qml"))
problems = [problem for path in files for problem in duplicates(path)]
plain = [problem for path in files for problem in rich_text(path)]
for problem in problems + plain:
    print("FAIL", problem)
print("ok   no duplicate QML bindings" if not problems else f"{len(problems)} problem(s)")
print("ok   every Text is plain text" if not plain else f"{len(plain)} rich-text problem(s)")
sys.exit(1 if problems or plain else 0)
