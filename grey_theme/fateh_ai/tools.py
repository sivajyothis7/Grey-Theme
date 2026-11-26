# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Read-only ERP tools the model may call.

Security rules (see docs/fateh-ai-v2-design.md §3):
- every tool runs as the asking user — never `ignore_permissions`, never `frappe.get_all` on
  business data: rows come from `frappe.get_list` (roles + User Permissions + permission query
  conditions), documents from `frappe.get_doc` + `has_permission` + field-level read filtering;
- nothing here writes business data;
- blocked doctypes and secret-looking fields are refused regardless of role;
- the model never writes SQL fragments: fields, filters, groupings and orderings are passed as
  structure and validated against DocType meta before they reach `get_list`.
"""

import json
import re
import time

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, nowdate, strip_html

MAX_ROWS = 200
DEFAULT_ROWS = 20
MAX_RESULT_CHARS = 16000
PREVIEW_ROWS = 50

BLOCKED_DOCTYPES = {
	"AI Settings",
	"Access Log",
	"Activity Log",
	"Connected App",
	"Deleted Document",
	"Email Account",
	"Email Queue",
	"Error Log",
	"Fateh AI Audit Log",
	"Fateh AI Conversation",
	"Fateh AI Message",
	"Has Role",
	"Integration Request",
	"LDAP Settings",
	"Module Profile",
	"OAuth Authorization Code",
	"OAuth Bearer Token",
	"OAuth Client",
	"Personal Data Download Request",
	"Role",
	"Role Profile",
	"Server Script",
	"Social Login Key",
	"System Settings",
	"Token Cache",
	"User",
	"User Permission",
	"User Social Login",
	"Version",
	"Webhook",
}

BLOCKED_FIELD_RE = re.compile(r"(passw|secret|api_?key|token|private_?key|otp|encryption)", re.I)
STANDARD_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")
LAYOUT_TYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Fold",
	"Heading",
	"Image",
	"Table",
	"Table MultiSelect",
	"Password",
	"Attach Image",
	"Signature",
}
NUMERIC_TYPES = {"Currency", "Float", "Int", "Percent", "Duration"}
DATE_TYPES = {"Date", "Datetime"}
OPERATORS = {
	"=",
	"!=",
	">",
	"<",
	">=",
	"<=",
	"like",
	"not like",
	"in",
	"not in",
	"between",
	"is",
}
PERIODS = ("day", "week", "month", "quarter", "year")
FIELDNAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class ToolError(Exception):
	"""A problem the model should read and recover from (bad field, missing filter...)."""


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

_REGISTRY = {}


def tool(name, description, properties, required=(), label=None, system_manager_only=False, setting=None):
	def decorator(fn):
		_REGISTRY[name] = frappe._dict(
			name=name,
			description=description,
			schema={"type": "object", "properties": properties, "required": list(required)},
			handler=fn,
			label=label or name.replace("_", " ").capitalize(),
			system_manager_only=system_manager_only,
			setting=setting,
		)
		return fn

	return decorator


def get_tools(settings, user=None):
	"""Tool definitions available to `user`, in the canonical (Anthropic) shape."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	out = []
	for t in _REGISTRY.values():
		if t.system_manager_only and "System Manager" not in roles:
			continue
		if t.setting and not settings.get(t.setting):
			continue
		out.append({"name": t.name, "description": t.description, "input_schema": t.schema})
	return out


def tool_label(name, args=None):
	t = _REGISTRY.get(name)
	if not t:
		return name
	doctype = (args or {}).get("doctype") or (args or {}).get("report_name")
	return f"{_(t.label)}: {doctype}" if doctype else _(t.label)


def execute(name, args, settings, user=None):
	"""Run one tool. Returns a dict:

	    status       "Success" | "Error" | "Denied"
	    content      JSON string handed back to the model
	    preview      {"columns": [...], "rows": [[...]], "total": n} for the UI, or None
	    row_count    rows returned
	    reference    (doctype, name) when the tool read one document
	    error        message when status != Success
	"""
	user = user or frappe.session.user
	started = time.monotonic()
	t = _REGISTRY.get(name)
	result = frappe._dict(status="Success", content="", preview=None, row_count=0, reference=None, error=None)

	try:
		if not t or name not in {d["name"] for d in get_tools(settings, user)}:
			raise frappe.PermissionError(_("Tool %(name)s is not available to you.") % {"name": name})
		if not isinstance(args, dict):
			raise ToolError(_("Tool arguments must be a JSON object."))
		if "__invalid_json__" in args:
			raise ToolError(_("Your tool arguments were not valid JSON. Send a JSON object."))
		missing = [p for p in t.schema["required"] if args.get(p) in (None, "", [])]
		if missing:
			raise ToolError(_("Missing required argument(s): %(m)s") % {"m": ", ".join(missing)})

		data = t.handler(**_known_args(t, args))
		result.row_count = cint(data.pop("_row_count", 0)) if isinstance(data, dict) else 0
		result.preview = data.pop("_preview", None) if isinstance(data, dict) else None
		result.reference = data.pop("_reference", None) if isinstance(data, dict) else None
		result.content = _to_model_json(data)
	except frappe.PermissionError as e:
		result.status = "Denied"
		result.error = _clean_message(e) or _("You do not have permission for this.")
	except (ToolError, frappe.ValidationError, frappe.DoesNotExistError) as e:
		result.status = "Error"
		result.error = _clean_message(e)
	except Exception as e:
		result.status = "Error"
		result.error = _clean_message(e) or e.__class__.__name__
		frappe.log_error(title=f"Fateh AI tool {name} failed", message=frappe.get_traceback(with_context=True))
	finally:
		frappe.clear_messages()

	if result.status != "Success":
		result.content = json.dumps({"error": result.error, "status": result.status})
	result.duration_ms = int((time.monotonic() - started) * 1000)
	return result


