"""`fm-experiments`: store the matches you choose, group them, and compare what you tried.

Only what you ask for is stored. `store` reads FM (read-only) into its own
capture file, `data/experiment-capture.json`, never the match history's, and
keeps the match you have just played; `store-history` copies a match already
in your history. Nothing here writes to the match history: a replayed fixture
stays out of your season. See `docs/match-experiments.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.experiments import ExperimentReport
from fm_analytics.domain.experiments import MatchLabel, Stored, StoredMatch
from fm_analytics.domain.mentality import MentalityPlan
from fm_analytics.domain.matches import MatchCapture, MatchRecord
from fm_analytics.match_ingest import DEFAULT_DATABASE, PROJECT_ROOT, run_capture_tool
from fm_analytics.persistence.experiments import ExperimentStore, ExperimentStoreError
from fm_analytics.persistence.match_history import MatchHistory, MatchHistoryError, MatchHistoryStore
from fm_analytics.reporting import build_experiment_export, build_experiment_report

DEFAULT_EXPERIMENTS = PROJECT_ROOT / "data" / "experiments.sqlite3"
EXPERIMENT_CAPTURE = PROJECT_ROOT / "data" / "experiment-capture.json"
ALL_STORED = "All stored matches"


def latest_played(capture: MatchCapture, match_key: str | None = None) -> MatchRecord:
    """The match just played (the latest), or the one named by `match_key`, when FM's full stats were read."""
    if match_key is not None:
        match = next((match for match in capture.matches if match.key == match_key), None)
    elif capture.matches:
        match = max(capture.matches, key=lambda match: match.date)
    else:
        raise ValueError("FM has no played match to store")
    if match is None or match.detail is None:
        # Never another match in its place: an older match is not the one just played.
        named = match_key if match is None else f"{match.date} {match.home.name} v {match.away.name}"
        raise ValueError(f"FM's full stats for {named} could not be read, so it cannot be stored")
    return match


def with_default_variant(label: MatchLabel, match: MatchRecord, club_id: str) -> MatchLabel:
    """A label with no variant takes the name of the tactic FM saved with the match."""
    if label.variant.strip():
        return label
    saved = match.detail.saved_tactics.get(match.side_of(club_id)) if match.detail else None
    if saved is None or not saved.name:
        raise ValueError("give the match a label: FM saved no tactic name with it")
    return replace(label, variant=saved.name)


def store_from_fm(
    store: ExperimentStore, label: MatchLabel, *, groups: Sequence[str] = (), match_key: str | None = None,
    capture_path: Path = EXPERIMENT_CAPTURE,
) -> tuple[Stored, MatchRecord]:
    """Read FM now (read-only) and store the match just played, or `match_key`.

    The match just played is read alone, in a couple of seconds. Another
    match, or one whose stats that quick read cannot vouch for, takes the full
    read of every match (about fifteen), which tells a fixture's chunks apart
    by comparing them all.
    """
    run_capture_tool(capture_path, latest_only=match_key is None)
    capture = MatchCapture.from_document(json.loads(capture_path.read_text(encoding="utf-8")))
    if match_key is None and capture.matches and capture.matches[-1].detail is None:
        match_key = capture.matches[-1].key
        run_capture_tool(capture_path)
        capture = MatchCapture.from_document(json.loads(capture_path.read_text(encoding="utf-8")))
    match = latest_played(capture, match_key)
    label = with_default_variant(label, match, capture.managed_club.id)
    return store.store(match, capture.managed_club, label, groups=groups), match


def store_from_history(
    store: ExperimentStore, history: MatchHistory, match_key: str, label: MatchLabel, *, groups: Sequence[str] = ()
) -> Stored:
    """Copy a match from the match history into the store."""
    match = next((match for match in history.matches if match.key == match_key), None)
    if match is None:
        raise ValueError(f"no match {match_key} is in your match history")
    if label.mentality is None and match_key in history.mentalities:
        label = replace(label, mentality=history.mentalities[match_key])  # what you recorded on its page
    return store.store(match, history.club, with_default_variant(label, match, history.club.id), groups=groups)


# -- text -----------------------------------------------------------------------


