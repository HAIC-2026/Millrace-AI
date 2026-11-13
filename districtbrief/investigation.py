"""Bounded, stateless whole-plan execution over the verified analytical core."""
from __future__ import annotations
import copy
import json
from . import render
from .case_contract import InvestigationError, OPERATION_VERSION, SCHEMA_VERSION, TOKEN_KEYS, validate_request
from .claim_binding import ClaimBindings, digest, plan_hash
from .core import Unsupported, BRIEF_PRINT_BUDGET, print_units, L_ACS, L_COMPARE, L_NO_GAP, L_NO_ELIG, L_HYPOTHESIS, SMALL_TEXT_WEIGHT
from .interpret import interpret, recipe
from .rationale import PROGRAM_RATIONALE

# Staff inquiry prompts, not newly sourced eligibility or availability facts.
# Each admitted program keeps a distinct office decision and agency route.
VERIFICATION_CONTENT = {
    'snap_hi': {
        'questions': [
            'Ask DHS BESSD whether SNAP staff or an agency-approved outreach provider can participate in a food-assistance information session for the selected inquiry area.',
            'Verify the current SNAP intake and referral route, agency-approved food-assistance materials, and who may answer household-specific questions; this office does not screen eligibility.',
            'If staff propose a combined aging and food-information session, ask each agency about participation, approved materials and separate referrals. No partner, session or appointment is confirmed.',
            'Record the participation and approval answers. If either agency cannot confirm arrangements, keep separate official referrals; pursue a combined session only after both agencies agree.',
        ],
        'checklist': [
            'Ask BESSD about SNAP outreach participation and the current food-assistance intake/referral route.',
            'Ask both agencies about a proposed combined aging/food session; verify materials and separate referrals.',
            'Record participation/approval answers, staff role and next check; use separate referrals if unconfirmed.',
        ],
    },
    'medquest_hi': {
        'questions': [
            'Ask Med-QUEST which office or agency-approved partner can provide coverage information and the current application/referral route for the selected inquiry area.',
            'Verify agency-approved coverage-group materials, including Medicare and Medicaid coordination. Coverage status and individual eligibility remain unknown.',
            'Ask whether the agency can review or participate in a coverage-information session. Without confirmation, use its official information route rather than promise enrollment help or coverage.',
        ],
        'checklist': [
            'Ask Med-QUEST for the current coverage-information and application/referral route.',
            'Request agency review of coverage-group materials and any proposed information-session participation.',
            'Record the agency answer, staff role and next check; use official referrals if participation is unconfirmed.',
        ],
    },
    'hcv_honolulu': {
        'questions': [
            'Ask City and County of Honolulu DCS whether it serves the specified location; district identity does not establish agency coverage.',
            'Given the retained closed-at-check waiting-list status, ask Honolulu DCS for its current status and permissible information/referral route. Do not promise an application or voucher.',
            'Record agency scope and status answers before choosing outreach. If either remains unresolved, do not offer this program as an open alternative.',
        ],
        'checklist': [
            'Ask Honolulu DCS to confirm the specified location and current waiting-list status.',
            'Verify DCS-approved information and referral arrangements; do not promise an application or voucher.',
            'Record scope/status answers, staff role and next check before choosing a DCS information referral.',
        ],
    },
}

