frappe.query_reports["CL Report"] = {
    filters: [
        {
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "Link",
            options: "Customer",
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