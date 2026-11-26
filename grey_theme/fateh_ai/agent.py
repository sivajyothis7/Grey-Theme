# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""The agent loop. Runs in a background job as the asking user (frappe's execute_job calls
frappe.set_user with the enqueuing user), streams progress to that user over realtime and
stores every step as a Fateh AI Message row.

Realtime event "fateh_ai", payload {"conversation", "run_id", "type", ...}:
    start        {}
    delta        {"text"}                       streamed answer text
    tool_start   {"id", "name", "label", "args"}
    tool_end     {"id", "status", "error", "row_count", "duration_ms", "preview"}
    done         {"usage": {...}, "model"}
    error        {"message"}
    stopped      {}
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import cint, cstr, now_datetime

from grey_theme.fateh_ai import config, prompts, providers, tools

EVENT = "fateh_ai"
HISTORY_MESSAGES = 40
OLD_TOOL_RESULT_CHARS = 1500
FLUSH_SECONDS = 0.08
RUN_TTL = 15 * 60


def run_key(conversation):
	return f"fateh_ai:running:{conversation}"


def stop_key(run_id):
	return f"fateh_ai:stop:{run_id}"


def owner_key(run_id):
	return f"fateh_ai:run_owner:{run_id}"


class Run:
	def __init__(self, conversation, run_id, context=None):
		self.conversation = conversation
		self.run_id = run_id
		self.context = context or {}
		self.user = frappe.session.user
		self.usage = {"input_tokens": 0, "output_tokens": 0}
		self.model = None
		self._buffer = []
		self._last_flush = 0.0
		self._last_stop_check = 0.0
		self._stopped = False

	# ---------------------------------------------------------------- realtime
	def emit(self, kind, **data):
		payload = {"conversation": self.conversation, "run_id": self.run_id, "type": kind}
		payload.update(data)
		frappe.publish_realtime(EVENT, payload, user=self.user, after_commit=False)

	def push_text(self, text):
		self._buffer.append(text)
		if time.monotonic() - self._last_flush >= FLUSH_SECONDS:
			self.flush()

	def flush(self):
		if self._buffer:
			self.emit("delta", text="".join(self._buffer))
			self._buffer = []
		self._last_flush = time.monotonic()

	def should_stop(self):
		if self._stopped:
			return True
		now = time.monotonic()
		if now - self._last_stop_check < 0.4:
			return False
		self._last_stop_check = now
		self._stopped = bool(frappe.cache.get_value(stop_key(self.run_id)))
		return self._stopped

	# ---------------------------------------------------------------- storage
	def save_message(self, role, content="", blocks=None, steps=None, is_error=0, usage=None):
		doc = frappe.get_doc(
			{
				"doctype": "Fateh AI Message",
				"conversation": self.conversation,
				"role": role,
				"run_id": self.run_id,
				"content": content or "",
				"blocks": json.dumps(blocks, default=str) if blocks is not None else None,
				"steps": json.dumps(steps, default=str) if steps else None,
				"is_error": is_error,
				"model": self.model if role == "assistant" else None,
				"input_tokens": cint((usage or {}).get("input_tokens")),
				"output_tokens": cint((usage or {}).get("output_tokens")),
			}
		)
		# Internal store: rows are only ever served through api.py after an owner check.
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name

	def audit(self, tool_name, args, result):
		reference = result.reference or (None, None)
		try:
			frappe.get_doc(
				{
					"doctype": "Fateh AI Audit Log",
					"user": self.user,
					"conversation": self.conversation,
					"run_id": self.run_id,
					"tool": tool_name,
					"status": result.status,
					"arguments": json.dumps(args, default=str, indent=1)[:10000],
					"error": cstr(result.error)[:1000] or None,
					"row_count": result.row_count,
					"duration_ms": result.duration_ms,
					"reference_doctype": reference[0],
					"reference_name": reference[1],
				}
			).insert(ignore_permissions=True)  # append-only log, never user-editable
		except Exception:
			frappe.log_error(title="Fateh AI audit log failed", message=frappe.get_traceback())

	def finish_conversation(self):
		count = frappe.db.count("Fateh AI Message", {"conversation": self.conversation, "role": ["!=", "tool"]})
		current = frappe.db.get_value(
			"Fateh AI Conversation", self.conversation, ["total_input_tokens", "total_output_tokens"], as_dict=True
		) or {}
		frappe.db.set_value(
			"Fateh AI Conversation",
			self.conversation,
			{
				"message_count": count,
				"last_message_at": now_datetime(),
				"model": self.model,
				"total_input_tokens": cint(current.get("total_input_tokens")) + self.usage["input_tokens"],
				"total_output_tokens": cint(current.get("total_output_tokens")) + self.usage["output_tokens"],
			},
			update_modified=False,
		)
		frappe.db.commit()

	# ---------------------------------------------------------------- the loop
	def execute(self):
		settings = config.check_access(self.user)
		if not config.is_configured(settings):
			raise providers.ProviderError(_("The assistant has no model or API key configured. Ask a System Manager to fill in AI Settings."))

		system = prompts.build_system_prompt(settings, self.context, self.user)
		tool_defs = tools.get_tools(settings, self.user)
		messages = load_history(self.conversation, current_run=self.run_id)
		if not messages or messages[-1]["role"] != "user":
			raise providers.ProviderError(_("Nothing to answer."))

		self.emit("start")
		max_steps = settings.max_iterations
		for step in range(max_steps + 1):
			final = step == max_steps
			text, tool_uses, usage = self.call_model(settings, messages, system, tool_defs, final)
			self.usage["input_tokens"] += cint(usage.get("input_tokens"))
			self.usage["output_tokens"] += cint(usage.get("output_tokens"))

			if final and tool_uses:
				tool_uses = []  # out of budget: answer with what we have
				if not text.strip():
					text = _("I reached the limit of lookups for one question. Here is what I found so far — please narrow the question to go further.")
					self.push_text(text)
					self.flush()

			if not text.strip() and not tool_uses:
				text = _("The model returned an empty answer. Please try again or rephrase the question.")
				self.push_text(text)
				self.flush()

			blocks = ([{"type": "text", "text": text}] if text else []) + tool_uses
			assistant_name = self.save_message("assistant", content=text, blocks=blocks, usage=usage)
			messages.append({"role": "assistant", "content": blocks})

			if not tool_uses:
				break

			results, steps = [], []
			for tu in tool_uses:
				if self.should_stop():
					raise providers.StopRequested()
				args = tu.get("input") or {}
				self.emit("tool_start", id=tu["id"], name=tu["name"], label=tools.tool_label(tu["name"], args), args=args)
				result = tools.execute(tu["name"], args, settings, self.user)
				self.audit(tu["name"], args, result)
				step_ui = {
					"id": tu["id"],
					"name": tu["name"],
					"label": tools.tool_label(tu["name"], args),
					"args": args,
					"status": result.status,
					"error": result.error,
					"row_count": result.row_count,
					"duration_ms": result.duration_ms,
					"preview": result.preview,
				}
				steps.append(step_ui)
				self.emit("tool_end", **{k: v for k, v in step_ui.items() if k not in ("name", "label", "args")})
				results.append(
					{
						"type": "tool_result",
						"tool_use_id": tu["id"],
						"content": result.content,
						"is_error": result.status != "Success",
					}
				)

			frappe.db.set_value("Fateh AI Message", assistant_name, "steps", json.dumps(steps, default=str), update_modified=False)
			self.save_message("tool", blocks=results)
			messages.append({"role": "user", "content": results})

		self.flush()
		self.finish_conversation()
		self.emit("done", usage=self.usage, model=self.model)

	def call_model(self, settings, messages, system, tool_defs, final):
		text_parts, tool_uses, usage = [], [], {}
		stream = providers.stream_chat(
			settings,
			messages=messages,
			system=system,
			tools=tool_defs,
			tool_choice="none" if final else "auto",
			should_stop=self.should_stop,
		)
		for event in stream:
			kind = event["type"]
			if kind == "text":
				text_parts.append(event["text"])
				self.push_text(event["text"])
			elif kind == "tool_use":
				tool_uses.append({"type": "tool_use", "id": event["id"], "name": event["name"], "input": event["input"]})
			elif kind == "usage":
				usage = event
			elif kind == "model":
				self.model = event["model"]
		self.flush()
		return "".join(text_parts), tool_uses, usage


