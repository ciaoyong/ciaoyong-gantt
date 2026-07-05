#!/usr/bin/env python3
"""
validate.py — ciaoyong-gantt 發布前驗證（schema ＋ 公開紅線樣態掃描）

用法：
    python3 validate.py            # 驗 gantt.json ＋ 掃描 gantt.json/README.md/index.html
    python3 validate.py <file>...  # 只驗指定檔

紅線補充：已知人名等在地黑名單可放本機檔（不入 repo），
以環境變數 GANTT_BLOCKLIST 指定路徑，一行一詞。
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def is_real_date(s) -> bool:
    """格式正確且真實存在（擋 2026-99-99 這類會被 JS Date 滾動的值）。"""
    try:
        datetime.strptime(str(s), "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


STATUSES = {"idle", "active", "done", "blocked", "milestone"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

SENSITIVE = [
    ("電話樣態", re.compile(r"(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)|(?<!\d)0[2-8][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")),
    ("Email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("客戶 H 碼", re.compile(r"H-\d{9}")),
    ("舊客戶代號", re.compile(r"(?<![A-Za-z])C-\d{3,}")),
    ("統編樣態", re.compile(r"統編[^0-9]{0,4}\d{8}")),
    ("LINE ID 樣態", re.compile(r"(?<![\w@])@(?=[a-z0-9]*\d)[a-z0-9]{4,}(?![\w])")),  # 必含數字，排除 CSS @media 等
    ("非 GitHub 外部連結", re.compile(r"https?://(?!github\.com|ciaoyong\.github\.io|www\.w3\.org)[^\s\"')]+")),
]


def check_schema(path: Path) -> list[str]:
    errs = []
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"{path}: JSON 解析失敗 — {e}"]
    if not isinstance(j.get("meta"), dict) or not DATE_RE.match(j["meta"].get("updated", "")):
        errs.append("meta.updated 缺漏或非 YYYY-MM-DD")
    phases = j.get("phases")
    if not isinstance(phases, list) or not phases:
        return errs + ["phases 缺漏或為空"]
    ids = set()
    all_ids = set()
    for p in phases:
        for t in p.get("tasks", []):
            all_ids.add(t.get("id", ""))
    for p in phases:
        if not ID_RE.match(str(p.get("id", ""))):
            errs.append(f"phase id 不合法：{p.get('id')}")
        for t in p.get("tasks", []):
            tid = str(t.get("id", ""))
            label = t.get("name") or tid
            if not ID_RE.match(tid):
                errs.append(f"任務 id 不合法：{tid}")
            if tid in ids:
                errs.append(f"任務 id 重複：{tid}")
            ids.add(tid)
            if not t.get("name"):
                errs.append(f"任務 {tid} 缺 name")
            if t.get("status") not in STATUSES:
                errs.append(f"「{label}」status 不合法：{t.get('status')}")
            pr = t.get("progress")
            if not (isinstance(pr, int) and 0 <= pr <= 100):
                errs.append(f"「{label}」progress 須為 0–100 整數")
            if t.get("status") == "done" and pr != 100:
                errs.append(f"「{label}」done 但 progress ≠ 100")
            for d in ("start", "end"):
                if not DATE_RE.match(str(t.get(d, ""))):
                    errs.append(f"「{label}」{d} 缺漏或非 YYYY-MM-DD")
                elif not is_real_date(t[d]):
                    errs.append(f"「{label}」{d} 不是真實存在的日期：{t[d]}")
            if DATE_RE.match(str(t.get("start", ""))) and DATE_RE.match(str(t.get("end", ""))) \
                    and t["end"] < t["start"]:
                errs.append(f"「{label}」end 早於 start")
            for dep in t.get("deps", []):
                if dep not in all_ids:
                    errs.append(f"「{label}」的前置 {dep} 不存在")
    return errs


def scan_sensitive(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errs = []
    for name, pat in SENSITIVE:
        for m in pat.finditer(text):
            errs.append(f"{path.name}: {name} → {m.group(0)[:40]}")
    bl_path = os.environ.get("GANTT_BLOCKLIST")
    if bl_path and Path(bl_path).exists():
        for word in Path(bl_path).read_text(encoding="utf-8").split():
            if word and word in text:
                errs.append(f"{path.name}: 黑名單詞命中 → {word}")
    return errs


def main():
    here = Path(__file__).parent
    targets = [Path(a) for a in sys.argv[1:]] or [here / "gantt.json", here / "README.md", here / "index.html"]
    errs = []
    for p in targets:
        if not p.exists():
            errs.append(f"{p}: 檔案不存在")
            continue
        if p.name == "gantt.json":
            errs += check_schema(p)
        errs += scan_sensitive(p)
    if errs:
        for e in errs:
            print(f"  ✗ {e}", file=sys.stderr)
        raise SystemExit(f"驗證失敗：{len(errs)} 項。修正後才可 push。")
    print("✅ 驗證通過（schema ＋ 紅線樣態）", file=sys.stderr)


if __name__ == "__main__":
    main()
