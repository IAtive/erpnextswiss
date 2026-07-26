# -*- coding: utf-8 -*-
# Copyright (c) 2026, Kramdi and contributors
"""ERPNextSwiss configuration readiness check (per company).

Verifies that the company AND the data it creates (bank accounts, customers,
suppliers, settings) are correctly configured so that the following work:
QR-bill, bank reconciliation (camt), e-invoicing (EN 16931), payment file
generation (pain.001) and multi-currency invoicing.

Mirrors the VAT plausibility control: `collect(company)` returns a flat list of
rows {group, entity, check, status, impact}, consumed by the Script Report
« Controle de configuration ». Each check carries an IMPACT message explaining
what will NOT work if it is misconfigured.

Strings are English SOURCES wrapped in _() (translated fr/de/it via locale/*.po).
`group` and `status` are STABLE keys (used for logic/ordering) translated only at
display time by the report. CONTEXTUAL: only what the company USES is checked
(active QRR method, foreign-currency parties, ALYF installed, e-invoice available)
-> avoids false alarms. Extensible: add a check = add a `_row(...)`.
"""
import frappe
from frappe import _

# statuts : clés stables (préfixe emoji = repère indépendant de la langue pour la
# logique de tri/coloration) ; le TEXTE est traduit à l'affichage par le rapport.
OK = "✅ OK"
KO = "❌ Issue"
WARN = "⚠️ Check"
NA = "➖ N/A"

# domaines (regroupement par entité) — clés stables, traduites à l'affichage
G_COMPANY = "1 · Company"
G_BANK = "2 · Bank accounts"
G_PARTY_ACC = "3 · Party accounts (currencies)"
G_CUSTOMER = "4 · Customers"
G_SUPPLIER = "5 · Suppliers"
G_FX = "6 · Exchange rates (FTA)"
G_SETTINGS = "7 · Settings"

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
    return bool(addr and addr.get("address_line1") and addr.get("pincode")
                and addr.get("city") and addr.get("country"))


def _is_foreign(addr):
    return bool(addr and addr.get("country") and addr.get("country") != "Switzerland")


def _is_qr_iban(iban):
    try:
        from erpnextswiss.swiss_qr.validation import is_qr_iban
        return is_qr_iban(iban)
    except Exception:
        return False


def _valid_swiss_uid(uid):
    if not uid:
        return False
    try:
        from eu_einvoice.switzerland import is_valid_swiss_vat_id
        return bool(is_valid_swiss_vat_id(uid))
    except Exception:
        import re
        return bool(re.match(r"^CHE\d{9}$",
                             (uid or "").replace(" ", "").replace(".", "").replace("-", "").upper()[:12]))


def _app_installed(app):
    return app in frappe.get_installed_apps()


