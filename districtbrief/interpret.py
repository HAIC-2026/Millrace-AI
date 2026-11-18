"""A closed literal grammar. Full-string matches never discard qualifiers or negation."""
from __future__ import annotations
import copy
import re
import unicodedata

DEFAULT_METRICS=['population_65_plus','male_householder_65_plus_living_alone','female_householder_65_plus_living_alone','poverty_rate_65_plus']

def recipe(district):
    return {'district':district,'map_session':2026,'issue_id':'aging_at_home','service_area_id':None,'steps':[
        {'step_id':'s1','operation':'profile','args':{'metric_ids':list(DEFAULT_METRICS)}},
        {'step_id':'s2','operation':'compare','args':{'metric_ids':['poverty_rate_65_plus'],'comparison_geography':'HI-STATE-2024'}},
        {'step_id':'s3','operation':'program_evidence','args':{'program_ids':['kupuna_care_hi']}},
        {'step_id':'s4','operation':'outreach_lead','args':{'program_id':'kupuna_care_hi'}}]}

def food_assistance_recipe(district):
    return {'district':district,'map_session':2026,'issue_id':'food_assistance_outreach','service_area_id':None,'steps':[
        {'step_id':'s1','operation':'profile','args':{'metric_ids':['poverty_rate_all_people','median_household_income']}},
        {'step_id':'s2','operation':'program_evidence','args':{'program_ids':['snap_hi']}},
        {'step_id':'s3','operation':'outreach_lead','args':{'program_id':'snap_hi'}}]}

