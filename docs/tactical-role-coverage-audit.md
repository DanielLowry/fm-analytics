# Tactical role coverage audit

Status: **Role-coverage delivery complete.** This records the catalogue audit undertaken
in September 2026 and the expansion work it recommends. It complements the
[tactical model upgrade plan](tactical-model-upgrade-plan.md): that document
describes the model and its calibration; this one focuses on whether every
role the model can score has a meaningful tactical home.

## Objective

The tactic catalogue should help a manager make use of distinctive players.
It is not enough for the Squad and Roles pages to identify a player as a good
Carrilero or Wide Playmaker if no recommended tactic can select that role.
The aim is therefore catalogue-wide coverage of permitted roles, with each
role appearing in a tactic whose instructions, balance requirements,
attribute emphasis and (where it matters) attribute taper tell the same
football story.

This does **not** mean opening every slot to every role. Roles whose system
traits differ materially change the identity of the tactic, so they deserve
their own template or deliberately authored variant rather than a broad
alternate-role list.

## Baseline findings

The audit started from 42 tactics and 84 roles. The role coverage below counts
roles used as a tactic slot's default; alternates are not treated as complete
coverage because the default template is what expresses the tactic's intended
identity.

| Position group | Default-used | Total | Finding |
| --- | ---: | ---: | --- |
| GK | 2 | 2 | Complete |
| DL/DR | 12 | 12 | Complete |
| WBL/WBR | 2 | 2 | Complete |
| DM | 4 | 4 | Complete |
| AMC | 7 | 7 | Complete |
| AML/AMR | 12 | 12 | Complete |
| ST | 13 | 13 | Complete |
| MC | 8 | 14 | Six role gap |
| ML/MR | 3 | 9 | Six role gap |
| DC | 3 | 9 | Six role gap |

AMC is not a coverage problem. The catalogue already has appropriate homes
for Enganche, Trequartista, Shadow Striker, AM(A/S), and AP(A/S). In
particular, specialist roles are not being hidden behind generic AMC
alternatives: `enganche_4231`, `trequartista_4312`, `gegenpress_4231`,
`complete_wingback_4231`, and `raumdeuter_counter_4231` each give one a
specific tactical context.

The 18 roles missing from default tactic slots at the start of the audit were:

- **MC:** `dlp_mc_defend`, `ap_mc_support`, `rpm_mc_support`,
  `bwm_mc_defend`, `mez_support`, `car_mc_support`.
- **ML/MR:** `dw_defend`, `dw_support`, `wp_support`, `wp_attack`,
  `iw_ml_mr_support`, `iw_ml_mr_attack`.
- **DC:** `cd_stopper`, `bpd_stopper`, `bpd_cover`, `nncb_defend`,
  `nncb_stopper`, `nncb_cover`.

Every shipped default role version met its declared system requirements and
instruction demands, except `possession_4141`'s default DLF(S) version, which
supplied box presence 1.4 against `Work Ball Into Box`'s 1.5 demand. Its
existing CF(S) alternate meets that demand. This is a small calibration issue,
not a reason to discard the tactic.

## Existing-template opportunities

These are opportunities for distinct variants, not evidence that the current
templates are invalid:

- `inverted_wingback_433` can gain an asymmetric Carrilero version. A
  Carrilero is a better channel protector than generic CM(S) beside an
  inverted full-back.
- `pressing_442` can gain a Defensive Winger variant for squads whose best
  wide worker is genuinely a pressing/defensive player rather than a WM(S).
- `solid_4231` uses no-nonsense full-backs but ordinary central defenders.
  A low-block No-Nonsense CB variant would make that identity consistent.
- `control_possession_4231` merits a patient AP(S) counterpart to its AP(A)
  version: Lower Tempo and Hold Shape should be able to find a controller who
  creates without being selected chiefly as an extra box runner.
- `wide_playmakers_433` correctly uses creative AML/AMR roles, but cannot
  expose the distinct ML/MR Wide Playmaker roles. They need a flat-midfield
  formation, not a rename of this tactic.

## Attribute adjustments

All baseline tactics have `attributeEmphasis`, but only four had an
`attributeTaper`: `balanced_41212_diamond`, `positive_4312_narrow`,
`trequartista_4312`, and `vertical_442`.

Emphasis should remain a soft differentiator. Tapers should be used when a
role-led system genuinely breaks down below an attribute level: passing and
vision for a wide playmaker, stamina for a roaming playmaker, or pace and
anticipation for a stopper/cover high line. They should normally be scoped to
the relevant position group and calibrated using the existing taper policy;
they are not hard selection floors. Balanced fallback systems should not
acquire arbitrary tapers simply because the mechanism exists.

## Delivery completed

Phase 1 adds three templates that create meaningful homes for eight missing
roles, rather than merely adding labels:

1. **Positional Play 4-3-3** — DLP(D), Carrilero(S), Mezzala(S). It uses
   positional roles to create a stable passing structure and tapers the
   technical/core midfield requirements.
2. **Wide Creator 4-4-2** — Defensive Winger(S) and Wide Playmaker(A). It
   makes a flat-wide creator and a wide defensive worker selectable together,
   with separate tapers for their distinct jobs.
3. **No-Nonsense 5-3-2** — the three No-Nonsense Centre-Back duties. It is
   deliberately a direct, deep defensive alternative, not a ball-playing
   duplication of the existing 5-3-2.

Phase 2 completed the remaining coverage work:

4. **Roaming Playmaker 4-3-3** — BWM(D), RPM(S), AP(S). The two creators
   are balanced by a genuine defensive ball-winner, with technical and
   stamina tapers across midfield.
5. **Inverted Wide 4-4-2** — DW(D) and IW(A). One flank stays secure while
   the other has an overlapping wing-back and an inverted runner.
6. **Wide Control 4-1-4-1** — WP(S) and IW(S). This is a controlled
   possession home for genuine flat-wide creators rather than AML/AMR
   approximations.
7. **Aggressive Playing 3-4-3** — BPD(Stopper) and BPD(Cover). The
   stopper-and-cover pairing is legal and purpose-built for a high line.
8. **Front-Foot 4-4-2** — CD(Stopper). It pairs the stopper with a Cover
   defender behind a two-forward press.

The catalogue now contains 50 tactics and **every one of the 84 permitted
roles appears as a tactic default**. The two stopper types intentionally sit
in separate tactics: the exclusion groups prohibit two stopper centre-backs
in the same XI, which is football-correct as well as a catalogue invariant.

## Further expansion

Further additions should be driven by a distinct player-search outcome, not
coverage for its own sake. The existing-template opportunities above remain
good candidates, especially a patient AP(S) possession 4-2-3-1 and an
asymmetric Carrilero inverted-wing-back 4-3-3.

Every addition must pass the shared-scale calibration tests, document its role
rationale and instructions, and regenerate `docs/tactic-catalogue.md`.
