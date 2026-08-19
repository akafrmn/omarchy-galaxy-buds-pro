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
  readonly property string deviceName: String(buds.name || "Galaxy Buds")

  // Models differ in what they can do at all: the Buds+ has no ANC and no
  // 360 Audio, the original Buds has no case battery. The helper simply omits
  // what the earbuds never report, so absence here means "hide the control".
  readonly property bool hasSpatial: buds.spatial !== undefined
  readonly property bool hasSeamless: buds.seamless !== undefined
  readonly property bool hasTouch: touch.enabled !== undefined
  readonly property bool hasModes: modes.length > 1

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Every visible string can be replaced from this widget's shell.json entry:
  //   { "id": "aislandener.galaxy-buds", "labels": { "anc": "ANC", ... } }
  readonly property var labels: setting("labels", ({}))
  function t(key, fallback) {
    var value = labels ? labels[key] : undefined
    return value === undefined || value === null ? fallback : String(value)
  }

  // Without these the bar gives the widget zero width and nothing renders.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property int cursorIndex: 0
  readonly property int cursorCount: 1 + toggleRows.length

  readonly property var modeOptions: {
    var names = {
      "off": t("off", "Off"),
      "anc": t("anc", "ANC"),
      "ambient": t("ambient", "Ambient"),
      "adaptive": t("adaptive", "Adaptive")
    }
    var out = []
    for (var i = 0; i < modes.length; i++)
      out.push({value: modes[i], label: names[modes[i]] || modes[i]})
    return out
  }

  readonly property var batteryRows: {
    var rows = []
    if (!connected) return rows
    if (battery.left !== undefined)
      rows.push({label: t("left", "L"), value: battery.left})
    if (battery.right !== undefined)
      rows.push({label: t("right", "R"), value: battery.right})
    // The case only reports while the earbuds sit in it.
    if (battery.case > 0)
      rows.push({label: t("case", "Case"), value: battery.case})
    return rows
  }

  readonly property var toggleRows: {
    var rows = []
    if (!connected) return rows
    if (hasSpatial)
      rows.push({key: "spatial", label: t("spatial", "360 Audio"), checked: buds.spatial === true})
    if (hasTouch)
      rows.push({key: "touch", label: t("touch", "Touch controls"), checked: touch.enabled === true})
    if (hasSeamless)
      rows.push({key: "seamless", label: t("seamless", "Quick connect"), checked: buds.seamless === true})
    return rows
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

  function selectCursor(index) {
    cursorIndex = Math.max(0, Math.min(cursorCount - 1, index))
  }

  function activateCursor() {
    if (!connected) return
    if (cursorIndex === 0) {
      cycle()
      return
    }
    var row = toggleRows[cursorIndex - 1]
    if (row) setToggle(row.key, !row.checked)
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
        spacing: Style.space(12)

        // ---------- Hero: headphones · device name ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroName.implicitHeight)

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

          Text {
            id: heroName
            text: root.deviceName
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        // ---------- Battery: one bar per earbud, plus the case ----------
        Column {
          width: parent.width
          spacing: Style.space(6)
          visible: root.batteryRows.length > 0

          Repeater {
            model: root.batteryRows

            Item {
              required property var modelData
              width: panelColumn.width
              height: Style.space(16)

              Text {
                id: cellLabel
                text: modelData.label
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                width: Style.space(34)
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Rectangle {
                id: track
                anchors.left: cellLabel.right
                anchors.right: cellValue.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                height: Style.space(6)
                radius: height / 2
                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15)

                Rectangle {
                  width: Math.max(parent.height, parent.width * Math.max(0, Math.min(100, modelData.value)) / 100)
                  height: parent.height
                  radius: parent.radius
                  // A charge this low is the one thing here worth interrupting for.
                  color: modelData.value <= 20 ? root.urgent : root.foreground
                  Behavior on width { NumberAnimation { duration: 160 } }
                }
              }

              Text {
                id: cellValue
                text: modelData.value + "%"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
                width: Style.space(34)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }
        }

        PanelSeparator {
          width: parent.width
          foreground: root.foreground
          visible: root.connected && root.hasModes
        }

        PanelSectionHeader {
          width: parent.width
          text: root.t("noiseControl", "Noise control")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected && root.hasModes
        }

        ButtonGroup {
          id: modeGroup
          width: parent.width
          options: root.modeOptions
          value: root.noise
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected && root.hasModes
          cursorIndex: root.cursorIndex === 0 ? modeGroup.selectedOptionIndex() : -1
          onChanged: function(value) {
            root.selectCursor(0)
            root.setNoise(value)
          }
        }

        PanelSectionHeader {
          width: parent.width
          text: root.t("settings", "Settings")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.toggleRows.length > 0
        }

        Repeater {
          model: root.toggleRows

          Item {
            required property var modelData
            required property int index
            width: panelColumn.width
            height: Math.max(rowLabel.implicitHeight, rowSwitch.implicitHeight)

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
              hasCursor: root.cursorIndex === index + 1
              foreground: root.foreground
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onHovered: function(on) { if (on) root.selectCursor(index + 1) }
              onToggled: root.setToggle(modelData.key, !modelData.checked)
            }
          }
        }

        Text {
          width: parent.width
          visible: !root.connected
          text: !root.service
                ? root.t("serviceOff", "The plugin service is not running.")
                : root.buds.reason === "not paired"
                  ? root.t("notPaired", "No Galaxy Buds paired.")
                  : root.t("disconnected", "Disconnected. Take them out of the case to reconnect.")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
