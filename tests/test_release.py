"""Offline public-adapter checks. No network inference, secrets or ledgers."""
import concurrent.futures
import copy
from html import escape
import http.cookiejar
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_app import Application
from districtbrief.public_packet import PublicPacket as RuntimePacket, PUBLIC_SNAPSHOT_ID as RELEASE_SNAPSHOT_ID
from districtbrief.packet import ACCEPTED_SNAPSHOT_ID as SOURCE_SNAPSHOT_ID, PacketError
ACCEPTED_SNAPSHOT_ID = RELEASE_SNAPSHOT_ID  # requests bind the release packet, not the source snapshot
H001 = {'state_fips':'15','chamber':'house','code':'001','boundary_session':2024}
H009 = dict(H001,code='009')


class AdapterChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = Application(cls.tmp.name,secure_cookie=False)
        cls.port = None

    @classmethod
    def tearDownClass(cls):
        for handler in cls.app.service.metrics.handlers: handler.close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie='', **overrides):
        raw = json.dumps(body).encode() if body is not None else b''
        target, _, query = path.partition('?')
        env = {'REQUEST_METHOD':method,'PATH_INFO':target,'QUERY_STRING':query,
               'wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),
               'CONTENT_TYPE':'application/json','HTTP_HOST':'example.test','HTTP_COOKIE':cookie}
        env.update(overrides)
        headers=[]
        def respond(status,items): headers.extend([int(status.split()[0]),dict(items)])
        data=b''.join(self.app(env,respond))
        out=json.loads(data) if data and 'application/json' in headers[1]['Content-Type'] else data
        return headers[0],headers[1],out

    def session(self):
        code,headers,_=self.call('GET','/api/catalog')
        self.assertEqual(code,200)
        return headers['Set-Cookie'].split(';',1)[0]

    def req(self,rid='journey',**fields):
        return dict(request_id=rid,snapshot_id=ACCEPTED_SNAPSHOT_ID,input_mode='guided',task='profile',district=H001,**fields)

    def two(self,cookie,request):
        code,_,first=self.call('POST','/api/resolve',request,cookie)
        self.assertEqual(code,200,first)
        self.assertEqual(first['status'],'resolved',first)
        code,_,out=self.call('POST','/api/execute',{'request_id':request['request_id'],'snapshot_id':ACCEPTED_SNAPSHOT_ID},cookie)
        self.assertEqual(code,200,out)
        self.assertEqual(out['status'],'ok',out)
        self.assertEqual(out['model_calls'],0)
        return out

    def test_journey_sources_edits_and_export(self):
        cookie=self.session()
        prof=self.two(cookie,self.req('profile'))
        self.assertEqual(len(prof['findings']),20)
        for finding in prof['findings']:
            raw_label = finding['metric']['official_variable_label']
            self.assertIn('!!', raw_label)
            self.assertIn(escape(raw_label.replace('!!', ' › ')), prof['html'])
            self.assertNotIn(escape(raw_label), prof['html'])
        self.assertEqual(prof['findings'][8]['metric']['metric_id'],'poverty_rate_all_people')
        req=self.req('compare'); req.update(task='compare',metric_ids=['poverty_rate_all_people'],comparison_geography='HI-STATE-2024')
        cmp=self.two(cookie,req)
        self.assertEqual(cmp['findings'][0]['difference']['display'],'+2.5')
        req=self.req('program'); req.update(task='program_relevance',program_ids=['snap_hi'])
        prog=self.two(cookie,req)
        program = prog['findings'][0]['program']
        self.assertIn('Hawaiʻi DHS', prog['html'])
        self.assertIn('Hawaiʻi statewide', prog['html'])
        self.assertIn(f'<dt>Checked</dt><dd>{program["checked_at"][:10]}</dd>', prog['html'])
        self.assertNotIn(program['checked_at'], prog['html'])
        self.assertTrue(all(e.get('verification_kind') == 'authored_reference' and e['verified_against_extract'] is None for e in prog['findings'][0]['evidence']))
        source=prof['findings'][8]['source']; fid=prof['findings'][8]['finding_id']
        code,_,src=self.call('GET','/api/source?source_id='+source['source_id']+'&finding_id='+fid)
        self.assertEqual(code,200,src)
        self.assertFalse(src['result']['retained_file']['matches_source_manifest'])
        ids=[fid,cmp['findings'][0]['finding_id'],prog['findings'][0]['finding_id']]
        req=self.req('brief'); req.update(task='brief',selected_finding_ids=ids,edits={'title':'Visitor Private Title','note':'Visitor Private Note','finding_notes':{fid:'Visitor Private Finding Note'}})
        brief=self.two(cookie,req)
        self.assertEqual([e['finding_id'] for e in brief['data']['brief']['entries']],ids)
        self.assertIn('Staff edit — not a verified fact',brief['html'])
        self.assertIn('Visitor Private Note',brief['html'])
        self.assertIn('id="brief-doc"',brief['html'])
        self.assertIn('id="print-brief"',brief['html'])
        logs=(Path(self.tmp.name)/'metrics.jsonl').read_text()
        for private in ['Visitor Private','session_id','request_id','utterance',cookie]: self.assertNotIn(private,logs)
        req=self.req('selected'); req.update(metric_ids=['poverty_rate_all_people'])
        self.assertEqual(len(self.two(cookie,req)['findings']),1)

    def test_isolation_same_ids_and_references(self):
        a,b=self.session(),self.session()
        req=self.req('shared-id')
        self.assertEqual(self.call('POST','/api/resolve',req,a)[2]['status'],'resolved')
        self.assertEqual(self.call('POST','/api/execute',{'request_id':'shared-id','snapshot_id':ACCEPTED_SNAPSHOT_ID},b)[2]['status'],'error')
        breq=copy.deepcopy(req); breq['district']=H009
        self.assertEqual(self.call('POST','/api/resolve',breq,b)[2]['status'],'resolved')
        aout=self.call('POST','/api/execute',{'request_id':'shared-id','snapshot_id':ACCEPTED_SNAPSHOT_ID},a)[2]
        bout=self.call('POST','/api/execute',{'request_id':'shared-id','snapshot_id':ACCEPTED_SNAPSHOT_ID},b)[2]
        self.assertEqual(aout['resolution']['district']['code'],'001')
        self.assertEqual(bout['resolution']['district']['code'],'009')
        self.assertEqual(self.call('POST','/api/execute',{'request_id':'shared-id','snapshot_id':ACCEPTED_SNAPSHOT_ID},a)[2]['status'],'error')
        req=self.req('stolen-reference',result_reference=aout['result_reference'])
        res=self.two(b,req)
        self.assertEqual(res['context_provenance'],{'kind':'client_carried','reason':'session_mismatch'})
        req=self.req('owned-reference',result_reference=aout['result_reference'])
        self.assertEqual(self.two(a,req)['context_provenance']['kind'],'server_issued_in_process')
        # Edits are request/browser-owned. A second session receives no first-session note.
        req=self.req('other-brief'); req.update(task='brief',selected_finding_ids=[aout['findings'][0]['finding_id']])
        self.assertNotIn('Visitor Private Note',self.two(b,req)['html'])

    def test_docs_page_is_public_and_linked_from_home(self):
        for path in ('/docs', '/docs/'):
            status, headers, body=self.call('GET',path)
            self.assertEqual(status,200)
            self.assertEqual(headers['Content-Type'],'text/html; charset=utf-8')
            self.assertNotIn('Set-Cookie',headers)
            self.assertIn(b'https://haic.millrace.ai/mcp',body)
            self.assertEqual(self.call('HEAD',path)[2],b'')
        self.assertIn(b'href="/docs"',self.call('GET','/')[2])
        self.assertEqual(self.call('GET','/static/docs.html')[0],404)

    def test_limits_routes_and_json(self):
        cookie=self.session()
        self.assertEqual(self.call('POST','/api/resolve',self.req(),cookie,CONTENT_LENGTH='65537')[0],413)
        self.assertEqual(self.call('POST','/api/resolve',self.req(),cookie,CONTENT_LENGTH='')[0],411)
        self.assertEqual(self.call('POST','/api/resolve',self.req(),cookie,CONTENT_TYPE='text/plain')[0],415)
        self.assertEqual(self.call('POST','/api/resolve',self.req(),cookie,HTTP_ORIGIN='https://evil.test')[0],403)
        self.assertEqual(self.call('POST','/api/resolve',self.req())[0],403)
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":"\\ud800"}', b'{}x']:
            self.assertEqual(self.call('POST','/api/resolve',None,cookie,**{'wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw))})[0],400)
        for path in ['/api/run','/api/c/runtime','/api/hosted/cancel','/runtime-packet/PACKET-MANIFEST.json','/static/../public_app.py','/static/c-runtime.js','/.git/config','/metrics.jsonl']:
            self.assertEqual(self.call('GET',path)[0],404,path)
        self.assertEqual(self.call('DELETE','/api/catalog')[0],405)
        code,h,body=self.call('HEAD','/')
        self.assertEqual(code,200);self.assertEqual(body,b'')
        self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy'])
        self.assertNotIn('Strict-Transport-Security',h)
        self.assertIn('HttpOnly',h['Set-Cookie'])
        req=self.req('duplicate')
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[0],200)
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[0],409)

    def test_validation_work_and_error_response_stay_bounded(self):
        cookie=self.session()
        for items in ([f'm{i:04}' for i in range(4000)], [0]*10000):
            req=self.req('oversized-list',metric_ids=items)
            self.assertLess(len(json.dumps(req).encode()),65536)
            code,headers,out=self.call('POST','/api/resolve',req,cookie)
            self.assertEqual(code,400)
            self.assertEqual(len(out['validation_errors']),1)
            self.assertEqual(out['validation_errors'][0]['field'],'metric_ids')
            self.assertLess(int(headers['Content-Length']),4096)
        req=self.req('many-errors',metric_ids=[0]*20,program_ids=[0]*5,
                     observation_ids=[0]*8,selected_finding_ids=[0]*40,
                     displayed_context={'metric_ids':[0]*20,'program_ids':[0]*5,'observation_ids':[0]*8})
        code,headers,out=self.call('POST','/api/resolve',req,cookie)
        self.assertEqual(code,400)
        self.assertEqual(len(out['validation_errors']),32)
        self.assertLess(int(headers['Content-Length']),12000)
        req=self.req('long-error',edits={'finding_notes':{'x'*10000:'note'}})
        code,headers,out=self.call('POST','/api/resolve',req,cookie)
        self.assertEqual(code,400)
        self.assertLess(int(headers['Content-Length']),4096)
        from districtbrief.contract import validate_request
        req=self.req('ordered-list',metric_ids=['population_65_plus','median_age','population_65_plus'])
        normalized,errors=validate_request(req,ACCEPTED_SNAPSHOT_ID)
        self.assertEqual(errors,[])
        self.assertEqual(normalized['metric_ids'],['population_65_plus','median_age'])

    def test_every_catalog_source_and_statistic_cell(self):
        catalog=self.call('GET','/api/catalog')[2]
        from urllib.parse import urlencode
        for source in catalog['sources']:
            code,_,out=self.call('GET','/api/source?'+urlencode({'source_id':source['source_id']}))
            self.assertEqual((code,out['status']),(200,'ok'),source['source_id'])
            self.assertIn(out['result']['retained_file']['verification_scope'], ('normalized_projection','bundled_original_bytes'))
        for row in catalog['observations']:
            code,_,out=self.call('GET','/api/source?'+urlencode({'source_id':row['source_id'],'finding_id':row['finding_id']}))
            self.assertEqual((code,out['status']),(200,'ok'),row['finding_id'])
            self.assertIs(out['result']['detail']['cell_verified'],False,row['finding_id'])
        for sid in ['../metrics.jsonl','/etc/passwd','a.b','bad-id','https://example.com','x'*65,'acs_2024_dp02_metadata','c-hosted-config.example.json']:
            code,_,out=self.call('GET','/api/source?'+urlencode({'source_id':sid}))
            self.assertIn(code,(400,404),sid)
            self.assertNotEqual(out['status'],'ok')

    def test_sources_distinguish_reports_captures_and_count_sources(self):
        catalog = self.call('GET', '/api/catalog')[2]
        captures = {
            'hi_mqd_reports': ('reports.html', 'redirected from .html'),
            'hi_mqd_reports_canonical': ('reports', 'direct address'),
        }
        for source_id, (path, descriptor) in captures.items():
            with self.subTest(source=source_id):
                _, _, inspection = self.call('GET', f'/api/source?source_id={source_id}')
                result = inspection['result']
                self.assertEqual(result['source']['url'], f'https://medquest.hawaii.gov/en/resources/{path}')
                self.assertEqual(result['cited_by']['participation'], [])
                label = f'Med-QUEST reports page ({descriptor})'
                self.assertIn(label, catalog['sources_html'])
                self.assertIn(label, inspection['html'])
                self.assertIn('Reference only. The app uses no administrative counts', inspection['html'])
        _, _, inspection = self.call('GET', '/api/source?source_id=hi_snap_sfy2027')
        self.assertEqual(len(inspection['result']['cited_by']['participation']), 7)
        self.assertIn('The app uses 7 administrative rows from this source.', inspection['html'])
        self.assertIn('district participation gap', inspection['html'])

    def test_cookie_extraction_signatures_and_session_refresh(self):
        cookie=self.session()
        name,token=cookie.split('=',1)
        # An unrelated malformed parent-domain cookie precedes the exact session.
        for parent in ['parent="unterminated', 'parent=bad value', 'parent={bad}', 'other=plain']:
            code,_,out=self.call('POST','/api/resolve',self.req('parent-'+str(len(parent))),parent+'; '+cookie)
            self.assertEqual((code,out['status']),(200,'resolved'),parent)
        bad_tokens=[token[:-1]+('0' if token[-1]!='0' else '1'),token.rsplit('.',1)[0]+'.é', '"'+token.rsplit('.',1)[0]+'.é"', 'forged', token.upper()]
        for bad in bad_tokens:
            code,headers,out=self.call('POST','/api/resolve',self.req('bad-cookie'),name+'='+bad)
            self.assertEqual(code,403,bad)
            self.assertEqual(out['reason'],'Your session was refreshed. Press Run again; your selections are kept.')
            fresh=headers['Set-Cookie'].split(';',1)[0]
            code,_,out=self.call('POST','/api/resolve',self.req('retry-'+str(len(bad))),fresh)
            self.assertEqual((code,out['status']),(200,'resolved'))
        for header in [cookie+'; '+cookie, name+'=forged; '+cookie, cookie+'; '+name, cookie+'; '+name+' =forged', 'prefix'+cookie]:
            self.assertEqual(self.call('POST','/api/resolve',self.req('duplicate-cookie'),header)[0],403)
        import hashlib,hmac
        expired=str(int(time.time())-43201)+'.'+'a'*64
        expired+='.'+hmac.new(self.app.secret,expired.encode(),hashlib.sha256).hexdigest()
        self.assertEqual(self.call('POST','/api/resolve',self.req('expired'),name+'='+expired)[0],403)
        code,_,out=self.call('GET','/api/source?a=1&b=2&c=3&d=4&e=5')
        self.assertEqual(code,400)
        self.assertIn('at most four',out['reason'])
        self.assertNotIn('internal_error',(Path(self.tmp.name)/'metrics.jsonl').read_text())

    def test_secure_host_cookie_and_restart_recovery(self):
        old=self.app
        with tempfile.TemporaryDirectory() as state:
            self.app=Application(state,secure_cookie=True)
            try:
                cookie=self.session()
                self.assertTrue(cookie.startswith('__Host-haic_session='))
                _,headers,_=self.call('GET','/')
                self.assertIn('; Secure',headers['Set-Cookie'])
                self.assertIn('; HttpOnly',headers['Set-Cookie'])
                self.assertIn('; SameSite=Strict',headers['Set-Cookie'])
                self.assertEqual(headers['Strict-Transport-Security'],'max-age=31536000')
                self.assertIn('; Path=/',headers['Set-Cookie'])
                self.assertNotIn('Domain=',headers['Set-Cookie'])
                # A worker restart rotates the secret. The new cookie allows retry.
                self.app.secret=b'new-worker-secret-for-offline-test'
                code,headers,out=self.call('POST','/api/resolve',self.req('restarted'),cookie)
                self.assertEqual(code,403)
                fresh=headers['Set-Cookie'].split(';',1)[0]
                self.assertEqual(self.call('POST','/api/resolve',self.req('restarted'),fresh)[2]['status'],'resolved')
            finally:
                for handler in self.app.service.metrics.handlers: handler.close()
                self.app=old

    def test_runtime_has_no_provider_imports(self):
        banned=('districtbrief.b_provider','districtbrief.hosted_provider','districtbrief.route_b','districtbrief.route_c','districtbrief.route_hosted','onnxruntime','torch')
        self.assertFalse(any(x in sys.modules for x in banned))
        self.assertEqual(self.app.service.variant,'A')
        self.assertEqual(self.app.service.core.packet.verification['verification_scope'],'publication_normalized_facts')
        for name in ('route_a','resolve','contract','geography','xlsx','packet'):  # core/render carry statewide copy
            baseline_root=os.environ.get('HAIC_BASELINE_APP')
            if baseline_root:
                baseline=Path(baseline_root)/'districtbrief'/(name+'.py')
                self.assertEqual((ROOT/'districtbrief'/(name+'.py')).read_bytes(),baseline.read_bytes())


class StatewideChecks(AdapterChecks):
    """All 51 House and 25 Senate districts through the public adapter."""
    DISTRICTS=[('house',n) for n in range(1,52)]+[('senate',n) for n in range(1,26)]

    def district(self,chamber,number):
        return {'state_fips':'15','chamber':chamber,'code':f'{number:03}','boundary_session':2024}

    def run_task(self,cookie,rid,chamber,number,**fields):
        req=dict(request_id=rid,snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='guided',district=self.district(chamber,number),**fields)
        return self.two(cookie,req)

    def test_release_identity_and_regeneration(self):
        v=self.app.service.core.packet.verification
        self.assertNotEqual(RELEASE_SNAPSHOT_ID,SOURCE_SNAPSHOT_ID)
        self.assertEqual(v['snapshot_id'], RELEASE_SNAPSHOT_ID)
        self.assertEqual(v['verification_scope'], 'publication_normalized_facts')
        self.assertFalse(v['full_r2_archive_verified'])
        health=self.call('GET','/healthz')[2]
        self.assertEqual(health['snapshot_id'], RELEASE_SNAPSHOT_ID)
        cookie=self.session()
        stale=dict(request_id='stale',snapshot_id=SOURCE_SNAPSHOT_ID,input_mode='guided',task='profile',district=H001)
        self.assertEqual(self.call('POST','/api/resolve',stale,cookie)[0],400)

    def test_altered_or_extra_packet_files_fail_startup(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir=Path(tmp)/'runtime-packet'
            shutil.copytree(ROOT/'runtime-packet',copy_dir)
            RuntimePacket(copy_dir)
            target=copy_dir/'data/statistics/observations.json'
            original=target.read_bytes()
            target.write_bytes(original+b' ')
            with self.assertRaises(PacketError): RuntimePacket(copy_dir)
            target.write_bytes(original)
            raw=copy_dir/'data/geography/raw/2024_house.geojson'
            raw.write_bytes(raw.read_bytes()+b'x')
            with self.assertRaises(PacketError): RuntimePacket(copy_dir)
            raw.write_bytes(raw.read_bytes()[:-1])
            (copy_dir/'data/extra.json').write_text('{}')
            with self.assertRaises(PacketError): RuntimePacket(copy_dir)

    def test_catalog_lists_all_districts(self):
        cat=self.call('GET','/api/catalog')[2]
        with_stats={(d['chamber'],d['code']) for d in cat['districts'] if d['boundary_session']==2024 and d['has_statistics']}
        self.assertEqual(with_stats,{(c,f'{n:03}') for c,n in self.DISTRICTS})
        self.assertEqual(cat['coverage']['statistics_observations'],1640)
        self.assertEqual(cat['coverage']['statistics_geographies'],82)
        self.assertEqual({g['observation_count'] for g in cat['geographies']},{20})
        self.assertEqual([g['geography_id'] for g in cat['geographies'][:2]],['HI-STATE-2024','HI-COUNTY-009-2024'])
        self.assertTrue(all(d['approx_county'] is None for d in cat['districts']))
        self.assertIn('normalized district and county profiles',' '.join(cat['limitations']))
        self.assertNotIn('Only five geographies',json.dumps(cat))

    def test_every_district_full_profile(self):
        cookie=self.session()
        metrics=[m['metric_id'] for m in self.call('GET','/api/catalog')[2]['metrics']]
        self.assertEqual(len(metrics),20)
        seen={}; annotated=[]
        for chamber,number in self.DISTRICTS:
            code=f'{number:03}'
            out=self.run_task(cookie,f'p-{chamber}-{code}',chamber,number,task='profile')
            self.assertEqual([f['metric']['metric_id'] for f in out['findings']],metrics,(chamber,code))
            self.assertEqual(out['data']['identity']['geoid'],'15'+code)
            self.assertEqual(out['data']['coverage']['missing_estimates'],[])
            for f in out['findings']:
                g=f['geography']
                self.assertEqual((g['chamber'],g['district_code'],g['boundary_session'],g['geoid']),(chamber,code,2024,'15'+code))
                self.assertEqual(g['source_name'],f'State {chamber.capitalize()} District {number} (2024); Hawaii')
                self.assertEqual(f['source']['source_id'],'dbedt_2024_'+chamber)
                self.assertIsInstance(f['estimate'],float); self.assertIsNone(f['annotation'])
                self.assertEqual(f['moe_confidence_level'],0.9)
                self.assertEqual((f['period']['start_year'],f['period']['end_year']),(2020,2024))
                self.assertTrue(f['universe'] and f['unit'] and f['estimate_display'])
                if f['finding_id']=='stat:HI-SENATE-008-2024:total_population':
                    # The one district annotation in the workbooks: a controlled estimate has no sampling MOE.
                    self.assertEqual((f['margin_of_error'],f['moe_display'],f['moe_annotation']),(None,'*****','*****'))
                    self.assertIn('Sampling variability does not apply',f['annotation_meaning'])
                    self.assertIn('controlled estimate; no numeric margin of error published',f['text'])
                    self.assertNotIn('*****',f['text'])
                    self.assertNotIn('with published 90% margins of error',' '.join(f['limitations']))
                    annotated.append(f['finding_id'])
                else:
                    self.assertIsInstance(f['margin_of_error'],float); self.assertIsNone(f['moe_annotation'])
                    self.assertTrue(f['moe_display'].startswith('±'))
                loc=f['source']['locator']
                self.assertTrue(all(loc[k] for k in ('sheet','label_cell','geography_cell','estimate_cell','moe_cell')))
            seen[(chamber,code)]=[(f['estimate_display'],f['source']['locator']['estimate_cell']) for f in out['findings']]
        self.assertEqual(len(seen),76)
        self.assertEqual(annotated,['stat:HI-SENATE-008-2024:total_population'])
        # The same numeric code names different districts in each chamber.
        for number in range(1,26):
            self.assertNotEqual(seen[('house',f'{number:03}')],seen[('senate',f'{number:03}')],number)
        for chamber,number in [('house',52),('senate',26),('house',0)]:
            req=dict(request_id=f'none-{chamber}-{number}',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='guided',task='profile',district=self.district(chamber,number))
            self.assertEqual(self.call('POST','/api/resolve',req,cookie)[2]['status'],'unsupported')

    def test_last_districts_cross_chamber_compare_program_outreach_brief(self):
        from decimal import Decimal
        cookie=self.session()
        obs={o['observation_id']:o for o in json.loads((ROOT/'runtime-packet/data/statistics/observations.json').read_text())['observations']}
        def raw(pid,mid): return Decimal(obs[pid+':'+mid]['raw_cells']['estimate'].replace(',','').replace('%',''))
        for mid in ('poverty_rate_all_people','median_household_income','median_gross_rent','median_age'):
            cmp=self.run_task(cookie,'x-'+mid,'house',51,task='compare',metric_ids=[mid],comparison_geography='HI-SENATE-025-2024')['findings'][0]
            want=raw('HI-HOUSE-051-2024',mid)-raw('HI-SENATE-025-2024',mid)
            self.assertEqual(Decimal(str(cmp['difference']['value'])),want,mid)
            self.assertEqual(cmp['difference']['direction'],'higher' if want>0 else 'lower' if want<0 else 'equal')
            self.assertTrue(all(cmp['compatibility']['checks'].values()))
            self.assertTrue(any('overlap' in l for l in cmp['limitations']))
            back=self.run_task(cookie,'y-'+mid,'senate',25,task='compare',metric_ids=[mid],comparison_geography='HI-HOUSE-051-2024')['findings'][0]
            self.assertEqual(Decimal(str(back['difference']['value'])),-want,mid)
        count=self.run_task(cookie,'count','senate',25,task='compare',metric_ids=['total_population'],comparison_geography='HI-STATE-2024')['findings'][0]
        self.assertIsNone(count['difference']); self.assertTrue(count['not_differenced_reason'])
        maui=self.run_task(cookie,'maui','house',13,task='compare',metric_ids=['unemployment_rate'],comparison_geography='HI-COUNTY-009-2024')['findings'][0]
        self.assertEqual(maui['right']['geography']['label'],'Maui County')
        req=dict(request_id='kauai',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='guided',task='compare',district=self.district('house',16),metric_ids=['median_age'],comparison_geography='HI-COUNTY-007-2024')
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[2]['status'],'resolved')
        out=self.call('POST','/api/execute',{'request_id':'kauai','snapshot_id':RELEASE_SNAPSHOT_ID},cookie)[2]
        self.assertEqual(out['status'],'ok'); self.assertEqual(out['findings'][0]['right']['geography']['label'],'Kauai County')
        # Program relevance and outreach keep regional and eligibility limits for new districts.
        prog=self.run_task(cookie,'prog','senate',25,task='program_relevance',program_ids=['snap_hi'])['findings'][0]
        self.assertTrue(prog['informational_only']); self.assertTrue(all(e.get('verification_kind') == 'authored_reference' and e['verified_against_extract'] is None for e in prog['evidence']))
        self.assertTrue(all(r['district_gap_usable'] is False for r in prog['participation_context']))
        self.assertTrue(any('eligibility' in l for l in prog['limitations']) and any('participation gap' in l for l in prog['limitations']))
        lead=self.run_task(cookie,'lead','senate',25,task='outreach',program_ids=['snap_hi'])['findings'][0]
        self.assertTrue(lead['hypothesis']); self.assertIn('not a measured gap or eligibility finding',lead['text'])
        self.assertEqual(lead['geography']['geography_id'],'HI-SENATE-025-2024')
        hcv=self.run_task(cookie,'hcv-in','house',51,task='program_relevance',program_ids=['hcv_honolulu'])['findings'][0]
        self.assertIsNone(hcv['jurisdiction_check']['in_agency_area'])
        away=self.run_task(cookie,'hcv-out','house',16,task='program_relevance',program_ids=['hcv_honolulu'])['findings'][0]
        self.assertIsNone(away['jurisdiction_check']['in_agency_area']); self.assertIsNone(away['geography']['approx_county'])
        req=dict(request_id='hcv-lead',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='guided',task='outreach',district=self.district('house',16),program_ids=['hcv_honolulu'])
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[2]['status'],'resolved')
        self.assertEqual(self.call('POST','/api/execute',{'request_id':'hcv-lead','snapshot_id':RELEASE_SNAPSHOT_ID},cookie)[2]['status'],'unsupported')
        kupuna=self.run_task(cookie,'kupuna','house',16,task='program_relevance',program_ids=['kupuna_care_hi'])['findings'][0]
        self.assertIsNone(kupuna['referral']['county_office']); self.assertEqual(kupuna['referral']['phone'],'808-586-0100')
        # Brief for a last district: statistic, cross-chamber comparison, outreach hypothesis, labeled staff edits.
        stat='stat:HI-SENATE-025-2024:median_gross_rent'
        ids=[stat,'cmp:HI-SENATE-025-2024~HI-HOUSE-051-2024:poverty_rate_all_people',lead['finding_id']]
        brief=self.run_task(cookie,'brief','senate',25,task='brief',selected_finding_ids=ids,edits={'title':'Senate 25 staff title','note':'Staff note text','finding_notes':{stat:'Staff finding note'}})
        doc=brief['data']['brief']
        self.assertEqual([e['finding_id'] for e in doc['entries']],ids)
        self.assertLessEqual(doc['print_units'],doc['print_budget'])
        self.assertEqual({c['source_id'] for c in doc['citations']}>={'dbedt_2024_senate','dbedt_2024_house','dbedt_2024_state'},True)
        for text in ('Staff edit — not a verified fact','Senate 25 staff title','Staff finding note','id="print-brief"','Senate District 025'): self.assertIn(text,brief['html'])
        foreign=dict(request_id='foreign',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='guided',task='brief',district=self.district('senate',25),selected_finding_ids=['stat:HI-HOUSE-051-2024:median_age'])
        self.assertEqual(self.call('POST','/api/resolve',foreign,cookie)[2]['status'],'resolved')
        self.assertEqual(self.call('POST','/api/execute',{'request_id':'foreign','snapshot_id':RELEASE_SNAPSHOT_ID},cookie)[2]['status'],'unsupported')

    def test_typed_commands_reach_new_districts(self):
        cookie=self.session()
        for rid,text,code,chamber in [('t1','profile house 51','051','house'),('t2','show profile for senate 25','025','senate')]:
            req=dict(request_id=rid,snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='language',utterance=text)
            first=self.call('POST','/api/resolve',req,cookie)[2]
            self.assertEqual(first['status'],'resolved',first)
            out=self.call('POST','/api/execute',{'request_id':rid,'snapshot_id':RELEASE_SNAPSHOT_ID},cookie)[2]
            self.assertEqual((out['status'],out['resolution']['district']['chamber'],out['resolution']['district']['code'],len(out['findings'])),('ok',chamber,code,20))
        req=dict(request_id='t3',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='language',utterance='compare median gross rent with senate 25 for house 51')
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[2]['status'],'resolved')
        out=self.call('POST','/api/execute',{'request_id':'t3','snapshot_id':RELEASE_SNAPSHOT_ID},cookie)[2]
        self.assertEqual(out['findings'][0]['finding_id'],'cmp:HI-HOUSE-051-2024~HI-SENATE-025-2024:median_gross_rent')
        req=dict(request_id='t4',snapshot_id=RELEASE_SNAPSHOT_ID,input_mode='language',utterance='profile 25')
        self.assertEqual(self.call('POST','/api/resolve',req,cookie)[2]['status'],'clarification')


