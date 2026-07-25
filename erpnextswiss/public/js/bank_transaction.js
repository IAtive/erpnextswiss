// Copyright (c) 2026, Kramdi and contributors
// For license information, please see license.txt
//
// Bouton "Rapprocher au taux banque" : pour une transaction FX (multidevise)
// enrichie du taux banque, crée le Payment Entry alloué à la facture au taux
// exact de la banque -> écart de change auto en 6999, sans saisie de taux.
// Non-invasif : n'altère pas l'écran de réconciliation d'ALYF.

frappe.ui.form.on("Bank Transaction", {
	refresh(frm) {
		const doc = frm.doc;
		// seulement si soumise, non réconciliée et multidevise (taux banque présent)
		if (doc.docstatus !== 1) return;
		if (doc.status === "Reconciled" || flt(doc.unallocated_amount) <= 0) return;
		if (!doc.bank_exchange_rate) return;

		frm.add_custom_button(
			__("Reconcile at bank rate"),
			() => open_bank_rate_dialog(frm),
			__("Actions")
		);
	},
});

function open_bank_rate_dialog(frm) {
	const is_pay = flt(frm.doc.withdrawal) > 0;
	const default_type = is_pay ? "Purchase Invoice" : "Sales Invoice";

	const d = new frappe.ui.Dialog({
		title: __("Reconcile at bank rate"),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<div class="text-muted small">${__("Account amount")}: <b>${
					frm.doc.currency
				} ${flt(frm.doc.withdrawal || frm.doc.deposit)}</b> · ${__("Original")}: <b>${
					frm.doc.original_amount || ""
				} ${frm.doc.original_currency || ""}</b> · ${__("Bank rate")}: <b>${
					frm.doc.bank_exchange_rate
				}</b></div>`,
			},
			{
				fieldname: "voucher_type",
				label: __("Voucher type"),
				fieldtype: "Select",
				options: "Purchase Invoice\nSales Invoice",
				default: default_type,
				reqd: 1,
			},
			{
				fieldname: "voucher",
				label: __("Invoice"),
				fieldtype: "Dynamic Link",
				options: "voucher_type",
				reqd: 1,
				get_query: () => ({ filters: { docstatus: 1, outstanding_amount: [">", 0] } }),
			},
		],
		primary_action_label: __("Reconcile"),
		primary_action(values) {
			frappe.call({
				method: "erpnextswiss.treasury.fx_reconcile.reconcile_at_bank_rate",
				args: {
					bank_transaction_name: frm.doc.name,
					voucher_type: values.voucher_type,
					voucher_name: values.voucher,
				},
				freeze: true,
				freeze_message: __("Creating payment at bank rate..."),
				callback(r) {
					if (r.message) {
						frappe.show_alert({
							message: __("Reconciled via {0}", [r.message.payment_entry]),
							indicator: "green",
						});
						d.hide();
						frm.reload_doc();
					}
				},
			});
		},
	});
	d.show();
}
