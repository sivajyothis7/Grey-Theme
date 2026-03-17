import frappe

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)

    
    blank_row = {
        "customer": "",
        "invoice_amount": None,
        "paid_amount": None,
        "outstanding_amount": None
    }
    data.append(blank_row)

   
    if data:
        total_row = {
            "customer": "Total",
            "invoice_amount": sum(d.get("invoice_amount") or 0 for d in data if d.get("customer")),
            "paid_amount": sum(d.get("paid_amount") or 0 for d in data if d.get("customer")),
            "outstanding_amount": sum(d.get("outstanding_amount") or 0 for d in data if d.get("customer")),
        }
        data.append(total_row)

    
    return columns, data, None, None, None, True


def get_columns():
    return [
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 200},
        {"label": "Invoiced Amount", "fieldname": "invoice_amount", "fieldtype": "Currency", "width": 150},
        {"label": "Paid Amount", "fieldname": "paid_amount", "fieldtype": "Currency", "width": 150},
        {"label": "Outstanding Amount", "fieldname": "outstanding_amount", "fieldtype": "Currency", "width": 150},
    ]


def get_data(filters):
    warehouse_filter = ""
    if filters.get("warehouse"):
        warehouse_filter = " AND sii.warehouse = %(warehouse)s"

    return frappe.db.sql(f"""
        SELECT
            si.customer,
            SUM(sii.amount) AS invoice_amount,
            SUM(sii.amount) - SUM(sii.amount * si.outstanding_amount / si.grand_total) AS paid_amount,
            SUM(sii.amount * si.outstanding_amount / si.grand_total) AS outstanding_amount
        FROM `tabSales Invoice` si
        INNER JOIN `tabSales Invoice Item` sii ON si.name = sii.parent
        WHERE si.docstatus = 1
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
            {warehouse_filter}
        GROUP BY si.customer
        ORDER BY si.customer
    """, filters, as_dict=1)