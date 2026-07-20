# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Génère les `VAT query` (viewVAT_<box>) consommées par le doctype VAT Declaration
d'ERPNextSwiss, de façon DATA-DRIVEN depuis le référentiel `AFC VAT Box`.

Les VAT query sont GLOBALES : le placeholder `{company}` est remplacé à l'exécution par le
moteur d'ERPNextSwiss (get_view_total / get_view_tax). Une seule série sert toutes les sociétés.

Chaque query renvoie les colonnes attendues par le moteur : base_grand_total,
total_taxes_and_charges, posting_date. Le moteur l'enveloppe et ajoute le filtre de dates.

Usage :
  bench --site <site> execute erpnextswiss.swiss_vat_config.vat_declaration.generate_vat_queries
"""
import frappe

# --- Patterns SQL (le {{company}} reste littéral pour le moteur ; {box} est injecté) ----------

# Colonnes attendues par le DECOMPTE : base_grand_total (SUM base), total_taxes_and_charges
# (SUM tax), posting_date. Les colonnes SUPPLEMENTAIRES (name, account, description, tax_code,
# currency, tax_amount, total_amount) sont IGNOREES par le decompte et servent le JOURNAL TVA
# (report Kontrolle MwSt, qui fait SELECT *). Le {{company}} reste litteral ; {box}/{rate} injectes.

# A. Base des ventes par case (via afc_box de la ligne, fallback template document, + secondaire)
PAT_SALES_BASE = """SELECT
    si.name AS name, 'Sales Invoice' AS doctype, si.posting_date AS posting_date,
    sii.income_account AS account, sii.description AS description,
    COALESCE(itt.title, stct.title) AS tax_code, si.currency AS currency,
    sii.base_net_amount AS base_grand_total,
    ROUND(sii.base_net_amount * {rate} / 100, 2) AS tax_amount,
    ROUND(sii.base_net_amount * (100 + {rate}) / 100, 2) AS total_amount,
    0 AS total_taxes_and_charges
FROM `tabSales Invoice Item` sii
JOIN `tabSales Invoice` si ON si.name = sii.parent
LEFT JOIN `tabItem Tax Template` itt ON itt.name = sii.item_tax_template
LEFT JOIN `tabSales Taxes and Charges Template` stct ON stct.name = si.taxes_and_charges
WHERE si.docstatus = 1 AND si.company = '{{company}}'
  AND ( COALESCE(itt.afc_box, (SELECT s.afc_box FROM `tabSales Taxes and Charges` s
                               WHERE s.parent = si.name AND s.afc_box IS NOT NULL LIMIT 1)) = '{box}'
        OR COALESCE(itt.afc_box_secondary, (SELECT s.afc_box_secondary FROM `tabSales Taxes and Charges` s
                               WHERE s.parent = si.name AND s.afc_box_secondary IS NOT NULL LIMIT 1)) = '{box}' )"""

# B. Total du chiffre d'affaires (toutes les ventes, sans filtre de case) — case 200
# (taux mixte -> pas de TVA par ligne calculable generiquement : tax_amount = 0, total = net)
PAT_SALES_TOTAL = """SELECT
    si.name AS name, 'Sales Invoice' AS doctype, si.posting_date AS posting_date,
    sii.income_account AS account, sii.description AS description,
    '' AS tax_code, si.currency AS currency,
    sii.base_net_amount AS base_grand_total,
    0 AS tax_amount,
    sii.base_net_amount AS total_amount,
    0 AS total_taxes_and_charges
FROM `tabSales Invoice Item` sii
JOIN `tabSales Invoice` si ON si.name = sii.parent
WHERE si.docstatus = 1 AND si.company = '{{company}}'"""

# C. Impôt préalable (achats) par compte (l'afc_box est porté par le compte de TVA)
PAT_PURCHASE_TAX = """SELECT
    pi.name AS name, 'Purchase Invoice' AS doctype, pi.posting_date AS posting_date,
    ptc.account_head AS account, pi.remarks AS description,
    ptc.description AS tax_code, pi.currency AS currency,
    pi.base_net_total AS base_grand_total,
    ptc.base_tax_amount AS tax_amount,
    (pi.base_net_total + ptc.base_tax_amount) AS total_amount,
    ptc.base_tax_amount AS total_taxes_and_charges
