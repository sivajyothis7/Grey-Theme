import frappe
from frappe import _
from datetime import date


def check_auto_suspend_date():
	"""Check if auto suspend date has been reached and suspend the site automatically"""
	try:
		settings = frappe.get_single("Site Suspension Settings")

		# If site is already suspended, skip
		if settings.is_suspended:
			return

		# Check if auto_suspend_date is set
		if not getattr(settings, "auto_suspend_date", None):
			return

		# Get today's date
		today = date.today()

		# Convert auto_suspend_date to date object if it's a string
		suspend_date = settings.auto_suspend_date
		if isinstance(suspend_date, str):
			from datetime import datetime
			suspend_date = datetime.strptime(suspend_date, "%Y-%m-%d").date()
		elif hasattr(suspend_date, "date"):
			suspend_date = suspend_date.date()

		# If today's date is greater than or equal to the suspend date, suspend the site
		if today >= suspend_date:
			settings.is_suspended = 1
			if not settings.suspension_reason:
				settings.suspension_reason = _("Site automatically suspended on scheduled date: {0}").format(
					settings.auto_suspend_date
				)
			settings.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.logger().info(
				f"[grey_theme] Site automatically suspended on {today} as per auto_suspend_date: {settings.auto_suspend_date}"
			)

	except frappe.DoesNotExistError:
		pass
	except Exception as e:
		frappe.logger().error(f"[grey_theme] Error in check_auto_suspend_date: {str(e)}")

