# Phase 01 — Production-shaped extraction API

## Outcome

Replace the Phase 00 spike with a small, versioned, testable FMBridge service
that supplies the current squad observations needed by the MVP without leaking
probe/framework types or putting football decisions in the bridge.

## Prerequisites

- Phase 00 exit criteria met on a recorded FM20 environment
- Known rules for reacquiring live objects after the game advances
- Sanitized examples of game and squad responses

## Subphases

| ID | Subphase | Status | Result |
| --- | --- | --- | --- |
| 01.1 | [Contract and versioning](01.1-contract-and-versioning.md) | Complete | Versioned paths, published v1 semantics, strict decoding, and shared golden resources implemented |
| 01.2 | [Source lifecycle](01.2-source-lifecycle.md) | In progress | Automated cache refresh and failure recovery covered; live advancement/membership soak remains |
| 01.3 | [Core resources](01.3-core-resources.md) | Planned | Deliberately scoped game, club, player, squad, and fixture endpoints |
| 01.4 | [Reliability and diagnostics](01.4-reliability-and-diagnostics.md) | Planned | Bounded requests and actionable operational status |
| 01.5 | [Contract verification](01.5-contract-verification.md) | Planned | Automated producer/consumer compatibility evidence |

## Current starting point

01.1 has frozen the existing `/health`, `/game`, and `/squad` behavior into an
explicit versioned contract and sanitized golden fixtures. The
[MVP squad-input inventory](mvp-squad-inputs.md) records what is proven live and
what remains blocked on visibility research.

Work now moves to 01.2, beginning with the deferred date-advance and temporary
squad-membership-change soak check. External-player enumeration does not begin
here; it remains gated by the Phase 03 discoverability research.

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
- The contract can represent the squad inputs required by the MVP—positions,
  availability, condition, match sharpness, and attribute observations—even
  where live mappings remain deliberately unavailable pending Phase 03 proof.

## Non-goals

- Historical persistence
- Role scoring or other football logic
- Exposing every object available in the extraction framework
- Enumerating external players before Phase 03 proves entity discoverability
- Remote/network deployment; FMBridge remains local-only