def interpret(utterance,plan,*,allow_food=False):
    # Replace reviewed spelling variants one character at a time so match spans stay original.
    chars=[];offset=[]
    for i,c in enumerate(utterance):
        for n in unicodedata.normalize('NFD',c.lower()):
            if not unicodedata.combining(n):
                if n.isspace():
                    if chars and chars[-1]==' ':continue
                    n=' '
                chars.append(n);offset.append(i)
    t=''.join(chars)
    result={'matched_fields':[],'inherited_fields':[],'choices':[],'reason':None}
    proposed=copy.deepcopy(plan)
    def match(field,value,m,start=0,end=None):
        a,b=m.span() if end is None else (start,end)
        span=[offset[a],offset[b-1]+1] if a<b else [0,0]
        result['matched_fields'].append({'field':field,'value':value,'span':span})
    def unresolved(reason,choices=(),status='clarification'):
        result['reason']=reason;result['choices']=list(choices)
        return status,copy.deepcopy(plan),result
    def add(op,args):
        used={s['step_id'] for s in proposed['steps']}
        num=next(i for i in range(1,1000) if f's{i}' not in used)
        if len(proposed['steps'])>=8:return False
        proposed['steps'].append({'step_id':f's{num}','operation':op,'args':args});return True
    # Every family uses fullmatch. These tokens receive a concrete supported-method explanation.
    if re.search(r'\b(?:not|never|without|except|exclude|don\x27t|eligible|unenrolled|nonparticip|significant|causal|impact|current|live|rank|trend|resident)\b',t):
        return unresolved('This qualifier or request is outside the tested grammar. Use the visible plan controls; eligibility gaps, statistical tests, causal effects and current fetching are unsupported.',status='unsupported')
    food=re.fullmatch(r'\s*snap outreach in (house|senate)\s+(\d{1,3})\s*',t)
    if food:
        if not allow_food:return unresolved('SNAP outreach recipe is unavailable in this evidence snapshot.',status='unsupported')
        chamber=food.group(1);code=int(food.group(2))
        if not 1<=code<=(51 if chamber=='house' else 25):return unresolved('District is outside the admitted chamber range.',status='unsupported')
        district={'state_fips':'15','chamber':chamber,'code':f'{code:03}','boundary_session':2024}
        proposed=food_assistance_recipe(district)
        match('issue_id','food_assistance_outreach',food)
        match('district',district,food,food.start(1),food.end(2))
        return 'ok',proposed,result
    if re.fullmatch(r'\s*snap outreach in district\s+\d{1,3}\s*',t):
        return unresolved('Choose the chamber explicitly before using SNAP outreach.')
    m=re.fullmatch(r'\s*(?:(aging at home|older-adult support at home) in |use |profile )(house|senate)\s+(\d{1,3})\s*',t)
    if m:
        chamber=m.group(2);code=int(m.group(3))
        if not 1<=code<=(51 if chamber=='house' else 25):return unresolved('District is outside the admitted chamber range.',status='unsupported')
        d={'state_fips':'15','chamber':chamber,'code':f'{code:03}','boundary_session':2024}
        if m.group(1):
            proposed=recipe(d)
            match('issue_id','aging_at_home',m,m.start(1),m.end(1))
        elif proposed is None:proposed=recipe(d)
        else:proposed['district']=d
        if t.strip().startswith('profile '):proposed['steps']=[{'step_id':'s1','operation':'profile','args':{'metric_ids':None}}];proposed['issue_id']='custom'
        match('district',d,m,m.start(2),m.end(3))
        if t.strip().startswith('profile '):match('metric_ids',None,m)
    else:
        m=re.fullmatch(r'\s*(?:use )?district\s+(\d{1,3})\s*',t)
        if m:
            n=int(m.group(1));choices=[]
            for chamber,limit in [('house',51),('senate',25)]:
                if 1<=n<=limit:choices.append({'field':'district','value':{'state_fips':'15','chamber':chamber,'code':f'{n:03}','boundary_session':2024},'label':f'{chamber.capitalize()} {n:03}'})
            return unresolved('Choose the chamber explicitly.',choices)
        if proposed is None:
            # 'add' and 'program' are the same program_evidence command (below); both may name the district.
            explicit=re.fullmatch(r'\s*(?:compare senior poverty with (?:state|maui county)|(?:add|program) (?:snap|med-quest|kupuna care)) for (house|senate)\s+(\d{1,3})\s*',t)
            if not explicit:return unresolved('Choose a district and chamber first.')
            ch=explicit.group(1);n=int(explicit.group(2))
            if not 1<=n<=(51 if ch=='house' else 25):return unresolved('District is outside the admitted range.',status='unsupported')
            proposed={'district':{'state_fips':'15','chamber':ch,'code':f'{n:03}','boundary_session':2024},'map_session':2026,'issue_id':'custom','service_area_id':None,'steps':[]}
        m=re.fullmatch(r'\s*compare senior poverty with (state|maui county)(?: for (house|senate)\s+(\d{1,3}))?\s*',t)
        if m:
            if m.group(2):
                n=int(m.group(3));ch=m.group(2)
                if not 1<=n<=(51 if ch=='house' else 25):return unresolved('District is outside the admitted range.',status='unsupported')
                proposed['district']={'state_fips':'15','chamber':ch,'code':f'{n:03}','boundary_session':2024}
                match('district',proposed['district'],m,m.start(2),m.end(3))
            g='HI-STATE-2024' if m.group(1)=='state' else 'HI-COUNTY-009-2024';steps=[s for s in proposed['steps'] if s['operation']=='compare']
            if len(steps)>1:return unresolved('Choose which comparison step to change.',[{'field':'step_id','value':s['step_id'],'label':s['step_id']} for s in steps])
            args={'metric_ids':['poverty_rate_65_plus'],'comparison_geography':g}
            if steps:steps[0]['args']=args
            elif not add('compare',args):return unresolved('The plan already has eight steps.',status='unsupported')
            match('comparison_geography',g,m)
        else:
            m=re.fullmatch(r'\s*(?:add |program )(snap|med-quest|kupuna care)(?: for (house|senate)\s+(\d{1,3}))?\s*',t)
            if m:
                p={'snap':'snap_hi','med-quest':'medquest_hi','kupuna care':'kupuna_care_hi'}[m.group(1)]
                if m.group(2):
                    n=int(m.group(3));ch=m.group(2)
                    if not 1<=n<=(51 if ch=='house' else 25):return unresolved('District is outside the admitted range.',status='unsupported')
                    proposed['district']={'state_fips':'15','chamber':ch,'code':f'{n:03}','boundary_session':2024}
                    match('district',proposed['district'],m,m.start(2),m.end(3))
                # A step with exactly this operation and scope already in the resulting plan is reported, not added
                # again, so it never takes a slot (also in a full plan). An explicit district above still applies;
                # a step with a different program set is a distinct scope and a new step is added as before.
                same=next((i for i,s in enumerate(proposed['steps']) if s['operation']=='program_evidence' and s['args']=={'program_ids':[p]}),None)
                if same is not None:result['reason']=f'Step {same+1} of the plan is already this program reference, so no step was added.'
                elif not add('program_evidence',{'program_ids':[p]}):return unresolved('The plan already has eight steps.',status='unsupported')
                match('program_id',p,m)
            else:
                m=re.fullmatch(r'\s*remove (comparison|step (s[0-9]{1,3}))\s*',t)
                if m:
                    steps=[s for s in proposed['steps'] if s['operation']=='compare'] if m.group(1)=='comparison' else [s for s in proposed['steps'] if s['step_id']==m.group(2)]
                    if len(steps)!=1:return unresolved('Choose one existing step to remove.',[{'field':'step_id','value':s['step_id'],'label':s['step_id']} for s in steps])
                    proposed['steps'].remove(steps[0]);match('removed_step_id',steps[0]['step_id'],m)
                elif re.fullmatch(r'\s*show the full profile\s*',t):
                    steps=[s for s in proposed['steps'] if s['operation']=='profile']
                    if len(steps)>1:return unresolved('Choose which profile step to change.')
                    if steps:steps[0]['args']={'metric_ids':None}
                    elif not add('profile',{'metric_ids':None}):return unresolved('The plan already has eight steps.',status='unsupported')
                    result['matched_fields'].append({'field':'metric_ids','value':None,'span':[0,len(utterance)]})
                else:return unresolved('This text does not match a supported complete phrase. Correct it or use the plan controls.',status='unsupported')
    matched={m['field'] for m in result['matched_fields']}
    result['inherited_fields']=[{'field':k,'value':v} for k,v in proposed.items() if plan is not None and k not in matched and plan.get(k)==v]
    return 'ok',proposed,result
