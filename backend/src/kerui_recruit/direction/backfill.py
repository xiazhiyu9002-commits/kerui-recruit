from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kerui_recruit.db.models import Candidate, Jd, JdRevision, ResumeRevision, SchemaVersion
from kerui_recruit.direction.classifier import DirectionClassificationInput, DirectionClassifier
from kerui_recruit.direction.models import (
    CLASSIFIER_VERSION,
    DirectionDecision,
    DirectionProfile,
    TAXONOMY_VERSION,
    build_direction_diagnostics,
    parse_direction_profile,
)
from kerui_recruit.search.sync import enqueue_sync

STATE_FILENAME = "direction-backfill-state-v1.json"
LOCK_FILENAME = "direction-backfill.lock"
LOCK_EXPIRY_SECONDS = 24 * 3600


@dataclass
class BackfillStats:
    scanned: int = 0
    already_current_skipped: int = 0
    manual_skipped: int = 0
    needs_backfill: int = 0
    current_unknown: int = 0
    success: int = 0
    failed: int = 0
    unknown: int = 0
    uncertain: int = 0
    llm_attempts: int = 0
    llm_schema_repair_attempts: int = 0
    llm_retries: int = 0
    llm_successes: int = 0
    llm_failures: int = 0
    db_writes: int = 0
    conflict_skipped: int = 0
    distribution: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    skip_reasons: list[dict] = field(default_factory=list)
    pause_reason: str | None = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "already_current_skipped": self.already_current_skipped,
            "manual_skipped": self.manual_skipped,
            "needs_backfill": self.needs_backfill,
            "current_unknown": self.current_unknown,
            "success": self.success,
            "failed": self.failed,
            "unknown": self.unknown,
            "uncertain": self.uncertain,
            "llm_attempts": self.llm_attempts,
            "llm_schema_repair_attempts": self.llm_schema_repair_attempts,
            "llm_retries": self.llm_retries,
            "llm_successes": self.llm_successes,
            "llm_failures": self.llm_failures,
            "db_writes": self.db_writes,
            "conflict_skipped": self.conflict_skipped,
            "distribution": dict(self.distribution),
            "pause_reason": self.pause_reason,
            "errors": list(self.errors),
            "skip_reasons": list(self.skip_reasons),
        }


