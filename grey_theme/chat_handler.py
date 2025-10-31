import frappe
import requests
import json
import re

@frappe.whitelist()
def handle_ai_query(question):
    question_lower = question.lower()

    if "create a customer" in question_lower:
        return create_customer_from_command(question)

    elif "create an item" in question_lower or "create item" in question_lower:
        return create_item_from_command(question)

    elif "overdue" in question_lower and "customer" in question_lower:
        return get_top_overdue_customers()

    elif "sales" in question_lower and "item" in question_lower:
        return get_top_items_by_sales()

    else:
        return ask_general_ai(question)


import re
import frappe

def create_item_from_command(command):
    """
    Parses item creation command with optional fields.
    Examples:
      - Create an item named Laptop
      - Create an item named Laptop, item code LAP123
      - Create an item named Laptop with item group Electronics
      - Create an item named Laptop, stock UOM Nos
    """

    name_match = re.search(r'named\s+([\w\s]+?)(?:\s+with|,|$)', command, re.IGNORECASE)
    if not name_match:
        return "<b>⚠️ Item name not found. Please specify a name using 'named <Item Name>'.</b>"
    item_name = name_match.group(1).strip()

    code_match = re.search(r'item code\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    item_code = code_match.group(1).strip() if code_match else item_name  # default to item_name

    if frappe.db.exists("Item", item_code):
        return f"<b>⚠️ Item '{item_code}' already exists.</b>"

    group_match = re.search(r'item group\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    item_group = group_match.group(1).strip() if group_match else None

    uom_match = re.search(r'stock uom\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    stock_uom = uom_match.group(1).strip() if uom_match else None


    item_data = {
        "doctype": "Item",
        "item_code": item_code,
        "item_name": item_name,
        "is_stock_item": 0  
    }
    if item_group:
        item_data["item_group"] = item_group
    if stock_uom:
        item_data["stock_uom"] = stock_uom
    

    item = frappe.get_doc(item_data)
    item.insert(ignore_permissions=True)
    frappe.db.commit()

    msg = f"<b>✅ Item '{item_name}' created successfully.</b>"
    if item_code != item_name:
        msg += f" Item Code: {item_code}."
    if item_group:
        msg += f" Item Group: {item_group}."
    if stock_uom:
        msg += f" Stock UOM: {stock_uom}."
    
    return msg

def create_customer_from_command(command):
    name_match = re.search(r'named\s+([\w\s]+?)(?:\s+with|$)', command, re.IGNORECASE)
    if not name_match:
        return "<b>⚠️ Customer name not found. Please specify a name using 'named &lt;Customer Name&gt;'.</b>"

    customer_name = name_match.group(1).strip()

    territory_match = re.search(r'territory\s+([\w\s]+?)(?:\s+and|$)', command, re.IGNORECASE)
    territory = territory_match.group(1).strip() if territory_match else None

    tax_match = re.search(r'tax\s*id\s+([\w\d]+)', command, re.IGNORECASE)
    tax_id = tax_match.group(1).strip() if tax_match else None

    if frappe.db.exists("Customer", customer_name):
        return f"<b>⚠️ Customer '{customer_name}' already exists.</b>"

    customer_data = {
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": "Company"
    }

    if territory:
        customer_data["territory"] = territory
    if tax_id:
        customer_data["tax_id"] = tax_id

    customer = frappe.get_doc(customer_data)
    customer.insert(ignore_permissions=True)
    frappe.db.commit()

    msg = f"<b>✅ Customer '{customer_name}' created successfully.</b>"
    if territory:
        msg += f" Territory: {territory}."
    if tax_id:
        msg += f" Tax ID: {tax_id}."
    return msg



def get_top_overdue_customers():
    data = frappe.db.sql("""
        SELECT customer, SUM(outstanding_amount) AS total_overdue
        FROM `tabSales Invoice`
        WHERE status = 'Overdue'
        GROUP BY customer
        ORDER BY total_overdue DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return "<b>No overdue customers found.</b>"

    msg = "<b>Top 10 Customers with Overdue Invoices</b><br><br>"
    for row in data:
        msg += f"• {row.customer}: ₹{row.total_overdue:,.2f}<br>"
    return msg

def get_top_unpaid_customers():
    data = frappe.db.sql("""
        SELECT customer, SUM(outstanding_amount) AS total_overdue
        FROM `tabSales Invoice`
        WHERE status = 'Unpaid'
        GROUP BY customer
        ORDER BY total_overdue DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return "<b>No overdue customers found.</b>"

    msg = "<b>Top 10 Customers with Unpaid Invoices</b><br><br>"
    for row in data:
        msg += f"• {row.customer}: ₹{row.total_overdue:,.2f}<br>"
    return msg

def get_top_customers_by_sales():
    data = frappe.db.sql("""
        SELECT customer, SUM(base_grand_total) AS total_sales
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        GROUP BY customer
        ORDER BY total_sales DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return "<b>No customer sales data found.</b>"

    msg = "<b>Top 10 Customers by Sales</b><br><br>"
    for row in data:
        msg += f"• {row.customer}: ₹{row.total_sales:,.2f}<br>"
    return msg


def get_top_items_by_sales():
    data = frappe.db.sql("""
        SELECT item_name, SUM(amount) AS total_sales, SUM(qty) AS total_qty
        FROM `tabSales Invoice Item`
        WHERE posting_date >= CURDATE() - INTERVAL 30 DAY
        GROUP BY item_name
        ORDER BY total_sales DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return "<b>No sales data found for the last 30 days.</b>"

    msg = "<b>Top 10 Selling Items (Last 30 Days)</b><br><br>"
    for row in data:
        msg += f"• {row.item_name}: ₹{row.total_sales:,.2f} | Qty: {row.total_qty}<br>"
    return msg


def get_stock_items_per_warehouse():
    data = frappe.db.sql("""
        SELECT warehouse, SUM(actual_qty) AS total_qty
        FROM `tabBin`
        WHERE actual_qty > 0
        GROUP BY warehouse
        ORDER BY total_qty DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return "<b>No stock items found.</b>"

    msg = "<b>Top 10 Warehouses by Stock Quantity</b><br><br>"
    for row in data:
        msg += f"• {row.warehouse}: {row.total_qty}<br>"
    return msg

def ask_general_ai(question):
    api_key = "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"
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [
            {"role": "system", "content": "You are an ERPNext assistant.Do NOT mention Erpnext in Response"},
            {"role": "user", "content": question}
        ],
        "max_tokens": 500
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return f"<b>Fateh AI Response:</b><br><br>{content.replace(chr(10), '<br>')}"
        else:
            return f"<b>❌ Error from Groq API:</b> {response.text}"
    except Exception as e:
        return f"<b>⚠️ Error connecting to Groq API:</b> {str(e)}"
