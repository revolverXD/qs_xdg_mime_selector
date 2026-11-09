// Standalone Quickshell app: pick which app opens each XDG file type.
// Run it with `qs -p <this directory>`; it talks to xdgtypes.py (SQLite index + xdg-mime).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

PanelWindow {
    id: win
    visible: true
    exclusiveZone: 0
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    anchors { top: true; bottom: true; left: true; right: true }
    color: "#a0000000"

    property var types: []
    property var apps: []
    property var selected: null
    property string filter: "all" // all | set | unset
    property string status: "indexing file types…"

    // One python call at a time; requests asked for while busy are queued.
    property var queue: []
    property var pending: null

    readonly property string script: decodeURIComponent(
        Qt.resolvedUrl("xdgtypes.py").toString().replace("file://", ""))

    function call(args, callback) {
        queue.push([args, callback]);
        pump();
    }

    function pump() {
        if (run.running || queue.length === 0)
            return;
        pending = queue.shift();
        run.command = ["python3", win.script].concat(pending[0]);
        run.running = true;
    }

    function loadTypes(text) {
        call(["types", text, filter], (r) => {
            types = r;
            // keep the selection pointing at fresh data after set/unset
            if (selected !== null)
                for (let i = 0; i < r.length; i++)
                    if (r[i].id === selected.id) {
                        selected = r[i];
                        break;
                    }
            status = r.length === 0 ? "no matching type" : r.length + " types";
        });
    }

    function loadApps(mime, text) {
        call(["apps", mime, text], (r) => apps = r);
    }

    function refresh() {
        loadApps(selected.id, appSearch.text);
        loadTypes(search.text);
    }

    function setDefault(appId) {
        call(["set", selected.id, appId], refresh);
    }

    function clearDefault() {
        call(["unset", selected.id], refresh);
    }

    Process {
        id: run
        running: false
        stdout: SplitParser {
            splitMarker: "\n"
            onRead: (line) => {
                if (win.pending === null)
                    return;
                const callback = win.pending[1];
                win.pending = null;
                let data;
                try {
                    data = JSON.parse(line);
                } catch (e) {
                    win.status = "bad output from xdgtypes.py";
                    return;
                }
                callback(data);
            }
        }
        stderr: SplitParser {
            splitMarker: "\n"
            onRead: (line) => win.status = line
        }
        onExited: (code) => {
            if (code !== 0)
                win.status = "xdgtypes.py exited with " + code;
            win.pump();
        }
        Component.onCompleted: call(["build"], () => {
            win.status = "";
            win.loadTypes("");
        })
    }

    MouseArea { // click the dim area around the card to close
        anchors.fill: parent
        onClicked: Qt.quit()
    }

    Shortcut {
        sequences: ["Escape"]
        onActivated: Qt.quit()
    }

    Rectangle {
        id: card
        width: 1020
        height: 620
        anchors.centerIn: parent
        radius: 10
        color: "#1c1c20"
        border.color: "#3c3c44"

        Column {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            Row {
                spacing: 10
                Text {
                    text: "Default app per file type"
                    color: "#ffffff"
                    font.pixelSize: 16
                    font.bold: true
                    anchors.verticalCenter: parent.verticalCenter
                }
                TextField {
                    id: search
                    width: 300
                    placeholderText: "type, extension or description"
                    selectByMouse: true
                    font.pixelSize: 13
                    onTextChanged: win.loadTypes(text)
                    Component.onCompleted: forceActiveFocus()
                }
                // which defaults to list
                Repeater {
                    model: [
                        { "label": "all", "value": "all" },
                        { "label": "have a default", "value": "set" },
                        { "label": "no default", "value": "unset" },
                    ]
                    Rectangle {
                        required property var modelData
                        radius: 4
                        color: win.filter === modelData.value ? "#3c3c48" : "#26262c"
                        border.color: "#3c3c44"
                        implicitWidth: chipLabel.implicitWidth + 14
                        implicitHeight: 24
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: {
                                win.filter = modelData.value;
                                win.loadTypes(search.text);
                            }
                        }
                        Text {
                            id: chipLabel
                            anchors.centerIn: parent
                            text: modelData.label
                            color: "#c8c8d0"
                            font.pixelSize: 12
                        }
                    }
                }
                Text {
                    text: win.status
                    color: "#888888"
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                spacing: 14
                Rectangle { width: 1; height: 530; color: "#333338" }

                ListView {
                    width: 440
                    height: 530
                    clip: true
                    spacing: 2
                    model: win.types
                    delegate: Rectangle {
                        width: 438
                        height: 38
                        radius: 4
                        color: win.selected !== null && win.selected.id === modelData.id
                              ? "#2f2f3a" : (hover.hovered ? "#25252c" : "transparent")
                        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: {
                                win.selected = modelData;
                                win.loadApps(modelData.id, appSearch.text);
                            }
                        }
                        // green dot = this type already has a default app
                        Text {
                            id: dot
                            x: 6
                            anchors.verticalCenter: parent.verticalCenter
                            text: "●"
                            color: modelData.default ? "#4caf50" : "#4a4a52"
                            font.pixelSize: 13
                        }
                        Column {
                            x: 26
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                text: modelData.id
                                color: "#e8e8e8"
                                font.pixelSize: 13
                                font.family: "monospace"
                            }
                            Text {
                                text: ((modelData.descr || "") + (modelData.defaultName
                                      ? "  ·  " + modelData.defaultName : "  ·  no default"))
                                color: "#9a9aa2"
                                font.pixelSize: 11
                            }
                        }
                    }
                }

                Rectangle { width: 1; height: 530; color: "#333338" }

                Column {
                    width: 500
                    spacing: 6
                    Text {
                        text: win.selected === null ? "pick a file type on the left" : win.selected.id
                        color: "#e8e8e8"
                        font.pixelSize: 13
                        font.family: "monospace"
                    }
                    Row {
                        spacing: 8
                        height: 28 // the default Button style has no implicit height in this style
                        Text {
                            text: win.selected === null ? ""
                                  : "current default: " + (win.selected.defaultName || "none")
                            color: "#9a9aa2"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Button {
                            text: "Remove default"
                            font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                            visible: win.selected !== null
                                  && win.selected.default !== ""
                            onClicked: win.clearDefault()
                        }
                    }
                    TextField {
                        id: appSearch
                        width: 500
                        placeholderText: "filter apps"
                        selectByMouse: true
                        font.pixelSize: 13
                        onTextChanged: if (win.selected !== null)
                            win.loadApps(win.selected.id, text)
                    }
                    Text {
                        text: win.selected === null ? "" : "click an app to make it the default"
                        color: "#7a7a82"
                        font.pixelSize: 11
                    }

                    ListView {
                        width: 500
                        height: 400
                        clip: true
                        spacing: 2
                        model: win.apps
                        delegate: Rectangle {
                            width: 498
                            height: 26
                            radius: 4
                            color: hover.hovered ? "#25252c" : "transparent"
                            HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.setDefault(modelData.id) }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 6
                                Text {
                                    text: "●"
                                    color: modelData.isDefault ? "#4caf50" : "transparent"
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: modelData.name
                                    color: modelData.isDefault ? "#e8e8e8"
                                          : (modelData.handles ? "#c8c8d0" : "#8a8a92")
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: modelData.isDefault ? "  (current default)"
                                          : (hover.hovered ? "  ← set as default"
                                             : (modelData.handles ? "" : "  (does not handle this type)"))
                                    color: "#7a7a82"
                                    font.pixelSize: 11
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
