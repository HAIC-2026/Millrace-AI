"""Conservative service-area references, distinct from district geometry."""

AREAS = frozenset(('statewide', 'oahu', 'hawaii_island', 'maui', 'molokai', 'lanai', 'kauai', 'kalawao'))


class ServiceScope:
    def __init__(self, metadata):
        self.relations = metadata.read_json('geography/relations.v1.json')

    def resolve(self, district, program_id, service_area_id=None):
        if service_area_id is not None and service_area_id not in AREAS:
            raise ValueError('unknown service area')
        # A selected inquiry area is a staff choice, not evidence of coverage.
        jurisdiction = {'state': 'unknown',
                        'scope_kind': 'staff_selected_area' if service_area_id else 'program_service_area',
                        'area_ids': [service_area_id] if service_area_id else [],
                        'source_claim_refs': [],
                        'limitations': ['Staff-selected areas and official island labels do not establish program coverage.']}
        questions = [{
            'kupuna_care_hi': 'Confirm the responsible service route, current assessment access, provider reach, wait, funding and cost.',
            'snap_hi': 'Ask BESSD to confirm the application route and handling for the specified location.',
            'medquest_hi': 'Ask Med-QUEST to confirm the application route and handling for the specified location.',
            'hcv_honolulu': 'Ask Honolulu DCS to confirm its service area, portability rules and current waiting-list status for the inquiry.',
            'wic_hi': 'Ask the WIC Services Branch to confirm the clinic route and appointment access for the specified location.',
        }.get(program_id, 'Confirm the responsible agency and application route for the specified location.')]
        if (program_id == 'kupuna_care_hi' and district.get('chamber') == 'house'
                and district.get('code') == '013'):
            questions.append(self.relations['house_013'])
        return {'jurisdiction': jurisdiction,
                'access': {'state': 'unknown', 'questions': questions,
                           'limitations': ['A dated reference does not establish current access or capacity.']},
                'eligibility_area': 'unknown'}
