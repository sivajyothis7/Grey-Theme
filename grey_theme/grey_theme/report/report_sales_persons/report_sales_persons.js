// Copyright (c) 2025, siva and contributors
// For license information, please see license.txt


frappe.query_reports["Report-Sales Persons"] = {
    "filters": [
        {
            "fieldname": "job_record",
            "label": __("Job Record"),
            "fieldtype": "Link",
            "options": "Job Record",
            "reqd": 0,
            "default": "",
            "width": "80"
        },
        {
            "fieldname": "sales_person",
            "label": __("Sales Person"),
            "fieldtype": "Link",
            "options": "Sales Person",
            "width": "80"
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "width": "80"
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "width": "80"
        }
    ],

    "onload": function(report) {
        report.page.add_inner_button(__('Refresh Data'), function() {
            report.refresh();
        });
    },

    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        
        if (column.fieldname == "profit_and_loss") {
            value = data.profit_and_loss < 0
                ? `<span style="color:red">${value}</span>`
                : `<span style="color:green">${value}</span>`;
        }

        return value;
    }
};
