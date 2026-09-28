# -*- coding: utf-8 -*-
"""產生合成資料，讓你不連網也能看到整套輸出長什麼樣子。數字全是假的。"""
import random
import datetime as dt
import numpy as np

from config import SEED_NAMES, THEMES, BULL, BEAR, EUPHORIA, PANIC


def build(conn, days=42, seed=7):
    rnd = random.Random(seed)
    rs = np.random.default_rng(seed)
    today = dt.date.today()
    names = dict(SEED_NAMES)
    for i in range(150):                      # 填充股，讓全市場百分位有意義
        names[f"{9100+i}"] = f"填充{i}"
    conn.executemany("INSERT OR REPLACE INTO companies VALUES(?,?,?,?)",
                     [(c, n, "DEMO", float(rs.integers(2, 30)) * 1e8) for c, n in names.items()])
    hot = set(THEMES["CPO/矽光子"]["tickers"])          # 劇本：CPO 近 10 天暴熱、法人倒貨
    cold = set(THEMES["記憶體"]["tickers"])             # 劇本：記憶體恐慌
    warm = set(THEMES["重電"]["tickers"])               # 劇本：重電穩定升溫
    real = list(SEED_NAMES)
    base_rate = {c: rs.uniform(0.3, 3) for c in real}
    base_rate["2330"] = 12

    def fmt(code):
        return rnd.choice([code, SEED_NAMES[code], f"{code} {SEED_NAMES[code]}"])

    pid = 0
    for k in range(days, -1, -1):
        d = today - dt.timedelta(days=k)
        ramp = max(0, 10 - k) / 10
        for code in real:
            lam = base_rate[code]
            mood = {"b": BULL, "e": [], "p": []}
            if code in hot:
                lam *= 1 + 7 * ramp
                mood["e"] = EUPHORIA if ramp > 0.3 else []
            if code in cold and k < 8:
                lam *= 2.5
                mood = {"b": BEAR, "e": [], "p": PANIC}
            if code in warm:
                lam *= 1 + 0.08 * (days - k) / 3
            for _ in range(rs.poisson(lam)):
                pid += 1
                side = "空" if mood["b"] is BEAR else rnd.choice(["多", "多", None])
                title = f"[標的] {code} {SEED_NAMES[code]} {side or '多空不明'}" if rnd.random() < .3 else f"[閒聊] {fmt(code)} 今天"
                body = f"{fmt(code)} " + " ".join(rnd.choices(mood["b"], k=2) + rnd.choices(mood["e"] or [""], k=1))
                p = f"DEMO.{pid}"
                conn.execute("INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                             (p, "demo", "Stock", None, title, f"user{rnd.randint(1,400)}", d.isoformat(),
                              d.isoformat(), "標的", side, body, 0, 0, 0))
                cm = []
                for j in range(rs.poisson(12 if code in hot and ramp > 0 else 5)):
                    words = rnd.choices(mood["b"], k=1) + (rnd.choices(mood["e"], k=1) if mood["e"] and rnd.random() < .4 else []) \
                        + (rnd.choices(mood["p"], k=1) if mood["p"] and rnd.random() < .4 else [])
                    cm.append((p, j, rnd.choice(["推", "推", "→", "噓"]), f"u{rnd.randint(1,900)}", " ".join(words), d.isoformat()))
                conn.executemany("INSERT INTO comments VALUES(?,?,?,?,?,?)", cm)
    # 行情
    tdays = [today - dt.timedelta(days=k) for k in range(days + 30, -1, -1)]
    tdays = [d for d in tdays if d.weekday() < 5]
    for code in names:
        price, mbal = rs.uniform(30, 900), rs.uniform(1e6, 3e7)
        for i, d in enumerate(tdays):
            left = len(tdays) - i
            drift = 0.0
            if code in hot and left <= 12:
                drift = 0.03
            if code in cold and left <= 8:
                drift = -0.025
            if code in warm:
                drift = 0.004
            price *= 1 + drift + rs.normal(0, 0.018)
            mbal *= 1 + (0.04 if code in hot and left <= 8 else 0) + rs.normal(0, 0.01)
            vol = rs.uniform(1e6, 2e7) * (3 if code in hot and left <= 10 else 1)
            net = rs.normal(0, 0.03) * vol - (0.06 * vol if code in hot and left <= 6 else 0)
            conn.execute("INSERT OR REPLACE INTO prices VALUES(?,?,?,?)", (d.isoformat(), code, round(price, 2), vol))
            conn.execute("INSERT OR REPLACE INTO margin VALUES(?,?,?,?)", (d.isoformat(), code, mbal, mbal * .1))
            conn.execute("INSERT OR REPLACE INTO inst VALUES(?,?,?)", (d.isoformat(), code, net))
    conn.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", (tdays[-2].isoformat(), "3363", "notice"))
    conn.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", (tdays[-1].isoformat(), "4979", "punish"))
    conn.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (dt.datetime.now().isoformat(timespec='seconds'), "demo", 1, pid, "合成資料"))
    conn.commit()
    print(f"[DEMO] 產生 {pid} 篇合成文章")
