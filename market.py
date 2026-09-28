# -*- coding: utf-8 -*-
"""證交所 / 櫃買中心公開資料。欄位名稱官方偶爾會改，所以全部用容錯方式解析。
任何一個來源失敗都不會讓整個流程中斷，模型會自動用剩下的元件計分。"""
import time
import datetime as dt
from zoneinfo import ZoneInfo

import requests

from db import log_run

TPE = ZoneInfo("Asia/Taipei")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) twheat/1.0"}
TWSE_OA = "https://openapi.twse.com.tw/v1"
TPEX_OA = "https://www.tpex.org.tw/openapi/v1"
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"


def _num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _pick(d, cands):
    for c in cands:
        if c in d and d[c] not in (None, ""):
            return d[c]
    for c in cands:
        for k in d:
            if c.lower() in k.lower() and d[k] not in (None, ""):
                return d[k]
    return None


def _iso(s, fallback):
    """民國 1150925 / 115/09/25 / 20260925 → 2026-09-25"""
    if not s:
        return fallback
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    try:
        if len(digits) == 7:
            return dt.date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:])).isoformat()
        if len(digits) == 8:
            return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        pass
    return fallback


def _get(url, params=None):
    r = requests.get(url, params=params, headers=UA, timeout=25)
    r.raise_for_status()
    return r.json()


def today_tpe():
    return dt.datetime.now(TPE).date().isoformat()


# ---------------- 公司清單 ----------------
def fetch_companies(conn):
    total = 0
    for market, url in (("TWSE", f"{TWSE_OA}/opendata/t187ap03_L"),
                        ("TPEx", f"{TPEX_OA}/mopsfin_t187ap03_O")):
        try:
            rows = []
            for r in _get(url):
                code = _pick(r, ["公司代號", "SecuritiesCompanyCode", "CompanyCode"])
                name = _pick(r, ["公司簡稱", "CompanyAbbreviation", "CompanyShortName"])
                shares = _num(_pick(r, ["已發行普通股數或TDR原股發行股數", "已發行普通股數", "IssueShares"]))
                if code and name:
                    rows.append((str(code).strip(), str(name).strip(), market, shares))
            conn.executemany("INSERT OR REPLACE INTO companies VALUES(?,?,?,?)", rows)
            conn.commit()
            log_run(conn, f"companies/{market}", bool(rows), len(rows))
            total += len(rows)
        except Exception as e:  # noqa
            log_run(conn, f"companies/{market}", False, 0, repr(e))
    return total


def _upsert_name(conn, code, name, market):
    conn.execute("INSERT OR IGNORE INTO companies(code, name, market) VALUES(?,?,?)", (code, name, market))


# ---------------- 當日行情（openapi，只給最新一天） ----------------
def fetch_prices_today(conn):
    latest = None
    specs = (("TWSE", f"{TWSE_OA}/exchangeReport/STOCK_DAY_ALL",
              ["Code", "證券代號"], ["Name", "證券名稱"], ["ClosingPrice", "收盤價"], ["TradeVolume", "成交股數"]),
             ("TPEx", f"{TPEX_OA}/tpex_mainboard_daily_close_quotes",
              ["SecuritiesCompanyCode", "代號"], ["CompanyName", "名稱"], ["Close", "收盤"], ["TradingShares", "TradeVolume", "成交股數"]))
    for market, url, kc, kn, kp, kv in specs:
        try:
            rows = []
            for r in _get(url):
                code = _pick(r, kc)
                if not code:
                    continue
                d = _iso(_pick(r, ["Date", "日期"]), today_tpe())
                close, vol = _num(_pick(r, kp)), _num(_pick(r, kv))
                if close is None:
                    continue
                rows.append((d, str(code).strip(), close, vol))
                name = _pick(r, kn)
                if name:
                    _upsert_name(conn, str(code).strip(), str(name).strip(), market)
            conn.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?)", rows)
            conn.commit()
            if rows:
                latest = max(latest or "", max(r[0] for r in rows))
            log_run(conn, f"prices/{market}", bool(rows), len(rows), rows[0][0] if rows else "")
        except Exception as e:  # noqa
            log_run(conn, f"prices/{market}", False, 0, repr(e))
    return latest


