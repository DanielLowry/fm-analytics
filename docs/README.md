# Project documentation

## Start here

- [Early-game MVP](mvp.md) defines the current product boundary and acceptance
  criteria.
- [Architecture](architecture.md) describes the current application and data
  boundaries.
- [Application improvement review](app-improvement-review.md) is the active
  performance, integration, and product-polish backlog.
- [Analytics performance investigation](analytics-performance.md) is the
  current measured cost model and records the package, vectorisation, and
  process-parallel experiments for tactic ranking.
- [Delivery roadmap](phases/README.md) tracks capability gates, evidence, and
  intentional deferrals.
- [Tactical-system roadmap](tactical-system-roadmap.md) tracks deliberate
  changes to the football model rather than application polish.
- [Tactic catalogue](tactic-catalogue.md) is the generated one-page index of
  every tactic: shape, roles by line, the attributes it leans on and what it
  needs. Per-tactic detail lives in the tactic's own data file.
- [Tactical model upgrade plan](tactical-model-upgrade-plan.md) covers the
  catalogue audit, per-tactic attribute weighting and opponent-aware tactic
  selection. Its catalogue, justification, emphasis and taper work is **built**;
  the opponent is built in analytics but has no UI yet. Read its §2–§2k "as
  built" sections for current behaviour, and §2k for the counts and timings in
  the older sections that have since drifted.

## Current operating and research references

- [Field-acquisition workbench](field-acquisition-workbench.md) explains how
  visible FM facts become screen-independent, validated sources.
- [Property-discovery playbook](property-discovery-playbook.md) documents the
  reusable property-discovery method.
- [Frida and player discoverability](frida-discoverability.md) records current
  Player Search evidence and remaining validation gates.
- [Scouting workspace](scouting-workspace.md) documents the visibility-aware
  recruitment page and candidate-feed contract.
- [Research automation strategy](research-automation.md) defines the research
  automation programme.
- [Research catalogue](../research/README.md) indexes semantic registry facts
  and reusable captures.
- [FMBridge contract v1](contracts/v1.md) defines current resource and error
  semantics.

## Historical material

The [documentation archive](archive/README.md) contains completed proposals and
superseded runbooks. Archived documents are evidence and context, not current
instructions or backlog.

When implementation evidence changes an assumption, update the relevant phase
document and the current architecture or backlog. Do not keep completed plans
in the active index merely because their history is useful; archive them.
