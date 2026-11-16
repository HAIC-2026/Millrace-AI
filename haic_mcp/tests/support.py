"""Shared test support. Decisions built here are SYNTHETIC decisions (what an interpreter might return), checked
against the real engine; they are not shipped answers or reserved evaluation cases."""
from __future__ import annotations

import atexit
import copy
import json
import shutil
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
PYTHON = sys.executable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from haic_mcp.engine import Engine  # noqa: E402
from haic_mcp.tools import Connector, ToolError  # noqa: E402

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = Engine()
    return _ENGINE


def connector(**kw):
    return Connector(engine(), **kw)


SENTINEL = {'district': {'chamber': '', 'code': ''}, 'map_session': 0, 'issue_id': '', 'service_area_id': '', 'steps': []}


def step(sid, op, metrics=(), geo='', programs=(), observations=()):
    return {'step_id': sid, 'operation': op, 'metric_ids': list(metrics), 'comparison_geography': geo,
            'program_ids': list(programs), 'observation_ids': list(observations)}


def synthetic_decision(status='propose', intent='create_plan', chamber='', code='', issue='', steps=(), map_session=0,
                       service_area='', focus='', field='', choices=(), reason='', inherited=()):
    plan = copy.deepcopy(SENTINEL)
    if steps or chamber:
        plan = {'district': {'chamber': chamber, 'code': code}, 'map_session': map_session, 'issue_id': issue,
                'service_area_id': service_area, 'steps': list(steps)}
    return {'status': status, 'intent': intent, 'plan': plan, 'focus_alias': focus, 'clarify_field': field,
            'clarify_choices': list(choices), 'reason_code': reason, 'inherited_fields': list(inherited)}


def recipe_steps(issue):
    """The catalog recipe's steps in wire form (the same rows prepare_question exposes)."""
    from districtbrief.interpret import recipe, food_assistance_recipe
    from districtbrief.ia_language import wire_plan
    build = {'aging_at_home': recipe, 'food_assistance_outreach': food_assistance_recipe}[issue]
    return wire_plan(build({'state_fips': '15', 'chamber': 'house', 'code': '001', 'boundary_session': 2024}))['steps']


RECIPE_LABEL = {'aging_at_home': 'Older-adult support at home', 'food_assistance_outreach': 'SNAP outreach'}

EIGHT_STEPS = [
    step('s1', 'profile'),
    step('s2', 'compare', ['poverty_rate_65_plus', 'poverty_rate_all_people', 'median_household_income', 'population_65_plus'], 'HI-STATE-2024'),
    step('s3', 'compare', ['poverty_rate_65_plus', 'poverty_rate_all_people', 'median_household_income', 'population_65_plus'], 'HI-COUNTY-003-2024'),
    step('s4', 'compare', ['poverty_rate_65_plus', 'poverty_rate_all_people', 'median_household_income', 'population_65_plus'], 'HI-SENATE-025-2024'),
    step('s5', 'program_evidence', programs=['snap_hi', 'medquest_hi', 'hcv_honolulu', 'kupuna_care_hi', 'wic_hi']),
    step('s6', 'outreach_lead', programs=['kupuna_care_hi']),
    step('s7', 'outreach_lead', programs=['snap_hi']),
]


# The largest engine-ok eight-step plan found by the independent QA size search (greedy, not exhaustive): five
# four-measure compares covering all twenty measures, a Med-QUEST lead, five programs and eight administrative rows.
MAXIMAL_Q = ('For House 28, compare all twenty measures against Senate 25 and Honolulu County, add program evidence for SNAP, '
             'Med-QUEST, Section 8, Kupuna Care and WIC, a Med-QUEST outreach lead, and administrative evidence.')
