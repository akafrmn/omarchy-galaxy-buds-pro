import QtQuick
import Quickshell
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

  readonly property string pluginId: "io.github.akafrmn.galaxy-buds-pro"
  readonly property string helperPath: Qt.resolvedUrl("bin/galaxy-buds").toString().replace(/^file:\/\//, "")

  function send(request) {
    if (daemon.running) daemon.write(JSON.stringify(request) + "\n")
  }

  function setNoise(mode) { send({"cmd": "noise", "value": mode}) }
  function cycle() { send({"cmd": "cycle"}) }
  function setToggle(name, value) { send({"cmd": name, "value": value}) }
  function setCodec(profile) { send({"cmd": "codec", "value": profile}) }

  // Firmware update check. Starts off and follows the widget's setting (on by
  // default), so a user who turned it off never makes a single request.
  property bool firmwareCheck: false
  function pushFirmwareCheck() { send({"cmd": "firmware_check", "value": root.firmwareCheck}) }
  onFirmwareCheckChanged: pushFirmwareCheck()

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

  // ---- low battery warning ---------------------------------------------
  // Lives here rather than in Panel.qml: the panel is instantiated once per
  // monitor, so notifying from there would fire one notification per screen.
  // The panel pushes the user's settings down instead (idempotent per monitor).
  property bool lowBatteryEnabled: true
  property int lowBatteryThreshold: 15

  // Placement nibble 3 means the earbud is sitting in the case; a bud in the
  // case is on its way up, not down, so it never warrants a warning.
  readonly property int placementInCase: 3
  // Re-arm only once the bud climbs clear of the threshold, so a charge level
  // hovering on the boundary cannot produce a stream of notifications.
  readonly property int rearmMargin: 5

  function budBattery(side) {
    var battery = root.state ? root.state.battery : null
    var value = battery ? Number(battery[side]) : NaN
    return isFinite(value) ? value : -1
  }

  function budLow(side) {
    var value = budBattery(side)
    if (value < 0) return false
    var charging = root.state ? root.state.charging : null
    if (charging && charging[side] === true) return false
    var wearing = root.state ? root.state.wearing : null
    // 3 is the open case, 4 the closed one.
    if (wearing && Number(wearing[side]) >= root.placementInCase) return false
    // Nibble 0: the bud dropped off the link (closed case, out of range) and
    // its 0 is no reading, not a flat battery.
    if (wearing && Number(wearing[side]) === 0 && value <= 0) return false
    return value <= root.lowBatteryThreshold
  }

  function budClear(side) {
    var value = budBattery(side)
    return value < 0 || value > root.lowBatteryThreshold + root.rearmMargin
  }

  function checkLowBattery() {
    if (!root.lowBatteryEnabled) return
    if (!root.state || root.state.connected !== true) return

    var leftLow = budLow("left")
    var rightLow = budLow("right")

    if (leftLow || rightLow) {
      if (lowBatteryState.notified) return
      lowBatteryState.notified = true
      var parts = []
      if (leftLow) parts.push("Left " + budBattery("left") + "%")
      if (rightLow) parts.push("Right " + budBattery("right") + "%")
      notifier.command = [
        "omarchy-notification-send",
        "-g", "󰋋",
        "-u", "critical",
        "-i", "battery-caution",
        "-t", "30000",
        "-r", "9271",
        (root.state.name || "Galaxy Buds") + " battery low",
        parts.join("  ·  ")
      ]
      notifier.running = true
    } else if (lowBatteryState.notified && budClear("left") && budClear("right")) {
      lowBatteryState.notified = false
    }
  }

  onStateChanged: root.checkLowBattery()

  // Survives a shell reload so a restart does not re-announce a level the user
  // has already been told about.
  property PersistentProperties lowBatteryState: PersistentProperties {
    reloadableId: "io.github.akafrmn.galaxy-buds-pro.lowBattery"
    property bool notified: false
  }

  property Process notifier: Process {}

  property Process daemon: Process {
    command: ["/usr/bin/python3", root.helperPath]
    running: true
    stdinEnabled: true
    onRunningChanged: if (running) root.pushFirmwareCheck()
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
    function codec(profile: string): void { root.setCodec(profile) }
    function open(): void { if (root.shell) root.shell.summon(root.pluginId, "{}") }
    function close(): void { if (root.shell) root.shell.hide(root.pluginId) }
    function toggle(): void { if (root.shell) root.shell.toggle(root.pluginId, "{}") }
    // Exposed for testing the warning without waiting for a real drain.
    function testLowBattery(): void {
      root.lowBatteryState.notified = false
      root.checkLowBattery()
    }
  }
}
