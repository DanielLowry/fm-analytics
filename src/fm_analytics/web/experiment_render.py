"""HTML for the Experiments pages. Rendering only: every figure comes from
`reporting.build_experiment_report`, never from here."""

from __future__ import annotations

import html
from typing import Sequence
from urllib.parse import quote

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.experiments import ExperimentReport, VariantFigures
from fm_analytics.domain.experiments import MatchGroup, StoredMatch
from fm_analytics.web.match_render import versus


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def group_url(name: str) -> str:
    return "/experiments/group/" + quote(name, safe="")


def _tactic_options(catalogue: FootballCatalogue, current: str | None = None) -> str:
    return "<option value=''>Not a catalogue tactic</option>" + "".join(
        f"<option value='{_e(key)}'{' selected' if key == current else ''}>{_e(tactic.name)}</option>"
        for key, tactic in sorted(catalogue.tactics.items(), key=lambda item: item[1].name)
    )


def label_fields(catalogue: FootballCatalogue, groups: Sequence[MatchGroup], *, variant: str = "",
                 tactic: str | None = None, note: str = "", tags: dict | None = None, with_groups: bool = True) -> str:
    tag_text = "\n".join(f"{key}={value}" for key, value in (tags or {}).items())
    group_boxes = "".join(
        f"<label class='fm-check'><input type='checkbox' name='group' value='{_e(group.name)}'> {_e(group.name)}</label>"
        for group in groups
    )
    return (
        f"<label>Label: the variant this match tried<input name='label' maxlength='80' value='{_e(variant)}' "
        "placeholder=\"Blank: the name of the tactic FM saved with it\"></label>"
        f"<label>Catalogue tactic, if one fits<select name='tactic'>{_tactic_options(catalogue, tactic)}</select></label>"
        f"<label class='wide'>Notes: anything FM can't record<textarea name='note' maxlength='1000' "
        f"placeholder='Changes made in the match, team talks, what you saw'>{_e(note)}</textarea></label>"
        f"<label class='wide'>Tags, one key=value a line<textarea name='tags' rows='2' placeholder='mentality=cautious'>{_e(tag_text)}</textarea></label>"
        + (("<fieldset class='fm-groups wide'><legend>Put it in groups</legend>" + group_boxes
            + "<label>New group<input name='new_group' maxlength='80' placeholder='e.g. Woking replays'></label></fieldset>")
           if with_groups else "")
    )


def keep_match_form(match_key: str, catalogue: FootballCatalogue, groups: Sequence[MatchGroup]) -> str:
    """The match page's "keep this match for experiments" form."""
    return (
        "<section class='fm-workspace-panel fm-experiment-keep'><details><summary>Store this match for experiments</summary>"
        "<p class='muted'>Copies the match exactly as recorded into your experiments, where you can group it "
        "and compare it with others. Your match history is not changed.</p>"
        "<form class='fm-experiment-form' method='post' action='/experiments/store-history'>"
        f"<input type='hidden' name='match' value='{_e(match_key)}'>"
        + label_fields(catalogue, groups) + "<div class='wide'><button type='submit'>Store it</button></div></form></details></section>"
    )


def _note(note: tuple[str, bool] | None) -> str:
    if not note:
        return ""
    message, ok = note
    return f"<p class='{'fm-note-ok' if ok else 'warn'}'>{_e(message)}</p>"


def _restore(match: StoredMatch) -> str:
    """A withdrawn match's way back into the comparisons, keeping its label."""
    tags = "\n".join(f"{key}={value}" for key, value in match.label.tags.items())
    return (
        " <span class='muted'>(withdrawn)</span><form class='fm-inline-form' method='post' action='/experiments/relabel'>"
        f"<input type='hidden' name='id' value='{match.id}'><input type='hidden' name='label' value='{_e(match.label.variant)}'>"
        f"<input type='hidden' name='tactic' value='{_e(match.label.tactic_key or '')}'>"
        f"<input type='hidden' name='note' value='{_e(match.label.note)}'><input type='hidden' name='tags' value='{_e(tags)}'>"
        "<button type='submit' class='secondary'>Restore</button></form>"
    )


