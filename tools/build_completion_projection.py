#!/usr/bin/env python3
"""Assemble a bounded public fact candidate from verified retained inputs and authored artifacts."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from retain_r2_inputs import verify
from districtbrief.public_packet import records,snapshot_id
from districtbrief.candidate_metadata import metadata_id,metadata_records
import compile_statistics
PUBLIC_FILES=('SOURCE-CATALOG.json','data/geography/manifest.json',
 'data/geography/raw/2024_house.geojson','data/geography/raw/2024_senate.geojson',
 'data/geography/raw/2026_house.geojson','data/geography/raw/2026_senate.geojson',
 'data/participation/observations.json','data/programs/registry.json',
 'data/statistics/observations.json','data/statistics/raw/DP03_metadata.json')
BASE_METADATA=('geography/relations.v1.json','recipes/aging_at_home.v1.json','responses/verification.v1.json')
RECIPE_FILES=('recipes/food_assistance_outreach.v1.json','responses/food_assistance_outreach.v1.json')
def read(path):return json.loads(path.read_text())
def write(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def copy(source,target):
 if source.is_symlink() or not source.is_file():raise ValueError('missing or symbolic admitted payload')
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
def assemble(inputs,county,recipe,output):
 if output.exists():raise ValueError('output root must not exist')
 for root in (inputs,county,recipe):
  if root.is_symlink() or not root.is_dir():raise ValueError('input roots must be real directories')
 verification=read(inputs/'INPUT-VERIFICATION.json')
 actual=verify(inputs)
 if verification!=actual or actual['files']!=93:raise ValueError('retained input verification differs')
 county_check=read(county/'input-verification.json');recipe_check=read(recipe/'input-verification.json')
 raw=(county/'observations.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=county_check['observations_sha256'] or not county_check['original_1560_semantically_equal'] or county_check['new_pairs_checked']!=80:raise ValueError('county artifact verification differs')
 if hashlib.sha256((inputs/'runtime-packet/data/programs/registry.json').read_bytes()).hexdigest()!=recipe_check['registry_sha256']:raise ValueError('recipe registry verification differs')
 old=read(inputs/'runtime-packet/data/statistics/observations.json')['observations'];candidate=json.loads(raw)
 rows=candidate['observations'];byid={r['observation_id']:r for r in rows}
 if len(rows)!=1640 or len(byid)!=1640 or any(byid.get(r['observation_id'])!=r for r in old):raise ValueError('county observation lineage differs')
 # Recompile from the complete verified workbook/metadata tree, never the reduced public bundle.
 compile_statistics.PACKET=inputs/'runtime-packet'
 compiled=json.loads(compile_statistics.compile_observations(read(inputs/'runtime-packet/SOURCE-PACKET-MANIFEST.json')))
 if compiled['observations']!=rows:raise ValueError('county artifact does not match raw-workbook compiler')
 for row in rows:
  for key,annotation in [('estimate','annotation'),('margin_of_error','moe_annotation')]:
   value=row[key]
   if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):raise ValueError('invalid numeric observation')
   if value is None and not row[annotation]:raise ValueError('unexplained unavailable observation')
 # Fixed source projection allowlist excludes workbooks, captured program pages and private material.
 output.mkdir(parents=False,exist_ok=False)
 try:
  for rel in PUBLIC_FILES:copy(ROOT/'runtime-packet'/rel,output/'runtime-packet'/rel)
  (output/'runtime-packet/data/statistics/observations.json').write_bytes(raw)
  for rel in BASE_METADATA:copy(ROOT/'candidate-metadata'/rel,output/'candidate-metadata'/rel)
  for rel in RECIPE_FILES:copy(recipe/rel,output/'candidate-metadata'/rel)
  facts=records(output/'runtime-packet','PACKET-MANIFEST.json');data_id=snapshot_id(facts)
  oldmanifest=read(ROOT/'runtime-packet/PACKET-MANIFEST.json')
  oldmanifest.update(snapshot_id=data_id,files=facts)
  write(output/'runtime-packet/PACKET-MANIFEST.json',oldmanifest)
  meta_records=metadata_records(output/'candidate-metadata');meta_id=metadata_id(meta_records)
  write(output/'candidate-metadata/MANIFEST.json',{'metadata_snapshot_id':meta_id,'files':meta_records})
  provenance=read(ROOT/'DATA-PROVENANCE.json');provenance['statistics'].update(observations=1640,metrics=20,geographies=82,unchanged_normalized_statistics_from_r2=False,original_r2_observations_preserved=1560,added_county_observations=80)
  provenance['coverage_lineage']={'parent_combined_snapshot_id':actual['combined_snapshot_id'],'county_artifact_sha256':hashlib.sha256(raw).hexdigest(),'recipe_version':'food_assistance_outreach/1','current_agency_conditions':'unverified; retained reference checked 2026-10-30'}
  write(output/'DATA-PROVENANCE.json',provenance)
  inventory=[]
  for prefix in ('runtime-packet','candidate-metadata'):
   for row in records(output/prefix,'PACKET-MANIFEST.json' if prefix=='runtime-packet' else 'MANIFEST.json'):inventory.append({**row,'path':prefix+'/'+row['path']})
  write(output/'docs/PROJECTION-INPUTS.json',{'schema':'ia1-projection-inputs/1','description':'Bundled normalized facts and authored metadata. Historical capture references do not verify omitted origin bytes.','files':sorted(inventory,key=lambda r:r['path'].encode())})
  return {'data_snapshot_id':data_id,'metadata_snapshot_id':meta_id,'PUBLIC_MANIFEST_SHA256':hashlib.sha256((output/'runtime-packet/PACKET-MANIFEST.json').read_bytes()).hexdigest(),'PUBLIC_METADATA_MANIFEST_SHA256':hashlib.sha256((output/'candidate-metadata/MANIFEST.json').read_bytes()).hexdigest(),'PUBLIC_SNAPSHOT_ID':data_id,'observations':len(rows),'geographies':len({r['observation_id'].split(':',1)[0] for r in rows})}
 except Exception:
  shutil.rmtree(output);raise
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('verified-input-root','county-root','recipe-root','output-root'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();print(json.dumps(assemble(a.verified_input_root,a.county_root,a.recipe_root,a.output_root),sort_keys=True))
