"""adlog.kr 플레이스 순위에서 특정 업체 정보를 가져온다.

사용법:
    ADLOG_ID=... ADLOG_PW=... python3 adlog_place_rank.py [업체명]

결과:
    output/place_rank_raw.html  로그인 후 받은 원본 페이지
    output/place_rank_<업체명>.csv  업체명이 포함된 표 행
"""
import csv
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.adlog.kr"
LOGIN_URL = f"{BASE}/bbs/login_check.php"
PLACE_RANK_PATH = "/adlog/naver_place_rank.php"
OUT_DIR = Path(__file__).parent / "output"


def login(session: requests.Session) -> None:
    user_id = os.environ.get("ADLOG_ID")
    password = os.environ.get("ADLOG_PW")
    if not user_id or not password:
        sys.exit("ADLOG_ID / ADLOG_PW 환경 변수가 설정되지 않았습니다.")

    session.get(f"{BASE}/bbs/login.php")
    resp = session.post(
        LOGIN_URL,
        data={"mb_id": user_id, "mb_password": password, "url": PLACE_RANK_PATH},
    )
    resp.raise_for_status()

    check = session.get(f"{BASE}{PLACE_RANK_PATH}", allow_redirects=False)
    if check.status_code in (301, 302) and "login.php" in check.headers.get("Location", ""):
        sys.exit("로그인 실패: 아이디/비밀번호를 확인하세요.")


def fetch_rows(session: requests.Session, keyword: str):
    resp = session.get(f"{BASE}{PLACE_RANK_PATH}")
    resp.raise_for_status()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "place_rank_raw.html").write_text(resp.text, encoding="utf-8")

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        header = [th.get_text(strip=True) for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if cells and any(keyword in c for c in cells):
                rows.append((header, cells))
    return rows


def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "차앤박"
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"

    login(session)
    rows = fetch_rows(session, keyword)

    if not rows:
        print(f"'{keyword}' 이(가) 포함된 행을 찾지 못했습니다. output/place_rank_raw.html 을 확인하세요.")
        return

    out_csv = OUT_DIR / f"place_rank_{keyword}.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if rows[0][0]:
            writer.writerow(rows[0][0])
        for _, cells in rows:
            writer.writerow(cells)
            print(" | ".join(cells))
    print(f"\n{len(rows)}건 저장: {out_csv}")


if __name__ == "__main__":
    main()
