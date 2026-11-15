"""Financial regressions: exact rates, temporary holds, durable unknown liability."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps
from districtbrief.ia_language_accounting import (BudgetLedger,MAX_INPUT,MAX_OUTPUT,POLICY,
    POLICY_HASH,RATES,parse_usage,reservation,usage_cost)

def usage(i=1000,o=100,cached=0,written=0,reasoning=30):
    return {'input_tokens':i,'output_tokens':o,'total_tokens':i+o,
        'input_tokens_details':{'cached_tokens':cached,'cache_write_tokens':written,
            'cache_write_tokens_details':{'ttl_30m_tokens':written,'ttl_12h_tokens':0}},
        'output_tokens_details':{'reasoning_tokens':min(reasoning,o)}}

def ledger_fixture(directory,config='sha256:'+'a'*64):
    root=Path(directory);(root/'ledger').mkdir(mode=0o700)
    ledger=BudgetLedger(config,root,protected=False)
    (root/'approval.json').write_bytes(dumps(ledger.approval_template('approved-test-reference',stage='evaluation')))
    ledger.initialize('approved-test-reference');return ledger

class LanguageAccountingTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.ledger=ledger_fixture(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_exact_current_rate_regression_and_reservation(self):
        self.assertEqual(RATES,{'uncached_input':1000,'cached_input':50,'cache_write_30m':1250,'output':5000})
        self.assertEqual(MAX_INPUT,12288);self.assertEqual(reservation(),27033600)
        self.assertEqual(usage_cost(parse_usage(usage(12288,2048))),22528000)
        self.assertEqual(usage_cost(parse_usage(usage(1597,117))),2182000)
        # 120 max-size generations and8smokes fit test; holds are not multiplied into spend.
        self.assertLess(128*22528000+reservation(),13000000000)
    def test_inclusive_cache_buckets_and_reasoning_not_double_counted(self):
        u=parse_usage(usage(8000,200,3000,4000,150))
        self.assertEqual(u['uncached_input_tokens'],1000)
        self.assertEqual(usage_cost(u),1000*1000+3000*50+4000*1250+200*5000)
        zero=parse_usage(usage(0,0,reasoning=0));self.assertEqual(usage_cost(zero),0)
        # A missing usage object is different from reported all-zero usage.
        for broken in (None,{},dict(usage(),total_tokens=1),dict(usage(),input_tokens=True)):
            with self.assertRaises(LanguageError):parse_usage(broken)
        raw=usage();raw['input_tokens_details'].pop('cache_write_tokens')
        with self.assertRaises(LanguageError):parse_usage(raw)
    def test_temporary_hold_released_after_known_usage(self):
        e=self.ledger.reserve('test','sha256:'+'b'*64);a=self.ledger.summary()['buckets']['test']
        self.assertEqual(a['held_liability_nano_usd'],reservation());self.assertEqual(a['settled_usage_estimate_nano_usd'],0);self.assertEqual(a['nonmodel_contingency_nano_usd'],2000000000);self.assertEqual(a['available_nano_usd'],13000000000-reservation())
        self.ledger.counted(e,1000);self.ledger.dispatched(e);self.ledger.settle(e,parse_usage(usage()),'completed')
        a=self.ledger.summary()['buckets']['test'];self.assertEqual(a['held_liability_nano_usd'],0)
        self.assertEqual(a['settled_usage_estimate_nano_usd'],1500000);self.assertEqual(a['available_nano_usd'],13000000000-1500000)
        self.assertIsNone(self.ledger.summary()['provider_billed_comparison'])
    def test_cancel_before_dispatch_releases_only_undispatched_hold(self):
        e=self.ledger.reserve('demo','hash');self.ledger.release_before_dispatch(e,'cancelled')
        s=self.ledger.summary();self.assertFalse(s['unresolved']);self.assertEqual(s['buckets']['demo']['available_nano_usd'],10000000000)
        e=self.ledger.reserve('demo','hash');self.ledger.counted(e,1000);self.ledger.dispatched(e)
        with self.assertRaises(LanguageError):self.ledger.release_before_dispatch(e,'cancelled')
        self.assertTrue(self.ledger.summary()['unresolved'])
    def test_unknown_liability_blocks_both_buckets_and_survives_restart(self):
        e=self.ledger.reserve('test','hash');self.ledger.counted(e,1000);self.ledger.dispatched(e);self.ledger.unknown(e,'timeout')
        restarted=BudgetLedger(self.ledger.config_hash,self.tmp.name,protected=False)
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError):restarted.reserve(bucket,'hash')
        self.assertEqual(restarted.summary()['buckets']['test']['held_liability_nano_usd'],reservation(1000))
    def test_no_reset_and_approval_reference_is_not_authority(self):
        with self.assertRaises(LanguageError):self.ledger.initialize('approved-test-reference')
        a=json.loads((Path(self.tmp.name)/'approval.json').read_bytes());a['approved']=False
        (Path(self.tmp.name)/'approval.json').write_bytes(dumps(a))
        with self.assertRaises(LanguageError):self.ledger.reserve('test','hash')
    def test_qualification_three_counts_then_requires_root_reconciliation(self):
        a=json.loads((Path(self.tmp.name)/'approval.json').read_bytes());a['stage']='qualification'
        (Path(self.tmp.name)/'approval.json').write_bytes(dumps(a))
        for _ in range(3):
            e=self.ledger.reserve('test','hash');self.ledger.count_dispatched(e);self.ledger.release_before_dispatch(e,'count_rejected')
        with self.assertRaises(LanguageError):self.ledger.reserve('test','hash')
        before=self.ledger.path.read_bytes();a['stage']='evaluation';(Path(self.tmp.name)/'approval.json').write_bytes(dumps(a))
        self.assertEqual(self.ledger.path.read_bytes(),before);self.assertEqual(self.ledger.summary()['count_requests'],3)
        e=self.ledger.reserve('test','hash');self.ledger.release_before_dispatch(e,'cancelled')
    def test_atomic_replace_failure_retains_original_reservation(self):
        e=self.ledger.reserve('test','hash');before=self.ledger.path.read_bytes()
        with patch('districtbrief.ia_language_accounting.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(LanguageError):self.ledger.release_before_dispatch(e,'cancelled')
        self.assertEqual(self.ledger.path.read_bytes(),before);self.assertTrue(self.ledger.halt_path.exists())
        with self.assertRaises(LanguageError):BudgetLedger(self.ledger.config_hash,self.tmp.name,protected=False).reserve('demo','hash')
    def test_settlement_fsync_failure_never_admits_additional_call(self):
        e=self.ledger.reserve('test','hash');self.ledger.counted(e,1000);self.ledger.dispatched(e)
        with patch('districtbrief.ia_language_accounting.os.fsync',side_effect=OSError('injected')):
            with self.assertRaises(LanguageError):self.ledger.settle(e,parse_usage(usage()),'completed')
        with self.assertRaises(LanguageError):self.ledger.reserve('demo','hash')
    def test_directory_fsync_failure_halts_shared_authority_after_replace(self):
        e=self.ledger.reserve('test','hash');self.ledger.counted(e,1000);self.ledger.dispatched(e)
        real_fsync=os.fsync;calls=[]
        def fault(fd):
            calls.append(fd)
            if len(calls)==2:raise OSError('directory sync fault')
            return real_fsync(fd)
        with patch('districtbrief.ia_language_accounting.os.fsync',side_effect=fault):
            with self.assertRaises(LanguageError):self.ledger.settle(e,parse_usage(usage()),'completed')
        self.assertTrue(self.ledger.halt_path.exists())
        for b in ('test','demo'):
            with self.assertRaises(LanguageError):BudgetLedger(self.ledger.config_hash,self.tmp.name,protected=False).reserve(b,'hash')
    def test_process_global_job_lock_nonblocking(self):
        fd=self.ledger.acquire_job()
        try:
            with self.assertRaises(LanguageError):BudgetLedger(self.ledger.config_hash,self.tmp.name,protected=False).acquire_job()
        finally:self.ledger.release_job(fd)
        fd=self.ledger.acquire_job();self.ledger.release_job(fd)
    def test_bucket_cap_rejects_without_consuming_or_shifting(self):
        state=json.loads(self.ledger.path.read_bytes());state['entries']=[{'entry_id':'old','bucket':'test','state':'settled',
            'reserved_nano_usd':14999999999,'settled_estimate_nano_usd':14999999999}]
        self.ledger.path.write_bytes(dumps(state))
        with self.assertRaises(LanguageError):self.ledger.reserve('test','hash')
        self.assertEqual(self.ledger.summary()['buckets']['demo']['available_nano_usd'],10000000000)
