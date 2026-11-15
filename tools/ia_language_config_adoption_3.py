#!/usr/bin/env python3
"""Root-only offline THIRD adoption: exactly the committed second record's active configuration
(82a) to one new active configuration on the same ledger and financial origin.

SOURCE ONLY: not part of the runtime image entrypoint. Requires the exact committed approval v3
(count ceiling 7, exhausted at count 7, sequence 35, no holds), the exact pinned 7-entry budget
bytes and the immutable first and second record bytes. Publishes the protected
config-adoption-3.json record (exclusive, fsynced), then commits approval v4 atomically with the
fixed count ceiling 7, so this transition gives NO new count headroom. Never writes, copies,
resets, initializes, refunds, restamps or relabels budget.json or records 1-2; makes no network,
secret or provider access. It is not a general ceiling-raise tool and accepts no other transition.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from districtbrief.ia_language import LanguageError, dumps, strict_json
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_RECORD_SHA256, ADOPTION2_ACTIVE_CONFIG_HASH,
    ADOPTION2_CHECKPOINT, ADOPTION2_MAX_COUNT_REQUESTS, ADOPTION2_RECORD_SHA256, ADOPTION3_BUDGET_SHA256, ADOPTION3_CHECKPOINT,
    ADOPTION3_MAX_COUNT_REQUESTS, ADOPTION_CHECKPOINT, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY, POLICY_HASH,
    BudgetLedger, _ref, _sha, adoption3_record, approval_v3, approval_v4, validate_adoption2_record, validate_adoption_record)
from tools.ia_language_config_adoption import (ROOT_UID, SERVICE_GID, AdoptionError, _ancestors, _halt, _lock,
    _publish_atomic, _publish_exclusive, _read_regular)

# Exact committed approval v3 bytes (record-2 helper output); reviewed pin, never recomputed authority.
APPROVAL3_SHA256='sha256:9fdf89a68066212d2057eae6c49e6ca1aa3735100bd523c41be7742b04d19b3a'

def _halt_checked(ledger):
    """Best-effort shared marker, then independent confirmation (same as cap v6/v8): fsync the marker and
    its directory. Raises OSError when the marker cannot be confirmed. No recovery, reset or rollback."""
    _halt(ledger)
    for p in (ledger.halt_path,ledger.directory):
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

def _sha_of(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def _fingerprint(path):
    s=os.lstat(path);return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns

def _records(ledger,catalog_digest):
    """Exact immutable record 1 and record 2 bytes; returns (record1, record2, approval reference)."""
    first=_read_regular(ledger,ledger.adoption_path,0o440,ROOT_UID,SERVICE_GID,16384)
    second=_read_regular(ledger,ledger.adoption2_path,0o440,ROOT_UID,SERVICE_GID,16384)
    if _sha_of(first)!=ADOPTION1_RECORD_SHA256:raise AdoptionError('first_record_mismatch')
    if _sha_of(second)!=ADOPTION2_RECORD_SHA256:raise AdoptionError('second_record_mismatch')
    reference=strict_json(first)['original_approval_reference']
    try:validate_adoption_record(first,{'approval_reference':reference,'adoption_record_sha256':ADOPTION1_RECORD_SHA256},
            ADOPTION1_ACTIVE_CONFIG_HASH,catalog_digest)
    except ValueError:raise AdoptionError('first_record_mismatch') from None
    try:validate_adoption2_record(second,{'approval_reference':reference,'adoption2_record_sha256':ADOPTION2_RECORD_SHA256},
            ADOPTION2_ACTIVE_CONFIG_HASH,catalog_digest)
    except ValueError:raise AdoptionError('second_record_mismatch') from None
    return first,second,reference

def _classify_approval(raw,reference,expected_v4):
    """'legacy' only for the exact committed second-transition v3 bytes; 'committed' only for the exact new v4."""
    if expected_v4 is not None and raw==expected_v4:return 'committed'
    if (raw==dumps(approval_v3(reference,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION2_RECORD_SHA256,ADOPTION2_MAX_COUNT_REQUESTS))
            and _sha_of(raw)==APPROVAL3_SHA256):return 'legacy'
    a=strict_json(raw)
    if type(a) is dict and a.get('schema_version')=='ia-language-approval/4':
        if expected_v4 is None:return 'v4_unverified'
        raise AdoptionError('adoption_conflict')
    raise AdoptionError('approval_not_reviewed_second_transition')

def _verify_checkpoint(raw,reference):
    """Exact seq35/count7/63617000/no-hold 7-entry history with positional origin/c0d/82a stamps."""
    state=strict_json(raw)
    if (type(state) is not dict or state['schema_version']!='ia-language-ledger/1' or state['ledger_id']!=ADOPTION_LEDGER_ID
            or state['config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH or state['policy_hash']!=POLICY_HASH
            or state['limits_nano_usd']!=POLICY['limits_nano_usd'] or state['approval_reference']!=reference
            or type(state['entries']) is not list):raise AdoptionError('ledger_identity_mismatch')
    entries=state['entries'];n1=ADOPTION_CHECKPOINT['count_requests'];n2=ADOPTION2_CHECKPOINT['count_requests']
    def ok(e):
        return (type(e) is dict and e.get('state')=='settled' and e.get('count_requests')==1 and type(e.get('sequence')) is int
            and type(e.get('settled_estimate_nano_usd')) is int and 0<=e['settled_estimate_nano_usd'])
    if not all(map(ok,entries)):raise AdoptionError('ledger_checkpoint_mismatch')
    observed={'sequence':state['sequence'],'count_requests':sum(e.get('count_requests',0) for e in entries),
        'settled_nano_usd':sum(e['settled_estimate_nano_usd'] for e in entries if e['state']=='settled'),
        'held_nano_usd':sum(e['reserved_nano_usd'] for e in entries if e['state'] in ('reserved','dispatched','unknown')),
        'unresolved':any(e['state'] in ('reserved','dispatched','unknown') for e in entries)}
    origin,first,second=entries[:n1],entries[n1:n2],entries[n2:]
    if (observed!=ADOPTION3_CHECKPOINT or len(entries)!=ADOPTION3_CHECKPOINT['count_requests']
            or any('config_hash' in e or e['sequence']>ADOPTION_CHECKPOINT['sequence'] for e in origin)
            or sum(e['settled_estimate_nano_usd'] for e in origin)!=ADOPTION_CHECKPOINT['settled_nano_usd']
            or any(e.get('config_hash')!=ADOPTION1_ACTIVE_CONFIG_HASH or not ADOPTION_CHECKPOINT['sequence']<e['sequence']<=ADOPTION2_CHECKPOINT['sequence'] for e in first)
            or sum(e['settled_estimate_nano_usd'] for e in origin+first)!=ADOPTION2_CHECKPOINT['settled_nano_usd']
            or any(e.get('config_hash')!=ADOPTION2_ACTIVE_CONFIG_HASH or not ADOPTION2_CHECKPOINT['sequence']<e['sequence']<=ADOPTION3_CHECKPOINT['sequence'] for e in second)):
        raise AdoptionError('ledger_checkpoint_mismatch')

def adopt3(control_dir,*,active_config_hash,catalog_digest,transition_reference,source_component_sha256,image_digest,
        review_receipt_sha256,expected_budget_sha256,max_count_requests,protected=True):
    control=Path(control_dir)
    if not all(_sha(v) for v in (active_config_hash,catalog_digest,source_component_sha256,image_digest,review_receipt_sha256,expected_budget_sha256)):raise AdoptionError('invalid_pin')
    if active_config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH):raise AdoptionError('invalid_pin')
    if expected_budget_sha256!=ADOPTION3_BUDGET_SHA256:raise AdoptionError('budget_pin_mismatch')
    if not _ref(transition_reference):raise AdoptionError('invalid_transition_reference')
    # Fixed ceiling: the exhausted 7 stays 7. No other value; headroom needs the separate cap GO.
    if type(max_count_requests) is not int or max_count_requests!=ADOPTION3_MAX_COUNT_REQUESTS:raise AdoptionError('invalid_max_count_requests')
    if protected:
        if os.geteuid()!=ROOT_UID:raise AdoptionError('root_required')
        if not control.is_absolute():raise AdoptionError('control_realpath_mismatch')
        _ancestors(control)
    ledger=BudgetLedger(active_config_hash,control,protected=protected,catalog_digest=catalog_digest)
    ledger._check(control,0o750,ROOT_UID,SERVICE_GID,True);ledger._check(ledger.directory,0o700,SERVICE_GID,SERVICE_GID,True)
    approval_path=control/'approval.json'
    # Validate the OLD authority and immutable records 1-2 before taking any lock.
    first,second,reference=_records(ledger,catalog_digest)
    if transition_reference in (strict_json(first)['transition_reference'],strict_json(second)['transition_reference']):raise AdoptionError('invalid_transition_reference')
    _classify_approval(_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384),reference,None)
    job=_lock(ledger.directory/'job.lock')
    try:
        budget=_lock(ledger.directory/'budget.lock')
        try:return _adopt3_locked(ledger,approval_path,first,second,reference,active_config_hash,catalog_digest,transition_reference,
            source_component_sha256,image_digest,review_receipt_sha256,protected)
        finally:os.close(budget)
    finally:os.close(job)

def _adopt3_locked(ledger,approval_path,first,second,reference,active,catalog,transition,source_pin,image_pin,review_pin,protected):
    ceiling=ADOPTION3_MAX_COUNT_REQUESTS
    if os.path.lexists(ledger.halt_path):raise AdoptionError('accounting_halted')
    pre=_read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)
    pre_sha=_sha_of(pre)
    if pre_sha!=ADOPTION3_BUDGET_SHA256:raise AdoptionError('budget_pin_mismatch')
    history={ledger.path:pre,ledger.adoption_path:first,ledger.adoption2_path:second}
    fingerprints={p:_fingerprint(p) for p in history}
    if _records(ledger,catalog)[:2]!=(first,second):raise AdoptionError('record_changed')
    current=_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384)
    _verify_checkpoint(pre,reference)
    record=dumps(adoption3_record(active_config_hash=active,catalog_digest=catalog,original_approval_reference=reference,
        transition_reference=transition,source_component_sha256=source_pin,image_digest=image_pin,
        review_receipt_sha256=review_pin,budget_sha256=pre_sha))
    record_sha=_sha_of(record)
    new_approval=dumps(approval_v4(reference,active,record_sha,ceiling))
    state=_classify_approval(current,reference,new_approval)
    resumed=os.path.lexists(ledger.adoption3_path)
    if resumed and _read_regular(ledger,ledger.adoption3_path,0o440,ROOT_UID,SERVICE_GID,16384)!=record:raise AdoptionError('adoption_conflict')
    if state=='committed' and not resumed:raise AdoptionError('adoption_conflict')
    try:
        if not resumed:_publish_exclusive(ledger.adoption3_path,record,protected)
        if state=='legacy':_publish_atomic(approval_path,new_approval,protected)  # approval replacement is the commit
        # Post-verify bytes, inode and mtime of all history, then the exact runtime parser (both locks held).
        for p,raw in history.items():
            if p.read_bytes()!=raw or _fingerprint(p)!=fingerprints[p]:raise AdoptionError('history_changed')
        if ledger.adoption3_path.read_bytes()!=record or approval_path.read_bytes()!=new_approval:raise AdoptionError('commit_verification_failed')
        summary=ledger._summary(ledger._read())
        lineage=[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,active]
        if (summary['approval_schema'],summary['ledger_id'],summary['sequence'],summary['count_requests'],summary['unresolved'],
                summary['financial_origin_config_hash'],summary['previous_active_config_hash'],summary['active_config_hash'],
                summary['max_count_requests'],summary['count_capacity_remaining'],summary['adoption_record_sha256'],
                summary['adoption2_record_sha256'],summary['adoption3_record_sha256'],summary['config_lineage'],
                [x['sha256'] for x in summary['adoption_lineage']])!=(
                'ia-language-approval/4',ADOPTION_LEDGER_ID,ADOPTION3_CHECKPOINT['sequence'],ADOPTION3_CHECKPOINT['count_requests'],False,
                ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,active,ceiling,0,ADOPTION1_RECORD_SHA256,
                ADOPTION2_RECORD_SHA256,record_sha,lineage,[ADOPTION1_RECORD_SHA256,ADOPTION2_RECORD_SHA256,record_sha]):
            raise AdoptionError('commit_verification_failed')
    except (OSError,LanguageError,AdoptionError,ValueError,KeyError,TypeError) as exc:
        # Partial state (record 3 and/or approval 4) is left exactly as found for root inspection.
        try:_halt_checked(ledger)
        except OSError:raise AdoptionError('adoption_commit_uncertain_halt_unconfirmed') from exc
        raise AdoptionError('adoption_commit_uncertain_halted') from exc
    return {'status':'adopted','resumed':resumed or state=='committed','ledger_id':ADOPTION_LEDGER_ID,
        'financial_origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'previous_active_config_hash':ADOPTION2_ACTIVE_CONFIG_HASH,
        'active_config_hash':active,'config_lineage':summary['config_lineage'],'catalog_digest':catalog,'policy_hash':POLICY_HASH,
        'adoption_record_sha256':ADOPTION1_RECORD_SHA256,'adoption2_record_sha256':ADOPTION2_RECORD_SHA256,
        'adoption3_record_sha256':record_sha,'adoption_lineage':summary['adoption_lineage'],'approval_sha256':_sha_of(new_approval),
        'previous_approval_sha256':APPROVAL3_SHA256,'budget_sha256_unchanged':pre_sha,'history_bytes_inode_mtime_unchanged':True,
        'sequence':summary['sequence'],'count_requests':summary['count_requests'],
        'max_count_requests':ceiling,'count_capacity_remaining':summary['count_capacity_remaining'],
        'buckets':summary['buckets'],'provider_calls':0,'ledger_writes':0}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',required=True)
    for name in ('active-config-hash','catalog-digest','transition-reference','source-component-sha256','image-digest',
            'review-receipt-sha256','expected-budget-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-count-requests',required=True,type=int)
    args=parser.parse_args(argv)
    try:
        result=adopt3(args.control_dir,active_config_hash=args.active_config_hash,catalog_digest=args.catalog_digest,
            transition_reference=args.transition_reference,source_component_sha256=args.source_component_sha256,
            image_digest=args.image_digest,review_receipt_sha256=args.review_receipt_sha256,
            expected_budget_sha256=args.expected_budget_sha256,max_count_requests=args.max_count_requests)
        print(dumps(result).decode());return 0
    except AdoptionError as exc:
        if '_commit_uncertain_' in exc.code:
            # Writes may have happened: stop and inspect the control state; never retry from this output.
            print(json.dumps({'status':'commit_uncertain','code':exc.code,'provider_calls':0,'inspect_control_state':True}));return 3
        print(json.dumps({'status':'refused','code':exc.code,'provider_calls':0}));return 2
    except (OSError,LanguageError,ValueError,KeyError,TypeError,AttributeError,UnicodeError,RecursionError):
        print(json.dumps({'status':'refused','code':'adoption_precondition_failed','provider_calls':0}));return 2

if __name__=='__main__':raise SystemExit(main())
