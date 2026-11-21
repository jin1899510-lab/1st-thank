"""경쟁사·소구점 분석 자료 수집 (proposals/기획_경쟁사·소구점 분석.md).

사용법:
    python tools/appeal.py --slug nekonomura --place "https://m.place.naver.com/restaurant/1573719918"
        [--keywords "장산역 초밥,해운대 초밥,..."]   # 메인 키워드 5개를 직접 줄 때
        [--menu "초밥"]                               # 전국 조사용 대표 메뉴 키워드 (없으면 리뷰 메뉴 언급 1위)
        [--radius 1000] [--our-reviews 100] [--comp-reviews 50] [--nat-reviews 30]
        [--skip-national]

저장 (proposals/<slug>/data/appeal/):
    our.json, competitors.json, national.json  — 매장마다 소개·메뉴·가격·리뷰 통계·리뷰 본문·방문 상황·쿠폰·소식·교통·상권 유형
    keywords.json                               — 메인 키워드 5개 고른 근거 (검색량)
    appeal_data.md                              — 사람이 보는 요약 (분석은 APPEAL_GUIDE.md 대로 Claude가 appeal_report.md 로)

- 리뷰 본문은 에고라이트 브라우저로 리뷰 화면을 열고 '펼쳐서 더보기'를 눌러 사람처럼 읽는다 (API 직접 호출은 막혀 있어 쓰지 않는다).
- 메뉴·가격·리뷰 통계·소식·교통은 플레이스 페이지 데이터에서 읽는다.
"""
import argparse
import collections
import json
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import naver_place as np_  # noqa: E402
from browser_collect import ego_script, run_ego, data_dir, _place_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

FOOD = re.compile(r"식당|음식|요리|한식|일식|중식|양식|분식|카페|디저트|베이커리|주점|술집|이자카야|포차|고기|구이|족발|보쌈|치킨|피자|햄버거|국밥|국수|냉면|초밥|회|해물|횟집|뷔페|돈가스|덮밥|라멘|파스타|브런치|샤브|곱창|막창|찌개|백반|도시락|김밥|떡볶이")

# 전국 조사 지역 (위도, 경도). 고정 5곳 + 상권 유형별 대표 지역
REGIONS_FIXED = {"서울 강남역": (37.4979, 127.0276), "서울 홍대입구": (37.5572, 126.9245), "부산 서면": (35.1578, 129.0600),
                 "대구 동성로": (35.8690, 128.5960), "대전 둔산": (36.3518, 127.3786)}
REGIONS_BY_TYPE = {
    "학원가": {"서울 대치동": (37.4946, 127.0627), "서울 목동": (37.5265, 126.8750), "서울 중계동": (37.6467, 127.0730), "대구 범어동": (35.8600, 128.6230)},
    "오피스": {"서울 여의도": (37.5219, 126.9245), "서울 을지로": (37.5660, 126.9910), "성남 판교": (37.3947, 127.1112)},
    "관광·랜드마크": {"부산 해운대해수욕장": (35.1587, 129.1604), "경주 황리단길": (35.8380, 129.2100), "전주 한옥마을": (35.8150, 127.1530), "제주 애월": (33.4630, 126.3190)},
    "대학가": {"서울 신촌": (37.5598, 126.9425), "부산대 앞": (35.2310, 129.0840), "대전 궁동": (36.3620, 127.3500)},
    "주거(가족)": {"서울 위례": (37.4780, 127.1460), "화성 동탄": (37.2000, 127.0730), "세종 나성동": (36.4860, 127.2580)},
    "주거(1인)": {"서울 신림": (37.4842, 126.9297), "서울 망원": (37.5560, 126.9100)},
    "역세권": {"서울 건대입구": (37.5404, 127.0692), "부산 연산": (35.1860, 129.0820)},
}

# 상권 유형을 정하는 주변 시설 (네이버 플레이스 반경 검색어)
AREA_QUERIES = {"학원": "학원가", "초등학교": "학원가", "아파트": "주거(가족)", "오피스텔": "주거(1인)", "회사": "오피스",
                "지하철역": "역세권", "관광명소": "관광·랜드마크", "호텔": "관광·랜드마크", "대학교": "대학가"}

