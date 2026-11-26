# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Fateh AI v1 entry points — retired.

v1 executed LLM-generated SQL without permission checks, wrote query results to public files
and created Customers/Items with ignore_permissions. It is replaced by grey_theme.fateh_ai
(read-only, permission-guarded tools). These shims only exist so a browser that still has the
old page cached gets a clear message instead of a 500 until it reloads.
"""

import frappe
from frappe import _


def _retired():
	return {
		"status": "error",
		"error": _("Fateh AI has been upgraded. Please reload the page (Ctrl+Shift+R)."),
	}


@frappe.whitelist()
def handle_ai_query(question=None):
	return _retired()


@frappe.whitelist()
def ask_general_ai(question=None):
	return _retired()
