# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Fateh AI v2: move the v1 plaintext Groq/DeepSeek key into the encrypted `api_key` field.

v1 kept keys in plain Data fields (`groq_api_key`, `deepseek_api_key`) of the AI Settings
Single. This copies the one in use into the Password field, blanks the plaintext copies, and
keeps the assistant switched on for sites that were already using it — with the new floating
launcher off, so nobody's desk changes without an administrator choosing it.

Idempotent: a site with no legacy key, or whose api_key is already set, is left alone apart
from blanking leftover plaintext.
"""

import frappe
from frappe.utils import cstr
from frappe.utils.password import get_decrypted_password, set_encrypted_password

DOCTYPE = "AI Settings"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	values = frappe.db.get_singles_dict(DOCTYPE)
	groq = cstr(values.get("groq_api_key")).strip()
	deepseek = cstr(values.get("deepseek_api_key")).strip()
	if not groq and not deepseek:
		return

	existing = get_decrypted_password(DOCTYPE, DOCTYPE, "api_key", raise_exception=False)
	updates = {"groq_api_key": None, "deepseek_api_key": None}

	if not existing:
		use_deepseek = cstr(values.get("default_provider")) == "DeepSeek" and deepseek
		provider, key = ("DeepSeek", deepseek) if (use_deepseek or not groq) else ("Groq", groq)
		set_encrypted_password(DOCTYPE, DOCTYPE, key, "api_key")
		updates.update(
			{
				"provider": provider,
				# Frappe keeps a same-length mask in the main table so the form shows the key as set
				"api_key": "*" * len(key),
				"enabled": 1,
				"show_launcher": 0,
			}
		)

	frappe.db.set_single_value(DOCTYPE, updates)
	frappe.clear_document_cache(DOCTYPE, DOCTYPE)
