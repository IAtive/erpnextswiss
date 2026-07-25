// Copyright (c) 2026, Kramdi and contributors
// For license information, please see license.txt
//
// Menu "Importer camt / ZIP" sur la liste Bank Transaction.
// Étend (n'écrase pas) le listview_settings du core ERPNext.
// L'import passe par l'endpoint Treasury (FX correct + ZIP, sans licence fintech).

(() => {
	const base = frappe.listview_settings["Bank Transaction"] || {};
	const prev_onload = base.onload;
	base.onload = function (listview) {
		if (prev_onload) prev_onload.call(this, listview);
		listview.page.add_menu_item(__("Import camt / ZIP"), () =>
			open_treasury_camt_import(() => listview.refresh())
		);
	};
	frappe.listview_settings["Bank Transaction"] = base;
})();

function open_treasury_camt_import(on_done) {
	frappe.prompt(
		[
			{
				fieldname: "bank_account",
				label: __("Fallback bank account"),
				fieldtype: "Link",
				options: "Bank Account",
				reqd: 0,
				description: __(
					"Optional: used only if the file IBAN does not match any account."
				),
			},
		],
		(values) => {
			const uploader = new frappe.ui.FileUploader({
				dialog_title: __("Import camt.053 (XML or ZIP)"),
				upload_notes: __("FX-correct import (amount in account currency + bank rate)."),
				// endpoint Treasury (lit frappe.local.uploaded_file + form_dict.docname)
				method: "erpnextswiss.treasury.overrides.upload_camt_file",
				doctype: "Bank Account",
				docname: values.bank_account || "",
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
			// rafraîchir la liste une fois le dialog fermé (après import)
			if (on_done && uploader.dialog) {
				uploader.dialog.$wrapper.on("hidden.bs.modal", () => on_done());
			}
		},
		__("Import camt / ZIP"),
		__("Continue")
	);
}
