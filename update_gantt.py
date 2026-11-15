#!/usr/bin/env python3
"""
update_gantt.py — 一鍵安全發布看板資料（給板主與同事的 AI 用）

做的事（照順序）：
  1. 檢查工作區與暫存區：只允許根目錄白名單檔有變更，rename 兩端都檢查
     （gantt.json＝甘特資料；pdca.json＝PDCA 子頁手工欄位。
      兩者皆屬日常維護範圍；index.html / pdca.html 等程式檔不在此列，
      要改請走一般 git 流程並人工檢視）
  2. git pull --rebase --autostash（先合線上最新版，避免蓋掉別人的更新）
  3. 自動把 meta.updated 蓋成今天
  4. 跑 validate.py（schema ＋ 公開紅線樣態掃描），不過就中止
  5. 只 commit 本次資料路徑，核對實際提交範圍後才 push，約 1 分鐘後看板生效

用法：
    python3 update_gantt.py --message "一句話說明改了什麼"
    python3 update_gantt.py --message "..." --no-push   # 仍會 pull、改資料與 commit，只是不 push（非唯讀）
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 可用本工具發布的資料檔（程式檔不在此列，避免一鍵推程式）
PUBLISHABLE = ("gantt.json", "pdca.json")


def run(cmd, check=True, *, text=True):
    r = subprocess.run(cmd, cwd=HERE, text=text, capture_output=True)
    if check and r.returncode != 0:
        print(r.stdout, file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"✗ 指令失敗：{' '.join(cmd)}")
    return r



def nul_fields(raw):
    """只解析完整的 NUL 格式；不把換行、引號或箭頭當成路徑分隔符。"""
    if not isinstance(raw, bytes) or (raw and not raw.endswith(b"\0")):
        raise SystemExit("中止：Git 路徑輸出格式不完整，未繼續發布。")
    fields = raw[:-1].split(b"\0") if raw else []
    if any(not field for field in fields):
        raise SystemExit("中止：Git 路徑輸出包含空欄位，未繼續發布。")
    return fields


def parse_status(raw):
    """porcelain v1 -z 的 rename/copy：目的路徑在前，來源路徑另佔一欄。"""
    fields = iter(nul_fields(raw))
    entries = []
    for record in fields:
        if len(record) < 4 or record[2:3] != b" ":
            raise SystemExit("中止：Git 狀態格式不明，未繼續發布。")
        status = record[:2]
        paths = [os.fsdecode(record[3:])]
        if b"R" in status or b"C" in status:
            source = next(fields, None)
            if source is None:
                raise SystemExit("中止：Git rename/copy 缺來源路徑，未繼續發布。")
            paths.append(os.fsdecode(source))
        entries.append((status, paths))
    return entries


def require_allowed(paths):
    others = sorted(set(paths) - set(PUBLISHABLE))
    if others:
        for path in others:
            print(f"  ✗ 非白名單路徑：{path!r}", file=sys.stderr)
        raise SystemExit(
            f"中止：本工具只發布根目錄的 {'／'.join(PUBLISHABLE)}；其他工作內容原樣保留，請另行處理。")


def staged_paths():
    # --no-renames 讓來源的刪除與目的的新增各自列出，不只檢查 rename 目的端。
    raw = run(["git", "diff", "--cached", "--name-only", "--no-renames", "-z", "--"], text=False).stdout
    paths = [os.fsdecode(field) for field in nul_fields(raw)]
    require_allowed(paths)
    return paths


def check_publish_scope():
    top = run(["git", "rev-parse", "--show-toplevel"]).stdout.rstrip("\n")
    if Path(top).resolve() != HERE:
        raise SystemExit("中止：發布腳本不在 Git 根目錄，未繼續發布。")
    raw = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all",
               "--ignore-submodules=none"], text=False).stdout
    entries = parse_status(raw)
    changed = set()
    safe_statuses = {b" M", b"M ", b"MM", b"A ", b"AM", b"R ", b"RM", b" R",
                     b"C ", b"CM", b" C", b"??"}
    for status, paths in entries:
        require_allowed(paths)
        if status not in safe_statuses:
            raise SystemExit(f"中止：資料檔狀態 {status!r} 不適合一鍵發布（刪除／型別變更／衝突等），請另行處理。")
        changed.update(paths)
    staged_paths()  # 獨立核對整個 index，包含執行前就已 stage 的內容。
    for name in PUBLISHABLE:
        path = HERE / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SystemExit(f"中止：{name} 必須是一般檔案，不能是 symlink 或目錄。")
    if not (HERE / "gantt.json").is_file():
        raise SystemExit("中止：缺少一般檔案 gantt.json，未繼續發布。")
    return [name for name in PUBLISHABLE if name in changed]


def commit_data(message, paths):
    """commit 本身限路徑；hook 或並行動作改動歷史時，保留現況並阻止 push。"""
    before = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    result = run(["git", "commit", "--only", "-m", f"update: {message}", "--", *paths], check=False)
    after = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end="")
        if after != before:
            raise SystemExit(f"中止：commit 指令失敗但 HEAD 已變為 {after}；保留本機現況，未 push，請人工檢查。")
        raise SystemExit("中止：commit 失敗，未 push；工作區與暫存內容保留供檢查。")
    parents = run(["git", "rev-list", "--parents", "-n", "1", after]).stdout.split()
    if parents != [after, before]:
        raise SystemExit(f"中止：commit 歷史非預期的單一提交（HEAD {after}）；保留本機現況，未 push。")
    raw = run(["git", "diff", "--name-only", "--no-renames", "-z", before, after, "--"], text=False).stdout
    committed = [os.fsdecode(field) for field in nul_fields(raw)]
    if not committed or not set(committed).issubset(paths):
        raise SystemExit(f"中止：已產生本機 commit {after}，但提交路徑超出本次範圍；未 push，請人工檢查。")
    return after

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", required=True, help="一句話說明本次更新（會進 commit 訊息，公開可見，禁個資）")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    check_publish_scope()  # 任何 pull／資料寫入前先拒絕範圍外的變更。

    # 0) --message 會進公開 commit 訊息：先用 validate.py 同一套紅線樣態掃它（2026-10-22）
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(args.message)
        tmp = tf.name
    mv = run([sys.executable, str(HERE / "validate.py"), tmp], check=False)
    Path(tmp).unlink(missing_ok=True)
    if mv.returncode != 0:
        print(mv.stderr, file=sys.stderr, end="")
        raise SystemExit("中止：--message 含紅線樣態（電話／Email／客戶代號／外部連結等），未發布。")

    # 1) 訊息驗證期間可能有其他線寫入，pull 前再次核對。
    check_publish_scope()

    # 2) 先併線上最新（--autostash 保住你的本地修改）
    run(["git", "pull", "--rebase", "--autostash", "origin", "main"])

    check_publish_scope()  # 合線後重查，避免新狀態或 symlink 被直接寫入。

    # 3) meta.updated ＝ 今天
    gp = HERE / "gantt.json"
    j = json.loads(gp.read_text(encoding="utf-8"))
    j.setdefault("meta", {})["updated"] = date.today().isoformat()
    gp.write_text(json.dumps(j, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 4) 驗證（schema ＋ 紅線樣態）
    v = run([sys.executable, str(HERE / "validate.py")], check=False)
    print(v.stderr, file=sys.stderr, end="")
    if v.returncode != 0:
        raise SystemExit("中止：驗證未通過，未發布。請依上列錯誤修正 gantt.json 後重跑。")

    # 5) commit ＋ push
    changed = check_publish_scope()
    if not changed:
        print("沒有可發布的變更（資料檔與線上版相同）。", file=sys.stderr)
        return
    run(["git", "add", "--", *changed])
    check_publish_scope()
    staged = staged_paths()
    if not staged:
        print("沒有可提交的資料變更。", file=sys.stderr)
        return
    committed = commit_data(args.message, [name for name in PUBLISHABLE if name in staged])
    if args.no_push:
        print("已 commit（--no-push，未推送）。", file=sys.stderr)
        return
    run(["git", "push", "origin", f"{committed}:refs/heads/main"])
    print("✅ 已發布。約 1 分鐘後生效：https://ciaoyong.github.io/ciaoyong-gantt/", file=sys.stderr)


if __name__ == "__main__":
    main()