def format_report(report: ExperimentReport) -> str:
    lines = [f"{report.name}: {len(report.runs)} matches"
             + (f" ({report.withdrawn} withdrawn, left out)" if report.withdrawn else "")
             + (f". {report.note}" if report.note else "")]
    if not report.variants:
        return lines[0] + "\nNothing to compare yet: store some matches first."
    lines += ["", f"  {'label':<34} {'n':>3}  W-D-L   pts/g  balance (spread)  worth       shots    on goal  2nd-half shots",
              ]
    for variant in report.variants:
        worth, shots, on_goal, late = (variant.average(name) for name in ("worth", "shots", "on_goal", "second_half_shots"))
        spread = f"({variant.balance_spread})" if variant.balance_spread is not None else ""
        won, drawn, lost = variant.record
        lines.append(f"  {variant.variant[:34]:<34} {variant.count:>3}  {won}-{drawn}-{lost}  {variant.points_per_game:>6}  "
                     f"{variant.balance:>+6} {spread:<9}  {worth[0]}–{worth[1]:<6}  {shots[0]}–{shots[1]:<5}  "
                     f"{on_goal[0]}–{on_goal[1]:<5}  {late[0]}–{late[1]}")
    for item in report.comparisons:
        settle = f"; about {item.runs_needed} of each would settle it" if item.runs_needed and item.verdict != "clear" else ""
        margin = f" ± {item.margin}" if item.margin is not None else ""
        lines.append(f"  {item.variant} against {item.against}: {item.difference:+}{margin} – {item.verdict}{settle}")
    lines += ["", "Matches:"]
    for run in report.runs:
        lines.append(f"  #{run.run_id:<4} {run.variant[:28]:<28} v {run.opponent[:20]:<20} {run.result} "
                     f"{run.goals[0]}-{run.goals[1]}  worth {run.worth[0]}–{run.worth[1]}"
                     + (f"  ({run.mentality.text})" if run.mentality else "")
                     + (f"  [{run.note}]" if run.note else "")
                     + (" " + " ".join(f"{key}={value}" for key, value in run.tags.items()) if run.tags else ""))
    return "\n".join(lines)


def format_store(stored: tuple[StoredMatch, ...], store: ExperimentStore) -> str:
    lines = ["Stored matches:" if stored else "No stored matches yet."]
    for item in stored:
        match = item.match
        lines.append(f"  #{item.id:<4} {match.date} v {item.opponent[:22]:<22} {match.home_goals}-{match.away_goals}  "
                     f"{item.label.variant}" + (f" ({item.label.mentality.text})" if item.label.mentality else "")
                     + (" (withdrawn)" if item.withdrawn else "")
                     + (f"  groups: {', '.join(item.groups)}" if item.groups else ""))
    groups = store.groups()
    if groups:
        lines += ["Groups:"] + [f"  {group.name}: {len(group.active)} matches" for group in groups]
    return "\n".join(lines)


# -- command line ---------------------------------------------------------------


def _tags(values: Sequence[str]) -> dict[str, str]:
    tags = {}
    for value in values:
        key, separator, text = value.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"a tag is key=value, not {value!r}")
        tags[key.strip()] = text.strip()
    return tags


def _label(args: argparse.Namespace) -> MatchLabel:
    if args.tactic and args.tactic not in MVP_CATALOGUE.tactics:
        raise ValueError(f"unknown tactic key {args.tactic!r}")
    return MatchLabel(args.label or "", args.tactic, args.note, _tags(args.tag),
                      MentalityPlan.parse(args.mentality) if args.mentality else None)


