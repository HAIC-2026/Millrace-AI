"""Active funding authority: carry-forward without reset, finite admission per profile, one serialized ledger."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps
from districtbrief.ia_language_funding import (FundingLedger, financial_plan, initialize_ledger, parse_usage, reservation,
    usage_cost, validate_funding)
from districtbrief.ia_language_profiles import load_profiles
from language_funding_fixture import PROFILE, SOL, bound, funding_record, ledger_fixture, usage

PROFILES=load_profiles()

def carried_record(**changes):
    """Same shape and magnitudes as the planned production record (synthetic ids/hashes)."""
    sources=[{'kind':'canonical_ledger','id':'11111111-1111-4111-8111-111111111111','file_sha256':'1'*64,'sequence':1475,'entries':295,
              'starts':295,'released_zero_start':0,'settled_nano_usd':{'test':2784803000,'demo':0},'held_nano_usd':0,'unresolved_entries':0,
              'reference':'test:canonical-ledger'},
             {'kind':'evaluation_journal','id':'22222222-2222-4222-8222-222222222222','file_sha256':'2'*64,'sequence':226,'entries':50,
              'starts':42,'released_zero_start':8,'settled_nano_usd':{'test':435749000,'demo':0},'held_nano_usd':0,'unresolved_entries':0,
              'reference':'test:evaluation-journal'}]
    f=funding_record(limits_nano_usd={'test':22000000000,'demo':3000000000},contingency_nano_usd={'test':7489755000,'demo':712704000},
        admission={'test':{'terra-medium':122,'sol-low':122},'demo':{'terra-medium':58}},max_starts=639,
        carry_forward={'starts':337,'settled_nano_usd':{'test':3220552000,'demo':0},'held_nano_usd':0,'sources':sources})
    for k,v in changes.items():f[k]=copy.deepcopy(v)
    return f

class FundingPlanTests(unittest.TestCase):
    def test_root_tentative_study_plan_fits_same_25_usd(self):
        f=validate_funding(dumps(carried_record()),PROFILES);plan=financial_plan(f,PROFILES)
        self.assertTrue(plan['ok']);self.assertEqual((plan['carried_starts'],plan['admitted_new_starts'],plan['max_starts']),(337,302,639))
        t,d=plan['buckets']['test'],plan['buckets']['demo']
        self.assertEqual(t['by_profile']['terra-medium']['reservation_per_start_nano_usd'],27033600)
        self.assertEqual(t['by_profile']['sol-low']['reservation_per_start_nano_usd'],54067200)
        # Root financial direction: test 20.6046046 + demo 2.2806528 = 22.8852574 USD bounded plan inside the same 25.
        self.assertEqual(t['worst_case_total_nano_usd'],3220552000+7489755000+122*27033600+122*54067200)
        self.assertEqual((t['worst_case_total_nano_usd'],d['worst_case_total_nano_usd'],plan['total']['worst_case_total_nano_usd']),
                         (20604604600,2280652800,22885257400))
        self.assertEqual(plan['total']['headroom_nano_usd'],2114742600)
        # The Count reserve is a P1 planning assumption at the selected model's uncached-input price, not a known fee:
        # historical 2,992,347 counted tokens at Terra input + every admitted new start at its cap and profile price.
        self.assertEqual(f['contingency_nano_usd']['test'],2992347*1000+122*12288*1000+122*12288*2000)
        self.assertEqual(f['contingency_nano_usd']['demo'],58*12288*1000)
        self.assertEqual(plan['count_fee']['historical_count_requests'],337);self.assertEqual(plan['count_fee']['planned_new_count_requests'],302)
        # The original 15 USD test limit could not fund the paired study's worst case; that is why root reallocated.
        old=carried_record(limits_nano_usd={'test':15000000000,'demo':10000000000});self.assertFalse(financial_plan(old,PROFILES)['ok'])
    def test_unfunded_inconsistent_or_unpinned_records_are_refused(self):
        bad={'unfunded_demo':dict(admission={'test':{'terra-medium':122,'sol-low':122},'demo':{'terra-medium':200}}),
             'max_starts_mismatch':dict(max_starts=640),
             'carry_sum':dict(carry_forward=dict(carried_record()['carry_forward'],starts=336)),
             'carry_money':dict(carry_forward=dict(carried_record()['carry_forward'],settled_nano_usd={'test':2784803000,'demo':0})),
             'carry_hold':dict(carry_forward=dict(carried_record()['carry_forward'],held_nano_usd=1)),
             'over_total':dict(total_limit_nano_usd=25000000001),
             'limits_over_total':dict(limits_nano_usd={'test':22000000000,'demo':3000000001}),
             'profile_hash':dict(profile_hashes={'terra-medium':PROFILE.profile_hash,'sol-low':'sha256:'+'0'*64}),
             'unpinned_admission':dict(admission={'test':{'terra-medium':122,'sol-low':122,'sol-medium':1},'demo':{'terra-medium':58}}),
             'not_approved':dict(approved=False),'ledger_id':dict(ledger_id='not-a-uuid'),
             'contingency_over_limit':dict(contingency_nano_usd={'test':2000000000,'demo':3000000001})}
        for name,change in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(LanguageError) as e:validate_funding(dumps(carried_record(**change)),PROFILES)
                self.assertEqual(e.exception.code,'approval_unavailable')
        extra=carried_record();extra['refund_nano_usd']=1
        with self.assertRaises(LanguageError):validate_funding(dumps(extra),PROFILES)
        dup=dumps(carried_record()).replace(b'"approved":true',b'"approved":true,"approved":true')
        with self.assertRaises(LanguageError):validate_funding(dup,PROFILES)

class FundingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.terra=ledger_fixture(self.tmp.name,funding=carried_record());self.sol=bound(self.terra,SOL)
    def tearDown(self):self.tmp.cleanup()
    def start(self,ledger,bucket,tokens=1000,out=100):
        e=ledger.reserve(bucket,'sha256:'+'b'*64);ledger.count_dispatched(e);ledger.counted(e,tokens);ledger.dispatched(e)
        ledger.settle(e,parse_usage(usage(tokens,out),ledger.profile),'completed');return e
    def test_carry_forward_is_cumulative_and_never_fresh_credit(self):
        s=self.terra.summary()
        self.assertEqual((s['carried_starts'],s['new_starts'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining']),(337,0,337,639,302))
        t=s['buckets']['test'];self.assertEqual((t['carried_settled_nano_usd'],t['settled_usage_estimate_nano_usd'],t['new_settled_nano_usd']),(3220552000,3220552000,0))
        self.assertEqual(t['available_nano_usd'],22000000000-3220552000-7489755000)
        self.assertEqual(s['total']['available_nano_usd'],25000000000-3220552000-7489755000-712704000)
        self.assertEqual(json.loads(self.terra.path.read_text())['entries'],[])  # no copied historical transactions
        self.start(self.terra,'test');self.start(self.sol,'test',2000,300)
        s=self.sol.summary();t=s['buckets']['test']
        self.assertEqual(t['new_settled_nano_usd'],(1000*1000+100*5000)+(2000*2000+300*10000))
        self.assertEqual(t['settled_usage_estimate_nano_usd'],3220552000+t['new_settled_nano_usd'])
        self.assertEqual((s['new_starts'],s['count_requests'],s['new_generation_calls']),(2,339,2))
        self.assertEqual(s['admission']['test']['sol-low'],{'cap':122,'used':1,'remaining':121})
        self.assertEqual(s['new_usage_totals_by_profile']['sol-low'],{'input_tokens':2000,'output_tokens':300,'reasoning_tokens_within_output':30})
    def test_profile_admission_is_bucket_and_profile_specific(self):
        with self.assertRaises(LanguageError) as e:self.sol.reserve('demo','h')
        self.assertEqual(e.exception.code,'profile_not_admitted')
        tight=carried_record(admission={'test':{'terra-medium':1,'sol-low':1},'demo':{'terra-medium':1}},max_starts=340)
        self.terra.funding_path.write_bytes(dumps(tight))  # root amendment: same ledger and carry-forward, new finite caps
        self.start(self.sol,'test')
        with self.assertRaises(LanguageError) as e:self.sol.reserve('test','h')
        self.assertEqual(e.exception.code,'count_ceiling_reached')
        self.start(self.terra,'test');self.start(self.terra,'demo')
        for ledger,bucket in ((self.terra,'test'),(self.terra,'demo')):
            with self.assertRaises(LanguageError) as e:ledger.reserve(bucket,'h')
            self.assertEqual(e.exception.code,'count_ceiling_reached')
        self.assertEqual(self.terra.summary()['count_capacity_remaining'],0)
    def test_count_start_is_durable_and_rechecked_before_transport(self):
        e=self.terra.reserve('test','h')
        with self.assertRaises(LanguageError):self.terra.dispatched(e)  # no generation without a durable Count start
        with self.assertRaises(LanguageError):self.terra.counted(e,1000)
        # Root narrows admission after the reservation: the durable recheck immediately before the Count refuses.
        f=carried_record(admission={'test':{'terra-medium':0,'sol-low':1},'demo':{'terra-medium':1}},max_starts=339)
        self.terra.funding_path.write_bytes(dumps(f))
        with self.assertRaises(LanguageError) as err:self.terra.count_dispatched(e)
        self.assertEqual(err.exception.code,'count_ceiling_reached')
        self.terra.release_before_dispatch(e,'count_ceiling_reached')
        s=self.terra.summary();self.assertFalse(s['unresolved']);self.assertEqual((s['new_starts'],s['states']['released']),(0,1))
    def test_unknown_liability_from_one_profile_blocks_all_profiles_and_buckets(self):
        e=self.sol.reserve('test','h');self.sol.count_dispatched(e);self.sol.counted(e,1000);self.sol.dispatched(e);self.sol.unknown(e,'provider_timeout')
        for ledger,bucket in ((self.terra,'test'),(self.terra,'demo'),(self.sol,'test')):
            with self.assertRaises(LanguageError) as err:ledger.reserve(bucket,'h')
            self.assertEqual(err.exception.code,'unresolved_liability')
        s=self.terra.summary();self.assertEqual(s['buckets']['test']['held_liability_nano_usd'],reservation(SOL,1000))
        with self.assertRaises(LanguageError):self.terra.settle(e,parse_usage(usage(),PROFILE),'completed')  # only its own profile advances it
        with self.assertRaises(LanguageError):self.terra.release_before_dispatch(e,'x')
        self.assertTrue(self.terra.summary()['unresolved'])
    def test_one_job_slot_shared_across_profiles_and_processes(self):
        fd=self.sol.acquire_job()
        try:
            with self.assertRaises(LanguageError) as err:self.terra.acquire_job()
            self.assertEqual(err.exception.code,'busy')
        finally:self.sol.release_job(fd)
        self.terra.release_job(self.terra.acquire_job())
    def test_no_reset_refund_or_reinitialization(self):
        self.start(self.terra,'test');before=self.terra.path.read_bytes()
        with self.assertRaises(LanguageError):self.terra.initialize('approved-test-reference')
        with self.assertRaises(LanguageError):self.terra.approval_template('x')
        with self.assertRaises(LanguageError) as err:initialize_ledger(self.root,protected=False)
        self.assertEqual(err.exception.code,'ledger_exists');self.assertEqual(self.terra.path.read_bytes(),before)
        # Amending the carry-forward (e.g. a refund) breaks the binding: fail closed, never re-seed.
        refund=carried_record();refund['carry_forward']['sources'][1]['settled_nano_usd']['test']=0;refund['carry_forward']['settled_nano_usd']['test']=2784803000
        self.terra.funding_path.write_bytes(dumps(refund))
        with self.assertRaises(LanguageError) as err:self.terra.summary()
        self.assertEqual(err.exception.code,'ledger_unavailable')
        with self.assertRaises(LanguageError) as err:self.terra.reserve('test','h')
        self.assertEqual(err.exception.code,'ledger_unavailable')
        self.terra.funding_path.write_bytes(dumps(carried_record()));self.assertEqual(self.terra.summary()['new_starts'],1)
        # A missing ledger is unavailable for the service; only the one-shot operator init could create one, and HALTED blocks it.
        os.rename(self.terra.path,self.root/'moved.json')
        with self.assertRaises(LanguageError):self.terra.reserve('test','h')
        self.terra.halt_path.write_bytes(b'')
        with self.assertRaises(LanguageError):initialize_ledger(self.root,protected=False)
        self.assertFalse(self.terra.path.exists())
    def seal(self):
        from districtbrief.ia_language_funding import genesis_record
        g=genesis_record(json.loads(self.terra.path.read_text()));self.terra.genesis_path.write_bytes(dumps(g));return g
    def test_sealed_genesis_forbids_reinitialization_and_detects_recreated_ledger(self):
        self.start(self.terra,'test');g=self.seal();self.assertEqual(self.terra.summary()['new_starts'],1)
        os.rename(self.terra.path,self.root/'moved.json')
        with self.assertRaises(LanguageError) as err:initialize_ledger(self.root,protected=False)
        self.assertEqual(err.exception.code,'ledger_initialization_forbidden');self.assertFalse(self.terra.path.exists())
        # Even a re-created ledger (hand-written, same funding) is refused because its genesis differs.
        fresh=dict(json.loads((self.root/'moved.json').read_text()),created_at=g['created_at']+1.0,sequence=0,entries=[])
        self.terra.path.write_bytes(dumps(fresh))
        for ledger in (self.terra,self.sol):
            with self.assertRaises(LanguageError) as err:ledger.reserve('test','h')
            self.assertEqual(err.exception.code,'ledger_unavailable')
        os.replace(self.root/'moved.json',self.terra.path);self.assertEqual(self.terra.summary()['new_starts'],1)
        for bad in (dict(g,ledger_id='33333333-3333-4333-8333-333333333333'),dict(g,extra=1),dict(g,created_at=int(g['created_at']))):
            self.terra.genesis_path.write_bytes(dumps(bad))
            with self.assertRaises(LanguageError):self.terra.summary()
    def test_protected_ledger_requires_the_genesis_sentinel(self):
        from districtbrief.ia_language_funding import FundingLedger as FL
        class Unchecked(FL):
            def _check(self,*a,**k):pass  # ownership/mode checks are host-only; this isolates the sentinel rule
            def _protected_read(self,p):return Path(p).read_bytes()
        protected=Unchecked(PROFILE,self.root,config_hash=self.terra.config_hash,protected=True)
        with self.assertRaises(LanguageError) as err:protected.summary()
        self.assertEqual(err.exception.code,'ledger_unavailable')
        self.seal();self.assertEqual(protected.summary()['new_starts'],0)
    def test_halted_is_sticky_and_blocks_both_profiles(self):
        with patch('districtbrief.ia_language_accounting.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(LanguageError):self.terra.reserve('test','h')
        self.assertTrue(self.terra.halt_path.exists())
        for ledger in (bound(self.terra,PROFILE),bound(self.terra,SOL)):
            with self.assertRaises(LanguageError) as err:ledger.reserve('test','h')
            self.assertEqual(err.exception.code,'accounting_halted')
            with self.assertRaises(LanguageError):ledger.acquire_job()
        self.assertTrue(self.terra.halt_path.exists())
    def test_tampered_ledger_entries_fail_closed(self):
        self.start(self.terra,'test');good=json.loads(self.terra.path.read_text())
        for name,mutate in {'model_without_count':lambda s:s['entries'][0].update(count_requests=0),
                            'settled_over_hold':lambda s:s['entries'][0].update(settled_estimate_nano_usd=s['entries'][0]['reserved_nano_usd']+1),
                            'copied_history':lambda s:s.update(carry_forward_sha256='sha256:'+'0'*64),
                            'foreign_ledger':lambda s:s.update(ledger_id='33333333-3333-4333-8333-333333333333'),
                            'sequence':lambda s:s['entries'][0].update(sequence=s['sequence']+1),
                            'extra_key':lambda s:s['entries'][0].update(refund=True)}.items():
            with self.subTest(name=name):
                s=copy.deepcopy(good);mutate(s);self.terra.path.write_bytes(dumps(s))
                with self.assertRaises(LanguageError) as err:self.terra.summary()
                self.assertEqual(err.exception.code,'ledger_unavailable')
    def test_protected_mode_requires_root_owned_funding_and_private_ledger(self):
        protected=FundingLedger(PROFILE,self.root,config_hash=self.terra.config_hash,protected=True)
        with self.assertRaises(LanguageError) as err:protected.summary()
        self.assertEqual(err.exception.code,'approval_unavailable')
    def test_pricing_uses_profile_rates_reasoning_subset_and_caps(self):
        u=parse_usage(usage(8000,200,3000,4000,150),SOL)
        self.assertEqual(usage_cost(u,SOL),1000*2000+3000*100+4000*2500+200*10000)
        self.assertEqual(usage_cost(u,PROFILE),1000*1000+3000*50+4000*1250+200*5000)
        self.assertEqual(usage_cost(parse_usage(usage(1000,2048,reasoning=2048),SOL),SOL),1000*2000+2048*10000)  # reasoning not added again
        for broken in (usage(12289,1),usage(1000,2049)):
            with self.assertRaises(LanguageError) as err:parse_usage(broken,SOL)
            self.assertEqual(err.exception.code,'usage_exceeds_limits')
        for p in (PROFILE,SOL):
            worst=usage_cost(parse_usage(usage(12288,2048,0,12288,2048),p),p)  # even all-cache-write input fits the hold
            self.assertLessEqual(worst,reservation(p))
        with self.assertRaises(LanguageError):reservation(SOL,12289)

if __name__=='__main__':unittest.main()
