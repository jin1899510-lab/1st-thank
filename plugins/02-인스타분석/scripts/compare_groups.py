"""상위 그룹과 하위 그룹의 수치 차이를 표로 만든다.

사용법:
    python3 compare_groups.py <결과폴더> [그룹크기]

    결과폴더 안에 reels_raw.json(fetch_reels.py)과
    해부_결과.json(Claude가 templates/해부기준.md 대로 작성)이 있어야 한다.

결과:
    상위하위_비교.md  반응 숫자 + 해부 항목별 상위/하위 평균·비율 비교
"""
import json
import sys
from pathlib import Path

from prepare_dissect import split_groups, views


def avg(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(values) / len(values) if values else None


def ratio(values, test):
    values = [v for v in values if v is not None]
    return sum(1 for v in values if test(v)) / len(values) * 100 if values else None


def fmt(v, pct=False):
    if v is None:
        return "불명"
    return f"{v:.0f}%" if pct else (f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}")


def get(d, path):
    for key in path.split("."):
        d = d.get(key) if isinstance(d, dict) else None
    return d


def rate(r, key):
    v = views(r)
    return r.get(key) / v * 100 if v and isinstance(r.get(key), (int, float)) and r.get(key) >= 0 else None


RAW_ROWS = [
    ("조회수", lambda r: views(r)),
    ("좋아요", lambda r: r.get("likesCount") if (r.get("likesCount") or 0) >= 0 else None),
    ("댓글", lambda r: r.get("commentsCount")),
    ("공유", lambda r: r.get("sharesCount")),
    ("좋아요율(%)", lambda r: rate(r, "likesCount")),
    ("댓글율(%)", lambda r: rate(r, "commentsCount")),
    ("길이(초)", lambda r: r.get("videoDuration")),
    ("캡션 글자수", lambda r: len(r.get("caption") or "")),
]

# (표시 이름, 경로, 종류) 종류: avg=평균, yes=참 비율, has=값 있음 비율
DISSECT_ROWS = [
    ("텍스트 채널 겹친 개수", "L1.텍스트채널", "count"),
    ("미끼 비율", "L1.미끼", "yes"),
    ("첫 발화 3초 안", "L1.첫발화3초", "yes"),
    ("일한 채널 수 (0~3)", "L1.일한채널수", "avg"),
    ("정보 항목 수", "L2.정보항목수", "avg"),
    ("항목당 초", "L2.항목당초", "avg"),
    ("보류 장치 위치(%)", "L2.보류장치.퍼센트", "avg"),
    ("캡션 첫 줄 후킹", "L3.캡션첫줄후킹", "yes"),
    ("총정리·순위형", "L3.총정리형", "yes"),
]


def dissect_value(d, path, kind):
    v = get(d, path) if d else None
    if kind == "count":
        return len(v) if isinstance(v, list) else None
    return v


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    reels = json.loads((folder / "reels_raw.json").read_text(encoding="utf-8"))
    top, bottom = split_groups(reels, size)
    if not bottom:
        sys.exit(f"하위 그룹이 없습니다. fetch_reels.py로 {size * 2}개 이상 가져오세요.")

    dissect_path = folder / "해부_결과.json"
    dissected = {}
    if dissect_path.exists():
        dissected = {d["url"]: d for d in json.loads(dissect_path.read_text(encoding="utf-8"))}

    lines = [
        "# 상위 / 하위 그룹 비교",
        "",
        f"상위 {len(top)}개 vs 하위 {len(bottom)}개 (조회수 기준)",
        "",
        "## 반응 숫자 (평균)",
        "",
        "| 항목 | 상위 | 하위 | 차이(배) |",
        "|---|---|---|---|",
    ]
    for name, fn in RAW_ROWS:
        a, b = avg([fn(r) for r in top]), avg([fn(r) for r in bottom])
        times = f"{a / b:.1f}" if a is not None and b else "-"
        lines.append(f"| {name} | {fmt(a)} | {fmt(b)} | {times} |")

    lines += ["", "## 해부 항목", ""]
    if not dissected:
        lines.append("(해부_결과.json 이 없어 생략)")
    else:
        lines += ["| 항목 | 상위 | 하위 | 해부된 수 (상위/하위) |", "|---|---|---|---|"]
        for name, path, kind in DISSECT_ROWS:
            tv = [dissect_value(dissected.get(r.get("url")), path, kind) for r in top]
            bv = [dissect_value(dissected.get(r.get("url")), path, kind) for r in bottom]
            if kind == "yes":
                a, b = ratio(tv, bool), ratio(bv, bool)
                cells = (fmt(a, pct=True), fmt(b, pct=True))
            else:
                cells = (fmt(avg(tv)), fmt(avg(bv)))
            n = (sum(v is not None for v in tv), sum(v is not None for v in bv))
            lines.append(f"| {name} | {cells[0]} | {cells[1]} | {n[0]}/{n[1]} |")

    out = folder / "상위하위_비교.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"비교표 저장 → {out}")


if __name__ == "__main__":
    main()
