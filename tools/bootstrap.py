"""Fetch only pinned public dependencies listed in dependencies.lock.json."""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def bootstrap(group=None):
    specs = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8'))
    for item in specs:
        if group and item.get('group') != group:
            continue
        target = ROOT / item['target']
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'Pinned public research dependency'})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise RuntimeError(f'Dependency checksum mismatch: {item["target"]}')
            target.write_bytes(data)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError(f'Existing dependency checksum mismatch: {item["target"]}')
        if item.get('extract'):
            destination = ROOT / item['extract']
            marker = destination / '.extracted-by-lab'
            if not marker.exists():
                destination.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(target) as archive:
                    for member in archive.infolist():
                        path = (destination / member.filename).resolve()
                        if not path.is_relative_to(destination.resolve()):
                            raise RuntimeError('Archive path escapes dependency directory')
                    archive.extractall(destination)
                marker.write_text(item['sha256'], encoding='ascii')
    return ROOT / '.deps'


if __name__ == '__main__':
    bootstrap()
    print('Pinned public dependencies ready.')
