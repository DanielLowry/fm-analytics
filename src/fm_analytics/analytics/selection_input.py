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

    exported_by_id = {player.id: player for player in export.players}
    squad_ids = [player.id for player in squad.players]
    if len(squad_ids) != len(set(squad_ids)):
        raise ValueError("squad player ids must be unique")
    missing = [player.id for player in squad.players if player.id not in exported_by_id]
    if missing:
        raise ValueError(
            f"manager-visible squad export is missing player UIDs {missing!r}"
        )

    merged_players = []
    for player in squad.players:
        exported = exported_by_id[player.id]
        if _normalized_name(player.name) != _normalized_name(exported.name):
            raise ValueError(
                f"player UID {player.id!r} has conflicting names "
                f"{player.name!r} and {exported.name!r}"
            )
        merged_players.append(
            replace(
                player,
                positions=exported.positions,
                attributes=exported.attributes,
            )
        )

    squad_id_set = set(squad_ids)
    extras = tuple(
        player.id for player in export.players if player.id not in squad_id_set
    )
    return SquadAttributeMerge(
        squad=replace(squad, players=tuple(merged_players)),
        matched_players=len(merged_players),
        extra_export_player_ids=extras,
    )


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()
