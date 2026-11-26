# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class FatehAIAuditLog(Document):
	@staticmethod
	def clear_old_logs(days=90):
		"""Called by Log Settings (registered through default_log_clearing_doctypes)."""
		table = frappe.qb.DocType("Fateh AI Audit Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))
