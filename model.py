# -*- coding: utf-8 -*-
"""過熱評分模型。

Heat Score (0-100) = 加權平均(可用元件)，缺資料的元件自動剔除並重新分配權重：
  A 討論熱度  : 7 日加權提及量的橫斷面百分位 + 相對自身 28 日基期的 z 分數
  S 情緒極端  : 看多比例偏離中性的程度 + 狂熱/槓桿用語密度
  L 槓桿擁擠  : 融資 5 日增速百分位 + 5 日平均周轉率百分位（對全市場排名）
  P 股價延伸  : 20 日、5 日報酬的全市場百分位
  W 官方警示  : 處置=100、注意=60，以加成方式把分數往 100 推
另外產生不進分數、但更重要的「旗標」：散戶熱法人賣、槓桿急升、加速中、恐慌投降。
"""
import json
import numpy as np
import pandas as pd

from config import WEIGHTS, MIN_MENTIONS, LABELS, THEMES
from db import company_names


def _pct(s):
    return s.rank(pct=True) * 100


def _clip(x, lo=0, hi=100):
    return np.clip(x, lo, hi)


def label(score):
    for th, name in LABELS:
        if score >= th:
            return name
    return LABELS[-1][1]


def _market_features(conn, D):
    Ds = D.strftime("%Y-%m-%d")
    px = pd.read_sql("SELECT date, code, close, volume FROM prices WHERE date<=?", conn, params=[Ds])
    out = pd.DataFrame()
    if px.empty:
        return out, None
    pw = px.pivot(index="date", columns="code", values="close").sort_index()
    vw = px.pivot(index="date", columns="code", values="volume").sort_index()
    pw, vw = pw.iloc[-60:], vw.iloc[-60:]
    out = pd.DataFrame(index=pw.columns)
    last = pw.iloc[-1]
    if len(pw) >= 6:
        out["ret5"] = last / pw.iloc[-6] - 1
    if len(pw) >= 21:
        out["ret20"] = last / pw.iloc[-21] - 1
    out["vol5"] = vw.iloc[-5:].mean()
    sh = pd.read_sql("SELECT code, shares FROM companies WHERE shares>0", conn).set_index("code")["shares"]
    out["turnover"] = out["vol5"] / sh.reindex(out.index) * 100
    mg = pd.read_sql("SELECT date, code, margin_bal FROM margin WHERE date<=?", conn, params=[Ds])
    if not mg.empty:
        mw = mg.pivot(index="date", columns="code", values="margin_bal").sort_index()
        if len(mw) >= 6:
            base = mw.iloc[-6].replace(0, np.nan)
            out["margin_chg5"] = (mw.iloc[-1] / base - 1).reindex(out.index)
        out["margin_bal"] = mw.iloc[-1].reindex(out.index)
    ins = pd.read_sql("SELECT date, code, net FROM inst WHERE date<=?", conn, params=[Ds])
    if not ins.empty:
        iw = ins.pivot(index="date", columns="code", values="net").sort_index()
        out["inst5"] = iw.iloc[-5:].sum().reindex(out.index)
        out["inst_ratio"] = out["inst5"] / (out["vol5"] * 5).replace(0, np.nan)
    wr = pd.read_sql("SELECT date, code, kind FROM warnings", conn)
    out["W"] = 0.0
    if not wr.empty:
        wr["date"] = pd.to_datetime(wr["date"])
        notice = set(wr[(wr.kind == "notice") & (wr.date > D - pd.Timedelta(days=7))].code)
        punish = set(wr[(wr.kind == "punish") & (wr.date > D - pd.Timedelta(days=14))].code)
        out.loc[out.index.isin(notice), "W"] = 60.0
        out.loc[out.index.isin(punish), "W"] = 100.0
    # 全市場百分位
    if "ret20" in out or "ret5" in out:
        parts = []
        if "ret20" in out:
            parts.append((_pct(out["ret20"]), 0.6))
        if "ret5" in out:
            parts.append((_pct(out["ret5"]), 0.4))
        tot = sum(w for _, w in parts)
        out["P"] = sum(p * w for p, w in parts) / tot
    lp = []
    if "margin_chg5" in out and out["margin_chg5"].notna().any():
        lp.append(_pct(out["margin_chg5"]))
    if out["turnover"].notna().any():
        lp.append(_pct(out["turnover"]))
    if lp:
        out["L"] = pd.concat(lp, axis=1).mean(axis=1)
    return out, pw.index[-1]


