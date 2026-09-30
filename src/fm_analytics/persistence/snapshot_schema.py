"""SQLite schema for immutable squad captures."""

SCHEMA = """
CREATE TABLE captures (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    contract_version TEXT NOT NULL,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    game_date TEXT NOT NULL,
    manager_id TEXT NOT NULL,
    manager_name TEXT NOT NULL,
    controlled_club_id TEXT,
    controlled_club_name TEXT,
    squad_club_id TEXT,
    squad_club_name TEXT,
    CHECK ((controlled_club_id IS NULL) = (controlled_club_name IS NULL)),
    CHECK ((squad_club_id IS NULL) = (squad_club_name IS NULL))
);

CREATE TABLE squad_players (
    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    player_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    -- NULL is the first team (Squad.players); any other value is FM's own
    -- raw team-type marker for one of the club's other squads
    -- (Squad.other_teams), never 0, which is reserved for the first team.
    team_marker INTEGER CHECK (team_marker IS NULL OR team_marker <> 0),
    name TEXT NOT NULL,
    date_of_birth TEXT,
    age INTEGER CHECK (age IS NULL OR age >= 0),
    club_id TEXT NOT NULL,
    condition_percent INTEGER CHECK (
        condition_percent IS NULL OR condition_percent BETWEEN 0 AND 100
    ),
    match_fitness_percent INTEGER CHECK (
        match_fitness_percent IS NULL OR match_fitness_percent BETWEEN 0 AND 100
    ),
    availability TEXT NOT NULL,
    injured INTEGER CHECK (injured IS NULL OR injured IN (0, 1)),
    suspended INTEGER CHECK (suspended IS NULL OR suspended IN (0, 1)),
    preferred_foot TEXT,
    contract_present INTEGER NOT NULL CHECK (contract_present IN (0, 1)),
    contract_type TEXT,
    contract_start_date TEXT,
    contract_end_date TEXT,
    contract_joined_date TEXT,
    squad_status TEXT,
    transfer_status TEXT,
    contracted_club_id TEXT,
    contracted_club_name TEXT,
    PRIMARY KEY (capture_id, player_id),
    UNIQUE (capture_id, ordinal),
    CHECK ((contracted_club_id IS NULL) = (contracted_club_name IS NULL))
);

CREATE TABLE player_positions (
    capture_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    position TEXT NOT NULL,
    PRIMARY KEY (capture_id, player_id, ordinal),
    FOREIGN KEY (capture_id, player_id)
        REFERENCES squad_players(capture_id, player_id) ON DELETE CASCADE
);

CREATE TABLE player_position_familiarity (
    capture_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    position TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 20),
    PRIMARY KEY (capture_id, player_id, position),
    FOREIGN KEY (capture_id, player_id)
        REFERENCES squad_players(capture_id, player_id) ON DELETE CASCADE
);

CREATE TABLE player_attributes (
    capture_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('known', 'range', 'unknown')),
    value INTEGER,
    minimum INTEGER,
    maximum INTEGER,
    PRIMARY KEY (capture_id, player_id, name),
    FOREIGN KEY (capture_id, player_id)
        REFERENCES squad_players(capture_id, player_id) ON DELETE CASCADE,
    CHECK (
        (visibility = 'known' AND value IS NOT NULL
            AND minimum IS NULL AND maximum IS NULL)
        OR
        (visibility = 'range' AND value IS NULL
            AND minimum IS NOT NULL AND maximum IS NOT NULL
            AND minimum <= maximum)
        OR
        (visibility = 'unknown' AND value IS NULL
            AND minimum IS NULL AND maximum IS NULL)
    )
);
"""
