import frappe
from frappe.utils import flt, cint

@frappe.whitelist()
def get_item_warehouse_stock(item_code, company=None, limit=8):
    """Return available stock per warehouse for a given item (ERPNext v15-safe)."""
    if not item_code:
        return []

    query = """
        SELECT
            b.warehouse,
            SUM(b.actual_qty) AS actual_qty,
            SUM(b.projected_qty) AS projected_qty
        FROM `tabBin` b
        INNER JOIN `tabWarehouse` w ON b.warehouse = w.name
        WHERE b.item_code = %s
    """
    params = [item_code]

    if company:
        query += " AND w.company = %s"
        params.append(company)

    query += """
        GROUP BY b.warehouse
        ORDER BY SUM(b.projected_qty) DESC
        LIMIT %s
    """
    params.append(cint(limit))

    data = frappe.db.sql(query, tuple(params), as_dict=True)

    for d in data:
        d["actual_qty"] = flt(d.get("actual_qty") or 0)
        d["projected_qty"] = flt(d.get("projected_qty") or 0)

    return data
