# ciaoyong-gantt

喬雍 CRM 開發總規劃 · 甘特追蹤板（GitHub Pages）。

- **看板網址**：https://ciaoyong.github.io/ciaoyong-gantt/
- **單一真相**：`gantt.json` — 全團隊打開看板看到的都是這一份
- **留言／回報**：本 repo 的 Issues（板上每個任務有「💬 開 Issue 回報」）

## 協作流程

| 角色 | 做法 |
|---|---|
| 所有人（看） | 開看板網址即可，免登入 |
| 同事（回報） | 板上點任務 →「💬 開 Issue 回報」（需免費 GitHub 帳號）；或板上試改後「⤓ 匯出 JSON」傳給板主 |
| 板主（發布） | 板上改完 → 黃色橫幅 →「↥ 複製 JSON 並去 GitHub 發布」→ GitHub 編輯頁全選貼上 → Commit。約 1 分鐘生效 |

板上的編輯只存於**自己瀏覽器的草稿**；發布（commit `gantt.json`）後才對所有人生效。
打開看板時若線上版比你的草稿基準新，會明確詢問要用哪份，不會默默沿用舊草稿。

## 資料格式（schema v1）

```json
{
  "meta": { "title": "…", "updated": "YYYY-MM-DD" },
  "phases": [
    { "id": "p1", "name": "階段名", "tasks": [
      { "id": "t1", "name": "任務名", "owner": "AI",
        "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
        "status": "idle | active | done | blocked | milestone",
        "progress": 0, "note": "", "deps": ["前置任務 id"] }
    ]}
  ]
}
```

規則：

- `status` 只允許五值；`progress` 為 0–100 整數，`done` 必為 100
- `start`／`end` 必填、ISO 格式、`end ≥ start`；**已完成任務＝真實日期**，
  未來任務＝板主核定的排程日期
- `id` 全域唯一（英數 `-` `_`）；`deps`＝前置任務 id 陣列（資訊性，
  顯示於任務列與 tooltip）
- `note` 為受控欄位：禁個資與內部細節

## 更新 SOP（板主／AI）

1. 改 `gantt.json`
2. `python3 validate.py`（schema ＋ 紅線樣態掃描）**通過才可 commit**
3. commit ＋ push（本 repo 的 `gantt.json` 更新屬常設授權範圍）
4. push 後 CI 會再跑一次 validate 當保險

## 🔴 公開紅線

本 repo 全部內容公開（含 README、commit message、Issues）：

- **不出現任何客戶指涉**——姓名／電話／地址／LINE ID／Email／統編，
  **連客戶代號都不使用**（本板只有計畫任務，無客戶維度）
- 人員一律**角色代稱**（板主／AI／客服／PT／業務），不用真名
- 任務名使用抽象流程詞，內部作業細節留在私有 repo
- `validate.py` 內建樣態掃描；已知人名黑名單放本機檔
  （環境變數 `GANTT_BLOCKLIST`，不入 repo）

## 部署（一次性設定）

Settings → Pages → Source「Deploy from a branch」→ `main`／`/ (root)` → Save。
之後每次 commit 自動重新部署，約 1 分鐘生效。