SITU = {
    "time": re.compile(r"^(아침|점심|오후|저녁|밤)에 방문$"),
    "reserve": re.compile(r"^예약 (없이|후) 이용$"),
    "wait": re.compile(r"(바로 입장|분 이내|분 이상|시간 이상)"),
    "purpose": re.compile(r"^(일상|친목|데이트|가족모임|기념일|여행|나들이|비즈니스|회식|모임|업무|기타|휴식|운동|쇼핑|공부)$"),
    "with": re.compile(r"^(혼자|친구|연인・배우자|연인·배우자|아이|가족|부모님|지인・동료|지인·동료|반려동물|단체|자녀|기타)$"),
}
SCENE_WORDS = ["학원", "학생", "아이", "애들", "가족", "부모님", "혼밥", "혼자", "점심", "저녁", "퇴근", "회식", "직장", "회사", "데이트",
               "여행", "관광", "포장", "배달", "주차", "대기", "웨이팅", "예약", "가성비", "양이", "푸짐", "신선", "친절", "깔끔",
               "분위기", "전망", "재방문", "단골", "반찬", "샐러드", "국", "디저트", "서비스", "리필", "세트", "가격", "비싸", "아쉬"]


# ---------------------------------------------------------------- 페이지 데이터 (requests)
def page_data(pid):
    me = np_.place_detail(pid)
    menu = np_._apollo(f"https://m.place.naver.com/restaurant/{pid}/menu/list")
    items = [v for k, v in menu.items() if k.startswith("PlaceMenuItem:")]
    menus = [{"name": i.get("name"), "price": ((i.get("price") or {}).get("displayText")), "desc": (i.get("description") or "")[:120],
              "set": i.get("isSetMenu"), "img": i.get("hasImage")} for i in items]
    rv = np_._apollo(f"https://m.place.naver.com/restaurant/{pid}/review/visitor")
    st = rv.get(f"VisitorReviewStatsResult:{pid}") or {}
    an = st.get("analysis") or {}
    vk = (an.get("votedKeyword") or {})
    stats = {"total": (st.get("review") or {}).get("totalCount"), "image": (st.get("review") or {}).get("imageReviewCount"),
             "themes": [f"{t['label']} {t['count']}" for t in an.get("themes") or []][:10],
             "menus": [f"{t['label']} {t['count']}" for t in an.get("menus") or []][:15],
             "liked": [f"{x.get('displayName') or x.get('name') or x.get('code')} {x.get('count')}" for x in (vk.get("details") or [])][:12],
             "liked_users": vk.get("userCount")}
    trans = []
    for k, v in rv.items():
        if k.startswith("SubwayStationInfo"):
            trans.append(f"{v.get('displayName')} {v.get('nearestExit')}번 출구 도보 {v.get('walkTime')}분 ({v.get('walkingDistance')}m)")
        elif k.startswith("BusStation"):
            trans.append(f"버스 {v.get('name')}")
    feed = np_._apollo(f"https://m.place.naver.com/restaurant/{pid}/feed")
    feeds = [{"date": v.get("relativeCreated"), "category": v.get("category"), "title": v.get("title"), "desc": (v.get("desc") or "")[:150]}
             for k, v in feed.items() if k.startswith("Feed:")][:12]
    return {"id": pid, "name": me.get("name"), "category": me.get("category"), "address": me.get("address"), "road": me.get("road_address"),
            "x": me.get("x"), "y": me.get("y"), "description": (me.get("description") or "")[:800], "conveniences": me.get("conveniences"),
            "micro_review": me.get("micro_review"), "visitor_reviews": me.get("visitor_reviews"), "blog_reviews": me.get("blog_reviews"),
            "images": me.get("images"), "coupon_count": me.get("coupon"), "booking": me.get("booking"), "naver_order": me.get("naver_order"),
            "menus": menus, "review_stats": stats, "transport": trans[:4], "feed": feeds}


