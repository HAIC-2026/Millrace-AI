#!/usr/bin/env python3
"""Root-only offline adoption of the single reviewed origin-to-active language configuration.

Writes exactly the protected config-adoption.json record, then commits approval v2.
Never writes, copies, resets or relabels budget.json; makes no network or provider calls.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from districtbrief.ia_language import LanguageError, dumps, strict_json
from districtbrief.ia_language_accounting import (ADOPTION_CHECKPOINT, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH,
    MAX_COUNT_CEILING, POLICY, POLICY_HASH, BudgetLedger, _V1_KEYS, _ref, _sha, adoption_record, approval_v2)

ROOT_UID=0
SERVICE_GID=10001

class AdoptionError(Exception):
    def __init__(self,code):super().__init__(code);self.code=code

def _fsync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def _halt(ledger):
    # Same shared marker as the runtime: commit durability is uncertain, so nothing may spend.
    try:
        fd=os.open(ledger.halt_path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
        _fsync_dir(ledger.directory)
    except OSError:pass

def _read_regular(ledger,path,mode,uid,gid,limit):
    ledger._check(path,mode,uid,gid)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:raw=f.read(limit+1)
    if len(raw)>limit:raise AdoptionError('control_file_too_large')
    return raw

def _ancestors(path):
    # Expected realpath and protected ancestors: no symlinked or group/world-writable path component.
    if Path(os.path.realpath(path))!=path:raise AdoptionError('control_realpath_mismatch')
    for p in path.parents:
        s=p.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid!=ROOT_UID or stat.S_IMODE(s.st_mode)&0o022:raise AdoptionError('control_ancestor_unprotected')

def _classify_approval(raw,expected_v2):
    """Return 'legacy' for the exact old qualification authority, 'committed' for the exact new one."""
    if raw==expected_v2:return 'committed'
    a=strict_json(raw)
    if type(a) is dict and a.get('schema_version')=='ia-language-approval/2':raise AdoptionError('adoption_conflict')
    if (type(a) is not dict or set(a)!=_V1_KEYS or a['schema_version']!='ia-language-approval/1' or a['approved'] is not True
            or a['provider']!='openai' or a['model']!=POLICY['model'] or a['limits_nano_usd']!=POLICY['limits_nano_usd']
            or a['policy_hash']!=POLICY_HASH or a['config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH or a['stage']!='qualification'
            or not _ref(a['approval_reference'])):raise AdoptionError('approval_not_reviewed_origin')
    return 'legacy'

def _verify_checkpoint(raw,reference):
    state=strict_json(raw)
    if (state['schema_version']!='ia-language-ledger/1' or state['ledger_id']!=ADOPTION_LEDGER_ID
            or state['config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH or state['policy_hash']!=POLICY_HASH
            or state['limits_nano_usd']!=POLICY['limits_nano_usd'] or state['approval_reference']!=reference
            or type(state['entries']) is not list):raise AdoptionError('ledger_identity_mismatch')
    entries=state['entries']
    settled=sum(e['settled_estimate_nano_usd'] for e in entries if e['state']=='settled')
    held=sum(e['reserved_nano_usd'] for e in entries if e['state'] in ('reserved','dispatched','unknown'))
    observed={'sequence':state['sequence'],'count_requests':sum(e.get('count_requests',0) for e in entries),
        'settled_nano_usd':settled,'held_nano_usd':held,'unresolved':any(e['state'] in ('reserved','dispatched','unknown') for e in entries)}
    if observed!=ADOPTION_CHECKPOINT or any('config_hash' in e for e in entries):raise AdoptionError('ledger_checkpoint_mismatch')

def _lock(path):
    fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)  # Existing service lock only; root never creates it.
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise AdoptionError('lock_not_regular')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:os.close(fd);raise AdoptionError('busy') from None
    except BaseException:os.close(fd);raise
    return fd

def _publish_exclusive(path,data,protected):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o440)
    try:
        if protected:os.fchown(fd,ROOT_UID,SERVICE_GID)
        os.fchmod(fd,0o440)
        view=memoryview(data)
        while view:view=view[os.write(fd,view):]
        os.fsync(fd)
    finally:os.close(fd)
    _fsync_dir(path.parent)

def _publish_atomic(path,data,protected):
    tmp=path.parent/('.approval-'+uuid.uuid4().hex)
    try:
        _publish_exclusive(tmp,data,protected)
        os.replace(tmp,path)
        _fsync_dir(path.parent)
    finally:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass

def adopt(control_dir,*,active_config_hash,catalog_digest,transition_reference,source_component_sha256,
        image_digest,review_receipt_sha256,max_count_requests,protected=True):
    control=Path(control_dir)
    if not all(_sha(v) for v in (active_config_hash,catalog_digest,source_component_sha256,image_digest,review_receipt_sha256)):raise AdoptionError('invalid_pin')
    if active_config_hash==ADOPTION_ORIGIN_CONFIG_HASH:raise AdoptionError('invalid_pin')
    if not _ref(transition_reference):raise AdoptionError('invalid_transition_reference')
    if type(max_count_requests) is not int or not ADOPTION_CHECKPOINT['count_requests']<max_count_requests<=MAX_COUNT_CEILING:raise AdoptionError('invalid_max_count_requests')
    if protected:
        if os.geteuid()!=ROOT_UID:raise AdoptionError('root_required')
        if not control.is_absolute():raise AdoptionError('control_realpath_mismatch')
        _ancestors(control)
    ledger=BudgetLedger(active_config_hash,control,protected=protected,catalog_digest=catalog_digest)
    ledger._check(control,0o750,ROOT_UID,SERVICE_GID,True);ledger._check(ledger.directory,0o700,SERVICE_GID,SERVICE_GID,True)
    approval_path=control/'approval.json'
    # Validate the OLD authority before taking any lock; resume also tolerates the exact new commit.
    raw=_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384)
    if strict_json(raw).get('schema_version')!='ia-language-approval/2':_classify_approval(raw,None)
    job=_lock(ledger.directory/'job.lock')
    try:
        budget=_lock(ledger.directory/'budget.lock')
        try:return _adopt_locked(ledger,approval_path,active_config_hash,catalog_digest,transition_reference,
            source_component_sha256,image_digest,review_receipt_sha256,max_count_requests,protected)
        finally:os.close(budget)
    finally:os.close(job)

def _adopt_locked(ledger,approval_path,active,catalog,transition,source_pin,image_pin,review_pin,ceiling,protected):
    if os.path.lexists(ledger.halt_path):raise AdoptionError('accounting_halted')
    pre=_read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)
    pre_sha='sha256:'+hashlib.sha256(pre).hexdigest()
    current=_read_regular(ledger,approval_path,0o440,ROOT_UID,SERVICE_GID,16384)
    reference=strict_json(current).get('approval_reference')
    if not _ref(reference):raise AdoptionError('approval_not_reviewed_origin')
    _verify_checkpoint(pre,reference)
    record=dumps(adoption_record(active_config_hash=active,catalog_digest=catalog,original_approval_reference=reference,
        transition_reference=transition,source_component_sha256=source_pin,image_digest=image_pin,
        review_receipt_sha256=review_pin,budget_sha256=pre_sha))
    record_sha='sha256:'+hashlib.sha256(record).hexdigest()
    new_approval=dumps(approval_v2(reference,active,record_sha,ceiling))
    state=_classify_approval(current,new_approval)
    resumed=os.path.lexists(ledger.adoption_path)
    if resumed and _read_regular(ledger,ledger.adoption_path,0o440,ROOT_UID,SERVICE_GID,16384)!=record:raise AdoptionError('adoption_conflict')
    if state=='committed' and not resumed:raise AdoptionError('adoption_conflict')
    try:
        if not resumed:_publish_exclusive(ledger.adoption_path,record,protected)
        if state=='legacy':_publish_atomic(approval_path,new_approval,protected)  # approval replacement is the commit
        # Post-verify with the exact runtime parser, outside its own lock (we already hold both).
        if _read_regular(ledger,ledger.path,0o600,SERVICE_GID,SERVICE_GID,4*1024*1024)!=pre:raise AdoptionError('ledger_changed')
        if ledger.adoption_path.read_bytes()!=record or approval_path.read_bytes()!=new_approval:raise AdoptionError('commit_verification_failed')
        summary=ledger._summary(ledger._read())
        if (summary['ledger_id'],summary['sequence'],summary['count_requests'],summary['unresolved'],summary['financial_origin_config_hash'],
                summary['active_config_hash'],summary['max_count_requests'],summary['adoption_record_sha256'])!=(
                ADOPTION_LEDGER_ID,ADOPTION_CHECKPOINT['sequence'],ADOPTION_CHECKPOINT['count_requests'],False,
                ADOPTION_ORIGIN_CONFIG_HASH,active,ceiling,record_sha):raise AdoptionError('commit_verification_failed')
    except (OSError,LanguageError,AdoptionError,ValueError,KeyError,TypeError) as exc:
        _halt(ledger)
        raise AdoptionError('adoption_commit_uncertain_halted') from exc
    return {'status':'adopted','resumed':resumed or state=='committed','ledger_id':ADOPTION_LEDGER_ID,
        'financial_origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'active_config_hash':active,'catalog_digest':catalog,
        'policy_hash':POLICY_HASH,'adoption_record_sha256':record_sha,'approval_sha256':'sha256:'+hashlib.sha256(new_approval).hexdigest(),
        'budget_sha256_unchanged':pre_sha,'sequence':summary['sequence'],'count_requests':summary['count_requests'],
        'max_count_requests':ceiling,'count_capacity_remaining':summary['count_capacity_remaining'],
        'buckets':summary['buckets'],'provider_calls':0,'ledger_writes':0}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',required=True)
    for name in ('active-config-hash','catalog-digest','transition-reference','source-component-sha256','image-digest','review-receipt-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-count-requests',required=True,type=int)
    args=parser.parse_args(argv)
    try:
        result=adopt(args.control_dir,active_config_hash=args.active_config_hash,catalog_digest=args.catalog_digest,
            transition_reference=args.transition_reference,source_component_sha256=args.source_component_sha256,
            image_digest=args.image_digest,review_receipt_sha256=args.review_receipt_sha256,max_count_requests=args.max_count_requests)
        print(dumps(result).decode());return 0
    except AdoptionError as exc:
        print(json.dumps({'status':'refused','code':exc.code,'provider_calls':0}));return 2
    except (OSError,LanguageError,ValueError,KeyError,TypeError,AttributeError,UnicodeError,RecursionError):
        print(json.dumps({'status':'refused','code':'adoption_precondition_failed','provider_calls':0}));return 2

if __name__=='__main__':raise SystemExit(main())
