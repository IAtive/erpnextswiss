# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Configuration comptable/TVA suisse (bexio) d'une Company ERPNext 16 - POINT D'ENTREE UNIQUE.

Reprend l'integralite de l'ancien ch_accounting_setup + pose la nomenclature bexio
(CODE - Description taux%) et les afc_box A LA CREATION des templates.

Prerequis : plan comptable bexio importe (chart 'ch_pme_fr') + app erpnextswiss.swiss_vat_config installee
            (doctype AFC VAT Box + custom fields afc_box seedes).

Usage :
  bench --site <site> execute erpnextswiss.swiss_vat_config.company_setup.setup_company --kwargs "{'company':'X'}"
"""
import frappe


# ------------------------------------------------------------------ helpers ---
def _pct(rate):
    return f"{rate:.2f}%"


def _title(code, desc, rate):
    return f"{code} - {desc} {_pct(rate)}"


def _acc(company, num):
    name = frappe.db.get_value("Account", {"account_number": num, "company": company})
    if not name:
        print(f"  ⚠️ compte {num} introuvable pour {company}")
    return name


def _acc_silent(company, num):
    """Comme _acc mais SANS warning — pour les vérifs « existe déjà ? » AVANT une création
    (un compte absent est alors NORMAL : on va justement le créer)."""
    return frappe.db.get_value("Account", {"account_number": num, "company": company})


def _box(box):
    return box if (box and frappe.db.exists("AFC VAT Box", box)) else None


# =============================================== NETTOYAGE DEFAUTS ERPNEXT ====
DEFAULT_TITLES = ["Switzerland normal VAT", "Switzerland reduced VAT", "Switzerland lodging VAT"]
DEFAULT_ACCOUNT_NAMES = ["VAT 8.1%", "VAT 2.6%", "VAT 3.8%"]
DEFAULT_TAX_GROUPS = ["Duties and Taxes", "Tax Assets"]


def cleanup_defaults(company):
    print("→ Nettoyage des templates/comptes par defaut ERPNext…")
    for dt in ["Sales Taxes and Charges Template", "Purchase Taxes and Charges Template", "Item Tax Template"]:
        for title in DEFAULT_TITLES:
            name = frappe.db.get_value(dt, {"title": title, "company": company})
            if name:
                try:
                    frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
                except Exception:
                    frappe.db.set_value(dt, name, "disabled", 1)
    for acc_name in DEFAULT_ACCOUNT_NAMES:
        name = frappe.db.get_value("Account", {"account_name": acc_name, "company": company})
        if not name:
            continue
        if frappe.db.exists("GL Entry", {"account": name}):
            frappe.db.set_value("Account", name, "disabled", 1)
        else:
            try:
                frappe.delete_doc("Account", name, ignore_permissions=True, force=True)
            except Exception:
                frappe.db.set_value("Account", name, "disabled", 1)
    for grp_name in DEFAULT_TAX_GROUPS:
        grp = frappe.db.get_value("Account", {"account_name": grp_name, "company": company, "is_group": 1})
        if grp and not frappe.db.exists("Account", {"parent_account": grp}):
            try:
                frappe.delete_doc("Account", grp, ignore_permissions=True, force=True)
            except Exception:
                pass


# =============================================== DEFINITIONS BEXIO ============
# SALES (compte 2200) : (code, desc, rate, charge_type, afc_box, afc_box_secondary, active, is_default)
SALES = [
    ("NC81", "Chiffre d'affaires (TN)", 8.1, "On Net Total", "303", None, True, True),
    ("CR26", "Chiffre d'affaires (TR)", 2.6, "On Net Total", "313", None, True, False),
    ("CS38", "Chiffre d'affaires (TS)", 3.8, "On Net Total", "343", None, False, False),
    ("PO81", "Imposition d'operation par option", 8.1, "On Net Total", "303", "205", False, False),
    ("C00", "Sans TVA", 0, "On Net Total", None, None, False, False),
    ("CEX", "Exportation / Exonere", 0, "On Net Total", "220", None, True, False),
    ("CSE", "Prestations fournies a l'etranger", 0, "On Net Total", "221", None, False, False),
    ("ANN", "Transfert (procedure d'annonce)", 0, "On Net Total", "225", None, False, False),
    ("OEX", "Operations exclues", 0, "On Net Total", "230", None, False, False),
    ("SUB", "Subventions, taxes de sejour", 0, "On Net Total", "900", None, False, False),
    ("DON", "Dons, dividendes, remunerations", 0, "On Net Total", "910", None, False, False),
]
# PURCHASE simples (case portee par le COMPTE) : (code, desc, rate, charge_type, account_num, active, is_default)
PURCHASE = [
    ("IPM81", "Mat./Ser. (TN)", 8.1, "On Net Total", "1170", True, True),
    ("IPM26", "Mat./Ser. (TR)", 2.6, "On Net Total", "1170", True, False),
    ("IPM38", "Mat./Ser. (TS)", 3.8, "On Net Total", "1170", False, False),
    ("IPIM", "Importation", 0, "On Net Total", "1170", True, False),
    ("DOUAM", "Entree mat./ser. (douane)", 100, "Actual", "1170", True, False),
    ("IPCE81", "Inv./CE (TN)", 8.1, "On Net Total", "1171", True, False),
    ("IPCE26", "Inv./CE (TR)", 2.6, "On Net Total", "1171", True, False),
    ("IPCE38", "Inv./CE (TS)", 3.8, "On Net Total", "1171", False, False),
    ("IP00", "Sans TVA", 0, "On Net Total", "1171", True, False),
    ("DOUACE", "Entree inv./CE (douane)", 100, "Actual", "1171", True, False),
    ("DUIP", "Deduction ulterieure de l'impot prealable", 8.1, "On Net Total", "1170", False, False),
    ("RIP", "Reductions de l'impot prealable", 8.1, "On Net Total", "1173", False, False),
    ("IPPS", "Correction prestation a soi-meme", 8.1, "On Net Total", "1174", False, False),
]
# REVERSE CHARGE (acquisitions, 2 lignes Add/Deduct) : (code, desc, rate, deductible_num, due_num, active)
REVERSE = [
    ("IAM81", "Impot sur les acquisitions Mat./Ser.", 8.1, "1170", "2203", True),
    ("IACE81", "Impot sur les acquisitions Inv./CE", 8.1, "1171", "2203", True),
]
# ITEM TAX TEMPLATES (codes ventes = classification ligne) : (code, desc, rate, afc_box, afc_box_secondary, active)
ITEMS = [
    ("NC81", "Chiffre d'affaires (TN)", 8.1, "303", None, True),
    ("CR26", "Chiffre d'affaires (TR)", 2.6, "313", None, True),
    ("CS38", "Chiffre d'affaires (TS)", 3.8, "343", None, False),
    ("PO81", "Imposition d'operation par option", 8.1, "303", "205", False),
    ("CEX", "Exportation / Exonere", 0, "220", None, True),
    ("CSE", "Prestations fournies a l'etranger", 0, "221", None, False),
    ("ANN", "Transfert (procedure d'annonce)", 0, "225", None, False),
    ("OEX", "Operations exclues", 0, "230", None, False),
    ("C00", "Sans TVA", 0, None, None, False),
]

COMPANY_DEFAULTS = {
    "round_off_account": "6945",
    "exchange_gain_loss_account": "6999",
    "stock_adjustment_account": "4800",
    "default_discount_account": "3800",
    # Épingler les comptes tiers NORMAUX : sinon, avec 2030 (acomptes reçus) typé Receivable,
    # ERPNext choisit 2030 comme débiteur par défaut → les créances clients atterrissent sur le
    # compte d'acompte au lieu de 1100. On force 1100 (Clients) / 2000 (Fournisseurs).
    "default_receivable_account": "1100",
    "default_payable_account": "2000",
}
DISABLED_ACCOUNTS = ["6949"]
ADVANCE_CONFIG = {
    "default_advance_received_account": ("2030", "Receivable"),
    "default_advance_paid_account": ("1130", "Payable"),
}
# Case portee par le compte (achat) : num -> box
ACCOUNT_AFC = {"1170": "400", "1171": "405", "1173": "420", "1174": "415", "2203": "383"}

# --- Compte banque CHF unique -----------------------------------------------
# Un seul compte de banque CHF, nomme "Banque CHF". Le chart corrige (generate_coa.py :
# ACCOUNT_RENAME/EXCLUDE_ACCOUNTS) ne cree deja plus qu'un compte 1020 "Banque CHF" et retire
# le placeholder "Bank"/1029 du plan. La fonction ci-dessous ne sert donc qu'a MIGRER une
# societe nee de l'ANCIEN chart (renommer 1020) ; no-op silencieux pour une nouvelle societe.
BANK_CHF = ("1020", "Banque CHF")

# --- Banque & compte bancaire par defaut ------------------------------------
# On seede la banque UBS (master global) + un compte bancaire d'entreprise rattache au compte
# 1020 (banque CHF), marque par defaut et compte de societe (necessaire pour le rapprochement
# bancaire). L'IBAN est laisse VIDE : a renseigner manuellement (specifique a la societe).
DEFAULT_BANK = ("UBS Switzerland AG", "UBSW")   # (bank_name, BIC/SWIFT)
DEFAULT_BANK_ACCOUNT_NAME = "UBS CHF"           # rattache au compte 1020

# --- Modes de paiement -------------------------------------------------------
# TOUS les modes sont traduits en francais (y compris les inactifs). On n'ACTIVE que
# Carte de credit + Virement bancaire, tous deux mappes sur le compte banque CHF (1020) de la
# societe ; les autres (Especes, Cheque, Traite bancaire) sont desactives. NB : Mode of Payment
# est un master GLOBAL -> le renommage et l'activation valent pour tout le bench ; seul le
# mapping du compte est par societe.
MODE_RENAMES = [
    ("Credit Card", "Carte de crédit"),
    ("Wire Transfer", "Virement bancaire"),
    ("Cash", "Espèces"),
    ("Cheque", "Chèque"),
    ("Bank Draft", "Traite bancaire"),
]
MODES_ENABLED = ["Carte de crédit", "Virement bancaire"]
MODES_DISABLED = ["Espèces", "Chèque", "Traite bancaire"]


# =============================================== CREATION DES TEMPLATES ======
def create_sales(company):
    print("→ Sales Taxes and Charges Templates…")
    for code, desc, rate, ctype, box, box2, active, is_def in SALES:
        title = _title(code, desc, rate)
        if frappe.db.exists("Sales Taxes and Charges Template", {"title": title, "company": company}):
            continue
        acc = _acc(company, "2200")
        if not acc:
            continue
        doc = frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template", "title": title, "company": company,
            "disabled": 0 if active else 1, "is_default": 1 if is_def else 0,
            "taxes": [{"charge_type": ctype, "account_head": acc,
                       "rate": rate if ctype == "On Net Total" else 0, "description": title,
                       "afc_box": _box(box), "afc_box_secondary": _box(box2)}],
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)


def create_purchase(company):
    print("→ Purchase Taxes and Charges Templates…")
    for code, desc, rate, ctype, num, active, is_def in PURCHASE:
        title = _title(code, desc, rate)
        if frappe.db.exists("Purchase Taxes and Charges Template", {"title": title, "company": company}):
            continue
        acc = _acc(company, num)
        if not acc:
            continue
        # case portee par la ligne : defaut = case du compte, sauf DUIP (partage 1170 avec 400) -> 410
        box = "410" if code == "DUIP" else ACCOUNT_AFC.get(num)
        doc = frappe.get_doc({
            "doctype": "Purchase Taxes and Charges Template", "title": title, "company": company,
            "disabled": 0 if active else 1, "is_default": 1 if is_def else 0,
            "taxes": [{"charge_type": ctype, "account_head": acc, "category": "Total",
                       "add_deduct_tax": "Add", "rate": rate if ctype == "On Net Total" else 0,
                       "description": title, "afc_box": _box(box)}],
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)


def create_reverse_charge(company):
    print("→ Reverse charge (acquisitions, double ligne)…")
    for code, desc, rate, ded_num, due_num, active in REVERSE:
        title = _title(code, desc, rate)
        existing = frappe.db.get_value("Purchase Taxes and Charges Template", {"title": title, "company": company})
        if existing:
            frappe.delete_doc("Purchase Taxes and Charges Template", existing, ignore_permissions=True, force=True)
        ded, due = _acc(company, ded_num), _acc(company, due_num)
        if not ded or not due:
            continue
        doc = frappe.get_doc({
            "doctype": "Purchase Taxes and Charges Template", "title": title, "company": company,
            "disabled": 0 if active else 1, "is_default": 0,
            "taxes": [
                {"charge_type": "On Net Total", "account_head": ded, "rate": rate, "category": "Total",
                 "add_deduct_tax": "Add", "description": f"{title} — deductible",
                 "afc_box": _box(ACCOUNT_AFC.get(ded_num))},
                {"charge_type": "On Net Total", "account_head": due, "rate": rate, "category": "Total",
                 "add_deduct_tax": "Deduct", "description": f"{title} — impot du (acquisitions)",
                 "afc_box": _box("383")},
            ],
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)


def create_items(company):
    print("→ Item Tax Templates (codes ventes)…")
    acc = _acc(company, "2200")
    if not acc:
        return
    for code, desc, rate, box, box2, active in ITEMS:
        title = _title(code, desc, rate)
        if frappe.db.exists("Item Tax Template", {"title": title, "company": company}):
            continue
        doc = frappe.get_doc({
            "doctype": "Item Tax Template", "title": title, "company": company,
            "disabled": 0 if active else 1,
            "afc_box": _box(box), "afc_box_secondary": _box(box2),
            "taxes": [{"tax_type": acc, "tax_rate": rate}],
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)


# =============================================== CONFIG COMPTES / SOCIETE =====
def migrate_afc_to_lines(company):
    """Migration : pose l'afc_box sur les LIGNES de taxe des templates existants
    (vente : header -> ligne 2200 ; achat : case du compte, sauf DUIP -> 410)."""
    n = 0
    for name in frappe.get_all("Sales Taxes and Charges Template", filters={"company": company}, pluck="name"):
        doc = frappe.get_doc("Sales Taxes and Charges Template", name)
        hb, hs = doc.get("afc_box"), doc.get("afc_box_secondary")
        changed = False
        for row in doc.taxes:
            if hb and not row.get("afc_box"):
                row.afc_box = hb
                changed = True
            if hs and not row.get("afc_box_secondary"):
                row.afc_box_secondary = hs
                changed = True
        if changed:
            doc.save(ignore_permissions=True)
            n += 1
    for name in frappe.get_all("Purchase Taxes and Charges Template", filters={"company": company}, pluck="name"):
        doc = frappe.get_doc("Purchase Taxes and Charges Template", name)
        is_duip = (doc.title or "").startswith("DUIP")
        changed = False
        for row in doc.taxes:
            if row.get("afc_box"):
                continue
            accnum = frappe.db.get_value("Account", row.account_head, "account_number")
            box = "410" if (is_duip and accnum == "1170") else ACCOUNT_AFC.get(accnum)
            if box:
                row.afc_box = box
                changed = True
        if changed:
            doc.save(ignore_permissions=True)
            n += 1
    frappe.db.commit()
    return f"Migration afc_box -> lignes : {n} template(s) mis a jour."


def tag_account_boxes(company):
    print("→ afc_box sur les comptes de TVA (achat)…")
    for num, box in ACCOUNT_AFC.items():
        name = _acc(company, num)
        if name and frappe.db.exists("AFC VAT Box", box):
            frappe.db.set_value("Account", name, "afc_box", box)


def set_company_defaults(company):
    print("→ Comptes par defaut de la societe…")
    updates = {}
    for field, num in COMPANY_DEFAULTS.items():
        acc = _acc(company, num)
        if acc:
            updates[field] = acc
    if updates:
        frappe.db.set_value("Company", company, updates)


# Comptes techniques de l'inventaire PERPÉTUEL. SRBNB + EIIV = « reçu / engagé, PAS encore facturé »
# → passifs de régularisation (CO art. 958b, comptabilité d'exercice), rangés dans la famille 230.
# (num, nom, account_type ERPNext)
PERPETUAL_ACCOUNTS = [
    ("2301", "Marchandises reçues, non facturées", "Stock Received But Not Billed"),
    ("2302", "Frais accessoires inclus dans la valorisation", "Expenses Included In Valuation"),
]


def setup_perpetual_inventory(company):
    """Méthode d'inventaire PERPÉTUEL — le stock est le cœur de métier (négoce / revendeur).
    Le stock est valorisé EN TEMPS RÉEL : chaque réception l'entre (Dr 1200), chaque livraison en
    sort le coût (Dr 4200 COGS / Cr 1200). **Impact TVA : AUCUN** (la TVA reste sur les factures ;
    les mouvements de stock n'en portent pas). Voir doc §15 #10 + §20 (négoce/perpétuel).

    Pose :
      - 2 comptes techniques en **passif de régularisation** (famille 230, CO 958b) :
          **2301 SRBNB** « Marchandises reçues, non facturées » — tampon réception ↔ facture,
          **2302 EIIV** « Frais accessoires inclus dans la valorisation » — tampon landed cost ↔ facture ;
      - **active « Enable Perpetual Inventory »** + câble les comptes de stock de la société
          (1200 stock, 4208 ajustement, 2301 SRBNB).
    `account_type` posé sur 1200 (Stock) / 4208 (Stock Adjustment) pour qu'ERPNext les reconnaisse ;
    EIIV (2302) est trouvé par son `account_type` seul (pas de champ Company)."""
    print("→ Inventaire perpétuel (négoce)…")
    ref2300 = _acc(company, "2300")  # Passifs de régularisation → parent commun de 2301/2302
    parent = frappe.db.get_value("Account", ref2300, "parent_account") if ref2300 else None
    for num, name, atype in PERPETUAL_ACCOUNTS:
        if _acc_silent(company, num):
            continue
        if not parent:
            print(f"  ⚠️ parent (2300) introuvable — {num} non créé")
            continue
        doc = frappe.get_doc({"doctype": "Account", "company": company, "account_number": num,
                              "account_name": name, "account_type": atype, "parent_account": parent})
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)
        print(f"  ✓ {num} « {name} » créé ({atype})")
    # Comptes de stock reconnus par ERPNext via leur account_type
    stock = _acc(company, "1200")                                    # Stock In Hand
    adjust = _acc_silent(company, "4208") or _acc_silent(company, "4800")  # Stock Adjustment
    if stock:
        frappe.db.set_value("Account", stock, "account_type", "Stock")
    if adjust:
        frappe.db.set_value("Account", adjust, "account_type", "Stock Adjustment")
    # Activation + câblage société
    srbnb = _acc_silent(company, "2301")
    updates = {"enable_perpetual_inventory": 1}
    if stock:
        updates["default_inventory_account"] = stock
    if adjust:
        updates["stock_adjustment_account"] = adjust
    if srbnb:
        updates["stock_received_but_not_billed"] = srbnb
    frappe.db.set_value("Company", company, updates)
    print("  ✓ perpétuel activé (stock 1200, ajustement 4208/4800, SRBNB 2301, EIIV 2302)")


def set_erpnextswiss_settings(company):
    """Configure ERPNextSwiss Settings : compte intermediaire (compte d'attente) = 1099.
    Utilise par le Bank Wizard pour parquer les lignes bancaires non identifiees.
    NOTE : ERPNextSwiss Settings est un doctype GLOBAL (mono-instance) ; en multi-societe
    ce compte est partage — a arbitrer si plusieurs societes."""
    if not frappe.db.exists("DocType", "ERPNextSwiss Settings"):
        return  # erpnextswiss non installe
    acc = _acc(company, "1099")  # Compte d'attente pour des montants a clarifier
    if acc:
        frappe.db.set_single_value("ERPNextSwiss Settings", "intermediate_account", acc)
        print(f"→ ERPNextSwiss Settings : compte intermediaire = {acc}")


# Comptes multi-devises (créance/dette en EUR) — décision fiduciaire : CHF + EUR.
# Chacun est rangé sous le MÊME groupe que son homologue CHF (ref), avec account_currency = devise.
# NB : PAS de compte bancaire EUR (1021) par défaut — on considère que la société n'a qu'un
# compte bancaire CHF (1020) et paie/encaisse l'EUR via conversion bancaire (écart de change → 6999).
# À n'ajouter que si la société détient réellement un compte bancaire en EUR.
CURRENCY_ACCOUNTS = [
    # (numéro, nom, type, devise, compte CHF de référence pour le parent)
    ("1101", "Créances clients EUR",     "Receivable", "EUR", "1100"),
    ("2001", "Dettes fournisseurs EUR",  "Payable",    "EUR", "2000"),
]

# Compte de change LATENT (non réalisé) — requis par l'outil « Exchange Rate Revaluation ».
# Créé comme FRÈRE de 6999 « Gains de change » (même parent : Produits financiers), en CHF, SANS
# case AFC (le change n'a AUCUN impact TVA). Distinct de 6999 (réalisé) pour repérer/neutraliser
# les gains latents (prudence / réserve latente). Cf. doc §11.
UNREALIZED_FX = ("6998", "Différences de change non réalisées", "6999")


def set_accounting_settings():
    """Réglages GLOBAUX (doctypes mono-instance) :
    1. Accounts Settings.book_tax_discount_loss = 1 — ventilation TVA des escomptes.
       Sans ce flag, un escompte de paiement rapide passe EN TOTALITÉ sur le compte d'escompte
       (3800) sans reprendre la TVA. Avec le flag, ERPNext ventile automatiquement :
         - part nette → compte d'escompte (default_discount_account) ;
         - part TVA  → le compte de taxe de la facture (2200 en vente / impôt préalable en achat),
                       au prorata du % d'escompte → reprise TVA correcte au grand livre.
       L'escompte doit être appliqué via une Payment Terms Template (escompte paiement rapide),
       pas via une déduction manuelle. Voir doc §11/§15 #3.
    2. System Settings.rounding_method = "Commercial Rounding" — arrondi commercial (0.5 → au-dessus),
       conforme à la pratique suisse/AFC, plutôt que "Banker's Rounding" (0.5 → au pair le plus proche)
       qui n'est pas la convention suisse. N'affecte que les cas de demi-rappen.
    3. Accounts Settings.allow_stale = 1 — cours de change « périmés » autorisés. Notre modèle TVA
       s'appuie sur les cours mensuels moyens AFC : un cours daté du 1er du mois doit couvrir TOUT le
       mois (donc être « vieux » de 1 à 30 jours, volontairement). Si la case est décochée, ERPNext
       ajoute le filtre `date > transaction − stale_days` (défaut 1 jour) → le cours du 1er serait
       rejeté dès le 3 et ERPNext irait chercher un taux en ligne (Frankfurter / cours BCE) NON
       conforme AFC. On force donc allow_stale = 1. Cf. get_exchange_rate (erpnext/setup/utils.py).
    4. Currency Exchange Settings.disabled = 1 — coupe le fallback API en ligne. Les taux doivent
       provenir EXCLUSIVEMENT des cours AFC (importés dans Currency Exchange par erpnextswiss). En
       désactivant le provider en ligne, get_exchange_rate ne peut plus appeler Frankfurter/BCE : s'il
       manque un cours, il renvoie 0.00 et invite à créer un Currency Exchange manuellement (transaction
       bloquée = sûr) plutôt que de comptabiliser silencieusement un taux non conforme.
    5. Currency CHF (globale) : fraction = "centime" (au lieu de "Rappen[K]" — nom allemand + artefact
       de note de bas de page hérité du seed Frappe) et symbol = "CHF" (au lieu de "Fr") — conforme à
       une facturation suisse francophone / bexio. Purement cosmétique (montant en toutes lettres +
       affichage) ; n'affecte ni les montants ni la comptabilité. NB : Currency est un doctype GLOBAL."""
    frappe.db.set_single_value("Accounts Settings", "book_tax_discount_loss", 1)
    print("→ Accounts Settings : book_tax_discount_loss = 1 (ventilation TVA des escomptes)")
    frappe.db.set_single_value("System Settings", "rounding_method", "Commercial Rounding")
    print("→ System Settings : rounding_method = Commercial Rounding (arrondi commercial suisse)")
    frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)
    print("→ Accounts Settings : allow_stale = 1 (réutilise le cours mensuel AFC tout le mois)")
    if frappe.db.exists("DocType", "Currency Exchange Settings"):
        frappe.db.set_single_value("Currency Exchange Settings", "disabled", 1)
        print("→ Currency Exchange Settings : disabled = 1 (fallback API en ligne coupé — cours AFC only)")
    if frappe.db.exists("Currency", "CHF"):
        frappe.db.set_value("Currency", "CHF", {"fraction": "centime", "symbol": "CHF"})
        print("→ Currency CHF : fraction = centime, symbol = CHF (facturation suisse FR)")


def setup_currency_accounts(company):
    """Crée les comptes de créance/dette en devise (EUR) — idempotent.
    Nécessaires pour suivre créances/dettes en EUR et calculer l'écart de change au règlement.
    Pas de compte bancaire EUR : la société paie/encaisse l'EUR via son compte CHF (conversion)."""
    print("→ Comptes multi-devises (EUR)…")
    for num, name, atype, curr, ref in CURRENCY_ACCOUNTS:
        if _acc_silent(company, num):
            continue  # déjà présent → rien à faire (pas de warning parasite)
        ref_acc = _acc(company, ref)  # 1100/2000 : vrai lookup (warn justifié si absent)
        if not ref_acc:
            continue
        parent = frappe.db.get_value("Account", ref_acc, "parent_account")
        doc = frappe.get_doc({"doctype": "Account", "company": company, "account_number": num,
                              "account_name": name, "account_type": atype,
                              "account_currency": curr, "parent_account": parent})
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)
        print(f"  ✓ {num} « {name} » créé")


