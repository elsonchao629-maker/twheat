# -*- coding: utf-8 -*-
"""手機推播：Telegram。設定 TELEGRAM_TOKEN 與 TELEGRAM_CHAT_ID 才會啟用。"""
import os
import requests


def send(res, html_path):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[notify] 未設定 Telegram，略過")
        return
    mk, th, t = res["market"], res["themes"], res["tickers"]
    lines = [f"📊 台股論壇熱度 {res['asof']}",
             f"貪婪指數 {mk['greed']:.0f}｜看多 {mk['bull_share']*100:.0f}%｜狂熱用語 {mk['euph_rate']*100:.1f}%", "",
             "🔥 題材"]
    for _, r in th.dropna(subset=["score"]).head(4).iterrows():
        lines.append(f"• {r['theme']} {r['score']:.0f}（{r['top'].split('、')[0]}）")
    lines += ["", "⚠️ 個股"]
    for code, r in t.head(8).iterrows():
        f = f"｜{r['flags']}" if r["flags"] else ""
        lines.append(f"• {code} {r['name']} {r['score']:.0f} {r['label']}{f}")
    url = os.getenv("PAGES_URL")
    if url:
        lines += ["", url]
    base = f"https://api.telegram.org/bot{token}"
    try:
        requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": "\n".join(lines)}, timeout=20)
        with open(html_path, "rb") as fh:          # 附上完整報告，手機點開即可看
            requests.post(f"{base}/sendDocument", data={"chat_id": chat},
                          files={"document": (os.path.basename(html_path), fh, "text/html")}, timeout=60)
        print("[notify] Telegram 已送出")
    except requests.RequestException as e:
        print(f"[notify] 失敗 {e!r}")
