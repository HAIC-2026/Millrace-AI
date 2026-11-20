#!/usr/bin/env python3
"""Build or check the public ACS expansion using pinned, retained inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import compile_statistics as compiler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from districtbrief.public_packet import PublicPacket, public_metadata, records, snapshot_id

BASELINE_MANIFEST_SHA256 = "ada890eece21c2be8df5d305548e0a06d9880c49fe57e87dd8bb1fe889133ddb"
PACKET_MANIFEST = "PACKET-MANIFEST.json"
OBSERVATIONS = compiler.OBSERVATIONS


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def pinned_manifest(path, expected_sha256):
    body = path.read_bytes()
    if compiler.sha256(body) != expected_sha256:
        raise ValueError(f"Unexpected manifest hash for {path}")
    return json.loads(body)


def build(baseline_packet, source_manifest_path, statistics_dir):
    baseline_manifest = pinned_manifest(baseline_packet / PACKET_MANIFEST, BASELINE_MANIFEST_SHA256)
    baseline_files = records(baseline_packet, PACKET_MANIFEST)
    if baseline_files != baseline_manifest["files"] or snapshot_id(baseline_files) != baseline_manifest["snapshot_id"]:
        raise ValueError("Baseline public packet does not match its pinned manifest")

    source_manifest = pinned_manifest(source_manifest_path, compiler.SOURCE_MANIFEST_SHA256)
    baseline = json.loads((baseline_packet / OBSERVATIONS).read_bytes())
    compiled = json.loads(compiler.compile_observations(source_manifest, statistics_dir=statistics_dir,
                                                       include_guided_expansion=True))
    new_metrics = {item[0] for item in compiler.GUIDED_EXPANSION}
    original_rows = [row for row in compiled["observations"] if row["metric_id"] not in new_metrics]
    added_rows = [row for row in compiled["observations"] if row["metric_id"] in new_metrics]
    if len(original_rows) != 1640 or original_rows != baseline["observations"]:
        raise ValueError("Original 1,640 observations differ from the public baseline")
    if len(added_rows) != 82 * len(new_metrics) or len({r["observation_id"] for r in added_rows}) != len(added_rows):
        raise ValueError("New observations do not cover each geography and metric exactly once")
    baseline["observations"].extend(added_rows)
    observations = json_bytes(baseline)

    files = [dict(row, bytes=len(observations), sha256=compiler.sha256(observations))
             if row["path"] == OBSERVATIONS else row for row in baseline_files]
    packet_id = snapshot_id(files)
    packet_manifest = json_bytes(dict(baseline_manifest, files=files, snapshot_id=packet_id))

    meta_root = ROOT / "candidate-metadata"
    metadata = public_metadata(meta_root)
    input_files = sorted(
        [dict(row, path="runtime-packet/" + row["path"]) for row in files]
        + [dict(row, path="candidate-metadata/" + row["path"]) for row in records(meta_root, "MANIFEST.json")],
        key=lambda row: row["path"].encode("utf-8"),
    )
    inputs = {
        "schema": "ia1-projection-inputs/1",
        "description": "Bundled normalized facts and authored metadata. Historical capture references do not verify omitted origin bytes.",
        "files": input_files,
    }
    outputs = {
        "runtime-packet/" + OBSERVATIONS: observations,
        "runtime-packet/" + PACKET_MANIFEST: packet_manifest,
        "docs/PROJECTION-INPUTS.json": json_bytes(inputs),
    }
    report = {
        "baseline_data_snapshot_id": baseline_manifest["snapshot_id"],
        "data_snapshot_id": packet_id,
        "data_manifest_sha256": compiler.sha256(packet_manifest),
        "combined_evidence_snapshot_id": metadata.combined_snapshot_id(packet_id),
        "metadata_snapshot_id": metadata.metadata_snapshot_id,
        "observations_sha256": compiler.sha256(observations),
        "original_observations_preserved": len(original_rows),
        "new_observations": len(added_rows),
        "new_metrics": len(new_metrics),
    }
    return outputs, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-packet", required=True, type=Path, help="ac065bd runtime-packet directory")
    parser.add_argument("--source-manifest", required=True, type=Path, help="retained SOURCE-PACKET-MANIFEST.json")
    parser.add_argument("--statistics-dir", required=True, type=Path, help="retained statistics/ with manifest.json and raw/")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-directory", type=Path, help="new directory outside the publication tree")
    mode.add_argument("--check", action="store_true", help="compare regenerated files to the bundled projection")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without python -O: compiler validation uses assertions")
    outputs, report = build(args.baseline_packet, args.source_manifest, args.statistics_dir)
    if args.check:
        differences = [name for name, body in outputs.items() if (ROOT / name).read_bytes() != body]
        if differences:
            raise SystemExit("Projection differs from regenerated evidence: " + ", ".join(differences))
        PublicPacket(ROOT / "runtime-packet")
        report["verified_identical"] = True
    else:
        target = args.output_directory.resolve()
        if target == ROOT or ROOT in target.parents:
            parser.error("Output directory must stay outside the publication tree")
        target.mkdir()
        for name, body in outputs.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
