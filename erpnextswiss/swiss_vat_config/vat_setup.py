# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Setup de l'app erpnextswiss.swiss_vat_config : custom fields `afc_box` + seed du referentiel AFC VAT Box.

Idempotent : create_custom_fields et le seed verifient l'existence avant de creer.
Appele par les hooks after_install / after_migrate (voir hooks.py).
"""
import re
from collections import Counter

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def strip_box_suffix(company):
    """Retire ' [xxx]' des titres de templates de TVA (afc_box conserve).
    Saute les cas ou le nettoyage creerait une collision (ex. corrections 415/420)."""
    abbr = frappe.get_cached_value("Company", company, "abbr")
    pat = re.compile(r"\s*\[[^\]]+\]")
    log = []
    for doctype in ["Sales Taxes and Charges Template", "Purchase Taxes and Charges Template"]:
        rows = frappe.get_all(doctype, filters={"company": company}, fields=["name", "title"])
        counts = Counter(pat.sub("", r.title).strip() for r in rows)
        for r in rows:
            new_title = pat.sub("", r.title).strip()
            if new_title == r.title:
                continue
            if counts[new_title] > 1:
                log.append(f"  [collision, garde digit] {r.title}")
                continue
            new_name = f"{new_title} - {abbr}"
            frappe.db.set_value(doctype, r.name, "title", new_title, update_modified=False)
            if new_name != r.name and not frappe.db.exists(doctype, new_name):
                frappe.rename_doc(doctype, r.name, new_name, force=True)
                log.append(f"  {r.name}  ->  {new_name}")
    frappe.db.commit()
    return "Renommage:\n" + "\n".join(log)

# --- Custom fields afc_box (Link -> AFC VAT Box) sur les 3 doctypes -----------
CUSTOM_FIELDS = {
    # Ligne d'écriture manuelle : « code TVA » de la ligne (à la bexio). Alimente le décompte HORS
    # facture (corrections, prestations à soi-même, dégrèvements). Seules les cases « taguables » sont
    # proposées ; le compte utilisé est libre (c'est le tag qui compte).
    "Journal Entry Account": [
        {
            "fieldname": "afc_box",
            "label": "Case AFC (TVA)",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "credit_in_account_currency",
            "link_filters": '[["AFC VAT Box","je_taggable","=",1]]',
            "in_list_view": 1,
            "description": "Case du decompte TVA alimentee par cette ligne (equivalent d'un code TVA sur l'ecriture). A poser sur la ligne qui porte le montant de TVA. Seules les cases marquees 'Taguable en ecriture' apparaissent. Montant repris = debit ou credit de la ligne selon le sens de la case. Laisser vide si la ligne n'a aucun effet TVA.",
        }
    ],
    "Item Tax Template": [
        {
            "fieldname": "afc_box",
            "label": "AFC VAT Box",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "disabled",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "description": "Case principale du decompte alimentee par les lignes utilisant ce template (vente).",
        },
        {
            "fieldname": "afc_box_secondary",
            "label": "AFC VAT Box (secondaire)",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "afc_box",
            "description": "Case secondaire (double appartenance, ex. opte 205.303 : primaire=303, secondaire=205).",
        },
    ],
    # Case portee par la LIGNE de taxe (vente) : fallback pour les lignes sans Item Tax Template.
    "Sales Taxes and Charges": [
        {
            "fieldname": "afc_box",
            "label": "AFC VAT Box",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "account_head",
            "in_list_view": 1,
            "description": "Case du decompte pour cette ligne de taxe (vente) — fallback des lignes sans Item Tax Template.",
        },
        {
            "fieldname": "afc_box_secondary",
            "label": "AFC VAT Box (secondaire)",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "afc_box",
            "description": "Case secondaire (double appartenance, ex. opte 205.303).",
        },
    ],
    # Case portee par la LIGNE de taxe (achat) : prime sur l'afc_box du compte (override).
    "Purchase Taxes and Charges": [
        {
            "fieldname": "afc_box",
            "label": "AFC VAT Box",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "account_head",
            "in_list_view": 1,
            "description": "Case du decompte pour cette ligne de taxe (achat) — prime sur l'afc_box du compte.",
        },
        {
            "fieldname": "afc_box_secondary",
            "label": "AFC VAT Box (secondaire)",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "afc_box",
            "description": "Case secondaire (symetrie ; non utilise cote achat).",
        },
    ],
    "Account": [
        {
            "fieldname": "afc_box",
            "label": "AFC VAT Box",
            "fieldtype": "Link",
            "options": "AFC VAT Box",
            "insert_after": "tax_rate",
            "depends_on": "eval:doc.account_type=='Tax'",
            "in_standard_filter": 1,
            "description": "Case du decompte TVA suisse (impot prealable) alimentee par ce compte (achat).",
        }
    ],
}


def create_afc_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


# --- Referentiel des cases (methode effective) --------------------------------
# code, label, part, side, amount_type, computation, rate, ech_identifier, legal_ref, sort, formula
_B = "I - Chiffre d'affaires"
_II = "II - Impot"
_III = "III - Autres"
BOXES = [
    ("200", "Total des contre-prestations", _B, "Sales", "Base", "Total", 0, "totalConsideration", "art.39 LTVA", 10, ""),
    ("205", "Prestations optees (art.22)", _B, "Sales", "Base", "Declared", 0, "opted", "art.22 LTVA", 20, ""),
    ("220", "Prestations exonerees / export", _B, "Sales", "Base", "Declared", 0, "suppliesToForeignCountries", "art.23 LTVA", 30, ""),
    ("221", "Prestations a l'etranger", _B, "Sales", "Base", "Declared", 0, "suppliesAbroad", "", 40, ""),
    ("225", "Procedure de declaration", _B, "Sales", "Base", "Declared", 0, "transferNotificationProcedure", "art.38 LTVA", 50, ""),
    ("230", "Prestations exclues", _B, "Sales", "Base", "Declared", 0, "suppliesExemptFromTax", "art.21 LTVA", 60, ""),
    ("235", "Diminutions (escomptes, pertes)", _B, "Sales", "Base", "Declared", 0, "reductionOfConsideration", "", 70, ""),
    ("299", "Chiffre d'affaires imposable", _B, "", "", "Calculated", 0, "", "", 80, "200-220-221-225-230-235"),
    ("303", "Base taux normal 8.1%", _II, "Sales", "Base", "Declared", 8.1, "suppliesPerTaxRate", "", 90, ""),
    ("313", "Base taux reduit 2.6%", _II, "Sales", "Base", "Declared", 2.6, "suppliesPerTaxRate", "", 100, ""),
    ("343", "Base taux hebergement 3.8%", _II, "Sales", "Base", "Declared", 3.8, "suppliesPerTaxRate", "", 110, ""),
    ("382", "Impot sur les acquisitions (anciens taux <=2023)", _II, "Purchase", "Base+Tax", "Declared", 0, "acquisitionTaxOld", "art.45 LTVA", 120, ""),
    ("383", "Impot sur les acquisitions", _II, "Purchase", "Base+Tax", "Declared", 8.1, "acquisitionTax", "art.45 LTVA", 121, ""),
    ("399", "Total impot du", _II, "", "", "Calculated", 0, "", "", 130, "impot(303,313,343)+impot(383)"),
    ("400", "Impot prealable materiel et services", _II, "Purchase", "Tax", "Declared", 0, "inputTaxMaterialAndServices", "", 140, ""),
    ("405", "Impot prealable investissements", _II, "Purchase", "Tax", "Declared", 0, "inputTaxInvestments", "", 150, ""),
    ("410", "Degrevement ulterieur", _II, "Purchase", "Tax", "Declared", 0, "subsequentInputTaxDeduction", "art.32 LTVA", 160, ""),
    ("415", "Corrections (double affectation)", _II, "Purchase", "Tax", "Declared", 0, "inputTaxCorrections", "art.30 LTVA", 170, ""),
    ("420", "Reductions (subventions)", _II, "Purchase", "Tax", "Declared", 0, "inputTaxReductions", "art.33 LTVA", 180, ""),
    ("479", "Total impot prealable", _II, "", "", "Calculated", 0, "", "", 190, "400+405+410-415-420"),
    ("500", "Montant a payer a l'AFC", "", "", "", "Calculated", 0, "payableTax", "", 200, "399-479"),
    ("510", "Avoir en faveur de l'assujetti", "", "", "", "Calculated", 0, "payableTax", "", 210, ""),
    ("900", "Subventions, taxes touristiques", _III, "Sales", "Base", "Declared", 0, "subsidies", "art.18 LTVA", 220, ""),
    ("910", "Dons, dividendes, indemnites", _III, "Sales", "Base", "Declared", 0, "donations", "art.18 LTVA", 230, ""),
]


# Cases qui RÉDUISENT le total (soustraites dans 479 = 400+405+410-415-420) → gl_sign = crédit.
REDUCES_TOTAL = {"415", "420"}
# Cases sélectionnables sur une ligne d'écriture (corrections/ajustements hors facture). Phase 1 :
# uniquement les cases d'impôt préalable qui ne rentrent pas dans une facture (dégrèvement + corrections).
JE_TAGGABLE = {"410", "415", "420"}


def seed_afc_boxes():
    created = updated = 0
    for (code, label, part, side, amount, comp, rate, ech, legal, sort, formula) in BOXES:
        reduces = 1 if code in REDUCES_TOTAL else 0
        taggable = 1 if code in JE_TAGGABLE else 0
        if frappe.db.exists("AFC VAT Box", code):
            # màj idempotente des flags (au cas où la case a été seedée avant l'ajout des champs)
            frappe.db.set_value("AFC VAT Box", code,
                                {"reduces_total": reduces, "je_taggable": taggable},
                                update_modified=False)
            updated += 1
            continue
        frappe.get_doc({
            "doctype": "AFC VAT Box",
            "box_code": code,
            "box_label": label,
            "part": part or None,
            "side": side or None,
            "amount_type": amount or None,
            "computation": comp,
            "rate": rate,
            "ech_identifier": ech,
            "legal_ref": legal,
            "sort_order": sort,
            "formula": formula,
            "reduces_total": reduces,
            "je_taggable": taggable,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        created += 1
    frappe.db.commit()
    return f"AFC VAT Box: {created} cases creees ({len(BOXES) - created} deja presentes)"


# --- Tagging des defauts (mapping du plan bexio -> cases), par societe ---------
# Item Tax Template (ligne) : le taux -> la case. (TVA 0% laisse vide -> fallback document)
ITEM_TEMPLATE_MAP = {
    "TVA 8.1%": "303",
    "TVA 2.6%": "313",
    "TVA 3.8% (hébergement)": "343",
}
# Sales Taxes and Charges Template (fallback document) : par titre
SALES_DOC_MAP = {
    "TVA 8.1% (vente) [303]": "303",
    "TVA 2.6% (vente) [313]": "313",
    "TVA 3.8% hébergement [343]": "343",
    "Export exonéré [220]": "220",
    "Prestations à l'étranger [221]": "221",
    "Procédure de déclaration [225]": "225",
    "Ventes non imposables [230]": "230",
    "TVA 8.1% option art.22 [205.303]": "303",
    "Subventions/surtaxes [900]": "900",
    "Dons/dividendes/indemnités [910]": "910",
}
# Cases SECONDAIRES (double appartenance) : template -> case secondaire
SALES_DOC_SECONDARY_MAP = {
    "TVA 8.1% option art.22 [205.303]": "205",  # opte = taxable (303) + memo opte (205)
}
# Account (achat) : numero de compte -> case
ACCOUNT_MAP = {
    "1170": "400",
    "1171": "405",
    "1173": "420",
    "1174": "415",
    "2203": "383",  # impot sur les acquisitions (taux actuels) - base+tax via Pattern D
}

# Item Tax Templates 0% PAR CATEGORIE (pour ventiler les factures multi-categories 0% au niveau ligne)
CATEGORY_ITEM_TEMPLATES = [
    ("TVA 0% Export", "220"),
    ("TVA 0% Étranger", "221"),
    ("TVA 0% Procédure", "225"),
    ("TVA 0% Exclu", "230"),
]


def create_category_item_templates(company):
    """Cree les 4 Item Tax Templates 0% par categorie + les tagge (idempotent)."""
    acc2200 = frappe.db.get_value("Account", {"account_number": "2200", "company": company})
    if not acc2200:
        return "compte 2200 introuvable"
    log = []
    for title, box in CATEGORY_ITEM_TEMPLATES:
        nm = frappe.db.get_value("Item Tax Template", {"title": title, "company": company})
        if nm:
            frappe.db.set_value("Item Tax Template", nm, "afc_box", box)
            log.append(f"  {title:22} (existant) -> afc_box {box}")
            continue
        doc = frappe.get_doc({
            "doctype": "Item Tax Template",
            "title": title,
            "company": company,
            "afc_box": box,
            "taxes": [{"tax_type": acc2200, "tax_rate": 0}],
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)
        log.append(f"  {title:22} cree -> afc_box {box}")
    frappe.db.commit()
    return "Item Tax Templates 0% par categorie:\n" + "\n".join(log)


def tag_default_boxes(company):
    """Pose afc_box sur les templates/comptes bexio par defaut d'une societe."""
    log = []

    def set_box(doctype, name, box):
        if name and frappe.db.exists("AFC VAT Box", box):
            frappe.db.set_value(doctype, name, "afc_box", box)
            log.append(f"  {doctype[:22]:22} {name[:40]:40} -> {box}")

    # Item Tax Templates (par titre + societe)
    for title, box in ITEM_TEMPLATE_MAP.items():
        nm = frappe.db.get_value("Item Tax Template", {"title": title, "company": company})
        set_box("Item Tax Template", nm, box)
    # Sales Taxes and Charges Templates (fallback) : case primaire
    for title, box in SALES_DOC_MAP.items():
        nm = frappe.db.get_value("Sales Taxes and Charges Template", {"title": title, "company": company})
        set_box("Sales Taxes and Charges Template", nm, box)
    # Cases secondaires (double appartenance)
    for title, box in SALES_DOC_SECONDARY_MAP.items():
        nm = frappe.db.get_value("Sales Taxes and Charges Template", {"title": title, "company": company})
        if nm and frappe.db.exists("AFC VAT Box", box):
            frappe.db.set_value("Sales Taxes and Charges Template", nm, "afc_box_secondary", box)
            log.append(f"  {'Sales Taxes (secondaire)':22} {nm[:40]:40} -> {box}")
    # Comptes (achat)
    for num, box in ACCOUNT_MAP.items():
        nm = frappe.db.get_value("Account", {"account_number": num, "company": company})
        set_box("Account", nm, box)

    frappe.db.commit()
    return "Tagging par defaut:\n" + "\n".join(log)


