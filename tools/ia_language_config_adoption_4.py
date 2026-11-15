#!/usr/bin/env python3
"""Root-only offline FOURTH adoption: exactly the committed third record's active configuration
(829) to one new active configuration on the same ledger and financial origin.

SOURCE ONLY: not part of the runtime image entrypoint. Requires the exact committed approval v4
(count ceiling 127, exhausted at count 127, sequence 635, no holds), the exact pinned 127-entry
budget bytes and the immutable first, second and third record bytes. Publishes the protected
config-adoption-4.json record (exclusive, fsynced), then commits approval v5 atomically with the
fixed count ceiling 127, so this transition gives NO new count headroom. Never writes, copies,
resets, initializes, refunds, restamps or relabels budget.json or records 1-3; makes no network,
secret or provider access. It is not a general ceiling-raise tool and accepts no other transition.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from districtbrief.ia_language import LanguageError, dumps, strict_json
from districtbrief import ia_language_accounting as acc
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_RECORD_SHA256, ADOPTION2_ACTIVE_CONFIG_HASH,
    ADOPTION2_CHECKPOINT, ADOPTION3_ACTIVE_CONFIG_HASH, ADOPTION3_CHECKPOINT, ADOPTION4_CHECKPOINT, ADOPTION4_MAX_COUNT_REQUESTS,
    ADOPTION_CHECKPOINT, ADOPTION_HISTORICAL_CATALOG_DIGEST, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY, POLICY_HASH,
    BudgetLedger, _ref, _sha, adoption4_record, approval_v4, approval_v5, validate_adoption2_record, validate_adoption3_record,
    validate_adoption_record)
from tools.ia_language_config_adoption import (ROOT_UID, SERVICE_GID, AdoptionError, _ancestors, _lock,
    _publish_atomic, _publish_exclusive, _read_regular)
from tools.ia_language_config_adoption_3 import _fingerprint, _halt_checked, _sha_of

# Exact committed approval v4 bytes at the exhausted quality ceiling 127 (cap v8 output); reviewed pin.
APPROVAL4_SHA256='sha256:74ede06c347c9e20794f4387d55d6c35dcd414f9fc6760d7c9437e4408dc8356'
# Record-2/3 and budget pins are read through `acc` at call time (one reviewed copy, no local duplicates).

def _records(ledger):
    """Exact immutable record 1-3 bytes under their committed catalog; returns (raw1, raw2, raw3, approval reference)."""
    raws=[_read_regular(ledger,p,0o440,ROOT_UID,SERVICE_GID,16384) for p in (ledger.adoption_path,ledger.adoption2_path,ledger.adoption3_path)]
    pins=(ADOPTION1_RECORD_SHA256,acc.ADOPTION2_RECORD_SHA256,acc.ADOPTION3_RECORD_SHA256)
    codes=('first_record_mismatch','second_record_mismatch','third_record_mismatch')
    for raw,pin,code in zip(raws,pins,codes):
        if _sha_of(raw)!=pin:raise AdoptionError(code)
    reference=strict_json(raws[0])['original_approval_reference']
    approval={'approval_reference':reference,'adoption_record_sha256':pins[0],'adoption2_record_sha256':pins[1],'adoption3_record_sha256':pins[2]}
    for validate,raw,active,code in zip((validate_adoption_record,validate_adoption2_record,validate_adoption3_record),raws,
            (ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH),codes):
        try:validate(raw,approval,active,ADOPTION_HISTORICAL_CATALOG_DIGEST)
        except ValueError:raise AdoptionError(code) from None
    return (*raws,reference)

def _classify_approval(raw,reference,expected_v5):
    """'legacy' only for the exact committed v4 bytes at ceiling 127; 'committed' only for the exact new v5."""
    if expected_v5 is not None and raw==expected_v5:return 'committed'
    if (raw==dumps(approval_v4(reference,ADOPTION3_ACTIVE_CONFIG_HASH,acc.ADOPTION3_RECORD_SHA256,ADOPTION4_MAX_COUNT_REQUESTS))
            and _sha_of(raw)==APPROVAL4_SHA256):return 'legacy'
    a=strict_json(raw)
    if type(a) is dict and a.get('schema_version')=='ia-language-approval/5':
        if expected_v5 is None:return 'v5_unverified'
        raise AdoptionError('adoption_conflict')
    raise AdoptionError('approval_not_reviewed_third_transition')

def _verify_checkpoint(raw,reference):
    """Exact seq635/count127/1101867000/no-hold 127-entry history with positional origin/c0d/82a/829 stamps."""
    state=strict_json(raw)
    if (type(state) is not dict or state['schema_version']!='ia-language-ledger/1' or state['ledger_id']!=ADOPTION_LEDGER_ID
            or state['config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH or state['policy_hash']!=POLICY_HASH
            or state['limits_nano_usd']!=POLICY['limits_nano_usd'] or state['approval_reference']!=reference
            or type(state['entries']) is not list):raise AdoptionError('ledger_identity_mismatch')
    entries=state['entries']
    def ok(e):
        return (type(e) is dict and e.get('state')=='settled' and e.get('count_requests')==1 and type(e.get('sequence')) is int
            and type(e.get('settled_estimate_nano_usd')) is int and 0<=e['settled_estimate_nano_usd'])
    if not all(map(ok,entries)):raise AdoptionError('ledger_checkpoint_mismatch')
    observed={'sequence':state['sequence'],'count_requests':sum(e['count_requests'] for e in entries),
        'settled_nano_usd':sum(e['settled_estimate_nano_usd'] for e in entries),'held_nano_usd':0,'unresolved':False}
    if observed!=ADOPTION4_CHECKPOINT or len(entries)!=ADOPTION4_CHECKPOINT['count_requests']:raise AdoptionError('ledger_checkpoint_mismatch')
    # Each earlier checkpoint is an exact prefix: (stamp, checkpoint) in committed order; origin entries are unstamped.
    start=0;low=0
    for stamp,cp in ((None,ADOPTION_CHECKPOINT),(ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_CHECKPOINT),
            (ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_CHECKPOINT),(ADOPTION3_ACTIVE_CONFIG_HASH,ADOPTION4_CHECKPOINT)):
        segment=entries[start:cp['count_requests']]
        if (any(('config_hash' in e) if stamp is None else e.get('config_hash')!=stamp for e in segment)
                or any(not low<e['sequence']<=cp['sequence'] for e in segment)
                or sum(e['settled_estimate_nano_usd'] for e in entries[:cp['count_requests']])!=cp['settled_nano_usd']):
            raise AdoptionError('ledger_checkpoint_mismatch')
        start=cp['count_requests'];low=cp['sequence']

def adopt4(control_dir,*,active_config_hash,catalog_digest,transition_reference,source_component_sha256,image_digest,
        review_receipt_sha256,expected_budget_sha256,max_count_requests,protected=True):
    control=Path(control_dir)
    if not all(_sha(v) for v in (active_config_hash,catalog_digest,source_component_sha256,image_digest,review_receipt_sha256,expected_budget_sha256)):raise AdoptionError('invalid_pin')
    if active_config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH):raise AdoptionError('invalid_pin')
    if expected_budget_sha256!=acc.ADOPTION4_BUDGET_SHA256:raise AdoptionError('budget_pin_mismatch')
    if not _ref(transition_reference):raise AdoptionError('invalid_transition_reference')
    # Fixed ceiling: the exhausted 127 stays 127. No other value; headroom needs a separate cap GO.
    if type(max_count_requests) is not int or max_count_requests!=ADOPTION4_MAX_COUNT_REQUESTS:raise AdoptionError('invalid_max_count_requests')
    if protected:
        if os.geteuid()!=ROOT_UID:raise AdoptionError('root_required')
        if not control.is_absolute():raise AdoptionError('control_realpath_mismatch')
        _ancestors(control)
    ledger=BudgetLedger(active_config_hash,control,protected=protected,catalog_digest=catalog_digest)
    ledger._check(control,0o750,ROOT_UID,SERVICE_GID,True);ledger._check(ledger.directory,0o700,SERVICE_GID,SERVICE_GID,True)
    approval_path=control/'approval.json'
    # Validate the OLD authority and immutable records 1-3 before taking any lock.
    *history,reference=_records(ledger)
    if transition_reference in [strict_json(raw)['transition_reference'] for raw in history]:raise AdoptionError('invalid_transition_reference')
    _classify_approval(_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384),reference,None)
    job=_lock(ledger.directory/'job.lock')
    try:
        budget=_lock(ledger.directory/'budget.lock')
        try:return _adopt4_locked(ledger,approval_path,history,reference,active_config_hash,catalog_digest,transition_reference,
            source_component_sha256,image_digest,review_receipt_sha256,protected)
        finally:os.close(budget)
    finally:os.close(job)

def _adopt4_locked(ledger,approval_path,records,reference,active,catalog,transition,source_pin,image_pin,review_pin,protected):
    ceiling=ADOPTION4_MAX_COUNT_REQUESTS
    if os.path.lexists(ledger.halt_path):raise AdoptionError('accounting_halted')
    pre=_read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)
    pre_sha=_sha_of(pre)
    if pre_sha!=acc.ADOPTION4_BUDGET_SHA256:raise AdoptionError('budget_pin_mismatch')
    history=dict(zip((ledger.path,ledger.adoption_path,ledger.adoption2_path,ledger.adoption3_path),(pre,*records)))
    fingerprints={p:_fingerprint(p) for p in history}
    if list(_records(ledger)[:3])!=list(records):raise AdoptionError('record_changed')
    current=_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384)
    _verify_checkpoint(pre,reference)
    record=dumps(adoption4_record(active_config_hash=active,catalog_digest=catalog,original_approval_reference=reference,
        transition_reference=transition,source_component_sha256=source_pin,image_digest=image_pin,
        review_receipt_sha256=review_pin,budget_sha256=pre_sha))
    record_sha=_sha_of(record)
    new_approval=dumps(approval_v5(reference,active,record_sha,ceiling))
    state=_classify_approval(current,reference,new_approval)
    resumed=os.path.lexists(ledger.adoption4_path)
    if resumed and _read_regular(ledger,ledger.adoption4_path,0o440,ROOT_UID,SERVICE_GID,16384)!=record:raise AdoptionError('adoption_conflict')
    if state=='committed' and not resumed:raise AdoptionError('adoption_conflict')
    try:
        if not resumed:_publish_exclusive(ledger.adoption4_path,record,protected)
        if state=='legacy':_publish_atomic(approval_path,new_approval,protected)  # approval replacement is the commit
        # Post-verify bytes, inode and mtime of all history, then the exact runtime parser (both locks held).
        for p,raw in history.items():
            if p.read_bytes()!=raw or _fingerprint(p)!=fingerprints[p]:raise AdoptionError('history_changed')
        if ledger.adoption4_path.read_bytes()!=record or approval_path.read_bytes()!=new_approval:raise AdoptionError('commit_verification_failed')
        summary=ledger._summary(ledger._read())
        lineage=[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH,active]
        records_lineage=[ADOPTION1_RECORD_SHA256,acc.ADOPTION2_RECORD_SHA256,acc.ADOPTION3_RECORD_SHA256,record_sha]
        if (summary['approval_schema'],summary['ledger_id'],summary['sequence'],summary['count_requests'],summary['unresolved'],
                summary['financial_origin_config_hash'],summary['previous_active_config_hash'],summary['active_config_hash'],
                summary['max_count_requests'],summary['count_capacity_remaining'],summary['config_lineage'],
                [x['sha256'] for x in summary['adoption_lineage']],summary['buckets']['test']['settled_usage_estimate_nano_usd'],
                summary['buckets']['demo']['entries'])!=(
                'ia-language-approval/5',ADOPTION_LEDGER_ID,ADOPTION4_CHECKPOINT['sequence'],ADOPTION4_CHECKPOINT['count_requests'],False,
                ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH,active,ceiling,0,lineage,records_lineage,
                ADOPTION4_CHECKPOINT['settled_nano_usd'],0):
            raise AdoptionError('commit_verification_failed')
    except (OSError,LanguageError,AdoptionError,ValueError,KeyError,TypeError) as exc:
        # Partial state (record 4 and/or approval 5) is left exactly as found for root inspection.
        try:_halt_checked(ledger)
        except OSError:raise AdoptionError('adoption_commit_uncertain_halt_unconfirmed') from exc
        raise AdoptionError('adoption_commit_uncertain_halted') from exc
    return {'status':'adopted','resumed':resumed or state=='committed','ledger_id':ADOPTION_LEDGER_ID,
        'financial_origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'previous_active_config_hash':ADOPTION3_ACTIVE_CONFIG_HASH,
        'active_config_hash':active,'config_lineage':summary['config_lineage'],'catalog_digest':catalog,'policy_hash':POLICY_HASH,
        'adoption_record_sha256':records_lineage[0],'adoption2_record_sha256':records_lineage[1],
        'adoption3_record_sha256':records_lineage[2],'adoption4_record_sha256':record_sha,
        'adoption_lineage':summary['adoption_lineage'],'approval_sha256':_sha_of(new_approval),
        'previous_approval_sha256':_sha_of(current) if state=='legacy' else APPROVAL4_SHA256,
        'budget_sha256_unchanged':pre_sha,'history_bytes_inode_mtime_unchanged':True,
        'entries_preserved':len(strict_json(pre)['entries']),'sequence':summary['sequence'],'count_requests':summary['count_requests'],
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
        result=adopt4(args.control_dir,active_config_hash=args.active_config_hash,catalog_digest=args.catalog_digest,
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
