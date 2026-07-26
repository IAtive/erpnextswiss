// Copyright (c) 2026, Kramdi and contributors
/* eslint-disable */

frappe.query_reports["Controle de configuration"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1,
            "default": frappe.defaults.get_default("Company")
        }
    ],
    // arbre repliable par catégorie (tout replié au départ)
    "tree": true,
    "name_field": "label",
    "parent_field": "parent_id",
    "initial_depth": 0,
    // colorer le Statut + rendre la colonne « Ouvrir » cliquable
    "formatter": function (value, row, column, data, default_formatter) {
        if (column.fieldname === "link_url") {
            // lien direct vers l'enregistrement en cause (vide pour les groupes / lignes sans cible)
            return data && data.link_url
                ? `<a href="${data.link_url}">${__("Open")} ↗</a>`
                : "";
        }
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
