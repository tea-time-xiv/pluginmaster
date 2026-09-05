#!/usr/bin/env python3
"""Generate pluginmaster.json from the latest GitHub release of every plugin in plugins.json.

The plugin's own manifest (shipped inside the release zip) is the source of truth for the
listing text, so a description or tag edit lands here without touching this repo. The
changelog shown in-game (/xlplugins -> Changelog) comes from the plugin repo's CHANGELOG.md
at the release tag: for third-party repos Dalamud only renders the Changelog field of the
installed manifest, and it renders it as plain text.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(ROOT, "plugins.json")
OUTPUT = os.path.join(ROOT, "pluginmaster.json")

# Dalamud draws the changelog with plain ImGui text, so keep it short and unformatted.
MAX_CHANGELOG_LINES = 25
MAX_CHANGELOG_CHARS = 2000

ICON_CANDIDATES = ["images/icon.png", "images/Icon.png", "icon.png"]


def request(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": "tea-time-xiv-pluginmaster",
    })
    # API only: the workflow token is scoped to this repo, and raw.githubusercontent.com
    # rejects it for the plugin repos. Those are public, so they need no auth there.
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def get_json(url):
    return json.loads(request(url))


def try_request(url):
    """Return the body, or None on 404."""
    try:
        return request(url)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def latest_release(repo):
    """Newest published, non-draft, non-prerelease release."""
    releases = get_json(API + "/repos/" + repo + "/releases?per_page=30")
    stable = [r for r in releases
              if not r["draft"] and not r["prerelease"] and r.get("published_at")]
    if not stable:
        raise RuntimeError(repo + ": no published stable release")
    stable.sort(key=lambda r: r["published_at"], reverse=True)
    return stable[0]


def manifest_from_asset(asset_url, internal_name):
    blob = request(asset_url, accept="application/octet-stream")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        wanted = internal_name + ".json"
        names = [n for n in zf.namelist() if os.path.basename(n) == wanted]
        if not names:
            raise RuntimeError(wanted + " not in release asset (has " + str(zf.namelist()) + ")")
        return json.loads(zf.read(names[0]).decode("utf-8-sig"))


def markdown_to_plain(text):
    """Dalamud renders the changelog as plain text, so flatten the markdown we ship."""
    out = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith(("<!--", "|")):        # comments, markdown tables
            continue
        if re.match(r"^\s*Full Changelog:", line):        # auto-generated release footer
            continue
        line = re.sub(r"^\s*#{1,6}\s*(.+?)\s*$", r"\1:", line)   # ### Added -> Added:
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", line)   # [text](url) -> text
        line = re.sub(r"(\*\*|__|`)", "", line)                  # bold / code marks
        line = re.sub(r"^(\s*)[*+]\s+", r"\1- ", line)           # normalise bullets
        out.append(line.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out[:MAX_CHANGELOG_LINES])[:MAX_CHANGELOG_CHARS].strip()


def changelog_section(markdown, version):
    """Pull the '## <version>' section out of a Keep a Changelog style file."""
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        header = re.sub(r"[\[\]]", "", line[3:])
        if re.search(r"(^|\s)" + re.escape(version) + r"($|\s|,)", header):
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip() or None


def resolve_changelog(entry, repo, tag, version, release_body, default_branch):
    path = entry.get("changelogPath", "CHANGELOG.md")
    # The tag is the honest source. The default branch is a fallback for releases cut
    # before the repo had a CHANGELOG.md; the section is keyed by version, so it still
    # describes the released version and not unreleased work.
    for ref in (tag, default_branch):
        raw = try_request("https://raw.githubusercontent.com/" + repo + "/" + ref + "/" + path)
        if not raw:
            continue
        section = changelog_section(raw.decode("utf-8-sig"), version)
        if section:
            return markdown_to_plain(section)
        print("  warn: " + path + "@" + ref + " has no section for " + version, file=sys.stderr)
    if release_body and release_body.strip():
        return markdown_to_plain(release_body)
    return "- " + version


def resolve_icon(entry, repo, tag):
    candidates = [entry["iconPath"]] if entry.get("iconPath") else ICON_CANDIDATES
    for path in candidates:
        url = "https://raw.githubusercontent.com/" + repo + "/" + tag + "/" + path
        if try_request(url) is not None:
            return url
    return None


def build_entry(entry):
    repo = entry["repo"]
    internal_name = entry["internalName"]
    release = latest_release(repo)
    tag = release["tag_name"]

    asset = next((a for a in release["assets"] if a["name"] == entry["asset"]), None)
    if asset is None:
        raise RuntimeError(repo + ": asset " + entry["asset"] + " missing from " + tag +
                           " (has " + str([a["name"] for a in release["assets"]]) + ")")

    manifest = manifest_from_asset(asset["browser_download_url"], internal_name)
    version = manifest.get("AssemblyVersion") or tag.lstrip("v")
    if version != tag.lstrip("v"):
        raise RuntimeError(repo + ": manifest version " + version + " != tag " + tag)
    if manifest.get("InternalName") != internal_name:
        raise RuntimeError(repo + ": manifest InternalName " + str(manifest.get("InternalName")) +
                           " != registry " + internal_name)

    download = asset["browser_download_url"]
    published = datetime.strptime(release["published_at"], "%Y-%m-%dT%H:%M:%SZ")
    published = published.replace(tzinfo=timezone.utc)

    out = OrderedDict()
    out["Author"] = manifest.get("Author", "tea-time-xiv")
    out["Name"] = manifest.get("Name", internal_name)
    out["Punchline"] = manifest.get("Punchline", "")
    out["Description"] = manifest.get("Description", "")
    default_branch = get_json(API + "/repos/" + repo).get("default_branch", "master")
    out["Changelog"] = resolve_changelog(entry, repo, tag, version,
                                         release.get("body") or "", default_branch)
    out["InternalName"] = internal_name
    out["AssemblyVersion"] = version
    out["RepoUrl"] = "https://github.com/" + repo
    out["ApplicableVersion"] = manifest.get("ApplicableVersion", "any")
    out["DalamudApiLevel"] = manifest["DalamudApiLevel"]
    out["IsHide"] = False
    out["IsTestingExclusive"] = False
    out["AcceptsFeedback"] = manifest.get("AcceptsFeedback", True)
    out["DownloadCount"] = 0
    # Dalamud reads LastUpdate as unix *seconds* and sorts the in-game changelog list by it.
    out["LastUpdate"] = int(published.timestamp())
    out["DownloadLinkInstall"] = download
    out["DownloadLinkUpdate"] = download

    if manifest.get("Tags"):
        out["Tags"] = manifest["Tags"]
    if manifest.get("CategoryTags"):
        out["CategoryTags"] = manifest["CategoryTags"]
    icon = resolve_icon(entry, repo, tag)
    if icon:
        out["IconUrl"] = icon

    print("  " + internal_name + " " + version + " (" + published.strftime("%Y-%m-%d") +
          ") changelog=" + str(len(out["Changelog"].splitlines())) + " lines")
    return out


def main():
    with open(REGISTRY, encoding="utf-8") as fh:
        registry = json.load(fh)

    previous = {}
    if os.path.exists(OUTPUT):
        with open(OUTPUT, encoding="utf-8") as fh:
            previous = {e["InternalName"]: e for e in json.load(fh)}

    entries = []
    failures = []
    for entry in registry:
        print("* " + entry["repo"])
        try:
            entries.append(build_entry(entry))
        except Exception as err:  # one broken repo must not wipe the whole listing
            print("  ERROR: " + str(err), file=sys.stderr)
            failures.append(entry["internalName"])

    # A transient API failure must never drop a plugin out of the repo, so reuse whatever
    # the committed file already says for the plugins that failed.
    lost = []
    for internal_name in failures:
        if internal_name in previous:
            print("::warning::kept previous pluginmaster entry for " + internal_name +
                  "; its release could not be read")
            entries.append(OrderedDict(previous[internal_name]))
        else:
            lost.append(internal_name)

    entries.sort(key=lambda e: e["Name"].lower())
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("wrote " + OUTPUT + " (" + str(len(entries)) + " plugins)")
    if lost:
        # No previous entry to fall back on, so the listing really is incomplete.
        print("::error::no release could be read for: " + ", ".join(lost))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
