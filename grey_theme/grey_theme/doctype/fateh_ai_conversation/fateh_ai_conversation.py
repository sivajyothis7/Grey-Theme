# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FatehAIConversation(Document):
	def on_trash(self):
		# Messages belong to the conversation and go with it. Audit Log rows are
		# deliberately kept: deleting a chat must not erase the trail of what was read.
		frappe.db.delete("Fateh AI Message", {"conversation": self.name})