# The statewide class reuses the adapter helpers; the inherited pilot checks run once, above.
for _name in [n for n in dir(AdapterChecks) if n.startswith('test_')]:
    setattr(StatewideChecks,_name,None)


class ProductionChecks(unittest.TestCase):
    def test_gunicorn_http_and_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
            env=dict(os.environ,PORT=str(port),HAIC_STATE_DIR=tmp,HAIC_LOCAL_HTTP='1',PYTHONDONTWRITEBYTECODE='1')
            proc=subprocess.Popen([sys.executable,'-m','gunicorn','--config','gunicorn.conf.py','wsgi:application'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                base=f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(base+'/healthz',timeout=1) as resp: self.assertEqual(json.load(resp)['status'],'ok')
                        break
                    except OSError: time.sleep(.1)
                else: self.fail('Gunicorn failed startup')
                a=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                b=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                for browser in [a,b]: browser.open(base+'/api/catalog',timeout=5).close()
                def post(browser,path,body):
                    req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    with browser.open(req,timeout=5) as resp:return json.load(resp)
                req={'request_id':'same','snapshot_id':ACCEPTED_SNAPSHOT_ID,'input_mode':'guided','task':'profile','district':H001}
                self.assertEqual(post(a,'/api/resolve',req)['status'],'resolved')
                self.assertEqual(post(b,'/api/execute',{'request_id':'same','snapshot_id':ACCEPTED_SNAPSHOT_ID})['status'],'error')
                self.assertEqual(post(a,'/api/execute',{'request_id':'same','snapshot_id':ACCEPTED_SNAPSHOT_ID})['status'],'ok')
                oversized=urllib.request.Request(base+'/api/resolve',data=b'x'*65537,headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:a.open(oversized,timeout=5)
                self.assertEqual(caught.exception.code,413)
            finally:
                proc.terminate()
                _,err=proc.communicate(timeout=10)
                self.assertEqual(proc.returncode,0,err.decode())


if __name__=='__main__':unittest.main(verbosity=2)