def setup_fx_revaluation_account(company):
    """Crée le compte de change LATENT (6998, frère de 6999 « Gains de change ») et le pose comme
    unrealized_exchange_gain_loss_account de la société. Sans ce compte, l'outil natif
    « Exchange Rate Revaluation » (réévaluation des postes ouverts en devise au bouclement) refuse
    de tourner (frappe.throw). Idempotent. Aucune case AFC (change = zéro impact TVA)."""
    print("→ Compte de change latent (réévaluation)…")
    num, name, ref = UNREALIZED_FX
    acc = _acc_silent(company, num)  # « existe déjà ? » sans warning
    if not acc:
        ref_acc = _acc(company, ref)   # 6999 « Gains de change » : vrai lookup
        if not ref_acc:
            return
        parent = frappe.db.get_value("Account", ref_acc, "parent_account")
        curr = frappe.get_value("Company", company, "default_currency")
        doc = frappe.get_doc({"doctype": "Account", "company": company, "account_number": num,
                              "account_name": name, "account_currency": curr,
                              "parent_account": parent})
        doc.flags.ignore_permissions = True
        doc.insert(ignore_if_duplicate=True)
        acc = _acc(company, num)
        print(f"  ✓ {num} « {name} » créé (frère de {ref})")
    if acc:
        frappe.db.set_value("Company", company, "unrealized_exchange_gain_loss_account", acc)
        print(f"  ✓ unrealized_exchange_gain_loss_account = {acc}")


