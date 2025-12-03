from frappe.utils import flt
import frappe

def execute(filters=None):
    columns, data, chart = [], [], None

    columns = [
        {"label": "Job Record", "fieldname": "job_record", "fieldtype": "Link", "options": "Job Record", "width": 200},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": "Sales Person", "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 150},
        {"label": "Sales Invoices", "fieldname": "sales_invoices", "fieldtype": "Data", "width": 270},
        {"label": "Total Credit", "fieldname": "total_credit", "fieldtype": "Currency", "width": 150},
        {"label": "Total Debit", "fieldname": "total_debit", "fieldtype": "Currency", "width": 150},
        {"label": "Profit & Loss", "fieldname": "profit_and_loss", "fieldtype": "Currency", "width": 150},
    ]

    job_record_filter = filters.get('job_record') if filters else None
    sales_person_filter = filters.get('sales_person') if filters else None
    from_date = filters.get('from_date') if filters else None
    to_date = filters.get('to_date') if filters else None

    user_permissions = frappe.permissions.get_user_permissions(frappe.session.user)
    user_company = user_permissions.get('Company', [None])[0]

    job_filters = {}
    if user_company:
        job_filters['company'] = user_company.doc
    if job_record_filter:
        job_filters['name'] = job_record_filter
    if sales_person_filter:
        job_filters['sales_person'] = sales_person_filter
    if from_date and to_date:
        job_filters['date'] = ['between', [from_date, to_date]]

    job_record_list = frappe.get_all(
        'Job Record',
        filters=job_filters,
        fields=['name', 'sales_person', 'job_id']
    )

    overall_credit_total = 0
    overall_debit_total = 0
    overall_profit_and_loss = 0

    invoice_data, debit_data, pnl_data, pnl_colors = [], [], [], []
    has_data = False

    for job in job_record_list:
        total_credit = 0
        total_debit = 0
        customer = job.job_id
        sales_invoices_list = []

        # ✅ SALES INVOICE
        sales_invoices = frappe.get_all(
            'Sales Invoice',
            filters={'custom_job_record': job.name, 'docstatus': 1},
            fields=['name', 'base_grand_total']
        )

        for inv in sales_invoices:
            total_credit += flt(inv.base_grand_total)
            sales_invoices_list.append(inv.name)

        # ✅ PURCHASE INVOICE
        purchase_invoices = frappe.get_all(
            'Purchase Invoice',
            filters={'custom_job_record': job.name, 'docstatus': 1},
            fields=['base_grand_total']
        )

        for inv in purchase_invoices:
            total_debit += flt(inv.base_grand_total)

        # ✅ JOURNAL ENTRY
        journal_entries = frappe.get_all(
            'Journal Entry',
            filters={'custom_job_record': job.name, 'docstatus': 1},
            fields=['name']
        )

        for je in journal_entries:
            accounts = frappe.get_all(
                'Journal Entry Account',
                filters={'parent': je.name, 'debit': ['>', 0]},
                fields=['debit']
            )
            for acc in accounts:
                total_debit += flt(acc.debit)

        if total_credit or total_debit:
            has_data = True
            pnl = total_credit - total_debit

            data.append({
                'job_record': job.name,
                'customer': customer,
                'sales_person': job.sales_person,
                'sales_invoices': ', '.join(sales_invoices_list),
                'total_credit': total_credit,
                'total_debit': total_debit,
                'profit_and_loss': pnl
            })

            overall_credit_total += total_credit
            overall_debit_total += total_debit
            overall_profit_and_loss += pnl

            invoice_data.append({'x': job.name, 'y': total_credit})
            debit_data.append({'x': job.name, 'y': total_debit})
            pnl_data.append({'x': job.name, 'y': pnl})
            pnl_colors.append('red' if pnl < 0 else 'green')

    if not has_data:
        frappe.msgprint("No data found for selected filters")
        return columns, data, None, None

    # ✅ OVERALL TOTAL
    data.append({
        'job_record': 'Overall Totals',
        'customer': '',
        'sales_person': '',
        'sales_invoices': '',
        'total_credit': overall_credit_total,
        'total_debit': overall_debit_total,
        'profit_and_loss': overall_profit_and_loss
    })

    # ✅ CHART
    chart = {
        "data": {
            "labels": [d['x'] for d in invoice_data],
            "datasets": [
                {"name": "Credit", "values": [d['y'] for d in invoice_data]},
                {"name": "Debit", "values": [d['y'] for d in debit_data]},
                {"name": "Profit / Loss", "values": [d['y'] for d in pnl_data]}
            ]
        },
        "type": "bar",
        "colors": ["#7cd6fd", "#743ee2", pnl_colors]
    }

    return columns, data, None, chart
