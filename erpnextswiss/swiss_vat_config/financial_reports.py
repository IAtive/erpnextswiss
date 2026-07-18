# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Compte de résultat statutaire CO 959b (par nature, étagé) — Financial Report Template natif.

Construit un « Financial Report Template » ERPNext reproduisant le format bexio / CO 959b :
paliers Résultat brut → EBIT → Résultat avant impôts → Bénéfice de l'exercice.

Mapping par CLASSE du plan comptable KMU (account_number), signes additifs via reverse_sign :
  - lignes de comptes  : Period Movement (Débits − Crédits) + reverse_sign → produits positifs,
    charges négatives ;
  - lignes de paliers  : formules additives référençant les reference_code.

Usage :
  bench --site <site> execute erpnextswiss.swiss_vat_config.financial_reports.create_co959b_template
"""
import frappe

TEMPLATE_NAME = "Compte de resultat CO 959b"

_BAL = "Period Movement (Debits - Credits)"


def _acc(ref, name, filt):
    return {"data_source": "Account Data", "reference_code": ref, "display_name": name,
            "balance_type": _BAL, "reverse_sign": 1, "calculation_formula": filt}


def _calc(ref, name, formula):
    return {"data_source": "Calculated Amount", "reference_code": ref, "display_name": name,
            "bold_text": 1, "calculation_formula": formula}


def _blank():
    return {"data_source": "Blank Line"}


# filtres par classe KMU (comptes feuilles uniquement)
def _cls(*prefixes):
    conds = [["account_number", "like", f"{p}%"] for p in prefixes]
    inner = conds[0] if len(conds) == 1 else {"or": conds}
    import json
    return json.dumps({"and": [inner, ["is_group", "=", 0]]})


ROWS = [
    _acc("PRODUITS", "Produits nets des ventes de biens et de prestations de services", _cls("3")),
    _acc("CH_MAT", "Charges de matériel, de marchandises et de prestations", _cls("4")),
    _calc("RES_BRUT", "RÉSULTAT BRUT", "PRODUITS + CH_MAT"),
    _blank(),
    _acc("CH_PERS", "Charges de personnel", _cls("5")),
    _acc("AUTRES_EXPL", "Autres charges d'exploitation", _cls("60", "61", "62", "63", "64", "65", "66")),
    _acc("AMORT", "Amortissements et corrections de valeur sur immobilisations", _cls("68")),
    _calc("EBIT", "RÉSULTAT D'EXPLOITATION (EBIT)", "RES_BRUT + CH_PERS + AUTRES_EXPL + AMORT"),
    _blank(),
    _acc("FINANCIER", "Résultat financier (charges et produits financiers)", _cls("69")),
    _acc("HORS_EXPL", "Résultat hors exploitation", _cls("80", "81")),
    _acc("EXCEPTIONNEL", "Résultat exceptionnel", _cls("85")),
    _calc("AVANT_IMPOTS", "RÉSULTAT AVANT IMPÔTS", "EBIT + FINANCIER + HORS_EXPL + EXCEPTIONNEL"),
    _blank(),
    _acc("IMPOTS", "Impôts directs", _cls("89")),
    _blank(),
    _calc("BENEFICE", "BÉNÉFICE / PERTE DE L'EXERCICE", "AVANT_IMPOTS + IMPOTS"),
]


def create_co959b_template():
    if frappe.db.exists("Financial Report Template", TEMPLATE_NAME):
        frappe.delete_doc("Financial Report Template", TEMPLATE_NAME, ignore_permissions=True, force=True)
    doc = frappe.get_doc({
        "doctype": "Financial Report Template",
        "template_name": TEMPLATE_NAME,
        "report_type": "Profit and Loss Statement",
        "rows": ROWS,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    frappe.db.commit()
    return f"Template '{TEMPLATE_NAME}' créé ({len(ROWS)} lignes)."