def experiments_body(stored: Sequence[StoredMatch], groups: Sequence[MatchGroup], catalogue: FootballCatalogue,
                     *, note: tuple[str, bool] | None, reads_fm: bool) -> str:
    store_form = (
        "<form class='fm-experiment-form' method='post' action='/experiments/store'>"
        + label_fields(catalogue, groups)
        + "<div class='wide'><button type='submit'>Read FM and store the match I've just played</button></div></form>"
        if reads_fm else
        "<p class='muted'>Reading FM needs fm-web started with <code>--direct-live</code>. You can still store any "
        "match from its page under Matches, or with <code>fm-experiments store</code>.</p>"
    )
    group_rows = "".join(
        f"<tr><td><a href='{group_url(group.name)}'>{_e(group.name)}</a></td><td>{len(group.active)}</td>"
        f"<td>{len({match.label.variant for match in group.active})}</td><td>{_e(group.note)}</td></tr>"
        for group in groups
    )
    match_rows = "".join(
        f"<tr{' class=muted' if match.withdrawn else ''}><td><input type='checkbox' name='id' value='{match.id}' "
        f"form='membership' aria-label='Select #{match.id}'></td><td>#{match.id}</td>"
        f"<td data-sort='{match.match.date}'>{match.match.date:%d %b %Y}</td><td>{_e(match.opponent)}</td>"
        f"<td><a href='/experiments/match/{match.id}'>{match.match.home_goals}–{match.match.away_goals}</a></td>"
        f"<td>{_e(match.label.variant)}{_restore(match) if match.withdrawn else ''}</td>"
        f"<td>{_e(', '.join(match.groups))}</td><td>{_e(match.label.note)}</td></tr>"
        for match in reversed(stored)
    )
    group_options = "".join(f"<option value='{_e(group.name)}'>{_e(group.name)}</option>" for group in groups)
    return (
        "<section class='fm-match-review-hero'><span class='eyebrow'>Experiments</span>"
        "<h2>Store the matches you choose, group them, compare what you tried</h2>"
        "<p>Nothing is stored here unless you ask, and reading matches from FM never adds to it. Save in FM before a "
        "match, play it, store it here with a label for what you tried, then reload and play it again with something "
        "changed. Store the same label several times: FM's match engine is random, so one replay proves little.</p>"
        "</section>"
        + _note(note)
        + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div><h2>Store a match</h2>"
        "<p>FM is read read-only, into a capture of its own that never reaches your match history.</p></div></div>"
        + store_form + "</section>"
        + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div><h2>Groups</h2>"
        "<p>Your own collections of stored matches; one match can be in several.</p></div></div>"
        + (f"<div class='table-scroll'><table class='sortable'><thead><tr><th>Group</th><th>Matches</th><th>Labels</th>"
           f"<th>Note</th></tr></thead><tbody>{group_rows}</tbody></table></div>" if groups else
           "<p class='muted'>No groups yet: name one when you store a match, or below.</p>")
        + "<form class='fm-inline-form' method='post' action='/experiments/group'><label>New group"
        "<input name='name' maxlength='80' required></label><label>Note<input name='note' maxlength='1000'></label>"
        "<button type='submit'>Create group</button></form>"
        f"<p><a class='button-link secondary' href='/experiments/all'>Compare all {len(stored)} stored matches</a></p>"
        "</section>"
        + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div><h2>Stored matches</h2>"
        "<p>Tick matches, then put them in a group or take them out.</p></div></div>"
        + ("<form id='membership' class='fm-inline-form' method='post' action='/experiments/membership'>"
           f"<label>Group<select name='group'>{group_options}</select></label>"
           "<button type='submit' name='member' value='1'>Add ticked</button>"
           "<button type='submit' name='member' value='0' class='secondary'>Remove ticked</button></form>"
           if groups and stored else "")
        + (f"<div class='table-scroll'><table class='sortable'><thead><tr><th></th><th>#</th><th>Date</th><th>Opponent</th>"
           f"<th>Score</th><th>Label</th><th>Groups</th><th>Notes</th></tr></thead><tbody>{match_rows}</tbody></table></div>"
           if stored else "<p class='muted'>No matches stored yet.</p>")
        + "</section>"
    )


def _variant_row(variant: VariantFigures) -> str:
    won, drawn, lost = variant.record
    spread = f" <span class='muted'>(± {variant.balance_spread})</span>" if variant.balance_spread is not None else ""
    return (
        f"<tr><td>{_e(variant.variant)}</td><td>{variant.count}</td><td>W{won} D{drawn} L{lost}</td>"
        f"<td>{variant.points_per_game}</td><td data-sort='{variant.balance}'>{variant.balance:+}{spread}</td>"
        + "".join(f"<td>{versus(*variant.average(name))}</td>"
                  for name in ("worth", "shots", "on_goal", "clear_cut_chances", "second_half_shots", "goals"))
        + f"<td>{'–' if variant.possession is None else f'{variant.possession:.0f}%'}</td></tr>"
    )