def disable_unused_accounts(company):
    print("→ Desactivation des comptes non utilises (6949 - Option A change)…")
    for num in DISABLED_ACCOUNTS:
        name = _acc(company, num)
        if name and not frappe.db.get_value("Account", name, "disabled"):
            frappe.db.set_value("Account", name, "disabled", 1)


def setup_advance_accounts(company):
    print("→ Comptes d'acompte (Book Advance in Separate Party Account)…")
    updates = {"book_advance_payments_in_separate_party_account": 1}
    for field, (num, at) in ADVANCE_CONFIG.items():
        name = _acc(company, num)
        if not name:
            continue
        if frappe.db.get_value("Account", name, "account_type") != at:
            frappe.db.set_value("Account", name, "account_type", at)
        updates[field] = name
    frappe.db.set_value("Company", company, updates)


def cleanup_bank_accounts(company):
    """Garantit un compte banque CHF nomme « Banque CHF ». Le chart corrige cree deja 1020
    « Banque CHF » et n'inclut plus le placeholder « Bank »/1029 : cette etape ne sert donc qu'a
    MIGRER une societe creee avec l'ANCIEN chart, en renommant 1020. No-op silencieux (aucune
    sortie) pour une societe nee du chart corrige. Le renommage cascade tous les liens."""
    from erpnext.accounts.doctype.account.account import update_account_number
    num, target = BANK_CHF
    name = _acc(company, num)
    if name and frappe.db.get_value("Account", name, "account_name") != target:
        print("→ Compte banque CHF (migration ancien chart : 1020 → « Banque CHF »)…")
        update_account_number(name, target, num)   # renomme le libelle + cascade les liens
        print(f"  ✓ {num} renomme en « {target} »")


