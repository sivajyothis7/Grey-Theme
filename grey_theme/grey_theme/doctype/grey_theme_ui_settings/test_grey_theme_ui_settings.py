# Copyright (c) 2026, Enfono Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from grey_theme.grey_theme.doctype.grey_theme_ui_settings.grey_theme_ui_settings import (
	SETTINGS_DOCTYPE,
	get_ui_settings,
	parse_excluded_doctypes,
)

DEFAULTS = {
	"enable_grid_enhancer": 0,
	"enable_split_view": 0,
	"grid_column_limit": 60,
	"grid_min_column_width": 100,
	"grid_sticky_columns": 1,
	"grid_max_sticky_columns": 3,
	"split_view_list_width_pct": 50,
	"split_view_min_pane_width": 280,
	"split_view_hide_page_from_search": 1,
	"split_view_excluded_doctypes": "",
}


class TestGreyThemeUISettings(FrappeTestCase):
	def setUp(self):
		self.reset_settings()

	def tearDown(self):
		self.reset_settings()

	def reset_settings(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.update(DEFAULTS)
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)

	def test_boot_payload_defaults_to_both_features_off(self):
		settings = get_ui_settings()

		self.assertEqual(settings["grid_enhancer"], 0)
		self.assertEqual(settings["split_view"], 0)
		# the full contract shape must always be present, even when disabled
		self.assertEqual(settings["grid_column_limit"], 60)
		self.assertEqual(settings["split_view_list_width_pct"], 50)
		self.assertEqual(settings["split_view_excluded_doctypes"], [])

	def test_column_budget_below_frappe_default_is_rejected(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.grid_column_limit = 5
		doc.flags.ignore_permissions = True

		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_column_budget_in_range_is_accepted(self):
		# use a value that differs from the default so this cannot pass by accident
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.grid_column_limit = 120
		doc.flags.ignore_permissions = True
		doc.save()

		self.assertEqual(frappe.get_single(SETTINGS_DOCTYPE).grid_column_limit, 120)

	def test_column_budget_above_maximum_is_rejected(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.grid_column_limit = 500
		doc.flags.ignore_permissions = True

		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_blank_numeric_field_falls_back_to_default(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.grid_min_column_width = 0
		doc.flags.ignore_permissions = True
		doc.save()

		self.assertEqual(doc.grid_min_column_width, 100)

	def test_excluded_doctypes_parsing(self):
		self.assertEqual(
			parse_excluded_doctypes("Sales Invoice\n\n Item "),
			["Sales Invoice", "Item"],
		)
		self.assertEqual(parse_excluded_doctypes(None), [])
		self.assertEqual(parse_excluded_doctypes("   \n  \n"), [])

	def test_excluded_doctypes_reach_the_boot_payload(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.enable_split_view = 1
		doc.split_view_excluded_doctypes = "Sales Invoice\n\n Item "
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)

		settings = get_ui_settings()
		self.assertEqual(settings["split_view"], 1)
		self.assertEqual(settings["split_view_excluded_doctypes"], ["Sales Invoice", "Item"])
