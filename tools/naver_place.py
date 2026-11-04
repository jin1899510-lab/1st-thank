"""네이버 플레이스·통합검색 수집 (모바일 페이지의 __APOLLO_STATE__를 읽는다)."""
import json
import re
import time

import requests

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
APOLLO = re.compile(r"window.__APOLLO_STATE__\s*=\s*(\{.*?\});\s*window", re.S)


def _apollo(url, params=None):
    r = _get(url, params)
    r.encoding = "utf-8"
    m = APOLLO.search(r.text)
    if not m:
        raise RuntimeError(f"APOLLO_STATE 없음: {url} ({r.status_code})")
    return json.loads(m.group(1))


def place_raw(pid):
    """매장 홈 페이지의 원본 상태값 전체."""
    return _apollo(f"https://m.place.naver.com/restaurant/{pid}/home")


def place_detail(pid, raw=None):
    """매장 핵심 정보: 리뷰·사진·쿠폰·소식·편의시설·영업시간·좌표 등."""
    d = raw or place_raw(pid)
    base = d.get(f"PlaceDetailBase:{pid}", {})
    pd = d["ROOT_QUERY"][next(k for k in d["ROOT_QUERY"] if k.startswith("placeDetail"))]
    vs = next((v for k, v in d.items() if k.startswith("VisitorReviewStatsResult")), {})
    voted = ((vs.get("analysis") or {}).get("votedKeyword") or {}).get("details", [])
    hours = []
    for nb in pd.get("newBusinessHours") or []:
        for h in nb.get("businessHours") or []:
            bh = h.get("businessHours") or {}
            hours.append({
                "day": h.get("day"),
                "open": bh.get("start"),
                "close": bh.get("end"),
                "break": [(b.get("start"), b.get("end")) for b in h.get("breakHours") or []],
                "note": h.get("description"),
            })
    coord = base.get("coordinate") or {}
    return {
        "id": pid,
        "name": base.get("name"),
        "category": base.get("category"),
        "road_address": base.get("roadAddress"),
        "address": base.get("address"),
        "phone": base.get("phone") or base.get("virtualPhone"),
        "x": coord.get("x"),
        "y": coord.get("y"),
        "conveniences": base.get("conveniences"),
        "micro_review": base.get("microReviews"),
        "visitor_reviews": (vs.get("review") or {}).get("totalCount") or base.get("visitorReviewsTotal"),
        "blog_reviews": base.get("cafeBlogReviewsTotal"),
        "images": (pd.get("images") or {}).get("totalImages"),
        "coupon": (pd.get("hasCoupon") or {}).get("count"),
        "news_feed": bool((pd.get("hasFeed") or {}).get("feedExist")),
        "booking": bool(pd.get("naverBooking")),
        "naver_order": {k: (pd.get("naverOrder") or {}).get(k) for k in ("isPickup", "isDelivery")},
        "description": pd.get("description"),
        "voted_keywords": [(x["displayName"], x["count"]) for x in voted],
        "hours": hours,
        "homepage": (((pd.get("homepages") or {}).get("repr")) or {}).get("url"),
        "road": base.get("road"),
    }


def place_list(query, x, y):
    """매장 위치 기준 모바일 플레이스 검색 상위 10곳 (네이버가 10곳만 준다)."""
    d = _apollo("https://m.place.naver.com/restaurant/list",
                {"query": query, "x": x, "y": y, "start": 1, "display": 10})
    rq = d["ROOT_QUERY"]
    k = next(k for k in rq if k.startswith("placeList(") and "filterOpening" not in k)
    b = rq[k]["businesses"]
    items = []
    for ref in b["items"]:
        i = d[ref["__ref"]]
        items.append({
            "id": i["id"], "name": i["name"], "category": i.get("category"),
            "visitor_reviews": i.get("visitorReviewCount"), "blog_reviews": i.get("blogCafeReviewCount"),
            "distance": i.get("distance"), "road_address": i.get("roadAddress"),
        })
    return {"total": b["total"], "items": items}


def _get(url, params, tries=3):
    for n in range(tries):
        try:
            return requests.get(url, params=params, headers={"User-Agent": UA}, timeout=20)
        except requests.RequestException:
            if n == tries - 1:
                raise
            time.sleep(3 * (n + 1))


def search_exposure(query, pid):
    """모바일 통합검색: 플레이스 순서, AI 브리핑 여부, 파워링크 광고주."""
    r = _get("https://m.search.naver.com/search.naver", {"query": query, "where": "m"})
    r.encoding = "utf-8"
    h = r.text
    ids = []
    for m in re.finditer(r"place\.naver\.com/(?:restaurant|place)/(\d+)", h):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    powerlink = []
    i = h.find("PowerLink_")
    if i >= 0:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h[i:i + 6000]))
        powerlink = [txt[:300]]
    return {
        "place_rank": ids.index(pid) + 1 if pid in ids else None,
        "ai_briefing": "footnoteSources" in h,
        "powerlink_snippet": powerlink,
    }


def within_m(distance, limit_m):
    """'240m' / '1.2km' 문자열이 limit_m 안인지."""
    if not distance:
        return False
    if distance.endswith("km"):
        return float(distance[:-2]) * 1000 <= limit_m
    if distance.endswith("m"):
        return float(distance[:-1]) <= limit_m
    return False


def pause(sec=1.2):
    time.sleep(sec)
