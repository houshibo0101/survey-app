#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据层：SQLite 存储、口令散列、会话令牌、首次初始化与示例数据。"""

import datetime
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SURVEY_DATA", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("SURVEY_DB", os.path.join(DATA_DIR, "survey.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS surveys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  created_by INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  survey_id INTEGER NOT NULL,
  pos INTEGER NOT NULL DEFAULT 0,
  qtype TEXT NOT NULL DEFAULT 'single',
  title TEXT NOT NULL,
  options TEXT NOT NULL DEFAULT '[]',
  required INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(survey_id) REFERENCES surveys(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  survey_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  submitted_at TEXT NOT NULL,
  UNIQUE(survey_id, user_id),
  FOREIGN KEY(survey_id) REFERENCES surveys(id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id INTEGER NOT NULL,
  question_id INTEGER NOT NULL,
  value TEXT NOT NULL DEFAULT '""',
  FOREIGN KEY(response_id) REFERENCES responses(id) ON DELETE CASCADE,
  FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS visibility (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  viewer_id INTEGER NOT NULL,
  target_id INTEGER NOT NULL,
  survey_id INTEGER NOT NULL DEFAULT 0,
  UNIQUE(viewer_id, target_id, survey_id),
  FOREIGN KEY(viewer_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(target_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fake_options (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  question_id INTEGER NOT NULL,
  options TEXT NOT NULL DEFAULT '[]',
  UNIQUE(user_id, question_id),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prompts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_api_key": "",
    "ai_model": "deepseek-chat",
    "ai_temperature": "0.8",
    "ai_system_prompt": (
        "你是一位资深的问卷设计专家，擅长把研究目标拆解成清晰、中立、无引导性的题目。"
        "你只输出 JSON，不输出任何解释、Markdown 代码围栏或多余文字。"
    ),
}

_secret_cache = []


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 口令与会话

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260000)
    return "pbkdf2$260000$%s$%s" % (salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def get_secret():
    if _secret_cache:
        return _secret_cache[0]
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='secret'").fetchone()
        if not row:
            value = secrets.token_hex(32)
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('secret',?)", (value,))
            conn.commit()
            row = {"value": value}
        _secret_cache[:] = [row["value"]]
        return row["value"]
    finally:
        conn.close()


def make_token(user_id, days=7):
    expires = int(time.time()) + days * 86400
    message = "%s.%s" % (user_id, expires)
    signature = hmac.new(get_secret().encode(), message.encode(), hashlib.sha256).hexdigest()
    return "%s.%s" % (message, signature)


def verify_token(token):
    try:
        user_id, expires, signature = token.split(".")
        message = "%s.%s" % (user_id, expires)
        expected = hmac.new(get_secret().encode(), message.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires) < time.time():
            return None
        return int(user_id)
    except Exception:
        return None


# ---------------------------------------------------------------- 设置

def get_settings():
    conn = connect()
    try:
        data = dict(DEFAULT_SETTINGS)
        for row in conn.execute("SELECT key, value FROM settings"):
            data[row["key"]] = row["value"]
        return data
    finally:
        conn.close()


def set_settings(values):
    conn = connect()
    try:
        for key, value in values.items():
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- 初始化

def init():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        get_secret()
        if not conn.execute("SELECT 1 FROM users WHERE is_admin=1").fetchone():
            admin_password = os.environ.get("SURVEY_ADMIN_PASSWORD") or "admin123"
            conn.execute(
                "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) VALUES(?,?,?,?,?)",
                ("admin", "系统管理员", hash_password(admin_password), 1, now()),
            )
        if not conn.execute("SELECT 1 FROM surveys").fetchone():
            seed_demo(conn)
        conn.commit()
    finally:
        conn.close()


def seed_demo(conn):
    cur = conn.execute(
        "INSERT INTO surveys(title, description, status, created_by, created_at) VALUES(?,?,?,?,?)",
        (
            "示例问卷：团队协作与沟通调研",
            "这是一份系统自动创建的示例问卷，用于演示填写、结果查看、可见性与虚假选项功能。你可以直接修改或删除它。",
            "open",
            1,
            now(),
        ),
    )
    survey_id = cur.lastrowid
    questions = [
        ("single", "你对本次团队协作的总体满意度是？", ["非常满意", "比较满意", "一般", "不太满意", "非常不满意"]),
        ("multi", "你在项目中主要负责哪些模块？（可多选）", ["需求分析", "界面设计", "前端开发", "后端开发", "测试", "文档"]),
        ("single", "你最希望合作的搭档是？", ["张三", "李四", "王五", "赵六"]),
        ("text", "对团队协作还有什么建议？", []),
    ]
    for index, (qtype, title, options) in enumerate(questions):
        conn.execute(
            "INSERT INTO questions(survey_id, pos, qtype, title, options, required) VALUES(?,?,?,?,?,?)",
            (survey_id, index, qtype, title, json.dumps(options, ensure_ascii=False), 1),
        )


# ---------------------------------------------------------------- 业务查询辅助

def get_survey_questions(conn, survey_id):
    return rows_to_dicts(
        conn.execute(
            "SELECT id, survey_id, pos, qtype, title, options, required FROM questions "
            "WHERE survey_id=? ORDER BY pos, id",
            (survey_id,),
        )
    )


def question_options(question):
    try:
        value = json.loads(question["options"] or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def question_brief(conn, question_id):
    row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    return dict(row) if row else None


def fake_options_for(conn, user_id, survey_id):
    """返回 {question_id: [options]}，只包含该用户在问卷中被伪装的题目。"""
    result = {}
    rows = conn.execute(
        "SELECT f.question_id, f.options FROM fake_options f "
        "JOIN questions q ON q.id = f.question_id WHERE f.user_id=? AND q.survey_id=?",
        (user_id, survey_id),
    )
    for row in rows:
        try:
            options = json.loads(row["options"])
            if isinstance(options, list) and options:
                result[row["question_id"]] = options
        except Exception:
            pass
    return result