def fetch_margin_today(conn, date):
    specs = (("TWSE", f"{TWSE_OA}/exchangeReport/MI_MARGN",
              ["股票代號", "Code", "代號"], ["融資今日餘額", "MarginPurchaseTodayBalance"], ["融券今日餘額", "ShortSaleTodayBalance"]),
             ("TPEx", f"{TPEX_OA}/tpex_mainboard_margin_balance",
              ["SecuritiesCompanyCode", "代號", "Code"], ["MarginPurchaseBalance", "融資餘額", "資餘額"], ["ShortSaleBalance", "融券餘額", "券餘額"]))
    for market, url, kc, km, ks in specs:
        try:
            rows = []
            for r in _get(url):
                code, mb = _pick(r, kc), _num(_pick(r, km))
                if code and mb is not None:
                    d = _iso(_pick(r, ["Date", "日期"]), date)
                    rows.append((d, str(code).strip(), mb, _num(_pick(r, ks))))
            conn.executemany("INSERT OR REPLACE INTO margin VALUES(?,?,?,?)", rows)
            conn.commit()
            log_run(conn, f"margin/{market}", bool(rows), len(rows))
        except Exception as e:  # noqa
            log_run(conn, f"margin/{market}", False, 0, repr(e))


def fetch_warnings(conn):
    today = today_tpe()
    specs = (("notice", f"{TWSE_OA}/announcement/notice"),
             ("punish", f"{TWSE_OA}/announcement/punish"),
             ("notice", f"{TPEX_OA}/tpex_trading_warning_information"),
             ("punish", f"{TPEX_OA}/tpex_disposal_information"))
    for kind, url in specs:
        try:
            rows = []
            for r in _get(url):
                code = _pick(r, ["Code", "證券代號", "SecuritiesCompanyCode", "代號"])
                if code:
                    d = _iso(_pick(r, ["Date", "公布日期", "日期"]), today)
                    rows.append((d, str(code).strip(), kind))
            conn.executemany("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", rows)
            conn.commit()
            log_run(conn, f"warnings/{kind}/{url.split('/')[-1]}", True, len(rows))
        except Exception as e:  # noqa
            log_run(conn, f"warnings/{kind}/{url.split('/')[-1]}", False, 0, repr(e))


# ---------------- 歷史回補（證交所 rwd，可指定日期，僅上市） ----------------
def _tables(j):
    out = []
    for t in j.get("tables", []) or []:
        if t.get("fields") and t.get("data"):
            out.append((t["fields"], t["data"]))
    for k in list(j):
        if k.startswith("fields"):
            dk = "data" + k[6:]
            if j.get(dk):
                out.append((j[k], j[dk]))
    return out


def _find(tables, must):
    for f, d in tables:
        if all(any(m in x for x in f) for m in must):
            return f, d
    return None, None


def _col(fields, name):
    for i, f in enumerate(fields):
        if name in f:
            return i
    return None


def fetch_twse_day(conn, date):
    """date: YYYY-MM-DD。抓當天上市收盤、融資、三大法人。回傳是否為交易日。"""
    ymd = date.replace("-", "")
    ok_any = False
    # 收盤行情
    try:
        j = _get(f"{TWSE_RWD}/afterTrading/MI_INDEX", {"date": ymd, "type": "ALLBUT0999", "response": "json"})
        f, d = _find(_tables(j), ["證券代號", "收盤價", "成交股數"])
        if d:
            ic, ip, iv, iname = _col(f, "證券代號"), _col(f, "收盤價"), _col(f, "成交股數"), _col(f, "證券名稱")
            rows = [(date, r[ic].strip(), _num(r[ip]), _num(r[iv])) for r in d if _num(r[ip]) is not None]
            for r in d:
                if iname is not None:
                    _upsert_name(conn, r[ic].strip(), r[iname].strip(), "TWSE")
            conn.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?)", rows)
            ok_any = bool(rows)
    except Exception as e:  # noqa
        print(f"  MI_INDEX {date} 失敗: {e!r}")
    if not ok_any:
        return False       # 非交易日或被擋，後面不用抓
    time.sleep(3)
    # 融資融券（欄位重複：第一個「今日餘額」是融資、第二個是融券）
    try:
        j = _get(f"{TWSE_RWD}/marginTrading/MI_MARGN", {"date": ymd, "selectType": "ALL", "response": "json"})
        f, d = _find(_tables(j), ["代號", "今日餘額"])
        if d:
            idx = [i for i, x in enumerate(f) if "今日餘額" in x]
            ic = _col(f, "代號")
            rows = [(date, r[ic].strip(), _num(r[idx[0]]), _num(r[idx[1]]) if len(idx) > 1 else None) for r in d]
            conn.executemany("INSERT OR REPLACE INTO margin VALUES(?,?,?,?)", rows)
    except Exception as e:  # noqa
        print(f"  MI_MARGN {date} 失敗: {e!r}")
    time.sleep(3)
    # 三大法人買賣超
    try:
        j = _get(f"{TWSE_RWD}/fund/T86", {"date": ymd, "selectType": "ALLBUT0999", "response": "json"})
        f, d = _find(_tables(j), ["證券代號", "三大法人買賣超股數"])
        if d:
            ic, inet = _col(f, "證券代號"), _col(f, "三大法人買賣超股數")
            rows = [(date, r[ic].strip(), _num(r[inet])) for r in d]
            conn.executemany("INSERT OR REPLACE INTO inst VALUES(?,?,?)", rows)
    except Exception as e:  # noqa
        print(f"  T86 {date} 失敗: {e!r}")
    conn.commit()
    return True