def _known_args(t, args):
	allowed = set(t.schema["properties"])
	return {k: v for k, v in args.items() if k in allowed}


def _clean_message(e):
	msg = cstr(e) or cstr(getattr(e, "message", ""))
	if not msg and frappe.local.message_log:
		try:
			msg = json.loads(frappe.local.message_log[-1]).get("message")
		except Exception:
			msg = cstr(frappe.local.message_log[-1])
	return strip_html(cstr(msg)).strip()[:600]


def _to_model_json(data):
	text = json.dumps(data, default=_json_default, ensure_ascii=False)
	if len(text) <= MAX_RESULT_CHARS:
		return text
	# trim the biggest list until the payload fits, and tell the model
	rows_key = next((k for k in ("rows", "data", "results", "items") if isinstance(data.get(k), list)), None)
	if rows_key:
		rows = data[rows_key]
		while rows and len(text) > MAX_RESULT_CHARS:
			rows = rows[: max(1, int(len(rows) * 0.7))] if len(rows) > 1 else []
			data[rows_key] = rows
			data["truncated"] = _("Only the first %(n)s rows fit; narrow the filters for the rest.") % {"n": len(rows)}
			text = json.dumps(data, default=_json_default, ensure_ascii=False)
	return text[:MAX_RESULT_CHARS]


def _json_default(value):
	if hasattr(value, "isoformat"):
		return value.isoformat()
	try:
		return float(value)
	except Exception:
		return cstr(value)


def _compact(value, limit=400):
	if value is None:
		return None
	if isinstance(value, float):
		return round(value, 4)
	if isinstance(value, (int, bool)):
		return value
	if hasattr(value, "isoformat"):
		return value.isoformat()
	if not isinstance(value, str):
		try:
			return round(float(value), 4)
		except Exception:
			value = cstr(value)
	if "<" in value and ">" in value:
		value = strip_html(value)
	return value if len(value) <= limit else value[:limit] + "…"


def _preview(rows, columns=None, total=None):
	if not rows:
		return {"columns": columns or [], "rows": [], "total": total or 0}
	columns = columns or list(rows[0].keys())
	return {
		"columns": columns,
		"rows": [[_compact(r.get(c), 120) for c in columns] for r in rows[:PREVIEW_ROWS]],
		"total": total if total is not None else len(rows),
	}


# --------------------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------------------


def resolve_doctype(name, ptype="read", allow_child=False):
	"""Canonical DocType name the user may `ptype`, or raise."""
	name = cstr(name).strip().strip("`")
	if name.startswith("tab") and frappe.db.exists("DocType", name[3:]):
		name = name[3:]
	if not name:
		raise ToolError(_("doctype is required."))

	canonical = frappe.db.get_value("DocType", name, "name")
	if not canonical:
		raise ToolError(
			_("DocType %(name)s does not exist. Use find_doctype to look up the right name.") % {"name": name}
		)
	if canonical in BLOCKED_DOCTYPES or canonical.startswith("__"):
		raise frappe.PermissionError(_("%(dt)s cannot be read by the assistant.") % {"dt": canonical})

	meta = frappe.get_meta(canonical)
	if meta.istable and not allow_child:
		parents = frappe.get_all(
			"DocField", filters={"options": canonical, "fieldtype": ["in", ["Table", "Table MultiSelect"]]},
			pluck="parent", limit=3,
		)
		raise ToolError(
			_("%(dt)s is a child table. Query its parent (%(parents)s) and use child fields as 'ChildDocType.fieldname'.")
			% {"dt": canonical, "parents": ", ".join(parents) or "?"}
		)
	if not meta.istable and not frappe.has_permission(canonical, ptype):
		raise frappe.PermissionError(_("You do not have permission to read %(dt)s.") % {"dt": canonical})
	return canonical


def _permitted_fieldnames(doctype, parenttype=None):
	try:
		from frappe.model import get_permitted_fields

		fields = set(get_permitted_fields(doctype, parenttype=parenttype, permission_type="read"))
	except Exception:
		fields = set(frappe.get_meta(doctype).get_valid_columns())
	fields.update(STANDARD_FIELDS)
	return {f for f in fields if not BLOCKED_FIELD_RE.search(f)}


def _child_tables(meta):
	"""{child doctype: table fieldname} and {table fieldname: child doctype}."""
	by_doctype, by_field = {}, {}
	for df in meta.get_table_fields():
		by_doctype.setdefault(df.options, df.fieldname)
		by_field[df.fieldname] = df.options
	return by_doctype, by_field


class FieldRef(frappe._dict):
	"""A validated column: sql expression, alias, label, fieldtype, owning doctype."""


