"""Verified publication facts, distinct from the complete historical R2 archive."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .packet import Packet, PacketError
from .candidate_metadata import CandidateMetadata

PUBLIC_MANIFEST_SHA256 = '33e94a6aa593af0807ee432996bdfa0c229c5a936573ce6aef5d114b9ff1276c'
PUBLIC_METADATA_MANIFEST_SHA256 = '51b5f726a6b295c01a28cace0be0b8c8025b1e7b4881511366a9219acf2de564'
PUBLIC_SNAPSHOT_ID = 'sha256:972b7a41a85f9a51303358abdd82900c4e988cdc571ffc085a9b3e7046fb9892'


def records(root, manifest_name):
    root = Path(root).resolve()
    result = []
    for path in sorted(root.rglob('*'), key=lambda p: p.relative_to(root).as_posix().encode('utf-8')):
        if path.is_symlink():
            raise PacketError('Publication inputs must not contain symlinks')
        if path.is_file() and path.relative_to(root).as_posix() != manifest_name:
            data = path.read_bytes()
            result.append({'path':path.relative_to(root).as_posix(), 'bytes':len(data),
                           'sha256':hashlib.sha256(data).hexdigest()})
    return result


def snapshot_id(rows):
    lines = ''.join(f"{r['sha256']}  {r['bytes']}  {r['path']}\n" for r in rows)
    return 'sha256:' + hashlib.sha256(lines.encode('utf-8')).hexdigest()


class PublicPacket(Packet):
    profile = 'public'
    fetch_policy = ('Bundled normalized facts and provenance only. Historical source hashes identify '
                    'original captures. Omitted original bytes are not verified here. '
                    'Citation URLs are never fetched by an analytical request.')

    def _verify(self):
        if self.manifest_sha256 != PUBLIC_MANIFEST_SHA256 or self.snapshot_id != PUBLIC_SNAPSHOT_ID:
            raise PacketError('Publication facts manifest pin mismatch')
        actual = records(self.dir, 'PACKET-MANIFEST.json')
        if actual != self.manifest.get('files') or snapshot_id(actual) != self.snapshot_id:
            raise PacketError('Publication facts files or identity mismatch')
        return {'verified':True, 'verification_scope':'publication_normalized_facts',
                'snapshot_id':self.snapshot_id, 'manifest_sha256':self.manifest_sha256,
                'file_count':len(actual), 'full_r2_archive_verified':False,
                'note':'Only bundled listed files are verified. Historical provenance does not verify omitted raw bytes.'}

    def _load_sources(self):
        sources = self.read_json('SOURCE-CATALOG.json')
        if not isinstance(sources, dict) or any(k != v.get('source_id') for k,v in sources.items()):
            raise PacketError('Publication source catalog must contain unique source records')
        for source in sources.values():
            source['record_scope'] = 'historical_origin_capture'
            if source.get('notes'):
                source['notes'] = 'Historical capture note: ' + source['notes']
        return sources

    def source_file_status(self, source_id):
        src = self.sources.get(source_id)
        if src is None:
            return {'available':False, 'reason':'unknown source_id'}
        rel = src['packet_path']
        row = self.files.get(rel)
        # A projected file at the same historic path is not the original source capture.
        if row and (row['sha256'], row['bytes']) == (src.get('sha256'), src.get('bytes')):
            data = self.path(rel).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if actual != src['sha256']:
                raise PacketError('Bundled origin source changed after startup')
            return {'available':True, 'sha256_on_disk':actual, 'matches_source_manifest':True,
                    'verification_scope':'bundled_original_bytes', 'reason':None}
        return {'available':False, 'matches_source_manifest':False,
                'verification_scope':'normalized_projection', 'projection_verified':True,
                'reason':'Original capture is not bundled. Its historical hash and locator are provenance only.'}


def public_metadata(root):
    return CandidateMetadata(root, manifest_sha256=PUBLIC_METADATA_MANIFEST_SHA256)
