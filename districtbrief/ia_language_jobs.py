"""Lazy after-fork one-slot interpreter; request threads never wait for providers."""
from __future__ import annotations
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
import copy
import os
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from .case_contract import InvestigationError, obj, uuid4
from .claim_binding import digest
from .ia_language import (SCHEMA_VERSION, DISABLED_MESSAGE, PRIVACY_NOTICE, MESSAGES,
    LanguageError, RECOVERY_CATEGORIES, convert_decision, prepare_request, value_free_catalog)
from .ia_language_funding import FundingLedger
from .ia_language_profiles import Profile
from .ia_language_provider import OpenAIProvider, configuration_hash, provider_payload, emit_operator_diagnostic

# Closed attribution on every terminal job record (HTTP status and operator rows). Value-free: no utterance,
# arguments, rejection code or stage. It separates a model's own decision from a server typed recovery or
# refusal so hosted-pipeline results and server recoveries are counted separately.
# failure_class is a closed, non-sensitive discriminator of WHY a job did not end in the model's own decision.
FAILURE_CLASSES={
    'invalid_provider_arguments':'invalid_arguments','provider_refusal':'provider_refusal','provider_incomplete':'incomplete_output',
    'provider_output_invalid':'invalid_output','provider_timeout':'deadline',
    **{k:'transport' for k in ('provider_transport_error','invalid_provider_json','provider_http_error','provider_response_too_large','provider_route_forbidden')},
    **{k:'request_bounds' for k in ('provider_payload_too_large','input_token_limit')},'input_count_rejected':'count_rejected',
    **{k:'identity_or_usage' for k in ('provider_identity_mismatch','unknown_usage','provider_count_mismatch','unexpected_cache_usage','unexpected_cache_write','usage_exceeds_limits')},
    'credential_unavailable':'credential','cancelled':'cancelled'}
ATTRIBUTION_VALUES={
    'decision_origin':('model','server_recovery','server_refusal','model_refusal','service_failure','not_decided'),
    'model_status':('propose','clarify','unsupported','uncertain','invalid','not_decoded','not_reported'),
    'model_intent':('create_plan','replace_plan','inspect_source','none','invalid','not_decoded','not_reported'),
    'recovery_category':('',*sorted(set(RECOVERY_CATEGORIES.values()))),
    'failure_class':('none','local_refusal','invalid_arguments','provider_refusal','incomplete_output','invalid_output','deadline',
                     'transport','request_bounds','count_rejected','identity_or_usage','credential','accounting','cancelled',
                     'start_refused','internal')}

def _failure_class(code):
    if code in FAILURE_CLASSES:return FAILURE_CLASSES[code]
    if code.startswith(('accounting_','ledger_','approval_','budget_','count_ceiling','unresolved_','control_','invalid_bucket','qualification_')):return 'accounting'
    return 'internal'

def _attribution(origin,decision=None,category='',reported=True,failure='none'):
    def pick(key,field):
        if not reported:return 'not_reported'
        if decision is None:return 'not_decoded'
        value=decision.get(field) if type(decision) is dict else None
        return value if type(value) is str and value in ATTRIBUTION_VALUES[key][:-3] else 'invalid'
    return {'decision_origin':origin,'model_status':pick('model_status','status'),'model_intent':pick('model_intent','intent'),
            'recovery_category':category,'failure_class':failure}

# Public (non-operator) admission: one rolling window across the whole site, no per-session cap. Only admitted starts
# are recorded; a refused start records nothing and reaches no Count, generation or ledger. Per-session timestamps are
# kept only as existing bookkeeping for the session's latest context (status staleness), never as a limit.
SITE_STARTS_PER_WINDOW=3
SITE_WINDOW_SECONDS=300
SESSION_RETENTION_SECONDS=3600
RATE_LIMIT_MESSAGE=('The shared limit of 3 language questions every 5 minutes across the site is reached. '
                    'Try again in a few minutes; guided controls and typed requests still work.')

