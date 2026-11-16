"""Run as container PID 1 via python -u -c; no runtime source edits."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request

SOURCE_COMMIT = '2439110ac9523cdedbc35b9b55aeeb43607468c1'
SOURCE_URL = 'https://codeload.github.com/HAIC-2026/Millrace-AI/tar.gz/' + SOURCE_COMMIT
SOURCE_SHA256 = 'd0966ffb176f5df8c5b3c83e0138cedfc89067bb32556a53f4b5258a7261dc0f'
CADDY_URL = 'https://github.com/caddyserver/caddy/releases/download/v2.11.9/caddy_2.11.9_linux_amd64.tar.gz'
CADDY_SHA256 = '5b8cb7faf8726a2028ad96a66e54e6e81e8f361bc6175e5d22bbd997cc5177fb'
STATE = Path('/opt/haic-state')
SOURCE = STATE / ('Millrace-AI-' + SOURCE_COMMIT)
ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
       'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
       'XDG_CONFIG_HOME': '/opt/haic-state/caddy-config',
       'XDG_DATA_HOME': '/opt/haic-state/caddy-data'}


def fetch(url, digest, maximum):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum or hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('artifact integrity failure')
    return data


def proxy_config(host):
    return {
        'admin': {'disabled': True},
        'logging': {'logs': {'default': {'level': 'ERROR', 'writer': {'output': 'discard'}}}},
        'apps': {'http': {'servers': {'haic': {
            'listen': [':8080'], 'automatic_https': {'disable': True},
            'routes': [
                {'match': [{'header': {'X-Forwarded-Host': [host]}, 'path': ['/mcp']}], 'handle': [
                    {'handler': 'request_body', 'max_size': 131072},
                    {'handler': 'reverse_proxy', 'upstreams': [{'dial': '127.0.0.1:8765'}],
                     'headers': {'request': {'set': {'Host': [host]}}},
                     'transport': {'protocol': 'http', 'dial_timeout': '5s',
                                   'read_timeout': '90s', 'write_timeout': '90s'}}
                ], 'terminal': True},
                {'match': [{'header': {'X-Forwarded-Host': [host]}, 'path': ['/healthz'], 'method': ['GET']}],
                 'handle': [{'handler': 'static_response', 'status_code': 200,
                             'body': 'ready\n', 'headers': {'Content-Type': ['text/plain']}}],
                 'terminal': True},
                {'handle': [{'handler': 'static_response', 'status_code': 404,
                             'body': 'not found\n'}], 'terminal': True}
            ]
        }}}}
    }


def initialize():
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'haic-host-readiness', 'version': '1'}}}).encode()
    request = urllib.request.Request('http://127.0.0.1:8765/mcp', data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(request, timeout=2) as response:
        result = json.load(response)
    if not result.get('result', {}).get('serverInfo'):
        raise RuntimeError('MCP readiness failure')


def main():
    pod_id = os.environ.get('RUNPOD_POD_ID', '')
    if not re.fullmatch(r'[a-z0-9]{8,40}', pod_id):
        raise RuntimeError('missing or invalid Runpod pod identity')
    host = pod_id + '-8080.proxy.runpod.net'
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    # Every launch verifies and reconstructs public source, including after disk reset.
    with tarfile.open(fileobj=io.BytesIO(fetch(SOURCE_URL, SOURCE_SHA256, 8 * 1024 * 1024))) as archive:
        members = archive.getmembers()
        root = 'Millrace-AI-' + SOURCE_COMMIT
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != root:
                raise RuntimeError('invalid source archive path')
            if not (member.isfile() or member.isdir()):
                raise RuntimeError('unsupported source archive member')
        archive.extractall(STATE, members=members, filter='data')
    binary_archive = fetch(CADDY_URL, CADDY_SHA256, 32 * 1024 * 1024)
    with tarfile.open(fileobj=io.BytesIO(binary_archive)) as archive:
        binary = archive.extractfile('caddy').read()
    caddy = STATE / 'caddy'
    caddy.write_bytes(binary)
    caddy.chmod(0o700)
    venv = STATE / 'venv'
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True, env=ENV)
    python = str(venv / 'bin/python')
    with (STATE / 'install.log').open('w') as log:
        subprocess.run([python, '-m', 'pip', 'install', '--disable-pip-version-check',
            '--no-cache-dir', '--require-hashes', '--no-deps', '-r',
            str(SOURCE / 'haic_mcp/requirements.lock')], check=True, env=ENV,
            stdout=log, stderr=subprocess.STDOUT)
    config = STATE / 'caddy.json'
    config.write_text(json.dumps(proxy_config(host)))
    subprocess.run([str(caddy), 'validate', '--config', str(config)], check=True, env=ENV, cwd=STATE)
    (STATE / 'pins.json').write_text(json.dumps({
        'source_commit': SOURCE_COMMIT, 'source_sha256': SOURCE_SHA256,
        'caddy_sha256': CADDY_SHA256, 'host': host,
        'base_image': 'python@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944'
    }, indent=2) + '\n')
    children = []

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (STATE / 'connector.log').open('w') as log:
        try:
            app = subprocess.Popen([python, '-B', '-m', 'haic_mcp', '--port', '8765',
                '--allowed-host', host, '--allowed-origin', 'https://' + host,
                '--allowed-origin', 'https://chatgpt.com'], cwd=SOURCE, env=ENV,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            children.append(app)
            deadline = time.monotonic() + 60
            while True:
                if app.poll() is not None:
                    raise RuntimeError('connector exited during startup')
                try:
                    initialize()
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('connector readiness timeout')
                    time.sleep(1)
            proxy = subprocess.Popen([str(caddy), 'run', '--config', str(config)], env=ENV, cwd=STATE,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(proxy)
            print(json.dumps({'hosting': 'started', 'source_commit': SOURCE_COMMIT,
                              'url': 'https://' + host + '/mcp'}), flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(1)
            raise RuntimeError('service process exited')
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"hosting":"failed"}', file=sys.stderr, flush=True)
        raise SystemExit(1)