class Investigation:
    def __init__(self,core,metadata=None):
        self.core=core;self.metadata=metadata or core.metadata
        self.data_snapshot_id=core.snapshot_id
        self.metadata_snapshot_id=self.metadata.metadata_snapshot_id
        self.snapshot_id=self.metadata.combined_snapshot_id(self.data_snapshot_id)
        self.templates=self.metadata.read_json('responses/verification.v1.json')
    def bootstrap(self):
        return {'schema_version':SCHEMA_VERSION,'operation_version':OPERATION_VERSION,'recipe_versions':['aging_at_home/1','custom/1'],
                'snapshot_id':self.snapshot_id,'data_snapshot_id':self.data_snapshot_id,'metadata_snapshot_id':self.metadata_snapshot_id,
                'release_id':self.release_id(),'input_profile':getattr(self.core.packet,'profile','r2'),
                'verification':self.core.packet.verification,'default_plan':recipe({'state_fips':'15','chamber':'house','code':'028','boundary_session':2024})}
    def release_id(self):
        # Release source identity is provided by the generated source manifest, separately from evidence identity.
        from pathlib import Path
        import hashlib
        p=Path(__file__).resolve().parents[1]/'RELEASE-MANIFEST.json'
        return 'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()
    def _envelope(self,r):
        return {'status':'ok','tokens':{k:r[k] for k in TOKEN_KEYS},'model_calls':0,'data_snapshot_id':self.data_snapshot_id,
            'metadata_snapshot_id':self.metadata_snapshot_id,'normalized_plan':copy.deepcopy(r['plan']),
            'interpretation':{'matched_fields':[],'inherited_fields':[],'choices':[],'reason':None},
            'steps':[],'claims':[],'responses':[],'selection_review':[],'action_review':None,'brief':None,'limitations':[]}
    def _review(self,ref,bindings,pid,comparison_results):
        state='retired';reason='claim_no_longer_in_plan'
        if ref['snapshot_id']!=self.snapshot_id:state,reason='stale_snapshot','snapshot_unavailable'
        elif self.core.finding_profile(ref['finding_id']) not in (None,pid):state,reason='foreign_context','foreign_primary_district'
        elif ref['finding_id'].startswith('cmp:') and ref not in comparison_results:
            # A hypothesis's fixed State reference is support, not a current
            # standalone comparison result after that plan step changes/removes.
            state,reason='retired','comparison_not_in_current_steps'
        elif ref['finding_id'] in bindings.claims and bindings.claims[ref['finding_id']]['claim_ref']==ref:state,reason='retained','exact_canonical_identity'
        return {'claim_ref':ref,'state':state,'reason_code':reason}
    def _responses(self,plan,bindings,programs,hypotheses):
        responses=[];pid=self.core.profile_id_for(plan['district']['chamber'],plan['district']['code'],2024)
        for program_id in programs:
            program=bindings.bind(self.core.prog_finding(program_id,pid));hyp=hypotheses.get(program_id)
            scope=self.core.service_scope.resolve(plan['district'],program_id,plan['service_area_id'])
            # Scope selected for this inquiry is bound to the action, separately from the general reference.
            template_id=self.templates['actions'].get(program_id)
            content=VERIFICATION_CONTENT.get(program_id,{'questions':[],'checklist':self.templates['checklist']})
            checklist=[{'item_id':item_id,'text':text,'owner_role':'','due_date':None,'completed':False,'staff_edited':False} for item_id,text in zip(('agency_route','partner_plan','next_check'),content['checklist'])] if template_id else []
            facts=list(dict.fromkeys([*program['unknowns'],*scope['access']['questions'],*content['questions']]))
            support=hyp['dependencies'] if hyp else []
            action_ref=None
            if template_id:
                action_binding={'binding_version':'ia-action/1','operation_version':OPERATION_VERSION,'snapshot_id':self.snapshot_id,
                    'action_id':template_id,'program_claim_ref':program['claim_ref'],'hypothesis_claim_ref':hyp['claim_ref'] if hyp else None,
                    'support_claim_refs':support,'service_scope':scope,'template':self.templates}
                if program_id in VERIFICATION_CONTENT:
                    action_binding.update(verification_questions=facts,template_checklist=checklist)
                # Kūpuna's unchanged prompts remain bound by its existing metadata,
                # scope and program dependencies; preserve that unchanged identity.
                action_ref={'action_id':template_id,'semantic_hash':digest(action_binding)}
            weakening=list(self.templates['limitations']) if program_id=='kupuna_care_hi' else [PROGRAM_RATIONALE[program_id]['connection']]
            responses.append({'program_id':program_id,'tier':'verification_action' if action_ref else ('hypothesis' if hyp else 'reference'),
                'program_claim_ref':program['claim_ref'],'hypothesis_claim_ref':hyp['claim_ref'] if hyp else None,'action_ref':action_ref,
                'support_claim_refs':support,'jurisdiction':scope['jurisdiction'],'access':program['access'],'eligibility_area':scope['eligibility_area'],
                'weakening_facts':weakening,'facts_to_verify':facts,'template_checklist':checklist})
        return responses
    def _cite_action(self,brief,response,bindings):
        if response is None:return
        dependency=response['hypothesis_claim_ref'] or response['program_claim_ref']
        sources=bindings.claims[dependency['finding_id']]['binding']['source_records']
        before=sum(print_units(f"{c['publisher']} {c['source_id']} {c['url']} "+"; ".join(c['locators']))+80 for c in brief['citations'])
        by_source={c['source_id']:c for c in brief['citations']};numbers=[]
        for record in sources:
            sid=record['source_id'];loc=record['locator'];src=self.core.packet.sources[sid]
            if loc.get('sheet') and loc.get('estimate_cell'):
                locator=f"{loc['sheet']}!{loc['estimate_cell']} (MOE {loc['moe_cell']})"
            elif loc.get('text_path'):
                locator=f"{loc['text_path']} lines {loc['line_start']}–{loc['line_end']}"
            elif loc.get('path'):
                locator=f"{loc['path']} pages {loc.get('pages')} ({loc.get('section')})"
            else:locator=json.dumps(loc,ensure_ascii=False,sort_keys=True)
            if sid not in by_source:
                row={'n':len(brief['citations'])+1,'source_id':sid,'publisher':src.get('publisher'),'url':src.get('url'),
                     'sha256':src.get('sha256'),'retrieved_at_utc':src.get('retrieved_at_utc'),'locators':[]}
                by_source[sid]=row;brief['citations'].append(row)
            row=by_source[sid]
            if locator not in row['locators']:row['locators'].append(locator)
            if row['n'] not in numbers:numbers.append(row['n'])
        brief['action_citations']=numbers
        after=sum(print_units(f"{c['publisher']} {c['source_id']} {c['url']} "+"; ".join(c['locators']))+80 for c in brief['citations'])
        brief['print_units']+=int(SMALL_TEXT_WEIGHT*(after-before))

    def handle(self,r):
        validate_request(r,self.core,self.snapshot_id)
        out=self._envelope(r)
        if r['mode']=='interpret':
            status,plan,reading=interpret(r['utterance'],r['plan']);out.update(status=status,normalized_plan=plan,interpretation=reading)
            return out
        plan=r['plan'];pid=self.core.profile_id_for(plan['district']['chamber'],plan['district']['code'],2024)
        bindings=ClaimBindings(self.core,self.snapshot_id,plan['map_session']);programs=[];hypotheses={}
        for step in plan['steps']:
            op,a=step['operation'],step['args'];record={'step_id':step['step_id'],'operation':op,'status':'ok','claim_refs':[],'reason_code':None,'message':None,'next_actions':[]}
            try:
                if op=='administrative_evidence':res=self.core.administrative_evidence(**a)
                else:res=getattr(self.core,op)(pid,**a)
                for f in res['findings']:
                    c=bindings.bind(f);record['claim_refs'].append(c['claim_ref'])
                    if op in ('program_evidence','outreach_lead'):
                        p=f['program']['program_id']
                        if p not in programs:programs.append(p)
                        if op=='outreach_lead':hypotheses[p]=c
                out['limitations'].extend(x for x in res['limitations'] if x not in out['limitations'])
            except Unsupported as e:
                record.update(status='unsupported',reason_code='comparison_geography_unavailable' if op=='compare' and a['comparison_geography'] not in self.core.profiles else 'operation_unsupported',message=e.reason,next_actions=e.next_actions)
            except Exception:
                # Do not leak exception bodies or private input. Independent steps still succeed.
                record.update(status='error',reason_code='step_failed',message='This step failed safely. Keep the plan and retry; independent results remain available.')
            out['steps'].append(record)
        failures=[s for s in out['steps'] if s['status']!='ok']
        if failures:out['status']='partial' if any(s['status']=='ok' for s in out['steps']) else ('error' if any(s['status']=='error' for s in failures) else 'unsupported')
        out['responses']=self._responses(plan,bindings,programs,hypotheses)
        out['claims']=[{k:v for k,v in c.items() if k!='binding'} for c in bindings.claims.values()]
        comparison_results=[ref for step in out['steps'] if step['operation']=='compare' and step['status']=='ok' for ref in step['claim_refs']]
        out['selection_review']=[self._review(ref,bindings,pid,comparison_results) for ref in r['selected_claim_refs']]
        action=r['selected_action_ref'];selected_response=next((x for x in out['responses'] if x['action_ref']==action),None) if action else None
        out['action_review']={'action_ref':action,'state':'retained' if selected_response else 'retired','reason_code':'exact_canonical_identity' if selected_response else 'action_no_longer_in_plan'} if action else None
        if r['mode']=='brief':
            bad=next((x for x in out['selection_review'] if x['state']!='retained'),None)
            if bad:
                code='foreign_context' if bad['state']=='foreign_context' else 'selection_conflict'
                raise InvestigationError(409,code,'The brief contains a primary finding from another district.' if code=='foreign_context' else 'The selected finding is not an exact current result.','selected_claim_refs','review_selections')
            if action and selected_response is None:raise InvestigationError(409,'action_conflict','The selected response needs review.','selected_action_ref','review_selections')
            if not plan['steps']:raise InvestigationError(409,'empty_plan','An empty plan has no printable facts.','plan.steps')
            # Any staff contribution, including completion or a blank custom item, needs explicit contextual review.
            edits=r['staff_edits'];has_staff=bool(any(v for k,v in edits.items() if k!='finding_notes') or any(edits.get('finding_notes',{}).values()) or r['checklist_edits'] or r['tracking'] is not None)
            expected={'branch_id':r['branch_id'],'revision':r['revision'],'plan_hash':plan_hash(plan)}
            if has_staff and r['edits_reviewed_for']!=expected:raise InvestigationError(409,'staff_review_required','Review all staff text and checklist progress for this exact context before including it.','edits_reviewed_for','review_staff_work')
            legacy=copy.deepcopy(edits)
            legacy['finding_notes']={ref['finding_id']:edits.get('finding_notes',{}).get(ref['semantic_hash'],'') for ref in r['selected_claim_refs'] if edits.get('finding_notes',{}).get(ref['semantic_hash'])}
            ids=[x['finding_id'] for x in r['selected_claim_refs']]
            try:brief=self.core.brief(pid,ids,legacy)['data']['brief']
            except Unsupported as e:
                overflow=bool(e.data and 'print_units' in e.data)
                err=InvestigationError(409,'brief_overflow' if overflow else 'brief_conflict',e.reason,'selected_claim_refs','shorten_brief')
                if overflow:
                    err.issues.append({'path':'brief','code':'brief_overflow','message':f"print_units={e.data['print_units']}; print_budget={e.data['print_budget']}"})
                raise err from None
            brief['snapshot_id']=self.snapshot_id
            brief['map_session']=plan['map_session'];brief['statistical_session']=2024
            brief['action']=selected_response
            brief['action_program']=copy.deepcopy(self.core.programs[selected_response['program_id']]) if selected_response else None
            self._cite_action(brief,selected_response,bindings)
            brief['checklist']=copy.deepcopy(selected_response['template_checklist']) if selected_response else []
            by_id={x['item_id']:x for x in brief['checklist']}
            for item in r['checklist_edits']:
                row=by_id.get(item['item_id'])
                if row is None:
                    template_text=dict(zip(('agency_route','partner_plan','next_check'),self.templates['checklist'])).get(item['item_id'],'')
                    row={'item_id':item['item_id'],'text':template_text,'owner_role':'','due_date':None,'completed':False};brief['checklist'].append(row)
                row.update(item);row['staff_edited']=True
            brief['tracking']=r['tracking']
            required_limits=[L_ACS,L_COMPARE,L_NO_GAP,L_NO_ELIG,L_HYPOTHESIS]
            brief['limitations']=list(dict.fromkeys(brief['limitations']+required_limits))
            if selected_response:
                extra=['Current availability, capacity, wait, funding and cost remain unverified.',*selected_response['weakening_facts'],*selected_response['jurisdiction']['limitations']]
                brief['limitations']=list(dict.fromkeys(brief['limitations']+extra))
            # All action and checklist content contributes to the established conservative print budget.
            # Count actual printed words, not hashes/internal dependency payloads.
            printed=render.action_checklist_text(brief)
            brief['print_units']+=int(print_units(printed)+sum(print_units(x) for x in brief['limitations'] if x not in self.core.brief(pid,ids,legacy)['data']['brief']['limitations']))
            if brief['print_units']>BRIEF_PRINT_BUDGET:
                err=InvestigationError(409,'brief_overflow',f"This brief is too long for one printed page (estimated {brief['print_units']} of {BRIEF_PRINT_BUDGET} print units). Remove a finding, shorten staff notes or shorten checklist text; all edits remain recoverable.",'staff_edits','shorten_brief')
                err.issues.append({'path':'brief','code':'brief_overflow','message':f"print_units={brief['print_units']}; print_budget={BRIEF_PRINT_BUDGET}"});raise err
            brief['html']=render.brief_doc_html(brief);out['brief']=brief
        size=len(json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))
        if size>524288:raise InvestigationError(409,'response_too_large','Reduce the plan or selected evidence detail.','plan.steps','reduce_plan')
        return out