# --- Renommage "bexio" (taux en prefixe, libelles explicites) -----------------
# cle = titre courant, valeur = nouveau titre. Par doctype.
RENAME_SALES = {
    "TVA 8.1% (vente)": "8.1% Taux normal",
    "TVA 2.6% (vente)": "2.6% Taux réduit",
    "TVA 3.8% hébergement": "3.8% Hébergement",
    "TVA 8.1% option art.22": "8.1% Prestations optées (art. 22)",
    "Export exonéré": "0% Exportations et prestations exonérées",
    "Prestations à l'étranger": "0% Prestations à l'étranger",
    "Procédure de déclaration": "0% Transferts (procédure de déclaration)",
    "Ventes non imposables": "0% Opérations exclues (art. 21)",
    "Vente 0%": "0% Autres opérations non imposables",
    "Subventions/surtaxes": "0% Subventions et contributions",
    "Dons/dividendes/indemnités": "0% Dons et dividendes",
}
RENAME_ITEM = {
    "TVA 8.1%": "8.1% Taux normal",
    "TVA 2.6%": "2.6% Taux réduit",
    "TVA 3.8% (hébergement)": "3.8% Hébergement",
    "TVA 0%": "0% Autres opérations non imposables",
    "TVA 0% Export": "0% Exportations et prestations exonérées",
    "TVA 0% Étranger": "0% Prestations à l'étranger",
    "TVA 0% Procédure": "0% Transferts (procédure de déclaration)",
    "TVA 0% Exclu": "0% Opérations exclues (art. 21)",
}
RENAME_PURCHASE = {
    "Impôt préalable 8.1% - Matériel/March.": "8.1% Impôt préalable - Matériel et prestations",
    "Impôt préalable 2.6% - Matériel/March.": "2.6% Impôt préalable - Matériel et prestations",
    "Impôt préalable 8.1% - Investissements": "8.1% Impôt préalable - Investissements",
    "Impôt préalable 2.6% - Investissements": "2.6% Impôt préalable - Investissements",
    "Import matériel exonéré": "0% Import - Matériel exonéré",
    "Import investissement exonéré": "0% Import - Investissement exonéré",
    "TVA import matériel (douane)": "Import - TVA à l'importation (matériel)",
    "TVA import investissement (douane)": "Import - TVA à l'importation (investissement)",
    "Impôt sur acquisitions - Matériel 8.1%": "8.1% Impôt sur acquisitions - Matériel",
    "Impôt sur acquisitions - Invest. 8.1%": "8.1% Impôt sur acquisitions - Investissements",
    "Impôt préalable 8.1% - Matériel": "8.1% Dégrèvement ultérieur (matériel)",
    "Impôt préalable 3.8% - Matériel": "3.8% Impôt préalable - Matériel et prestations",
    "Impôt préalable 3.8% - Investissements": "3.8% Impôt préalable - Investissements",
    "Correction impôt préalable 8.1% [415]": "8.1% Correction impôt préalable (double affectation)",
    "Correction impôt préalable 8.1% [420]": "8.1% Réduction impôt préalable (subventions)",
}


