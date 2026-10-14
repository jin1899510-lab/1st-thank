"""adlog.kr 메인에 노출되는 '네이버 플레이스 공지'에서 새 공지를 찾는다.

사용법:
    ADLOG_ID=... ADLOG_PW=... python3 adlog_place_notice.py           # 새 공지만
    ADLOG_ID=... ADLOG_PW=... python3 adlog_place_notice.py --latest  # 최신 공지 1건(예시용)

결과:
    output/new_place_notices.json   새 공지 목록
    cards/notice_<번호>.json         카드뉴스 초안(이미 있으면 덮어쓰지 않음)
    data/place_notice_seen.json     이미 확인한 공지 번호
"""
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from adlog_place_rank import BASE, OUT_DIR, login

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "data" / "place_notice_seen.json"
CARD_DIR = ROOT / "cards"
NOTICE_URL = "https://new.smartplace.naver.com/notices/{}"


def fetch_notices(session: requests.Session):
    resp = session.get(f"{BASE}/adlog/")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    box = next(
        (w for w in soup.select(".blog_notice_warp")
         if "플레이스 공지" in w.select_one(".blog_notice_title").get_text()),
        None,
    )
    if box is None:
        sys.exit("adlog 메인에서 '네이버 플레이스 공지' 영역을 찾지 못했습니다.")

    notices = []
    for item in box.select(".blog_notice_wr_title"):
        a = item.find("a", href=True)
        m = re.search(r"/notices/(\d+)", a["href"])
        if not m:
            continue
        service = a.select_one(".place_service")
        category = a.select_one(".place_class")
        date = item.select_one("div.fr")
        notices.append({
            "id": int(m.group(1)),
            "service": service.get_text(strip=True) if service else "",
            "category": category.get_text(strip=True) if category else "",
            "title": a.find_all("span")[-1].get_text(strip=True),
            "date": date.get_text(strip=True) if date else "",
            "url": NOTICE_URL.format(m.group(1)),
        })
    return notices


def fetch_body(notice) -> str:
    """원문 본문. 네이버 접속이 막힌 환경에서는 빈 문자열."""
    try:
        resp = requests.get(notice["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    og = soup.find("meta", property="og:description")
    return og["content"].strip() if og and og.get("content") else ""


def make_draft(notice) -> dict:
    """제목·분류만으로 만든 카드뉴스 초안. 본문 요약 카드는 직접 채운다."""
    tag = " · ".join(t for t in (notice["service"], notice["category"]) if t)
    return {
        "id": notice["id"],
        "source": notice["url"],
        "date": notice["date"],
        "cards": [
            {"type": "cover", "tag": f"네이버 플레이스 공지 · {tag}",
             "title": re.sub(r"^\[[^\]]+\]\s*", "", notice["title"]), "sub": notice["date"]},
            {"type": "point", "label": "무슨 공지?", "title": notice["title"],
             "body": [notice.get("body") or "(원문을 보고 핵심 1~2줄로 채우기)"]},
            {"type": "list", "label": "지금 할 일", "title": "사장님 체크리스트",
             "items": ["(조치 1)", "(조치 2)", "(조치 3)"]},
            {"type": "end", "title": "원문에서 자세히 확인하세요", "url": notice["url"]},
        ],
    }


def main() -> None:
    latest_only = "--latest" in sys.argv
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    login(session)

    notices = fetch_notices(session)
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()

    if latest_only:
        targets = [max(notices, key=lambda n: (n["date"], n["id"]))]
    else:
        targets = [n for n in notices if n["id"] not in seen]
        if not seen:  # 첫 실행: 기존 공지는 '확인함'으로만 기록
            targets = []

    for n in targets:
        n["body"] = fetch_body(n)
        card_file = CARD_DIR / f"notice_{n['id']}.json"
        if not card_file.exists():
            CARD_DIR.mkdir(exist_ok=True)
            card_file.write_text(json.dumps(make_draft(n), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{n['date']}] #{n['id']} {n['title']}\n  {n['url']}\n  카드 초안: {card_file}")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "new_place_notices.json").write_text(
        json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen | {n["id"] for n in notices})))

    if not targets:
        print("새로 올라온 플레이스 공지가 없습니다.")


if __name__ == "__main__":
    main()
