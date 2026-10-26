# Bundled components

PDVL Studio source is MIT licensed; see app/LICENSE.

- Codex SDK and CLI 0.164.0: Apache-2.0. See CODEX-LICENSE.txt and CODEX-NOTICE.txt.
  https://github.com/openai/codex/tree/rust-v0.164.0
  Unused optional voice resources are omitted; text/file task executables are retained.
- CPython portable distribution: Python Software Foundation and bundled component licenses.
  See runtime/python/LICENSE* and licenses retained in that distribution.
  https://github.com/astral-sh/python-build-standalone/releases/tag/20260901
- Node.js: MIT and bundled dependency notices, retained in runtime/node/LICENSE.
  https://nodejs.org/dist/v22.23.4/
- Git: GPL-2.0. See GIT-COPYING.txt. The complete unmodified corresponding source is
  included as git-corresponding-source.tar.xz. build_macos.py records the build flags.
  This build provides local repository operations; HTTP transport, Perl/Tcl/Python
  scripts, translations and Rust components are disabled.
- Python dependencies: individual licenses are retained in their *.dist-info directories.
- Node dependencies: individual licenses are retained in their package directories.

Runtime versions and archive SHA-256 values are recorded in runtimes.json.
The app does not include model weights, API usage credits, a ChatGPT subscription,
or any user's credentials or research database.
