# GitHub 排程診斷（2026-09-09）

監控仍使用 GitHub Actions，原 cron 保留 `*/5 * * * *`。本次未加入外部服務。

## 已確認

- `main` 是預設分支，workflow 已提交到 `main`。
- 儲存庫公開、未封存，Actions enabled，allowed_actions=all。
- `availability.yml` 狀態 active；停用再啟用沒有立刻產生 schedule 紀錄。
- 兩次 workflow_dispatch 都成功，表示監控可在 hosted runner 執行。
- `actionlint` v1.7.12 檢查原 workflow 與診斷 workflow，退出碼為 0。
- `schedule-probe.yml` 是獨立測試：沒有 workflow_dispatch、concurrency、checkout 或第三方 action。
  cron 為 `2-57/5 * * * *`；push 觸發於 01:01:33 UTC 成功。
- 相同帳號的 `randy-tsukemen/hiking` 已有真正 schedule 紀錄，且同時設定 workflow_dispatch。
  `.github/workflows/smoke.yml` 自 2026-07-07 未變更，cron 是 `0 22 * * 0`。
  2026-09-06 原定 22:00 UTC，實際 23:19:47 UTC 建立執行（延遲 79 分 47 秒）。
  2026-08-30 原定 22:00 UTC，實際 2026-08-31 00:00:38 UTC 建立執行（延遲 120 分 38 秒）。

## 判讀界線

沒有 schedule run 表示尚未出現排程觸發的執行紀錄；不是監控 Python 已啟動後失敗。
目前最有依據的推測是 GitHub 排程派發延遲，但 API 未揭露排程佇列，無法據此確認根因。
GitHub Status 顯示正常也不保證單一 schedule 準時。
手動成功、push 成功、workflow active，都不等於 cron 已成功。

## 查驗

```sh
gh run list --repo randy-tsukemen/tateyama --event schedule --limit 10 \
  --json workflowName,event,status,conclusion,createdAt,url
gh workflow list --repo randy-tsukemen/tateyama --all
```

- 原監控有 schedule 紀錄：再核對結果及後續間隔；單次成功不保證每五分鐘準時。
- 只有 probe 有 schedule 紀錄：原 workflow 的排程登錄值得進一步隔離。
- 兩者均無：無法歸因於手動觸發、第三方 action 或監控程式；需繼續觀察 GitHub 派發。

probe 不查詢訂房網站，不發空位通知。確認排程行為後停用／移除，避免永久留下測試排程。

## 官方規則

- 多個事件可同時存在：https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#using-multiple-events
- schedule 可延遲／漏跑，最短五分鐘：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
