"""Separately verified candidate evidence; does not modify the runtime packet."""
import hashlib
import json
from pathlib import Path

# This pins the manifest itself, in addition to its constituent file hashes.
MANIFEST_SHA256 = "8bf76f4b133a7dcc5585704d335953350b12802768addd42651eeb07efeb82ee"


def metadata_records(root):
    root = Path(root)
    files = sorted((p for p in root.rglob('*') if p.is_file() and p != root / 'MANIFEST.json'),
                   key=lambda p: p.relative_to(root).as_posix().encode('utf-8'))
    if any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('metadata must not contain symlinks')
    return [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]


def metadata_id(records):
    lines = ''.join(f"{r['sha256']}  {r['bytes']}  {r['path']}\n" for r in records)
    return 'sha256:' + hashlib.sha256(lines.encode('utf-8')).hexdigest()


class CandidateMetadata:
    def __init__(self, metadata_dir, manifest_sha256=MANIFEST_SHA256):
        self.root = Path(metadata_dir).resolve()
        raw = (self.root / 'MANIFEST.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest_sha256:
            raise ValueError('candidate metadata manifest pin mismatch')
        manifest = json.loads(raw)
        records = metadata_records(self.root)
        if manifest != {'metadata_snapshot_id': metadata_id(records), 'files': records}:
            raise ValueError('candidate metadata files or identity mismatch')
        self.metadata_snapshot_id = manifest['metadata_snapshot_id']
        self._paths = {r['path'] for r in records}

    def has_path(self, relative):
        return relative in self._paths

    def read_json(self, relative):
        if relative not in self._paths:
            raise ValueError('metadata path not admitted')
        return json.loads((self.root / relative).read_text(encoding='utf-8'))

    def combined_snapshot_id(self, data_snapshot_id):
        obj = {'data_snapshot_id': data_snapshot_id, 'metadata_snapshot_id': self.metadata_snapshot_id}
        raw = json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        return 'sha256:' + hashlib.sha256(raw).hexdigest()
