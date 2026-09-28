# -*- coding: utf-8 -*-
"""驗證模型：各熱度標籤之後 5 / 20 個交易日的報酬，跟同期全市場比。
需要每天跑 daily 累積 scores 與 prices，至少 2~3 個月才有意義。"""
import pandas as pd


def run(conn, horizons=(5, 20)):
    try:
        sc = pd.read_sql("SELECT asof, code, score, label FROM scores", conn)
    except Exception:  # noqa
        print("還沒有 scores 紀錄，請先每天跑 daily。")
        return None
    px = pd.read_sql("SELECT date, code, close FROM prices", conn)
    if sc.empty or px.empty:
        print("資料不足。")
        return None
    pw = px.pivot(index="date", columns="code", values="close").sort_index()
    dates = list(pw.index)
    mkt = pw.pct_change(fill_method=None)
    out = []
    for _, r in sc.iterrows():
        i0 = next((i for i, d in enumerate(dates) if d >= r["asof"]), None)
        if i0 is None or r["code"] not in pw:
            continue
        row = {"label": r["label"], "score": r["score"]}
        for h in horizons:
            if i0 + h < len(dates):
                p0, p1 = pw[r["code"]].iloc[i0], pw[r["code"]].iloc[i0 + h]
                ret = p1 / p0 - 1 if p0 and p0 == p0 else None
                bench = (pw.iloc[i0 + h] / pw.iloc[i0] - 1).median()
                row[f"fwd{h}"] = ret
                row[f"ex{h}"] = None if ret is None else ret - bench
        out.append(row)
    df = pd.DataFrame(out)
    cols = [c for c in df.columns if c.startswith(("fwd", "ex"))]
    if not cols:
        print("前瞻報酬期間還不夠長。")
        return None
    g = df.groupby("label")[cols].agg(["mean", "median"]) * 100
    n = df.groupby("label").size().rename("樣本數")
    win = df.groupby("label")[[c for c in cols if c.startswith("ex")]].apply(lambda x: (x > 0).mean())
    pd.set_option("display.width", 200)
    print("=== 各標籤前瞻報酬（ex = 超額，相對全市場中位數）===")
    print(n.to_string())
    print(g.round(2).to_string())
    print("\n=== 超額報酬勝率 ===")
    print((win * 100).round(1).to_string())
    return df