class DirectionBackfillService:
    """离线方向回填：幂等版本判断、并发、429 退避、cursor 续跑、单条失败继续。"""

    def __init__(self, session_factory: sessionmaker[Session], classifier: DirectionClassifier,
                 *, concurrency: int = 4, max_retries: int = 3,
                 state_dir: Path | None = None) -> None:
        self.session_factory = session_factory
        self.classifier = classifier
        self.concurrency = max(3, min(concurrency, 5))
        self.max_retries = max_retries
        self.state_dir = state_dir
        self.state_path = state_dir / STATE_FILENAME if state_dir else None
        self.lock_path = state_dir / LOCK_FILENAME if state_dir else None

    def preflight(self) -> dict:
        """全量回填前预检：DB schema、Provider、人工覆盖、幂等、单任务锁。"""
        from kerui_recruit.db.migrate import SCHEMA_VERSION
        with self.session_factory() as session:
            schema_version = session.scalar(select(func.max(SchemaVersion.version)))
            candidate_count = session.scalar(select(func.count()).select_from(Candidate)) or 0
            jd_count = session.scalar(select(func.count()).select_from(Jd)) or 0
            manual_count = (
                session.scalar(select(func.count()).select_from(ResumeRevision).where(
                    ResumeRevision.is_current.is_(True),
                    ResumeRevision.manual_overrides.like("%direction_profile%"))) or 0
            ) + (
                session.scalar(select(func.count()).select_from(JdRevision).where(
                    JdRevision.is_current.is_(True),
                    JdRevision.manual_overrides.like("%direction_profile%"))) or 0
            )
        lock = self._read_lock()
        lock_state, lock_reason = (self._lock_state(lock) if lock is not None
                                   else ("NONE", "无锁"))
        return {
            "schema_version": schema_version,
            "schema_supported": schema_version == SCHEMA_VERSION,
            "llm_enabled": getattr(self.classifier, "llm_provider", None) is not None,
            "candidate_count": candidate_count,
            "jd_count": jd_count,
            "manual_override_count": manual_count,
            "concurrency": self.concurrency,
            "max_retries": self.max_retries,
            "lock_held": lock is not None,
            "lock_state": lock_state,
            "lock_reason": lock_reason,
            "lock": lock,
        }

    @staticmethod
    def distribution_warnings(stats: BackfillStats) -> list[str]:
        total = sum(stats.distribution.values())
        warnings: list[str] = []
        if not total:
            return warnings
        for code, count in stats.distribution.items():
            if code != "UNKNOWN" and count / total > 0.70:
                warnings.append(f"方向 {code} 占比 {count}/{total}（>70%），建议抽查 20 份")
        unknown_ratio = stats.distribution.get("UNKNOWN", 0) / total
        if unknown_ratio > 0.50:
            warnings.append(f"UNKNOWN 占比 {unknown_ratio:.0%}（>50%），建议抽查 20 份")
        return warnings

    async def run(self, *, entity_types: tuple[str, ...] = ("resume_revision", "jd_revision"),
                  mode: str = "dry-run", batch_size: int = 20,
                  max_items: int | None = None) -> BackfillStats:
        if mode not in ("dry-run", "rules-only", "full", "resume"):
            raise ValueError(f"Unknown backfill mode: {mode}")
        formal = mode in ("full", "resume")
        # full/resume 是 LLM 主判模式：无 Provider 时直接拒绝，零写入。
        if formal and getattr(self.classifier, "llm_provider", None) is None:
            raise RuntimeError("full/resume 需要方向 LLM Provider；请使用 dry-run 或 rules-only")
        stats = BackfillStats()
        run_id = uuid.uuid4().hex
        if formal:
            if mode == "resume":
                state = self._read_state()
                if state is not None:
                    invalid = self._validate_resume_state(state)
                    if invalid:
                        raise RuntimeError(invalid)
                    stats = self._stats_from_state(state)
            self._acquire_lock(run_id)
        try:
            semaphore = asyncio.Semaphore(self.concurrency)
            processed = 0
            for entity_type in entity_types:
                cursor = self._resume_cursor(entity_type) if mode == "resume" else None
                while True:
                    remaining = None if max_items is None else max_items - processed
                    if remaining is not None and remaining <= 0:
                        break
                    fetch_size = batch_size if remaining is None else min(batch_size, remaining)
                    revision_ids = self._eligible_records(entity_type, cursor, fetch_size)
                    if not revision_ids:
                        break
                    cursor = revision_ids[-1]
                    await asyncio.gather(*(self._backfill_one(
                        stats, entity_type, revision_id, mode, semaphore) for revision_id in revision_ids))
                    processed += len(revision_ids)
                    if formal:
                        self._persist_cursor(entity_type, cursor, stats, run_id, mode, status="RUNNING")
                    if max_items is not None and processed >= max_items:
                        if formal:
                            self._persist_cursor(entity_type, cursor, stats, run_id, mode, status="PAUSED_LIMIT")
                        return stats
                    if self._should_pause(stats):
                        if formal:
                            self._persist_cursor(entity_type, cursor, stats, run_id, mode, status="PAUSED_ERROR_RATE")
                        stats.pause_reason = "PAUSED_ERROR_RATE"
                        return stats
            if formal:
                self._finish_state(stats, run_id, mode)
            return stats
        finally:
            if formal:
                self._release_lock(run_id)

    def _validate_resume_state(self, state: dict) -> str | None:
        """resume 前校验状态兼容性；返回错误描述或 None。"""
        if state.get("format_version") != 1:
            return f"状态文件 format_version 不兼容：{state.get('format_version')}"
        if state.get("taxonomy_version") != TAXONOMY_VERSION:
            return f"状态文件 taxonomy_version 不兼容：{state.get('taxonomy_version')}"
        if state.get("classifier_version") != CLASSIFIER_VERSION:
            return f"状态文件 classifier_version 不兼容：{state.get('classifier_version')}"
        if state.get("status") == "DONE":
            return "回填已完成，无法 resume"
        return None

    @staticmethod
    def _stats_from_state(state: dict) -> BackfillStats:
        """从持久化状态恢复累计 stats，续跑时不再从 0 开始。"""
        raw = state.get("stats") or {}
        stats = BackfillStats()
        for key in (
            "scanned", "already_current_skipped", "manual_skipped", "needs_backfill",
            "current_unknown", "success", "failed", "unknown", "uncertain",
            "llm_attempts", "llm_schema_repair_attempts", "llm_retries",
            "llm_successes", "llm_failures", "db_writes", "conflict_skipped",
        ):
            if key in raw:
                setattr(stats, key, raw[key])
        stats.distribution = dict(raw.get("distribution") or {})
        return stats

    # -- 幂等与扫描 ---------------------------------------------------------

    def _eligible_records(self, entity_type: str, cursor: str | None, batch_size: int) -> list[str]:
        model = ResumeRevision if entity_type == "resume_revision" else JdRevision
        with self.session_factory() as session:
            stmt = select(model.id).where(model.is_current.is_(True), model.status == "READY")
            if cursor is not None:
                stmt = stmt.where(model.id > cursor)
            stmt = stmt.order_by(model.id).limit(batch_size)
            return [revision_id for (revision_id,) in session.execute(stmt)]

    @staticmethod
    def _needs_backfill(parsed: dict) -> bool:
        raw = parsed.get("direction_profile")
        if not isinstance(raw, dict):
            return True
        try:
            profile = DirectionProfile.model_validate(raw)
        except ValidationError:
            return True
        return profile.taxonomy_version != TAXONOMY_VERSION or profile.classifier_version != CLASSIFIER_VERSION

    async def _backfill_one(self, stats: BackfillStats, entity_type: str, revision_id: str,
                            mode: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                model = ResumeRevision if entity_type == "resume_revision" else JdRevision
                with self.session_factory() as session:
                    revision = session.get(model, revision_id)
                    if revision is None:
                        return
                    manual = dict(revision.manual_overrides or {})
                    parsed = dict(revision.parsed_data or {})
                stats.scanned += 1
                if manual.get("direction_profile"):
                    stats.manual_skipped += 1
                    return
                if not self._needs_backfill(parsed):
                    stats.already_current_skipped += 1
                    current = parse_direction_profile(parsed.get("direction_profile"))
                    if current.status == "UNKNOWN":
                        stats.current_unknown += 1
                    return
                stats.needs_backfill += 1
                if mode == "dry-run":
                    return
                if mode == "rules-only":
                    decision = self.classifier.classify_rules_only(_build_input(parsed, entity_type))
                    self._count_distribution(stats, decision.effective_profile)
                    return
                fingerprint_before = _input_fingerprint(_build_input(parsed, entity_type))
                decision = await self._classify(parsed, entity_type, stats)
                with self.session_factory() as session:
                    skip = self._write_if_current(session, entity_type, revision_id, decision, fingerprint_before)
                    if skip is not None:
                        stats.conflict_skipped += 1
                        stats.skip_reasons.append({
                            "entity_type": entity_type, "revision_id": revision_id, "reason": skip,
                        })
                        return
                    session.commit()
                stats.db_writes += 1
                stats.success += 1
                stats.consecutive_failures = 0
                self._count_distribution(stats, decision.effective_profile)
            except Exception as error:  # noqa: BLE001 - 单条失败继续
                stats.failed += 1
                stats.consecutive_failures += 1
                stats.errors.append(_sanitize_error(entity_type, revision_id, error))

    async def _classify(self, parsed: dict, entity_type: str, stats: BackfillStats | None = None) -> DirectionDecision:
        payload = _build_input(parsed, entity_type)
        decision = await self.classifier.classify(payload)
        total_attempts = decision.llm_attempts
        total_schema_repair = decision.llm_schema_repair_attempts
        total_successes = decision.llm_successes
        total_failures = decision.llm_failures
        retries = 0
        for attempt in range(self.max_retries):
            if decision.used_rule_fallback and self._is_retryable(decision.llm_error_code):
                # 429 指数退避 + 抖动，上限 30s。
                await asyncio.sleep(min(2 ** (attempt + 2) + random.uniform(0, 1), 30))
                decision = await self.classifier.classify(payload)
                total_attempts += decision.llm_attempts
                total_schema_repair += decision.llm_schema_repair_attempts
                total_successes += decision.llm_successes
                total_failures += decision.llm_failures
                retries += 1
            else:
                break
        if stats is not None:
            stats.llm_attempts += total_attempts
            stats.llm_schema_repair_attempts += total_schema_repair
            stats.llm_retries += retries
            stats.llm_successes += total_successes
            stats.llm_failures += total_failures
        return decision

    @staticmethod
    def _is_retryable(error_code: str | None) -> bool:
        return error_code in {"E_API_RATE_LIMIT", "E_API_UPSTREAM", "E_API_BUSY", "E_API_NETWORK"}

    @staticmethod
    def _save(session: Session, revision, decision: DirectionDecision, entity_type: str) -> None:
        profile_json = decision.effective_profile.model_dump(mode="json")
        review = dict(revision.review_data or {})
        review["direction_profile"] = profile_json
        review["direction_diagnostics"] = build_direction_diagnostics(decision)
        revision.review_data = review
        parsed = dict(revision.parsed_data or {})
        parsed["direction_profile"] = profile_json
        revision.parsed_data = parsed
        if entity_type == "resume_revision":
            enqueue_sync(session, "candidate", revision.document.candidate_id, mode="METADATA")
        else:
            enqueue_sync(session, "jd", revision.jd_id, mode="METADATA")

    def _write_if_current(self, session: Session, entity_type: str, revision_id: str,
                          decision: DirectionDecision, fingerprint_before: str) -> str | None:
        """写回前重新校验，返回 None 表示已写入，否则返回 skip 原因。

        在 LLM 等待期间用户可能新增人工方向、修改 parsed 输入、或该记录已被
        其他任务处理/变为非 current；这些场景必须跳过写回，绝不覆盖新状态。
        """
        model = ResumeRevision if entity_type == "resume_revision" else JdRevision
        revision = session.get(model, revision_id)
        if revision is None:
            return "revision_gone"
        if not getattr(revision, "is_current", True):
            return "not_current"
        if revision.status != "READY":
            return "not_ready"
        manual = dict(revision.manual_overrides or {})
        if manual.get("direction_profile"):
            return "manual_override"
        current_parsed = dict(revision.parsed_data or {})
        fingerprint_after = _input_fingerprint(_build_input(current_parsed, entity_type))
        if fingerprint_after != fingerprint_before:
            return "input_changed"
        if not self._needs_backfill(current_parsed):
            return "already_backfilled"
        self._save(session, revision, decision, entity_type)
        return None

    @staticmethod
    def _count_distribution(stats: BackfillStats, profile: DirectionProfile) -> None:
        code = profile.primary_role_code or "UNKNOWN"
        stats.distribution[code] = stats.distribution.get(code, 0) + 1
        if profile.status == "UNKNOWN":
            stats.unknown += 1
        elif profile.status == "UNCERTAIN":
            stats.uncertain += 1

    @staticmethod
    def _should_pause(stats: BackfillStats) -> bool:
        if stats.consecutive_failures >= 10:
            return True
        if stats.scanned >= 20 and stats.failed / stats.scanned > 0.10:
            return True
        return False

    # -- 持久化状态与单任务锁 ---------------------------------------------

    def _resume_cursor(self, entity_type: str) -> str | None:
        state = self._read_state()
        if not state:
            return None
        return (state.get("entity_cursors") or {}).get(entity_type)

    def _persist_cursor(self, entity_type: str, cursor: str, stats: BackfillStats,
                        run_id: str, mode: str, status: str = "RUNNING") -> None:
        if self.state_path is None:
            return
        # 合并而非覆盖：resume_revision 与 jd_revision 的 cursor 必须独立保存。
        existing = self._read_state() or {}
        cursors = dict(existing.get("entity_cursors") or {})
        cursors[entity_type] = cursor
        state = {
            "format_version": 1,
            "run_id": run_id,
            "status": status,
            "taxonomy_version": TAXONOMY_VERSION,
            "classifier_version": CLASSIFIER_VERSION,
            "mode": mode,
            "entity_cursors": cursors,
            "stats": stats.to_dict(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_json(self.state_path, state)

    def _finish_state(self, stats: BackfillStats, run_id: str, mode: str) -> None:
        if self.state_path is None:
            return
        state = {
            "format_version": 1,
            "run_id": run_id,
            "status": "DONE",
            "taxonomy_version": TAXONOMY_VERSION,
            "classifier_version": CLASSIFIER_VERSION,
            "mode": mode,
            "entity_cursors": {},
            "stats": stats.to_dict(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_json(self.state_path, state)

    def _read_state(self) -> dict | None:
        if self.state_path is None or not self.state_path.exists():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _acquire_lock(self, run_id: str) -> None:
        if self.lock_path is None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": run_id,
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "taxonomy_version": TAXONOMY_VERSION,
            "classifier_version": CLASSIFIER_VERSION,
        }
        existing = self._read_lock()
        if existing is not None:
            state, reason = self._lock_state(existing)
            if state in ("STALE_DEAD_PID", "INVALID"):
                # 只有明确 dead / 损坏的陈旧锁才安全清理；存活 PID 即使过期也不静默删除。
                self.lock_path.unlink(missing_ok=True)
            else:
                raise RuntimeError(f"另一个回填任务正在运行（{state}: {reason}）：{existing}")
        # 原子创建，避免并发竞争。
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError(f"回填锁已存在：{self.lock_path}")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    def _release_lock(self, run_id: str) -> None:
        if self.lock_path is None or not self.lock_path.exists():
            return
        existing = self._read_lock()
        if existing is None or existing.get("run_id") != run_id:
            return
        self.lock_path.unlink(missing_ok=True)

    def _read_lock(self) -> dict | None:
        if self.lock_path is None or not self.lock_path.exists():
            return None
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"_invalid": True}

    def _lock_state(self, lock: dict) -> tuple[str, str]:
        """返回锁状态与原因：ACTIVE / STALE_DEAD_PID / EXPIRED_LIVE / INVALID。"""
        if not isinstance(lock, dict) or lock.get("_invalid"):
            return "INVALID", "锁内容损坏"
        pid = lock.get("pid")
        if pid is None:
            return "INVALID", "缺少 pid"
        try:
            alive = _pid_exists(int(pid))
        except (ValueError, TypeError):
            return "INVALID", "非法 pid"
        if not alive:
            return "STALE_DEAD_PID", "PID 不存在"
        started = lock.get("started_at")
        if started:
            try:
                start = datetime.fromisoformat(started)
                if (datetime.now(timezone.utc) - start).total_seconds() > LOCK_EXPIRY_SECONDS:
                    return "EXPIRED_LIVE", "超过过期阈值但 PID 仍存活"
            except (ValueError, TypeError):
                pass
        return "ACTIVE", "PID 存活且未过期"


def _pid_exists(pid: int) -> bool:
    """判断进程是否存在（跨平台安全，不在 Windows 上用 signal 0 == CTRL_C_EVENT）。"""
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _build_input(parsed: dict, entity_type: str) -> DirectionClassificationInput:
    if entity_type == "jd_revision":
        duties = " ".join(parsed.get("core_duties") or []) + " " + (parsed.get("summary") or "")
        must = " ".join(r.get("value", "") for r in parsed.get("requirements") or [] if r.get("kind") == "MUST")
        return DirectionClassificationInput(
            recent_title=parsed.get("title") or "",
            recent_duties=(duties + " " + must).strip(),
            skills=tuple(parsed.get("required_skills") or []) + tuple(parsed.get("tech_direction") or []),
            industry=parsed.get("industry") or "",
            business_scene=" ".join(parsed.get("plus_industry") or []),
        )
    experiences = parsed.get("experiences") or []
    recent = experiences[0] if experiences else None
    projects = parsed.get("projects") or []
    return DirectionClassificationInput(
        recent_title=(recent.get("title") or "") if recent else "",
        recent_duties=(recent.get("summary") or "") if recent else (parsed.get("summary") or ""),
        history_titles=tuple(e.get("title") for e in experiences[1:] if e.get("title")),
        project_summaries=tuple(" ".join(str(x) for x in (p.get("name"), p.get("tech_stack"), p.get("business_scene"), p.get("summary")) if x) for p in projects),
        skills=tuple(parsed.get("skills") or []),
        industry=parsed.get("current_industry") or parsed.get("industry") or "",
        business_scene=" ".join(p.get("business_scene") for p in projects if p.get("business_scene")),
    )


def _input_fingerprint(payload: DirectionClassificationInput) -> str:
    """分类输入的稳定指纹，用于写回前检测输入是否在 LLM 等待期间发生变化。"""
    data = {
        "recent_title": payload.recent_title,
        "recent_duties": payload.recent_duties,
        "history_titles": list(payload.history_titles),
        "project_summaries": list(payload.project_summaries),
        "skills": list(payload.skills),
        "industry": payload.industry,
        "business_scene": payload.business_scene,
    }
    stable = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


_RETRYABLE_CODES = {"E_API_RATE_LIMIT", "E_API_UPSTREAM", "E_API_BUSY", "E_API_NETWORK"}


def _sanitize_error(entity_type: str, revision_id: str, error: Exception) -> dict:
    """结构化、脱敏的错误条目：不含正文、电话、邮箱、API Key 或 Provider 原始载荷。"""
    code = getattr(error, "code", None)
    return {
        "entity_type": entity_type,
        "revision_id": revision_id,
        "error_type": type(error).__name__,
        "error_code": code,
        "retryable": code in _RETRYABLE_CODES,
        "attempt_count": 1,
        "final_status": "failed",
    }
