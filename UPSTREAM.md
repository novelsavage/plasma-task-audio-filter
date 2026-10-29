# Upstream source

The QML task manager under `plasmoid/` is derived from KDE plasma-desktop v6.6.6:

https://github.com/KDE/plasma-desktop/tree/v6.6.6/applets/taskmanager

Original SPDX copyright and license notices remain in the files. The derived work is distributed under GPL-2.0-or-later; the GPL v2 text is included in LICENSE.

Changes: a Keep/Calendar app-ID filter, icons-only mode, explicit translation domain, a runtime launcher-list handshake, filesystem package metadata, and install/restore tooling. The installed KDE native backend is loaded separately and is not bundled.
