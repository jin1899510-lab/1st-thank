"""(사장님 PC에서 실행) build_capcut.py 가 만든 초안을 캡컷 프로젝트 폴더에 넣는다.

사용법 (윈도우):
    python install_capcut.py <초안폴더 또는 .zip> --source "원본 영상 폴더" [--drafts "캡컷 초안 폴더"]

    --source  촬영 원본이 있는 폴더. 초안에 적힌 "폴더 안 경로"로 찾고,
              없으면 같은 파일 이름을 하위 폴더까지 찾는다.
    --drafts  캡컷 초안 폴더 (기본: C:\\Users\\<사용자>\\AppData\\Local\\CapCut Drafts)

하는 일:
  1. 초안 안의 자리표시(##SRC##, ##DRAFT##, ##ROOT##)를 이 PC의 실제 경로로 바꾼다.
  2. 같은 이름의 프로젝트가 있으면 "<이름>_백업_<시각>" 으로 옮겨 두고 새로 넣는다.
  3. 캡컷이 켜져 있으면 프로젝트를 덮어쓸 수 없으므로, 캡컷이 꺼질 때까지 기다린다.
캡컷을 다시 켜면 목록에 프로젝트가 나타난다.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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


def main():
    ap = argparse.ArgumentParser(description="캡컷 초안 설치")
    ap.add_argument("draft")
    ap.add_argument("--source", required=True)
    ap.add_argument("--drafts", default=default_drafts())
    args = ap.parse_args()

    src_path = Path(args.draft)
    tmp = None
    if src_path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(src_path) as z:
            z.extractall(tmp)
        inner = [p for p in tmp.iterdir() if p.is_dir() and (p / "draft_content.json").exists()]
        if not inner:
            sys.exit("압축 파일 안에서 캡컷 초안 폴더(draft_content.json)를 찾지 못했습니다.")
        src_path = inner[0]
    if not (src_path / "draft_content.json").exists():
        sys.exit(f"{src_path} 는 캡컷 초안 폴더가 아닙니다 (draft_content.json 없음).")

    drafts = Path(args.drafts)
    source_root = Path(args.source)
    if not drafts.exists():
        sys.exit(f"캡컷 초안 폴더가 없습니다: {drafts}\n캡컷 설정 > 초안 위치를 확인해 --drafts 로 알려주세요.")
    if not source_root.exists():
        sys.exit(f"원본 영상 폴더가 없습니다: {source_root}")

    name = src_path.name
    target = drafts / name
    missing, cache = [], {}

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
            if v.startswith("##DRAFT##"):
                return str(target) + v[len("##DRAFT##"):].replace("/", os.sep)
            if v.startswith("##ROOT##"):
                return str(drafts) + v[len("##ROOT##"):].replace("/", os.sep)
        return v

    fixed = {}
    for f in src_path.glob("*.json"):
        fixed[f.name] = fix(json.loads(f.read_text(encoding="utf-8")))
    meta = fixed.get("draft_meta_info.json")
    if meta is not None:  # 캡컷 목록에 이름·위치가 제대로 보이도록
        meta.update({"draft_name": name, "draft_fold_path": str(target), "draft_root_path": str(drafts)})
    if missing:
        print("원본 폴더에서 찾지 못한 파일 (캡컷에서 빈칸으로 보입니다):")
        for m in sorted(set(missing)):
            print("  -", m)

    if capcut_running():
        print("캡컷이 켜져 있어요. 캡컷을 끄면 자동으로 넣습니다… (그만두려면 Ctrl+C)")
        while capcut_running():
            time.sleep(3)

    if target.exists():
        backup = drafts / f"{name}_백업_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.move(str(target), str(backup))
        print(f"기존 프로젝트를 {backup.name} 으로 옮겨 두었습니다.")
    shutil.copytree(src_path, target)
    for fname, data in fixed.items():
        (target / fname).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"캡컷 프로젝트 '{name}' 를 넣었습니다 → {target}\n캡컷을 켜면 목록에 보입니다.")


if __name__ == "__main__":
    main()
