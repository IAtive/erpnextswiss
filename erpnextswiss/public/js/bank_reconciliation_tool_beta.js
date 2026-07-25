// Copyright (c) 2026, Kramdi and contributors
// For license information, please see license.txt
//
// Bouton "Importer camt / ZIP" visible en haut de l'écran de réconciliation ALYF
// (Bank Reconciliation Tool Beta). Additif : n'altère pas le JS d'ALYF.
// L'import passe par l'endpoint Treasury (FX correct + ZIP, sans licence fintech).

frappe.ui.form.on("Bank Reconciliation Tool Beta", {
	refresh(frm) {
		// Action PRINCIPALE : "Réconcilier" toujours visible en haut à droite.
		// Relaie simplement le bouton natif d'ALYF ([data-fieldname="bt_reconcile"])
		// -> aucune logique dupliquée, on déclenche exactement le même comportement.
		frm.add_custom_button(__("Reconcile"), () => {
			const $btn = $(
				'button[data-fieldname="bt_reconcile"]:visible, [data-fieldname="bt_reconcile"] button:visible'
			).first();
			if ($btn.length) {
				$btn.click();
			} else {
				frappe.show_alert({
					message: __("Please first select a transaction and a voucher to reconcile."),
					indicator: "orange",
				});
			}
		}).addClass("btn-primary").removeClass("btn-default");

		// Bouton SECONDAIRE, séparé : import camt / ZIP (style par défaut, distinct du primaire).
		frm.add_custom_button(__("Import camt / ZIP"), () => {
			treasury_open_camt_import(frm.doc.bank_account, () => frm.refresh());
		});
	},
});

function treasury_open_camt_import(bank_account, on_done) {
	const open = (ba) => {
		const uploader = new frappe.ui.FileUploader({
			dialog_title: __("Import camt.053 (XML or ZIP)"),
			upload_notes: __("FX-correct import (amount in account currency + bank rate)."),
			method: "erpnextswiss.treasury.overrides.upload_camt_file",
			doctype: "Bank Account",
			docname: ba || "",
			allow_multiple: false,
			allow_toggle_private: false,
			allow_take_photo: false,
			allow_web_link: false,
			allow_google_drive: false,
			disable_file_browser: true,
			restrictions: {
				allowed_file_types: [".xml", ".XML", ".zip", ".ZIP"],
				max_number_of_files: 1,
			},
		});
		// rafraîchir la vue une fois le dialog fermé (après import)
		if (on_done && uploader.dialog) {
			uploader.dialog.$wrapper.on("hidden.bs.modal", () => on_done());
		}
	};
	if (bank_account) {
		open(bank_account);
	} else {
		// aucun compte sélectionné -> demander un fallback
		frappe.prompt(
			[
				{
					fieldname: "bank_account",
					label: __("Fallback bank account"),
					fieldtype: "Link",
					options: "Bank Account",
					reqd: 0,
					description: __("Optional: used if the file IBAN does not match any account."),
				},
			],
			(v) => open(v.bank_account),
			__("Import camt / ZIP"),
			__("Continue")
		);
	}
}
