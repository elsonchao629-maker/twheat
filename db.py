# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime as dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY, source TEXT, board TEXT, url TEXT, title TEXT, author TEXT,
  ts TEXT, date TEXT, category TEXT, side TEXT, content TEXT,
  n_push INT, n_boo INT, n_arrow INT, processed INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_posts_date ON posts(date);
CREATE TABLE IF NOT EXISTS comments(
  post_id TEXT, idx INT, tag TEXT, user TEXT, content TEXT, date TEXT,
  PRIMARY KEY(post_id, idx));
CREATE TABLE IF NOT EXISTS mentions(
  src_id TEXT, post_id TEXT, kind TEXT, code TEXT, date TEXT, weight REAL,
  bull INT, bear INT, euph INT, panic INT, author TEXT);
CREATE INDEX IF NOT EXISTS ix_m_date ON mentions(date);
CREATE INDEX IF NOT EXISTS ix_m_post ON mentions(post_id);
CREATE TABLE IF NOT EXISTS theme_hits(src_id TEXT, post_id TEXT, theme TEXT, date TEXT, weight REAL);
CREATE INDEX IF NOT EXISTS ix_t_post ON theme_hits(post_id);
CREATE TABLE IF NOT EXISTS companies(code TEXT PRIMARY KEY, name TEXT, market TEXT, shares REAL);
CREATE TABLE IF NOT EXISTS prices(date TEXT, code TEXT, close REAL, volume REAL, PRIMARY KEY(date, code));
CREATE TABLE IF NOT EXISTS margin(date TEXT, code TEXT, margin_bal REAL, short_bal REAL, PRIMARY KEY(date, code));
CREATE TABLE IF NOT EXISTS inst(date TEXT, code TEXT, net REAL, PRIMARY KEY(date, code));
CREATE TABLE IF NOT EXISTS warnings(date TEXT, code TEXT, kind TEXT, PRIMARY KEY(date, code, kind));
CREATE TABLE IF NOT EXISTS runs(ts TEXT, source TEXT, ok INT, rows INT, msg TEXT);
"""


def connect(path):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def log_run(conn, source, ok, rows=0, msg=""):
    conn.execute("INSERT INTO runs VALUES(?,?,?,?,?)",
                 (dt.datetime.now().isoformat(timespec="seconds"), source, int(ok), rows, str(msg)[:300]))
    conn.commit()
    flag = "OK " if ok else "ERR"
    print(f"[{flag}] {source}: {rows} rows {msg}")


def company_names(conn):
    from config import SEED_NAMES
    names = dict(SEED_NAMES)
    for code, name in conn.execute("SELECT code, name FROM companies"):
        if name:
            names[code] = name
    return names