# ---------------------------------------------------------------------------
# Contrôles par domaine
# ---------------------------------------------------------------------------
def _check_company(company, ctx, rows):
    c = frappe.get_doc("Company", company)
    L = ("Company", company)

    if not c.get("default_bank_account"):
        rows.append(_row(G_COMPANY, company, _("Default bank account"), KO,
                         _("The QR-bill, the pain.001 file and the e-invoice cannot be generated "
                           "(receiving account missing)."), *L))
    else:
        rows.append(_row(G_COMPANY, company, _("Default bank account"), OK, "", *L))

    addr = _primary_address("Company", company)
    if not _address_complete(addr):
        if addr:
            rows.append(_row(G_COMPANY, company, _("Company address complete"), KO,
                             _("The pain.001 debtor and the QR-bill creditor will be incomplete → "
                               "payment files / QR-bills rejected."), "Address", addr.name))
        else:
            rows.append(_row(G_COMPANY, company, _("Company address complete"), KO,
                             _("No address linked to the company → pain.001 and QR-bill rejected."), *L))
    else:
        rows.append(_row(G_COMPANY, company, _("Company address complete"), OK, "", "Address", addr.name))

    if c.get("default_currency") != "CHF":
        rows.append(_row(G_COMPANY, company, _("Company currency = CHF"), WARN,
                         _("The company currency is not CHF: this distorts the scope of the "
                           "multi-currency checks and the base accounting."), *L))
    else:
        rows.append(_row(G_COMPANY, company, _("Company currency = CHF"), OK, "", *L))

    if not (c.get("default_receivable_account") and c.get("default_payable_account")):
        rows.append(_row(G_COMPANY, company, _("Default receivable/payable accounts"), KO,
                         _("Invoice creation will be blocked (default receivable/payable account missing)."), *L))
    else:
        rows.append(_row(G_COMPANY, company, _("Default receivable/payable accounts"), OK, "", *L))

    if ctx["uses_fx"]:
        if not c.get("exchange_gain_loss_account"):
            rows.append(_row(G_COMPANY, company, _("Exchange gain/loss account"), KO,
                             _("Foreign-currency payments cannot book the exchange difference "
                               "(Payment Entry submission blocked)."), *L))
        else:
            rows.append(_row(G_COMPANY, company, _("Exchange gain/loss account"), OK, "", *L))
        if not c.get("unrealized_exchange_gain_loss_account"):
            rows.append(_row(G_COMPANY, company, _("Unrealized exchange account (revaluation)"), KO,
                             _("The exchange rate revaluation tool will refuse to run (unrealized "
                               "exchange gain/loss account / 6998 missing)."), *L))
        else:
            rows.append(_row(G_COMPANY, company, _("Unrealized exchange account (revaluation)"), OK, "", *L))

    if ctx["uses_einvoice"]:
        if not _valid_swiss_uid(c.get("tax_id")):
            rows.append(_row(G_COMPANY, company, _("Valid VAT number (UID)"), KO,
                             _("The e-invoice will be REJECTED: seller VAT identifier missing/invalid "
                               "(EN 16931 rule BR-CO-26). Expected format: CHE-123.456.789 MWST (valid check digit)."), *L))
        else:
            rows.append(_row(G_COMPANY, company, _("Valid VAT number (UID)"), OK, "", *L))


def _check_bank_accounts(company, ctx, rows):
    gl = frappe.db.get_value("Company", company, "default_bank_account")
    if gl:
        acc = frappe.db.get_value("Account", gl, ["iban", "bic", "qr_method", "qr_iban"], as_dict=True)
        A = ("Account", gl)
        if not acc.iban:
            rows.append(_row(G_BANK, gl, _("Regular IBAN of the receiving account"), KO,
                             _("pain.001 (« IBAN missing in pay from account »), e-invoice and QR SCOR/NON "
                               "cannot show your IBAN."), *A))
        elif _is_qr_iban(acc.iban):
            rows.append(_row(G_BANK, gl, _("Regular IBAN of the receiving account"), KO,
                             _("The IBAN field contains a QR-IBAN: the pain.001 debtor will be invalid. "
                               "Put the QR-IBAN in the QR-IBAN field."), *A))
        else:
            rows.append(_row(G_BANK, gl, _("Regular IBAN of the receiving account"), OK, "", *A))

        if not acc.bic:
            rows.append(_row(G_BANK, gl, _("BIC of the receiving account"), KO,
                             _("pain.001 generation will fail (« missing IBAN and/or BIC »)."), *A))
        else:
            rows.append(_row(G_BANK, gl, _("BIC of the receiving account"), OK, "", *A))

        if (acc.qr_method or "SCOR") == "QRR":
            if not acc.qr_iban or not _is_qr_iban(acc.qr_iban):
                rows.append(_row(G_BANK, gl, _("Valid QR-IBAN (QRR method)"), KO,
                                 _("The QRR QR-bill cannot be issued: QR-IBAN missing or outside the "
                                   "institution range 30000-31999."), *A))
            else:
                rows.append(_row(G_BANK, gl, _("Valid QR-IBAN (QRR method)"), OK, "", *A))

    if ctx["uses_reconcile"]:
        cba = frappe.get_all("Bank Account", filters={"company": company, "is_company_account": 1},
                             fields=["name", "iban", "account"])
        if not cba:
            rows.append(_row(G_BANK, company, _("Company bank account (Bank Account)"), KO,
                             _("camt statement import cannot route any transaction (no company Bank Account)."),
                             "Company", company))
        for ba in cba:
            B = ("Bank Account", ba.name)
            if not ba.iban:
                rows.append(_row(G_BANK, ba.name, _("Bank Account IBAN (camt routing)"), KO,
                                 _("camt statements for this account will be ignored "
                                   "(« No Bank Account found for IBAN »)."), *B))
            if not ba.account:
                rows.append(_row(G_BANK, ba.name, _("GL account linked to the Bank Account"), KO,
                                 _("Imported transactions will have no currency (GL account not linked)."), *B))
            if ba.iban and ba.account:
                rows.append(_row(G_BANK, ba.name, _("Bank Account (IBAN + GL account)"), OK, "", *B))


