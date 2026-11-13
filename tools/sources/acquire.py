#!/usr/bin/env python3
"""Capture only reviewed official sources into a new staging directory.

Raw source bytes are data, never code or instructions. See README.md before use.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import pathlib
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'allowlist.json').read_text())

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect rejected; review and update allowlist')


def fetch(source, raw, manual_dir):
    ident = source['source_id']
    try:
        if ident.startswith('dbedt_'):
            if manual_dir is None:
                raise ValueError('manual State workbook required; automated access disabled')
            path = manual_dir / (ident + '.xlsx')
            if path.stat().st_size > CONFIG['max_bytes']:
                raise ValueError('file exceeds size limit')
            body = path.read_bytes()
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            req = urllib.request.Request(source['url'], headers={'User-Agent': 'DistrictBrief-source-review/1'})
            with urllib.request.build_opener(NoRedirect).open(req, timeout=CONFIG['timeout_seconds']) as resp:
                body = resp.read(CONFIG['max_bytes'] + 1)
                if len(body) > CONFIG['max_bytes']:
                    raise ValueError('response exceeds size limit')
                content_type = resp.headers.get('Content-Type', '')
        if ident.startswith('dbedt_'):
            import io
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                if sum(i.file_size for i in z.infolist()) > 100_000_000:
                    raise ValueError('expanded XLSX exceeds size limit')
                if 'xl/workbook.xml' not in z.namelist() or z.testzip():
                    raise ValueError('invalid XLSX')
            suffix = '.xlsx'
            details = {'kind': 'xlsx'}
        else:
            data = json.loads(body)
            suffix = '.json'
            if ident.endswith('_geometry'):
                expected = 51 if '_house_' in ident else 25
                if data.get('type') != 'FeatureCollection' or len(data.get('features', [])) != expected:
                    raise ValueError('unexpected GeoJSON collection/count')
                for feature in data['features']:
                    if feature.get('type') != 'Feature' or feature.get('geometry', {}).get('type') not in ('Polygon', 'MultiPolygon'):
                        raise ValueError('unexpected geometry')
                details = {'kind': 'geojson', 'features': expected}
            else:
                if not isinstance(data.get('variables'), dict) or not data['variables']:
                    raise ValueError('missing Census variables')
                details = {'kind': 'census-metadata', 'variables': len(data['variables'])}
        digest = hashlib.sha256(body).hexdigest()
        (raw / (ident + suffix)).write_bytes(body)
        return {'source_id': ident, 'url': source['url'], 'captured_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'access_method': 'manual import' if ident.startswith('dbedt_') else 'direct HTTPS',
                'content_type': content_type, 'bytes': len(body), 'sha256': digest,
                'historical_sha256': source['sha256'], 'matches_historical': digest == source['sha256'], **details}
    except Exception as e:
        return {'source_id': ident, 'url': source['url'], 'error': f'{type(e).__name__}: {e}'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('destination', type=pathlib.Path, help='new, non-existing capture directory')
    ap.add_argument('--manual-workbooks', type=pathlib.Path, help='directory containing four manually acquired DBEDT files named by source ID')
    args = ap.parse_args()
    args.destination.mkdir(parents=False, exist_ok=False)
    raw = args.destination / 'raw'; raw.mkdir()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda s: fetch(s, raw, args.manual_workbooks), CONFIG['sources']))
    report = {'schema': 'ia1-acquisition-report/1', 'complete': all('error' not in x for x in records), 'sources': records,
              'note': 'Raw staging only. No frozen snapshot or case is changed. Review changes before normalization.'}
    (args.destination / 'acquisition-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'complete': report['complete'], 'captured': sum('error' not in x for x in records), 'errors': [x for x in records if 'error' in x]}, indent=2))
    return 0 if report['complete'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
