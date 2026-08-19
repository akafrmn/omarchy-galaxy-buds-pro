import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "aislandener.galaxy-buds"
  ipcTarget: "aislandener.galaxy-buds"
  manageIpc: false

  readonly property string helperPath: Qt.resolvedUrl("bin/galaxy-buds").toString().replace(/^file:\/\//, "")

  // Whole state arrives as one JSON object per line; the daemon always sends
  // the complete picture, so replacing it wholesale keeps bindings simple.
  property var state: ({})

  readonly property bool connected: state.connected === true
  readonly property string noise: String(state.noise || "off")
  readonly property var battery: state.battery || ({})
  readonly property var touch: state.touch || ({})
  readonly property var modes: state.modes || ["off", "anc", "ambient"]
  readonly property bool hasSpatial: state.spatial !== undefined
  readonly property string deviceName: String(state.name || "Galaxy Buds")

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property int cursorIndex: 0
  readonly property int cursorCount: 4  // modes row + three toggles

  readonly property var modeOptions: {
    var labels = {"off": "Desligado", "anc": "ANC", "ambient": "Ambiente", "adaptive": "Adaptativo"}
    var out = []
    for (var i = 0; i < modes.length; i++)
      out.push({value: modes[i], label: labels[modes[i]] || modes[i]})
    return out
  }

  function send(request) {
    if (daemon.running) daemon.write(JSON.stringify(request) + "\n")
  }

  function setNoise(mode) { send({"cmd": "noise", "value": mode}) }
  function cycle() { send({"cmd": "cycle"}) }
  function setToggle(name, value) { send({"cmd": name, "value": value}) }

  function applyState(line) {
    var text = String(line || "").trim()
    if (text === "") return
    try {
      root.state = JSON.parse(text)
    } catch (error) {
      // A malformed line means the helper printed something unexpected; the
      // next state line supersedes it anyway.
    }
  }

  // The glyph carries the mode on its own, the way the other bar icons do:
  // an ear that hears the room for ambient, a crossed-out one for ANC.
  function modeIcon() {
    if (!connected) return "󰟎"
    if (noise === "anc" || noise === "adaptive") return "󰋏"
    if (noise === "ambient") return "󰋎"
    return "󰋋"
  }

  function modeLabel() {
    var labels = {"off": "Desligado", "anc": "ANC", "ambient": "Som ambiente", "adaptive": "Adaptativo"}
    return connected ? (labels[noise] || noise) : "Desconectado"
  }

  function batteryText() {
    if (!connected) return "desconectado"
    var left = battery.left, right = battery.right
    if (left === undefined) return "conectado"
    var text = "L " + left + "%  ·  R " + right + "%"
    if (battery.case > 0) text += "  ·  " + battery.case + "%"
    return text
  }

  function selectCursor(index) {
    cursorIndex = Math.max(0, Math.min(cursorCount - 1, index))
  }

  function activateCursor() {
    if (!connected) return
    if (cursorIndex === 1) setToggle("spatial", !(state.spatial === true))
    else if (cursorIndex === 2) setToggle("touch", !(touch.enabled === true))
    else if (cursorIndex === 3) setToggle("seamless", !(state.seamless === true))
    else cycle()
  }

  Process {
    id: daemon
    running: true
    command: ["/usr/bin/python3", root.helperPath]
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { root.applyState(line) }
    }
    // The helper dying (BlueZ restart, a stray kill) would otherwise leave the
    // widget frozen on its last state forever.
    onExited: {
      root.state = {}
      restartTimer.restart()
    }
  }

  Timer {
    id: restartTimer
    interval: 3000
    repeat: false
    onTriggered: daemon.running = true
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function cycle(): void { root.cycle() }
    function set(mode: string): void { root.setNoise(mode) }
    function status(): string { return JSON.stringify(root.state) }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.modeIcon()
    opacity: root.connected ? 1.0 : 0.5
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton) root.cycle()
      else root.toggle()
    }

    PanelToolTip {
      visible: button.tooltipHovered && !root.opened
      text: root.modeLabel()
      fontFamily: root.fontFamily
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(420))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) root.selectCursor(root.cursorIndex + dy)
        else if (dx !== 0 && root.cursorIndex === 0 && root.connected) root.cycle()
      }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        var index = ["1", "2", "3", "4"].indexOf(text)
        if (index >= 0 && index < root.modes.length && root.connected)
          root.setNoise(root.modes[index])
      }

      Column {
        id: panelColumn
        anchors.fill: parent
        spacing: Style.space(14)

        // ---------- Hero: headphones · name/battery ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

          Text {
            id: heroIcon
            text: root.modeIcon()
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
            opacity: root.connected ? 1.0 : 0.5
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: root.deviceName
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              text: root.batteryText()
              color: Qt.darker(root.foreground, 1.55)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.foreground }

        PanelSectionHeader {
          width: parent.width
          text: "Controle de ruído"
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected
        }

        ButtonGroup {
          id: modeGroup
          width: parent.width
          options: root.modeOptions
          value: root.noise
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected
          cursorIndex: root.cursorIndex === 0 ? modeGroup.selectedOptionIndex() : -1
          onChanged: function(value) {
            root.selectCursor(0)
            root.setNoise(value)
          }
        }

        PanelSectionHeader {
          width: parent.width
          text: "Ajustes"
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected
        }

        Repeater {
          model: root.connected ? [
            {"key": "spatial", "label": "360 Audio", "checked": root.state.spatial === true,
             "shown": root.hasSpatial, "cursor": 1},
            {"key": "touch", "label": "Controles de toque", "checked": root.touch.enabled === true,
             "shown": true, "cursor": 2},
            {"key": "seamless", "label": "Conexão rápida", "checked": root.state.seamless === true,
             "shown": root.state.seamless !== undefined, "cursor": 3}
          ] : []

          Item {
            required property var modelData
            width: panelColumn.width
            visible: modelData.shown
            height: visible ? Math.max(rowLabel.implicitHeight, rowSwitch.implicitHeight) : 0

            Text {
              id: rowLabel
              text: modelData.label
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            ToggleSwitch {
              id: rowSwitch
              checked: modelData.checked
              hasCursor: root.cursorIndex === modelData.cursor
              foreground: root.foreground
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onHovered: function(on) { if (on) root.selectCursor(modelData.cursor) }
              onToggled: root.setToggle(modelData.key, !modelData.checked)
            }
          }
        }

        Text {
          width: parent.width
          visible: !root.connected
          text: root.state.reason === "not paired"
                ? "Nenhum Galaxy Buds pareado."
                : "Fones desconectados. Tire-os do estojo para reconectar."
          color: Qt.darker(root.foreground, 1.55)
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