def _verdicts(report: ExperimentReport) -> str:
    if not report.comparisons:
        return ""
    items = []
    for item in report.comparisons:
        if item.verdict == "too few runs":
            text = "too few matches to judge yet (3 of each, at least)"
        elif item.verdict == "clear":
            text = f"<strong>clearly worse</strong> ({item.difference:+} ± {item.margin})"
        else:
            settle = f"; about {item.runs_needed} matches of each would settle a gap this size" if item.runs_needed else ""
            text = f"not clear yet ({item.difference:+} ± {item.margin}){settle}"
        items.append(f"<li><strong>{_e(item.variant)}</strong> against {_e(item.against)}: {text}</li>")
    return f"<ul class='fm-verdicts'>{''.join(items)}</ul>"


def _match_rows(report: ExperimentReport, catalogue: FootballCatalogue) -> str:
    rows = []
    for run in report.runs:
        tags = " ".join(f"{key}={value}" for key, value in run.tags.items())
        rows.append(
            f"<tr><td>#{run.run_id}</td><td>{_e(run.variant)}</td>"
            f"<td><a href='/experiments/match/{run.run_id}'>{_e(run.opponent)}</a></td>"
            f"<td data-sort='{run.match.date}'>{run.match.date:%d %b}</td>"
            f"<td>{run.result} {run.goals[0]}–{run.goals[1]}</td><td>{versus(*run.worth)}</td>"
            f"<td data-sort='{run.balance:.2f}'>{run.balance:+.2f}</td><td>{versus(*run.shots)}</td>"
            f"<td>{versus(*run.on_goal)}</td><td>{versus(*run.clear_cut_chances)}</td>"
            f"<td>{versus(*run.second_half_shots)}</td>"
            f"<td>{'–' if run.possession is None else f'{run.possession}%'}</td><td>{_e(run.saved_tactic or '')}</td>"
            f"<td>{_e(run.note)}{' <span class=muted>' + _e(tags) + '</span>' if tags else ''}</td>"
            f"<td><details><summary>Edit</summary><form class='fm-experiment-form' method='post' action='/experiments/relabel'>"
            f"<input type='hidden' name='id' value='{run.run_id}'><input type='hidden' name='back' value='{_e(report.name)}'>"
            + label_fields(catalogue, (), variant=run.variant, tactic=run.tactic_key, note=run.note, tags=dict(run.tags),
                           with_groups=False)
            + "<div class='wide'><button type='submit'>Save</button> <button type='submit' name='withdraw' value='1' "
            "class='secondary'>Withdraw from comparisons</button></div></form></details></td></tr>"
        )
    return "".join(rows)


def group_body(report: ExperimentReport, catalogue: FootballCatalogue, *, copy_control: str,
               note: tuple[str, bool] | None) -> str:
    variants = "".join(_variant_row(variant) for variant in report.variants)
    return (
        "<p><a href='/experiments'>← Experiments</a></p>"
        f"<section class='fm-match-review-hero'><span class='eyebrow'>Experiment</span><h2>{_e(report.name)}</h2>"
        f"<p>{len(report.runs)} matches" + (f", {report.withdrawn} withdrawn and left out" if report.withdrawn else "")
        + (f". {_e(report.note)}" if report.note else ".") + "</p>" + copy_control + "</section>"
        + _note(note)
        + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div><h2>By label</h2>"
        "<p>Best first, by the balance of chances: what your shots were worth less what theirs were, valued as a "
        "match page values them. It moves far less from one replay to the next than goals or points do.</p>"
        "</div></div>"
        + (f"<div class='table-scroll'><table class='sortable'><thead><tr><th>Label</th><th>Matches</th><th>Record</th>"
           f"<th>Points per game</th><th>Balance (spread)</th><th>Chances worth</th><th>Shots</th><th>On goal</th>"
           f"<th>Clear-cut chances</th><th>Second-half shots</th><th>Goals</th><th>Possession</th></tr></thead>"
           f"<tbody>{variants}</tbody></table></div>" if report.variants else "<p class='muted'>No matches in it yet.</p>")
        + _verdicts(report)
        + "<p class='muted fm-match-note'>Pairs are you, then them, averaged over the label's matches. A gap counts "
        "as clear when it is more than twice its standard error (about 19 times in 20 it is not chance). "
        f"Shots are valued from {report.rates_from} of your competitive matches.</p></section>"
        + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div><h2>Matches</h2>"
        "<p>Each one as stored; edit a label, notes or tags, or withdraw a match from the comparison.</p></div></div>"
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>#</th><th>Label</th><th>Opponent</th>"
        "<th>Date</th><th>Result</th><th>Chances worth</th><th>Balance</th><th>Shots</th><th>On goal</th>"
        "<th>Clear-cut chances</th><th>Second-half shots</th><th>Possession</th><th>FM's saved tactic</th>"
        f"<th>Notes and tags</th><th></th></tr></thead><tbody>{_match_rows(report, catalogue)}</tbody></table></div></section>"
    )
