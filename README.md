# 台股論壇熱度雷達（twheat）

量化 PTT Stock 板的討論熱度與情緒，再跟證交所／櫃買的融資、周轉率、法人、注意／處置資料交叉比對，
輸出「題材熱度」、「個股過熱分數」與警示旗標。

## 📱 手機版（推薦）：雲端每天自動跑，手機只負責看
程式跑在 GitHub Actions（免費），結果用 Telegram 推播到手機，也可以用 GitHub Pages 網址直接開。
設定只需要做一次，用電腦大約 15 分鐘，之後全部在手機上操作。

1. **建 repo**：到 github.com 建一個新 repo（Public 才能用免費的 Pages；只用 Telegram 的話 Private 也可以），把整個 twheat 資料夾的內容推上去（包含 `.github/workflows/daily.yml`）。
2. **Telegram 機器人**：在 Telegram 找 @BotFather → `/newbot` → 拿到 token；先傳一則訊息給你的 bot，再開 `https://api.telegram.org/bot<token>/getUpdates` 找到 `chat.id`。
3. **填入 Secrets**：repo → Settings → Secrets and variables → Actions → 新增 `TELEGRAM_TOKEN`、`TELEGRAM_CHAT_ID`。
4. **（選用）Pages**：Settings → Pages → Deploy from branch → `main` / `/docs`。拿到網址後在 Variables 新增 `PAGES_URL`，推播裡就會附上連結。
5. **手機操作**：用手機瀏覽器開 repo → Actions → twheat → Run workflow
   - 先跑 `check`，看 log 確認雲端連得到 PTT 和證交所
   - 再跑 `backfill`（天數 21，大約 1~2 小時）
   - 之後每個工作日台灣晚上 10 點（加州早上 7 點）會自動跑 `daily`，跑完推播到 Telegram，附上完整 HTML 報告

注意：
- 資料庫 `data/forum.db` 每次跑完都會 commit 回 repo，舊推文 60 天後會自動清掉以控制大小。
- GitHub 的伺服器在海外，如果 `check` 顯示證交所或 PTT 擋海外 IP，把 log 貼給 Claude，我們再改用其他方案。
- 報告已針對手機版面調整：第一欄固定不動，表格可以左右滑。

## 安裝（Mac 本機版）
```bash
cd twheat
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py demo        # 先看合成資料的示範報告 → reports/heat_demo.html
```

## 第一次使用
```bash
python run.py check              # 逐一測試資料來源，若有 ✗ 把輸出貼給 Claude 修
python run.py backfill --days 21 # PTT 回補 21 天（約 1~2 小時）+ 證交所 45 天
```

## 每天自動跑
台灣盤後融資、法人資料約台灣晚上 9 點前出齊，等於加州早上 6 點左右。
```bash
crontab -e
# 加州時間週一到週五早上 7:00
0 7 * * 1-5 cd /路徑/twheat && .venv/bin/python run.py daily >> data/cron.log 2>&1
```
產出：`reports/heat_YYYY-MM-DD.html`（看板）與 `reports/brief_YYYY-MM-DD.md`（直接貼給 Claude 做質化判讀）。

## Threads / CMoney
兩者都需要登入或是 app 內容，無法穩定爬取。把看到的貼文複製進一個 txt（每則之間空一行）：
```bash
python run.py import threads_0927.txt --source threads --date 2026-09-27
```

## 模型
| 元件 | 權重 | 內容 |
|---|---|---|
| A 討論熱度 | 30% | 7 日加權提及量百分位 ＋ 相對自身 28 日基期 z 分數 |
| S 情緒極端 | 20% | 看多比例偏離中性 ＋ 狂熱用語（歐印、梭哈、信貸…）密度 |
| L 槓桿擁擠 | 25% | 融資 5 日增速、周轉率的全市場百分位 |
| P 股價延伸 | 15% | 20 日／5 日報酬全市場百分位 |
| 官方警示 | 加成 | 注意股 60、處置股 100，把分數往 100 推 |

標籤：≥80 極度過熱、≥65 過熱、≥50 熱門、≥30 升溫。
旗標（比分數更重要）：散戶熱·法人賣、融資急升、討論加速、狂熱用語、恐慌投降（反向訊號）。

所有權重、題材、關鍵字、情緒字典都在 `config.py`，自己可以改。

## 已知限制（請先讀）
- 證交所／櫃買端點與欄位是依公開文件撰寫，**開發環境無法連線實測**。第一次務必跑 `check`，失敗的來源會自動略過，模型改用剩下的元件計分（報告最下方會列出來源狀態）。
- 三大法人歷史回補目前只有上市；上櫃股的「散戶熱·法人賣」旗標需要法人資料才會出現。
- 情緒是字典法，會誤判反諷與「推文說反話」。權重是啟發式，**累積 2~3 個月後用 `python run.py backtest` 驗證再調**。
- 請維持預設的請求間隔，尊重 PTT 與證交所的伺服器。
- 這是情緒與擁擠度的量化工具，不是買賣訊號，不構成投資建議。
