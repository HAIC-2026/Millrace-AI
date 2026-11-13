"""Read-only access to the frozen builder packet.

Every byte the application uses comes from the sibling ``builder-packet/``
directory. On load we verify each payload file against PACKET-MANIFEST.json and
recompute ``snapshot_id`` with the manifest's own digest rule; any mismatch is a
different, unaccepted packet and loading fails.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ACCEPTED_SNAPSHOT_ID = "sha256:7a8849f0759010fff359f589730e6e3c9bad70b4af3788cf1a304424c99fe96d"
ACCEPTED_MANIFEST_SHA256 = "ec95c6b8e95e7908f89baae757d6b6885daf678531a9ceb79842d493dd463f1d"

FAMILY_MANIFESTS = {
    "statistics": "data/statistics/manifest.json",
    "geography": "data/geography/manifest.json",
    "programs": "data/programs/manifests.json",
    "participation": "data/participation/manifests.json",
}


class PacketError(Exception):
    """The packet is missing, altered or not the accepted snapshot."""


def default_packet_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "builder-packet"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Packet:
    """Verified, read-only view of the packet files."""

    def __init__(self, packet_dir: str | Path | None = None, verify: bool = True):
        self.dir = Path(packet_dir or default_packet_dir()).resolve()
        manifest_path = self.dir / "PACKET-MANIFEST.json"
        if not manifest_path.is_file():
            raise PacketError(f"PACKET-MANIFEST.json not found under {self.dir}")
        self.manifest_sha256 = _sha256(manifest_path)
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.snapshot_id = self.manifest.get("snapshot_id")
        self.files = {f["path"]: f for f in self.manifest["files"]}
        self.verification = self._verify() if verify else {"verified": False}
        self.sources = self._load_sources()

    # -- integrity -------------------------------------------------------
    def _verify(self) -> dict:
        problems = []
        for rel, entry in self.files.items():
            p = self.dir / rel
            if not p.is_file():
                problems.append(f"missing {rel}")
                continue
            if p.stat().st_size != entry["bytes"] or _sha256(p) != entry["sha256"]:
                problems.append(f"hash/size mismatch {rel}")
        lines = "".join(
            f"{f['sha256']}  {f['bytes']}  {f['path']}\n"
            for f in sorted(self.manifest["files"], key=lambda f: f["path"].encode("utf-8"))
        )
        computed = "sha256:" + hashlib.sha256(lines.encode("utf-8")).hexdigest()
        if computed != self.snapshot_id:
            problems.append("snapshot_id does not match digest rule")
        if self.snapshot_id != ACCEPTED_SNAPSHOT_ID:
            problems.append(f"snapshot_id {self.snapshot_id} is not the accepted snapshot")
        if problems:
            raise PacketError("; ".join(problems))
        return {
            "verified": True,
            "file_count": len(self.files),
            "snapshot_id": computed,
            "manifest_sha256": self.manifest_sha256,
            "manifest_sha256_matches_accepted": self.manifest_sha256 == ACCEPTED_MANIFEST_SHA256,
        }

    # -- access ----------------------------------------------------------
    def path(self, rel: str) -> Path:
        """Resolve a packet-relative path, refusing anything outside the packet or unlisted."""
        p = (self.dir / rel).resolve()
        if self.dir not in p.parents:
            raise PacketError(f"path escapes packet: {rel}")
        if str(p.relative_to(self.dir)) not in self.files and p.name != "PACKET-MANIFEST.json":
            raise PacketError(f"path not listed in packet manifest: {rel}")
        return p

    def read_json(self, rel: str):
        return json.loads(self.path(rel).read_text(encoding="utf-8"))

    def read_text(self, rel: str) -> str:
        return self.path(rel).read_text(encoding="utf-8")

    def _load_sources(self) -> dict:
        sources = {}
        for family, rel in FAMILY_MANIFESTS.items():
            base = rel.rsplit("/", 1)[0]
            for entry in self.read_json(rel):
                packet_path = f"{base}/{entry['path']}"
                listed = self.files.get(packet_path)
                sources[entry["source_id"]] = {
                    "source_id": entry["source_id"],
                    "family": family,
                    "publisher": entry.get("publisher"),
                    "url": entry.get("url"),
                    "final_url": entry.get("final_url"),
                    "retrieved_at_utc": entry.get("retrieved_at_utc"),
                    "content_type": entry.get("content_type"),
                    "bytes": entry.get("bytes"),
                    "sha256": entry.get("sha256"),
                    "packet_path": packet_path,
                    "manifest_path": rel,
                    "listed_in_packet_manifest": listed is not None,
                    "notes": entry.get("notes"),
                }
        return sources

    def source_file_status(self, source_id: str) -> dict:
        """Re-hash the retained file for one source (no network)."""
        src = self.sources.get(source_id)
        if src is None:
            return {"available": False, "reason": "unknown source_id"}
        try:
            p = self.path(src["packet_path"])
        except PacketError as exc:
            return {"available": False, "reason": str(exc)}
        if not p.is_file():
            return {"available": False, "reason": "retained file missing"}
        digest = _sha256(p)
        ok = digest == src["sha256"]
        return {
            "available": ok,
            "sha256_on_disk": digest,
            "matches_source_manifest": ok,
            "reason": None if ok else "retained bytes do not match source manifest hash",
        }
