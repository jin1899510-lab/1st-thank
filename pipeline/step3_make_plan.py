"""3단계: 요약 계획(outline.json) + 음성 인식 결과(transcript.json) → 편집 계획(edit_plan.json).

Claude 는 outline.json 에 '판단'만 적는다:
  질문 구간·소제목, 주제와 강조 단어, 잘라낼 구간, 릴스 구간·제목·훅, 오타 수정.
이 스크립트가 단어별 시간을 이용해 답변 자막을 자동으로 나누고(한 줄 14자 안팎, 최대 2줄),
말 사이의 긴 침묵을 자동으로 잘라낸다.

사용 예:
  python step3_make_plan.py --client 한방장어 --episode 01편
"""

import argparse
import re

from common import job_dir, load_config, read_json, write_json

FILLERS = {"음", "어", "아", "뭐", "그", "이", "저", "그니까", "막"}  # 자막에서만 뺄 군말 (단독 단어일 때)
LINE_CHARS = 14
MAX_CHARS = 26
MAX_SEC = 4.0
BREAK_GAP = 0.6
MIN_SEC = 0.7


def apply_fixes(text, fixes):
    for f in fixes:
        text = text.replace(f["from"], f["to"])
    return text


def tidy_text(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[.,]+$", "", text)
    text = text.replace(". ", " ").replace(", ", " ")
    return text.strip()


def wrap(text):
    if len(text) <= LINE_CHARS or "\n" in text:
        return text
    spaces = [i for i, c in enumerate(text) if c == " "]
    if not spaces:
        return text
    mid = len(text) / 2
    i = min(spaces, key=lambda k: abs(k - mid))
    return text[:i] + "\n" + text[i + 1:]


def inside(t, ranges):
    return any(s <= t < e for s, e in ranges)


GOOD_ENDINGS = ("요", "고", "서", "데", "면", "까", "죠", "다", "니", "며", ",", ".", "?", "!")


def split_balanced(ws):
    """한 문장(구간)을 글자 수가 비슷한 조각들로 나눈다.
    - 한 글자짜리 꼬리 조각이 생기지 않게 조각마다 최소 4자
    - 가능하면 '~요, ~고, ~서'처럼 말이 끊기는 곳에서 나눔"""
    from itertools import combinations

    lens = [len(w["word"].strip()) for w in ws]
    total = sum(lens)
    dur = ws[-1]["end"] - ws[0]["start"]
    n = max(1, -(-total // MAX_CHARS), int(-(-dur // MAX_SEC)))
    n = min(n, len(ws))
    if n == 1:
        return [ws]
    target = total / n
    best, best_cost = None, None
    for cuts in combinations(range(1, len(ws)), n - 1):
        bounds = (0,) + cuts + (len(ws),)
        sizes = [sum(lens[bounds[k]:bounds[k + 1]]) for k in range(n)]
        if min(sizes) < 4:
            continue
        cost = sum((x - target) ** 2 for x in sizes)
        cost -= sum(8 for c in cuts if ws[c - 1]["word"].strip().endswith(GOOD_ENDINGS))
        if best_cost is None or cost < best_cost:
            best, best_cost = bounds, cost
    if best is None:
        return [ws]
    return [ws[best[k]:best[k + 1]] for k in range(n)]


def chunk_words(segments, q_ranges):
    """Whisper 문장(구간) 단위로 묶고, 긴 문장은 고르게 나눈다. 질문 구간의 단어는 제외."""
    groups = []
    for seg in segments:
        cur, prev = [], None
        for w in seg["words"]:
            if not w["word"].strip():
                continue
            if inside((w["start"] + w["end"]) / 2, q_ranges):
                if cur:
                    groups.append(cur)
                cur, prev = [], None
                continue
            if cur and (w["start"] - prev["end"] > BREAK_GAP
                        or (prev["word"].strip().endswith((".", "?", "!")) and len(cur) >= 2)):
                groups.append(cur)
                cur = []
            cur.append(w)
            prev = w
        if cur:
            groups.append(cur)

    # 아주 짧은 조각(6자 미만)은 바로 붙어 있는 다음 조각과 합침
    merged = []
    for g in groups:
        if merged:
            last = merged[-1]
            short = len("".join(w["word"] for w in last).strip()) < 6
            close = g[0]["start"] - last[-1]["end"] < 0.3
            fits = len("".join(w["word"] for w in last + g).strip()) <= MAX_CHARS
            if short and close and fits:
                merged[-1] = last + g
                continue
        merged.append(g)
    return [part for g in merged for part in split_balanced(g)]


def silence_cuts(words, min_gap, pad):
    cuts = []
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > min_gap:
            cuts.append({"start": round(a["end"] + pad, 2), "end": round(b["start"] - pad, 2), "reason": "침묵"})
    return cuts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--episode", required=True)
    args = ap.parse_args()

    cfg = load_config()
    out = job_dir(cfg, args.client, args.episode)
    tr = read_json(out / "transcript.json")
    ol = read_json(out / "outline.json")

    words = [w for seg in tr["segments"] for w in seg["words"] if w["word"].strip()]
    fixes = ol.get("fixes", [])
    questions = sorted(ol.get("questions", []), key=lambda q: q["start"])
    q_ranges = [(q["start"], q["end"]) for q in questions]
    topics = {t["id"]: t for t in ol["topics"]}

    def topic_at(t):
        cur = ol["topics"][0]["id"]
        for q in questions:
            if q["start"] <= t:
                cur = q["topic"]
        return cur

    items = [{"type": "question", "start": q["start"], "end": q["end"], "text": q["text"], "topic": q["topic"]}
             for q in questions]

    answers = []
    for ch in chunk_words(tr["segments"], q_ranges):
        kept = [w for w in ch if w["word"].strip().strip(".,?!") not in FILLERS]
        if not kept:
            continue
        text = tidy_text(apply_fixes("".join(w["word"] for w in kept), fixes))
        if not text:
            continue
        start, end = ch[0]["start"], ch[-1]["end"]
        tid = topic_at(start)
        hl = [k for k in topics.get(tid, {}).get("keywords", []) if k in text][:2]
        answers.append({"type": "answer", "start": round(start, 2), "end": round(end, 2),
                        "text": wrap(text), "topic": tid, "highlights": hl})

    # 너무 짧은 자막은 다음 자막 직전까지 늘림
    for a, b in zip(answers, answers[1:] + [None]):
        if a["end"] - a["start"] < MIN_SEC:
            limit = b["start"] if b else a["end"] + MIN_SEC
            a["end"] = round(min(a["start"] + MIN_SEC, limit), 2)
    items += answers

    sil = ol.get("auto_silence", {"min_gap": 0.7, "pad": 0.12})
    cuts = list(ol.get("cuts", []))
    if sil:
        cuts += silence_cuts(words, sil["min_gap"], sil["pad"])
    if words:  # 첫 말 전, 마지막 말 뒤 빈 구간
        cuts.append({"start": 0.0, "end": max(0.0, round(words[0]["start"] - 0.2, 2)), "reason": "시작 전"})
        cuts.append({"start": round(words[-1]["end"] + 0.3, 2), "end": tr["duration"] + 1, "reason": "끝난 뒤"})

    plan = {
        "make_full": ol.get("make_full", True),
        "crop": ol.get("crop", {"center_x": 0.5}),
        "topics": [{"id": t["id"], "name": t["name"], **({"color": t["color"]} if t.get("color") else {})}
                   for t in ol["topics"]],
        "items": sorted(items, key=lambda x: x["start"]),
        "cuts": sorted(cuts, key=lambda c: c["start"]),
        "reels": ol.get("reels", []),
        "fixes": fixes,
        "notes": ol.get("notes", []),
    }
    write_json(out / "edit_plan.json", plan)
    manual = len(ol.get("cuts", []))
    print(f"완료: 소제목 {len(questions)}개, 자막 {len(answers)}개, 잘라낼 구간 {manual}곳 + 침묵 {len(cuts) - manual}곳")
    print(f"  → {out / 'edit_plan.json'}")


if __name__ == "__main__":
    main()