def resolve_field(doctype, spec, allow_child=True):
	"""Validate 'fieldname', 'Child DocType.fieldname' or 'table_fieldname.fieldname'."""
	spec = cstr(spec).strip().strip("`")
	if not spec:
		raise ToolError(_("Empty field name."))

	meta = frappe.get_meta(doctype)
	owner = doctype
	fieldname = spec
	if "." in spec:
		if not allow_child:
			raise ToolError(_("Child-table fields are not allowed here: %(f)s") % {"f": spec})
		head, fieldname = spec.rsplit(".", 1)
		head = head.strip("`").removeprefix("tab")
		by_doctype, by_field = _child_tables(meta)
		if head in by_field:
			owner = by_field[head]
		elif head in by_doctype:
			owner = head
		elif head == doctype:
			owner = doctype
		else:
			raise ToolError(
				_("%(head)s is not a child table of %(dt)s. Child tables: %(tables)s")
				% {"head": head, "dt": doctype, "tables": ", ".join(sorted(by_doctype)) or "none"}
			)

	if not FIELDNAME_RE.match(fieldname):
		raise ToolError(_("Invalid field name: %(f)s") % {"f": spec})
	if BLOCKED_FIELD_RE.search(fieldname):
		raise frappe.PermissionError(_("Field %(f)s cannot be read by the assistant.") % {"f": spec})

	owner_meta = frappe.get_meta(owner)
	df = owner_meta.get_field(fieldname)
	if fieldname not in STANDARD_FIELDS and fieldname != "parent":
		if not df or df.fieldtype in LAYOUT_TYPES:
			raise ToolError(
				_("%(dt)s has no field %(f)s. Use describe_doctype to see the fields.") % {"dt": owner, "f": fieldname}
			)
	permitted = _permitted_fieldnames(owner, parenttype=doctype if owner != doctype else None)
	if fieldname not in permitted and fieldname != "parent":
		raise frappe.PermissionError(_("You cannot read %(dt)s.%(f)s.") % {"dt": owner, "f": fieldname})

	alias = fieldname if owner == doctype else f"{frappe.scrub(owner)}__{fieldname}"
	return FieldRef(
		expr=f"`tab{owner}`.`{fieldname}`",
		alias=alias,
		fieldname=fieldname,
		doctype=owner,
		label=(df.label if df else fieldname.replace("_", " ").title()),
		fieldtype=(df.fieldtype if df else ("Datetime" if fieldname in ("creation", "modified") else "Data")),
		is_child=owner != doctype,
	)


def normalize_filters(doctype, filters):
	"""Accept {field: value}, {field: [op, value]}, [[field, op, value], ...] or
	[[ChildDocType, field, op, value], ...]; validate every field and operator."""
	if not filters:
		return []
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except ValueError:
			raise ToolError(_("filters must be a JSON object or a list of [field, operator, value]."))

	items = []
	if isinstance(filters, dict):
		for key, value in filters.items():
			if isinstance(value, (list, tuple)) and len(value) == 2 and cstr(value[0]).lower() in OPERATORS:
				items.append([key, value[0], value[1]])
			else:
				items.append([key, "=", value])
	elif isinstance(filters, list):
		for f in filters:
			if not isinstance(f, (list, tuple)):
				raise ToolError(_("Each filter must be a list like [field, operator, value]."))
			if len(f) == 4:
				items.append([f"{f[0]}.{f[1]}", f[2], f[3]])
			elif len(f) == 3:
				items.append(list(f))
			elif len(f) == 2:
				items.append([f[0], "=", f[1]])
			else:
				raise ToolError(_("Bad filter: %(f)s") % {"f": cstr(f)})
	else:
		raise ToolError(_("filters must be an object or a list."))

	out = []
	for field, op, value in items:
		op = cstr(op).strip().lower()
		if op == "==":
			op = "="
		if op not in OPERATORS:
			raise ToolError(_("Operator %(op)s is not supported. Use one of: %(ops)s") % {"op": op, "ops": ", ".join(sorted(OPERATORS))})
		ref = resolve_field(doctype, field)
		if op in ("in", "not in") and isinstance(value, str):
			value = [v.strip() for v in value.split(",") if v.strip()]
		if op == "between" and (not isinstance(value, (list, tuple)) or len(value) != 2):
			raise ToolError(_("between needs a two-item list [from, to]."))
		if op == "is" and cstr(value).lower() not in ("set", "not set"):
			raise ToolError(_("Operator 'is' takes 'set' or 'not set'."))
		out.append([ref.doctype, ref.fieldname, op, value])
	return out


def _order_by(doctype, order_by, aliases=None):
	if not order_by:
		return None
	parts = []
	for chunk in cstr(order_by).split(","):
		bits = chunk.strip().split()
		if not bits:
			continue
		field = bits[0]
		direction = bits[1].lower() if len(bits) > 1 else "desc"
		if direction not in ("asc", "desc"):
			raise ToolError(_("order_by direction must be asc or desc."))
		if aliases and field in aliases:
			parts.append(f"{aliases[field]} {direction}")
		else:
			parts.append(f"{resolve_field(doctype, field).expr} {direction}")
	return ", ".join(parts) or None


def _limit(value, default=DEFAULT_ROWS, maximum=MAX_ROWS):
	value = cint(value) or default
	return max(1, min(maximum, value))


def _default_list_fields(doctype):
	meta = frappe.get_meta(doctype)
	permitted = _permitted_fieldnames(doctype)
	fields = ["name"]
	for f in (meta.title_field, "status", "posting_date", "transaction_date", "company"):
		if f and f in permitted and meta.get_field(f) and f not in fields:
			fields.append(f)
	for df in meta.fields:
		if len(fields) >= 8:
			break
		if df.in_list_view and df.fieldname in permitted and df.fieldtype not in LAYOUT_TYPES and df.fieldname not in fields:
			fields.append(df.fieldname)
	return fields


# --------------------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------------------


@tool(
	"find_doctype",
	"Find ERPNext/Frappe DocTypes (record types such as 'Sales Invoice', 'Item', 'Employee') whose name "
	"matches a keyword. Use when you are not sure of the exact DocType name.",
	{"keyword": {"type": "string", "description": "Word or phrase, e.g. 'invoice', 'stock entry', 'leave'."}},
	required=("keyword",),
	label="Finding record types",
)
def find_doctype(keyword):
	keyword = cstr(keyword).strip()
	if not keyword:
		raise ToolError(_("keyword is required."))
	words = [w for w in re.split(r"\s+", keyword) if w][:4]
	candidates = frappe.get_all(
		"DocType",
		filters={"istable": 0, "name": ["like", f"%{keyword}%"]},
		fields=["name", "module", "issingle"],
		limit=40,
	)
	if not candidates and len(words) > 1:
		seen = {}
		for w in words:
			for row in frappe.get_all(
				"DocType", filters={"istable": 0, "name": ["like", f"%{w}%"]}, fields=["name", "module", "issingle"], limit=40
			):
				seen.setdefault(row.name, [row, 0])[1] += 1
		candidates = [r for r, _hits in sorted(seen.values(), key=lambda x: -x[1])][:40]

	results = []
	for row in candidates:
		if row.name in BLOCKED_DOCTYPES or not frappe.has_permission(row.name, "read"):
			continue
		results.append({"doctype": row.name, "module": row.module, "single": cint(row.issingle)})
		if len(results) >= 15:
			break
	return {"results": results, "_row_count": len(results)}