def _check_settings(company, ctx, rows):
    if frappe.db.exists("DocType", "ERPNextSwiss Settings"):
        s = frappe.get_single("ERPNextSwiss Settings")
        E = ("ERPNextSwiss Settings", None)
        if s.get("xml_version") != "09":
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("pain.001 version = 09"), KO,
                             _("Your payment files use combined addresses (type K), REMOVED by SIX "
                               "(Nov. 2025) → rejected by the bank. Switch to version 09."), *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("pain.001 version = 09"), OK, "", *E))
        if not s.get("validate_xml"):
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("pain.001 XML validation"), WARN,
                             _("A non-conformant pain.001 will only be detected after the bank rejects it "
                               "(enable « Validate XML »)."), *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("pain.001 XML validation"), OK, "", *E))
        if not s.get("planning_days"):
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("Planning period (Payment Proposal)"), WARN,
                             _("Creating a payment proposal will fail (« Please configure the planning "
                               "period in ERPNextSwiss Settings »)."), *E))
        else:
            rows.append(_row(G_SETTINGS, "ERPNextSwiss Settings", _("Planning period (Payment Proposal)"), OK, "", *E))

    if ctx["uses_fx"]:
        A = ("Accounts Settings", None)
        if frappe.db.get_single_value("Accounts Settings", "allow_stale") != 1:
            rows.append(_row(G_SETTINGS, "Accounts Settings", _("Stale exchange rates allowed"), WARN,
                             _("The 1st-of-month FTA rate will be rejected mid-month → ERPNext will fetch a "
                               "non-compliant online rate (enable « allow stale »)."), *A))
        else:
            rows.append(_row(G_SETTINGS, "Accounts Settings", _("Stale exchange rates allowed"), OK, "", *A))

    if ctx["uses_reconcile"] and frappe.db.exists("DocType", "Banking Reference Mapping"):
        refs = {r.document_type: r.field_name
                for r in frappe.get_single("Banking Settings").get("reference_fields", [])}
        B = ("Banking Settings", None)
        if refs.get("Sales Invoice") != "qr_reference" or refs.get("Purchase Invoice") != "esr_reference_number":
            rows.append(_row(G_SETTINGS, "Banking Settings", _("Reference mapping (auto-matching)"), WARN,
                             _("Incoming/outgoing payments will not auto-match by QR reference "
                               "(mapping SI→qr_reference / PI→esr_reference_number missing)."), *B))
        else:
            rows.append(_row(G_SETTINGS, "Banking Settings", _("Reference mapping (auto-matching)"), OK, "", *B))


def _check_customers(company, ctx, rows):
    foreign_no_ccy, ccy_no_account, no_address = [], [], []
    for cust in frappe.get_all("Customer", fields=["name", "customer_name", "default_currency"]):
        disp = cust.customer_name or cust.name
        addr = _primary_address("Customer", cust.name)
        if ctx["uses_einvoice"] and not addr:
            no_address.append((disp, cust.name))
        if _is_foreign(addr) and (not cust.default_currency or cust.default_currency == "CHF"):
            foreign_no_ccy.append((disp, cust.name))
        if cust.default_currency and cust.default_currency != "CHF":
            if not ctx["multi_ccy_single_account"] and not _party_has_account(
                    "Customer", cust.name, company, cust.default_currency):
                ccy_no_account.append(("%s (%s)" % (disp, cust.default_currency), cust.name))

    if ctx["uses_einvoice"]:
        _emit_offenders(rows, G_CUSTOMER, _("Billing address present"), no_address, WARN,
                        _("Without an address, the e-invoice will be REJECTED (buyer address mandatory, "
                          "EN 16931 BR-10/11) and the QR-bill « payable by » block will stay empty."), "Customer")
    _emit_offenders(rows, G_CUSTOMER, _("Foreign customer with missing/CHF currency"), foreign_no_ccy, WARN,
                    _("Foreign customer without a foreign billing currency: foreign-currency invoices and "
                      "e-invoicing may be mislabeled (check the customer currency)."), "Customer")
    _emit_offenders(rows, G_CUSTOMER, _("Receivable account in the currency"), ccy_no_account, KO,
                    _("Customer invoice in this currency BLOCKED: no receivable account in the currency "
                      "(customer Accounting tab) and « multi-currency on a single account » disabled."), "Customer")


