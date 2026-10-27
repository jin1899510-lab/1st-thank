"""4단계: 편집 계획(edit_plan.json)으로 캡컷 프로젝트(타임라인)를 자동 생성.

만드는 것
  {업체}_{편}_전체     반복·군말(cuts)을 잘라낸 전체 편집본
  {업체}_{편}_릴스01…  내용별로 자른 1분 미만 릴스 (reels)

각 타임라인 구성
  영상 트랙   9:16 꽉 채움 + 얼굴 중앙 + 컷마다 번갈아 확대(점프컷 가림) + 천천히 밀어들어가는 줌
  '훅'        릴스 첫 2~3초 화면 중앙 큰 문구 (등장 애니메이션)
  '소제목'    질문 요약(전체본) / 릴스 제목(릴스). 주제 색, 등장 애니메이션
  '자막'      답변 자막. 핵심 단어는 주제 색으로 강조, 등장 애니메이션
자막은 캡컷 텍스트로 들어가므로 캡컷에서 트랙별로 한꺼번에 수정할 수 있습니다.

캡컷을 완전히 끈 상태에서 실행하세요. 켜져 있으면 캡컷 자동 저장이 덮어쓸 수 있습니다.

사용 예:
  python step4_build_capcut.py --client 한방장어 --episode 01편            # 전체본 + 릴스 전부
  python step4_build_capcut.py --client 한방장어 --episode 01편 --only 릴스02
  python step4_build_capcut.py --client 한방장어 --episode 01편 --replace  # 같은 이름 덮어쓰기
"""

import argparse
import json
from pathlib import Path

import pycapcut as cc

from common import draft_name, hex_to_rgb, job_dir, load_config, read_json
from timemap import TimeMap, no_overlap, subtract


# ---------------------------------------------------------------- 텍스트

