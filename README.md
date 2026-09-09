# 立山空床監控

監控 **2026-10-10 入住、2026-10-11 退房，1 位成人**：

- 雷鳥莊：日曆全部五種房型（房數按網站原樣顯示，個室及雙人房需自行確認入住限制）。
- みくりが池温泉：男女共用 6 人相部屋、8 人上下舖相部屋、官網限定 4 人相部屋。

GitHub Actions 每 5 分鐘執行一次（`*/5 * * * *`）。排程並非準時保證，可能延遲或漏跑。
查到空位會以 exit code 1 讓工作失敗；網路或日曆格式異常以 exit code 2 失敗，標題明確區分。
每次仍有空位都會失敗，不去除重複通知。無空位則成功。日期過後不再查詢網站；請停用 workflow 以停止啟動 runner。

## Email 設定

在 https://github.com/settings/notifications 的 Actions 區域啟用 Email，並選擇只通知失敗的工作。
GitHub 通知取決於個人設定，程式不需要 SMTP 密碼，也不會直接寄信。
Actions 頁面可手動 Run workflow，每次摘要包含房型、狀態及訂房連結。

目前儲存庫公開，使用標準 `ubuntu-latest` GitHub-hosted runner，不消耗私人儲存庫的 Actions 分鐘額度。
每天預計執行 288 次。若未來改回私人儲存庫，請重新確認 Actions 額度。

## 本機執行

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python monitor.py
```

使用 requests（逾時及最多兩次重試）與 BeautifulSoup，只讀取四個公開訂房頁面，不提交預約。
みくりが池温泉讀取頁面 Object.assign(data_ve, ...) 的 JSON，核對方案、房型、日期及人數，
再取指定月份與日期的 roomSalesStatusKbn。只有 ○／△ 且有價格才報空位。
雷鳥莊核對年月日，僅有正數室數及訂房連結才報空位。
缺少目標日或未知格式視為監控異常，不當成額滿。

測試涵蓋空位／額滿／停止銷售、錯日期、未知格式、訂房連結與部分網站失敗時仍回報空位。
results.json 是本機檢查結果，不納入 Git。
