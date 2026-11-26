# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import cstr


class FatehAIEvalCase(Document):
	def validate(self):
		for field in ("expect_tools", "must_include", "must_not_include"):
			lines = [line.strip() for line in cstr(self.get(field)).splitlines() if line.strip()]
			self.set(field, "\n".join(lines) or None)
