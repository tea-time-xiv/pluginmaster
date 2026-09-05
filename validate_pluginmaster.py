#!/usr/bin/env python3
"""Sanity-check pluginmaster.json before Dalamud ever sees it.

A malformed repo file breaks the plugin installer for every user of the repo, and the
failure shows up in-game rather than in CI, so check the shapes Dalamud depends on.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

REQUIRED = [
    "Author", "Name", "Punchline", "Description", "InternalName", "AssemblyVersion",
    "ApplicableVersion", "DalamudApiLevel", "IsHide", "IsTestingExclusive",
    "LastUpdate", "DownloadLinkInstall", "DownloadLinkUpdate",
]

# 2020-01-01 .. 2100-01-01, in seconds. Dalamud parses LastUpdate with
# FromUnixTimeSeconds and dates the in-game changelog entry with it, so a value in
# milliseconds silently sorts the entry to the year 57000.
MIN_LAST_UPDATE = 1577836800
MAX_LAST_UPDATE = 4102444800


def main():
    errors = []

    with open(os.path.join(ROOT, "plugins.json"), encoding="utf-8") as fh:
        registry = json.load(fh)
    with open(os.path.join(ROOT, "pluginmaster.json"), encoding="utf-8") as fh:
        plugins = json.load(fh)

    if not isinstance(plugins, list):
        print("pluginmaster.json must be a JSON array")
        return 1

    registered = {e["internalName"] for e in registry}
    listed = {p.get("InternalName") for p in plugins}
    for missing in sorted(registered - listed):
        errors.append("registered plugin missing from pluginmaster.json: " + missing)
    for extra in sorted(listed - registered):
        errors.append("pluginmaster.json lists unregistered plugin: " + str(extra))

    seen = set()
    for plugin in plugins:
        name = plugin.get("InternalName", "<no InternalName>")

        for field in REQUIRED:
            if field not in plugin:
                errors.append(name + ": missing " + field)

        if name in seen:
            errors.append(name + ": duplicate entry")
        seen.add(name)

        version = plugin.get("AssemblyVersion", "")
        if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
            errors.append(name + ": bad AssemblyVersion " + repr(version))

        for field in ("DownloadLinkInstall", "DownloadLinkUpdate"):
            url = plugin.get(field, "")
            if not url.startswith("https://"):
                errors.append(name + ": " + field + " is not https")
            elif version and "/v" + version + "/" not in url:
                errors.append(name + ": " + field + " does not point at v" + version)

        last_update = plugin.get("LastUpdate")
        if not isinstance(last_update, int) or not MIN_LAST_UPDATE <= last_update <= MAX_LAST_UPDATE:
            errors.append(name + ": LastUpdate " + repr(last_update) +
                          " is not a plausible unix-seconds timestamp")

        if not isinstance(plugin.get("DalamudApiLevel"), int):
            errors.append(name + ": DalamudApiLevel must be an int")

        # An empty changelog hides the plugin from the in-game changelog tab entirely.
        if not (plugin.get("Changelog") or "").strip():
            errors.append(name + ": empty Changelog")

    for error in errors:
        print("::error::" + error)

    print(str(len(plugins)) + " plugins checked, " + str(len(errors)) + " problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
