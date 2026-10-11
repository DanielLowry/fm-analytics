"""`fm-web`'s command-line options: where the squad, the histories and the captures come from.

`server.main` parses them; kept apart from the server so the HTTP side and the
option list can each be read on its own.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fm_analytics.candidate_pool import DEFAULT_OUT_OF_DATE_MONTHS
from fm_analytics.knowledge_ingest import DEFAULT_DATABASE as DEFAULT_KNOWLEDGE_DATABASE
from fm_analytics.match_ingest import DEFAULT_DATABASE as DEFAULT_MATCH_DATABASE
from fm_analytics.web.experiment_state import add_experiment_arguments
from fm_analytics.web.hidden_state import add_hidden_arguments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only squad decision-support view")
    parser.add_argument("--league-json", type=Path,
                        help="dated manager-visible league capture for team comparison; with --direct-live it "
                             "defaults to data/league-capture.json, which the League page's read button writes")
    parser.add_argument("--league-db", type=Path, default=Path("data/league-history.sqlite3"),
                        help="append-only league and roster capture history")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--cache-ttl-seconds",
        type=float,
        default=8.0,
        help="how long to reuse a computed recommendation before recomputing it (default: %(default)s)",
    )
    parser.add_argument(
        "--ranking-workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help=(
            "bounded worker processes for tactic ranking; use 1 for the "
            "existing sequential calculation (default: %(default)s)"
        ),
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--fixture",
        help="serve a fixed game/squad fixture (default when no other source is given)",
    )
    source.add_argument(
        "--snapshot-db",
        help="serve the latest (or --capture-id) capture from a --snapshot-db SQLite file",
    )
    source.add_argument(
        "--base-url",
        help="serve the current squad from the FM HTTP bridge at this URL",
    )
    source.add_argument(
        "--direct-live",
        action="store_true",
        help="serve the current squad directly from FM20, without the HTTP bridge",
    )
    parser.add_argument(
        "--capture-id",
        type=int,
        help="a specific capture id to serve from --snapshot-db (default: the latest)",
    )
    parser.add_argument(
        "--fm-html",
        nargs="+",
        help="overlay a manual FM20 Squad HTML export onto the chosen source, like the CLI's --fm-html",
    )
    parser.add_argument(
        "--fm-html-player-count",
        type=int,
        help="required unique-player count shown by FM for --fm-html completeness",
    )
    parser.add_argument(
        "--my-tactics",
        metavar="KEY[,KEY...]",
        help=(
            "comma-separated tactic keys you actually play, primary first "
            "(e.g. vertical_442,wing_play_442). Depth, set pieces and the "
            "tactics page then default to these instead of the top-ranked tactic."
        ),
    )
    parser.add_argument(
        "--knowledge-db",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DATABASE,
        help=(
            "player-knowledge database that scouting captures are recorded into "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--out-of-date-months",
        type=int,
        default=DEFAULT_OUT_OF_DATE_MONTHS,
        help=(
            "game months after which a remembered attribute or fact is labelled "
            "out of date on the Scouting pages (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--no-record-knowledge",
        action="store_true",
        help="do not record scouting captures into the player-knowledge database",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="compare saves without creating, updating or migrating databases; disables history recording and editing",
    )
    add_experiment_arguments(parser)
    add_hidden_arguments(parser)
    parser.add_argument(
        "--match-db",
        type=Path,
        default=DEFAULT_MATCH_DATABASE,
        help="match-history database the Matches page reads and records into (default: %(default)s)",
    )
    parser.add_argument(
        "--scouting-json",
        help="manager-visible discoverability/scouting capture JSON for the Scouting page",
    )
    return parser
