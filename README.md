# Tea Time plugin repository

The Dalamud repo URL for players:

```
https://raw.githubusercontent.com/tea-time-xiv/pluginmaster/master/pluginmaster.json
```

## How publishing works

`pluginmaster.json` is **generated**. Do not edit it by hand — the next run overwrites it.

1. A plugin repo builds, tags and publishes a GitHub release with its `<InternalName>.zip`.
   That is the whole of its publishing duty: it holds **no credential for this repo**, and
   this repo holds none for it.
2. [`.github/workflows/publish.yml`](.github/workflows/publish.yml) runs every 15 minutes,
   and on demand, executing [`build_pluginmaster.py`](build_pluginmaster.py). For every
   plugin in [`plugins.json`](plugins.json) it:
   - reads the latest published, non-draft, non-prerelease release,
   - downloads the release asset and reads `<InternalName>.json` **from inside the zip** —
     that manifest is the source of truth for author, name, punchline, description, tags and
     API level, so plugin text is edited in the plugin repo and nowhere else,
   - reads `CHANGELOG.md` at the release tag and lifts the section for the released version
     into the `Changelog` field,
   - writes `LastUpdate` from the release timestamp, in unix **seconds**.
3. [`validate_pluginmaster.py`](validate_pluginmaster.py) checks the result, and the file is
   committed only if it actually changed.

### Publishing a release right now

The schedule catches a new release within 15 minutes on its own. To not wait:

- **Actions tab** -> *Publish pluginmaster* -> **Run workflow**, or
- `gh workflow run publish.yml -R tea-time-xiv/pluginmaster`

The `reason` input is free text and shows up in the run list, so a run is still explicable
months later.

Only one workflow ever writes the file, and it is serialised with a `concurrency` group, so
a manual run and a scheduled one cannot clobber each other — the failure mode the old
per-repo "clone, edit, push" scripts had.

> GitHub disables scheduled workflows in a public repo after **60 days without repository
> activity**. This job only commits when something changed, so a long quiet stretch can switch
> the cron off; the Actions tab says so, and the Run workflow button brings it back.

## In-game changelogs

For a third-party repo, Dalamud shows **one** changelog entry per installed plugin: the
`Changelog` field of the manifest it installed, dated by `LastUpdate`
(`DalamudChangelogManager.ReloadChangelogAsync`). There is no version history and no markdown
rendering. So each plugin's `CHANGELOG.md` section should be a handful of plain `-` bullets
describing that version, and an empty `Changelog` hides the plugin from the changelog tab
entirely — [`validate_pluginmaster.py`](validate_pluginmaster.py) fails the build on one.

## Adding a plugin

Append one object to `plugins.json`:

```json
{ "repo": "tea-time-xiv/myplugin", "internalName": "MyPlugin", "asset": "MyPlugin.zip" }
```

Optional keys: `changelogPath` (default `CHANGELOG.md`), `iconPath` (default: the first of
`images/icon.png`, `images/Icon.png`, `icon.png` that exists at the tag).

Then run the workflow manually, or wait for the cron. The plugin repo needs no publishing
code, and no secret, beyond the release itself.

## Running it locally

```bash
python build_pluginmaster.py && python validate_pluginmaster.py
```

`GITHUB_TOKEN` is optional locally (it only raises the API rate limit).
