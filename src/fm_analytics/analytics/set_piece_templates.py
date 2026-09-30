"""Names and tactical intent for the set-piece routine catalogue."""

FREE_KICK_TYPE_TABS = (
    ("direct_free_kick", "Direct"),
    ("direct_small_chance", "Direct (small chance of shot)"),
    ("indirect_wide", "Indirect (wide)"),
    ("indirect_deep", "Indirect (deep)"),
)

ATTACKING_ROUTINE_TEMPLATES = (
    (
        "corner", "Attacking corner",
        "Create separated first-contact, second-ball and transition responsibilities.",
        "Keep the delivery choice aligned with the selected curve.",
    ),
    (
        "direct_free_kick", "Direct free kick",
        "Prioritise the shot, wall-side rebounds and protection against the counter.",
        "The taker is selected from the direct-free-kick ranking.",
    ),
    (
        "direct_small_chance", "Direct free kick (small chance of shot)",
        "Retain a shooting threat while preparing near-, far- and edge-of-area runs.",
        "Use the shot as a disguise; the role mix expects a delivery more often.",
    ),
    (
        "indirect_wide", "Indirect free kick (wide)",
        "Attack the near post, far post and edge from a wide delivery angle.",
        "The near- and far-post runners are the primary delivery targets.",
    ),
    (
        "indirect_deep", "Indirect free kick (deep)",
        "Send runners from deeper starting positions without losing counter cover.",
        "The deeper ball favours forward runners over a second player with the taker.",
    ),
)

DEFENDING_FREE_KICK_TEMPLATES = (
    (
        "direct_free_kick", "Direct free kicks",
        "Build the strongest wall, protect rebounds and retain one counter outlet.",
        "Five wall players reflect the immediate shooting threat.",
    ),
    (
        "direct_small_chance", "Direct free kicks (small chance of shot)",
        "Respect the shot while adding marking cover for a probable delivery.",
        "Four wall players balance the reduced shot threat against extra runners.",
    ),
    (
        "indirect_wide", "Indirect free kicks (wide)",
        "Protect delivery lanes, track runners and keep one counter outlet.",
        "Three wall players protect the near shooting route without crowding the box.",
    ),
    (
        "indirect_deep", "Indirect free kicks (deep)",
        "Prioritise marking and aerial cover against a deep delivery.",
        "No wall is used because the routine is outside realistic shooting range.",
    ),
)
