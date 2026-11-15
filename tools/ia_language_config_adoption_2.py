#!/usr/bin/env python3
"""Root-only offline SECOND adoption: exactly the committed first record's active configuration
to one new active configuration on the same ledger and financial origin.

Requires the exact committed approval v2 (count ceiling 6, exhausted at count 6) and the immutable
first record bytes. Publishes the protected config-adoption-2.json record (fsynced), then commits
approval v3 atomically with a fixed count ceiling of 7. Never writes, copies, resets, initializes or
relabels budget.json or the first record; makes no network, secret or provider access. It is not a
general ceiling-raise tool and accepts no other transition or ceiling.
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
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_MAX_COUNT_REQUESTS,
    ADOPTION1_RECORD_SHA256, ADOPTION2_CHECKPOINT, ADOPTION2_MAX_COUNT_REQUESTS, ADOPTION_CHECKPOINT,
    ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY, POLICY_HASH, BudgetLedger, _ref, _sha,
    adoption2_record, approval_v2, approval_v3, validate_adoption_record)
from tools.ia_language_config_adoption import (ROOT_UID, SERVICE_GID, AdoptionError, _ancestors, _halt, _lock,
    _publish_atomic, _publish_exclusive, _read_regular)

def _sha_of(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()

def _first_record(ledger,catalog_digest):
    """Exact immutable first record bytes; returns (raw, approval reference)."""
    raw=_read_regular(ledger,ledger.adoption_path,0o440,ROOT_UID,SERVICE_GID,16384)
    if _sha_of(raw)!=ADOPTION1_RECORD_SHA256:raise AdoptionError('first_record_mismatch')
    reference=strict_json(raw)['original_approval_reference']
    try:validate_adoption_record(raw,{'approval_reference':reference,'adoption_record_sha256':ADOPTION1_RECORD_SHA256},
            ADOPTION1_ACTIVE_CONFIG_HASH,catalog_digest)
    except ValueError:raise AdoptionError('first_record_mismatch') from None
    return raw,reference

def _classify_approval(raw,reference,expected_v3):
    """'legacy' only for the exact committed first-transition v2 bytes; 'committed' only for the exact new v3."""
    if expected_v3 is not None and raw==expected_v3:return 'committed'
    if raw==dumps(approval_v2(reference,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,ADOPTION1_MAX_COUNT_REQUESTS)):return 'legacy'
    a=strict_json(raw)
    if type(a) is dict and a.get('schema_version')=='ia-language-approval/3':
        if expected_v3 is None:return 'v3_unverified'
        raise AdoptionError('adoption_conflict')
    raise AdoptionError('approval_not_reviewed_first_transition')

def _verify_checkpoint(raw,reference):
    state=strict_json(raw)
    if (type(state) is not dict or state['schema_version']!='ia-language-ledger/1' or state['ledger_id']!=ADOPTION_LEDGER_ID
            or state['config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH or state['policy_hash']!=POLICY_HASH
            or state['limits_nano_usd']!=POLICY['limits_nano_usd'] or state['approval_reference']!=reference
            or type(state['entries']) is not list):raise AdoptionError('ledger_identity_mismatch')
    entries=state['entries'];origin=entries[:ADOPTION_CHECKPOINT['count_requests']];first=entries[ADOPTION_CHECKPOINT['count_requests']:]
    def ok(e):
        return (type(e) is dict and e.get('state')=='settled' and e.get('count_requests')==1 and type(e.get('sequence')) is int
            and type(e.get('settled_estimate_nano_usd')) is int and 0<=e['settled_estimate_nano_usd'])
    observed={'sequence':state['sequence'],'count_requests':sum(e.get('count_requests',0) for e in entries),
        'settled_nano_usd':sum(e['settled_estimate_nano_usd'] for e in entries if e['state']=='settled'),
        'held_nano_usd':sum(e['reserved_nano_usd'] for e in entries if e['state'] in ('reserved','dispatched','unknown')),
        'unresolved':any(e['state'] in ('reserved','dispatched','unknown') for e in entries)}
    if (observed!=ADOPTION2_CHECKPOINT or len(entries)!=ADOPTION2_CHECKPOINT['count_requests'] or not all(map(ok,entries))
            # Unstamped origin history up to checkpoint 1, then previous-active entries only.
            or any('config_hash' in e or e['sequence']>ADOPTION_CHECKPOINT['sequence'] for e in origin)
            or sum(e['settled_estimate_nano_usd'] for e in origin)!=ADOPTION_CHECKPOINT['settled_nano_usd']
            or any(e.get('config_hash')!=ADOPTION1_ACTIVE_CONFIG_HASH or not ADOPTION_CHECKPOINT['sequence']<e['sequence']<=ADOPTION2_CHECKPOINT['sequence'] for e in first)):
        raise AdoptionError('ledger_checkpoint_mismatch')

def adopt2(control_dir,*,active_config_hash,catalog_digest,transition_reference,source_component_sha256,image_digest,
        review_receipt_sha256,expected_budget_sha256,max_count_requests,protected=True):
    control=Path(control_dir)
    if not all(_sha(v) for v in (active_config_hash,catalog_digest,source_component_sha256,image_digest,review_receipt_sha256,expected_budget_sha256)):raise AdoptionError('invalid_pin')
    if active_config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH):raise AdoptionError('invalid_pin')
    if not _ref(transition_reference):raise AdoptionError('invalid_transition_reference')
    # Fixed next ceiling: exactly one more count after the exhausted 6. No other value.
    if type(max_count_requests) is not int or max_count_requests!=ADOPTION2_MAX_COUNT_REQUESTS:raise AdoptionError('invalid_max_count_requests')
    if protected:
        if os.geteuid()!=ROOT_UID:raise AdoptionError('root_required')
        if not control.is_absolute():raise AdoptionError('control_realpath_mismatch')
        _ancestors(control)
    ledger=BudgetLedger(active_config_hash,control,protected=protected,catalog_digest=catalog_digest)
    ledger._check(control,0o750,ROOT_UID,SERVICE_GID,True);ledger._check(ledger.directory,0o700,SERVICE_GID,SERVICE_GID,True)
    approval_path=control/'approval.json'
    # Validate the OLD authority and immutable first record before taking any lock.
    first,reference=_first_record(ledger,catalog_digest)
    if transition_reference==strict_json(first)['transition_reference']:raise AdoptionError('invalid_transition_reference')
    _classify_approval(_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384),reference,None)
    job=_lock(ledger.directory/'job.lock')
    try:
        budget=_lock(ledger.directory/'budget.lock')
        try:return _adopt2_locked(ledger,approval_path,first,reference,active_config_hash,catalog_digest,transition_reference,
            source_component_sha256,image_digest,review_receipt_sha256,expected_budget_sha256,protected)
        finally:os.close(budget)
    finally:os.close(job)

def _adopt2_locked(ledger,approval_path,first,reference,active,catalog,transition,source_pin,image_pin,review_pin,budget_pin,protected):
    ceiling=ADOPTION2_MAX_COUNT_REQUESTS
    if os.path.lexists(ledger.halt_path):raise AdoptionError('accounting_halted')
    pre=_read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)
    pre_sha=_sha_of(pre)
    if pre_sha!=budget_pin:raise AdoptionError('budget_pin_mismatch')
    if _first_record(ledger,catalog)[0]!=first:raise AdoptionError('first_record_mismatch')
    current=_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384)
    _verify_checkpoint(pre,reference)
    record=dumps(adoption2_record(active_config_hash=active,catalog_digest=catalog,original_approval_reference=reference,
        transition_reference=transition,source_component_sha256=source_pin,image_digest=image_pin,
        review_receipt_sha256=review_pin,budget_sha256=pre_sha))
    record_sha=_sha_of(record)
    new_approval=dumps(approval_v3(reference,active,record_sha,ceiling))
    state=_classify_approval(current,reference,new_approval)
    resumed=os.path.lexists(ledger.adoption2_path)
    if resumed and _read_regular(ledger,ledger.adoption2_path,0o440,ROOT_UID,SERVICE_GID,16384)!=record:raise AdoptionError('adoption_conflict')
    if state=='committed' and not resumed:raise AdoptionError('adoption_conflict')
    try:
        if not resumed:_publish_exclusive(ledger.adoption2_path,record,protected)
        if state=='legacy':_publish_atomic(approval_path,new_approval,protected)  # approval replacement is the commit
        # Post-verify with the exact runtime parser, outside its own lock (we already hold both).
        if _read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)!=pre:raise AdoptionError('ledger_changed')
        if (ledger.adoption_path.read_bytes()!=first or ledger.adoption2_path.read_bytes()!=record
                or approval_path.read_bytes()!=new_approval):raise AdoptionError('commit_verification_failed')
        summary=ledger._summary(ledger._read())
        if (summary['ledger_id'],summary['sequence'],summary['count_requests'],summary['unresolved'],summary['financial_origin_config_hash'],
                summary['previous_active_config_hash'],summary['active_config_hash'],summary['max_count_requests'],summary['count_capacity_remaining'],
                summary['adoption_record_sha256'],summary['adoption2_record_sha256'],summary['config_lineage'])!=(
                ADOPTION_LEDGER_ID,ADOPTION2_CHECKPOINT['sequence'],ADOPTION2_CHECKPOINT['count_requests'],False,ADOPTION_ORIGIN_CONFIG_HASH,
                ADOPTION1_ACTIVE_CONFIG_HASH,active,ceiling,ceiling-ADOPTION2_CHECKPOINT['count_requests'],ADOPTION1_RECORD_SHA256,record_sha,
                [ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,active]):raise AdoptionError('commit_verification_failed')
    except (OSError,LanguageError,AdoptionError,ValueError,KeyError,TypeError) as exc:
        _halt(ledger)
        raise AdoptionError('adoption_commit_uncertain_halted') from exc
    return {'status':'adopted','resumed':resumed or state=='committed','ledger_id':ADOPTION_LEDGER_ID,
        'financial_origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'previous_active_config_hash':ADOPTION1_ACTIVE_CONFIG_HASH,
        'active_config_hash':active,'catalog_digest':catalog,'policy_hash':POLICY_HASH,
        'adoption_record_sha256':ADOPTION1_RECORD_SHA256,'adoption2_record_sha256':record_sha,'approval_sha256':_sha_of(new_approval),
        'budget_sha256_unchanged':pre_sha,'sequence':summary['sequence'],'count_requests':summary['count_requests'],
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
        result=adopt2(args.control_dir,active_config_hash=args.active_config_hash,catalog_digest=args.catalog_digest,
            transition_reference=args.transition_reference,source_component_sha256=args.source_component_sha256,
            image_digest=args.image_digest,review_receipt_sha256=args.review_receipt_sha256,
            expected_budget_sha256=args.expected_budget_sha256,max_count_requests=args.max_count_requests)
        print(dumps(result).decode());return 0
    except AdoptionError as exc:
        print(json.dumps({'status':'refused','code':exc.code,'provider_calls':0}));return 2
    except (OSError,LanguageError,ValueError,KeyError,TypeError,AttributeError,UnicodeError,RecursionError):
        print(json.dumps({'status':'refused','code':'adoption_precondition_failed','provider_calls':0}));return 2

if __name__=='__main__':raise SystemExit(main())
