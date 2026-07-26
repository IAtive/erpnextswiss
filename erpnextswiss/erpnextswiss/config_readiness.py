# -*- coding: utf-8 -*-
# Copyright (c) 2026, Kramdi and contributors
"""Contrôle de configuration ERPNextSwiss (par société).

Vérifie que la société ET les données qu'elle crée (comptes bancaires, clients,
fournisseurs, paramètres) sont correctement configurés pour que fonctionnent :
la QR-facture, le rapprochement bancaire (camt), l'e-facturation (EN 16931), la
génération des paiements (pain.001) et la facturation multidevises.

Modèle calqué sur le contrôle de plausibilité TVA : `collect(company)` renvoie une
liste plate de « rows » {group, entity, check, status, impact}, consommée par le
Script Report « Configuration Readiness ». Chaque contrôle porte un message
d'IMPACT expliquant ce qui ne fonctionnera pas s'il n'est pas configuré.

CONTEXTUEL : on ne signale que ce que la société UTILISE (méthode QRR active,
tiers en devise, ALYF installé, e-invoice disponible) -> évite les fausses alertes.
Extensible : ajouter un contrôle = ajouter un `_row(...)`.
"""
import frappe
from frappe import _

OK = "✅ OK"
KO = "❌ Anomalie"
WARN = "⚠️ À vérifier"
NA = "➖ Non applicable"

# domaines (regroupement par entité, comme demandé pour l'écran)
G_COMPANY = "1 · Société"
G_BANK = "2 · Comptes bancaires"
G_PARTY_ACC = "3 · Comptes de tiers (devises)"
G_CUSTOMER = "4 · Clients"
G_SUPPLIER = "5 · Fournisseurs"
G_SETTINGS = "6 · Paramètres"
G_FX = "7 · Change (cours AFC)"

_CAP = 50  # nombre max de contrevenants listés par contrôle


def _form_url(doctype, name):
    """URL du formulaire de l'enregistrement en cause (vide si pas de cible)."""
    if not doctype:
        return ""
    slug = doctype.lower().replace(" ", "-")
    try:
        single = bool(frappe.get_meta(doctype).issingle)
    except Exception:
        single = False
    if single or not name:
        return "/app/" + slug
    from urllib.parse import quote
    return "/app/%s/%s" % (slug, quote(str(name)))


