"""Team strength from hidden attributes: the XIs clubs fielded, their best XIs, and results against strength.

HIDDEN DATA. Everything here is computed from `domain.hidden.HiddenCapture`,
the real values FM keeps for every player, shown to the manager or not. It
answers the one question the manager-visible model cannot: how much of a
club's results is down to the players it has. Only
`hidden_reporting.build_hidden_strength_report` calls it, for the League page's
hidden view (docs/hidden-attributes.md). Nothing in the recommendation path
may: see analytics/CLAUDE.md, "The manager-visible boundary".

Every XI is scored by the same team model as everywhere else
(`xi_selection.recommend_tactic`: central objective, neutral opponent, no
recent form, the caller's selection policies), so a score here can be set
beside the League page's conservative score for the same squad. Only the
inputs differ: every attribute at its true value, FM's real position
ratings, and every player fully fit, so that only the players are compared.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import permutations
from typing import Iterable, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScoreCache
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    TacticEvaluation,
    TacticFitPolicy,
)
from fm_analytics.analytics.xi_selection import recommend_tactic
from fm_analytics.domain.hidden import POSITION_CODES, HiddenCapture, HiddenPlayer
from fm_analytics.domain.matches import MatchRecord, TeamRef
from fm_analytics.domain.models import AttributeObservation, Visibility

# Where each position sits on the pitch (line, then left/centre/right), to
# find the closest shape our catalogue has when it has none exactly like an XI.
_GRID = {
    "GK": (0, 1), "SW": (1, 1), "DL": (2, 0), "DC": (2, 1), "DR": (2, 2),
    "WBL": (3, 0), "DM": (3, 1), "WBR": (3, 2), "ML": (4, 0), "MC": (4, 1), "MR": (4, 2),
    "AML": (5, 0), "AMC": (5, 1), "AMR": (5, 2), "ST": (6, 1),
}
_LINES = (("DL", "DC", "DR", "SW", "WBL", "WBR"), ("DM",), ("ML", "MC", "MR"), ("AML", "AMC", "AMR"), ("ST",))
# More positions than this out of place and a shape is too different to stand in.
_MAX_MOVES = 4
MIN_MODEL_MATCHES = 40
_MAX_GOALS = 12


Shape = tuple[str, ...]  # an XI's eleven positions, sorted


def shape_of(positions: Iterable[str]) -> Shape:
    return tuple(sorted(positions))


def shape_label(shape: Iterable[str]) -> str:
    """A formation name from the positions alone, by line: "4-4-2", "4-1-4-1", "5-2-1-2"."""
    counts = Counter(shape)
    return "-".join(str(n) for n in (sum(counts[p] for p in line) for line in _LINES) if n) or "?"


def _distance(a: str, b: str) -> int:
    (row_a, col_a), (row_b, col_b) = _GRID[a], _GRID[b]
    return abs(row_a - row_b) + abs(col_a - col_b)


@dataclass(frozen=True)
class ShapeMatch:
    """A catalogue shape standing in for an XI's: its tactics, and who moves where."""

    shape: Shape
    tactic_keys: tuple[str, ...]
    moves: Mapping[str, frozenset[str]]  # an XI position -> the catalogue positions its players may take
    cost: int  # 0 when the catalogue has this exact shape

    @property
    def exact(self) -> bool:
        return self.cost == 0


def catalogue_shapes(catalogue: FootballCatalogue) -> dict[Shape, tuple[str, ...]]:
    shapes: dict[Shape, list[str]] = {}
    for key, tactic in catalogue.tactics.items():
        shapes.setdefault(shape_of(slot.position for slot in tactic.slots), []).append(key)
    return {shape: tuple(keys) for shape, keys in shapes.items()}