FROM `tabPurchase Taxes and Charges` ptc
JOIN `tabPurchase Invoice` pi ON pi.name = ptc.parent
JOIN `tabAccount` acc ON acc.name = ptc.account_head
WHERE pi.docstatus = 1 AND pi.company = '{{company}}' AND COALESCE(ptc.afc_box, acc.afc_box) = '{box}'"""


# D. Impôt sur les acquisitions (reverse charge) : la case porte À LA FOIS la base (Prestations,
#    lue par get_total) ET l'impôt (lu par get_tax). Une seule query sert les deux. La taxe due
#    vit sur le compte 2203 (ligne "Deduct" du montage reverse charge) ; la base = net de la facture.
PAT_ACQUISITION = """SELECT
    pi.name AS name, 'Purchase Invoice' AS doctype, pi.posting_date AS posting_date,
    ptc.account_head AS account, pi.remarks AS description,
    ptc.description AS tax_code, pi.currency AS currency,
    pi.base_net_total AS base_grand_total,
    ABS(ptc.base_tax_amount) AS tax_amount,
    (pi.base_net_total + ABS(ptc.base_tax_amount)) AS total_amount,
    ABS(ptc.base_tax_amount) AS total_taxes_and_charges
FROM `tabPurchase Taxes and Charges` ptc
JOIN `tabPurchase Invoice` pi ON pi.name = ptc.parent
JOIN `tabAccount` acc ON acc.name = ptc.account_head
WHERE pi.docstatus = 1 AND pi.company = '{{company}}' AND COALESCE(ptc.afc_box, acc.afc_box) = '{box}'"""


# E. Escompte accordé (diminution de la contre-prestation) — case 235 UNIQUEMENT.
#    L'escompte de paiement rapide (ventilation native ERPNext) pose la part NETTE sur le compte
#    d'escompte (default_discount_account) via une déduction de Payment Entry de VENTE (Receive).
#    viewVAT_235 l'additionne à la base 235 (les lignes de facture taguées 235 restent captées par
#    PAT_SALES_BASE). La reprise TVA du décompte suit automatiquement (TVA vente dérivée = base × taux).
#    Le montant de la déduction (ped.amount) est en monnaie de la société (CHF), signe positif.
PAT_SALES_ESCOMPTE = """
UNION ALL
SELECT
    pe.name AS name, 'Payment Entry' AS doctype, pe.posting_date AS posting_date,
    ped.account AS account, 'Escompte accordé' AS description,
    '' AS tax_code, pe.paid_from_account_currency AS currency,
    ped.amount AS base_grand_total,
    0 AS tax_amount, ped.amount AS total_amount, 0 AS total_taxes_and_charges
FROM `tabPayment Entry Deduction` ped
JOIN `tabPayment Entry` pe ON pe.name = ped.parent
WHERE pe.docstatus = 1 AND pe.company = '{{company}}'
  AND pe.payment_type = 'Receive'
  AND ped.account = (SELECT c.default_discount_account FROM `tabCompany` c WHERE c.name = '{{company}}')"""


# F. Escompte obtenu (reprise de l'impôt préalable) — cases impôt préalable (400/405…).
#    Miroir de l'escompte accordé : l'escompte de paiement rapide (ventilation native) reprend la part
#    TVA sur le compte d'impôt préalable de la facture (1170 → case 400, 1171 → case 405) via une
#    déduction de Payment Entry d'ACHAT (Pay). ped.amount est NÉGATIF (reprise) → soustrait de la case.
#    On matche par acc.afc_box = case (le compte d'impôt préalable porte la case). La part nette de
#    l'escompte (compte 4900/3800) n'a pas d'afc_box → naturellement exclue.
PAT_PURCHASE_ESCOMPTE = """
UNION ALL
SELECT
    pe.name AS name, 'Payment Entry' AS doctype, pe.posting_date AS posting_date,
    ped.account AS account, 'Escompte obtenu (reprise impôt préalable)' AS description,
    '' AS tax_code, (SELECT c.default_currency FROM `tabCompany` c WHERE c.name = '{{company}}') AS currency,
    0 AS base_grand_total,
    ped.amount AS tax_amount,
    ped.amount AS total_amount,
    ped.amount AS total_taxes_and_charges
