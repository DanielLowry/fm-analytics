# Project documentation

- [Initial plan](initial_plan.md) records the original project vision and broad
  capability sequence.
- [Early-game MVP](mvp.md) defines the first useful product outcome and its
  acceptance criteria.
- [Architecture](architecture.md) describes the current Python HTTP boundary.
- [Decision-support design](decision-support-design.md) takes a whole-system
  view of the five manager questions, the field-resolution seam, and the
  sequence for getting there.
- [Field-acquisition workbench](field-acquisition-workbench.md) explains how
  visible FM facts become screen-independent, validated sources.
- [Property-discovery playbook](property-discovery-playbook.md) is the worked
  method behind the first extracted field: read FM's own code to find its keyed
  property getter, then let Frida run it on FM's own thread.
- [Frida and player discoverability](frida-discoverability.md) records the
  current Player Search evidence, the distinction between observed and
  screen-independent discovery, and the remaining validation gates.
- [Research automation strategy](research-automation.md) defines the replay,
  persistent-instrumentation, experiment, trace-store, UI-oracle, and semantic-
  registry programme intended to remove repeated operator-led FM sessions.
- [Research catalogue](../research/README.md) is the machine-queryable semantic
  registry and reusable-capture inventory used by that programme.
- [Documentation archive](archive/README.md) preserves superseded research
  runbooks that are no longer instructions to execute.
- [FMBridge contract v1](contracts/v1.md) defines the current versioned resource
  and error semantics.
- [Delivery roadmap](phases/README.md) is the working plan, with phase gates,
  subphases, exit criteria, and intentional deferrals.

When implementation evidence changes an assumption, update the relevant phase
document first and then reconcile the architecture or original plan if the
change is fundamental.