class HighlightTextSegment(cc.TextSegment):
    """일부 단어만 다른 색으로 칠하는 텍스트 (pycapcut 은 한 가지 색만 지원해서 확장)."""

    def __init__(self, *args, highlights=None, highlight_color=(1.0, 0.36, 0.54), font_path=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.highlights = [h for h in (highlights or []) if h]
        self.highlight_color = list(highlight_color)
        self.font_path = font_path

    def _ranges(self):
        marks = [False] * len(self.text)
        for word in self.highlights:
            start = self.text.find(word)
            while start != -1:
                for i in range(start, start + len(word)):
                    marks[i] = True
                start = self.text.find(word, start + len(word))
        ranges, i = [], 0
        while i < len(marks):
            j = i
            while j < len(marks) and marks[j] == marks[i]:
                j += 1
            ranges.append((i, j, marks[i]))
            i = j
        return ranges

    def export_material(self):
        ret = super().export_material()
        content = json.loads(ret["content"])
        base = content["styles"][0]
        if self.font_path:  # PC 에 설치된 글꼴 파일 (예: G마켓 산스)
            base["font"] = {"id": "", "path": self.font_path}
            ret["font_path"] = self.font_path
        styles = []
        for start, end, hit in (self._ranges() if self.highlights else [(0, len(self.text), False)]):
            st = json.loads(json.dumps(base))
            st["range"] = [start, end]
            if hit:
                st["fill"]["content"]["solid"]["color"] = self.highlight_color
            styles.append(st)
        content["styles"] = styles
        ret["content"] = json.dumps(content, ensure_ascii=False)
        return ret


def enum_member(enum_cls, name):
    """설정에 적힌 효과 이름을 찾는다. 없으면(캡컷/pycapcut 버전 차이) 건너뛴다."""
    if not name:
        return None
    member = getattr(enum_cls, name, None)
    if member is None:
        print(f"  [안내] '{name}' 효과를 찾을 수 없어 건너뜁니다.")
    return member


def make_text(cfg, kind, text, start, end, color_hex, highlights=None, highlight_hex=None):
    s = cfg["style"][kind]
    font = enum_member(cc.FontType, cfg["style"].get("font"))
    style = cc.TextStyle(size=s["size"], bold=s.get("bold", False), color=hex_to_rgb(color_hex),
                         align=1, auto_wrapping=True, max_line_width=s.get("max_line_width", 0.86))
    border = cc.TextBorder(color=hex_to_rgb(s["border_color"]), width=s["border_width"])
    shadow = cc.TextShadow(alpha=0.75, diffuse=12, distance=5) if s.get("shadow") else None
    bg = s.get("background")
    background = None
    if bg:  # 글씨 뒤 둥근 상자: 밝은 배경에서도 잘 보이게. color 가 "topic" 이면 주제 색
        background = cc.TextBackground(color=(highlight_hex or color_hex) if bg["color"] == "topic" else bg["color"],
                                       alpha=bg.get("alpha", 1.0), round_radius=bg.get("round_radius", 0.4),
                                       height=bg.get("height", 0.14), width=bg.get("width", 0.14))
    seg = HighlightTextSegment(
        text, cc.trange_seconds(start, end=end), font=font, style=style, border=border, shadow=shadow,
        background=background, clip_settings=cc.ClipSettings(transform_y=s["position_y"]),
        highlights=highlights, highlight_color=hex_to_rgb(highlight_hex or color_hex),
        font_path=s.get("font_path"),
    )
    fx = cfg.get("effects", {})
    intro = enum_member(cc.TextIntro, fx.get(f"{kind}_intro"))
    if intro:
        seg.add_animation(intro, min(0.4, (end - start) / 3) * 1e6)
    loop = enum_member(cc.TextLoopAnim, fx.get(f"{kind}_loop"))
    if loop:
        seg.add_animation(loop)
    return seg


# ---------------------------------------------------------------- 영상

def base_scale(src_w, src_h, canvas_w, canvas_h, zoom=1.0):
    src_ratio, can_ratio = src_w / src_h, canvas_w / canvas_h
    # 캡컷은 기본으로 화면 안에 '맞춤'으로 넣으므로, 꽉 채우려면 비율 차이만큼 키운다
    return (src_ratio / can_ratio if src_ratio > can_ratio else can_ratio / src_ratio) * zoom


def offset_x(scale, center_x, landscape):
    """center_x(원본 가로 0~1)를 화면 중앙으로. 단위는 '화면 가로의 절반', 검은 여백이 안 생기게 제한."""
    if not landscape:
        return 0.0
    limit = scale - 1.0
    return max(-limit, min(limit, (0.5 - center_x) * scale * 2))


# ---------------------------------------------------------------- 타임라인 생성

def build(folder, name, cfg, job, plan, ranges, *, title=None, hook=None, topic_id=None, replace=False, media_path=None):
    canvas = cfg["canvas"]
    fx = cfg.get("effects", {})
    palette = cfg["topic_palette"]
    topics = {t["id"]: t for t in plan.get("topics", [])}

    def color_of(tid):
        return topics.get(tid, {}).get("color", palette[0])

    def q_color(tid):
        """소제목 글자색: 설정에 color 가 있으면 그 색(배경 상자가 주제 색), 없으면 주제 색"""
        return cfg["style"]["question"].get("color") or color_of(tid)

    pieces = subtract(ranges, [(c["start"], c["end"]) for c in plan.get("cuts", [])])
    tm = TimeMap(pieces)
    if tm.total < 1:
        print(f"  [건너뜀] {name}: 남는 영상이 없습니다.")
        return None

    if folder.has_draft(name) and not replace:
        raise SystemExit(f"[오류] 캡컷에 '{name}' 프로젝트가 이미 있습니다. 덮어쓰려면 --replace 를 붙여 주세요.")
    script = folder.create_draft(name, canvas["width"], canvas["height"], canvas.get("fps", 30), allow_replace=True)
    script.add_track(cc.TrackType.video)
    script.add_track(cc.TrackType.text, "자막", relative_index=1)
    script.add_track(cc.TrackType.text, "소제목", relative_index=2)
    script.add_track(cc.TrackType.text, "훅", relative_index=3)

    # 영상: 조각마다 번갈아 확대 + 천천히 줌인
    crop = plan.get("crop", {})
    landscape = job["width"] / job["height"] > canvas["width"] / canvas["height"]
    scale0 = base_scale(job["width"], job["height"], canvas["width"], canvas["height"], crop.get("zoom", 1.0))
    punch = fx.get("punch_in_zoom", 1.12)
    drift = fx.get("slow_zoom", 1.04)
    intro = enum_member(cc.IntroType, fx.get("video_intro"))
    material = cc.VideoMaterial(job["edit_video"])
    if media_path:  # 다른 PC 에서 만들 때: 캡컷이 열 PC 의 영상 경로를 기록
        material.path = media_path
    for i, (ps, pe, t) in enumerate(tm.pieces):
        dur = pe - ps
        scale = scale0 * (punch if i % 2 else 1.0)
        seg = cc.VideoSegment(
            material, cc.trange_seconds(t, duration=dur),
            source_timerange=cc.trange_seconds(ps, duration=dur),
            clip_settings=cc.ClipSettings(scale_x=scale, scale_y=scale,
                                          transform_x=offset_x(scale, crop.get("center_x", 0.5), landscape)),
        )
        if drift and dur > 1.5:
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, scale)
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, int(dur * 1e6) - 1, scale * drift)
        if i == 0 and intro:
            seg.add_animation(intro)
        script.add_segment(seg)

    # 훅 (릴스 첫 화면)
    text_start = 0.0
    if hook:
        hook_len = min(fx.get("hook_seconds", 2.5), tm.total)
        script.add_segment(make_text(cfg, "hook", hook, 0, hook_len, cfg["style"]["hook"]["color"],
                                     highlight_hex=color_of(topic_id)), "훅")
        text_start = hook_len

    # 소제목
    if title:  # 릴스: 제목 하나를 끝까지
        script.add_segment(make_text(cfg, "question", title, text_start, tm.total, q_color(topic_id),
                                     highlight_hex=color_of(topic_id)), "소제목")
    else:  # 전체본: 질문마다, 다음 질문 전까지 유지
        qs = []
        for q in plan["items"]:
            if q["type"] == "question":
                sp = tm.span(q["start"], q["end"])
                if sp:
                    qs.append((sp[0], q))
        qs.sort(key=lambda x: x[0])
        spans = [(s, qs[k + 1][0] if k + 1 < len(qs) else tm.total, q) for k, (s, q) in enumerate(qs)]
        for s, e, q in no_overlap(spans):
            script.add_segment(make_text(cfg, "question", q["text"], s, e, q_color(q.get("topic")),
                                         highlight_hex=color_of(q.get("topic"))), "소제목")

    # 답변 자막
    spans = []
    for a in plan["items"]:
        if a["type"] == "answer":
            sp = tm.span(a["start"], a["end"])
            if sp:
                spans.append((sp[0], sp[1], a))
    for s, e, a in no_overlap(spans):
        script.add_segment(make_text(cfg, "answer", a["text"], s, e, cfg["style"]["answer"]["color"],
                                     highlights=a.get("highlights"), highlight_hex=color_of(a.get("topic"))), "자막")

    script.save()
    print(f"  완료: '{name}' ({tm.total:.1f}초, 컷 {len(tm.pieces)}개)")
    return tm.total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--only", help="이것만 만들기: 전체 또는 릴스01 같은 이름")
    ap.add_argument("--replace", action="store_true", help="같은 이름의 캡컷 프로젝트가 있으면 덮어쓰기")
    ap.add_argument("--no-full", action="store_true", help="전체본은 만들지 않기")
    ap.add_argument("--no-reels", action="store_true", help="릴스는 만들지 않기")
    ap.add_argument("--media-path", help="캡컷을 여는 PC 의 영상 경로 (다른 컴퓨터에서 프로젝트를 만들 때만)")
    args = ap.parse_args()

    cfg = load_config()
    out = job_dir(cfg, args.client, args.episode)
    job = read_json(out / "job.json")
    plan = read_json(out / "edit_plan.json")
    for i, t in enumerate(plan.get("topics", [])):
        t.setdefault("color", cfg["topic_palette"][i % len(cfg["topic_palette"])])

    folder = cc.DraftFolder(cfg["capcut_draft_dir"])
    base = draft_name(args.client, args.episode)
    max_len = cfg.get("reel_max_seconds", 59)

    jobs = []
    if plan.get("make_full", True) and not args.no_full:
        jobs.append(("전체", dict(ranges=[(0.0, job["duration"])])))
    for r in ([] if args.no_reels else plan.get("reels", [])):
        jobs.append((f"릴스{r['id']}", dict(ranges=[tuple(x) for x in r["ranges"]], title=r.get("title"),
                                           hook=r.get("hook"), topic_id=r.get("topic"))))
    if args.only:
        jobs = [j for j in jobs if j[0] == args.only]
        if not jobs:
            raise SystemExit(f"[오류] '{args.only}' 를 계획에서 찾을 수 없습니다.")

    print(f"캡컷 프로젝트 생성: {len(jobs)}개")
    for label, kw in jobs:
        total = build(folder, f"{base}_{label}", cfg, job, plan, replace=args.replace, media_path=args.media_path, **kw)
        if total and label != "전체" and total > max_len:
            print(f"  [주의] {label} 길이 {total:.1f}초 → {max_len}초를 넘습니다. 계획에서 구간을 줄여 주세요.")

    print(f"\n위치: {Path(cfg['capcut_draft_dir'])}")
    print("캡컷을 열면 프로젝트 목록에 나타납니다.")


if __name__ == "__main__":
    main()