def page_data_retry(pid, tries=4):
    """네이버가 잠시 막으면(요청이 많을 때) 기다렸다가 다시 시도한다."""
    for k in range(tries):
        try:
            return page_data(pid)
        except Exception as e:  # noqa: BLE001
            if k == tries - 1:
                raise
            wait = 20 * (k + 1)
            print(f"   잠시 막힘 → {wait}초 뒤 다시 ({str(e)[:60]})", flush=True)
            time.sleep(wait)


# ---------------------------------------------------------------- 리뷰 본문·쿠폰 (브라우저)
REVIEW_JS = r"""
const jobs = __JOBS__;
result = {};
for (const [pid, want] of jobs) {
  const r = { reviews: [], coupons: [] };
  try {
    await page.goto("https://m.place.naver.com/restaurant/" + pid + "/home", { timeout: 60000 });
    await page.waitForTimeout(1500 + Math.random() * 800);
    r.coupons = await page.evaluate(() => { const t = document.body.innerText.split("\n").map(s => s.trim()); const i = t.lastIndexOf("쿠폰"); const out = []; if (i >= 0) for (const s of t.slice(i + 1, i + 10)) { if (/^(주소|다운로드|찾아가는길)$/.test(s)) break; if (s) out.push(s); } return out; });
    await page.goto("https://m.place.naver.com/restaurant/" + pid + "/review/visitor?reviewSort=recent", { timeout: 60000 });
    await page.waitForTimeout(1800 + Math.random() * 800);
    const count = () => page.evaluate(() => [...document.querySelectorAll("ul li")].filter(li => /방문일/.test(li.innerText)).length);
    for (let i = 0; i < 20; i++) {
      const before = await count(); if (before >= want) break;
      const ok = await page.evaluate(() => { const a = [...document.querySelectorAll("a")].find(x => (x.innerText || "").trim() === "펼쳐서 더보기"); if (!a) return false; a.scrollIntoView({ block: "center" }); return true; });
      if (!ok) break;
      await page.waitForTimeout(300 + Math.random() * 400);
      try { await page.click('a:has-text("펼쳐서 더보기")', { label: "load more reviews" }); } catch (e) { break; }
      await page.waitForFunction((b) => [...document.querySelectorAll("ul li")].filter(li => /방문일/.test(li.innerText)).length > b, before, { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(500 + Math.random() * 900);
    }
    r.reviews = await page.evaluate((want) => [...document.querySelectorAll("ul li")].filter(li => /방문일/.test(li.innerText)).slice(0, want).map(li => {
      const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT); const toks = []; let n;
      while ((n = w.nextNode())) { const s = n.textContent.trim(); if (s) toks.push(s); }
      return toks;
    }), want);
  } catch (e) { r.error = String(e).slice(0, 200); }
  result[pid] = r;
  await page.waitForTimeout(1200 + Math.random() * 1500);
}
"""


def parse_review(toks):
    """리뷰 카드 글 조각 → 별점·방문 상황·본문·키워드·방문일·몇 번째."""
    out = {"situation": {}, "keywords": [], "body": "", "visited": None, "nth": None, "proof": None, "rating": None}
    i = 0
    if "별점" in toks and "점" in toks:
        out["rating"] = toks[toks.index("별점") + 1] if toks.index("별점") + 1 < len(toks) else None
        i = toks.index("점") + 1
    elif "팔로우" in toks:
        i = toks.index("팔로우") + 1
    else:
        i = next((k + 1 for k, t in enumerate(toks) if re.match(r"리뷰 ?\d", t)), 0)
    end = toks.index("반응 남기기") if "반응 남기기" in toks else len(toks)
    body, kws = [], []
    for t in toks[i:end]:
        if t in ("대기 시간", "예약", "방문", "동행", "목적"):
            continue
        hit = next((k for k, p in SITU.items() if p.search(t)), None)
        if hit and (not body or hit in ("purpose", "with", "wait") and len(body) < 1):
            out["situation"][hit] = t
        elif len(t) <= 14 and t.endswith("요") and body:
            kws.append(t)
        elif t not in ("접기", "더보기", "+", "펼쳐보기") and not re.fullmatch(r"\+\d+", t):
            body.append(t)
    out["body"] = " ".join(body)[:600]
    out["keywords"] = kws
    if "방문일" in toks:
        j = toks.index("방문일")
        out["visited"] = toks[j + 1] if j + 1 < len(toks) else None
    out["nth"] = next((t for t in toks if re.fullmatch(r"\d+번째 방문", t)), None)
    if "인증 수단" in toks:
        j = toks.index("인증 수단")
        out["proof"] = toks[j + 1] if j + 1 < len(toks) else None
    return out


