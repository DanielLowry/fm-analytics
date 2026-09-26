# Set-piece optimizer

The Set pieces screen is a match-plan builder, not a collection of independent
player rankings. When the role-scoring feed is complete it uses the exact XI
from the selected tactic. On a partial snapshot it remains available as a
clearly labelled squad-wide template.

## What it produces

- left- and right-side orders for corners, direct free kicks, and indirect
  free kicks;
- a penalty order and, when the dedicated rating is present, a long-throw
  order;
- attacking corner and attacking wide-free-kick routines from both sides;
- defensive corner and defensive wide-free-kick routines;
- one named player, FM instruction, field zone, purpose, score, and strongest
  visible inputs for every routine job; and
- secure, balanced, and aggressive attacking commitments with three, two, or
  one rest-defence jobs respectively.

Each routine is solved as one exact assignment. A player can fill only one job,
so the taker cannot also be placed in the box and the same aerial specialist
cannot occupy the near, central, and far-post zones. The objective maximizes
the sum of the job-specific visible-attribute scores, with the existing small
preferred-foot bonus applied to side-specific delivery.

## Evidence boundary

The model uses only `Player.attributes`, availability, positions, and verified
preferred foot. Unknown observations stay at the current-ranking floor and
retain their uncertainty range.

`freeKickTaking`, `penaltyTaking`, and `longThrows` are recognized from custom
FM HTML views (`Fre`, `Pen`, and `L Th`). If present, the first two replace their
fallback proxy profile and the UI labels the result **Dedicated rating**. The
live FM20 reader still lacks verified offsets/display IDs for these fields:

- direct and indirect free kicks fall back to transparent technical profiles;
- penalties fall back to finishing, composure, and technique; and
- long throws are withheld rather than inferred from unrelated attributes.

This is source coverage, not unfinished optimizer behavior. Adding verified
live-reader mappings later will activate the dedicated scoring path without a
set-piece model or UI change.

## Interpretation

The weights are reviewable football hypotheses, not reverse-engineered match
engine coefficients, and the 0–100 values are comparisons rather than expected
goal probabilities. Opponent-specific aerial matchups are not inferred: the
manager should still move the primary and secondary markers onto the actual
opposition threats in FM.
