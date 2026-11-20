"""Catalog pagination and startup-recovery contracts over the public WSGI adapter. Offline; no model calls."""
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_app import Application, catalog_fold
from districtbrief import render


class CatalogPagination(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = Application(cls.tmp.name, secure_cookie=False)
        cls.cat = cls.call('/api/catalog')[1]
        cls.snapshot = cls.call('/api/health')[1]['snapshot_id']

    @classmethod
    def tearDownClass(cls):
        for handler in cls.app.service.metrics.handlers: handler.close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, path, query='', method='GET'):
        status, data = cls.call_raw(path, query, method)
        return status, (json.loads(data) if data else None)

    @classmethod
    def call_raw(cls, path, query='', method='GET'):
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': query, 'wsgi.input': io.BytesIO(b''),
               'CONTENT_LENGTH': '0', 'HTTP_HOST': 'example.test'}
        status = []
        data = b''.join(cls.app(env, lambda s, h: status.append(int(s.split()[0]))))
        return status[0], data

    def page(self, **params):
        return self.call('/api/catalog/observations', urlencode(params))

    def walk(self, limit, **filters):
        ids, offset, matched = [], 0, None
        while True:
            code, out = self.page(offset=offset, limit=limit, snapshot_id=self.snapshot, **filters)
            self.assertEqual((code, out['status'], out['model_calls']), (200, 'ok', 0), out)
            self.assertEqual(out['total'], 3280)
            matched = out['matched'] if matched is None else matched
            self.assertEqual(out['matched'], matched)
            self.assertEqual(re.findall(r'<tr [^>]*data-finding-id="([^"]+)"', out['rows_html']), out['finding_ids'])
            ids += out['finding_ids']
            offset += limit
            if offset >= matched:
                return ids, matched

    def reference(self, geography_id='', metric_id='', q=''):
        geos = {g['geography_id']: g['label'] for g in self.cat['geographies']}
        metrics = {m['metric_id']: m for m in self.cat['metrics']}
        words = catalog_fold(q).split()
        out = []
        for o in self.cat['observations']:
            # The visible row words: geography, measure, published estimate and MOE (***** reads Not published),
            # unit and universe.
            moe = o['moe_display'] or ''
            hay = catalog_fold(' '.join((geos[o['geography_id']], metrics[o['metric_id']]['label'], o['estimate_display'] or '',
                                         moe, 'Not published' if moe == '*****' else '', o['unit'] or '',
                                         metrics[o['metric_id']].get('universe') or '')))
            if (not geography_id or o['geography_id'] == geography_id) and (not metric_id or o['metric_id'] == metric_id) \
                    and all(w in hay for w in words):
                out.append(o['finding_id'])
        return out

    def test_legacy_catalog_shape_is_kept_and_html_holds_only_the_first_page(self):
        cat = self.cat
        self.assertEqual(len(cat['observations']), 3280)
        for key in ('templates', 'metrics', 'geographies', 'unavailable_geographies', 'programs', 'districts',
                    'participation', 'administrative_rows', 'sources', 'coverage', 'commands', 'sources_html',
                    'investigation', 'language'):
            self.assertIn(key, cat)
        html = cat['html']
        table = html[html.index('id="cat-table"'):html.index('</table>', html.index('id="cat-table"'))]
        self.assertEqual(re.findall(r'data-finding-id="([^"]+)"><td', table),
                         [o['finding_id'] for o in cat['observations'][:render.CATALOG_PAGE_SIZE]])
        self.assertIn('data-total="3280"', table)
        for control in ('id="cat-geo"', 'id="cat-metric"', 'id="cat-q"', 'id="cat-clear"', 'id="cat-prev"',
                        'id="cat-next"', 'id="cat-count"', 'id="cat-error"'):
            self.assertIn(control, html)
        self.assertEqual(html.count('<option value="') - html.count('<option value=""'), 82 + 40)
        self.assertIn('3,280 statistics in this data', html)
        self.assertIn('id="source-label-data"', cat['sources_html'])

    def test_catalog_summary_omits_only_observations(self):
        status, full = self.call_raw('/api/catalog')
        self.assertEqual(status, 200)
        status, summary = self.call_raw('/api/catalog', 'view=summary')
        self.assertEqual(status, 200)
        expected = json.loads(full)
        self.assertTrue(expected.pop('observations'))
        self.assertEqual(json.loads(summary), expected)
        self.assertLess(len(summary), len(full) // 2)
        for query in ('view=', 'view=full', 'view=SUMMARY', 'view=summary&view=summary', 'view=summary&other=1', 'unknown'):
            with self.subTest(query=query):
                self.assertEqual(self.call_raw('/api/catalog', query), (200, full))
        self.assertEqual(self.call_raw('/api/catalog'), (200, full))

    def test_paging_covers_every_row_once_in_catalog_order(self):
        every = [o['finding_id'] for o in self.cat['observations']]
        for limit in (50, 100, 37):
            with self.subTest(limit=limit):
                ids, matched = self.walk(limit)
                self.assertEqual(matched, 3280)
                self.assertEqual(ids, every)
                self.assertEqual(len(set(ids)), 3280)

    def test_filters_and_search_span_the_full_corpus(self):
        cases = [dict(metric_id='median_age'), dict(geography_id='HI-STATE-2024'),
                 dict(geography_id='HI-COUNTY-009-2024', metric_id='median_age'), dict(q='poverty'),
                 dict(q='Hawaiʻi 65'), dict(q='HAWAII county'), dict(q='house district 28'),
                 dict(metric_id='median_age', q='senate')]
        for filters in cases:
            with self.subTest(**filters):
                expected = self.reference(**filters)
                self.assertTrue(expected, filters)
                ids, matched = self.walk(50, **filters)
                self.assertEqual((ids, matched), (expected, len(expected)))
        self.assertEqual(self.walk(50, metric_id='median_age')[1], 82)
        self.assertEqual(self.walk(50, geography_id='HI-STATE-2024')[1], 40)
        self.assertEqual(self.reference(q='Hawaiʻi'), self.reference(q='hawaii'))

    def test_search_matches_published_estimate_and_moe_text(self):
        h028_poverty = 'stat:HI-HOUSE-028-2024:poverty_rate_all_people'
        row = next(o for o in self.cat['observations'] if o['finding_id'] == h028_poverty)
        self.assertEqual((row['estimate_display'], row['moe_display']), ('23.4%', '±3.1'))
        for q in ('house 028 23.4', 'House District 028 23.4%', 'house 028 3.1', 'house 028 ±3.1'):
            with self.subTest(q=q):
                ids, _ = self.walk(50, q=q)
                self.assertIn(h028_poverty, ids)
                self.assertEqual(ids, self.reference(q=q))
                self.assertTrue(all(i.startswith('stat:HI-HOUSE-028-2024:') for i in ids))
        unpublished = [o['finding_id'] for o in self.cat['observations'] if o['moe_display'] == '*****']
        self.assertTrue(unpublished)
        self.assertEqual(self.walk(50, q='not published')[0], unpublished)
        self.assertEqual(self.walk(50, q='*****')[0], unpublished)

    def test_no_match_is_an_empty_first_page(self):
        code, out = self.page(q='no such words anywhere')
        self.assertEqual((code, out['matched'], out['offset'], out['finding_ids']), (200, 0, 0, []))
        self.assertIn('class="cat-empty"', out['rows_html'])

    def test_bounds_and_malformed_requests_are_rejected(self):
        bad = ['offset=3280', 'offset=-1', 'offset=1.5', 'offset=abc', 'limit=0', 'limit=101', 'limit=', 'x=1',
               'offset=0&offset=50', 'geography_id=HI-NOPE', 'metric_id=nope', 'q=' + 'a' * 101, '&&',
               'metric_id=median_age&offset=82', 'offset=' + '9' * 7]
        for query in bad:
            with self.subTest(query=query):
                code, out = self.call('/api/catalog/observations', query)
                self.assertEqual(code, 400)
                self.assertEqual(out['status'], 'error')
                self.assertTrue(out['reason'].endswith('.'))
        code, out = self.page(snapshot_id='sha256:' + '0' * 64)
        self.assertEqual((code, out['status']), (409, 'error'))
        self.assertEqual(self.call('/api/catalog/observations', 'offset=3240&limit=100')[1]['finding_ids'][-1],
                         self.cat['observations'][-1]['finding_id'])
        self.assertEqual(self.call('/api/catalog/observations', method='HEAD')[0], 200)
        self.assertEqual(self.call('/api/catalog/observations', method='POST')[0], 404)

    def test_browser_client_uses_the_paged_route_and_has_one_startup_retry(self):
        app_js = (ROOT / 'static/app.js').read_text(encoding='utf-8')
        investigation_js = (ROOT / 'static/investigation.js').read_text(encoding='utf-8')
        index = (ROOT / 'static/index.html').read_text(encoding='utf-8')
        self.assertIn('/api/catalog/observations?', app_js)
        self.assertIn('fetch("/api/catalog?view=summary"', investigation_js)
        self.assertEqual(index.count('id="app-startup-retry"'), 1)
        self.assertNotIn('cat-more', app_js)

    def test_privacy_copy_names_catalog_search_text(self):
        index = (ROOT / 'static/index.html').read_text(encoding='utf-8')
        privacy = (ROOT / 'PRIVACY.md').read_text(encoding='utf-8')
        self.assertIn('Data catalog filters and search text are sent to this app’s server in the page request, not to OpenAI.', index)
        self.assertIn('requested addresses, which can contain catalog search text', index)
        self.assertIn('Data catalog filters and search text reach the server in the request address', privacy)
        self.assertIn('Records exclude typed requests, catalog search text,', privacy)
        self.assertIn('Search text goes to this app’s server, not to OpenAI.', self.cat['html'])


if __name__ == '__main__':
    unittest.main()
