#!/usr/bin/python3
"""Install/restore this user's task manager without restarting Plasma."""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = "org.novelsavage.plasma.taskaudiofilter"
ORIGINAL = "org.kde.plasma.icontasks"
LEGACY_PLUGIN = "org.novelsavage.plasma.audiofilter"
STATE = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    / "plasma-audio-filter"
)
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def schema_defaults():
    schema = HERE / "plasmoid" / PLUGIN / "contents/config/main.xml"
    result = {}
    for group in ET.parse(schema).getroot().findall("{*}group"):
        result[group.attrib["name"]] = {
            entry.attrib["name"]: {
                "StringList": [],
                "Bool": False,
                "Int": 0,
                "UInt": 0,
                "Enum": 0,
                "Double": 0.0,
            }.get(entry.attrib["type"], "")
            for entry in group.findall("{*}entry")
        }
    return result


def evaluate(script):
    result = subprocess.run(
        [
            "qdbus6",
            "org.kde.plasmashell",
            "/PlasmaShell",
            "org.kde.PlasmaShell.evaluateScript",
            script,
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=15,
    )
    if "Error:" in result.stdout:
        raise RuntimeError(result.stdout)
    return json.loads(result.stdout)


def listing():
    return evaluate("""var result=[]; panels().forEach(function(p) {
        p.currentConfigGroup=["General"];
        var order=String(p.readConfig("AppletOrder", "")).split(";");
        p.widgets().forEach(function(w) {
            result.push({panel:p.id,id:w.id,type:w.type,index:order.indexOf(String(w.id)),geometry:w.geometry});
        });
    }); print(JSON.stringify(result));""")


def snapshot(widget):
    return evaluate(
        """var w=panelById(%d).widgetById(%d); var defaults=%s;
        function read(path) {
            w.currentConfigGroup=path;
            var values={}; var children={};
            var types=defaults[path.join("/")] || {};
            w.configKeys.forEach(function(k){
                values[k]=w.readConfig(k, types[k] === undefined ? "" : types[k]);
            });
            var groups=w.configGroups;
            groups.forEach(function(g){children[g]=read(path.concat([g]));});
            return {values:values,children:children};
        }
        print(JSON.stringify(read([])));"""
        % (widget["panel"], widget["id"], json.dumps(schema_defaults()))
    )


def create(panel, plugin, config, index, geometry=None):
    position = ""
    if geometry and geometry.get("width", 0) > 0:
        position = ",%s,%s,%s,%s" % (
            geometry["x"] + 1,
            geometry["y"] + 1,
            geometry["width"],
            geometry["height"],
        )
    return evaluate(
        """var p=panelById(%d); var w=p.addWidget(%s%s);
        function write(path,node) {
            w.currentConfigGroup=path;
            Object.keys(node.values).forEach(function(k){
                if(k.indexOf("audioFilter")!==0) w.writeConfig(k,node.values[k]);
            });
            Object.keys(node.children).forEach(function(g){write(path.concat([g]),node.children[g]);});
        }
        write([],%s); w.currentConfigGroup=["General"]; w.reloadConfig();
        w.index=%d; print(JSON.stringify({id:w.id,type:w.type}));"""
        % (panel, json.dumps(plugin), position, json.dumps(config), index)
    )


def remove(panel, widget):
    evaluate(
        "panelById(%d).widgetById(%d).remove();print(JSON.stringify(true));"
        % (panel, widget)
    )


def wait_ready(panel, widget, expected_launchers=None):
    for _ in range(40):
        ready = evaluate(
            'var w=panelById(%d).widgetById(%d);w.currentConfigGroup=["General"];'
            'print(JSON.stringify(w.readConfig("audioFilterReady",false)));'
            % (panel, widget)
        )
        if ready is True:
            if expected_launchers is None:
                return
            state = evaluate(
                'var w=panelById(%d).widgetById(%d);w.currentConfigGroup=["General"];'
                'print(JSON.stringify(w.readConfig("audioFilterLauncherState","")));'
                % (panel, widget)
            )
            if state and json.loads(state) == expected_launchers:
                return
        time.sleep(0.25)
    raise RuntimeError(
        "The custom task manager did not load the expected launcher list; the original has been kept."
    )


def install():
    def trace(message):
        if os.environ.get("AUDIO_FILTER_TRACE"):
            print(message, file=sys.stderr, flush=True)

    trace("Reading current task manager")
    version = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Version}", "plasma-desktop"], text=True
    )
    if not version.split(":")[-1].startswith("6.6.6-"):
        raise RuntimeError(
            "This package was verified against Plasma 6.6.6. Rebase before installing on "
            + version
        )
    widgets = listing()
    if any(w["type"] == PLUGIN for w in widgets):
        print("Already active; nothing changed.")
        return
    originals = [w for w in widgets if w["type"] in (ORIGINAL, LEGACY_PLUGIN)]
    if len(originals) != 1:
        raise RuntimeError(
            "Expected exactly one Icons-Only Task Manager; found " + str(len(originals))
        )
    old = originals[0]
    config = snapshot(old)
    trace("Typed configuration captured")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = STATE / stamp
    backup.mkdir(mode=0o700)
    source = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "plasma-org.kde.plasma.desktop-appletsrc"
    )
    if source.exists():
        shutil.copy2(source, backup / source.name)
    saved = dict(old, config=config, backup=str(backup))
    (backup / "snapshot.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2)
    )
    (STATE / "active.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    target = DATA / "plasma/plasmoids" / PLUGIN
    if target.exists():
        shutil.copytree(target, backup / "previous-package")
    shutil.copytree(HERE / "plasmoid" / PLUGIN, target, dirs_exist_ok=True)
    initial = {
        key: value
        for key, value in config["children"]
        .get("General", {})
        .get("values", {})
        .items()
        if not key.startswith("audioFilter")
    }
    (target / "contents/ui/InitialSettings.qml").write_text(
        "// SPDX-License-Identifier: GPL-2.0-or-later\nimport QtQml\n"
        "QtObject { readonly property var values: (" + json.dumps(initial) + ") }\n"
    )
    trace("Creating replacement widget")
    new = create(old["panel"], PLUGIN, config, old["index"], old.get("geometry"))
    try:
        trace("Waiting for the runtime launcher list")
        wait_ready(
            old["panel"],
            new["id"],
            config["children"]
            .get("General", {})
            .get("values", {})
            .get("launchers", []),
        )
    except Exception:
        remove(old["panel"], new["id"])
        raise
    remove(old["panel"], old["id"])
    saved["active_id"] = new["id"]
    (STATE / "active.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    print(json.dumps({"active": new, "backup": str(backup)}, ensure_ascii=False))


def restore():
    custom = [w for w in listing() if w["type"] in (PLUGIN, LEGACY_PLUGIN)]
    if not custom:
        print("No custom task manager is active; nothing changed.")
        return
    for old in custom:
        # Preserve pins and settings changed since installation.
        config = snapshot(old)
        new = create(old["panel"], ORIGINAL, config, old["index"], old.get("geometry"))
        time.sleep(1)
        remove(old["panel"], old["id"])
        print(json.dumps({"restored": new}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "restore", "status"])
    args = parser.parse_args()
    if args.action == "install":
        install()
    elif args.action == "restore":
        restore()
    else:
        print(json.dumps(listing(), ensure_ascii=False, indent=2))
