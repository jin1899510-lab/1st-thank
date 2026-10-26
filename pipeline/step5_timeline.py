"""5단계: 편집 계획으로 타임라인 표를 만든다 (전체본 + 릴스마다).

결과:
  timeline.md   채팅·메모장용 표 + 요약
  timeline.csv  엑셀용 (한글 깨짐 방지 UTF-8 BOM)

사용 예:
  python step5_timeline.py --client 한방장어 --episode 01편
"""

import argparse
import csv

from common import draft_name, fmt_time, job_dir, load_config, read_json
from timemap import TimeMap, subtract

HEADER = ["타임라인", "시작~끝", "구분", "원고", "주제", "자막 스타일·색"]


def timeline_rows(label, plan, topics, ranges, title=None, hook=None, topic_id=None, hook_len=2.5):
    tm = TimeMap(subtract(ranges, [(c["start"], c["end"]) for c in plan.get("cuts", [])]))
    rows = []
    if hook:
        t = topics.get(topic_id, {})
        rows.append((0.0, [label, f"{fmt_time(0)}~{fmt_time(min(hook_len, tm.total))}", "훅",
                           hook.replace("\n", " "), t.get("name", ""), "훅 · 화면 중앙"]))
    if title:
        t = topics.get(topic_id, {})
        start = min(hook_len, tm.total) if hook else 0.0
        rows.append((start, [label, f"{fmt_time(start)}~{fmt_time(tm.total)}", "소제목",
                             title, t.get("name", ""), f"소제목 · {t.get('color', '')}"]))
    for it in plan["items"]:
        if title and it["type"] == "question":
            continue  # 릴스에서는 릴스 제목이 소제목 역할
        sp = tm.span(it["start"], it["end"])
        if not sp:
            continue
        t = topics.get(it.get("topic"), {})
        if it["type"] == "question":
            kind, style = "질문", f"소제목 · {t.get('color', '')}"
        else:
            kind, style = "답변", "귀여운 자막"
            if it.get("highlights"):
                style += f" · 강조({', '.join(it['highlights'])}) {t.get('color', '')}"
        rows.append((sp[0], [label, f"{fmt_time(sp[0])}~{fmt_time(sp[1])}", kind,
                             it["text"].replace("\n", " "), t.get("name", ""), style]))
    rows.sort(key=lambda r: r[0])
    return [r for _, r in rows], tm.total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--episode", required=True)
    args = ap.parse_args()

    cfg = load_config()
    out = job_dir(cfg, args.client, args.episode)
    job = read_json(out / "job.json")
    plan = read_json(out / "edit_plan.json")
    base = draft_name(args.client, args.episode)
    hook_len = cfg.get("effects", {}).get("hook_seconds", 2.5)

    palette = cfg["topic_palette"]
    topics = {t["id"]: {**t, "color": t.get("color", palette[i % len(palette)])}
              for i, t in enumerate(plan.get("topics", []))}

    timelines = []
    if plan.get("make_full", True):
        timelines.append((f"{base}_전체", dict(ranges=[(0.0, job["duration"])])))
    for r in plan.get("reels", []):
        timelines.append((f"{base}_릴스{r['id']}", dict(ranges=[tuple(x) for x in r["ranges"]], title=r.get("title"),
                                                      hook=r.get("hook"), topic_id=r.get("topic"))))

    md = [f"# {args.client} {args.episode} 타임라인", ""]
    all_rows, lengths = [], []
    for label, kw in timelines:
        rows, total = timeline_rows(label, plan, topics, hook_len=hook_len, **kw)
        lengths.append((label, total, kw.get("title")))
        all_rows += rows
        md += [f"## {label} ({fmt_time(total)})", "",
               "| " + " | ".join(HEADER[1:]) + " |", "|" + "---|" * (len(HEADER) - 1)]
        md += ["| " + " | ".join(c.replace("|", "/") for c in r[1:]) + " |" for r in rows]
        md.append("")

    with open(out / "timeline.csv", "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([HEADER] + all_rows)

    max_len = cfg.get("reel_max_seconds", 59)
    md += ["## 요약", f"- 원본 길이: {fmt_time(job['duration'])}", "- 만든 타임라인:"]
    for label, total, title in lengths:
        warn = " ⚠️ 1분 초과" if "릴스" in label and total > max_len else ""
        md.append(f"  - {label} — {fmt_time(total)}{' · ' + title if title else ''}{warn}")
    md.append("- 주제와 색:")
    md += [f"  - {t['name']} — {t['color']}" for t in topics.values()]
    cuts = plan.get("cuts", [])
    if cuts:
        md.append(f"- 잘라낸 구간 {len(cuts)}곳 (원본 기준):")
        md += [f"  - {fmt_time(c['start'])}~{fmt_time(c['end'])} {c.get('reason', '')}" for c in cuts]
    md.append(f"- 얼굴 보정: {'FFmpeg 기본 보정 적용 (피부결·밝기·채도)' if job.get('beauty') else '미적용 (캡컷 리터치에서 조정 권장)'}")
    fx = cfg.get("effects", {})
    md.append(f"- 효과: 컷마다 번갈아 확대 ×{fx.get('punch_in_zoom')}, 천천히 줌인 ×{fx.get('slow_zoom')}, "
              f"글자 등장 애니메이션 (훅 {fx.get('hook_intro')}, 소제목 {fx.get('question_intro')}, 자막 {fx.get('answer_intro')})")
    fixes = plan.get("fixes", [])
    if fixes:
        md.append("- 자동 인식에서 고친 단어:")
        md += [f"  - {f['from']} → {f['to']}" for f in fixes]
    notes = plan.get("notes", [])
    if notes:
        md.append("- 직접 확인할 것:")
        md += [f"  - {n}" for n in notes]

    (out / "timeline.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\n저장: {out / 'timeline.md'}, {out / 'timeline.csv'}")


if __name__ == "__main__":
    main()
