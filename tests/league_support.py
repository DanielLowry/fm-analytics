"""Small synthetic visible-knowledge league, never a live capture."""
from dataclasses import replace

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition
from tools.league_demo import build_demo_capture as league_capture


def small_catalogue():
    tactic = MVP_CATALOGUE.tactics["balanced_442"]
    positions = tuple(sorted({slot.position for slot in tactic.slots}))
    role = RoleDefinition("generic", "Generic role", positions, (RoleAttribute("passing", 1),),
                          MVP_CATALOGUE.version)
    tactic = replace(tactic, instructions=(), instruction_rationale={}, in_possession=None, in_transition=None, out_of_possession=None, attribute_taper=(),
                     attribute_emphasis=(), slots=tuple(replace(slot, role_key=role.key,
                     alternate_role_keys=(), attribute_emphasis={}) for slot in tactic.slots))
    return FootballCatalogue(MVP_CATALOGUE.version, {role.key: role}, {tactic.key: tactic})
