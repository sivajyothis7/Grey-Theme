# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""LLM adapters.

The rest of Fateh AI speaks one message format — Anthropic-style content blocks:

    {"role": "user",      "content": [{"type": "text", "text": "..."}]}
    {"role": "assistant", "content": [{"type": "text", "text": "..."},
                                      {"type": "tool_use", "id": "...", "name": "...", "input": {...}}]}
    {"role": "user",      "content": [{"type": "tool_result", "tool_use_id": "...",
                                       "content": "<json string>", "is_error": False}]}

Tools are {"name", "description", "input_schema"}.

`stream_chat()` translates to the provider's wire format, streams the response and yields
normalised events:

    {"type": "text", "text": "<delta>"}
    {"type": "tool_use", "id": ..., "name": ..., "input": {...}}
    {"type": "usage", "input_tokens": n, "output_tokens": n}
    {"type": "model", "model": "<model actually used>"}
    {"type": "stop", "reason": "end_turn" | "tool_use" | "max_tokens"}

Resilience (lessons from Groq retiring model ids without notice):
- 429 / 5xx / connection errors are retried with backoff, but only while nothing has been
  yielded yet — a half-streamed answer is never replayed.
- 404 / model_not_found / model_decommissioned moves on to the next model in the chain.
"""

import json
import time

import frappe
import requests
from frappe import _
from frappe.utils import cint, cstr

ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MODEL_GONE_CODES = ("model_not_found", "model_decommissioned", "not_found_error")
MAX_RETRIES = 2


class ProviderError(Exception):
	def __init__(self, message, status=None, retryable=False, model_gone=False):
		super().__init__(message)
		self.status = status
		self.retryable = retryable
		self.model_gone = model_gone


class StopRequested(Exception):
	pass


# --------------------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------------------


def stream_chat(settings, *, messages, system, tools=None, tool_choice="auto", should_stop=None):
	"""Yield normalised events, walking the model fallback chain."""
	if not settings.models:
		raise ProviderError(_("No model is configured in AI Settings."))

	last_error = None
	for model in settings.models:
		attempt = 0
		while True:
			yielded = False
			try:
				for event in _stream_one(settings, model, messages, system, tools, tool_choice, should_stop):
					if not yielded:
						yielded = True
						yield {"type": "model", "model": model}
					yield event
				return
			except ProviderError as e:
				last_error = e
				if e.model_gone and not yielded:
					break  # try the next model in the chain
				if e.retryable and not yielded and attempt < MAX_RETRIES:
					attempt += 1
					time.sleep(min(2**attempt, 8))
					continue
				raise
			except requests.RequestException as e:
				last_error = ProviderError(_("Could not reach the model provider: %(err)s") % {"err": cstr(e)})
				if not yielded and attempt < MAX_RETRIES:
					attempt += 1
					time.sleep(min(2**attempt, 8))
					continue
				raise last_error from e

	raise last_error or ProviderError(_("No model in the chain is available."))


def complete(settings, *, messages, system, max_tokens=64):
	"""Non-tool, collected completion — used by Test Connection."""
	text = []
	usage = {}
	model_used = None
	for event in stream_chat(settings, messages=messages, system=system, tools=None):
		if event["type"] == "text":
			text.append(event["text"])
		elif event["type"] == "usage":
			usage = event
		elif event["type"] == "model":
			model_used = event["model"]
	return {"text": "".join(text), "usage": usage, "model": model_used}


def list_models(settings):
	"""Model ids the configured key can use (best effort)."""
	headers = _headers(settings)
	url = f"{settings.base_url}/models"
	resp = requests.get(url, headers=headers, timeout=20)
	if resp.status_code >= 400:
		raise _error_from_response(resp)
	data = resp.json()
	items = data.get("data") or data.get("models") or []
	ids = []
	for item in items:
		model_id = item.get("id") or item.get("name")
		if model_id:
			ids.append(model_id)
	return sorted(set(ids))


# --------------------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------------------


def _stream_one(settings, model, messages, system, tools, tool_choice, should_stop):
	if settings.kind == "anthropic":
		yield from _anthropic_stream(settings, model, messages, system, tools, tool_choice, should_stop)
	else:
		yield from _openai_stream(settings, model, messages, system, tools, tool_choice, should_stop)


def _headers(settings):
	if settings.kind == "anthropic":
		return {
			"x-api-key": settings.api_key,
			"anthropic-version": ANTHROPIC_VERSION,
			"content-type": "application/json",
		}
	headers = {"Content-Type": "application/json"}
	if settings.api_key:
		headers["Authorization"] = f"Bearer {settings.api_key}"
	if settings.provider == "OpenRouter":
		headers["X-Title"] = "Fateh AI"
	return headers


def _post_stream(settings, url, payload):
	resp = requests.post(
		url,
		headers=_headers(settings),
		data=json.dumps(payload, default=str),
		stream=True,
		timeout=(15, settings.request_timeout),
	)
	if resp.status_code >= 400:
		try:
			raise _error_from_response(resp)
		finally:
			resp.close()
	return resp


def _error_from_response(resp):
	status = resp.status_code
	try:
		body = resp.json()
	except Exception:
		body = {"error": {"message": cstr(resp.text)[:500]}}

	err = body.get("error") if isinstance(body, dict) else None
	if isinstance(err, str):
		err = {"message": err}
	err = err or {}
	code = cstr(err.get("code") or err.get("type"))
	message = cstr(err.get("message")) or cstr(resp.reason) or _("Request failed")

	model_gone = status == 404 or code in MODEL_GONE_CODES or (
		status == 400 and ("decommissioned" in message.lower() or "does not exist" in message.lower())
	)
	if status in (401, 403):
		message = _("The API key was rejected by the provider (%(status)s): %(msg)s") % {
			"status": status,
			"msg": message,
		}
	return ProviderError(
		f"{status}: {message}",
		status=status,
		retryable=status in RETRY_STATUSES,
		model_gone=model_gone,
	)


def _iter_sse(resp, should_stop):
	"""Yield (event_name, data_str) pairs from a text/event-stream response."""
	event_name = None
	data_lines = []
	try:
		for raw in resp.iter_lines(decode_unicode=False):
			if should_stop and should_stop():
				raise StopRequested()
			line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
			if not line:
				if data_lines:
					yield event_name, "\n".join(data_lines)
				event_name, data_lines = None, []
				continue
			if line.startswith(":"):
				continue
			if line.startswith("event:"):
				event_name = line[6:].strip()
			elif line.startswith("data:"):
				data_lines.append(line[5:].lstrip())
		if data_lines:
			yield event_name, "\n".join(data_lines)
	finally:
		resp.close()


def _parse_args(raw):
	raw = (raw or "").strip()
	if not raw:
		return {}
	try:
		value = json.loads(raw)
		return value if isinstance(value, dict) else {"value": value}
	except ValueError:
		return {"__invalid_json__": raw[:2000]}


# --------------------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, Groq, DeepSeek, Gemini, OpenRouter, Ollama, custom)
# --------------------------------------------------------------------------------------


def to_openai_messages(messages, system):
	out = []
	if system:
		out.append({"role": "system", "content": system})

	for msg in messages:
		role = msg["role"]
		blocks = msg["content"]
		if isinstance(blocks, str):
			blocks = [{"type": "text", "text": blocks}]

		if role == "assistant":
			text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
			calls = [
				{
					"id": b["id"],
					"type": "function",
					"function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, default=str)},
				}
				for b in blocks
				if b.get("type") == "tool_use"
			]
			item = {"role": "assistant", "content": text if (text or not calls) else None}
			if calls:
				item["tool_calls"] = calls
			out.append(item)
			continue

		# user turn: tool results become role=tool messages, any text becomes a user message
		texts = []
		for b in blocks:
			if b.get("type") == "tool_result":
				out.append(
					{"role": "tool", "tool_call_id": b["tool_use_id"], "content": cstr(b.get("content"))}
				)
			elif b.get("type") == "text":
				texts.append(b.get("text", ""))
		if texts:
			out.append({"role": "user", "content": "\n\n".join(texts)})
	return out


def to_openai_tools(tools):
	return [
		{
			"type": "function",
			"function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
		}
		for t in tools or []
	]


def _openai_stream(settings, model, messages, system, tools, tool_choice, should_stop):
	payload = {
		"model": model,
		"messages": to_openai_messages(messages, system),
		"stream": True,
		"temperature": settings.temperature,
	}
	if settings.provider == "OpenAI":
		payload["max_completion_tokens"] = settings.max_output_tokens
		payload["stream_options"] = {"include_usage": True}
	else:
		payload["max_tokens"] = settings.max_output_tokens
		if settings.provider == "OpenRouter":
			payload["stream_options"] = {"include_usage": True}

	if "gpt-oss" in model:
		# gpt-oss is a reasoning model: with no effort hint it can spend the whole budget
		# thinking and answer with empty content.
		payload["reasoning_effort"] = "medium"

	if tools:
		payload["tools"] = to_openai_tools(tools)
		payload["tool_choice"] = tool_choice

	resp = _post_stream(settings, f"{settings.base_url}/chat/completions", payload)

	calls = {}
	order = []
	finish = None
	usage = None

	for _event, data in _iter_sse(resp, should_stop):
		if data == "[DONE]":
			break
		try:
			chunk = json.loads(data)
		except ValueError:
			continue

		if chunk.get("error"):
			err = chunk["error"]
			message = err.get("message") if isinstance(err, dict) else cstr(err)
			raise ProviderError(cstr(message) or _("The provider returned an error."))

		usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage") or usage

		for choice in chunk.get("choices") or []:
			delta = choice.get("delta") or {}
			if delta.get("content"):
				yield {"type": "text", "text": delta["content"]}

			for position, tc in enumerate(delta.get("tool_calls") or []):
				# OpenAI/Groq send an index per call; some compatible servers omit it and send
				# each call whole in one chunk, where its position is the identity.
				index = tc.get("index")
				if index is None:
					index = f"pos{position}:{tc.get('id') or ''}"
				acc = calls.get(index)
				if acc is None:
					acc = calls[index] = {"id": "", "name": "", "args": ""}
					order.append(index)
				if tc.get("id"):
					acc["id"] = tc["id"]
				fn = tc.get("function") or {}
				if fn.get("name") and not acc["name"]:
					acc["name"] = fn["name"]
				if fn.get("arguments"):
					args = fn["arguments"]
					acc["args"] += args if isinstance(args, str) else json.dumps(args)

			if choice.get("finish_reason"):
				finish = choice["finish_reason"]

	for n, index in enumerate(order):
		acc = calls[index]
		if not acc["name"]:
			continue
		yield {
			"type": "tool_use",
			"id": acc["id"] or f"call_{frappe.generate_hash(length=12)}_{n}",
			"name": acc["name"],
			"input": _parse_args(acc["args"]),
		}

	if usage:
		yield {
			"type": "usage",
			"input_tokens": cint(usage.get("prompt_tokens") or usage.get("input_tokens")),
			"output_tokens": cint(usage.get("completion_tokens") or usage.get("output_tokens")),
		}

	reason = {"tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens"}.get(
		finish, "tool_use" if order else "end_turn"
	)
	yield {"type": "stop", "reason": reason}


# --------------------------------------------------------------------------------------
# Anthropic Messages API
# --------------------------------------------------------------------------------------


def to_anthropic_messages(messages):
	out = []
	for msg in messages:
		blocks = msg["content"]
		if isinstance(blocks, str):
			blocks = [{"type": "text", "text": blocks}]
		clean = []
		for b in blocks:
			kind = b.get("type")
			if kind == "text":
				if b.get("text"):
					clean.append({"type": "text", "text": b["text"]})
			elif kind == "tool_use":
				clean.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b.get("input") or {}})
			elif kind == "tool_result":
				item = {"type": "tool_result", "tool_use_id": b["tool_use_id"], "content": cstr(b.get("content"))}
				if b.get("is_error"):
					item["is_error"] = True
				clean.append(item)
		if clean:
			out.append({"role": msg["role"], "content": clean})
	return out


def _anthropic_stream(settings, model, messages, system, tools, tool_choice, should_stop):
	payload = {
		"model": model,
		"max_tokens": settings.max_output_tokens,
		"messages": to_anthropic_messages(messages),
		"stream": True,
		"temperature": settings.temperature,
	}
	if system:
		# cache the (large, stable) system prompt between the steps of one question
		payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
	if tools:
		payload["tools"] = tools
		payload["tool_choice"] = {"type": "none"} if tool_choice == "none" else {"type": "auto"}

	resp = _post_stream(settings, f"{settings.base_url}/messages", payload)

	blocks = {}
	input_tokens = 0
	output_tokens = 0
	stop_reason = "end_turn"

	for event_name, data in _iter_sse(resp, should_stop):
		try:
			event = json.loads(data)
		except ValueError:
			continue
		kind = event.get("type") or event_name

		if kind == "message_start":
			usage = (event.get("message") or {}).get("usage") or {}
			input_tokens = (
				cint(usage.get("input_tokens"))
				+ cint(usage.get("cache_read_input_tokens"))
				+ cint(usage.get("cache_creation_input_tokens"))
			)
		elif kind == "content_block_start":
			block = event.get("content_block") or {}
			blocks[event.get("index")] = {
				"type": block.get("type"),
				"id": block.get("id"),
				"name": block.get("name"),
				"json": "",
			}
		elif kind == "content_block_delta":
			delta = event.get("delta") or {}
			if delta.get("type") == "text_delta" and delta.get("text"):
				yield {"type": "text", "text": delta["text"]}
			elif delta.get("type") == "input_json_delta":
				acc = blocks.get(event.get("index"))
				if acc is not None:
					acc["json"] += delta.get("partial_json") or ""
		elif kind == "content_block_stop":
			acc = blocks.get(event.get("index"))
			if acc and acc["type"] == "tool_use":
				yield {"type": "tool_use", "id": acc["id"], "name": acc["name"], "input": _parse_args(acc["json"])}
		elif kind == "message_delta":
			stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
			output_tokens = cint((event.get("usage") or {}).get("output_tokens")) or output_tokens
		elif kind == "error":
			err = event.get("error") or {}
			etype = cstr(err.get("type"))
			raise ProviderError(
				cstr(err.get("message")) or etype,
				retryable=etype in ("overloaded_error", "rate_limit_error", "api_error"),
			)

	yield {"type": "usage", "input_tokens": input_tokens, "output_tokens": output_tokens}
	yield {"type": "stop", "reason": stop_reason}
