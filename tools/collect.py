"""업체 하나의 기본 자료를 한 번에 수집해서 proposals/<slug>/data/ 에 저장한다.

사용법:
    python3 tools/collect.py --slug nekonomura --place-id 1573719918 \
        --keywords "장산역 맛집,장산역 초밥,장산역 연어덮밥,해운대 초밥"

저장 파일 (data/):
    place.json          매장 정보 (리뷰·사진·쿠폰·소식·영업시간·좌표)
    place_apollo.json   매장 페이지 원본
    ranks.json          키워드별 모바일 플레이스 상위 10곳과 우리 매장 순위
    competitors.json    상위 10곳 중 반경 안 경쟁 매장 상세
    naver_search.json   통합검색 노출·AI 브리핑·파워링크
    adlog_place.json    애드로그 플레이스 분석·히든 키워드 순위 (ADLOG_ID/PW 있을 때)
    adlog_searchvol.json 키워드 월간 검색수 (ADLOG_ID/PW 있을 때)
    summary.md          위 내용을 사람이 읽기 좋게 요약

구글 지도·웹 검색·AI 검색·트렌드는 이 스크립트 밖에서 한다 (SKILL.md 참고).
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import naver_place as np_  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="proposals/ 아래 폴더 이름 (영문)")
    ap.add_argument("--place-id", required=True, help="네이버 플레이스 ID (링크의 숫자)")
    ap.add_argument("--keywords", required=True, help="쉼표로 구분한 키워드")
    ap.add_argument("--radius", type=int, default=500, help="경쟁 매장 반경(m), 기본 500")
    ap.add_argument("--skip-adlog", action="store_true")
    a = ap.parse_args()

    out = ROOT / "proposals" / a.slug / "data"
    out.mkdir(parents=True, exist_ok=True)
    kws = [k.strip() for k in a.keywords.split(",") if k.strip()]
    pid = a.place_id
    today = date.today().isoformat()

    print("1/5 매장 정보")
    raw = np_.place_raw(pid)
    save(out / "place_apollo.json", raw)
    me = np_.place_detail(pid, raw)
    me["collected"] = today
    save(out / "place.json", me)

    print("2/5 키워드별 플레이스 상위 10곳")
    ranks, near = {}, {}
    for q in kws:
        try:
            r = np_.place_list(q, me["x"], me["y"])
        except Exception as e:  # 한 키워드 실패로 전체를 멈추지 않는다
            print("  실패", q, e)
            continue
        ids = [i["id"] for i in r["items"]]
        r["our_rank_top10"] = ids.index(pid) + 1 if pid in ids else None
        ranks[q] = r
        for i in r["items"]:
            if i["id"] != pid and np_.within_m(i["distance"], a.radius):
                near[i["id"]] = i["distance"]
        print(f"  {q}: 전체 {r['total']}곳, 우리 {r['our_rank_top10'] or '10위 밖'}")
        np_.pause()
    save(out / "ranks.json", {"collected": today, "keywords": ranks})

    print(f"3/5 반경 {a.radius}m 경쟁 매장 {len(near)}곳 상세")
    comps = []
    for cid, dist in near.items():
        try:
            c = np_.place_detail(cid)
            c["distance"] = dist
            comps.append(c)
        except Exception as e:
            print("  실패", cid, e)
        np_.pause()
    comps.sort(key=lambda c: float(c["distance"].rstrip("km")) * (1000 if c["distance"].endswith("km") else 1))
    save(out / "competitors.json", {"collected": today, "radius_m": a.radius, "items": comps})

    print("4/5 통합검색 노출·AI 브리핑·파워링크")
    exp = {}
    for q in [me["name"]] + kws:
        try:
            exp[q] = np_.search_exposure(q, pid)
        except Exception as e:
            print("  실패", q, e)
        np_.pause()
    save(out / "naver_search.json", {"collected": today, "keywords": exp})

    adl, vol = None, None
    if not a.skip_adlog and os.environ.get("ADLOG_ID"):
        print("5/5 애드로그 히든 키워드·검색량")
        import adlog
        s = adlog.session()
        adl = adlog.place_analysis(s, pid)
        save(out / "adlog_place.json", adl)
        vol = adlog.search_volume(s, kws)
        save(out / "adlog_searchvol.json", {"collected": today, "keywords": vol})
    else:
        print("5/5 애드로그 건너뜀 (ADLOG_ID 없음 또는 --skip-adlog)")

    (out / "summary.md").write_text(summary(me, ranks, comps, exp, adl, vol, today), encoding="utf-8")
    print("완료:", out / "summary.md")


def summary(me, ranks, comps, exp, adl, vol, today):
    L = [f"# {me['name']} 수집 요약 ({today})", ""]
    L += [f"- 주소: {me['road_address']} / 카테고리: {me['category']} / 전화: {me['phone']}",
          f"- 방문자 리뷰 {me['visitor_reviews']} · 블로그 리뷰 {me['blog_reviews']} · 사진 {me['images']} · "
          f"쿠폰 {me['coupon'] or 0} · 소식 {'있음' if me['news_feed'] else '없음'} · 예약 {'O' if me['booking'] else 'X'}",
          f"- 리뷰 키워드: {', '.join(f'{k} {n}' for k, n in me['voted_keywords'][:5])}",
          f"- 한 줄 소개(네이버): {', '.join(me['micro_review'] or [])}", ""]
    L += ["## 키워드별 순위·검색량", "", "| 키워드 | 월간 검색수 | 플레이스 상위 10 | 통합검색 | AI 브리핑 |", "|---|---|---|---|---|"]
    for q, r in ranks.items():
        v = (vol or {}).get(q.replace(" ", ""), {})
        e = exp.get(q, {})
        tot = v.get("total") if v else "-"
        if v and not (v.get("pc") or v.get("mobile")):
            tot = "10 미만"
        rank = f"{r['our_rank_top10']}위" if r["our_rank_top10"] else "10위 밖"
        prank = f"{e['place_rank']}번째" if e.get("place_rank") else "-"
        L.append(f"| {q} | {tot} | {rank} | {prank} | {'뜸' if e.get('ai_briefing') else '-'} |")
    if adl:
        L += ["", "## 애드로그 히든 키워드 순위", ""]
        L += [f"- {k['keyword']}: {k['rank']}위 (변동 {k['change']})" for k in adl["keyword_ranks"]]
    L += ["", "## 반경 안 경쟁 매장", "", "| 매장 | 거리 | 리뷰 | 사진 | 쿠폰 | 소식 |", "|---|---|---|---|---|---|"]
    for c in comps:
        L.append(f"| {c['name']} | {c['distance']} | {c['visitor_reviews']} | {c['images']} | "
                 f"{c['coupon'] or '-'} | {'있음' if c['news_feed'] else '-'} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
