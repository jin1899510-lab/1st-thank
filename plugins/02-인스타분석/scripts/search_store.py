"""가게 이름(+지역)으로 네이버 검색을 읽어 원고용 기본 정보를 모은다.

사용법:
    python3 search_store.py "가게 이름 지역" [--out 결과.json]

결과 (화면 출력, --out 이면 파일로도 저장):
    네이버 플레이스 카드에서: 주소, 영업시간, 전화, 편의시설, 메뉴·가격, 플레이스 번호
    검색 결과 글에서:          가게 소개·특징 문장 (셀링포인트 후보, 출처 표시용 원문 일부)

검색 결과는 사실 확인 없이 원고에 넣지 않는다. Claude가 이 결과를 요약해
'내 콘텐츠 정보' 칸을 채우고, 채운 칸은 "검색으로 채움"으로 표시해 사장님이 확인하게 한다.
네이버 화면 구조가 바뀌면 일부 항목이 비어 나올 수 있다 (그때는 빈칸으로 둔다).
"""
import html
import json
import re
import sys
from urllib.parse import quote

import requests

SEARCH = "https://m.search.naver.com/search.naver?query="
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"


def page_text(raw):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def between(text, start, ends, limit=300):
    i = text.find(start)
    if i < 0:
        return None
    chunk = text[i + len(start): i + len(start) + limit]
    cut = min([chunk.find(e) for e in ends if chunk.find(e) >= 0] or [len(chunk)])
    return chunk[:cut].strip() or None


def parse(raw, query):
    text = page_text(raw)
    info = {"query": query, "source": SEARCH + quote(query)}
    place = re.search(r"place\.naver\.com/(?:restaurant|place|cafe|hairshop|accommodation)/(\d+)", raw)
    if place:
        info["place_id"] = place.group(1)
        info["place_url"] = f"https://m.place.naver.com/place/{place.group(1)}/home"
    info["address"] = between(text, "주소 ", [" 지도", " 내비게이션", " 거리뷰"], 120)
    hours = between(text, "영업시간 ", [" 펼쳐보기", " 전화번호", " 편의"], 120)
    info["hours"] = hours
    phone = re.search(r"전화번호 (\d{2,4}-\d{3,4}-\d{4})", text)
    info["phone"] = phone.group(1) if phone else None
    info["amenities"] = between(text, "편의 ", [" 메뉴", " 정보", " 홈페이지"], 150)

    menu_block = between(text, "메뉴판 이미지 ", [" 더보기", " AI 브리핑", " 이 장소와"], 600) or ""
    info["menu"] = [{"name": n.strip(), "price": p + "원"} for n, p in re.findall(r"(.+?) ([\d,]{3,}) 원", menu_block)][:15]

    # 검색 결과의 소개·요약 문장 (셀링포인트 후보). 광고·비슷한 장소 목록은 빼고 앞부분만.
    facts, seen = [], set()
    start = text.find("관련질문")
    block = text[start: start + 4000] if start >= 0 else ""
    # "질문? 출처 N건 AI 요약으로 … 있어요." 꼬리표를 지우고 문장 단위로 나눈다
    block = re.sub(r"[^.?!]*\? 출처 \d+건 AI 요약으로 정확하지 않은 정보가 포함될 수 있어요\.", " ", block)
    for sentence in re.split(r"(?<=[.!])\s+", block):
        s = sentence.strip()
        if len(s) < 15 or s.endswith("?") or "AI" in s[:20] or "관련질문" in s:
            continue
        key = re.sub(r"\W", "", s)[:30]
        if key not in seen:
            seen.add(key)
            facts.append(s)
    info["facts"] = facts[:10]
    info["found"] = bool(info.get("address") or info["menu"] or info["facts"])
    return info


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        sys.exit(__doc__)
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    query = " ".join(args).strip()
    resp = requests.get(SEARCH + quote(query), headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    info = parse(resp.text, query)
    data = json.dumps(info, ensure_ascii=False, indent=2)
    print(data)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(data)
    if not info["found"]:
        print("검색 결과에서 가게 정보를 찾지 못했습니다. 지역을 붙이거나 정확한 상호로 다시 검색하세요.", file=sys.stderr)


if __name__ == "__main__":
    main()
