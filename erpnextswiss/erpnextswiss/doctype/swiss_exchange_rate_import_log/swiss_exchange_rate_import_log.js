// Copyright (c) 2026, IAtive and contributors
// For license information, please see license.txt

frappe.ui.form.on("Swiss Exchange Rate Import Log", {
	refresh(frm) {
		frm.add_custom_button(__("Voir les Currency Exchange"), () => {
			if (!frm.doc.value_date) {
				frappe.show_alert({ message: __("Aucune date de valeur sur ce log."), indicator: "orange" });
				return;
			}
			frappe.route_options = { date: frm.doc.value_date };
			frappe.set_route("List", "Currency Exchange");
		});
	},
});
