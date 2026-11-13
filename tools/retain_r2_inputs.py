#!/usr/bin/env python3
"""Install or verify complete retained historical inputs. Never downloads sources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_app import load_core


def verify(root):
    inventory = json.loads((ROOT / 'docs/R2-INPUTS.json').read_text())
    for row in inventory['files']:
        path = root / row['path']
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symbolic R2 input: ' + row['path'])
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('R2 input hash mismatch: ' + row['path'])
    core = load_core('r2', root)
    return {'input_profile':'r2', 'files':len(inventory['files']),
            'data_snapshot_id':core.snapshot_id,
            'metadata_snapshot_id':core.metadata.metadata_snapshot_id,
            'combined_snapshot_id':core.metadata.combined_snapshot_id(core.snapshot_id)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-dir', type=Path, help='Existing complete retained R2 release/input directory')
    p.add_argument('--output', type=Path, help='New private directory, must not exist')
    p.add_argument('--check', type=Path, help='Verify an already installed private input directory')
    args = p.parse_args()
    if args.check:
        if args.from_dir or args.output:
            p.error('--check cannot be combined with installation')
        print(json.dumps(verify(args.check.resolve()), sort_keys=True))
        return
    if not args.from_dir or not args.output:
        p.error('Use --from-dir and --output, or --check')
    source, target = args.from_dir.resolve(), args.output.resolve()
    if target.exists():
        p.error('--output must not exist')
    if target == ROOT or ROOT in target.parents:
        p.error('Retained inputs must stay outside the public source directory')
    verify(source)
    rows = json.loads((ROOT / 'docs/R2-INPUTS.json').read_text())['files']
    target.mkdir(parents=True, mode=0o700)
    try:
        for row in rows:
            dest = target / row['path']
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source / row['path'], dest)
            dest.chmod(0o600)
        result = verify(target)
    except Exception:
        shutil.rmtree(target)
        raise
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
