# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Socle des tests par scénarios comptables — builders, asserters, masters.

Le contexte `Ctx` porte la société + la période, expose des BUILDERS (créer une facture
d'achat/vente, une écriture) et des ASSERTERS (vérifier GL, cases TVA, compte de résultat,
plausibilité). Les asserters ENREGISTRENT le résultat (ils ne lèvent pas) → tous les
contrôles s'exécutent et le rapport les montre tous.
"""
import frappe
from frappe.utils import flt

PERIOD = ("2026-01-01", "2026-12-31")   # période de référence des scénarios
DATE = "2026-06-15"                       # date de comptabilisation par défaut


def _acc(company, num):
    return frappe.db.get_value("Account", {"account_number": num, "company": company})


def _tax_template(company, code, purchase=True):
    dt = "Purchase Taxes and Charges Template" if purchase else "Sales Taxes and Charges Template"
    name = frappe.db.get_value(dt, {"company": company, "title": ["like", f"{code} %"]})
    if not name:
        frappe.throw(f"Template TVA '{code}' introuvable pour {company} — setup_company fait ?")
    if frappe.db.get_value(dt, name, "disabled"):
        frappe.db.set_value(dt, name, "disabled", 0)   # activer les codes inactifs (DUIP, PO81…) pour le test
    return name


def _item_tax_template(company, code):
    return frappe.db.get_value("Item Tax Template", {"company": company, "title": ["like", f"{code} %"]})


def _escompte_terms():
    """Payment Terms Template avec escompte paiement rapide — fixture de test (chemin natif ERPNext).
    10% dans les 30 jours (10% choisi pour des chiffres ronds : net 100 + TVA 8.10 sur 1000+81).
    C'est via CE chemin (et non une déduction manuelle) qu'ERPNext ventile la TVA de l'escompte."""
    name = "SCEN Escompte 10%"
    if not frappe.db.exists("Payment Terms Template", name):
        frappe.get_doc({
            "doctype": "Payment Terms Template", "template_name": name,
            "terms": [{
                "invoice_portion": 100,
                "due_date_based_on": "Day(s) after invoice date", "credit_days": 30,
                "discount_type": "Percentage", "discount": 10,
                "discount_validity_based_on": "Day(s) after invoice date", "discount_validity": 30,
            }],
        }).insert(ignore_permissions=True)
    return name


# --- Masters (idempotent) -----------------------------------------------------
def _leaf(doctype):
    """Renvoie une feuille (is_group=0) d'un doctype d'arbre (Customer Group, Territory…)."""
    return frappe.db.get_value(doctype, {"is_group": 0}, "name")


def _warehouse(company):
    """Un entrepôt-feuille de la société (pour les mouvements de stock en inventaire perpétuel)."""
    return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name")