def _row(group, entity, check, status, impact="", link_dt=None, link_name=None):
    return {"group": group, "entity": entity, "check": check, "status": status,
            "impact": impact, "link_url": _form_url(link_dt, link_name)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _primary_address(doctype, name):
    """Retourne le doc Address (primaire de préférence) lié au tiers, ou None."""
    rows = frappe.db.sql(
        """SELECT dl.parent AS addr, a.is_primary_address
             FROM `tabDynamic Link` dl
             JOIN `tabAddress` a ON a.name = dl.parent
            WHERE dl.link_doctype = %s AND dl.link_name = %s AND dl.parenttype = 'Address'
         ORDER BY a.is_primary_address DESC LIMIT 1""",
        (doctype, name), as_dict=True,
    )
    return frappe.get_doc("Address", rows[0].addr) if rows else None


def _address_complete(addr):
    """Adresse structurée complète (rue, NPA, localité, pays)."""
    return bool(addr and addr.get("address_line1") and addr.get("pincode")
                and addr.get("city") and addr.get("country"))


def _is_foreign(addr):
    """Adresse hors Suisse (pays renseigné et != Suisse)."""
    return bool(addr and addr.get("country") and addr.get("country") != "Switzerland")


def _is_qr_iban(iban):
    try:
        from erpnextswiss.swiss_qr.validation import is_qr_iban
        return is_qr_iban(iban)
    except Exception:
        return False


def _valid_swiss_uid(uid):
    """Valide un UID suisse avec clé de contrôle (si eu_einvoice présent)."""
    if not uid:
        return False
    try:
        from eu_einvoice.switzerland import is_valid_swiss_vat_id
        return bool(is_valid_swiss_vat_id(uid))
    except Exception:
        # repli : format CHE + 9 chiffres (sans contrôle de clé)
        import re
        return bool(re.match(r"^CHE\d{9}$", (uid or "").replace(" ", "").replace(".", "").replace("-", "").upper()[:12]))


def _app_installed(app):
    return app in frappe.get_installed_apps()


# ---------------------------------------------------------------------------
# Contrôles par domaine
# ---------------------------------------------------------------------------
def _check_company(company, ctx, rows):
    c = frappe.get_doc("Company", company)
    L = ("Company", company)   # cible de lien commune à ce bloc

    # compte de réception
    if not c.get("default_bank_account"):
        rows.append(_row(G_COMPANY, company, "Compte bancaire par défaut", KO,
                         "La QR-facture, le fichier pain.001 et la e-facture ne peuvent pas être générés "
                         "(compte de réception manquant).", *L))
    else:
        rows.append(_row(G_COMPANY, company, "Compte bancaire par défaut", OK, "", *L))

    # adresse société
    addr = _primary_address("Company", company)
    if not _address_complete(addr):
        rows.append(_row(G_COMPANY, company, "Adresse société complète", KO,
                         "Le débiteur du pain.001 et le créancier de la QR-facture seront incomplets → "
                         "fichiers de paiement / bulletins QR rejetés.",
                         "Address", addr.name if addr else None) if addr
                    else _row(G_COMPANY, company, "Adresse société complète", KO,
                              "Aucune adresse liée à la société → pain.001 et QR-facture rejetés.", *L))
    else:
        rows.append(_row(G_COMPANY, company, "Adresse société complète", OK, "", "Address", addr.name))

    # devise de la société
    if c.get("default_currency") != "CHF":
        rows.append(_row(G_COMPANY, company, "Devise de la société = CHF", WARN,
                         "La devise de la société n'est pas CHF : cela fausse le périmètre des contrôles "
                         "multidevises et la comptabilité de référence.", *L))
    else:
        rows.append(_row(G_COMPANY, company, "Devise de la société = CHF", OK, "", *L))

    # comptes de tiers par défaut
    if not (c.get("default_receivable_account") and c.get("default_payable_account")):
        rows.append(_row(G_COMPANY, company, "Comptes clients/fournisseurs par défaut", KO,
                         "La création de factures sera bloquée (compte de créance/dette par défaut manquant).", *L))
    else:
        rows.append(_row(G_COMPANY, company, "Comptes clients/fournisseurs par défaut", OK, "", *L))

    # change (si la société utilise des devises)
    if ctx["uses_fx"]:
        if not c.get("exchange_gain_loss_account"):
            rows.append(_row(G_COMPANY, company, "Compte de gain/perte de change", KO,
                             "Les paiements en devise ne pourront pas comptabiliser l'écart de change "
                             "(soumission du Payment Entry bloquée).", *L))
        else:
            rows.append(_row(G_COMPANY, company, "Compte de gain/perte de change", OK, "", *L))
        # réévaluation de change (change latent, compte 6998)
        if not c.get("unrealized_exchange_gain_loss_account"):
            rows.append(_row(G_COMPANY, company, "Compte de change latent (réévaluation)", KO,
                             "L'outil de réévaluation de change (change latent) refusera de tourner "
                             "(compte de change non réalisé / 6998 manquant).", *L))
        else:
            rows.append(_row(G_COMPANY, company, "Compte de change latent (réévaluation)", OK, "", *L))

    # e-invoice (si eu_einvoice installé)
    if ctx["uses_einvoice"]:
        if not _valid_swiss_uid(c.get("tax_id")):
            rows.append(_row(G_COMPANY, company, "N° TVA (UID) valide", KO,
                             "L'e-facture sera REJETÉE : identifiant TVA du vendeur manquant/invalide "
                             "(règle EN 16931 BR-CO-26). Format attendu : CHE-123.456.789 MWST (clé valide).", *L))
        else:
            rows.append(_row(G_COMPANY, company, "N° TVA (UID) valide", OK, "", *L))


def _check_bank_accounts(company, ctx, rows):
    # compte GL de réception (QR / pain.001)
    gl = frappe.db.get_value("Company", company, "default_bank_account")
    if gl:
        acc = frappe.db.get_value("Account", gl, ["iban", "bic", "qr_method", "qr_iban"], as_dict=True)
        label = gl
        A = ("Account", gl)   # cible de lien
        if not acc.iban:
            rows.append(_row(G_BANK, label, "IBAN classique du compte de réception", KO,
                             "pain.001 (« IBAN missing in pay from account »), e-facture et QR SCOR/NON "
                             "ne pourront pas indiquer votre IBAN.", *A))
        elif _is_qr_iban(acc.iban):
            rows.append(_row(G_BANK, label, "IBAN classique du compte de réception", KO,
                             "Le champ IBAN contient une QR-IBAN : le débiteur du pain.001 sera invalide. "
                             "Mettez la QR-IBAN dans le champ QR-IBAN.", *A))
        else:
            rows.append(_row(G_BANK, label, "IBAN classique du compte de réception", OK, "", *A))

        if not acc.bic:
            rows.append(_row(G_BANK, label, "BIC du compte de réception", KO,
                             "La génération du pain.001 échouera (« missing IBAN and/or BIC »).", *A))
        else:
            rows.append(_row(G_BANK, label, "BIC du compte de réception", OK, "", *A))

        # méthode QR + QR-IBAN si QRR
        if (acc.qr_method or "SCOR") == "QRR":
            if not acc.qr_iban or not _is_qr_iban(acc.qr_iban):
                rows.append(_row(G_BANK, label, "QR-IBAN valide (méthode QRR)", KO,
                                 "La QR-facture QRR ne peut pas être émise : QR-IBAN manquante ou hors "
                                 "plage institution 30000-31999.", *A))
            else:
                rows.append(_row(G_BANK, label, "QR-IBAN valide (méthode QRR)", OK, "", *A))

    # Bank Account (doctype) pour le routage camt (si réconciliation via ALYF)
    if ctx["uses_reconcile"]:
        cba = frappe.get_all("Bank Account", filters={"company": company, "is_company_account": 1},
                             fields=["name", "iban", "account"])
        if not cba:
            rows.append(_row(G_BANK, company, "Compte bancaire de société (Bank Account)", KO,
                             "L'import de relevés camt ne pourra router aucun mouvement "
                             "(aucun Bank Account « compte de société »).", "Company", company))
        for ba in cba:
            B = ("Bank Account", ba.name)
            if not ba.iban:
                rows.append(_row(G_BANK, ba.name, "IBAN du Bank Account (routage camt)", KO,
                                 "Les relevés camt de ce compte seront ignorés (« No Bank Account found for IBAN »).", *B))
            if not ba.account:
                rows.append(_row(G_BANK, ba.name, "Compte GL lié au Bank Account", KO,
                                 "Les transactions importées n'auront pas de devise (compte GL non lié).", *B))
            if ba.iban and ba.account:
                rows.append(_row(G_BANK, ba.name, "Bank Account (IBAN + compte GL)", OK, "", *B))


def _check_settings(company, ctx, rows):
    if frappe.db.exists("DocType", "ERPNextSwiss Settings"):
        s = frappe.get_single("ERPNextSwiss Settings")
        E = ("ERPNextSwiss Settings", None)
        if s.get("xml_version") != "09":
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Version pain.001 = 09", KO,
                             "Vos fichiers de paiement utilisent des adresses combinées (type K), "
                             "RETIRÉES par SIX (nov. 2025) → rejetés par la banque. Passez en version 09.", *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Version pain.001 = 09", OK, "", *E))
        if not s.get("validate_xml"):
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Validation XML pain.001", WARN,
                             "Un pain.001 non conforme ne sera détecté qu'après rejet par la banque "
                             "(activez « Validate XML »).", *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Validation XML pain.001", OK, "", *E))
        if not s.get("planning_days"):
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Période de planification (Payment Proposal)", WARN,
                             "La création d'une proposition de paiement échouera "
                             "(« Please configure the planning period in ERPNextSwiss Settings »).", *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", "Période de planification (Payment Proposal)", OK, "", *E))

    # change AFC
    if ctx["uses_fx"]:
        A = ("Accounts Settings", None)
        if frappe.db.get_single_value("Accounts Settings", "allow_stale") != 1:
            rows.append(_row(G_SETTINGS, "Accounts Settings", "Cours de change périmés autorisés", WARN,
                             "Le cours mensuel AFC du 1er sera rejeté en cours de mois → ERPNext ira "
                             "chercher un cours en ligne NON conforme AFC (activez « allow stale »).", *A))
        else:
            rows.append(_row(G_SETTINGS, "Accounts Settings", "Cours de change périmés autorisés", OK, "", *A))

    # matching ALYF
    if ctx["uses_reconcile"] and frappe.db.exists("DocType", "Banking Reference Mapping"):
        refs = {r.document_type: r.field_name
                for r in frappe.get_single("Banking Settings").get("reference_fields", [])}
        B = ("Banking Settings", None)
        if refs.get("Sales Invoice") != "qr_reference" or refs.get("Purchase Invoice") != "esr_reference_number":
            rows.append(_row(G_SETTINGS, "Banking Settings", "Mapping de référence (matching auto)", WARN,
                             "Les encaissements/décaissements ne se rapprocheront pas automatiquement par "
                             "la référence QR (mapping SI→qr_reference / PI→esr_reference_number manquant).", *B))
        else:
            rows.append(_row(G_SETTINGS, "Banking Settings", "Mapping de référence (matching auto)", OK, "", *B))


def _check_customers(company, ctx, rows):
    # règle demandée : client avec ADRESSE ÉTRANGÈRE mais devise absente OU CHF -> avertissement
    foreign_no_ccy, ccy_no_account, no_address = [], [], []
    for cust in frappe.get_all("Customer", fields=["name", "customer_name", "default_currency"]):
        disp = cust.customer_name or cust.name
        addr = _primary_address("Customer", cust.name)
        # adresse de facturation absente (bloquant pour l'e-facture : BR-10/11)
        if ctx["uses_einvoice"] and not addr:
            no_address.append((disp, cust.name))
        if _is_foreign(addr) and (not cust.default_currency or cust.default_currency == "CHF"):
            foreign_no_ccy.append((disp, cust.name))
        # client en devise étrangère : compte de créance dédié requis
        if cust.default_currency and cust.default_currency != "CHF":
            if not ctx["multi_ccy_single_account"] and not _party_has_account(
                    "Customer", cust.name, company, cust.default_currency):
                ccy_no_account.append(("%s (%s)" % (disp, cust.default_currency), cust.name))

    if ctx["uses_einvoice"]:
        _emit_offenders(rows, G_CUSTOMER, "Adresse de facturation présente", no_address, WARN,
                        "Sans adresse, l'e-facture sera REJETÉE (adresse acheteur obligatoire, EN 16931 "
                        "BR-10/11) et le bloc « payable par » de la QR-facture restera vide.", "Customer")
    _emit_offenders(rows, G_CUSTOMER, "Client étranger avec devise manquante/CHF", foreign_no_ccy, WARN,
                    "Client à l'étranger sans devise de facturation étrangère : les factures en devise et "
                    "l'e-facturation risquent d'être mal libellées (vérifiez la devise du client).", "Customer")
    _emit_offenders(rows, G_CUSTOMER, "Compte de créance en devise", ccy_no_account, KO,
                    "Facture client dans cette devise BLOQUÉE : aucun compte de créance dans la devise "
                    "(onglet Comptabilité du client) et « multidevises sur compte unique » désactivé.", "Customer")


def _check_suppliers(company, ctx, rows):
    foreign_no_ccy, ccy_no_account, no_iban, no_address = [], [], [], []
    # l'IBAN fournisseur se lit sur le champ Supplier.iban (utilisé par le Payment
    # Proposal), avec en repli un Bank Account lié au fournisseur.
    meta = frappe.get_meta("Supplier")
    has_iban_field = bool(meta.get_field("iban"))
    has_country_field = bool(meta.get_field("country"))
    fields = ["name", "supplier_name", "default_currency"]
    if has_iban_field:
        fields.append("iban")
    if has_country_field:
        fields.append("country")
    for sup in frappe.get_all("Supplier", fields=fields):
        disp = sup.supplier_name or sup.name
        addr = _primary_address("Supplier", sup.name)
        # adresse de facturation absente (créancier pain.001 + e-facture d'achat)
        if not addr:
            no_address.append((disp, sup.name))
        # étranger = pays de la FICHE ≠ Suisse, OU adresse étrangère (le fournisseur
        # peut avoir son pays sur la fiche sans adresse complète).
        foreign = (sup.get("country") and sup.get("country") != "Switzerland") or _is_foreign(addr)
        if foreign and (not sup.default_currency or sup.default_currency == "CHF"):
            foreign_no_ccy.append((disp, sup.name))
        if sup.default_currency and sup.default_currency != "CHF":
            if not ctx["multi_ccy_single_account"] and not _party_has_account(
                    "Supplier", sup.name, company, sup.default_currency):
                ccy_no_account.append(("%s (%s)" % (disp, sup.default_currency), sup.name))
        # IBAN (paiement pain.001) — Supplier.iban, sinon un Bank Account lié
        if not sup.get("iban") and not frappe.db.exists(
                "Bank Account", {"party_type": "Supplier", "party": sup.name}):
            no_iban.append((disp, sup.name))

    _emit_offenders(rows, G_SUPPLIER, "Adresse de facturation présente", no_address, WARN,
                    "Sans adresse, ce fournisseur ne peut pas être payé par pain.001 (créancier sans "
                    "adresse → fichier rejeté par la banque) et l'e-facture d'achat sera incomplète.", "Supplier")
    _emit_offenders(rows, G_SUPPLIER, "Fournisseur étranger avec devise manquante/CHF", foreign_no_ccy, WARN,
                    "Fournisseur à l'étranger sans devise étrangère : les factures/paiements en devise "
                    "risquent d'être mal libellés (vérifiez la devise du fournisseur).", "Supplier")
    _emit_offenders(rows, G_SUPPLIER, "Compte de dette en devise", ccy_no_account, KO,
                    "Facture fournisseur dans cette devise BLOQUÉE : aucun compte de dette dans la devise "
                    "(onglet Comptabilité du fournisseur).", "Supplier")
    if ctx["uses_payments"]:
        _emit_offenders(rows, G_SUPPLIER, "IBAN fournisseur (paiement pain.001)", no_iban, WARN,
                        "Ce fournisseur ne pourra pas être payé par fichier pain.001 (aucun IBAN renseigné).",
                        "Supplier")


def _check_modes_of_payment(company, rows):
    """Chaque mode de paiement ACTIVÉ doit avoir un compte par défaut pour la société.
    Non bloquant (⚠️) : impacte seulement la création manuelle de Payment Entry via ce mode."""
    if not frappe.db.exists("DocType", "Mode of Payment"):
        return
    has_enabled = bool(frappe.get_meta("Mode of Payment").get_field("enabled"))
    filters = {"enabled": 1} if has_enabled else {}
    offenders = []
    for mop in frappe.get_all("Mode of Payment", filters=filters, pluck="name"):
        has_acc = frappe.db.sql(
            """SELECT 1 FROM `tabMode of Payment Account`
                WHERE parent=%s AND company=%s AND IFNULL(default_account,'')<>'' LIMIT 1""",
            (mop, company))
        if not has_acc:
            offenders.append((mop, mop))
    _emit_offenders(rows, G_SETTINGS, "Compte par défaut du mode de paiement", offenders, WARN,
                    "Ce mode de paiement (activé) n'a pas de compte par défaut pour cette société → "
                    "la création d'un paiement via ce mode exigera de choisir le compte à la main.",
                    "Mode of Payment")


def _foreign_party_currencies():
    """Ensemble des devises (≠ CHF) utilisées par les clients/fournisseurs."""
    curr = set()
    for dt in ("Customer", "Supplier"):
        for r in frappe.get_all(dt, filters={"default_currency": ["not in", ["", "CHF"]]},
                                fields=["default_currency"], distinct=True):
            if r.default_currency:
                curr.add(r.default_currency)
    return curr


def _check_exchange_rates(company, ctx, rows):
    """Cours de change AFC : disponibilité par devise + config de l'import automatique."""
    if not ctx["uses_fx"]:
        return
    curr = _foreign_party_currencies()

    # 1) un cours (Currency Exchange) existe-t-il pour chaque devise des tiers ?
    for ccy in sorted(curr):
        has_rate = (frappe.db.exists("Currency Exchange", {"from_currency": ccy, "to_currency": "CHF"})
                    or frappe.db.exists("Currency Exchange", {"from_currency": "CHF", "to_currency": ccy}))
        if not has_rate:
            rows.append(_row(G_FX, ccy, "Cours de change disponible", KO,
                             "Aucun cours %s↔CHF : toute facture en %s sera BLOQUÉE (cours 0.00, "
                             "fallback en ligne coupé). Importez les cours AFC." % (ccy, ccy)))
        else:
            rows.append(_row(G_FX, ccy, "Cours de change disponible", OK))

    # 2) Swiss Exchange Rate Settings (import automatique des cours AFC)
    if not frappe.db.exists("DocType", "Swiss Exchange Rate Settings"):
        return
    s = frappe.get_single("Swiss Exchange Rate Settings")
    S = ("Swiss Exchange Rate Settings", None)

    if not s.get("enabled"):
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Import automatique des cours AFC activé", WARN,
                         "L'import automatique des cours AFC est désactivé → les cours ne se mettent pas à "
                         "jour tout seuls (risque de cours périmés/manquants).", *S))
        return
    rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Import automatique des cours AFC activé", OK, "", *S))

    # devise cible = CHF
    if s.get("target_currency") != "CHF":
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Devise cible = CHF", WARN,
                         "La devise cible de l'import n'est pas CHF (config à revoir).", *S))
    else:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Devise cible = CHF", OK, "", *S))

    # couverture : toutes les devises des tiers sont-elles récupérées ?
    configured = {r.currency for r in s.get("currencies", [])}
    missing = sorted(curr - configured)
    if missing:
        rows.append(_row(G_FX, ", ".join(missing), "Devises des tiers couvertes par l'import", WARN,
                         "Ces devises utilisées par vos tiers ne sont PAS récupérées automatiquement : %s. "
                         "Ajoutez-les à la liste des devises de l'import." % ", ".join(missing), *S))
    else:
        rows.append(_row(G_FX, "—", "Devises des tiers couvertes par l'import", OK, "", *S))

    # dernier run récent (fraîcheur selon la fréquence configurée)
    _check_last_run(s, rows, S)