@tool(
	"describe_doctype",
	"List the fields of a DocType (fieldname, label, type, link target) and its child tables. Call this before "
	"filtering or aggregating on fields you have not seen yet.",
	{"doctype": {"type": "string"}},
	required=("doctype",),
	label="Reading the structure of",
)
def describe_doctype(doctype):
	doctype = resolve_doctype(doctype)
	meta = frappe.get_meta(doctype)

	def describe(m, parenttype=None):
		permitted = _permitted_fieldnames(m.name, parenttype=parenttype)
		out = []
		for df in m.fields:
			if df.fieldtype in LAYOUT_TYPES or df.fieldname not in permitted:
				continue
			entry = f"{df.fieldname} ({df.label or df.fieldname}) {df.fieldtype}"
			if df.fieldtype in ("Link", "Dynamic Link") and df.options:
				entry += f"→{df.options}"
			elif df.fieldtype == "Select" and df.options:
				opts = [o for o in cstr(df.options).split("\n") if o][:15]
				entry += " [" + "|".join(opts) + "]"
			if df.reqd:
				entry += " *"
			out.append(entry)
		return out

	children = []
	for df in meta.get_table_fields():
		if df.options in BLOCKED_DOCTYPES:
			continue
		children.append(
			{"table_field": df.fieldname, "doctype": df.options, "fields": describe(frappe.get_meta(df.options), doctype)[:60]}
		)

	return {
		"doctype": doctype,
		"is_submittable": cint(meta.is_submittable),
		"is_single": cint(meta.issingle),
		"title_field": meta.title_field,
		"fields": describe(meta)[:150],
		"child_tables": children,
		"note": "* = mandatory. docstatus: 0 draft, 1 submitted, 2 cancelled.",
	}


@tool(
	"search_records",
	"List records of a DocType with filters, chosen fields and ordering (respects the user's permissions). "
	"Child-table fields can be used as 'Sales Invoice Item.item_code'.",
	{
		"doctype": {"type": "string"},
		"filters": {
			"description": "Object {field: value} or {field: [operator, value]}, or list of [field, operator, value]. "
			"Operators: = != > < >= <= like 'not like' in 'not in' between is. Dates as YYYY-MM-DD.",
		},
		"fields": {"type": "array", "items": {"type": "string"}, "description": "Fieldnames to return (default: key fields)."},
		"order_by": {"type": "string", "description": "e.g. 'posting_date desc'"},
		"limit": {"type": "integer", "description": "Rows to return, default 20, max 200."},
	},
	required=("doctype",),
	label="Searching",
)
def search_records(doctype, filters=None, fields=None, order_by=None, limit=None):
	doctype = resolve_doctype(doctype)
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		raise ToolError(_("%(dt)s is a single (settings) record. Use get_record.") % {"dt": doctype})

	limit = _limit(limit)
	field_specs = fields if isinstance(fields, list) and fields else _default_list_fields(doctype)
	refs = [resolve_field(doctype, f) for f in field_specs[:30]]
	if not any(r.fieldname == "name" and not r.is_child for r in refs):
		refs.insert(0, resolve_field(doctype, "name"))

	select = [f"{r.expr} as `{r.alias}`" for r in refs]
	flt_ = normalize_filters(doctype, filters)
	rows = frappe.get_list(
		doctype,
		fields=select,
		filters=flt_,
		order_by=_order_by(doctype, order_by) or f"`tab{doctype}`.`modified` desc",
		limit_page_length=limit + 1,
	)
	more = len(rows) > limit
	rows = rows[:limit]
	total = len(rows)
	if more:
		counted = frappe.get_list(doctype, fields=[f"count(distinct `tab{doctype}`.`name`) as total"], filters=flt_)
		total = cint(counted[0].total) if counted else total

	clean = [{k: _compact(v) for k, v in r.items()} for r in rows]
	return {
		"doctype": doctype,
		"rows": clean,
		"returned": len(clean),
		"total_matching": total,
		"_row_count": len(clean),
		"_preview": _preview(clean, [r.alias for r in refs], total),
	}


