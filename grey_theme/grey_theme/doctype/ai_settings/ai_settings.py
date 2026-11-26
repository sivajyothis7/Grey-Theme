# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt

from grey_theme.fateh_ai.config import NUMERIC_BOUNDS, PROVIDERS

# Plain literals matching the DocType labels so _() resolves against the extracted catalogue.
LABELS = {
	"daily_message_limit": "Daily Message Limit Per User",
	"max_output_tokens": "Max Output Tokens",
	"max_iterations": "Max Tool Steps Per Question",
	"request_timeout": "Request Timeout (s)",
}


class AISettings(Document):
	def validate(self):
		for fieldname, (default, minimum, maximum) in NUMERIC_BOUNDS.items():
			value = cint(self.get(fieldname))
			if not value and fieldname != "daily_message_limit":
				value = default
			if value < minimum or value > maximum:
				frappe.throw(
					_("%(label)s must be between %(min)s and %(max)s.")
					% {"label": _(LABELS[fieldname]), "min": minimum, "max": maximum},
					title=_("Invalid Value"),
				)
			self.set(fieldname, value)

		if self.temperature is None or self.temperature == "":
			self.temperature = 0.2
		if flt(self.temperature) < 0 or flt(self.temperature) > 2:
			frappe.throw(_("Temperature must be between 0 and 2."), title=_("Invalid Value"))

		self.provider = self.provider or "Groq"
		self.base_url = cstr(self.base_url).strip().rstrip("/") or None
		self.model = cstr(self.model).strip() or None
		if self.base_url and not self.base_url.startswith(("https://", "http://")):
			frappe.throw(_("Base URL must start with https:// or http://"), title=_("Invalid Value"))

		preset = PROVIDERS.get(self.provider) or {}
		if not self.base_url and not preset.get("base_url"):
			frappe.throw(_("Base URL is required for %(p)s.") % {"p": self.provider}, title=_("Missing Value"))
		seen = set()
		for row in self.get("report_notes") or []:
			if row.report in seen:
				frappe.throw(
					_("Report %(r)s is listed twice in the Report Guide.") % {"r": row.report}, title=_("Duplicate Report")
				)
			seen.add(row.report)
			row.keywords = ", ".join(k.strip().lower() for k in cstr(row.keywords).split(",") if k.strip()) or None

		if self.enabled and not self.model and not preset.get("default_model"):
			frappe.throw(
				_("Model is required for %(p)s. Use Fetch Models to pick one.") % {"p": self.provider},
				title=_("Missing Value"),
			)

	def on_update(self):
		# frappe.boot.fateh_ai is built from these settings and bootinfo is cached per user.
		# Drop only that hash, not the whole site cache (see grey_theme_ui_settings.py).
		frappe.cache.delete_key("bootinfo")
