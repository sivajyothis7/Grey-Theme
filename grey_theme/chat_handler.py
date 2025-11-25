import frappe
import requests
import json
import re
import uuid
from frappe.utils.xlsxutils import make_xlsx
from frappe.utils import get_url

@frappe.whitelist()
def handle_ai_query(question):
    question_lower = (question or "").lower()

    if "create a customer" in question_lower:
        return create_customer_from_command(question)

    elif "create an item" in question_lower or "create item" in question_lower:
        return create_item_from_command(question)

    elif "overdue" in question_lower and "customer" in question_lower:
        return get_top_overdue_customers()

    elif "unpaid" in question_lower and "invoice" in question_lower:
        return get_top_unpaid_customers()

    elif "top customers" in question_lower and "sales" in question_lower:
        return get_top_customers_by_sales()

    elif "top selling items" in question_lower or ("top" in question_lower and "items" in question_lower):
        return get_top_items_by_sales()

    elif "stock items" in question_lower or "warehouse" in question_lower:
        return get_stock_items_per_warehouse()

    else:
        return ask_general_ai(question)



def create_item_from_command(command):
    name_match = re.search(r'named\s+([\w\s]+?)(?:\s+with|,|$)', command, re.IGNORECASE)
    if not name_match:
        return "⚠️ Item name not found. Please specify a name using 'named <Item Name>'."
    item_name = name_match.group(1).strip()
    code_match = re.search(r'item code\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    item_code = code_match.group(1).strip() if code_match else item_name
    if frappe.db.exists("Item", item_code):
        return f"⚠️ Item '{item_code}' already exists."
    group_match = re.search(r'item group\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    item_group = group_match.group(1).strip() if group_match else None
    uom_match = re.search(r'stock uom\s+([\w\s]+?)(?:,|\s+and|$)', command, re.IGNORECASE)
    stock_uom = uom_match.group(1).strip() if uom_match else None

    item_data = {"doctype": "Item", "item_code": item_code, "item_name": item_name, "is_stock_item": 0}
    if item_group: item_data["item_group"] = item_group
    if stock_uom: item_data["stock_uom"] = stock_uom

    item = frappe.get_doc(item_data)
    item.insert(ignore_permissions=True)
    frappe.db.commit()

    msg = f"✅ Item '{item_name}' created successfully."
    if item_code != item_name: msg += f" Item Code: {item_code}."
    if item_group: msg += f" Item Group: {item_group}."
    if stock_uom: msg += f" Stock UOM: {stock_uom}."
    return msg

def create_customer_from_command(command):
    name_match = re.search(r'named\s+([\w\s]+?)(?:\s+with|$)', command, re.IGNORECASE)
    if not name_match:
        return "<b>⚠️ Customer name not found.</b>"
    customer_name = name_match.group(1).strip()
    territory_match = re.search(r'territory\s+([\w\s]+?)(?:\s+and|$)', command, re.IGNORECASE)
    territory = territory_match.group(1).strip() if territory_match else None
    tax_match = re.search(r'tax\s*id\s+([\w\d]+)', command, re.IGNORECASE)
    tax_id = tax_match.group(1).strip() if tax_match else None
    if frappe.db.exists("Customer", customer_name):
        return f"⚠️ Customer '{customer_name}' already exists."

    customer_data = {"doctype": "Customer", "customer_name": customer_name, "customer_type": "Company"}
    if territory: customer_data["territory"] = territory
    if tax_id: customer_data["tax_id"] = tax_id

    customer = frappe.get_doc(customer_data)
    customer.insert(ignore_permissions=True)
    frappe.db.commit()

    msg = f"✅ Customer '{customer_name}' created successfully."
    if territory: msg += f" Territory: {territory}."
    if tax_id: msg += f" Tax ID: {tax_id}."
    return msg


def get_top_overdue_customers():
    data = frappe.db.sql("""
        SELECT customer, SUM(outstanding_amount) AS total_overdue
        FROM `tabSales Invoice`
        WHERE outstanding_amount > 0
        GROUP BY customer
        ORDER BY total_overdue DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return {"status":"empty", "message":"No overdue customers found."}

    columns = ["Customer", "Total Overdue"]
    rows = [[row.customer, float(row.total_overdue)] for row in data]
    excel_url = export_to_excel(data, filename_prefix="Top_Overdue_Customers")

    return {"status":"success", "columns":columns, "rows":rows, "excel_url": excel_url}


def get_top_unpaid_customers():
    data = frappe.db.sql("""
        SELECT customer, SUM(outstanding_amount) AS total_unpaid
        FROM `tabSales Invoice`
        WHERE outstanding_amount > 0
        GROUP BY customer
        ORDER BY total_unpaid DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return {"status":"empty", "message":"No unpaid customers found."}

    columns = ["Customer", "Total Unpaid"]
    rows = [[row.customer, float(row.total_unpaid)] for row in data]
    excel_url = export_to_excel(data, filename_prefix="Top_Unpaid_Customers")
    return {"status":"success", "columns":columns, "rows":rows, "excel_url": excel_url}


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
        return {"status":"empty", "message":"No customer sales data found."}

    columns = ["Customer", "Total Sales"]
    rows = [[row.customer, float(row.total_sales)] for row in data]
    excel_url = export_to_excel(data, filename_prefix="Top_Customers_By_Sales")
    return {"status":"success", "columns":columns, "rows":rows, "excel_url": excel_url}


def get_top_items_by_sales():
    data = frappe.db.sql("""
        SELECT sii.item_name, SUM(sii.amount) AS total_sales, SUM(sii.qty) AS total_qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
        WHERE si.posting_date >= CURDATE() - INTERVAL 30 DAY
        GROUP BY sii.item_name
        ORDER BY total_sales DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return {"status":"empty", "message":"No sales data found for the last 30 days."}

    columns = ["Item", "Total Sales", "Qty"]
    rows = [[row.item_name, float(row.total_sales), float(row.total_qty)] for row in data]
    excel_url = export_to_excel(data, filename_prefix="Top_Items_By_Sales")
    return {"status":"success", "columns":columns, "rows":rows, "excel_url": excel_url}


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
        GROUP BY warehouse
        ORDER BY total_qty DESC
        LIMIT 10
    """, as_dict=True)

    if not data:
        return {"status":"empty", "message":"No stock items found."}

    columns = ["Warehouse", "Total Qty"]
    rows = [[row.warehouse, float(row.total_qty)] for row in data]
    excel_url = export_to_excel(data, filename_prefix="Stock_Items_Per_Warehouse")
    return {"status":"success", "columns":columns, "rows":rows, "excel_url": excel_url}



def clean_sql_from_llm(text):
    block = re.findall(r"```sql\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if block:
        sql = block[0]
    else:
        m = re.search(r"(select[\s\S]*)", text, flags=re.IGNORECASE)
        sql = m.group(1) if m else text
    sql = re.sub(r"```+", "", sql)
    sql = sql.strip().rstrip(";")
    if not sql.lower().startswith("select"):
        m = re.search(r"(select[\s\S]*)", sql, flags=re.IGNORECASE)
        if m: sql = m.group(1).strip()
    return sql.strip()

def export_to_excel(data, filename_prefix="Query_Result"):
    if not data:
        return None
    columns = list(data[0].keys())
    rows = [[row.get(col) for col in columns] for row in data]
    sheet = [columns] + rows
    file_id = str(uuid.uuid4())
    filename = f"{filename_prefix}_{file_id}.xlsx"
    filepath = frappe.get_site_path("public", "files", filename)
    xlsx = make_xlsx(sheet, "Data")
    with open(filepath, "wb") as f:
        f.write(xlsx.getvalue())
    return get_url(f"/files/{filename}")



@frappe.whitelist()
def ask_general_ai(question):
    settings = frappe.get_single("AI Settings")
    api_key = (settings.groq_api_key or "").strip()
    url = "https://api.groq.com/openai/v1/chat/completions"
    model = "meta-llama/llama-4-scout-17b-16e-instruct"

    if not api_key:
        return {"status":"error","error":"Missing Groq API key."}

    prompt = f"""
You are an ERPNext SQL generator.
Convert this natural language question into a SAFE MariaDB SELECT query.

Rules:
- ONLY output SQL. No extra explanation or commentary.
- Use ONLY these ERPNext tables when applicable:
  - Customers: `tabCustomer`
  - Items: `tabItem`
  - Sales Invoice: `tabSales Invoice`
  - Sales Invoice Item: `tabSales Invoice Item`
  - Stock quantities: ALWAYS use `tabBin` (never use `tabStock Item`)
  - Warehouse: `tabWarehouse`
  - Employee: `tabEmployee`
- SELECT queries only. No DDL/DML (no INSERT/UPDATE/DELETE).
- No use of dynamic EXEC / stored procs.
- Prefer explicit columns; use LIMIT when returning many rows.

User question:
{question}
"""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages":[{"role":"user","content":prompt}], "max_tokens": 300}
    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    if resp.status_code != 200:
        return {"status":"error","error": f"LLM API Error: {resp.text}"}

    llm_sql = resp.json().get("choices",[{}])[0].get("message",{}).get("content","")
    sql = clean_sql_from_llm(llm_sql)

    try:
        data = frappe.db.sql(sql, as_dict=True)
        if not data:
            return {"status":"empty"}
        columns = list(data[0].keys())
        rows = [list(row.values()) for row in data]
        excel_url = export_to_excel(data)
        return {"status":"success","columns":columns,"rows":rows,"excel_url":excel_url}
    except Exception as e:
        return {"status":"error","error": str(e)}
