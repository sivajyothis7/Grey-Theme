

import frappe





def validate_item_uom(doc, method):
    settings = frappe.get_single("Stock Settings")
    if not settings.custom_enable_item_uom_validation:
        return
    if not hasattr(doc, "items"):
        return
    for row in doc.items:
        if not row.item_code or not row.uom:
            continue
        item = frappe.get_doc("Item", row.item_code)
        allowed_uoms = [d.uom for d in item.uoms]
        if item.stock_uom:
            allowed_uoms.append(item.stock_uom)
        if row.uom not in allowed_uoms:
            frappe.throw(
                f"Row {row.idx}: Please select the UOM from the dropdown for Item {row.item_code}"
            )