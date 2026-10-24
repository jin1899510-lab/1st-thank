"""(사장님 PC에서 실행) build_capcut.py 가 만든 편(초안)을 캡컷 프로젝트의 타임라인으로 넣는다.

    업체 하나 = 캡컷 프로젝트 하나, 편 하나 = 타임라인 하나
    예) 프로젝트「마라쿵젠 남포동본점」 ├─ 타임라인「01 모임 장소 고민 끝」
                                      └─ 타임라인「02 훠궈 양꼬치 무한리필」

사용법 (윈도우):
    python install_capcut.py <편 초안폴더 또는 .zip> [더 많은 편…] [--source "원본 영상 폴더"] [--drafts "캡컷 초안 폴더"]

    --source  촬영 원본이 있는 폴더. 초안에 적힌 "폴더 안 경로"로 찾고,
              없으면 같은 파일 이름을 하위 폴더까지 찾는다.
              빼면 바탕 화면·다운로드·동영상·문서·OneDrive·다른 드라이브에서
              원본 파일 이름으로 폴더를 알아서 찾는다.
    --drafts  캡컷 초안 폴더 (기본: C:\\Users\\<사용자>\\AppData\\Local\\CapCut Drafts)

편 정보는 초안 안 reels_plan.json 에서 읽는다.
    store   업체 이름 = 프로젝트 이름 (없으면 project 에서 " 02편" 같은 꼬리를 뗀 것)
    episode 편 번호 (없으면 timeline/project 의 "NN편", 그것도 없으면 다음 번호)
    title   타임라인 제목 → 타임라인 이름 "01 제목"

하는 일:
  1. 자리표시(##SRC##, ##DRAFT##, ##ROOT##)를 이 PC의 실제 경로로 바꾼다.
  2. 프로젝트가 없으면 새로 만들고, 있으면 Timelines/project.json 에 타임라인을 더한다.
     같은 번호 타임라인이 이미 있으면 내용만 새로 바꾼다 (전에 있던 것은 백업).
  3. 바꾸기 전 프로젝트 전체를 "CapCut 초안 백업" 폴더(캡컷 목록에 안 보이는 곳)에 복사해 둔다.
  4. 캡컷이 켜져 있으면 덮어쓸 수 없으므로, 캡컷이 꺼질 때까지 기다린다.

캡컷 9.6 구조 (사장님 PC에서 확인):
    <프로젝트>/Timelines/project.json        {"main_timeline_id", "timelines": [{"id","name",...}], ...}
    <프로젝트>/Timelines/<타임라인ID>/draft_content.json  타임라인 하나의 내용
    <프로젝트>/draft_content.json             메인 타임라인 사본 (예전 버전 호환)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path


def default_drafts():
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return str(Path(local) / "CapCut Drafts")


def capcut_running():
    if sys.platform != "win32":
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"], capture_output=True, text=True).stdout
    return "CapCut.exe" in out


def find_source(source_root, rel, cache):
    direct = source_root / Path(rel)
    if direct.exists():
        return direct
    name = Path(rel).name
    if name not in cache:
        cache[name] = next(iter(source_root.rglob(name)), None)
    return cache[name]


SKIP_DIRS = {"appdata", "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
             "system volume information", "node_modules", ".git", "capcut drafts"}


def guess_source(names):
    """원본 파일 이름들이 가장 많이 들어 있는 폴더를 찾는다. 못 찾으면 None."""
    home = Path.home()
    roots = [home / d for d in ("Desktop", "바탕 화면", "Downloads", "Videos", "Pictures", "Documents")]
    roots += sorted(home.glob("OneDrive*")) + [home]
    if sys.platform == "win32":
        roots += [Path(f"{c}:\\") for c in "DEFGHIJ" if Path(f"{c}:\\").exists()]
    names = {n.lower() for n in names}
    best, best_n, seen = None, 0, set()
    for root in roots:
        if not root.exists():
            continue
        print(f"  찾는 중: {root}")
        for dirpath, dirnames, filenames in os.walk(root):
            key = os.path.normcase(dirpath)
            if key in seen:
                dirnames[:] = []
                continue
            seen.add(key)
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            n = sum(1 for f in filenames if f.lower() in names)
            if n > best_n:
                best, best_n = Path(dirpath), n
                if n == len(names):
                    return best
    return best


def new_id():
    # 캡컷과 같은 모양: 8자-4자-4자(소문자)-4자-12자
    a, b, c, d, e = str(uuid.uuid4()).upper().split("-")
    return "-".join([a, b, c.lower(), d, e])


def now_us():
    return int(time.time() * 1_000_000)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def episode_info(plan, folder_name):
    project = plan.get("project") or folder_name
    store = plan.get("store") or re.sub(r"\s*\d+\s*편$", "", project).strip()
    ep = plan.get("episode")
    if ep is None:
        m = re.search(r"(\d+)\s*편", str(plan.get("timeline", "")) + " " + project)
        ep = int(m.group(1)) if m else None
    title = plan.get("title") or ""
    return store, ep, title


def unpack(paths, tmp):
    """인자로 받은 폴더·zip 에서 편 초안 폴더(draft_content.json 이 있는 폴더)를 모두 찾는다."""
    found = []
    for p in map(Path, paths):
        if p.suffix.lower() == ".zip":
            dest = Path(tempfile.mkdtemp(dir=tmp))
            with zipfile.ZipFile(p) as z:
                z.extractall(dest)
            p = dest
        if (p / "draft_content.json").exists():
            found.append(p)
        else:
            inner = [d for d in p.iterdir() if d.is_dir() and (d / "draft_content.json").exists()] if p.is_dir() else []
            if not inner:
                sys.exit(f"{p} 에서 캡컷 초안(draft_content.json)을 찾지 못했습니다.")
            found.extend(inner)
    return found


def main():
    ap = argparse.ArgumentParser(description="캡컷 프로젝트에 편(타임라인) 넣기")
    ap.add_argument("drafts_in", nargs="*", metavar="초안")
    ap.add_argument("--source")
    ap.add_argument("--drafts", default=default_drafts())
    args = ap.parse_args()

    if not args.drafts_in:  # 설치.bat 에서 인자 없이 부르면 옆의 "편" 폴더
        args.drafts_in = [str(Path(__file__).resolve().parent / "편")]
    drafts = Path(args.drafts).resolve()
    if not drafts.exists():
        sys.exit(f"캡컷 초안 폴더가 없습니다: {drafts}\n캡컷 설정 > 초안 위치를 확인해 --drafts 로 알려주세요.")

    tmp = Path(tempfile.mkdtemp())
    episodes, media_names = [], set()
    for d in unpack(args.drafts_in, tmp):
        plan = read_json(d / "reels_plan.json") if (d / "reels_plan.json").exists() else {}
        store, ep, title = episode_info(plan, d.name)
        episodes.append({"dir": d, "store": store, "ep": ep, "title": title})
        media_names |= {Path(m["rel"]).name for m in plan.get("media", {}).values() if m.get("rel")}

    if args.source:
        source_root = Path(args.source).resolve()
    else:
        print("촬영 원본 영상이 있는 폴더를 찾고 있어요… (조금 걸릴 수 있어요)")
        source_root = guess_source(media_names) if media_names else None
        if source_root is None:
            print("원본 영상 폴더를 찾지 못했어요. 찾는 파일 이름: " + ", ".join(sorted(media_names)[:3]) + " …")
            typed = input("영상 폴더 주소를 붙여넣고 Enter (모르면 그냥 Enter): ").strip().strip('"')
            if not typed:
                sys.exit("영상이 이 컴퓨터에 있는지 확인해 주세요.")
            source_root = Path(typed)
        else:
            print(f"찾았어요 → {source_root}")
    if not source_root.exists():
        sys.exit(f"원본 영상 폴더가 없습니다: {source_root}")
    episodes.sort(key=lambda e: (e["store"], e["ep"] if e["ep"] is not None else 9999))

    if capcut_running():
        print("캡컷이 켜져 있어요. 캡컷을 끄면 자동으로 넣습니다… (그만두려면 Ctrl+C)")
        while capcut_running():
            time.sleep(3)

    backed_up, cache, missing = set(), {}, []
    for e in episodes:
        target = drafts / e["store"]
        tl_root = target / "Timelines"
        if target.exists() and e["store"] not in backed_up:
            backup = drafts.parent / "CapCut 초안 백업" / f"{e['store']}_{datetime.now():%Y%m%d_%H%M%S_%f}"
            shutil.copytree(target, backup, ignore=shutil.ignore_patterns(".locked"))
            print(f"기존 프로젝트를 백업했습니다 → {backup}")
        backed_up.add(e["store"])  # 이번에 새로 만든 프로젝트도 다시 백업하지 않음
        target.mkdir(exist_ok=True)

        proj_path = tl_root / "project.json"
        if proj_path.exists():
            proj = read_json(proj_path)
        else:
            t = now_us()
            proj = {"config": {"color_space": -1, "hdr_vivid": False, "mixed_track_mode_on": False,
                               "render_index_track_mode_on": False, "use_float_render": False},
                    "create_time": t, "id": new_id(), "main_timeline_id": "", "timelines": [],
                    "update_time": t, "version": 0}
        live = [t for t in proj["timelines"] if not t.get("is_marked_delete")]

        ep = e["ep"]
        if ep is None:
            nums = [int(m.group(1)) for t in live if (m := re.match(r"(\d+)\s", t.get("name", "")))]
            ep = max(nums, default=len(live)) + 1
        prefix = f"{ep:02d}"
        name = f"{prefix} {e['title']}".strip()
        entry = next((t for t in live if t.get("name", "").split(" ")[0] == prefix), None)
        if entry:
            tl_id = entry["id"]
            entry.update({"name": name, "update_time": now_us()})
            print(f"타임라인 '{prefix}' 가 이미 있어 내용을 새로 바꿉니다.")
        else:
            tl_id = new_id()
            t = now_us()
            proj["timelines"].append({"create_time": t, "id": tl_id, "is_marked_delete": False,
                                      "name": name, "update_time": t})
        if not proj.get("main_timeline_id") or not any(t["id"] == proj["main_timeline_id"] for t in proj["timelines"]):
            proj["main_timeline_id"] = tl_id
        proj["update_time"] = now_us()

        # 편마다 소재 폴더를 나눠 이름이 겹치지 않게 (카드 c1 이 1편·2편 모두 있음)
        assets = target / "reels_assets" / prefix
        if assets.exists():
            shutil.rmtree(assets)
        if (e["dir"] / "reels_assets").exists():
            shutil.copytree(e["dir"] / "reels_assets", assets)

        def fix(v):
            if isinstance(v, dict):
                return {k: fix(x) for k, x in v.items()}
            if isinstance(v, list):
                return [fix(x) for x in v]
            if isinstance(v, str):
                if v.startswith("##SRC##/"):
                    rel = v[len("##SRC##/"):]
                    found = find_source(source_root, rel, cache)
                    if not found:
                        missing.append(rel)
                        return str(source_root / Path(rel))
                    return str(found)
                if v.startswith("##DRAFT##/reels_assets/"):
                    return str(assets / v[len("##DRAFT##/reels_assets/"):].replace("/", os.sep))
                if v.startswith("##DRAFT##"):
                    return str(target) + v[len("##DRAFT##"):].replace("/", os.sep)
                if v.startswith("##ROOT##"):
                    return str(drafts) + v[len("##ROOT##"):].replace("/", os.sep)
            return v

        content = fix(read_json(e["dir"] / "draft_content.json"))
        content["id"] = tl_id
        content["name"] = name
        tl_dir = tl_root / tl_id
        tl_dir.mkdir(parents=True, exist_ok=True)
        write_json(tl_dir / "draft_content.json", content)
        if (e["dir"] / "reels_plan.json").exists():
            shutil.copyfile(e["dir"] / "reels_plan.json", tl_dir / "reels_plan.json")
        write_json(proj_path, proj)

        # 프로젝트 맨 위 사본·목록 정보 (메인 타임라인 기준)
        if proj["main_timeline_id"] == tl_id:
            write_json(target / "draft_content.json", content)
        meta_path = target / "draft_meta_info.json"
        if meta_path.exists():
            meta = read_json(meta_path)
        else:
            meta = fix(read_json(e["dir"] / "draft_meta_info.json"))
            meta["draft_id"] = proj["id"]
        meta.update({"draft_name": e["store"], "draft_fold_path": str(target), "draft_root_path": str(drafts),
                     "tm_draft_modified": now_us()})
        write_json(meta_path, meta)
        print(f"  {e['store']}  ▸ 타임라인 '{name}'")

    shutil.rmtree(tmp, ignore_errors=True)
    if missing:
        print("원본 폴더에서 찾지 못한 파일 (캡컷에서 빈칸으로 보입니다):")
        for m in sorted(set(missing)):
            print("  -", m)
    print("다 넣었습니다. 캡컷을 켜고 프로젝트를 연 뒤, 위쪽 타임라인 목록에서 편을 고르세요.")


if __name__ == "__main__":
    main()
