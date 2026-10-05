# -*- coding: utf-8 -*-
"""
SafeStep AI - 구조 검증 시뮬레이션

목적
    "위험은 장소가 아니라 상황이다" 라는 주장이 실제로 경로 선택을 바꾸는지를
    확인한다. 도로망과 사고이력은 가상으로 만든 값이며, 실제 사고 감소 효과를
    주장하기 위한 것이 아니다. 같은 지도 위에서 시간과 날씨만 바꿨을 때
    위험가중 경로탐색이 다른 답을 내는지, 그 구조가 작동하는지만 본다.

확인하려는 것
    1. 같은 출발지/목적지인데 조건이 바뀌면 추천 경로가 바뀌는가
    2. 고정 거리 규칙 방식과 상황 반영 방식이 다른 구간을 위험하다고 보는가
    3. 안전 경로가 시간을 얼마나 더 쓰고 위험 노출을 얼마나 줄이는가

반증 조건
    조건을 바꿔도 항상 같은 경로만 나온다면 이 아이디어의 전제가 틀린 것이다.
"""

import heapq
import json
import random

random.seed(20261007)

# ---------------------------------------------------------------- 도로망 구성
# 7x7 격자 교차로. 가로 120m, 세로 100m 간격으로 가정한다.
NX, NY = 7, 7
SEG_X_LEN, SEG_Y_LEN = 120.0, 100.0   # m
# 보행신호 설계 기준속도 1.0 m/s, 어린이보호구역은 0.8 m/s 를 적용한다.
# 통학로 시뮬레이션이므로 보수적으로 0.9 m/s 를 쓴다.
WALK_SPEED = 0.9 * 60                 # m/min (= 시속 3.24km)

SCHOOL = (6, 0)   # 북동쪽 끝
HOME = (0, 6)     # 남서쪽 끝


def pos(n):
    """교차로의 실제 좌표(m)"""
    x, y = n
    return (x * SEG_X_LEN, y * SEG_Y_LEN)


def nodes():
    return [(x, y) for x in range(NX) for y in range(NY)]


# 간선도로 축: 집(0,6)에서 학교(6,0) 쪽으로 비스듬히 뚫린 큰길.
# 격자를 돌아가지 않고 대각선으로 질러가므로 거리가 짧다.
# 대신 차로가 많고 사고이력과 횡단보도가 몰려 있다.
ARTERIAL = [((0, 6), (1, 5)), ((1, 5), (2, 4)), ((2, 4), (3, 3)),
            ((3, 3), (4, 2)), ((4, 2), (5, 1)), ((5, 1), (6, 0))]
ARTERIAL_SET = set(tuple(sorted(e)) for e in ARTERIAL)


def neighbors(n):
    x, y = n
    out = []
    if x + 1 < NX: out.append((x + 1, y))
    if x - 1 >= 0: out.append((x - 1, y))
    if y + 1 < NY: out.append((x, y + 1))
    if y - 1 >= 0: out.append((x, y - 1))
    for a, b in ARTERIAL:                    # 대각 간선도로 연결
        if n == a: out.append(b)
        if n == b: out.append(a)
    return out


def edge_key(a, b):
    return tuple(sorted([a, b]))