def _check_suppliers(company, ctx, rows):
    foreign_no_ccy, ccy_no_account, no_iban, no_address = [], [], [], []
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
        if not addr:
            no_address.append((disp, sup.name))
        foreign = (sup.get("country") and sup.get("country") != "Switzerland") or _is_foreign(addr)
        if foreign and (not sup.default_currency or sup.default_currency == "CHF"):
            foreign_no_ccy.append((disp, sup.name))
        if sup.default_currency and sup.default_currency != "CHF":
            if not ctx["multi_ccy_single_account"] and not _party_has_account(
                    "Supplier", sup.name, company, sup.default_currency):
                ccy_no_account.append(("%s (%s)" % (disp, sup.default_currency), sup.name))
        if not sup.get("iban") and not frappe.db.exists(
                "Bank Account", {"party_type": "Supplier", "party": sup.name}):
            no_iban.append((disp, sup.name))

    _emit_offenders(rows, G_SUPPLIER, _("Billing address present"), no_address, WARN,
                    _("Without an address, this supplier cannot be paid by pain.001 (creditor without "
                      "address → file rejected by the bank) and the purchase e-invoice will be incomplete."), "Supplier")
    _emit_offenders(rows, G_SUPPLIER, _("Foreign supplier with missing/CHF currency"), foreign_no_ccy, WARN,
                    _("Foreign supplier without a foreign currency: foreign-currency invoices/payments may "
                      "be mislabeled (check the supplier currency)."), "Supplier")
    _emit_offenders(rows, G_SUPPLIER, _("Payable account in the currency"), ccy_no_account, KO,
                    _("Supplier invoice in this currency BLOCKED: no payable account in the currency "
                      "(supplier Accounting tab)."), "Supplier")
    if ctx["uses_payments"]:
        _emit_offenders(rows, G_SUPPLIER, _("Supplier IBAN (pain.001 payment)"), no_iban, WARN,
                        _("This supplier cannot be paid by pain.001 file (no IBAN set)."), "Supplier")


def _check_modes_of_payment(company, rows):
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
    _emit_offenders(rows, G_SETTINGS, _("Default account of the payment mode"), offenders, WARN,
                    _("This (enabled) payment mode has no default account for this company → creating a "
                      "payment via this mode will require choosing the account manually."), "Mode of Payment")


def _foreign_party_currencies():
    curr = set()
    for dt in ("Customer", "Supplier"):
        for r in frappe.get_all(dt, filters={"default_currency": ["not in", ["", "CHF"]]},
                                fields=["default_currency"], distinct=True):
            if r.default_currency:
                curr.add(r.default_currency)
    return curr


