from . import __version__ as app_version
app_name = "grey_theme"
app_title = "Grey Theme"
app_publisher = "siva"
app_description = "Grey Theme"
app_email = "siva@enfono.in"
app_license = "mit"
# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/grey_theme/css/theme.css"
# app_include_js = "/assets/grey_theme/js/grey_theme.js"
app_include_js = ["/assets/grey_theme/js/suspension_check.js"]

# include js, css files in header of web template
web_include_css = [
    "/assets/grey_theme/css/login.css",
    "/assets/grey_theme/css/dv-login.css?ver=" + app_version
]
# web_include_js = "/assets/grey_theme/js/grey_theme.js"
# doctype_js = {
#     "Sales Order": "public/js/test.js"
# }
# doctype_js = {
#     "Sales Invoice": "public/js/customer_price_history.js"
# }
# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "grey_theme/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "grey_theme/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "grey_theme.utils.jinja_methods",
# 	"filters": "grey_theme.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "grey_theme.install.before_install"
# after_install = "grey_theme.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "grey_theme.uninstall.before_uninstall"
# after_uninstall = "grey_theme.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "grey_theme.utils.before_app_install"
# after_app_install = "grey_theme.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "grey_theme.utils.before_app_uninstall"
# after_app_uninstall = "grey_theme.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "grey_theme.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events
doc_events = {
	"Site Suspension Settings": {
		"on_update": "grey_theme.suspension_api.broadcast_status_change"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {"cron": {"0 5 * * *": ["grey_theme.backup_check.check_gdrive_backup"]}}

# scheduler_events = {
# 	"all": [
# 		"grey_theme.tasks.all"
# 	],
# 	"daily": [
# 		"grey_theme.tasks.daily"
# 	],
# 	"hourly": [
# 		"grey_theme.tasks.hourly"
# 	],
# 	"weekly": [
# 		"grey_theme.tasks.weekly"
# 	],
# 	"monthly": [
# 		"grey_theme.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "grey_theme.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "grey_theme.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "grey_theme.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = ["grey_theme.suspension_api.check_suspension"]
after_request = ["grey_theme.suspension_api.force_redirect_after_request"]

# Job Events
# ----------
# before_job = ["grey_theme.utils.before_job"]
# after_job = ["grey_theme.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"grey_theme.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

