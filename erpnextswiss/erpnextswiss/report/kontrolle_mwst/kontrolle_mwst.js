// Copyright (c) 2016-2023, libracore and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Kontrolle MwSt"] = {
    "filters": [
        {
            "fieldname":"from_date",
            "label": __("From date"),
            "fieldtype": "Date",
            "default": new Date().getFullYear() + "-01-01"
        },
        {
            "fieldname":"end_date",
            "label": __("End date"),
            "fieldtype": "Date",
            "default" : frappe.datetime.get_today()
        },
        {
            "fieldname":"code",
            "label": __("Code"),
            "fieldtype": "Select",
            // Fix fork : options remplies dynamiquement dans onload a partir des VAT query
            // existantes (dropdown data-driven -> inclut 205 et tout code genere, exclut les obsoletes).
            "options": "200",
            "default" : "200",
            "reqd": 1
        },
        {
            "fieldname":"company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default" : frappe.defaults.get_default("Company"),
            "reqd": 1
        }
    ],
    "onload": function(report) {
        // Construit la liste des codes AFC a partir des VAT query "viewVAT_<code>" reellement definies.
        frappe.db.get_list("VAT query", { fields: ["name"], limit: 0 }).then(function(rows) {
            var codes = (rows || [])
                .map(function(r) { return r.name.replace("viewVAT_", ""); })
                .filter(function(c) { return /^[0-9]+$/.test(c); })
                .sort(function(a, b) { return parseInt(a, 10) - parseInt(b, 10); });
            if (codes.length) {
                var f = report.get_filter("code");
                f.df.options = codes.join("\n");
                f.refresh();
            }
        });
    }
};
