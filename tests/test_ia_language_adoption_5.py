"""Offline FIFTH configuration adoption (record-4 active f73 -> one new active, ceiling 253 -> 395) on the same ledger.
Temp directories only. The SYNTHETIC history is built from the adoption-4 synthetic fixture: the unstubbed adoption-4
helper commits a synthetic record 4 for f73 under the historical catalog, then 126 synthetic settled f73 entries bring
the budget to the exact checkpoint (sequence 1265, count 253, 2,364,916,000 nano-USD, no holds) and approval v5 is set to
the committed ceiling 253. Record/budget/approval pins are overridden test-locally with the synthetic hashes; a separate
test proves the unpatched production pins are the reviewed values and refuse the synthetic history. No actual ledger
bytes, host control state, secrets or network. Protected-mode cases use the local owner mapping only."""
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps, strict_json
from districtbrief import ia_language_accounting as acc
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_RECORD_SHA256, ADOPTION2_ACTIVE_CONFIG_HASH,
    ADOPTION3_ACTIVE_CONFIG_HASH, ADOPTION4_ACTIVE_CONFIG_HASH, ADOPTION_HISTORICAL_CATALOG_DIGEST, ADOPTION_ORIGIN_CONFIG_HASH,
    POLICY, POLICY_HASH, BudgetLedger, approval_v5, approval_v6, reservation)
from tools import ia_language_config_adoption_4 as helper4
from tools import ia_language_config_adoption_5 as helper

FIXTURES=Path(__file__).parent/'fixtures'
V5=json.loads((FIXTURES/'ia-language-dev-v5-replay.json').read_text())
CP=json.loads((FIXTURES/'ia-language-adoption4-synthetic.json').read_text())
assert CP['synthetic'] is True
OVERRIDE4=CP['test_pin_overrides']
RECORD1=dumps(V5['first_adoption_record']);RECORD2=dumps(CP['record2']);RECORD3=dumps(CP['record3'])
REF=CP['record3']['original_approval_reference']
F73=ADOPTION4_ACTIVE_CONFIG_HASH
NEW='sha256:'+'1'*64
NEW_CATALOG='sha256:'+'8'*64
PINS={'transition_reference':'root-go-adoption-5','source_component_sha256':'sha256:'+'2'*64,
      'image_digest':'sha256:'+'3'*64,'review_receipt_sha256':'sha256:'+'4'*64}
CHECKPOINT={'sequence':1265,'count_requests':253,'settled_nano_usd':2364916000,'held_nano_usd':0,'unresolved':False}
PRODUCTION={'ADOPTION4_RECORD_SHA256':'sha256:9785a2bf73542af00a62757b538e489e1625b5d543497dc7b58d872ba82ec4ed',
    'ADOPTION5_BUDGET_SHA256':'sha256:535ca077d3403df74f1fc5935781a7ac9d2d74e01d05c16c332f2ade2a3220de'}
