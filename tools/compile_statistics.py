"""Offline, deterministic statewide ACS normalization for the guided release.

Standard library only (Python 3.11+). No network, no openpyxl, no timestamps.

Inputs (all inside ``runtime-packet/``, verified against the pinned, unchanged
source packet manifest ``SOURCE-PACKET-MANIFEST.json`` before use):
  data/statistics/manifest.json            source records (URL, retrieval time, hash)
  data/statistics/raw/{house,senate,state,counties}.xlsx   DBEDT 2024 ACS workbooks
  data/statistics/raw/DP0{2,3,4,5}_metadata.json           Census variable labels

Outputs:
  data/statistics/observations.json  20 measures x (51 House + 25 Senate districts,
                                     State of Hawaii and five counties) = 1,640 rows
  PACKET-MANIFEST.json               release packet manifest with a new snapshot_id

Column mapping is read from each sheet's own headers: row 1 names the geography
that starts a column block, row 2 names each column's statistic. Nothing is
assumed about district order, block width or sheet order.

Values: a cell holding a plain published number becomes a numeric estimate or
margin. Anything else (annotation symbols, open-ended medians such as
"3,500+", blanks) keeps its raw text, gets a null numeric value and an
annotation, and is never replaced by zero or an invented number.

Usage:
  python3 tools/compile_statistics.py            rewrite the two outputs
  python3 tools/compile_statistics.py --check    recompile in memory and compare bytes
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

RELEASE = Path(__file__).resolve().parents[1]
PACKET = RELEASE / "runtime-packet"
STATS = PACKET / "data" / "statistics"
OBSERVATIONS = "data/statistics/observations.json"

# The unchanged original builder packet manifest (89 entries; 85 data files are retained).
SOURCE_SNAPSHOT_ID = "sha256:7a8849f0759010fff359f589730e6e3c9bad70b4af3788cf1a304424c99fe96d"
SOURCE_MANIFEST_SHA256 = "ec95c6b8e95e7908f89baae757d6b6885daf678531a9ceb79842d493dd463f1d"

# Reviewed row-to-Census-variable mapping, unchanged from the pilot extraction.
# id, table, workbook row, Census stem, statistic, row label, unit, universe
METRICS = [
 ("total_households","DP02",4,"0001","estimate","Total households","households","Households"),
 ("male_householder_65_plus_living_alone","DP02",12,"0009","estimate","65 years and over","households","Households with male householder, no spouse/partner present, living alone, age 65 years and over"),
 ("female_householder_65_plus_living_alone","DP02",16,"0013","estimate","65 years and over","households","Households with female householder, no spouse/partner present, living alone, age 65 years and over"),
 ("households_with_social_security","DP03",74,"0066","estimate","With Social Security","households","Households; receipt of Social Security income in past 12 months, not fixed-income status or recipient count"),
 ("total_population","DP05",4,"0001","estimate","Total population","persons","Total population"),
 ("population_65_plus","DP05",27,"0024","estimate","65 years and over","persons","Total population"),
 ("median_age","DP05",21,"0018","estimate","Median age (years)","years","Total population"),
 ("median_household_income","DP03",70,"0062","estimate","Median household income (dollars)","2024 inflation-adjusted USD","Households; income in past 12 months"),
 ("poverty_rate_all_people","DP03",138,"0128","percent","All people","percent","Population for whom poverty status is determined"),
 ("poverty_rate_65_plus","DP03",145,"0135","percent","65 years and over","percent","People age 65 years and over for whom poverty status is determined"),
 ("civilian_labor_force","DP03",6,"0003","estimate","Civilian labor force","persons","Population age 16 years and over; civilian labor force"),
 ("unemployed","DP03",8,"0005","estimate","Unemployed","persons","Population age 16 years and over in civilian labor force"),
 ("unemployment_rate","DP03",12,"0009","percent","Unemployment Rate","percent","Civilian labor force age 16 years and over"),
 ("education_health_social_assistance_industry","DP03",48,"0042","estimate","Educational services, and health care and social assistance","persons","Civilian employed population age 16 years and over; industry of employment"),
 ("total_housing_units","DP04",4,"0001","estimate","Total housing units","housing units","Housing units"),
 ("occupied_housing_units","DP04",5,"0002","estimate","Occupied housing units","housing units","Housing units"),
 ("renter_occupied_units","DP04",55,"0047","estimate","Renter-occupied","housing units","Occupied housing units"),
 ("median_gross_rent","DP04",152,"0134","estimate","Median (dollars)","USD per month","Renter-occupied housing units paying cash rent"),
 ("rent_burden_denominator","DP04",155,"0136","estimate","Occupied units paying rent (excluding units where GRAPI cannot be computed)","housing units","Occupied units paying rent with computable gross rent as a percentage of household income"),
 ("rent_35_plus_percent_income","DP04",161,"0142","estimate","35.0 percent or more","housing units","Occupied units paying rent with computable gross rent as a percentage of household income"),
]
JOINT = ("male_householder_65_plus_living_alone", "female_householder_65_plus_living_alone", "poverty_rate_65_plus")
TABLES = ("DP02", "DP03", "DP04", "DP05")
LIMITATIONS = [
    "DBEDT republished ACS values are the numerical fixture; Census API group metadata corroborates definitions, not an independent measurement.",
    "Poverty status universe excludes several populations. Age-specific poverty rate is a published joint statistic; it is not a count of seniors, fixed-income seniors or program-eligible seniors.",
    "Social Security receipt is at household level and does not establish fixed-income status.",
]
# Row 2 header text for the two statistics a measure can use, and for their margins.
VALUE_HEADER = {"estimate": "Estimate", "percent": "Percent"}
MOE_HEADER = {"estimate": "Margin of Error", "percent": "Percent Margin of Error"}
DISTRICT_HEADER = re.compile(r"State (House|Senate) District ([0-9]{1,3}) \(2024\); Hawaii")
PLAIN_NUMBER = re.compile(r"[±]?[-]?[\d,]+(?:\.\d+)?%?")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def column_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def column_letters(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def read_workbook(data: bytes) -> dict:
    """Return {sheet name: {(row, column): stored text}} for non-empty cells."""
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")).iter(PKG + "Relationship")}
        shared = []
        for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).iter(NS + "si"):
            # Rich-text runs are concatenated; phonetic runs are not displayed text.
            shared.append("".join((t.text or "") for el in si if el.tag in (NS + "t", NS + "r")
                                  for t in ([el] if el.tag == NS + "t" else el.findall(NS + "t"))))
        sheets = {}
        for sheet in ET.fromstring(zf.read("xl/workbook.xml")).find(NS + "sheets"):
            target = rels[sheet.get(RID)]
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            cells = {}
            for c in ET.fromstring(zf.read(part)).iter(NS + "c"):
                kind, v = c.get("t", "n"), c.find(NS + "v")
                if v is None or v.text is None:
                    continue
                if kind == "s":
                    text = shared[int(v.text)]
                elif kind == "n":
                    text = v.text
                else:
                    raise SystemExit(f"unexpected cell type {kind!r} at {sheet.get('name')}!{c.get('r')}")
                if text != "":
                    m = re.fullmatch(r"([A-Z]+)([0-9]+)", c.get("r"))
                    cells[(int(m.group(2)), column_number(m.group(1)))] = text
            name = sheet.get("name")
            assert name not in sheets, name
            sheets[name] = cells
    return sheets


def header_blocks(cells: dict) -> dict:
    """Map each row-1 geography name to {row-2 header text: column} for its column block."""
    starts = sorted((col, text) for (row, col), text in cells.items() if row == 1 and col > 1)
    last = max(col for (row, col) in cells if row == 2)
    blocks = {}
    for i, (col, name) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else last
        roles = {}
        for c in range(col, end + 1):
            role = cells.get((2, c))
            assert role is not None and role not in roles, (name, c, role)
            roles[role] = c
        assert set(roles) == {"Estimate", "Margin of Error", "Percent", "Percent Margin of Error"}, (name, roles)
        assert name not in blocks, f"duplicate geography header {name!r}"
        blocks[name] = dict(roles, _start=col)
    return blocks


def parse(raw):
    """(numeric value, annotation). A plain published number has no annotation."""
    if raw is None:
        return None, "blank"
    s = raw.strip()
    if PLAIN_NUMBER.fullmatch(s):
        return float(s.replace("±", "").replace(",", "").replace("%", "")), None
    return None, s


def compile_observations(source_manifest: dict) -> bytes:
    listed = {f["path"]: f for f in source_manifest["files"]}
    raw = {}
    for rel in ["data/statistics/manifest.json"] + [f"data/statistics/raw/{k}.xlsx" for k in ("house", "senate", "state", "counties")] \
            + [f"data/statistics/raw/{t}_metadata.json" for t in TABLES]:
        data = (PACKET / rel).read_bytes()
        assert len(data) == listed[rel]["bytes"] and sha256(data) == listed[rel]["sha256"], f"input differs from source packet: {rel}"
        raw[rel] = data
    sources = {s["source_id"]: s for s in json.loads(raw["data/statistics/manifest.json"])}
    meta = {t: json.loads(raw[f"data/statistics/raw/{t}_metadata.json"])["variables"] for t in TABLES}
    books = {}
    for kind in ("house", "senate", "state", "counties"):
        data = raw[f"data/statistics/raw/{kind}.xlsx"]
        assert sha256(data) == sources[f"dbedt_2024_{kind}"]["sha256"], kind
        sheets = read_workbook(data)
        assert set(sheets) == set(TABLES), (kind, sorted(sheets))
        books[kind] = {t: (sheets[t], header_blocks(sheets[t])) for t in TABLES}

    # Geographies, from the headers actually present in every profile sheet.
    selections = [("state", "Hawaii", "HI-STATE-2024",
                   {"state_fips": "15", "chamber": None, "district_code": None, "geoid": "15", "boundary_session": None,
                    "boundary_vintage": "2024-01-01", "summary_level": "040"}),
                  ("counties", "Maui County, Hawaii", "HI-COUNTY-009-2024",
                   {"state_fips": "15", "chamber": None, "district_code": None, "geoid": "15009", "boundary_session": None,
                    "boundary_vintage": "2024-01-01", "summary_level": "050"})]
    for chamber, count, level in (("house", 51, "620"), ("senate", 25, "610")):
        found = {}
        for table in TABLES:
            numbers = []
            for name in books[chamber][table][1]:
                m = DISTRICT_HEADER.fullmatch(name)
                assert m and m.group(1).lower() == chamber, (chamber, table, name)
                numbers.append(int(m.group(2)))
                found.setdefault(int(m.group(2)), set()).add(name)
            assert sorted(numbers) == list(range(1, count + 1)), (chamber, table, sorted(numbers))
        for number in range(1, count + 1):
            (name,) = found[number]
            code = f"{number:03}"
            selections.append((chamber, name, f"HI-{chamber.upper()}-{code}-2024",
                               {"state_fips": "15", "chamber": chamber, "district_code": code, "geoid": "15" + code,
                                "boundary_session": 2024, "summary_level": level}))

    # Append the four additional native county profiles; retain existing ordering.
    for name, code in (("Hawaii", "001"), ("Honolulu", "003"), ("Kalawao", "005"), ("Kauai", "007")):
        selections.append(("counties", f"{name} County, Hawaii", f"HI-COUNTY-{code}-2024",
                           {"state_fips": "15", "chamber": None, "district_code": None, "geoid": "15" + code,
                            "boundary_session": None, "boundary_vintage": "2024-01-01", "summary_level": "050"}))

    observations = []
    for kind, header, key, geography in selections:
        source = sources[f"dbedt_2024_{kind}"]
        geography = dict(geography, source_name=header)
        for mid, table, row, stem, stat, label, unit, universe in METRICS:
            cells, blocks = books[kind][table]
            assert cells.get((row, 1)) == label, (kind, table, row, label, cells.get((row, 1)))
            variable = f"{table}_{stem}{'PE' if stat == 'percent' else 'E'}"
            assert meta[table][variable]["label"].endswith("!!" + label), (variable, meta[table][variable]["label"])
            block = blocks[header]
            value_col, moe_col = block[VALUE_HEADER[stat]], block[MOE_HEADER[stat]]
            value_raw, moe_raw = cells.get((row, value_col)), cells.get((row, moe_col))
            value, annotation = parse(value_raw)
            moe, moe_annotation = parse(moe_raw)
            observations.append({
                "observation_id": f"{key}:{mid}", "geography": dict(geography), "metric_id": mid, "label": label,
                "table_id": table, "variable_id": variable, "margin_of_error_variable_id": variable[:-1] + "M",
                "official_variable_label": meta[table][variable]["label"], "universe": universe, "unit": unit,
                "period": {"start_year": 2020, "end_year": 2024, "product": "2024 ACS 5-year estimates",
                           "dollar_year": 2024 if "USD" in unit else None},
                "estimate": value, "margin_of_error": moe, "moe_confidence_level": 0.90,
                "annotation": annotation, "moe_annotation": moe_annotation,
                "raw_cells": {"sheet": table, "label_cell": f"A{row}",
                              "geography_cell": f"{column_letters(block['_start'])}1",
                              "estimate_cell": f"{column_letters(value_col)}{row}", "estimate": value_raw,
                              "moe_cell": f"{column_letters(moe_col)}{row}", "moe": moe_raw},
                "source_id": source["source_id"], "source_url": source["url"], "source_sha256": source["sha256"],
                "retrieved_at_utc": source["retrieved_at_utc"],
                "spatial_method": "native published geography; no apportionment",
                "joint_statistic": mid in JOINT,
            })
    assert len(observations) == len(METRICS) * 82
    payload = {"schema_version": "1.0", "observations": observations, "limitations": LIMITATIONS}
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def compile_manifest(source_manifest: dict, observations: bytes) -> bytes:
    files = []
    for entry in source_manifest["files"]:
        if not entry["path"].startswith("data/"):
            continue  # four handoff/specification files are not runtime data
        if entry["path"] == OBSERVATIONS:
            files.append({"path": OBSERVATIONS, "bytes": len(observations), "sha256": sha256(observations),
                          "role": "normalized_statistics", "origin": "release_derived",
                          "derived_by": "tools/compile_statistics.py",
                          "replaces_source_packet_sha256": entry["sha256"]})
        else:
            data = (PACKET / entry["path"]).read_bytes()
            assert len(data) == entry["bytes"] and sha256(data) == entry["sha256"], entry["path"]
            files.append({"path": entry["path"], "bytes": entry["bytes"], "sha256": entry["sha256"],
                          "role": entry["role"], "origin": "source_packet_unchanged"})
    files.sort(key=lambda f: f["path"].encode("utf-8"))
    lines = "".join(f"{f['sha256']}  {f['bytes']}  {f['path']}\n" for f in files)
    manifest = {
        "schema": "haic-guided-statewide-packet-manifest/1",
        "packet": "Guided statewide runtime packet: 84 unchanged source-packet data files and one regenerated "
                  "statistics normalization covering all 51 House and 25 Senate districts",
        "snapshot_id": "sha256:" + sha256(lines.encode("utf-8")),
        "snapshot_digest_rule": "snapshot_id = 'sha256:' + hex SHA-256 of the UTF-8 text formed by one line "
                                "'<sha256>  <bytes>  <path>\\n' per listed file, sorted by path (UTF-8 byte order). "
                                "Both manifest files are excluded.",
        "derived_from": {"source_snapshot_id": SOURCE_SNAPSHOT_ID,
                         "source_packet_manifest": "SOURCE-PACKET-MANIFEST.json",
                         "source_packet_manifest_sha256": SOURCE_MANIFEST_SHA256,
                         "note": "This packet is a derivative. It is not the source snapshot and is not "
                                 "byte-identical to it: " + OBSERVATIONS + " is regenerated."},
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
    }
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    source_bytes = (PACKET / "SOURCE-PACKET-MANIFEST.json").read_bytes()
    assert sha256(source_bytes) == SOURCE_MANIFEST_SHA256, "SOURCE-PACKET-MANIFEST.json is not the pinned source manifest"
    source_manifest = json.loads(source_bytes)
    assert source_manifest["snapshot_id"] == SOURCE_SNAPSHOT_ID
    observations = compile_observations(source_manifest)
    manifest = compile_manifest(source_manifest, observations)
    outputs = {PACKET / OBSERVATIONS: observations, PACKET / "PACKET-MANIFEST.json": manifest}
    check = "--check" in sys.argv[1:]
    same = True
    for path, data in outputs.items():
        if check:
            same = same and path.is_file() and path.read_bytes() == data
        else:
            path.write_bytes(data)
    report = {"mode": "check" if check else "write", "observations": len(json.loads(observations)["observations"]),
              "observations_sha256": sha256(observations), "observations_bytes": len(observations),
              "packet_manifest_sha256": sha256(manifest), "snapshot_id": json.loads(manifest)["snapshot_id"]}
    if check:
        report["byte_identical_to_release"] = same
    print(json.dumps(report, indent=2))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
