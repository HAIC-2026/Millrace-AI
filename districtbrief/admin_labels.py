"""Reviewed administrative series labels, tied to recorded locator and coverage.

These labels describe the retained publisher series, not a derived population.
Review is AI engineering review of packet locators/coverage, not staff acceptance.
"""

SERIES = {
    "snap_monthly_persons": ("SNAP monthly caseload — persons", "All SNAP categories; statewide monthly persons"),
    "snap_monthly_households": ("SNAP monthly caseload — households", "All SNAP categories; statewide monthly households"),
    "snap_average_monthly_persons": ("Food Stamp Program — average monthly persons", "Average monthly individuals; period basis unspecified"),
    "medicaid_managed_care": ("Medicaid managed care total", "Paid managed-care capitation; at least part of month"),
    "medicaid_only": ("Medicaid Only total", "Fee for Service plus Medicare Savings Only; excludes managed care"),
    "medicaid_total_enrollment": ("Medicaid total enrollment", "Managed care plus Medicaid Only; includes Medicare Savings Only"),
    "medicaid_managed_care_island": ("Medicaid managed care by island", "Paid managed-care capitation only; excludes Medicaid Only"),
}

ROW_SERIES = {}
for n in (1, 3, 5, 7):
    ROW_SERIES[f"hi_snap_sfy2027_{n:03}"] = "snap_monthly_persons"
for n in (2, 4, 6):
    ROW_SERIES[f"hi_snap_sfy2027_{n:03}"] = "snap_monthly_households"
for n in range(8, 13):
    ROW_SERIES[f"dbedt_county_h_{n:03}"] = "snap_average_monthly_persons"
for lo, hi, series in ((13, 16, "medicaid_managed_care"), (16, 19, "medicaid_only"),
                       (19, 22, "medicaid_total_enrollment"), (22, 25, "medicaid_managed_care_island")):
    for n in range(lo, hi):
        ROW_SERIES[f"hi_mqd_enrollment_2026_{n:03}"] = series


def metadata(row):
    series_id = ROW_SERIES[row["observation_id"]]
    label, coverage = SERIES[series_id]
    # Preserve the publisher's distinction between unpopulated month and observed zero.
    if row["status"] == "unpublished":
        coverage = "Preallocated month; category inputs unpopulated; value unpublished"
    return {"series_id": series_id, "series_label": label, "coverage_label": coverage}