def closest_shapes(shape: Shape, shapes: Mapping[Shape, tuple[str, ...]]) -> tuple[ShapeMatch, ...]:
    """The catalogue shapes nearest an XI's: the exact one if we have it, else every one tied nearest.

    Nearness is how far its players would have to move, position by position
    across the pitch (an MC dropping to DM is one step), under the cheapest
    pairing. Positions our grid does not know make the XI unmatched.
    """
    if any(position not in _GRID for position in shape):
        return ()
    if shape in shapes:
        return (ShapeMatch(shape, shapes[shape], {}, 0),)
    have = Counter(shape)
    found: list[ShapeMatch] = []
    for candidate, keys in shapes.items():
        if len(candidate) != len(shape) or any(position not in _GRID for position in candidate):
            continue
        need = Counter(candidate)
        extra = list((have - need).elements())
        missing = list((need - have).elements())
        if len(extra) > _MAX_MOVES:
            continue
        cost, pairing = min(((sum(_distance(a, b) for a, b in zip(extra, order)), order)
                             for order in permutations(missing)), key=lambda item: item[0])
        moves: dict[str, set[str]] = {}
        for source, target in zip(extra, pairing):
            moves.setdefault(source, set()).add(target)
        found.append(ShapeMatch(candidate, keys, {k: frozenset(v) for k, v in moves.items()}, cost))
    if not found:
        return ()
    best = min(match.cost for match in found)
    return tuple(sorted((match for match in found if match.cost == best), key=lambda match: match.shape))


@dataclass(frozen=True)
class XiPlayer:
    player_id: str
    name: str
    position: str  # where the XI's evaluation placed him
    role_name: str
    score: float  # his slot score in this XI


@dataclass(frozen=True)
class XiStrength:
    """One XI under the team model. `score` is None when it could not be scored, and `missing` says why."""

    score: float | None
    shape: str  # by line, from the positions fielded or the tactic used
    tactic_key: str | None = None
    tactic_name: str | None = None
    exact_shape: bool = True  # False: our catalogue lacks the shape and its nearest stood in
    players: tuple[XiPlayer, ...] = ()
    missing: tuple[str, ...] = ()
    # True when the squad has nobody FM rates able to play some slot, so the
    # XI was picked with everyone allowed anywhere, at his real rating there.
    out_of_position: bool = False

    @property
    def scored(self) -> bool:
        return self.score is not None


