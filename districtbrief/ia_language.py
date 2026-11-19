"""Nonexecuting IA language contract, value-free projection and checked proposals."""
from __future__ import annotations
import copy
import json
import math
import re
from .case_contract import (InvestigationError, OPERATION_VERSION, SERVICES, claim_ref,
    depth, integer, obj, text, unique_ids, uuid4, validate_plan)
from .claim_binding import digest

SCHEMA_VERSION = 'ia-language/1'
FUNCTION_NAME = 'ia_language_decision'
DISABLED_MESSAGE = 'Language questions are unavailable. Use Typed request or guided controls.'
PRIVACY_NOTICE = ('Your question and value-free plan/catalog context are sent to OpenAI. '
                  'Omit confidential or resident details. Notes and claim values are excluded.')
OPERATIONS = ('profile','compare','program_evidence','outreach_lead','administrative_evidence')
CONTEXT_KEYS = ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version',
                'confirmed_plan','draft_plan','focused_step_id','selected_claim_refs')
INHERITABLE = ('district','map_session','issue_id','service_area_id','steps','focus')
EMPTY_PLAN = {'district':{'chamber':'','code':''},'map_session':0,'issue_id':'','service_area_id':'','steps':[]}
MESSAGES = {
 'propose':'Review this language proposal, then Apply to the draft. Run remains a separate action.',
 'clarify':'Choose the missing or conflicting context, then ask again.',
 'unsupported':'This request is outside the admitted evidence or operations. Use guided controls.',
 'uncertain':'The question could not be interpreted reliably. Rephrase it or use guided controls.',
 'pending':'Interpreting the question. Guided controls remain available.',
 'cancelled':'Interpretation cancelled. Existing work is unchanged.',
 'expired':'This interpretation expired. Ask again with the current context.',
 'error':'Language interpretation failed safely. Use Typed request or guided controls.',
}

class LanguageError(ValueError):
    def __init__(self, code='invalid_request', status=400):
        super().__init__(code); self.code,self.status=code,status

# Closed, value-free attribution categories for a server typed recovery (auditable in HTTP/operator records).
RECOVERY_CATEGORIES={'control_conflict':'control_conflict','ambiguous_reference':'ambiguous_referent',
    'explicit_district_missing':'missing_district','explicit_metric_ambiguous':'ambiguous_poverty_metric',
    'ungrounded_program':'generic_program_theme','nonlegislative_district':'nonlegislative_district',
    'unsupported_explicit_constraint':'unsupported_inference','unsupported_cross_measure':'cross_measure_comparison',
    'explicit_comparator_chamber_missing':'ambiguous_comparator_chamber',
    'explicit_comparator_county_unstated':'ambiguous_comparator_county'}

class Recovery(LanguageError):
    """A deterministic guard refusal with a fixed typed recovery (clarify/unsupported), never a proposal.
    Only conditions the request/context proves; choices are server aliases from the request's choice table."""
    def __init__(self, code, state, *, reason, field='', choices=()):
        super().__init__(code); self.state,self.reason,self.field,self.choices=state,reason,field,tuple(choices)
        self.category=RECOVERY_CATEGORIES[code]

def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode('utf-8')

def strict_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('duplicate_key')
            out[k]=v
        return out
    def bad(_):raise ValueError('nonfinite')
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
    def finite(v):
        if type(v) is float and not math.isfinite(v):raise ValueError('nonfinite')
        if isinstance(v,dict):
            for x in v.values():finite(x)
        if isinstance(v,list):
            for x in v:finite(x)
    finite(value);return value

