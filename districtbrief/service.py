"""Request handling shared by the HTTP server and tests.

Run = resolve (no core query) then execute (one core operation). Resolution is
returned first so the header can show the resolved task and district context
before the core query. Every phase is logged as one JSON line with route,
operation arguments, validation failures, status, elapsed time and model-call
count. Hosted routing is explicit and never changes deterministic facts.
"""

from __future__ import annotations

import copy
import json
import secrets
import threading
import time
import traceback
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from . import render, route_a
from .contract import TEMPLATES, envelope, validate_request
from .core import Core, Unsupported

PENDING_LIMIT = 256
C_INFLIGHT_LIMIT = 8
C_HISTORY_LIMIT = 32
C_DEADLINE_SECONDS = 5
RE_EVENT_KINDS = ("select_finding", "deselect_finding", "apply_edits", "print", "view_source", "open_tab",
                  "choice_click")


class Service:
    def __init__(self, core: Core, log_dir: str | Path | None = None, *, variant="A", router=None):
        if variant != "A":
            raise ValueError("This release serves guided variant A only")
        self.core = core
        self.variant = variant
        self.router = router or route_a
        self.hosted = variant == "C" and getattr(self.router, "execution_kind", None) == "hosted"
        self.snapshot_id = core.snapshot_id
        self.pending: OrderedDict = OrderedDict()
        self.result_records: OrderedDict = OrderedDict()
        self.c_transactions: OrderedDict = OrderedDict()
        self.c_session_generations: OrderedDict = OrderedDict()
        self.c_prepare_sequence = 0
        self.lock = threading.Lock()
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.counters = {"core_operations": 0, "model_calls": 0}
        self._catalog = None

    # ------------------------------------------------------------- logging
    def _log(self, name: str, record: dict):
        record = dict(record, ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      model_calls=record.get("model_calls", 0), variant=self.variant)
        if self.variant == "C" and not self.hosted:
            record.update(weights_installed=self.router.package is not None,
                          learned_routing_tested=False, learned_quality_verified=False, remote_model_api_calls=0)
        if not self.log_dir:
            return
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.lock:
            with open(self.log_dir / name, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    # ------------------------------------------------------------ helpers
    def _with_html(self, env: dict) -> dict:
        if (env.get("resolution") or {}).get("decision"):
            env["decision"] = env["resolution"]["decision"]
        env["header_html"] = render.header_html(env.get("resolution"), env["status"], env.get("input_mode"),
                                                env.get("request_id"), env.get("context_id"))
        env["html"] = render.result_html(env)
        return env

    def _validation_error(self, raw, errors):
        rid = raw.get("request_id") if isinstance(raw, dict) and isinstance(raw.get("request_id"), str) else None
        env = envelope("error", None, self.snapshot_id, reason="The request failed contract validation.",
                       retry="Correct the listed fields and run again. Nothing was queried.",
                       validation_errors=errors, request_id=rid)
        env["decision"] = {"kind": "error", "reason": "request_validation_failed"}
        return self._with_html(env)

    def _usage(self, env: dict, phase: str) -> dict:
        if self.hosted:
            saved = (env.get("resolution") or {}).get("routing_usage") or {
                "model_calls": 0, "calls": [], "call_ids": [], "cost_usd": 0,
                "request_total_cost_usd": 0, "lane": "no_model", "config_hash": self.router.config_hash,
                "cost_basis": "documented usage-rate estimate; not invoice"}
            usage = copy.deepcopy(saved)
            usage["phase"] = phase
            if phase == "execute":
                usage.update(cost_usd=0, model_calls=0, calls=[], call_ids=[],
                             request_total_call_ids=saved.get("call_ids", []))
            env.update(variant="C", runtime=self.identity(), model_usage=usage,
                       model_calls=usage["model_calls"], remote_model_api_calls=usage["model_calls"])
            return env
        if self.variant == "C":
            env.update(variant="C", model_calls=0, remote_model_api_calls=0, runtime=self.identity())
            resolution = env.get("resolution") or {}
            if "decision" in resolution:
                env["decision"] = resolution["decision"]
            trace = resolution.get("routing_trace") or {}
            env["inference_usage"] = {"remote_model_api_calls": 0,
                "browser_result_received": trace.get("lane") == "browser_onnx",
                "execution": "browser_single_thread_wasm" if trace.get("lane") == "browser_onnx" else "none",
                "model_calls_scope": "remote_model_api_calls", "browser_execution_attested": False}
            return env
        if self.variant != "B":
            return env
        from .route_b import telemetry
        saved = ((env.get("resolution") or {}).get("routing_usage") or
                 telemetry(config_hash=self.router.config_hash, lane="no_model"))
        usage = dict(saved)
        usage["phase"] = phase
        if phase == "execute":
            usage.update(cost_usd=0, model_calls=0, calls=[], call_ids=[], tool_calls=[],
                         request_total_call_ids=saved.get("call_ids", []))
        env.update(variant=self.variant, model_usage=usage, model_calls=usage["model_calls"])
        return env

    def identity(self) -> dict:
        if self.hosted:
            runtime = self.router.runtime()
            return dict(runtime, variant="C", config_hash=self.router.config_hash,
                        label="Prototype C · hosted routing",
                        language_help="Bounded hosted interpretation over the checked fixture. Guided controls use zero model calls.",
                        guided_policy="shared_deterministic_zero_model")
        if self.variant == "C":
            runtime = self.router.runtime()
            label = "browser model installed" if runtime["ready"] else "package invalid" if runtime["status"] == "invalid" else "weights absent"
            return dict(runtime, variant="C", label="Prototype C · " + label,
                        language_help=("Local browser ONNX routing uses an explicitly installed package. Learned quality remains unverified."
                            if runtime["ready"] else "No usable local language model is installed. Use guided controls; learned routing is untested."),
                        guided_policy="shared_deterministic_zero_model", model=runtime.get("model_hash"),
                        config_hash=self.router.config_hash)
        return {"variant": self.variant,
                "label": "Prototype B · adapted to transfer contract" if self.variant == "B" else
                         "Prototype A · guided deterministic routing",
                "language_help": ("Bounded language routing over the same checked fixture. Guided controls use zero model calls."
                                  if self.variant == "B" else
                                  "Literal commands only (see “Typed commands”). Unrecognized text is not interpreted."),
                "guided_policy": "shared_deterministic_zero_model",
                "model": self.router.freeze["config"]["model"] if self.variant == "B" else None,
                "config_hash": self.router.config_hash if self.variant == "B" else None}

    # Metadata-only process-local provenance. This is neither authentication nor
    # a general restriction on selecting public finding IDs.
    @staticmethod
    def _metadata(fields):
        from .router_contract import METADATA_FIELDS
        return {k: copy.deepcopy(fields.get(k)) for k in METADATA_FIELDS}

    def _context_record(self, request):
        ref = request.get("result_reference")
        session = (request.get("action") or {}).get("session_id")
        reason = "reference_missing"
        with self.lock:
            record = self.result_records.get(ref) if ref else None
            if ref and record is None:
                reason = "reference_expired_or_unknown"
            elif record is not None:
                if record["snapshot_id"] != self.snapshot_id:
                    reason = "snapshot_mismatch"
                elif record["session_id"] != session:
                    reason = "session_mismatch"
                else:
                    return copy.deepcopy(record), {"kind": "server_issued_in_process", "reason": "matching_reference"}
        return None, {"kind": "client_carried", "reason": reason}

    def _remember_result(self, request, res, env):
        canonical = self._metadata(res)
        args = res.get("args") or {}
        for key in ("metric_ids", "comparison_geography", "program_ids", "observation_ids"):
            if key in args:
                canonical[key] = copy.deepcopy(args[key])
        if args.get("program_id"):
            canonical["program_ids"] = [args["program_id"]]
        descriptors, pairs = [], []
        def source_pairs(value, finding_id=None):
            if isinstance(value, dict):
                finding_id = value.get("finding_id") or finding_id
                if value.get("observation_id") in self.core.administrative_rows:
                    finding_id = "admin:" + value["observation_id"]
                if isinstance(value.get("source_id"), str) and finding_id:
                    yield {"source_id": value["source_id"], "finding_id": finding_id}
                for child in value.values():
                    yield from source_pairs(child, finding_id)
            elif isinstance(value, list):
                for child in value:
                    yield from source_pairs(child, finding_id)
        for finding in env.get("findings") or []:
            desc = {k: copy.deepcopy(finding[k]) for k in ("finding_id", "kind", "observation_id", "series_id", "unit", "period", "status") if k in finding}
            desc["profile_id"] = self.core.finding_profile(finding["finding_id"])
            if finding.get("metric"):
                desc["metric_id"] = finding["metric"]["metric_id"]
            if finding.get("program"):
                desc["program_id"] = finding["program"]["program_id"]
            descriptors.append(desc)
            for pair in source_pairs(finding):
                if pair not in pairs:
                    pairs.append(pair)
        ref = "result_" + secrets.token_urlsafe(24)
        record = {"snapshot_id": self.snapshot_id, "session_id": (request.get("action") or {}).get("session_id"),
                  "canonical": canonical, "submitted_controls": self._metadata(request),
                  "finding_descriptors": descriptors, "cited_pairs": pairs}
        with self.lock:
            self.result_records[ref] = record
            while len(self.result_records) > PENDING_LIMIT:
                self.result_records.popitem(last=False)
        return ref

    # ------------------------------------------------------------- resolve
    def resolve(self, raw) -> dict:
        t0 = time.perf_counter()
        request, errors = validate_request(raw, self.snapshot_id)
        if errors:
            env = self._validation_error(raw, errors)
            self._log("runs.jsonl", {"phase": "resolve", "request_id": env["request_id"], "status": "error",
                                     "validation_errors": errors, "core_called": False,
                                     "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)})
            return self._usage(env, "resolve")
        if self.variant == "C" and not self.hosted:
            with self.lock:
                self._expire_c_locked(time.monotonic())
                duplicate = any(r["request"]["request_id"] == request["request_id"] for r in self.c_transactions.values())
                if not duplicate:
                    self._supersede_c_locked(request)
            if duplicate:
                return self._c_error("request_id_reused", request)
        confirmed, provenance = self._context_record(request)
        # Server metadata travels separately from validated client-carried fields.
        if self.variant in ("B", "C"):
            if self.hosted:
                from .route_hosted import HostedRequestError
                try:
                    outcome = self.router.route(self.core, request, confirmed_context=confirmed)
                except HostedRequestError as exc:
                    return self._hosted_error(exc.code, request["request_id"])
            else:
                outcome = self.router.route(self.core, request, confirmed_context=confirmed)
        else:
            outcome = self.router.route(self.core, request)
        return self._resolve_outcome(request, outcome, provenance, t0)

    def _resolve_outcome(self, request, outcome, provenance, t0, *, store_pending=True):
        res = outcome.resolution
        res["context_provenance"] = provenance
        from .router_contract import decision_from_outcome
        res["decision"] = decision_from_outcome(outcome, core=self.core)
        record = {"phase": "resolve", "request_id": request["request_id"], "input_mode": request["input_mode"],
                  "utterance": request["utterance"], "action": request["action"], "route_id": res.get("route_id"),
                  "outcome": outcome.status, "task": res.get("task"), "operation": res.get("operation"),
                  "args": res.get("args"), "unresolved": res.get("unresolved"), "core_called": False,
                  "context_provenance": provenance, "routing_trace": res.get("routing_trace"),
                  "decision": res.get("decision")}
        if outcome.status == "resolved":
            if store_pending:
                def publish():
                    with self.lock:
                        self.pending[request["request_id"]] = (request, res)
                        while len(self.pending) > PENDING_LIMIT:
                            self.pending.popitem(last=False)
                if self.hosted:
                    from .route_hosted import HostedRequestError
                    try:
                        self.router.publish_pending(request["request_id"], request["action"]["session_id"], publish)
                    except HostedRequestError as exc:
                        out = self._hosted_error(exc.code, request["request_id"], resolution=res)
                        record.update(status="error", publication_error=exc.code,
                                      model_usage=out["model_usage"], model_calls=out["model_calls"])
                        with self.lock:
                            self.counters["model_calls"] += out["model_calls"]
                        record["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                        self._log("runs.jsonl", record)
                        return out
                else:
                    publish()
            out = {"status": "resolved", "phase": "resolve", "request_id": request["request_id"],
                   "snapshot_id": self.snapshot_id, "input_mode": request["input_mode"], "resolution": res,
                   "model_calls": 0, "decision": res["decision"], "context_provenance": provenance}
            from .contract import context_id
            out["context_id"] = context_id(res)
            out["header_html"] = render.header_html(res, "resolved", request["input_mode"],
                                                    request["request_id"], out["context_id"])
        else:
            out = self._with_html(envelope(outcome.status, request, self.snapshot_id, resolution=res,
                                           clarification=outcome.clarification, reason=outcome.reason,
                                           next_actions=outcome.next_actions))
        out["context_provenance"] = provenance
        self._usage(out, "resolve")
        if self.variant == "B" or self.hosted:
            record.update(model_usage=out["model_usage"], model_calls=out["model_calls"])
            with self.lock:
                self.counters["model_calls"] += out["model_calls"]
        record["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        self._log("runs.jsonl", record)
        return out

    # Registry callbacks always acquire router registry before Service.lock.
    # Core execution and network work occur after those locks have been released.
    def _hosted_error(self, code, request_id=None, *, resolution=None):
        env = envelope("error", None, self.snapshot_id, request_id=request_id,
                       resolution=resolution,
                       reason="Hosted request could not continue (" + code + ").",
                       retry="Previous results remain available. Run again or use guided controls.")
        env["error_code"] = code
        return self._usage(self._with_html(env), "resolve")

    def hosted_cancel(self, raw):
        if not self.hosted:
            return self._hosted_error("hosted_unavailable")
        if not isinstance(raw, dict) or set(raw) != {"request_id", "session_id"}:
            return self._hosted_error("invalid_cancel")
        from .route_hosted import HostedRequestError
        def remove():
            with self.lock:
                self.pending.pop(raw["request_id"], None)
        try:
            result = self.router.cancel(raw["request_id"], raw["session_id"], remove)
        except HostedRequestError as exc:
            return self._hosted_error(exc.code, raw.get("request_id"))
        return self._usage(dict(result, snapshot_id=self.snapshot_id,
                                reason="Dispatch already started." if result["status"] == "already_dispatched" else
                                "Cancellation recorded. An admitted call may still finish and settle."), "cancel")

    def _hosted_execute(self, raw):
        rid = raw.get("request_id") if isinstance(raw, dict) else None
        session = raw.get("session_id") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or set(raw) != {"request_id", "snapshot_id", "session_id"} or raw.get("snapshot_id") != self.snapshot_id:
            return self._hosted_error("invalid_execute", rid)
        from .route_hosted import HostedRequestError
        def consume():
            with self.lock:
                return self.pending.pop(rid, None)
        try:
            pending = self.router.consume_pending(rid, session, consume)
        except HostedRequestError as exc:
            return self._hosted_error(exc.code, rid)
        if pending is None:
            self.router.finish_dispatch(rid, session)
            return self._hosted_error("pending_missing", rid)
        request, res = pending
        try:
            env = self._execute(request, res)
        finally:
            self.router.finish_dispatch(rid, session)
        if env["status"] == "ok":
            env["result_reference"] = self._remember_result(request, res, env)
        env["context_provenance"] = res.get("context_provenance")
        self._usage(env, "execute")
        self._log("runs.jsonl", {"phase": "execute", "request_id": rid, "status": env["status"],
                                 "core_called": True, "model_usage": env["model_usage"]})
        return env

    # ------------------------------ bounded C browser inference transactions
    @staticmethod
    def _c_binding(transaction_id, record):
        return {"transaction_id": transaction_id, "binding": record["binding"],
                "artifact_id": record["artifact_id"]}

    def _c_error(self, code, request=None):
        out = self.router._failure(code)
        return self._usage(self._with_html(envelope(out.status, request, self.snapshot_id,
            resolution=out.resolution, reason=code, next_actions=out.next_actions)), "c_runtime")

    def _expire_c_locked(self, now):
        for record in self.c_transactions.values():
            if record["state"] in ("inference", "validating", "resolved") and now >= record["expires"]:
                record["state"] = "expired"
                self.pending.pop(record["request"]["request_id"], None)
        while len(self.c_transactions) > C_HISTORY_LIMIT:
            key = next((key for key, value in self.c_transactions.items()
                        if value["state"] not in ("inference", "validating", "resolved", "dispatching")), None)
            if key is None:
                break
            del self.c_transactions[key]

    def _supersede_c_locked(self, request):
        session = (request.get("action") or {}).get("session_id")
        if session:
            self.c_prepare_sequence += 1
            self.c_session_generations[session] = self.c_prepare_sequence
            self.c_session_generations.move_to_end(session)
            while len(self.c_session_generations) > PENDING_LIMIT:
                self.c_session_generations.popitem(last=False)
            for record in self.c_transactions.values():
                if ((record["request"].get("action") or {}).get("session_id") == session and
                        record["state"] in ("inference", "validating", "resolved")):
                    record["state"] = "superseded"
                    self.pending.pop(record["request"]["request_id"], None)
            return self.c_prepare_sequence
        return None

    def c_runtime(self):
        if self.variant != "C":
            return {"status": "error", "reason": "c_runtime_unavailable"}
        return dict(self.router.runtime(), variant="C", snapshot_id=self.snapshot_id)

    def c_prepare(self, raw):
        if self.variant != "C":
            return {"status": "error", "reason": "c_runtime_unavailable"}
        t0 = time.perf_counter()
        request, errors = validate_request(raw, self.snapshot_id)
        if errors:
            return self._usage(self._validation_error(raw, errors), "c_prepare")
        with self.lock:
            self._expire_c_locked(time.monotonic())
            duplicate = any(r["request"]["request_id"] == request["request_id"] for r in self.c_transactions.values())
            generation = self._supersede_c_locked(request) if not duplicate else None
        if duplicate:
            return self._c_error("request_id_reused", request)
        confirmed, provenance = self._context_record(request)
        outcome, work = self.router.prepare_browser(self.core, request, confirmed_context=confirmed)
        if outcome is not None:
            return self._resolve_outcome(request, outcome, provenance, t0)
        from .c_encoding import digest
        transaction_id = "c_" + secrets.token_urlsafe(24)
        artifact_id = self.router.package.artifact_id
        binding = digest({"transaction_id": transaction_id, "artifact_id": artifact_id,
                          "request": request, "confirmed": confirmed, "provenance": provenance})
        record = {"request": copy.deepcopy(request), "guard": work["guard"], "provenance": provenance,
                  "artifact_id": artifact_id, "binding": binding, "state": "inference",
                  "expires": time.monotonic() + C_DEADLINE_SECONDS}
        with self.lock:
            self._expire_c_locked(time.monotonic())
            full = sum(r["state"] in ("inference", "validating", "resolved", "dispatching")
                       for r in self.c_transactions.values()) >= C_INFLIGHT_LIMIT
            # Another concurrent prepare may have claimed this request while encoding.
            duplicate = any(r["request"]["request_id"] == request["request_id"] for r in self.c_transactions.values())
            session = (request.get("action") or {}).get("session_id")
            stale = session is not None and self.c_session_generations.get(session) != generation
            if not full and not duplicate and not stale:
                self.c_transactions[transaction_id] = record
                self._expire_c_locked(time.monotonic())
        if full or duplicate or stale:
            return self._c_error("transaction_superseded" if stale else "inference_capacity" if full else "request_id_reused", request)
        encoded = work["encoded"]
        out = dict(self.router.package.public(self.router.heads["shape"][1]), status="inference",
                   request_id=request["request_id"], snapshot_id=self.snapshot_id,
                   deadline_ms=C_DEADLINE_SECONDS * 1000, inputs={"byte_ids": [encoded["byte_ids"]], "lengths": [encoded["length"]]},
                   **self._c_binding(transaction_id, record))
        out["c_transaction"] = self._c_binding(transaction_id, record)
        self._log("runs.jsonl", {"phase": "c_prepare", "request_id": request["request_id"],
                  "transaction_id": transaction_id, "artifact_id": artifact_id, "core_called": False,
                  "context_provenance": provenance, "status": "inference"})
        return out

    def _c_record_locked(self, raw, *, keys):
        if not isinstance(raw, dict) or set(raw) != keys:
            return None, "transaction_request_invalid"
        if any(not isinstance(raw.get(k), str) for k in ("transaction_id", "binding", "artifact_id")):
            return None, "transaction_request_invalid"
        record = self.c_transactions.get(raw["transaction_id"])
        if record is None:
            return None, "transaction_unknown"
        if (not raw["binding"].isascii() or not secrets.compare_digest(raw["binding"], record["binding"]) or
                raw["artifact_id"] != record["artifact_id"] or self.router.package is None or
                raw["artifact_id"] != self.router.package.artifact_id):
            return None, "artifact_or_context_mismatch"
        return record, None

    def c_complete(self, raw):
        if self.variant != "C":
            return {"status": "error", "reason": "c_runtime_unavailable"}
        t0 = time.perf_counter()
        with self.lock:
            self._expire_c_locked(time.monotonic())
            record, error = self._c_record_locked(raw, keys={"transaction_id", "binding", "artifact_id", "logits"})
            if not error and record["state"] != "inference":
                error = "transaction_" + record["state"]
            if not error:
                record["state"] = "validating"  # exactly one completion may claim validation
        if error:
            return self._c_error(error)
        request = record["request"]
        outcome = self.router.complete_browser(self.core, request, raw["logits"], record["guard"])
        out = self._resolve_outcome(request, outcome, record["provenance"], t0, store_pending=False)
        with self.lock:
            self._expire_c_locked(time.monotonic())
            stale = record["state"] != "validating"
            if not stale:
                record["state"] = "resolved" if out["status"] == "resolved" else "rejected"
                if record["state"] == "resolved":
                    self.pending[request["request_id"]] = (request, outcome.resolution)
        if stale:
            return self._c_error("transaction_" + record["state"], request)
        out["c_transaction"] = self._c_binding(raw["transaction_id"], record)
        return out

    def c_cancel(self, raw):
        if self.variant != "C":
            return {"status": "error", "reason": "c_runtime_unavailable"}
        reasons = {"cancelled", "timeout", "worker_error", "worker_crashed"}
        with self.lock:
            self._expire_c_locked(time.monotonic())
            record, error = self._c_record_locked(raw, keys={"transaction_id", "binding", "artifact_id", "reason"})
            if not error and (not isinstance(raw["reason"], str) or raw["reason"] not in reasons):
                error = "transaction_cancel_reason_invalid"
            if not error:
                dispatched = record["state"] in ("dispatching", "finished")
                if record["state"] in ("inference", "validating", "resolved"):
                    record["state"] = raw["reason"]
                    self.pending.pop(record["request"]["request_id"], None)
                state = record["state"]
        if error:
            return self._c_error(error)
        self._log("runs.jsonl", {"phase": "c_cancel", "request_id": record["request"]["request_id"],
                  "transaction_id": raw["transaction_id"], "state": state, "core_called": False,
                  "dispatch_started": dispatched})
        return {"status": "already_dispatched" if dispatched else "cancelled", "reason": state,
                "dispatch_started": dispatched, "cancellation_boundary": "Dispatch already started; cancellation cannot undo the core operation."
                    if dispatched else "Pending inference and analytical dispatch are invalidated.",
                "request_id": record["request"]["request_id"], "snapshot_id": self.snapshot_id}

    # ------------------------------------------------------------- execute
    def execute(self, raw) -> dict:
        if self.hosted:
            return self._hosted_execute(raw)
        t0 = time.perf_counter()
        rid = raw.get("request_id") if isinstance(raw, dict) else None
        sid = raw.get("snapshot_id") if isinstance(raw, dict) else None
        c_record = None
        c_error = None
        with self.lock:
            if self.variant == "C":
                self._expire_c_locked(time.monotonic())
                c_record = next((r for r in self.c_transactions.values() if r["request"]["request_id"] == rid), None)
                if c_record:
                    expected = self._c_binding(next(k for k, v in self.c_transactions.items() if v is c_record), c_record)
                    if any(raw.get(k) != v for k, v in expected.items()):
                        c_error = "artifact_or_context_mismatch"
                    elif c_record["state"] != "resolved":
                        c_error = "transaction_" + c_record["state"]
                    elif rid not in self.pending:
                        c_record["state"] = "expired"
                        c_error = "transaction_expired"
                    elif sid == self.snapshot_id:
                        c_record["state"] = "dispatching"
            pending = self.pending.pop(rid, None) if isinstance(rid, str) and not c_error and sid == self.snapshot_id else None
        if c_error:
            return self._c_error(c_error)
        if sid != self.snapshot_id or pending is None:
            env = envelope("error", None, self.snapshot_id, request_id=rid if isinstance(rid, str) else None,
                           reason="No resolved request with this ID and snapshot is waiting to run.",
                           retry="Press Run again to resolve and execute the request.")
            self._log("runs.jsonl", {"phase": "execute", "request_id": rid, "status": "error",
                                     "reason": env["reason"], "core_called": False})
            return self._usage(self._with_html(env), "execute")
        request, res = pending
        try:
            env = self._execute(request, res)
        finally:
            if c_record:
                with self.lock:
                    c_record["state"] = "finished"
        if env["status"] == "ok":
            env["result_reference"] = self._remember_result(request, res, env)
        env["context_provenance"] = res.get("context_provenance")
        env = self._usage(env, "execute")
        self._log("runs.jsonl", {"phase": "execute", "request_id": request["request_id"],
                                 "route_id": res.get("route_id"), "operation": res["operation"],
                                 "args": res["args"], "status": env["status"], "reason": env.get("reason"),
                                 "context_id": env.get("context_id"),
                                 "finding_ids": [f["finding_id"] for f in env["findings"]],
                                 "core_called": True, "model_usage": env.get("model_usage"),
                                 "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)})
        return env

    def run(self, raw) -> dict:
        """Resolve and execute in one call (used by tests and scripted runs)."""
        first = self.resolve(raw)
        if first["status"] != "resolved":
            return first
        execute = {"request_id": first["request_id"], "snapshot_id": self.snapshot_id}
        if self.hosted:
            execute["session_id"] = (raw.get("action") or {}).get("session_id")
        env = self.execute(execute)
        return self._usage(env, "run")

    def _execute(self, request: dict, res: dict) -> dict:
        op, a = res["operation"], res["args"]
        core = self.core
        try:
            with self.lock:
                self.counters["core_operations"] += 1
            if op == "profile":
                out = core.profile(a["profile_id"], a.get("metric_ids"))
            elif op == "compare":
                out = core.compare(a["profile_id"], a["metric_ids"], a["comparison_geography"])
            elif op == "program_evidence":
                out = core.program_evidence(a["profile_id"], a["program_ids"])
            elif op == "outreach_lead":
                out = core.outreach_lead(a["profile_id"], a["program_id"], a.get("metric_ids"))
            elif op == "administrative_evidence":
                out = core.administrative_evidence(a["observation_ids"])
            elif op == "brief":
                out = core.brief(a["profile_id"], a["finding_ids"], a.get("edits") or {})
            else:  # pragma: no cover - route table guarantees a known operation
                raise RuntimeError(f"unknown operation {op}")
        except Unsupported as u:
            return self._with_html(envelope("unsupported", request, self.snapshot_id, resolution=res,
                                            reason=u.reason, next_actions=u.next_actions, data=u.data,
                                            limitations=core.catalog_limitations()))
        except Exception as exc:  # operation failure: keep context, never substitute
            self._log("errors.jsonl", {"request_id": request["request_id"], "operation": op, "args": a,
                                       "error": f"{type(exc).__name__}: {exc}",
                                       "trace": traceback.format_exc(limit=5)})
            return self._with_html(envelope(
                "error", request, self.snapshot_id, resolution=res,
                reason=f"The {op} operation failed ({type(exc).__name__}). No value was substituted and no "
                       "other geography was used.",
                retry="The resolved context above is retained. Press Run to retry; if it fails again, "
                      "inspect the data catalog or choose another supported task."))
        return self._with_html(envelope("ok", request, self.snapshot_id, resolution=res,
                                        findings=out["findings"], limitations=out["limitations"],
                                        data=out.get("data"),
                                        next_actions=self._journey_next(res, out)))

    def _journey_next(self, res: dict, out: dict) -> list:
        """Fixed next-step suggestions along the staff journey."""
        d = res.get("district")
        task = res["task"]
        if task == "profile":
            return [{"label": "Compare Poverty rate, all people with the State of Hawaiʻi",
                     "request": {"task": "compare", "district": d, "metric_ids": ["poverty_rate_all_people"],
                                 "comparison_geography": "HI-STATE-2024"}},
                    {"label": "Explain SNAP relevance", "request": {"task": "program_relevance", "district": d,
                                                                   "program_ids": ["snap_hi"]}}]
        if task == "compare":
            return [{"label": "Explain SNAP relevance", "request": {"task": "program_relevance", "district": d,
                                                                   "program_ids": ["snap_hi"]}}]
        if task == "program_relevance":
            return [{"label": f"Draft an outreach hypothesis for {self.core.programs[p]['name']}",
                     "request": {"task": "outreach", "district": d, "program_ids": [p]}}
                    for p in res["args"]["program_ids"]]
        if task == "outreach":
            return [{"label": TEMPLATES["brief"] + " (uses your selected findings)",
                     "request": {"task": "brief", "district": d, "use_selection": True}}]
        return []

    # ------------------------------------------------------- catalog/source
    def catalog(self) -> dict:
        if self._catalog is None:
            cat = self.core.catalog()
            cat["runtime"] = self.identity()
            cat["commands"] = {"forms": route_a.COMMAND_HELP, "rules": route_a.COMMAND_RULES}
            cat["html"] = render.catalog_html(cat)
            cat["sources_html"] = render.sources_html(cat)
            self._catalog = cat
        return self._catalog

    def source(self, source_id: str | None, finding_id: str | None = None) -> dict:
        t0 = time.perf_counter()
        from .contract import RE_FINDING_ID
        import re
        if not isinstance(source_id, str) or not re.match(r"^[A-Za-z0-9_]{1,64}$", source_id or ""):
            out = {"status": "error", "reason": "Malformed or missing source_id.", "model_calls": 0}
        elif finding_id is not None and not RE_FINDING_ID.match(finding_id):
            out = {"status": "error", "reason": "Malformed finding_id.", "model_calls": 0}
        else:
            try:
                res = self.core.source(source_id, finding_id)
                out = {"status": "ok", "result": res, "html": render.source_html(res), "model_calls": 0}
            except Unsupported as u:
                out = {"status": "unsupported", "reason": u.reason, "model_calls": 0}
            except Exception as exc:
                out = {"status": "error", "reason": f"Source lookup failed ({type(exc).__name__}); retained "
                                                    "evidence could not be read. Nothing was fetched.",
                       "model_calls": 0}
        self._log("runs.jsonl", {"phase": "source", "source_id": source_id, "finding_id": finding_id,
                                 "status": out["status"], "core_called": True,
                                 "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)})
        return out

    def event(self, raw) -> dict:
        if not isinstance(raw, dict) or raw.get("kind") not in RE_EVENT_KINDS:
            return {"status": "error", "reason": f"kind must be one of {list(RE_EVENT_KINDS)}"}
        rec = {"phase": "user_action", "kind": raw["kind"]}
        for k in ("session_id", "finding_id", "detail"):
            v = raw.get(k)
            if isinstance(v, str) and len(v) <= 200:
                rec[k] = v
        self._log("events.jsonl", rec)
        return {"status": "ok"}