def rename_templates_bexio(company):
    """Renomme tous les templates de TVA en nomenclature bexio (taux prefixe). afc_box conserve."""
    abbr = frappe.get_cached_value("Company", company, "abbr")
    log = []
    for doctype, mapping in [
        ("Sales Taxes and Charges Template", RENAME_SALES),
        ("Purchase Taxes and Charges Template", RENAME_PURCHASE),
        ("Item Tax Template", RENAME_ITEM),
    ]:
        for old_title, new_title in mapping.items():
            old_name = frappe.db.get_value(doctype, {"title": old_title, "company": company})
            if not old_name:
                continue
            frappe.db.set_value(doctype, old_name, "title", new_title, update_modified=False)
            new_name = f"{new_title} - {abbr}"
            if new_name != old_name and not frappe.db.exists(doctype, new_name):
                frappe.rename_doc(doctype, old_name, new_name, force=True)
            log.append(f"  {doctype[:5]}: {old_title[:35]:35} -> {new_title}")
    frappe.db.commit()
    return "Renommage bexio:\n" + "\n".join(log)


def after_install():
    create_afc_custom_fields()
    seed_afc_boxes()
    _create_financial_templates()


def after_migrate():
    create_afc_custom_fields()
    seed_afc_boxes()          # idempotent : (re)pose les flags reduces_total / je_taggable
    _create_financial_templates()
    try:
        from erpnextswiss.swiss_vat_config.vat_declaration import generate_vat_queries
        generate_vat_queries()   # régénère les viewVAT (dont l'union écriture PAT_JE_TAGGED_TAX)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "erpnextswiss.swiss_vat_config: generate_vat_queries")


def _create_financial_templates():
    """Crée/rafraîchit les Financial Report Templates statutaires (compte de résultat CO 959b)
    et le Print Format « Décompte TVA (AFC) »."""
    try:
        from erpnextswiss.swiss_vat_config.financial_reports import create_co959b_template
        create_co959b_template()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "erpnextswiss.swiss_vat_config: create_co959b_template")
    try:
        from erpnextswiss.swiss_vat_config.print_formats import create_vat_print_format
        create_vat_print_format()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "erpnextswiss.swiss_vat_config: create_vat_print_format")
