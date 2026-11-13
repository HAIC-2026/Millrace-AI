#!/usr/bin/env python3
"""Build a new review candidate from a completed acquisition; never changes runtime."""
import argparse
import hashlib
import json
import math
import pathlib
import shutil
import tempfile
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import compile_statistics as compiler
from districtbrief.geography import GeographyIndex


def validate_geometry(ident, data, record):
    parts = ident.split('_')
    session, chamber = int(parts[1]), parts[2]
    expected = 51 if chamber == 'house' else 25
    if data.get('type') != 'FeatureCollection' or len(data.get('features', [])) != expected:
        raise ValueError('invalid geometry feature count')
    reader = GeographyIndex.__new__(GeographyIndex)
    codes = set()
    for feature in data['features']:
        item, _ = reader._record(session, chamber, ident, {'url':record['url'], 'sha256':record['sha256']}, feature)
        if item['code'] in codes:
            raise ValueError('duplicate district code')
        codes.add(item['code'])
    if codes != {f'{i:03}' for i in range(1, expected + 1)}:
        raise ValueError('missing or out-of-range district code')

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture', type=pathlib.Path)
    ap.add_argument('destination', type=pathlib.Path, help='new, non-existing review directory')
    args = ap.parse_args()
    if not __debug__:
        raise SystemExit('Run without python -O: compiler validation uses assertions')
    report = json.loads((args.capture / 'acquisition-report.json').read_text())
    allowed = json.loads((pathlib.Path(__file__).parent / 'allowlist.json').read_text())['sources']
    records = {r['source_id']: r for r in report['sources']}
    if not report['complete'] or len(report['sources']) != len(allowed) or set(records) != {s['source_id'] for s in allowed}:
        raise ValueError('capture incomplete or source set differs from allowlist')
    for s in allowed:
        r = records[s['source_id']]
        if r['url'] != s['url']:
            raise ValueError('source URL differs from allowlist')
        suffix = '.xlsx' if s['source_id'].startswith('dbedt_') else '.json'
        body = (args.capture / 'raw' / (s['source_id'] + suffix)).read_bytes()
        if len(body) != r['bytes'] or hashlib.sha256(body).hexdigest() != r['sha256']:
            raise ValueError('capture bytes do not match report')
    expected_files = {s['source_id'] + ('.xlsx' if s['source_id'].startswith('dbedt_') else '.json') for s in allowed}
    raw_files = list((args.capture / 'raw').iterdir())
    if {p.name for p in raw_files} != expected_files or any(p.is_symlink() or not p.is_file() for p in raw_files):
        raise ValueError('unexpected, missing or symbolic capture files')
    args.destination.mkdir(parents=False, exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        packet = pathlib.Path(tmp)
        raw = packet / 'data/statistics/raw'; raw.mkdir(parents=True)
        source_manifest = []
        files = []
        for s in allowed:
            ident = s['source_id']; r = records[ident]
            if ident.startswith('dbedt_'):
                dest = raw / (ident.rsplit('_', 1)[-1] + '.xlsx')
            elif ident.startswith('acs_'):
                dest = raw / (ident.split('_')[2] + '_metadata.json')
            else:
                continue
            shutil.copyfile(args.capture / 'raw' / (ident + dest.suffix), dest)
            rel = str(dest.relative_to(packet)); files.append({'path': rel, 'bytes': r['bytes'], 'sha256': r['sha256']})
            source_manifest.append({'source_id': ident, 'url': s['url'], 'sha256': r['sha256'], 'retrieved_at_utc': r['captured_at_utc']})
        manifest_path = packet / 'data/statistics/manifest.json'
        manifest_path.write_text(json.dumps(source_manifest))
        b = manifest_path.read_bytes(); files.append({'path': str(manifest_path.relative_to(packet)), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()})
        compiler.PACKET = packet
        observations = compiler.compile_observations({'files': files})
        rows = json.loads(observations)['observations']
        for row in rows:
            for key in ('estimate', 'margin_of_error'):
                value = row[key]
                if value is not None and (not isinstance(value, (float, int)) or not math.isfinite(value)):
                    raise ValueError(f'nonfinite statistic: {row["observation_id"]} {key}')
                if value is None and not row['annotation' if key == 'estimate' else 'moe_annotation']:
                    raise ValueError('missing value must carry its annotation')
        (args.destination / 'statistics-observations.json').write_bytes(observations)
    outputs = [{'path':'statistics-observations.json','sha256':hashlib.sha256(observations).hexdigest(),'observations':len(json.loads(observations)['observations'])}]
    for ident, r in records.items():
        if ident.endswith('_geometry'):
            data = json.loads((args.capture / 'raw' / (ident + '.json')).read_bytes())
            validate_geometry(ident, data, r)
            # Preserve source geometry/properties exactly; serialize deterministically.
            body = (json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
            name = ident + '.geojson'; (args.destination / name).write_bytes(body)
            outputs.append({'path':name,'sha256':hashlib.sha256(body).hexdigest(),'features':len(data['features'])})
    (args.destination / 'review-manifest.json').write_text(json.dumps({'schema':'ia1-refresh-candidate/1','status':'unreviewed; do not install automatically','inputs':list(records.values()),'outputs':outputs},indent=2)+'\n')
    print(json.dumps(outputs,indent=2))

if __name__ == '__main__': main()
