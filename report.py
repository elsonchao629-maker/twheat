# -*- coding: utf-8 -*-
import os
import json
import html
import math

LABEL_COLOR = {"極度過熱": "var(--red)", "過熱": "var(--orange)", "熱門": "var(--yellow)",
               "升溫": "var(--blue)", "冷": "var(--muted)"}


def _f(x, fmt="{:.0f}", na="—"):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return na
        return fmt.format(x)
    except (TypeError, ValueError):
        return na


def spark(vals, w=90, h=22):
    if isinstance(vals, str):
        vals = json.loads(vals)
    if not vals:
        return ""
    mx = max(vals) or 1
    step = w / max(len(vals) - 1, 1)
    pts = " ".join(f"{i*step:.1f},{h - (v/mx)*(h-2) - 1:.1f}" for i, v in enumerate(vals))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline fill="none" stroke="currentColor" stroke-width="1.5" points="{pts}"/></svg>')


def bar(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return '<span class="na">—</span>'
    return f'<span class="bar"><i style="width:{max(0,min(100,v)):.0f}%"></i></span><span class="bv">{v:.0f}</span>'


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#8a877f;--card:#fff;--line:#e6e2d9;--accent:#b4442a;
--red:#c0392b;--orange:#d9772b;--yellow:#c9a227;--blue:#3a6ea5;--bar:#d7d2c6;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151513;--fg:#ecebe6;--muted:#8d8a82;
--card:#1e1e1b;--line:#2f2e2a;--bar:#3a3934}}
:root[data-theme="dark"]{--bg:#151513;--fg:#ecebe6;--muted:#8d8a82;--card:#1e1e1b;--line:#2f2e2a;--bar:#3a3934}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"PingFang TC","Noto Sans TC",sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{color:var(--muted);font-size:13px}
.demo{background:var(--accent);color:#fff;padding:8px 12px;border-radius:8px;font-weight:600;margin:10px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:24px}.kpi span{color:var(--muted);font-size:12px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right}
th{position:sticky;top:0;background:var(--card);color:var(--muted);font-weight:600}
td.l,th.l{text-align:left}
tr>:first-child{position:sticky;left:0;background:var(--card);z-index:1}
@media (max-width:600px){main{padding:14px 10px 40px}h1{font-size:19px}.kpi b{font-size:20px}th,td{padding:6px 7px}}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;color:#fff;font-size:12px}
.bar{display:inline-block;width:46px;height:6px;background:var(--bar);border-radius:3px;vertical-align:middle;overflow:hidden}
.bar i{display:block;height:100%;background:var(--fg)}.bv{display:inline-block;width:24px;font-size:11px;color:var(--muted)}
.flags{color:var(--red);font-size:12px;white-space:normal;min-width:140px;text-align:left}
.na{color:var(--muted)}ul{padding-left:18px}.ok{color:#2e8b57}.err{color:var(--red)}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}
"""


def render(res, path, demo=False):
    t, th, mk = res["tickers"], res["themes"], res["market"]
    greed = mk["greed"]
    mood = "極度貪婪" if greed >= 75 else "貪婪" if greed >= 60 else "中性" if greed >= 40 else "恐懼" if greed >= 25 else "極度恐懼"
    h = [f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>"
         f"<title>台股論壇熱度 {res['asof']}</title><style>{CSS}</style></head><body><main>"]
    h.append(f"<h1>台股論壇熱度雷達</h1><div class='sub'>論壇資料截至 {res['asof']}｜"
             f"行情截至 {res['trade_date'] or '無'}｜{'已有 28 日基期' if res['has_hist'] else '基期不足 14 天，熱度僅用橫斷面排名'}</div>")
    if demo:
        h.append("<div class='demo'>DEMO：以下全部是合成資料，只用來展示輸出格式，不代表任何真實市場狀況。</div>")
    h.append("<h2>市場情緒</h2><div class='kpis'>")
    h.append(f"<div class='kpi'><span>論壇貪婪指數</span><b>{greed:.0f}</b><span>{mood}</span></div>")
    h.append(f"<div class='kpi'><span>7日看多比例</span><b>{mk['bull_share']*100:.0f}%</b><span>情緒字典判定</span></div>")
    h.append(f"<div class='kpi'><span>狂熱用語密度</span><b>{mk['euph_rate']*100:.1f}%</b><span>歐印/梭哈/信貸…</span></div>")
    h.append(f"<div class='kpi'><span>7日討論量 vs 基期</span><b>{_f(mk['zvol'], '{:+.1f}σ')}</b>"
             f"<span style='color:var(--fg)'>{spark(mk['spark'], 120, 24)}</span></div></div>")

    h.append("<h2>題材熱度</h2><div class='wrap'><table><tr><th class='l'>題材</th><th>熱度分</th><th>過熱比例</th>"
             "<th>7日聲量</th><th>聲量/基期</th><th class='l'>28日趨勢</th><th class='l'>領頭標的</th></tr>")
    for _, r in th.iterrows():
        sc = r["score"]
        lab = "" if (isinstance(sc, float) and math.isnan(sc)) else label_tag(sc)
        h.append(f"<tr><td class='l'><b>{html.escape(r['theme'])}</b></td><td>{_f(sc)} {lab}</td>"
                 f"<td>{_f(r['breadth']*100 if r['breadth']==r['breadth'] else float('nan'), '{:.0f}%')}</td>"
                 f"<td>{r['m7']:.0f}</td><td>{_f(r['trend'], '{:.1f}x')}</td>"
                 f"<td class='l'>{spark(r['spark'])}</td><td class='l'>{html.escape(r['top'])}</td></tr>")
    h.append("</table></div>")

    h.append("<h2>個股熱度排行</h2><div class='wrap'><table><tr><th class='l'>標的</th><th>熱度</th>"
             "<th>A 討論</th><th>S 情緒</th><th>L 槓桿</th><th>P 漲幅</th><th>7日聲量</th><th>看多%</th>"
             "<th>20日漲幅</th><th>融資5日</th><th class='l'>28日聲量</th><th class='l'>旗標</th></tr>")
    for code, r in t.head(40).iterrows():
        h.append(f"<tr><td class='l'><b>{code}</b> {html.escape(str(r['name']))}</td>"
                 f"<td><b>{r['score']:.0f}</b> {label_tag(r['score'])}</td>"
                 f"<td>{bar(r['A'])}</td><td>{bar(r['S'])}</td><td>{bar(r['L'])}</td><td>{bar(r['P'])}</td>"
                 f"<td>{r['m7']:.0f}</td><td>{r['bull_share']*100:.0f}%</td>"
                 f"<td>{_f(r.get('ret20', float('nan'))*100 if r.get('ret20') == r.get('ret20') else float('nan'), '{:+.1f}%')}</td>"
                 f"<td>{_f(r.get('margin_chg5', float('nan'))*100 if r.get('margin_chg5') == r.get('margin_chg5') else float('nan'), '{:+.1f}%')}</td>"
                 f"<td class='l'>{spark(r['spark'])}</td><td class='flags'>{html.escape(r['flags'])}</td></tr>")
    h.append("</table></div>")

    warn = t[t["flags"] != ""]
    if len(warn):
        h.append("<h2>警示清單</h2><ul>")
        for code, r in warn.head(20).iterrows():
            h.append(f"<li><b>{code} {html.escape(str(r['name']))}</b>（{r['score']:.0f}）：{html.escape(r['flags'])}</li>")
        h.append("</ul>")

    h.append("<h2>資料來源狀態</h2><div class='wrap'><table><tr><th class='l'>來源</th><th>狀態</th><th>筆數</th>"
             "<th class='l'>最後執行</th><th class='l'>訊息</th></tr>")
    for _, r in res["health"].iterrows():
        h.append(f"<tr><td class='l'>{html.escape(r['source'])}</td><td class='{'ok' if r['ok'] else 'err'}'>"
                 f"{'OK' if r['ok'] else '失敗'}</td><td>{r['rows']}</td><td class='l'>{r['ts']}</td>"
                 f"<td class='l'>{html.escape(str(r['msg'])[:80])}</td></tr>")
    h.append("</table></div>")
    h.append("""<details><summary>方法說明（點開）</summary><ul>
<li><b>A 討論熱度</b>：7 日加權提及量（主文 1、標題 2、推文 0.25）的百分位，基期足夠時再混合相對自身 28 日基期的 z 分數。</li>
<li><b>S 情緒極端</b>：看多/看空字典比例偏離中性的程度，加上「歐印、梭哈、信貸、財富自由」等狂熱用語密度。</li>
<li><b>L 槓桿擁擠</b>：融資 5 日增速與 5 日平均周轉率，在全市場的百分位。</li>
<li><b>P 股價延伸</b>：20 日與 5 日報酬在全市場的百分位。</li>
<li><b>官方警示</b>：注意股/處置股以加成方式把分數推向 100。</li>
<li>缺資料的元件會自動剔除並重新分配權重。權重是啟發式設定，需累積 2~3 個月資料後用 backtest.py 驗證。</li>
<li>這是情緒與擁擠度的量化工具，不是買賣訊號，也不構成投資建議。</li></ul></details>""")
    h.append("</main></body></html>")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(h))
    return path


def label_tag(score):
    from model import label
    lab = label(score)
    return f"<span class='tag' style='background:{LABEL_COLOR[lab]}'>{lab}</span>"


def brief(res, path):
    """給 Claude 的精簡摘要：貼進對話就能讓我做質化判讀。"""
    t, th, mk = res["tickers"], res["themes"], res["market"]
    L = [f"# 台股論壇熱度摘要 {res['asof']}（行情 {res['trade_date']}）",
         f"論壇貪婪指數 {mk['greed']:.0f}｜7日看多 {mk['bull_share']*100:.0f}%｜狂熱用語 {mk['euph_rate']*100:.1f}%｜"
         f"聲量 vs 基期 {_f(mk['zvol'], '{:+.1f}σ')}", "", "## 題材",
         "| 題材 | 熱度 | 過熱比例 | 7日聲量 | 聲量/基期 | 領頭 |", "|---|---|---|---|---|---|"]
    for _, r in th.iterrows():
        L.append(f"| {r['theme']} | {_f(r['score'])} | {_f(r['breadth']*100 if r['breadth']==r['breadth'] else float('nan'), '{:.0f}%')} "
                 f"| {r['m7']:.0f} | {_f(r['trend'], '{:.1f}x')} | {r['top']} |")
    L += ["", "## 個股 Top 20", "| 代號 | 名稱 | 熱度 | 標籤 | A | S | L | P | 看多% | 20日% | 融資5日% | 法人5日/量 | 旗標 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for code, r in t.head(20).iterrows():
        g = lambda k, m=1, fmt="{:.0f}": _f(r[k] * m if k in r and r[k] == r[k] else float("nan"), fmt)  # noqa
        L.append(f"| {code} | {r['name']} | {r['score']:.0f} | {r['label']} | {g('A')} | {g('S')} | {g('L')} | {g('P')} "
                 f"| {r['bull_share']*100:.0f} | {g('ret20',100,'{:+.1f}')} | {g('margin_chg5',100,'{:+.1f}')} "
                 f"| {g('inst_ratio',100,'{:+.1f}')} | {r['flags']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path