def setup_bank(company):
    """Seede la banque UBS (master global) et un compte bancaire d'entreprise rattache au compte
    1020 (banque CHF), marque « Is Default » + « Is Company Account » (requis pour le rapprochement
    bancaire). L'IBAN est laisse VIDE — a renseigner manuellement. Idempotent."""
    print("→ Banque & compte bancaire par defaut…")
    bank_name, bic = DEFAULT_BANK
    if not frappe.db.exists("Bank", bank_name):
        frappe.get_doc({"doctype": "Bank", "bank_name": bank_name,
                        "swift_number": bic}).insert(ignore_permissions=True)
        print(f"  ✓ Banque « {bank_name} » (BIC {bic}) creee")
    acc = _acc(company, BANK_CHF[0])   # 1020 - Banque CHF
    if not acc:
        return
    if frappe.db.exists("Bank Account", {"account_name": DEFAULT_BANK_ACCOUNT_NAME, "company": company}):
        return
    frappe.get_doc({
        "doctype": "Bank Account",
        "account_name": DEFAULT_BANK_ACCOUNT_NAME,
        "bank": bank_name,
        "account": acc,                # champ « Company Account » = compte GL 1020
        "is_default": 1,
        "is_company_account": 1,
        "company": company,
        # iban : volontairement vide (specifique a la societe, a renseigner manuellement)
    }).insert(ignore_permissions=True)
    print(f"  ✓ Compte bancaire « {DEFAULT_BANK_ACCOUNT_NAME} » (→ {acc}) cree — IBAN a renseigner")