FROM `tabPayment Entry Deduction` ped
JOIN `tabPayment Entry` pe ON pe.name = ped.parent
JOIN `tabAccount` acc ON acc.name = ped.account
WHERE pe.docstatus = 1 AND pe.company = '{{company}}'
  AND pe.payment_type = 'Pay'
  AND acc.afc_box = '{box}'"""


# G. Écritures manuelles taguées (case portée par la LIGNE de Journal Entry, hors facture) — cases
#    d'impôt/correction (410/415/420…). Le « code TVA sur l'écriture » à la bexio : la fiduciaire tague
#    la ligne qui porte la TVA, sur N'IMPORTE QUEL compte. Le SIGNE vient de la CASE (pas du compte) :
#    {sign} = 'jea.debit - jea.credit' (case qui ajoute, ex. 410) ou 'jea.credit - jea.debit' (case qui
#    réduit, ex. 415/420). Seules les lignes TAGUÉES sont lues → aucune pollution (règlement, réévaluation).
PAT_JE_TAGGED_TAX = """
UNION ALL
SELECT
    je.name AS name, 'Journal Entry' AS doctype, je.posting_date AS posting_date,
    jea.account AS account, COALESCE(je.user_remark, je.title, '') AS description,
    '' AS tax_code, (SELECT c.default_currency FROM `tabCompany` c WHERE c.name = '{{company}}') AS currency,
    0 AS base_grand_total,
    ({sign}) AS tax_amount,
    ({sign}) AS total_amount,
    ({sign}) AS total_taxes_and_charges
FROM `tabJournal Entry Account` jea
JOIN `tabJournal Entry` je ON je.name = jea.parent
WHERE je.docstatus = 1 AND je.company = '{{company}}' AND jea.afc_box = '{box}'"""


def je_supported(box):
    """SOURCE DE VÉRITÉ de la couverture « TVA sur écriture » : vrai si `_sql_for` sait lire une
    ligne de Journal Entry taguée pour cette case. Utilisée par le moteur (ci-dessous) ET par la
    validation du doctype AFC VAT Box (empêche de rendre `je_taggable` une case non gérée).
    PHASE 1 : cases d'IMPÔT côté ACHAT (400/405/410/415/420). Étendre ICI pour la phase 2 (ex. base
    de vente) — moteur, validation et filtre restent cohérents automatiquement."""
    def g(k):
        return box.get(k) if hasattr(box, "get") else getattr(box, k, None)
    return g("computation") == "Declared" and g("side") == "Purchase" and g("amount_type") == "Tax"


def _sql_for(box):
    """Retourne le SQL de la case, ou None si non générable (Calculated)."""
    comp, side, amt = box.computation, box.side, box.amount_type
    rate = box.rate or 0
    if comp == "Calculated":
        return None
    if comp == "Total":
        return PAT_SALES_TOTAL.format(box=box.box_code, rate=rate)
    if comp == "Declared" and side == "Sales" and amt == "Base":
        # Case 235 (diminutions) : on ajoute les escomptes accordés au paiement (déductions de vente).
        pat = PAT_SALES_BASE + (PAT_SALES_ESCOMPTE if box.box_code == "235" else "")
        return pat.format(box=box.box_code, rate=rate)
    if comp == "Declared" and side == "Purchase" and amt == "Tax":
        # Cases impôt préalable : on soustrait les reprises d'escompte obtenu (déductions d'achat).
        pat = PAT_PURCHASE_TAX + PAT_PURCHASE_ESCOMPTE
        # + écritures manuelles taguées (hors facture) si la case est taguable ET supportée. Le SIGNE vient
        # de la CASE : réduction (415/420) → crédit ; ajout (410) → débit. Substitué AVANT .format.
        if box.get("je_taggable") and je_supported(box):
            sign = "jea.credit - jea.debit" if box.get("reduces_total") else "jea.debit - jea.credit"
            pat = pat + PAT_JE_TAGGED_TAX.replace("{sign}", sign)
        return pat.format(box=box.box_code, rate=rate)
    if comp == "Declared" and side == "Purchase" and amt == "Base+Tax":
        return PAT_ACQUISITION.format(box=box.box_code, rate=rate)
    return None


def generate_vat_queries():
    created, updated, skipped = [], [], []
    boxes = frappe.get_all("AFC VAT Box", filters={"enabled": 1},
                           fields=["box_code", "side", "amount_type", "computation", "rate",
                                   "reduces_total", "je_taggable"])
    for b in boxes:
        sql = _sql_for(b)
        name = f"viewVAT_{b.box_code}"
        if not sql:
            skipped.append(f"{name} ({b.computation}/{b.side}/{b.amount_type})")
            continue
        if frappe.db.exists("VAT query", name):
            frappe.db.set_value("VAT query", name, "query", sql, update_modified=False)
            updated.append(name)
        else:
            frappe.get_doc({"doctype": "VAT query", "title": name, "code": b.box_code,
                            "query": sql}).insert(ignore_permissions=True)
            created.append(name)
    frappe.db.commit()
    out = [f"VAT query générées : {len(created)} créées, {len(updated)} mises à jour."]
    out.append("  créées : " + ", ".join(sorted(created)))
    out.append("  màj    : " + ", ".join(sorted(updated)))
    out.append("  SKIP (calculées / cas spéciaux Phase 4) : " + ", ".join(sorted(skipped)))
    return "\n".join(out)
