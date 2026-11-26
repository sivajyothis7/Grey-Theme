# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Whitelisted endpoints for the Fateh AI chat UI.

Conversations and messages are an internal store: they carry no role permissions for normal
users and are only reachable through these endpoints, each of which checks that the
conversation belongs to the session user. (System Managers can audit them from the desk.)
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_datetime, now_datetime, today

from grey_theme.fateh_ai import agent, config, providers

MAX_MESSAGE_CHARS = 8000
CONVERSATION = "Fateh AI Conversation"
MESSAGE = "Fateh AI Message"


# ------------------------------------------------------------------ helpers


def _own_conversation(name):
	name = cstr(name).strip()
	owner = frappe.db.get_value(CONVERSATION, name, "user") if name else None
	if not owner:
		raise frappe.DoesNotExistError(_("Conversation not found."))
	if owner != frappe.session.user:
		raise frappe.PermissionError(_("This conversation belongs to another user."))
	return name


def _clean_context(context):
	if isinstance(context, str):
		try:
			context = json.loads(context)
		except ValueError:
			return {}
	if not isinstance(context, dict):
		return {}
	out = {}
	for key in ("view", "doctype", "docname", "title", "report"):
		if context.get(key):
			out[key] = cstr(context[key])[:200]
	if isinstance(context.get("route"), list):
		out["route"] = [cstr(p)[:80] for p in context["route"][:4]]
	if isinstance(context.get("selected"), list):
		out["selected"] = [cstr(p)[:140] for p in context["selected"][:20]]
	if context.get("filters") is not None:
		try:
			text = json.dumps(context["filters"], default=str)
			out["filters"] = json.loads(text) if len(text) <= 2000 else None
		except (TypeError, ValueError):
			pass
	return out


def _messages_today(user):
	return frappe.db.count(
		MESSAGE, {"owner": user, "role": "user", "creation": [">=", get_datetime(today())]}
	)


def _is_running(conversation):
	run_id = agent.cache_get(agent.run_key(conversation))
	return cstr(run_id) or None


# ------------------------------------------------------------------ boot / status


def get_boot_info():
	"""Small, key-free payload published at boot as frappe.boot.fateh_ai."""
	try:
		if not frappe.db.exists("DocType", config.SETTINGS_DOCTYPE):
			return {"enabled": 0}
		settings = config.get_settings(include_key=False)
		allowed, _reason = config.get_access(frappe.session.user, settings)
		return {
			"enabled": cint(settings.enabled),
			"allowed": cint(allowed),
			"launcher": cint(settings.show_launcher and allowed),
			"name": settings.assistant_name,
		}
	except Exception:
		return {"enabled": 0}


@frappe.whitelist()
def bootstrap():
	settings = config.get_settings()
	allowed, reason = config.get_access(frappe.session.user, settings)
	is_sm = "System Manager" in frappe.get_roles()
	return {
		"enabled": cint(settings.enabled),
		"allowed": cint(allowed),
		"reason": reason,
		"configured": cint(config.is_configured(settings)) if allowed else 0,
		"name": settings.assistant_name,
		"model": (settings.models or [None])[0] if allowed else None,
		"provider": settings.provider if allowed else None,
		"is_system_manager": cint(is_sm),
		"daily_limit": settings.daily_message_limit,
		"used_today": _messages_today(frappe.session.user) if allowed else 0,
		"user_first_name": frappe.db.get_value("User", frappe.session.user, "first_name") or "",
	}


# ------------------------------------------------------------------ chat


@frappe.whitelist(methods=["POST"])
def send_message(message: str, conversation: str | None = None, context: str | dict | None = None):
	settings = config.check_access()
	if not config.is_configured(settings):
		frappe.throw(_("The assistant has no model or API key configured yet. Ask a System Manager to complete AI Settings."))

	message = cstr(message).strip()
	if not message:
		frappe.throw(_("Please type a question."))
	if len(message) > MAX_MESSAGE_CHARS:
		frappe.throw(_("Please keep a question under %(n)s characters.") % {"n": MAX_MESSAGE_CHARS})

	user = frappe.session.user
	if settings.daily_message_limit and _messages_today(user) >= settings.daily_message_limit:
		frappe.throw(_("You have reached today's limit of %(n)s questions.") % {"n": settings.daily_message_limit})

	if conversation:
		conversation = _own_conversation(conversation)
		if _is_running(conversation):
			frappe.throw(_("Still answering the previous question. Wait for it or press Stop."))
	else:
		doc = frappe.get_doc(
			{
				"doctype": CONVERSATION,
				"user": user,
				"title": message.splitlines()[0][:80],
				"last_message_at": now_datetime(),
			}
		)
		doc.insert(ignore_permissions=True)  # internal store, owner set explicitly above
		conversation = doc.name

	run_id = frappe.generate_hash(length=12)
	frappe.get_doc(
		{"doctype": MESSAGE, "conversation": conversation, "role": "user", "run_id": run_id, "content": message}
	).insert(ignore_permissions=True)
	frappe.db.set_value(CONVERSATION, conversation, "last_message_at", now_datetime(), update_modified=False)

	frappe.cache.set_value(agent.run_key(conversation), run_id, expires_in_sec=agent.RUN_TTL)
	frappe.cache.set_value(agent.owner_key(run_id), user, expires_in_sec=agent.RUN_TTL)

	frappe.enqueue(
		"grey_theme.fateh_ai.agent.run",
		queue="default",
		timeout=900,
		enqueue_after_commit=True,
		now=bool(frappe.flags.in_test),
		conversation=conversation,
		run_id=run_id,
		context=_clean_context(context),
	)
	return {"conversation": conversation, "run_id": run_id}