def setup_modes_of_payment(company):
    """Modes de paiement : traduits en FR, seuls « Carte de crédit » et « Virement bancaire »
    actifs, tous deux mappes sur le compte banque CHF (1020) de la societe. Idempotent.
    NB : Mode of Payment est un master GLOBAL (renommage/activation valent pour tout le bench) ;
    le mapping du compte est par societe."""
    print("→ Modes de paiement (FR, banque CHF unique)…")
    # 1) renommage global EN → FR (idempotent). ⚠️ La collation MariaDB est accent-INSENSIBLE :
    #    frappe.db.exists("Chèque") renvoie "Cheque" -> un garde-fou `not exists(fr)` sauterait a
    #    tort le renommage accent-seul (Cheque -> Chèque). On lit donc le nom REELLEMENT stocke
    #    (get_value renvoie la casse/les accents reels) et on ne renomme que s'il differe exactement.
    for en, fr in MODE_RENAMES:
        current = frappe.db.get_value("Mode of Payment", en, "name")
        if current and current != fr:
            frappe.rename_doc("Mode of Payment", current, fr, force=True)
            print(f"  ✓ « {current} » → « {fr} »")
    # 2) activer les deux modes cibles, desactiver les autres (global)
    for mode in MODES_ENABLED:
        if frappe.db.exists("Mode of Payment", mode):
            frappe.db.set_value("Mode of Payment", mode, "enabled", 1)
    for mode in MODES_DISABLED:
        if frappe.db.exists("Mode of Payment", mode):
            frappe.db.set_value("Mode of Payment", mode, "enabled", 0)
    # 3) mapping compte banque (par societe) : les modes actifs pointent sur 1020, on retire les
    #    mappings de la societe sur les modes desactives (ex. Cash → 1000 devenu inutile)
    bank = _acc(company, BANK_CHF[0])
    if not bank:
        return
    for mode in MODES_ENABLED:
        if not frappe.db.exists("Mode of Payment", mode):
            continue
        doc = frappe.get_doc("Mode of Payment", mode)
        row = next((a for a in doc.accounts if a.company == company), None)
        if row and row.default_account != bank:
            row.default_account = bank
            doc.save(ignore_permissions=True)
        elif not row:
            doc.append("accounts", {"company": company, "default_account": bank})
            doc.save(ignore_permissions=True)
    for mode in MODES_DISABLED:
        if not frappe.db.exists("Mode of Payment", mode):
            continue
        doc = frappe.get_doc("Mode of Payment", mode)
        kept = [a for a in doc.accounts if a.company != company]
        if len(kept) != len(doc.accounts):
            doc.accounts = kept
            doc.save(ignore_permissions=True)