@tool(
	"get_record",
	"Read one document in full (fields and child-table rows the user may see). For settings DocTypes pass the "
	"DocType name as name.",
	{
		"doctype": {"type": "string"},
		"name": {"type": "string", "description": "Document ID, e.g. ACC-SINV-2026-00012."},
		"fields": {"type": "array", "items": {"type": "string"}, "description": "Optional subset of top-level fields."},
	},
	required=("doctype", "name"),
	label="Reading",
)
def get_record(doctype, name, fields=None):
	doctype = resolve_doctype(doctype)
	meta = frappe.get_meta(doctype)
	name = doctype if meta.issingle else cstr(name).strip()
	if not meta.issingle and not frappe.db.exists(doctype, name):
		raise ToolError(_("%(dt)s %(name)s was not found. Use search_link to find the right ID.") % {"dt": doctype, "name": name})

	doc = frappe.get_doc(doctype, name)
	if not doc.has_permission("read"):
		raise frappe.PermissionError(_("You do not have permission to read %(dt)s %(name)s.") % {"dt": doctype, "name": name})
	doc.apply_fieldlevel_read_permissions()

	permitted = _permitted_fieldnames(doctype)
	wanted = set(fields) if isinstance(fields, list) and fields else None
	out = {"doctype": doctype, "name": doc.name}
	for df in meta.fields:
		if df.fieldtype in LAYOUT_TYPES or df.fieldname not in permitted:
			continue
		if wanted and df.fieldname not in wanted:
			continue
		value = doc.get(df.fieldname)
		if value in (None, "", 0) and df.fieldtype not in NUMERIC_TYPES:
			continue
		out[df.fieldname] = _compact(value, 1000)
	out["docstatus"] = doc.docstatus

	if not wanted:
		for tf in meta.get_table_fields():
			if tf.options in BLOCKED_DOCTYPES or tf.fieldname not in permitted:
				continue
			child_permitted = _permitted_fieldnames(tf.options, parenttype=doctype)
			child_meta = frappe.get_meta(tf.options)
			rows = []
			for child in (doc.get(tf.fieldname) or [])[:40]:
				row = {}
				for df in child_meta.fields:
					if df.fieldtype in LAYOUT_TYPES or df.fieldname not in child_permitted:
						continue
					value = child.get(df.fieldname)
					if value in (None, ""):
						continue
					row[df.fieldname] = _compact(value, 300)
				rows.append(row)
			if rows:
				out[tf.fieldname] = rows
				total_rows = len(doc.get(tf.fieldname) or [])
				if total_rows > 40:
					out[f"{tf.fieldname}__note"] = _("showing 40 of %(n)s rows") % {"n": total_rows}

	return {"record": out, "_row_count": 1, "_reference": (doctype, doc.name)}


@tool(
	"count_records",
	"Count records of a DocType matching filters (respects permissions).",
	{"doctype": {"type": "string"}, "filters": {"description": "Same format as search_records."}},
	required=("doctype",),
	label="Counting",
)
def count_records(doctype, filters=None):
	doctype = resolve_doctype(doctype)
	rows = frappe.get_list(
		doctype, fields=[f"count(distinct `tab{doctype}`.`name`) as total"], filters=normalize_filters(doctype, filters)
	)
	total = cint(rows[0].total) if rows else 0
	return {"doctype": doctype, "count": total, "_row_count": 1}


@tool(
	"aggregate",
	"Group and total records (respects permissions): sums, counts, averages, min/max, optionally by one or two "
	"fields and/or by time period. Use for 'top customers', 'sales by month', 'qty per warehouse'. Child-table "
	"fields allowed as 'Sales Invoice Item.item_code'.",
	{
		"doctype": {"type": "string"},
		"metrics": {
			"type": "array",
			"description": "List of {function: sum|count|avg|min|max, field: fieldname}. count needs no field.",
			"items": {"type": "object"},
		},
		"group_by": {"type": "array", "items": {"type": "string"}, "description": "Up to 2 fields."},
		"period": {
			"type": "object",
			"description": "{field: a Date field, by: day|week|month|quarter|year} to bucket by time.",
		},
		"filters": {"description": "Same format as search_records."},
		"order_by": {"type": "string", "description": "A metric alias such as 'sum_base_grand_total desc', or a group field."},
		"limit": {"type": "integer", "description": "Default 20, max 200."},
	},
	required=("doctype", "metrics"),
	label="Totalling",
)
def aggregate(doctype, metrics, group_by=None, period=None, filters=None, order_by=None, limit=None):
	doctype = resolve_doctype(doctype)
	if not isinstance(metrics, list) or not metrics:
		raise ToolError(_("metrics must be a non-empty list like [{'function': 'sum', 'field': 'base_grand_total'}]."))

	select, columns, group_exprs, aliases = [], [], [], {}
	uses_child = False

	for spec in (group_by or [])[:2]:
		ref = resolve_field(doctype, spec)
		uses_child = uses_child or ref.is_child
		select.append(f"{ref.expr} as `{ref.alias}`")
		group_exprs.append(ref.expr)
		columns.append(ref.alias)
		aliases[spec] = ref.expr
		aliases[ref.alias] = ref.expr

	if period:
		if not isinstance(period, dict):
			raise ToolError(_("period must be an object {field, by}."))
		ref = resolve_field(doctype, period.get("field") or "posting_date")
		if ref.fieldtype not in DATE_TYPES:
			raise ToolError(_("%(f)s is not a date field.") % {"f": ref.fieldname})
		by = cstr(period.get("by") or "month").lower()
		if by not in PERIODS:
			raise ToolError(_("period.by must be one of %(p)s") % {"p": ", ".join(PERIODS)})
		uses_child = uses_child or ref.is_child
		parts = {"day": ["date"], "week": ["year", "week"], "month": ["year", "month"], "quarter": ["year", "quarter"], "year": ["year"]}[by]
		for fn in parts:
			alias = f"period_{fn}"
			select.append(f"{fn}({ref.expr}) as `{alias}`")
			group_exprs.append(alias)
			columns.append(alias)
			aliases[alias] = alias

	metric_aliases = []
	for m in metrics[:6]:
		if not isinstance(m, dict):
			raise ToolError(_("Each metric must be an object {function, field}."))
		fn = cstr(m.get("function") or m.get("fn") or "").lower()
		if fn not in ("sum", "count", "avg", "min", "max"):
			raise ToolError(_("Metric function must be sum, count, avg, min or max."))
		if fn == "count" and not m.get("field"):
			alias = "count"
			select.append(f"count(distinct `tab{doctype}`.`name`) as `{alias}`")
		else:
			ref = resolve_field(doctype, m.get("field"))
			uses_child = uses_child or ref.is_child
			if fn in ("sum", "avg") and ref.fieldtype not in NUMERIC_TYPES:
				raise ToolError(_("%(f)s is %(t)s, not numeric; %(fn)s needs a number field.") % {"f": ref.fieldname, "t": ref.fieldtype, "fn": fn})
			alias = f"{fn}_{ref.alias}"
			select.append(f"{fn}({ref.expr}) as `{alias}`")
		metric_aliases.append(alias)
		columns.append(alias)
		aliases[alias] = alias

	limit = _limit(limit)
	if order_by:
		order = _order_by(doctype, order_by, aliases)
	elif group_by:
		order = f"{metric_aliases[0]} desc"
	elif period:
		order = ", ".join(a for a in columns if a.startswith("period_"))
	else:
		order = None

	kwargs = dict(fields=select, filters=normalize_filters(doctype, filters), limit_page_length=limit)
	if group_exprs:
		kwargs["group_by"] = ", ".join(group_exprs)
	if order:
		kwargs["order_by"] = order
	rows = frappe.get_list(doctype, **kwargs)
	clean = [{k: _compact(v) for k, v in r.items()} for r in rows]

	note = []
	if any("base_" in a for a in metric_aliases):
		note.append("base_* amounts are in company currency.")
	if uses_child and "count" in metric_aliases:
		note.append("count = number of distinct parent documents.")
	return {
		"doctype": doctype,
		"rows": clean,
		"returned": len(clean),
		"note": " ".join(note) or None,
		"_row_count": len(clean),
		"_preview": _preview(clean, columns),
	}


