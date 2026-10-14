"""Coordinated scouting refresh, preparation, progress and time estimates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import inspect
import math
import threading
import time

from fm_analytics.analytics import MVP_CATALOGUE, rank_for_position
from fm_analytics.web.rendering import ScoutingPoolNotBuilt


# Initial estimates from the real-pool investigation. Successful jobs refine
# them; live throughput replaces the estimate once a counted stage advances.
STAGES = {
    "preparing": ("Preparing scouting refresh", 3.0),
    "pool": ("Building the player list", 2.0),
    "identities": ("Reading player details", 3.0),
    "players": ("Reading attributes and interest", 10.0),
    "validating": ("Checking the capture", 2.0),
    "recording": ("Saving scouting history", 3.0),
    "history": ("Loading player history", 5.0),
    "rankings": ("Preparing player rankings", 10.0),
}


@dataclass(frozen=True)
class ScoutingRefreshJob:
    status: str = "idle"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    message: str = ""
    error: str = ""
    allow_rebuild: bool = False
    needs_player_search: bool = False
    job_id: int = 0
    stage: str = "preparing"
    completed: int = 0
    total: int = 0
    detail: str = ""
    started: float = 0.0
    stage_started: float = 0.0
    percent: float = 0.0


class ScoutingJobs:
    def setup_scouting_jobs(self):
        self._scouting_refresh_lock = threading.Lock()
        self._scouting_preparation_lock = threading.RLock()
        self._scouting_ranking_lock = threading.RLock()
        self._scouting_refresh_job = ScoutingRefreshJob()
        self._scouting_refresh_thread = None
        self._scouting_visible_pool = None
        self._scouting_ranked_pool = None
        self._scouting_ready_generation = 0
        self._scouting_ready_counts = (0, 0)
        self._scouting_stage_estimates = {key: value[1] for key, value in STAGES.items()}
        self._scouting_stage_times = {}

    def scouting_rankings(self, candidates, **options):
        # Share in-flight cold calculations between page requests and startup
        # warm-up. A refresh builds its next generation in a private cache.
        with self._scouting_ranking_lock:
            return rank_for_position(candidates, MVP_CATALOGUE, cache=self.scouting_rank_cache, **options)

    def warm_scouting_rankings(self):
        try:
            with self._scouting_preparation_lock:
                pool = self.scouting()
                if self._scouting_ranked_pool is pool:
                    return
                self.scouting_rankings(pool)
                self._scouting_ranked_pool = pool
        except (OSError, ValueError, KeyError):
            pass

    def _scouting_progress(self, stage, completed=0, total=0, detail=""):
        if stage not in STAGES or not 0 <= completed <= total:
            return
        now = time.monotonic()
        with self._scouting_refresh_lock:
            job = self._scouting_refresh_job
            if job.status != "running":
                return
            stages = list(STAGES)
            if stages.index(stage) < stages.index(job.stage):
                return
            stage_started = job.stage_started
            if stage != job.stage:
                self._scouting_stage_times[job.stage] = now - stage_started
                stage_started = now
            elif completed == 0 and (total != job.total or detail != job.detail):
                # A retry has a new denominator and its own throughput.
                stage_started = now
            index = stages.index(stage)
            estimates = self._scouting_stage_estimates
            fraction = completed / total if total else 0
            percent = 100 * (sum(estimates[key] for key in stages[:index]) + estimates[stage] * fraction) / sum(estimates.values())
            self._scouting_refresh_job = replace(
                job, stage=stage, completed=completed, total=total, detail=detail,
                stage_started=stage_started, percent=max(job.percent, min(99, percent)),
            )

    def refresh_scouting(self, *, allow_rebuild=False):
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        with self._scouting_preparation_lock:
            # Snapshot the previous pool before the command promotes its file.
            self.scouting()
            options = {"allow_rebuild": allow_rebuild}
            if "progress" in inspect.signature(self.scouting_refresh).parameters:
                options["progress"] = self._scouting_progress
            result = self.scouting_refresh(**options)
            save_key = self.knowledge_save_key
            if self.scouting_capture_path is not None:
                from fm_analytics.web.server import _capture_save_key
                save_key = _capture_save_key(self.scouting_capture_path)
            self._scouting_progress("recording")
            self.record_knowledge()
            self._scouting_progress("history")
            current = self.scouting_provider()
            pool = self._with_knowledge(current, self._knowledge_generation, save_key=save_key)
            self._scouting_progress("rankings", 0, len(pool))
            cache = {}
            rank_for_position(pool, MVP_CATALOGUE, cache=cache, progress=lambda done, total: self._scouting_progress("rankings", done, total))
            current_count = sum(candidate.in_current_feed for candidate in pool)
            with self._scouting_ranking_lock, self._scouting_refresh_lock:
                self.scouting_rank_cache = cache
                self._scouting_visible_pool = self._scouting_ranked_pool = pool
                self.knowledge_save_key = save_key
                self._scouting_ready_counts = (current_count, len(pool) - current_count)
                self._scouting_ready_generation += 1
            return result

    def request_scouting_refresh(self, *, allow_rebuild=False):
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        with self._scouting_refresh_lock:
            if self._scouting_refresh_job.status == "running":
                return False
            now = time.monotonic()
            self._scouting_stage_times = {}
            self._scouting_refresh_job = ScoutingRefreshJob(
                status="running", started_at=datetime.now(timezone.utc),
                allow_rebuild=allow_rebuild, job_id=self._scouting_refresh_job.job_id + 1,
                started=now, stage_started=now,
            )
            worker = threading.Thread(target=self._background_scouting_refresh,
                kwargs={"allow_rebuild": allow_rebuild}, daemon=True, name="scouting-refresh")
            self._scouting_refresh_thread = worker
            worker.start()
        return True

    def _background_scouting_refresh(self, *, allow_rebuild):
        try:
            message = self.refresh_scouting(allow_rebuild=allow_rebuild)
        except Exception as exc:
            with self._scouting_refresh_lock:
                self._scouting_refresh_job = replace(self._scouting_refresh_job,
                    status="failed", ended_at=datetime.now(timezone.utc), error=str(exc),
                    needs_player_search=isinstance(exc, ScoutingPoolNotBuilt))
            return
        with self._scouting_refresh_lock:
            job = self._scouting_refresh_job
            self._scouting_stage_times[job.stage] = time.monotonic() - job.stage_started
            for stage, duration in self._scouting_stage_times.items():
                previous = self._scouting_stage_estimates[stage]
                self._scouting_stage_estimates[stage] = max(0.1, previous * 0.5 + duration * 0.5)
            self._scouting_refresh_job = replace(job, status="succeeded", percent=100,
                ended_at=datetime.now(timezone.utc), message=message)

    @property
    def scouting_refresh_job(self):
        with self._scouting_refresh_lock:
            return self._scouting_refresh_job

    def scouting_refresh_status(self):
        with self._scouting_refresh_lock:
            job = self._scouting_refresh_job
            elapsed = (time.monotonic() - job.started) if job.started_at else 0
            if job.ended_at and job.started_at:
                elapsed = (job.ended_at - job.started_at).total_seconds()
            remaining = None
            if job.status == "running":
                spent = time.monotonic() - job.stage_started
                estimate = self._scouting_stage_estimates[job.stage]
                if 0 < job.completed < job.total:
                    current = spent * (job.total - job.completed) / job.completed
                elif job.total and job.completed == job.total:
                    current = 0
                else:
                    current = estimate - spent if spent < estimate else None
                if current is not None:
                    stages = list(STAGES)
                    remaining = math.ceil(current + sum(self._scouting_stage_estimates[key] for key in stages[stages.index(job.stage) + 1:]))
            return {"status": job.status, "job_id": job.job_id, "stage": job.stage,
                "label": STAGES[job.stage][0], "completed": job.completed, "total": job.total,
                "detail": job.detail, "percent": job.percent, "elapsed_seconds": round(elapsed),
                "remaining_seconds": remaining, "generation": self._scouting_ready_generation,
                "current_players": self._scouting_ready_counts[0], "history_players": self._scouting_ready_counts[1],
                "message": job.message, "error": job.error,
                "needs_player_search": job.needs_player_search,
                "knowledge_note": self.knowledge_note}
