"""Exact, process-parallel orchestration for independent tactic evaluations."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing import get_all_start_methods, get_context
from signal import SIG_IGN, SIGINT, signal
from threading import Lock
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.opponent import OpponentProfile
from fm_analytics.analytics.role_scoring import RoleScoreCache
from fm_analytics.analytics.xi_models import (
    EffectiveAndPotentialRecommendation,
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SystemFitPolicy,
    TacticEvaluation,
    TacticFitPolicy,
    TacticRecommendation,
)


def rank_evaluations(evaluations: Sequence[TacticEvaluation]) -> TacticRecommendation:
    """Apply the one canonical, deterministic tactic-ranking order."""
    return TacticRecommendation(
        evaluations=tuple(
            sorted(
                evaluations,
                key=lambda item: (
                    not item.has_legal_xi,
                    -len(item.assignments),
                    -item.score.central,
                    -item.score.lower,
                    item.tactic.key,
                ),
            )
        )
    )


@dataclass(frozen=True)
class _TacticRankingJob:
    tactic_keys: tuple[str, ...]
    players: tuple[PlayerSelectionInput, ...]
    catalogue: FootballCatalogue
    readiness_policy: ReadinessPolicy
    familiarity_policy: FamiliarityPolicy
    fit_policy: TacticFitPolicy
    system_policy: SystemFitPolicy
    opponent: OpponentProfile


def _evaluate_tactic_ranking_job(
    job: _TacticRankingJob,
) -> tuple[tuple[TacticEvaluation, ...], tuple[TacticEvaluation, ...]]:
    """Evaluate one picklable tactic slice in a spawned worker process."""
    # Importing here avoids a module-import cycle; the child imports this
    # module first, and only evaluates tactics after it is fully initialised.
    from fm_analytics.analytics.xi_selection import evaluate_tactic

    cache = RoleScoreCache()
    potential_familiarity = job.familiarity_policy.potential()
    effective: list[TacticEvaluation] = []
    potential: list[TacticEvaluation] = []
    for tactic_key in job.tactic_keys:
        tactic = job.catalogue.tactics[tactic_key]
        effective.append(
            evaluate_tactic(
                tactic, job.players, job.catalogue,
                readiness_policy=job.readiness_policy,
                familiarity_policy=job.familiarity_policy,
                fit_policy=job.fit_policy, system_policy=job.system_policy,
                opponent=job.opponent, role_score_cache=cache,
            )
        )
        potential.append(
            evaluate_tactic(
                tactic, job.players, job.catalogue,
                readiness_policy=job.readiness_policy,
                familiarity_policy=potential_familiarity,
                fit_policy=job.fit_policy, system_policy=job.system_policy,
                opponent=job.opponent, role_score_cache=cache,
            )
        )
    return tuple(effective), tuple(potential)


def _initialise_ranking_worker() -> None:
    """Leave Ctrl-C to the server process that owns the executor."""
    signal(SIGINT, SIG_IGN)


def _ranking_worker_ready() -> None:
    """A tiny module-level task used to start persistent workers safely."""


class TacticRankingExecutor:
    """A bounded, reusable pool for exact tactic ranking.

    ``spawn`` is the default because the web application has background
    threads; the executor is intended to be owned by a long-lived surface,
    warmed before that surface starts serving requests, then shut down with it.
    """

    def __init__(self, *, workers: int = 4, start_method: str = "spawn") -> None:
        if workers < 1:
            raise ValueError("workers must be at least one")
        if start_method not in get_all_start_methods():
            raise ValueError(f"unsupported multiprocessing start method {start_method!r}")
        self.workers = workers
        self.start_method = start_method
        self._executor: ProcessPoolExecutor | None = None
        self._lock = Lock()
        self._closed = False

    @property
    def is_parallel(self) -> bool:
        return self.workers > 1

    def warm(self) -> None:
        if not self.is_parallel:
            return
        executor = self._get_executor()
        for future in tuple(executor.submit(_ranking_worker_ready) for _ in range(self.workers)):
            future.result()

    def rank(
        self,
        players: Sequence[PlayerSelectionInput],
        catalogue: FootballCatalogue,
        *,
        readiness_policy: ReadinessPolicy = ReadinessPolicy(),
        familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
        fit_policy: TacticFitPolicy = TacticFitPolicy(),
        system_policy: SystemFitPolicy = SystemFitPolicy(),
        opponent: OpponentProfile = OpponentProfile.neutral(),
    ) -> EffectiveAndPotentialRecommendation:
        if not self.is_parallel or len(catalogue.tactics) < 2:
            return self._sequential(
                players, catalogue, readiness_policy, familiarity_policy,
                fit_policy, system_policy, opponent,
            )
        player_tuple = tuple(players)
        tactic_keys = tuple(catalogue.tactics)
        worker_count = min(self.workers, len(tactic_keys))
        jobs = tuple(
            _TacticRankingJob(
                tactic_keys=tactic_keys[index::worker_count], players=player_tuple,
                catalogue=catalogue, readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy, fit_policy=fit_policy,
                system_policy=system_policy, opponent=opponent,
            )
            for index in range(worker_count)
        )
        try:
            executor = self._get_executor()
            futures = tuple(executor.submit(_evaluate_tactic_ranking_job, job) for job in jobs)
            completed = tuple(future.result() for future in futures)
        except (BrokenProcessPool, OSError):
            self._discard_broken_executor()
            return self._sequential(
                players, catalogue, readiness_policy, familiarity_policy,
                fit_policy, system_policy, opponent,
            )
        return EffectiveAndPotentialRecommendation(
            effective=rank_evaluations(
                tuple(item for effective, _potential in completed for item in effective)
            ),
            potential=rank_evaluations(
                tuple(item for _effective, potential in completed for item in potential)
            ),
        )

    @staticmethod
    def _sequential(
        players: Sequence[PlayerSelectionInput], catalogue: FootballCatalogue,
        readiness_policy: ReadinessPolicy, familiarity_policy: FamiliarityPolicy,
        fit_policy: TacticFitPolicy, system_policy: SystemFitPolicy,
        opponent: OpponentProfile,
    ) -> EffectiveAndPotentialRecommendation:
        from fm_analytics.analytics.xi_selection import recommend_tactic_effective_and_potential

        return recommend_tactic_effective_and_potential(
            players, catalogue, readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy, fit_policy=fit_policy,
            system_policy=system_policy, opponent=opponent,
        )

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=True)

    def _get_executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._closed:
                raise RuntimeError("tactic ranking executor has been shut down")
            if self._executor is None:
                self._executor = ProcessPoolExecutor(
                    max_workers=self.workers, mp_context=get_context(self.start_method),
                    initializer=_initialise_ranking_worker,
                )
            return self._executor

    def _discard_broken_executor(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