MAXIMAL_STEPS = [
    step('s1', 'administrative_evidence', observations=['dbedt_county_h_009', 'dbedt_county_h_010', 'dbedt_county_h_011', 'dbedt_county_h_012',
                                                        'dbedt_county_h_008', 'hi_mqd_enrollment_2026_019', 'hi_mqd_enrollment_2026_020',
                                                        'hi_mqd_enrollment_2026_021']),
    step('s2', 'compare', ['median_household_income', 'poverty_rate_all_people', 'civilian_labor_force', 'unemployed'], 'HI-SENATE-025-2024'),
    step('s3', 'compare', ['renter_occupied_units', 'occupied_housing_units', 'median_gross_rent', 'total_housing_units'], 'HI-SENATE-025-2024'),
    step('s4', 'compare', ['population_65_plus', 'unemployment_rate', 'total_households', 'median_age'], 'HI-SENATE-025-2024'),
    step('s5', 'compare', ['female_householder_65_plus_living_alone', 'male_householder_65_plus_living_alone',
                           'households_with_social_security', 'education_health_social_assistance_industry'], 'HI-SENATE-025-2024'),
    step('s6', 'compare', ['rent_35_plus_percent_income', 'rent_burden_denominator', 'total_population', 'poverty_rate_65_plus'], 'HI-COUNTY-003-2024'),
    step('s7', 'outreach_lead', programs=['medquest_hi']),
    step('s8', 'program_evidence', programs=['snap_hi', 'medquest_hi', 'hcv_honolulu', 'kupuna_care_hi', 'wic_hi']),
]


class Flow:
    """Drive the tool sequence through any `call(name, args) -> structured` function."""

    def __init__(self, call):
        self.call = call

    def prepare(self, utterance, context=None, identity=None):
        args = {'utterance': utterance}
        if context is not None:
            args.update(context=context, expected_identity=identity)
        return self.call('prepare_question', args)

    def validate(self, prepared, decision):
        return self.call('validate_proposal', {'request': prepared['request'], 'decision': decision,
                                               'expected_identity': prepared['identity']})

    @staticmethod
    def bundle(validated):
        return {'request': validated['request'], 'decision': validated['decision'],
                'expected_identity': validated['identity'], 'proposal_digest': validated['proposal_digest']}

    def run(self, validated):
        return self.call('run_plan', self.bundle(validated))

    def ask_and_run(self, utterance, decision, context=None, identity=None):
        prepared = self.prepare(utterance, context, identity)
        validated = self.validate(prepared, decision)
        assert validated['status'] == 'propose', validated
        return prepared, validated, self.run(validated)


def local_call(conn):
    def call(name, args):
        return conn.call(name, copy.deepcopy(args))[0]
    return call


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def scratch_dir():
    base = os.environ.get('HAIC_MCP_TEST_TMP')
    if base:
        Path(base).mkdir(parents=True, exist_ok=True)
    path = tempfile.mkdtemp(prefix='haic-mcp-test-', dir=base or None)
    atexit.register(shutil.rmtree, path, True)  # test copies never outlive the test process
    return path


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServerProcess:
    """A real `python -m haic_mcp` process on an unused loopback port; always terminated by stop()."""

    def __init__(self, port=None, extra_args=(), env=None):
        self.port = port or free_port()
        environment = {k: v for k, v in os.environ.items() if not k.startswith('HAIC_')}
        environment.update(PYTHONDONTWRITEBYTECODE='1', **(env or {}))
        self.proc = subprocess.Popen([PYTHON, '-B', '-m', 'haic_mcp', '--port', str(self.port), *extra_args], cwd=str(ROOT),
                                     env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.startup = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = self.proc.stderr.readline()
            if not line:
                break
            if line.startswith('{"startup"'):
                self.startup = json.loads(line)
                break
        if not self.startup or self.startup['startup'] != 'ok':
            self.stop()
            raise RuntimeError('server did not start: %r' % (self.startup,))
        while time.monotonic() < deadline:  # wait until uvicorn accepts connections
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.05)
        self.log = []
        self._drainer = threading.Thread(target=self._drain, daemon=True)  # a full stderr pipe must never block the server
        self._drainer.start()

    def _drain(self):
        for line in self.proc.stderr:
            self.log.append(line.rstrip('\n'))

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/mcp'

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        if hasattr(self, '_drainer'):
            self._drainer.join(5)
        if self.proc.stderr and not self._drainer_alive():
            self.proc.stderr.close()
        return self.log

    def _drainer_alive(self):
        return hasattr(self, '_drainer') and self._drainer.is_alive()
