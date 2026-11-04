"""애드로그(adlog.kr) 수집: 플레이스 분석·히든 키워드 순위, 키워드 월간 검색수.

환경 변수 ADLOG_ID, ADLOG_PW 가 필요하다.
"""
import json
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.adlog.kr/adlog/"


def session():
    if not os.environ.get("ADLOG_ID") or not os.environ.get("ADLOG_PW"):
        sys.exit("ADLOG_ID / ADLOG_PW 환경 변수가 없습니다.")
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get("https://www.adlog.kr/bbs/login.php")
    s.post("https://www.adlog.kr/bbs/login_check.php",
           data={"mb_id": os.environ["ADLOG_ID"], "mb_password": os.environ["ADLOG_PW"],
                 "url": "/adlog/naver_place_rank.php"})
    return s


def _post_json(s, path, body, referer):
    s.headers["Referer"] = BASE + referer
    r = s.post(BASE + path, json=body, timeout=60)
    r.encoding = "utf-8"
    t = r.text.strip()
    return json.loads(t) if t else None


def place_analysis(s, pid):
    """플레이스 기본 정보와, 매장이 잡혀 있는 키워드별 순위(최근 30일 이력)."""
    info = _post_json(s, "ajax_place_detail_info.php", {"place_id": pid}, "naver_place.php")
    hist = _post_json(s, "ajax_place_compare.php", {"place_id": pid, "mode": "history", "days": 30},
                      "naver_place.php")
    kws = (hist or {}).get(str(pid), {})
    ranks = sorted(
        ({"keyword": k, "rank": v.get("place_rank"), "change": v.get("place_change"),
          "date": v.get("place_date"), "history": [(h["place_date"], h["place_rank"]) for h in v.get("history", [])]}
         for k, v in kws.items()),
        key=lambda x: x["rank"] or 9999)
    return {"info": info, "keyword_ranks": ranks}


def search_volume(s, keywords):
    """키워드 월간 검색수(PC·모바일). 애드로그 검색광고 키워드 도구에 등록한 뒤 표를 읽는다."""
    s.headers["Referer"] = BASE + "naver_keyword_searchad.php"
    for kw in keywords:
        s.post(BASE + "ajax_search.php", data={
            "api_section": 10, "api_type": 10, "group_no": 0, "keyword": kw.replace(" ", ""), "keyword2": "",
            "blog_info": "", "api_check_keyword": "", "api_check_keyword2": "",
            "api_geo_x": "", "api_geo_y": "", "api_place_local": ""}, timeout=60)
        time.sleep(1.5)
    r = s.get(BASE + "naver_keyword_searchad.php")
    r.encoding = "utf-8"
    table = BeautifulSoup(r.text, "html.parser").find_all("table")[0]
    want = {k.replace(" ", "") for k in keywords}
    out = {}
    for tr in table.find_all("tr"):
        c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(c) < 9 or c[1] not in want or c[1] in out:
            continue
        num = lambda v: int(v.replace(",", "")) if v.replace(",", "").isdigit() else None  # 빈칸 = 10 미만
        out[c[1]] = {"pc": num(c[2]), "mobile": num(c[3]), "total": num(c[4]),
                     "click_pc": c[5], "click_mobile": c[6], "ctr_pc": c[7], "ctr_mobile": c[8]}
    return out
