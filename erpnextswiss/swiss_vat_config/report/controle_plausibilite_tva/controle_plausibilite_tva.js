// Copyright (c) 2026, IAtive and contributors
/* eslint-disable */

frappe.query_reports["Controle plausibilite TVA"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1,
            "default": frappe.defaults.get_default("Company")
        },
        {
            "fieldname": "from_date",
            "label": __("From date"),
            "fieldtype": "Date",
            "reqd": 1,
            "default": frappe.datetime.year_start()
        },
        {
            "fieldname": "to_date",
            "label": __("To date"),
            "fieldtype": "Date",
            "reqd": 1,
            "default": frappe.datetime.get_today()
        }
    ],
    // colorer la colonne Statut
    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "status" && data && data.status) {
            if (data.status.indexOf("Anomalie") !== -1) {
                value = `<span style="color:#c0392b;font-weight:600">${value}</span>`;
            } else if (data.status.indexOf("vérifier") !== -1) {
                value = `<span style="color:#b8860b;font-weight:600">${value}</span>`;
            } else if (data.status.indexOf("OK") !== -1) {
                value = `<span style="color:#1e8449">${value}</span>`;
            }
        }
        return value;
    }
};
