# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

SETTINGS_DOCTYPE = "AI Settings"

# Provider presets. "kind" picks the adapter in providers.py.
PROVIDERS = {
	"Groq": {
		"kind": "openai",
		"base_url": "https://api.groq.com/openai/v1",
		"default_model": "openai/gpt-oss-120b",
	},
	"OpenAI": {"kind": "openai", "base_url": "https://api.openai.com/v1", "default_model": None},
	"Anthropic": {
		"kind": "anthropic",
		"base_url": "https://api.anthropic.com/v1",
		"default_model": "claude-sonnet-5-5",
	},
	"Google Gemini": {
		"kind": "openai",
		"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
		"default_model": None,
	},
	"DeepSeek": {"kind": "openai", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
	"OpenRouter": {"kind": "openai", "base_url": "https://openrouter.ai/api/v1", "default_model": None},
	"Ollama": {
		"kind": "openai",
		"base_url": "http://localhost:11434/v1",
		"default_model": None,
		"key_optional": True,
	},
	"Custom (OpenAI-compatible)": {"kind": "openai", "base_url": None, "default_model": None, "key_optional": True},
}

# (default, minimum, maximum)
NUMERIC_BOUNDS = {
	"daily_message_limit": (100, 0, 100000),
	"max_output_tokens": (4096, 256, 64000),
	"max_iterations": (8, 1, 25),
	"request_timeout": (90, 10, 600),
}


class AccessDenied(frappe.PermissionError):
	pass


def get_settings(include_key: bool = True) -> frappe._dict:
	"""Resolved assistant settings, including the decrypted API key unless include_key=False.

	Never send the returned dict to the browser — it holds the key.
	"""
	doc = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	provider = doc.get("provider") or "Groq"
	preset = PROVIDERS.get(provider) or PROVIDERS["Custom (OpenAI-compatible)"]

	models = []
	primary = cstr(doc.get("model")).strip() or preset.get("default_model")
	if primary:
		models.append(primary)
	for line in cstr(doc.get("fallback_models")).splitlines():
		line = line.strip()
		if line and line not in models:
			models.append(line)

	def _num(fieldname):
		default, minimum, maximum = NUMERIC_BOUNDS[fieldname]
		value = cint(doc.get(fieldname))
		if fieldname != "daily_message_limit" and not value:
			value = default
		return max(minimum, min(maximum, value))

	temperature = doc.get("temperature")
	return frappe._dict(
		enabled=cint(doc.get("enabled")),
		assistant_name=cstr(doc.get("assistant_name")).strip() or "Fateh AI",
		show_launcher=cint(doc.get("show_launcher")),
		allowed_roles=[row.role for row in (doc.get("allowed_roles") or []) if row.role],
		daily_message_limit=_num("daily_message_limit"),
		provider=provider,
		kind=preset["kind"],
		base_url=(cstr(doc.get("base_url")).strip() or preset.get("base_url") or "").rstrip("/"),
		api_key=(doc.get_password("api_key", raise_exception=False) or "") if include_key else "",
		key_optional=bool(preset.get("key_optional")),
		models=models,
		temperature=flt(temperature) if temperature is not None else 0.2,
		max_output_tokens=_num("max_output_tokens"),
		max_iterations=_num("max_iterations"),
		request_timeout=_num("request_timeout"),
		extra_instructions=cstr(doc.get("extra_instructions")).strip(),
		enable_sql_tool=cint(doc.get("enable_sql_tool")),
	)


def get_access(user: str | None = None, settings: frappe._dict | None = None) -> tuple[bool, str]:
	"""Whether `user` may use the assistant, and why not."""
	user = user or frappe.session.user
	if user == "Guest":
		return False, _("Please log in.")

	if frappe.db.get_value("User", user, "user_type") != "System User":
		return False, _("The assistant is available to desk users only.")

	settings = settings or get_settings()
	if not settings.enabled:
		return False, _("%(name)s is not enabled. A System Manager can turn it on in AI Settings.") % {
			"name": settings.assistant_name
		}

	if settings.allowed_roles and user != "Administrator":
		if not set(settings.allowed_roles) & set(frappe.get_roles(user)):
			return False, _("Your role is not allowed to use %(name)s.") % {"name": settings.assistant_name}

	return True, ""


def check_access(user: str | None = None, settings: frappe._dict | None = None) -> frappe._dict:
	settings = settings or get_settings()
	ok, reason = get_access(user, settings)
	if not ok:
		raise AccessDenied(reason)
	return settings


def is_configured(settings: frappe._dict) -> bool:
	return bool(settings.models and settings.base_url and (settings.api_key or settings.key_optional))