class _Scorer:
    """Scores XIs from one capture, sharing role scores and the derived catalogue views."""

    def __init__(self, capture: HiddenCapture, catalogue: FootballCatalogue, readiness: ReadinessPolicy,
                 familiarity: FamiliarityPolicy, fit: TacticFitPolicy):
        self.capture, self.catalogue = capture, catalogue
        self.readiness, self.familiarity, self.fit = readiness, familiarity, fit
        self.cache = RoleScoreCache()
        self.shapes = catalogue_shapes(catalogue)
        self._catalogues: dict[tuple[str, ...], FootballCatalogue] = {}
        self._observations: dict[str, Mapping[str, AttributeObservation]] = {}
        self._line_ups: dict[tuple, XiStrength] = {}
        self._closest: dict[Shape, tuple[ShapeMatch, ...]] = {}

    def closest(self, shape: Shape) -> tuple[ShapeMatch, ...]:
        if shape not in self._closest:
            self._closest[shape] = closest_shapes(shape, self.shapes)
        return self._closest[shape]

    def _restricted(self, keys: tuple[str, ...]) -> FootballCatalogue:
        if keys not in self._catalogues:
            self._catalogues[keys] = replace(self.catalogue, tactics={key: self.catalogue.tactics[key] for key in keys})
        return self._catalogues[keys]

    def selection(self, player: HiddenPlayer, positions: tuple[str, ...] | None = None) -> PlayerSelectionInput:
        """Him exactly as FM knows him, fully fit; `positions` restricts where he may play."""
        observations = self._observations.get(player.id)
        if observations is None:
            # One mapping per player: the role-score cache recognises a player by it.
            observations = {name: AttributeObservation(Visibility.KNOWN, value)
                            for name, value in player.attributes.items()}
            self._observations[player.id] = observations
        return PlayerSelectionInput(
            id=player.id, name=player.name, positions=positions or player.positions, attributes=observations,
            availability="available", injured=False, suspended=False, condition_percent=100,
            match_fitness_percent=100, position_familiarity=dict(player.position_ratings),
        )

    def best(self, players: Sequence[PlayerSelectionInput], keys: Iterable[str]) -> TacticEvaluation | None:
        keys = tuple(sorted(set(keys)))
        if not keys or not players:
            return None
        selected = recommend_tactic(players, self._restricted(keys), readiness_policy=self.readiness,
                                    familiarity_policy=self.familiarity, fit_policy=self.fit,
                                    role_score_cache=self.cache).selected
        return selected if selected.has_legal_xi else None

    def best_xi(self, squad: Sequence[HiddenPlayer], keys: Iterable[str]) -> XiStrength:
        """A squad's best XI in these tactics, every player where FM rates him able to play.

        A squad with nobody rated able to play some slot (no DM, say) still
        fields one: then everyone may play anywhere, discounted by his real
        rating there exactly as an unfamiliar position always is.
        """
        keys = tuple(keys)
        evaluation = self.best([self.selection(player) for player in squad], keys)
        if evaluation is not None:
            return _strength(evaluation, exact=True)
        evaluation = self.best([self.selection(player, POSITION_CODES) for player in squad], keys)
        if evaluation is not None:
            return replace(_strength(evaluation, exact=True), out_of_position=True)
        shape = shape_label(slot.position for slot in self.catalogue.tactics[keys[0]].slots) if keys else "?"
        return XiStrength(None, shape, missing=(f"{len(squad)} players: not enough for an XI",))

    def line_up(self, starters: Sequence[tuple[HiddenPlayer | None, str | None, str]]) -> XiStrength:
        """The eleven a club fielded, each where he started, in the best tactic of their shape.

        `starters` is (player, start position, name in the match record). The
        tactic is our catalogue's best for that shape, with its roles chosen
        for these players; without that exact shape, the nearest stands in and
        only the players it moves may change position.
        """
        missing = tuple(name for player, position, name in starters if player is None or position is None)
        positions = [position for _player, position, _name in starters if position]
        label = shape_label(positions)
        if missing or len(starters) != 11:
            return XiStrength(None, label, missing=missing or (f"{len(starters)} starters recorded",))
        key = tuple(sorted((player.id, position) for player, position, _name in starters))
        if key in self._line_ups:
            return self._line_ups[key]
        best: tuple[TacticEvaluation, ShapeMatch] | None = None
        for match in self.closest(shape_of(positions)):
            players = [self.selection(player, (position, *sorted(match.moves.get(position, ()))))
                       for player, position, _name in starters]
            evaluation = self.best(players, match.tactic_keys)
            if evaluation is not None and (best is None or evaluation.score.central > best[0].score.central):
                best = (evaluation, match)
        result = (XiStrength(None, label, missing=("no tactic of a similar shape",)) if best is None else
                  replace(_strength(best[0], exact=best[1].exact), shape=label))
        self._line_ups[key] = result
        return result


def _strength(evaluation: TacticEvaluation, *, exact: bool) -> XiStrength:
    players = tuple(
        XiPlayer(item.player_id, item.player_name, item.slot.position, item.intrinsic_role_score.role_name,
                 round(item.selection_score.central, 2))
        for item in sorted(evaluation.assignments, key=lambda item: _GRID.get(item.slot.position, (9, 9)))
    )
    return XiStrength(round(evaluation.score.central, 2),
                      shape_label(slot.position for slot in evaluation.tactic.slots),
                      evaluation.tactic.key, evaluation.tactic.name, exact, players)


# --- Results against strength -------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What a strength gap predicts for one match, from the home side's view."""

    home_goals: float
    away_goals: float
    home_win: float
    draw: float
    away_win: float

    def expected_points(self, side: str) -> float:
        win = self.home_win if side == "home" else self.away_win
        return 3 * win + self.draw

    def points_variance(self, side: str) -> float:
        """How much the points from this one match would vary if it were played again and again."""
        win = self.home_win if side == "home" else self.away_win
        return 9 * win + self.draw - self.expected_points(side) ** 2


