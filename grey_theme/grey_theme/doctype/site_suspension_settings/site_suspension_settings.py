from frappe.model.document import Document

class SiteSuspensionSettings(Document):
	def before_save(self):
		"""Clear auto_suspend_date when site is activated"""
		doc_before_save = self.get_doc_before_save()

		if doc_before_save:
			was_suspended = bool(doc_before_save.get("is_suspended"))
			is_now_active = not bool(self.is_suspended)

			if was_suspended and is_now_active:
				self.auto_suspend_date = None
		else:
			if not self.is_suspended and getattr(self, "auto_suspend_date", None):
				self.auto_suspend_date = None

