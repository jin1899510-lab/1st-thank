"""애드로그 OpenAPI (https://www.adlog.kr/api/doc/).

인증 키는 세션 환경의 네트워크 시크릿(api.adlog.kr, Authorization: Bearer)으로 프록시가 붙인다.
코드에는 키를 넣지 않는다. user_id 는 환경 변수 ADLOG_ID.

메뉴 코드: 1064 플레이스, 1061 웹사이트, 1067 가격비교, 1040 블로그
- 키워드 등록은 멤버십 슬롯을 쓴다 (다 쓰면 deleteKeyword 로 지운다).
- 순위 데이터(getKeywordListDetail)는 '실사용 전환' 뒤에만 나온다.
- 하루 호출 한도: 멤버십 슬롯 수 × 20.
"""
import os
import time

import requests

BASE = "https://api.adlog.kr/api/"
PLACE, WEBSITE, SHOPPING, BLOG = 1064, 1061, 1067, 1040


def _post(path, **body):
    body["user_id"] = os.environ["ADLOG_ID"]
    r = requests.post(BASE + path, json=body, headers={"content-Type": "application/json"}, timeout=60)
    r.encoding = "utf-8"
    return r.json()


def usage():
    return _post("getUsage.php")


def create_keyword(menu, keyword, target, memo="", group_no=0):
    """target: 플레이스면 업체 ID, 웹사이트·블로그면 URL. 등록 간격 제한(9004)이면 기다렸다 한 번 더."""
    res = _post("createKeyword.php", api_menu=menu, keyword=keyword[:30], keyword2=str(target),
                memo=memo, group_no=group_no)
    if res.get("code") == "9004":
        time.sleep(int(res.get("retry_after") or 10) + 1)
        res = _post("createKeyword.php", api_menu=menu, keyword=keyword[:30], keyword2=str(target),
                    memo=memo, group_no=group_no)
    return res


def list_keywords(menu, page=1, group_no=None):
    body = {"api_menu": menu, "page": page}
    if group_no is not None:
        body["group_no"] = group_no
    return _post("getKeywordList.php", **body)


def keyword_detail(menu, api_no, page=1):
    return _post("getKeywordListDetail.php", api_menu=menu, api_no=api_no, page=page)


def research(menu, api_nos):
    return _post("researchKeyword.php", api_menu=menu, api_no_arr=list(api_nos)[:50])


def delete(menu, api_nos):
    return _post("deleteKeyword.php", api_menu=menu, api_no_arr=list(api_nos), confirm="Y")