@tool(
	"search_link",
	"Fuzzy-find record IDs by name or title, e.g. a customer called 'al noor' or an item 'steel pipe 2 inch'. "
	"Returns IDs to use in filters or get_record.",
	{
		"doctype": {"type": "string", "description": "e.g. Customer, Supplier, Item, Employee, Warehouse."},
		"text": {"type": "string"},
		"limit": {"type": "integer", "description": "Default 10, max 30."},
	},
	required=("doctype", "text"),
	label="Looking up",
)
def search_link(doctype, text, limit=None):
	doctype = resolve_doctype(doctype)
	from frappe.desk.search import search_link as _search_link

	limit = _limit(limit, default=10, maximum=30)
	results = _search_link(doctype, cstr(text).strip(), page_length=limit)
	if results is None:  # older builds put the results on frappe.response
		results = frappe.response.pop("results", None) or []
	out = []
	for r in results or []:
		r = r if isinstance(r, dict) else {"value": r}
		out.append({"name": r.get("value"), "label": strip_html(cstr(r.get("label") or "")), "description": strip_html(cstr(r.get("description") or ""))[:200]})
	return {"doctype": doctype, "results": out, "_row_count": len(out)}


def _report_permitted(report_name):
	name = frappe.db.get_value("Report", {"name": cstr(report_name).strip()}, "name")
	if not name:
		raise ToolError(_("Report %(r)s does not exist. Use list_reports.") % {"r": report_name})
	report = frappe.get_cached_doc("Report", name)
	if report.disabled:
		raise ToolError(_("Report %(r)s is disabled.") % {"r": name})
	if report.ref_doctype in BLOCKED_DOCTYPES:
		raise frappe.PermissionError(_("Report %(r)s cannot be run by the assistant.") % {"r": name})
	if not report.is_permitted() or (report.ref_doctype and not frappe.has_permission(report.ref_doctype, "report")):
		raise frappe.PermissionError(_("You do not have permission to run %(r)s.") % {"r": name})
	return report


@tool(
	"list_reports",
	"Find standard/custom reports the user can run (e.g. 'Accounts Receivable', 'Stock Balance', 'General Ledger', "
	"'Gross Profit'). Prefer a report when the user asks for a ledger-accurate figure.",
	{
		"keyword": {"type": "string", "description": "Part of the report name, e.g. 'receivable', 'stock'."},
		"doctype": {"type": "string", "description": "Optional: reports based on this DocType."},
	},
	label="Finding reports",
)
def list_reports(keyword=None, doctype=None):
	filters = {"disabled": 0}
	if keyword:
		filters["name"] = ["like", f"%{cstr(keyword).strip()}%"]
	if doctype:
		filters["ref_doctype"] = cstr(doctype).strip()
	candidates = frappe.get_all(
		"Report", filters=filters, fields=["name", "ref_doctype", "report_type", "module"], order_by="name asc", limit=60
	)
	out = []
	for row in candidates:
		try:
			_report_permitted(row.name)
		except (frappe.PermissionError, ToolError):
			continue
		out.append({"report": row.name, "based_on": row.ref_doctype, "type": row.report_type, "module": row.module})
		if len(out) >= 25:
			break
	return {"reports": out, "_row_count": len(out)}


_JS_FILTER_RE = re.compile(r"fieldname\s*:\s*[\"']([A-Za-z0-9_]+)[\"']")


def _extract_js_filters(script):
	out = []
	matches = list(_JS_FILTER_RE.finditer(script or ""))
	for i, m in enumerate(matches):
		window = script[max(0, m.start() - 200) : (matches[i + 1].start() if i + 1 < len(matches) else m.end() + 600)]

		def grab(key):
			hit = re.search(rf"{key}\s*:\s*(?:__\()?\s*[\"']([^\"']+)[\"']", window)
			return hit.group(1) if hit else None

		item = {"fieldname": m.group(1), "label": grab("label"), "fieldtype": grab("fieldtype"), "options": grab("options")}
		if re.search(r"reqd\s*:\s*(1|true)", window):
			item["required"] = 1
		default = re.search(r"default\s*:\s*([^,\n]+)", window)
		if default:
			text = default.group(1).strip()
			if "Company" in text:
				item["default"] = "user's default company"
			elif "datetime" in text or "add_months" in text or "get_today" in text:
				item["default"] = "a computed date"
			elif text[:1] in "\"'":
				item["default"] = text.strip("\"'")
		out.append({k: v for k, v in item.items() if v})
	# de-duplicate by fieldname, keep first
	seen, unique = set(), []
	for item in out:
		if item["fieldname"] not in seen:
			seen.add(item["fieldname"])
			unique.append(item)
	return unique[:40]


