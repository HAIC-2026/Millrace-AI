"""Meaningful IA-1 contract, partial-execution and security regression checks."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from public_app import Application
from districtbrief.case_contract import InvestigationError
from districtbrief.claim_binding import plan_hash
from districtbrief.interpret import recipe

class InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.app=Application(cls.tmp.name,secure_cookie=False);cls.i=cls.app.investigation
    @classmethod
    def tearDownClass(cls):
        for h in cls.app.service.metrics.handlers:h.close()
        cls.tmp.cleanup()
    def request(self,chamber='house',code='028'):
        return {**{k:str(uuid.uuid4()) for k in ('request_id','case_id','branch_id')},'revision':1,'schema_version':'haic-investigation/1','operation_version':'ia-core/1','recipe_version':'aging_at_home/1','snapshot_id':self.i.snapshot_id,'mode':'run','plan':recipe({'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024}),'selected_claim_refs':[],'selected_action_ref':None}
    def call(self,path,body=None,cookie='',raw=None,**overrides):
        raw=raw if raw is not None else json.dumps(body).encode() if body is not None else b''
        target,_,query=path.partition('?');env={'REQUEST_METHOD':'POST' if body is not None or raw else 'GET','PATH_INFO':target,'QUERY_STRING':query,'wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),'CONTENT_TYPE':'application/json','HTTP_HOST':'example.test','HTTP_COOKIE':cookie};env.update(overrides)
        status=[]
        def start(s,h):status.extend([int(s.split()[0]),dict(h)])
        data=b''.join(self.app(env,start));return status[0],status[1],json.loads(data) if data and 'json' in status[1]['Content-Type'] else data
    def session(self):return self.call('/api/catalog')[1]['Set-Cookie'].split(';')[0]
    def brief(self,r,o):
        r=copy.deepcopy(r);r.update(mode='brief',selected_claim_refs=[o['claims'][0]['claim_ref']],selected_action_ref=None,staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None);return r
    def test_primary_values_and_uniform_method(self):
        for chamber,code,expected in [('house','028','+19.8'),('house','013','+1.0'),('senate','025','−3.9')]:
            r=self.request(chamber,code);o=self.i.handle(r);self.assertEqual(o['status'],'ok');self.assertEqual(o['model_calls'],0)
            cmp=next(c for c in o['claims'] if c['kind']=='comparison');self.assertEqual(cmp['difference']['display'],expected);self.assertIn('No statistical difference test was performed.',cmp['text'])
            self.assertEqual([x['program_id'] for x in o['responses']],['kupuna_care_hi'])
    def test_partial_and_no_hidden_substitute(self):
        r=self.request();r['plan']['steps'][1]['args']['comparison_geography']='HI-COUNTY-003-2024';o=self.i.handle(r)
        self.assertEqual(o['status'],'partial');self.assertEqual(o['steps'][1]['reason_code'],'comparison_geography_unavailable');self.assertTrue(o['claims'])
    def test_interpret_full_grammar_and_zero_dispatch(self):
        for utterance,status in [('aging at home in house 28','ok'),('use district 13','clarification'),('compare poverty with state','unsupported'),('add snap but not for seniors','unsupported'),('compare senior poverty with state without uncertainty','unsupported'),('add med-quest','ok')]:
            r=self.request();r.update(mode='interpret',utterance=utterance);r.pop('selected_claim_refs');r.pop('selected_action_ref')
            with patch.object(self.i.core,'profile',side_effect=AssertionError('dispatch')):o=self.i.handle(r)
            self.assertEqual(o['status'],status,utterance);self.assertEqual(o['claims'],[])
    def test_literal_whitespace_spans_and_null_subject(self):
        from districtbrief.interpret import interpret
        for phrase in ['aging   at home in house 28','compare senior poverty with state for house 28','program kūpuna care for house 28']:
            status,plan,reading=interpret(phrase,None)
            self.assertEqual(status,'ok',phrase);self.assertEqual(plan['district']['code'],'028')
            for field in reading['matched_fields']:
                start,end=field['span'];self.assertTrue(0<=start<end<=len(phrase))

    def test_every_derived_source_reference_is_inspectable(self):
        out=self.i.handle(self.request());refs={(r['source_id'],r['finding_id']) for c in out['claims'] for r in c['source_inspection_refs']}
        self.assertTrue(refs)
        for sid,fid in refs:
            source=self.i.core.source(sid,fid)
            self.assertIsNotNone(source['detail'],(sid,fid))
            self.assertNotIn(fid.split(':')[0],('cmp','lead'))

    def test_hypothesis_full_basis_and_state_reference(self):
        r=self.request('house','013');r['plan']['steps'][0]['args']['metric_ids']=['population_65_plus'];o=self.i.handle(r)
        h=next(x for x in o['claims'] if x['kind']=='outreach_hypothesis');self.assertEqual(len(h['measure_ids']),4)
        before=h['claim_ref'];r['plan']['steps'][1]['args']['comparison_geography']='HI-COUNTY-009-2024';o=self.i.handle(r)
        self.assertEqual(next(x for x in o['claims'] if x['kind']=='outreach_hypothesis')['claim_ref'],before)
        county=next(x for x in o['claims'] if x['kind']=='comparison' and x['right']['geography']['geography_id']=='HI-COUNTY-009-2024')
        self.assertTrue(any('containment' in x for x in county['limitations']))
        r['plan']['steps'][3]['args']['metric_ids']=['population_65_plus']
        with self.assertRaises(InvestigationError) as e:self.i.handle(r)
        self.assertEqual(e.exception.code,'reviewed_basis_required')
    def test_changed_comparison_retires_selection_but_keeps_hypothesis_basis(self):
        r=self.request('house','013');original=self.i.handle(r)
        state_ref=next(c['claim_ref'] for c in original['claims'] if c['kind']=='comparison')
        hypothesis=next(c['claim_ref'] for c in original['claims'] if c['kind']=='outreach_hypothesis')
        statistic=original['claims'][0]['claim_ref']
        r['selected_claim_refs']=[state_ref,hypothesis,statistic]
        unchanged=self.i.handle(r)
        self.assertEqual([x['state'] for x in unchanged['selection_review']],['retained']*3)
        r['plan']['steps'][1]['args']['comparison_geography']='HI-COUNTY-009-2024'
        changed=self.i.handle(r)
        self.assertEqual([x['state'] for x in changed['selection_review']],['retired','retained','retained'])
        h=next(c for c in changed['claims'] if c['kind']=='outreach_hypothesis')
        self.assertEqual(h['claim_ref'],hypothesis);self.assertIn(state_ref,h['dependencies'])
        self.assertTrue(any(c['claim_ref']==state_ref for c in changed['claims']))
        b=self.brief(r,changed);b['selected_claim_refs']=[state_ref]
        with self.assertRaises(InvestigationError) as exc:self.i.handle(b)
        self.assertEqual(exc.exception.code,'selection_conflict')
        r['plan']['steps']=[s for s in r['plan']['steps'] if s['operation']!='compare']
        removed=self.i.handle(r)
        self.assertEqual([x['state'] for x in removed['selection_review']],['retired','retained','retained'])

    def test_core_overflow_exposes_estimate_and_budget(self):
        r=self.request();r['plan']['steps'][0]['args']['metric_ids']=None;o=self.i.handle(r)
        refs=[c['claim_ref'] for c in o['claims'] if c['kind']=='statistic'][:8]
        b=self.brief(r,o);b['selected_claim_refs']=refs
        b['staff_edits']={'title':'W'*90,'note':'W'*400,'next_steps':'W'*300,'finding_notes':{ref['semantic_hash']:'W'*160 for ref in refs}}
        b['edits_reviewed_for']={'branch_id':b['branch_id'],'revision':b['revision'],'plan_hash':plan_hash(b['plan'])}
        with self.assertRaises(InvestigationError) as exc:self.i.handle(b)
        self.assertEqual(exc.exception.code,'brief_overflow')
        self.assertTrue(any('print_units=' in issue['message'] and 'print_budget=7000' in issue['message'] for issue in exc.exception.issues))

    def test_program_specific_verification_changes_the_office_decision(self):
        from districtbrief.rationale import PROGRAM_RATIONALE
        r=self.request();r['plan']['steps'] += [
            {'step_id':'s5','operation':'program_evidence','args':{'program_ids':['snap_hi']}},
            {'step_id':'s6','operation':'outreach_lead','args':{'program_id':'snap_hi'}}]
        code,_,out=self.call('/api/investigation',r,self.session());self.assertEqual(code,200,out)
        snap=next(c for c in out['responses'] if c['program_id']=='snap_hi')
        words=' '.join(snap['facts_to_verify']);checklist=' '.join(c['text'] for c in snap['template_checklist'])
        for required in ('BESSD','food-assistance','combined aging and food-information session','separate official referrals'):
            self.assertIn(required,words)
        self.assertIn('No partner, session or appointment is confirmed.',words)
        self.assertIn('participation/approval answers',checklist)
        for unrelated in ('assessment access','provider reach','808-586-0100','Kalawao'):
            self.assertNotIn(unrelated,words)
        h=next(c for c in out['claims'] if c['kind']=='outreach_hypothesis' and c['program']['program_id']=='snap_hi')
        self.assertEqual(h['measure_ids'],PROGRAM_RATIONALE['snap_hi']['metrics'])
        self.assertTrue(any(ref['finding_id'].startswith('cmp:HI-HOUSE-028-2024~HI-STATE-2024:') for ref in h['dependencies']))
        care_code,_,care_out=self.call('/api/investigation',self.request('house','013'),self.session());self.assertEqual(care_code,200,care_out);care=care_out['responses'][0]
        care_words=' '.join(care['facts_to_verify']);self.assertIn('808-586-0100',care_words);self.assertIn('provider reach',care_words);self.assertIn('Kalawao',care_words)
        self.assertNotIn('BESSD',care_words);self.assertTrue(any('age-60+' in x for x in care['weakening_facts']))
        from districtbrief.claim_binding import digest
        legacy_care_binding={'binding_version':'ia-action/1','operation_version':'ia-core/1','snapshot_id':self.i.snapshot_id,
            'action_id':'kupuna_verify/1','program_claim_ref':care['program_claim_ref'],'hypothesis_claim_ref':care['hypothesis_claim_ref'],
            'support_claim_refs':care['support_claim_refs'],'service_scope':self.i.core.service_scope.resolve(self.request('house','013')['plan']['district'],'kupuna_care_hi'), 'template':self.i.templates}
        self.assertEqual(care['action_ref']['semantic_hash'],digest(legacy_care_binding))
        # SNAP's actual question/checklist text participates in its new identity.
        snap_binding={'binding_version':'ia-action/1','operation_version':'ia-core/1','snapshot_id':self.i.snapshot_id,
            'action_id':'snap_verify/1','program_claim_ref':snap['program_claim_ref'],'hypothesis_claim_ref':snap['hypothesis_claim_ref'],
            'support_claim_refs':snap['support_claim_refs'],'service_scope':self.i.core.service_scope.resolve(r['plan']['district'],'snap_hi'),
            'template':self.i.templates,'verification_questions':snap['facts_to_verify'],'template_checklist':snap['template_checklist']}
        self.assertEqual(snap['action_ref']['semantic_hash'],digest(snap_binding))
        old=copy.deepcopy(snap_binding);old.pop('verification_questions');old.pop('template_checklist')
        self.assertNotEqual(snap['action_ref']['semantic_hash'],digest(old))
        # The actual action brief prints the question and decision checklist.
        b=self.brief(r,out);b['selected_action_ref']=snap['action_ref'];brief=self.i.handle(b)['brief']
        self.assertIn('BESSD',brief['html']);self.assertIn('combined aging and food-information session',brief['html'])
        self.assertIn('participation/approval answers',brief['html'])
        for response in out['responses']:
            self.assertTrue(all(len(item['text'])<=120 for item in response['template_checklist']))

    def test_other_program_actions_keep_distinct_questions_and_wic_reference(self):
        r=self.request('house','013');r['plan']['steps']=[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['medquest_hi','hcv_honolulu','wic_hi']}}]
        o=self.i.handle(r);cards={c['program_id']:c for c in o['responses']}
        med=' '.join(cards['medquest_hi']['facts_to_verify']);hcv=' '.join(cards['hcv_honolulu']['facts_to_verify'])
        self.assertIn('coverage-information session',med);self.assertIn('Coverage status and individual eligibility remain unknown.',med)
        self.assertIn('Honolulu DCS',hcv);self.assertIn('closed-at-check',hcv);self.assertEqual(cards['hcv_honolulu']['access']['recorded_status'],'closed_at_check')
        for words in (med,hcv):
            self.assertNotIn('808-586-0100',words);self.assertNotIn('provider reach',words)
        self.assertEqual(cards['wic_hi']['tier'],'reference');self.assertIsNone(cards['wic_hi']['action_ref']);self.assertEqual(cards['wic_hi']['template_checklist'],[])

    def test_scope_never_uses_approx_point_or_auto_admin(self):
        r=self.request('house','013');pid='HI-HOUSE-013-2024';self.assertIsNone(self.i.core.county_of(pid))
        p=self.i.core.prog_finding('hcv_honolulu',pid);self.assertIsNone(p['jurisdiction_check']['in_agency_area']);self.assertNotIn('Outside this agency',p['text']);self.assertEqual(p['participation_context'],[])
        p=self.i.core.prog_finding('kupuna_care_hi',pid);self.assertEqual(p['referral']['phone'],'808-586-0100');self.assertTrue(any('Kalawao' in x for x in p['scope_questions']))
    def test_staff_review_and_escape(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o);b['staff_edits']={'note':'<script>Hawaiʻi & office</script>'}
        with self.assertRaises(InvestigationError) as e:self.i.handle(b)
        self.assertEqual(e.exception.code,'staff_review_required');b['edits_reviewed_for']={'branch_id':b['branch_id'],'revision':b['revision'],'plan_hash':plan_hash(b['plan'])}
        o=self.i.handle(b);self.assertIn('&lt;script&gt;',o['brief']['html']);self.assertNotIn('<script>',o['brief']['html'])
        b['revision']+=1
        with self.assertRaises(InvestigationError):self.i.handle(b)
    def test_foreign_and_changed_ref_block_brief(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o)
        other=self.i.handle(self.request('senate','025'));b['selected_claim_refs']=[other['claims'][0]['claim_ref']]
        with self.assertRaises(InvestigationError) as e:self.i.handle(b)
        self.assertEqual(e.exception.code,'foreign_context')
        b['selected_claim_refs']=[dict(o['claims'][0]['claim_ref'],semantic_hash='sha256:'+'0'*64)]
        with self.assertRaises(InvestigationError):self.i.handle(b)
    def test_validation_precedes_dispatch(self):
        mutations=[lambda r:r.update(extra=True),lambda r:r.update(revision=True),lambda r:r['plan'].update(service_area_id=[]),lambda r:r.update(mode={}),lambda r:r['plan']['steps'][0]['args'].update(extra=True)]
        for f in mutations:
            r=self.request();f(r)
            with patch.object(self.i.core,'profile',side_effect=AssertionError('dispatch')):
                with self.assertRaises(InvestigationError):self.i.handle(r)
    def test_http_protections_and_geometry(self):
        cookie=self.session();r=self.request()
        self.assertEqual(self.call('/api/investigation',r,cookie)[0],200)
        self.assertEqual(self.call('/api/investigation',r,self.session())[0],403)
        self.assertEqual(self.call('/api/investigation',self.request(),cookie,HTTP_ORIGIN='https://evil.example')[0],403)
        for raw,expected in [(b'{"mode":1,"mode":2}',400),(b'{"x":NaN}',400),(b'\xff',400),(b' '*65537,413)]:
            self.assertEqual(self.call('/api/investigation',cookie=cookie,raw=raw)[0],expected)
        self.assertEqual(self.call('/api/investigation',self.request(),cookie,CONTENT_TYPE='text/plain')[0],415)
        url='/api/geometry?snapshot_id='+self.i.snapshot_id+'&chamber=senate&code=025&session=2026'
        code,_,g=self.call(url);self.assertEqual(code,200);self.assertEqual(g['component_count'],10)
        self.assertEqual(self.call(url+'&other=1')[0],400)
        self.assertEqual(self.call(url.replace(self.i.snapshot_id,'sha256:'+'0'*64))[0],409)
    def test_tracking_without_action_is_printed(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o)
        b['tracking']={'label':'OFFICE_TRACKING_REVIEWED','baseline':3,'as_of':'2026-11-13'}
        b['edits_reviewed_for']={'branch_id':b['branch_id'],'revision':b['revision'],'plan_hash':plan_hash(b['plan'])}
        brief=self.i.handle(b)['brief'];self.assertIn('OFFICE_TRACKING_REVIEWED',brief['html']);self.assertIn('not a verified fact',brief['html'])

    def test_checklist_without_action_is_printed_and_reviewed(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o)
        b['checklist_edits']=[{'item_id':'custom1','text':'Reviewed office-only follow-up','owner_role':'Office role','completed':True},{'item_id':'agency_route','completed':False}]
        b['edits_reviewed_for']={'branch_id':b['branch_id'],'revision':b['revision'],'plan_hash':plan_hash(b['plan'])}
        brief=self.i.handle(b)['brief'];self.assertEqual(len(brief['checklist']),2);self.assertIn('Reviewed office-only follow-up',brief['html']);self.assertIn('Office role',brief['html']);self.assertIn('Verify responsible service route',brief['html'])
        self.assertIsNone(brief['action'])

    def test_action_cites_dependencies_without_selected_program_row(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o);b['selected_action_ref']=o['responses'][0]['action_ref']
        brief=self.i.handle(b)['brief'];self.assertEqual(len(brief['entries']),1)
        program=self.i.core.prog_finding('kupuna_care_hi','HI-HOUSE-028-2024')
        self.assertTrue({e['source_id'] for e in program['evidence']} <= {c['source_id'] for c in brief['citations']})
        self.assertTrue(brief['action_citations']);self.assertIn('Verification action',brief['html']);self.assertLessEqual(brief['print_units'],7000)

    def test_brief_canaries_absent_from_operational_logs(self):
        r=self.request();o=self.i.handle(r);b=self.brief(r,o);b['selected_action_ref']=o['responses'][0]['action_ref']
        b['staff_edits']={'title':'CANARY_TITLE','note':'CANARY_NOTE','next_steps':'CANARY_NEXT','finding_notes':{o['claims'][0]['claim_ref']['semantic_hash']:'CANARY_FINDING'}}
        b['checklist_edits']=[{'item_id':'custom1','text':'CANARY_CHECK','owner_role':'CANARY_OWNER','due_date':'2026-11-15','completed':True}]
        b['tracking']={'label':'CANARY_TRACK','baseline':7,'as_of':'2026-11-13'}
        b['edits_reviewed_for']={'branch_id':b['branch_id'],'revision':b['revision'],'plan_hash':plan_hash(b['plan'])}
        code,_,out=self.call('/api/investigation',b,self.session());self.assertEqual(code,200,out)
        logs=(Path(self.tmp.name)/'metrics.jsonl').read_text()
        self.assertNotIn('CANARY_',logs)
        self.assertIn('CANARY_NOTE',out['brief']['html'])

    def test_unexpected_step_failure_is_bounded(self):
        with patch.object(self.i.core,'profile',side_effect=RuntimeError('PRIVATE_CANARY')):o=self.i.handle(self.request())
        self.assertEqual(o['status'],'partial');self.assertEqual(o['steps'][0]['status'],'error');self.assertNotIn('PRIVATE_CANARY',json.dumps(o))