def load_history(conversation, current_run=None):
	"""Canonical message list for the model, repaired so every provider accepts it:
	consecutive same-role turns merged, dangling tool_use given a result, old tool output trimmed."""
	rows = frappe.get_all(
		"Fateh AI Message",
		filters={"conversation": conversation},
		fields=["role", "content", "blocks", "run_id"],
		order_by="creation desc",
		limit=HISTORY_MESSAGES,
	)
	rows.reverse()

	messages = []
	for row in rows:
		try:
			blocks = json.loads(row.blocks) if row.blocks else None
		except ValueError:
			blocks = None
		if blocks is None:
			blocks = [{"type": "text", "text": row.content or ""}] if row.content else []
		if not blocks:
			continue
		role = "assistant" if row.role == "assistant" else "user"
		if row.role == "tool" and row.run_id != current_run:
			for b in blocks:
				if b.get("type") == "tool_result" and len(cstr(b.get("content"))) > OLD_TOOL_RESULT_CHARS:
					b["content"] = cstr(b["content"])[:OLD_TOOL_RESULT_CHARS] + "…(trimmed)"
		messages.append({"role": role, "content": blocks})

	# the window may start mid-turn: drop leading assistant turns and orphan tool results
	while messages and (
		messages[0]["role"] != "user" or any(b.get("type") == "tool_result" for b in messages[0]["content"])
	):
		messages.pop(0)

	repaired = []
	for msg in messages:
		if repaired and repaired[-1]["role"] == msg["role"]:
			repaired[-1]["content"] = repaired[-1]["content"] + msg["content"]
		else:
			repaired.append({"role": msg["role"], "content": list(msg["content"])})

	# every tool_use must be answered by a tool_result in the next user turn, and vice versa
	for i, msg in enumerate(repaired):
		if msg["role"] != "assistant":
			continue
		ids = [b["id"] for b in msg["content"] if b.get("type") == "tool_use"]
		if not ids:
			continue
		nxt = repaired[i + 1] if i + 1 < len(repaired) else None
		if nxt is None or nxt["role"] != "user":
			nxt = {"role": "user", "content": []}
			repaired.insert(i + 1, nxt)
		answered = {b.get("tool_use_id") for b in nxt["content"] if b.get("type") == "tool_result"}
		missing = [
			{"type": "tool_result", "tool_use_id": tid, "content": json.dumps({"error": "cancelled"}), "is_error": True}
			for tid in ids
			if tid not in answered
		]
		# tool results must come first in the user turn
		results = [b for b in nxt["content"] if b.get("type") == "tool_result" and b.get("tool_use_id") in ids]
		others = [b for b in nxt["content"] if b.get("type") != "tool_result"]
		nxt["content"] = results + missing + others

	for i, msg in enumerate(repaired):
		if msg["role"] == "user":
			prev_ids = set()
			if i > 0 and repaired[i - 1]["role"] == "assistant":
				prev_ids = {b["id"] for b in repaired[i - 1]["content"] if b.get("type") == "tool_use"}
			msg["content"] = [
				b for b in msg["content"] if b.get("type") != "tool_result" or b.get("tool_use_id") in prev_ids
			]
	return [m for m in repaired if m["content"]]


def run(conversation, run_id, context=None):
	"""Background job entry point (enqueued by api.send_message)."""
	agent = Run(conversation, run_id, context)
	try:
		agent.execute()
	except providers.StopRequested:
		agent.flush()
		frappe.db.rollback()
		agent.save_message("assistant", content=_("(Stopped.)"), blocks=[{"type": "text", "text": "(stopped by user)"}], is_error=1)
		agent.finish_conversation()
		agent.emit("stopped")
	except (providers.ProviderError, config.AccessDenied) as e:
		frappe.db.rollback()
		message = cstr(e) or _("The assistant could not answer.")
		agent.save_message("assistant", content=message, is_error=1)
		agent.finish_conversation()
		agent.emit("error", message=message)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Fateh AI run failed", message=frappe.get_traceback(with_context=True))
		message = _("Something went wrong while answering. The error was logged for your administrator.")
		agent.save_message("assistant", content=message, is_error=1)
		agent.finish_conversation()
		agent.emit("error", message=message)
	finally:
		frappe.cache.delete_value(run_key(conversation))
		frappe.cache.delete_value(stop_key(run_id))
