# 立山空床監控

監控以下兩個入住日，皆為 **1 位成人、入住 1 晚**：

- 2026-10-10 入住、2026-10-11 退房。
- 2026-10-11 入住、2026-10-12 退房。

- 雷鳥莊：日曆全部五種房型（房數按網站原樣顯示，個室及雙人房需自行確認入住限制）。
- みくりが池温泉：男女共用 6 人相部屋、8 人上下舖相部屋、官網限定 4 人相部屋。

## 五分鐘觸發器

`dispatcher.yml` 在 GitHub-hosted runner 內每隔 300 秒呼叫 `availability.yml` 的
`workflow_dispatch` API。使用 GitHub 提供的短期 `GITHUB_TOKEN`（actions: write），不存個人 Token。
每輪最多檢查 12 次，接著啟動下一輪，傳遞下次執行時間。併發群組保證只有一個觸發器正在執行。
監控失敗不會終止觸發器，因此有空位時仍持續查詢並產生失敗紀錄。

- 啟動：Actions →「立山監控五分鐘觸發器」→ Run workflow，使用預設輸入。
- 停止：**先停用觸發器 workflow，再取消它正在執行及排隊中的 runs**。程式每 30 秒檢查是否停用；
  也可以停用監控 workflow，觸發器在下一次檢查後停止接續。
- 重新啟動：啟用兩個 workflow，再手動啟動觸發器一次。
- 到期：2026-10-12 00:00 JST 起不再 dispatch／接續。建議同時停用觸發器，以停止每小時備援 cron。
- 原監控已移除 cron。觸發器保留每小時第 17 分鐘的 cron，僅用於中斷後的盡力恢復。
  GitHub cron 仍可能延遲，所以 runner 取消、平台故障或接續 API 失敗時，不保證能即時恢復。
- API 請求每五分鐘送出；runner 排隊、接續及請求時間會讓實際開始時間稍晚。跳過錯過的時段，不密集補跑。
- `next_at` 是接續用的 Unix timestamp；一般手動啟動請留空。`cycles` 僅用於控制每輪長度。

有空位以 exit code 1 讓監控失敗；網站讀取異常以 exit code 2 失敗，摘要明確區分。
每次仍有空位都會失敗，不去除重複通知。無空位則成功。

## Telegram 通知（主要通知管道）

免費 Telegram Bot 直接傳送通知，不依賴 GitHub 失敗信件的通知規則。
GitHub Secrets 需有 `TELEGRAM_BOT_TOKEN` 與 `TELEGRAM_CHAT_ID`。

- 有空位：傳送入住日期、飯店、房型、網站狀態及訂房連結。每次五分鐘檢查仍有空位就再提醒。
- 額滿：不傳訊息。
- 網站查詢異常：傳送「監控異常（不是空位通知）」。
- API 限流、暫時性錯誤及網路失敗最多嘗試三次；重試可能造成重複訊息。
- API 接受訊息不代表手機已顯示／已讀。請開啟 Telegram 通知，勿將 Bot 靜音。
- 手動啟動空床監控並勾選 `test_notification`，會先傳 Telegram 測試，再刻意失敗以測試 Email。
- 初次設定 workflow 只接受唯一的私人 `/start` 對話；Chat ID 經 RSA 加密後才輸出，
  在本機解密並存入 Secret，Token 與 Chat ID 不公開。設定完成後停用此 workflow。
- 若觸發器／GitHub 平台完全停擺，通知程式也不會執行；本方案不提供獨立心跳監控。

## Email 設定

在 https://github.com/settings/notifications 的 Actions 區域啟用 Email，並選擇只通知失敗的工作。
GitHub 通知取決於個人設定，程式不需要 SMTP 密碼，也不會直接寄信。
Actions 頁面可手動 Run workflow，每次摘要包含房型、狀態及訂房連結。
觸發器使用機器人身分，Email 是否送達必須實測；在觸發器勾選 `test_notification`，
會啟動一次明確標示「通知測試（非空位通知）」的失敗，不接續下一輪。
請確認已 Watch 此儲存庫並開啟 Actions Email。測試失敗只證明流程成立，不證明信件已送達。

目前儲存庫公開，使用標準 `ubuntu-latest` GitHub-hosted runner，不消耗私人儲存庫的 Actions 分鐘額度。
每天約 288 次監控，另有持續運作的觸發器 runner。若未來改回私人儲存庫，請重新確認 Actions 額度。

## 本機執行

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python monitor.py --date 2026-10-10 --date 2026-10-11
```

使用 requests（逾時及最多兩次重試）與 BeautifulSoup，只讀取四個公開訂房頁面，不提交預約。
みくりが池温泉讀取頁面 Object.assign(data_ve, ...) 的 JSON，核對方案、房型、日期及人數，
再取指定月份與日期的 roomSalesStatusKbn。只有 ○／△ 且有價格才報空位。
雷鳥莊核對年月日，僅有正數室數及訂房連結才報空位。
缺少目標日或未知格式視為監控異常，不當成額滿。

測試涵蓋空位／額滿／停止銷售、錯日期、未知格式、訂房連結與部分網站失敗時仍回報空位。
results.json 是本機檢查結果，不納入 Git。