def _object(fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
def _enum(values):return {'type':'string','enum':list(values)}
def _array(values):return {'type':'array','items':_enum(values)}

def wire_plan(plan):
    if plan is None:return None
    rows=[]
    for s in plan['steps']:
        a=s['args'];rows.append({'step_id':s['step_id'],'operation':s['operation'],
            'metric_ids':copy.deepcopy(a.get('metric_ids') or []),
            'comparison_geography':a.get('comparison_geography',''),
            'program_ids':copy.deepcopy(a.get('program_ids') or ([a['program_id']] if 'program_id' in a else [])),
            'observation_ids':copy.deepcopy(a.get('observation_ids') or [])})
    return {'district':{k:plan['district'][k] for k in ('chamber','code')},'map_session':plan['map_session'],
            'issue_id':plan['issue_id'],'service_area_id':plan['service_area_id'] or '', 'steps':rows}

EXAMPLE_DISTRICT={'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}  # recipe step templates only

def value_free_catalog(core):
    """Explicit whitelist: no program prose, source body, observation value or URL."""
    from .case_contract import admitted_recipes
    recipes=admitted_recipes(core)
    metrics=[{k:m[k] for k in ('metric_id','label','unit','universe')} for m in core.metrics.values()]
    programs=[{'program_id':k,'label':v['name']} for k,v in core.programs.items()]
    sources=[{'source_id':k,'title':v.get('title') or v.get('name') or ''}
             for k,v in core.packet.sources.items()]
    # Descriptions are source catalog titles only, never retained passages.
    sources=[{'source_id':x['source_id'],'title':str(x['title'])[:180]} for x in sources]
    from .admin_labels import ROW_SERIES,SERIES
    observations=[]
    for k,v in core.administrative_rows.items():
        observations.append({'observation_id':k,'series_id':ROW_SERIES[k],
            'geography':{key:copy.deepcopy(v.get('geography',{}).get(key)) for key in ('type','name','geoid') if key in v.get('geography',{})},
            **{key:copy.deepcopy(v[key]) for key in ('program_id','period','source_id') if key in v}})
    from .interpret import recipe,food_assistance_recipe
    d=EXAMPLE_DISTRICT
    recipe_plans=[]
    for version,build in [('aging_at_home/1',recipe),('food_assistance_outreach/1',food_assistance_recipe)]:
        if version in recipes:
            p=wire_plan(build(d));recipe_plans.append({'issue_id':p['issue_id'],'steps':p['steps']})
    return {'operations':list(OPERATIONS),'metrics':metrics,'programs':programs,
            'geographies':sorted(core.profiles),'issues':[r.rsplit('/',1)[0] for r in recipes],
            'recipes':recipes,'service_areas':sorted(SERVICES),
            'administrative_observations':observations,'administrative_series':{k:v[0] for k,v in SERIES.items()},
            'recipe_plans':recipe_plans,'outreach_program_ids':['kupuna_care_hi','snap_hi','medquest_hi','hcv_honolulu'],'sources':sources,
            'outreach_basis':'outreach_lead always uses the complete reviewed basis; never eligibility, participation gap or a resident count'}

def _choices(catalog,selected,conflict,comparator_choices):
    choices={}
    def add(alias,field,value,label):choices[alias]={'alias':alias,'field':field,'value':value,'label':label}
    for chamber,n in [('house',51),('senate',25)]:
        add('c_'+chamber,'chamber',chamber,chamber.title())
        for number in range(1,n+1):
            code=f'{number:03}';add(f'd_{chamber[0]}{code}','district',{'chamber':chamber,'code':code},f'{chamber.title()} {number}')
    for m in catalog['metrics']:add('m_'+m['metric_id'],'metric',m['metric_id'],m['label'])
    for p in catalog['programs']:add('p_'+p['program_id'],'program',p['program_id'],p['label'])
    for g in comparator_choices:add('g_'+g,'comparator',g,g.replace('HI-','').replace('-2024',''))
    for alias in selected:add('r_'+alias,'referent',alias,alias.replace('_',' ').title())
    for source in catalog['sources']:
        add(source['alias'],'referent',source['alias'],source['title'] or source['source_id'])
    if conflict:
        for v in ('confirmed','draft'):add('x_'+v,'control_conflict',v,'Use '+v+' plan')
    return choices

def _claim_geography(claim):
    def identity(g):
        if not isinstance(g,dict):return None
        return {k:copy.deepcopy(g[k]) for k in ('geography_id','chamber','district_code','boundary_session') if k in g}
    if claim.get('kind')=='comparison':
        return {side:identity(claim.get(side,{}).get('geography')) for side in ('left','right')}
    return identity(claim.get('geography'))

def prepare_request(raw, investigation, session):
    """The only Core-capable seam; invoked synchronously before background dispatch."""
    try:
        obj(raw,('schema_version','request_id','context','utterance'));depth(raw)
        if len(dumps(raw))>65536:raise LanguageError('request_too_large')
        if raw['schema_version']!=SCHEMA_VERSION:raise LanguageError('version_mismatch',409)
        uuid4(raw['request_id'],'request_id');text(raw['utterance'],500,'utterance',1)
        if not raw['utterance'].strip() or re.search(r'(?:https?://|www\.)',raw['utterance'],re.I):raise LanguageError('utterance_not_admitted')
        c=raw['context'];obj(c,CONTEXT_KEYS)
        for k in ('case_id','branch_id'):uuid4(c[k],k)
        integer(c['revision'],0,2147483647,'revision')
        if c['snapshot_id']!=investigation.snapshot_id:raise LanguageError('snapshot_unavailable',409)
        if c['operation_version']!=OPERATION_VERSION:raise LanguageError('version_mismatch',409)
        recipes=investigation.bootstrap()['recipe_versions']
        if c['recipe_version'] not in recipes:raise LanguageError('version_mismatch',409)
        for key in ('confirmed_plan','draft_plan'):
            if c[key] is not None:validate_plan(c[key],investigation.core)
        active=c['confirmed_plan']
        if active is not None and active['issue_id']+'/1'!=c['recipe_version']:raise LanguageError('version_mismatch',409)
        ids=[s['step_id'] for s in (active or c['draft_plan'] or {'steps':[]})['steps']]
        if c['focused_step_id'] is not None and c['focused_step_id'] not in ids:raise LanguageError('invalid_focus')
        refs=c['selected_claim_refs']
        if type(refs) is not list or len(refs)>8:raise LanguageError('invalid_selections')
        if len({dumps(r) for r in refs})!=len(refs):raise LanguageError('duplicate_selections')
        for r in refs:claim_ref(r,'selected_claim_refs')
        if refs and active is None:raise LanguageError('selection_requires_confirmed_plan',409)
        # Only confirmed current bindings may be re-derived, and only here.
        claims={};step_claims={}
        if active is not None:
            run={'schema_version':'haic-investigation/1','operation_version':OPERATION_VERSION,
                 'recipe_version':c['recipe_version'],'snapshot_id':c['snapshot_id'],
                 'request_id':raw['request_id'],**{k:c[k] for k in ('case_id','branch_id','revision')},
                 'mode':'run','plan':copy.deepcopy(active),'selected_claim_refs':copy.deepcopy(refs),'selected_action_ref':None}
            result=investigation.handle(run)
            if result['status']!='ok' or any(x['state']!='retained' for x in result['selection_review']):raise LanguageError('stale_selection',409)
            claims={dumps(x['claim_ref']):x for x in result['claims']}
            step_claims={dumps(r):s['step_id'] for s in result['steps'] for r in s['claim_refs']}
        selected={};aliases={}
        for index,ref in enumerate(refs,1):
            claim=claims.get(dumps(ref))
            if claim is None:raise LanguageError('stale_selection',409)
            alias=f'selected_{index}';sources=copy.deepcopy(claim['source_inspection_refs'])
            selected[alias]={'kind':claim['kind'],'step_id':step_claims.get(dumps(ref)),
                'metric_id':(claim.get('metric') or {}).get('metric_id'),
                'program_id':(claim.get('program') or {}).get('program_id'),
                'geography':_claim_geography(claim),'period':copy.deepcopy(claim.get('period')),
                'source_ids':list(dict.fromkeys(x['source_id'] for x in sources))}
            # A comparison's nested operands are excluded: geography and period only.
            aliases[alias]=sources
        catalog=value_free_catalog(investigation.core)
        catalog_digest=digest(catalog)  # Stable scope before request-specific source aliases.
        for index,src in enumerate(catalog['sources'],1):
            alias=f'source_{index}';src['alias']=alias;aliases[alias]=[{'source_id':src['source_id']}]
        current_ids=list(ids)
        for p in (c['confirmed_plan'],c['draft_plan']):
            if p:
                for s in p['steps']:
                    if s['step_id'] not in current_ids:current_ids.append(s['step_id'])
        # Union can exceed eight with a divergent draft: require an explicit choice.
        conflict=c['confirmed_plan'] is not None and c['draft_plan'] is not None and c['confirmed_plan']!=c['draft_plan']
        if len(current_ids)>8:current_ids=ids
        fresh=[]
        for i in range(1,1000):
            if f's{i}' not in current_ids:fresh.append(f's{i}')
            if len(fresh)==8:break
        # Comparator clarification universe: every already-admitted catalog geography (State, counties, House and
        # Senate districts). Offering a typed choice is not a Plan: committed comparators are still checked by the
        # guard's provenance rules. Values are admitted canonical geography IDs; sorted order.
        comparator_choices=set(catalog['geographies'])
        choices=_choices(catalog,selected,conflict,sorted(comparator_choices))
        tokens={k:copy.deepcopy(c[k]) for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')}
        tokens.update(schema_version=SCHEMA_VERSION,release_id=investigation.release_id())
        canonical=copy.deepcopy(c)
        binding={'context':canonical,'tokens':tokens,'session':session,'request_id':raw['request_id'],'catalog_digest':catalog_digest}
        provider_context={'utterance':raw['utterance'],'confirmed_plan':wire_plan(c['confirmed_plan']),
            'draft_plan':wire_plan(c['draft_plan']),'focused_step_id':c['focused_step_id'],
            'selected':selected,'catalog':catalog,
            'step_ids':current_ids+fresh,'control_conflict':conflict}
        return {'request_id':raw['request_id'],'context':canonical,'tokens':tokens,'context_digest':digest(binding),
                'provider_context':provider_context,'aliases':aliases,'choices':choices,'step_ids':current_ids+fresh,
                'catalog_digest':catalog_digest,'schema':decision_schema(catalog,current_ids+fresh,aliases,choices)}
    except InvestigationError as exc:raise LanguageError(exc.code,exc.status) from None
    except (TypeError,KeyError,ValueError,UnicodeError) as exc:
        if isinstance(exc,LanguageError):raise
        raise LanguageError() from None

def decision_schema(catalog,step_ids,aliases,choices):
    if len(step_ids)>16 or not step_ids or len(set(step_ids))!=len(step_ids):raise LanguageError('step_domain_oversized')
    step=_object({'step_id':_enum(step_ids),'operation':_enum(OPERATIONS),
        'metric_ids':_array(x['metric_id'] for x in catalog['metrics']),
        'comparison_geography':_enum(['',*catalog['geographies']]),
        'program_ids':_array(x['program_id'] for x in catalog['programs']),
        'observation_ids':_array(x['observation_id'] for x in catalog['administrative_observations'])})
    plan=_object({'district':_object({'chamber':_enum(['','house','senate']),
        'code':_enum(['',*[f'{i:03}' for i in range(1,52)]])}),
        'map_session':{'type':'integer','enum':[0,2024,2026]},'issue_id':_enum(['',*catalog['issues']]),
        'service_area_id':_enum(['',*catalog['service_areas']]),'steps':{'type':'array','items':step}})
    schema=_object({'status':_enum(['propose','clarify','unsupported','uncertain']),
        'intent':_enum(['create_plan','replace_plan','inspect_source','none']),'plan':plan,
        'focus_alias':_enum(['',*aliases]),
        'clarify_field':_enum(['','district','chamber','metric','comparator','program','referent','control_conflict']),
        'clarify_choices':_array(['',*choices]),
        'reason_code':_enum(['','missing_context','ambiguous_reference','control_conflict','unsupported_operation','unavailable_evidence','uncertain_interpretation']),
        'inherited_fields':_array(INHERITABLE)})
    lint_schema(schema);return schema

def lint_schema(schema):
    stats={'enum_entries':0,'maximum_enum':0,'covered_string_characters':0,'object_properties':0,'nesting_depth':0,'schema_bytes':len(dumps(schema))}
    def visit(s,level):
        if type(s) is not dict or set(s)-{'type','properties','required','additionalProperties','items','enum'}:raise LanguageError('schema_keyword')
        stats['nesting_depth']=max(stats['nesting_depth'],level)
        if 'enum' in s:
            values=s['enum'];stats['enum_entries']+=len(values);stats['maximum_enum']=max(stats['maximum_enum'],len(values))
            chars=sum(len(x) for x in values if isinstance(x,str));stats['covered_string_characters']+=chars
            if len(values)>250 and chars>15000:raise LanguageError('schema_enum_strings')
        if s['type']=='object':
            if s.get('additionalProperties') is not False or set(s['required'])!=set(s['properties']):raise LanguageError('schema_open_object')
            stats['object_properties']+=len(s['properties']);stats['covered_string_characters']+=sum(map(len,s['properties']))
            for k,v in s['properties'].items():
                if k=='step_id' and len(v.get('enum',[]))>16:raise LanguageError('step_domain_oversized')
                visit(v,level+1)
        elif s['type']=='array':visit(s['items'],level+1)
        elif s['type'] not in ('string','integer'):raise LanguageError('schema_type')
    visit(schema,1)
    if stats['enum_entries']>1000 or stats['object_properties']>5000 or stats['nesting_depth']>10 or stats['covered_string_characters']>120000 or stats['schema_bytes']>32768:raise LanguageError('schema_too_large')
    return stats

def validate_wire(value,schema):
    if schema['type']=='object':
        if type(value) is not dict or set(value)!=set(schema['properties']):raise LanguageError('invalid_provider_shape')
        for k,v in value.items():validate_wire(v,schema['properties'][k])
    elif schema['type']=='array':
        if type(value) is not list or len(value)>max(8,20 if schema['items'].get('enum') and 'total_households' in schema['items']['enum'] else 8):raise LanguageError('invalid_provider_list')
        for v in value:validate_wire(v,schema['items'])
        if any(value.count(v)>1 for v in value):raise LanguageError('duplicate_provider_values')
    elif schema['type']=='integer':
        # JSON Schema integers include finite numeric values with no fractional part.
        # Normalize that representation only after enforcing the exact admitted enum.
        if type(value) not in (int,float) or (type(value) is float and (not math.isfinite(value) or not value.is_integer())) or value not in schema.get('enum',[]):
            raise LanguageError('invalid_provider_enum')
    elif type(value) is not str or value not in schema.get('enum',[]):raise LanguageError('invalid_provider_enum')

# Proposal map_session 0 means "not stated". It resolves from an explicit map phrase, else the
# confirmed plan's map control or, with no plan context at all, the existing new-plan default
# (Typed request and guided defaultPlan both create map 2026). Data periods (e.g. ACS 2020-2024)
# are never map evidence; statistical boundaries stay fixed 2024. All refusals use uncertain
# terminal prefixes (explicit_/invalid_provider_). An explicit map year in the utterance must be
# reported by the model: the sentinel is then inconsistent and refused, so the server never fills a
# stated year into a proposal attributed to the model.
NEW_PLAN_MAP_SESSION=2026
_MAP_YEAR=re.compile(r'\b(?:map(?:\s+session)?|district\s+map|redistricting|reapportionment)\s+(?:for\s+|of\s+|from\s+)?(202[46])\b'
    r'|\b(202[46])\s+(?:legislative\s+|district\s+|redistricting\s+|reapportionment\s+)?(?:map|maps|map\s+session|redistricting|reapportionment)\b'
    r'|\b(202[46])\s+(?:state\s+)?(?:legislative\s+districts?|(?:house|senate)\s+districts)\b'
    # A boundary year tied to the map itself: "the 2024 boundary on the map", "2024 session boundary map". A bare
    # "2024 boundaries" stays unread (the fixed statistical boundaries are 2024).
    r'|\b(202[46])\s+(?:session\s+)?(?:district\s+)?boundar(?:y|ies)\s+(?:maps?\b|(?:on|in|for)\s+(?:the\s+)?maps?\b)(?!\s+(?:legend|key|caption|labels?)\b)'
    # "switch the map to [the] 2024 [session]": the year must end the map phrase ("map to 2024 estimates" is data).
    r'|\bmap(?:\s+session)?\s+to\s+(?:the\s+)?(202[46])(?=\s*(?:sessions?\b|maps?\b|boundar|[.,;:!?)]|$)|\s+(?:and|instead|please|now|too|so|then|for|with)\b)')
# Narrow direction: map [session] from X to Y, or from the X map to Y [map/one].
# The map anchor is required so a data-period "from X to Y" never selects a map.
_MAP_SWITCH=re.compile(r'\b(?:map(?:\s+session)?\s+from\s+(202[46])|from\s+(?:the\s+)?(202[46])\s+map)'
    r'\s+(?:to|with|for)\s+(?:the\s+)?(202[46])(?:\s+(?:map|one))?\b')
# Narrow exclusion immediately before a map phrase ("not on the 2024 map", "instead of the 2024 map").
_MAP_NEGATION=re.compile(r"\b(?:not|never|without|excluding|exclude|instead\s+of|rather\s+than|don'?t|do\s+not|doesn'?t|won'?t|no\s+need\s+to|avoid|stop)\s+"
    r"(?:(?:use|using|on|in|with|show|showing|switch|switching|change|changing|put|putting|move|moving|set|setting|turn|turning|display|displaying|draw|drawing|go|going)\s+)?"
    r"(?:(?:back\s+|over\s+)?to\s+)?(?:the\s+|a\s+)?$")
# "Don't change/alter/touch the 2024 map" KEEPS that map (not an exclusion); only a "to"-directed phrase is excluded.
_MAP_KEEP=re.compile(r"\b(?:don'?t|do\s+not|never)\s+(?:change|alter|modify|touch|reset|replace)\s+(?:the\s+|this\s+|our\s+)?$")
# Any other negation earlier in the same clause cannot be attributed to the map phrase: refuse rather than guess.
_MAP_NEGATION_NEARBY=re.compile(r"\b(?:not|never|no|without|don'?t|do\s+not|doesn'?t|won'?t|avoid|stop)\b[^.;:!?,]{0,50}$")

def _map_mentions(u):
    """(selected, excluded) explicit map years; a switch source and a negated phrase are exclusions."""
    selected,excluded=set(),set();spans=[]
    for m in _MAP_SWITCH.finditer(u):
        # A negated switch ("don't switch the map from 2026 to 2024") states neither year as the request: refuse.
        if _MAP_NEGATION_NEARBY.search(u[max(0,m.start()-60):m.start()]):raise LanguageError('explicit_map_ambiguous')
        excluded.add(int(m.group(1) or m.group(2)));selected.add(int(m.group(3)));spans.append(m.span())
    for m in _MAP_YEAR.finditer(u):
        if any(a<=m.start()<b for a,b in spans):continue
        year=int(m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5))
        before=u[max(0,m.start()-60):m.start()]
        if _MAP_KEEP.search(before) and not m.group(5):selected.add(year)
        elif _MAP_NEGATION.search(before):excluded.add(year)
        elif _MAP_NEGATION_NEARBY.search(before):raise LanguageError('explicit_map_ambiguous')
        else:selected.add(year)
    return selected,excluded

def resolve_map_session(prepared,wire_map):
    """Return the proposal map session; never infers it from a district or data period."""
    u=prepared['provider_context']['utterance'].lower().replace('’',"'");c=prepared['context']
    selected,excluded=_map_mentions(u)
    # Two selected maps without a direction, or a year both selected and excluded: do not guess.
    if len(selected)>1 or selected&excluded:raise LanguageError('explicit_map_ambiguous')
    if wire_map!=0:
        if (selected and wire_map not in selected) or wire_map in excluded:raise LanguageError('explicit_map_conflict')
        if selected:return wire_map
    elif selected:raise LanguageError('explicit_map_unreported')
    confirmed,draft=c['confirmed_plan'],c['draft_plan']
    if confirmed is not None:
        if draft is not None and draft['map_session']!=confirmed['map_session']:raise LanguageError('invalid_provider_map_context')
        resolved=confirmed['map_session']
    # Held rule: confirmed, else the visible unsaved draft. A draft map is kept, never reset to the default.
    elif draft is not None:resolved=draft['map_session']
    else:resolved=NEW_PLAN_MAP_SESSION
    if wire_map!=0 and wire_map!=resolved:
        # The other year of the two-map domain is stated only by an explicit exclusion ("not on the 2024
        # map"). Otherwise a model year that no map phrase states never replaces the held/default map
        # (no inference from geography IDs, boundaries or data periods).
        if not excluded:raise LanguageError('explicit_map_unstated_change')
        return wire_map
    if resolved in excluded:raise LanguageError('explicit_map_conflict')
    return resolved

def ordinary_plan(wire,core,map_session=None):
    if not 1<=len(wire['steps'])<=8:raise LanguageError('invalid_plan_steps')
    steps=[]
    for s in wire['steps']:
        op=s['operation'];m,g,p,o=(s[k] for k in ('metric_ids','comparison_geography','program_ids','observation_ids'))
        if op=='profile' and not(g or p or o):a={'metric_ids':m or None}
        elif op=='compare' and 1<=len(m)<=4 and g and not(p or o):a={'metric_ids':m,'comparison_geography':g}
        elif op=='program_evidence' and 1<=len(p)<=5 and not(m or g or o):a={'program_ids':p}
        elif op=='outreach_lead' and len(p)==1 and p[0] in ('kupuna_care_hi','snap_hi','medquest_hi','hcv_honolulu') and not(m or g or o):a={'program_id':p[0]}
        elif op=='administrative_evidence' and 1<=len(o)<=8 and not(m or g or p):a={'observation_ids':o}
        else:raise LanguageError('inapplicable_provider_fields')
        if g and g not in core.profiles:raise LanguageError('unavailable_comparator')
        steps.append({'step_id':s['step_id'],'operation':op,'args':a})
    plan={'district':{'state_fips':'15',**wire['district'],'boundary_session':2024},
        'map_session':int(wire['map_session']) if map_session is None else map_session,'issue_id':wire['issue_id'],'service_area_id':wire['service_area_id'] or None,'steps':steps}
    try:validate_plan(plan,core)
    except InvestigationError:raise LanguageError('invalid_provider_plan') from None
    return plan

# Small explicit-constraint checks supplement the model; they do not execute a Plan.
PROGRAM_PATTERNS={'snap_hi':r'\b(?:snap|food stamps?)\b','wic_hi':r'\bwic\b','medquest_hi':r'\b(?:med[ -]?quest|medicaid|quest integration)\b',
                  'kupuna_care_hi':r'\b(?:k[ūu]puna care)\b','hcv_honolulu':r'\b(?:section 8|housing choice voucher|hcv)\b'}
METRIC_PATTERNS={'poverty_rate_65_plus':r'\b(?:senior|elderly|older adult|65\+?|65 and over|65 years? and over)[\w\s,+-]{0,30}\bpoverty\b|\bpoverty[\w\s,+-]{0,30}\b(?:senior|65|older adult)',
 'poverty_rate_all_people':r'\b(?:all[- ]people|overall|all ages)[\w\s]{0,15}poverty\b|\bpoverty rate[\w\s]{0,15}\ball people\b',
 'median_household_income':r'\bmedian household income\b','median_age':r'\bmedian age\b',
 'population_65_plus':r'\b(?:population|people|residents)[\w\s]{0,12}(?:65|age 65)|\b(?:senior|older adult) population\b',
 'total_population':r'\btotal population\b','unemployed':r'\bunemployed\b','unemployment_rate':r'\bunemployment rate\b'}

POVERTY_METRICS={'poverty_rate_65_plus','poverty_rate_all_people'}
# Staff-facing recipe names come from the app's own issue labels (render._ISSUE_NAMES: the issue selector and printed
# brief) plus the typed-request alias, never from evaluation wording. A following lead/hypothesis/step/reference noun
# names one step of that kind, not the recipe ("a SNAP outreach lead").
from .render import _ISSUE_NAMES
RECIPE_ALIASES={'aging_at_home':('aging at home',),'food_assistance_outreach':('food assistance outreach',)}
RECIPE_LABELS={v.rsplit('/',1)[0]:(label,*RECIPE_ALIASES.get(v.rsplit('/',1)[0],())) for v,label in _ISSUE_NAMES.items() if v!='custom/1'}
RECIPE_NAMES={issue:r'\b(?:'+'|'.join(re.escape(n.lower()).replace(r'\-','[- ]') for n in names)+r')\b(?!\s+(?:leads?|hypothes[ie]s|steps?|references?|cards?)\b)'
              for issue,names in RECIPE_LABELS.items()}
def _positive_recipes(utterance,admitted=None):
    """Recipes the utterance names positively. A negated, removed or replaced mention ("not/instead of/rather than SNAP
    outreach", "switch/replace the SNAP outreach ... with") names nothing, using the existing negation/removal helpers."""
    out=set()
    for issue,pat in RECIPE_NAMES.items():
        if admitted is not None and issue+'/1' not in admitted:continue
        for m in re.finditer(pat,utterance):
            before=utterance[max(0,m.start()-60):m.start()]
            source=_REPLACE_SOURCE_BEFORE.search(before) and not re.search(r'\b(?:to|with|for|into)\s+(?:the\s+|a\s+)?$',before)  # target stays positive
            if (_NEGATED_BEFORE.search(before[-30:]) or _REMOVAL_BEFORE.search(before) or source
                    or re.search(r'\bstop\s+(?:the\s+)?$',before) or _NEGATED_AFTER.match(utterance[m.end():])):continue
            out.add(issue);break
    return out
def _recipe_build(issue):
    from .interpret import recipe,food_assistance_recipe
    return {'aging_at_home':recipe,'food_assistance_outreach':food_assistance_recipe}[issue]
# A population stated next to "poverty" names one admitted poverty measure. Only a bare,
# population-free "poverty" is ambiguous (prompt: generic poverty needs metric clarification).
_SENIOR=r'(?:k[ūu]puna|elders?|seniors?|elderly|older (?:adults?|residents?|people)|aged? 65|65\+?|65 and over)'
_ALL=r'(?:all (?:people|ages|residents)|overall|everyone|general population)'
POVERTY_POPULATIONS={'poverty_rate_65_plus':re.compile(r'\b'+_SENIOR+r'[\w\s,+-]{0,30}\bpoverty\b|\bpoverty\b[\w\s,+-]{0,30}\b'+_SENIOR),
                     'poverty_rate_all_people':re.compile(r'\b'+_ALL+r'[\w\s,+-]{0,30}\bpoverty\b|\bpoverty\b[\w\s,+-]{0,30}\b'+_ALL+r'\b')}
# Provenance for a proposal whose utterance names no house/senate+number. The district comes only
# from an unambiguous utterance reference or from held context: the confirmed plan, else (no
# confirmed plan) the visible unconfirmed draft. A divergent confirmed/draft pair is already a
# control conflict. Missing, chamber-only or otherwise ambiguous geography never becomes a
# model-chosen district. All refusals use the uncertain explicit_ prefix.
_ABBREVIATED_DISTRICT=re.compile(r'\b([hs])d\s*-?\s*0*(\d{1,2})\b')
_BARE_DISTRICT=re.compile(r'\bdistrict\s*(?:#\s*|no\.?\s*|number\s+)?0*(\d{1,2})\b')
_CHAMBER_ONLY=re.compile(r'\b(?:a|an|the|this|that|my|our|same|state)\s+(house|senate)\b|\b(house|senate)\s+(?:district|seat)s?\b')

# Non-State-legislative district wording (congressional, council, school, U.S. House, ...) names geography
# outside the admitted State House/Senate catalog. Its number never borrows a held or stated chamber.
_NONLEGISLATIVE=re.compile(r"\b(?:congressional|council|county|school|precinct|neighborhood(?:\s+board)?|police|fire|water|zoning|"
    r"census|planning|judicial|complex[- ]area|board|federal|u\.\s?s\.|united states)\s+(?:house\s+|senate\s+)?district\b"
    r"|(?:\bfederal|\bu\.\s?s\.|\bunited states|\bcongressional)\s+(?:house|senate)\b|\bcd\s*-?\s*\d{1,2}\b"
    r"|\bcongress(?:ional)?\s+(?:[\w-]+\s+){0,2}?(?:district|seat|member|representative|\d)|\b(?:1st|2nd|first|second)\s+congressional\b")
# Period-less "US House/Senate/Congress" is read only in its capitalized form on the original text, so the
# pronoun ("show us House district 28") never matches.
_US_FEDERAL=re.compile(r'\bUS\s+(?:[Hh]ouse|[Ss]enate|[Cc]ongress)\b')

def _district_clarification(chambers,number=None):
    # Missing or chamber-ambiguous district: typed choices only, never a model-chosen district. Progressive: with no
    # number and no single stated chamber, ask the chamber first (c_house/c_senate); a stated chamber gets that chamber's
    # complete district list; a bare number gets that number in each chamber. Never a partial or place-derived subset.
    if number is None and set(chambers)>={'house','senate'}:
        return Recovery('explicit_district_missing','clarify',reason='missing_context',field='chamber',choices=('c_house','c_senate'))
    choices=[f'd_{c[0]}{n:03}' for c in ('house','senate') if c in chambers
             for n in range(1,(51 if c=='house' else 25)+1) if number is None or n==int(number)]
    return Recovery('explicit_district_missing','clarify',reason='missing_context',field='district',choices=choices)

# Actual district-number mentions only: "House 5"/"HD 5" (explicit) and a number list after "district(s)"/"seat(s)"
# ("district 1 or 2", "seat 3"). Ages, counts and other numbers ("kids under 5") are not district mentions.
_BARE_DISTRICT_LIST=re.compile(r'\b(?:districts?|seats?)\s*(?:#\s*|no\.?\s*|number\s+)?0*(\d{1,2})\b((?:\s*(?:,|or|and|/)\s*0*\d{1,2}\b)*)')
# The asker's own district is identity, not plan context: the visible default/held district never answers it.
_OWN_DISTRICT=re.compile(r"\b(?:my|our)\s+(?:own\s+)?(?:(?:house|senate)\s+)?(?:district|seat)\b|\bthe\s+(?:district|seat)\s+(?:i|we)\s+(?:represent|serve|hold)\b")
def _district_mentions(u):
    """(explicit {(chamber, n)}, bare {n}) from a canonical lower-case utterance."""
    explicit={(m.group(1),int(m.group(2))) for m in re.finditer(r'\b'+_DISTRICT+r'\b',u)}
    bare=set()
    for m in _BARE_DISTRICT_LIST.finditer(u):
        numbers={int(x) for x in re.findall(r'\d+',m.group(1)+(m.group(2) or ''))}
        chamber=re.search(r'\b(house|senate)\s*$',u[:m.start()])
        if chamber:explicit|={(chamber.group(1),n) for n in numbers}
        else:bare|=numbers
    return explicit,bare
def grounded_district_choices(prepared,choices):
    """A model district clarification may offer only districts the request grounds: an explicit mention, a bare
    mentioned number in either chamber, or the held (confirmed/draft) district. A model-derived place or identity
    subset ("around Hilo", "the district I represent") is not a verified mapping: the progressive server clarification
    replaces it. Returns None when grounded, else the Recovery."""
    c=prepared['context'];u=_canonical_districts(prepared['provider_context']['utterance'].lower())
    explicit,bare=_district_mentions(u)
    # A district in a comparator role ("against district 10", "than in district 10", "the State and district 10",
    # "against Senate 10") never grounds a primary-district choice. A model district clarification that offers one gets
    # the typed comparator clarification instead (as on the proposal path): both admitted chambers for a bare number, the
    # named chamber for an explicit one. A district that is also named without a comparator role still grounds.
    bare_roles={};explicit_roles={};primary=set()
    for n in _bare_comparators(u):bare_roles[n]=[_gid(ch,n) for ch in ('house','senate')]
    memo={}
    for m in re.finditer(r'\b'+_DISTRICT+r'\b',u):
        alias=f'd_{m.group(1)[0]}{int(m.group(2)):03}'
        if _comparator_role(u,m,memo) and not _is_negated(u,m):explicit_roles[alias]=_gid(m.group(1),m.group(2))
        else:primary.add(alias)
    offered=[]
    for a in choices:
        if a in primary:continue
        if a in explicit_roles:offered.append(explicit_roles[a])
        elif int(a[3:]) in bare_roles:offered.extend(bare_roles[int(a[3:])])
    if offered:
        # Only admitted catalog geographies are offered (no Senate 26-51).
        return Recovery('explicit_comparator_chamber_missing','clarify',reason='missing_context',field='comparator',
                        choices=[x for x in dict.fromkeys('g_'+g for g in offered) if x in prepared['choices']])
    ok={f'd_{ch[0]}{n:03}' for ch,n in explicit}|{f'd_{ch[0]}{n:03}' for n in bare for ch in ('house','senate')}
    for p in (c['confirmed_plan'],c['draft_plan']):
        if p and not _OWN_DISTRICT.search(u):ok.add(f"d_{p['district']['chamber'][0]}{p['district']['code']}")
    if all(a in ok for a in choices):return None
    original=prepared['provider_context']['utterance']
    if re.search(_NONLEGISLATIVE.pattern,original,re.I) or _US_FEDERAL.search(original):raise LanguageError('nonlegislative_district_unproven')
    chambers={m.group(1) or m.group(2) for m in _CHAMBER_ONLY.finditer(u)}
    number=next(iter(bare)) if len(bare)==1 and not explicit else None
    return _district_clarification(chambers or ('house','senate'),number)
def missing_district(prepared):
    """The progressive district clarification when request/context prove the district is missing: no confirmed or
    draft plan, no actual district-number mention (ages and counts do not count), no non-legislative district. Else None (the model's clarification
    stands). Derived only from the request; it never chooses a district."""
    c=prepared['context'];original=prepared['provider_context']['utterance']
    if c['confirmed_plan'] is not None or c['draft_plan'] is not None:return None
    u=_canonical_districts(original.lower())
    if any(_district_mentions(u)):return None
    if re.search(_NONLEGISLATIVE.pattern,original,re.I) or _US_FEDERAL.search(original):return None
    return _district_clarification({m.group(1) or m.group(2) for m in _CHAMBER_ONLY.finditer(u)} or ('house','senate'))

def _canonical_districts(u):
    # Explicit chamber+number spellings read exactly as "house N"/"senate N" for every district check.
    u=_ABBREVIATED_DISTRICT.sub(lambda m:('house ' if m.group(1)=='h' else 'senate ')+m.group(2),u)
    u=re.sub(r'\b(house|senate)\s+district\s+(?:number\s+|no\.?\s*|#\s*)0*(\d{1,2})\b',r'\1 \2',u)
    return re.sub(r'\bdistrict\s+(?:number\s+|no\.?\s*|#\s*)?0*(\d{1,2})\s+(?:in|of)\s+the\s+(?:state\s+)?(house|senate)\b',r'\2 \1',u)

def district_provenance(utterance,context,plan):
    proposed=(plan['district']['chamber'],plan['district']['code'])
    abbreviated=[('house' if m.group(1)=='h' else 'senate',f'{int(m.group(2)):03}') for m in _ABBREVIATED_DISTRICT.finditer(utterance)]
    if abbreviated:
        if proposed!=abbreviated[0]:raise LanguageError('explicit_district_conflict')
        return
    held=context['confirmed_plan'] or context['draft_plan']
    current=(held['district']['chamber'],held['district']['code']) if held else None
    chambers={m.group(1) or m.group(2) for m in _CHAMBER_ONLY.finditer(utterance)}
    # A comparator-positioned bare number ("against district 20") never names the primary; the comparator checks
    # below offer its chamber choice.
    memo={};numbers=[f'{int(m.group(1)):03}' for m in _BARE_DISTRICT.finditer(utterance) if not _comparator_role(utterance,m,memo)]
    if chambers and proposed[0] not in chambers:raise LanguageError('explicit_district_conflict')
    if numbers:
        # A number without a chamber takes its chamber only from one stated chamber, or from the number itself when
        # only one chamber has it (House 26-51). Held context never supplies the chamber of a newly named bare number
        # (same policy as a bare comparator number): an ambiguous one clarifies with that number in each chamber.
        possible=[c for c in ('house','senate') if int(numbers[0])<=(51 if c=='house' else 25)]
        chamber=next(iter(chambers)) if len(chambers)==1 else possible[0] if not chambers and len(possible)==1 else None
        if chamber is None:raise _district_clarification(chambers or ('house','senate'),numbers[0])
        if proposed!=(chamber,numbers[0]):raise LanguageError('explicit_district_conflict')
        return
    if current is None or _OWN_DISTRICT.search(utterance):raise _district_clarification(chambers or ('house','senate'))
    # Without an explicit district the held district is never silently replaced.
    if proposed!=current:raise LanguageError('explicit_district_unstated_change')

# Directed order: a district mention is a comparator when a comparison cue directly precedes it
# ("against/versus/vs/minus/than/relative to/compared with|to", or "compare ... with|to|against" in the same
# clause) or directly follows it ("as the baseline", "serves as the comparison"). Exactly one unmarked
# district is the primary. Only comparator mentions plus a held plan keep the held primary. A single named
# district with no cue is the primary; two or more DISTINCT districts with no comparator role established fail
# closed for every ordering (mention order is never a role). Any other mix also fails closed.
_COMPARATOR_BEFORE=re.compile(r'\b(?:against|versus|vs\.?|minus|than(?:\s+(?:in|for|at))?|relative to|compared (?:with|to)(?:\s+(?:that|those)\s+of)?|comparison (?:with|to)|benchmarked (?:against|to))\s+(?:the\s+|an?\s+|our\s+)?$')
# The compare clause is bounded: no comma/clause punctuation, no conjunction or second verb, at most 40 chars.
_CLAUSE_STOP=r'(?!\b(?:and|then|but|or|also|plus|switch|move|change|go|use|show|profile|keep|add)\b)[^.;:!?,]'
_COMPARE_CLAUSE=re.compile(r'\bcompar(?:e|es|ed|ing)\b(?:'+_CLAUSE_STOP+r'){0,40}?\b(?:with|to|against)\s+(?:the\s+)?$')
# "switch/move/change [the district] to X", "go to X": X is explicitly the new primary.
_NAVIGATE_BEFORE=re.compile(r'\b(?:switch|move|change|go|jump|turn)\s+(?:the\s+(?:district|plan|focus)\s+)?(?:over\s+|back\s+)?to\s+(?:the\s+)?$')
# Role-noun wording assigns a comparison role without a cue this guard can attribute to one mention.
_ROLE_PHRASE=re.compile(r'\b(?:for|as)\s+(?:a\s+|the\s+|our\s+)?(?:comparison|comparator|baseline|benchmark|reference)\b'
    r'|\b(?:baseline|benchmark|reference|comparator)\s+(?:of|is)\b|\b(?:the|a|an|our)\s+(?:comparison|comparator|baseline|benchmark|reference)\s+(?:for|of)\b'
    r'|\b(?:house|senate)\s*\d{1,2}\s+(?:benchmark|baseline|comparator|reference)\b')
# A negated mention ("not for House 30", "exclude House 30") is neither primary nor comparator.
_NEGATED_MENTION=re.compile(r'\b(not|no|exclude|excluding|except|without|never|skip|drop|remove)\s+(?:for\s+|with\s+|in\s+|on\s+|to\s+)?(?:the\s+)?$')
_COMPARATOR_AFTER=re.compile(r'^\s*,?\s*(?:(?:as|is|serves?\s+as|will\s+serve\s+as|acts?\s+as|for)\s+(?:the\s+|a\s+|an\s+|our\s+)?|(?:the|a|an|our)\s+)'
    r'(?:baseline|comparator|benchmark|reference|comparison)\b')
# A role noun directly governing the next mention ("the comparator to X", "comparison district to X", "baseline of X").
_ROLE_GOVERNS_BEFORE=re.compile(r'\b(?:comparator|comparison|baseline|benchmark|reference)(?:\s+district)?\s+(?:to|as|is|of|=|:)\s+(?:be\s+)?(?:the\s+)?$')
# A negated compare verb in the same bounded clause excludes its mention ("don't compare with X", "stop comparing to X").
_NEGATED_COMPARE=re.compile(r"\b(don['\u2019]?t|do not|never|stop|no longer|not|avoid|without|skip|remove|drop|delete|exclude|no need to)\s+(?:(?:want|need|have)\s+to\s+|the\s+)?(?:compar\w*|benchmark\w*)\b(?:"+_CLAUSE_STOP+r"){0,40}?\b(?:with|to|against)\s+(?:the\s+)?$")
# A negated removal/avoidance verb ("don't remove the comparison with X") cannot be proven either way: fail closed.
_REMOVAL_VERBS=('avoid','without','skip','remove','drop','delete','exclude','stop','no longer')
# Any negative token earlier in the same bounded clause (no conjunction/punctuation crossing) negates the removal.
_NEGATED_REMOVAL_BEFORE=re.compile(r"\b(?:\w+n['\u2019]t|not|no|never|without|cannot|nor|neither)\b(?:"+_CLAUSE_STOP+r"){0,30}$")
def _is_negated(utterance,m):
    prefix=utterance[:m.start()];window=prefix[-90:];neg=_NEGATED_COMPARE.search(window)
    near=prefix[-30:];mention=_NEGATED_MENTION.search(near)
    for match,base,verb in ((neg,len(prefix)-len(window),neg and neg.group(1)),(mention,len(prefix)-len(near),mention and mention.group(1))):
        if match and verb in _REMOVAL_VERBS+('excluding',) and _NEGATED_REMOVAL_BEFORE.search(prefix[:base+match.start()][-30:]):
            raise LanguageError('explicit_comparator_removal_ambiguous')
    return bool(mention or neg)
_COMPARISON_WORDS=r'\b(?:compar(?:e|ed|es|ing|ison)|versus|vs|minus|against|relative to|than|baseline|benchmark(?:ed)?)\b'
_DISTRICT=r'(house|senate)\s*(?:district\s*)?0*(\d{1,2})'
# Explicit replacement wording: (old, new) district groups. Never inferred from mention order alone.
_REPLACEMENTS=(
    (re.compile(r'\b(?:replace|change|switch|move|swap)\s+(?:(?:this|the|our|my)\s+(?:plan|district|brief|case)\s+)?(?:from\s+)?'+_DISTRICT+r'\s+(?:with|to|for)\s+'+_DISTRICT+r'\b'),(1,2),(3,4)),
    (re.compile(r'\b'+_DISTRICT+r'\s+instead\s+of\s+'+_DISTRICT+r'\b'),(3,4),(1,2)),
    (re.compile(r'\binstead\s+of\s+'+_DISTRICT+r'\s*,?\s*(?:use\s+|show\s+)?'+_DISTRICT+r'\b'),(1,2),(3,4)),
    (re.compile(r'\bnot\s+'+_DISTRICT+r'\s*(?:[-–—,;:]|but)\s*(?:use\s+)?'+_DISTRICT+r'\b'),(1,2),(3,4)))

def _key(m):return (m.group(1),int(m.group(2)))
def _navigates(utterance,m):return bool(_NAVIGATE_BEFORE.search(utterance[:m.start()][-50:]))
def _comparator_role(utterance,m,memo=None):
    """A district mention (bare "district N" not preceded by a chamber, or explicit "House N") in a comparator role: a
    directed cue, or a peer joined by and/or/plus directly after a directed comparator (the State, a county or a
    district). Shared by the clarification grounding, district_provenance and the proposal comparator recovery; each
    applies its own negation rule."""
    # Call-local memo (a caller looping over one utterance may pass its own dict; nothing is kept after it returns): a
    # peer's role reads its antecedent's role, so each mention is evaluated once and the mention list is built once.
    memo={} if memo is None else memo
    if None not in memo:memo[None]=[*re.finditer(r'\b'+_DISTRICT+r'\b',utterance),*_BARE_DISTRICT_LIST.finditer(utterance)]
    mentions=memo[None]
    def role(x):
        key=(x.start(),x.end())
        if key not in memo:
            if re.search(r'\b(?:house|senate)\s*$',utterance[:x.start()]):memo[key]=False
            elif _is_comparator(utterance,x):memo[key]=True
            elif _navigates(utterance,x):memo[key]=False
            else:
                earlier=[y for y in mentions if y.end()<=x.start()]
                # A negated antecedent passes no role on, as for the State and county antecedents in _peer_comparator.
                memo[key]=_peer_comparator(utterance,x,earlier,[role(y) and not _is_negated(utterance,y) for y in earlier])
        return memo[key]
    return role(m)
def _bare_comparators(utterance):
    """Chamberless bare district numbers in a (non-negated) comparator role: every number of a "district(s) N[, M or K]"
    list whose head has the role. The one reading used by the clarification grounding and the proposal recovery."""
    out=[];memo={}
    for m in _BARE_DISTRICT_LIST.finditer(utterance):
        if _comparator_role(utterance,m,memo) and not _is_negated(utterance,m):out+=[int(x) for x in re.findall(r'\d+',m.group(1)+(m.group(2) or ''))]
    return list(dict.fromkeys(out))
def _is_comparator(utterance,m):
    if _navigates(utterance,m):return False
    prefix=utterance[:m.start()]
    return bool(_COMPARATOR_BEFORE.search(prefix[-60:]) or _COMPARE_CLAUSE.search(prefix) or _ROLE_GOVERNS_BEFORE.search(prefix[-50:])
                or _COMPARATOR_AFTER.search(utterance[m.end():m.end()+50]))

# Coordinated peer: a district joined ("and/or/plus") directly after a directed comparator (the State, a county or a
# comparator district) is a further comparator, unless it opens its own comparison clause ("..., and House 12 with X").
# Only an explicit conjunction joins peers; a bare comma may open the main clause ("Compare to Senate 25, House 28 ...").
# Directed State antecedent for a peer district (not "between/next to/alongside the State and district N").
_STATE_DIRECTED=re.compile(r'\b(?:with|(?<!next\s)to|against|versus|vs\.?|than(?:\s+(?:in|for|at))?)\s+$')
_PEER_JOIN=re.compile(r'(?:\s*,\s*(?:and|or|plus)\s+|\s+(?:and|or|plus|&)\s+)(?:also\s+)?(?:the\s+)?$')
_OWN_CLAUSE_AFTER=re.compile(r"^\s*(?:[\w-]+\s+){0,3}?(?:with|against|versus|vs\.?|compared|relative|to|than)\b")
def _peer_comparator(utterance,m,mentions,marked):
    join=_PEER_JOIN.search(utterance[:m.start()][-30:])
    if not join or _OWN_CLAUSE_AFTER.match(utterance[m.end():m.end()+40]):return False
    end=m.start()-len(join.group(0))
    for other,is_cmp in zip(mentions,marked):
        if other.end()==end:return is_cmp
    for s in _STATE_MENTION.finditer(utterance):
        if s.end()==end:
            before=utterance[max(0,s.start()-60):s.start()]
            directed=_STATE_DIRECTED.search(before) or _is_comparator(utterance,s) or _peer_comparator(utterance,s,mentions,marked)
            return bool(directed and not _REMOVAL_BEFORE.search(before) and not _is_negated(utterance,s))
    for _gids,a,b in _county_groups(utterance):
        if b==end:return _is_comparator(utterance,_Span(a,b)) and not _is_negated(utterance,_Span(a,b))
    return False

def _directed_districts(utterance,mentions,held,retargets=()):
    """(expected primary (chamber,code), comparator mentions). retargets: mentions proven to be the focused compare
    step's new comparator."""
    marked=[m in retargets or _is_comparator(utterance,m) for m in mentions]
    for i,m in enumerate(mentions):
        if not marked[i] and not _navigates(utterance,m):marked[i]=_peer_comparator(utterance,m,mentions[:i],marked[:i])
    unmarked={_key(m) for m,c in zip(mentions,marked) if not c}
    navigated={_key(m) for m in mentions if _navigates(utterance,m)}
    if navigated:
        # An explicit switch names the primary; every other district must carry a comparator cue.
        if len(navigated)!=1 or unmarked-navigated:raise LanguageError('explicit_district_ambiguous')
        primary=next(m for m in mentions if _key(m) in navigated)
        return (primary.group(1),f'{int(primary.group(2)):03}'),[m for m in mentions if _key(m)!=_key(primary)]
    if not any(marked) and len(unmarked)>=2 and _ROLE_PHRASE.search(utterance):raise LanguageError('explicit_district_ambiguous')
    if not any(marked):
        # No comparator role was proven: never pick a primary by mention order among distinct districts.
        if len({_key(m) for m in mentions})>1:raise LanguageError('explicit_district_ambiguous')
        m=mentions[0];return (m.group(1),f'{int(m.group(2)):03}'),mentions[1:]
    if len(unmarked)==1:
        primary=next(m for m,c in zip(mentions,marked) if not c)
        return (primary.group(1),f'{int(primary.group(2)):03}'),[m for m in mentions if _key(m)!=_key(primary)]
    if not unmarked and len({_key(m) for m in mentions})==1:
        # One comparator-only district: the primary comes from held context, else it is proven missing.
        if held is None:raise _district_clarification(('house','senate'))
        return (held['district']['chamber'],held['district']['code']),list(mentions)
    raise LanguageError('explicit_district_ambiguous')

def _gid(chamber,number):return f'HI-{chamber.upper()}-{int(number):03}-2024'

# Focused-step retarget: "point/aim/set/change/switch this step|comparison at|to X" names X as the new comparator of
# the focused step. It applies only when trusted context focuses a held compare step; the proposal must then put X in
# exactly that step, and the held primary district stays. Without such a focus the wording proves nothing (fail closed).
_STEP_RETARGET_BEFORE=re.compile(r'\b(?:point|aim|retarget|repoint|redirect|set|change|switch|move|turn)\s+(?:this|that|the)\s+(?:focused\s+|selected\s+)?'
    r'(?:step|comparison|comparator)\s+(?:back\s+|over\s+)?(?:at|to|toward|towards|on|onto)\s+(?:the\s+)?$')
def _focused_compare(context,held):
    """The step a "this step/comparison" retarget names: the explicitly focused held compare step, else the held plan's
    only compare step (unambiguous and visible). None when neither is proven."""
    steps=(held or {'steps':[]})['steps'];focus=context['focused_step_id']
    if focus:
        step=next((s for s in steps if s['step_id']==focus),None)
        return step if step is not None and step['operation']=='compare' else None
    compares=[s for s in steps if s['operation']=='compare']
    return compares[0] if len(compares)==1 else None
def _negated_before(utterance,start):
    # Any negative token earlier in the same bounded clause (existing helper): the edit is not requested.
    return bool(_NEGATED_REMOVAL_BEFORE.search(utterance[:start][-40:]))

# Metric edits: a metric named as a removal/negation or replacement source is not required; it must be absent.
_REMOVAL_BEFORE=re.compile(r'\b(?:remove|drop|delete|omit|without|exclude|excluding|no longer|instead of|rather than|not)\s+(?:the\s+|a\s+|any\s+)?(?:[\w-]+\s+){0,2}$')
_REPLACE_BEFORE=re.compile(r'\b(replace|swap|trade|change|switch)\b[^.;]{0,40}$')
_REPLACE_AFTER=re.compile(r'^\s*(?:[\w-]+\s+){0,2}?(?:with|to|by|into)\b')
_SWAP_AFTER=re.compile(r'^\s*(?:[\w-]+\s+){0,2}?for\b')
_NOT_JUST=re.compile(r'\bnot\s+(?:just|only|merely)\s+(?:the\s+)?$')
def _removed_metrics(utterance):
    out=set()
    for metric,pat in METRIC_PATTERNS.items():
        for m in re.finditer(pat,utterance):
            prefix=utterance[max(0,m.start()-60):m.start()];after=utterance[m.end():];verb=_REPLACE_BEFORE.search(prefix)
            # Only the replacement SOURCE is removed: no other named measure between the verb and this one.
            source=verb and not any(re.search(p,prefix[verb.end():]) for p in METRIC_PATTERNS.values())
            if ((_REMOVAL_BEFORE.search(prefix) and not _NOT_JUST.search(prefix))
                    or (source and (_REPLACE_AFTER.search(after) or (verb.group(1) in ('swap','trade') and _SWAP_AFTER.search(after))))):out.add(metric)
    return out

# Service areas are staff inquiry scopes: a proposal keeps the held one (confirmed, else draft) unless the
# utterance names one as the service area or removes it. County comparators ("Maui County") and statewide
# figures ("the statewide rate") never name a service area.
SERVICE_AREA_PATTERNS={'statewide':r'\bstatewide\b','oahu':r'\boahu\b','maui':r'\bmaui\b','molokai':r'\bmolokai\b',
    'lanai':r'\blanai\b','kauai':r'\bkauai\b','kalawao':r'\bkalawao\b','hawaii_island':r'\b(?:hawaii island|island of hawaii|big island)\b'}
_SERVICE_AREA_WORDING=re.compile(r'\bservice[- ]areas?\b')
_SERVICE_AREA_REMOVAL=re.compile(r'\b(?:remove|clear|drop|without|no|reset)\s+(?:the\s+|a\s+|any\s+)?service[- ]areas?\b')
_NOT_AREA_AFTER=re.compile(r'^\s+(?:county|rates?|averages?|levels?|figures?|values?|comparisons?|totals?|benchmarks?|numbers?|percentages?|medians?)\b')
# County comparator names: "<name> County", "County of <name>", "City and County of Honolulu".
COUNTY_GEOGRAPHIES={'HI-COUNTY-001-2024':'hawaii','HI-COUNTY-003-2024':'honolulu','HI-COUNTY-005-2024':'kalawao',
    'HI-COUNTY-007-2024':'kauai','HI-COUNTY-009-2024':'maui'}
_CN=r'(?:hawaii|honolulu|kalawao|kauai|maui)'
# One county-name grammar for every county check: "<name> County", "County of <name>" (also "City and County of
# Honolulu"), and a shared plural noun over a list ("Maui and Kauai counties", "Maui, Kauai and Hawaii counties").
_CN_LIST=_CN+r'(?:\s*,\s*'+_CN+r')*(?:\s*,?\s*(?:and|or|&)\s+'+_CN+r')?'
# List tail: "<A> County", "<A> and <B> County/counties"; list head: "County/counties of <A>[, <B>] [and <C>]".
# A bare island name without a county word is never a county; "State of Hawaii" is not Hawaii County.
# A plural tail needs two or more names: "other Hawaii counties" never names Hawaii County.
_CN_LIST2=_CN+r'(?:\s*,\s*'+_CN+r')*\s*,?\s*(?:and|or|&)\s+'+_CN
_COUNTY_GROUP=re.compile(r'(?<!state\sof\s)\b('+_CN_LIST2+r')\s+counties\b|(?<!state\sof\s)\b('+_CN_LIST+r')\s+countys?\b'
    r'|\bcount(?:y|ies)\s+of\s+(?:the\s+)?('+_CN_LIST+r')\b')
def _county_groups(plain):
    """(county geography IDs, start, end) for each county mention; a shared-noun list is one mention."""
    by_name={name:gid for gid,name in COUNTY_GEOGRAPHIES.items()};out=[]
    for m in _COUNTY_GROUP.finditer(plain):
        names=re.findall(_CN,m.group(1) or m.group(2) or m.group(3))
        out.append(([by_name[n] for n in names],m.start(),m.end()))
    return out
# Hawaii County is coextensive with Hawaii Island, so "the Big Island" names it unambiguously, but only where a
# comparator is being named or removed (elsewhere it may be a service area or orientation label).
_COEXTENSIVE_ISLAND=re.compile(r'\b(?:big island|hawaii island|island of hawaii)\b')
def _island_county_groups(plain):
    out=[]
    for m in _COEXTENSIVE_ISLAND.finditer(plain):
        before=plain[max(0,m.start()-80):m.start()]
        if _is_comparator(plain,m) or _is_negated(plain,m) or _REMOVAL_BEFORE.search(before[-60:]) or _LIST_JOIN_BEFORE.search(before):
            out.append((['HI-COUNTY-001-2024'],m.start(),m.end()))
    return out
def _all_county_groups(plain):
    groups=_county_groups(plain)
    return groups+[g for g in _island_county_groups(plain) if not any(a<=g[1]<b for _x,a,b in groups)]
def _named_counties(plain):
    return {gid for gids,_a,_b in _all_county_groups(plain) for gid in gids}  # possessive: apostrophe stripped
# A bare island name in a comparator position ("compare with Maui") is not a county name; it gets the one relevant
# county comparator as a typed choice instead of a guessed or refused comparison. Hawaii (State vs county) is excluded.
_BARE_ISLAND={'maui':'HI-COUNTY-009-2024','kauai':'HI-COUNTY-007-2024','oahu':'HI-COUNTY-003-2024','honolulu':'HI-COUNTY-003-2024'}
_BARE_ISLAND_RE=re.compile(r'\b(maui|kauai|oahu|honolulu)\b(?!\s+(?:count(?:y|ies)|service[- ]areas?)\b)')
def _bare_island_comparators(plain):
    spans=[(a,b) for _g,a,b in _county_groups(plain)]
    return [_BARE_ISLAND[m.group(1)] for m in _BARE_ISLAND_RE.finditer(plain)
            if not any(a<=m.start()<b for a,b in spans) and _is_comparator(plain,m) and not _is_negated(plain,m)]

def _named_service_areas(plain):
    if not _SERVICE_AREA_WORDING.search(plain):return set()
    return {k for k,pat in SERVICE_AREA_PATTERNS.items() for m in re.finditer(pat,plain) if not _NOT_AREA_AFTER.match(plain[m.end():])}
def _plain(text):
    import unicodedata
    text=unicodedata.normalize('NFKD',text.replace('ʻ','').replace('‘','').replace('’','').replace("'",''))
    return ''.join(c for c in text if not unicodedata.combining(c))
# Generic themes offer only typed program choices (never a guessed program).
PROGRAM_THEMES=((r'\b(?:food assistance|food program|nutrition program)s?\b',('snap_hi','wic_hi')),
    (r'\bhousing assistance\b',('hcv_honolulu',)),(r'\bhealth coverage\b',('medquest_hi',)),
    (r'\bbenefits? programs?\b',('snap_hi','medquest_hi','hcv_honolulu','kupuna_care_hi','wic_hi')))
# Cross-measure: proven only when two different measures sit on the two sides of ONE comparison connector
# in one clause (no and/also/then/plus/add/show/keep/include, comma, semicolon or period between them), or
# "compare <measure> to|with <measure>". Edits ("change X to Y") and multi-step requests are not comparisons.
_MEASURE=r'(poverty|median household income|household income|median income|income|median age|unemployment|population|median gross rent|rent)'
_GAP=r'(?:(?!\b(?:and|also|then|plus|add|show|keep|include)\b)[^,;.]){0,45}?'
_CROSS=(re.compile(r'\b'+_MEASURE+r'\b'+_GAP+r'\b(?:versus|vs\.?|against|minus|compared (?:with|to)|relative to)\b'+_GAP+r'\b'+_MEASURE+r'\b'),
        re.compile(r'\bcompare\s+(?:the\s+)?(?:senior\s+|elderly\s+|overall\s+|all[- ]ages\s+)?'+_MEASURE+r'\s+(?:to|with)\s+(?:the\s+)?(?:senior\s+|elderly\s+|overall\s+)?'+_MEASURE+r'\b'))
_CLAUSE_BREAK=re.compile(r'[;.]|\b(?:also|then|plus|add|show|keep|include)\b')
def _measure_kind(text):
    return 'income' if 'income' in text else 'rent' if 'rent' in text else text
_NEGATED_AFTER=re.compile(r'\s+(?:nothing|none|neither)\b')
_NEGATED_BEFORE=re.compile(r"\b(?:no|not|never|without|avoid|exclude|excluding|don'?t|do not|nothing)\s+(?:[\w-]+\s+){0,2}$")
# Unsupported inference. Operation phrases prove the request on their own. A bare causal/eligibility keyword
# proves it only inside a closed request form (a question about who/what/whether, or a determine/estimate
# verb); otherwise it is unproven and the proposal is refused as uncertain, never answered as unsupported.
_UNSAFE_OPERATION=r'\b(?:resident lookup|names? of residents|participation gap|unmet need|live availability|currently (?:open|available)|predict(?:s|ed|ing|ions?)?|forecast(?:s|ed|ing)?)\b'
# Statistical-significance wording only (not "the significance of a program"): no significance test is performed, so a
# clarification never asks for a field as if one were available.
_SIGNIFICANCE=(r'\bstatistical(?:ly)?\s+signific\w*|\bsignifican(?:ce|t)\s+(?:test\w*|difference\w*|gap\w*)\b|\btest\w*\s+(?:of|for)\s+significance\b'
    r'|\bsignificantly\s+(?:different|higher|lower|greater|larger|smaller|more|less|above|below|worse|better)\b|\bp[- ]?values?\b'
    r'|\b(?:difference|gap)s?\b[^.;:!?]{0,60}?\bsignificant\b|\bstatistically\s+(?:different|distinguishable|higher|lower|greater|smaller)\b'
    r'|\bsignificant\s+at\s+(?:the\s+)?(?:\d|p\b|alpha)|(?<![\w\'\u2019])t[- ]tests?\b')
_UNSAFE_KEYWORD=r'\b(?:caus(?:e|ed|es|al)|eligib(?:le|ility)|qualif(?:y|ies))\b'
_UNSAFE_REQUEST=re.compile(r'\b(?:who|whom|which|what|how many|how much|whether|if|is|are|am|was|were|do|does|did|can|could|would|will|should)\b[^.;:!?]{0,60}?\b(?:caus(?:e|ed|es)|eligible|qualif(?:y|ies))\b'
    r'|\b(?:determine|check|assess|verify|screen|decide|confirm|estimate|count|calculate|identify|find|list)\b[^.;:!?]{0,40}?\b(?:eligib(?:le|ility)|qualif(?:y|ies)|caus(?:e|ed|es|al))\b'
    r'|\bcaus(?:ed|es)\s+by\b|\bcauses?\s+of\b|\bcausal\s+(?:effect|impact|link|relationship|analysis|inference|explanation)s?\b')
def _unnegated(pattern,utterance):
    utterance=utterance.replace('\u2019',"'")  # Curly apostrophe reads as ASCII ("don’t"); same length, so offsets hold.
    return [m for m in re.finditer(pattern,utterance)
            if not _NEGATED_BEFORE.search(utterance[max(0,m.start()-30):m.start()]) and not _NEGATED_AFTER.match(utterance[m.end():])]

def _unsupported_constraint(utterance):
    """An existing unsupported operation proven by the request, independent of model decision type."""
    keywords=_unnegated(_UNSAFE_KEYWORD,utterance)
    return (_unnegated(_UNSAFE_OPERATION,utterance) or _unnegated(_SIGNIFICANCE,utterance)
            or any(r.start()<=k.start()<r.end() for r in _UNSAFE_REQUEST.finditer(utterance) for k in keywords))

def _measure_referents(utterance,provider_context):
    """Selected aliases whose metric the utterance names: a specific measure pattern/label, else generic poverty."""
    labels={m['metric_id']:m['label'].lower() for m in provider_context['catalog']['metrics']}
    metrics={v['metric_id'] for v in provider_context['selected'].values() if v['metric_id']}
    named={m for m in metrics if (m in METRIC_PATTERNS and re.search(METRIC_PATTERNS[m],utterance))
           or (m in POVERTY_POPULATIONS and POVERTY_POPULATIONS[m].search(utterance))
           or re.search(r'\b'+re.escape(labels.get(m,m))+r'\b',utterance)}
    if 'poverty_rate_65_plus' in named:named.discard('population_65_plus')
    if not named and re.search(r'\bpoverty\b',utterance):named=metrics&POVERTY_METRICS
    return [alias for alias,v in provider_context['selected'].items() if v['metric_id'] in named]

def _unresolved_conflict(utterance,confirmed,draft):
    """Conflicting confirmed/draft fields that the utterance does not state completely and unambiguously."""
    unresolved=[]
    for field in ('district','map_session','issue_id','service_area_id','steps'):
        if confirmed[field]==draft[field]:continue
        if field=='district':
            mentions=[m for m in re.finditer(r'\b'+_DISTRICT+r'\b',utterance)
                      if not _is_negated(utterance,m)]
            stated=len({_key(m) for m in mentions})==1 and not any(_is_comparator(utterance,m) for m in mentions)
        elif field=='map_session':
            selected,excluded=_map_mentions(utterance.replace('\u2019',"'"));stated=len(selected)==1 and not selected&excluded
        elif field=='service_area_id':
            plain=_plain(utterance);stated=bool(_SERVICE_AREA_REMOVAL.search(plain)) or len(_named_service_areas(plain))==1
        elif field=='issue_id':stated=len(_positive_recipes(utterance))==1
        else:stated=False  # A complete step list is never read from wording.
        if not stated:unresolved.append(field)
    return unresolved

class _Span:
    # Minimal match-like span for _is_comparator (start/end only).
    def __init__(self,a,b):self._a,self._b=a,b
    def start(self):return self._a
    def end(self):return self._b

def _nonlegislative_proof(original):
    lowered=original.lower()
    if len(lowered)!=len(original):lowered=None  # Positions must align; else fall back to the conservative refusal.
    spans=[m.span() for m in re.finditer(_NONLEGISLATIVE.pattern,original,re.I)]+[m.span() for m in _US_FEDERAL.finditer(original)]
    if not spans:return
    rest=original
    for a,b in spans:rest=rest[:a]+' '*(b-a)+rest[b:]
    if re.search(r'\b'+_DISTRICT+r'\b|\b[hs]d\s*-?\s*\d{1,2}\b',rest,re.I):
        directed=lowered is not None and any(_is_comparator(lowered,_Span(a,b)) for a,b in spans)
        if not directed:raise LanguageError('nonlegislative_district_unproven')
    raise Recovery('nonlegislative_district','unsupported',reason='unavailable_evidence')

_REPLACE_TARGET=re.compile(r'\b(?:replace|swap|switch|change)\b[^.;]{0,60}?\b(?:with|to|for)\s+(?:the\s+)?$')
_REPLACE_SOURCE_BEFORE=re.compile(r'\b(?:replace|swap|switch|change)\s+(?:the\s+)?(?:[\w-]+\s+){0,3}$')
_REPLACE_SOURCE_AFTER=re.compile(r'^\s*(?:comparison|comparator|benchmark)?\s*(?:with|to|for)\b')
_LIST_JOIN=re.compile(r'^\s*,?\s*(?:and|or|,)\s+(?:also\s+)?(?:the\s+|with\s+)?$')
# A list position right after a named county or the State ("with Maui County and the Big Island").
_LIST_JOIN_BEFORE=re.compile(r'\b(?:county|counties|state)\s*,?\s*(?:and|or|&|plus)\s+(?:also\s+)?(?:the\s+)?$')
# A county named only as where the district lies ("House 13 includes Kalawao County", "in Maui County").
_COUNTY_CONTEXT=re.compile(r'\b(?:includes?|including|contains?|containing|within|inside|part\s+of|located\s+in|lies\s+in|in)\s+(?:the\s+)?(?:city\s+and\s+)?$')
# A parenthetical directly after a district names where it lies: "House 13 (Maui County)".
_DISTRICT_PAREN=re.compile(r'\b(?:house|senate)\s*(?:district\s*)?\d{1,2}\s*\(\s*$')
# Comparative requests, including ordinary forms without a directed cue ("between X and Y", "next to Y").
_COMPARATIVE=re.compile(_COMPARISON_WORDS+r'|\b(?:between|next\s+to|alongside|beside|side\s+by\s+side)\b')
_STATE_MENTION=re.compile(r'\b(?:the\s+)?state(?:wide)?\b(?!\s+(?:house|senate|legislat))|\bhawaii\s+state\b')
# "not just/only/merely the State" adds the State; it is not an exclusion.
_ADDITIVE_NOT=re.compile(r'\bnot\s+(?:just|only|merely)\s+$')
# A directed or list position before a State mention: the State is then a requested comparator.
_STATE_CUE=re.compile(r'\b(?:with|to|against|versus|vs\.?|than|and|or|plus|also|between|next\s+to|alongside|beside|not\s+(?:just|only|merely))\s+$')
_ADDITIVE_COMPARISON=re.compile(r'\b(?:also|too|as well|in addition|additionally|add|adding|plus|keep|keeping|both|alongside|along with)\b')
def _county_comparators(plain,plan,held_gids,comparator_gids):
    """In a comparative request every positively named county must be a compared geography, and a State named in a
    comparator position must be compared too. Excluded are negated or removed counties, a replacement source, and a
    county named only as where the district lies. A negated or removed State is never compared, even if held."""
    compared={s['args']['comparison_geography'] for s in plan['steps'] if s['operation']=='compare'}
    if not compared and not _COMPARATIVE.search(plain):return
    required,excluded=set(),set()
    for gids,a,b in _all_county_groups(plain):
        m=_Span(a,b);before=plain[max(0,a-80):a]
        source=_REPLACE_SOURCE_BEFORE.search(before) and _REPLACE_SOURCE_AFTER.match(plain[b:b+40])
        if source or _is_negated(plain,m) or _REMOVAL_BEFORE.search(before[-60:]):excluded.update(gids);continue
        directed=_is_comparator(plain,m) or _REPLACE_TARGET.search(before)
        if not directed and (_COUNTY_CONTEXT.search(before[-40:]) or (_DISTRICT_PAREN.search(before[-30:]) and re.match(r'^\s*\)',plain[b:]))):continue
        required.update(gids)
    positive_state,excluded_state,area_state=False,False,False
    for m in _STATE_MENTION.finditer(plain):
        before=plain[max(0,m.start()-60):m.start()]
        source=_REPLACE_SOURCE_BEFORE.search(before) and _REPLACE_SOURCE_AFTER.match(plain[m.end():m.end()+40])
        if not _ADDITIVE_NOT.search(before) and (source or _REMOVAL_BEFORE.search(before)):excluded_state=True
        elif re.search(r'\barea\s+(?:to|as|is)\s+$',before) or re.match(r'^\s+(?:(?:service|inquiry|program)\s+)?areas?\b',plain[m.end():]):area_state=True  # service area, not a comparator
        elif _STATE_CUE.search(before) or _is_comparator(plain,m):positive_state=True
    if required-compared:raise LanguageError('explicit_comparator_conflict')
    if excluded&compared-held_gids:raise LanguageError('explicit_comparator_conflict')
    if 'HI-STATE-2024' in compared and excluded_state and not positive_state:raise LanguageError('explicit_comparator_conflict')
    if positive_state and not excluded_state and 'HI-STATE-2024' not in compared:raise LanguageError('explicit_comparator_conflict')
    # Statewide service-area wording is never State comparison intent: it cannot add a new State comparator.
    if area_state and not positive_state and 'HI-STATE-2024' in compared-held_gids:raise LanguageError('explicit_comparator_conflict')
    if positive_state:
        # A State comparison does not exclude other comparators. Each non-State comparator must itself be grounded:
        # positively named (county or district), or a held comparator that is not removed and that additive wording
        # keeps ("also/too/as well/add/keep/both"). A bare restated State comparison never silently keeps an old one.
        additive=_ADDITIVE_COMPARISON.search(plain)
        for gid in compared-{'HI-STATE-2024'}:
            if gid in required or gid in comparator_gids:continue
            if gid in held_gids and gid not in excluded and additive:continue
            raise LanguageError('explicit_comparator_conflict')
    if required:
        # New comparison geographies must be stated: the named counties, named districts, or the State when named.
        # Only an explicit State comparison allows a new State comparator (never a statewide service-area mention).
        allowed=required|comparator_gids|held_gids|({'HI-STATE-2024'} if positive_state else set())
        if compared-allowed:raise LanguageError('explicit_comparator_conflict')

def local_guard(prepared,decision,plan):
    utterance=prepared['provider_context']['utterance'].lower();context=prepared['context'];confirmed=context['confirmed_plan']
    held=confirmed or context['draft_plan']  # One held rule everywhere: confirmed, else the visible draft.
    # HD/SD n aliases read exactly as House/Senate n for every directed district check below.
    utterance=_canonical_districts(utterance)
    # Unsupported inference is never reinterpreted as independent successful steps. A negated constraint
    # ("no causal claims") states what NOT to do and proves nothing unsupported.
    if plan is not None:
        if _unsupported_constraint(utterance):
            raise Recovery('unsupported_explicit_constraint','unsupported',reason='unsupported_operation')
        if _unnegated(_UNSAFE_KEYWORD,utterance):raise LanguageError('unsupported_inference_unproven')
    # A non-State-legislative district is outside the admitted geography; never borrow a chamber. It is
    # proven the requested geography only when no State House/Senate district is also named, or when it is
    # the directed comparator; beside a named State district it is unproven and refused as uncertain.
    if plan is not None:_nonlegislative_proof(prepared['provider_context']['utterance'])
    # A divergent unsaved draft blocks only plan proposals; a confirmed claim's source stays inspectable. A
    # conflicting field is resolved only by an explicit, unambiguous complete value in the utterance; any
    # other conflicting field still needs the typed control choice.
    if (prepared['provider_context']['control_conflict'] and decision['status']=='propose' and decision['intent'] in ('create_plan','replace_plan')
            and _unresolved_conflict(utterance,confirmed,context['draft_plan'])):
        raise Recovery('control_conflict','clarify',reason='control_conflict',field='control_conflict',choices=('x_confirmed','x_draft'))
    mentions=list(re.finditer(r'\b'+_DISTRICT+r'\b',utterance))
    # Typed recoveries that depend only on the utterance/context precede plan-specific refusals.
    if plan is not None:
        for pattern in _CROSS:
            relation=pattern.search(utterance)
            if relation and _measure_kind(relation.group(1))!=_measure_kind(relation.group(2)):
                raise Recovery('unsupported_cross_measure','unsupported',reason='unsupported_operation')
        measures=list(re.finditer(r'\b(?:poverty|median household income|median age|unemployment|total population|senior population)\b',utterance))
        if len(measures)>=2 and len(mentions)>=2 and len({m.group() for m in measures})>=2:
            spans=sorted([(m.start(),m.end(),'m') for m in measures[:2]]+[(m.start(),m.end(),'d') for m in mentions[:2]])
            order=''.join(k for *_,k in spans)
            # Interleaved district/measure pairs read as a between-measure comparison; refuse (no recovery)
            # unless a clause break or add/show verb separates the second pair.
            if order in ('dmdm','mdmd') and not _CLAUSE_BREAK.search(utterance[spans[1][1]:spans[3][0]]):
                raise LanguageError('unsupported_cross_measure')
    named={k for k,v in PROGRAM_PATTERNS.items() if re.search(v,utterance)}
    # An admitted recipe named by its staff label (unnegated) names its own program(s) and fixes the proposal's issue.
    recipes=_positive_recipes(utterance,prepared['provider_context']['catalog']['recipes'])
    for issue in recipes:
        named|={p for s in _recipe_build(issue)(EXAMPLE_DISTRICT)['steps'] for p in s['args'].get('program_ids',[])+[s['args'].get('program_id')] if p}
    themes=[ids for pattern,ids in PROGRAM_THEMES if re.search(pattern,utterance)]
    if plan is not None:
        proposed={p for s in plan['steps'] for p in s['args'].get('program_ids',[])}|{s['args']['program_id'] for s in plan['steps'] if 'program_id' in s['args']}
        # Held program context follows the one held rule (confirmed, else the visible unconfirmed draft); a divergent
        # confirmed/draft pair was already resolved or refused as a control conflict above.
        inherited={p for s in (held or {'steps':[]})['steps'] for p in s['args'].get('program_ids',[])}|{s['args']['program_id'] for s in (held or {'steps':[]})['steps'] if 'program_id' in s['args']}
    # A theme phrase needs a program choice only when the proposal selects a program the utterance does not
    # name and the confirmed plan does not hold; a plan with no such program step proposes normally.
    if themes and not named and plan is not None and proposed-inherited:
        raise Recovery('ungrounded_program','clarify',reason='missing_context',field='program',
                       choices=['p_'+x for x in dict.fromkeys(x for ids in themes for x in ids)])
    comparator_gids=set()
    negated=[m for m in mentions if _is_negated(utterance,m)]
    live=[m for m in mentions if m not in negated]
    if plan is not None and mentions:
        replacement=None
        for pattern,old_groups,new_groups in _REPLACEMENTS:
            replacement=pattern.search(utterance)
            if replacement:break
        if replacement:negated=[]  # Replacement wording names the old district explicitly.
        if replacement and _negated_before(utterance,replacement.start()):raise LanguageError('explicit_district_ambiguous')  # "don't move ..."
        if replacement:
            old=(replacement.group(old_groups[0]),f'{int(replacement.group(old_groups[1])):03}')
            if held is None or (held['district']['chamber'],held['district']['code'])!=old:
                raise LanguageError('explicit_district_conflict')
            expected=(replacement.group(new_groups[0]),f'{int(replacement.group(new_groups[1])):03}')
            comparators=[m for m in mentions if not replacement.start()<=m.start()<replacement.end()]
        elif live:
            # "Point this step/comparison at X" retargets one compare step; it never navigates the primary district.
            wording=[(m,_STEP_RETARGET_BEFORE.search(utterance[:m.start()][-60:])) for m in live]
            retargets=[m for m,w in wording if w]
            if retargets:
                if any(_negated_before(utterance,m.start()-60+w.start() if m.start()>=60 else w.start()) for m,w in wording if w):
                    raise LanguageError('explicit_district_ambiguous')  # "don't point this step at X"
                focused=_focused_compare(context,held)
                if focused is None:raise LanguageError('explicit_step_focus_missing')
                if (plan['district']['chamber'],plan['district']['code'])!=(held['district']['chamber'],held['district']['code']):
                    raise LanguageError('explicit_district_conflict')  # a step retarget never moves the primary  # no focus and no unique held comparison
                if len({_key(m) for m in retargets})!=1:raise LanguageError('explicit_district_ambiguous')
                target=_gid(*_key(retargets[0]))
                proposed_steps={s['step_id']:s for s in plan['steps']}
                step=proposed_steps.get(focused['step_id'])
                if (step is None or step['operation']!='compare' or step['args']['comparison_geography']!=target
                        or step['args']['metric_ids']!=focused['args']['metric_ids']):raise LanguageError('explicit_comparator_conflict')
                # Only the target changes: every other held step stays as it is (additions remain visible in the diff).
                if any(proposed_steps.get(s['step_id'])!=s for s in held['steps'] if s['step_id']!=focused['step_id']):
                    raise LanguageError('explicit_comparator_conflict')
            # Several distinct districts with no replacement and no comparison: never silently pick one.
            if len({_key(m) for m in live})>1 and not re.search(_COMPARISON_WORDS,utterance) and not retargets:
                raise LanguageError('explicit_district_ambiguous')
            expected,comparators=_directed_districts(utterance,live,held,retargets)
        else:
            # Every mention is negated: the held district stays (never the negated one).
            if held is None:raise _district_clarification(('house','senate'))
            expected,comparators=(held['district']['chamber'],held['district']['code']),[]
        if (plan['district']['chamber'],plan['district']['code'])!=expected:raise LanguageError('explicit_district_conflict')
        comparator_gids={_gid(*_key(m)) for m in comparators if _key(m)!=(expected[0],int(expected[1]))}
        if comparator_gids and re.search(_COMPARISON_WORDS,utterance):
            if comparator_gids-{s['args']['comparison_geography'] for s in plan['steps'] if s['operation']=='compare'}:
                raise LanguageError('explicit_comparator_conflict')
    if plan is not None and not mentions:district_provenance(utterance,context,plan)
    if plan is not None and negated:
        excluded={_gid(*_key(m)) for m in negated}
        if _gid(plan['district']['chamber'],plan['district']['code']) in excluded or any(
                s['operation']=='compare' and s['args']['comparison_geography'] in excluded for s in plan['steps']):
            raise LanguageError('explicit_district_conflict')
    if plan is not None:
        plan_numbers={int(s['args']['comparison_geography'].split('-')[2]) for s in plan['steps']
                      if s['operation']=='compare' and re.match(r'HI-(?:HOUSE|SENATE)-',s['args']['comparison_geography'])}
        bare_comparators=_bare_comparators(utterance)
        missing=[n for n in bare_comparators if n not in plan_numbers]
        if missing:  # A requested comparator that the proposal dropped or could not place.
            raise Recovery('explicit_comparator_chamber_missing','clarify',reason='missing_context',field='comparator',
                           choices=['g_'+_gid(c,n) for n in missing for c in ('house','senate')])
        islands=_bare_island_comparators(_plain(utterance))
        if islands:
            raise Recovery('explicit_comparator_county_unstated','clarify',reason='missing_context',field='comparator',
                           choices=['g_'+g for g in dict.fromkeys(islands)])
    if plan is not None:
        # Comparator provenance: a district comparator is either explicitly named in the utterance or already a
        # held comparator. Never a model-invented neighbor or a borrowed chamber for a bare number.
        held_gids={s['args']['comparison_geography'] for s in (held or {'steps':[]})['steps'] if s['operation']=='compare'}
        for s in plan['steps']:
            gid=s['args'].get('comparison_geography','')
            if s['operation']=='compare' and gid.startswith('HI-COUNTY-') and gid not in held_gids and gid not in _named_counties(_plain(utterance)):
                raise LanguageError('explicit_comparator_unstated')  # never "its county"/"a nearby county"
            if s['operation']=='compare' and re.match(r'HI-(?:HOUSE|SENATE)-',gid) and gid not in comparator_gids|held_gids:
                number=int(gid.split('-')[2])
                if number in bare_comparators or any(int(m.group(1))==number and not re.search(r'\b(?:house|senate)\s*$',utterance[:m.start()]) for m in _BARE_DISTRICT.finditer(utterance)):
                    raise Recovery('explicit_comparator_chamber_missing','clarify',reason='missing_context',field='comparator',
                                   choices=['g_'+_gid(c,n) for n in dict.fromkeys([number,*bare_comparators]) for c in ('house','senate')])
                raise LanguageError('explicit_comparator_unstated')
    if plan is not None:
        if proposed-named-inherited:raise LanguageError('ungrounded_program')
        for pid,pat in PROGRAM_PATTERNS.items():
            if pid in proposed and re.search(r'\b(?:not|without|remove|exclude|drop)\s+(?:the\s+)?(?:'+pat+r')',utterance):raise LanguageError('negated_program')
        plain=_plain(utterance);held_area=(held or {}).get('service_area_id')
        areas=_named_service_areas(plain)
        if plan['service_area_id'] is not None and plan['service_area_id']!=held_area and plan['service_area_id'] not in areas:
            raise LanguageError('explicit_service_area_unstated')
        if plan['service_area_id']!=held_area and held_area is not None and not areas and not _SERVICE_AREA_REMOVAL.search(plain):
            raise LanguageError('explicit_service_area_unstated_change')
        metric_set={m for s in plan['steps'] for m in (s['args'].get('metric_ids') or [])}
        removed=_removed_metrics(utterance)
        explicit={m for m,pat in METRIC_PATTERNS.items() if re.search(pat,utterance)}-removed
        if 'poverty_rate_65_plus' in explicit:explicit.discard('population_65_plus')
        # The desired end state: removed/replaced metrics are absent, other named measures are present. An
        # all-measures profile covers a named measure only when a full profile is asked for (no broadening).
        if removed&metric_set:raise LanguageError('explicit_metric_conflict')
        full=re.search(r'\b(?:full|complete|entire|whole|general)\s+profile\b|\ball (?:the\s+)?(?:measures|metrics|indicators|statistics)\b|\bevery (?:measure|metric|indicator)\b',utterance)
        if explicit-metric_set and not (full and any(s['operation']=='profile' and s['args']['metric_ids'] is None for s in plan['steps'])):raise LanguageError('explicit_metric_conflict')
        # Generic "poverty" is ambiguous between the two admitted poverty measures; only a named
        # population or a poverty metric already held in context may supply one.
        if re.search(r'\bpoverty\b',utterance) and metric_set&POVERTY_METRICS:
            named_poverty=(explicit&POVERTY_METRICS)|{m for m,pat in POVERTY_POPULATIONS.items() if pat.search(utterance)}
            held_metrics={m for p in (confirmed,context['draft_plan']) if p for s in p['steps'] for m in (s['args'].get('metric_ids') or [])}
            # A recipe's canonical metrics are its documented default only when the recipe is named in the
            # utterance or already held by admitted context (confirmed, else unconflicted draft); never
            # from the model's own issue_id alone.
            from .interpret import recipe,food_assistance_recipe
            for issue,build in (('aging_at_home',recipe),('food_assistance_outreach',food_assistance_recipe)):
                if plan['issue_id']==issue and (issue in recipes or (held is not None and held['issue_id']==issue)):
                    held_metrics|={m for s in build(plan['district'])['steps'] for m in (s['args'].get('metric_ids') or [])}
            if (metric_set&POVERTY_METRICS)-named_poverty-held_metrics:
                if named_poverty:raise LanguageError('explicit_metric_conflict')
                raise Recovery('explicit_metric_ambiguous','clarify',reason='missing_context',field='metric',
                               choices=('m_poverty_rate_all_people','m_poverty_rate_65_plus'))
        _county_comparators(plain,plan,held_gids,comparator_gids)
        # A named recipe is a prompt/catalog DEFAULT (full recipe_plans steps plus explicit edits), not a server rule:
        # the guard never forces its issue or steps, so omit/add/replace edits and negated or replaced recipes stay valid.
    if decision['intent']=='inspect_source':
        focus=decision['focus_alias'];selected=context['selected_claim_refs']
        aliases=set(re.findall(r'\b(?:selected_[1-8]|source_[0-9]+)\b',utterance))
        for source in prepared['provider_context']['catalog']['sources']:
            if re.search(r'\b'+re.escape(source['source_id'].replace('_',' '))+r'\b',utterance.replace('_',' ')):
                aliases.add(source['alias'])
        ordinals=('first','second','third','fourth','fifth','sixth','seventh','eighth')
        for index,ordinal in enumerate(ordinals,1):
            if re.search(r'\b'+ordinal+r'\b',utterance):aliases.add(f'selected_{index}')
        for match in re.finditer(r'\b([1-8])(?:st|nd|rd|th)\s+selected\b',utterance):
            aliases.add('selected_'+match.group(1))
        for match in re.finditer(r'\bselected\s+(?:(?:finding|claim)\s+)?(?:number\s+)?([1-8])\b',utterance):
            aliases.add('selected_'+match.group(1))
        if aliases:
            if len(aliases)!=1 or focus not in aliases or focus not in prepared['aliases']:
                raise LanguageError('ambiguous_reference')
        else:
            referential=bool(re.search(r'\b(?:that|this|its|figure|number|why|definition|source)\b',utterance))
            if referential and len(selected)==1 and focus!='selected_1':raise LanguageError('ambiguous_reference')
            if referential and len(selected)>1:
                # The utterance's measure may single out one selected claim, using only the value-free
                # selected metadata (metric_id) and catalog labels. Zero or several viable referents clarify.
                viable=_measure_referents(utterance,prepared['provider_context'])
                if len(viable)==1:
                    if focus!=viable[0]:raise LanguageError('ambiguous_reference')
                    return
                raise Recovery('ambiguous_reference','clarify',reason='ambiguous_reference',field='referent',
                               choices=[f'r_selected_{n}' for n in range(1,len(selected)+1)])
            if referential and not selected:
                explicit=any(src['source_id'].replace('_',' ') in utterance.replace('_',' ') and focus==src['alias']
                    for src in prepared['provider_context']['catalog']['sources'])
                if not explicit:raise LanguageError('ambiguous_reference')

def _restated(prepared,field,value):
    # Exact restatement of the same value is stated, not inherited (truthful preview label). Only precise
    # forms count: the same House/Senate N (or HD/SD N), the same explicit map year, the named service area.
    u=_canonical_districts(prepared['provider_context']['utterance'].lower())
    if field=='district':return any(_key(m)==(value['chamber'],int(value['code'])) for m in re.finditer(r'\b'+_DISTRICT+r'\b',u))
    if field=='map_session':return value in _map_mentions(u.replace('\u2019',"'"))[0]
    if field=='service_area_id':return value is not None and value in _named_service_areas(_plain(u))
    return False

def typed_diff(before,after):
    before=before or {};diff=[]
    for k in ('district','map_session','issue_id','service_area_id'):
        if before.get(k)!=after[k]:diff.append({'field':k,'change':'added' if k not in before else 'changed','before':copy.deepcopy(before.get(k)),'after':copy.deepcopy(after[k])})
    old={s['step_id']:s for s in before.get('steps',[])};new={s['step_id']:s for s in after['steps']}
    for sid in [*old,*[x for x in new if x not in old]]:
        if old.get(sid)!=new.get(sid):diff.append({'field':'steps','step_id':sid,'change':'removed' if sid not in new else 'added' if sid not in old else 'changed','before':copy.deepcopy(old.get(sid)),'after':copy.deepcopy(new.get(sid))})
    if list(old)!=list(new) and set(old)==set(new):diff.append({'field':'step_order','change':'changed','before':list(old),'after':list(new)})
    return diff

# Rejection stages for private operator diagnostics only (never staff-visible).
STAGES=('wire_schema','decision_fields','map_session','plan_conversion','local_guard','inheritance','source_reference','nonproposal_fields')

def _recovered(prepared,exc):
    """Fixed-template typed recovery for a refused proposal; choices come only from the server table."""
    choices=[copy.deepcopy(prepared['choices'][a]) for a in exc.choices if a in prepared['choices']]
    if exc.state=='clarify' and not choices:raise LanguageError(exc.code)
    return {'status':exc.state,'intent':'none','message':MESSAGES[exc.state],'reason_code':exc.reason,'normalized_plan':None,
            'typed_diff':[],'inherited_fields':[],'source_inspection_refs':[],'choices':choices,'clarify_field':exc.field,
            'recovered_from':exc.code,'recovery_category':exc.category}

def convert_decision(prepared,decision,core):
    stage=['wire_schema']
    try:
        out=_convert(prepared,decision,core,stage)
    except Recovery as exc:
        exc.stage=stage[0];out=_recovered(prepared,exc)
    except LanguageError as exc:
        exc.stage=stage[0];raise
    asked=out['status'] in ('propose','unsupported') and snap_gap_asked(prepared)
    if out['status']=='propose' and out['intent'] in ('create_plan','replace_plan') and (asked or coordinated_gap_asked(prepared,require_other=False)):
        # A proven SNAP participation gap is never answered by a substitute plan, even a valid one ("enrollment gap",
        # "take-up gap"): the fixed unsupported recovery replaces the proposal, as the local guard does for eligibility.
        exc=Recovery('unsupported_explicit_constraint','unsupported',reason='unsupported_operation');exc.stage='local_guard'
        out=_recovered(prepared,exc)
    offer=snap_gap_offer(prepared) if asked and out['status']=='unsupported' else None
    if offer is not None:out['participation_gap']=offer
    return out

# SNAP participation gap, in a few fixed forms whose eligibility and enrollment words bind to SNAP itself: "eligible for /
# qualify for SNAP but/and/who (are) not enrolled|receiving|... [in it|in SNAP]" ending the clause; "SNAP-eligible
# residents who are not enrolled"; "eligible non-participants in SNAP"; "SNAP participation gap" / "participation gap in
# SNAP". Anything else (another program after the verb, a second program, unclear wording) keeps the generic refusal.
_GAP_SNAP=r"(?:snap|food\s+stamps?)(?:\s+(?:benefits|program))?"
_GAP_NEG=r"(?:not|never|aren't|isn't|don't|doesn't|haven't|hasn't|(?:are|is|do|does|have|has)\s+(?:not|never))"
_GAP_VERB=(r"(?:yet\s+|currently\s+|already\s+)?(?:enrol(?:l|ls|led|ling)?|receiv(?:e|es|ing)|get(?:s|ting)?|participat(?:e|es|ing)"
           r"|signed\s+up|sign(?:ing)?\s+up|us(?:e|es|ing)|appl(?:y|ied|ying)|claim(?:s|ed|ing)?)")
_GAP_TAIL=(r"(?:\s+(?:in|into|on|for|with)?\s*(?:it|them|"+_GAP_SNAP+r"|the\s+program|benefits))?"
           r"(?:\s+(?:yet|now|currently|today))?\s*(?:[?.!;,]|$)")
_GAP_NOT_ENROLLED=r"\s+(?:(?:are|is|do|does|have|has)\s+)?(?:still\s+)?"+_GAP_NEG+r"\s+"+_GAP_VERB+_GAP_TAIL
# Fixed filler between "SNAP-eligible" and the negated verb: who is counted and where (never another program or topic).
_GAP_FILLER=r"(?:\s+(?:residents?|people|persons|households?|families|individuals|adults|seniors|kupuna|kūpuna|keiki|children|in|of|from|living|the|house|senate|district|\d{1,2})){0,5}?(?:\s+(?:who|that))?"
_GAP_FORMS=(
    r"\b(?:(?:eligible|qualif(?:y|ies|ied))\s+for|entitled\s+to)\s+"+_GAP_SNAP+r"\s*,?\s*(?:but|and|yet|who|that)"+_GAP_NOT_ENROLLED,
    r"\b"+_GAP_SNAP+r"[- ](?:eligible|qualified)"+_GAP_FILLER+_GAP_NOT_ENROLLED,
    r"\b(?:eligible|qualif(?:ied|ying))\s+non-?(?:participants|enrollees|recipients)\s+(?:in|of|for)\s+"+_GAP_SNAP+r"\b",
    r"\b"+_GAP_SNAP+r"[- ]eligible\s+non-?(?:participants|enrollees|recipients)\b",
    r"\b"+_GAP_SNAP+r"[- ](?:eligible|qualified)\s+(?:but|and|yet)\s+(?:un-?enrolled|non-?(?:enrolled|participating))\b",
    r"\b"+_GAP_SNAP+r"\s+(?:participation|enrol(?:l)?ment|take[- ]?up|uptake)\s+gaps?\b",
    r"\b(?:participation|enrol(?:l)?ment|take[- ]?up|uptake)\s+gaps?\s+(?:in|for|of)\s+"+_GAP_SNAP+r"\b",
    r"\bgaps?\s+in\s+(?:the\s+)?"+_GAP_SNAP+r"\s+(?:participation|enrol(?:l)?ment|take[- ]?up|uptake)\b")
# Next to the one named district: a coordinated or ranged number ("House 28 or 29", "House 28-30", "27 and House 28").
_GAP_DISTRICT_PEER_AFTER=re.compile(r"^\s*(?:,|/|&|\+|-|–|—|\bor\b|\band\b|\bto\b|\bthrough\b|\bthru\b|\bplus\b|\bvs\b)\s*(?:district\s*|#\s*)?\d")
_GAP_DISTRICT_PEER_BEFORE=re.compile(r"\d\s*(?:,|/|&|\+|-|–|—|\bor\b|\band\b|\bto\b|\bthrough\b|\bplus\b)\s*$")
# A coordinated gap: one clause (split at . ; ! ? and "then") that is not itself negated names SNAP and, as a separate
# positive mention, another known program, and asks expressly for an enrollment/participation/take-up gap. It is refused
# like a SNAP gap (never a substitute plan) but never gets the SNAP-only outreach offer.
_GAP_KIND=r"\b(?:participation|enrol(?:l)?ment|take[- ]?up|uptake)\s+gaps?\b|\bgaps?\s+in\s+(?:the\s+)?(?:[\w-]+\s+){0,2}?(?:participation|enrol(?:l)?ment|take[- ]?up|uptake)\b"
_CLAUSE_SPLIT=re.compile(r"[.;!?]+|\bthen\b")
# What a request clause asks for is read only at its start: optionally after one leading comma/colon phrase ("In House 28,",
# "For the whole county,"). A gap or population phrase later in the clause (a purpose: "so our team can estimate the
# gap", "for a meeting about families entitled to SNAP ...") is never the requested output.
def _clause_starts(clause):
    c=re.sub(r"^\W*(?:please\s+)?","",clause)
    lead=re.match(r"[^,:;]{1,60}[,:]\s*",c)
    return [c]+([c[lead.end():]] if lead else [])
# A gap phrase must follow a direct head (or open the clause as bare shorthand) with only articles, "both/all" and program
# names between, and not be followed by another noun ("gap meeting", "gap matters").
_GAP_HEAD=(r"(?:(?:what\s+(?:is|are|was|were)|how\s+(?:large|big|wide)\s+(?:is|are)|give\s+me\s+a\s+brief\s+on|a\s+brief\s+on|brief\s+on|"
           r"show(?:\s+me)?|give\s+me|find|estimate|calculate|compute|tell\s+me|(?:i|we)\s+(?:want|need|would\s+like)|i'd\s+like)\s+)")
_GAP_FILL=r"(?:(?:the|both|all|a|an)\s+|(?:"+"|".join(p[2:-2] for p in PROGRAM_PATTERNS.values())+r")(?:\s*(?:,|/|&|\band\b|\bor\b)\s*|\s+))*"
_GAP_OBJECT=re.compile(_GAP_HEAD+_GAP_FILL+r"(?:"+_GAP_KIND+r")(?=\s*(?:[?.!,;:]|$|\b(?:in|for|of|across|between|among|and|by|but)\b))")
# Bare shorthand: the whole clause is the gap (or population) phrase plus optional simple scopes, then the end. A scope is
# in/for/of/across/within + a district, a program, or "(the) + one or two words"; anything else (a verb continuation, a
# context declaration, another request) leaves the clause unrecognised.
_BARE_SCOPE=(r"(?:\s+(?:in|for|of|across|within)\s+(?:(?:house|senate)\s*(?:district\s*)?\d{1,2}|(?:the\s+)?(?:"+
             "|".join(p[2:-2] for p in PROGRAM_PATTERNS.values())+r")|(?:the\s+)?[a-z'-]+(?:\s+[a-z'-]+)?))*\W*$")
_GAP_BARE=re.compile(_GAP_FILL+r"(?:"+_GAP_KIND+r")"+_BARE_SCOPE)
def _gap_object(clause):
    return any(_GAP_OBJECT.match(c) or _GAP_BARE.match(c) for c in _clause_starts(clause))
# An eligible-but-unenrolled population form is the requested output only after a counting opening ("how many", "(what
# is the) number of") in that clause, right after a direct head, or as a bare population phrase leading into it.
_COUNT_OPENING=re.compile(r"(?:how\s+many|what\s+(?:is\s+the\s+)?number\s+of|number\s+of)\b")
_POP_HEAD=r"(?:show(?:\s+me)?|give\s+me|find|estimate|calculate|count|list|tell\s+me)\s+(?:the\s+|all\s+)?"
_POP_SUBJECT=r"(?:(?:the|all|those|residents?|people|households?|families|individuals|who|that|are|is|(?:house|senate)\s*(?:district\s*)?\d{1,2})\s+)*"
# Between a counting opening and the form only a positively bounded counted noun phrase may stand: count nouns, the/all/
# those, in/of/within, a House/Senate district, and a linking who/that/are/is. Any other word (a purpose, a condition)
# means the form is not what is counted, and ordinary handling applies.
_COUNT_LEAD=(r"\s+(?:(?:the|all|those|in|of|within|who|that|are|is|residents?|people|persons|households?|families|individuals|adults|"
             r"seniors|kupuna|kūpuna|keiki|children|(?:house|senate)\s*(?:district\s*)?\d{1,2})\s+)*")
def _population_object(clause,form):
    for c in _clause_starts(clause):
        if re.match(_COUNT_OPENING.pattern+_COUNT_LEAD+form,c):return True
        if re.match(_POP_HEAD+_POP_SUBJECT+form,c) or re.match(_POP_SUBJECT+form+_BARE_SCOPE,c):return True
    return False
# Only request sentences count. A one-sentence question is always a request (shorthand such as "SNAP enrollment gap in
# House 28"); in several sentences, one counts only with a '?' or a direct/imperative opening, so a statement ("The SNAP
# enrollment gap matters to us.") is background. Request sentences are then split at "then" as before.
_REQUEST_OPENING=re.compile(r"^\W*(?:please\s+)?(?:what|how|which|who|whether|is|are|can|could|would|will|do|does|show|give|estimate|find|"
    r"calculate|compute|count|tell|list|provide|get|make|prepare|draft|create|a\s+brief|brief\s+on|(?:i|we)\s+(?:want|need|would\s+like)|i'd\s+like)\b")
def _request_clauses(u):
    sentences=[x for x in re.findall(r"[^.;!?]+[.;!?]*",u) if x.strip()]
    asks=sentences if len(sentences)<=1 else [x for x in sentences if x.rstrip().endswith('?') or _REQUEST_OPENING.match(x)]
    return [c for x in asks for c in _CLAUSE_SPLIT.split(x) if c.strip()]
_CLAUSE_NEGATED=re.compile(r"^\s*(?:not|no|never|without|except|excluding|skip|don't|do\s+not|rather\s+than|instead\s+of)\b")
def coordinated_gap_asked(prepared,require_other=True):
    u=_canonical_districts(prepared['provider_context']['utterance'].lower()).replace('’',"'")
    for clause in _request_clauses(u):
        if _CLAUSE_NEGATED.match(clause) or not _gap_object(clause):continue
        if not _unnegated(PROGRAM_PATTERNS['snap_hi'],clause):continue
        if not require_other or any(_unnegated(p,clause) for k,p in PROGRAM_PATTERNS.items() if k!='snap_hi'):return True
    return False
# Affirmative vocabulary for the offer: once the one district mention is removed, every remaining word must be a question
# word, a SNAP/gap term, a resident noun, an enrollment verb, a function word or narrow meeting-deliverable wording. Any
# other word (another program, a subarea, direction, place, period, map or boundary term, a number) withholds the offer;
# the request keeps its generic refusal. Safety over paraphrase coverage.
_GAP_VOCAB=frozenset("""
how many what is are was the a an show give me i need it something can take into for meeting brief on to of in
residents resident people households household families individuals who that live
qualify qualifies eligible entitled snap food stamps stamp benefits program
but and yet not never aren't isn't don't doesn't haven't hasn't do does have has still currently
enrolled enroll receiving receive get getting them signed sign up
participation enrollment enrolment take uptake gap gaps non participants unenrolled
""".split())
def _gap_vocabulary_only(u,m):
    rest=u[:m.start()]+' '+u[m.end():]
    return all(w in _GAP_VOCAB for w in re.findall(r"[^\W_]+(?:'[^\W_]+)?",rest))
def snap_gap_asked(prepared):
    """True when the request clearly asks a SNAP participation gap in one of the fixed forms: SNAP is the only (unnegated)
    program, no other program theme is named, and the gap wording binds to SNAP. Geography is not judged here."""
    u=_canonical_districts(prepared['provider_context']['utterance'].lower()).replace('\u2019',"'")
    if not _unnegated(PROGRAM_PATTERNS['snap_hi'],u):return False
    if any(re.search(p,u) for k,p in PROGRAM_PATTERNS.items() if k!='snap_hi'):return False
    if any(re.search(p,u) for p,ids in PROGRAM_THEMES if 'snap_hi' not in ids or len(ids)>2):return False
    # The eligible-but-unenrolled population forms (first five) are direct; a gap phrase must also be the request's object.
    return any(_unnegated(PROGRAM_PATTERNS['snap_hi'],c) and _unnegated(form,c) and (_population_object(c,form) if i<5 else _gap_object(c))
               for c in _request_clauses(u) for i,form in enumerate(_GAP_FORMS))
def snap_gap_offer(prepared):
    """A deterministic, value-free offer for an unsupported SNAP participation-gap question about exactly one named,
    admitted State House/Senate district: open the checked SNAP outreach recipe there. Never a count, a plan, a guessed
    district or a model field. None unless the request proves every condition (one program, one district, no other
    geography, comparison or map year, and the SNAP outreach recipe admitted)."""
    pc=prepared['provider_context'];original=pc['utterance']
    if 'food_assistance_outreach/1' not in pc['catalog']['recipes']:return None
    u=_canonical_districts(original.lower()).replace('’',"'")
    if not snap_gap_asked(prepared):return None
    try:
        if re.search(_NONLEGISLATIVE.pattern,original,re.I) or _US_FEDERAL.search(original):return None
        plain=_plain(u)
        if _COMPARATIVE.search(plain) or _STATE_MENTION.search(plain) or _all_county_groups(plain):return None
        selected,excluded=_map_mentions(u)
        if selected or excluded:return None
        explicit,bare=_district_mentions(u)
        mentions=list(re.finditer(r'\b'+_DISTRICT+r'\b',u))
        if len(explicit)!=1 or bare or len(mentions)!=1 or any(_is_negated(u,m) or _is_comparator(u,m) for m in mentions):return None
        # Exactly one chamber word (no plural, bare or second chamber reference) and no coordinated or ranged number.
        m=mentions[0]
        if len(re.findall(r'\b(?:house|senate)s?\b',u))!=1:return None
        if _GAP_DISTRICT_PEER_AFTER.match(u[m.end():]) or _GAP_DISTRICT_PEER_BEFORE.search(u[:m.start()]):return None
        if not _gap_vocabulary_only(u,m):return None
    except LanguageError:
        return None  # Ambiguous wording is never resolved into an offer.
    chamber,number=next(iter(explicit))
    if not 1<=number<=(51 if chamber=='house' else 25):return None
    return {'kind':'snap_participation_gap','program_id':'snap_hi','issue_id':'food_assistance_outreach',
            'district':{'state_fips':'15','chamber':chamber,'code':f'{number:03}','boundary_session':2024}}

def _convert(prepared,decision,core,stage):
    validate_wire(decision,prepared['schema']);status=decision['status'];intent=decision['intent'];stage[0]='decision_fields'
    common={'status':status,'intent':intent,'message':MESSAGES[status],'reason_code':decision['reason_code'],
            'normalized_plan':None,'typed_diff':[],'inherited_fields':[],'source_inspection_refs':[],'choices':[],'clarify_field':''}
    if status=='propose':
        if decision['clarify_field'] or decision['clarify_choices'] or decision['reason_code']:raise LanguageError('inapplicable_provider_fields')
        if intent in ('create_plan','replace_plan'):
            if decision['focus_alias']:raise LanguageError('inapplicable_provider_fields')
            if intent=='replace_plan' and prepared['context']['confirmed_plan'] is None and prepared['context']['draft_plan'] is None:raise LanguageError('missing_context')
            stage[0]='map_session';map_error=None
            try:mapped=resolve_map_session(prepared,int(decision['plan']['map_session']))
            except LanguageError as exc:mapped,map_error=NEW_PLAN_MAP_SESSION,exc  # Provisional: a typed recovery takes precedence.
            stage[0]='plan_conversion';plan=ordinary_plan(decision['plan'],core,mapped)
            stage[0]='local_guard';local_guard(prepared,decision,plan)
            if map_error is not None:stage[0]='map_session';raise map_error
            stage[0]='inheritance'
            before=prepared['context']['draft_plan'] or prepared['context']['confirmed_plan']
            # decision['inherited_fields'] is untrusted model metadata: it is schema-validated but never authority. The
            # server derives the preview's inherited fields and typed diff from trusted context below; the plan itself
            # passed every Core, explicit-request, district/map/provenance and comparator check above.
            # Keep IDs for unchanged steps, even if the provider allocates another ID.
            if before:
                for s in plan['steps']:
                    for old in before['steps']:
                        if s['operation']==old['operation'] and s['args']==old['args'] and s['step_id']!=old['step_id']:raise LanguageError('changed_unchanged_step_id')
            derived=[]
            confirmed=prepared['context']['confirmed_plan']
            if confirmed:
                # Preview labels every confirmed field the proposal retains exactly (restated or not); changed
                # fields appear in the typed diff instead. Draft-only context is never inheritance.
                derived=[field for field in INHERITABLE if field!='focus' and plan[field]==confirmed[field] and not _restated(prepared,field,plan[field])]
                if prepared['context']['focused_step_id'] is not None and any(s['step_id']==prepared['context']['focused_step_id'] for s in plan['steps']):derived.append('focus')
            common.update(normalized_plan=plan,typed_diff=typed_diff(before,plan),inherited_fields=derived)
        elif intent=='inspect_source':
            stage[0]='source_reference'
            if decision['plan']!=EMPTY_PLAN or not decision['focus_alias'] or decision['inherited_fields']:raise LanguageError('inapplicable_provider_fields')
            local_guard(prepared,decision,None);common['source_inspection_refs']=copy.deepcopy(prepared['aliases'][decision['focus_alias']])
            common['message']='Review the selected source reference. Apply opens deterministic source inspection.'
        else:raise LanguageError('invalid_intent')
    else:
        stage[0]='nonproposal_fields'
        if intent!='none' or decision['plan']!=EMPTY_PLAN or decision['focus_alias'] or decision['inherited_fields']:raise LanguageError('inapplicable_provider_fields')
        reason=decision['reason_code']
        if status=='clarify':
            field=decision['clarify_field'];choices=decision['clarify_choices']
            # A referent clarification exists only for source inspection, which asks about a figure ("is that a forecast?"):
            # like the inspect_source proposal it is exempt from operation/eligibility detection; significance still recovers.
            utterance=prepared['provider_context']['utterance'].lower()
            if _unnegated(_SIGNIFICANCE,utterance) if field=='referent' else _unsupported_constraint(utterance):
                raise Recovery('unsupported_explicit_constraint','unsupported',reason='unsupported_operation')
            if field=='district' and choices and all(a in prepared['choices'] and prepared['choices'][a]['field']=='district' for a in choices):
                ungrounded=grounded_district_choices(prepared,choices)
                if ungrounded is not None and (field,sorted(choices))!=(ungrounded.field,sorted(ungrounded.choices)):raise ungrounded
            if field in ('district','chamber'):
                # A proven missing district always gets the one progressive server clarification (chamber first, then
                # that chamber's complete list), never a partial, place-derived or wrong-kind list; an identical model
                # clarification stays the model's own.
                proven=missing_district(prepared)
                if proven is not None and (field,sorted(choices))!=(proven.field,sorted(proven.choices)):raise proven
            if not field or not choices or '' in choices or reason not in ('missing_context','ambiguous_reference','control_conflict'):raise LanguageError('invalid_clarification')
            if any(prepared['choices'][a]['field']!=field for a in choices):raise LanguageError('invalid_clarification')
            common.update(clarify_field=field,choices=[copy.deepcopy(prepared['choices'][a]) for a in choices])
        elif decision['clarify_field'] or decision['clarify_choices']:raise LanguageError('inapplicable_provider_fields')
        elif status=='unsupported' and reason not in ('unsupported_operation','unavailable_evidence'):raise LanguageError('invalid_unsupported_reason')
        elif status=='uncertain' and reason!='uncertain_interpretation':raise LanguageError('invalid_uncertain_reason')
    return common
