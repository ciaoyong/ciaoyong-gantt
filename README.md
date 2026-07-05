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
2. `python3 update_gantt.py --message "一句話說明"` —— 它會自動：
   pull 最新 → 蓋 `meta.updated` → 跑 `validate.py` → commit → push
3. push 後 CI 會再跑一次 validate 當保險

## 給 AI 的維護 SOP（同事的 Claude／AI 照此執行）

> 適用對象：擁有本 repo write 權限的 GitHub 帳號（org 成員）。
> 一次性設定：`gh auth login`（或已設 git 憑證）。

1. **取得／更新 repo**：
   - 本機沒有：`git clone https://github.com/ciaoyong/ciaoyong-gantt.git`
   - 已有：先 `git pull`
2. **只改 `gantt.json`**，依上方「資料格式」：
   - 改日期／狀態／進度：找到該任務改欄位值（status 五值、progress 0–100、
     done 必 100、日期 YYYY-MM-DD 且 end ≥ start）
   - 新增任務：加進對應 phase 的 `tasks`，`id` 全域唯一、`deps` 填前置任務 id
   - **本 repo 其他檔案一律不動**（index.html／validate.py 等由板主維護）
3. **發布**：`python3 update_gantt.py --message "一句話說明"`
   （自動驗證＋推送；驗證不過會列出原因，修好重跑）
4. **push 被拒**＝別人剛更新過：重跑一次 update_gantt.py 即可（內建 rebase）
5. 🔴 **公開紅線（每次都要自檢）**：gantt.json 與 commit 訊息**不可出現**
   客戶姓名／電話／地址／LINE ID／Email／統編／客戶代號；人員一律
   角色代稱（板主／AI／客服／PT／業務）；任務名用抽象流程詞。
   拿不準就不要寫，回報板主。

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
