"""Server-only semantic bindings. Ordered operands remain ordered."""
from __future__ import annotations
import copy
import hashlib
import json
import unicodedata
from decimal import Decimal
from .case_contract import OPERATION_VERSION
from .rationale import PROGRAM_RATIONALE

FIELDS=('binding_version','operation_version','kind','snapshot_id','metric_id','table_id','variable_id','moe_variable_id','universe','unit','geography','period','source_records','value','transformation','operands','program_binding','rationale_binding')

def normalized(value):
    if isinstance(value,str):return unicodedata.normalize('NFC',value)
    if type(value) is float:return format(Decimal(str(value)).normalize(),'f')
    if isinstance(value,list):return [normalized(v) for v in value]
    if isinstance(value,dict):return {unicodedata.normalize('NFC',k):normalized(v) for k,v in value.items()}
    return value

def canonical_bytes(value):
    return json.dumps(normalized(value),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')

def digest(value):return 'sha256:'+hashlib.sha256(canonical_bytes(value)).hexdigest()

def plan_hash(plan):return digest(plan)

class ClaimBindings:
    def __init__(self,core,snapshot_id,map_session=2026):
        self.core,self.snapshot_id,self.map_session=core,snapshot_id,map_session
        self.claims={}
    def _source(self,sid,locator):
        s=self.core.packet.sources[sid]
        return {'source_id':sid,'publisher_url':s.get('url'),'retained_hash':s.get('sha256'),
                'retrieval_method':s.get('retrieval_method') or s.get('method') or 'retained_source_packet',
                'retrieved_at':s.get('retrieved_at_utc'),'locator':locator,
                'origin_bytes_verified': (self.core.packet.source_file_status(sid)['available']
                    if getattr(self.core.packet,'profile',None)=='public' else True),
                **({'verification_scope':'normalized_projection_with_historical_source_reference'}
                   if getattr(self.core.packet,'profile',None)=='public' else {})}
    def _geography(self,f):
        g=copy.deepcopy(f.get('geography'))
        if g and g.get('geography_id') in self.core.profiles:
            # Program relevance and hypotheses carry a subject address, not the full
            # statistical identity. Resolve it from trusted profiles before hashing.
            full=copy.deepcopy(self.core.profiles[g['geography_id']]['geography'])
            full.update(g);g=full
            g['type']=self.core._geo_kind(g)
            g['code']=g.get('district_code')
            g['boundary_vintage']=g.get('boundary_session')
        if g and g.get('chamber'):
            rec=self.core.geo.get(g['chamber'],g.get('district_code') or g.get('code') or g['geography_id'].split('-')[2],2024)
            g['compatibility']={'statistical_session':2024,'map_session':self.map_session,
                                'method':'canonical_polygon_content/1','equal':bool(rec and (self.map_session==2024 or rec['geometry_equal_to_other_session']))}
        return g
    def bind(self,f):
        fid=f['finding_id']
        if fid in self.claims:return self.claims[fid]
        b={k:None for k in FIELDS};b.update(binding_version='ia-claim/1',operation_version=OPERATION_VERSION,kind=f['kind'],snapshot_id=self.snapshot_id,
                universe=f.get('universe'),unit=f.get('unit'),period=f.get('period'),geography=self._geography(f),operands=[],source_records=[])
        metric=f.get('metric') or {}
        b.update(metric_id=metric.get('metric_id'),table_id=metric.get('table_id'),variable_id=metric.get('variable_id'),moe_variable_id=metric.get('margin_of_error_variable_id'))
        deps=[];sources=[]
        kind=f['kind']
        if kind=='statistic':
            src=f['source'];sources=[self._source(src['source_id'],src['locator'])]
            b['value']={'estimate':f['estimate'],'display':f['estimate_display'],'moe':f['margin_of_error'],'moe_display':f['moe_display'],'confidence':f['moe_confidence_level'],'annotation':f['annotation'],'moe_annotation':f['moe_annotation']}
            b['transformation']={'operation':'published_statistic','version':'1','method':f['transformation']}
        elif kind=='comparison':
            deps=[self.bind(f['left'])['claim_ref'],self.bind(f['right'])['claim_ref']]
            sources=[*self.claims[f['left']['finding_id']]['binding']['source_records'],*self.claims[f['right']['finding_id']]['binding']['source_records']]
            b['geography']={'left':self._geography(f['left']),'right':self._geography(f['right'])}
            b['value']={'difference':f['difference'],'not_differenced_reason':f['not_differenced_reason']}
            b['transformation']={'operation':'left_minus_right' if f['difference'] else 'side_by_side','version':'1','method':f['transformation']}
        elif kind=='administrative_context':
            src=f['source'];sources=[self._source(src['source_id'],src['locator'])]
            b['value']=copy.deepcopy(self.core.administrative_rows[f['observation_id']])
            b['transformation']={'operation':'administrative_reference','version':'1','district_allocation':False}
        elif kind=='program_relevance':
            sources=[self._source(e['source_id'],e['locator']) for e in f['evidence']]
            b['program_binding']={'program':f['program'],'jurisdiction':f.get('jurisdiction'),'access':f.get('access'),'jurisdiction_check':f['jurisdiction_check'],'referral':f['referral']}
            b['transformation']={'operation':'program_reference','version':'1'}
        elif kind=='outreach_hypothesis':
            program=self.bind(self.core.prog_finding(f['program']['program_id'],f['geography']['geography_id']))
            for o in f['observed_need']:
                deps.append(self.bind(self.core.finding(o['finding_id']))['claim_ref'])
                if o['state_reference']:deps.append(self.bind(self.core.finding(o['state_reference']['finding_id']))['claim_ref'])
            deps.append(program['claim_ref'])
            sources=[s for r in deps for s in self.claims[r['finding_id']]['binding']['source_records']]
            b['program_binding']=program['binding']['program_binding']
            b['rationale_binding']={'version':'reviewed-rationale/1','program_id':f['program']['program_id'],'rationale':PROGRAM_RATIONALE[f['program']['program_id']], 'ordered_support':deps,'reference_geography':'HI-STATE-2024'}
            b['transformation']={'operation':'reviewed_outreach_hypothesis','version':'1','no_eligibility_or_gap':True}
        b['operands']=deps
        unique={canonical_bytes(s):s for s in sources}
        b['source_records']=sorted(unique.values(),key=lambda s:(s['source_id'],s['retained_hash'] or '',canonical_bytes(s['locator'])))
        b=normalized(b)
        ref={'snapshot_id':self.snapshot_id,'finding_id':fid,'semantic_hash':digest(b)}
        if deps:
            inspections=[inspection for dependency in deps for inspection in self.claims[dependency['finding_id']]['source_inspection_refs']]
        else:
            inspections=[{'source_id':s['source_id'],'finding_id':fid} for s in b['source_records']]
        inspections=list({(r['source_id'],r['finding_id']):r for r in inspections}.values())
        claim=dict(copy.deepcopy(f),claim_ref=ref,binding=b,dependencies=deps,source_inspection_refs=inspections)
        self.claims[fid]=claim
        return claim
