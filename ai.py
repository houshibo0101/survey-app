#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 出题：调用 OpenAI 兼容的 /chat/completions 接口，并解析题目 JSON。"""

import json
import re
import ssl
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 120

QTYPE_LABELS = {
    "single": "单选题",
    "multi": "多选题",
    "text": "填空题",
    "scale": "量表题",
}


class AIError(Exception):
    pass


def normalize_base_url(base_url):
    """兼容用户直接粘贴完整端点的情况：去掉 /chat/completions、/responses 等后缀。"""
    url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/") or DEFAULT_BASE_URL


def chat(cfg, messages, timeout=TIMEOUT):
    base_url = normalize_base_url(cfg.get("base_url"))
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or DEFAULT_MODEL).strip()
    if not api_key:
        raise AIError("尚未配置 AI 模型 API Key，请先到「系统设置」填写。")
    try:
        temperature = float(cfg.get("temperature") or 0.8)
    except Exception:
        temperature = 0.8
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:600]
        hint = ""
        if error.code in (404, 400):
            hint = (
                "（请确认接口地址：DeepSeek 为 https://api.deepseek.com/v1，"
                "火山方舟为 https://ark.cn-beijing.volces.com/api/v3，智谱为 https://open.bigmodel.cn/api/paas/v4）"
            )
        raise AIError("AI 接口返回 HTTP %s：%s %s" % (error.code, detail, hint))
    except urllib.error.URLError as error:
        raise AIError("无法连接 AI 接口：%s" % error.reason)
    except Exception as error:  # noqa: BLE001
        raise AIError("调用 AI 接口失败：%s" % error)

    try:
        data = json.loads(body)
    except Exception:
        raise AIError("AI 接口返回的不是 JSON：" + body[:300])
    if isinstance(data, dict) and data.get("error"):
        message = data["error"]
        if isinstance(message, dict):
            message = message.get("message") or json.dumps(message, ensure_ascii=False)
        raise AIError("AI 接口错误：" + str(message)[:400])
    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        raise AIError("AI 接口返回结构异常：" + body[:300])


def build_messages(system_prompt, user_prompt, count, qtypes):
    qtypes = [item for item in (qtypes or ["single"]) if item in QTYPE_LABELS] or ["single"]
    labels = [QTYPE_LABELS[item] for item in qtypes]
    system = (system_prompt or "").strip() or (
        "你是一位资深的问卷设计专家，只输出 JSON，不输出解释或代码围栏。"
    )
    system += (
        "\n\n输出要求：只返回一个 JSON 对象，格式为 "
        '{"questions":[{"title":"题干","type":"single|multi|text|scale","options":["选项1","选项2"]}]}。'
        "\n规则：title 必须是完整问句；单选题固定 4-6 个选项；多选题固定 4-6 个选项且不少于两个；"
        "填空题 options 为 []；量表题 options 为 1-5 的五个刻度描述。不要编号，不要重复题干。"
        "\n本题只允许使用以下题型：" + "、".join(labels) + "（type 字段依次为 " + ", ".join(qtypes) + "）。"
    )
    user = (user_prompt or "").strip()
    if not user:
        user = "请设计一组关于用户满意度的调查问题。"
    user += "\n\n请严格生成 %d 道题目，题型限定为：%s。" % (count, "、".join(labels))
    if len(qtypes) > 1:
        user += "每种题型至少 1 道，数量尽量平均分布。"
    user += "全部使用简体中文，直接输出 JSON。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _clean_options(value):
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    elif isinstance(value, str):
        items = [piece.strip() for piece in re.split(r"[，,、；;\n]+", value)]
    else:
        items = []
    result = []
    for item in items:
        item = re.sub(r"^[A-Fa-f][\.、\)]\s*", "", item).strip()
        if item and item not in result:
            result.append(item)
    return result


def parse_questions(text):
    """从模型输出中提取题目数组，兼容代码围栏、前后说明文字等。"""
    if not text:
        raise AIError("AI 没有返回内容。")
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    candidates = []
    for match in re.finditer(r"\{[\s\S]*\}|\[[\s\S]*\]", raw):
        candidates.append(match.group(0))
    candidates.append(raw)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            data = data.get("questions") or data.get("data") or data.get("items")
        if isinstance(data, list) and data:
            questions = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("question") or "").strip()
                if not title:
                    continue
                qtype = str(item.get("type") or "single").strip().lower()
                qtype = {
                    "单选": "single",
                    "多选": "multi",
                    "填空": "text",
                    "问答": "text",
                    "量表": "scale",
                }.get(qtype, qtype)
                if qtype not in QTYPE_LABELS:
                    qtype = "single"
                options = _clean_options(item.get("options") or item.get("choices") or [])
                if qtype in ("single", "multi") and len(options) < 2:
                    continue
                if qtype == "text":
                    options = []
                if qtype == "scale" and len(options) != 5:
                    options = ["非常不同意", "不同意", "一般", "同意", "非常同意"]
                questions.append({"title": title, "type": qtype, "options": options})
            if questions:
                return questions
    raise AIError("无法解析 AI 返回的题目，请调整提示词后重试。原始返回：" + raw[:300])


def generate(cfg, user_prompt, count, qtypes):
    count = max(1, min(int(count or 5), 20))
    if isinstance(qtypes, str):
        qtypes = [qtypes]
    qtypes = [item for item in (qtypes or ["single"]) if item in QTYPE_LABELS] or ["single"]
    messages = build_messages(cfg.get("system_prompt"), user_prompt, count, qtypes)
    content = chat(cfg, messages)
    return parse_questions(content)


def test_connection(cfg):
    """用一条极短请求验证地址、密钥、模型是否可用。"""
    reply = chat(cfg, [{"role": "user", "content": "只回复两个字：正常"}], timeout=40)
    return (reply or "").strip()[:200]