def _check_last_run(s, rows, S):
    from frappe.utils import now_datetime, get_datetime
    last = s.get("last_run")
    if not last:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Dernier import exécuté", WARN,
                         "L'import des cours n'a JAMAIS été exécuté (aucun « last run »).", *S))
        return
    freq = s.get("frequency") or "Daily"
    max_h = {"Daily": 26, "Weekly": 8 * 24, "Monthly": 35 * 24}.get(freq, 26)
    age_h = (now_datetime() - get_datetime(last)).total_seconds() / 3600.0
    if age_h > max_h:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Dernier import récent", WARN,
                         "Dernier import il y a %.0f h (attendu ≤ %.0f h pour une fréquence %s) → "
                         "le planificateur ne tourne peut-être plus." % (age_h, max_h, freq), *S))
    else:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Dernier import récent (%.0f h)" % age_h,
                         OK, "", *S))
    # statut du dernier import
    st = (s.get("last_status") or "")
    if st and not any(k in st.lower() for k in ("ok", "success", "succ", "✅")):
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", "Statut du dernier import", WARN,
                         "Le dernier import n'est pas OK : %s" % st, *S))


def _party_has_account(party_type, party, company, currency):
    """Le tiers a-t-il un compte de tiers dans la devise voulue pour cette société ?"""
    accounts = frappe.db.sql(
        """SELECT account FROM `tabParty Account`
            WHERE parenttype=%s AND parent=%s AND company=%s""",
        (party_type, party, company), as_dict=True,
    )
    for a in accounts:
        if a.account and frappe.db.get_value("Account", a.account, "account_currency") == currency:
            return True
    return False