class LanguageService:
    def __init__(self,investigation,*,enabled=False,provider=None,ledger=None,profile=None):
        self.investigation=investigation;self.enabled=bool(enabled);self.provider=provider;self.ledger=ledger
        # The selected profile comes from protected operator configuration (or the injected ledger), never a request.
        if profile is None and ledger is not None:profile=getattr(ledger,'profile',None)
        if (self.enabled or profile is not None) and not isinstance(profile,Profile):raise LanguageError('profile_unavailable',503)
        self.profile=profile;self._identity=None
        self._lock=threading.RLock();self._executor=None;self._pid=os.getpid();self._active=None
        self._jobs=OrderedDict();self._early_cancels=OrderedDict();self._sessions=OrderedDict();self._site=deque();self._latest={}
    def bootstrap(self):
        return {'enabled':self.enabled,'schema_version':SCHEMA_VERSION,
            'message':MESSAGES['propose'] if self.enabled else DISABLED_MESSAGE,'privacy_notice':PRIVACY_NOTICE,
            'limits':{'utterance_characters':500,'deadline_seconds':25,'site_starts_per_window':SITE_STARTS_PER_WINDOW,
                      'site_window_seconds':SITE_WINDOW_SECONDS}}
    def identity(self):
        """Value-free configured identity for machine verification (health): no budget, secret or request data."""
        if self.profile is None:return None
        if self._identity is None:
            catalog_digest=digest(value_free_catalog(self.investigation.core))
            self._identity=dict(self.profile.public_identity(),catalog_digest=catalog_digest,
                active_config_hash=configuration_hash(catalog_digest,self.profile))
        return copy.deepcopy(self._identity)
    def _resources(self):
        if self.ledger is None:
            self.ledger=FundingLedger(self.profile,config_hash=self.identity()['active_config_hash'])
        if getattr(getattr(self.ledger,'profile',None),'profile_hash',None)!=self.profile.profile_hash:raise LanguageError('profile_ledger_mismatch',503)
        if self.provider is None:self.provider=OpenAIProvider()
        if self._executor is None:
            self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='ia-language')
    def _prune(self,now):
        # Cancel-before-start records have their own bound; misses must never evict admitted work.
        for rid,j in list(self._early_cancels.items()):
            if now-j['finished_at']>=600:self._early_cancels.pop(rid)
        while len(self._early_cancels)>32:self._early_cancels.popitem(last=False)
        for rid,j in list(self._jobs.items()):
            if j['finished_at'] is not None and now-j['finished_at']>=600:self._jobs.pop(rid)
        terminal=[rid for rid,j in self._jobs.items() if j['finished_at'] is not None]
        for rid in terminal[:-32]:self._jobs.pop(rid)
        for session,last in list(self._sessions.items()):
            while last and now-last[0]>=SESSION_RETENTION_SECONDS:last.popleft()
            if not last:self._sessions.pop(session,None);self._latest.pop(session,None)
        while self._site and now-self._site[0]>=SITE_WINDOW_SECONDS:self._site.popleft()
    def _base(self,j,status=None):
        p=j.get('prepared');out={'status':status or j['status'],'schema_version':SCHEMA_VERSION,
            'request_id':j['request_id'],'model_calls':j['model_calls'],
            'message':MESSAGES.get(status or j['status'],MESSAGES['error'])}
        if p:out.update(context_digest=p['context_digest'],tokens=copy.deepcopy(p['tokens']),context=copy.deepcopy(p['context']))
        # expired: the job was still pending at the 25 s job deadline (distinct from a provider-timeout error).
        if out['status'] in ('cancelled','expired'):
            out['attribution']=_attribution('not_decided',reported=False,failure='cancelled' if out['status']=='cancelled' else 'deadline')
        return out
    def _expire(self,j,now):
        if j['status']=='pending' and now>=j['deadline']:
            j['cancelled'].set();j.update(status='expired',finished_at=now,response=None)
    @staticmethod
    def _id(raw):
        try:
            obj(raw,('schema_version','request_id'))
            if raw['schema_version']!=SCHEMA_VERSION:raise LanguageError('version_mismatch',409)
            uuid4(raw['request_id'],'request_id');return raw['request_id']
        except InvestigationError as e:raise LanguageError(e.code,e.status) from None
    def _error(self,code,status,*,request_id=None):
        state='disabled' if status==503 and code=='disabled' else 'busy' if code in ('busy','accounting_busy') else 'error'
        out={'status':state,'schema_version':SCHEMA_VERSION,'code':code,'model_calls':0,
            'message':DISABLED_MESSAGE if state=='disabled' else 'Another language question is running. Try again after it finishes.' if state=='busy'
                else RATE_LIMIT_MESSAGE if code=='shared_demonstration_rate_limit' else 'Language interpretation is unavailable for this request. Use Typed request or guided controls.'}
        if request_id:out['request_id']=request_id
        out['attribution']=_attribution('not_decided',failure='start_refused')  # No job ran: nothing was decoded.
        return status,out
    def handle(self,action,raw,session):
        return self._handle(action,raw,session,operator=False)
    def operator_start(self,raw,*,diagnostic_sink=None):
        # This method is called only by the protected local CLI, never selected by JSON/HTTP.
        return self._handle('start',raw,'operator',operator=True,diagnostic_sink=diagnostic_sink)
    def _handle(self,action,raw,session,*,operator,diagnostic_sink=None):
        if not self.enabled:return self._error('disabled',503)
        # A preload never starts threads. Reject inherited executors after a fork.
        if self._pid!=os.getpid():
            self._pid=os.getpid();self._executor=None;self._active=None;self._jobs=OrderedDict();self._early_cancels=OrderedDict()
            self._lock=threading.RLock();self._sessions=OrderedDict();self._site=deque();self._latest={}
        try:
            if action=='start':return self._start(raw,session,operator,diagnostic_sink if operator else None)
            rid=self._id(raw);now=time.monotonic()
            with self._lock:
                self._prune(now);j=self._jobs.get(rid) or self._early_cancels.get(rid)
                if j is not None and j['session']!=session:return self._error('session_mismatch',403)
                if action=='cancel':
                    if j is None:
                        j={'request_id':rid,'session':session,'status':'cancelled','model_calls':0,'prepared':None,
                            'cancelled':threading.Event(),'finished_at':now,'response':None,'deadline':now}
                        j['cancelled'].set();self._early_cancels[rid]=j;self._prune(now)
                        return 200,self._base(j)
                    self._expire(j,now)
                    if j['status']=='pending':j['cancelled'].set();j.update(status='cancelled',finished_at=now,response=None)
                    else:
                        out=self._base(j);out['code']='already_terminal';return 200,out
                    return 200,self._base(j)
                if action!='status':return self._error('unknown_language_route',400)
                if j is None:return self._error('request_expired',409,request_id=rid)
                self._expire(j,now)
                if j['prepared'] and self._latest.get(session)!=j['prepared']['context_digest']:
                    j['cancelled'].set();j.update(status='expired',finished_at=now,response=None)
                out=self._base(j)
                if j['response']:out.update(copy.deepcopy(j['response']))
                return 200,out
        except LanguageError as exc:return self._error(exc.code,exc.status)
        except Exception:return self._error('language_failed',503)
    def _start(self,raw,session,operator,diagnostic_sink=None):
        begun=time.monotonic()
        # Validate a duplicate/foreign UUID before any Core or external work.
        try:
            if not isinstance(raw,dict):raise LanguageError()
            uuid4(raw.get('request_id'),'request_id')
        except InvestigationError as e:raise LanguageError(e.code,e.status) from None
        rid=raw['request_id']
        with self._lock:
            self._prune(begun);known=self._jobs.get(rid) or self._early_cancels.get(rid)
            if known:return self._error('session_mismatch' if known['session']!=session else 'duplicate_request',403 if known['session']!=session else 409)
            if self._active is not None:return self._error('busy',409)
            if not operator:
                if len(self._site)>=SITE_STARTS_PER_WINDOW:return self._error('shared_demonstration_rate_limit',429)
                if session not in self._sessions and len(self._sessions)>=1024:return self._error('session_limit_full',429)
            p=prepare_request(raw,self.investigation,session)
            provider_payload(p,self.profile)  # Bound and lint the complete payload before all provider access.
            if time.monotonic()-begun>=1:raise LanguageError('context_validation_too_slow',409)
            self._resources();job_fd=self.ledger.acquire_job()
            now=time.monotonic();j={'request_id':rid,'session':session,'status':'pending','model_calls':0,
                'prepared':p,'cancelled':threading.Event(),'finished_at':None,'response':None,
                'deadline':begun+25,'done':threading.Event(),'job_fd':job_fd,'bucket':'test' if operator else 'demo'}
            self._jobs[rid]=j;self._active=rid;self._latest[session]=p['context_digest']
            if not operator:self._sessions.setdefault(session,deque()).append(now);self._site.append(now)
            # DTO validation uses only copied catalog IDs; the worker receives no Core/Investigation.
            cat=p['provider_context']['catalog'];validation=SimpleNamespace(metrics={x['metric_id']:None for x in cat['metrics']},
                programs={x['program_id']:None for x in cat['programs']},
                administrative_rows={x['observation_id']:None for x in cat['administrative_observations']},
                profiles={g:None for g in cat['geographies']},
                admitted_recipe_versions=tuple(cat['recipes']))
            try:self._executor.submit(self._work,j,copy.deepcopy(p),validation,diagnostic_sink)
            except Exception:
                self.ledger.release_job(job_fd);self._active=None;self._jobs.pop(rid);raise LanguageError('executor_unavailable',503) from None
            return 202,self._base(j)
    def _work(self,j,prepared,validation,diagnostic_sink=None):
        result=None;phase='provider';local_diagnostic=None;decision=None
        def dispatched():
            with self._lock:j['model_calls']=1
        try:
            args=(prepared,self.ledger,j['bucket'],j['cancelled'],j['deadline'],dispatched)
            if diagnostic_sink is None:decision,_diagnostics=self.provider.interpret(*args)
            else:decision,_diagnostics=self.provider.interpret(*args,diagnostic_sink=diagnostic_sink)
            phase='validation'
            recovered=None
            if not j['cancelled'].is_set():
                result=convert_decision(prepared,decision,validation);recovered=result.pop('recovered_from',None)
                category=result.pop('recovery_category','')
                result['attribution']=_attribution('server_recovery' if recovered else 'model',decision,category)
            local_diagnostic={'event':'local_result','phase':phase,'status':result['status'] if result else 'cancelled',
                'stage':None,'rejection_code':None,'recovered_from':recovered,'exception_type':None,'frames':[]}
        except LanguageError as exc:
            if diagnostic_sink is not None:
                local_diagnostic={'event':'local_result','phase':phase,'status':'rejected','stage':getattr(exc,'stage',None) if phase=='validation' else 'provider',
                    'rejection_code':exc.code,'recovered_from':None,
                    'exception_type':type(exc).__name__,'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-8:]]}
            # No provider body, utterance, exception or accounting detail reaches staff/logs.
            # Every local refusal of decoded model content is an interpretation failure (uncertain);
            # service failures (503) and provider-phase failures other than invalid arguments stay error.
            # Only decoded model content is an interpretation failure: validation refusals (non-503) and
            # unparseable function arguments. Transport/body/HTTP/identity/usage failures are service errors.
            uncertain=(phase=='validation' and exc.status!=503) or exc.code=='invalid_provider_arguments'
            result={'status':'uncertain' if uncertain else 'error','reason_code':'uncertain_interpretation' if uncertain else '',
                    'message':MESSAGES['uncertain'] if uncertain else MESSAGES['error'],
                    'attribution':_attribution('server_refusal' if uncertain else 'model_refusal' if exc.code=='provider_refusal' else 'service_failure',
                        decision if phase=='validation' else None,
                        failure='local_refusal' if uncertain and phase=='validation' else _failure_class(exc.code))}
        except Exception as exc:
            if diagnostic_sink is not None:
                local_diagnostic={'event':'local_result','phase':phase,'status':'rejected','stage':None,'rejection_code':None,'recovered_from':None,
                    'exception_type':type(exc).__name__,'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-8:]]}
            result={'status':'error','reason_code':'','message':MESSAGES['error'],
                    'attribution':_attribution('service_failure',decision if phase=='validation' else None,failure='internal')}
        finally:
            if diagnostic_sink is not None and local_diagnostic is not None:emit_operator_diagnostic(diagnostic_sink,local_diagnostic)
            with self._lock:
                now=time.monotonic();self._expire(j,now)
                if j['status']=='pending':
                    if j['cancelled'].is_set():j.update(status='cancelled',response=None)
                    elif result:j.update(status=result['status'],response=result)
                    else:j.update(status='error',response=None)
                    j['finished_at']=now
                try:self.ledger.release_job(j['job_fd'])
                finally:
                    if self._active==j['request_id']:self._active=None
                    self._prune(now)
                    j['done'].set()
    def operator_wait(self,request_id):
        with self._lock:
            j=self._jobs.get(request_id)
            if j is None:raise LanguageError('request_expired',409)
            done=j['done'];left=max(0,j['deadline']-time.monotonic())
        done.wait(left)
        return self.handle('status',{'schema_version':SCHEMA_VERSION,'request_id':request_id},'operator')
    def close(self):
        with self._lock:
            for j in self._jobs.values():
                if j['status']=='pending':j['cancelled'].set()
        if self._executor:self._executor.shutdown(wait=False,cancel_futures=True)
