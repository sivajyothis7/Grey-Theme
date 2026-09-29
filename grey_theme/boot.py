# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe


def extend_bootinfo(bootinfo):
	"""Publish the Grey Theme UI settings to the desk as frappe.boot.grey_theme_ui.

	Registered under the `extend_bootinfo` hook, which frappe/sessions.py calls as
	frappe.get_attr(hook)(bootinfo=bootinfo) — so the argument must stay named `bootinfo`.

	This must never raise: a failure here would break every desk login. The controller
	import is deliberately kept INSIDE the try block — `frappe.get_attr` imports this
	module to resolve the hook, so a module-level import that fails (app half-migrated,
	circular import, syntax error in the controller) would propagate out of the hook
	loop and 500 the desk before this function ever ran.
	"""
	try:
		from grey_theme.grey_theme.doctype.grey_theme_ui_settings.grey_theme_ui_settings import (
			get_ui_settings,
		)

		bootinfo.grey_theme_ui = get_ui_settings()
		return
	except Exception:
		try:
			frappe.log_error(
				title="Grey Theme extend_bootinfo failed",
				message=frappe.get_traceback(with_context=True),
				defer_insert=True,
			)
		except Exception:
			pass

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