def _emit_offenders(rows, group, check, offenders, status, impact, link_dt=None):
    """Une row par contrevenant (capée) ; sinon une row OK de synthèse.
    offenders : liste de tuples (libellé_affiché, nom_du_doc)."""
    if offenders:
        for display, docname in offenders[:_CAP]:
            rows.append(_row(group, display, check, status, impact, link_dt, docname))
        if len(offenders) > _CAP:
            rows.append(_row(group, "… +%d autres" % (len(offenders) - _CAP), check, status, impact))
    else:
        rows.append(_row(group, "—", check, OK))


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------
def _context(company):
    """Détecte ce que la société UTILISE, pour ne contrôler que le pertinent."""
    uses_reconcile = _app_installed("banking")
    uses_einvoice = _app_installed("eu_einvoice")
    # devises : un tiers en devise != CHF, ou un compte GL en devise != CHF
    uses_fx = bool(frappe.get_all("Customer", filters={"default_currency": ["not in", ["", "CHF"]]}, limit=1)
                   or frappe.get_all("Supplier", filters={"default_currency": ["not in", ["", "CHF"]]}, limit=1))
    multi = frappe.db.get_single_value("Accounts Settings",
                                       "allow_multi_currency_invoices_against_single_party_account") == 1
    return {
        "uses_reconcile": uses_reconcile,
        "uses_einvoice": uses_einvoice,
        "uses_fx": uses_fx,
        "uses_payments": True,  # pain.001 = core ERPNextSwiss
        "multi_ccy_single_account": multi,
    }


