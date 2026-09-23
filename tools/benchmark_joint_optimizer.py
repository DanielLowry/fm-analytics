"""Compare the production role-version loop with the joint MILP prototype.

The synthetic input is deliberately deterministic and printed with the result,
because XI optimisation cost depends heavily on positional eligibility.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from time import perf_counter

from fm_analytics.analytics import (
    FamiliarityPolicy,
    FootballCatalogue,
    MVP_CATALOGUE,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    evaluate_tactic,
)
from fm_analytics.analytics.joint_optimizer import optimise_tactic_jointly
from fm_analytics.domain import AttributeObservation, Visibility


@dataclass(frozen=True)
class Comparison:
    tactic_key: str
    production_score: float
    joint_score: float
    same_score: bool
    same_roles: bool
    same_players: bool
    joint_variables: int
    joint_binaries: int
    joint_constraints: int
    joint_nodes: int


def synthetic_players(count: int, seed: int) -> tuple[PlayerSelectionInput, ...]:
    rng = random.Random(seed)
    positions = tuple(
        sorted(
            {
                position
                for role in MVP_CATALOGUE.roles.values()
                for position in role.eligible_positions
            }
        )
    )
    attributes = tuple(
        sorted(
            {
                attribute.name
                for role in MVP_CATALOGUE.roles.values()
                for attribute in role.attributes
            }
        )
    )
    return tuple(
        PlayerSelectionInput(
            id=str(index),
            name=f"Synthetic Player {index:02}",
            positions=tuple(rng.sample(positions, rng.randint(2, 4))),
            attributes={
                name: AttributeObservation(
                    Visibility.KNOWN, value=rng.randint(6, 18)
                )
                for name in attributes
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
            position_familiarity={position: 20 for position in positions},
        )
        for index in range(1, count + 1)
    )


def _signature(assignments) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            assignment.slot.key,
            assignment.player_id,
            assignment.intrinsic_role_score.role_key,
        )
        for assignment in assignments
    )


def benchmark(*, player_count: int, seed: int, tactic_key: str | None) -> None:
    players = synthetic_players(player_count, seed)
    familiarity = FamiliarityPolicy(floor_multiplier=1.0)
    tactics = (
        (MVP_CATALOGUE.tactics[tactic_key],)
        if tactic_key
        else tuple(MVP_CATALOGUE.tactics.values())
    )

    started = perf_counter()
    production = {
        tactic.key: evaluate_tactic(
            tactic,
            players,
            MVP_CATALOGUE,
            familiarity_policy=familiarity,
        )
        for tactic in tactics
    }
    production_seconds = perf_counter() - started

    started = perf_counter()
    joint = {
        tactic.key: optimise_tactic_jointly(
            tactic,
            players,
            MVP_CATALOGUE,
            familiarity_policy=familiarity,
        )
        for tactic in tactics
    }
    joint_seconds = perf_counter() - started

    comparisons: list[Comparison] = []
    infeasible: list[str] = []
    for tactic in tactics:
        old = production[tactic.key]
        new = joint[tactic.key]
        if not old.has_legal_xi or new is None:
            if old.has_legal_xi != (new is not None):
                infeasible.append(tactic.key)
            continue
        old_signature = _signature(old.assignments)
        new_signature = _signature(new.assignments)
        comparisons.append(
            Comparison(
                tactic_key=tactic.key,
                production_score=old.score.central,
                joint_score=new.objective,
                same_score=abs(old.score.central - new.objective) <= 1e-5,
                same_roles=tuple(item[2] for item in old_signature)
                == tuple(item[2] for item in new_signature),
                same_players=tuple(item[1] for item in old_signature)
                == tuple(item[1] for item in new_signature),
                joint_variables=new.variable_count,
                joint_binaries=new.binary_variable_count,
                joint_constraints=new.constraint_count,
                joint_nodes=new.mip_node_count,
            )
        )

    mismatches = [item for item in comparisons if not item.same_score]
    role_ties = [item for item in comparisons if item.same_score and not item.same_roles]
    player_ties = [item for item in comparisons if item.same_score and not item.same_players]
    print(
        f"Synthetic squad: {player_count} players, 2-4 random eligible positions, "
        f"full familiarity, attributes 6-18, seed={seed}"
    )
    print(f"Tactics: {len(tactics)} ({len(comparisons)} legal full XIs in both solvers)")
    print(f"Production: {production_seconds:.3f}s")
    print(f"Joint MILP: {joint_seconds:.3f}s")
    print(
        f"Speed-up: {production_seconds / joint_seconds:.2f}x"
        if joint_seconds
        else "Speed-up: infinite"
    )
    print(
        f"Equal objective: {len(comparisons) - len(mismatches)}/{len(comparisons)}; "
        f"equal roles: {len(comparisons) - len(role_ties)}/{len(comparisons)}; "
        f"equal players: {len(comparisons) - len(player_ties)}/{len(comparisons)}"
    )
    if comparisons:
        print(
            "Joint model maxima: "
            f"{max(item.joint_variables for item in comparisons)} variables, "
            f"{max(item.joint_binaries for item in comparisons)} binaries, "
            f"{max(item.joint_constraints for item in comparisons)} constraints, "
            f"{max(item.joint_nodes for item in comparisons)} branch-and-bound nodes"
        )
    for item in mismatches:
        print(
            f"MISMATCH {item.tactic_key}: production={item.production_score:.6f} "
            f"joint={item.joint_score:.6f}"
        )
    if role_ties:
        print("Equal-score role differences: " + ", ".join(item.tactic_key for item in role_ties))
    if player_ties:
        print("Equal-score player differences: " + ", ".join(item.tactic_key for item in player_ties))
    if infeasible:
        print("Feasibility disagreement: " + ", ".join(infeasible))


def stress_benchmark(*, player_count: int, seed: int) -> None:
    """Exercise the 2^7 * 3^3 role-version case that motivated the prototype."""
    version = "joint-optimiser-stress-v1"
    roles = tuple(
        RoleDefinition(
            key=f"role-{name}",
            name=f"Role {name.upper()}",
            eligible_positions=("ST",),
            attributes=(RoleAttribute(name, 1.0), RoleAttribute("common", 0.5)),
            catalogue_version=version,
        )
        for name in ("a", "b", "c")
    )
    slots = tuple(
        TacticSlot(f"binary-{index}", "ST", "role-a", ("role-b",))
        for index in range(7)
    ) + tuple(
        TacticSlot(f"ternary-{index}", "ST", "role-a", ("role-b", "role-c"))
        for index in range(3)
    ) + (TacticSlot("pinned", "ST", "role-a"),)
    tactic = TacticDefinition(
        key="stress",
        name="3,456 role-version stress case",
        formation="synthetic",
        mentality="Balanced",
        instructions=(),
        slots=slots,
        catalogue_version=version,
    )
    catalogue = FootballCatalogue(
        version=version,
        roles={role.key: role for role in roles},
        tactics={tactic.key: tactic},
    )
    rng = random.Random(seed)
    players = tuple(
        PlayerSelectionInput(
            id=str(index),
            name=f"Stress Player {index:02}",
            positions=("ST",),
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=rng.randint(6, 18))
                for name in ("a", "b", "c", "common")
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
            position_familiarity={"ST": 20},
        )
        for index in range(1, player_count + 1)
    )
    familiarity = FamiliarityPolicy(floor_multiplier=1.0)

    started = perf_counter()
    production = evaluate_tactic(
        tactic, players, catalogue, familiarity_policy=familiarity
    )
    production_seconds = perf_counter() - started
    started = perf_counter()
    joint = optimise_tactic_jointly(
        tactic, players, catalogue, familiarity_policy=familiarity
    )
    joint_seconds = perf_counter() - started
    assert joint is not None

    print(
        f"Stress case: 7 binary slots, 3 ternary slots, 1 pinned slot; "
        f"3,456 role versions; {player_count} all-position-eligible players; seed={seed}"
    )
    print(f"Production: {production_seconds:.3f}s")
    print(f"Joint MILP: {joint_seconds:.3f}s")
    print(f"Speed-up: {production_seconds / joint_seconds:.2f}x")
    print(
        f"Objective: production={production.score.central:.6f}, "
        f"joint={joint.objective:.6f}, "
        f"equal={abs(production.score.central - joint.objective) <= 1e-5}"
    )
    print(
        f"Joint model: {joint.variable_count} variables, {joint.binary_variable_count} "
        f"binaries, {joint.constraint_count} constraints, "
        f"{joint.mip_node_count} branch-and-bound nodes"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--tactic", choices=tuple(MVP_CATALOGUE.tactics))
    parser.add_argument(
        "--stress",
        action="store_true",
        help="run the synthetic 2^7 * 3^3 role-version case",
    )
    args = parser.parse_args()
    if args.stress:
        stress_benchmark(player_count=args.players, seed=args.seed)
    else:
        benchmark(player_count=args.players, seed=args.seed, tactic_key=args.tactic)


if __name__ == "__main__":
    main()
