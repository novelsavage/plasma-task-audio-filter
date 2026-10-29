// SPDX-License-Identifier: GPL-2.0-or-later
.pragma library

// Chrome's extension IDs remain stable across desktop-file/profile suffixes.
var excludedChromeAppIds = [
    "eilembjdkfgodjkcjnpgpaenohkicgjd", // Google Keep
    "kjbdgfilnfhdoflbpgamdcdgpehopbep"  // Google Calendar
];

function isExcluded(appId) {
    if (typeof appId !== "string" || !appId) return false;
    return excludedChromeAppIds.some(function(id) {
        // Accept the app-id itself, crx_<id>, and Chrome's desktop-file ID.
        var pattern = new RegExp("(^|[^a-p])" + id + "($|[^a-p])");
        return pattern.test(appId.toLowerCase());
    });
}
