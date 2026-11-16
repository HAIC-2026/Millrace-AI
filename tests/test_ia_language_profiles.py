"""Model profiles are validated DATA chosen only by protected operator configuration."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps, prepare_request
from districtbrief.ia_language_profiles import PROFILES_PATH, load_profile, load_profiles, parse_profiles
from districtbrief.ia_language_provider import OpenAIProvider, configuration_hash, provider_payload
from language_funding_fixture import PROFILE, SOL, ledger_fixture, bound, usage
import test_ia_language_contract as contract_fixtures

def data():return json.loads(PROFILES_PATH.read_text())

class ProfileDataTests(unittest.TestCase):
    def test_current_profiles_rates_caps_efforts_and_expected_identity(self):
        profiles=load_profiles();self.assertEqual(sorted(profiles),['sol-low','terra-high','terra-medium'])  # repair-1 v2: terra-high data added
        t,s=profiles['terra-medium'],profiles['sol-low']
        self.assertEqual((t.model,t.reasoning_effort,t.service_tier),('gpt-6.1-terra','medium','default'))
        self.assertEqual((s.model,s.reasoning_effort,s.service_tier),('gpt-6.1-sol','low','default'))
        # Official Standard short-context USD per 1M tokens (D/docs/api-pricing.md): 1 nano-USD/token = $0.001/M.
        self.assertEqual(t.rates,{'uncached_input':1000,'cached_input':50,'cache_write_30m':1250,'output':5000})
        self.assertEqual(s.rates,{'uncached_input':2000,'cached_input':100,'cache_write_30m':2500,'output':10000})
        for p in (t,s):
            self.assertEqual((p.max_input_tokens,p.max_output_tokens),(12288,2048))
            self.assertEqual((p.expected_model,p.expected_service_tier,p.expected_reasoning_effort),(p.model,'default',p.reasoning_effort))
        d=data()['models']
        self.assertEqual(d['gpt-6.1-terra']['supported_reasoning_efforts'],['none','low','medium','high','xhigh','max'])
        self.assertEqual(d['gpt-6.1-sol']['supported_reasoning_efforts'],['low','medium','high','xhigh','max'])
        self.assertTrue(all(m['processing']=='standard' and m['api']=='responses' and m['provider']=='openai' for m in d.values()))
    def test_new_profile_is_data_not_code(self):
        d=data();d['profiles']['sol-medium']=dict(copy.deepcopy(d['profiles']['sol-low']),reasoning_effort='medium',
            expected_response={'model':'gpt-6.1-sol','service_tier':'default','reasoning_effort':'medium'})
        extra=parse_profiles(dumps(d))['sol-medium']
        self.assertEqual((extra.model,extra.reasoning_effort),('gpt-6.1-sol','medium'))
        self.assertNotIn(extra.profile_hash,{PROFILE.profile_hash,SOL.profile_hash})
        self.assertEqual(parse_profiles(dumps(d))['sol-low'],SOL)  # other profiles' identity unchanged
    def test_invalid_profile_data_fails_closed(self):
        def mutate(f):
            d=data();f(d);return dumps(d)
        bad=[lambda d:d['profiles']['sol-low'].update(reasoning_effort='none',expected_response=dict(d['profiles']['sol-low']['expected_response'],reasoning_effort='none')),
             lambda d:d['profiles']['sol-low'].update(reasoning_effort='minimal'),
             lambda d:d['profiles']['sol-low'].update(service_tier='priority'),
             lambda d:d['profiles']['sol-low']['expected_response'].update(service_tier='flex'),
             lambda d:d['profiles']['sol-low']['expected_response'].update(reasoning_effort='medium'),
             lambda d:d['profiles']['sol-low']['expected_response'].update(model='gpt-6.1-terra'),  # cross-model acceptance
             lambda d:d['profiles']['terra-medium']['expected_response'].update(model='gpt-6.1-sol'),
             lambda d:d['profiles']['sol-low']['expected_response'].update(model='gpt-6.1-sol-2026-11-01'),
             lambda d:d['models']['gpt-6.1-sol'].update(processing='fast'),
             lambda d:d['models']['gpt-6.1-sol'].update(processing='regional'),
             lambda d:d['models']['gpt-6.1-sol'].update(api='chat_completions'),
             lambda d:d['models']['gpt-6.1-sol'].update(provider='other'),
             lambda d:d['models']['gpt-6.1-sol']['rates_nano_usd_per_token'].update(output=True),
             lambda d:d['models']['gpt-6.1-sol']['rates_nano_usd_per_token'].update(output=0),
             lambda d:d['models']['gpt-6.1-sol']['rates_nano_usd_per_token'].pop('cached_input'),
             lambda d:d['profiles']['sol-low'].update(max_input_tokens=272001),
             lambda d:d['profiles']['sol-low'].update(max_output_tokens=2048.0),
             lambda d:d['profiles']['sol-low'].update(model='gpt-6-astra'),
             lambda d:d['profiles']['sol-low'].update(notes='x'),
             lambda d:d['profiles'].update({'Bad Id':d['profiles']['sol-low']}),
             lambda d:d.update(schema_version='ia-language-profiles/2')]
        for i,f in enumerate(bad):
            with self.subTest(i=i):
                with self.assertRaises(LanguageError) as e:parse_profiles(mutate(f))
                self.assertEqual(e.exception.code,'profile_unavailable')
        raw=PROFILES_PATH.read_bytes()
        with self.assertRaises(LanguageError):parse_profiles(raw.replace(b'"profiles": {',b'"profiles": {"terra-medium": {}, ',1))  # duplicate key
        for name in ('sol-high',None,'',1):
            with self.assertRaises(LanguageError):load_profile(name)
    def test_profile_hash_binds_rates_and_ignores_formatting(self):
        d=data();self.assertEqual(parse_profiles(json.dumps(d).encode())['sol-low'].profile_hash,SOL.profile_hash)
        d['models']['gpt-6.1-sol']['rates_nano_usd_per_token']['output']=10001
        self.assertNotEqual(parse_profiles(dumps(d))['sol-low'].profile_hash,SOL.profile_hash)
        self.assertEqual(parse_profiles(dumps(d))['terra-medium'].profile_hash,PROFILE.profile_hash)
    def test_config_hash_binds_profile_data_bytes(self):
        # Profile data is one of the hashed language components, so any data edit changes every config hash.
        from districtbrief import ia_language_provider
        catalog='sha256:'+'c'*64;before=configuration_hash(catalog,PROFILE)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in ('ia_language.py','ia_language_provider.py','ia_language_jobs.py','ia_language_funding.py','ia_language_accounting.py','ia_language_profiles.py','ia_language_profiles.json'):
                (root/n).write_bytes(PROFILES_PATH.with_name(n).read_bytes())
            (root/'ia_language_profiles.json').write_bytes(PROFILES_PATH.read_bytes()+b'\n')
            with patch.object(ia_language_provider,'__file__',str(root/'ia_language_provider.py')):
                self.assertNotEqual(configuration_hash(catalog,PROFILE),before)

class ProfileSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from public_app import load_core
        from districtbrief.investigation import Investigation
        cls.i=Investigation(load_core())
    def app(self,env):
        import public_app
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.dict(os.environ,env,clear=False):
            for k in ('HAIC_LANGUAGE_ENABLED','HAIC_LANGUAGE_PROFILE'):
                if k not in env:os.environ.pop(k,None)
            a=public_app.Application(tmp.name,secure_cookie=False)
        self.addCleanup(lambda:[h.close() for h in a.service.metrics.handlers])
        return a
    def health(self,a):
        out=[]
        body=a({'REQUEST_METHOD':'GET','PATH_INFO':'/api/health'},lambda s,h:out.append(s))
        return json.loads(b''.join(body))
    def test_operator_env_selects_profile_and_health_reports_it_without_spending(self):
        with patch('districtbrief.ia_language_provider.read_secret',side_effect=AssertionError('secret')),\
                patch('districtbrief.ia_language_funding.FundingLedger.approval',side_effect=AssertionError('ledger')):
            a=self.app({'HAIC_LANGUAGE_ENABLED':'1','HAIC_LANGUAGE_PROFILE':'terra-medium'})
            h=self.health(a)
        self.assertTrue(h['language']['enabled']);self.assertEqual(h['model_calls'],0)
        lp=h['language_profile'];self.assertEqual({k:lp[k] for k in ('profile_id','model','reasoning_effort','service_tier','profile_hash')},PROFILE.public_identity())
        self.assertEqual(lp['active_config_hash'],configuration_hash(lp['catalog_digest'],PROFILE))
        self.assertNotIn('rates',json.dumps(h));self.assertNotIn('limit_nano_usd',json.dumps(h))
        disabled=self.health(self.app({}));self.assertFalse(disabled['language']['enabled']);self.assertIsNone(disabled['language_profile'])
    def test_metrics_rows_never_claim_model_call_counts(self):
        import pathlib
        a=self.app({'HAIC_LANGUAGE_ENABLED':'1','HAIC_LANGUAGE_PROFILE':'terra-medium'})
        a.service._log('events.jsonl',{'phase':'resolve','status':'ok','model_calls':7})  # a supplied count is never copied
        a.service._log('errors.jsonl',{'model_calls':0})
        rows=[json.loads(x) for x in (pathlib.Path(a.service.metrics.handlers[0].baseFilename)).read_text().splitlines()]
        self.assertEqual(len(rows),2)
        for r in rows:
            self.assertNotIn('model_calls',r);self.assertEqual(r['model_calls_authority'],'funding_ledger')
    def test_missing_or_unknown_profile_fails_startup_closed(self):
        with self.assertRaises(ValueError):self.app({'HAIC_LANGUAGE_ENABLED':'1'})
        with self.assertRaises(LanguageError):self.app({'HAIC_LANGUAGE_ENABLED':'1','HAIC_LANGUAGE_PROFILE':'sol-medium'})
        # A profile name without the enable flag never enables language.
        self.assertFalse(self.health(self.app({'HAIC_LANGUAGE_PROFILE':'sol-low'}))['language']['enabled'])
    def test_client_cannot_choose_profile(self):
        from districtbrief.ia_language_jobs import LanguageService
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);ledger=ledger_fixture(tmp.name)
        calls=[]
        provider=OpenAIProvider(transport=lambda *a:calls.append(a),secret_reader=lambda:calls.append('secret'))
        service=LanguageService(self.i,enabled=True,ledger=ledger,provider=provider);self.addCleanup(service.close)
        h=contract_fixtures.LanguageContractTests();h.i=self.i;raw=h.request();raw['profile']='sol-low'
        code,out=service.handle('start',raw,'s')
        self.assertNotEqual(code,202);self.assertEqual(out['model_calls'],0);self.assertEqual(calls,[])
        raw=h.request();raw['context']['profile']='sol-low'
        code,out=service.handle('start',raw,'s');self.assertNotEqual(code,202);self.assertEqual(calls,[])
        self.assertEqual(ledger.summary()['buckets']['demo']['entries'],0)

if __name__=='__main__':unittest.main()