def backfill_twse(conn, days=45, delay=3.0):
    d = dt.datetime.now(TPE).date()
    n = 0
    for _ in range(days):
        if d.weekday() < 5:
            have = conn.execute("SELECT COUNT(*) FROM inst WHERE date=?", (d.isoformat(),)).fetchone()[0]
            if not have:
                ok = fetch_twse_day(conn, d.isoformat())
                n += int(ok)
                print(f"  {d} {'✓' if ok else '休市/無資料'}")
                time.sleep(delay)
        d -= dt.timedelta(days=1)
    log_run(conn, "backfill/twse", n > 0, n, f"{days} 日曆天")


def check():
    """逐一測試資料來源，印出欄位，方便官方改版時修正。"""
    import json
    tests = [("TWSE 公司", f"{TWSE_OA}/opendata/t187ap03_L", None),
             ("TPEx 公司", f"{TPEX_OA}/mopsfin_t187ap03_O", None),
             ("TWSE 行情", f"{TWSE_OA}/exchangeReport/STOCK_DAY_ALL", None),
             ("TPEx 行情", f"{TPEX_OA}/tpex_mainboard_daily_close_quotes", None),
             ("TWSE 融資", f"{TWSE_OA}/exchangeReport/MI_MARGN", None),
             ("TPEx 融資", f"{TPEX_OA}/tpex_mainboard_margin_balance", None),
             ("TWSE 注意", f"{TWSE_OA}/announcement/notice", None),
             ("TWSE 處置", f"{TWSE_OA}/announcement/punish", None),
             ("TPEx 注意", f"{TPEX_OA}/tpex_trading_warning_information", None),
             ("TPEx 處置", f"{TPEX_OA}/tpex_disposal_information", None)]
    for name, url, p in tests:
        try:
            j = _get(url, p)
            first = j[0] if isinstance(j, list) and j else j
            keys = list(first.keys())[:12] if isinstance(first, dict) else str(first)[:80]
            print(f"✓ {name}: {len(j) if isinstance(j, list) else 1} 筆  欄位={json.dumps(keys, ensure_ascii=False)}")
        except Exception as e:  # noqa
            print(f"✗ {name}: {e!r}")
        time.sleep(0.5)
    d = dt.datetime.now(TPE).date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    for name, path, p in (("TWSE rwd 行情", "afterTrading/MI_INDEX", {"type": "ALLBUT0999"}),
                          ("TWSE rwd 融資", "marginTrading/MI_MARGN", {"selectType": "ALL"}),
                          ("TWSE rwd 法人", "fund/T86", {"selectType": "ALLBUT0999"})):
        try:
            j = _get(f"{TWSE_RWD}/{path}", {"date": d.strftime("%Y%m%d"), "response": "json", **p})
            tbs = _tables(j)
            print(f"✓ {name} ({d}): stat={j.get('stat')} tables={len(tbs)} "
                  f"欄位={[t[0][:6] for t in tbs[:3]]}")
        except Exception as e:  # noqa
            print(f"✗ {name}: {e!r}")
        time.sleep(3)
    from ptt import PTT
    html = PTT().get("https://www.ptt.cc/bbs/Stock/index.html")
    print("✓ PTT Stock 首頁可讀取" if html and "r-ent" in html else "✗ PTT 讀取失敗")
