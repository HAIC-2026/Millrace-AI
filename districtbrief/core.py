"""Shared analytical core: catalog, profile, compare, program_evidence,
outreach_lead, brief and source.

Reads only the verified packet. Validates IDs, performs the one approved
arithmetic step (point differences of published estimates with matching
measure, universe, unit and period), checks compatibility and returns evidence
objects. It makes no network requests and no model calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from . import admin_labels, xlsx
from .contract import (CONTRACT_VERSION, DEFAULT_SESSION, EDIT_LIMITS, MAX_BRIEF_FINDINGS,
                       RE_FINDING_ID, TEMPLATES)
from .geography import GeographyIndex
from .packet import Packet
from .candidate_metadata import CandidateMetadata
from .service_scope import ServiceScope
from .rationale import KUPUNA_COUNTY_OFFICE, PROGRAM_RATIONALE


class Unsupported(Exception):
    """A validated request the fixture cannot support; carries useful next actions."""

    def __init__(self, reason, next_actions=None, data=None):
        super().__init__(reason)
        self.reason = reason
        self.next_actions = next_actions or []
        self.data = data


METRIC_DISPLAY = {
    "total_households": ("Total households", "Households"),
    "male_householder_65_plus_living_alone": ("Male householders age 65+ living alone", "Households & older adults"),
    "female_householder_65_plus_living_alone": ("Female householders age 65+ living alone", "Households & older adults"),
    "households_with_social_security": ("Households with Social Security income", "Households & older adults"),
    "total_population": ("Total population", "Population"),
    "population_65_plus": ("Population age 65 and over", "Population"),
    "median_age": ("Median age", "Population"),
    "median_household_income": ("Median household income", "Income & poverty"),
    "poverty_rate_all_people": ("Poverty rate, all people", "Income & poverty"),
    "poverty_rate_65_plus": ("Poverty rate, age 65 and over", "Income & poverty"),
    "civilian_labor_force": ("Civilian labor force", "Employment"),
    "unemployed": ("Unemployed people in the civilian labor force", "Employment"),
    "unemployment_rate": ("Unemployment rate", "Employment"),
    "education_health_social_assistance_industry": ("Employed in education, health care & social assistance", "Employment"),
    "total_housing_units": ("Total housing units", "Housing"),
    "occupied_housing_units": ("Occupied housing units", "Housing"),
    "renter_occupied_units": ("Renter-occupied housing units", "Housing"),
    "median_gross_rent": ("Median gross rent", "Housing"),
    "rent_burden_denominator": ("Renter units with computable rent-to-income ratio", "Housing"),
    "rent_35_plus_percent_income": ("Renter units paying 35%+ of income for gross rent", "Housing"),
    # Guided-only ACS measures added from the same four DBEDT workbooks. Ask keeps ORIGINAL_METRIC_IDS.
    "households_with_snap": ("Households reporting SNAP receipt in the past 12 months", "SNAP receipt (survey)"),
    "households_with_snap_share": ("Households reporting SNAP receipt in the past 12 months, share",
                                   "SNAP receipt (survey)"),
    "disability_share": ("People with a disability, share", "Disability & health insurance"),
    "disability_65_plus_share": ("Share of people age 65 and over who have a disability", "Disability & health insurance"),
    "english_less_than_very_well_share": ("People age 5 and over who speak English less than “very well,” share",
                                          "Language & education"),
    "uninsured_share": ("People without health insurance coverage, share", "Disability & health insurance"),
    "population_60_64": ("Population age 60 to 64", "Population"),
    "households_with_someone_65_plus": ("Households with someone age 65 and over", "Households & older adults"),
    "native_hawaiian_one_race": ("Native Hawaiian alone (one race reported)", "Native Hawaiian & Pacific Islander"),
    "no_vehicle_share": ("Occupied housing units with no vehicle available, share", "Housing"),
    "rent_30_to_34_9_share": ("Gross rent at 30.0–34.9% of household income (share of computable ratios)", "Housing"),
    "broadband_subscription_share": ("Households with a broadband Internet subscription, share", "Households"),
    "rent_35_plus_share": ("Gross rent at 35% or more of household income (share of computable ratios)", "Housing"),
    "nhpi_alone_or_in_combination_share": ("Native Hawaiian and Other Pacific Islander alone or in combination, share",
                                           "Native Hawaiian & Pacific Islander"),
    "bachelors_or_higher_share": ("People age 25 and over with a bachelor’s degree or higher, share",
                                  "Language & education"),
    "retirement_income_share": ("Households with retirement income, share", "Income & poverty"),
    "per_capita_income": ("Per-capita income", "Income & poverty"),
    "population_85_plus": ("Population age 85 and over", "Population"),
    "worked_from_home_share": ("Workers age 16 and over who worked from home, share", "Employment"),
    "owner_occupied_share": ("Owner-occupied share of occupied housing units", "Housing"),
}
# The original ordered measure domain. Ask (the optional language preview) admits only these measures, and a plan
# profile step with metric_ids null ("All 20 measures") keeps exactly this meaning. Added measures are guided-only:
# Single lookup, Data catalog, explicit plan steps, source inspection and printable briefs.
ORIGINAL_METRIC_IDS = (
    "total_households", "male_householder_65_plus_living_alone", "female_householder_65_plus_living_alone",
    "households_with_social_security", "total_population", "population_65_plus", "median_age",
    "median_household_income", "poverty_rate_all_people", "poverty_rate_65_plus", "civilian_labor_force",
    "unemployed", "unemployment_rate", "education_health_social_assistance_industry", "total_housing_units",
    "occupied_housing_units", "renter_occupied_units", "median_gross_rent", "rent_burden_denominator",
    "rent_35_plus_percent_income",
)
# One-page print budget. A conservative, deterministic width estimate (not a layout engine): characters
# are weighted by approximate glyph width; staff blocks and finding entries add a line of overhead;
# limitations and citations print smaller in two columns. Calibrated with tools/print_fit_check.py in
# headless Chrome on US-letter paper with the app stylesheet; other browsers/fonts/paper may differ.
BRIEF_PRINT_BUDGET = 7000  # every measured near-budget fill up to 7800 printed on one page
STAFF_BLOCK_OVERHEAD = 130
ENTRY_OVERHEAD = 60
# A comparison entry (two estimates, difference, test statement, universe and two citations) prints taller
# than its characters estimate. Conservative allowance measured on comparison-heavy custom briefs (one to
# eight of the longest comparisons, with and without maximum staff text) in headless Chrome on US letter;
# 175 would be the bare minimum to refuse four longest comparisons with every staff field at its maximum.
COMPARISON_OVERHEAD = 185
TITLE_WEIGHT = 1.6
SMALL_TEXT_WEIGHT = 0.6
_WIDE = set("WMmw@%&")


def print_units(text: str) -> float:
    units = 0.0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            units += 2.0
        elif ch in _WIDE:
            units += 2.2
        elif ch.isupper():
            units += 1.45
        elif ord(ch) > 0x2000 and unicodedata.category(ch).startswith("S"):
            units += 2.0  # symbols/emoji may fall back to wider fonts
        else:
            units += 1.0
    return units


INTENSIVE_UNITS = {"percent": "percentage points", "years": "years",
                   "2024 inflation-adjusted USD": "2024 inflation-adjusted USD",
                   "USD per month": "USD per month"}

CONTROLLED_MOE_GUIDANCE_ID = "acs_controlled_estimate_guidance"
CONTROLLED_MOE_GUIDANCE_LABEL = "ACS help page on controlled estimates"
CONTROLLED_MOE_STATUS = "Controlled estimate; no numeric margin of error published"
L_ACS = ("ACS 2020–2024 5-year estimates (DBEDT republication) with published 90% margins of error; "
         "values describe the five-year period, not a single year.")
L_ACS_PERIOD = "ACS 2020–2024 5-year estimates (DBEDT republication) describe the full five-year period."
L_FIXTURE = ("ACS statistics cover published normalized district and county profiles in this snapshot. "
             "Other workbook measures are not normalized.")
L_COMPARE = ("Point differences of published estimates only; no derived margin of error is substituted and "
             "no statistical significance or causality is implied.")
L_COUNTS = ("Counts for geographies of different size are shown side by side without a difference; "
            "the fixture has no published rate for this measure.")
L_NO_GAP = ("No measured district participation gap, district allocation of state, county or island "
            "counts, or eligible-nonparticipant estimate is supported.")
L_NO_ELIG = ("Program information is informational only. The administering agency determines individual "
             "eligibility; no eligibility determination or eligibility count is made.")
L_HYPOTHESIS = ("Outreach leads are hypotheses for staff follow-up, built from area estimates and program "
                "references; they are not measured need, gaps or eligibility findings.")
L_OVERLAP = "House and Senate districts can overlap; a comparison does not imply independent populations."
L_EDITS = "Staff edits are labeled separately and are not verified facts."
# First sentence of the packet poverty limitation: it applies to every poverty-status measure.
POVERTY_UNIVERSE_NOTE = "Poverty status universe excludes several populations."


def moe_status(value, annotation) -> str | None:
    if annotation == "*****":
        return CONTROLLED_MOE_STATUS
    if value is None:
        return "Margin of error unavailable"
    return None


def acs_period_limitations(limitations: list[str]) -> list[str]:
    """Keep a single ACS period caveat when some estimates lack a numeric margin."""
    if L_ACS_PERIOD in limitations:
        return [lim for lim in limitations if lim != L_ACS]
    return limitations


STATUS_TEXT = {
    "reference_checked": "Reference checked",
    "waiting_list_closed_at_check": "Waiting list reported closed when checked",
    "reference_checked_with_staleness_caveat": "Reference checked, with staleness caveat",
}


def _decimal_places(text: str) -> int:
    m = re.search(r"\.(\d+)", text)
    return len(m.group(1)) if m else 0


def _published_decimal(text: str) -> Decimal:
    return Decimal(re.sub(r"[^\d.\-]", "", text))


def _format_decimal(value: Decimal, places: int) -> str:
    q = Decimal(1).scaleb(-places)
    v = value.quantize(q)
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}{abs(v):,.{places}f}"


class Core:
    def __init__(self, packet: Packet | None = None, metadata=None):
        self.packet = packet or Packet()
        self.snapshot_id = self.packet.snapshot_id
        self.metadata = metadata or CandidateMetadata(Path(__file__).resolve().parents[1] / "candidate-metadata")
        self.service_scope = ServiceScope(self.metadata)
        self.geo = GeographyIndex(self.packet.dir)
        stats = self.packet.read_json("data/statistics/observations.json")
        self.stat_limitations = list(stats.get("limitations", []))
        if not self.stat_limitations[1].startswith(POVERTY_UNIVERSE_NOTE + " "):
            raise ValueError("poverty limitation text changed; review metric-specific caveats")
        self.observations = {o["observation_id"]: o for o in stats["observations"]}
        self.metrics: dict = {}
        self.profiles: dict = {}
        for o in stats["observations"]:
            pid, mid = o["observation_id"].split(":", 1)
            assert mid == o["metric_id"], o["observation_id"]
            if mid not in self.metrics:
                label, group = METRIC_DISPLAY.get(mid, (o["label"], "Other"))
                self.metrics[mid] = {
                    "metric_id": mid,
                    "label": label,
                    "group": group,
                    "published_label": o["label"],
                    "official_variable_label": o["official_variable_label"],
                    "table_id": o["table_id"],
                    "variable_id": o["variable_id"],
                    "margin_of_error_variable_id": o["margin_of_error_variable_id"],
                    "universe": o["universe"],
                    "unit": o["unit"],
                    "period": o["period"],
                    "joint_statistic": o["joint_statistic"],
                    "differenced_in_comparisons": o["unit"] in INTENSIVE_UNITS,
                    "guided_only": mid not in ORIGINAL_METRIC_IDS,
                }
            prof = self.profiles.setdefault(pid, {"geography_id": pid, "geography": o["geography"],
                                                  "observation_ids": []})
            prof["observation_ids"].append(o["observation_id"])
        for pid, prof in self.profiles.items():
            prof["label"] = self._geo_label(prof["geography"])
            prof["kind"] = self._geo_kind(prof["geography"])
        self.programs = {p["program_id"]: p for p in self.packet.read_json("data/programs/registry.json")}
        self.participation = self.packet.read_json("data/participation/observations.json")
        self.administrative_rows = {r["observation_id"]: r for r in self.participation}
        assert set(self.administrative_rows) == set(admin_labels.ROW_SERIES)
        self._extract_cache: dict = {}

    # ------------------------------------------------------------------ ids
    @staticmethod
    def _geo_kind(g: dict) -> str:
        if g.get("chamber"):
            return "district"
        return {"040": "state", "050": "county"}.get(g.get("summary_level"), "other")

    @staticmethod
    def _geo_label(g: dict) -> str:
        if g.get("chamber"):
            return f"{g['chamber'].capitalize()} District {g['district_code']} (boundary session {g['boundary_session']})"
        if g.get("summary_level") == "040":
            return "State of Hawaiʻi"
        return g.get("source_name", "").replace(", Hawaii", "")

    @staticmethod
    def profile_id_for(chamber: str, code: str, session: int) -> str:
        return f"HI-{chamber.upper()}-{code}-{session}"

    def district_record(self, d: dict) -> dict | None:
        return self.geo.get(d["chamber"], d["code"], d.get("boundary_session") or DEFAULT_SESSION)

    def has_statistics(self, chamber: str, code: str, session: int) -> bool:
        return self.profile_id_for(chamber, code, session) in self.profiles

    def county_of(self, profile_id: str) -> str | None:
        prof = self.profiles.get(profile_id)
        if not prof:
            return None
        g = prof["geography"]
        if g.get("chamber"):
            # District internal points and island labels do not establish county coverage.
            return None
        if g.get("summary_level") == "050":
            return self._geo_label(g)
        return None

    def comparison_choices(self, profile_id: str, districts: bool = True) -> list:
        return [p for p in self.profiles if p != profile_id
                and (districts or self.profiles[p]["kind"] != "district")]

    def _district_dict(self, profile_id: str) -> dict:
        g = self.profiles[profile_id]["geography"]
        return {"state_fips": g["state_fips"], "chamber": g["chamber"], "code": g["district_code"],
                "boundary_session": g["boundary_session"]}

    def _require_profile(self, profile_id: str) -> dict:
        prof = self.profiles.get(profile_id)
        if prof is None:
            raise Unsupported(
                self._unavailable_geo_reason(profile_id) + " Normalized districts: House 001–051 and "
                "Senate 001–025 (boundary session 2024).")
        return prof

    # ------------------------------------------------------------- catalog
    @staticmethod
    def catalog_limitations() -> list:
        return [L_FIXTURE, L_NO_GAP, L_NO_ELIG]

    def catalog(self) -> dict:
        counts = self.geo.count()
        districts = []
        for rec in self.geo.list():
            districts.append({
                "chamber": rec["chamber"], "code": rec["code"], "boundary_session": rec["boundary_session"],
                "name": rec["name"], "geoid": rec["geoid"],
                "has_statistics": self.has_statistics(rec["chamber"], rec["code"], rec["boundary_session"]),
                "geometry_equal_to_other_session": rec["geometry_equal_to_other_session"],
                "approx_county": None,
            })
        observations = []
        for oid, o in self.observations.items():
            observations.append({
                "finding_id": f"stat:{oid}", "observation_id": oid,
                "geography_id": oid.split(":")[0], "metric_id": o["metric_id"],
                "estimate_display": o["raw_cells"]["estimate"],
                "moe_display": o["raw_cells"]["moe"],
                "unit": o["unit"], "annotation": o["annotation"], "moe_annotation": o["moe_annotation"],
                "source_id": o["source_id"],
            })
        participation = [{
            "observation_id": r["observation_id"], "program_id": r["program_id"],
            "geography": r["geography"], "period": r["period"], "unit": r["unit"],
            "value": r["value"], "status": r["status"], "coverage": r["coverage"],
            "district_gap_usable": r["district_gap_usable"], "source_id": r["source_id"],
            **admin_labels.metadata(r),
        } for r in self.participation]
        return {
            "contract_version": CONTRACT_VERSION,
            "snapshot_id": self.snapshot_id,
            "templates": [{"task": t, "label": l} for t, l in TEMPLATES.items()],
            "default_session": DEFAULT_SESSION,
            "district_counts": counts,
            "districts": districts,
            "geographies": [{
                "geography_id": pid, "label": p["label"], "kind": p["kind"],
                "geoid": p["geography"]["geoid"], "summary_level": p["geography"]["summary_level"],
                "boundary_session": p["geography"].get("boundary_session"),
                "observation_count": len(p["observation_ids"]),
                "approx_county": self.county_of(pid) if p["kind"] == "district" else None,
            } for pid, p in self.profiles.items()],
            "unavailable_geographies": [
                {"geography_id": f"HI-COUNTY-{code}-2024", "label": name}
                for code, name in (("001", "Hawaii County"), ("003", "Honolulu County"),
                                   ("005", "Kalawao County"), ("007", "Kauai County"), ("009", "Maui County"))
                if f"HI-COUNTY-{code}-2024" not in self.profiles
            ],
            "metrics": list(self.metrics.values()),
            "programs": [{
                "program_id": p["program_id"], "name": p["name"], "agency": p["agency"],
                "jurisdiction": p["jurisdiction"], "status": p["status"], "checked_at": p["checked_at"],
                "rationale_metric_ids": PROGRAM_RATIONALE[p["program_id"]]["metrics"],
            } for p in self.programs.values()],
            "observations": observations,
            "participation": participation,
            "administrative_rows": participation,
            "sources": sorted(self.packet.sources.values(), key=lambda s: (s["family"], s["source_id"])),
            "coverage": {
                "statistics_observations": len(self.observations),
                "statistics_geographies": len(self.profiles),
                "metrics": len(self.metrics),
                "programs": len(self.programs),
                "participation_rows": len(self.participation),
                "map": "IA-1 displays complete retained district boundaries, with statistical session 2024 and separate map-session identity; map geometry does not establish service coverage.",
            },
            "limitations": [L_FIXTURE, L_ACS, L_NO_GAP, L_NO_ELIG] + self.stat_limitations,
        }

    # -------------------------------------------------------------- findings
    def stat_finding(self, obs_id: str) -> dict:
        o = self.observations.get(obs_id)
        if o is None:
            raise Unsupported(f"Observation {obs_id} is not in the normalized fixture.")
        src = self.packet.sources.get(o["source_id"], {})
        rc = o["raw_cells"]
        metric = self.metrics[o["metric_id"]]
        status = moe_status(o["margin_of_error"], o["moe_annotation"])
        limitations = [L_ACS_PERIOD if status else L_ACS]
        # The age-specific poverty caveat below already states the joint-statistic limitation for that measure.
        if o["joint_statistic"] and o["metric_id"] != "poverty_rate_65_plus":
            limitations.append("Published joint statistic for the stated universe; it is not a count of "
                               "program-eligible people.")
        if o["metric_id"] == "poverty_rate_65_plus":
            limitations.append(self.stat_limitations[1])
        elif o["metric_id"] == "poverty_rate_all_people":
            # Only the universe sentence applies; the age-specific sentence describes the 65+ measure.
            limitations.append(POVERTY_UNIVERSE_NOTE)
        if o["metric_id"] == "households_with_social_security":
            limitations.append(self.stat_limitations[2])
        annotation_meaning = None
        if o["moe_annotation"] == "*****":
            guidance = self.packet.sources.get(CONTROLLED_MOE_GUIDANCE_ID, {})
            publisher = guidance.get("publisher") or "U.S. Census Bureau"
            annotation_meaning = (
                "A controlled estimate conforms to official Population Estimates Program totals. "
                "Sampling variability does not apply, so no numeric margin of error is published. "
                f"See the {CONTROLLED_MOE_GUIDANCE_LABEL} from the {publisher}."
            )
            limitations.append(annotation_meaning)
        elif o["moe_annotation"] or o["annotation"]:
            annotation_meaning = "Published annotation retained as shown in the source; no numeric value is substituted."
        pid = obs_id.split(":")[0]
        geo_label = self.profiles[pid]["label"]
        moe_text = (status.lower() if status
                    else f"±{rc['moe'].lstrip('±')} {('percentage points ' if o['unit'] == 'percent' else '')}90% MOE")
        return {
            "finding_id": f"stat:{obs_id}",
            "kind": "statistic",
            "verified": True,
            "observation_id": obs_id,
            "metric": {k: metric[k] for k in ("metric_id", "label", "group", "published_label",
                                               "official_variable_label", "table_id", "variable_id",
                                               "margin_of_error_variable_id", "joint_statistic")},
            "geography": dict(o["geography"], geography_id=pid, label=geo_label),
            "estimate": o["estimate"],
            "estimate_display": rc["estimate"],
            "margin_of_error": o["margin_of_error"],
            "moe_display": rc["moe"],
            "moe_confidence_level": o["moe_confidence_level"],
            "annotation": o["annotation"],
            "moe_annotation": o["moe_annotation"],
            "annotation_meaning": annotation_meaning,
            "unit": o["unit"],
            "universe": o["universe"],
            "period": dict(o["period"], label=f"ACS {o['period']['start_year']}–{o['period']['end_year']} 5-year"),
            "transformation": f"None: published estimate and MOE as republished; {o['spatial_method']}.",
            "source": {
                "source_id": o["source_id"], "url": o["source_url"], "sha256": o["source_sha256"],
                "publisher": src.get("publisher"), "retrieved_at_utc": o["retrieved_at_utc"],
                "packet_path": src.get("packet_path"),
                "locator": {"type": "sheet_cell", "sheet": rc["sheet"], "label_cell": rc["label_cell"],
                            "geography_cell": rc["geography_cell"], "estimate_cell": rc["estimate_cell"],
                            "moe_cell": rc["moe_cell"]},
            },
            "text": f"{geo_label}: {metric['label']} {self._value_text(rc['estimate'], o['unit'])} ({moe_text}); "
                    f"universe: {o['universe']}; ACS {o['period']['start_year']}–{o['period']['end_year']} 5-year.",
            "limitations": limitations,
        }

    @staticmethod
    def _value_text(display: str, unit: str) -> str:
        return display if unit == "percent" else f"{display} {unit}"

    def _comparison_operand_text(self, operand: dict, status: str | None) -> str:
        value = (self._value_text(operand["estimate_display"], operand["unit"])
                 if operand["estimate"] is not None else "estimate unavailable")
        if status is None:
            level = "90% " if operand["moe_confidence_level"] == 0.9 else ""
            status = f"{level}margin of error ±{operand['moe_display'].lstrip('±')}"
        return f"{operand['geography']['label']} {value} ({status.lower()})"

    def cmp_finding(self, left_pid: str, right_pid: str, metric_id: str) -> dict:
        if metric_id not in self.metrics:
            raise Unsupported(f"Unknown metric {metric_id!r}.")
        self._require_profile(left_pid)
        if right_pid not in self.profiles:
            raise Unsupported(self._unavailable_geo_reason(right_pid),
                              [self._na_compare(left_pid, metric_id, p)
                               for p in self.comparison_choices(left_pid, districts=False)])
        if left_pid == right_pid:
            raise Unsupported("A geography cannot be compared with itself.",
                              [self._na_compare(left_pid, metric_id, p)
                               for p in self.comparison_choices(left_pid, districts=False)])
        lo = self.observations.get(f"{left_pid}:{metric_id}")
        ro = self.observations.get(f"{right_pid}:{metric_id}")
        if lo is None or ro is None:
            raise Unsupported(f"Metric {metric_id} is not normalized for both geographies.")
        checks = {
            "measure": lo["variable_id"] == ro["variable_id"],
            "universe": lo["universe"] == ro["universe"],
            "unit": lo["unit"] == ro["unit"],
            "period": lo["period"] == ro["period"],
        }
        if not all(checks.values()):
            failed = [k for k, v in checks.items() if not v]
            raise Unsupported(f"Incompatible comparison: {', '.join(failed)} differ.", data={"checks": checks})
        left = self.stat_finding(lo["observation_id"])
        right = self.stat_finding(ro["observation_id"])
        limitations = [L_COMPARE]
        if {self.profiles[left_pid]["kind"],self.profiles[right_pid]["kind"]} == {"district","county"}:
            limitations.append("The selected county is an explicit contextual reference. Full district containment within that county is not established; no program service area is inferred.")
        difference = None
        if lo["estimate"] is None or ro["estimate"] is None:
            not_differenced = "An estimate is unavailable; no difference is computed and no value is assumed."
        elif lo["unit"] in INTENSIVE_UNITS:
            a, b = _published_decimal(lo["raw_cells"]["estimate"]), _published_decimal(ro["raw_cells"]["estimate"])
            places = max(_decimal_places(lo["raw_cells"]["estimate"]), _decimal_places(ro["raw_cells"]["estimate"]))
            diff = a - b
            difference = {
                "value": float(diff),
                "display": _format_decimal(diff, places),
                "unit": INTENSIVE_UNITS[lo["unit"]],
                "method": "Left published estimate minus right published estimate (point difference); "
                          "no derived MOE; no significance implied.",
                "direction": "higher" if diff > 0 else ("lower" if diff < 0 else "equal"),
            }
            not_differenced = None
        else:
            not_differenced = L_COUNTS
            limitations.append(L_COUNTS)
        if left["geography"].get("chamber") and right["geography"].get("chamber"):
            limitations.append(L_OVERLAP)
        for f in (left, right):
            for lim in f["limitations"]:
                if lim not in limitations:
                    limitations.append(lim)
        metric = self.metrics[metric_id]
        left_status = moe_status(left["margin_of_error"], left["moe_annotation"])
        right_status = moe_status(right["margin_of_error"], right["moe_annotation"])
        if left_status or right_status:
            left_text = self._comparison_operand_text(left, left_status)
            right_text = self._comparison_operand_text(right, right_status)
            if difference:
                summary = (f"{metric['label']}: {left_text} vs {right_text}. "
                           f"Point difference {difference['display']} {difference['unit']} (no significance implied). "
                           f"{left['period']['label']}.")
            else:
                summary = (f"{metric['label']}: {left_text} and {right_text}, shown side by side. No point difference was computed. "
                           f"{left['period']['label']}.")
        elif difference:
            summary = (f"{metric['label']}: {left['geography']['label']} {self._value_text(left['estimate_display'], lo['unit'])} "
                       f"(±{left['moe_display'].lstrip('±')}) vs {right['geography']['label']} "
                       f"{self._value_text(right['estimate_display'], ro['unit'])} (±{right['moe_display'].lstrip('±')}); "
                       f"point difference {difference['display']} {difference['unit']} (no significance implied); "
                       f"{left['period']['label']}, ± is the published 90% MOE.")
        else:
            summary = (f"{metric['label']}: {left['geography']['label']} {self._value_text(left['estimate_display'], lo['unit'])} "
                       f"(MOE {left['moe_display']}) and {right['geography']['label']} "
                       f"{self._value_text(right['estimate_display'], ro['unit'])} (MOE {right['moe_display']}), "
                       f"shown side by side; not differenced; {left['period']['label']}, published 90% MOEs.")
        summary += " No statistical difference test was performed."
        return {
            "finding_id": f"cmp:{left_pid}~{right_pid}:{metric_id}",
            "kind": "comparison",
            "verified": True,
            "metric": left["metric"],
            "left": left,
            "right": right,
            "compatibility": {"compatible": True, "checks": checks},
            "difference": difference,
            "not_differenced_reason": not_differenced,
            "unit": lo["unit"],
            "universe": lo["universe"],
            "period": left["period"],
            "transformation": difference["method"] if difference else "None: side-by-side published values.",
            "text": summary,
            "limitations": acs_period_limitations(limitations),
        }

    def _unavailable_geo_reason(self, pid: str) -> str:
        names = {"HI-COUNTY-001-2024": "Hawaii County", "HI-COUNTY-003-2024": "Honolulu County",
                 "HI-COUNTY-005-2024": "Kalawao County", "HI-COUNTY-007-2024": "Kauai County"}
        if pid in names:
            return f"{names[pid]} has no normalized statistics in this snapshot."
        m = re.match(r"^HI-(HOUSE|SENATE)-(\d{3})-(\d{4})$", pid)
        if m:
            chamber, code, session = m.group(1).lower(), m.group(2), int(m.group(3))
            if self.geo.get(chamber, code, session):
                return (f"{chamber.capitalize()} District {code} (session {session}) exists in the boundary layer, "
                        "but its statistics are not normalized in this fixture.")
            return f"{chamber.capitalize()} District {code} (session {session}) does not exist in the boundary layers."
        return f"Geography {pid} is not available in this fixture."

    def _na_compare(self, left_pid, metric_id, right_pid) -> dict:
        return {"label": f"Compare {self.metrics[metric_id]['label']} with {self.profiles[right_pid]['label']}",
                "request": {"task": "compare", "district": self._district_dict(left_pid),
                            "metric_ids": [metric_id], "comparison_geography": right_pid}}

    def _participation_context(self, program_id: str, county: str | None) -> list:
        # Administrative observations are explicit, independently scoped references only.
        # No automatic district match, including statewide aggregates.
        return []

    def _extract_lines(self, text_path: str) -> list:
        if text_path not in self._extract_cache:
            self._extract_cache[text_path] = self.packet.read_text(f"data/programs/{text_path}").splitlines()
        return self._extract_cache[text_path]

    def _evidence(self, ev: dict) -> dict:
        loc = ev["locator"]
        src = self.packet.sources.get(ev["source_id"], {})
        out = {"source_id": ev["source_id"], "claim": ev["claim"], "support_text": ev["support_text"],
               "locator": loc, "source_url": src.get("url"), "source_sha256": src.get("sha256"),
               "retrieved_at_utc": src.get("retrieved_at_utc"), "publisher": src.get("publisher")}
        if ev.get("verification_kind") == "authored_reference":
            out["verified_against_extract"] = None
            out["verification_kind"] = "authored_reference"
            out["locator_text"] = "Historical source locator: " + json.dumps(loc, ensure_ascii=False, sort_keys=True)
        elif "text_path" in loc:
            lines = self._extract_lines(loc["text_path"])
            span = lines[loc["line_start"] - 1: loc["line_end"]]
            out["verified_against_extract"] = "\n".join(span) == ev["support_text"]
            out["locator_text"] = f"{loc['text_path']} lines {loc['line_start']}–{loc['line_end']}"
        else:
            out["verified_against_extract"] = None
            out["locator_text"] = f"{loc.get('path')} pages {loc.get('pages')} ({loc.get('section')})"
        return out

    def prog_finding(self, program_id: str, profile_id: str) -> dict:
        p = self.programs.get(program_id)
        if p is None:
            raise Unsupported(f"Program {program_id!r} has no registry record in this packet.",
                              [self._na_program(profile_id, q) for q in self.programs])
        prof = self._require_profile(profile_id)
        rat = PROGRAM_RATIONALE[program_id]
        county = self.county_of(profile_id)
        scope = self.service_scope.resolve(self._district_dict(profile_id), program_id)
        in_area = None if rat.get("jurisdiction_counties") else True
        jur_note = (f"{p['jurisdiction']}. District-wide service coverage is unverified; "
                    "confirm the responsible route with the agency. Unknown coverage does not establish outside jurisdiction.")
        access = {"recorded_status": "closed_at_check" if p["status"] == "waiting_list_closed_at_check" else "reference_checked",
                  "checked_at": p["checked_at"], "effective_period": p["effective_period"],
                  "current_availability": "unverified", "cost": "unverified"}
        related = []
        for mid in rat["metrics"]:
            f = self.stat_finding(f"{profile_id}:{mid}")
            related.append({"finding_id": f["finding_id"], "metric_id": mid, "label": f["metric"]["label"],
                            "estimate_display": f["estimate_display"], "moe_display": f["moe_display"],
                            "unit": f["unit"], "universe": f["universe"], "period_label": f["period"]["label"]})
        status_notes = [f"{STATUS_TEXT.get(p['status'], p['status'])} on {p['checked_at'][:10]}."]
        if p["status"] == "waiting_list_closed_at_check":
            status_notes.append("The agency page reported its waiting list closed when checked; this is not a claim "
                                "of permanent closure. Do not promise that an application is open or a voucher is available.")
        if p["status"] == "reference_checked_with_staleness_caveat":
            status_notes.append("The income-table effective date is unresolved; current income guidelines must "
                                "come from a WIC clinic before any income discussion.")
        ep = p["effective_period"]
        eff_text = (f"effective from {ep['from']}" if ep.get("from") else "effective date not established") + \
                   (f" to {ep['to']}" if ep.get("to") else "")
        participation = self._participation_context(program_id, county)
        limitations = [L_NO_ELIG, L_NO_GAP]
        if not rat["metrics"]:
            limitations.append(rat["connection"])
        if participation:
            limitations.append("Administrative participation counts are state, county or island aggregates with their "
                               "own periods and coverage; they are not allocated to districts and are not compared "
                               "with district estimates.")
        referral = p["referral"]
        phone = referral.get("agency_phone")
        if program_id == "kupuna_care_hi":
            phone = "808-586-0100"  # Retained statewide EOA directory; local routing remains a question.
        return {
            "finding_id": f"prog:{program_id}@{profile_id}",
            "kind": "program_relevance",
            "verified": True,
            "informational_only": True,
            "program": {k: p[k] for k in ("program_id", "name", "agency", "jurisdiction", "official_url",
                                           "checked_at", "effective_period", "status", "criteria_summary",
                                           "missing_facts", "referral", "scope", "review_notes", "source_ids")},
            "geography": {"geography_id": profile_id, "label": prof["label"], "approx_county": county},
            "jurisdiction": scope["jurisdiction"], "access": access,
            "scope_questions": scope["access"]["questions"],
            "eligibility_area": scope["eligibility_area"],
            "jurisdiction_check": {"in_agency_area": in_area, "note": jur_note,
                                   "method": "Reviewed service-scope records; no point-derived county decision."},
            "status_notes": status_notes,
            "effective_text": eff_text,
            "relevance": {"connection": rat["connection"], "related_observations": related,
                          "observation_based": bool(rat["metrics"])},
            "unknowns": list(p["missing_facts"]),
            "referral": {"url": referral.get("url"), "phone": phone, "tty": referral.get("tty"),
                         "next_step": referral.get("next_step"),
                         "county_office": KUPUNA_COUNTY_OFFICE.get(county or "") if program_id == "kupuna_care_hi" else None},
            "evidence": [self._evidence(ev) for ev in p["evidence"]],
            "participation_context": participation,
            "text": (f"{p['name']} ({p['agency']}; {p['jurisdiction']}): informational relevance for {prof['label']}. "
                     f"{' '.join(status_notes)} Rules {eff_text}. "
                     + ("" if in_area is True else "District-wide agency scope is unverified. ")
                     + f"Referral: {referral.get('url')}" + (f", {phone}" if phone else "") + "."),
            "limitations": limitations,
        }

    def _na_program(self, profile_id, program_id) -> dict:
        return {"label": f"Explain {self.programs[program_id]['name']} relevance",
                "request": {"task": "program_relevance", "district": self._district_dict(profile_id)
                            if profile_id in self.profiles else None, "program_ids": [program_id]}}

    def lead_finding(self, program_id: str, profile_id: str, metric_ids: list | None = None) -> dict:
        prog = self.prog_finding(program_id, profile_id)
        rat = PROGRAM_RATIONALE[program_id]
        others = [self._na_outreach(profile_id, q) for q in self.programs
                  if q != program_id and PROGRAM_RATIONALE[q]["metrics"]
                  and not PROGRAM_RATIONALE[q].get("jurisdiction_counties")]
        if not rat["metrics"]:
            raise Unsupported(f"No outreach hypothesis for {prog['program']['name']}: {rat['connection']}",
                              others + [self._na_program(profile_id, program_id)])
        if prog["jurisdiction_check"]["in_agency_area"] is not True:
            raise Unsupported(f"No outreach hypothesis for {prog['program']['name']} in {prog['geography']['label']}: "
                              f"{prog['jurisdiction_check']['note']}", others + [self._na_program(profile_id, program_id)])
        # The lead ID names exactly one fact set: the full reviewed measure list, in rationale order.
        if metric_ids and list(metric_ids) != list(rat["metrics"]):
            raise Unsupported(f"An outreach hypothesis uses the full reviewed measure set for {prog['program']['name']} "
                              f"({', '.join(rat['metrics'])}); measure subsets or reorderings are not supported.",
                              [self._na_outreach(profile_id, program_id)])
        chosen = rat["metrics"]
        observed = []
        for mid in chosen:
            stat = self.stat_finding(f"{profile_id}:{mid}")
            entry = {"finding_id": stat["finding_id"], "label": stat["metric"]["label"],
                     "estimate_display": stat["estimate_display"], "moe_display": stat["moe_display"],
                     "unit": stat["unit"], "universe": stat["universe"], "period_label": stat["period"]["label"],
                     "state_reference": None}
            if profile_id != "HI-STATE-2024" and self.metrics[mid]["differenced_in_comparisons"]:
                cmp = self.cmp_finding(profile_id, "HI-STATE-2024", mid)
                entry["state_reference"] = {"finding_id": cmp["finding_id"],
                                            "estimate_display": cmp["right"]["estimate_display"],
                                            "moe_display": cmp["right"]["moe_display"],
                                            "difference": cmp["difference"]}
            observed.append(entry)
        unknowns = list(prog["unknowns"]) + [
            "How many district residents are eligible or already participating (no district participation "
            "count or gap exists in this packet)",
        ]
        ref = prog["referral"]
        next_step = (f"Share official {prog['program']['name']} information through community partners serving "
                     f"{prog['geography']['label']} and point residents to the agency referral "
                     f"({ref['url']}" + (f", {ref['phone']}" if ref.get("phone") else "") + "). "
                     f"Agency guidance: {ref['next_step']} Do not screen or tell individuals they qualify.")
        parts, limitations, any_counts, any_diff = [], [L_HYPOTHESIS], False, False
        for e in observed:
            unit = "" if e["unit"] == "percent" else f" {e['unit']}"
            part = f"{e['label']} {e['estimate_display']} ±{e['moe_display'].lstrip('±')}"
            sr = e["state_reference"]
            if sr:
                any_diff = True
                diff_unit = " percentage points" if e["unit"] == "percent" else ""
                part += (f" (state {sr['estimate_display']} ±{sr['moe_display'].lstrip('±')}; "
                         f"difference {sr['difference']['display']}{diff_unit}){unit}")
            else:
                any_counts = True
                part += unit
            parts.append(part)
            for lim in self.stat_finding(e["finding_id"].split(":", 1)[1])["limitations"]:
                if lim not in limitations:
                    limitations.append(lim)
        if any_diff:
            limitations.append(L_COMPARE)
        if any_counts:
            limitations.append("Count measures in an outreach hypothesis are shown for the district only, without "
                               "a state difference.")
        for lim in prog["limitations"]:
            if lim not in limitations:
                limitations.append(lim)
        p = prog["program"]
        contact = ref["url"] + (f", {ref['phone']}" if ref.get("phone") else "") + \
            (f" (TTY {ref['tty']})" if ref.get("tty") else "") + \
            (f" ({ref['county_office']} county office)" if ref.get("county_office") else "")
        text = (
            f"Outreach hypothesis — not a measured gap or eligibility finding: {p['name']} information may be relevant "
            f"in {prog['geography']['label']}. Observed area conditions (ACS 2020–2024 5-year estimates; ± is the "
            f"published 90% margin of error; state = State of Hawaiʻi; point differences imply no significance): "
            f"{'; '.join(parts)}. "
            f"Program context (informational): {p['agency']}; {p['jurisdiction']}; {' '.join(prog['status_notes'])} "
            f"Rules {prog['effective_text']}. Unknowns the agency determines: {'; '.join(prog['unknowns'])}; district "
            f"eligibility and participation (no district count or gap exists). Next step: share official {p['name']} "
            f"information through community partners and refer residents to {contact}; the agency determines "
            f"eligibility — do not screen or tell individuals they qualify."
        )
        return {
            "finding_id": f"lead:{program_id}@{profile_id}",
            "kind": "outreach_hypothesis",
            "verified": True,
            "hypothesis": True,
            "label": "Outreach hypothesis — not a measured gap or eligibility finding",
            "program": {"program_id": program_id, "name": p["name"], "agency": p["agency"],
                        "jurisdiction": p["jurisdiction"], "checked_at": p["checked_at"], "status": p["status"],
                        "effective_period": p["effective_period"]},
            "geography": prog["geography"],
            "measure_ids": list(chosen),
            "observed_need": observed,
            "program_connection": {"text": rat["connection"], "program_finding_id": prog["finding_id"],
                                   "status_notes": prog["status_notes"], "effective_text": prog["effective_text"]},
            "unknowns": unknowns,
            "next_step": next_step,
            "referral": ref,
            "text": text,
            "limitations": limitations,
        }

    def _na_outreach(self, profile_id, program_id) -> dict:
        return {"label": f"Draft an outreach hypothesis for {self.programs[program_id]['name']}",
                "request": {"task": "outreach", "district": self._district_dict(profile_id),
                            "program_ids": [program_id]}}

    def finding(self, finding_id: str) -> dict:
        if not RE_FINDING_ID.match(finding_id):
            raise Unsupported(f"Malformed finding ID {finding_id!r}.")
        kind, rest = finding_id.split(":", 1)
        if kind == "admin":
            return self.admin_finding(rest)
        if kind == "stat":
            return self.stat_finding(rest)
        if kind == "cmp":
            pair, metric_id = rest.rsplit(":", 1)
            left, right = pair.split("~")
            return self.cmp_finding(left, right, metric_id)
        program_id, pid = rest.split("@")
        if kind == "prog":
            return self.prog_finding(program_id, pid)
        return self.lead_finding(program_id, pid)

    @staticmethod
    def finding_profile(finding_id: str) -> str | None:
        kind, rest = finding_id.split(":", 1)
        if kind == "admin":
            return None  # district-agnostic administrative context
        if kind == "stat":
            return rest.split(":")[0]
        if kind == "cmp":
            return rest.split("~")[0]
        return rest.split("@")[1]

    # ----------------------------------------------------------- operations
    def admin_label(self, observation_id: str) -> str:
        r = self.administrative_rows[observation_id]
        return f"{admin_labels.metadata(r)['series_label']} · {r['geography']['name']} · {r['period']} · {r['unit']} · {r['status']}"

    @staticmethod
    def _admin_locator_text(locator):
        return "; ".join(f"{key}: {value}" for key, value in locator.items())

    def admin_finding(self, observation_id: str) -> dict:
        row = self.administrative_rows.get(observation_id)
        if row is None:
            raise Unsupported(f"Administrative observation {observation_id!r} is not in the retained fixture.")
        src = self.packet.sources[row["source_id"]]
        meta = admin_labels.metadata(row)
        value_text = (f"{row['value']:,} {row['unit']}" if row["value"] is not None else
                      f"unpublished ({row.get('missing_reason', row['status'])}); no value is supplied")
        return {
            **{k: row.get(k) for k in ("observation_id", "program_id", "geography", "period", "unit", "value",
                                       "status", "coverage", "revision_status", "suppression", "missing_reason")},
            **meta, "finding_id": "admin:" + observation_id, "kind": "administrative_context", "verified": True,
            "district_gap_usable": False,
            "source": {"source_id": row["source_id"], "url": src["url"], "sha256": src["sha256"],
                       "publisher": src["publisher"], "retrieved_at_utc": src["retrieved_at_utc"],
                       "packet_path": src["packet_path"], "locator": dict(row["locator"])},
            "text": f"{meta['series_label']} — {row['geography']['name']}; {row['period']}: {value_text}. "
                    f"Coverage: {row['coverage']} Status: {row['status']}. Administrative context; not a district count.",
            "limitations": [L_NO_GAP, "Administrative records retain their own geography, period, unit and coverage; "
                            "they are not ACS estimates, eligibility denominators or district participation counts.",
                            row["revision_status"], row["suppression"]],
        }

    def administrative_evidence(self, observation_ids: list) -> dict:
        if not isinstance(observation_ids, list) or not 1 <= len(observation_ids) <= 8:
            raise Unsupported("Select 1–8 known administrative observation IDs.")
        unknown = [oid for oid in observation_ids if oid not in self.administrative_rows]
        if unknown:
            raise Unsupported("Unknown administrative observation ID(s): " + ", ".join(unknown) + ".")
        selected = set(observation_ids)
        findings = [self.admin_finding(oid) for oid in self.administrative_rows if oid in selected]
        limitations = list(dict.fromkeys(lim for f in findings for lim in f["limitations"]))
        return {"findings": findings, "limitations": limitations,
                "data": {"evidence_scope": "recorded administrative geography; district-agnostic context",
                         "observation_ids": [f["observation_id"] for f in findings]}}

    def original_metric_ids(self) -> list:
        """The frozen meaning of a null plan profile: the original measures present in this packet, in order."""
        return [m for m in self.metrics if m in ORIGINAL_METRIC_IDS]

    def profile(self, profile_id: str, metric_ids: list | None = None) -> dict:
        prof = self._require_profile(profile_id)
        requested = None if metric_ids is None else list(dict.fromkeys(metric_ids))
        if metric_ids is not None:
            if not isinstance(metric_ids, list) or not 1 <= len(metric_ids) <= 20:
                raise Unsupported("A selected profile requires 1–20 known measure IDs; use null for the full profile.")
            unknown = [m for m in requested if m not in self.metrics]
            if unknown:
                raise Unsupported("Unknown measure ID(s): " + ", ".join(unknown) + ".")
        findings = [self.stat_finding(oid) for oid in prof["observation_ids"]
                    if requested is None or self.observations[oid]["metric_id"] in requested]
        g = prof["geography"]
        identity = None
        if g.get("chamber"):
            rec = self.geo.get(g["chamber"], g["district_code"], g["boundary_session"])
            identity = {k: rec[k] for k in ("state_fips", "chamber", "code", "boundary_session", "geoid", "name",
                                             "arealand", "areawater", "geometry_equal_to_other_session",
                                             "approx_county", "source_id", "source_url", "source_sha256")}
        missing = [f["finding_id"] for f in findings if f["estimate"] is None]
        annotated = [f["finding_id"] for f in findings if f["annotation"] or f["moe_annotation"]]
        lims = [L_ACS, L_FIXTURE]
        for f in findings:
            for lim in f["limitations"]:
                if lim not in lims:
                    lims.append(lim)
        return {"findings": findings, "limitations": acs_period_limitations(lims),
                "data": {"geography_id": profile_id, "label": prof["label"], "identity": identity,
                         "coverage": {"observations": len(findings), "metrics_total": len(self.metrics),
                                      "missing_estimates": missing, "annotated": annotated,
                                      "requested_metric_ids": requested,
                                      "returned_metric_ids": [f["metric"]["metric_id"] for f in findings],
                                      "filtered": requested is not None}}}

    def compare(self, profile_id: str, metric_ids: list, comparison_geography: str) -> dict:
        findings = [self.cmp_finding(profile_id, comparison_geography, m) for m in metric_ids]
        lims = []
        for f in findings:
            for lim in f["limitations"]:
                if lim not in lims:
                    lims.append(lim)
        return {"findings": findings, "limitations": acs_period_limitations(lims),
                "data": {"geography_id": profile_id, "comparison_geography": comparison_geography}}

    def program_population_context(self) -> dict:
        """Catalog definitions, without adding observations to a program's reviewed measure set."""
        mids = ("population_65_plus", "households_with_social_security",
                "poverty_rate_all_people", "poverty_rate_65_plus")
        snap = self.packet.read_json("data/statistics/raw/DP03_metadata.json")["variables"]["DP03_0074E"]
        period = self.metrics["total_households"]["period"]
        # The same DP03_0074E survey receipt measure, when this snapshot publishes its estimates, is a guided measure.
        receipt = self.metrics.get("households_with_snap")
        return {
            "definitions": [{k: self.metrics[mid][k] for k in
                             ("metric_id", "label", "universe", "unit", "table_id", "variable_id")}
                            for mid in mids],
            "snap_receipt_definition": {
                "label": snap["label"].rsplit("!!", 1)[1],
                "official_variable_label": snap["label"],
                "universe": snap["label"].split("!!")[-2],
                "unit": self.metrics["total_households"]["unit"],
                "table_id": "DP03", "variable_id": "DP03_0074E",
                "period_label": f"ACS {period['start_year']}–{period['end_year']} 5-year",
                "source_id": "acs_2024_DP03_metadata",
                "source_locator": "variables.DP03_0074E.label",
                "definition_only": receipt is None,
                **({"metric_id": receipt["metric_id"], "guided_label": receipt["label"]} if receipt else {}),
            },
            "notes": [
                "Age counts describe people; Social Security receipt describes households, not individual "
                "recipients. These are different statistical populations. Household income medians also "
                "do not count people in an income category.",
                *self.stat_limitations[1:3],
                "The ACS SNAP/food-stamp measure describes households receiving benefits in the past 12 "
                "months, within the ACS 2020–2024 5-year period. It is not an individual recipient count "
                "or a measure of current enrollment or eligibility. Dated administrative SNAP records "
                "count persons or households with their own periods and coverage, including monthly "
                "caseloads or average monthly persons; they are not the same survey measure or population.",
                "Everyday labels such as fixed income do not define a measured population in this fixture. "
                "A published age-specific poverty or householder-living-alone measure describes only its "
                "stated joint population; it does not add income-source, eligibility or enrollment status.",
                "Program registry records describe criteria and referrals, not linked resident records. "
                "Administrative participation totals have their own geography, period, unit and coverage. "
                "Neither links the ACS populations to individual eligibility or enrollment. Separate area "
                "estimates and program totals cannot identify a joint eligible and unenrolled population; "
                "subtracting or multiplying them cannot supply that missing count.",
            ],
        }

    def program_evidence(self, profile_id: str, program_ids: list) -> dict:
        findings = [self.prog_finding(p, profile_id) for p in program_ids]
        lims = []
        for f in findings:
            for lim in f["limitations"]:
                if lim not in lims:
                    lims.append(lim)
        return {"findings": findings, "limitations": lims,
                "data": {"geography_id": profile_id, "population_context": self.program_population_context()}}

    def outreach_lead(self, profile_id: str, program_id: str, metric_ids: list | None = None) -> dict:
        f = self.lead_finding(program_id, profile_id, metric_ids)
        return {"findings": [f], "limitations": list(f["limitations"]),
                "data": {"geography_id": profile_id, "population_context": self.program_population_context()}}

    def brief(self, profile_id: str, finding_ids: list, edits: dict) -> dict:
        prof = self._require_profile(profile_id)
        if len(finding_ids) > MAX_BRIEF_FINDINGS:
            raise Unsupported(f"A one-page brief holds at most {MAX_BRIEF_FINDINGS} findings; "
                              f"{len(finding_ids)} were selected. Remove some findings and run again.")
        foreign = [fid for fid in finding_ids if self.finding_profile(fid) not in (None, profile_id)]
        if foreign:
            raise Unsupported(f"These findings belong to a different district context than {prof['label']}: "
                              f"{', '.join(foreign)}. Build a brief for one district at a time.")
        findings = [self.finding(fid) for fid in finding_ids]
        notes = dict(edits.get("finding_notes") or {})
        orphan = [fid for fid in notes if fid not in finding_ids]
        if orphan:
            raise Unsupported(f"Staff notes refer to findings not in the brief: {', '.join(orphan)}.")
        citations, cite_index = [], {}

        def cite(source_id, locator_text):
            """One citation per retained source; every cited cell/line locator is listed under it."""
            if source_id not in cite_index:
                src = self.packet.sources.get(source_id, {})
                cite_index[source_id] = len(citations) + 1
                citations.append({"n": cite_index[source_id], "source_id": source_id, "publisher": src.get("publisher"),
                                  "url": src.get("url"), "sha256": src.get("sha256"),
                                  "retrieved_at_utc": src.get("retrieved_at_utc"), "locators": []})
            entry = citations[cite_index[source_id] - 1]
            if locator_text not in entry["locators"]:
                entry["locators"].append(locator_text)
            return cite_index[source_id]

        def stat_cites(stat):
            loc = stat["source"]["locator"]
            return [cite(stat["source"]["source_id"], f"{loc['sheet']}!{loc['estimate_cell']} (MOE {loc['moe_cell']})")]

        entries = []
        for f in findings:
            if f["kind"] == "statistic":
                ns = stat_cites(f)
            elif f["kind"] == "comparison":
                ns = stat_cites(f["left"]) + stat_cites(f["right"])
            elif f["kind"] == "administrative_context":
                ns = [cite(f["source"]["source_id"], self._admin_locator_text(f["source"]["locator"]))]
            elif f["kind"] == "program_relevance":
                ns = [cite(e["source_id"], e["locator_text"]) for e in f["evidence"]]
            else:
                prog = self.prog_finding(f["program"]["program_id"], profile_id)
                ns = []
                for o in f["observed_need"]:
                    ns += stat_cites(self.stat_finding(o["finding_id"].split(":", 1)[1]))
                    if o["state_reference"]:
                        ns += stat_cites(self.stat_finding(f"HI-STATE-2024:{o['finding_id'].rsplit(':', 1)[1]}"))
                ns += [cite(e["source_id"], e["locator_text"]) for e in prog["evidence"]]
            # Comparison summaries omit the structured universe; the standalone brief must retain it.
            text = f["text"] + (f" Universe: {f['universe']}." if f["kind"] == "comparison" else "")
            entries.append({"finding_id": f["finding_id"], "kind": f["kind"], "text": text,
                            "citations": sorted(set(ns)), "staff_note": notes.get(f["finding_id"])})
        lims = [L_EDITS]
        for f in findings:
            for lim in f["limitations"]:
                if lim not in lims:
                    lims.append(lim)
        lims = acs_period_limitations(lims)
        staff = {k: edits[k] for k in ("title", "note", "next_steps") if edits.get(k)}
        units = (sum(print_units(en["text"]) + ENTRY_OVERHEAD + (COMPARISON_OVERHEAD if en["kind"] == "comparison" else 0)
                     for en in entries)
                 + sum(print_units(en["staff_note"]) + STAFF_BLOCK_OVERHEAD for en in entries if en.get("staff_note"))
                 + sum(print_units(staff[k]) + STAFF_BLOCK_OVERHEAD for k in ("note", "next_steps") if k in staff)
                 + TITLE_WEIGHT * print_units(staff.get("title") or f"District brief: {prof['label']}")
                 + SMALL_TEXT_WEIGHT * (sum(print_units(x) + 40 for x in lims)
                                        + sum(print_units(f"{c['publisher']} {c['source_id']} {c['url']} "
                                                          + "; ".join(c["locators"])) + 80 for c in citations)))
        units = int(round(units))
        default_title = f"District brief: {prof['label']}"
        blob = json.dumps({"s": self.snapshot_id, "p": profile_id, "f": finding_ids, "e": edits},
                          sort_keys=True, ensure_ascii=False)
        brief = {
            "brief_id": "brief:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
            "title": staff.get("title") or default_title,
            "title_is_staff_edit": bool(staff.get("title")),
            "default_title": default_title,
            "geography": {"geography_id": profile_id, "label": prof["label"]},
            "snapshot_id": self.snapshot_id,
            "entries": entries,
            "citations": citations,
            "staff_edits": staff,
            "staff_edit_label": "Staff edit — not a verified fact",
            "limitations": lims,
            "edit_limits": EDIT_LIMITS,
            "print_units": units,
            "print_budget": BRIEF_PRINT_BUDGET,
        }
        if units > BRIEF_PRINT_BUDGET:
            raise Unsupported(
                f"This brief is too long for one printed page (estimated {units} of {BRIEF_PRINT_BUDGET} print units). "
                "Remove a finding or shorten the staff notes, then build it again. Nothing is cropped or dropped.",
                data={"print_units": units, "print_budget": BRIEF_PRINT_BUDGET})
        return {"findings": findings, "limitations": lims, "data": {"brief": brief}}

    # ---------------------------------------------------------------- source
    def source(self, source_id: str, finding_id: str | None = None) -> dict:
        src = self.packet.sources.get(source_id)
        if src is None:
            raise Unsupported(f"Source {source_id!r} is not in the packet's source manifests.")
        status = self.packet.source_file_status(source_id)
        cited_by = {
            "observations": [oid for oid, o in self.observations.items() if o["source_id"] == source_id],
            "programs": [p["program_id"] for p in self.programs.values()
                         if source_id in p["source_ids"] or any(e["source_id"] == source_id for e in p["evidence"])],
            "participation": [r["observation_id"] for r in self.participation if r["source_id"] == source_id],
        }
        detail = None
        if finding_id:
            detail = self._source_detail(src, finding_id, status)
        out = {"source": src, "retained_file": status, "cited_by": {k: v for k, v in cited_by.items()},
               "not_cited": not any(cited_by.values()),
               "fetch_policy": getattr(self.packet, "fetch_policy", "Retained packet bytes only; the URL is citation provenance and is never fetched."),
               "detail": detail}
        return out

    def _source_detail(self, src, finding_id, status) -> dict:
        f = self.finding(finding_id)
        if getattr(self.packet, 'profile', None) == 'public':
            # A normalized projection is not a reread of an omitted workbook or page.
            cited = ([f.get('source', {}).get('source_id')] if f['kind'] in ('statistic', 'administrative_context')
                     else [e['source_id'] for e in f.get('evidence', [])])
            if src['source_id'] not in cited:
                raise Unsupported('The finding does not cite this source.')
            return {'type': 'projection_reference', 'available': True,
                    'verification_kind': 'normalized_projection', 'cell_verified': False,
                    'origin_bytes_available': status['available'],
                    'verification_note': 'The bundled normalized facts and provenance are verified. '
                        'Historical source hashes and locators identify the original capture. '
                        'This view does not reread omitted original workbooks, pages or text extracts.',
                    'locator': f.get('source', {}).get('locator'),
                    'normalized_reference': f}
        if f["kind"] == "administrative_context":
            if f["source"]["source_id"] != src["source_id"]:
                raise Unsupported(f"Finding {finding_id} does not cite {src['source_id']}.")
            row = self.administrative_rows[f["observation_id"]]
            loc = dict(row["locator"])
            detail = {"type": "administrative_row", "available": status["available"], "locator": loc,
                      "normalized_row": dict(row), "cell_verified": None, "verification_kind": "hash_locator_only",
                      "verification_note": "Retained file hash and full locator only; no raw-cell reread "
                                                  "for genuine BIFF XLS/PDF. A hash match does not prove a cell match."}
            if src["packet_path"].lower().endswith(".xlsx") and loc.get("sheet") and loc.get("cell"):
                detail["cell_verified"] = False
                detail["verification_kind"] = "cell_reread"
                detail["verification_note"] = "Addressable XLSX cell reread and compared with normalized value."
                if status["available"]:
                    cells = xlsx.read_cells(str(self.packet.path(src["packet_path"])), loc["sheet"], [loc["cell"]])
                    detail["stored_text"] = cells.get(loc["cell"])
                    detail["cell_verified"] = _cell_matches(detail["stored_text"], row["value"])
            return detail
        if f["kind"] == "statistic":
            if f["source"]["source_id"] != src["source_id"]:
                raise Unsupported(f"Finding {finding_id} does not cite {src['source_id']}.")
            loc = f["source"]["locator"]
            if not status["available"]:
                return {"type": "sheet_cell", "available": False, "reason": status["reason"], "locator": loc,
                        "cell_verified": False, "verification_kind": "cell_reread_unavailable"}
            refs = [loc["label_cell"], loc["geography_cell"], loc["estimate_cell"], loc["moe_cell"]]
            cells = xlsx.read_cells(str(self.packet.path(src["packet_path"])), loc["sheet"], refs)
            o = self.observations[f["observation_id"]]
            stored_est, stored_moe = cells.get(loc["estimate_cell"]), cells.get(loc["moe_cell"])
            return {
                "type": "sheet_cell", "available": True, "locator": loc,
                "cells": [{"ref": r, "role": role, "stored_text": cells.get(r)} for r, role in
                          zip(refs, ("label", "geography", "estimate", "margin of error"))],
                "cell_verified": (_cell_matches(stored_est, o["estimate"]) and
                                  ((stored_moe is not None and "*****" in stored_moe) if o["margin_of_error"] is None
                                   else _cell_matches(stored_moe, o["margin_of_error"]))),
                "verification_kind": "cell_reread",
                "published_display": {"estimate": o["raw_cells"]["estimate"], "moe": o["raw_cells"]["moe"]},
                "estimate_matches": _cell_matches(stored_est, o["estimate"]),
                "moe_matches": (stored_moe is not None and "*****" in stored_moe) if o["margin_of_error"] is None
                else _cell_matches(stored_moe, o["margin_of_error"]),
            }
        if f["kind"] == "program_relevance":
            spans = [e for e in f["evidence"] if e["source_id"] == src["source_id"]]
            if not spans:
                raise Unsupported(f"Finding {finding_id} does not cite {src['source_id']}.")
            return {"type": "text_spans", "available": status["available"], "spans": spans}
        raise Unsupported("Source detail is available for statistic and program findings; open the cited "
                          "statistic or program finding instead.")


def _cell_matches(stored: str | None, value) -> bool:
    if stored is None or value is None:
        return False
    try:
        num = float(re.sub(r"[^\d.\-]", "", stored))
    except ValueError:
        return False
    return abs(num - value) < 1e-6 or abs(num * 100 - value) < 1e-6
