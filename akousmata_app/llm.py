"""BYOK completion adapter — three provider shapes, all local-first.

- ``openai_compatible``: any /v1/chat/completions endpoint (OpenAI, xAI/Grok,
  OpenRouter, Ollama, llama.cpp server) with a base URL, model, and key.
- ``anthropic``: the Anthropic Messages API.
- ``cli``: a local agent command that reads the prompt on stdin and prints
  the answer (codex CLI, opencode, or any executable on ``PATH``) — no key
  leaves the machine at all.

The rest of the app treats this as one function: ``complete(prompt) -> str``.
``LLMUnavailable`` means the navigator keeps working as a pure library.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import urllib.parse
import urllib.request
from typing import Any


class LLMUnavailable(RuntimeError):
    """No provider configured, or the provider call failed."""


def validate_http_url(value: str, *, label: str = "endpoint") -> str:
    """Return a normalized HTTP(S) URL or reject non-network URL schemes."""
    normalized = value.rstrip("/")
    try:
        parsed = urllib.parse.urlparse(normalized)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid http:// or https:// URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a valid http:// or https:// URL without credentials, query, or fragment")
    return normalized


def complete(prompt: str, settings: dict[str, Any], *, system: str | None = None, max_tokens: int = 1600, timeout: int = 120) -> str:
    llm = settings.get("llm") or {}
    provider = llm.get("provider") or "none"
    if provider == "openai_compatible":
        return _openai_compatible(prompt, llm, system=system, max_tokens=max_tokens, timeout=timeout)
    if provider == "anthropic":
        return _anthropic(prompt, llm, system=system, max_tokens=max_tokens, timeout=timeout)
    if provider == "cli":
        return _cli(prompt, llm, system=system, timeout=timeout)
    raise LLMUnavailable("no LLM provider configured (settings.llm.provider is 'none')")


def _openai_compatible(prompt: str, llm: dict[str, Any], *, system: str | None, max_tokens: int, timeout: int) -> str:
    try:
        base = validate_http_url(str(llm.get("base_url") or "https://api.openai.com"), label="openai_compatible base URL")
    except ValueError as exc:
        raise LLMUnavailable(str(exc)) from exc
    model = str(llm.get("model") or "")
    key = str(llm.get("api_key") or "")
    if not model:
        raise LLMUnavailable("openai_compatible provider needs settings.llm.model")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})},
        method="POST",
    )
    try:
        # validate_http_url() excludes urllib's local-file and custom schemes.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001 — every failure degrades identically
        raise LLMUnavailable(f"openai_compatible call failed: {exc}") from exc


def _anthropic(prompt: str, llm: dict[str, Any], *, system: str | None, max_tokens: int, timeout: int) -> str:
    key = str(llm.get("api_key") or "")
    model = str(llm.get("model") or "claude-haiku-4-5-20251001")
    if not key:
        raise LLMUnavailable("anthropic provider needs settings.llm.api_key")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    try:
        base = validate_http_url(str(llm.get("base_url") or "https://api.anthropic.com"), label="Anthropic base URL")
    except ValueError as exc:
        raise LLMUnavailable(str(exc)) from exc
    request = urllib.request.Request(
        f"{base}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            payload = json.loads(response.read().decode("utf-8"))
        return "".join(block.get("text", "") for block in payload.get("content", [])).strip()
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"anthropic call failed: {exc}") from exc


def _cli(prompt: str, llm: dict[str, Any], *, system: str | None, timeout: int) -> str:
    command = str(llm.get("command") or "").strip()
    if not command:
        raise LLMUnavailable("cli provider needs settings.llm.command")
    text = (f"{system}\n\n---\n\n{prompt}" if system else prompt)
    try:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("command is empty")
        result = subprocess.run(
            argv,
            input=text,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMUnavailable(f"cli agent timed out after {timeout}s") from exc
    except (OSError, ValueError) as exc:
        raise LLMUnavailable(f"cli agent could not start: {exc}") from exc
    if result.returncode != 0:
        raise LLMUnavailable(f"cli agent exited {result.returncode}: {result.stderr.strip()[:400]}")
    output = result.stdout.strip()
    if not output:
        raise LLMUnavailable("cli agent produced no output")
    return output
