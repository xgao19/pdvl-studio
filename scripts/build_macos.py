"""Build the self-contained Intel app and DMG from a source allowlist."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / '.local/build-macos-intel'
DIST = ROOT / 'dist'
MANIFEST = ROOT / 'packaging/macos/runtimes.json'
GIT_FLAGS = ['RUNTIME_PREFIX=YesPlease', 'NO_CURL=YesPlease', 'NO_EXPAT=YesPlease',
             'NO_GETTEXT=YesPlease', 'NO_TCLTK=YesPlease', 'NO_PERL=YesPlease',
             'NO_PYTHON=YesPlease', 'NO_RUST=YesPlease']


def run(args, **kwargs):
    print('→ ' + str(args[0]) + ' ' + ' '.join(str(a) for a in args[1:3]), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def download(entry: dict) -> Path:
    path = CACHE / entry['url'].rsplit('/', 1)[1].replace('%2B', '+')
    if not path.is_file():
        with urlopen(entry['url'], timeout=120) as source, path.with_suffix('.part').open('wb') as output:
            shutil.copyfileobj(source, output)
        path.with_suffix('.part').replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('Runtime checksum mismatch: ' + path.name)
    return path


def unpack(entry: dict, name: str) -> Path:
    archive = download(entry)
    destination = CACHE / name
    if not destination.exists():
        temporary = CACHE / (name + '.extracting')
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(temporary, filter='data')
        temporary.rename(destination)
    return destination


def copy_sources(destination: Path):
    """Never recurse over the checkout: private state is outside this allowlist."""
    if json.loads((ROOT / 'configs/desktop.json').read_text()).get('api_key') != '':
        raise ValueError('The distributed desktop preset must contain an empty API key')
    for directory, pattern in [('pdvl', '*.py'), ('web', '*'), ('configs', '*.json')]:
        for source in (ROOT / directory).glob(pattern):
            if not source.is_file() or source.is_symlink():
                raise ValueError('Invalid release source: ' + str(source))
            target = destination / directory / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    worker = destination / 'worker/codex'
    worker.mkdir(parents=True)
    for name in ('index.mjs', 'package.json', 'package-lock.json'):
        shutil.copy2(ROOT / 'worker/codex' / name, worker / name)
    shutil.copy2(ROOT / 'packaging/macos/launch.py', destination / 'launch.py')
    shutil.copy2(ROOT / 'LICENSE', destination / 'LICENSE')


def macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as file:
        return file.read(4) in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')


def audit_bundle(app: Path, minimum_macos: str = '13.0'):
    """Check relocation, architecture and the absence of private source data."""
    for path in app.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(app.resolve()):
            raise ValueError('External bundle symlink: ' + str(path))
        if path.name in ('.env', '.local', 'settings.json', 'auth.json') or path.suffix == '.sqlite3':
            raise ValueError('Private state in release: ' + str(path))
        if macho(path):
            architectures = subprocess.check_output(['lipo', '-archs', str(path)], text=True)
            if 'x86_64' not in architectures.split():
                raise ValueError('Non-Intel Mach-O: ' + str(path))
            linked = subprocess.check_output(['otool', '-L', str(path)], text=True)
            for line in linked.splitlines()[1:]:
                name = line.strip().split(' (', 1)[0]
                if name.startswith('/') and not name.startswith(('/usr/lib/', '/System/Library/')):
                    raise ValueError('Nonportable library dependency: ' + name)
            loads = subprocess.check_output(['otool', '-l', str(path)], text=True)
            for block in loads.split('Load command'):
                if 'cmd LC_BUILD_VERSION' in block or 'cmd LC_VERSION_MIN_MACOSX' in block:
                    version = re.search(r'\b(?:minos|version)\s+(\d+)\.(\d+)', block)
                    if version and tuple(map(int, version.groups())) > tuple(map(int, minimum_macos.split('.'))):
                        raise ValueError('Runtime requires a newer macOS: ' + str(path))


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64' or sys.version_info < (3, 12):
        raise SystemExit('Build on macOS Intel with Python 3.12+ and Apple Command Line Tools.')
    manifest = json.loads(MANIFEST.read_text())
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / 'pdvl/__init__.py').read_text())[1]
    CACHE.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)
    python = unpack(manifest['python'], 'python') / 'python'
    interpreter = python / 'bin/python3.12'
    lock_digest = hashlib.sha256((ROOT / 'requirements.lock').read_bytes()).hexdigest()
    stamp = CACHE / 'python-requirements.sha256'
    if not stamp.is_file() or stamp.read_text() != lock_digest:
        run([interpreter, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps',
             '--only-binary=:all:', '--require-hashes', '-r', ROOT / 'requirements.lock'])
        stamp.write_text(lock_digest)
    node = unpack(manifest['node'], 'node') / ('node-v' + manifest['node']['version'] + '-darwin-x64')
    git_source = unpack(manifest['git'], 'git') / ('git-' + manifest['git']['version'])
    git = CACHE / 'git-portable'
    flags = ['prefix=' + str(git), *GIT_FLAGS]
    with (CACHE / 'git-build.log').open('w') as log:
        run(['make', '-j4', *flags, 'all', 'install'], cwd=git_source, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, 'MACOSX_DEPLOYMENT_TARGET': manifest['minimum_macos']})
    # Git installs many hardlinks; retain one binary when copying across volumes.
    git_binary = git / 'bin/git'
    inode = git_binary.stat().st_ino
    for path in git.rglob('*'):
        if path != git_binary and path.is_file() and not path.is_symlink() and path.stat().st_ino == inode:
            path.unlink()
            path.symlink_to(os.path.relpath(git_binary, path.parent))

    app = DIST / 'PDVL Studio.app'
    shutil.rmtree(app, ignore_errors=True)
    resources = app / 'Contents/Resources'
    source = resources / 'app'
    source.mkdir(parents=True)
    copy_sources(source)
    runtime = resources / 'runtime'
    for name, origin in [('python', python), ('node', node), ('git', git)]:
        shutil.copytree(origin, runtime / name, symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Console entry points contain build-time interpreter paths; only the embedded interpreter is used.
    for path in (runtime / 'python/bin').iterdir():
        if path.name not in ('python3.12', 'python3', 'python'):
            path.unlink()
    binaries = runtime / 'bin'
    binaries.mkdir()
    wrapper = binaries / 'python3'
    wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/../python/bin/python3.12" -s -B "$@"\n')
    wrapper.chmod(0o755)
    (binaries / 'python').symlink_to('python3')
    (binaries / 'node').symlink_to('../node/bin/node')
    git_wrapper = binaries / 'git'
    git_wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/../git/bin/git" "$@"\n')
    git_wrapper.chmod(0o755)
    env = {**os.environ, 'PATH': str(binaries) + ':/usr/bin:/bin:/usr/sbin:/sbin'}
    run([node / 'bin/node', node / 'lib/node_modules/npm/bin/npm-cli.js', 'ci', '--omit=dev',
         '--ignore-scripts', '--no-audit', '--no-fund'], cwd=source / 'worker/codex', env=env)
    # The SDK text/file task API does not use voice. Its optional voice host
    # requires a newer macOS and must not raise this product's system requirement.
    shutil.rmtree(source / 'worker/codex/node_modules/@openai/codex-darwin-x64/vendor/x86_64-apple-darwin/codex-resources/voice')
    licenses = resources / 'licenses'
    licenses.mkdir()
    shutil.copy2(ROOT / 'packaging/macos/CODEX-NOTICE.txt', licenses / 'CODEX-NOTICE.txt')
    shutil.copy2(source / 'worker/codex/node_modules/@openai/codex-sdk/LICENSE', licenses / 'CODEX-LICENSE.txt')
    shutil.copy2(git_source / 'COPYING', licenses / 'GIT-COPYING.txt')
    shutil.copy2(download(manifest['git']), licenses / 'git-corresponding-source.tar.xz')
    shutil.copy2(ROOT / 'scripts/build_macos.py', licenses / 'build_macos.py')
    shutil.copy2(MANIFEST, licenses / 'runtimes.json')
    shutil.copy2(ROOT / 'packaging/macos/THIRD_PARTY_NOTICES.md', licenses / 'THIRD_PARTY_NOTICES.md')
    provenance = {'version': version, 'architecture': 'x86_64', 'runtimes': manifest,
                  'codex_sdk': json.loads((source / 'worker/codex/package.json').read_text())['dependencies']['@openai/codex-sdk'],
                  'python_lock_sha256': lock_digest,
                  'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT))}
    (resources / 'build-info.json').write_text(json.dumps(provenance, indent=2) + '\n')
    macos = app / 'Contents/MacOS'
    macos.mkdir()
    run(['xcrun', 'swiftc', '-module-cache-path', CACHE / 'swift-modules', '-swift-version', '5', '-O', '-target',
         'x86_64-apple-macosx' + manifest['minimum_macos'], '-framework', 'AppKit',
         ROOT / 'packaging/macos/main.swift', '-o', macos / 'PDVL Studio'])
    info = {'CFBundleName': 'PDVL Studio', 'CFBundleDisplayName': 'PDVL Studio',
            'CFBundleIdentifier': 'studio.pdvl.desktop', 'CFBundleExecutable': 'PDVL Studio',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': version, 'CFBundleVersion': version,
            'LSMinimumSystemVersion': manifest['minimum_macos'], 'NSHighResolutionCapable': True}
    with (app / 'Contents/Info.plist').open('wb') as file:
        plistlib.dump(info, file)
    audit_bundle(app, manifest['minimum_macos'])
    with (CACHE / 'codesign.log').open('w') as log:
        for path in resources.rglob('*'):
            if macho(path) and subprocess.run(['codesign', '--verify', str(path)], stdout=log, stderr=log).returncode:
                run(['codesign', '--force', '--sign', '-', str(path)], stdout=log, stderr=log)
        run(['codesign', '--force', '--sign', '-', str(app)], stdout=log, stderr=log)
    run(['codesign', '--verify', '--deep', '--strict', str(app)])
    staging = CACHE / 'dmg'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    run(['ditto', app, staging / app.name])
    (staging / 'Applications').symlink_to('/Applications')
    shutil.copy2(ROOT / 'packaging/macos/安装说明.txt', staging / '安装说明.txt')
    dmg = DIST / f'PDVL-Studio-{version}-macos-intel.dmg'
    run(['hdiutil', 'create', '-volname', 'PDVL Studio', '-srcfolder', staging,
         '-format', 'UDZO', '-ov', dmg])
    (DIST / 'SHA256SUMS').write_text(hashlib.sha256(dmg.read_bytes()).hexdigest() + '  ' + dmg.name + '\n')
    print('Built ' + str(dmg), flush=True)


if __name__ == '__main__':
    main()
