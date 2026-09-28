# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr

SETTINGS_DOCTYPE = "Grey Theme UI Settings"

# fieldname: (default, minimum, maximum, label)
NUMERIC_BOUNDS = {
	# 11 is Frappe's own built-in column budget, so anything lower is meaningless.
	"grid_column_limit": (60, 11, 200, "Column Budget Per Row"),
	"grid_min_column_width": (100, 60, 400, "Minimum Column Width (px)"),
	"grid_max_sticky_columns": (3, 1, 6, "Maximum Sticky Columns"),
	"split_view_list_width_pct": (50, 20, 80, "Default List Pane Width (%)"),
	"split_view_min_pane_width": (280, 200, 800, "Minimum Pane Width (px)"),
}


class GreyThemeUISettings(Document):
	def validate(self):
		for fieldname, (default, minimum, maximum, label) in NUMERIC_BOUNDS.items():
			value = cint(self.get(fieldname))

			# a blank/zeroed field is not a user choice — fall back to the shipped default
			if not value:
				value = default

			if value < minimum or value > maximum:
				frappe.throw(
					_("%(label)s must be between %(min)s and %(max)s.")
					% {"label": _(label), "min": minimum, "max": maximum},
					title=_("Invalid Value"),
				)

			# write the coerced value back so the stored Single is always sane
			self.set(fieldname, value)

		self.enable_grid_enhancer = cint(self.enable_grid_enhancer)
		self.enable_split_view = cint(self.enable_split_view)
		self.grid_sticky_columns = cint(self.grid_sticky_columns)
		self.split_view_hide_page_from_search = cint(self.split_view_hide_page_from_search)

	def on_update(self):
		# bootinfo is cached per user in v15 (frappe.cache.hget("bootinfo", user) —
		# frappe/sessions.py:140), so without this the new settings never reach the browser.
		#
		# Drop only that hash, not the whole cache: bare frappe.clear_cache() deletes EVERY
		# Redis key for the site (frappe/__init__.py:1002-1006), evicting every app's caches
		# on each save of this Single. "bootinfo" is the same key frappe's own
		# cache_manager.clear_user_cache() clears (cache_manager.py:50, :94).
		frappe.cache.delete_key("bootinfo")


def parse_excluded_doctypes(value) -> list:
	"""Split the Small Text on newlines, strip each line, drop the blanks."""
	return [line.strip() for line in cstr(value).splitlines() if line.strip()]


def get_disabled_ui_settings() -> dict:
	"""Full boot payload with both features off — the safe fallback shape."""
	return {
		"grid_enhancer": 0,
		"grid_column_limit": NUMERIC_BOUNDS["grid_column_limit"][0],
		"grid_min_column_width": NUMERIC_BOUNDS["grid_min_column_width"][0],
		"grid_sticky_columns": 0,
		"grid_max_sticky_columns": NUMERIC_BOUNDS["grid_max_sticky_columns"][0],
		"split_view": 0,
		"split_view_list_width_pct": NUMERIC_BOUNDS["split_view_list_width_pct"][0],
		"split_view_min_pane_width": NUMERIC_BOUNDS["split_view_min_pane_width"][0],
		"split_view_hide_page_from_search": 1,
		"split_view_excluded_doctypes": [],
	}


def get_ui_settings() -> dict:
	"""Boot payload published as frappe.boot.grey_theme_ui. This must never raise."""
	try:
		# boot can run mid-migrate on an existing site, before this DocType is synced
		if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
			return get_disabled_ui_settings()

		doc = frappe.get_cached_doc(SETTINGS_DOCTYPE)

		def bounded(fieldname):
			default, minimum, maximum, _label = NUMERIC_BOUNDS[fieldname]
			value = cint(doc.get(fieldname)) or default
			return max(minimum, min(maximum, value))

		return {
			"grid_enhancer": cint(doc.enable_grid_enhancer),
			"grid_column_limit": bounded("grid_column_limit"),
			"grid_min_column_width": bounded("grid_min_column_width"),
			"grid_sticky_columns": cint(doc.grid_sticky_columns),
			"grid_max_sticky_columns": bounded("grid_max_sticky_columns"),
			"split_view": cint(doc.enable_split_view),
			"split_view_list_width_pct": bounded("split_view_list_width_pct"),
			"split_view_min_pane_width": bounded("split_view_min_pane_width"),
			"split_view_hide_page_from_search": cint(doc.split_view_hide_page_from_search),
			"split_view_excluded_doctypes": parse_excluded_doctypes(
				doc.split_view_excluded_doctypes
			),
		}
	except Exception:
		try:
			frappe.log_error(
				title="Grey Theme UI Settings boot failed",
				message=frappe.get_traceback(with_context=True),
				defer_insert=True,
			)
		except Exception:
			pass

		return get_disabled_ui_settings()