def seg_length(a, b):
    (ax, ay), (bx, by) = pos(a), pos(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


# ------------------------------------------------- 구간별 정적 속성 (가상 생성)
# 실제 서비스에서는 TAAS 사고이력, 공공데이터포털 횡단보도/보호구역,
# 표준노드링크 도로망이 들어갈 자리다. 여기서는 구조 확인용으로 생성한다.

def school_dist(a, b):
    """구간 중점에서 학교까지의 격자 거리"""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    return abs(mx - SCHOOL[0]) + abs(my - SCHOOL[1])


EDGES = {}
for n in nodes():
    for m in neighbors(n):
        k = edge_key(n, m)
        if k in EDGES:
            continue
        d = school_dist(*k)
        # 학교에 가까울수록 횡단보도/보호구역/사고이력이 몰리도록 구성
        near = max(0.0, 1.0 - d / 8.0)
        EDGES[k] = {
            "length": seg_length(*k),
            "crosswalk": 1 if random.random() < 0.25 + 0.45 * near else 0,
            "school_zone": 1 if d <= 3.0 else 0,
            "accidents": max(0, int(random.gauss(2.6 * near, 0.9))),
            "lanes": random.choice([2, 2, 4, 4, 6]),
            "school_dist": d,
        }

# 간선도로 구간은 차로가 넓고 사고가 잦으며 횡단보도를 반드시 건너야 한다
for k in ARTERIAL_SET:
    e = EDGES[k]
    e["lanes"] = 6
    e["accidents"] += 3
    e["crosswalk"] = 1
    e["arterial"] = True
for k, e in EDGES.items():
    e.setdefault("arterial", False)


# ------------------------------------------------------------- 위험도 모델
# 로지스틱 형태의 점수 함수. 실제로는 TAAS 데이터로 학습할 자리이며,
# 여기서는 어떤 변수가 어떻게 작용하는지 구조만 드러내도록 계수를 고정했다.

def risk_score(e, ctx):
    """0~100 위험도. ctx = 시간대/요일/강수 상황"""
    z = -3.0
    z += 0.42 * e["accidents"]
    z += 0.35 * e["crosswalk"]
    z += 0.30 * e["school_zone"]
    z += 0.45 * (e["lanes"] - 2) / 2.0

    # 상황 변수 - 같은 구간이라도 여기서 값이 갈린다
    if ctx["commute"]:
        z += 0.85
        z += 0.55 * e["school_zone"]      # 등하교 x 스쿨존 상호작용
    if ctx["rain"]:
        z += 0.70
        z += 0.40 * e["crosswalk"]        # 비 x 횡단보도 상호작용
    if ctx["dark"]:
        z += 0.50
    if ctx["weekend"]:
        z -= 0.60

    p = 1 / (1 + pow(2.718281828, -z))
    return round(p * 100, 1)


def travel_min(e):
    return e["length"] / WALK_SPEED


# --------------------------------------------------------------- 경로 탐색
def dijkstra(ctx, beta):
    """beta=0 이면 순수 최단시간, beta>0 이면 위험가중"""
    dist = {n: float("inf") for n in nodes()}
    prev = {}
    dist[HOME] = 0.0
    pq = [(0.0, HOME)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u] + 1e-12:
            continue
        if u == SCHOOL:
            break
        for v in neighbors(u):
            e = EDGES[edge_key(u, v)]
            t = travel_min(e)
            r = risk_score(e, ctx)
            cost = t + beta * (r / 100.0) * t     # 위험할수록 그 구간을 걷는 비용이 커진다
            nd = d + cost
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    path, cur = [SCHOOL], SCHOOL
    while cur != HOME:
        cur = prev[cur]
        path.append(cur)
    return list(reversed(path))


def summarize(path, ctx):
    t = 0.0
    exposure = 0.0          # 위험도 x 그 구간에 머무는 시간
    risks = []
    for a, b in zip(path, path[1:]):
        e = EDGES[edge_key(a, b)]
        m = travel_min(e)
        r = risk_score(e, ctx)
        t += m
        exposure += (r / 100.0) * m
        risks.append(r)
    return {
        "minutes": round(t, 1),
        "exposure": round(exposure, 2),
        "peak_risk": max(risks),
        "mean_risk": round(sum(risks) / len(risks), 1),
        "path": path,
    }


# ---------------------------------------------------- 기존 고정 규칙 방식 비교
def static_rule_flags(path):
    """
    기존 방식 재현: 상황을 보지 않고 스쿨존/횡단보도면 위험으로 표시.
    시간과 날씨가 바뀌어도 결과가 동일하다는 점을 보이기 위한 것.
    """
    cnt = 0
    for a, b in zip(path, path[1:]):
        e = EDGES[edge_key(a, b)]
        if e["school_zone"] or e["crosswalk"]:
            cnt += 1
    return cnt


# ------------------------------------------------------------------ 시나리오
SCENARIOS = {
    "일요일 14:00 맑음": dict(commute=False, rain=False, dark=False, weekend=True),
    "월요일 08:05 비":  dict(commute=True,  rain=True,  dark=False, weekend=False),
    "월요일 20:30 맑음": dict(commute=False, rain=False, dark=True,  weekend=False),
}

BETA = 2.5   # 안전 우선 모드

print("=" * 72)
print("SafeStep AI 구조 검증 시뮬레이션")
print("가상 도로망 7x7 / 가상 사고이력 / 실제 사고 감소 효과 주장 아님")
print("=" * 72)

results = {}
for name, ctx in SCENARIOS.items():
    fast = dijkstra(ctx, beta=0.0)
    safe = dijkstra(ctx, beta=BETA)
    f, s = summarize(fast, ctx), summarize(safe, ctx)

    changed = fast != safe
    results[name] = {
        "fast": f, "safe": s, "changed": changed,
        "static_flags": static_rule_flags(fast),
    }

    print(f"\n[{name}]")
    print(f"  최단경로     {f['minutes']:5.1f}분   평균위험 {f['mean_risk']:5.1f}   최고위험 {f['peak_risk']:5.1f}   노출 {f['exposure']:5.2f}")
    print(f"  SafeStep    {s['minutes']:5.1f}분   평균위험 {s['mean_risk']:5.1f}   최고위험 {s['peak_risk']:5.1f}   노출 {s['exposure']:5.2f}")
    extra = s["minutes"] - f["minutes"]
    drop = (1 - s["exposure"] / f["exposure"]) * 100 if f["exposure"] else 0
    print(f"  차이         +{extra:.1f}분 더 걷고 위험노출 {drop:.0f}% 감소")
    print(f"  경로가 바뀌었는가: {'예' if changed else '아니오'}")
    print(f"  기존 고정규칙이 위험하다고 표시한 구간 수: {results[name]['static_flags']}개 (조건 무관 고정)")

# ------------------------------------------------------- 핵심 확인: 경로 변화
print("\n" + "=" * 72)
print("확인 1. 같은 출발지/목적지에서 조건만 바꿨을 때 추천 경로가 달라지는가")
print("=" * 72)
safe_paths = {n: tuple(results[n]["safe"]["path"]) for n in SCENARIOS}
uniq = len(set(safe_paths.values()))
for n, p in safe_paths.items():
    print(f"  {n:18s} 경유 교차로 수 {len(p)}")
print(f"\n  서로 다른 경로의 가짓수: {uniq} / {len(SCENARIOS)}")
print("  판정:", "조건에 따라 경로가 갈림 (전제 성립)" if uniq > 1
      else "조건이 바뀌어도 같은 경로 (전제 반증)")

print("\n" + "=" * 72)
print("확인 2. 사용자가 시간과 안전을 저울질할 수 있는가 (모드 선택)")
print("=" * 72)
print("  beta 를 올릴수록 위험을 더 크게 피한다. 월요일 08:05 비 기준.")
ctx = SCENARIOS["월요일 08:05 비"]
base = summarize(dijkstra(ctx, 0.0), ctx)
print(f"\n  {'모드':10s} {'추가시간':>8s} {'위험노출':>8s} {'감소율':>7s}")
print("  " + "-" * 38)
balanced = None
for label, b in [("빠른 길", 0.0), ("균형 A", 0.4), ("균형 B", 0.8),
                 ("균형 C", 1.4), ("안전 우선", 2.5)]:
    s = summarize(dijkstra(ctx, b), ctx)
    extra = s["minutes"] - base["minutes"]
    drop = (1 - s["exposure"] / base["exposure"]) * 100
    mark = ""
    if balanced is None and 0 < extra <= 3.0:
        balanced, mark = (label, extra, drop), "   <- 추가 3분 이내"
    print(f"  {label:10s} {extra:+7.1f}분 {s['exposure']:8.2f} {drop:6.0f}%{mark}")

if balanced:
    print(f"\n  추가 보행시간 3분 이내 조건을 만족하면서 위험노출을 "
          f"{balanced[2]:.0f}% 줄이는 설정이 존재한다.")
else:
    print("\n  추가 3분 이내로는 유의미한 감소를 얻지 못한다. 목표치 재검토 필요.")

print("\n" + "=" * 72)
print("확인 2-B. 경로 후보를 '실제로 다니는 길'로 제한하면 어떻게 되는가")
print("=" * 72)
print("  지도 위 모든 길이 아니라, 사람들이 실제 걷는 길만 후보로 둔다.")


def habitual_routes(n=40):
    """
    가상의 '사람들이 실제로 다니는 길' 집합.
    학교 방향으로만 전진하는 경로를 무작위로 만들되,
    큰길(간선도로)은 주요 통학로이므로 더 자주 선택되게 한다.
    실제 서비스에서는 이 집합이 사용자 통행 기록으로 대체된다.
    """
    used = set()
    for _ in range(n):
        cur, guard = HOME, 0
        while cur != SCHOOL and guard < 60:
            guard += 1
            cands = []
            for v in neighbors(cur):
                # 학교 쪽으로 가까워지는 방향만 (사람은 되돌아가지 않는다)
                if abs(v[0] - SCHOOL[0]) + abs(v[1] - SCHOOL[1]) < \
                   abs(cur[0] - SCHOOL[0]) + abs(cur[1] - SCHOOL[1]):
                    w = 3.0 if edge_key(cur, v) in ARTERIAL_SET else 1.0
                    cands.append((v, w))
            if not cands:
                break
            tot = sum(w for _, w in cands)
            r, acc = random.random() * tot, 0
            for v, w in cands:
                acc += w
                if r <= acc:
                    used.add(edge_key(cur, v))
                    cur = v
                    break
    return used


WALKED = habitual_routes()
print(f"  통행 기록에 나타난 구간 수: {len(WALKED)} / 전체 {len(EDGES)}개")


def dijkstra_limited(ctx, beta, allowed):
    dist = {n: float("inf") for n in nodes()}
    prev = {}
    dist[HOME] = 0.0
    pq = [(0.0, HOME)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u] + 1e-12:
            continue
        for v in neighbors(u):
            k = edge_key(u, v)
            if k not in allowed:
                continue
            e = EDGES[k]
            t = travel_min(e)
            r = risk_score(e, ctx)
            nd = d + t + beta * (r / 100.0) * t
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dist[SCHOOL] == float("inf"):
        return None
    path, cur = [SCHOOL], SCHOOL
    while cur != HOME:
        cur = prev[cur]
        path.append(cur)
    return list(reversed(path))


print(f"\n  {'시나리오':18s} {'방식':12s} {'추가시간':>8s} {'위험노출감소':>11s}")
print("  " + "-" * 54)
for name, ctx in SCENARIOS.items():
    base = summarize(dijkstra(ctx, 0.0), ctx)
    full = summarize(dijkstra(ctx, BETA), ctx)
    lim_p = dijkstra_limited(ctx, BETA, WALKED)
    lim = summarize(lim_p, ctx) if lim_p else None

    def row(label, s):
        if s is None:
            print(f"  {'':18s} {label:12s} {'경로 없음':>8s}")
            return
        ex = s["minutes"] - base["minutes"]
        dr = (1 - s["exposure"] / base["exposure"]) * 100 if base["exposure"] else 0
        print(f"  {'':18s} {label:12s} {ex:+7.1f}분 {dr:10.0f}%")

    print(f"  {name:18s}")
    row("전체 도로", full)
    row("다니는 길만", lim)

print("\n  해석: 추가시간이 줄면 제한이 효과가 있는 것이고,")
print("        위험노출 감소폭까지 같이 줄면 안전 이득을 일부 포기한 것이다.")

print("\n" + "=" * 72)
print("확인 3. 우회해도 피할 수 없는 구간이 남는가")
print("=" * 72)
for name, ctx2 in SCENARIOS.items():
    f = summarize(dijkstra(ctx2, 0.0), ctx2)
    s = summarize(dijkstra(ctx2, BETA), ctx2)
    gap = f["peak_risk"] - s["peak_risk"]
    note = "남음 (개입 필요)" if gap < 5 else "회피 성공"
    print(f"  {name:18s} 최단 최고위험 {f['peak_risk']:5.1f} -> 안전 {s['peak_risk']:5.1f}   {note}")
print("\n  경로 변경만으로 모든 위험이 사라지지 않는다.")
print("  이것이 3단계 개입(음성/진동/안전미션)이 필요한 이유다.")

print("\n" + "=" * 72)
print("확인 4. 같은 구간의 위험도가 상황에 따라 달라지는가")
print("=" * 72)
sample = sorted(EDGES.items(), key=lambda kv: -kv[1]["accidents"])[0]
k, e = sample
print(f"  표본 구간 {k}  사고이력 {e['accidents']}건 / 횡단보도 {e['crosswalk']} / 스쿨존 {e['school_zone']}")
for n, ctx in SCENARIOS.items():
    print(f"    {n:18s} 위험도 {risk_score(e, ctx):5.1f}")
print("  기존 고정규칙 방식: 위 세 경우 모두 동일하게 '위험구역'으로 표시")

with open("sim_result.json", "w", encoding="utf-8") as fp:
    json.dump({k: {"fast": v["fast"], "safe": v["safe"], "changed": v["changed"]}
               for k, v in results.items()}, fp, ensure_ascii=False, indent=2,
              default=str)
print("\n결과를 sim_result.json 에 저장했습니다.")
