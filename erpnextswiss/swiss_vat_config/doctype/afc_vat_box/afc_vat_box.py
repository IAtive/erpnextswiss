# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AFCVATBox(Document):
    def validate(self):
        # « Taguable en écriture » n'est possible que sur une case que le moteur sait lire depuis une
        # écriture (source de vérité unique : vat_declaration.je_supported). Sinon on aurait un tag
        # ORPHELIN (la case apparaîtrait au menu du Journal Entry mais ne serait jamais comptée).
        if self.je_taggable:
            from erpnextswiss.swiss_vat_config.vat_declaration import je_supported
            if not je_supported(self):
                frappe.throw(_(
                    "« Taguable en écriture » n'est possible que sur une case d'IMPÔT côté ACHAT "
                    "(le moteur ne gère pas encore la voie écriture pour les cases de CA/base). "
                    "Case {0} : {1} / {2} / {3}."
                ).format(self.box_code, self.computation, self.side, self.amount_type))