def _check_exchange_rates(company, ctx, rows):
    if not ctx["uses_fx"]:
        return
    curr = _foreign_party_currencies()

    for ccy in sorted(curr):
        has_rate = (frappe.db.exists("Currency Exchange", {"from_currency": ccy, "to_currency": "CHF"})
                    or frappe.db.exists("Currency Exchange", {"from_currency": "CHF", "to_currency": ccy}))
        if not has_rate:
            rows.append(_row(G_FX, ccy, _("Exchange rate available"), KO,
                             _("No {0}↔CHF rate: any invoice in {0} will be BLOCKED (rate 0.00, online "
                               "fallback disabled). Import the FTA rates.").format(ccy)))
        else:
            rows.append(_row(G_FX, ccy, _("Exchange rate available"), OK))

    if not frappe.db.exists("DocType", "Swiss Exchange Rate Settings"):
        return
    s = frappe.get_single("Swiss Exchange Rate Settings")
    S = ("Swiss Exchange Rate Settings", None)

    if not s.get("enabled"):
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Automatic FTA rate import enabled"), WARN,
                         _("Automatic FTA rate import is disabled → rates will not update on their own "
                           "(risk of stale/missing rates)."), *S))
        return
    rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Automatic FTA rate import enabled"), OK, "", *S))

    if s.get("target_currency") != "CHF":
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Target currency = CHF"), WARN,
                         _("The import target currency is not CHF (config to review)."), *S))
    else:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Target currency = CHF"), OK, "", *S))

    configured = {r.currency for r in s.get("currencies", [])}
    missing = sorted(curr - configured)
    if missing:
        rows.append(_row(G_FX, ", ".join(missing), _("Party currencies covered by the import"), WARN,
                         _("These currencies used by your parties are NOT fetched automatically: {0}. "
                           "Add them to the import currency list.").format(", ".join(missing)), *S))
    else:
        rows.append(_row(G_FX, "—", _("Party currencies covered by the import"), OK, "", *S))

    _check_last_run(s, rows, S)


def _check_last_run(s, rows, S):
    from frappe.utils import now_datetime, get_datetime
    last = s.get("last_run")
    if not last:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Last import executed"), WARN,
                         _("The rate import has NEVER run (no « last run »)."), *S))
        return
    freq = s.get("frequency") or "Daily"
    max_h = {"Daily": 26, "Weekly": 8 * 24, "Monthly": 35 * 24}.get(freq, 26)
    age_h = (now_datetime() - get_datetime(last)).total_seconds() / 3600.0
    if age_h > max_h:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Recent import"), WARN,
                         _("Last import {0} h ago (expected ≤ {1} h for {2} frequency) → the scheduler "
                           "may no longer be running.").format(int(age_h), int(max_h), freq), *S))
    else:
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Recent import"), OK, "", *S))
    st = (s.get("last_status") or "")
    if st and not any(k in st.lower() for k in ("ok", "success", "succ", "✅")):
        rows.append(_row(G_FX, "Swiss Exchange Rate Settings", _("Last import status"), WARN,
                         _("The last import is not OK: {0}").format(st), *S))


def _check_party_accounts_settings(company, ctx, rows):
    if ctx["uses_fx"]:
        A = ("Accounts Settings", None)
        if ctx["multi_ccy_single_account"]:
            rows.append(_row(G_PARTY_ACC, "Accounts Settings", _("Multi-currency on a single party account"), OK,
                             _("Enabled: a single CHF account can carry foreign-currency invoices "
                               "(per-currency party accounts not required)."), *A))
        else:
            rows.append(_row(G_PARTY_ACC, "Accounts Settings", _("Multi-currency on a single party account"), WARN,
                             _("Disabled: each foreign-currency party MUST have a receivable/payable account "
                               "in its currency, otherwise its invoices will be blocked."), *A))


def _party_has_account(party_type, party, company, currency):
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
    if offenders:
        for display, docname in offenders[:_CAP]:
            rows.append(_row(group, display, check, status, impact, link_dt, docname))
        if len(offenders) > _CAP:
            rows.append(_row(group, _("… +{0} more").format(len(offenders) - _CAP), check, status, impact))
    else:
        rows.append(_row(group, "—", check, OK))


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------
def _context(company):
    """Détecte ce que la société UTILISE, pour ne contrôler que le pertinent."""
    uses_fx = bool(frappe.get_all("Customer", filters={"default_currency": ["not in", ["", "CHF"]]}, limit=1)
                   or frappe.get_all("Supplier", filters={"default_currency": ["not in", ["", "CHF"]]}, limit=1))
    return {
        "uses_reconcile": _app_installed("banking"),
        "uses_einvoice": _app_installed("eu_einvoice"),
        "uses_fx": uses_fx,
        "uses_payments": True,  # pain.001 = core ERPNextSwiss
        "multi_ccy_single_account": frappe.db.get_single_value(
            "Accounts Settings", "allow_multi_currency_invoices_against_single_party_account") == 1,
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
