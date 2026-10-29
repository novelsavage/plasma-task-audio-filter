#!/usr/bin/python3
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent
PKG = ROOT.parent / "plasmoid/org.novelsavage.plasma.taskaudiofilter"


def wait(fn, msg):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.15)
    raise RuntimeError(msg)


if len(sys.argv) == 1:
    if not shutil.which("bwrap"):
        raise SystemExit(
            "bubblewrap is required. This test never falls back to the host desktop."
        )
    d = pathlib.Path(tempfile.mkdtemp(prefix="af-test-"))
    for name in ["config", "data", "cache", "runtime", "home", "state"]:
        (d / name).mkdir(mode=0o700)
    services = d / "data/dbus-1/services"
    services.mkdir(parents=True)
    (services / "org.freedesktop.portal.Desktop.service").write_text(
        "[D-BUS Service]\nName=org.freedesktop.portal.Desktop\nExec=/bin/false\n"
    )
    (d / "bus.conf").write_text(
        """<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth><apparmor mode="disabled"/><policy context="default"><allow user="*"/><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy><standard_session_servicedirs/></busconfig>"""
    )
    # A private mount/PID/user namespace hides the host home, runtime sockets,
    # desktop bus, system bus and notification services. Namespace exit also
    # reaps D-Bus-activated descendants. Never run a full shell on the host bus.
    cmd = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--tmpfs",
        "/home",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/mnt",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--ro-bind",
        str(ROOT.parent),
        "/mnt/src",
        "--bind",
        str(d),
        "/mnt/test",
        "--ro-bind",
        "/usr/bin/true",
        "/usr/bin/plasma-welcome",
        "--chdir",
        "/mnt/test",
        "--clearenv",
    ]
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/mnt/test/home",
        "LANG": "C.UTF-8",
        "XDG_CONFIG_HOME": "/mnt/test/config",
        "XDG_DATA_HOME": "/mnt/test/data",
        "XDG_CACHE_HOME": "/mnt/test/cache",
        "XDG_RUNTIME_DIR": "/mnt/test/runtime",
        "XDG_STATE_HOME": "/mnt/test/state",
        "QT_QPA_PLATFORM": "offscreen",
        "AUDIO_TEST_ROOT": "/mnt/test",
        "AUDIO_TEST_SANDBOX": "1",
        "KDE_DEBUG": "1",
        "XDG_MENU_PREFIX": "plasma-",
    }
    for key, value in environment.items():
        cmd += ["--setenv", key, value]
    cmd += [
        "dbus-run-session",
        "--config-file=/mnt/test/bus.conf",
        "--",
        "/usr/bin/python3",
        "/mnt/src/tests/gui_test.py",
        "inside",
    ]
    import resource

    def disable_core_files():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    try:
        subprocess.run(cmd, check=True, timeout=100, preexec_fn=disable_core_files)
    finally:
        evidence = ROOT / "artifacts"
        evidence.mkdir(exist_ok=True)
        for name in [
            "result.json",
            "filtered.png",
            "pins.png",
            "plasma.log",
            "kwin.log",
        ]:
            if (d / name).exists():
                shutil.copy2(d / name, evidence / name)
        shutil.rmtree(d)
    sys.exit()
if sys.argv[1] == "fixture":
    from PyQt6.QtWidgets import QApplication, QLabel

    app = QApplication([])
    app.setDesktopFileName(sys.argv[2])
    app.setApplicationName(sys.argv[3])
    w = QLabel(sys.argv[3])
    w.setWindowTitle(sys.argv[3])
    w.resize(350, 100)
    w.show()
    sys.exit(app.exec())
import dbus

d = pathlib.Path(os.environ["AUDIO_TEST_ROOT"])
assert str(d) == "/mnt/test" and os.environ.get("AUDIO_TEST_SANDBOX") == "1"
assert os.environ["XDG_RUNTIME_DIR"] == "/mnt/test/runtime"
assert os.environ["HOME"] == "/mnt/test/home"
children = []


def spawn(cmd, env, name):
    p = subprocess.Popen(
        cmd, env=env, stdout=(d / name).open("w"), stderr=subprocess.STDOUT
    )
    children.append(p)
    return p


def evaluate(s):
    return dbus.Interface(
        bus.get_object("org.kde.plasmashell", "/PlasmaShell"), "org.kde.PlasmaShell"
    ).evaluateScript(s)


