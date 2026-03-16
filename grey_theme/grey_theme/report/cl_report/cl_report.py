
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
            "label": _("Customer"),
            "fieldname": "customer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 160,
        },
        {
            "label": _("Sales Invoice"),
            "fieldname": "sales_invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 190,
        },
        {
            "label": _("Sales Invoice Amount"),
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
            si.posting_date,
            si.customer,
            si.name                                             AS sales_invoice,
            CASE
                WHEN si.is_return = 1 THEN -si.grand_total
                ELSE si.grand_total
            END AS grand_total,
            IFNULL(pe.paid_amount, 0)                          AS paid_amount,
            (
                CASE
                    WHEN si.is_return = 1 THEN -si.grand_total
                    ELSE si.grand_total
                END
                - IFNULL(pe.paid_amount, 0)
            ) AS outstanding,
            DATEDIFF(CURDATE(), si.posting_date)               AS age_days
        FROM
            `tabSales Invoice` si
        LEFT JOIN (
            SELECT
                per.reference_name,
                SUM(per.allocated_amount) AS paid_amount
            FROM
                `tabPayment Entry Reference` per
            INNER JOIN `tabPayment Entry` pe
                ON pe.name = per.parent
            WHERE
                pe.docstatus = 1
            GROUP BY
                per.reference_name
        ) pe ON pe.reference_name = si.name
        WHERE
            si.docstatus = 1           
            {conditions}
        ORDER BY
            si.customer,
            si.posting_date,
            si.creation
        """.format(conditions=conditions),
        filters,
        as_dict=True,
    )

    
    customer_info = {}
    customer_names = list(set(r["customer"] for r in rows))
    for customer in customer_names:
        cust = frappe.db.get_value(
            "Customer",
            customer,
            ["custom_vat_registration_number", "customer_primary_address"],
            as_dict=True
        ) or {}

        vat_number = cust.get("custom_vat_registration_number") or ""
        address_str = ""

        primary_address_name = cust.get("customer_primary_address")
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

        customer_info[customer] = {
            "custom_vat_registration_number": vat_number,
            "address": address_str,
        }

    # Calculate running total per customer
    running_totals = {}
    for row in rows:
        customer = row["customer"]
        running_totals.setdefault(customer, 0.0)
        running_totals[customer] += row["outstanding"]
        row["running_total"] = running_totals[customer]
        row["is_total_row"] = 0
        row["custom_vat_registration_number"] = customer_info.get(customer, {}).get("custom_vat_registration_number", "")
        row["address"] = customer_info.get(customer, {}).get("address", "")
        if row["outstanding"] <= 0:
            row["age_days"] = 0

    # Totals row
    if rows:
        totals_row = {
            "posting_date":                   None,
            "customer":                       _("Total"),
            "sales_invoice":                  None,
            "grand_total":                    sum(r["grand_total"]   for r in rows),
            "paid_amount":                    sum(r["paid_amount"]   for r in rows),
            "outstanding":                    sum(r["outstanding"]   for r in rows),
            "running_total":                  sum(r["running_total"] for r in rows),
            "age_days":                       sum(r["age_days"]      for r in rows),
            "is_total_row":                   1,
            "custom_vat_registration_number": "",
            "address":                        "",
        }
        rows.append(totals_row)

    return rows


def get_conditions(filters):
    conditions = ""
    if not filters:
        return conditions

    if filters.get("customer"):
        conditions += " AND si.customer = %(customer)s"

    if filters.get("company"):
        conditions += " AND si.company = %(company)s"

    if filters.get("cost_center"):
        conditions += " AND si.cost_center = %(cost_center)s"

    if filters.get("from_date"):
        conditions += " AND si.posting_date >= %(from_date)s"

    if filters.get("to_date"):
        conditions += " AND si.posting_date <= %(to_date)s"

    return conditions