def compute(conn, asof=None):
    m = pd.read_sql("SELECT code, date, weight, bull, bear, euph, panic, author, kind FROM mentions", conn)
    if m.empty:
        raise RuntimeError("資料庫沒有任何論壇提及資料，請先跑 scrape 或 demo")
    m["date"] = pd.to_datetime(m["date"])
    D = pd.to_datetime(asof) if asof else m["date"].max()
    start = D - pd.Timedelta(days=34)
    covered = set(pd.to_datetime(pd.read_sql("SELECT DISTINCT date FROM posts", conn)["date"]))
    mm = m[(m.date >= start) & (m.date <= D)]
    rng = pd.date_range(start, D)
    wp = (mm.groupby(["code", "date"])["weight"].sum().unstack("date")
          .reindex(columns=rng).fillna(0.0))
    feat = pd.DataFrame(index=wp.index)
    feat["m7"] = wp.iloc[:, -7:].sum(axis=1)
    feat["m3"] = wp.iloc[:, -3:].sum(axis=1)
    base_cols = [c for c in rng[:-7] if c in covered]
    has_hist = len(base_cols) >= 14
    if has_hist:
        b = wp[base_cols]
        feat["base_daily"] = b.mean(axis=1)
        feat["z"] = (feat["m7"] / 7 - feat["base_daily"]) / (b.std(axis=1) + 0.5)
    w7 = mm[mm.date > D - pd.Timedelta(days=7)]
    s7 = w7.groupby("code").agg(n7=("weight", "size"), bull7=("bull", "sum"), bear7=("bear", "sum"),
                                 euph7=("euph", "sum"), panic7=("panic", "sum"), authors7=("author", "nunique"))
    feat = feat.join(s7)
    feat = feat[feat["m7"] >= MIN_MENTIONS].copy()
    if feat.empty:
        raise RuntimeError("近 7 天沒有任何個股達到最低提及門檻")
    # A
    feat["A"] = _pct(np.log1p(feat["m7"]))
    if has_hist:
        feat["A"] = 0.5 * feat["A"] + 0.5 * _clip(50 + 20 * feat["z"].fillna(0))
    feat["accel"] = (feat["m3"] / 3 + 0.5) / ((feat["m7"] - feat["m3"]) / 4 + 0.5)
    # S
    feat["bull_share"] = (feat["bull7"] + 1) / (feat["bull7"] + feat["bear7"] + 2)
    feat["euph_rate"] = feat["euph7"] / feat["n7"].clip(lower=1)
    feat["panic_rate"] = feat["panic7"] / feat["n7"].clip(lower=1)
    feat["S"] = (0.6 * _clip(100 * (feat["bull_share"] - 0.5) / 0.35)
                 + 0.4 * _clip(100 * feat["euph_rate"] / 0.10))
    # 市場面
    mk, trade_date = _market_features(conn, D)
    if not mk.empty:
        feat = feat.join(mk, how="left")
    for c in ("P", "L", "W"):
        if c not in feat:
            feat[c] = np.nan
    # 綜合分數：缺值元件權重重新分配
    core = ["A", "S", "L", "P"]
    comp = feat[core]
    wts = pd.Series({k: WEIGHTS[k] for k in core})
    avail = comp.notna()
    base = (comp.fillna(0) * wts).sum(axis=1) / (avail * wts).sum(axis=1)
    # 官方警示當作「往 100 推」的加成，而不是沒警示就扣分
    feat["score"] = base + WEIGHTS["W"] * feat["W"].fillna(0) * (1 - base / 100)
    feat["coverage"] = avail.dot(wts) / wts.sum()
    feat["label"] = feat["score"].apply(label)
    # 旗標
    flags = []
    for code, r in feat.iterrows():
        f = []
        if r.get("W", 0) >= 100:
            f.append("處置中")
        elif r.get("W", 0) >= 60:
            f.append("注意股")
        if r["A"] >= 70 and r["bull_share"] >= 0.65 and pd.notna(r.get("inst_ratio")) and r["inst_ratio"] < -0.02:
            f.append("散戶熱·法人賣")
        if pd.notna(r.get("margin_chg5")) and r["margin_chg5"] >= 0.10 and r["A"] >= 60:
            f.append(f"融資5日+{r['margin_chg5']*100:.0f}%")
        if r["accel"] >= 2.0 and r["m3"] >= 5:
            f.append("討論加速")
        if r["euph_rate"] >= 0.10:
            f.append("狂熱用語")
        if r["panic_rate"] >= 0.10 and r["bull_share"] <= 0.4:
            f.append("恐慌投降(反向)")
        flags.append("、".join(f))
    feat["flags"] = flags
    names = company_names(conn)
    feat["name"] = [names.get(c, "") for c in feat.index]
    feat["spark"] = [json.dumps([round(x, 2) for x in wp.loc[c].iloc[-28:].tolist()]) for c in feat.index]
    feat = feat.sort_values("score", ascending=False)
    feat.index.name = "code"

    themes = _themes(conn, wp, feat, D, start, covered)
    market = _market_mood(mm, wp, D, covered, base_cols)
    health = pd.read_sql("SELECT source, ok, rows, msg, MAX(ts) AS ts FROM runs GROUP BY source ORDER BY source", conn)
    return {"asof": D.strftime("%Y-%m-%d"), "trade_date": trade_date, "has_hist": has_hist,
            "tickers": feat, "themes": themes, "market": market, "health": health}


