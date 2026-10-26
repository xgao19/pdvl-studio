# macOS Intel distribution

The Intel preview is a native AppKit launcher around the existing local web workbench.
It bundles its own x86_64 Python, Node, pinned Codex SDK/CLI and a Git build for local
repository operations. Unused voice assets are omitted, so their macOS 14 requirement
does not raise the system requirement for this text/file research application. End users do not need Homebrew, Python, Node, npm, Git or a
ChatGPT subscription to install it. Model requests require the user's API key.

## Install

Download `PDVL-Studio-0.2.0-macos-intel.dmg` and `SHA256SUMS` from the
[Intel preview release](https://github.com/xgao19/pdvl-studio/releases/tag/v0.2.0-intel-preview.1).
The existing repository is private; downloads require repository access.

1. Open the DMG and drag **PDVL Studio.app** to **Applications**.
2. Open the app and paste an Ollama API key. The endpoint and dated DeepSeek Flash
   model are prefilled; other compatible providers can be configured explicitly.
3. The app opens the workbench in the default browser. Use the app's menu to reopen
   it, change API settings, locate research data, or quit.

The preview is ad-hoc signed and **not Apple Developer ID signed/notarized**. macOS
may require approval in System Settings → Privacy & Security after an internet
download. Do not disable Gatekeeper or remove quarantine attributes globally.
The app declares macOS 13+ and Intel x86_64; it was tested on macOS 26.6.2 Intel.
Older supported releases still require separate machine/VM validation.

## Private data and configuration

The app's data root is `~/Library/Application Support/PDVL Studio`, separate from
the app bundle. `settings.json` is the single private source for endpoint, model and
API key, created atomically with permissions `0600` inside a `0700` directory.
The launcher passes configuration through stdin, never command-line arguments.
Adapter model registry and Codex TOML are derived from this file and contain no key.
The child environment excludes existing app/API credentials; the SDK's shell snapshots
are disabled and command processes receive only core OS environment variables.

The Codex home and SQLite state live in the app's own data directory. Normal
`~/.codex` config/login files are not changed. API usage goes to the selected provider.
Changing settings stops the old backend and worker, archives partial execution,
then restarts with the new profile. Queued tasks whose credential destination changed
fail before launching a CLI; a new provider key is never sent to an old queued endpoint.
Session continuation still requires the same frozen runtime profile.

Replacing the application preserves the data directory. To back up full continuation
state, quit the app and copy the whole directory. The source checkout's `.local/`
data stays separate and is not automatically migrated or included in the installer.

## Build and verify

Build on an Intel Mac with Python 3.12+ and Apple Command Line Tools:

```bash
python3 scripts/build_macos.py
python3 scripts/smoke_macos.py --app 'dist/PDVL Studio.app'
pytest -q
node --test tests/test_runs_ui.mjs
```

The builder verifies pinned archive SHA-256 values from `packaging/macos/runtimes.json`,
installs hash-locked Python requirements, and uses `npm ci` for the pinned SDK/CLI.
Only explicitly selected source files enter the bundle. Every Mach-O is checked for
x86_64, minimum OS version and dependencies outside Apple's system libraries.
Git's executable path and the entire backend are tested after moving the app into a
new directory containing spaces. The bundle is ad-hoc signed and verified before
creating the DMG and `SHA256SUMS`.

`--live` on the smoke script accepts a settings JSON object **on stdin**, creates only
temporary settings/data, and tests real chat, symbolic execution, cancellation, resume,
archive hashes, evidence citations, restart persistence and shutdown. It makes paid/API
quota-consuming requests; never put key values in arguments, logs or tracked files.

Local validation for this preview: 49 Python tests and 4 Node UI tests passed. The
relocated package completed the full live chain using Ollama's dated DeepSeek Flash
model; foreground heartbeat cancellation stopped execution, continuation restored the
workspace and kept the thread, citations retained original archive hashes, and claims
remained `idea`. Native onboarding save/start and quit were also checked. This is a
bounded local validation, not a claim about every Codex tool or older macOS release.

## Release contents

Publish the DMG and checksum file as GitHub Release assets; do not commit built
applications or runtimes to Git history. `Contents/Resources/build-info.json` records
the source commit, whether the checkout was dirty, lock digest and component versions.
Build the published release from a clean committed checkout.

Licenses and notices are bundled with the app, including the Git corresponding source
archive and build recipe. Dependency license files remain in their respective runtime
and package directories. No API credits, user login, credentials or research database
are part of the distribution.

For future lock updates, compile production requirements with hashes, constrain test
dependencies to that lock, and retain `-r requirements.lock` in `requirements-test.lock`.
Test version updates before changing the pinned runtime manifest or SDK lock.
