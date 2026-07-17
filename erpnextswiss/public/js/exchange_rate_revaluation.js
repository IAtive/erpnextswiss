// Exchange Rate Revaluation — bouton « Appliquer cours de clôture AFC ».
//
// Remplit `new_exchange_rate` sur toutes les lignes (par devise) avec le cours de CLÔTURE AFC
// (cours du jour BAZG à la date de la réévaluation), SANS créer de Currency Exchange : le cours
// de clôture ne vit que dans ce formulaire, donc les transactions restent au cours moyen mensuel.
// La méthode serveur (year_end_rates) est en LECTURE SEULE ; le recalcul gain/perte est celui
// d'ERPNext (déclenché par frappe.model.set_value → handler natif new_exchange_rate).
frappe.ui.form.on("Exchange Rate Revaluation", {
    refresh(frm) {
        if (frm.doc.docstatus !== 0) return;                 // seulement en brouillon (avant submit)
        if (!(frm.doc.accounts && frm.doc.accounts.length)) return;
        frm.add_custom_button(__("Appliquer cours de clôture AFC"), () => {
            const devises = [...new Set(
                (frm.doc.accounts || []).map((r) => r.account_currency).filter(Boolean)
            )];
            if (!devises.length) return;
            frappe.call({
                method: "erpnextswiss.scripts.swiss_exchange_rates.year_end_rates",
                args: { date: frm.doc.posting_date, currencies: devises },
                freeze: true,
                freeze_message: __("Récupération des cours de clôture AFC…"),
            }).then((r) => {
                const rates = r.message || {};
                let applied = 0;
                const missing = [];
                (frm.doc.accounts || []).forEach((row) => {
                    const rate = rates[row.account_currency];
                    if (rate) {
                        // set_value déclenche le handler natif → recalcul new_balance + gain/perte
                        frappe.model.set_value(row.doctype, row.name, "new_exchange_rate", rate);
                        applied += 1;
                    } else if (!missing.includes(row.account_currency)) {
                        missing.push(row.account_currency);
                    }
                });
                frm.refresh_field("accounts");
                let msg = __("Cours de clôture appliqués sur {0} ligne(s).", [applied]);
                if (missing.length) {
                    msg += " " + __("Devises sans cours : {0}.", [missing.join(", ")]);
                }
                frappe.show_alert({
                    message: msg,
                    indicator: missing.length ? "orange" : "green",
                });
            });
        }, __("Cours AFC"));
    },
});