def create_company(company_name, abbr, currency="CHF"):
    """Cree une Company avec le plan comptable bexio (utilitaire de provisioning/test)."""
    if frappe.db.exists("Company", company_name):
        return company_name
    doc = frappe.get_doc({
        "doctype": "Company", "company_name": company_name, "abbr": abbr,
        "default_currency": currency, "country": "Switzerland",
        "chart_of_accounts": "Suisse - Plan comptable PME (Bexio) - FR",
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    frappe.db.commit()
    return company_name


# =============================================== ENTRY POINT ==================
def setup_company(company):
    if not frappe.db.exists("Company", company):
        frappe.throw(f"Societe '{company}' introuvable.")
    print(f"\n=== Configuration comptable/TVA (bexio) : {company} ===")
    cleanup_defaults(company)
    create_sales(company)
    create_purchase(company)
    create_reverse_charge(company)
    create_items(company)
    tag_account_boxes(company)
    set_company_defaults(company)
    setup_perpetual_inventory(company)
    set_erpnextswiss_settings(company)
    set_accounting_settings()
    setup_currency_accounts(company)
    setup_fx_revaluation_account(company)
    cleanup_bank_accounts(company)
    setup_bank(company)
    setup_modes_of_payment(company)
    disable_unused_accounts(company)
    setup_advance_accounts(company)
    frappe.db.commit()
    n_purch = len(PURCHASE) + len(REVERSE)
    print(f"=== Termine pour {company} : {len(SALES)} sales, {n_purch} purchase "
          f"({len(REVERSE)} reverse charge), {len(ITEMS)} item templates. ===")
    print("\n" + "!" * 78)
    print("!!  ACTIONS MANUELLES REQUISES avant utilisation (voir doc §18) :")
    print(f"!!   1. Banque « {DEFAULT_BANK[0]} » : vérifier / compléter le BIC (BIC complet UBS = UBSWCHZH80A).")
    print(f"!!   2. Compte bancaire « {DEFAULT_BANK_ACCOUNT_NAME} » : RENSEIGNER L'IBAN de la société,")
    print("!!      puis vérifier la banque et le compte rattachés.")
    print("!!   3. Renseigner le compte de tiers des fournisseurs/clients en devise (EUR → 2001 / 1101).")
    print("!!   4. Renommer les comptes génériques du plan si besoin (banques, etc.).")
    print("!" * 78 + "\n")
    return "OK"
