"""The Contracts page, and the contract panel on a squad player's report.

Both read `reporting.build_contract_review` over the cached recommendation
bundle and the recorded match history; nothing here computes a verdict.
"""

from __future__ import annotations

from http import HTTPStatus

from fm_analytics.analytics.contract_planning import ContractReview
from fm_analytics.reporting import build_contract_review
from fm_analytics.web.contract_render import contract_panel, contracts_body
from fm_analytics.web.rendering import _layout, _options, _query_first

_SCOPES = (("first", "First team"), ("all", "All club squads"))


class ContractPagesMixin:
    def _match_history_or_none(self):
        """The recorded history, or None when it is switched off or unreadable.

        Form is optional evidence: a history that cannot be read leaves every
        player without match evidence rather than failing the page.
        """
        try:
            return self.server.match_history()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - see the docstring
            return None

    def _contracts_page(self, path: str, query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Contracts")  # type: ignore[attr-defined]
        if bundle is None:
            return
        scope = _query_first(query, "team") or "first"
        if scope not in dict(_SCOPES):
            self._send(  # type: ignore[attr-defined]
                _layout("Contracts", path, "<p class='error'>Choose the first team or all club squads.</p>"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        include_others = scope == "all" and bool(bundle.squad.other_teams)
        review = build_contract_review(
            bundle, self._match_history_or_none(), include_other_squads=include_others
        )
        scope_form = (
            "<form class='filters fm-contract-scope' method='get' action='/contracts'>"
            "<label>Squad<select name='team'>" + _options(_SCOPES, scope, "") + "</select></label>"
            "<button type='submit'>Show</button></form>"
            if bundle.squad.other_teams
            else ""
        )
        self._send(  # type: ignore[attr-defined]
            _layout("Contracts", path, contracts_body(review, scope_form, show_squad=include_others), wide=True)
        )

    def _contract_panel_for(self, player_id: str) -> str:
        """The player's contract plan for his report, or nothing when it cannot be computed.

        Never raises: the player report must still render when the squad cannot
        be scored (incomplete attributes) or the bundle fails for any reason.
        """
        try:
            bundle = self.server.bundle()  # type: ignore[attr-defined]
            in_first_team = any(player.id == player_id for player in bundle.squad.players)
            review: ContractReview = build_contract_review(
                bundle, self._match_history_or_none(), include_other_squads=not in_first_team
            )
        except Exception:  # noqa: BLE001 - see the docstring
            return ""
        item = review.for_player(player_id)
        return contract_panel(item, review) if item is not None else ""
