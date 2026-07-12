// Copyright (c) 2026, IAtive and contributors
// For license information, please see license.txt

frappe.ui.form.on("Swiss Exchange Rate Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Lancer maintenant"), () => {
			frappe.dom.freeze(__("Récupération des cours AFC…"));
			frm.call("run_now")
				.then((r) => {
					frappe.dom.unfreeze();
					const m = r.message || {};
					frappe.msgprint({
						title: __("Import des cours AFC"),
						indicator: m.status === "Error" ? "red" : (m.status === "Partial" ? "orange" : "green"),
						message: __("Période {0} — {1} inséré(s), {2} déjà présent(s).", [
							m.period || "?", m.inserted || 0, m.skipped || 0,
						]) + (m.message ? "<br><small>" + frappe.utils.escape_html(m.message) + "</small>" : ""),
					});
					frm.reload_doc();
				})
				.catch(() => frappe.dom.unfreeze());
		}).addClass("btn-primary");

		frm.add_custom_button(__("Voir l'historique"), () => {
			frappe.set_route("List", "Swiss Exchange Rate Import Log");
		});

		frm.add_custom_button(__("Voir les Currency Exchange"), () => {
			frappe.set_route("List", "Currency Exchange");
		});
	},
});
