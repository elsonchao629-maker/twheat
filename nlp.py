# -*- coding: utf-8 -*-
"""從文章/推文抽出個股、題材與情緒。規則式，透明可調，不是黑盒子。"""
import re
from config import (ALIASES, AMBIGUOUS_NAMES, YEAR_LIKE, THEMES, BULL, BEAR, EUPHORIA, PANIC,
                    POST_W, TITLE_W, COMMENT_W)
from db import company_names


class Extractor:
    def __init__(self, names):
        self.names = names
        self.codes = set(names)
        n2c = {}
        for code, name in names.items():
            n = (name or "").replace("*", "").strip()
            variants = {n}
            for suf in ("-KY", "-DR", "KY"):
                if n.endswith(suf):
                    variants.add(n[: -len(suf)].rstrip("-"))
            for v in variants:
                if len(v) >= 2 and v not in AMBIGUOUS_NAMES and not v.isdigit():
                    n2c.setdefault(v, code)
        n2c.update(ALIASES)
        self.n2c = n2c
        cjk = sorted([k for k in n2c if not k.isascii()], key=len, reverse=True)
        asc = sorted([k for k in n2c if k.isascii()], key=len, reverse=True)
        self.cjk_re = re.compile("|".join(map(re.escape, cjk))) if cjk else None
        self.asc_re = (re.compile(r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, asc)) + r")(?![A-Za-z0-9])")
                       if asc else None)
        self.code_re = re.compile(r"(?<![\d./:])(\d{4,6}[A-Z]?)(?![\d./:%年元點張萬億塊])")
        self.theme_re = {t: re.compile("|".join(map(re.escape, v["kw"])), re.I) for t, v in THEMES.items()}

    def tickers(self, text):
        found = set()
        if not text:
            return found
        if self.cjk_re:
            found |= {self.n2c[m.group()] for m in self.cjk_re.finditer(text)}
        if self.asc_re:
            found |= {self.n2c[m.group(1)] for m in self.asc_re.finditer(text)}
        for m in self.code_re.finditer(text):
            c = m.group(1)
            if c in self.codes:
                if c in YEAR_LIKE and self.names.get(c, "@@") not in text:
                    continue
                found.add(c)
        return found

    def themes(self, text):
        return {t for t, rx in self.theme_re.items() if text and rx.search(text)}


def _count(text, words):
    t = text.lower()
    return min(sum(t.count(w.lower()) for w in words), 3)


def sentiment(text):
    text = text or ""
    return {"bull": _count(text, BULL), "bear": _count(text, BEAR),
            "euph": _count(text, EUPHORIA), "panic": _count(text, PANIC)}


def process(conn, reprocess=False):
    """把尚未處理的文章轉成 mentions / theme_hits。"""
    ex = Extractor(company_names(conn))
    q = "SELECT id, title, content, date, author, side FROM posts" + ("" if reprocess else " WHERE processed=0")
    posts = conn.execute(q).fetchall()
    n_m = 0
    for pid, title, content, date, author, side in posts:
        conn.execute("DELETE FROM mentions WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM theme_hits WHERE post_id=?", (pid,))
        rows, trows = [], []
        body = (content or "")[:4000]
        t_codes = ex.tickers(title or "")
        codes = t_codes | ex.tickers(body)
        s = sentiment((title or "") + "\n" + body)
        if side == "多":
            s["bull"] += 2
        elif side == "空":
            s["bear"] += 2
        for c in codes:
            w = TITLE_W if c in t_codes else POST_W
            rows.append((pid, pid, "post", c, date, w, s["bull"], s["bear"], s["euph"], s["panic"], author))
        for th in ex.themes((title or "") + "\n" + body):
            trows.append((pid, pid, th, date, POST_W))
        for idx, tag, user, ctext, cdate in conn.execute(
                "SELECT idx, tag, user, content, date FROM comments WHERE post_id=?", (pid,)):
            cc = ex.tickers(ctext)
            if not cc:
                cc = codes if len(codes) == 1 else set()   # 推文沒寫代號時，歸給單一標的的主文
            cs = sentiment(ctext)
            sid = f"{pid}#{idx}"
            for c in cc:
                rows.append((sid, pid, "comment", c, cdate or date, COMMENT_W,
                             cs["bull"], cs["bear"], cs["euph"], cs["panic"], user))
            for th in ex.themes(ctext):
                trows.append((sid, pid, th, cdate or date, COMMENT_W))
        conn.executemany("INSERT INTO mentions VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.executemany("INSERT INTO theme_hits VALUES(?,?,?,?,?)", trows)
        conn.execute("UPDATE posts SET processed=1 WHERE id=?", (pid,))
        n_m += len(rows)
    conn.commit()
    print(f"[NLP] 處理 {len(posts)} 篇文章，產生 {n_m} 筆個股提及")
