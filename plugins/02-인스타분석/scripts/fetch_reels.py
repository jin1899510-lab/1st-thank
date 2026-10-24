"""Apify instagram-reel-scraper로 인스타 계정의 릴스를 최신순으로 가져온다.

사용법:
    APIFY_TOKEN=... python3 fetch_reels.py <계정아이디> [개수] [옵션]

옵션:
    --shares       공유 수도 가져오기 (Apify 유료 요금제만)
    --transcript   음성 받아쓰기도 가져오기
    --video        영상 파일 사본도 Apify에 저장하기 (인스타 링크 만료 대비)
    --out 폴더     결과 저장 폴더 (기본: 고객설정/인스타분석/<계정아이디>/<날짜>)

결과:
    reels_raw.json  Apify가 준 원본 데이터
    reels.csv       릴스별 요약 표 (조회수·좋아요·댓글·공유·길이·링크)

토큰은 코드에 쓰지 않고 환경변수 APIFY_TOKEN에서 읽는다.
결과에는 남의 계정 정보가 들어가므로 저장소 밖(고객설정 폴더)에 저장한다.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

API = "https://api.apify.com/v2"
ACTOR = "apify~instagram-reel-scraper"
POLL_SECS = 5
MAX_WAIT_SECS = 30 * 60

CSV_FIELDS = [
    ("게시일", "timestamp"),
    ("링크", "url"),
    ("조회수", "videoViewCount"),
    ("재생수", "videoPlayCount"),
    ("좋아요", "likesCount"),
    ("댓글", "commentsCount"),
    ("공유", "sharesCount"),
    ("길이(초)", "videoDuration"),
    ("캡션", "caption"),
    ("영상주소", "videoUrl"),
]


def default_out_dir(username):
    base = os.environ.get("SOHO_CUSTOMER_DIR")
    if not base:
        base = r"C:\작업\고객설정" if os.name == "nt" else str(Path.home() / "작업" / "고객설정")
    return Path(base) / "인스타분석" / username / datetime.now().strftime("%Y%m%d_%H%M")


def parse_args(argv):
    opts = {"shares": False, "transcript": False, "video": False, "out": None}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--shares", "--transcript", "--video"):
            opts[a[2:]] = True
        elif a == "--out" and i + 1 < len(argv):
            opts["out"] = argv[i + 1]
            i += 1
        else:
            rest.append(a)
        i += 1
    if not rest:
        sys.exit(__doc__)
    username = rest[0].strip().lstrip("@").rstrip("/").split("/")[-1]
    limit = int(rest[1]) if len(rest) > 1 else 10
    return username, limit, opts


def run_actor(session, actor_input):
    resp = session.post(f"{API}/acts/{ACTOR}/runs", json=actor_input, timeout=60)
    if resp.status_code == 401:
        sys.exit("APIFY_TOKEN이 올바르지 않습니다. Apify 콘솔 → Settings → API & Integrations 에서 확인하세요.")
    resp.raise_for_status()
    run = resp.json()["data"]
    print(f"Apify 실행 시작 (run {run['id']}) — 보통 1~3분 걸립니다.")

    waited = 0
    while run["status"] in ("READY", "RUNNING"):
        if waited >= MAX_WAIT_SECS:
            sys.exit(f"{MAX_WAIT_SECS // 60}분이 지나도 끝나지 않았습니다. Apify 콘솔에서 run {run['id']}를 확인하세요.")
        time.sleep(POLL_SECS)
        waited += POLL_SECS
        resp = session.get(f"{API}/actor-runs/{run['id']}", timeout=60)
        resp.raise_for_status()
        run = resp.json()["data"]

    if run["status"] != "SUCCEEDED":
        sys.exit(f"Apify 실행 실패: {run['status']} (run {run['id']})")

    resp = session.get(
        f"{API}/datasets/{run['defaultDatasetId']}/items",
        params={"clean": "true", "format": "json"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    username, limit, opts = parse_args(sys.argv[1:])
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("환경변수 APIFY_TOKEN이 없습니다.")

    actor_input = {
        "username": [username],
        "resultsLimit": limit,
        "skipPinnedPosts": True,
        "includeSharesCount": opts["shares"],
        "includeTranscript": opts["transcript"],
        "includeDownloadedVideo": opts["video"],
    }

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    items = run_actor(session, actor_input)

    errors = [it for it in items if it.get("error")]
    reels = [it for it in items if not it.get("error")]
    if not reels:
        msg = errors[0].get("errorDescription") or errors[0].get("error") if errors else "결과 없음"
        sys.exit(f"릴스를 가져오지 못했습니다: {msg} (계정 아이디·공개 계정 여부 확인)")
    reels.sort(key=lambda r: r.get("timestamp") or "", reverse=True)

    out_dir = Path(opts["out"]) if opts["out"] else default_out_dir(username)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reels_raw.json").write_text(json.dumps(reels, ensure_ascii=False, indent=2), encoding="utf-8")

    # utf-8-sig: 엑셀에서 한글이 깨지지 않게
    with open(out_dir / "reels.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([name for name, _ in CSV_FIELDS])
        for r in reels:
            writer.writerow([r.get(key, "") for _, key in CSV_FIELDS])

    print(f"@{username} 릴스 {len(reels)}개 저장 → {out_dir}")
    for r in reels:
        views = r.get("videoPlayCount") or r.get("videoViewCount") or 0
        print(f"  {(r.get('timestamp') or '')[:10]}  조회 {views:>9,}  좋아요 {r.get('likesCount') or 0:>7,}  {r.get('url', '')}")


if __name__ == "__main__":
    main()
