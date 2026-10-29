"""One place that talks to Groq's chat API across its whole model lineup.

Groq's free tier meters every model separately (requests and tokens per minute and per day),
so when one model's allowance is used up the others are still open. Calls here try each model
in turn, and each API key within a model, and only give up when all of them have refused.

Lineup checked live 2026-10-29 for this account (chat capable): openai/gpt-oss-120b,
openai/gpt-oss-20b and qwen/qwen3.8-27b. All three return a clean JSON answer to the
extraction prompts; llama-3.3-70b-versatile no longer exists there. Override the order with the
GROQ_MODELS environment variable (comma separated).
"""
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
MODELS = [m.strip() for m in os.environ.get("GROQ_MODELS", ",".join(DEFAULT_MODELS)).split(",") if m.strip()]

# Groq sits behind Cloudflare, which rejects urllib's default User-Agent (error 1010).
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

OK, RATE_LIMITED, ERROR = "ok", "ratelimited", "error"


def api_keys() -> list[str]:
    names = ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROQ_API_KEY_5")
    return [k for k in (os.environ.get(n, "") for n in names) if k]


def chat(prompt: str, max_tokens: int, timeout: int = 60) -> tuple[str | None, str, str]:
    """Returns (text, status, model_used). status is "ok", "ratelimited" (every model and key
    answered 429 or 413) or "error" (a real failure, or nothing usable came back)."""
    keys = api_keys()
    if not keys:
        return None, ERROR, ""

    limited = False
    for model in MODELS:
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if model.startswith("openai/gpt-oss"):
            # A reasoning model: without this it can spend the whole budget thinking and
            # return an empty answer.
            body["reasoning_effort"] = "low"
        payload = json.dumps(body).encode("utf-8")

        for key in keys:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions", data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": _UA})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    content = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    limited = True
                    continue  # this key is spent for this model: try the next key
                if e.code == 413:
                    limited = True  # this request is too big for this model's limit
                break  # next model
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
                break
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
            if content:
                return content, OK, model
            break  # empty answer: try the next model

    return None, (RATE_LIMITED if limited else ERROR), ""