@tool(
	"get_report_filters",
	"Show the filters a report accepts (fieldnames, which are required). Call before run_report.",
	{"report_name": {"type": "string"}},
	required=("report_name",),
	label="Checking report filters",
)
def get_report_filters(report_name):
	report = _report_permitted(report_name)
	filters = []
	if report.report_type in ("Script Report", "Query Report"):
		try:
			from frappe.desk.query_report import get_script

			script = (get_script(report.name) or {}).get("script")
			filters = _extract_js_filters(script)
		except Exception:
			filters = []
	for row in report.get("filters") or []:
		filters.append({"fieldname": row.fieldname, "label": row.label, "fieldtype": row.fieldtype, "options": row.options, "required": cint(row.mandatory)})
	return {
		"report": report.name,
		"type": report.report_type,
		"based_on": report.ref_doctype,
		"filters": filters,
		"note": "Dates as YYYY-MM-DD. Pass filters as an object {fieldname: value}.",
	}


def _normalize_columns(columns):
	out = []
	for i, col in enumerate(columns or []):
		if isinstance(col, dict):
			fieldname = col.get("fieldname") or col.get("id") or f"col_{i}"
			out.append({"field": fieldname, "label": strip_html(cstr(col.get("label") or fieldname)), "type": col.get("fieldtype") or "Data"})
		else:
			parts = cstr(col).split(":")
			label = parts[0]
			ftype = parts[1].split("/")[0] if len(parts) > 1 and parts[1] else "Data"
			out.append({"field": frappe.scrub(label) or f"col_{i}", "label": label, "type": ftype})
	return out


@tool(
	"run_report",
	"Run a report the user may access and return its rows (first 50 by default). Use get_report_filters first.",
	{
		"report_name": {"type": "string"},
		"filters": {"type": "object", "description": "{fieldname: value}. Dates as YYYY-MM-DD."},
		"limit": {"type": "integer", "description": "Rows to return, default 50, max 200."},
	},
	required=("report_name",),
	label="Running report",
)
def run_report(report_name, filters=None, limit=None):
	report = _report_permitted(report_name)
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except ValueError:
			raise ToolError(_("filters must be a JSON object."))
	filters = filters if isinstance(filters, dict) else {}

	from frappe.desk.query_report import run as run_query_report

	result = run_query_report(report_name=report.name, filters=filters, ignore_prepared_report=False) or {}
	if result.get("prepared_report"):
		raise ToolError(
			_("%(r)s is a background (prepared) report and cannot run inside the chat. Ask the user to open it from the desk.") % {"r": report.name}
		)

	columns = _normalize_columns(result.get("columns"))
	limit = _limit(limit, default=50)
	rows = []
	for raw in (result.get("result") or [])[: limit]:
		if isinstance(raw, dict):
			row = {c["field"]: _compact(raw.get(c["field"]), 200) for c in columns if raw.get(c["field"]) not in (None, "")}
		elif isinstance(raw, (list, tuple)):
			row = {c["field"]: _compact(v, 200) for c, v in zip(columns, raw) if v not in (None, "")}
		else:
			continue
		rows.append(row)

	total = len(result.get("result") or [])
	summary = [
		{"label": strip_html(cstr(s.get("label"))), "value": _compact(s.get("value"))}
		for s in (result.get("report_summary") or [])
		if isinstance(s, dict)
	]
	return {
		"report": report.name,
		"filters": filters,
		"columns": [{"field": c["field"], "label": c["label"], "type": c["type"]} for c in columns],
		"rows": rows,
		"total_rows": total,
		"summary": summary or None,
		"message": strip_html(cstr(result.get("message")))[:500] or None,
		"_row_count": len(rows),
		"_preview": _preview(rows, [c["field"] for c in columns][:12], total),
	}


@tool(
	"stock_balance",
	"Current stock (Bin) per item and warehouse: actual, reserved, ordered, projected qty and stock value. "
	"Filter by item, warehouse, item group or company.",
	{
		"item_code": {"type": "string"},
		"warehouse": {"type": "string"},
		"item_group": {"type": "string"},
		"company": {"type": "string"},
		"include_zero": {"type": "boolean", "description": "Include rows with zero qty (default false)."},
		"limit": {"type": "integer", "description": "Default 50, max 200."},
	},
	label="Checking stock",
)
def stock_balance(item_code=None, warehouse=None, item_group=None, company=None, include_zero=False, limit=None):
	resolve_doctype("Bin")
	filters = []
	if item_code:
		filters.append(["Bin", "item_code", "=", cstr(item_code).strip()])
	if warehouse:
		filters.append(["Bin", "warehouse", "=", cstr(warehouse).strip()])
	if item_group:
		items = frappe.get_list("Item", filters={"item_group": cstr(item_group).strip()}, pluck="name", limit_page_length=2000)
		if not items:
			return {"rows": [], "note": _("No items you can see in group %(g)s.") % {"g": item_group}, "_row_count": 0}
		filters.append(["Bin", "item_code", "in", items])
	if company:
		warehouses = frappe.get_list("Warehouse", filters={"company": cstr(company).strip()}, pluck="name", limit_page_length=2000)
		if not warehouses:
			return {"rows": [], "note": _("No warehouses you can see for %(c)s.") % {"c": company}, "_row_count": 0}
		filters.append(["Bin", "warehouse", "in", warehouses])
	if not include_zero:
		filters.append(["Bin", "actual_qty", "!=", 0])

	fields = ["item_code", "warehouse", "actual_qty", "reserved_qty", "ordered_qty", "projected_qty", "valuation_rate", "stock_value", "stock_uom"]
	permitted = _permitted_fieldnames("Bin")
	fields = [f for f in fields if f in permitted]
	rows = frappe.get_list("Bin", fields=fields, filters=filters, order_by="actual_qty desc", limit_page_length=_limit(limit, default=50))
	clean = [{k: _compact(v) for k, v in r.items()} for r in rows]
	totals = {}
	for key in ("actual_qty", "stock_value"):
		if key in fields:
			totals[key] = round(sum(flt(r.get(key)) for r in rows), 3)
	return {"rows": clean, "totals_of_returned_rows": totals, "_row_count": len(clean), "_preview": _preview(clean, fields)}


