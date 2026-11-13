"""Hawaii state legislative district geography for districtbrief.

Identity rule
-------------
A district is identified by the tuple (state_fips, chamber, code, boundary_session).
GEOID alone is not a key. House 001 and Senate 001 both carry GEOID '15001', and
Maui County's GEOID '15009' collides with House district 009 in the same text space.
Chamber and session must always travel with the 3-digit code.

Source files
------------
Layers are read from data/geography/raw/ under the packet root, as listed in
data/geography/manifest.json (paths are relative to data/geography/). Only the four
TIGERweb legislative geometry layers are used, as data only: 2024 and 2026, House
and Senate. Each file's byte length and sha256 are checked against the manifest
before it is parsed. Any mismatch, missing manifest entry, or path that escapes
data/geography/ raises ValueError.

What "equal" means
------------------
- strict: the canonical fingerprints match. A Polygon is wrapped into MultiPolygon
  form, rings and coordinates are kept exactly as supplied, and the fingerprint is
  sha256 of the compact JSON of that normalized form.
- order_insensitive: the same polygons match as a multiset, ignoring the order of
  polygons inside a MultiPolygon. Ring order and vertex order are still significant.
- strict implies order_insensitive.
- geometry_equal_across_sessions() and the record field
  'geometry_equal_to_other_session' report the order_insensitive result.

County
------
Internal points do not establish county or service jurisdiction. County is unknown
unless independently supported evidence is admitted.

"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path

SESSIONS = (2024, 2026)
CHAMBERS = ('house', 'senate')
STATE_FIPS = '15'

SOURCE_IDS = {
    (2024, 'house'): 'tigerweb_2024_house_geometry',
    (2024, 'senate'): 'tigerweb_2024_senate_geometry',
    (2026, 'house'): 'tigerweb_2026_house_geometry',
    (2026, 'senate'): 'tigerweb_2026_senate_geometry',
}
CODE_PROPERTY = {'house': 'SLDL', 'senate': 'SLDU'}

COUNTY_METHOD = ('approximate: TIGERweb internal point within a coarse county bounding box; '
                 'jurisdiction caveat only, not a legal determination')

# (name, lat_min, lat_max, lon_min, lon_max)
COUNTY_BOXES = (
    ('Hawaii County', 18.8, 20.35, -156.15, -154.75),
    ('Maui County', 20.45, 21.25, -157.35, -155.95),
    ('Honolulu County', 21.2, 21.75, -158.35, -157.6),
    ('Kauai County', 21.75, 22.3, -160.6, -159.2),
)
# Northwestern Hawaiian Islands (lon below this) are assigned to Honolulu County.
NWHI_LON_BELOW = -160.6

_MANIFEST_KEYS = ('source_id', 'url', 'path', 'bytes', 'sha256')
_CODE_RE = re.compile(r'[0-9]{1,3}')


def polygons_of(geometry):
    """Return the polygon list of a Polygon or MultiPolygon, coordinates unchanged.

    A Polygon is wrapped as a one-element list. Any other geometry type raises ValueError.
    """
    if not isinstance(geometry, dict):
        raise ValueError('geometry must be a GeoJSON geometry object')
    gtype = geometry.get('type')
    coords = geometry.get('coordinates')
    if gtype == 'Polygon':
        if not isinstance(coords, list):
            raise ValueError('Polygon coordinates must be a list of rings')
        return [coords]
    if gtype == 'MultiPolygon':
        if not isinstance(coords, list) or not all(isinstance(p, list) for p in coords):
            raise ValueError('MultiPolygon coordinates must be a list of polygons')
        return coords
    raise ValueError(f'unsupported geometry type: {gtype!r}')


def _dumps(obj):
    return json.dumps(obj, separators=(',', ':'))


def _polygons_fingerprint(polygons):
    normalized = {'type': 'MultiPolygon', 'coordinates': polygons}
    return hashlib.sha256(_dumps(normalized).encode('utf-8')).hexdigest()


def geometry_fingerprint(geometry):
    """sha256 hex digest of the canonical MultiPolygon form of a geometry."""
    return _polygons_fingerprint(polygons_of(geometry))


def compare_geometries(a, b):
    """Return {'strict': bool, 'order_insensitive': bool} for two geometries."""
    polys_a = polygons_of(a)
    polys_b = polygons_of(b)
    strict = _polygons_fingerprint(polys_a) == _polygons_fingerprint(polys_b)
    order_insensitive = (sorted(_dumps(p) for p in polys_a)
                         == sorted(_dumps(p) for p in polys_b))
    return {'strict': strict, 'order_insensitive': order_insensitive}


def _finite(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} must be finite')
    return number


def approximate_county(lat, lon):
    """Return unknown; a single point cannot establish district jurisdiction."""
    _finite(lat, 'lat')
    _finite(lon, 'lon')
    return {'name': None, 'method': 'Unknown: internal points do not establish jurisdiction.'}


def _valid_key(chamber, code, session):
    if not isinstance(chamber, str) or chamber not in CHAMBERS:
        return None
    if isinstance(session, bool) or not isinstance(session, int) or session not in SESSIONS:
        return None
    if not isinstance(code, str) or len(code) != 3:
        return None
    return (chamber, session, code)


class GeographyIndex:
    """Hawaii legislative district geometry and metadata for a packet.

    Loads all four TIGERweb layers once. Records are keyed by
    (chamber, boundary_session, code). Lookups return deep copies, so callers
    cannot change the index.
    """

    def __init__(self, packet_dir):
        started = time.perf_counter()
        self._geo_dir = Path(packet_dir) / 'data' / 'geography'
        manifest = self._read_manifest()
        self._records = {}
        self._cross = {}
        self._features = {}
        geometries = {}
        for session in SESSIONS:
            for chamber in CHAMBERS:
                source_id = SOURCE_IDS[(session, chamber)]
                records, layer_geometries = self._load_layer(
                    session, chamber, manifest[source_id])
                self._records.update(records)
                geometries.update(layer_geometries)
        self._link_sessions(geometries)
        self.load_seconds = time.perf_counter() - started

    # ----- loading -------------------------------------------------------

    def _read_manifest(self):
        path = self._geo_dir / 'manifest.json'
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError(f'cannot read manifest {path}') from exc
        if not isinstance(doc, list):
            raise ValueError('manifest must be a JSON list of entries')
        needed = set(SOURCE_IDS.values())
        found = {}
        for entry in doc:
            if not isinstance(entry, dict):
                raise ValueError('manifest entries must be JSON objects')
            sid = entry.get('source_id')
            if not (isinstance(sid, str) and sid in needed):
                continue
            if sid in found:
                raise ValueError(f'manifest lists {sid} more than once')
            for key in _MANIFEST_KEYS:
                if key not in entry:
                    raise ValueError(f'manifest entry {sid} lacks {key}')
            found[sid] = entry
        missing = sorted(needed - set(found))
        if missing:
            joined = ', '.join(missing)
            raise ValueError(f'manifest has no entry for: {joined}')
        return found

    def _verified_bytes(self, source_id, entry):
        rel = entry['path']
        if not isinstance(rel, str):
            raise ValueError(f'{source_id}: manifest path must be a string')
        root = self._geo_dir.resolve()
        target = (self._geo_dir / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise ValueError(f'{source_id}: path {rel!r} escapes data/geography') from None
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise ValueError(f'{source_id}: cannot read {rel!r}') from exc
        if len(data) != entry['bytes']:
            raise ValueError(
                f'{source_id}: {len(data)} bytes on disk, manifest says {entry["bytes"]}')
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f'{source_id}: sha256 does not match manifest')
        return data

    def _load_layer(self, session, chamber, entry):
        source_id = SOURCE_IDS[(session, chamber)]
        data = self._verified_bytes(source_id, entry)
        try:
            doc = json.loads(data.decode('utf-8'))
        except ValueError as exc:
            raise ValueError(f'{source_id}: not valid UTF-8 JSON') from exc
        if not (isinstance(doc, dict) and doc.get('type') == 'FeatureCollection'
                and isinstance(doc.get('features'), list)):
            raise ValueError(f'{source_id}: expected a GeoJSON FeatureCollection')
        records = {}
        geometries = {}
        for feature in doc['features']:
            record, geometry = self._record(session, chamber, source_id, entry, feature)
            key = (chamber, session, record['code'])
            if key in records:
                raise ValueError(f'{source_id}: duplicate district code {record["code"]}')
            records[key] = record
            geometries[key] = geometry
            self._features[key] = feature
        return records, geometries

    def _record(self, session, chamber, source_id, entry, feature):
        if not (isinstance(feature, dict) and feature.get('type') == 'Feature'):
            raise ValueError(f'{source_id}: feature is not a GeoJSON Feature')
        props = feature.get('properties')
        geometry = feature.get('geometry')
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise ValueError(f'{source_id}: feature lacks properties or geometry')
        if props.get('STATE') != STATE_FIPS:
            raise ValueError(f'{source_id}: STATE is not {STATE_FIPS!r}')
        if props.get('LSY') != str(session):
            raise ValueError(
                f'{source_id}: LSY {props.get("LSY")!r} does not match session {session}')
        code_prop = CODE_PROPERTY[chamber]
        raw_code = props.get(code_prop)
        if not (isinstance(raw_code, str) and _CODE_RE.fullmatch(raw_code)):
            raise ValueError(f'{source_id}: bad {code_prop} value {raw_code!r}')
        code = raw_code.zfill(3)
        if int(code) < 1:
            raise ValueError(f'{source_id}: district code must be at least 1')
        expected_geoid = STATE_FIPS + code
        if props.get('GEOID') != expected_geoid:
            raise ValueError(
                f'{source_id}: GEOID {props.get("GEOID")!r} is not {expected_geoid!r}')
        name = props.get('NAME')
        if not isinstance(name, str):
            raise ValueError(f'{source_id}: NAME must be a string')
        for label in ('AREALAND', 'AREAWATER'):
            value = props.get(label)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f'{source_id}: {label} must be an integer')
        lat = _finite(props.get('INTPTLAT'), f'{source_id} INTPTLAT')
        lon = _finite(props.get('INTPTLON'), f'{source_id} INTPTLON')
        _validate_geometry(geometry)
        fingerprint = geometry_fingerprint(geometry)
        record = {
            'state_fips': STATE_FIPS,
            'chamber': chamber,
            'code': code,
            'boundary_session': session,
            'geoid': expected_geoid,
            'name': name,
            'lsy': props['LSY'],
            'arealand': props['AREALAND'],
            'areawater': props['AREAWATER'],
            'internal_point': {'lat': lat, 'lon': lon},
            'geometry_fingerprint': fingerprint,
            'geometry_equal_to_other_session': None,
            'source_id': source_id,
            'source_url': entry['url'],
            'source_sha256': entry['sha256'],
            'approx_county': {'name': None, 'method': 'Unknown: internal points do not establish jurisdiction.'},
        }
        return record, geometry

    def _link_sessions(self, geometries):
        first, second = SESSIONS
        pairs = sorted({(chamber, code) for (chamber, _session, code) in self._records})
        for chamber, code in pairs:
            key_a = (chamber, first, code)
            key_b = (chamber, second, code)
            if key_a in geometries and key_b in geometries:
                comparison = compare_geometries(geometries[key_a], geometries[key_b])
                self._cross[(chamber, code)] = comparison
                flag = comparison['order_insensitive']
                self._records[key_a]['geometry_equal_to_other_session'] = flag
                self._records[key_b]['geometry_equal_to_other_session'] = flag

    # ----- queries -------------------------------------------------------

    def get(self, chamber, code, session):
        """Return a copy of one district record, or None for any unknown or invalid key."""
        key = _valid_key(chamber, code, session)
        if key is None:
            return None
        record = self._records.get(key)
        return copy.deepcopy(record) if record is not None else None

    def list(self, chamber=None, session=None):
        """Return record copies sorted by (chamber, session, code). Invalid filters give []."""
        if chamber is not None and not (isinstance(chamber, str) and chamber in CHAMBERS):
            return []
        if session is not None and not (
                isinstance(session, int) and not isinstance(session, bool)
                and session in SESSIONS):
            return []
        keys = sorted(
            k for k in self._records
            if (chamber is None or k[0] == chamber) and (session is None or k[1] == session))
        return [copy.deepcopy(self._records[k]) for k in keys]

    def count(self):
        """Return {'2024': {'house': n, 'senate': n}, '2026': {...}}."""
        result = {str(s): {c: 0 for c in CHAMBERS} for s in SESSIONS}
        for chamber, session, _code in self._records:
            result[str(session)][chamber] += 1
        return result

    def geometry_comparison(self, chamber, code):
        """Return {'strict': bool, 'order_insensitive': bool} across sessions, or None."""
        if not (isinstance(chamber, str) and chamber in CHAMBERS and isinstance(code, str)):
            return None
        value = self._cross.get((chamber, code))
        return copy.deepcopy(value) if value is not None else None

    def geometry_equal_across_sessions(self, chamber, code):
        """Order-insensitive geometry equality between 2024 and 2026, or None if not in both."""
        comparison = self.geometry_comparison(chamber, code)
        return None if comparison is None else comparison['order_insensitive']

    def find_by_geoid(self, geoid):
        """Return copies of every record whose GEOID matches. GEOID is not unique."""
        if not isinstance(geoid, str):
            return []
        keys = sorted(k for k, rec in self._records.items() if rec['geoid'] == geoid)
        return [copy.deepcopy(self._records[k]) for k in keys]


def _validate_geometry(geometry):
    polygons = polygons_of(geometry)
    if not polygons:
        raise ValueError('empty geometry')
    for polygon in polygons:
        if not polygon:
            raise ValueError('empty polygon')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('invalid polygon ring')
            for point in ring:
                if (not isinstance(point, list) or len(point) < 2 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                        for v in point)):
                    raise ValueError('invalid or nonfinite coordinate')


def geometry_payload(packet, combined_snapshot_id, chamber, code, session):
    """Return an entire verified feature, retaining every coordinate and ring."""
    if not isinstance(combined_snapshot_id, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', combined_snapshot_id):
        raise ValueError('invalid snapshot identity')
    key = _valid_key(chamber, code, session)
    if key is None:
        raise ValueError('invalid geometry identity')
    index = getattr(packet, "_ia1_geometry_index", None)
    if index is None:
        index = GeographyIndex(packet.dir)
        packet._ia1_geometry_index = index
    record = index.get(chamber, code, session)
    if record is None:
        raise KeyError('geometry not found')
    feature = copy.deepcopy(index._features[key])
    result = {'snapshot_id': combined_snapshot_id, 'chamber': chamber, 'code': code,
              'session': session, 'source_id': record['source_id'],
              'source_sha256': record['source_sha256'],
              'compatibility': {'statistical_session': 2024, 'display_session': session,
                                'method': 'canonical polygon content, order insensitive; ring and vertex order retained',
                                'version': 'geography-compatibility/1',
                                'equal': index.geometry_equal_across_sessions(chamber, code)},
              'component_count': len(polygons_of(feature['geometry'])), 'feature': feature}
    if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) > 1048576:
        raise ValueError('geometry response exceeds 1 MiB')
    return result
