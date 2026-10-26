"""Relocate the Intel app, test its own runtimes, optionally exercise a real API.

For --live, provide {api_key, base_url, model} on stdin. Never put keys in arguments.
Temporary settings, research state and the copied app are removed when the test ends.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

import httpx


def wait_run(api, rid, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = api.get('/runs/' + rid)
        response.raise_for_status()
        run = response.json()
        if run['state'] not in ('queued', 'running', 'cancelling'):
            return run
        time.sleep(.25)
    raise RuntimeError('Timed out waiting for packaged Codex')


def post(api, path, payload):
    response = api.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def start(python, launcher, env, log):
    proc = subprocess.Popen([python, launcher], env=env, stdout=subprocess.PIPE,
                            stderr=log, text=True, start_new_session=True)
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        if not selector.select(20):
            proc.terminate(); proc.wait(timeout=20)
            raise RuntimeError('Packaged backend did not start')
    line = proc.stdout.readline().strip()
    if not line.startswith('PDVL_READY http://127.0.0.1:'):
        proc.wait(timeout=20)
        raise RuntimeError('Unexpected packaged startup result')
    return proc, line.removeprefix('PDVL_READY ').rstrip('/')


def stop(proc):
    children = subprocess.run(['pgrep', '-P', str(proc.pid)], capture_output=True, text=True).stdout.split()
    proc.terminate()
    proc.wait(timeout=25)
    assert proc.returncode == 0, 'Backend did not complete graceful shutdown'
    proc.stdout.close()
    for pid in children:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            continue
        raise AssertionError('Worker survived application shutdown')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    settings = json.load(sys.stdin) if args.live else {
        'api_key': 'offline-package-test', 'base_url': 'https://ollama.com/v1', 'model': 'deepseek-v4.1-flash:1017'}
    with tempfile.TemporaryDirectory(prefix='PDVL Intel relocation ') as directory:
        root = Path(directory)
        app = root / 'Moved Application/PDVL Studio.app'
        subprocess.run(['ditto', args.app.resolve(), app], check=True)
        resources = app / 'Contents/Resources'
        binary = resources / 'runtime/bin'
        python = binary / 'python3'
        launcher = resources / 'app/launch.py'
        state = root / 'Research Data'
        env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG') if key in os.environ}
        env.update(PATH=str(binary) + ':/usr/bin:/bin:/usr/sbin:/sbin', PDVL_HOME=str(state),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        subprocess.run([python, '-c', 'import sys, sympy, fastapi, ssl, sqlite3; assert "/runtime/python" in sys.base_prefix'],
                       env=env, check=True)
        subprocess.run([binary / 'node', '--version'], env=env, check=True)
        executable_path = subprocess.check_output([binary / 'git', '--exec-path'], env=env, text=True).strip()
        assert Path(executable_path).is_dir() and Path(executable_path).is_relative_to(resources / 'runtime/git')
        subprocess.run([python, launcher, '--configure'], input=json.dumps(settings), text=True, env=env, check=True)
        assert state.stat().st_mode & 0o777 == 0o700
        assert (state / 'settings.json').stat().st_mode & 0o777 == 0o600
        with (root / 'backend.log').open('w') as log:
            proc, url = start(python, launcher, env, log)
            report = {'live': args.live, 'relocated': True, 'portable_git': True}
            document = None
            try:
                with httpx.Client(base_url=url + '/api', timeout=90) as api:
                    assert api.get('/health').json()['codex_enabled'] is True
                    assert api.get('/models').json()['codex']['model'] == settings['model']
                    assert api.get('/health', headers={'Origin': 'https://untrusted.example'}).status_code == 403
                    # An already-running app owns the data lock; another copy must not rewrite adapters.
                    original = (state / 'codex/config.toml').read_bytes()
                    other = subprocess.run([python, launcher], env=env, capture_output=True, text=True, timeout=15)
                    assert other.returncode == 0 and url in other.stdout
                    assert (state / 'codex/config.toml').read_bytes() == original
                    if args.live:
                        pid = post(api, '/projects', {'title': 'macOS Intel 安装包实测'})['id']
                        claim = post(api, f'/projects/{pid}/claims', {'title': '条件符号恒等式',
                            'statement': '共享 log(mu) 项的差对 log(mu) 求导为零；额外 epsilon 项给出非零负控。',
                            'assumptions': ['mu>0', '其他参数不依赖 mu']})
                        response = api.post(f'/projects/{pid}/chat', json={'message': '请只回复一句：安装包连接正常。'})
                        response.raise_for_status()
                        reply = json.loads(response.text.splitlines()[-1])
                        assert reply['answer']
                        prompt = ('只在当前工作目录工作，禁止联网和读取工作区外文件。创建 check.py，用 SymPy '
                            '令 mu>0，F=a*log(mu)+b，G=F+C，a,b,C,epsilon 均不依赖 mu。'
                            '计算 simplify(mu*diff(G-F,mu)) 并 assert==0；对 Gbad=G+epsilon*log(mu) '
                            '同样求导并 assert==epsilon。只断言 CUSTOM_API_KEY 不在 os.environ 中，禁止读取或输出环境变量值。'
                            '实际运行 python3 check.py，保存 result.json，字段 zero="0", negative_control="epsilon"。'
                            '简短保存 findings.md 和 derivation.md 后结束。')
                        run = post(api, f'/projects/{pid}/runs', {'title': '安装包符号验证', 'question': prompt})
                        completed = wait_run(api, run['id'])
                        assert completed['state'] == 'completed', completed['state']
                        archived = api.get('/runs/' + run['id'] + '/artifacts').json()
                        hashes = {a['id']: a['sha256'] for a in archived}
                        artifact = next(a for a in archived if a['name'] == 'workspace/result.json')
                        assert json.loads(api.get('/artifacts/' + artifact['id']).content)['negative_control'] == 'epsilon'
                        evidence = post(api, f'/projects/{pid}/evidence', {'claim_id': claim['id'], 'artifact_id': artifact['id'],
                            'kind': 'derivation', 'verdict': 'supporting', 'description': '安装包实际执行的限定符号检查；不建立一般物理结论。'})
                        doc = post(api, f'/projects/{pid}/documents', {'title': '安装包验证记录',
                            'text': '该条件代数恒等式有脚本与负控记录。 [evidence:' + evidence['id'] + ']'})
                        document = doc['document']['id']
                        assert doc['revisions'][0]['sources'][0]['run_id'] == run['id']
                        assert api.get(f'/projects/{pid}/claims').json()[0]['status'] == 'idea'
                        control = post(api, '/runs/' + run['id'] + '/continue', {'message':
                            '现在测试取消：创建 checkpoint.py，写 ready.txt=ready，每0.2秒把 time.time() 写入 heartbeat.txt，'
                            '循环120秒。用前台 python3 checkpoint.py 实际运行，等待用户取消，不要缩短时长或改后台。'
                            '不读取环境变量或凭据，不联网，不访问工作区外文件。'})
                        heartbeat = state / 'runs' / control['id'] / 'workspace/heartbeat.txt'
                        submitted, deadline = time.time(), time.monotonic() + 150
                        while time.monotonic() < deadline:
                            try:
                                pulse = float(heartbeat.read_text().strip())
                            except (OSError, ValueError):
                                pulse = 0
                            if pulse > submitted:
                                post(api, '/runs/' + control['id'] + '/cancel', {})
                                break
                            time.sleep(.1)
                        else:
                            raise RuntimeError('No live foreground heartbeat')
                        assert wait_run(api, control['id'], 15)['state'] == 'cancelled'
                        pulse = heartbeat.read_bytes(); time.sleep(.6)
                        assert heartbeat.read_bytes() == pulse
                        resumed = post(api, '/runs/' + control['id'] + '/continue', {'message':
                            '上轮已取消。验证新工作目录恢复了 ready.txt，内容strip后为ready；实际重跑 python3 check.py，'
                            '确认 result.json 正例0和反例epsilon，保存 resume.json 含 restored=true。不要运行 checkpoint.py，不要sleep，'
                            '不读取环境变量或凭据，不联网，不访问工作区外文件，完成即结束。'})
                        final = wait_run(api, resumed['id'])
                        assert final['state'] == 'completed' and final['thread_id'] == completed['thread_id']
                        sources = api.get('/documents/' + document).json()['revisions'][0]['sources']
                        assert sources[0]['artifact_id'] == artifact['id']
                        for aid, digest in hashes.items():
                            assert hashlib.sha256(api.get('/artifacts/' + aid).content).hexdigest() == digest
                        assert not list((state / 'codex').glob('shell_snapshots/*.sh'))
                        report.update(chat=True, codex=True, cancel=True, resume=True, source_chain=True)
                    for file in resources.rglob('*'):
                        if file.is_file() and not file.is_symlink():
                            assert settings['api_key'].encode() not in file.read_bytes()
            finally:
                stop(proc)
            assert not (state / 'desktop.url').exists()
            proc, url = start(python, launcher, env, log)
            try:
                with httpx.Client(base_url=url + '/api', timeout=10) as api:
                    assert api.get('/health').json()['ok'] is True
                    if document:
                        assert api.get('/documents/' + document).json()['revisions'][0]['sources']
            finally:
                stop(proc)
            assert not (state / 'desktop.url').exists()
            report.update(restart_preserves_data=True, clean_shutdown=True)
            print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
