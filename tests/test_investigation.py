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
        r=self.request();r['plan']['steps'][1]['args']['comparison_geography']='HI-COUNTY-999-2024';o=self.i.handle(r)
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
        self.assertTrue(brief['action_citations']);self.assertIn('Agency action',brief['html']);self.assertIn('<strong>Next step:</strong> Kūpuna Care — '+self.i.core.programs['kupuna_care_hi']['referral']['next_step'],brief['html'])
        self.assertEqual(brief['html'].count(self.i.core.programs['kupuna_care_hi']['referral']['next_step']),1,'the recorded next step prints once, as the brief\'s Next step');self.assertLessEqual(brief['print_units'],7000)

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


class StaffPresentationTests(unittest.TestCase):
    """Ordinary staff text (screen brief, print brief, source view) carries human labels only; machine identities
    stay in the reply, the case contract and diagnostics. The print-fit estimate is unchanged by presentation."""
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.app=Application(cls.tmp.name,secure_cookie=False);cls.i=cls.app.investigation
    @classmethod
    def tearDownClass(cls):
        for h in cls.app.service.metrics.handlers:h.close()
        cls.tmp.cleanup()
    request=InvestigationTests.request
    @staticmethod
    def visible(html):
        import re
        return re.sub(r'<[^>]+>',' ',html)
    def assert_human(self,text):
        import re
        for pattern in (r'sha256',r'[0-9a-f]{12,}',r'snapshot',r'\b(stat|cmp|prog|lead|admin):',r'\bdbedt_\w+|\bhi_\w+_\w+|\btigerweb_\w+',
                        r'extracted/|data/statistics|packet path|\.txt\b',r'[{}]',r'\bbrief:[0-9a-f]',r'frozen fixture',r'No model generated'):
            self.assertIsNone(re.search(pattern,text,re.I),(pattern,re.search(pattern,text,re.I) and text[max(0,re.search(pattern,text,re.I).start()-60):][:140]))

    def test_printed_brief_is_human_and_keeps_machine_identity_in_data(self):
        for chamber,code in [('house','028'),('house','013'),('senate','025')]:
            r=self.request(chamber,code);o=self.i.handle(r)
            b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[c['claim_ref'] for c in o['claims'][:4]],selected_action_ref=o['responses'][0]['action_ref'],
                staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
            brief=self.i.handle(b)['brief'];text=self.visible(brief['html'])
            self.assert_human(text)
            self.assertIn('Retrieved 2026-',text);self.assertNotIn('Checked 2026',text)
            self.assertIn('ACS 2020–2024 5-year estimates by '+('Senate' if chamber=='senate' else 'House')+' district (workbook)',text)
            self.assertIn('Sheet DP0',text)
            # Machine identities remain available outside the printed text.
            self.assertTrue(brief['snapshot_id'].startswith('sha256:'));self.assertTrue(all(c['sha256'] and c['source_id'] for c in brief['citations']))
            self.assertEqual([e['finding_id'] for e in brief['entries']],[c['claim_ref']['finding_id'] for c in o['claims'][:4]])
            self.assertIn('data-finding-id="'+brief['entries'][0]['finding_id']+'"',brief['html'])

    def test_h013_kalawao_route_stays_in_the_printed_verification_questions(self):
        r=self.request('house','013');o=self.i.handle(r)
        b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[o['claims'][0]['claim_ref']],selected_action_ref=o['responses'][0]['action_ref'],staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
        text=self.visible(self.i.handle(b)['brief']['html'])
        self.assertIn('House 013 includes Kalawao',text);self.assertIn('808-586-0100',text)

    def test_print_estimates_for_four_finding_briefs_with_agency_step(self):
        for (chamber,code),units in {('house','028'):4919,('house','013'):5098,('senate','025'):4918}.items():
            r=self.request(chamber,code);o=self.i.handle(r)
            b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[c['claim_ref'] for c in o['claims'][:4]],selected_action_ref=o['responses'][0]['action_ref'],
                staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
            self.assertEqual(self.i.handle(b)['brief']['print_units'],units,(chamber,code))

    def test_source_view_names_what_it_supports_and_cannot_establish(self):
        from districtbrief import render
        out=self.i.handle(self.request());seen=set()
        for c in out['claims']:
            for ref in c['source_inspection_refs']:
                key=(ref['source_id'],ref['finding_id'])
                if key in seen:continue
                seen.add(key);html=render.source_html(self.i.core.source(*key));text=self.visible(html)
                self.assert_human(text)
                for label in ('Publisher','Retrieved','What this source cannot establish','official document title and publication date are not recorded'):
                    self.assertIn(label,text,key)
                self.assertIn(render.source_label(ref['source_id']),text)
        self.assertGreaterEqual(len(seen),5)

    def test_locator_wording_and_source_labels(self):
        from districtbrief import render
        self.assertEqual(render.human_locator('DP03!D145 (MOE E145)'),'Sheet DP03, cell D145 (MOE E145)')
        self.assertEqual(render.human_locator('extracted/hi_kupuna_law.txt lines 112–116'),'Lines 112–116')
        self.assertEqual(render.human_locator('Historical source locator: {"line_end": 65, "line_start": 61, "text_path": "extracted/hi_snap_rules.txt"}'),'Lines 61–65')
        self.assertEqual(render.human_locator('{"sheet": "JUL", "cell": "H12", "row_label": "STATE"}'),'Sheet JUL, cell H12 (row STATE)')
        self.assertEqual(render.human_locator('sheet: JUL; cell: H12; path: data/x.xlsx'),'Sheet JUL; Cell H12')
        sources=self.i.core.packet.sources
        for sid,src in sources.items():
            label=render.source_label(sid,src.get('url'))
            self.assertTrue(label and sid not in label and not label.startswith('Recorded source'),sid)
        html=render.sources_html({'sources':[dict(src,source_id=sid) for sid,src in sources.items()]})
        import re
        data=json.loads(re.search(r'<script type="application/json" id="source-label-data">(.*?)</script>',html,re.S).group(1))
        self.assertEqual(set(data),set(sources))

    def test_catalog_coverage_copy_follows_catalog_geographies(self):
        from districtbrief import render
        cat=self.app.service.catalog();text=self.visible(render.catalog_html(cat)).split('Normalized geographies')[0]
        self.assertEqual(len(cat['geographies']),82)
        for label in ('State of Hawaiʻi','Maui County','Hawaii County','Honolulu County','Kalawao County','Kauai County'):
            self.assertIn(label,text)
        self.assertIn('Comparison geographies (6):',text);self.assertIn('Every House and Senate district of the 2024 boundary session has statistics (76).',text)
        self.assertNotIn('Not normalized',text);self.assertNotIn('without statistics',text);self.assertIn('3,280 statistics in this data',text);self.assertNotIn('IA-1',text)
        self.assertIn('This app displays complete retained district boundaries',text)
        # A limited snapshot: fewer districts, only the State as comparison, one unavailable geography named.
        limited=copy.deepcopy(cat)
        limited['geographies']=[g for g in cat['geographies'] if g['kind']=='state']+[g for g in cat['geographies'] if g['kind']=='district'][:3]
        limited['unavailable_geographies']=[{'geography_id':'HI-COUNTY-009-2024','label':'Maui County'}]
        kept={g['geography_id'] for g in limited['geographies']};limited['observations']=[o for o in cat['observations'] if o['geography_id'] in kept]
        t=self.visible(render.catalog_html(limited)).split('Normalized geographies')[0]
        self.assertIn('3 of 76 House and Senate districts of the 2024 boundary session have statistics.',t)
        self.assertIn('Comparison geographies (1): State of Hawaiʻi.',t);self.assertIn('Geographies without statistics in this data: Maui County.',t)

    def test_brief_groups_selected_findings_and_prints_outreach_in_verbatim_parts(self):
        import re
        from districtbrief import render
        r=self.request('house','013');o=self.i.handle(r)
        picks=[c for c in o['claims'] if c['kind'] in ('statistic','outreach_hypothesis')][:1]+[c for c in o['claims'] if c['kind']=='outreach_hypothesis']
        b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[c['claim_ref'] for c in picks],selected_action_ref=o['responses'][0]['action_ref'],staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
        brief=self.i.handle(b)['brief'];html=brief['html'];text=self.visible(html)
        self.assertNotIn('Verified findings',text);self.assertIn('Selected findings',text)
        self.assertIn('Published estimates (survey estimates with margins of error)',text);self.assertIn('Outreach hypotheses (not measured gaps or eligibility findings)',text)
        hyp=next(en for en in brief['entries'] if en['kind']=='outreach_hypothesis')
        claim,segs=render.outreach_parts(hyp['text'])
        self.assertEqual(claim+''.join(' '+h+' '+'; '.join(items) for h,items in segs),hyp['text'],'segments keep every character')
        self.assertEqual([h for h,_ in segs][1:],['Program context (informational):','Unknowns the agency determines:','Next step:'])
        self.assertIn('class="brief-part-item"',html)
        self.assertIsNone(render.outreach_parts('A sentence without the recorded section labels.'))
        markers=[[int(n) for n in re.findall(r'\[(\d+)\]',m)] for m in re.findall(r'((?:<a class="cite"[^>]*>\[\d+\]</a>)+)',html)]
        self.assertTrue(markers and all(m==sorted(m) for m in markers),'citation markers in order')
        # The validated agency action's recorded next step leads the brief once; the hypothesis keeps its own part.
        self.assertIn('<section class="brief-takeaway"><p><strong>Next step:</strong> Kūpuna Care — Contact the county office on aging',html)
        self.assertNotIn('Recorded next step',html)
        self.assertIn('Hawaiʻi DOH Executive Office on Aging',text);self.assertNotIn('labelled',text)
        self.assertIn('Hawaiʻi DBEDT / U.S. Census Bureau ACS',text)
        self.assertEqual(brief['entries'][0]['text'],picks[0]['text'],'recorded claim text unchanged in the brief data')

    def test_display_names_keep_records_and_titles(self):
        from districtbrief import render
        self.assertEqual(render.hawaii_display('Hawaii DHS, Benefit, Employment & Support Services Division'),'Hawaiʻi DHS, Benefit, Employment & Support Services Division')
        self.assertEqual(render.hawaii_display('Hawaii statewide through county aging offices'),'Hawaiʻi statewide through county aging offices')
        for kept in ('Hawaii County','Bridging the Gap Hawaii (HI-501 Continuum of Care)','https://files.hawaii.gov/dbedt/x.xlsx'):
            self.assertEqual(render.hawaii_display(kept),kept)
        self.assertEqual(self.i.core.packet.sources['dbedt_2024_house']['publisher'],'Hawaii DBEDT / U.S. Census Bureau ACS','stored record unchanged')

    def test_printed_dollar_wording_is_readable_and_records_unchanged(self):
        import re
        from districtbrief import render
        from districtbrief.interpret import food_assistance_recipe
        plan=food_assistance_recipe({'state_fips':'15','chamber':'house','code':'028','boundary_session':2024})
        r=self.request();r.update(plan=plan,recipe_version='food_assistance_outreach/1');o=self.i.handle(r)
        income=next(c for c in o['claims'] if c['kind']=='statistic' and c['metric']['metric_id']=='median_household_income')
        hyp=next(c for c in o['claims'] if c['kind']=='outreach_hypothesis')
        b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[income['claim_ref'],hyp['claim_ref']],selected_action_ref=o['responses'][0]['action_ref'],staff_edits={},checklist_edits=[],tracking=None,edits_reviewed_for=None)
        brief=self.i.handle(b)['brief'];text=self.visible(brief['html'])
        self.assertIn('Median household income: $57,784 (2024 inflation-adjusted dollars) (90% margin of error ±$5,211); universe: Households',text)
        self.assertIn('Median household income: $57,784 ±$5,211 (state $100,389 ±$1,121; difference −$42,605) (2024 inflation-adjusted dollars)',text)
        self.assertIsNone(re.search(r'\d 2024 inflation-adjusted|\bUSD\b',text),'no adjacent value and year, no raw USD in the printed page')
        # Recorded text, entry text and claim identity are unchanged.
        self.assertIn('57,784 2024 inflation-adjusted USD (±5,211 90% MOE)',income['text'])
        self.assertEqual([en['text'] for en in brief['entries']],[income['text'],hyp['text']])
        # Other wording is printed unchanged and safely escaped.
        for t in ('Renter units paying 35%+ of income for gross rent 2,866 ±412 housing units.','Poverty rate, all people 23.4% ±3.1 (state 10.0% ±0.3; difference +13.4 percentage points)',
                  'House District 028 (boundary session 2024): Median household income MOE 5,211 (controlled estimate; no sampling MOE) 57,784 2024 inflation-adjusted USD'):
            self.assertEqual(render.dollar_wording(t),t)
        odd=render._finding_body({'kind':'statistic','text':'X: <b>Label</b> 1,000 USD per month (±10 90% MOE); universe: U; ACS 2020–2024 5-year.'})
        self.assertIn('&lt;b&gt;Label&lt;/b&gt;: $1,000 (dollars per month) (90% margin of error ±$10)',odd)

    def _brief_for(self,chamber,code,want,food=False,staff=None):
        from districtbrief.interpret import food_assistance_recipe
        r=self.request(chamber,code)
        if food:
            plan=food_assistance_recipe({'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024});r.update(plan=plan,recipe_version='food_assistance_outreach/1')
        o=self.i.handle(r)
        picks=[next(c for c in o['claims'] if c['kind']==k and (m is None or c.get('metric',{}).get('metric_id')==m) and (k!='statistic' or c['geography']['geography_id'].split('-')[1] in ('HOUSE','SENATE'))) for k,m in want]
        b=copy.deepcopy(r);b.update(mode='brief',selected_claim_refs=[c['claim_ref'] for c in picks],selected_action_ref=o['responses'][0]['action_ref'],staff_edits=staff or {},checklist_edits=[],tracking=None,
            edits_reviewed_for={'branch_id':b['branch_id'],'revision':1,'plan_hash':plan_hash(b['plan'])} if staff else None)
        return self.i.handle(b)['brief'],picks

    def test_printed_brief_is_compact_without_losing_recorded_content(self):
        import re
        from districtbrief import render
        from districtbrief.core import L_COMPARE,L_NO_ELIG,L_HYPOTHESIS
        brief,picks=self._brief_for('house','028',[('statistic','population_65_plus'),('statistic','poverty_rate_65_plus')],staff={'note':'Short staff summary.'})
        html=brief['html'];text=re.sub(r'\s+',' ',self.visible(html)).replace('( ','(').replace(' )',')')
        self.assertIn('Population age 65 and over: 6,463 persons (90% margin of error ±542 persons)',text)
        self.assertIn('Poverty rate, age 65 and over: 29.0% (90% margin of error ±4.3 percentage points)',text)
        self.assertIn('Short staff summary.',text)
        self.assertNotIn('Point differences of published estimates only',text,'no comparison or hypothesis printed')
        self.assertIn(L_COMPARE,brief['limitations'],'recorded limitations unchanged')
        printed=render.printed_limitations(brief)
        self.assertTrue(set(printed)<=set(brief['limitations']));self.assertIn(L_NO_ELIG,printed);self.assertIn(L_HYPOTHESIS,printed)
        self.assertNotIn('class="brief-foot"',html,'footer repeated two printed limitations')
        self.assertNotIn('Current availability and cost unverified.',text);self.assertIn('Current availability, capacity, wait, funding and cost remain unverified.',text)
        for c in brief['citations']:
            self.assertIn(f'href="{c["url"]}"',html)
        self.assertIn('ACS 2020–2024 5-year estimates by House district (workbook). https://files.hawaii.gov/dbedt/census/acs/acs2024/5yr/acs2024_5yr_house_hi.xlsx · Retrieved 2026-10-30',re.sub(r'\s+',' ',self.printed_text(html)).replace(' .','.'))
        self.assertEqual([en['text'] for en in brief['entries']],[c['text'] for c in picks],'recorded entry text unchanged')

    @staticmethod
    def printed_text(html):
        """What a reader sees and copies: inline tags (<wbr>, <span>, <a>) add nothing, other tags separate, entities decoded."""
        import re,html as h
        return h.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'</?(?:wbr|span|a)\b[^>]*>','',html)))

    def test_printed_sources_show_full_canonical_urls_and_locators(self):
        # Saved PDFs may drop link targets, so each source's full recorded address must be printed text.
        import re
        from districtbrief import render
        cases=[('house','013',[('statistic','population_65_plus'),('statistic','poverty_rate_65_plus')],False),
               ('senate','025',[('statistic','population_65_plus'),('statistic','poverty_rate_65_plus')],False),
               ('house','028',[('statistic','median_household_income'),('outreach_hypothesis',None)],True)]
        for chamber,code,want,food in cases:
            brief,_=self._brief_for(chamber,code,want,food=food,staff={'note':'Short staff summary.'})
            printed=self.printed_text(brief['html'])
            self.assertTrue(brief['citations'])
            for c in brief['citations']:
                rec=self.i.core.packet.sources[c['source_id']]
                self.assertEqual(c['url'],rec['url'],'citation keeps the canonical recorded URL')
                self.assertIn(c['url'],printed,f'{chamber} {code}: full URL printed for {c["source_id"]}')
                self.assertNotRegex(printed,re.escape(c['url'])+r'\w','no truncated or altered tail')
                self.assertIn(f'href="{c["url"]}"',brief['html'],'link target unchanged')
                item=self.printed_text(re.search(rf'<li id="cite-{c["n"]}">.*?</li>',brief['html']).group(0))
                self.assertIn(render.hawaii_display(c['publisher']),item);self.assertIn('Retrieved '+render.human_date(c.get('retrieved_at_utc')),item)
                self.assertNotIn('…',item)
                for raw in c['locators']:
                    m=render._SHEET_CELL.match(str(raw))
                    if m:
                        self.assertIn(f'Sheet {m["sheet"]}',item);self.assertIn(f'{m["cell"]} (MOE {m["moe"]})',item)
                    else:
                        self.assertIn(render.human_locator(raw),item)
        # Unknown or hostile strings stay escaped; the address is still printed exactly as text.
        bad={'n':9,'source_id':'not_in_catalog','publisher':'<b>Pub</b> & co','url':'https://example.org/a/<script>?q="x"&r=1',
             'retrieved_at_utc':'2026-10-30T00:00:00Z','locators':['<img src=x onerror=1>']}
        out=render._citation_html(bad)
        self.assertNotIn('<script>',out);self.assertNotIn('<b>',out);self.assertNotIn('<img',out)
        self.assertIn('<span class="url-host">https://example.org</span>/<wbr>a/<wbr>&lt;script&gt;?q=&quot;x&quot;&amp;r=1',out)
        self.assertIn(bad['url'],self.printed_text(out))

    def test_printed_urls_wrap_only_after_path_slashes_in_the_brief_font(self):
        # The address keeps scheme://host on one line, offers breaks only after path slashes, and uses no
        # invisible characters, so copied or extracted text is the canonical address after removing line wraps.
        import re,html as h,os
        from districtbrief import render
        brief,_=self._brief_for('house','013',[('statistic','population_65_plus'),('statistic','poverty_rate_65_plus')],staff={'note':'Short staff summary.','next_steps':'Call the county office on aging this week.'})
        page=brief['html']
        for ch in ('\u200b','\u200c','\u200d','\u2060','\ufeff','\u00ad'):
            self.assertNotIn(ch,page)
        spans=re.findall(r'<span class="url">(.*?)</span> · Retrieved',page)
        self.assertEqual(len(spans),len(brief['citations']))
        for c,span in zip(brief['citations'],spans):
            scheme,_,rest=c['url'].partition('://');host,_,path=rest.partition('/')
            self.assertTrue(span.startswith(f'<span class="url-host">{h.escape(scheme+"://"+host)}</span>/<wbr>'),span)
            self.assertNotIn('<wbr>',re.search(r'<span class="url-host">(.*?)</span>',span).group(1))
            self.assertEqual(span.count('<wbr>'),path.count('/')+1,'one break opportunity after each path slash')
            self.assertTrue(all(span[i-1]=='/' for i in [m.start() for m in re.finditer('<wbr>',span)]))
            self.assertEqual(h.unescape(re.sub(r'<[^>]+>','',span)),c['url'])
        self.assertEqual(render._url_html('https://example.org'),'<span class="url-host">https://example.org</span>')
        self.assertEqual(render._url_html('a/b'),'a/<wbr>b')
        # Brief font and sizes: the address uses the brief's named stack at the 8.5pt secondary size.
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'static','app.css'),encoding='utf-8') as f:
            css=f.read()
        rule=lambda sel: re.search(re.escape(sel)+r' \{([^}]*)\}',css).group(1)
        self.assertIn('font-family: inherit;',rule('.brief-doc .brief-cites .url'));self.assertIn('font-size: inherit;',rule('.brief-doc .brief-cites .url'))
        self.assertIn('font-variant-ligatures: none;',rule('.brief-doc .brief-cites .url'))
        self.assertIn('white-space: nowrap;',rule('.url .url-host'))
        self.assertIn('--brief-body: 9.5pt;',css);self.assertIn('--brief-small: 8.5pt;',css)
        self.assertIn('font-family: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif;',css)
        # The fit probe measures the same spacings that print: no print-only spacing overrides remain.
        for sel in ('#print-root .brief-doc section.staff-edit','#print-root .brief-doc h2 {','#print-root .brief-doc .brief-limits {'):
            self.assertNotIn(sel,css)

    def test_snap_brief_prints_hypothesis_label_once_and_eligibility_once(self):
        import re
        brief,picks=self._brief_for('house','028',[('statistic','median_household_income'),('outreach_hypothesis',None)],food=True)
        text=re.sub(r'\s+',' ',self.visible(brief['html']))
        self.assertNotIn('Outreach hypothesis Outreach hypothesis',text);self.assertEqual(text.count('Outreach hypothesis — not a measured gap'),1)
        self.assertIn('Eligibility facts the agency determines: the same open questions as listed under the outreach hypothesis above.',text)
        self.assertEqual(text.count('Countable gross/net income and allowable deductions'),1,'listed once, under the hypothesis')
        self.assertIn('Median household income: $57,784 (2024 inflation-adjusted dollars) (90% margin of error ±$5,211)',text)

    def test_figure_wording_covers_recorded_statistics_and_keeps_values(self):
        import re
        from districtbrief import render
        cat=self.i.core.catalog();formatted=unchanged=0
        def vals(t):
            t=re.sub(r'2024 inflation-adjusted (USD|dollars)|(USD|dollars) per month|90% MOE|90% margin of error|ACS 2020–2024 5-year|\(boundary session 2024\)','',t)
            return [x.replace('$','') for x in re.findall(r'[+−-]?\$?\d[\d,.]*',t)]
        for o in cat['observations']:
            t=self.i.core.stat_finding(o['geography_id']+':'+o['metric_id'])['text'];d=render.figure_wording(t)
            if d==t:
                unchanged+=1;self.assertIn('controlled estimate',t);continue
            formatted+=1;self.assertEqual(vals(t),vals(d),t);self.assertNotIn('90% MOE',d)
        self.assertEqual((formatted,unchanged),(3274,6))
        self.assertEqual(render.figure_wording('Something else 12 ±3 <b>'),'Something else: 12 ±3 <b>')
        self.assertEqual(render.figure_wording('No figures here.'),'No figures here.')
