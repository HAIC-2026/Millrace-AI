#!/usr/bin/env python3
"""Protected image-local IA harness. No endpoint or test-budget HTTP capability."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.claim_binding import digest
from districtbrief.ia_language import SCHEMA_VERSION, LanguageError, dumps, prepare_request, strict_json, value_free_catalog
from districtbrief.ia_language_accounting import POLICY_HASH, BudgetLedger
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider, configuration_hash

EVAL_ROOT=Path('/run/ia1-eval')
# Operator/evaluator recovery cutoff (UTC epoch seconds), supplied by the evaluator environment. It bounds
# only `smoke`/`evaluate`; public HTTP serving keeps its own budget/ceiling/rate controls and has no cutoff.
# Absent, malformed or passed means refuse: there is no built-in date and no unlimited default.
RECOVERY_CUTOFF_ENV='HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH'
_now=time.time

def recovery_cutoff():
    raw=os.environ.get(RECOVERY_CUTOFF_ENV)
    if type(raw) is not str or not re.fullmatch(r'[1-9][0-9]{8,11}',raw):return None
    return int(raw)

def before_cutoff(cutoff):
    return cutoff is not None and _now()<cutoff

NOT_STARTED={'status':'not_started','code':'recovery_cutoff_passed','model_calls':0,
    'attribution':{'decision_origin':'not_decided','model_status':'not_reported','model_intent':'not_reported','recovery_category':'','failure_class':'start_refused'}}

def protected_path(value,*,output=False):
    p=Path(value)
    if not p.is_absolute() or p.is_symlink():raise LanguageError('evaluation_path_forbidden',403)
    root=EVAL_ROOT.resolve();resolved=p.resolve(strict=not output)
    if root not in resolved.parents:raise LanguageError('evaluation_path_forbidden',403)
    parent=p.parent if output else p
    s=parent.stat()
    if stat.S_IMODE(s.st_mode)&0o007 or (output and not stat.S_ISDIR(s.st_mode)) or (not output and not stat.S_ISREG(s.st_mode)):raise LanguageError('evaluation_permissions',403)
    return p

def questions(path,maximum,exact=None):
    p=protected_path(path);rows=[]
    with p.open('rb') as f:
        for line in f:
            if len(line)>70000:raise LanguageError('evaluation_row_too_large')
            if not line.strip():raise LanguageError('evaluation_blank_row')
            try:r=strict_json(line)
            except (ValueError,UnicodeError):raise LanguageError('evaluation_json') from None
            if type(r) is not dict or set(r)!={'case_id','request'} or type(r['case_id']) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',r['case_id']) or type(r['request']) is not dict:raise LanguageError('evaluation_shape')
            rows.append(r)
            if len(rows)>maximum:raise LanguageError('evaluation_count')
    if not rows or (exact is not None and len(rows)!=exact) or len({r['case_id'] for r in rows})!=len(rows):raise LanguageError('evaluation_count')
    return rows,hashlib.sha256(p.read_bytes()).hexdigest()

def probe_request(i):
    return {'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':'Profile House28.',
        'context':{**{k:str(uuid.uuid4())for k in ('case_id','branch_id')},'revision':0,'snapshot_id':i.snapshot_id,
        'operation_version':'ia-core/1','recipe_version':'custom/1','confirmed_plan':None,'draft_plan':None,'focused_step_id':None,'selected_claim_refs':[]}}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--approval-reference',required=True)
    template=sub.add_parser('approval-template');template.add_argument('--approval-reference',required=True)
    sub.add_parser('summary');sub.add_parser('probe');sub.add_parser('identity')
    for command in ('smoke','evaluate'):
        p=sub.add_parser(command);p.add_argument('--questions',required=True);p.add_argument('--output',required=True)
        if command=='smoke':p.add_argument('--diagnostics',help='Private synthetic-smoke diagnostics file under the protected results directory; disabled by default.')
    args=parser.parse_args(argv)
    try:
        i=Investigation(load_core());catalog_digest=digest(value_free_catalog(i.core));config_hash=configuration_hash(catalog_digest)
        ledger=BudgetLedger(config_hash,catalog_digest=catalog_digest)
        if args.command=='identity':result={'active_config_hash':config_hash,'catalog_digest':catalog_digest,'policy_hash':POLICY_HASH,'control_access':False}
        elif args.command=='approval-template':result=ledger.approval_template(args.approval_reference)
        elif args.command=='init':result=ledger.initialize(args.approval_reference)
        elif args.command=='summary':result=ledger.summary()
        elif args.command=='probe':
            fd=ledger.acquire_job()
            try:result=OpenAIProvider().probe(ledger,prepare_request(probe_request(i),i,'operator'))
            finally:ledger.release_job(fd)
        else:
            # Recovery cutoff precedes every ledger read, input read and reservation.
            cutoff=recovery_cutoff()
            if cutoff is None:raise LanguageError('recovery_cutoff_unset',503)
            if not before_cutoff(cutoff):raise LanguageError('recovery_cutoff_passed',503)
            # Evaluate needs durable count capacity for every intended case before the input is touched.
            if args.command=='evaluate' and ledger.summary()['count_capacity_remaining']<120:raise LanguageError('count_capacity_insufficient',503)
            rows,questions_hash=questions(args.questions,8 if args.command=='smoke' else 120,exact=120 if args.command=='evaluate' else None)
            outpath=protected_path(args.output,output=True)
            diagnostic_file=None;diagnostic_failures=[0];diagnostic_path=None
            if getattr(args,'diagnostics',None):
                diagnostic_path=protected_path(args.diagnostics,output=True)
                if (EVAL_ROOT/'results').resolve() not in diagnostic_path.resolve().parents or diagnostic_path.resolve()==outpath.resolve():
                    raise LanguageError('evaluation_path_forbidden',403)
                dfd=os.open(diagnostic_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                diagnostic_file=os.fdopen(dfd,'wb')
            fd=os.open(outpath,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            service=LanguageService(i,enabled=True,ledger=ledger)
            completed=0;terminals={};origins={};failures={};halted=False
            try:
                with os.fdopen(fd,'wb') as f:
                    for row in rows:
                        begin=time.monotonic();before=ledger.summary()
                        if not before_cutoff(cutoff):
                            # Not started: recorded before any reservation, with no count or generation request.
                            code,response=503,json.loads(json.dumps(NOT_STARTED))
                        elif halted:
                            code,response=503,{'status':'error','code':'blocked_unresolved_liability','model_calls':0,
                                'attribution':{'decision_origin':'not_decided','model_status':'not_decoded','model_intent':'not_decoded','recovery_category':'','failure_class':'accounting'}}
                        else:
                            diagnostic_sink=None
                            if diagnostic_file is not None:
                                def diagnostic_sink(event,case_id=row['case_id']):
                                    try:
                                        encoded=dumps(dict(event,case_id=case_id))
                                        if len(encoded)>65536:raise ValueError('diagnostic_limit')
                                        diagnostic_file.write(encoded+b'\n');diagnostic_file.flush();os.fsync(diagnostic_file.fileno())
                                    except Exception:diagnostic_failures[0]+=1
                            code,response=service.operator_start(row['request'],diagnostic_sink=diagnostic_sink)
                            if code==202:code,response=service.operator_wait(row['request']['request_id'])
                        after=ledger.summary();halted=after['unresolved']
                        record={'case_id':row['case_id'],'status':response['status'],'http_status':code,'response':response,
                            'elapsed_seconds':time.monotonic()-begin,'model_calls':response['model_calls'],'bucket':'test',
                            'ledger_before':before,'ledger_after':after,'questions_sha256':questions_hash,'config_hash':config_hash}
                        f.write(dumps(record)+b'\n');f.flush();os.fsync(f.fileno());completed+=1
                        terminals[response['status']]=terminals.get(response['status'],0)+1
                        a=response.get('attribution') or {}
                        key='/'.join((response['status'],a.get('decision_origin','not_decided'),a.get('recovery_category','') or '-'))
                        origins[key]=origins.get(key,0)+1
                        fkey='/'.join((response['status'],a.get('failure_class','internal')));failures[fkey]=failures.get(fkey,0)+1
            finally:
                service.close()
                if diagnostic_file is not None:
                    try:diagnostic_file.close()
                    except Exception:diagnostic_failures[0]+=1
            # Raw counts by terminal/decision origin/recovery category: hosted-pipeline outcomes never hide server recoveries.
            result={'status':'completed','records':completed,'terminal_counts':terminals,'terminal_origin_counts':origins,'terminal_failure_counts':failures,'output':str(outpath),'questions_sha256':questions_hash,'ledger':ledger.summary(),
                'quality':'not_graded_by_operator; independent evaluator owns gold and grades',
                'diagnostics':{'enabled':diagnostic_path is not None,'path':str(diagnostic_path)if diagnostic_path else None,'write_failures':diagnostic_failures[0]}}
        print(dumps(result).decode());return 0
    except LanguageError as exc:
        print(json.dumps({'status':'error','code':exc.code,'model_calls':None,'model_calls_scope':'unknown_total_consult_durable_ledger'}));return 2
    except Exception:
        print(json.dumps({'status':'error','code':'operator_failed','model_calls':None,'model_calls_scope':'unknown_total_consult_durable_ledger'}));return 2

if __name__=='__main__':raise SystemExit(main())
