"""편집 계획(plan.json)으로 캡컷 프로젝트(초안) 폴더를 만든다. pycapcut 사용.

사용법:
    python3 build_capcut.py <plan.json> <카드폴더> <출력폴더>

    카드폴더  render_cards.py 가 만든 card_<id>.mp4 가 있는 폴더
    출력폴더  여기에 <프로젝트이름>/ 초안 폴더가 생긴다

원본 영상은 복사하지 않고 위치만 적는다. 이 단계에서는 사장님 PC 경로를 모르므로
  원본 영상 → "##SRC##/<원본폴더 안 경로>"
  카드 영상 → "##DRAFT##/reels_assets/card_<id>.mp4" (카드는 초안 폴더 안에 복사)
로 적어 두고, PC에서 install_capcut.py 가 실제 경로로 바꿔 캡컷 폴더에 넣는다.

plan.json 형식 (예시는 이 플러그인 SKILL.md 참고):
  media: {키: {local, rel, width, height, duration}}  local = 이 컴퓨터에서 읽을 사본
  cards: render_cards.py 와 같은 목록
  clips: 영상 트랙에 차례로 놓을 조각
         {src: 미디어키, start: 원본 기준 시작초, dur, volume, zoom: [시작배율, 끝배율],
          intro: 영상 시작 애니메이션, transition: {type, dur}}  또는  {card: 카드id, dur, transition}
  texts: [{text, start, end, size, y(화면 위에서부터 0~1), color, bold, border, intro, outro, track}]
"""
import json
import math
import shutil
import sys
from pathlib import Path

import pycapcut as cc
from pycapcut import ClipSettings, KeyframeProperty, TextBorder, TextStyle, TrackType, trange

SEC = 1_000_000
MAX_CARDS_PER_30S = 4


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def enum_by_name(enum_cls, name):
    for m in enum_cls:
        if m.name == name or getattr(m.value, "name", None) == name:
            return m
    raise ValueError(f"{enum_cls.__name__} 에 '{name}' 이(가) 없습니다")


def us(seconds):
    return int(round(seconds * SEC))


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    card_dir, out_root = Path(sys.argv[2]), Path(sys.argv[3])
    out_root.mkdir(parents=True, exist_ok=True)
    name = plan["project"]
    W, H, FPS = plan.get("width", 1080), plan.get("height", 1920), plan.get("fps", 30)

    # 모션그래픽 카드는 30초마다 최대 4개 (많으면 광고처럼 보이고 촬영 영상이 묻힌다)
    total = sum(float(c["dur"]) for c in plan["clips"])
    n_cards = sum(1 for c in plan["clips"] if "card" in c)
    limit = MAX_CARDS_PER_30S * max(1, math.ceil(total / 30))
    if n_cards > limit:
        sys.exit(f"모션그래픽 카드가 {n_cards}개입니다. {total:.0f}초 영상은 최대 {limit}개까지예요 (30초마다 {MAX_CARDS_PER_30S}개).")

    folder = cc.DraftFolder(str(out_root))
    script = folder.create_draft(name, W, H, FPS, allow_replace=True)
    draft_dir = out_root / name
    assets_dir = draft_dir / "reels_assets"
    assets_dir.mkdir(exist_ok=True)

    script.add_track(TrackType.video, "main")
    text_tracks = []
    for t in plan.get("texts", []):
        tr = t.get("track", "text")
        if tr not in text_tracks:
            text_tracks.append(tr)
            script.add_track(TrackType.text, tr, relative_index=len(text_tracks))

    # 원본 영상 소재: 이 컴퓨터의 사본으로 읽되 크기·길이는 원본 값으로 맞춘다 (회전 영상·작은 사본 대비)
    materials, path_map = {}, {}
    for key, m in plan["media"].items():
        mat = cc.VideoMaterial(m["local"], material_name=Path(m["rel"]).name)
        mat.width, mat.height = int(m["width"]), int(m["height"])
        mat.duration = us(m["duration"])
        materials[key] = mat
        path_map[str(Path(m["local"]).resolve())] = "##SRC##/" + m["rel"].replace("\\", "/")
    for card in plan.get("cards", []):
        src = card_dir / f"card_{card['id']}.mp4"
        dst = assets_dir / src.name
        shutil.copyfile(src, dst)
        materials["card:" + card["id"]] = cc.VideoMaterial(str(dst), material_name=dst.name)
        path_map[str(dst.resolve())] = "##DRAFT##/reels_assets/" + dst.name

    t = 0.0
    for c in plan["clips"]:
        dur = float(c["dur"])
        if "card" in c:
            seg = cc.VideoSegment(materials["card:" + c["card"]], trange(us(t), us(dur)),
                                  source_timerange=trange(0, us(dur)), volume=0.0)
        else:
            seg = cc.VideoSegment(materials[c["src"]], trange(us(t), us(dur)),
                                  source_timerange=trange(us(c["start"]), us(dur)), volume=float(c.get("volume", 0.0)))
            if c.get("zoom"):
                z0, z1 = c["zoom"]
                seg.add_keyframe(KeyframeProperty.uniform_scale, 0, z0)
                seg.add_keyframe(KeyframeProperty.uniform_scale, us(dur) - 1, z1)
        if c.get("intro"):
            seg.add_animation(enum_by_name(cc.IntroType, c["intro"]))
        if c.get("transition"):
            tr = c["transition"]
            seg.add_transition(enum_by_name(cc.TransitionType, tr["type"]), duration=us(tr.get("dur", 0.4)))
        script.add_segment(seg, "main")
        t += dur

    for x in plan.get("texts", []):
        style = TextStyle(size=x.get("size", 8.0), bold=x.get("bold", True), color=hex_rgb(x.get("color", "#ffffff")),
                          align=1, auto_wrapping=True, max_line_width=x.get("max_width", 0.86))
        seg = cc.TextSegment(x["text"], trange(us(x["start"]), us(x["end"] - x["start"])), style=style,
                             clip_settings=ClipSettings(transform_y=1 - 2 * x.get("y", 0.5)),
                             border=TextBorder(width=x.get("border_width", 40.0)) if x.get("border", True) else None)
        if x.get("intro"):
            seg.add_animation(enum_by_name(cc.TextIntro, x["intro"]))
        if x.get("outro"):
            seg.add_animation(enum_by_name(cc.TextOutro, x["outro"]))
        script.add_segment(seg, x.get("track", "text"))

    script.save()

    # 경로를 자리표시로 바꾼다 (PC에서 install_capcut.py 가 실제 경로로 채움)
    local_draft = str(draft_dir.resolve())
    local_root = str(out_root.resolve())

    def fix(v):
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, str):
            if v in path_map:
                return path_map[v]
            if v.startswith(local_draft):
                return "##DRAFT##" + v[len(local_draft):].replace("\\", "/")
            if v.startswith(local_root):
                return "##ROOT##" + v[len(local_root):].replace("\\", "/")
        return v

    for f in draft_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        f.write_text(json.dumps(fix(data), ensure_ascii=False), encoding="utf-8")
    saved = dict(plan, media={k: {x: y for x, y in m.items() if x != "local"} for k, m in plan["media"].items()},
                 cards=[{x: (Path(y).name if x == "background" and y else y) for x, y in c.items()} for c in plan.get("cards", [])])
    (draft_dir / "reels_plan.json").write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"초안 저장 → {draft_dir}  (길이 {t:.1f}초, 조각 {len(plan['clips'])}개, 글자 {len(plan.get('texts', []))}개)")


if __name__ == "__main__":
    main()