def review_summary(reviews):
    c = {k: collections.Counter() for k in SITU}
    words = collections.Counter()
    for r in reviews:
        for k, v in r["situation"].items():
            c[k][v] += 1
        for w in SCENE_WORDS:
            if w in r["body"]:
                words[w] += 1
    revisit = sum(1 for r in reviews if r["nth"] and not r["nth"].startswith("1번째"))
    return {"n": len(reviews), "time": c["time"].most_common(), "purpose": c["purpose"].most_common(6), "with": c["with"].most_common(6),
            "reserve": c["reserve"].most_common(), "wait": c["wait"].most_common(4), "scene_words": words.most_common(20),
            "revisit_share": round(revisit / len(reviews) * 100, 1) if reviews else None}


def browse_reviews(slug, jobs, tag):
    if not jobs:
        return {}
    res = run_ego(ego_script(f"appeal {slug} {tag}", REVIEW_JS.replace("__JOBS__", json.dumps(jobs))),
                  timeout=180 + sum(15 + n // 10 * 6 for _, n in jobs))
    return res


# ---------------------------------------------------------------- 상권 유형
def area_tags(x, y):
    found, near = collections.Counter(), {}
    for q, tag in AREA_QUERIES.items():
        try:
            r = np_.place_list(q, x, y)
        except Exception:  # noqa: BLE001
            continue
        ds = []
        for it in r["items"]:
            m = re.match(r"([\d.]+)(k?m)", it.get("distance") or "")
            if m:
                ds.append(float(m.group(1)) * (1000 if m.group(2) == "km" else 1))
        c300 = sum(1 for d in ds if d <= 300)
        c500 = sum(1 for d in ds if d <= 500)
        near[q] = {"within300": c300, "within500": c500, "nearest_m": min(ds) if ds else None,
                   "examples": [f"{it['name']} {it['distance']}" for it in r["items"][:3]]}
        score = c300 * 2 + c500
        if q in ("관광명소", "호텔", "대학교", "회사"):
            score = score if c500 >= 2 else 0
        if q == "지하철역":
            score = 6 if (min(ds) if ds else 9999) <= 400 else 0
        found[tag] += score
        np_.pause(0.8)
    tags = [t for t, s in found.most_common() if s >= 6][:3]
    return {"tags": tags or ["생활"], "scores": dict(found), "facilities": near}


# ---------------------------------------------------------------- 키워드·경쟁사·전국
def main_keywords(our, given, n=5):
    if given:
        return [k.strip() for k in given.split(",") if k.strip()][:n], {"given": True}
    addr = (our["address"] or "").split()
    dong = re.sub(r"\d+(동|가)$", r"\1", addr[2]) if len(addr) > 2 else ""
    gu = addr[1].rstrip("구군시") if len(addr) > 1 else ""
    station = re.sub(r"역$", "", (our["transport"][0].split()[0] if our["transport"] and not our["transport"][0].startswith("버스") else ""))
    places = [p for p in {f"{station}역" if station else "", dong, gu} if p]
    cat = re.sub(r"(전문점|당|집)$", "", (our["category"] or "").split(",")[0])
    words = [w.split()[0] for w in our["review_stats"]["menus"][:3]] + [cat, "맛집"]
    cands = list(dict.fromkeys(f"{p} {w}" for p in places for w in words if w))
    vol = {}
    try:
        import naver_ad
        rows, _ = naver_ad.volumes(cands)
        vol = {k: v["총 검색수"] if isinstance(v["총 검색수"], int) else 5 for k, v in rows.items()}
    except SystemExit:
        pass
    ranked = sorted(cands, key=lambda c: -vol.get(c.replace(" ", ""), 0))
    pick, wide = [], 0
    for c in ranked:  # 구 단위 넓은 키워드는 2개까지 (동네 키워드를 남기려고)
        if gu and c.startswith(gu + " "):
            if wide >= 2:
                continue
            wide += 1
        pick.append(c)
        if len(pick) == n:
            break
    return pick, {"candidates": cands, "volumes": vol}


def plist(q, x, y, tries=4):
    for k in range(tries):
        try:
            return np_.place_list(q, x, y)
        except Exception as e:  # noqa: BLE001
            if k == tries - 1:
                raise
            time.sleep(20 * (k + 1))


def dist_m(s):
    m = re.match(r"([\d.]+)(k?m)", s or "")
    return float(m.group(1)) * (1000 if m.group(2) == "km" else 1) if m else None


def gather_competitors(our, keywords, radius):
    comp, why = {}, collections.defaultdict(list)
    for kw in keywords:
        r = plist(kw, our["x"], our["y"])
        for rank, it in enumerate(r["items"], 1):
            if it["id"] == our["id"]:
                why["__our_rank__"].append(f"{kw} {rank}위")
                continue
            comp.setdefault(it["id"], it)
            why[it["id"]].append(f"{kw} {rank}위")
        np_.pause()
    # 반경 안 같은 업종·비슷한 업종
    terms = list(dict.fromkeys([our["category"] or "", (our["review_stats"]["menus"][0].split()[0] if our["review_stats"]["menus"] else "")]))
    for t in [t for t in terms if t]:
        r = plist(t, our["x"], our["y"])
        for it in r["items"]:
            d = dist_m(it.get("distance"))
            if it["id"] != our["id"] and d is not None and d <= radius:
                comp.setdefault(it["id"], it)
                why[it["id"]].append(f"반경 {int(d)}m '{t}'")
        np_.pause()
    return comp, why


def gather_national(our, menu_word, tags, per=5):
    regions = dict(REGIONS_FIXED)
    for t in tags:
        regions.update(REGIONS_BY_TYPE.get(t, {}))
    out = {}
    for name, (lat, lng) in regions.items():
        try:
            r = plist(menu_word, str(lng), str(lat))
        except Exception:  # noqa: BLE001
            continue
        items = sorted(r["items"], key=lambda it: -int(str(it.get("visitor_reviews") or "0").replace(",", "") or 0))[:per]
        for it in items:
            out.setdefault(it["id"], {**it, "region": name, "region_type": next((t for t, v in REGIONS_BY_TYPE.items() if name in v), "주요 도시")})
        np_.pause()
    return out


# ---------------------------------------------------------------- 실행
def build(slug, place, keywords=None, menu=None, radius=None, our_n=100, comp_n=50, nat_n=30, skip_national=False):
    d = data_dir(slug) / "appeal"
    d.mkdir(parents=True, exist_ok=True)
    pid = _place_id(place)
    print("1/6 우리 매장 페이지 자료")
    our = page_data(pid)
    is_food = bool(FOOD.search(our["category"] or ""))
    radius = radius or (1000 if is_food else 2000)
    print(f"2/6 상권 유형 ({'외식업' if is_food else '외식업 외'}, 반경 {radius}m)")
    our["area"] = area_tags(our["x"], our["y"])
    print(f"   → {our['area']['tags']}")
    print("3/6 메인 키워드 5개")
    kws, kw_basis = main_keywords(our, keywords)
    print(f"   → {kws}")
    (d / "keywords.json").write_text(json.dumps({"keywords": kws, **kw_basis}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("4/6 경쟁사 목록 (키워드 상위 10 + 반경 안 같은·비슷한 업종)")
    comp_list, why = gather_competitors(our, kws, radius)
    our["keyword_ranks"] = why.pop("__our_rank__", [])
    print(f"   → {len(comp_list)}곳")
    comps = {}
    for cid, it in comp_list.items():
        try:
            comps[cid] = {**page_data_retry(cid), "why": why[cid], "distance": it.get("distance")}
        except Exception as e:  # noqa: BLE001
            comps[cid] = {"id": cid, "name": it.get("name"), "error": str(e)[:100], "why": why[cid]}
        np_.pause(2.5 + random.random() * 2)
    nat = {}
    menu_word = menu or (our["review_stats"]["menus"][0].split()[0] if our["review_stats"]["menus"] else our["category"])
    if not skip_national:
        print(f"5/6 전국 같은 업종 ('{menu_word}', 주요 도시 5곳 + {our['area']['tags']} 대표 지역)")
        nat_list = gather_national(our, menu_word, our["area"]["tags"])
        for nid, it in nat_list.items():
            try:
                nat[nid] = {**page_data_retry(nid), "region": it["region"], "region_type": it["region_type"]}
            except Exception as e:  # noqa: BLE001
                nat[nid] = {"id": nid, "name": it.get("name"), "error": str(e)[:100], "region": it["region"]}
            np_.pause(2.5 + random.random() * 2)
        print(f"   → {len(nat)}곳")
    print("6/6 리뷰 본문·쿠폰 (브라우저, 시간이 걸립니다)")
    jobs = [[pid, our_n]] + [[c, comp_n] for c in comps] + [[n, nat_n] for n in nat]
    raw = {}
    for i in range(0, len(jobs), 8):  # 8곳씩 나눠서
        raw.update(browse_reviews(slug, jobs[i:i + 8], f"reviews {i // 8 + 1}"))
        print(f"   리뷰 {min(i + 8, len(jobs))}/{len(jobs)}곳")
        time.sleep(2 + random.random() * 3)
    for store in [our] + list(comps.values()) + list(nat.values()):
        r = raw.get(store["id"], {})
        store["reviews"] = [parse_review(t) for t in r.get("reviews", [])]
        store["review_summary"] = review_summary(store["reviews"])
        store["coupons"] = r.get("coupons", [])
    # 경쟁사·전국 매장 상권 유형: 우리와 600m 넘게 떨어진 곳과 전국 매장만 따로 계산
    for store in list(comps.values()) + list(nat.values()):
        if store.get("x") and (store in nat.values() or (dist_m(store.get("distance")) or 0) > 600):
            store["area"] = area_tags(store["x"], store["y"])
        else:
            store["area"] = {"tags": our["area"]["tags"], "note": "우리 매장과 같은 상권(600m 이내)"}
    meta = {"collected": date.today().isoformat(), "radius_m": radius, "keywords": kws, "menu_word": menu_word}
    for name, obj in (("our", our), ("competitors", comps), ("national", nat)):
        (d / f"{name}.json").write_text(json.dumps({"meta": meta, "data": obj}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_summary(d, our, comps, nat, meta)
    print(f"저장: {d}")


def _price_range(menus):
    ps = []
    for m in menus:
        v = re.sub(r"[^\d]", "", str(m.get("price") or ""))
        if v and 1000 <= int(v) <= 500000:
            ps.append(int(v))
    return f"{min(ps):,}~{max(ps):,}원 (중간 {sorted(ps)[len(ps) // 2]:,})" if ps else "-"


def write_summary(d, our, comps, nat, meta):
    def row(s, kind):
        rs = s.get("review_summary") or {}
        st = s.get("review_stats") or {}
        sit = ", ".join(f"{k} {v}" for k, v in (rs.get("with") or [])[:3])
        tm = ", ".join(f"{k} {v}" for k, v in (rs.get("time") or [])[:2])
        return (f"| {kind} | {s.get('name')} | {s.get('category') or '-'} | {s.get('visitor_reviews') or '-'} / {s.get('blog_reviews') or '-'} | "
                f"{', '.join((st.get('liked') or [])[:3]) or '-'} | {', '.join((st.get('menus') or [])[:3]) or '-'} | {_price_range(s.get('menus') or [])} | "
                f"{tm or '-'} · {sit or '-'} | {', '.join((s.get('area') or {}).get('tags') or [])} |")
    md = [f"# 소구점 분석 자료 — {our['name']} ({meta['collected']})", "",
          f"- 메인 키워드: {', '.join(meta['keywords'])} · 우리 순위: {', '.join(our.get('keyword_ranks') or []) or '상위 10 밖'}",
          f"- 반경 {meta['radius_m']}m · 전국 조사 메뉴: {meta['menu_word']} · 우리 상권 유형: {', '.join(our['area']['tags'])}",
          f"- 우리 교통: {', '.join(our.get('transport') or []) or '-'}", "",
          "| 구분 | 매장 | 업종 | 방문자/블로그 리뷰 | 리뷰 키워드 상위 | 메뉴 언급 상위 | 가격대 | 방문 시간·동행 (리뷰 표본) | 상권 유형 |",
          "|---|---|---|---|---|---|---|---|---|", row(our, "우리")]
    md += [row(s, "경쟁") for s in comps.values()]
    md += [row(s, f"전국·{s.get('region')}") for s in nat.values()]
    md += ["", "## 매장별 상세"]
    for kind, s in [("우리", our)] + [("경쟁", s) for s in comps.values()] + [(f"전국·{s.get('region')}", s) for s in nat.values()]:
        rs = s.get("review_summary") or {}
        md += [f"### [{kind}] {s.get('name')}" + (f" — {', '.join(s.get('why') or [])}" if s.get("why") else ""),
               f"- 소개글: {(s.get('description') or '-')[:300]}",
               f"- 한 줄 소개·편의: {s.get('micro_review') or '-'} / {', '.join(s.get('conveniences') or [])[:150] or '-'}",
               "- 메뉴: " + ("; ".join(f"{m['name']} {m['price'] or ''}" + (f" ({m['desc'][:40]})" if m.get("desc") else "") for m in (s.get("menus") or [])[:15]) or "-"),
               f"- 리뷰 키워드: {', '.join((s.get('review_stats') or {}).get('liked') or []) or '-'}",
               f"- 특징 언급: {', '.join((s.get('review_stats') or {}).get('themes') or []) or '-'}",
               f"- 방문 상황(표본 {rs.get('n')}): 시간 {rs.get('time')} · 목적 {rs.get('purpose')} · 동행 {rs.get('with')} · 재방문 {rs.get('revisit_share')}%",
               f"- 리뷰 본문 자주 나온 말: {', '.join(f'{w} {c}' for w, c in (rs.get('scene_words') or [])[:15]) or '-'}",
               f"- 쿠폰: {' / '.join(s.get('coupons') or []) or '-'} · 소식: " + ("; ".join(f"{f['title']}({f['date']})" for f in (s.get('feed') or [])[:4]) or "-"),
               f"- 상권: {', '.join((s.get('area') or {}).get('tags') or [])} · 교통: {', '.join(s.get('transport') or []) or '-'}", ""]
    md.append("- 다음: `proposals/APPEAL_GUIDE.md` 대로 appeal_report.md 를 쓴다 (리뷰 본문은 json 의 reviews).")
    (d / "appeal_data.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="경쟁사·소구점 분석 자료 수집")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--place", required=True)
    ap.add_argument("--keywords")
    ap.add_argument("--menu")
    ap.add_argument("--radius", type=int)
    ap.add_argument("--our-reviews", type=int, default=100)
    ap.add_argument("--comp-reviews", type=int, default=50)
    ap.add_argument("--nat-reviews", type=int, default=30)
    ap.add_argument("--skip-national", action="store_true")
    a = ap.parse_args()
    build(a.slug, a.place, a.keywords, a.menu, a.radius, a.our_reviews, a.comp_reviews, a.nat_reviews, a.skip_national)


if __name__ == "__main__":
    main()