PRODUCTION_APPROVAL5='sha256:8fbbbad37ffa0c757f15a6b0f8dd6e6115cadd7e2863a8a2dbf53778cfeb525c'
EARLIER=(ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH,F73)
def sha(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def fp(p):s=os.stat(p);return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
def put(path,data):
    if path.exists():os.chmod(path,0o640)  # offline fixtures only: published files are 0440
    path.write_bytes(data)

def synthetic_history(root):
    """Build records 1-4, the 253-entry budget and approval v5 at 253 in `root`; returns the synthetic pins."""
    (root/'ledger').mkdir(mode=0o700)
    for name,data in (('config-adoption.json',RECORD1),('config-adoption-2.json',RECORD2),('config-adoption-3.json',RECORD3),
            ('approval.json',dumps(CP['approval4']))):(root/name).write_bytes(data)
    (root/'ledger'/'budget.json').write_bytes(dumps(CP['budget']))
    for lock in ('job.lock','budget.lock'):(root/'ledger'/lock).write_bytes(b'')
    with patch.multiple(acc,**{k:OVERRIDE4[k] for k in ('ADOPTION2_RECORD_SHA256','ADOPTION3_BUDGET_SHA256','ADOPTION3_RECORD_SHA256','ADOPTION4_BUDGET_SHA256')}),\
         patch.object(helper4,'APPROVAL4_SHA256',OVERRIDE4['APPROVAL4_SHA256']):
        helper4.adopt4(root,active_config_hash=F73,catalog_digest=ADOPTION_HISTORICAL_CATALOG_DIGEST,
            transition_reference='SYNTHETIC-adoption-4',source_component_sha256='sha256:'+'5'*64,image_digest='sha256:'+'6'*64,
            review_receipt_sha256='sha256:'+'7'*64,expected_budget_sha256=OVERRIDE4['ADOPTION4_BUDGET_SHA256'],max_count_requests=127,protected=False)
    record4=(root/'config-adoption-4.json').read_bytes()
    budget=copy.deepcopy(CP['budget']);template=budget['entries'][-1]
    extra=CHECKPOINT['settled_nano_usd']-sum(e['settled_estimate_nano_usd'] for e in budget['entries'])
    each,rest=divmod(extra,126)
    for k in range(126):
        e=dict(template,entry_id=f'00000000-0000-4000-8000-{127+k:012d}',sequence=635+5*k+1,config_hash=F73,
               created_at=float(128+k),settled_at=128.5+k,reserved_nano_usd=reservation(),settled_estimate_nano_usd=each+(rest if k==125 else 0))
        budget['entries'].append(e)
    budget['sequence']=CHECKPOINT['sequence'];raw_budget=dumps(budget)
    put(root/'ledger'/'budget.json',raw_budget)
    with patch.multiple(acc,**{k:OVERRIDE4[k] for k in ('ADOPTION2_RECORD_SHA256','ADOPTION3_RECORD_SHA256')}):
        approval5=dumps(approval_v5(REF,F73,sha(record4),253))  # embeds the synthetic record-2/3 pins
    put(root/'approval.json',approval5)
    return {'record4':record4,'budget':raw_budget,'approval5':approval5,
            'pins':{'ADOPTION2_RECORD_SHA256':OVERRIDE4['ADOPTION2_RECORD_SHA256'],'ADOPTION3_RECORD_SHA256':OVERRIDE4['ADOPTION3_RECORD_SHA256'],
                    'ADOPTION3_BUDGET_SHA256':OVERRIDE4['ADOPTION3_BUDGET_SHA256'],'ADOPTION4_BUDGET_SHA256':OVERRIDE4['ADOPTION4_BUDGET_SHA256'],
                    'ADOPTION4_RECORD_SHA256':sha(record4),'ADOPTION5_BUDGET_SHA256':sha(raw_budget)}}

class FifthAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=self.root=Path(self.tmp.name)
        h=self.h=synthetic_history(r)
        p=patch.multiple(acc,**h['pins']);p.start();self.addCleanup(p.stop)
        p=patch.object(helper,'APPROVAL5_SHA256',sha(h['approval5']));p.start();self.addCleanup(p.stop)
        self.budget=r/'ledger'/'budget.json';self.approval=r/'approval.json';self.record5=r/'config-adoption-5.json'
        self.halted=r/'ledger'/'HALTED'
        self.history={p:(p.read_bytes(),fp(p)) for p in (self.budget,*(r/f for f in ('config-adoption.json','config-adoption-2.json','config-adoption-3.json','config-adoption-4.json')))}
        time.sleep(0.01)  # a rewrite would visibly move mtime_ns
    def tearDown(self):self.tmp.cleanup()
    def adopt(self,**over):
        kw=dict(active_config_hash=NEW,catalog_digest=NEW_CATALOG,expected_budget_sha256=self.h['pins']['ADOPTION5_BUDGET_SHA256'],
            max_count_requests=395,protected=False,**PINS)
        kw.update(over);return helper.adopt5(self.root,**kw)
    def refused(self,code,**over):
        with self.assertRaises(helper.AdoptionError) as c:self.adopt(**over)
        self.assertEqual(c.exception.code,code)
    def ledger(self,config=NEW,catalog=NEW_CATALOG):return BudgetLedger(config,self.root,protected=False,catalog_digest=catalog)
    def old_ledger(self):return self.ledger(F73,ADOPTION_HISTORICAL_CATALOG_DIGEST)
    def assert_history(self):
        for p,(raw,f) in self.history.items():self.assertEqual((p.read_bytes(),fp(p)),(raw,f),p.name)
    def assert_untouched(self):
        self.assert_history();self.assertEqual(self.approval.read_bytes(),self.h['approval5']);self.assertFalse(self.record5.exists())
        self.assertFalse(self.halted.exists())
    def uncreatable_marker(self):
        real=os.open;halt=str(self.halted)
        def guarded(path,*a,**k):
            if os.fspath(path)==halt:raise PermissionError(13,'synthetic uncreatable marker',halt)
            return real(path,*a,**k)
        p=patch('os.open',guarded);p.start();self.addCleanup(p.stop)

    def test_production_pins_are_reviewed_values_and_refuse_the_synthetic_history(self):
        patch.stopall()
        self.assertEqual({k:getattr(acc,k) for k in PRODUCTION},PRODUCTION)
        self.assertEqual(helper.APPROVAL5_SHA256,PRODUCTION_APPROVAL5)
        self.assertEqual((acc.ADOPTION5_CHECKPOINT,acc.ADOPTION5_MAX_COUNT_REQUESTS,acc.MAX_COUNT_CEILING,acc.ADOPTION4_COMMITTED_MAX_COUNT_REQUESTS,
            acc.ADOPTION4_ACTIVE_CONFIG_HASH,acc.POLICY_HASH),(CHECKPOINT,395,395,253,
            'sha256:f73aa800b625eab3d24c2a60b0f533e66f9769db5c3e8e5adf5b5d810206ff16',
            'sha256:14ec7c8f8dede96f5ad543dfce02c7a3eb57e74edb40391a3aefeff897375ac5'))
        self.assertFalse(set(self.h['pins'].values())&set(PRODUCTION.values()))
        self.refused('budget_pin_mismatch')  # only the 535c budget is admissible
        self.refused('second_record_mismatch',expected_budget_sha256=PRODUCTION['ADOPTION5_BUDGET_SHA256'])
        self.assert_untouched()

    def test_synthetic_history_is_the_exact_checkpoint_and_v5_reads_before_adoption(self):
        state=strict_json(self.h['budget']);entries=state['entries']
        self.assertEqual((len(entries),state['sequence'],sum(e['settled_estimate_nano_usd'] for e in entries)),(253,1265,2364916000))
        self.assertTrue(all(e['entry_id'].startswith('00000000-0000-4000-8000-') for e in entries))
        s=self.old_ledger().summary()
        self.assertEqual((s['approval_schema'],s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining']),
            ('ia-language-approval/5',1265,253,253,0))
        with self.assertRaises(LanguageError):self.ledger().summary()  # no authority for the new config before adoption

    def test_adopts_once_with_ceiling_395_and_preserves_all_253_entries(self):
        out=self.adopt();self.assert_history()
        record=self.record5.read_bytes();r=strict_json(record)
        self.assertEqual((r['schema_version'],r['previous_active_config_hash'],r['previous_adoption_record_sha256'],r['active_config_hash'],
            r['catalog_digest'],r['checkpoint']),('ia-language-config-adoption/5',F73,self.h['pins']['ADOPTION4_RECORD_SHA256'],NEW,NEW_CATALOG,
            dict(CHECKPOINT,budget_sha256=self.h['pins']['ADOPTION5_BUDGET_SHA256'])))
        self.assertEqual(self.approval.read_bytes(),dumps(approval_v6(REF,NEW,sha(record),395)))
        a=strict_json(self.approval.read_bytes())
        self.assertEqual((a['schema_version'],a['adoption4_record_sha256'],a['adoption5_record_sha256'],a['max_count_requests'],a['policy_hash'],
            a['limits_nano_usd']),('ia-language-approval/6',self.h['pins']['ADOPTION4_RECORD_SHA256'],sha(record),395,POLICY_HASH,POLICY['limits_nano_usd']))
        self.assertEqual((out['status'],out['entries_preserved'],out['count_requests'],out['max_count_requests'],out['count_capacity_remaining'],
            out['provider_calls'],out['ledger_writes'],out['budget_sha256_unchanged']),('adopted',253,253,395,142,0,0,self.h['pins']['ADOPTION5_BUDGET_SHA256']))
        s=self.ledger().summary()
        self.assertEqual(s['config_lineage'],[*EARLIER,NEW]);self.assertEqual(len(s['adoption_lineage']),5)
        self.assertEqual([x['transition_reference'] for x in s['adoption_lineage']][-2:],['SYNTHETIC-adoption-4','root-go-adoption-5'])
        self.assertEqual((s['sequence'],s['count_requests'],s['unresolved'],sum(b['held_liability_nano_usd'] for b in s['buckets'].values()),
            s['buckets']['test']['settled_usage_estimate_nano_usd']),(1265,253,False,0,2364916000))
        # Resume is idempotent and writes nothing further.
        again=self.adopt();self.assertTrue(again['resumed']);self.assert_history()
        # Older authorities refuse once record 5 exists.
        with self.assertRaises(LanguageError):self.old_ledger().summary()

    def test_v6_lineage_preserves_history_and_stamps_only_after_1265(self):
        self.adopt();ledger=self.ledger()
        eid=ledger.reserve('test','sha256:'+'9'*64);state=strict_json(self.budget.read_bytes())
        e=state['entries'][-1];self.assertEqual((e['entry_id'],e['sequence'],e['config_hash']),(eid,1266,NEW))
        ledger.release_before_dispatch(eid,'synthetic');self.assertEqual(len(strict_json(self.budget.read_bytes())['entries']),254)
        base=strict_json(self.budget.read_bytes())
        for index,stamp,seq in ((300,F73,1300),(253,F73,1266),(200,NEW,1000),(100,ADOPTION3_ACTIVE_CONFIG_HASH,700),(0,NEW,1),(130,None,700)):
            with self.subTest(index=index,stamp=str(stamp)[:12],seq=seq):
                b=copy.deepcopy(base)
                if index>=len(b['entries']):b['entries'].append(dict(b['entries'][-1],entry_id='x',sequence=seq,config_hash=stamp))
                else:
                    b['entries'][index]['sequence']=seq
                    if stamp is None:b['entries'][index].pop('config_hash',None)
                    else:b['entries'][index]['config_hash']=stamp
                put(self.budget,dumps(b))
                with self.assertRaises(LanguageError):self.ledger().summary()
        put(self.budget,dumps(base));self.assertEqual(self.ledger().summary()['count_requests'],253)

    def test_ceiling_395_refuses_the_next_count_and_larger_approvals(self):
        self.adopt();base=strict_json(self.budget.read_bytes());seq=base['sequence']
        for k in range(142):
            seq+=5;base['entries'].append(dict(base['entries'][-1],entry_id=f'c-{k}',sequence=seq-4,config_hash=NEW,settled_estimate_nano_usd=1))
        base['sequence']=seq;put(self.budget,dumps(base))
        s=self.ledger().summary();self.assertEqual((s['count_requests'],s['max_count_requests'],s['count_capacity_remaining']),(395,395,0))
        with self.assertRaises(LanguageError) as c:self.ledger().reserve('test','sha256:'+'9'*64)
        self.assertEqual(c.exception.code,'count_ceiling_reached')
        good=strict_json(self.approval.read_bytes())
        for bad in (396,395.0,True,'395',0):
            with self.subTest(bad=bad):
                put(self.approval,dumps(dict(good,max_count_requests=bad)))
                with self.assertRaises(LanguageError):self.ledger().approval()

    def test_every_precondition_refusal_writes_nothing(self):
        for code,over in (('invalid_max_count_requests',{'max_count_requests':253}),('invalid_max_count_requests',{'max_count_requests':394}),
                          ('invalid_max_count_requests',{'max_count_requests':396}),('invalid_max_count_requests',{'max_count_requests':395.0}),
                          ('invalid_max_count_requests',{'max_count_requests':True}),('budget_pin_mismatch',{'expected_budget_sha256':'sha256:'+'0'*64}),
                          ('invalid_pin',{'catalog_digest':'nope'}),('invalid_transition_reference',{'transition_reference':' '}),
                          ('invalid_transition_reference',{'transition_reference':'SYNTHETIC-adoption-4'}),('root_required' if os.geteuid()!=0 else 'control_ancestor_unprotected',{'protected':True})):
            with self.subTest(code=code,over=over):self.refused(code,**over);self.assert_untouched()
        for reused in EARLIER:
            with self.subTest(reused=reused[:15]):self.refused('invalid_pin',active_config_hash=reused);self.assert_untouched()

    def test_wrong_approval_budget_or_record_bytes_refuse(self):
        a5=strict_json(self.h['approval5'])
        for raw in (dumps(dict(a5,max_count_requests=127)),dumps(dict(a5,adoption4_record_sha256='sha256:'+'6'*64)),self.h['approval5']+b' ',dumps(CP['approval4'])):
            with self.subTest(raw=raw[-40:]):
                put(self.approval,raw)
                with self.assertRaises((helper.AdoptionError,LanguageError,ValueError)):self.adopt()
                self.assertFalse(self.record5.exists())
        put(self.approval,self.h['approval5'])
        b=strict_json(self.h['budget']);b['entries'][7]['settled_estimate_nano_usd']+=1;put(self.budget,dumps(b))
        self.refused('budget_pin_mismatch');put(self.budget,self.h['budget'])
        for name,code in (('config-adoption.json','first_record_mismatch'),('config-adoption-2.json','second_record_mismatch'),
                          ('config-adoption-3.json','third_record_mismatch'),('config-adoption-4.json','fourth_record_mismatch')):
            with self.subTest(record=name):
                path=self.root/name;raw=path.read_bytes();put(path,raw+b' ')
                self.refused(code);put(path,raw);self.assertFalse(self.record5.exists())

    def test_halted_marker_refuses_and_partial_commit_halts_without_retry(self):
        self.halted.write_bytes(b'');self.refused('accounting_halted');self.halted.unlink()
        with patch.object(helper,'_publish_atomic',side_effect=OSError('approval storage fault')):self.refused('adoption_commit_uncertain_halted')
        self.assertTrue(self.halted.exists());self.assertTrue(self.record5.exists());self.assertEqual(self.approval.read_bytes(),self.h['approval5'])
        self.assert_history()
        self.refused('accounting_halted')  # no retry path while HALTED exists
        with self.assertRaises(LanguageError):self.ledger().reserve('test','sha256:'+'9'*64)
        self.halted.unlink();self.record5.unlink()
        def fault(*_a,**_k):self.uncreatable_marker();raise OSError('fault')
        with patch.object(helper,'_publish_atomic',side_effect=fault):self.refused('adoption_commit_uncertain_halt_unconfirmed')
        self.assertFalse(self.halted.exists());self.assert_history()

    def test_cli_exit_codes(self):
        argv=['--control-dir',str(self.root),'--active-config-hash',NEW,'--catalog-digest',NEW_CATALOG,'--transition-reference','root-go-adoption-5',
            '--source-component-sha256',PINS['source_component_sha256'],'--image-digest',PINS['image_digest'],'--review-receipt-sha256',PINS['review_receipt_sha256'],
            '--expected-budget-sha256',self.h['pins']['ADOPTION5_BUDGET_SHA256'],'--max-count-requests','395']
        buf=io.StringIO()
        with redirect_stdout(buf):code=helper.main(argv)  # the real CLI is protected: refusal before any financial read
        out=json.loads(buf.getvalue());self.assertEqual((code,out['status'],out['provider_calls']),(2,'refused',0));self.assert_untouched()
        real=helper.adopt5;buf=io.StringIO()
        with patch.object(helper,'adopt5',lambda *a,**k:real(*a,**dict(k,protected=False))),redirect_stdout(buf):code=helper.main(argv)
        out=json.loads(buf.getvalue());self.assertEqual((code,out['status'],out['count_capacity_remaining']),(0,'adopted',142))

if __name__=='__main__':unittest.main()
