# Phase 01 — Production-shaped extraction API

## Outcome

Replace the Phase 00 spike with a small, versioned, testable FMBridge service
that exposes current manager-visible state without leaking framework types or
putting football decisions in C#.

## Prerequisites

- Phase 00 exit criteria met on a recorded FM20 environment
- Known rules for reacquiring live objects after the game advances
- Sanitized examples of game and squad responses

## Subphases

| ID | Subphase | Result |
| --- | --- | --- |
| 01.1 | [Contract and versioning](01.1-contract-and-versioning.md) | A documented, compatibility-tested wire contract |
| 01.2 | [Source lifecycle](01.2-source-lifecycle.md) | Reliable live and fixture data sources |
| 01.3 | [Core resources](01.3-core-resources.md) | Deliberately scoped game, club, player, squad, and fixture endpoints |
| 01.4 | [Reliability and diagnostics](01.4-reliability-and-diagnostics.md) | Bounded requests and actionable operational status |
| 01.5 | [Contract verification](01.5-contract-verification.md) | Automated C#/Python compatibility evidence |

## Phase exit criteria

- The Python client can use either the fixture or live bridge through the same
  domain interface.
- The API has an explicit versioning and compatibility policy.
- Responses contain only allowlisted DTO fields.
- Source-not-ready, unsupported-build, timeout, and internal-error cases are
  distinct and documented.
- Sanitized contract fixtures and automated consumer tests cover every public
  response shape.
- Repeated polling while the game advances does not leak resources or serve
  internally inconsistent responses.

## Non-goals

- Historical persistence
- Role scoring or other football logic
- Exposing every object available in the extraction framework
- Remote/network deployment; FMBridge remains local-only