def _label_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--label", help="the variant this match tried (default: FM's saved tactic name)")
    parser.add_argument("--tactic", help="the catalogue tactic key, when one fits")
    parser.add_argument("--note", default="", help="anything FM can't record: changes made in the match, say")
    parser.add_argument("--tag", action="append", default=[], help="key=value, as many as you like")
    parser.add_argument("--mentality", help="what it was played in, e.g. 'Balanced, 65 Cautious'")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fm-experiments", description="Store the matches you choose and compare them")
    parser.add_argument("--db", type=Path, default=DEFAULT_EXPERIMENTS, help="experiments database (default: %(default)s)")
    parser.add_argument("--history", type=Path, default=DEFAULT_DATABASE, help="match history, for valuing shots")
    commands = parser.add_subparsers(dest="command", required=True)
    store = commands.add_parser("store", help="read FM now and store the match you have just played")
    store.add_argument("--match", help="store this match key instead of the latest played")
    store.add_argument("--group", action="append", default=[], help="put it in this group (repeatable)")
    _label_options(store)
    history = commands.add_parser("store-history", help="store a match from your match history")
    history.add_argument("match")
    history.add_argument("--group", action="append", default=[])
    _label_options(history)
    commands.add_parser("list", help="every stored match and group")
    group = commands.add_parser("group", help="create, rename or delete a group, or put matches in one or take them out")
    group.add_argument("action", choices=("create", "add", "remove", "rename", "delete"))
    group.add_argument("name")
    group.add_argument("ids", nargs="*", type=int)
    group.add_argument("--note", help="the group's note (rename: default unchanged)")
    group.add_argument("--to", help="rename: the group's new name")
    relabel = commands.add_parser("relabel", help="change a stored match's label, notes or tags")
    relabel.add_argument("id", type=int)
    _label_options(relabel)
    for name, text in (("withdraw", "leave a stored match out of every comparison"), ("restore", "bring it back")):
        commands.add_parser(name, help=text).add_argument("id", type=int)
    commands.add_parser("delete", help="remove stored matches for good, from every group").add_argument(
        "ids", nargs="+", type=int)
    mentality = commands.add_parser("mentality", help="record the mentality stored matches were played in")
    mentality.add_argument("ids", nargs="+", type=int)
    plan = mentality.add_mutually_exclusive_group(required=True)
    plan.add_argument("--set", dest="plan", help="e.g. 'Balanced, 65 Cautious': kickoff, then minute and mentality")
    plan.add_argument("--clear", action="store_true")
    compare = commands.add_parser("compare", help="compare a group's matches label by label (default: all stored)")
    compare.add_argument("group", nargs="?")
    export = commands.add_parser("export", help="a comparison and every match's full record, as JSON")
    export.add_argument("group", nargs="?")
    export.add_argument("--output", type=Path)
    return parser


def _history(path: Path) -> MatchHistory | None:
    store = MatchHistoryStore(path)
    key = store.latest_save_key() if path.exists() else None
    return store.load_history(key) if key else None


def _selection(store: ExperimentStore, group: str | None) -> tuple[str, tuple[StoredMatch, ...], str]:
    """A group's name, matches and note, or every stored match."""
    if group is None:
        return ALL_STORED, store.matches(), ""
    found = store.group(group)
    if found is None:
        raise ValueError(f"no group is called {group!r}")
    return found.name, found.matches, found.note


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ExperimentStore(args.db)
    try:
        if args.command == "store":
            stored, match = store_from_fm(store, _label(args), groups=args.group, match_key=args.match)
            print(f"{'Stored' if stored.added else 'Already stored'} as #{stored.match_id}: {match.date} "
                  f"{match.home.name} {match.home_goals}-{match.away_goals} {match.away.name}.")
        elif args.command == "store-history":
            history = _history(args.history)
            if history is None:
                raise ValueError("there is no match history to copy from")
            stored = store_from_history(store, history, args.match, _label(args), groups=args.group)
            print(f"{'Stored' if stored.added else 'Already stored'} as #{stored.match_id}.")
        elif args.command == "list":
            print(format_store(store.matches(), store))
        elif args.command == "group":
            if args.action == "create":
                store.create_group(args.name, args.note or "")
                if args.ids:
                    store.set_membership(args.name, args.ids, member=True)
            elif args.action == "rename":
                found = store.group(args.name)
                if found is None:
                    raise ValueError(f"no group is called {args.name!r}")
                store.edit_group(args.name, args.to or args.name, found.note if args.note is None else args.note)
            elif args.action == "delete":
                store.delete_group(args.name)
            else:
                store.set_membership(args.name, args.ids, member=args.action == "add")
            print("Done.")
        elif args.command == "mentality":
            plan = None if args.clear else MentalityPlan.parse(args.plan)
            store.set_mentality(args.ids, plan)
            print(f"#{', #'.join(map(str, args.ids))}: {'played in ' + plan.text if plan else 'cleared'}.")
        elif args.command == "delete":
            gone = {item.id: item for item in store.matches() if item.id in args.ids}
            store.delete(args.ids)
            for match_id in args.ids:
                item = gone[match_id]
                print(f"Deleted #{match_id}: {item.match.date} v {item.opponent}, {item.label.variant}.")
        elif args.command in ("relabel", "withdraw", "restore"):
            current = next((item for item in store.matches() if item.id == args.id), None)
            if current is None:
                raise ValueError(f"no stored match {args.id}")
            label = current.label
            if args.command == "relabel":
                label = MatchLabel(args.label or label.variant, args.tactic or label.tactic_key,
                                   args.note or label.note, {**label.tags, **_tags(args.tag)},
                                   MentalityPlan.parse(args.mentality) if args.mentality else label.mentality)
            store.relabel(args.id, label, withdrawn=args.command == "withdraw" or (
                args.command == "relabel" and current.withdrawn))
            print("Done.")
        elif args.command == "compare":
            name, stored, note = _selection(store, args.group)
            print(format_report(build_experiment_report(name, stored, _history(args.history), note=note)))
        elif args.command == "export":
            name, stored, note = _selection(store, args.group)
            document = build_experiment_export(name, stored, _history(args.history), note=note)
            text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            if args.output:
                args.output.write_text(text, encoding="utf-8")
                print(f"Wrote {args.output}")
            else:
                sys.stdout.write(text)
    except (ExperimentStoreError, MatchHistoryError, RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
