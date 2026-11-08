"""Shared local test helpers. Fresh runs never overwrite archived evidence."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def new_run(label='test'):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT / 'runs' / f'{stamp}_{label}_{uuid.uuid4().hex[:6]}'
    folder.mkdir(parents=True, exist_ok=False)
    work = folder / 'work'
    shutil.copytree(ROOT / 'src', work)
    return folder, work


def execute(command, folder, log, env=None, timeout=600):
    with (folder / log).open('w', encoding='utf-8') as output:
        result = subprocess.run([str(x) for x in command], cwd=folder, env=env,
                                stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}; see {folder / log}')


def find_tool(name, variable):
    selected = os.environ.get(variable) or shutil.which(name)
    if not selected and variable == 'JAVA':
        home = os.environ.get('JAVA_HOME')
        if home:
            selected = str(Path(home) / 'bin' / ('java.exe' if os.name == 'nt' else 'java'))
    if not selected:
        raise RuntimeError(f'Install {name} or set {variable} to its executable path')
    return Path(selected).resolve()


def verify_recorded():
    manifest = json.loads((ROOT / 'provenance/manifest.json').read_text(encoding='utf-8'))
    count = 0
    for item in manifest['files']:
        path = ROOT / item['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError(f'Package file changed: {item["path"]}')
        count += 1
    return count


def finish(folder, result):
    result['physical_measurements'] = False
    result['run_directory'] = str(folder)
    (folder / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
