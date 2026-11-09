"""네이버 검색광고 API — 키워드 월간 검색수·클릭·경쟁 정도 (애드로그 호출 한도 없이).

키 (코드·저장소에 넣지 않는다). 아래 둘 중 하나:
  1) 환경 변수 NAVER_AD_CUSTOMER_ID, NAVER_AD_ACCESS_LICENSE, NAVER_AD_SECRET_KEY
  2) 사용자 폴더의 파일  C:/Users/<이름>/.naver_ad.json
       {"customer_id": "1234567", "access_license": "...", "secret_key": "..."}
  키 발급: searchad.naver.com → 도구 → API 사용 관리

사용법:
    python tools/naver_ad.py --slug song-law --keywords "변호사,법무법인,강남변호사" [--out naver_ad_volume.json]
    python tools/naver_ad.py --keywords "변호사"            # 화면에만 출력

- 한 번에 키워드 5개씩 묻는다(API 제한). 응답에서 띄어쓰기를 뺀 같은 키워드만 골라 저장한다.
- 월간 검색수는 최근 30일 기준, '< 10'은 10회 미만. compIdx = 경쟁 정도(낮음/중간/높음), plAvgDepth = 평균 노출 광고 수.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.searchad.naver.com"


def keys():
    cid, lic, sec = (os.environ.get(k) for k in ("NAVER_AD_CUSTOMER_ID", "NAVER_AD_ACCESS_LICENSE", "NAVER_AD_SECRET_KEY"))
    if not all((cid, lic, sec)):
        f = Path.home() / ".naver_ad.json"
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            cid, lic, sec = j.get("customer_id"), j.get("access_license"), j.get("secret_key")
    if not all((cid, lic, sec)):
        sys.exit("네이버 검색광고 API 키가 없습니다. 환경 변수 NAVER_AD_* 또는 ~/.naver_ad.json 을 만들어 주세요 (파일 맨 위 설명).")
    return str(cid), lic, sec


def _headers(method, uri, cid, lic, sec):
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(sec.encode(), f"{ts}.{method}.{uri}".encode(), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": lic, "X-Customer": cid, "X-Signature": sig}


def volumes(keywords):
    cid, lic, sec = keys()
    want = {k.replace(" ", ""): k for k in keywords}
    out = {}
    items = list(want)
    for i in range(0, len(items), 5):
        chunk = items[i:i + 5]
        for attempt in range(3):
            r = requests.get(BASE + "/keywordstool", params={"hintKeywords": ",".join(chunk), "showDetail": 1},
                             headers=_headers("GET", "/keywordstool", cid, lic, sec), timeout=30)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            r.raise_for_status()
            break
        for row in r.json().get("keywordList", []):
            k = row["relKeyword"].replace(" ", "")
            if k in want and k not in out:
                pc, mo = row.get("monthlyPcQcCnt"), row.get("monthlyMobileQcCnt")
                num = lambda v: v if isinstance(v, int) else None
                out[k] = {"키워드": k, "PC 검색수": pc, "MO 검색수": mo,
                          "총 검색수": (num(pc) or 0) + (num(mo) or 0) if (num(pc) is not None or num(mo) is not None) else "< 10",
                          "PC 클릭수": row.get("monthlyAvePcClkCnt"), "MO 클릭수": row.get("monthlyAveMobileClkCnt"),
                          "PC 클릭률": row.get("monthlyAvePcCtr"), "MO 클릭률": row.get("monthlyAveMobileCtr"),
                          "경쟁률": row.get("compIdx"), "평균광고수": row.get("plAvgDepth")}
        time.sleep(0.4)
    return out, [k for k in want if k not in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--out", default="naver_ad_volume.json")
    a = ap.parse_args()
    kws = [k.strip() for k in a.keywords.split(",") if k.strip()]
    rows, missing = volumes(kws)
    if a.slug:
        d = ROOT / "proposals" / a.slug / "data"
        d.mkdir(parents=True, exist_ok=True)
        obj = {"source": f"네이버 검색광고 API keywordstool, {date.today().isoformat()} 조회 (최근 30일 월간 검색수, '< 10'은 10회 미만)",
               "rows": [rows[k.replace(' ', '')] for k in kws if k.replace(' ', '') in rows], "missing": missing}
        (d / a.out).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(rows)}개 저장: {d / a.out}" + (f" (없음: {', '.join(missing)})" if missing else ""))
    else:
        for k, v in rows.items():
            print(k, v["총 검색수"], f"(PC {v['PC 검색수']} / MO {v['MO 검색수']})", v["경쟁률"])


if __name__ == "__main__":
    main()