def _themes(conn, wp, feat, D, start, covered):
    th = pd.read_sql("SELECT theme, date, weight FROM theme_hits WHERE date>=?", conn,
                     params=[start.strftime("%Y-%m-%d")])
    th["date"] = pd.to_datetime(th["date"])
    th = th[th.date <= D]
    rows = []
    for t, spec in THEMES.items():
        mem = [c for c in spec["tickers"] if c in wp.index]
        kw = th[th.theme == t].groupby("date")["weight"].sum().reindex(wp.columns).fillna(0)
        series = kw + (wp.loc[mem].sum() if mem else 0)
        m7 = series.iloc[-7:].sum()
        base = series[[c for c in wp.columns[:-7] if c in covered]]
        trend = (m7 / 7) / (base.mean() + 0.5) if len(base) >= 14 else np.nan
        inf = feat[feat.index.isin(spec["tickers"])]
        score = np.average(inf["score"], weights=inf["m7"]) if len(inf) else np.nan
        breadth = (inf["score"] >= 65).mean() if len(inf) else np.nan
        top = "、".join(f"{r['name'] or c}({r['score']:.0f})" for c, r in inf.head(4).iterrows())
        rows.append({"theme": t, "m7": m7, "trend": trend, "score": score, "breadth": breadth,
                     "n_hot": len(inf), "top": top, "spark": json.dumps([round(x, 2) for x in series.iloc[-28:].tolist()])})
    df = pd.DataFrame(rows)
    df["m7_pct"] = _pct(df["m7"])
    return df.sort_values(["score", "m7"], ascending=False, na_position="last")


def _market_mood(mm, wp, D, covered, base_cols):
    w7 = mm[mm.date > D - pd.Timedelta(days=7)]
    bull, bear = w7["bull"].sum(), w7["bear"].sum()
    n = max(len(w7), 1)
    bs = (bull + 1) / (bull + bear + 2)
    er = w7["euph"].sum() / n
    pr = w7["panic"].sum() / n
    parts = [_clip(100 * (bs - 0.4) / 0.3), _clip(100 * er / 0.06)]
    zvol = np.nan
    tot = wp.sum()
    if len(base_cols) >= 14:
        b = tot[base_cols]
        zvol = (tot.iloc[-7:].mean() - b.mean()) / (b.std() + 1)
        parts.append(_clip(50 + 20 * zvol))
    greed = float(np.mean(parts))
    return {"greed": greed, "bull_share": bs, "euph_rate": er, "panic_rate": pr, "zvol": zvol,
            "mentions7": float(tot.iloc[-7:].sum()), "posts7": int(w7[w7.kind == "post"].shape[0]),
            "spark": [round(x, 1) for x in tot.iloc[-28:].tolist()]}


def save_scores(conn, res):
    t = res["tickers"].reset_index()
    t.insert(0, "asof", res["asof"])
    cols = ["asof", "code", "name", "score", "label", "flags", "A", "S", "L", "P", "W", "m7", "accel",
            "bull_share", "euph_rate", "margin_chg5", "inst_ratio", "ret20", "turnover"]
    for c in cols:
        if c not in t.columns:
            t[c] = np.nan
    t = t[cols]
    try:
        conn.execute("DELETE FROM scores WHERE asof=?", (res["asof"],))
    except Exception:  # noqa  第一次還沒有這張表
        pass
    t.to_sql("scores", conn, if_exists="append", index=False)
    conn.commit()