try:
    # Exercise filter using the real Qt JavaScript engine.
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtQml import QJSEngine, QJSValue

    app = QCoreApplication([])
    engine = QJSEngine()
    source = (
        (PKG / "contents/ui/code/AudioFilter.js")
        .read_text()
        .replace(".pragma library", "")
    )
    assert not engine.evaluate(source).isError()
    cases = {
        "": False,
        "google-chrome": False,
        "org.kde.konsole": False,
        "crx_eilembjdkfgodjkcjnpgpaenohkicgjd": True,
        "chrome-kjbdgfilnfhdoflbpgamdcdgpehopbep-Default.desktop": True,
        "crx_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": False,
        "aeilembjdkfgodjkcjnpgpaenohkicgjda": False,
    }
    for key, expected in cases.items():
        assert (
            engine.globalObject().property("isExcluded").call([QJSValue(key)]).toBool()
            == expected
        ), key
    target = d / "data/plasma/plasmoids/org.novelsavage.plasma.taskaudiofilter"
    shutil.copytree(PKG, target)
    # A deliberately over-broad audio model reproduces the shared Chrome stream.
    # Its purpose is to test which real Task delegates keep/suppress that stream.
    (target / "contents/ui/PulseAudio.qml").write_text("""import QtQuick
 QtObject {
 signal streamsChanged()
 property var fake: QtObject { property bool corked:false;property bool muted:false;property int volume:65536;function mute(){muted=true;}function unmute(){muted=false;} }
 readonly property int minimalVolume:0
 readonly property int normalVolume:65536
 function streamsForAppId(id){return [];}
 function streamsForPid(pid){return [];}
 function streamsForAppName(name){return ["Chrome","Keep","Calendar"].includes(name) ? [fake] : [];}
 function registerPidMatch(name){}
 function hasPidMatch(name){return false;}
 }""")
    task = target / "contents/ui/Task.qml"
    s = task.read_text()
    pos = s.index("    Component.onCompleted: {")
    s = (
        s[:pos]
        + """    Timer { interval:500; running:true; repeat:true; onTriggered: {
 console.warn("AUDIO_RESULT " + JSON.stringify({appId:task.appId,name:task.appName,playing:task.playingAudio,streams:task.audioStreams.length,hasIcon:task.audioStreamIcon!==null,iconVisible:task.audioStreamIcon?.visible ?? false}));
 } }
 """
        + s[pos:]
    )
    task.write_text(s)
    desktop = d / "data/applications"
    desktop.mkdir(parents=True)
    fixtures = [
        ("google-chrome", "Chrome", "google-chrome"),
        ("chrome-eilembjdkfgodjkcjnpgpaenohkicgjd-Default", "Keep", "view-pim-notes"),
        (
            "chrome-kjbdgfilnfhdoflbpgamdcdgpehopbep-Default",
            "Calendar",
            "view-calendar",
        ),
    ]
    for ident, name, icon in fixtures:
        (desktop / (ident + ".desktop")).write_text(
            "[Desktop Entry]\nType=Application\nName="
            + name
            + "\nExec=/bin/true\nIcon="
            + icon
            + "\nStartupWMClass="
            + ident
            + "\n"
        )
    launcher_ids = ["pin-%02d" % i for i in range(18)]
    launcher_ids[7] = "pin,07"
    launchers = ["applications:" + ident + ".desktop" for ident in launcher_ids]
    for ident in launcher_ids:
        (desktop / (ident + ".desktop")).write_text(
            "[Desktop Entry]\nType=Application\nName="
            + ident
            + "\nExec=/bin/true\nIcon=applications-other\n"
        )
    subprocess.run(
        ["kbuildsycoca6", "--noincremental"], capture_output=True, check=True
    )
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        LIBGL_ALWAYS_SOFTWARE="1",
        KWIN_COMPOSE="O2",
        KWIN_WAYLAND_NO_PERMISSION_CHECKS="1",
        KWIN_SCREENSHOT_NO_PERMISSION_CHECKS="1",
    )
    spawn(
        [
            "kwin_wayland",
            "--virtual",
            "--width",
            "1000",
            "--height",
            "600",
            "--socket",
            "audio-test",
            "--no-lockscreen",
            "--no-kactivities",
        ],
        env,
        "kwin.log",
    )
    bus = dbus.SessionBus()
    wait(
        lambda: (
            bus.name_has_owner("org.kde.KWin") and (d / "runtime/audio-test").exists()
        ),
        "KWin failed",
    )
    env.update(
        QT_QPA_PLATFORM="wayland",
        WAYLAND_DISPLAY="audio-test",
        XDG_SESSION_TYPE="wayland",
        XDG_CURRENT_DESKTOP="KDE",
    )
    spawn(["plasmashell", "--no-respawn"], env, "plasma.log")
    wait(lambda: bus.name_has_owner("org.kde.plasmashell"), "Plasma failed")
    wait(
        lambda: json.loads(
            evaluate("print(JSON.stringify(desktops().length>0 && panels().length>0));")
        ),
        "Plasma layout failed",
    )
    time.sleep(1)
    for ident, name, icon in fixtures:
        spawn(
            ["/usr/bin/python3", str(__file__), "fixture", ident, name],
            env,
            name + ".log",
        )
    evaluate(
        'var p=new Panel();p.location="bottom";p.height=48;var w=p.addWidget("org.novelsavage.plasma.taskaudiofilter");w.currentConfigGroup=["General"];w.writeConfig("launchers",[]);print(w.id);'
    )
    log = d / "plasma.log"

    def states():
        result = {}
        for line in log.read_text().splitlines():
            if "AUDIO_RESULT " in line:
                try:
                    v = json.loads(line.split("AUDIO_RESULT ", 1)[1])
                    result[v["name"]] = v
                except ValueError:
                    pass
        return result

    wait(
        lambda: all(n in states() for n in ["Chrome", "Keep", "Calendar"]),
        "Missing task delegates: " + log.read_text()[-1600:],
    )
    time.sleep(3)
    result = states()
    for ident, name, icon in fixtures:
        assert result[name]["appId"] == ident, result
    assert result["Chrome"]["playing"] is True, result
    assert result["Chrome"]["iconVisible"] is True, result
    for name in ["Keep", "Calendar"]:
        assert result[name]["streams"] == 0 and not result[name]["iconVisible"], result
    (d / "result.json").write_text(
        json.dumps(
            {
                "filter_cases": cases,
                "tasks": result,
                "audio_model": "synthetic shared stream; real Task delegates and KWin/Plasma",
            },
            indent=2,
        )
    )
    # Verify the installer can replace/restore an applet, including pin order/settings.
    manage = ROOT.parent / "manage.py"
    evaluate(
        'panels().forEach(function(p){p.widgets().forEach(function(w){if(w.type=="org.novelsavage.plasma.taskaudiofilter" || w.type=="org.kde.plasma.icontasks")w.remove();});});var p=panels()[0];var w=p.addWidget("org.kde.plasma.icontasks");w.currentConfigGroup=["General"];w.writeConfig("launchers",'
        + json.dumps(launchers)
        + ');w.writeConfig("iconSpacing",2);w.writeConfig("showToolTips",false);'
    )
    testenv = dict(env, XDG_STATE_HOME=str(d / "state"), AUDIO_FILTER_TRACE="1")
    before = json.loads(
        subprocess.check_output(
            ["/usr/bin/python3", str(manage), "status"], env=testenv, text=True
        )
    )
    old_index = next(
        w["index"] for w in before if w["type"] == "org.kde.plasma.icontasks"
    )
    subprocess.run(
        ["/usr/bin/python3", str(manage), "install"],
        env=testenv,
        check=True,
        timeout=60,
    )
    after = json.loads(
        subprocess.check_output(
            ["/usr/bin/python3", str(manage), "status"], env=testenv, text=True
        )
    )
    assert (
        next(
            w["index"]
            for w in after
            if w["type"] == "org.novelsavage.plasma.taskaudiofilter"
        )
        == old_index
    )
    subprocess.run(
        ["/usr/bin/python3", str(manage), "restore"],
        env=testenv,
        check=True,
        timeout=60,
    )
    after = json.loads(
        subprocess.check_output(
            ["/usr/bin/python3", str(manage), "status"], env=testenv, text=True
        )
    )
    assert (
        next(w["index"] for w in after if w["type"] == "org.kde.plasma.icontasks")
        == old_index
    )
    final = json.loads(
        evaluate(
            'var a=[];panels().forEach(function(p){p.widgets().forEach(function(w){if(w.type=="org.kde.plasma.icontasks"){w.currentConfigGroup=["General"];a.push({launchers:w.readConfig("launchers",[]),spacing:w.readConfig("iconSpacing",0),tooltips:w.readConfig("showToolTips",true)});}});});print(JSON.stringify(a));'
        )
    )
    assert final == [{"launchers": launchers, "spacing": 2, "tooltips": False}], final
    print(
        "PASS",
        json.dumps(result),
        "install/restore preserves 18 typed launchers, escaped commas, bool/int settings and order",
    )
finally:
    for p in reversed(children):
        if p.poll() is None:
            p.terminate()
    for p in reversed(children):
        try:
            p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            p.kill()
