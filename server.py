#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调查问卷系统 —— HTTP 服务（仅依赖 Python 标准库）。

运行： python3 server.py
环境变量：PORT(默认 8090)、HOST(默认 127.0.0.1)、SURVEY_DATA(数据目录)
"""

import json
import mimetypes
import os
import re
import sys
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai
import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", "8090"))
HOST = os.environ.get("HOST", "127.0.0.1")
SESSION_COOKIE = "sess"
SESSION_DAYS = 7
MAX_BODY = 4 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def fail(message, status=400):
    raise ApiError(status, message)


def need(condition, message, status=400):
    if not condition:
        raise ApiError(status, message)


def text(value, limit=200):
    return str(value if value is not None else "").strip()[:limit]


def as_bool(value):
    return bool(value)


def public_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def normalize_options(raw):
    if isinstance(raw, list):
        items = [text(item, 200) for item in raw]
    elif isinstance(raw, str):
        items = [text(piece, 200) for piece in re.split(r"[\n,，、;；]+", raw)]
    else:
        items = []
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


# ---------------------------------------------------------------- 路由表

ROUTES = []


def route(method, pattern, name, admin=False):
    ROUTES.append((method, re.compile(pattern), name, admin))


route("GET", r"^/api/health$", "health")
route("POST", r"^/api/register$", "register")
route("POST", r"^/api/login$", "login")
route("POST", r"^/api/logout$", "logout")
route("GET", r"^/api/me$", "me")
route("POST", r"^/api/me/password$", "change_password")

route("GET", r"^/api/surveys$", "survey_list")
route("GET", r"^/api/surveys/(\d+)$", "survey_detail")
route("POST", r"^/api/surveys/(\d+)/submit$", "survey_submit")
route("GET", r"^/api/surveys/(\d+)/results$", "survey_results")

route("GET", r"^/api/admin/users$", "admin_users", admin=True)
route("POST", r"^/api/admin/users$", "admin_user_create", admin=True)
route("PATCH", r"^/api/admin/users/(\d+)$", "admin_user_update", admin=True)
route("POST", r"^/api/admin/users/(\d+)/password$", "admin_user_password", admin=True)
route("DELETE", r"^/api/admin/users/(\d+)$", "admin_user_delete", admin=True)

route("POST", r"^/api/admin/surveys$", "admin_survey_create", admin=True)
route("GET", r"^/api/admin/surveys/(\d+)$", "admin_survey_detail", admin=True)
route("PUT", r"^/api/admin/surveys/(\d+)$", "admin_survey_update", admin=True)
route("DELETE", r"^/api/admin/surveys/(\d+)$", "admin_survey_delete", admin=True)
route("POST", r"^/api/admin/surveys/(\d+)/questions$", "admin_question_create", admin=True)
route("POST", r"^/api/admin/surveys/(\d+)/questions/bulk$", "admin_question_bulk", admin=True)
route("PUT", r"^/api/admin/questions/(\d+)$", "admin_question_update", admin=True)
route("DELETE", r"^/api/admin/questions/(\d+)$", "admin_question_delete", admin=True)

route("GET", r"^/api/admin/visibility$", "admin_visibility_list", admin=True)
route("PUT", r"^/api/admin/visibility$", "admin_visibility_set", admin=True)
route("POST", r"^/api/admin/visibility/clear$", "admin_visibility_clear", admin=True)

route("GET", r"^/api/admin/fake-options$", "admin_fake_list", admin=True)
route("PUT", r"^/api/admin/fake-options$", "admin_fake_set", admin=True)
route("DELETE", r"^/api/admin/fake-options/(\d+)$", "admin_fake_delete", admin=True)
route("GET", r"^/api/admin/fake-options/preview$", "admin_fake_preview", admin=True)

route("GET", r"^/api/admin/settings$", "admin_settings_get", admin=True)
route("PUT", r"^/api/admin/settings$", "admin_settings_set", admin=True)
route("POST", r"^/api/admin/ai/generate$", "admin_ai_generate", admin=True)
route("POST", r"^/api/admin/ai/test$", "admin_ai_test", admin=True)
route("GET", r"^/api/admin/prompts$", "admin_prompt_list", admin=True)
route("POST", r"^/api/admin/prompts$", "admin_prompt_create", admin=True)
route("DELETE", r"^/api/admin/prompts/(\d+)$", "admin_prompt_delete", admin=True)


# ---------------------------------------------------------------- 请求处理

class Handler(BaseHTTPRequestHandler):
    server_version = "SurveyApp/1.0"
    protocol_version = "HTTP/1.1"

    # 每个请求独立连接
    conn = None
    user = None
    body = {}
    query = {}
    path = ""
    cookies_out = []

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def do_HEAD(self):
        self.dispatch("GET", head=True)

    # ------------------------------------------------------------ 基础设施

    def dispatch(self, method, head=False):
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        self.query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        self.cookies_out = []
        self.body = {}
        if method not in ("GET", "HEAD"):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.send_json({"error": "请求体过大"}, 413)
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    self.body = json.loads(raw.decode("utf-8"))
                except Exception:
                    return self.send_json({"error": "请求体不是合法的 JSON"}, 400)

        if not path.startswith("/api/"):
            if method in ("GET", "HEAD"):
                return self.serve_static(path, head)
            return self.send_json({"error": "not found"}, 404)

        matched = None
        for entry_method, pattern, name, admin_only in ROUTES:
            match = pattern.match(path)
            if match and entry_method == method:
                matched = (name, match, admin_only)
                break
        if not matched:
            return self.send_json({"error": "接口不存在"}, 404)

        name, match, admin_only = matched
        self.conn = db.connect()
        try:
            self.user = self.load_session_user()
            if name not in ("health", "register", "login") and not self.user:
                raise ApiError(401, "请先登录")
            if admin_only and not self.user["is_admin"]:
                raise ApiError(403, "需要管理员权限")
            handler = getattr(self, "api_" + name)
            groups = match.groups()
            result = handler(groups) if groups else handler()
            status = 200
            if isinstance(result, tuple):
                status, result = result
            self.send_json(result if result is not None else {"ok": True}, status)
        except ApiError as error:
            self.send_json({"error": error.message}, error.status)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.send_json({"error": "服务器内部错误"}, 500)
        finally:
            if self.conn:
                self.conn.close()
                self.conn = None

    def load_session_user(self):
        raw = self.headers.get("Cookie") or ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        if not morsel:
            return None
        user_id = db.verify_token(morsel.value)
        if not user_id:
            return None
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def set_session(self, user_id):
        token = db.make_token(user_id, SESSION_DAYS)
        self.cookies_out.append(
            "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
            % (SESSION_COOKIE, token, SESSION_DAYS * 86400)
        )

    def clear_session(self):
        self.cookies_out.append("%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % SESSION_COOKIE)

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for cookie in self.cookies_out:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def serve_static(self, path, head=False):
        if path in ("/", "/index.html"):
            file_path = os.path.join(STATIC_DIR, "index.html")
        elif path.startswith("/static/"):
            relative = path[len("/static/"):]
            file_path = os.path.normpath(os.path.join(STATIC_DIR, relative))
            if not file_path.startswith(STATIC_DIR + os.sep):
                return self.send_json({"error": "forbidden"}, 403)
        elif path == "/favicon.ico":
            # 浏览器自动请求，返回 204 避免控制台出现 404；图标由页面内 <link rel="icon"> 提供
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            # SPA：未知路径回落到首页
            file_path = os.path.join(STATIC_DIR, "index.html")

        if not os.path.isfile(file_path):
            return self.send_json({"error": "not found"}, 404)
        with open(file_path, "rb") as handle:
            data = handle.read()
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write(
            "[%s] %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.address_string(), fmt % args)
        )

    # ------------------------------------------------------------ 账号

    def api_health(self):
        return {"ok": True, "service": "survey", "time": db.now()}

    def api_register(self):
        username = text(self.body.get("username"), 40)
        password = str(self.body.get("password") or "")
        display_name = text(self.body.get("display_name"), 40) or username
        need(re.match(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$", username), "用户名需为 3-20 位字母、数字、下划线或中文")
        need(len(password) >= 6, "密码至少需要 6 位")
        if self.conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            fail("该用户名已被注册", 409)
        cur = self.conn.execute(
            "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) VALUES(?,?,?,0,?)",
            (username, display_name, db.hash_password(password), db.now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        self.set_session(row["id"])
        return {"user": public_user(row)}

    def api_login(self):
        username = text(self.body.get("username"), 40)
        password = str(self.body.get("password") or "")
        need(username and password, "请输入用户名和密码")
        row = self.conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or not db.verify_password(password, row["password_hash"]):
            fail("用户名或密码错误", 401)
        self.set_session(row["id"])
        return {"user": public_user(row)}

    def api_logout(self):
        self.clear_session()
        return {"ok": True}

    def api_me(self):
        if not self.user:
            return {"user": None}
        return {"user": public_user(self.user)}

    def api_change_password(self):
        old = str(self.body.get("old_password") or "")
        new = str(self.body.get("new_password") or "")
        need(len(new) >= 6, "新密码至少需要 6 位")
        need(db.verify_password(old, self.user["password_hash"]), "原密码不正确")
        self.conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(new), self.user["id"])
        )
        self.conn.commit()
        return {"ok": True}

    # ------------------------------------------------------------ 问卷填写

    def api_survey_list(self):
        rows = self.conn.execute(
            "SELECT s.id, s.title, s.description, s.status, s.created_at, "
            "(SELECT COUNT(*) FROM questions q WHERE q.survey_id=s.id) AS question_count, "
            "(SELECT COUNT(*) FROM responses r WHERE r.survey_id=s.id) AS response_count "
            "FROM surveys s ORDER BY s.id DESC"
        ).fetchall()
        surveys = []
        for row in rows:
            item = dict(row)
            item["answered"] = bool(
                self.conn.execute(
                    "SELECT 1 FROM responses WHERE survey_id=? AND user_id=?",
                    (row["id"], self.user["id"]),
                ).fetchone()
            )
            surveys.append(item)
        return {"surveys": surveys}

    def load_survey(self, survey_id):
        row = self.conn.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
        need(row, "问卷不存在", 404)
        return dict(row)

    def api_survey_detail(self, params):
        survey = self.load_survey(int(params[0]))
        questions = db.get_survey_questions(self.conn, survey["id"])
        faked = db.fake_options_for(self.conn, self.user["id"], survey["id"])
        items = []
        for question in questions:
            options = faked.get(question["id"]) or db.question_options(question)
            items.append(
                {
                    "id": question["id"],
                    "qtype": question["qtype"],
                    "title": question["title"],
                    "options": options,
                    "required": bool(question["required"]),
                }
            )
        response = self.conn.execute(
            "SELECT id FROM responses WHERE survey_id=? AND user_id=?",
            (survey["id"], self.user["id"]),
        ).fetchone()
        answers = {}
        if response:
            for row in self.conn.execute(
                "SELECT question_id, value FROM answers WHERE response_id=?", (response["id"],)
            ):
                try:
                    answers[str(row["question_id"])] = json.loads(row["value"])
                except Exception:
                    answers[str(row["question_id"])] = None
        return {
            "survey": survey,
            "questions": items,
            "answered": bool(response),
            "answers": answers,
        }

    def api_survey_submit(self, params):
        survey = self.load_survey(int(params[0]))
        need(survey["status"] == "open", "该问卷已关闭，无法提交")
        questions = db.get_survey_questions(self.conn, survey["id"])
        need(questions, "该问卷还没有题目")
        raw_answers = self.body.get("answers") or {}
        need(isinstance(raw_answers, dict), "answers 参数格式错误")
        faked = db.fake_options_for(self.conn, self.user["id"], survey["id"])
        stored = {}
        for question in questions:
            qid = str(question["id"])
            value = raw_answers.get(qid)
            options = faked.get(question["id"]) or db.question_options(question)
            qtype = question["qtype"]
            if qtype == "text":
                value = text(value, 2000)
                need(value or not question["required"], "请填写第 %d 题" % (question["pos"] + 1))
            elif qtype == "multi":
                need(isinstance(value, list), "第 %d 题答案格式错误" % (question["pos"] + 1))
                value = [str(v) for v in value if str(v) in options]
                need(value or not question["required"], "请选择第 %d 题" % (question["pos"] + 1))
            elif qtype == "scale":
                need(str(value) in ("1", "2", "3", "4", "5"), "请选择第 %d 题" % (question["pos"] + 1))
                value = int(value)
            else:
                need(str(value) in options, "请选择第 %d 题" % (question["pos"] + 1))
                value = str(value)
            stored[question["id"]] = value

        existing = self.conn.execute(
            "SELECT id FROM responses WHERE survey_id=? AND user_id=?",
            (survey["id"], self.user["id"]),
        ).fetchone()
        if existing:
            response_id = existing["id"]
            self.conn.execute("UPDATE responses SET submitted_at=? WHERE id=?", (db.now(), response_id))
            self.conn.execute("DELETE FROM answers WHERE response_id=?", (response_id,))
        else:
            cur = self.conn.execute(
                "INSERT INTO responses(survey_id, user_id, submitted_at) VALUES(?,?,?)",
                (survey["id"], self.user["id"], db.now()),
            )
            response_id = cur.lastrowid
        for question_id, value in stored.items():
            self.conn.execute(
                "INSERT INTO answers(response_id, question_id, value) VALUES(?,?,?)",
                (response_id, question_id, json.dumps(value, ensure_ascii=False)),
            )
        self.conn.commit()
        return {"ok": True, "response_id": response_id}

    def api_survey_results(self, params):
        survey = self.load_survey(int(params[0]))
        questions = db.get_survey_questions(self.conn, survey["id"])
        is_admin = bool(self.user["is_admin"])
        me = self.user["id"]

        granted = {}
        for row in self.conn.execute(
            "SELECT target_id FROM visibility WHERE viewer_id=? AND (survey_id=0 OR survey_id=?)",
            (me, survey["id"]),
        ):
            granted[row["target_id"]] = True

        response_rows = self.conn.execute(
            "SELECT r.id, r.user_id, r.submitted_at, u.username, u.display_name "
            "FROM responses r JOIN users u ON u.id = r.user_id WHERE r.survey_id=? ORDER BY r.id",
            (survey["id"],),
        ).fetchall()
        visible = [
            row
            for row in response_rows
            if is_admin or row["user_id"] == me or row["user_id"] in granted
        ]

        responses = []
        for row in visible:
            values = {}
            for answer in self.conn.execute(
                "SELECT question_id, value FROM answers WHERE response_id=?", (row["id"],)
            ):
                try:
                    values[str(answer["question_id"])] = json.loads(answer["value"])
                except Exception:
                    values[str(answer["question_id"])] = None
            responses.append(
                {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "submitted_at": row["submitted_at"],
                    "is_self": row["user_id"] == me,
                    "answers": values,
                }
            )

        aggregate = []
        if is_admin:
            for question in questions:
                options = db.question_options(question)
                qtype = question["qtype"]
                texts = []
                total = 0
                counts = {}
                rows = self.conn.execute(
                    "SELECT a.value FROM answers a JOIN responses r ON r.id = a.response_id "
                    "WHERE r.survey_id=? AND a.question_id=?",
                    (survey["id"], question["id"]),
                ).fetchall()
                for row in rows:
                    try:
                        value = json.loads(row["value"])
                    except Exception:
                        continue
                    total += 1
                    if qtype == "multi" and isinstance(value, list):
                        for item in value:
                            counts[str(item)] = counts.get(str(item), 0) + 1
                    elif qtype == "scale":
                        key = str(value)
                        counts[key] = counts.get(key, 0) + 1
                    elif qtype == "text":
                        if isinstance(value, str) and value.strip():
                            texts.append(value.strip()[:500])
                    else:
                        if isinstance(value, str):
                            counts[value] = counts.get(value, 0) + 1
                if qtype == "text":
                    merged = {}
                elif qtype == "scale":
                    merged = {str(i): 0 for i in range(1, 6)}
                else:
                    merged = {option: 0 for option in options}
                    for key, value in counts.items():
                        merged[key] = merged.get(key, 0) + value
                    counts = {}
                for key, value in counts.items():
                    merged[key] = value
                aggregate.append(
                    {
                        "question_id": question["id"],
                        "title": question["title"],
                        "qtype": qtype,
                        "options": options,
                        "counts": [{"option": k, "count": v} for k, v in merged.items()],
                        "texts": texts,
                        "total": total,
                    }
                )

        return {
            "survey": survey,
            "questions": [
                {
                    "id": q["id"],
                    "qtype": q["qtype"],
                    "title": q["title"],
                    "options": db.question_options(q),
                    "pos": q["pos"],
                }
                for q in questions
            ],
            "responses": responses,
            "aggregate": aggregate,
            "can_view_all": is_admin,
            "can_view_aggregate": is_admin,
            "granted": sorted(granted.keys()),
        }

    # ------------------------------------------------------------ 管理员：用户

    def api_admin_users(self):
        rows = self.conn.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM responses r WHERE r.user_id=u.id) AS response_count "
            "FROM users u ORDER BY u.is_admin DESC, u.id"
        ).fetchall()
        users = []
        for row in rows:
            item = public_user(row)
            item["response_count"] = row["response_count"]
            users.append(item)
        return {"users": users}

    def api_admin_user_create(self):
        username = text(self.body.get("username"), 40)
        password = str(self.body.get("password") or "")
        display_name = text(self.body.get("display_name"), 40) or username
        is_admin = 1 if as_bool(self.body.get("is_admin")) else 0
        need(re.match(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,20}$", username), "用户名需为 2-20 位字母、数字、下划线或中文")
        need(len(password) >= 6, "密码至少需要 6 位")
        if self.conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            fail("该用户名已存在", 409)
        cur = self.conn.execute(
            "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) VALUES(?,?,?,?,?)",
            (username, display_name, db.hash_password(password), is_admin, db.now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"user": public_user(row)}

    def api_admin_user_update(self, params):
        user_id = int(params[0])
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        need(row, "用户不存在", 404)
        display_name = text(self.body.get("display_name"), 40) or row["display_name"]
        is_admin = row["is_admin"]
        if "is_admin" in self.body:
            is_admin = 1 if as_bool(self.body.get("is_admin")) else 0
            if row["is_admin"] and not is_admin:
                admins = self.conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin=1").fetchone()["c"]
                need(admins > 1, "至少需要保留一名管理员")
        self.conn.execute(
            "UPDATE users SET display_name=?, is_admin=? WHERE id=?", (display_name, is_admin, user_id)
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return {"user": public_user(row)}

    def api_admin_user_password(self, params):
        user_id = int(params[0])
        password = str(self.body.get("password") or "")
        need(len(password) >= 6, "密码至少需要 6 位")
        need(self.conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone(), "用户不存在", 404)
        self.conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(password), user_id)
        )
        self.conn.commit()
        return {"ok": True}

    def api_admin_user_delete(self, params):
        user_id = int(params[0])
        need(user_id != self.user["id"], "不能删除自己的账号")
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        need(row, "用户不存在", 404)
        if row["is_admin"]:
            admins = self.conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin=1").fetchone()["c"]
            need(admins > 1, "至少需要保留一名管理员")
        self.conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        self.conn.commit()
        return {"ok": True}

    # ------------------------------------------------------------ 管理员：问卷

    def api_admin_survey_create(self):
        title = text(self.body.get("title"), 120)
        need(title, "请填写问卷标题")
        cur = self.conn.execute(
            "INSERT INTO surveys(title, description, status, created_by, created_at) VALUES(?,?,?,?,?)",
            (title, text(self.body.get("description"), 1000), "open", self.user["id"], db.now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM surveys WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"survey": dict(row)}

    def api_admin_survey_detail(self, params):
        survey = self.load_survey(int(params[0]))
        questions = db.get_survey_questions(self.conn, survey["id"])
        return {
            "survey": survey,
            "questions": [
                {
                    "id": q["id"],
                    "pos": q["pos"],
                    "qtype": q["qtype"],
                    "title": q["title"],
                    "options": db.question_options(q),
                    "required": bool(q["required"]),
                }
                for q in questions
            ],
        }

    def api_admin_survey_update(self, params):
        survey_id = int(params[0])
        survey = self.load_survey(survey_id)
        title = text(self.body.get("title"), 120) or survey["title"]
        description = (
            text(self.body.get("description"), 1000)
            if "description" in self.body
            else survey["description"]
        )
        status = text(self.body.get("status"), 20) or survey["status"]
        need(status in ("open", "closed"), "状态只能是 open 或 closed")
        self.conn.execute(
            "UPDATE surveys SET title=?, description=?, status=? WHERE id=?",
            (title, description, status, survey_id),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
        return {"survey": dict(row)}

    def api_admin_survey_delete(self, params):
        survey_id = int(params[0])
        self.load_survey(survey_id)
        self.conn.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
        self.conn.commit()
        return {"ok": True}

    def validate_question(self):
        qtype = text(self.body.get("qtype"), 20) or "single"
        need(qtype in ("single", "multi", "text", "scale"), "题型不合法")
        title = text(self.body.get("title"), 300)
        need(title, "请填写题干")
        options = normalize_options(self.body.get("options"))
        if qtype in ("single", "multi"):
            need(len(options) >= 2, "选择题至少需要两个选项")
        if qtype == "scale":
            options = options or ["非常不同意", "不同意", "一般", "同意", "非常同意"]
            need(len(options) == 5, "量表题需要 5 个刻度")
        if qtype == "text":
            options = []
        required = 1 if as_bool(self.body.get("required", True)) else 0
        return qtype, title, options, required

    def api_admin_question_create(self, params):
        survey_id = int(params[0])
        self.load_survey(survey_id)
        qtype, title, options, required = self.validate_question()
        pos = self.conn.execute(
            "SELECT COALESCE(MAX(pos), -1) + 1 AS p FROM questions WHERE survey_id=?", (survey_id,)
        ).fetchone()["p"]
        cur = self.conn.execute(
            "INSERT INTO questions(survey_id, pos, qtype, title, options, required) VALUES(?,?,?,?,?,?)",
            (survey_id, pos, qtype, title, json.dumps(options, ensure_ascii=False), required),
        )
        self.conn.commit()
        row = db.question_brief(self.conn, cur.lastrowid)
        row["options"] = json.loads(row["options"])
        return {"question": row}

    def api_admin_question_bulk(self, params):
        survey_id = int(params[0])
        self.load_survey(survey_id)
        questions = self.body.get("questions")
        need(isinstance(questions, list) and questions, "请提供要添加的题目")
        created = []
        pos = self.conn.execute(
            "SELECT COALESCE(MAX(pos), -1) + 1 AS p FROM questions WHERE survey_id=?", (survey_id,)
        ).fetchone()["p"]
        for item in questions:
            need(isinstance(item, dict), "题目格式错误")
            qtype = text(item.get("type") or item.get("qtype"), 20) or "single"
            need(qtype in ("single", "multi", "text", "scale"), "题型不合法")
            title = text(item.get("title"), 300)
            need(title, "题干不能为空")
            options = normalize_options(item.get("options"))
            if qtype in ("single", "multi"):
                need(len(options) >= 2, "选择题至少需要两个选项")
            if qtype == "scale":
                options = options if len(options) == 5 else ["非常不同意", "不同意", "一般", "同意", "非常同意"]
            if qtype == "text":
                options = []
            cur = self.conn.execute(
                "INSERT INTO questions(survey_id, pos, qtype, title, options, required) VALUES(?,?,?,?,?,?)",
                (survey_id, pos, qtype, title, json.dumps(options, ensure_ascii=False), 1),
            )
            pos += 1
            created.append(cur.lastrowid)
        self.conn.commit()
        return {"ok": True, "count": len(created), "ids": created}

    def api_admin_question_update(self, params):
        question_id = int(params[0])
        row = self.conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        need(row, "题目不存在", 404)
        qtype, title, options, required = self.validate_question()
        self.conn.execute(
            "UPDATE questions SET qtype=?, title=?, options=?, required=? WHERE id=?",
            (qtype, title, json.dumps(options, ensure_ascii=False), required, question_id),
        )
        self.conn.commit()
        row = db.question_brief(self.conn, question_id)
        row["options"] = json.loads(row["options"])
        return {"question": row}

    def api_admin_question_delete(self, params):
        question_id = int(params[0])
        need(self.conn.execute("SELECT 1 FROM questions WHERE id=?", (question_id,)).fetchone(), "题目不存在", 404)
        self.conn.execute("DELETE FROM questions WHERE id=?", (question_id,))
        self.conn.commit()
        return {"ok": True}

    # ------------------------------------------------------------ 管理员：可见性

    def api_admin_visibility_list(self):
        users = [
            public_user(row)
            for row in self.conn.execute("SELECT * FROM users ORDER BY is_admin DESC, id")
        ]
        pairs = [
            {"viewer_id": row["viewer_id"], "target_id": row["target_id"], "survey_id": row["survey_id"]}
            for row in self.conn.execute("SELECT viewer_id, target_id, survey_id FROM visibility")
        ]
        surveys = [
            {"id": row["id"], "title": row["title"]}
            for row in self.conn.execute("SELECT id, title FROM surveys ORDER BY id DESC")
        ]
        return {"users": users, "pairs": pairs, "surveys": surveys}

    def api_admin_visibility_set(self):
        viewer_id = int(self.body.get("viewer_id") or 0)
        target_id = int(self.body.get("target_id") or 0)
        survey_id = int(self.body.get("survey_id") or 0)
        enabled = 1 if as_bool(self.body.get("enabled")) else 0
        need(viewer_id and target_id, "参数不完整")
        need(viewer_id != target_id, "不能给自己设置查看权限")
        need(self.conn.execute("SELECT 1 FROM users WHERE id=?", (viewer_id,)).fetchone(), "查看者不存在", 404)
        need(self.conn.execute("SELECT 1 FROM users WHERE id=?", (target_id,)).fetchone(), "被查看者不存在", 404)
        if survey_id:
            need(self.conn.execute("SELECT 1 FROM surveys WHERE id=?", (survey_id,)).fetchone(), "问卷不存在", 404)
        if enabled:
            self.conn.execute(
                "INSERT OR IGNORE INTO visibility(viewer_id, target_id, survey_id) VALUES(?,?,?)",
                (viewer_id, target_id, survey_id),
            )
        else:
            self.conn.execute(
                "DELETE FROM visibility WHERE viewer_id=? AND target_id=? AND survey_id=?",
                (viewer_id, target_id, survey_id),
            )
        self.conn.commit()
        return {"ok": True}

    def api_admin_visibility_clear(self):
        survey_id = int(self.body.get("survey_id") or 0)
        self.conn.execute("DELETE FROM visibility WHERE survey_id=?", (survey_id,))
        self.conn.commit()
        return {"ok": True}

    # ------------------------------------------------------------ 管理员：虚假选项

    def api_admin_fake_list(self):
        survey_id = int(self.query.get("survey_id") or 0)
        need(survey_id, "请选择问卷")
        questions = db.get_survey_questions(self.conn, survey_id)
        overrides = self.conn.execute(
            "SELECT f.id, f.user_id, f.question_id, f.options, u.username, u.display_name "
            "FROM fake_options f JOIN users u ON u.id = f.user_id "
            "JOIN questions q ON q.id = f.question_id WHERE q.survey_id=? ORDER BY f.id",
            (survey_id,),
        ).fetchall()
        items = []
        for row in overrides:
            try:
                options = json.loads(row["options"])
            except Exception:
                options = []
            items.append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "question_id": row["question_id"],
                    "options": options,
                }
            )
        return {
            "questions": [
                {
                    "id": q["id"],
                    "title": q["title"],
                    "qtype": q["qtype"],
                    "options": db.question_options(q),
                }
                for q in questions
            ],
            "overrides": items,
        }

    def api_admin_fake_set(self):
        user_id = int(self.body.get("user_id") or 0)
        question_id = int(self.body.get("question_id") or 0)
        options = normalize_options(self.body.get("options"))
        need(user_id and question_id, "参数不完整")
        need(self.conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone(), "用户不存在", 404)
        need(self.conn.execute("SELECT 1 FROM questions WHERE id=?", (question_id,)).fetchone(), "题目不存在", 404)
        question = db.question_brief(self.conn, question_id)
        need(question["qtype"] in ("single", "multi"), "只有选择题可以设置虚假选项")
        if not options:
            self.conn.execute(
                "DELETE FROM fake_options WHERE user_id=? AND question_id=?", (user_id, question_id)
            )
        else:
            need(len(options) >= 2, "至少需要两个虚假选项")
            self.conn.execute(
                "INSERT OR REPLACE INTO fake_options(user_id, question_id, options) VALUES(?,?,?)",
                (user_id, question_id, json.dumps(options, ensure_ascii=False)),
            )
        self.conn.commit()
        return {"ok": True}

    def api_admin_fake_delete(self, params):
        fake_id = int(params[0])
        self.conn.execute("DELETE FROM fake_options WHERE id=?", (fake_id,))
        self.conn.commit()
        return {"ok": True}

    def api_admin_fake_preview(self):
        user_id = int(self.query.get("user_id") or 0)
        survey_id = int(self.query.get("survey_id") or 0)
        need(user_id and survey_id, "参数不完整")
        questions = db.get_survey_questions(self.conn, survey_id)
        faked = db.fake_options_for(self.conn, user_id, survey_id)
        return {
            "questions": [
                {
                    "id": q["id"],
                    "title": q["title"],
                    "qtype": q["qtype"],
                    "real_options": db.question_options(q),
                    "seen_options": faked.get(q["id"]) or db.question_options(q),
                    "faked": q["id"] in faked,
                }
                for q in questions
            ]
        }

    # ------------------------------------------------------------ 管理员：AI

    def ai_config(self):
        settings = db.get_settings()
        return {
            "base_url": settings.get("ai_base_url"),
            "api_key": settings.get("ai_api_key"),
            "model": settings.get("ai_model"),
            "temperature": settings.get("ai_temperature"),
            "system_prompt": settings.get("ai_system_prompt"),
        }

    def api_admin_settings_get(self):
        settings = db.get_settings()
        api_key = settings.get("ai_api_key") or ""
        return {
            "ai_base_url": settings.get("ai_base_url"),
            "ai_model": settings.get("ai_model"),
            "ai_temperature": settings.get("ai_temperature"),
            "ai_system_prompt": settings.get("ai_system_prompt"),
            "has_api_key": bool(api_key),
            "api_key_hint": ("%s****%s" % (api_key[:4], api_key[-4:])) if len(api_key) >= 12 else ("已配置" if api_key else ""),
        }

    def api_admin_settings_set(self):
        values = {}
        for field in ("ai_base_url", "ai_model", "ai_temperature", "ai_system_prompt"):
            if field in self.body:
                values[field] = text(self.body.get(field), 4000)
        if self.body.get("clear_api_key"):
            values["ai_api_key"] = ""
        elif self.body.get("ai_api_key"):
            values["ai_api_key"] = text(self.body.get("ai_api_key"), 400)
        if "ai_base_url" in values:
            need(values["ai_base_url"].startswith("http"), "接口地址需要以 http(s):// 开头")
        if "ai_temperature" in values:
            try:
                float(values["ai_temperature"])
            except Exception:
                fail("温度需要是数字")
        db.set_settings(values)
        return self.api_admin_settings_get()

    def api_admin_ai_generate(self):
        prompt = text(self.body.get("prompt"), 4000)
        count = int(self.body.get("count") or 5)
        raw_types = self.body.get("qtypes")
        allowed = ("single", "multi", "text", "scale")
        if isinstance(raw_types, list):
            qtypes = [text(item, 20) for item in raw_types]
            qtypes = [item for item in qtypes if item in allowed]
        else:
            single = text(self.body.get("qtype"), 20) or "single"
            qtypes = [single] if single in allowed else []
        need(qtypes, "请至少选择一种题型")
        cfg = self.ai_config()
        try:
            questions = ai.generate(cfg, prompt, count, qtypes)
        except ai.AIError as error:
            fail(str(error), 502)
        return {"questions": questions, "model": cfg.get("model"), "count": len(questions), "qtypes": qtypes}

    def api_admin_ai_test(self):
        cfg = self.ai_config()
        if "ai_base_url" in self.body:
            cfg["base_url"] = text(self.body.get("ai_base_url"), 400)
        if "ai_model" in self.body:
            cfg["model"] = text(self.body.get("ai_model"), 120)
        if "ai_temperature" in self.body:
            cfg["temperature"] = text(self.body.get("ai_temperature"), 20)
        key = text(self.body.get("ai_api_key"), 400)
        if key:
            cfg["api_key"] = key
        need(cfg.get("api_key"), "请先填写 API Key")
        try:
            reply = ai.test_connection(cfg)
        except ai.AIError as error:
            fail(str(error), 502)
        return {"ok": True, "reply": reply, "model": cfg.get("model")}

    def api_admin_prompt_list(self):
        rows = self.conn.execute("SELECT * FROM prompts ORDER BY id DESC").fetchall()
        return {"prompts": [dict(row) for row in rows]}

    def api_admin_prompt_create(self):
        name = text(self.body.get("name"), 80)
        content = text(self.body.get("content"), 4000)
        need(name and content, "请填写模板名称和内容")
        cur = self.conn.execute(
            "INSERT INTO prompts(name, content, created_at) VALUES(?,?,?)",
            (name, content, db.now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM prompts WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"prompt": dict(row)}

    def api_admin_prompt_delete(self, params):
        prompt_id = int(params[0])
        self.conn.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))
        self.conn.commit()
        return {"ok": True}


def main():
    db.init()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    sys.stderr.write("survey app listening on http://%s:%d\n" % (HOST, PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
