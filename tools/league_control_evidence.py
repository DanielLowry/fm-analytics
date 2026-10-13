"""Which kind of control goes with out-shooting weaker sides in our league?

Reads data/match-capture.json (read-only): every detailed league match, the
league table from FM's competition results, and each club's averages against
bottom-half opponents only. Prints rank correlations and a per-club table, and
writes the averages to data/exports/control-evidence.json. Used for
docs/control-tactics-plan.md.

Usage:  uv run python tools/league_control_evidence.py
"""
import json, collections, statistics as st
d = json.load(open('data/match-capture.json'))
LEAGUE = 'Vanarama National League South'
detail = {}
for m in d['clubMatches'] + d['matches']:
    if m.get('competition', {}).get('name') == LEAGUE and m.get('detail'):
        detail[(m['season'], m['date'], m['home']['id'], m['away']['id'])] = m
table = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0]))  # season -> club -> [pts, gd, played]
names = {}
for block in d['competitionResults']:
    if block['competition']['name'] != LEAGUE: continue
    for r in block['results']:
        s = r['season']; h, a = r['home']['id'], r['away']['id']
        names[h] = r['home']['name']; names[a] = r['away']['name']
        hg, ag = r['homeGoals'], r['awayGoals']
        for club, gf, ga in ((h, hg, ag), (a, ag, hg)):
            t = table[s][club]; t[2] += 1; t[1] += gf - ga
            t[0] += 3 if gf > ga else 1 if gf == ga else 0
half = {}
for s, clubs in table.items():
    ranked = sorted(clubs, key=lambda c: (-clubs[c][0], -clubs[c][1]))
    n = len(ranked)
    for i, c in enumerate(ranked): half[(s, c)] = ('top' if i < n // 2 else 'bottom', i + 1, n)
rows = collections.defaultdict(list)
for (s, date, h, a), m in detail.items():
    dh, da = m['detail']['home'], m['detail']['away']
    for club, opp, us, them, gf, ga in ((h, a, dh, da, m['homeGoals'], m['awayGoals']), (a, h, da, dh, m['awayGoals'], m['homeGoals'])):
        if half.get((s, opp), ('?',))[0] != 'bottom': continue
        pt = us['possession_time'] + them['possession_time']
        rows[(s, club)].append(dict(
            pts=3 if gf > ga else 1 if gf == ga else 0,
            poss=100 * us['possession_time'] / pt,
            pc=100 * us['passes_completed'] / us['passes_attempted'],
            opp_pc=100 * them['passes_completed'] / them['passes_attempted'],
            passes=us['passes_attempted'],
            pass_per_min=us['passes_attempted'] / (us['possession_time'] / 60),
            sot_m=us['shots_on_target'] - them['shots_on_target'],
            shot_share=100 * us['shots'] / max(1, us['shots'] + them['shots']),
            ccc_m=us['clear_cut_chances'] - them['clear_cut_chances'],
            corner_m=us['corners'] - them['corners'],
            cross_att=us.get('crosses_attempted'),
            cross_pc=(100 * us['crosses_completed'] / us['crosses_attempted']) if us.get('crosses_attempted') else None,
            tackles=us['tackles_attempted'],
            headers=us['headers_attempted'],
            fouls=us['fouls'],
        ))
summary = []
for (s, club), rs in rows.items():
    if len(rs) < 5: continue
    agg = {k: st.mean(r[k] for r in rs if r[k] is not None) for k in rs[0]}
    summary.append((s, club, half[(s, club)], len(rs), agg))
json.dump([(s, names.get(c, c), h, n, a) for s, c, h, n, a in summary], open('data/exports/control-evidence.json', 'w'), indent=1)

def spearman(x, y):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for k, i in enumerate(o): r[i] = k
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den
for label, subset in (('all clubs', summary), ('top-half clubs', [r for r in summary if r[2][0] == 'top'])):
    print(f"\n{label}: {len(subset)} club-seasons, vs bottom-half opponents only")
    for target in ('sot_m', 'ccc_m', 'pts'):
        ys = [r[4][target] for r in subset]
        line = []
        for k in ('poss', 'pc', 'pass_per_min', 'opp_pc', 'corner_m', 'cross_att', 'tackles', 'headers'):
            line.append(f"{k} {spearman([r[4][k] for r in subset], ys):+.2f}")
        print(f"  {target:6} vs  " + '  '.join(line))
print("\nTop-half club-seasons, sorted by SOT margin vs bottom half:")
print(f"{'season':6} {'club':26} {'pos':>4} {'n':>3} {'ppg':>5} {'SOTm':>5} {'CCCm':>5} {'poss':>5} {'pc':>5} {'p/min':>5} {'oppPC':>5} {'cornm':>5} {'xatt':>5} {'tack':>5} {'head':>5}")
for s, c, h, n, a in sorted([r for r in summary if r[2][0] == 'top'], key=lambda r: -r[4]['sot_m']):
    print(f"{s:6} {names.get(c, c)[:26]:26} {h[1]:>4} {n:>3} {a['pts']:5.2f} {a['sot_m']:+5.1f} {a['ccc_m']:+5.2f} {a['poss']:5.1f} {a['pc']:5.1f} {a['pass_per_min']:5.1f} {a['opp_pc']:5.1f} {a['corner_m']:+5.1f} {a['cross_att']:5.1f} {a['tackles']:5.1f} {a['headers']:5.1f}")

# ---- formations and roles the top half use against the bottom half ----
from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.match_roles import RoleCodes
codes = RoleCodes.build(MVP_CATALOGUE)
by_form = collections.defaultdict(list); role_counts = collections.Counter(); starters_n = 0
for (s, date, h, a), m in detail.items():
    det = m['detail']
    for side, club, opp in (('home', h, a), ('away', a, h)):
        if half.get((s, club), ('?',))[0] != 'top' or half.get((s, opp), ('?',))[0] != 'bottom': continue
        other = 'away' if side == 'home' else 'home'
        us, them = det[side], det[other]
        f = (det.get('formations') or {}).get(side) or '?'
        pt = us['possession_time'] + them['possession_time']
        by_form[f].append((us['shots_on_target'] - them['shots_on_target'], 100 * us['possession_time'] / pt,
                           100 * them['passes_completed'] / them['passes_attempted'], us.get('crosses_attempted') or 0,
                           us['corners'] - them['corners']))
        for p in det['players']:
            if p['side'] == side and p.get('started') and p.get('roleCode') is not None and p['position'] != 'GK':
                role_counts[codes.label(p['roleCode'], p.get('startPosition') or p['position'])] += 1; starters_n += 1
print("\nTop-half clubs v bottom half, by the top club's formation:")
print(f"{'formation':26} {'n':>4} {'SOTm':>5} {'poss':>5} {'oppPC':>5} {'xatt':>5} {'cornm':>5}")
for f, rs in sorted(by_form.items(), key=lambda kv: -len(kv[1])):
    if len(rs) < 8: continue
    cols = list(zip(*rs))
    print(f"{f:26} {len(rs):>4} {st.mean(cols[0]):+5.1f} {st.mean(cols[1]):5.1f} {st.mean(cols[2]):5.1f} {st.mean(cols[3]):5.1f} {st.mean(cols[4]):+5.1f}")
print("\nMost common starting roles for top-half clubs v bottom half (share of outfield starts):")
for label, n in role_counts.most_common(22):
    print(f"  {label:38} {100*n/starters_n:4.1f}%")
