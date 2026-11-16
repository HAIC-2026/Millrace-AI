#!/usr/bin/env python3
"""Freeze/check the explicit candidate file set and optionally archive that set."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from districtbrief.public_packet import PublicPacket, public_metadata

TOP_LEVEL=('README.md','DATA-PROVENANCE.json','Dockerfile','.dockerignore','.gitignore',
           'requirements.txt','public_app.py','wsgi.py','gunicorn.conf.py',
           'LICENSE','LICENSE-SCOPE.md','PRIVACY.md','DATA-NOTICES.md')
MODULES=('__init__','admin_labels','case_contract','candidate_metadata','claim_binding','contract',
         'core','geography','interpret','investigation','packet','rationale','render','resolve',
         'route_a','router_contract','service','service_scope','xlsx','public_packet',
         'ia_language','ia_language_provider','ia_language_accounting','ia_language_jobs',
         'ia_language_profiles','ia_language_funding')
DATA=('districtbrief/ia_language_profiles.json',)
STATIC=('app.css','app.js','case_state.js','index.html','investigation.js','map.js','request.js','language_state.js')
TESTS=('test_case_replay.py','test_case_state.cjs','test_claim_bindings.py','test_geometry.py',
       'test_investigation.py','test_release.py','test_scope.py','test_public_profile.py','test_completion.py',
       'test_ia_language_contract.py','test_ia_language_provider.py','test_ia_language_accounting.py','test_ia_language_jobs.py','test_ia_language_processes.py','test_ia_language_proposals.py',
       'test_ia_language_diagnostics.py','test_ia_language_adoption.py',
       'test_ia_language_map_default.py','test_ia_language_adoption_2.py',
       'test_ia_language_district_provenance.py','test_ia_language_adoption_3.py','test_ia_language_repair.py',
       'test_ia_language_source_review.py','test_ia_language_adoption_4.py','test_ia_language_integrated_review.py',
       'test_ia_language_contract_fixes.py','test_ia_language_ox3_review.py','test_ia_language_v5_review.py','test_ia_language_fh_r1.py','test_ia_language_v6_review.py',
       'test_ia_language_comparator_choices.py','test_metric_caveats.py','test_brief_presentation.py',
       'test_ia_language_adoption_5.py','test_ia_language_county_guard.py','test_ia_language_operator_cutoff.py',
       'test_recommended_brief.py','recommended_brief_fixture.py',
       'language_funding_fixture.py','test_ia_language_funding.py','test_ia_language_profiles.py','test_ia_language_shared_repairs.py','test_ia_language_repair1.py','test_ia_language_repair1_v2.py','test_ia_language_rate_limit.py','test_ia_language_repair1_v4.py')
FIXTURES=('issue_acceptance.json','private_case.json','public_case.json','README.md','ia-language-dev.json','ia-language-dev-v5-replay.json','ia-language-adoption3-synthetic.json','ia-language-prompt-v8.txt','ia-language-adoption4-synthetic.json','recommended-brief-results.json')
TOOLS=('build_candidate_metadata.py','build_release_manifest.py','compile_statistics.py','probe_investigation.py','retain_r2_inputs.py','build_completion_projection.py','ia_language_operator.py','ia_language_config_adoption.py','ia_language_config_adoption_2.py','ia_language_config_adoption_3.py','ia_language_config_adoption_4.py','ia_language_config_adoption_5.py')
EXCLUDED_PARTS=frozenset(('.venv','__pycache__','.git'))
MANIFEST='RELEASE-MANIFEST.json'
BASELINE_MANIFEST='686b23b6b7623d77f084ed4518e6d5adec620fbe713e17ee220caa63bce2e46d'


def admitted_files():
    packet=PublicPacket(ROOT/'runtime-packet')
    metadata=public_metadata(ROOT/'candidate-metadata')
    allowed=set(TOP_LEVEL)
    allowed.update('districtbrief/'+name+'.py' for name in MODULES)
    allowed.update(DATA)
    allowed.update('static/'+name for name in STATIC)
    allowed.update('tests/'+name for name in TESTS)
    allowed.update('tests/fixtures/'+name for name in FIXTURES)
    allowed.update('tools/'+name for name in TOOLS)
    allowed.update('docs/'+name for name in ('R2-INPUTS.json','R2-REPLAY.md','PROJECTION-INPUTS.json','PUBLIC33AF-REPLAY.md'))
    allowed.update('tools/sources/'+name for name in ('README.md','acquire.py','normalize.py','allowlist.json'))
    allowed.update('runtime-packet/'+row['path'] for row in packet.manifest['files'])
    allowed.add('runtime-packet/PACKET-MANIFEST.json')
    meta=json.loads((ROOT/'candidate-metadata/MANIFEST.json').read_text())
    allowed.update('candidate-metadata/'+row['path'] for row in meta['files'])
    allowed.add('candidate-metadata/MANIFEST.json')
    actual=set()
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix in ('.pyc','.pyo'):continue
        if path.is_symlink():raise SystemExit('non-excluded symlink in source tree: '+rel.as_posix())
        if path.is_file() and rel.as_posix()!=MANIFEST:actual.add(rel.as_posix())
    if actual!=allowed:
        raise SystemExit('source allowlist mismatch: '+json.dumps({'unexpected':sorted(actual-allowed),'missing':sorted(allowed-actual)}))
    return sorted(allowed,key=lambda name:name.encode('utf-8')),packet,metadata


def build_manifest():
    names,packet,metadata=admitted_files();files=[]
    for name in names:
        raw=(ROOT/name).read_bytes();files.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    records=''.join(f"{f['sha256']}  {f['bytes']}  {f['path']}\n" for f in files)
    manifest={'schema':'haic-ia1-release-manifest/1','operation_version':'ia-core/1','model_calls_default':0,'language_default':'disabled',
        'source_identity':'sha256:'+hashlib.sha256(records.encode()).hexdigest(),
        'hash_rule':'SHA256 UTF8 of sorted sha256  bytes  relative_path newline records; manifest excluded',
        'file_policy':'Explicit code/static/test/tool names plus separately verified runtime-packet and candidate-metadata manifests; virtualenv, Git and Python caches excluded; any other file rejected',
        'input_profile':'public',
        'lineage':{'selected_baseline_manifest_sha256':BASELINE_MANIFEST,'data_snapshot_id':packet.snapshot_id,
                   'metadata_snapshot_id':metadata.metadata_snapshot_id,'combined_evidence_snapshot_id':metadata.combined_snapshot_id(packet.snapshot_id)},
        'files':files}
    return manifest,(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');parser.add_argument('--archive');args=parser.parse_args()
    manifest,raw=build_manifest();target=ROOT/MANIFEST
    if args.check:
        if target.read_bytes()!=raw:raise SystemExit('candidate source manifest is stale')
    else:target.write_bytes(raw)
    result={'source_identity':manifest['source_identity'],'manifest_sha256':hashlib.sha256(raw).hexdigest(),'files':len(manifest['files'])}
    if args.archive:
        archive=Path(args.archive).resolve()
        if archive==ROOT or ROOT in archive.parents:raise SystemExit('archive must be outside candidate source')
        archive.parent.mkdir(parents=True,exist_ok=True)
        with archive.open('wb') as output,gzip.GzipFile(fileobj=output,mode='wb',filename='',mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w',format=tarfile.PAX_FORMAT) as tar:
            for name in sorted([f['path'] for f in manifest['files']]+[MANIFEST],key=lambda s:s.encode('utf-8')):
                payload=(ROOT/name).read_bytes()
                import io
                info=tarfile.TarInfo(name);info.size=len(payload);info.mode=0o644;info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
                tar.addfile(info,io.BytesIO(payload))
        result['archive']={'path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'members':len(manifest['files'])+1}
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
