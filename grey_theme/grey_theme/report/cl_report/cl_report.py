
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

    opening_row = None
    if filters and filters.get("from_date"):
        opening_row = frappe.db.sql(
            """
            SELECT
                NULL                                            AS posting_date,
                si.customer                                     AS customer,
                NULL                                            AS sales_invoice,
                IFNULL(SUM(si.grand_total), 0)                  AS grand_total,
                IFNULL(SUM(si.outstanding_amount), 0)           AS outstanding,
                IFNULL(SUM(si.grand_total - si.outstanding_amount), 0) AS paid_amount,
                NULL                                            AS age_days
            FROM
                `tabSales Invoice` si
            WHERE
                si.docstatus = 1
                AND si.customer = %(customer)s
                {company_condition}
                {cost_center_condition}
                AND si.posting_date < %(from_date)s
            """.format(
                company_condition=" AND si.company = %(company)s" if filters.get("company") else "",
                cost_center_condition=" AND si.cost_center = %(cost_center)s" if filters.get("cost_center") else "",
            ),
            filters,
            as_dict=True,
        )[0]
        opening_row["sales_invoice"] = _("Opening")
        opening_row["is_opening_row"] = 1
        opening_row["is_total_row"] = 0

    rows = frappe.db.sql(
        """
        SELECT
            si.posting_date,
            si.customer,
            si.name                                             AS sales_invoice,
            si.grand_total                                     AS grand_total,
            si.outstanding_amount                              AS outstanding,
            (si.grand_total - si.outstanding_amount)           AS paid_amount,
            DATEDIFF(CURDATE(), si.posting_date)               AS age_days
        FROM
            `tabSales Invoice` si
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
    if opening_row and opening_row.get("customer"):
        customer_names.append(opening_row["customer"])
        customer_names = list(set(customer_names))
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
    if opening_row:
        customer = opening_row["customer"]
        running_totals[customer] = float(opening_row.get("outstanding") or 0)
        opening_row["running_total"] = running_totals[customer]
        opening_row["custom_vat_registration_number"] = customer_info.get(customer, {}).get("custom_vat_registration_number", "")
        opening_row["address"] = customer_info.get(customer, {}).get("address", "")
        opening_row["age_days"] = None
        rows = [opening_row] + rows

    for row in rows:
        if row.get("is_opening_row"):
            continue
        customer = row["customer"]
        running_totals.setdefault(customer, 0.0)
        running_totals[customer] += row["outstanding"]
        row["running_total"] = running_totals[customer]
        row["is_total_row"] = 0
        row["is_opening_row"] = 0
        row["custom_vat_registration_number"] = customer_info.get(customer, {}).get("custom_vat_registration_number", "")
        row["address"] = customer_info.get(customer, {}).get("address", "")
        if row["outstanding"] <= 0:
            row["age_days"] = 0

    # Totals row
    if rows:
        last_running_total = rows[-1].get("running_total")
        totals_row = {
            "posting_date":                   None,
            "customer":                       _("Total"),
            "sales_invoice":                  None,
            "grand_total":                    sum(r["grand_total"]   for r in rows),
            "paid_amount":                    sum(r["paid_amount"]   for r in rows),
            "outstanding":                    sum(r["outstanding"]   for r in rows),
            "running_total":                  last_running_total,
            "age_days":                       None,
            "is_total_row":                   1,
            "is_opening_row":                 0,
            "custom_vat_registration_number": "",
            "address":                        "",
        }
        rows.append(totals_row)

    return rows


def get_conditions(filters):
    conditions = ""
    if not filters:
        frappe.throw(_("Customer is required to run this report."))

    if not filters.get("customer"):
        frappe.throw(_("Customer is required to run this report."))

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