@frappe.whitelist()
def collect(company):
    """Renvoie la liste plate des contrôles {group, entity, check, status, impact}."""
    if not company:
        return []
    ctx = _context(company)
    rows = []
    _check_company(company, ctx, rows)
    _check_bank_accounts(company, ctx, rows)
    _check_party_accounts_settings(company, ctx, rows)
    _check_customers(company, ctx, rows)
    _check_suppliers(company, ctx, rows)
    _check_exchange_rates(company, ctx, rows)
    _check_modes_of_payment(company, rows)
    _check_settings(company, ctx, rows)
    return rows


def _check_party_accounts_settings(company, ctx, rows):
    """Info sur l'option multidevises globale (contexte des comptes de tiers)."""
    if ctx["uses_fx"]:
        A = ("Accounts Settings", None)
        if ctx["multi_ccy_single_account"]:
            rows.append(_row(G_PARTY_ACC, "Accounts Settings",
                             "Multidevises sur compte de tiers unique", OK,
                             "Activé : un compte CHF unique peut porter des factures en devise "
                             "(comptes de tiers par devise non obligatoires).", *A))
        else:
            rows.append(_row(G_PARTY_ACC, "Accounts Settings",
                             "Multidevises sur compte de tiers unique", WARN,
                             "Désactivé : chaque tiers en devise DOIT avoir un compte de créance/dette "
                             "dans sa devise, sinon ses factures seront bloquées.", *A))
