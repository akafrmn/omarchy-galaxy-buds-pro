import QtQuick
import Quickshell.Io

// Mounted once per shell session. Bar widgets are mounted once per monitor, and
// only one process can hold the earbuds' SPP link, so the helper and the state
// it reports live here and every bar reads the same object.
QtObject {
  id: root

  property var shell: null
  property var manifest: null

  // Whole state arrives as one JSON object per line; the helper always sends
  // the complete picture, so replacing it wholesale keeps bindings simple.
  property var state: ({})

  readonly property string pluginId: "aislandener.galaxy-buds"
  readonly property string helperPath: Qt.resolvedUrl("bin/galaxy-buds").toString().replace(/^file:\/\//, "")

  function send(request) {
    if (daemon.running) daemon.write(JSON.stringify(request) + "\n")
  }

  function setNoise(mode) { send({"cmd": "noise", "value": mode}) }
  function cycle() { send({"cmd": "cycle"}) }
  function setToggle(name, value) { send({"cmd": name, "value": value}) }

  function applyLine(line) {
    var text = String(line || "").trim()
    if (text === "") return
    try {
      root.state = JSON.parse(text)
    } catch (error) {
      // A malformed line means the helper printed something unexpected; the
      // next state line supersedes it anyway.
    }
  }

  property Process daemon: Process {
    command: ["/usr/bin/python3", root.helperPath]
    running: true
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { root.applyLine(line) }
    }
    // The helper dying (BlueZ restart, a stray kill) would otherwise leave
    // every bar frozen on its last state forever.
    onExited: {
      root.state = {}
      restartTimer.restart()
    }
  }

  property Timer restartTimer: Timer {
    interval: 3000
    repeat: false
    onTriggered: daemon.running = true
  }

  // One handler for the whole session, so a keybind reaches the earbuds
  // regardless of which monitor is focused. Opening the popover is routed
  // through the shell, which picks the bar the pointer is on.
  property IpcHandler ipc: IpcHandler {
    target: root.pluginId

    function cycle(): void { root.cycle() }
    function set(mode: string): void { root.setNoise(mode) }
    function status(): string { return JSON.stringify(root.state) }
    function open(): void { if (root.shell) root.shell.summon(root.pluginId, "{}") }
    function close(): void { if (root.shell) root.shell.hide(root.pluginId) }
    function toggle(): void { if (root.shell) root.shell.toggle(root.pluginId, "{}") }
  }
}
