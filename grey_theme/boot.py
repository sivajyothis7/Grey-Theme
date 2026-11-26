# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe


def extend_bootinfo(bootinfo):
	"""Publish Grey Theme's desk settings at boot:

	    frappe.boot.grey_theme_ui   Grid Enhancer / Split View switches
	    frappe.boot.fateh_ai        assistant launcher switch (no secrets)

	Registered under the `extend_bootinfo` hook, which frappe/sessions.py calls as
	frappe.get_attr(hook)(bootinfo=bootinfo) — so the argument must stay named `bootinfo`.

	This must never raise: a failure here would break every desk login. Each part has its
	own try block, and every import is kept INSIDE it — `frappe.get_attr` imports this module
	to resolve the hook, so a module-level import that fails (app half-migrated, circular
	import, syntax error) would propagate out of the hook loop and 500 the desk.
	"""
	_add_ui_settings(bootinfo)
	_add_fateh_ai(bootinfo)


def _log(title):
	try:
		frappe.log_error(title=title, message=frappe.get_traceback(with_context=True), defer_insert=True)
	except Exception:
		pass


def _add_ui_settings(bootinfo):
	try:
		from grey_theme.grey_theme.doctype.grey_theme_ui_settings.grey_theme_ui_settings import (
			get_ui_settings,
		)

		bootinfo.grey_theme_ui = get_ui_settings()
		return
	except Exception:
		_log("Grey Theme extend_bootinfo failed")

	# Inline fallback: importing the controller is exactly what may have failed above,
	# so the disabled shape is spelled out here rather than fetched from it.
	bootinfo.grey_theme_ui = {
		"grid_enhancer": 0,
		"grid_column_limit": 60,
		"grid_min_column_width": 100,
		"grid_sticky_columns": 0,
		"grid_max_sticky_columns": 3,
		"split_view": 0,
		"split_view_list_width_pct": 50,
		"split_view_min_pane_width": 280,
		"split_view_hide_page_from_search": 1,
		"split_view_excluded_doctypes": [],
	}


def _add_fateh_ai(bootinfo):
	try:
		from grey_theme.fateh_ai.api import get_boot_info

		bootinfo.fateh_ai = get_boot_info()
	except Exception:
		_log("Fateh AI extend_bootinfo failed")
		bootinfo.fateh_ai = {"enabled": 0}
