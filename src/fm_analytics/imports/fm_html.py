from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Mapping

from fm_analytics.domain import AttributeObservation, Visibility


FM20_ATTRIBUTE_HEADERS: Mapping[str, str] = {
    "1v1": "oneOnOnes",
    "Acc": "acceleration",
    "Aer": "aerialReach",
    "Agi": "agility",
    "Agg": "aggression",
    "Ant": "anticipation",
    "Bal": "balance",
    "Bra": "bravery",
    "Cmd": "commandOfArea",
    "Com": "communication",
    "Cmp": "composure",
    "Cnt": "concentration",
    "Cor": "corners",
    "Cro": "crossing",
    "Dec": "decisions",
    "Det": "determination",
    "Dri": "dribbling",
    "Fin": "finishing",
    "Fir": "firstTouch",
    "Fla": "flair",
    "Han": "handling",
    "Hea": "heading",
    "Jum": "jumpingReach",
    "Kic": "kicking",
    "Ldr": "leadership",
    "Lon": "longShots",
    "Mar": "marking",
    "Nat": "naturalFitness",
    "OtB": "offTheBall",
    "Pac": "pace",
    "Pas": "passing",
    "Pos": "positioning",
    "Ref": "reflexes",
    "Sta": "stamina",
    "Str": "strength",
    "Tck": "tackling",
    "Tea": "teamwork",
    "Tec": "technique",
    "Thr": "throwing",
    "TRO": "rushingOut",
    "Vis": "vision",
    "Wor": "workRate",
}

_UNKNOWN_CELLS = frozenset(("", "-", "–", "—", "?", "n/a"))
_RANGE_PATTERN = re.compile(r"^(\d{1,2})\s*[-–—]\s*(\d{1,2})$")
_POSITION_PATTERN = re.compile(
    r"^((?:GK|SW|D|WB|DM|M|AM|ST)(?:/(?:GK|SW|D|WB|DM|M|AM|ST))*)"
    r"(?:\s*\(([RLC]+)\))?$"
)


@dataclass(frozen=True)
class VisibleExportPlayer:
    id: str
    name: str
    positions: tuple[str, ...]
    attributes: Mapping[str, AttributeObservation]


@dataclass(frozen=True)
class FmHtmlExport:
    source: str
    headers: tuple[str, ...]
    players: tuple[VisibleExportPlayer, ...]


@dataclass(frozen=True)
class ExportCompleteness:
    expected_players: int
    imported_players: int

    @property
    def is_complete(self) -> bool:
        return self.expected_players == self.imported_players


def verify_export_completeness(
    export: FmHtmlExport,
    *,
    expected_players: int,
) -> ExportCompleteness:
    """Prove that a merged export contains the player count shown by FM."""
    if expected_players < 1:
        raise ValueError("expected FM player count must be at least 1")
    result = ExportCompleteness(
        expected_players=expected_players,
        imported_players=len(export.players),
    )
    if not result.is_complete:
        raise ValueError(
            "FM export is incomplete: "
            f"imported {result.imported_players} unique players but FM shows "
            f"{result.expected_players}"
        )
    return result


def merge_fm_html_exports(exports: tuple[FmHtmlExport, ...]) -> FmHtmlExport:
    if not exports:
        raise ValueError("at least one FM HTML export is required")

    players_by_id: dict[str, VisibleExportPlayer] = {}
    headers: list[str] = []
    for export in exports:
        if export.source != "fm20-ui-html":
            raise ValueError(f"unsupported FM export source {export.source!r}")
        headers.extend(header for header in export.headers if header not in headers)
        for player in export.players:
            existing = players_by_id.get(player.id)
            if existing is not None and existing != player:
                raise ValueError(
                    f"conflicting rows found for exported player UID {player.id!r}"
                )
            players_by_id[player.id] = player

    return FmHtmlExport(
        source="fm20-ui-html",
        headers=tuple(headers),
        players=tuple(players_by_id.values()),
    )


def parse_attribute_cell(value: str) -> AttributeObservation:
    text = _cell_text(value)
    if text.casefold() in _UNKNOWN_CELLS:
        return AttributeObservation(visibility=Visibility.UNKNOWN)
    if text.isdecimal():
        number = int(text)
        _validate_attribute_value(number)
        return AttributeObservation(visibility=Visibility.KNOWN, value=number)
    match = _RANGE_PATTERN.fullmatch(text)
    if match:
        minimum, maximum = (int(part) for part in match.groups())
        _validate_attribute_value(minimum)
        _validate_attribute_value(maximum)
        return AttributeObservation(
            visibility=Visibility.RANGE,
            minimum=minimum,
            maximum=maximum,
        )
    raise ValueError(f"unsupported visible attribute cell {value!r}")