def ensure_masters(company):
    """Crée les tiers/articles de test s'ils n'existent pas (feuilles de groupe résolues dynamiquement)."""
    if not frappe.db.exists("Customer", "SCEN Client CH"):
        frappe.get_doc({"doctype": "Customer", "customer_name": "SCEN Client CH",
                        "customer_group": _leaf("Customer Group"),
                        "territory": _leaf("Territory")}).insert(ignore_permissions=True)
    # client dédié aux opérations EUR (un tiers ne peut pas mélanger CHF et EUR sur ses postes ouverts)
    if not frappe.db.exists("Customer", "SCEN Client EUR"):
        frappe.get_doc({"doctype": "Customer", "customer_name": "SCEN Client EUR",
                        "customer_group": _leaf("Customer Group"), "territory": _leaf("Territory"),
                        "default_currency": "EUR"}).insert(ignore_permissions=True)
    for sup in ("SCEN Fournisseur CH", "SCEN Fournisseur Etranger"):
        if not frappe.db.exists("Supplier", sup):
            frappe.get_doc({"doctype": "Supplier", "supplier_name": sup,
                            "supplier_group": _leaf("Supplier Group")}).insert(ignore_permissions=True)
    # fournisseur dédié aux opérations EUR (un tiers ne peut pas mélanger CHF et EUR sur ses postes ouverts)
    if not frappe.db.exists("Supplier", "SCEN Fournisseur EUR"):
        frappe.get_doc({"doctype": "Supplier", "supplier_name": "SCEN Fournisseur EUR",
                        "supplier_group": _leaf("Supplier Group"),
                        "default_currency": "EUR"}).insert(ignore_permissions=True)
    for it in ("SCEN Service", "SCEN Marchandise"):
        if not frappe.db.exists("Item", it):
            frappe.get_doc({"doctype": "Item", "item_code": it, "item_name": it,
                            "item_group": _leaf("Item Group"), "stock_uom": "Nos",
                            "is_stock_item": 0}).insert(ignore_permissions=True)
    # article DE STOCK (inventaire perpétuel) : maintenu en stock + comptes produit/charge par société
    if not frappe.db.exists("Item", "SCEN Stock"):
        frappe.get_doc({"doctype": "Item", "item_code": "SCEN Stock", "item_name": "SCEN Stock",
                        "item_group": _leaf("Item Group"), "stock_uom": "Nos",
                        "is_stock_item": 1, "valuation_method": "FIFO"}).insert(ignore_permissions=True)
    itm = frappe.get_doc("Item", "SCEN Stock")
    if not any(d.company == company for d in itm.get("item_defaults", [])):
        itm.append("item_defaults", {"company": company,
                                     "income_account": _acc(company, "3200"),   # Ventes de marchandises
                                     "expense_account": _acc(company, "4200"),   # COGS (achats/coût des ventes)
                                     "default_warehouse": _warehouse(company)})
        itm.save(ignore_permissions=True)
    # rattacher le compte de tiers EN DEVISE aux tiers EUR (1101 client / 2001 fournisseur) : ainsi
    # get_party_account renvoie le bon compte au rapprochement Bank Wizard (créance/dette EUR).
    for party_dt, party, num in (("Customer", "SCEN Client EUR", "1101"),
                                 ("Supplier", "SCEN Fournisseur EUR", "2001")):
        doc = frappe.get_doc(party_dt, party)
        if not any(a.company == company for a in doc.get("accounts", [])):
            acc = _acc(company, num)
            if acc:
                doc.append("accounts", {"company": company, "account": acc})
                doc.save(ignore_permissions=True)
    frappe.db.commit()