@dataclass(frozen=True)
class StrengthModel:
    """Goals against the XI-score gap, fitted on every league match where both XIs were scored.

    Each side's goals are a Poisson count whose log mean moves linearly with
    the gap (home XI score minus away XI score): `home_base + slope * gap` for
    the home side, `away_base - slope * gap` for the away side. Fitted by
    maximum likelihood; `slope_error` is its standard error.
    """

    home_base: float
    away_base: float
    slope: float
    slope_error: float
    matches: int

    def outcome(self, home_score: float, away_score: float) -> Outcome:
        gap = home_score - away_score
        home = math.exp(self.home_base + self.slope * gap)
        away = math.exp(self.away_base - self.slope * gap)
        home_p = [_poisson(k, home) for k in range(_MAX_GOALS + 1)]
        away_p = [_poisson(k, away) for k in range(_MAX_GOALS + 1)]
        win = sum(h * a for i, h in enumerate(home_p) for j, a in enumerate(away_p) if i > j)
        draw = sum(h * a for h, a in zip(home_p, away_p))
        total = sum(home_p) * sum(away_p)
        return Outcome(home, away, win / total, draw / total, (total - win - draw) / total)

    def goals_per_point(self) -> float:
        """Extra goals a match, roughly, for each point of XI-score advantage at an even match."""
        return self.slope * (math.exp(self.home_base) + math.exp(self.away_base))


def _poisson(k: int, mean: float) -> float:
    return math.exp(k * math.log(mean) - mean - math.lgamma(k + 1)) if mean > 0 else float(k == 0)


