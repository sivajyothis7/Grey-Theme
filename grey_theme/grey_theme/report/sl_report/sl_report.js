// Copyright (c) 2026, siva and contributors
// For license information, please see license.txt

frappe.query_reports["SL Report"] = {
    filters: [
        {
            fieldname: "supplier",
            label: __("Supplier"),
            fieldtype: "Link",
            options: "Supplier",
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
        },
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (data && data.is_total_row === 1) {
            value = `<span style="font-weight: bold;">${value !== null && value !== undefined ? value : ""}</span>`;
        }

        return value;
    },
};