@frappe.whitelist(methods=["POST"])
def stop(run_id: str):
	run_id = cstr(run_id).strip()
	owner = agent.cache_get(agent.owner_key(run_id))
	if not owner:
		return {"stopped": 0}
	if owner != frappe.session.user:
		raise frappe.PermissionError(_("Not your request."))
	frappe.cache.set_value(agent.stop_key(run_id), 1, expires_in_sec=agent.RUN_TTL)
	return {"stopped": 1}


@frappe.whitelist()
def get_run_status(conversation: str):
	conversation = _own_conversation(conversation)
	return {"running": _is_running(conversation)}


# ------------------------------------------------------------------ history


@frappe.whitelist()
def list_conversations(search: str | None = None, limit=60, start=0):
	config.check_access()
	user = frappe.session.user
	limit = max(1, min(200, cint(limit) or 60))
	start = max(0, cint(start))
	search = cstr(search).strip()

	filters = {"user": user}
	if search:
		conv = frappe.qb.DocType(CONVERSATION)
		msg = frappe.qb.DocType(MESSAGE)
		matched = (
			frappe.qb.from_(msg)
			.join(conv)
			.on(conv.name == msg.conversation)
			.select(msg.conversation)
			.distinct()
			.where((conv.user == user) & (msg.role != "tool") & (msg.content.like(f"%{search}%")))
			.limit(200)
		).run(pluck=True)
		titled = frappe.get_all(CONVERSATION, filters={"user": user, "title": ["like", f"%{search}%"]}, pluck="name", limit=200)
		names = list(dict.fromkeys(titled + matched))
		if not names:
			return []
		filters["name"] = ["in", names]

	return frappe.get_all(
		CONVERSATION,
		filters=filters,
		fields=["name", "title", "pinned", "last_message_at", "message_count"],
		order_by="pinned desc, last_message_at desc",
		start=start,
		limit=limit,
	)


@frappe.whitelist()
def get_conversation(name: str):
	name = _own_conversation(name)
	conv = frappe.db.get_value(CONVERSATION, name, ["name", "title", "pinned", "model"], as_dict=True)
	rows = frappe.get_all(
		MESSAGE,
		filters={"conversation": name, "role": ["!=", "tool"]},
		fields=["name", "role", "content", "steps", "is_error", "run_id", "creation", "model"],
		order_by="creation asc",
		limit=500,
	)
	for row in rows:
		try:
			row["steps"] = json.loads(row.steps) if row.steps else []
		except ValueError:
			row["steps"] = []
	conv["messages"] = rows
	conv["running"] = _is_running(name)
	return conv


@frappe.whitelist(methods=["POST"])
def rename_conversation(name: str, title: str):
	name = _own_conversation(name)
	title = cstr(title).strip()[:140]
	if not title:
		frappe.throw(_("Title cannot be empty."))
	frappe.db.set_value(CONVERSATION, name, "title", title, update_modified=False)
	return {"name": name, "title": title}


@frappe.whitelist(methods=["POST"])
def pin_conversation(name: str, pinned=1):
	name = _own_conversation(name)
	frappe.db.set_value(CONVERSATION, name, "pinned", 1 if cint(pinned) else 0, update_modified=False)
	return {"name": name, "pinned": 1 if cint(pinned) else 0}


@frappe.whitelist(methods=["POST"])
def delete_conversation(name: str):
	name = _own_conversation(name)
	if _is_running(name):
		frappe.throw(_("Stop the running answer before deleting this conversation."))
	frappe.delete_doc(CONVERSATION, name, ignore_permissions=True)  # owner verified above
	return {"deleted": name}


# ------------------------------------------------------------------ admin


@frappe.whitelist(methods=["POST"])
def test_connection():
	frappe.only_for("System Manager")
	settings = config.get_settings()
	if not config.is_configured(settings):
		frappe.throw(_("Fill in the provider, API key and model first (and save)."))
	started = time.monotonic()
	try:
		result = providers.complete(
			settings,
			system="You are a connection test. Reply with exactly: OK",
			messages=[{"role": "user", "content": [{"type": "text", "text": "Say OK"}]}],
		)
	except providers.ProviderError as e:
		return {"ok": 0, "message": cstr(e)}
	return {
		"ok": 1,
		"model": result["model"],
		"reply": result["text"][:200],
		"latency_ms": int((time.monotonic() - started) * 1000),
	}


@frappe.whitelist()
def list_models():
	frappe.only_for("System Manager")
	settings = config.get_settings()
	if not settings.base_url:
		frappe.throw(_("Set a Base URL for this provider first."))
	try:
		return {"models": providers.list_models(settings)}
	except providers.ProviderError as e:
		frappe.throw(cstr(e))
