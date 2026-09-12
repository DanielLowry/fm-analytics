from __future__ import annotations

from dataclasses import dataclass, replace

from fm_analytics.domain import Squad
from fm_analytics.imports import FmHtmlExport


@dataclass(frozen=True)
class SquadAttributeMerge:
    squad: Squad
    matched_players: int
    extra_export_player_ids: tuple[str, ...]


def overlay_squad_export(squad: Squad, export: FmHtmlExport) -> SquadAttributeMerge:
    """Combine live readiness with manager-visible HTML positions/attributes."""

    squad_ids = [player.id for player in squad.players]
    if len(squad_ids) != len(set(squad_ids)):
        raise ValueError("squad player ids must be unique")
    if export.source == "fm20-ui-html-squad-name":
        squad_names = [_normalized_name(player.name) for player in squad.players]
        if len(squad_names) != len(set(squad_names)):
            raise ValueError(
                "live squad contains duplicate normalized names; "
                "name-only HTML identity is unsafe"
            )
        exported = {
            _normalized_name(player.name): player for player in export.players
        }
        missing = [
            player.name
            for player in squad.players
            if _normalized_name(player.name) not in exported
        ]
        exported_for_player = {
            player.id: exported[_normalized_name(player.name)]
            for player in squad.players
            if _normalized_name(player.name) in exported
        }
        squad_name_set = set(squad_names)
        extras = tuple(
            player.name
            for player in export.players
            if _normalized_name(player.name) not in squad_name_set
        )
    elif export.source == "fm20-ui-html":
        exported = {player.id: player for player in export.players}
        missing = [player.id for player in squad.players if player.id not in exported]
        exported_for_player = {
            player.id: exported[player.id]
            for player in squad.players
            if player.id in exported
        }
        squad_id_set = set(squad_ids)
        extras = tuple(
            player.id for player in export.players if player.id not in squad_id_set
        )
    else:
        raise ValueError(f"unsupported squad export source {export.source!r}")
    if missing:
        raise ValueError(
            f"manager-visible squad export is missing players {missing!r}"
        )

    merged_players = []
    for player in squad.players:
        exported_player = exported_for_player[player.id]
        if _normalized_name(player.name) != _normalized_name(exported_player.name):
            raise ValueError(
                f"player UID {player.id!r} has conflicting names "
                f"{player.name!r} and {exported_player.name!r}"
            )
        merged_players.append(
            replace(
                player,
                positions=exported_player.positions or player.positions,
                attributes=exported_player.attributes,
            )
        )

    return SquadAttributeMerge(
        squad=replace(squad, players=tuple(merged_players)),
        matched_players=len(merged_players),
        extra_export_player_ids=extras,
    )


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()
