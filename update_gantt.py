#!/usr/bin/env python3
"""
update_gantt.py — 一鍵安全發布 gantt.json（給板主與同事的 AI 用）

做的事（照順序）：
  1. 檢查工作區：除了 gantt.json 之外不可有其他變更（本 repo 只有
     gantt.json 屬於日常維護範圍）
  2. git pull --rebase --autostash（先合線上最新版，避免蓋掉別人的更新）
  3. 自動把 meta.updated 蓋成今天
  4. 跑 validate.py（schema ＋ 公開紅線樣態掃描），不過就中止
  5. commit ＋ push，約 1 分鐘後看板生效

用法：
    python3 update_gantt.py --message "一句話說明改了什麼"
    python3 update_gantt.py --message "..." --no-push   # 只驗證與 commit，不推
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent


def run(cmd, check=True):
    r = subprocess.run(cmd, cwd=HERE, text=True, capture_output=True)
    if check and r.returncode != 0:
        print(r.stdout, file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"✗ 指令失敗：{' '.join(cmd)}")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", required=True, help="一句話說明本次更新（會進 commit 訊息，公開可見，禁個資）")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    # 1) 工作區只允許 gantt.json 有變更
    dirty = [l for l in run(["git", "status", "--porcelain"]).stdout.splitlines() if l.strip()]
    others = [l for l in dirty if not l.endswith("gantt.json")]
    if others:
        for l in others:
            print(f"  ✗ 非 gantt.json 的變更：{l}", file=sys.stderr)
        raise SystemExit("中止：本工具只發布 gantt.json；其他檔案的變更請先還原或另行處理。")

    # 2) 先併線上最新（--autostash 保住你的本地修改）
    run(["git", "pull", "--rebase", "--autostash", "origin", "main"])

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
    if not run(["git", "status", "--porcelain", "gantt.json"]).stdout.strip():
        print("沒有可發布的變更（gantt.json 與線上版相同）。", file=sys.stderr)
        return
    run(["git", "add", "gantt.json"])
    run(["git", "commit", "-m", f"update: {args.message}"])
    if args.no_push:
        print("已 commit（--no-push，未推送）。", file=sys.stderr)
        return
    run(["git", "push", "origin", "main"])
    print("✅ 已發布。約 1 分鐘後生效：https://ciaoyong.github.io/ciaoyong-gantt/", file=sys.stderr)


if __name__ == "__main__":
    main()