@tool(
	"party_outstanding",
	"Unpaid invoice balances per customer or supplier, from submitted invoices. Optional overdue-only. "
	"Invoice-based: unallocated advances/journal entries are not deducted — for ledger-accurate ageing use the "
	"'Accounts Receivable' / 'Accounts Payable' reports.",
	{
		"party_type": {"type": "string", "enum": ["Customer", "Supplier"]},
		"party": {"type": "string", "description": "Optional customer/supplier ID."},
		"company": {"type": "string"},
		"overdue_only": {"type": "boolean"},
		"limit": {"type": "integer", "description": "Default 20, max 200."},
	},
	required=("party_type",),
	label="Checking outstanding",
)
def party_outstanding(party_type, party=None, company=None, overdue_only=False, limit=None):
	if party_type not in ("Customer", "Supplier"):
		raise ToolError(_("party_type must be Customer or Supplier."))
	doctype = resolve_doctype("Sales Invoice" if party_type == "Customer" else "Purchase Invoice")
	party_field = "customer" if party_type == "Customer" else "supplier"
	filters = [[doctype, "docstatus", "=", 1], [doctype, "outstanding_amount", "!=", 0]]
	if party:
		filters.append([doctype, party_field, "=", cstr(party).strip()])
	if company:
		filters.append([doctype, "company", "=", cstr(company).strip()])
	if overdue_only:
		filters.append([doctype, "due_date", "<", nowdate()])

	currency_field = "party_account_currency" if frappe.get_meta(doctype).get_field("party_account_currency") else "currency"
	rows = frappe.get_list(
		doctype,
		fields=[
			f"`tab{doctype}`.`{party_field}` as party",
			f"`tab{doctype}`.`{currency_field}` as currency",
			f"sum(`tab{doctype}`.`outstanding_amount`) as outstanding",
			f"count(distinct `tab{doctype}`.`name`) as invoices",
			f"min(`tab{doctype}`.`due_date`) as oldest_due_date",
		],
		filters=filters,
		group_by=f"`tab{doctype}`.`{party_field}`, `tab{doctype}`.`{currency_field}`",
		order_by="outstanding desc",
		limit_page_length=_limit(limit),
	)
	clean = [{k: _compact(v) for k, v in r.items()} for r in rows]
	today = getdate(nowdate())
	for r in clean:
		if r.get("oldest_due_date"):
			r["days_overdue"] = max(0, (today - getdate(r["oldest_due_date"])).days)
	columns = ["party", "currency", "outstanding", "invoices", "oldest_due_date", "days_overdue"]
	return {"party_type": party_type, "rows": clean, "_row_count": len(clean), "_preview": _preview(clean, columns)}


_SQL_FORBIDDEN = re.compile(
	r"(\binto\b|\bload_file\b|\bsleep\s*\(|\bbenchmark\s*\(|\bfor\s+update\b|\block\s+in\s+share\b|"
	r"information_schema|performance_schema|\bmysql\s*\.|`?__\w+|\bset\s+@|\bhandler\b)",
	re.I,
)


@tool(
	"run_sql_select",
	"System Managers only: run one read-only SELECT on the database. Bypasses User Permissions — prefer the other "
	"tools. Tables are named `tabDocType`, e.g. `tabSales Invoice`.",
	{"query": {"type": "string"}, "limit": {"type": "integer", "description": "Default 100, max 500."}},
	required=("query",),
	system_manager_only=True,
	setting="enable_sql_tool",
	label="Running SQL",
)
def run_sql_select(query, limit=None):
	from frappe.utils.safe_exec import check_safe_sql_query

	query = cstr(query).strip().rstrip(";").strip()
	if ";" in query:
		raise ToolError(_("Only one statement is allowed."))
	if not check_safe_sql_query(query, throw=False):
		raise frappe.PermissionError(_("Only read-only SELECT queries are allowed."))
	if _SQL_FORBIDDEN.search(query):
		raise frappe.PermissionError(_("This query touches something the assistant may not read."))
	for blocked in BLOCKED_DOCTYPES:
		if f"tab{blocked}".lower() in query.lower():
			raise frappe.PermissionError(_("%(dt)s cannot be read by the assistant.") % {"dt": blocked})

	limit = _limit(limit, default=100, maximum=500)
	if not re.search(r"\blimit\s+\d+", query, re.I):
		query = f"{query} LIMIT {limit + 1}"
	rows = frappe.db.sql(f"SET STATEMENT max_statement_time=20 FOR {query}", as_dict=True)  # nosemgrep: validated read-only SELECT
	more = len(rows) > limit
	rows = rows[:limit]
	clean = [{k: _compact(v) for k, v in r.items()} for r in rows]
	return {
		"rows": clean,
		"returned": len(clean),
		"more_rows": bool(more),
		"warning": "Raw SQL ignores User Permissions.",
		"_row_count": len(clean),
		"_preview": _preview(clean),
	}
