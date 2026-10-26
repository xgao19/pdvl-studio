"""macOS launcher backend: private configuration, one server and one worker."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from .config import ROOT, home
from .db import init_db


def settings_path() -> Path:
    return home() / 'settings.json'


def desktop_lock():
    lock = (home() / 'desktop.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise
    return lock


def validate_settings(settings: dict) -> dict:
    if set(settings) != {'api_key', 'base_url', 'model'}:
        raise ValueError('请填写 API key、API 地址和模型。')
    if any(not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value)
           for value in settings.values()):
        raise ValueError('配置不能为空或包含控制字符。')
    settings = {key: value.strip() for key, value in settings.items()}
    url = urlsplit(settings['base_url'])
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or not (url.scheme == 'https' or url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('API 地址须为 HTTPS，或本机 HTTP 地址；不能包含密码、查询参数或片段。')
    settings['base_url'] = settings['base_url'].rstrip('/')
    return settings


def save_settings(settings: dict):
    settings = validate_settings(settings)
    directory = home()
    directory.chmod(0o700)
    with desktop_lock():
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as file:
            json.dump(settings, file, ensure_ascii=False)
        try:
            os.chmod(file.name, 0o600)
            os.replace(file.name, settings_path())
        finally:
            Path(file.name).unlink(missing_ok=True)


def apply_settings(settings: dict):
    """Generate non-secret adapter files from one private settings document."""
    settings = validate_settings(settings)
    os.environ.update(CUSTOM_API_KEY=settings['api_key'], CUSTOM_API_BASE=settings['base_url'],
                      CUSTOM_MODEL=settings['model'], PDVL_CODEX_ENABLED='1',
                      PDVL_MODELS_FILE=str(home() / 'models.json'))
    alias = 'configured-api'
    registry = {mode: alias for mode in ('discuss', 'investigate', 'verify', 'write')}
    registry['models'] = [{'id': alias, 'provider': 'custom', 'model': settings['model'],
                           'title': settings['model'], 'api': 'chat_completions', 'effort': None}]
    (home() / 'models.json').write_text(json.dumps(registry), encoding='utf-8')
    directory = home() / 'codex'
    directory.mkdir(mode=0o700, exist_ok=True)
    config = directory / 'config.toml'
    config.write_text(f'''model = {json.dumps(settings['model'], ensure_ascii=False)}
model_provider = "pdvl_api"
cli_auth_credentials_store = "ephemeral"
[features]
shell_snapshot = false
[shell_environment_policy]
inherit = "core"
[model_providers.pdvl_api]
name = "PDVL API"
base_url = {json.dumps(settings['base_url'], ensure_ascii=False)}
env_key = "CUSTOM_API_KEY"
wire_api = "responses"
requires_openai_auth = false
''', encoding='utf-8')
    config.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description='PDVL desktop backend')
    parser.add_argument('--configure', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    os.environ.setdefault('PDVL_HOME', str(Path.home() / 'Library/Application Support/PDVL Studio'))
    if args.configure:
        try:
            save_settings(json.load(sys.stdin))
        except BlockingIOError:
            raise SystemExit('请先退出正在运行的 PDVL Studio，再修改 API 配置。') from None
        except (ValueError, TypeError) as error:
            raise SystemExit(str(error)) from None
        return
    # Keep updates and multiple app copies from starting competing workers.
    try:
        lock = desktop_lock()
    except BlockingIOError:
        print('PDVL_READY ' + (home() / 'desktop.url').read_text().strip(), flush=True)
        return
    try:
        settings = json.loads(settings_path().read_text(encoding='utf-8'))
        apply_settings(settings)
    except (OSError, ValueError, TypeError):
        lock.close()
        raise SystemExit('请在 PDVL Studio 中填写有效的 API 配置。') from None

    import uvicorn
    init_db()
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    os.environ['PDVL_PORT'] = str(port)
    url = f'http://127.0.0.1:{port}/'
    (home() / 'desktop.url').write_text(url, encoding='utf-8')
    worker = subprocess.Popen([sys.executable, '-m', 'pdvl.cli', 'worker'], cwd=ROOT,
                              env=os.environ.copy(), start_new_session=True)

    def stop_worker():
        if worker.poll() is None:
            worker.send_signal(signal.SIGTERM)
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()

    class DesktopServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            stop_worker()
            super().handle_exit(sig, frame)

    server = DesktopServer(uvicorn.Config('pdvl.api:app', host='127.0.0.1', port=port,
                                          access_log=False, timeout_graceful_shutdown=5))
    def request_exit(sig, frame):
        server.should_exit = True
    # Uvicorn replays captured signals to the previous handler. Keep that replay
    # graceful so our finally block can remove runtime markers and close the lock.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_exit)
    print('PDVL_READY ' + url, flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        stop_worker()
        sock.close()
        (home() / 'desktop.url').unlink(missing_ok=True)
        lock.close()


if __name__ == '__main__':
    main()
