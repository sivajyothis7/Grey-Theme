# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""What the common reports are for, and links that open a report with its filters filled in.

Frappe's Report DocType has no description field, so the assistant could only guess a report's
purpose from its name. This guide covers the standard ERPNext / HRMS reports people ask about
most; any other report is described from its own metadata (type, DocType, module).

Links: /app/query-report/<name>?<filter>=<value> — the desk router turns the query string into
frappe.route_options and QueryReport.set_route_filters() applies it to the report's filters
(a JSON array string is parsed for multi-select filters).
"""

import json
from urllib.parse import quote, urlencode

import frappe
from frappe.utils import cstr

# report name: (what it answers, filters that matter)
GUIDE = {
	# receivables / payables
	"Accounts Receivable": ("Unpaid customer invoices with ageing buckets (0-30, 31-60 ... days) as on a date; ledger-accurate, advances and credit notes included.", "company, report_date, customer, ageing_based_on"),
	"Accounts Receivable Summary": ("One line per customer: total outstanding split into ageing buckets.", "company, report_date, customer_group"),
	"Accounts Payable": ("Unpaid supplier invoices with ageing buckets as on a date.", "company, report_date, supplier"),
	"Accounts Payable Summary": ("One line per supplier: total payable split into ageing buckets.", "company, report_date"),
	"Customer Ledger Summary": ("Per customer: opening balance, invoiced, paid, credit notes and closing balance for a period.", "company, from_date, to_date, customer"),
	"Supplier Ledger Summary": ("Per supplier: opening balance, invoiced, paid, debit notes and closing balance for a period.", "company, from_date, to_date, supplier"),
	"Payment Period Based On Invoice Date": ("How long customers/suppliers took to pay, grouped by days since invoice date.", "company, from_date, to_date, payment_type"),
	# ledgers and statements
	"General Ledger": ("Every accounting entry for an account, party or voucher with running balance — the audit trail behind any figure.", "company, from_date, to_date, account, party_type, party, group_by"),
	"Trial Balance": ("Opening, debit, credit and closing of every account for a period; checks that the books balance.", "company, fiscal_year, from_date, to_date"),
	"Balance Sheet": ("Assets, liabilities and equity at period ends.", "company, period_start_date, period_end_date, periodicity"),
	"Profit and Loss Statement": ("Income, expenses and net profit per period (month/quarter/year).", "company, period_start_date, period_end_date, periodicity, cost_center"),
	"Cash Flow": ("Cash in and out from operating, investing and financing activities.", "company, period_start_date, period_end_date, periodicity"),
	"Consolidated Financial Statement": ("Balance sheet / P&L / cash flow combined across a parent company and its subsidiaries.", "company, report, period_start_date, period_end_date"),
	"Budget Variance Report": ("Budget versus actual spend per account and cost center.", "company, from_fiscal_year, to_fiscal_year, budget_against"),
	"Bank Reconciliation Statement": ("Bank balance per books versus bank statement, with uncleared entries.", "company, account, report_date"),
	"Gross Profit": ("Profit per invoice, item, customer or sales person: selling amount minus buying (valuation) cost.", "company, from_date, to_date, group_by"),
	# sales
	"Sales Register": ("Every submitted sales invoice in a period with net, tax and grand totals.", "company, from_date, to_date, customer"),
	"Item-wise Sales Register": ("Sales invoice lines per item: qty, rate, amount and taxes.", "company, from_date, to_date, item_code, customer"),
	"Sales Analytics": ("Sales trend by customer, item, territory or group per month/quarter/year.", "company, from_date, to_date, tree_type, value_quantity, range"),
	"Item-wise Sales History": ("Items sold per customer with quantities and amounts over time.", "company, from_date, to_date, item_group"),
	"Sales Order Analysis": ("Open and completed sales orders: ordered, delivered, billed and pending quantities.", "company, from_date, to_date, status"),
	"Sales Person-wise Transaction Summary": ("Sales handled by each sales person with their contribution share.", "company, from_date, to_date, sales_person, doc_type"),
	"Territory-wise Sales": ("Quotations, orders and invoices per territory.", "company, from_date, to_date"),
	"Customer Acquisition and Loyalty": ("New versus repeat customers and their revenue per period.", "company, from_date, to_date"),
	"Inactive Customers": ("Customers with no order or invoice for a number of days.", "days_since_last_order, doctype"),
	"Delivered Items To Be Billed": ("Delivery note lines delivered but not yet invoiced.", "company"),
	"Ordered Items To Be Delivered": ("Sales order lines still to be delivered.", "company"),
	# buying
	"Purchase Register": ("Every submitted purchase invoice in a period with net, tax and grand totals.", "company, from_date, to_date, supplier"),
	"Item-wise Purchase Register": ("Purchase invoice lines per item: qty, rate, amount and taxes.", "company, from_date, to_date, item_code, supplier"),
	"Purchase Analytics": ("Purchase trend by supplier, item or group per month/quarter/year.", "company, from_date, to_date, tree_type, value_quantity, range"),
	"Purchase Order Analysis": ("Open and completed purchase orders: ordered, received, billed and pending quantities.", "company, from_date, to_date, status"),
	"Received Items To Be Billed": ("Purchase receipt lines received but not yet invoiced by the supplier.", "company"),
	"Supplier Quotation Comparison": ("Rates quoted by different suppliers for the same items side by side.", "company, from_date, to_date, item_code"),
	# stock
	"Stock Balance": ("Opening, in, out and closing quantity and value per item and warehouse for a period.", "company, from_date, to_date, warehouse, item_code, item_group"),
	"Stock Ledger": ("Every stock movement (in/out) per item and warehouse with running balance — the audit trail for stock.", "company, from_date, to_date, warehouse, item_code, voucher_no"),
	"Stock Projected Qty": ("Actual, ordered, reserved and projected quantity per item and warehouse, with reorder levels.", "company, warehouse, item_code, item_group"),
	"Stock Ageing": ("How long current stock has been sitting, in age buckets.", "company, to_date, warehouse, item_code"),
	"Warehouse wise Item Balance Age and Value": ("Stock quantity, value and age per item across warehouses.", "company, from_date, to_date, warehouse"),
	"Batch-Wise Balance History": ("Stock per batch: opening, in, out and closing quantities.", "company, from_date, to_date, item_code, batch_no"),
	"Stock Analytics": ("Stock movement trend per item or group per period.", "company, from_date, to_date, range"),
	"Itemwise Recommended Reorder Level": ("Suggested reorder level per item from past consumption.", "from_date, to_date"),
	"Stock and Account Value Comparison": ("Stock value per books versus stock ledger value, to find mismatches.", "company, account, as_on_date"),
	# HR / payroll
	"Monthly Attendance Sheet": ("Day-by-day attendance of each employee for a month.", "company, month, year, employee"),
	"Employee Leave Balance": ("Leave allocated, taken and remaining per employee and leave type.", "company, from_date, to_date, employee"),
	"Salary Register": ("Salary slips of a period with earnings, deductions and net pay per employee.", "company, from_date, to_date, docstatus"),
	"Employee Birthday": ("Employees with birthdays in a month.", "month, company"),
}

# words people use that are not in the report names
SYNONYMS = {
	"overdue": "Accounts Receivable",
	"ageing": "Accounts Receivable",
	"aging": "Accounts Receivable",
	"outstanding": "Accounts Receivable",
	"debtors": "Accounts Receivable",
	"creditors": "Accounts Payable",
	"profit": "Profit and Loss Statement",
	"margin": "Gross Profit",
	"p&l": "Profit and Loss Statement",
	"pnl": "Profit and Loss Statement",
	"ledger": "General Ledger",
	"statement": "Customer Ledger Summary",
	"inventory": "Stock Balance",
	"valuation": "Stock Balance",
	"reorder": "Stock Projected Qty",
	"slow": "Stock Ageing",
	"attendance": "Monthly Attendance Sheet",
	"leave": "Employee Leave Balance",
	"payroll": "Salary Register",
	"salary": "Salary Register",
	"unbilled": "Delivered Items To Be Billed",
	"pending": "Sales Order Analysis",
}


def describe(report) -> str:
	"""One line on what a report shows."""
	hit = GUIDE.get(report.name)
	if hit:
		return hit[0]
	kind = report.report_type or "Report"
	base = f" on {report.ref_doctype}" if report.ref_doctype else ""
	module = f" ({report.module})" if report.module else ""
	return f"{kind}{base}{module}."


def key_filters(report) -> str | None:
	hit = GUIDE.get(report.name)
	return hit[1] if hit else None


def link(report, filters=None) -> str:
	"""Desk URL that opens the report; Script/Query reports get their filters pre-filled."""
	name = report.name
	if report.report_type == "Report Builder" and report.ref_doctype:
		return f"/app/{quote(frappe.scrub(report.ref_doctype).replace('_', '-'))}/view/report/{quote(name, safe='')}"
	url = f"/app/query-report/{quote(name, safe='')}"
	params = {}
	for key, value in (filters or {}).items():
		if value in (None, "", []) or not isinstance(key, str):
			continue
		if isinstance(value, bool):
			value = int(value)
		params[key] = json.dumps(value) if isinstance(value, (list, dict)) else cstr(value)
	return url + ("?" + urlencode(params, quote_via=quote) if params else "")


def score(name: str, words: list[str]) -> int:
	"""How well a report matches the user's words (name and guide text)."""
	if not words:
		return 1
	text = (name + " " + (GUIDE.get(name, ("", ""))[0])).lower()
	points = 0
	for word in words:
		if word in name.lower():
			points += 3
		elif word in text:
			points += 1
		if SYNONYMS.get(word) == name:
			points += 4
	return points
