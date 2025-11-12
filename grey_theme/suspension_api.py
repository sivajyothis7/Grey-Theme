import frappe
from frappe import _

def check_suspension():
	"""Check if site is suspended — only after login"""
	skip_paths = [
		"/login", "/logout", "/suspended",
		"/api/method/login", "/api/method/logout"
	]
	if frappe.request.path in skip_paths:
		return
	if frappe.request.path.startswith("/assets/"):
		return
	# Allow API to complete so Desk can boot; client JS will redirect
	if frappe.request.path.startswith("/api/"):
		return
	# Administrator always has access
	if frappe.session.user == "Administrator":
		return
	try:
		settings = frappe.get_single("Site Suspension Settings")
		if settings.is_suspended:
			request_path = frappe.request.path or ""
			if not request_path.startswith("/suspended"):
				frappe.local.response["type"] = "redirect"
				frappe.local.response["location"] = "/suspended"
				frappe.local.response["status_code"] = 302
				return
	except frappe.DoesNotExistError:
		pass

def force_redirect_after_request(response):
	"""As a safety net, force redirect HTML responses to /suspended for non-admins."""
	try:
		content_type = (response.headers.get("Content-Type") or "").lower()
		path = frappe.request.path or ""
		if "text/html" not in content_type:
			return
		if path in ["/login", "/suspended"] or path.startswith("/assets/") or path.startswith("/api/"):
			return
		if frappe.session.user == "Administrator":
			return
		settings = frappe.get_single("Site Suspension Settings")
		if settings.is_suspended:
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = "/suspended"
			frappe.local.response["status_code"] = 302
	except Exception:
		pass
	return response

def broadcast_status_change(doc, method=None):
	"""Broadcast suspension status change to all sessions."""
	try:
		is_suspended = bool(doc.is_suspended)
		reason = getattr(doc, "suspension_reason", None)
		frappe.publish_realtime(
			"site_suspension_update",
			{"is_suspended": is_suspended, "reason": reason},
			user=None
		)
	except Exception:
		pass

@frappe.whitelist()
def toggle_suspension(suspend=True, reason=None):
	"""Suspend or unsuspend the site — only Administrator"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Only Administrator can suspend or unsuspend the site"))
	settings = frappe.get_single("Site Suspension Settings")
	settings.is_suspended = int(suspend)
	if suspend and reason:
		settings.suspension_reason = reason
	settings.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"success": True,
		"message": _("Site suspended successfully") if suspend else _("Site activated successfully")
	}

@frappe.whitelist()
def is_site_suspended():
	"""Return suspension status for client-side check"""
	user = frappe.session.user
	if user == "Guest":
		return {"is_suspended": False, "user": user}
	try:
		settings = frappe.get_single("Site Suspension Settings")
		return {
			"is_suspended": bool(settings.is_suspended),
			"user": user
		}
	except frappe.DoesNotExistError:
		return {"is_suspended": False, "user": user}

@frappe.whitelist(allow_guest=True)
def get_whatsapp_number():
	"""Get WhatsApp number from settings - allow guest access for suspended page"""
	try:
		settings = frappe.get_single("Site Suspension Settings")
		whatsapp_number = getattr(settings, "whatsapp_number", "919496549065") or "919496549065"
		return {"whatsapp_number": whatsapp_number}
	except frappe.DoesNotExistError:
		return {"whatsapp_number": "919496549065"}

