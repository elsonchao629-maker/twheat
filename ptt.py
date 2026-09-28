# -*- coding: utf-8 -*-
"""PTT 看板爬蟲（公開網頁版 www.ptt.cc）。"""
import re
import time
import datetime as dt
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from db import log_run

BASE = "https://www.ptt.cc"
TPE = ZoneInfo("Asia/Taipei")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def url_ts(href):
    m = re.search(r"M\.(\d+)\.A", href or "")
    return int(m.group(1)) if m else None


class PTT:
    def __init__(self, board="Stock", delay=0.5):
        self.board, self.delay = board, delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.cookies.set("over18", "1", domain="www.ptt.cc")

    def get(self, url):
        for i in range(3):
            try:
                r = self.s.get(url, timeout=15)
                if r.status_code == 200:
                    return r.text
                if r.status_code == 404:
                    return None
            except requests.RequestException:
                pass
            time.sleep(2 * (i + 1))
        return None

    def iter_index(self, cutoff_ts, max_pages=2000):
        url = f"{BASE}/bbs/{self.board}/index.html"
        pages = 0
        while url and pages < max_pages:
            html = self.get(url)
            if not html:
                break
            soup = BeautifulSoup(html, "html.parser")
            page_ts = []
            for el in soup.select("div.r-list-container > div"):
                cls = el.get("class") or []
                if "r-list-sep" in cls:        # 分隔線以下是置底文
                    break
                if "r-ent" not in cls:
                    continue
                a = el.select_one("div.title a")
                if not a:
                    continue                   # 已刪除
                ts = url_ts(a.get("href"))
                if ts is None:
                    continue
                page_ts.append(ts)
                if ts >= cutoff_ts:
                    yield a.get("href")
            if page_ts and max(page_ts) < cutoff_ts:
                break
            prev = next((b for b in soup.select("a.btn.wide") if "上頁" in b.get_text()), None)
            url = BASE + prev["href"] if prev and prev.get("href") else None
            pages += 1
            time.sleep(self.delay)

    def parse_article(self, html, href):
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("#main-content")
        if not main:
            return None
        meta = {}
        for ml in main.select("div.article-metaline"):
            t, v = ml.select_one(".article-meta-tag"), ml.select_one(".article-meta-value")
            if t and v:
                meta[t.get_text(strip=True)] = v.get_text(strip=True)
        ts = url_ts(href)
        post_dt = dt.datetime.fromtimestamp(ts, TPE)
        comments = []
        for i, p in enumerate(main.select("div.push")):
            tag = (p.select_one(".push-tag") or p).get_text(strip=True)
            user = (p.select_one(".push-userid") or p).get_text(strip=True)
            content = (p.select_one(".push-content") or p).get_text(strip=True).lstrip(":").strip()
            ipdt = (p.select_one(".push-ipdatetime") or p).get_text(" ", strip=True)
            cdate = None
            m = re.search(r"(\d{2})/(\d{2})\s+\d{2}:\d{2}", ipdt)
            if m:
                mo, d = int(m.group(1)), int(m.group(2))
                yr = post_dt.year + (1 if mo < post_dt.month - 6 else 0)
                try:
                    cdate = dt.date(yr, mo, d).isoformat()
                except ValueError:
                    cdate = None
            comments.append((i, tag, user, content, cdate))
        for sel in ("div.article-metaline", "div.article-metaline-right", "div.push"):
            for e in main.select(sel):
                e.decompose()
        body = main.get_text("\n").split("※ 發信站")[0].strip()
        title = meta.get("標題", "")
        category, side = None, None
        mc = re.match(r"\s*\[([^\]]+)\]", title)
        if mc:
            category = mc.group(1).strip()
        if category == "標的":
            tail = title[-6:]
            side = "空" if "空" in tail and "多" not in tail else ("多" if "多" in tail and "空" not in tail else None)
        tags = [c[1] for c in comments]
        return {
            "id": href.rsplit("/", 1)[-1].replace(".html", ""),
            "url": BASE + href, "title": title,
            "author": meta.get("作者", "").split(" ")[0],
            "ts": post_dt.isoformat(), "date": post_dt.date().isoformat(),
            "category": category, "side": side, "content": body,
            "n_push": tags.count("推"), "n_boo": tags.count("噓"), "n_arrow": tags.count("→"),
            "comments": comments,
        }


def scrape(conn, board="Stock", days=2, delay=0.5):
    ptt = PTT(board, delay)
    cutoff = int(time.time() - days * 86400)
    n = 0
    try:
        for href in ptt.iter_index(cutoff):
            html = ptt.get(BASE + href)
            time.sleep(delay)
            if not html:
                continue
            a = ptt.parse_article(html, href)
            if not a:
                continue
            conn.execute("INSERT OR REPLACE INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                         (a["id"], "ptt", board, a["url"], a["title"], a["author"], a["ts"], a["date"],
                          a["category"], a["side"], a["content"], a["n_push"], a["n_boo"], a["n_arrow"]))
            conn.execute("DELETE FROM comments WHERE post_id=?", (a["id"],))
            conn.executemany("INSERT INTO comments VALUES(?,?,?,?,?,?)",
                             [(a["id"], *c) for c in a["comments"]])
            n += 1
            if n % 25 == 0:
                conn.commit()
                print(f"  ...{n} 篇 ({a['date']})")
        conn.commit()
        log_run(conn, f"ptt/{board}", n > 0, n, f"近 {days} 天")
    except Exception as e:  # noqa
        conn.commit()
        log_run(conn, f"ptt/{board}", False, n, repr(e))
    return n


def import_text(conn, path, source="manual", date=None):
    """把從 Threads / CMoney 複製的文字匯入。每段（空行分隔）視為一則貼文。"""
    import hashlib
    date = date or dt.date.today().isoformat()
    text = open(path, encoding="utf-8").read()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    for b in blocks:
        pid = f"{source}-" + hashlib.md5(b.encode()).hexdigest()[:12]
        conn.execute("INSERT OR REPLACE INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                     (pid, source, None, None, b[:40], None, date, date, None, None, b, 0, 0, 0))
    conn.commit()
    log_run(conn, f"import/{source}", True, len(blocks), path)
