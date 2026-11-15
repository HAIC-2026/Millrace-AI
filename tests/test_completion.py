"""Candidate coverage and ingress regressions. No credentials or network inference."""
import copy,io,json,tempfile,unittest,uuid
from unittest.mock import patch
from public_app import Application,load_core
from districtbrief.case_contract import InvestigationError,admitted_recipes
from districtbrief.claim_binding import plan_hash
from districtbrief.geography import indicator_payload
from districtbrief.interpret import food_assistance_recipe,recipe
from districtbrief.investigation import Investigation
class CompletionChecks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.core=load_core();cls.inv=Investigation(cls.core)
 def request(self,plan):
  return {**{k:str(uuid.uuid4()) for k in ('request_id','case_id','branch_id')},'revision':1,'schema_version':'haic-investigation/1','operation_version':'ia-core/1','recipe_version':plan['issue_id']+'/1','snapshot_id':self.inv.snapshot_id,'mode':'run','plan':plan,'selected_claim_refs':[],'selected_action_ref':None}
 def test_all_five_counties_and_annotated_margin(self):
  for code in ('001','003','005','007','009'):
   result=self.core.compare('HI-HOUSE-028-2024',['poverty_rate_all_people'],'HI-COUNTY-'+code+'-2024')
   self.assertEqual(result['findings'][0]['right']['geography']['geography_id'],'HI-COUNTY-'+code+'-2024')
  kalawao=self.core.stat_finding('HI-COUNTY-005-2024:poverty_rate_all_people');self.assertEqual((kalawao['estimate'],kalawao['margin_of_error']),(22.7,16.8))
  for code in ('001','003','007'):
   value=self.core.stat_finding('HI-COUNTY-'+code+'-2024:total_population');self.assertIsNone(value['margin_of_error']);self.assertEqual(value['moe_annotation'],'*****')
 def test_food_recipe_two_districts_and_edited_print(self):
  self.assertIn('food_assistance_outreach/1',admitted_recipes(self.core))
  for chamber,code in [('house','028'),('senate','005')]:
   plan=food_assistance_recipe({'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024});r=self.request(plan);out=self.inv.handle(r)
   self.assertEqual(out['status'],'ok');self.assertEqual([p['program_id'] for p in out['responses']],['snap_hi'])
   action=out['responses'][0];self.assertEqual(action['action_ref']['action_id'],'snap_food_outreach_verify/1');self.assertTrue(any('documentation' in x for x in action['facts_to_verify']))
   claim=next(c for c in out['claims'] if c.get('metric',{}).get('metric_id')=='poverty_rate_all_people' and c['kind']=='statistic' and c['geography']['geography_id'].startswith('HI-'+chamber.upper()))
   b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[claim['claim_ref']],selected_action_ref=action['action_ref'],staff_edits={'note':'Check the agency route before outreach.'},checklist_edits=[],tracking={'label':'Office requests for SNAP information','baseline':None,'as_of':'2026-11-20'},edits_reviewed_for={'branch_id':r['branch_id'],'revision':1,'plan_hash':plan_hash(plan)})
   brief=self.inv.handle(b)['brief'];self.assertIn('baseline not recorded',brief['html']);self.assertIn('review date 2026-11-20',brief['html']);self.assertIn('not eligible or unserved residents',brief['html']);self.assertTrue(brief['citations']);self.assertIn('display class 20% or more' if chamber=='house' else 'display class',brief['html']);self.assertIn('Illustrative bins:',brief['html']);self.assertIn('not policy thresholds or statistical tests',brief['html']);self.assertIn('rank, significance, eligibility or causality',brief['html']);self.assertEqual(brief['district_indicator']['claim_ref'],claim['claim_ref']);self.assertEqual(len(brief['entries']),1)
   changed=copy.deepcopy(r);changed['plan']['issue_id']='aging_at_home';changed['recipe_version']='aging_at_home/1';other=self.inv.handle(changed)['responses'][0]
   self.assertEqual(other['action_ref']['action_id'],'snap_verify/1');self.assertNotEqual(other['action_ref'],action['action_ref'])
 def test_food_literal_clarifies_and_refuses_without_dispatch(self):
  for text,status in [('SNAP outreach in House 28','ok'),('SNAP outreach in Senate 5','ok'),('SNAP outreach in district 5','clarification'),('SNAP outreach for eligible residents in House 28','unsupported')]:
   r=self.request(recipe({'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}));r.update(mode='interpret',utterance=text);r.pop('selected_claim_refs');r.pop('selected_action_ref')
   with patch.object(self.core,'profile',side_effect=AssertionError('dispatch')):out=self.inv.handle(r)
   self.assertEqual(out['status'],status)
 def test_indicator_exact_identity_and_unavailable_margin(self):
  for chamber,code in [('house','013'),('senate','025')]:
   for session in (2024,2026):
    bound=indicator_payload(self.core,self.inv.snapshot_id,chamber,code,session);fact=self.core.stat_finding('HI-'+chamber.upper()+'-'+code+'-2024:poverty_rate_all_people')
    self.assertEqual((bound['snapshot_id'],bound['chamber'],bound['code'],bound['session']),(self.inv.snapshot_id,chamber,code,session));self.assertEqual(bound['estimate'],fact['estimate']);self.assertEqual(bound['margin_of_error'],fact['margin_of_error']);self.assertEqual(bound['source_id'],fact['source']['source_id'])
  fact=copy.deepcopy(fact);fact.update(estimate=None,annotation='N',margin_of_error=None,moe_annotation='*****')
  with patch.object(self.core,'stat_finding',return_value=fact):bound=indicator_payload(self.core,self.inv.snapshot_id,'house','013',2026)
  self.assertIsNone(bound['estimate']);self.assertIsNone(bound['margin_of_error']);self.assertEqual(bound['moe_annotation'],'*****')
 def test_indicator_print_unavailable_margin_and_incompatible_boundary(self):
  from districtbrief import render
  plan=recipe({'state_fips':'15','chamber':'house','code':'013','boundary_session':2024});r=self.request(plan);out=self.inv.handle(r)
  chosen=out['claims'][0]['claim_ref'];r.update(mode='brief',selected_claim_refs=[chosen],selected_action_ref=None,staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
  with patch.object(self.core.geo,'geometry_equal_across_sessions',return_value=False):brief=self.inv.handle(r)['brief']
  self.assertFalse(brief['district_indicator']['geometry_compatible']);self.assertIn('remains unshaded',brief['html']);self.assertEqual(len(brief['entries']),1);self.assertEqual(brief['entries'][0]['finding_id'],chosen['finding_id'])
  self.assertEqual(brief['district_indicator']['snapshot_id'],r['snapshot_id']);self.assertEqual(brief['district_indicator']['session'],r['plan']['map_session'])
  data=copy.deepcopy(brief);data['district_indicator'].update(estimate=None,annotation='N',margin_of_error=None,moe_annotation='*****')
  text=render.indicator_context_text(data);self.assertIn('display class unavailable',text);self.assertIn('90% MOE unavailable',text);self.assertNotIn('all people 0%',text)
 def test_language_disabled_ingress_and_static(self):
  with tempfile.TemporaryDirectory() as d:
   app=Application(d,secure_cookie=False)
   def call(path,body=None,cookie='',origin=None,raw=None):
    payload=raw if raw is not None else json.dumps(body).encode() if body is not None else b'';status=[]
    env={'REQUEST_METHOD':'GET' if body is None and raw is None else 'POST','PATH_INFO':path,'HTTP_HOST':'example.test','HTTP_COOKIE':cookie,'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(payload)),'wsgi.input':io.BytesIO(payload)}
    if origin:env['HTTP_ORIGIN']=origin
    def respond(code,headers):status.extend([int(code.split()[0]),dict(headers)])
    data=b''.join(app(env,respond));return status[0],status[1],json.loads(data) if data and 'json' in status[1]['Content-Type'] else data
   try:
    code,h,cat=call('/api/catalog');self.assertFalse(cat['language']['enabled']);self.assertNotIn('language',cat['investigation']);cookie=h['Set-Cookie'].split(';')[0]
    self.assertEqual(call('/static/language_state.js')[0],200)
    for action in ('start','status','cancel'):
     code,_,out=call('/api/language/'+action,{},cookie);self.assertEqual(code,503);self.assertEqual(out['model_calls'],0)
     self.assertEqual(call('/api/language/'+action,{},cookie,'https://other.test')[0],403)
     self.assertEqual(call('/api/language/'+action,{},cookie,raw=b'{"x":1,"x":2}')[0],400)
     self.assertEqual(call('/api/language/'+action,{},cookie,raw=b'{"x":1e999}')[0],400)
    with patch.object(app.language,'handle',return_value=(202,{'status':'pending','model_calls':0})):
     self.assertEqual(call('/api/language/start',{},cookie)[0],202)
   finally:
    for h in app.service.metrics.handlers:h.close()
