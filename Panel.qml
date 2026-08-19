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

  // The helper lives in the plugin's service, mounted once per session; this
  // widget is mounted once per monitor and only renders what the service holds.
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property var buds: service ? service.state : ({})

  readonly property bool connected: buds.connected === true
  readonly property string noise: String(buds.noise || "off")
  readonly property var battery: buds.battery || ({})
  readonly property var touch: buds.touch || ({})
  readonly property var modes: buds.modes || ["off", "anc", "ambient"]
  readonly property bool hasSpatial: buds.spatial !== undefined
  readonly property string deviceName: String(buds.name || "Galaxy Buds")

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Without these the bar gives the widget zero width and nothing renders.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property int cursorIndex: 0
  readonly property int cursorCount: 4  // modes row + three toggles

  readonly property var modeOptions: {
    var labels = {"off": "Desligado", "anc": "ANC", "ambient": "Ambiente", "adaptive": "Adaptativo"}
    var out = []
    for (var i = 0; i < modes.length; i++)
      out.push({value: modes[i], label: labels[modes[i]] || modes[i]})
    return out
  }

  function setNoise(mode) { if (service) service.setNoise(mode) }
  function cycle() { if (service) service.cycle() }
  function setToggle(name, value) { if (service) service.setToggle(name, value) }

  // The glyph carries the mode on its own, the way the other bar icons do:
  // an ear that hears the room for ambient, a crossed-out one for ANC.
  function modeIcon() {
    if (!connected) return "󰟎"
    if (noise === "anc" || noise === "adaptive") return "󰋏"
    if (noise === "ambient") return "󰋎"
    return "󰋋"
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
    if (cursorIndex === 1) setToggle("spatial", !(buds.spatial === true))
    else if (cursorIndex === 2) setToggle("touch", !(touch.enabled === true))
    else if (cursorIndex === 3) setToggle("seamless", !(buds.seamless === true))
    else cycle()
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
            {"key": "spatial", "label": "360 Audio", "checked": root.buds.spatial === true,
             "shown": root.hasSpatial, "cursor": 1},
            {"key": "touch", "label": "Controles de toque", "checked": root.touch.enabled === true,
             "shown": true, "cursor": 2},
            {"key": "seamless", "label": "Conexão rápida", "checked": root.buds.seamless === true,
             "shown": root.buds.seamless !== undefined, "cursor": 3}
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
          text: !root.service
                ? "O serviço do plugin não está ativo."
                : root.buds.reason === "not paired"
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
