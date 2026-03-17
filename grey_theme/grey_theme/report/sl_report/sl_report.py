
import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "label": _("Supplier"),
            "fieldname": "supplier",
            "fieldtype": "Link",
            "options": "Supplier",
            "width": 160,
        },
        {
            "label": _("Purchase Invoice"),
            "fieldname": "purchase_invoice",
            "fieldtype": "Link",
            "options": "Purchase Invoice",
            "width": 190,
        },
        {
            "label": _("Purchase Invoice Amount"),
            "fieldname": "grand_total",
            "fieldtype": "Currency",
            "width": 180,
        },
        {
            "label": _("Payments"),
            "fieldname": "paid_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Outstanding"),
            "fieldname": "outstanding",
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "label": _("Running Total"),
            "fieldname": "running_total",
            "fieldtype": "Currency",
            "width": 160,
        },
        {
            "label": _("Age (Days)"),
            "fieldname": "age_days",
            "fieldtype": "Int",
            "width": 110,
        },
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    rows = frappe.db.sql(
        """
        SELECT
            pi.posting_date,
            pi.supplier,
            pi.name                                             AS purchase_invoice,
            pi.grand_total                                     AS grand_total,
            pi.outstanding_amount                              AS outstanding,
            (pi.grand_total - pi.outstanding_amount)           AS paid_amount,
            DATEDIFF(CURDATE(), pi.posting_date)               AS age_days
        FROM
            `tabPurchase Invoice` pi
        WHERE
            pi.docstatus = 1           
            {conditions}
        ORDER BY
            pi.supplier,
            pi.posting_date,
            pi.creation
        """.format(conditions=conditions),
        filters,
        as_dict=True,
    )

    supplier_info = {}
    supplier_names = list(set(r["supplier"] for r in rows))
    for supplier in supplier_names:
        
        supp = frappe.db.get_value(
            "Supplier",
            supplier,
            ["tax_id", "supplier_primary_address"],
            as_dict=True
        ) or {}

        vat_number = supp.get("tax_id") or ""
        address_str = ""

        primary_address_name = supp.get("supplier_primary_address")
        if primary_address_name:
            addr = frappe.db.get_value(
                "Address",
                primary_address_name,
                ["address_line1", "address_line2", "city", "state", "pincode", "country"],
                as_dict=True
            ) or {}
            addr_parts = []
            for part in [
                addr.get("address_line1"),
                addr.get("address_line2"),
                addr.get("city"),
                addr.get("state"),
                addr.get("pincode"),
                addr.get("country"),
            ]:
                if part:
                    addr_parts.append(part)
            address_str = ", ".join(addr_parts)

        supplier_info[supplier] = {
            "tax_id": vat_number,
            "address": address_str,
        }

    # Calculate running total per supplier
    running_totals = {}
    for row in rows:
        supplier = row["supplier"]
        running_totals.setdefault(supplier, 0.0)
        running_totals[supplier] += row["outstanding"]
        row["running_total"] = running_totals[supplier]
        row["is_total_row"] = 0
        row["tax_id"] = supplier_info.get(supplier, {}).get("tax_id", "")
        row["address"] = supplier_info.get(supplier, {}).get("address", "")
        if row["outstanding"] <= 0:
            row["age_days"] = 0

    # Totals row
    if rows:
        last_running_total = rows[-1].get("running_total")
        totals_row = {
            "posting_date":                    None,
            "supplier":                        _("Total"),
            "purchase_invoice":                None,
            "grand_total":                     sum(r["grand_total"]   for r in rows),
            "paid_amount":                     sum(r["paid_amount"]   for r in rows),
            "outstanding":                     sum(r["outstanding"]   for r in rows),
            "running_total":                   last_running_total,
            "age_days":                        None,
            "is_total_row":                    1,
            "tax_id":                          "",
            "address":                         "",
        }
        rows.append(totals_row)

    return rows


def get_conditions(filters):
    conditions = ""
    if not filters:
        frappe.throw(_("Supplier is required to run this report."))

    if not filters.get("supplier"):
        frappe.throw(_("Supplier is required to run this report."))

    if filters.get("supplier"):
        conditions += " AND pi.supplier = %(supplier)s"

    if filters.get("company"):
        conditions += " AND pi.company = %(company)s"

    if filters.get("cost_center"):
        conditions += " AND pi.cost_center = %(cost_center)s"

    if filters.get("from_date"):
        conditions += " AND pi.posting_date >= %(from_date)s"

    if filters.get("to_date"):
        conditions += " AND pi.posting_date <= %(to_date)s"

    return conditions