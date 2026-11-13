"""Fixed observation-to-program rationale shared by every routing adapter.

Builder-authored from the packet's program registry (criteria summaries,
missing facts, review notes) and the normalized metric universes. It links
area-level ACS observations to *informational* program relevance only. It never
determines eligibility, counts eligible people or measures a participation gap.
This table needs human review before evaluation; both candidates must use it
unchanged.
"""

PROGRAM_RATIONALE = {
    "snap_hi": {
        "metrics": [
            "poverty_rate_all_people",
            "median_household_income",
            "unemployment_rate",
            "rent_35_plus_percent_income",
            "rent_burden_denominator",
        ],
        "connection": (
            "Area poverty, income, unemployment and rent-cost estimates describe economic conditions "
            "in which food-assistance information may be relevant. SNAP eligibility depends on "
            "household size, countable income, deductions, BBCE/categorical status and other rules "
            "that these area estimates do not measure."
        ),
    },
    "medquest_hi": {
        "metrics": [
            "poverty_rate_all_people",
            "poverty_rate_65_plus",
            "median_household_income",
            "population_65_plus",
        ],
        "connection": (
            "Area poverty and income estimates describe conditions in which health-coverage "
            "information may be relevant; the age 65+ population is context for questions about "
            "Medicare and Medicaid coordination. Coverage groups use different MAGI or "
            "MAGI-excepted standards, and age 65 or disability alone does not establish eligibility."
        ),
    },
    "hcv_honolulu": {
        "metrics": [
            "renter_occupied_units",
            "median_gross_rent",
            "rent_35_plus_percent_income",
            "rent_burden_denominator",
        ],
        "connection": (
            "Renter-occupied units and rent-cost estimates describe housing-cost conditions. "
            "This record is the City and County of Honolulu DCS voucher program (not HPHA); it serves "
            "its own agency jurisdiction and its waiting list was reported closed when checked."
        ),
        "jurisdiction_counties": ["Honolulu County"],
    },
    "kupuna_care_hi": {
        "metrics": [
            "population_65_plus",
            "male_householder_65_plus_living_alone",
            "female_householder_65_plus_living_alone",
            "poverty_rate_65_plus",
        ],
        "connection": (
            "Older-adult population and older householders living alone describe the population "
            "for whom aging-at-home supports may be relevant. Kūpuna Care requires an area agency "
            "assessment, an individualized support plan and available funding; none of these is "
            "measured by area estimates."
        ),
    },
    "wic_hi": {
        "metrics": [],
        "connection": (
            "No normalized observation in this fixture measures pregnant, postpartum or "
            "breastfeeding participants, infants or children under five, and the registry notes "
            "that income-only relevance is insufficient for WIC. The fixture therefore shows no "
            "observation-based district relevance for WIC."
        ),
    },
}

# Kūpuna Care registry referral phones are keyed by county office name.
KUPUNA_COUNTY_OFFICE = {
    "Honolulu County": "Honolulu",
    "Hawaii County": "Hawaii",
    "Maui County": "Maui/Molokai/Lanai",
    "Kauai County": "Kauai",
}
