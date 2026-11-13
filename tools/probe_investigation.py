#!/usr/bin/env python3
"""Record observed all-76 whole-plan results. No models or external sources."""
import argparse
import copy
import http.cookiejar
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from districtbrief.interpret import recipe

p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--fixtures',required=True);p.add_argument('--all-76',action='store_true');p.add_argument('--repeats',type=int,default=3);p.add_argument('--output',required=True);args=p.parse_args()
fixture=json.loads(Path(args.fixtures).read_text());opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
cat=json.load(opener.open(args.base_url+'/api/catalog'));identity=cat['investigation'];rows=[]
def run(ch,code,steps=None):
 plan=recipe({'state_fips':'15','chamber':ch,'code':code,'boundary_session':2024})
 if steps is not None:plan['steps']=steps
 r={**{k:str(uuid.uuid4()) for k in ('request_id','case_id','branch_id')},'revision':1,'schema_version':identity['schema_version'],'operation_version':identity['operation_version'],'recipe_version':'aging_at_home/1','snapshot_id':identity['snapshot_id'],'mode':'run','plan':plan,'selected_claim_refs':[],'selected_action_ref':None}
 start=time.perf_counter();raw=opener.open(urllib.request.Request(args.base_url+'/api/investigation',data=json.dumps(r).encode(),headers={'Content-Type':'application/json'})).read();elapsed=time.perf_counter()-start;o=json.loads(raw)
 return {'chamber':ch,'code':code,'seconds':elapsed,'bytes':len(raw),'status':o['status'],'model_calls':o['model_calls'],'step_failures':[s for s in o['steps'] if s['status']!='ok'],'claims':len(o['claims'])}
for repeat in range(args.repeats):
 for ch,count in [('house',51),('senate',25)]:
  for n in range(1,count+1):
   row=run(ch,f'{n:03}');row['repeat']=repeat+1;rows.append(row)
# Maximum unique evidence shape: all metrics + four distinct comparison bundles + program and leads.
metrics=[m['metric_id'] for m in cat['metrics']];worst=[{'step_id':'s1','operation':'profile','args':{'metric_ids':None}}]
for n in range(4):worst.append({'step_id':f's{n+2}','operation':'compare','args':{'metric_ids':metrics[n*4:n*4+4],'comparison_geography':'HI-STATE-2024'}})
worst.extend([{'step_id':'s6','operation':'program_evidence','args':{'program_ids':[p['program_id'] for p in cat['programs']]}},{'step_id':'s7','operation':'outreach_lead','args':{'program_id':'snap_hi'}},{'step_id':'s8','operation':'outreach_lead','args':{'program_id':'medquest_hi'}}]);worst_result=run('house','028',worst)
times=sorted(r['seconds'] for r in rows);out={'schema':'ia1-runtime-probe/1','identity':identity,'fixture_schema':fixture.get('schema_version',fixture.get('schema')),'requests':rows,'worst_plan':worst_result,'summary':{'districts':76,'repeats':args.repeats,'requests':len(rows),'default_p95_seconds':times[min(len(times)-1,int(len(times)*.95))],'default_max_seconds':max(times),'default_max_bytes':max(r['bytes'] for r in rows),'model_calls':sum(r['model_calls'] for r in rows),'failures':sum(bool(r['step_failures']) for r in rows)},'worker_rss':'Record separately from OS for the actual worker; HTTP cannot measure it.'}
Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out['summary']));print('worst',json.dumps(worst_result))
