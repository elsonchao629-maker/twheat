# -*- coding: utf-8 -*-
"""台股論壇熱度雷達 CLI

  python run.py check                  測試所有資料來源
  python run.py backfill --days 21     第一次使用：回補 PTT 21 天 + 證交所 45 天
  python run.py daily                  每天跑一次：抓資料 → 計分 → 產出報告
  python run.py import threads.txt --source threads   匯入手動複製的貼文
  python run.py report                 只重新計分與出報告
  python run.py backtest               驗證模型
  python run.py demo                   合成資料示範
"""
import os
import argparse
import datetime as dt

import config
from db import connect


def score_and_report(conn, demo=False, asof=None):
    import model
    import report
    res = model.compute(conn, asof)
    if not demo:
        model.save_scores(conn, res)
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    tag = "demo" if demo else res["asof"]
    html = report.render(res, os.path.join(config.REPORT_DIR, f"heat_{tag}.html"), demo=demo)
    md = report.brief(res, os.path.join(config.REPORT_DIR, f"brief_{tag}.md"))
    print(f"\n報告：{html}\n給 Claude 的摘要：{md}")
    # 手機版：發佈到 docs/（GitHub Pages）並推播
    import shutil
    os.makedirs("docs/archive", exist_ok=True)
    shutil.copy(html, "docs/index.html")
    shutil.copy(md, "docs/brief.md")
    if not demo:
        shutil.copy(html, f"docs/archive/{res['asof']}.html")
    import notify
    notify.send(res, html)
    t = res["tickers"].head(10)
    print("\nTop 10：")
    for code, r in t.iterrows():
        print(f"  {code} {r['name']:<8} {r['score']:5.1f} {r['label']:<5} {r['flags']}")
    return res


def prune(conn, keep_days=60):
    """控制資料庫大小（雲端版會 commit 進 repo）。提及紀錄已萃取完，舊推文與長內文可刪。"""
    cut = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    conn.execute("DELETE FROM comments WHERE date < ?", (cut,))
    conn.execute("UPDATE posts SET content = substr(content, 1, 1500) WHERE date < ?", (cut,))
    conn.commit()
    conn.execute("VACUUM")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "backfill", "daily", "import", "report", "backtest", "demo"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--source", default="manual")
    ap.add_argument("--date")
    ap.add_argument("--asof")
    ap.add_argument("--db", default=config.DB_PATH)
    a = ap.parse_args()

    if a.cmd == "check":
        import market
        market.check()
        return
    if a.cmd == "demo":
        db = "data/demo.db"
        if os.path.exists(db):
            os.remove(db)
        conn = connect(db)
        import demo
        import nlp
        demo.build(conn)
        nlp.process(conn)
        score_and_report(conn, demo=True)
        return

    conn = connect(a.db)
    import market
    import nlp
    import ptt
    if a.cmd == "backfill":
        market.fetch_companies(conn)
        ptt.scrape(conn, config.PTT_BOARD, days=a.days, delay=config.PTT_DELAY)
        market.backfill_twse(conn, days=max(45, a.days + 30), delay=config.TWSE_DELAY)
        latest = market.fetch_prices_today(conn)
        market.fetch_margin_today(conn, latest or market.today_tpe())
        market.fetch_warnings(conn)
        nlp.process(conn)
        score_and_report(conn)
    elif a.cmd == "daily":
        if dt.date.today().weekday() == 0 or not conn.execute("SELECT 1 FROM companies LIMIT 1").fetchone():
            market.fetch_companies(conn)
        ptt.scrape(conn, config.PTT_BOARD, days=2, delay=config.PTT_DELAY)
        latest = market.fetch_prices_today(conn)
        market.fetch_margin_today(conn, latest or market.today_tpe())
        if latest:
            market.fetch_twse_day(conn, latest)   # 補當日三大法人（上市）
        market.fetch_warnings(conn)
        nlp.process(conn)
        prune(conn)
        score_and_report(conn)
    elif a.cmd == "import":
        ptt.import_text(conn, a.path, a.source, a.date)
        nlp.process(conn)
    elif a.cmd == "report":
        nlp.process(conn)
        score_and_report(conn, asof=a.asof)
    elif a.cmd == "backtest":
        import backtest
        backtest.run(conn)


if __name__ == "__main__":
    main()