# --- Contexte : builders + asserters ------------------------------------------
class Ctx:
    def __init__(self, company, scenario_name):
        self.company = company
        self.name = scenario_name
        self.ps, self.pe = PERIOD
        self.results = []          # [{layer, target, expected, actual, ok, detail}]
        self.vouchers = []

    def _rec(self, layer, target, expected, actual, ok, detail=""):
        self.results.append(dict(layer=layer, target=str(target), expected=expected,
                                 actual=actual, ok=bool(ok), detail=detail))

    # ---- BUILDERS ----
    def _apply_template(self, doc, dt, tn):
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        doc.taxes_and_charges = tn
        for t in get_taxes_and_charges(dt, tn):
            doc.append("taxes", t)

    def make_purchase_invoice(self, supplier, net, tax_template=None, item="SCEN Service",
                              expense="4200", date=DATE, is_return=False, actual_tax=None,
                              payment_terms_template=None, currency=None, conversion_rate=None,
                              credit_to=None):
        """is_return=True → avoir/note de crédit fournisseur. actual_tax=montant → pose une taxe
        `Actual` (douane DOUAM : TVA import saisie en montant).
        payment_terms_template → escompte obtenu (paiement rapide, ventilation TVA native).
        currency/conversion_rate → facture en devise. credit_to → compte créancier (ex. 2001 EUR)."""
        pi = frappe.get_doc({
            "doctype": "Purchase Invoice", "company": self.company, "supplier": supplier,
            "posting_date": date, "set_posting_time": 1, "bill_no": frappe.generate_hash(length=10),
            "is_return": 1 if is_return else 0,
            "items": [{"item_code": item, "qty": -1 if is_return else 1, "rate": net,
                       "expense_account": _acc(self.company, expense)}]})
        if currency:
            pi.currency = currency
            pi.conversion_rate = conversion_rate or 1
        if credit_to:
            pi.credit_to = _acc(self.company, credit_to)   # compte créancier (ex. 2001 EUR)
        if payment_terms_template:
            pi.payment_terms_template = payment_terms_template
        if tax_template:
            self._apply_template(pi, "Purchase Taxes and Charges Template",
                                 _tax_template(self.company, tax_template, purchase=True))
            if actual_tax is not None:
                for t in pi.taxes:
                    if t.charge_type == "Actual":
                        t.tax_amount = actual_tax
        pi.set_missing_values()
        pi.calculate_taxes_and_totals()
        pi.insert(ignore_permissions=True)
        pi.submit()
        self.vouchers.append(("Purchase Invoice", pi.name))
        return pi

    def make_sales_invoice(self, customer, net=None, item="SCEN Service", item_tax_template=None,
                           lines=None, tax_template=None, income="3000", date=DATE,
                           is_return=False, currency=None, conversion_rate=None, debit_to=None,
                           payment_terms_template=None):
        """Une ou plusieurs lignes. Mono : make_sales_invoice(cust, net=X, item_tax_template=Y).
        Multi : make_sales_invoice(cust, lines=[{"net":1000,"item_tax_template":"NC81"}, ...], tax_template="NC81").
        is_return → avoir client. currency/conversion_rate → facture en devise."""
        if lines is None:
            lines = [{"net": net, "item": item, "item_tax_template": item_tax_template}]
        qty = -1 if is_return else 1
        items = []
        for ln in lines:
            d = {"item_code": ln.get("item", "SCEN Service"), "qty": qty, "rate": ln["net"],
                 "income_account": _acc(self.company, ln.get("income", income))}
            itt = ln.get("item_tax_template")
            if itt:
                d["item_tax_template"] = _item_tax_template(self.company, itt)
            items.append(d)
        si = frappe.get_doc({"doctype": "Sales Invoice", "company": self.company, "customer": customer,
                             "posting_date": date, "set_posting_time": 1, "is_return": 1 if is_return else 0,
                             "items": items})
        if currency:
            si.currency = currency
            si.conversion_rate = conversion_rate or 1
        if debit_to:
            si.debit_to = _acc(self.company, debit_to)   # compte débiteur (ex. 1101 EUR)
        if payment_terms_template:
            si.payment_terms_template = payment_terms_template   # génère l'échéancier + escompte
        if tax_template:
            self._apply_template(si, "Sales Taxes and Charges Template",
                                 _tax_template(self.company, tax_template, purchase=False))
        si.set_missing_values()
        si.calculate_taxes_and_totals()
        si.insert(ignore_permissions=True)
        si.submit()
        self.vouchers.append(("Sales Invoice", si.name))
        return si

    def make_advance_payment(self, party_type, party, amount, date=DATE):
        """Acompte (sans facture) : Receive (client → 2030) ou Pay (fournisseur → 1130)."""
        bank = _acc(self.company, "1020")
        pe = frappe.get_doc({"doctype": "Payment Entry", "company": self.company,
                             "payment_type": "Receive" if party_type == "Customer" else "Pay",
                             "party_type": party_type, "party": party, "posting_date": date,
                             "paid_amount": amount, "received_amount": amount})
        if party_type == "Customer":
            pe.paid_to = bank
        else:
            pe.paid_from = bank
        pe.reference_no = frappe.generate_hash(length=8)   # référence bancaire requise
        pe.reference_date = date
        pe.set_missing_values()
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.vouchers.append(("Payment Entry", pe.name))
        return pe

    def make_payment(self, invoice_doctype, invoice_name, date=DATE, exchange_rate=None, bank=None):
        """Paiement d'une facture. exchange_rate → taux au paiement (diff. de change).
        bank → compte banque (ex. 1021 EUR).
        Escompte : géré NATIVEMENT — si la facture porte une Payment Terms Template avec escompte
        et que `date` (reference_date) est dans le délai, ERPNext ventile seul l'escompte
        (part nette → 3800, part TVA → compte de taxe de la facture). Pas de déduction manuelle."""
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        # reference_date passée à get_payment_entry → c'est ELLE qui déclenche l'escompte natif
        pe = get_payment_entry(invoice_doctype, invoice_name, reference_date=date)
        pe.posting_date = date
        pe.reference_no = frappe.generate_hash(length=8)
        if bank:
            bank_acc = _acc(self.company, bank)
            bank_ccy = frappe.db.get_value("Account", bank_acc, "account_currency")
            if pe.payment_type == "Receive":
                pe.paid_to = bank_acc
                pe.paid_to_account_currency = bank_ccy
            else:
                pe.paid_from = bank_acc
                pe.paid_from_account_currency = bank_ccy
        if exchange_rate:
            # exchange_rate = taux de conversion en CHF à la date de RÈGLEMENT (banque en CHF).
            # Le compte tiers (créance/dette) se solde à sa VALEUR COMPTABLE (taux de la facture, laissé
            # tel quel par get_payment_entry) ; la banque encaisse/décaisse le montant réellement converti
            # = montant_en_devise × taux_du_jour. L'écart réalisé = base_paid − base_received → 6999.
            # (Vers une banque en devise, le gain resterait latent → réévaluation de change en fin de période.)
            if pe.payment_type == "Receive":
                pe.received_amount = flt(pe.paid_amount * exchange_rate, 2)   # CHF réellement encaissés
            else:
                pe.paid_amount = flt(pe.received_amount * exchange_rate, 2)    # CHF réellement décaissés
            pe.set_amounts()
        pe.insert(ignore_permissions=True)
        pe.submit()
        self.vouchers.append(("Payment Entry", pe.name))
        return pe

    def make_period_closing(self, closing="2979", date="2026-12-31"):
        """Bouclement : Period Closing Voucher → vire le résultat P&L sur le compte de clôture (2979)."""
        fy = frappe.db.get_value("Fiscal Year",
                                 {"year_start_date": ["<=", date], "year_end_date": [">=", date]}, "name")
        fy_start = frappe.db.get_value("Fiscal Year", fy, "year_start_date")
        pcv = frappe.get_doc({"doctype": "Period Closing Voucher", "company": self.company,
                              "posting_date": date, "transaction_date": date, "fiscal_year": fy,
                              "period_start_date": fy_start, "period_end_date": date,
                              "closing_account_head": _acc(self.company, closing),
                              "remarks": "Bouclement test scénario"})
        pcv.insert(ignore_permissions=True)
        pcv.submit()
        self.vouchers.append(("Period Closing Voucher", pcv.name))
        return pcv

    def make_exchange_revaluation(self, date, rates):
        """Réévaluation de change (change LATENT) au cours de clôture — outil natif
        Exchange Rate Revaluation. rates = {devise: cours de clôture}. Crée les Currency Exchange
        manquants, réévalue tous les soldes ouverts en devise (créance/dette/banque), et génère la
        JE de réévaluation : le gain/perte NON RÉALISÉ → unrealized_exchange_gain_loss_account (6998),
        le tiers/banque revalorisé au bilan. Retourne le nom de la JE de réévaluation."""
        for cur, rate in rates.items():
            if not frappe.db.exists("Currency Exchange",
                                    {"from_currency": cur, "to_currency": "CHF", "date": date}):
                frappe.get_doc({"doctype": "Currency Exchange", "from_currency": cur,
                                "to_currency": "CHF", "date": date,
                                "exchange_rate": rate}).insert(ignore_permissions=True)
        err = frappe.get_doc({"doctype": "Exchange Rate Revaluation", "company": self.company,
                              "posting_date": date, "rounding_loss_allowance": 0.05})
        err.fetch_and_calculate_accounts_data()   # peuple accounts AVANT insert (child obligatoire)
        err.insert(ignore_permissions=True)
        err.submit()
        self.vouchers.append(("Exchange Rate Revaluation", err.name))
        jv = (err.make_jv_entries() or {}).get("revaluation_jv")
        if jv:
            # make_jv_entries crée une JV EN BROUILLON (le comptable la revoit au bouclement) →
            # la soumettre pour générer les GL Entry (sinon aucun impact bilan/résultat).
            je = frappe.get_doc("Journal Entry", jv)
            if je.docstatus == 0:
                je.submit()
            self.vouchers.append(("Journal Entry", jv))
        return jv

    # ---- BUILDERS STOCK (inventaire perpétuel) ----
    def make_purchase_receipt(self, supplier, item="SCEN Stock", qty=10, rate=100,
                              warehouse=None, date=DATE):
        """Réception de marchandise en stock (Purchase Receipt) : Dr 1200 / Cr 2301 SRBNB (au net, sans TVA)."""
        pr = frappe.get_doc({"doctype": "Purchase Receipt", "company": self.company, "supplier": supplier,
                             "posting_date": date, "set_posting_time": 1,
                             "items": [{"item_code": item, "qty": qty, "rate": rate,
                                        "warehouse": warehouse or _warehouse(self.company)}]})
        pr.set_missing_values()
        pr.insert(ignore_permissions=True)
        pr.submit()
        self.vouchers.append(("Purchase Receipt", pr.name))
        return pr

    def invoice_receipt(self, pr, tax_template=None, date=DATE):
        """Facture d'achat LIÉE à une réception : solde le SRBNB (Dr 2301 / Cr 2000 + TVA éventuelle)."""
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
        pi = frappe.get_doc(make_purchase_invoice(pr.name))
        pi.posting_date = date
        pi.set_posting_time = 1
        pi.bill_no = frappe.generate_hash(length=10)
        if tax_template:
            self._apply_template(pi, "Purchase Taxes and Charges Template",
                                 _tax_template(self.company, tax_template, purchase=True))
        pi.set_missing_values()
        pi.calculate_taxes_and_totals()
        pi.insert(ignore_permissions=True)
        pi.submit()
        self.vouchers.append(("Purchase Invoice", pi.name))
        return pi

    def make_landed_cost(self, pr, charges, expense="2302", date=DATE):
        """Landed Cost Voucher : capitalise des frais accessoires (douane, transport) DANS le stock.
        charges = {'Droits de douane': 300, 'Transport': 200}. Écriture : Dr 1200 / Cr 2302 EIIV."""
        lcv = frappe.get_doc({"doctype": "Landed Cost Voucher", "company": self.company,
                              "posting_date": date, "distribute_charges_based_on": "Amount",
                              "purchase_receipts": [{"receipt_document_type": "Purchase Receipt",
                                                     "receipt_document": pr.name,
                                                     "supplier": pr.supplier,
                                                     "grand_total": pr.base_grand_total or pr.grand_total}]})
        lcv.get_items_from_purchase_receipts()
        acc = _acc(self.company, expense)
        for desc, amt in charges.items():
            lcv.append("taxes", {"description": desc, "expense_account": acc, "amount": amt})
        lcv.insert(ignore_permissions=True)
        lcv.submit()
        self.vouchers.append(("Landed Cost Voucher", lcv.name))
        return lcv

    def make_delivery_note(self, customer, item="SCEN Stock", qty=10, rate=200,
                           warehouse=None, item_tax_template=None, date=DATE):
        """Bon de livraison (Delivery Note) : sortie de stock AU COÛT — Dr 4200 COGS / Cr 1200 (sans TVA)."""
        d = {"item_code": item, "qty": qty, "rate": rate,
             "warehouse": warehouse or _warehouse(self.company)}
        if item_tax_template:
            d["item_tax_template"] = _item_tax_template(self.company, item_tax_template)
        dn = frappe.get_doc({"doctype": "Delivery Note", "company": self.company, "customer": customer,
                             "posting_date": date, "set_posting_time": 1, "items": [d]})
        dn.set_missing_values()
        dn.insert(ignore_permissions=True)
        dn.submit()
        self.vouchers.append(("Delivery Note", dn.name))
        return dn

    def invoice_delivery(self, dn, tax_template=None, date=DATE):
        """Facture de vente LIÉE à un bon de livraison : produit + TVA (le stock est déjà sorti à la livraison)."""
        from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
        si = frappe.get_doc(make_sales_invoice(dn.name))
        si.posting_date = date
        si.set_posting_time = 1
        if tax_template:
            self._apply_template(si, "Sales Taxes and Charges Template",
                                 _tax_template(self.company, tax_template, purchase=False))
        si.set_missing_values()
        si.calculate_taxes_and_totals()
        si.insert(ignore_permissions=True)
        si.submit()
        self.vouchers.append(("Sales Invoice", si.name))
        return si

    def make_journal_entry(self, box, tag_account, amount=162.0, contra="4200", date=DATE):
        """Écriture manuelle avec une ligne TAGUÉE d'une case AFC (feature « TVA sur Journal Entry »).
        Le côté tagué suit le signe de la case : réduction (415/420) → crédit ; ajout (410) → débit.
        `tag_account` peut être n'importe quel compte (account-agnostic : c'est le tag qui compte)."""
        reduces = frappe.db.get_value("AFC VAT Box", box, "reduces_total")
        tagged = {"account": _acc(self.company, tag_account), "afc_box": box}
        other = {"account": _acc(self.company, contra)}
        if reduces:
            tagged["credit_in_account_currency"] = amount
            other["debit_in_account_currency"] = amount
        else:
            tagged["debit_in_account_currency"] = amount
            other["credit_in_account_currency"] = amount
        je = frappe.get_doc({"doctype": "Journal Entry", "company": self.company, "posting_date": date,
                             "voucher_type": "Journal Entry", "user_remark": f"Correction case {box}",
                             "accounts": [other, tagged]})
        je.insert(ignore_permissions=True)
        je.submit()
        self.vouchers.append(("Journal Entry", je.name))
        return je

    # ---- ASSERTERS ----
    def assert_gl(self, voucher, expected):
        """expected = {num_compte: montant_signé} ; +=débit net, −=crédit net."""
        name = getattr(voucher, "name", voucher)
        for num, exp in expected.items():
            acc = _acc(self.company, num)
            val = frappe.db.sql("""SELECT ROUND(SUM(debit - credit), 2) FROM `tabGL Entry`
                WHERE voucher_no = %s AND account = %s AND is_cancelled = 0""", (name, acc))[0][0] or 0
            self._rec("GL", num, exp, float(val), abs(float(val) - exp) < 0.01)

    def assert_vat(self, base=None, tax=None):
        from erpnextswiss.erpnextswiss.doctype.vat_declaration.vat_declaration import get_view_total, get_view_tax
        for box, exp in (base or {}).items():
            v = get_view_total(f"viewVAT_{box}", self.ps, self.pe, self.company)["total"] or 0
            self._rec("TVA-base", box, exp, round(float(v), 2), abs(float(v) - exp) < 0.01)
        for box, exp in (tax or {}).items():
            v = get_view_tax(f"viewVAT_{box}", self.ps, self.pe, self.company)["total"] or 0
            self._rec("TVA-impôt", box, exp, round(float(v), 2), abs(float(v) - exp) < 0.01)

    def assert_pl(self, ref_code, exp):
        """ref_code = reference_code du palier CO 959b (CH_MAT, EBIT, BENEFICE…) — résolu vers son
        libellé via les ROWS du template (le moteur n'expose que le libellé, pas le reference_code)."""
        from erpnext.accounts.report.custom_financial_statement.custom_financial_statement import execute
        from erpnextswiss.swiss_vat_config.financial_reports import ROWS
        label = next((r.get("display_name") for r in ROWS if r.get("reference_code") == ref_code), None)
        f = frappe._dict({"company": self.company, "report_template": "Compte de resultat CO 959b",
                          "filter_based_on": "Date Range", "period_start_date": self.ps,
                          "period_end_date": self.pe, "periodicity": "Yearly",
                          "accumulated_values": 1, "selected_view": "Report"})
        r = execute(f)
        cols, data = r[0], r[1]
        pcol = [c["fieldname"] for c in cols if c.get("fieldtype") == "Currency"][-1]
        row = next((d for d in data if (d.get("account") or "").strip() == (label or "§").strip()), None)
        val = row.get(pcol) if row else None
        self._rec("Résultat", ref_code, exp, val, val is not None and abs(float(val) - exp) < 0.01)

    def assert_balance(self, num, exp):
        """Solde cumulé (D−C) d'un compte sur la période (pour un compte de bilan)."""
        acc = _acc(self.company, num)
        val = frappe.db.sql("""SELECT ROUND(SUM(debit - credit), 2) FROM `tabGL Entry`
            WHERE company = %s AND account = %s AND is_cancelled = 0
            AND posting_date BETWEEN %s AND %s""", (self.company, acc, self.ps, self.pe))[0][0] or 0
        self._rec("Solde", num, exp, float(val), abs(float(val) - exp) < 0.01)

    def assert_stock_value(self, item, exp, warehouse=None):
        """Valeur du stock d'un article (somme des stock_value_difference des SLE) sur la période."""
        wh = warehouse or _warehouse(self.company)
        val = frappe.db.sql("""SELECT ROUND(SUM(stock_value_difference), 2) FROM `tabStock Ledger Entry`
            WHERE company = %s AND item_code = %s AND warehouse = %s AND is_cancelled = 0""",
            (self.company, item, wh))[0][0] or 0
        self._rec("Stock", item, exp, float(val), abs(float(val) - exp) < 0.01)

    def assert_plausibilite_ok(self):
        from erpnextswiss.swiss_vat_config.plausibility import collect, KO
        rows = collect(self.company, self.ps, self.pe)
        ko = [r for r in rows if r["status"] == KO]
        self._rec("Plausibilité", "7 contrôles", "0 anomalie", f"{len(ko)} anomalie(s)",
                  len(ko) == 0, detail=" ; ".join(f"{r['item']} → {r['detail']}" for r in ko))
