// check if HLK is active, if so, load HLK extension
try {
    frappe.call({
        "method": "erpnextswiss.erpnextswiss.domains.is_domain_active",
        "args": {
            "domain": "HLK"
        },
        "callback": function(response) {
            if (response.message === 1) {
                // load HLK
                var script = document.createElement('script');
                script.onload = function () {
                    cur_frm.refresh();
                };
                script.src = "/assets/erpnextswiss/js/hlk_scripts/sales_invoice.js";
                document.head.appendChild(script);
            }
        }
    });
} catch {
    // do nothing
}

// La référence du bulletin QR (QRR / SCOR / NON) est désormais générée CÔTÉ SERVEUR
// (erpnextswiss.swiss_qr.references.set_qr_reference, doc_event Sales Invoice.validate),
// selon la méthode configurée sur le compte de réception (Account.qr_method).
// L'ancienne génération cliente onload (RF aléatoire, non conditionnel) est retirée :
//  - elle produisait toujours un RF, même quand la méthode voulue était QRR ou NON ;
//  - elle ne pouvait pas calculer une QRR (dépend du nom, absent avant le 1er save).
frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {

    }
});
