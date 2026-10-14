"""Investigate scouting refresh costs using an isolated copy of stored data.

    uv run python -m tools.benchmark_scouting_refresh

This never reads FM or writes to the source database. It compares compact
ranking with detailed scoring, and indexed history recording with the former
window queries. Complete ranking equality and replayed observation-table
equality are checked. Absolute timings are diagnostic, not CI thresholds.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import cProfile
from dataclasses import asdict
import json
from pathlib import Path
import platform
import pstats
import sqlite3
import tempfile
from time import perf_counter
from types import SimpleNamespace

from fm_analytics.analytics import MVP_CATALOGUE, ScoutingFilters, rank_for_position
from fm_analytics.analytics import scouting
from fm_analytics.analytics.role_scoring import score_role
from fm_analytics.candidate_pool import compose_candidate_pool
from fm_analytics.knowledge_ingest import capture_from_document
from fm_analytics.persistence.player_knowledge import PlayerKnowledgeStore, _attribute_state
from fm_analytics.web.handlers import SquadWebHandler
from fm_analytics.web.providers import scouting_json_provider
from fm_analytics.web.scouting_snapshot import SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _rewind_latest(connection: sqlite3.Connection, capture) -> None:
    """Remove this capture's last ingest from a disposable database only.

    Player identity rows remain. The benchmark therefore excludes the cost of
    first discovering a player; observations and sightings are replayed in full.
    """
    row = connection.execute(
        "SELECT id, content_hash FROM ingests ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None or row[1] != capture.content_hash():
        raise ValueError("The capture must match the database's latest ingest.")
    for table in ("sightings", "attribute_observations", "profile_observations"):
        connection.execute(f"DELETE FROM {table} WHERE ingest_id = ?", (row[0],))
    connection.execute("DELETE FROM ingests WHERE id = ?", (row[0],))


def _legacy_attributes(connection, save_id, ingest_id, capture) -> int:
    """Frozen pre-optimization window-query reference for history recording."""
    groups = {}
    for player in capture.players:
        if player.attributes:
            groups.setdefault(player.attributes_observed_on or capture.game_date, []).extend(
                (player.player_id, "current", name, observation)
                for name, observation in player.attributes.items()
            )
        if player.last_known_attributes:
            groups.setdefault(player.last_known_observed_on, []).extend(
                (player.player_id, "last_known", name, observation)
                for name, observation in player.last_known_attributes.items()
            )
    added = 0
    for observed_on in sorted(groups):
        latest = {
            (row[0], row[1]): tuple(row)[2:] for row in connection.execute(
                "SELECT player_id, attribute, visibility, value, minimum, maximum FROM ("
                " SELECT *, ROW_NUMBER() OVER (PARTITION BY player_id, attribute "
                " ORDER BY observed_on DESC, id DESC) AS rn "
                " FROM attribute_observations WHERE save_id = ? AND observed_on <= ?"
                ") WHERE rn = 1", (save_id, observed_on),
            )
        }
        changed = []
        for player_id, source, name, observation in groups[observed_on]:
            key = (player_id, name)
            state = _attribute_state(observation)
            if latest.get(key) != state:
                latest[key] = state
                changed.append((save_id, player_id, name, observed_on, ingest_id, source, *state))
        connection.executemany(
            "INSERT INTO attribute_observations "
            "(save_id, player_id, attribute, observed_on, ingest_id, source, visibility, value, minimum, maximum) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            changed,
        )
        added += len(changed)
    return added


def _table_equal(left: Path, right: Path, table: str) -> bool:
    order = "save_id, player_id, kind, attribute, observed_on" if table == "sightings" else "id"
    with closing(_read_only(left)) as source, closing(_read_only(right)) as target:
        source_rows = source.execute(f"SELECT * FROM {table} ORDER BY {order}")
        target_rows = target.execute(f"SELECT * FROM {table} ORDER BY {order}")
        # Compare in bounded batches, without holding two full histories in RAM.
        while True:
            batch = source_rows.fetchmany(1000)
            if batch != target_rows.fetchmany(1000):
                return False
            if not batch:
                return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=ROOT / "data/scouting-capture-enriched.json")
    parser.add_argument("--database", type=Path, default=ROOT / "data/player-knowledge.sqlite3")
    parser.add_argument("--profile", action="store_true", help="profile 500 candidates after baseline timing")
    args = parser.parse_args(argv)
    metrics = {}

    def timed(name, function):
        started = perf_counter()
        value = function()
        metrics[name] = round(perf_counter() - started, 6)
        print(f"{name}: {metrics[name]:.3f}s", flush=True)
        return value

    print(f"Python {platform.python_version()}, {platform.machine()}, {len(MVP_CATALOGUE.roles)} roles", flush=True)
    document = json.loads(args.capture.read_text(encoding="utf-8"))
    capture = timed("parse_knowledge_capture", lambda: capture_from_document(document))
    with tempfile.TemporaryDirectory(prefix="scouting-refresh-benchmark-") as directory:
        paths = [Path(directory) / f"knowledge-{index}.sqlite3" for index in range(2)]
        with closing(_read_only(args.database)) as source:
            with closing(sqlite3.connect(paths[0])) as target:
                source.backup(target)
        with closing(_read_only(paths[0])) as source, closing(sqlite3.connect(paths[1])) as target:
            source.backup(target)
        stores = [PlayerKnowledgeStore(path) for path in paths]
        feed = timed("parse_feed", scouting_json_provider(args.capture))
        profiles = timed("read_history", lambda: stores[0].best_known_profiles(capture.save_key, capture.game_date))
        pool = timed("merge_history", lambda: compose_candidate_pool(
            feed, profiles, save_key=capture.save_key, as_of=capture.game_date,
        ))
        print(f"Feed: {len(feed)} players; merged pool: {len(pool)}; game date: {capture.game_date}", flush=True)
        cache = {}
        original_summary = scouting.score_role_summary
        scouting.score_role_summary = lambda role, observations: scouting._role_fit(score_role(role, observations))
        try:
            baseline = timed("rank_detailed_reference", lambda: rank_for_position(pool, MVP_CATALOGUE, cache=cache))
            timed("rank_warm", lambda: rank_for_position(pool, MVP_CATALOGUE, cache=cache))
        finally:
            scouting.score_role_summary = original_summary
        if args.profile:
            profile = cProfile.Profile()
            profile.runcall(rank_for_position, pool[:500], MVP_CATALOGUE, cache={})
            pstats.Stats(profile).strip_dirs().sort_stats("cumtime").print_stats(20)
        numeric_cache = {}
        numeric = timed("rank_compact", lambda: rank_for_position(pool, MVP_CATALOGUE, cache=numeric_cache))
        assert numeric == baseline, "Compact scoring changed a complete ranking."
        print("All complete rankings identical.", flush=True)

        for path in paths:
            with closing(sqlite3.connect(path)) as connection, connection:
                _rewind_latest(connection, capture)
        dates = Counter()
        for player in capture.players:
            if player.attributes:
                dates[player.attributes_observed_on or capture.game_date] += len(player.attributes)
            if player.last_known_attributes:
                dates[player.last_known_observed_on] += len(player.last_known_attributes)
        print(f"Attribute groups: {len(dates)} dates, {sum(dates.values())} readings", flush=True)
        stores[0]._record_attributes = _legacy_attributes
        reference = timed("record_reference_replay", lambda: stores[0].record(capture))
        optimized = timed("record_indexed", lambda: stores[1].record(capture))
        assert reference == optimized, "Targeted lookups changed the record result."
        for table in ("profile_observations", "attribute_observations", "sightings"):
            assert _table_equal(paths[0], paths[1], table), f"Targeted lookups changed {table}."
        print(f"Replayed tables identical: {asdict(reference)}", flush=True)

        handler = object.__new__(SquadWebHandler)
        handler.server = SimpleNamespace(scouting_rankings=lambda candidates, **options: rank_for_position(candidates, MVP_CATALOGUE, cache=numeric_cache, **options))
        token = SNAPSHOT.set({"mode": "ranking", "rejected": set(), "raw_positions": False})
        try:
            body = timed("render_warm_snapshot", lambda: handler._scouting_results_block(
                pool, ScoutingFilters(include_former_scouted=True), len(pool),
            ))
        finally:
            SNAPSHOT.reset(token)
        print(f"Snapshot bytes: {len(body.encode('utf-8')):,}", flush=True)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
