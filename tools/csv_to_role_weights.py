#!/usr/bin/env python3
"""Convert fm20_role_attribute_weights_v2.csv to a JSON config file.

The JSON uses the same role keys as catalogue.json so the weight data
can be directly looked up when building RoleDefinition objects.

STALE as of role_weights_v4: seven roles were split by position group
(wb_support -> wb_dl_dr_support / wb_wbl_wbr_support, and likewise for
wb_attack, dlp_support, bwm_support, ap_attack, winger_support,
winger_attack), so a key is now (role, duty, position group) and not just
(role, duty). ``CATALOGUE_ROLE_MAP`` below still emits the old two-part keys
and would therefore produce a file the catalogue no longer matches. Loading
such a file fails loudly (see ``catalogue._attributes_from_weights``) rather
than silently scoring those roles on flat fallback weights, but this
converter needs the position group threading through before it is used
again.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

CSV_PATH = Path(__file__).with_name("..") / "fm20_role_attribute_weights_v2.csv"
JSON_PATH = Path(__file__).with_name("..") / "src" / "fm_analytics" / "analytics" / "data" / "role_weights_v2.json"

# Explicit mapping from (CSV role name, duty) -> catalogue role key.
# Only entries that map to a catalogue role are included; the rest are
# roles that exist in the CSV but not in the current catalogue.
CATALOGUE_ROLE_MAP: dict[tuple[str, str], str | None] = {
    # Goalkeepers
    ("Goalkeeper", "Defend"): "gk_defend",
    ("Sweeper Keeper", "Defend"): "sk_defend",
    ("Sweeper Keeper", "Attack"): None,
    ("Sweeper Keeper", "Support"): None,
    # Centre-backs
    ("Central Defender", "Defend"): "cd_defend",
    ("Central Defender", "Cover"): "cd_cover",
    ("Central Defender", "Stopper"): None,
    ("Ball-Playing Defender", "Defend"): "bpd_defend",
    ("Ball-Playing Defender", "Cover"): None,
    ("Ball-Playing Defender", "Stopper"): None,
    ("No-Nonsense Centre-Back", "Defend"): None,
    ("No-Nonsense Centre-Back", "Cover"): None,
    ("No-Nonsense Centre-Back", "Stopper"): None,
    ("Libero", "Attack"): None,
    ("Libero", "Support"): None,
    # Full backs / wing backs
    ("Full Back", "Attack"): None,
    ("Full Back", "Defend"): None,
    ("Full Back", "Support"): "fb_support",
    ("No-Nonsense Full Back", "Defend"): None,
    ("Wing Back", "Attack"): "wb_attack",
    ("Wing Back", "Defend"): None,
    ("Wing Back", "Support"): "wb_support",
    ("Complete Wing Back", "Attack"): None,
    ("Complete Wing Back", "Support"): None,
    ("Inverted Wing Back", "Attack"): None,
    ("Inverted Wing Back", "Defend"): None,
    ("Inverted Wing Back", "Support"): None,
    # Defensive midfield
    ("Defensive Midfielder", "Defend"): "dm_defend",
    ("Defensive Midfielder", "Support"): "dm_support",
    ("Anchor Man", "Defend"): None,
    ("Half Back", "Defend"): None,
    ("Regista", "Support"): None,
    ("Segundo Volante", "Attack"): None,
    ("Segundo Volante", "Support"): None,
    ("Ball-Winning Midfielder", "Defend"): None,
    ("Ball-Winning Midfielder", "Support"): "bwm_support",
    ("Deep-Lying Playmaker", "Defend"): None,
    ("Deep-Lying Playmaker", "Support"): "dlp_support",
    ("Roaming Playmaker", "Support"): None,
    # Central midfield
    ("Central Midfielder", "Defend"): "cm_defend",
    ("Central Midfielder", "Support"): "cm_support",
    ("Central Midfielder", "Attack"): None,
    ("Box-to-Box Midfielder", "Support"): "b2b_support",
    ("Mezzala", "Attack"): "mez_attack",
    ("Mezzala", "Support"): None,
    ("Carrilero", "Support"): None,
    ("Wide Midfielder", "Defend"): None,
    ("Wide Midfielder", "Support"): "wm_support",
    ("Wide Midfielder", "Attack"): None,
    ("Wide Playmaker", "Attack"): None,
    ("Wide Playmaker", "Support"): None,
    ("Defensive Winger", "Defend"): None,
    ("Defensive Winger", "Support"): None,
    # Attacking midfield
    ("Attacking Midfielder", "Attack"): None,
    ("Attacking Midfielder", "Support"): "am_support",
    ("Advanced Playmaker", "Attack"): "ap_attack",
    ("Advanced Playmaker", "Support"): None,
    ("Shadow Striker", "Attack"): "ss_attack",
    ("Enganche", "Support"): None,
    ("Trequartista", "Attack"): None,
    ("Inside Forward", "Attack"): "if_attack",
    ("Inside Forward", "Support"): None,
    ("Inverted Winger", "Attack"): None,
    ("Inverted Winger", "Support"): None,
    ("Raumdeuter", "Attack"): None,
    ("Winger", "Attack"): "winger_attack",
    ("Winger", "Support"): "winger_support",
    # Strikers
    ("Advanced Forward", "Attack"): "af_attack",
    ("Deep-Lying Forward", "Attack"): None,
    ("Deep-Lying Forward", "Support"): "dlf_support",
    ("Complete Forward", "Attack"): None,
    ("Complete Forward", "Support"): "cf_support",
    ("Poacher", "Attack"): "p_attack",
    ("Target Man", "Attack"): "tm_attack",
    ("Target Man", "Support"): None,
    ("Pressing Forward", "Attack"): None,
    ("Pressing Forward", "Defend"): None,
    ("Pressing Forward", "Support"): None,
    ("False Nine", "Support"): None,
    ("Wide Target Man", "Attack"): None,
    ("Wide Target Man", "Support"): None,
}


def _camel_case(name: str) -> str:
    """Convert space-separated attribute name to camelCase.

    'Off The Ball' -> 'offTheBall'
    'Aerial Reach' -> 'aerialReach'
    'One on Ones' -> 'oneOnOnes'
    """
    parts = name.strip().split()
    if not parts:
        return name
    return parts[0].lower() + "".join(word.capitalize() for word in parts[1:])


def main() -> None:
    roles: dict[str, dict] = {}
    skipped = 0
    versions: set[str] = set()

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            versions.add(row["model_version"])
            duty = row["duty"]
            role = row["role"]
            cat_key = CATALOGUE_ROLE_MAP.get((role, duty))

            if cat_key is None:
                skipped += 1
                continue

            attr_key = _camel_case(row["attribute"])

            if cat_key not in roles:
                roles[cat_key] = {
                    "positionGroup": row["position_group"],
                    "csvRole": role,
                    "duty": duty,
                    "attributes": {},
                }

            effective_weight = int(row["effective_weight"])
            duty_modifier = int(row["duty_modifier"])
            weight_tier = row["weight_tier"]
            core_soft_floor_applies = row["core_soft_floor_applies"] == "yes"

            attr_config: dict = {
                "effectiveWeight": effective_weight,
                "dutyModifier": duty_modifier,
                "weightTier": weight_tier,
                "coreSoftFloorApplies": core_soft_floor_applies,
            }

            if core_soft_floor_applies:
                for col, json_key in [
                    ("soft_floor_if_attr_lt_6", "softFloorIfAttrLt6"),
                    ("soft_floor_if_attr_lt_8", "softFloorIfAttrLt8"),
                    ("soft_floor_if_attr_lt_10", "softFloorIfAttrLt10"),
                    ("normal_multiplier_if_attr_ge_10", "normalMultiplierIfAttrGe10"),
                ]:
                    val = row[col]
                    if val:
                        attr_config[json_key] = float(val)

            notes = row.get("notes", "").strip()
            if notes:
                attr_config["notes"] = notes

            roles[cat_key]["attributes"][attr_key] = attr_config

    if len(versions) != 1:
        raise SystemExit(f"CSV must carry exactly one model_version, found {sorted(versions)}")
    document = {
        "version": versions.pop(),
        "roles": roles,
    }

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(roles)} catalogue roles to {JSON_PATH}")
    print(f"Skipped {skipped} CSV rows (roles not in catalogue)")


if __name__ == "__main__":
    main()
