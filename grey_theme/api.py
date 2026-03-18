import frappe



def validate_item_uom(doc, method):
    settings = frappe.get_single("Stock Settings")
    if not getattr(settings, "custom_enable_item_uom_validation", 0):
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



def create_custom_fields_for_selling_settings():
    field_id = "Stock Settings-custom_enable_item_uom_validation"
    if frappe.db.exists("Custom Field", field_id):
        return
    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Stock Settings",
        "fieldname": "custom_enable_item_uom_validation",
        "label": "Enable Item UOM Validation",
        "fieldtype": "Check",
        "insert_after": "allow_uom_with_conversion_rate_defined_in_item",
        "default": "0"
    })
    cf.insert(ignore_permissions=True)
    frappe.clear_cache()