def parse_fm_html_export(
    html: str,
    *,
    attribute_headers: Mapping[str, str] = FM20_ATTRIBUTE_HEADERS,
) -> FmHtmlExport:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    headers, rows = _select_player_table(parser.tables)

    normalized_headers = tuple(_cell_text(header) for header in headers)
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ValueError("FM export column headers must be unique")
    header_indexes = {
        header.casefold(): index for index, header in enumerate(normalized_headers)
    }
    uid_index = _required_header(header_indexes, "UID")
    name_index = _required_header(header_indexes, "Name")
    position_index = _required_header(header_indexes, "Position")
    attribute_indexes = tuple(
        (
            header_indexes[header.casefold()],
            canonical_name,
        )
        for header, canonical_name in attribute_headers.items()
        if header.casefold() in header_indexes
    )
    if not attribute_indexes:
        raise ValueError("FM export contains no recognized attribute columns")

    players: list[VisibleExportPlayer] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        if len(row) != len(normalized_headers):
            raise ValueError(
                f"FM export row {row_number} has {len(row)} cells; "
                f"expected {len(normalized_headers)}"
            )
        player_id = _cell_text(row[uid_index])
        name = _cell_text(row[name_index])
        if not player_id or not name:
            raise ValueError(f"FM export row {row_number} requires UID and Name")
        if player_id in seen_ids:
            raise ValueError(f"FM export contains duplicate UID {player_id!r}")
        seen_ids.add(player_id)
        players.append(
            VisibleExportPlayer(
                id=player_id,
                name=name,
                positions=parse_positions(row[position_index]),
                attributes={
                    canonical_name: parse_attribute_cell(row[index])
                    for index, canonical_name in attribute_indexes
                },
            )
        )

    if not players:
        raise ValueError("FM export contains no player rows")
    return FmHtmlExport(
        source="fm20-ui-html",
        headers=normalized_headers,
        players=tuple(players),
    )


def parse_positions(value: str) -> tuple[str, ...]:
    positions: list[str] = []
    for part in (_cell_text(item) for item in value.split(",")):
        match = _POSITION_PATTERN.fullmatch(part)
        if not match:
            raise ValueError(f"unsupported FM position cell {value!r}")
        areas, sides = match.groups()
        for area in areas.split("/"):
            if area in {"GK", "SW", "DM"}:
                positions.append(area)
            elif area == "ST" and sides in {None, "C"}:
                positions.append("ST")
            elif sides:
                positions.extend(f"{area}{side}" for side in sides)
            else:
                raise ValueError(f"unsupported FM position cell {value!r}")
    if not positions:
        raise ValueError("FM position cell must not be empty")
    return tuple(dict.fromkeys(positions))


def _validate_attribute_value(value: int) -> None:
    if not 1 <= value <= 20:
        raise ValueError("visible player attribute must be between 1 and 20")


def _cell_text(value: str) -> str:
    return " ".join(value.split())


def _required_header(indexes: Mapping[str, int], name: str) -> int:
    try:
        return indexes[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"FM export requires a {name!r} column") from exc


def _select_player_table(
    tables: tuple[tuple[tuple[str, ...], ...], ...]
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    for table in tables:
        if not table:
            continue
        headers = table[0]
        normalized = {_cell_text(header).casefold() for header in headers}
        if {"uid", "name", "position"}.issubset(normalized):
            return headers, table[1:]
    raise ValueError("no FM player table with UID, Name, and Position was found")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: tuple[tuple[tuple[str, ...], ...], ...] = ()
        self._tables: list[list[tuple[str, ...]]] = []
        self._table: list[tuple[str, ...]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        tag = tag.casefold()
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"th", "td"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append("".join(self._cell_parts))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            assert self._table is not None
            if self._row:
                self._table.append(tuple(self._row))
            self._row = None
        elif tag == "table" and self._table is not None:
            self._tables.append(self._table)
            self._table = None
            self.tables = tuple(tuple(table) for table in self._tables)