def fit_strength_model(samples: Sequence[tuple[float, float, int, int]]) -> StrengthModel | None:
    """(home XI score, away XI score, home goals, away goals) per match -> the fitted model, or None.

    None with fewer than MIN_MODEL_MATCHES matches, or when the fit does not
    settle: too few results to say how strength turns into goals.
    """
    if len(samples) < MIN_MODEL_MATCHES:
        return None
    gaps = [home - away for home, away, _h, _a in samples]
    home_goals = [h for _x, _y, h, _a in samples]
    away_goals = [a for _x, _y, _h, a in samples]
    if not sum(home_goals) or not sum(away_goals):
        return None
    theta = [math.log(sum(home_goals) / len(samples)), math.log(sum(away_goals) / len(samples)), 0.0]
    information = None
    for _ in range(50):
        a, c, b = theta
        gradient = [0.0, 0.0, 0.0]
        hessian = [[0.0] * 3 for _ in range(3)]
        for gap, gh, ga in zip(gaps, home_goals, away_goals):
            lh, la = math.exp(a + b * gap), math.exp(c - b * gap)
            gradient[0] += gh - lh
            gradient[1] += ga - la
            gradient[2] += (gh - lh) * gap - (ga - la) * gap
            hessian[0][0] -= lh
            hessian[1][1] -= la
            hessian[2][2] -= (lh + la) * gap * gap
            hessian[0][2] -= lh * gap
            hessian[1][2] += la * gap
        hessian[2][0], hessian[2][1] = hessian[0][2], hessian[1][2]
        step = _solve(hessian, gradient)
        if step is None:
            return None
        theta = [value - delta for value, delta in zip(theta, step)]
        information = hessian
        if max(abs(delta) for delta in step) < 1e-10:
            break
    else:
        return None
    variance = _solve([[-value for value in row] for row in information], [0.0, 0.0, 1.0])
    if variance is None or variance[2] <= 0:
        return None
    return StrengthModel(theta[0], theta[1], theta[2], math.sqrt(variance[2]), len(samples))


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """matrix⁻¹ · vector for a small system, by Gaussian elimination; None if singular."""
    size = len(vector)
    rows = [list(row) + [value] for row, value in zip(matrix, vector)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(rows[r][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for r in range(size):
            if r != column:
                factor = rows[r][column] / rows[column][column]
                rows[r] = [x - factor * y for x, y in zip(rows[r], rows[column])]
    return [rows[r][size] / rows[r][r] for r in range(size)]


# --- The report ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldedMatch:
    """A match with both XIs as they started it."""

    match: MatchRecord
    home: XiStrength
    away: XiStrength

    @property
    def scored(self) -> bool:
        return self.home.scored and self.away.scored


@dataclass(frozen=True)
class OurMatch:
    fielded: FieldedMatch
    side: str  # ours: "home" or "away"
    outcome: Outcome | None  # what the strength gap predicts; None without a model or a scored XI
    our_formation: str = ""  # the tactic we played where known, else the shape by line
    their_formation: str = ""  # FM's name for their formation, else the shape by line

    @property
    def match(self) -> MatchRecord:
        return self.fielded.match

    @property
    def ours(self) -> XiStrength:
        return getattr(self.fielded, self.side)

    @property
    def theirs(self) -> XiStrength:
        return getattr(self.fielded, "away" if self.side == "home" else "home")

    @property
    def opponent(self) -> TeamRef:
        return self.match.away if self.side == "home" else self.match.home

    @property
    def goals_for(self) -> int:
        return self.match.goals(self.side)

    @property
    def goals_against(self) -> int:
        return self.match.goals("away" if self.side == "home" else "home")

    @property
    def points(self) -> int:
        return 3 if self.goals_for > self.goals_against else int(self.goals_for == self.goals_against)

    @property
    def gap(self) -> float | None:
        return self.ours.score - self.theirs.score if self.ours.scored and self.theirs.scored else None

    @property
    def expected_points(self) -> float | None:
        return self.outcome.expected_points(self.side) if self.outcome else None

    @property
    def expected_for(self) -> float | None:
        if self.outcome is None:
            return None
        return self.outcome.home_goals if self.side == "home" else self.outcome.away_goals

    @property
    def expected_against(self) -> float | None:
        if self.outcome is None:
            return None
        return self.outcome.away_goals if self.side == "home" else self.outcome.home_goals


@dataclass(frozen=True)
class TacticRow:
    """One club's best XI in each of the tactics compared."""

    club: TeamRef
    ours: bool
    squad_size: int
    xis: Mapping[str, XiStrength]  # by tactic key


@dataclass(frozen=True)
class FormationUse:
    shape: Shape
    name: str  # FM's name (ours: our tactic's) where known, else by line
    matches: int
    exact: bool  # False: our catalogue has no tactic of this shape, so the nearest stood in


@dataclass(frozen=True)
class FormationRow:
    club: TeamRef
    ours: bool
    formations: tuple[FormationUse, ...]  # most used first
    best: XiStrength | None  # None when no formation of theirs is recorded
    best_formation: str | None


@dataclass(frozen=True)
class ClubRecord:
    """A club's league season so far against what its fielded XIs predicted."""

    club: TeamRef
    ours: bool
    played: int  # matches with both XIs scored
    points: int
    expected_points: float
    goals_for: int
    goals_against: int
    expected_for: float
    expected_against: float
    average_xi: float
    average_opponent_xi: float

    @property
    def points_gap(self) -> float:
        return self.points - self.expected_points


RECENT_MATCHES = 5


@dataclass(frozen=True)
class Verdict:
    """Our league season against what our XIs predicted, and where our players rank."""

    played: int
    points: int
    expected_points: float
    recent_played: int  # our last RECENT_MATCHES league matches with an expectation
    recent_points: int
    recent_expected: float
    # The usual run of luck: the standard deviation of points over those matches
    # if they were replayed with the same XIs, from the model's own odds.
    spread: float
    recent_spread: float
    clubs: int
    points_rank: int | None  # by points, among the clubs with a scored match
    fielded_rank: int | None  # by the average XI we fielded
    best_rank: int | None  # by our best XI in the tactic we played most
    best_tactic: str | None

    @property
    def points_gap(self) -> float:
        return self.points - self.expected_points

    @property
    def recent_gap(self) -> float:
        return self.recent_points - self.recent_expected


def _rank(rows, ours, value) -> int | None:
    """1 + how many rows beat ours on `value`; None when ours has no value."""
    mine = value(ours) if ours is not None else None
    if mine is None:
        return None
    return 1 + sum(1 for row in rows if row is not ours and (other := value(row)) is not None and other > mine)


@dataclass(frozen=True)
class HiddenStrength:
    capture: HiddenCapture
    season: int
    our_tactics: tuple[tuple[str, int], ...]  # tactic keys we used this season, with how many matches, most first
    compared_tactics: tuple[str, ...]
    our_matches: tuple[OurMatch, ...]
    by_tactic: tuple[TacticRow, ...]
    by_formation: tuple[FormationRow, ...]
    model: StrengthModel | None
    clubs: tuple[ClubRecord, ...]
    league_matches: int  # this season's league matches recorded
    league_scored: int  # ... with both XIs scored (the model's matches)
    verdict: Verdict | None = None  # None until we have a scored league match
    tactic_names: Mapping[str, str] = field(default_factory=dict)  # every compared tactic's name, by key


def _starters(capture: HiddenCapture, match: MatchRecord, side: str) -> list[tuple[HiddenPlayer | None, str | None, str]]:
    starters = []
    for line in sorted((p for p in match.detail.players_for(side) if p.started), key=lambda p: p.order):
        player = capture.players.get(line.player_id) if line.player_id else capture.by_short_id(line.short_id)
        # FM's short ID names one person; a different name means it is not who started.
        if player is not None and line.name and player.name != line.name:
            player = None
        starters.append((player, line.start_position or line.position, line.name or (player.name if player else line.label)))
    return starters


def build_hidden_strength(
    capture: HiddenCapture,
    our_matches: Sequence[MatchRecord],
    club_matches: Sequence[MatchRecord],
    *,
    our_club_id: str,
    season: int,
    our_tactic_keys: Mapping[str, str | None],
    catalogue: FootballCatalogue,
    extra_tactic: str | None = None,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> HiddenStrength:
    """Every table of the hidden view for one season.

    `our_matches` are our competitive matches that season; `club_matches` the
    other league clubs' recorded matches (any season: only this season's
    league matches are used). `our_tactic_keys` gives the catalogue tactic we
    played in each of our matches, by match key, where known.
    """
    scorer = _Scorer(capture, catalogue, readiness_policy, familiarity_policy, fit_policy)

    def in_league(match: MatchRecord) -> bool:
        # FM's match records and its competition object give the league different
        # IDs (148 and 5123055 for the National League South), but the same name.
        return match.competition.name == capture.competition.name

    ours = [match for match in our_matches if match.detail is not None]
    seen = {match.key for match in ours}
    theirs = [match for match in club_matches if match.detail is not None and match.season == season
              and in_league(match) and match.key not in seen]
    fielded = {match.key: FieldedMatch(match, scorer.line_up(_starters(capture, match, "home")),
                                       scorer.line_up(_starters(capture, match, "away")))
               for match in (*ours, *theirs)}
    league_fielded = [fielded[match.key] for match in (*ours, *theirs) if in_league(match)]
    model = fit_strength_model([(item.home.score, item.away.score, item.match.home_goals, item.match.away_goals)
                                for item in league_fielded if item.scored])

    def outcome(item: FieldedMatch) -> Outcome | None:
        return model.outcome(item.home.score, item.away.score) if model and item.scored else None

    def formation(match: MatchRecord, side: str) -> str:
        team = match.home if side == "home" else match.away
        key = our_tactic_keys.get(match.key) if team.id == our_club_id else None
        if key in catalogue.tactics:
            return catalogue.tactics[key].name
        named = match.detail.formations.get(side)
        return named or getattr(fielded[match.key], side).shape

    rows = tuple(OurMatch(fielded[match.key], match.side_of(our_club_id), outcome(fielded[match.key]),
                          formation(match, match.side_of(our_club_id)),
                          formation(match, "away" if match.side_of(our_club_id) == "home" else "home"))
                 for match in sorted(ours, key=lambda m: (m.date, m.key)))

    used = Counter(key for match in ours if (key := our_tactic_keys.get(match.key)) in catalogue.tactics)
    our_tactics = tuple(sorted(used.items(), key=lambda item: (-item[1], item[0])))
    compared = tuple(key for key, _count in our_tactics)
    if extra_tactic and extra_tactic not in compared:
        compared += (extra_tactic,)
    by_tactic = tuple(TacticRow(team.club, team.club.id == our_club_id, len(team.player_ids),
                                {key: scorer.best_xi(capture.squad(team.club.id), (key,)) for key in compared})
                      for team in capture.teams)

    shapes: dict[str, Counter] = {}
    names: dict[tuple[str, Shape], Counter] = {}
    for item in league_fielded:
        for side in ("home", "away"):
            team = item.match.home if side == "home" else item.match.away
            positions = [position for _p, position, _n in _starters(capture, item.match, side) if position]
            if len(positions) != 11:
                continue
            shape = shape_of(positions)
            shapes.setdefault(team.id, Counter())[shape] += 1
            names.setdefault((team.id, shape), Counter())[formation(item.match, side)] += 1
    by_formation = []
    for team in capture.teams:
        uses, keys, origin = [], [], {}
        for shape, count in sorted(shapes.get(team.club.id, Counter()).items(), key=lambda item: (-item[1], item[0])):
            name = names[(team.club.id, shape)].most_common(1)[0][0]
            matches = scorer.closest(shape)
            uses.append(FormationUse(shape, name, count, bool(matches) and matches[0].exact))
            for match in matches:
                for key in match.tactic_keys:
                    keys.append(key)
                    origin.setdefault(key, name)
        best = scorer.best_xi(capture.squad(team.club.id), keys) if keys else None
        by_formation.append(FormationRow(team.club, team.club.id == our_club_id, tuple(uses), best,
                                         origin.get(best.tactic_key) if best and best.tactic_key else None))

    clubs = []
    for team in capture.teams:
        mine = [(item, "home" if item.match.home.id == team.club.id else "away") for item in league_fielded
                if item.scored and team.club.id in (item.match.home.id, item.match.away.id)]
        if not mine:
            continue
        expected = [outcome(item) for item, _side in mine]
        goals_for = sum(item.match.goals(side) for item, side in mine)
        goals_against = sum(item.match.goals("away" if side == "home" else "home") for item, side in mine)
        points = sum(3 if item.match.goals(side) > item.match.goals("away" if side == "home" else "home") else
                     int(item.match.home_goals == item.match.away_goals) for item, side in mine)
        clubs.append(ClubRecord(
            team.club, team.club.id == our_club_id, len(mine), points,
            sum(o.expected_points(side) for o, (_i, side) in zip(expected, mine)) if model else 0.0,
            goals_for, goals_against,
            sum(o.home_goals if side == "home" else o.away_goals for o, (_i, side) in zip(expected, mine)) if model else 0.0,
            sum(o.away_goals if side == "home" else o.home_goals for o, (_i, side) in zip(expected, mine)) if model else 0.0,
            sum(getattr(item, side).score for item, side in mine) / len(mine),
            sum(getattr(item, "away" if side == "home" else "home").score for item, side in mine) / len(mine),
        ))
    clubs.sort(key=lambda row: (-row.points, -(row.goals_for - row.goals_against), -row.goals_for, row.club.name))
    verdict = None
    record = next((row for row in clubs if row.ours), None)
    if record is not None and model is not None:
        recent = [row for row in rows if in_league(row.match) and row.outcome is not None][-RECENT_MATCHES:]
        main = compared[0] if compared else None
        tactic_rows = {row.club.id: row for row in by_tactic}
        league_rows = [row for row in rows if in_league(row.match) and row.outcome is not None]
        verdict = Verdict(
            record.played, record.points, record.expected_points, len(recent), sum(row.points for row in recent),
            sum(row.expected_points for row in recent),
            math.sqrt(sum(row.outcome.points_variance(row.side) for row in league_rows)),
            math.sqrt(sum(row.outcome.points_variance(row.side) for row in recent)), len(clubs),
            _rank(clubs, record, lambda row: row.points), _rank(clubs, record, lambda row: row.average_xi),
            _rank(by_tactic, tactic_rows.get(our_club_id), lambda row: row.xis[main].score) if main else None, main,
        )
    return HiddenStrength(capture, season, our_tactics, compared, rows, by_tactic, tuple(by_formation),
                          model, tuple(clubs), len(league_fielded), sum(item.scored for item in league_fielded), verdict,
                          {key: catalogue.tactics[key].name for key in compared})
