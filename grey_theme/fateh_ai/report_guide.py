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

import ast
import json
import os
import re
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


# --------------------------------------------------------------------------------------------
# Where a report's description comes from, first match wins:
#   1. the site's own notes   AI Settings > Report Guide (an admin can describe any report)
#   2. app hooks              hooks.py: fateh_ai_report_guide = ["my_app.ai.report_notes"], a function
#                             returning {"Report Name": {"purpose": ..., "key_filters": ..., "keywords": ...}}
#   3. the built-in GUIDE     common ERPNext / HRMS reports
#   4. the report's own code  first sentences of its Python module docstring (read with ast, never imported)
# --------------------------------------------------------------------------------------------

_DOC_CACHE = {}  # report name -> docstring summary ("" when none), per process
_HOOK_CACHE = {}


def _site_notes() -> dict:
	try:
		doc = frappe.get_cached_doc("AI Settings")
	except Exception:
		return {}
	notes = {}
	for row in doc.get("report_notes") or []:
		if row.report and row.purpose:
			notes[row.report] = {
				"purpose": cstr(row.purpose).strip(),
				"key_filters": cstr(row.key_filters).strip() or None,
				"keywords": [k.strip().lower() for k in cstr(row.keywords).split(",") if k.strip()],
			}
	return notes


def _hook_notes() -> dict:
	key = frappe.local.site
	if key in _HOOK_CACHE:
		return _HOOK_CACHE[key]
	notes = {}
	for path in frappe.get_hooks("fateh_ai_report_guide") or []:
		try:
			for name, note in (frappe.get_attr(path)() or {}).items():
				if isinstance(note, str):
					note = {"purpose": note}
				notes[name] = {
					"purpose": cstr(note.get("purpose")).strip(),
					"key_filters": note.get("key_filters"),
					"keywords": [k.strip().lower() for k in cstr(note.get("keywords")).split(",") if k.strip()],
				}
		except Exception:
			frappe.log_error(title=f"Fateh AI report guide hook {path} failed", message=frappe.get_traceback())
	_HOOK_CACHE[key] = notes
	return notes


_SEPARATOR = re.compile(r"^[\s\-─═=_*#]+$")
_SEE_ALSO = re.compile(r"\s*\(?\bsee\s+[\w/.]+\.py\)?\.?", re.I)


def summarize_docstring(name: str, doc: str) -> str:
	"""The first one or two sentences of a report's docstring, without its title or rulers."""
	lines = [line.strip() for line in cstr(doc).splitlines()]
	lines = [line for line in lines if line and not _SEPARATOR.match(line)]
	text = " ".join(lines)
	# drop a leading "Report Name —" / "Report Name:" / "Report Name" title
	for sep in (" — ", " - ", ": ", " -- ", " "):
		if text.lower().startswith(name.lower() + sep.rstrip()):
			text = text[len(name) :].lstrip(" —:;,-")
			break
	text = _SEE_ALSO.sub("", text).strip(" ;,.-")
	if len(text) < 15:  # e.g. "MIS Profit and Loss; see sf_trading/x.py." says nothing
		return ""
	sentences = re.split(r"(?<=[.!?])\s+", text)
	summary = " ".join(sentences[:2]).strip()
	return summary[:300] + ("…" if len(summary) > 300 else "")


def _docstring(report) -> str:
	if report.name in _DOC_CACHE:
		return _DOC_CACHE[report.name]
	summary = ""
	try:
		if report.is_standard == "Yes" and report.module:
			app = frappe.db.get_value("Module Def", report.module, "app_name")
			folder = frappe.scrub(report.name)
			path = frappe.get_app_path(app, frappe.scrub(report.module), "report", folder, folder + ".py")
			if os.path.exists(path):
				with open(path, encoding="utf-8") as f:
					tree = ast.parse(f.read())
				doc = ast.get_docstring(tree) or ""
				if not doc:
					fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute"), None)
					doc = ast.get_docstring(fn) if fn else ""
				summary = summarize_docstring(report.name, doc or "")
	except Exception:
		summary = ""
	_DOC_CACHE[report.name] = summary
	return summary


def note_for(report, site=None, hooks=None) -> dict:
	"""{"purpose", "key_filters", "keywords", "source"} for a report. Pass site/hooks when
	describing many reports at once so the notes are read only once."""
	site = _site_notes() if site is None else site
	hooks = _hook_notes() if hooks is None else hooks
	for source, notes in (("site", site), ("app", hooks)):
		hit = notes.get(report.name)
		if hit and hit.get("purpose"):
			return {**hit, "source": source}
	if report.name in GUIDE:
		purpose, filters = GUIDE[report.name]
		return {"purpose": purpose, "key_filters": filters, "keywords": [], "source": "guide"}
	doc = _docstring(report)
	if doc:
		return {"purpose": doc, "key_filters": None, "keywords": [], "source": "code"}
	kind = report.report_type or "Report"
	base = f" on {report.ref_doctype}" if report.ref_doctype else ""
	module = f" ({report.module})" if report.module else ""
	return {"purpose": f"{kind}{base}{module}.", "key_filters": None, "keywords": [], "source": "metadata"}


def describe(report) -> str:
	"""One line on what a report shows."""
	return note_for(report)["purpose"]


def key_filters(report) -> str | None:
	return note_for(report).get("key_filters")


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


def score(name: str, words: list[str], purpose: str = "", keywords=()) -> int:
	"""How well a report matches the user's words: name, description, keywords, synonyms."""
	if not words:
		return 1
	text = (name + " " + (purpose or GUIDE.get(name, ("", ""))[0])).lower()
	keyword_text = " ".join(keywords).lower()
	points = 0
	for word in words:
		if word in name.lower():
			points += 3
		elif word in text:
			points += 1
		if keyword_text and re.search(rf"\b{re.escape(word)}", keyword_text):
			points += 4
		if SYNONYMS.get(word) == name:
			points += 4
	return points
