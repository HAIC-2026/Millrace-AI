#!/usr/bin/env python3
"""Build or check the separately pinned candidate metadata manifest."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from districtbrief.candidate_metadata import CandidateMetadata, metadata_id, metadata_records
root = Path(__file__).resolve().parents[1] / 'candidate-metadata'
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if args.check:
    from districtbrief.public_packet import public_metadata
    meta = public_metadata(root)
    print(meta.metadata_snapshot_id)
else:
    records = metadata_records(root)
    manifest = {'metadata_snapshot_id': metadata_id(records), 'files': records}
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (root / 'MANIFEST.json').write_bytes(raw)
    print('manifest sha256:', hashlib.sha256(raw).hexdigest())
    print('metadata snapshot:', manifest['metadata_snapshot_id'])
