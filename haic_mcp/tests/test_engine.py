"""Startup integrity, identity, module audit, hostile environment and interpretation-rule fidelity."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from haic_mcp import engine as engine_module
from haic_mcp.engine import FORBIDDEN_MODULES, PIN, StartupError, audit_modules
from haic_mcp.tests.support import PYTHON, ROOT, engine, scratch_dir

REAL_MANIFEST = json.loads((ROOT / 'RELEASE-MANIFEST.json').read_bytes())


def run_python(code, env=None):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('HAIC_')}
    environment.update(PYTHONDONTWRITEBYTECODE='1', **(env or {}))
    done = subprocess.run([PYTHON, '-I', '-B', '-c', code], capture_output=True, text=True, env=environment, timeout=180)
    if done.returncode != 0:
        raise AssertionError(done.stderr[-3000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


STARTUP = '''import json, sys
sys.path.insert(0, {real!r})
from haic_mcp.engine import Engine, StartupError
from haic_mcp.tools import Connector, ToolError
{pre}
try:
    e = Engine({root!r}, {pin!r})
except StartupError as x:
    print(json.dumps({{'ok': False, 'reason': str(x)}})); raise SystemExit(0)
out = {{'ok': True, 'identity': e.identity}}
{post}
print(json.dumps(out))
'''


def startup(root, pin=None, pre='', post=''):
    return run_python(STARTUP.format(real=str(ROOT), root=str(root), pin=pin, pre=pre, post=post))


def copy_engine():
    """A private copy of every listed release file plus the verified packet and metadata trees."""
    target = Path(scratch_dir()) / 'engine'
    for row in REAL_MANIFEST['files']:
        dest = target / row['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / row['path'], dest)
    for tree in ('runtime-packet', 'candidate-metadata'):
        shutil.copytree(ROOT / tree, target / tree, dirs_exist_ok=True)
    shutil.copy2(ROOT / 'RELEASE-MANIFEST.json', target / 'RELEASE-MANIFEST.json')
    return target


def repin(root, changed=(), source_identity=None):
    """Rewrite the copy's manifest for edited files (a new release); return the new manifest SHA-256."""
    path = root / 'RELEASE-MANIFEST.json'
    manifest = json.loads(path.read_bytes())
    for row in manifest['files']:
        if row['path'] in changed:
            data = (root / row['path']).read_bytes()
            row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    rows = sorted(manifest['files'], key=lambda r: r['path'].encode('utf-8'))
    lines = ''.join(f"{r['sha256']}  {r['bytes']}  {r['path']}\n" for r in rows)
    manifest['source_identity'] = source_identity or 'sha256:' + hashlib.sha256(lines.encode('utf-8')).hexdigest()
    raw = json.dumps(manifest, indent=1).encode('utf-8')
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class IdentityAndAuditTests(unittest.TestCase):
    def test_identity_is_complete_and_pinned(self):
        ident = engine().identity
        eng = ident['engine']
        self.assertEqual(eng['release_manifest_sha256'], 'sha256:' + PIN['release_manifest_sha256'])
        self.assertEqual(eng['release_manifest_sha256'], 'sha256:' + hashlib.sha256((ROOT / 'RELEASE-MANIFEST.json').read_bytes()).hexdigest())
        self.assertEqual(eng['source_identity'], REAL_MANIFEST['source_identity'])
        self.assertEqual((eng['data_snapshot_id'], eng['metadata_snapshot_id'], eng['snapshot_id']),
                         (REAL_MANIFEST['lineage']['data_snapshot_id'], REAL_MANIFEST['lineage']['metadata_snapshot_id'],
                          REAL_MANIFEST['lineage']['combined_evidence_snapshot_id']))
        self.assertEqual((eng['operation_version'], eng['investigation_schema_version'], eng['language_schema_version'], eng['input_profile']),
                         ('ia-core/1', 'haic-investigation/1', 'ia-language/1', 'public'))
        self.assertEqual(eng['recipe_versions'], ['aging_at_home/1', 'custom/1', 'food_assistance_outreach/1'])
        self.assertRegex(ident['connector']['build_digest'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(ident['connector']['build_digest'], engine_module.build_digest())
        self.assertEqual(len(REAL_MANIFEST["files"]), 146)

    def test_loaded_engine_modules_are_listed_and_local(self):
        e = engine()
        listed = {r['path'] for r in REAL_MANIFEST['files']}
        self.assertTrue(e.loaded_modules)
        self.assertTrue(set(e.loaded_modules) <= listed)
        for name, module in sys.modules.items():
            if name.startswith('districtbrief'):
                self.assertTrue(Path(module.__file__).resolve().is_relative_to(ROOT), name)
        self.assertFalse(set(FORBIDDEN_MODULES) & set(sys.modules))
        with self.assertRaisesRegex(StartupError, 'not a listed release file'):
            audit_modules(ROOT, listed - {'districtbrief/core.py'})


class TamperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_identity = engine().identity

    def test_intact_copy_starts_with_the_same_identity(self):
        out = startup(copy_engine())
        self.assertTrue(out['ok'], out)
        self.assertEqual(out['identity'], self.real_identity)

    def test_listed_byte_drift_missing_file_and_manifest_change_fail_closed(self):
        root = copy_engine()
        fixture = next(r['path'] for r in REAL_MANIFEST['files'] if r['path'].startswith('tests/fixtures/'))
        data = bytearray((root / fixture).read_bytes())
        data[-1] ^= 1
        (root / fixture).write_bytes(bytes(data))
        out = startup(root)
        self.assertEqual(out, {'ok': False, 'reason': 'listed release file changed: ' + fixture})
        root = copy_engine()
        (root / 'docs/R2-REPLAY.md').unlink()
        self.assertEqual(startup(root)['reason'], 'listed release file missing: docs/R2-REPLAY.md')
        root = copy_engine()
        with open(root / 'RELEASE-MANIFEST.json', 'ab') as fh:
            fh.write(b'\n')
        self.assertEqual(startup(root)['reason'], 'release manifest does not match the pinned SHA-256')
        root = copy_engine()
        data = bytearray((root / 'runtime-packet/data/statistics/observations.json').read_bytes())
        data[100] ^= 1
        (root / 'runtime-packet/data/statistics/observations.json').write_bytes(bytes(data))
        self.assertIn('runtime-packet/data/statistics/observations.json', startup(root)['reason'])

    def test_doc_only_release_has_a_new_identity_and_old_identity_is_rejected(self):
        root = copy_engine()
        with open(root / 'README.md', 'a', encoding='utf-8') as fh:
            fh.write('\nA documentation-only change.\n')
        pin = repin(root, changed={'README.md'})
        self.assertEqual(startup(root)['ok'], False)  # the baseline pin refuses the new release
        old = json.dumps(self.real_identity)
        post = (f"try:\n    Connector(e).call('prepare_question', {{'utterance': 'Profile House 3.', 'expected_identity': json.loads({old!r})}})\n"
                f"    out['old_identity'] = 'accepted'\nexcept ToolError as x:\n    out['old_identity'] = x.code")
        out = startup(root, pin=pin, post=post)
        self.assertTrue(out['ok'], out)
        new, real = out['identity']['engine'], self.real_identity['engine']
        self.assertNotEqual(new['release_manifest_sha256'], real['release_manifest_sha256'])
        self.assertNotEqual(new['source_identity'], real['source_identity'])
        self.assertEqual(new['snapshot_id'], real['snapshot_id'])
        self.assertEqual(out['old_identity'], 'identity_mismatch')

    def test_declared_source_identity_must_match_listed_files(self):
        root = copy_engine()
        pin = repin(root, source_identity='sha256:' + '6' * 64)
        self.assertEqual(startup(root, pin=pin)['reason'], 'declared source identity does not match the listed files')

    def test_prompt_ast_seam_fails_closed_on_drift(self):
        provider = 'districtbrief/ia_language_provider.py'
        for old, new, reason in (
                ('Interpret one staff question', 'Interpret one question', 'PROMPT literal does not match the pinned text'),
                ("'; '.join(", "' | '.join(", 'unexpected RECIPE_NAMES replacement expression'),
                (".replace('<RECIPE_NAMES>',", ".replace('<RECIPES>',", 'unexpected PROMPT receiver or placeholder shape'),
                ("COUNT_KEYS=(", "PROMPT=PROMPT+''\nCOUNT_KEYS=(", 'unexpected PROMPT assignment shape')):
            root = copy_engine()
            text = (root / provider).read_text(encoding='utf-8')
            self.assertEqual(text.count(old), 1, old)
            (root / provider).write_text(text.replace(old, new), encoding='utf-8')
            self.assertEqual(startup(root, pin=repin(root, changed={provider}))['reason'], reason)

    def test_modules_from_another_checkout_are_refused(self):
        pre = f"sys.path.insert(0, {str(ROOT)!r}); import districtbrief"
        self.assertEqual(startup(copy_engine(), pre=pre)['reason'], 'districtbrief is already loaded from another checkout')

    def test_release_change_after_startup_stops_serving(self):
        root = copy_engine()
        post = (f"open({str(root / 'RELEASE-MANIFEST.json')!r}, 'ab').write(b' ')\n"
                f"try:\n    Connector(e).call('prepare_question', {{'utterance': 'Profile House 3.'}})\n    out['after'] = 'served'\n"
                f"except ToolError as x:\n    out['after'] = x.code")
        self.assertEqual(startup(root, post=post)['after'], 'engine_changed')


class EnvironmentTests(unittest.TestCase):
    def test_hostile_language_environment_and_no_network_or_secrets(self):
        code = textwrap.dedent(f'''
            import builtins, json, socket, sys
            attempts = []
            def deny(*a, **k):
                attempts.append('network'); raise OSError('network disabled in test')
            socket.socket.connect = deny; socket.socket.connect_ex = deny; socket.create_connection = deny
            real_open = builtins.open
            def watched(path, *a, **k):
                if 'secret' in str(path).lower(): attempts.append('secret')
                return real_open(path, *a, **k)
            builtins.open = watched
            sys.path.insert(0, {str(ROOT)!r})
            from haic_mcp.tests.support import Flow, connector, engine, local_call, step, synthetic_decision
            flow = Flow(local_call(connector()))
            p, v, r = flow.ask_and_run('Compare senior poverty in House 12 with the State.', synthetic_decision(chamber='house', code='012',
                issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-STATE-2024')]))
            ref = r['claims'][-1]['claim_ref']
            flow.call('inspect_source', dict(Flow.bundle(v), mode='claim', claim_ref=ref))
            flow.call('build_brief', dict(Flow.bundle(v), selected_claim_refs=[ref]))
            print(json.dumps({{'attempts': attempts, 'modules': sorted(sys.modules), 'identity': engine().identity}}))
        ''')
        out = run_python(code, env={'HAIC_LANGUAGE_ENABLED': '1', 'HAIC_LANGUAGE_PROFILE': 'terra_high', 'HAIC_INPUT_PROFILE': 'r2',
                                    'HAIC_R2_INPUT_DIR': '/nonexistent', 'OPENAI_API_KEY': 'sk-test-not-a-key', 'HAIC_STATE_DIR': '/nonexistent'})
        self.assertEqual(out['attempts'], [])
        self.assertFalse(set(FORBIDDEN_MODULES) & set(out['modules']))
        self.assertFalse([m for m in out['modules'] if m.split('.')[0] in ('openai', 'requests', 'httpx', 'urllib3', 'boto3')])
        self.assertEqual(out['identity'], engine().identity)
        self.assertEqual(out['identity']['engine']['input_profile'], 'public')

    def test_interpretation_rules_match_pinned_prompt_except_transport_and_phase(self):
        # The provider is imported ONLY in this isolated test subprocess, to read its PROMPT as the oracle.
        code = textwrap.dedent(f'''
            import json, sys
            sys.path.insert(0, {str(ROOT)!r})
            from districtbrief.ia_language_provider import PROMPT
            print(json.dumps({{'prompt': PROMPT}}))
        ''')
        prompt = run_python(code)['prompt']
        rules = engine().rules
        self.assertTrue(rules.startswith(engine_module.RULES_HEADER) and rules.endswith(engine_module.RULES_FOOTER))
        body = rules[len(engine_module.RULES_HEADER):-len(engine_module.RULES_FOOTER)]
        self.assertEqual(body.replace(engine_module.MCP_TRANSPORT_SENTENCE, engine_module.TRANSPORT_SENTENCE), prompt)
        self.assertEqual(body.count(engine_module.MCP_TRANSPORT_SENTENCE), 1)
        self.assertNotIn('ia_language_decision', body)
        self.assertIn('"Older-adult support at home" or "aging at home" = aging_at_home', body)
        self.assertIn('apply only while turning the user question into one decision object', engine_module.RULES_HEADER)
        self.assertIn('do not restrict narrating', engine_module.RULES_HEADER)


if __name__ == '__main__':
    unittest.main()
