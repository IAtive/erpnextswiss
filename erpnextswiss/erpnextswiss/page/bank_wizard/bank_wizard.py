# -*- coding: utf-8 -*-
# Copyright (c) 2017-2026, libracore and contributors
# License: AGPL v3. See LICENCE

import frappe
from frappe import throw, _
import hashlib
import json
from bs4 import BeautifulSoup
import ast
from frappe.utils import cint, flt
from frappe.utils.data import get_url_to_form
from erpnext.setup.utils import get_exchange_rate
from erpnext.accounts.party import get_party_account
import datetime

# Fallback inspire de bexio : rapproche une facture ouverte du tiers deja identifie (par nom)
# dont le montant est dans la TOLERANCE CHF 5 OU 2% (la plus favorable) — gere escompte, frais,
# arrondi. Ne retourne un match que s'il est UNIQUE (evite les faux positifs).
def _match_within_tolerance(candidates, party, amount, party_key):
    amount = abs(float(amount))
    tol = max(5.0, round(amount * 0.02, 2))
    hits = [c for c in candidates
            if c.get(party_key) == party and abs(float(c['outstanding_amount']) - amount) <= tol]
    if len(hits) == 1:
        return hits[0]['name'], float(hits[0]['outstanding_amount'])
    return None, 0.0


# this function tries to match the amount to an open sales invoice
#
# returns the sales invoice reference (name string) or None
def match_by_amount(amount):
    # get sales invoices
    sql_query = ("""
        SELECT `name`
        FROM `tabSales Invoice`
        WHERE `docstatus` = 1
        AND `grand_total` = {0}
        AND `status` != 'Paid'; """.format(amount) )
    open_sales_invoices = frappe.db.sql(sql_query, as_dict=True)
    if open_sales_invoices:
        if len(open_sales_invoices) == 1:
            # found exactly one match
            return open_sales_invoices[0].name
        else:
            # multiple sales invoices with this amount found
            return None
    else:
        # no open sales invoice with this amount found
        return None

# this function tries to match the comments to an open sales invoice
#
# returns the sales invoice reference (name sting) or None
def match_by_comment(comment):
    # get sales invoices (submitted, not paid)
    sql_query = """
        SELECT `name`
        FROM `tabSales Invoice`
        WHERE `docstatus` = 1
        AND `status` != 'Paid';"""
    open_sales_invoices = frappe.db.sql(sql_query, as_dict=True)
    if open_sales_invoices:
        # find sales invoice referernce in the comment
        for reference in open_sales_invoices.name:
            if reference in comment:
                # found a match
                return reference
    return None

# find unpaid invoices for a customer
#
# returns a dict (name) of sales invoice references or None
def get_unpaid_sales_invoices_by_customer(customer):
    # get sales invoices (submitted, not paid)
    sql_query = """
        SELECT `name`
        FROM `tabSales Invoice`
        WHERE `docstatus` = 1
        AND `customer` = '{0}'
        AND `status` != 'Paid'; """.format(customer)
    open_sales_invoices = frappe.db.sql(sql_query, as_dict=True)
    return open_sales_invoices

# create a payment entry
def create_payment_entry(date, to_account, received_amount, transaction_id, remarks, party_iban=None, auto_submit=False):
    # get default customer
    default_customer = get_default_customer()
    if not frappe.db.exists('Payment Entry', {'reference_no': transaction_id}):
        # create new payment entry
        new_payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': "Receive",
            'party_type': "Customer",
            'party': default_customer,
            # date is in DD.MM.YYYY
            'posting_date': date,
            'paid_to': to_account,
            'received_amount': received_amount,
            'paid_amount': received_amount,
            'reference_no': transaction_id,
            'reference_date': date,
            'remarks': remarks,
            'bank_account_no': party_iban
        })
        inserted_payment_entry = new_payment_entry.insert()
        if auto_submit:
            new_payment_entry.submit()
        frappe.db.commit()
        return inserted_payment_entry
    else:
        return None

# creates the reference record in a payment entry
def create_reference(payment_entry, sales_invoice):
    # create a new payment entry reference
    reference_entry = frappe.get_doc({
        'doctype': "Payment Entry Reference",
        'parent': payment_entry,
        'parentfield': "references",
        'parenttype': "Payment Entry",
        'reference_doctype': "Sales Invoice",
        'reference_name': sales_invoice,
        'total_amount': frappe.get_value("Sales Invoice", sales_invoice, "base_grand_total"),
        'outstanding_amount': frappe.get_value("Sales Invoice", sales_invoice, "outstanding_amount")
    })
    paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")
    if paid_amount > reference_entry.outstanding_amount:
        reference_entry.allocated_amount = reference_entry.outstanding_amount
    else:
        reference_entry.allocated_amount = paid_amount
    reference_entry.insert();
    return

def log(comment):
    new_comment = frappe.get_doc({"doctype": "Log"})
    new_comment.comment = comment
    new_comment.insert()
    return new_comment

# converts a parameter to a bool
def assert_bool(param):
    result = param
    if result == 'false':
        result = False
    elif result == 'true':
        result = True
    return result

def get_default_customer():
    default_customer = frappe.get_value("ERPNextSwiss Settings", "ERPNextSwiss Settings", "default_customer")
    if not default_customer:
        default_customer = "Guest"
    return default_customer

@frappe.whitelist()
def get_bank_accounts():
    accounts = frappe.get_list('Account', filters={'account_type': 'Bank', 'is_group': 0}, fields=['name'], order_by='account_number')
    selectable_accounts = []
    for account in accounts:
        selectable_accounts.append(account.name)

    # frappe.throw(selectable_accounts)
    return {'accounts': selectable_accounts }

@frappe.whitelist()
def get_default_accounts(bank_account=None, company=None):
    if bank_account:
        company = frappe.get_value("Account", bank_account, "company")
    receivable_account = frappe.get_value('Company', company, 'default_receivable_account')
    payable_account = frappe.get_value('Company', company, 'default_payable_account')
    # fix v16 : default_expense_claim_payable_account est un champ HR (app hrms) qui peut ne pas
    # exister sur Company -> on le lit seulement s'il est present, sinon fallback sur le payable
    expense_payable_account = payable_account
    if frappe.get_meta('Company').has_field('default_expense_claim_payable_account'):
        expense_payable_account = frappe.get_value('Company', company, 'default_expense_claim_payable_account') or payable_account
    auto_process_matches = frappe.get_value('ERPNextSwiss Settings', 'ERPNextSwiss Settings', 'auto_process_matches')
    return {
        'company': company,
        'receivable_account': receivable_account,
        'payable_account': payable_account,
        'expense_payable_account': expense_payable_account,
        'auto_process_matches': auto_process_matches
    }

@frappe.whitelist()
def get_intermediate_account():
    account = frappe.get_value('ERPNextSwiss Settings', 'ERPNextSwiss Settings', 'intermediate_account')
    return {'account': account or "" }

@frappe.whitelist()
def get_default_customer():
    customer = frappe.get_value('ERPNextSwiss Settings', 'ERPNextSwiss Settings', 'default_customer')
    return {'customer': customer or "" }

@frappe.whitelist()
def get_default_supplier():
    supplier = frappe.get_value('ERPNextSwiss Settings', 'ERPNextSwiss Settings', 'default_supplier')
    return {'supplier': supplier or "" }

@frappe.whitelist()
def get_receivable_account(company=None):
    if not company:
        company = get_first_company()
    account = frappe.get_value('Company', company, 'default_receivable_account')
    return {'account': account or "" }

@frappe.whitelist()
def get_payable_account(company=None, employee=False):
    if not company:
        company = get_first_company()
    account = frappe.get_value('Company', company, 'default_payable_account')
    if employee:
        account = frappe.get_value('Company', company, 'default_expense_claim_payable_account') or account
    return {'account': account or "" }

def get_first_company():
    companies = frappe.get_all("Company", filters=None, fields=['name'])
    return companies[0]['name']

"""
Interpret meta information of the camt.053 record

Input: camt.053-xml-string
Output: meta-dict
"""
def read_camt053_meta(content):
    soup = BeautifulSoup(content, 'lxml')
    meta = {
        'iban': soup.document.bktocstmrstmt.stmt.acct.id.iban.get_text(),
        'electronic_sequence_number': soup.document.bktocstmrstmt.stmt.elctrncseqnb.get_text(),
        'msgid': soup.document.bktocstmrstmt.stmt.id.get_text(),
        'currency': soup.document.bktocstmrstmt.stmt.acct.ccy.get_text()
    }
    # find balances
    balances = soup.find_all('bal')
    for balance in balances:
        balance_soup = BeautifulSoup(str(balance), 'lxml')
        if balance_soup.tp.cdorprtry.cd.get_text() == "OPBD":
            meta['opening_balance'] = float(balance_soup.amt.get_text())
        elif balance_soup.tp.cdorprtry.cd.get_text() == "CLBD":
            meta['closing_balance'] = float(balance_soup.amt.get_text())
            
    return meta

@frappe.whitelist()
def read_camt053(content, account):
    settings = frappe.get_doc("ERPNextSwiss Settings", "ERPNextSwiss Settings")

    #read_camt_transactions_re(content)
    soup = BeautifulSoup(content, 'lxml')

    # general information
    try:
        #iban = doc['Document']['BkToCstmrStmt']['Stmt']['Acct']['Id']['IBAN']
        iban = soup.document.bktocstmrstmt.stmt.acct.id.iban.get_text()
    except:
        # fallback (Credit Suisse will provide bank account number instead of IBAN)
        iban = "n/a"
        try:
            acct_no = soup.document.bktocstmrstmt.stmt.acct.id.othr.id.get_text()
        except:
            # node not found, probably wrong format
            iban = "n/a"
            frappe.log_error("Unable to read structure. Please make sure that you have selected the correct format.", "BankWizard read_camt053")
            
    # find account by iban
    accounts = frappe.db.sql("""
            SELECT `name`
            FROM `tabAccount`
            WHERE `account_type` = 'Bank'
              AND `disabled` = 0
              AND REPLACE(`iban`, ' ', '') = %(iban)s
        """,
        {'iban': iban.replace(" ", "")},
        as_dict=True
    )

    skip_company_filter = False
    if len(accounts) == 0:
        frappe.msgprint( _("No account found for IBAN {0}. Make sure there is an account in the chart of accounts with this IBAN, account type Bank and not disabled.").format(iban), _("Bank Import IBAN validation"))
        accounts = [{'name': 'n/a'}]
        skip_company_filter = True
    else:
        account = accounts[0]['name']
    
    # transactions
    entries = soup.find_all('ntry')
    transactions = read_camt_transactions(entries, account, settings, skip_company_filter=skip_company_filter)
    html = render_transactions(transactions)
    
    return { 'transactions': transactions, 'html': html, 'bank': accounts[0]['name'] } 

@frappe.whitelist()
def render_transactions(transactions):
    if type(transactions) == str:
        transactions = json.loads(transactions)
    
    html = frappe.render_template('erpnextswiss/erpnextswiss/page/bank_wizard/transaction_table.html', { 'transactions': transactions }  )
    return html

def read_camt_transactions(transaction_entries, account, settings, debug=False, skip_company_filter=False):
    company = frappe.get_value("Account", account, "company")
    txns = []
    for entry in transaction_entries:
        entry_soup = BeautifulSoup(str(entry), 'lxml')
        if entry_soup.bookgdt.dt:
            date = entry_soup.bookgdt.dt.get_text()[:10]
        elif entry_soup.bookgdt.dttm:
            date = entry_soup.bookgdt.dttm.get_text()[:10]
        else:
            date = datetime.datetime.today().strftime("%Y-%m-%d")
        transactions = entry_soup.find_all('txdtls')
        # fetch entry amount as fallback
        entry_amount = float(entry_soup.amt.get_text())
        entry_currency = entry_soup.amt['ccy']
        # fetch global account service reference
        try:
            global_account_service_reference = entry_soup.acctsvcrref.get_text()
        except:
            global_account_service_reference = ""
        transaction_count = 0
        if transactions and len(transactions) > 0:
            for transaction in transactions:
                transaction_count += 1
                transaction_soup = BeautifulSoup(str(transaction), 'lxml')
                # --- find transaction type: paid or received: (DBIT: paid, CRDT: received)
                if settings.always_use_entry_transaction_type:
                    credit_debit = entry_soup.cdtdbtind.get_text()
                else:
                    try:
                        credit_debit = transaction_soup.cdtdbtind.get_text()
                    except:
                        # fallback to entry indicator
                        credit_debit = entry_soup.cdtdbtind.get_text()

                # collect payment instruction id
                try:
                    payment_instruction_id = transaction_soup.pmtinfid.get_text()
                except:
                    payment_instruction_id = None

                # --- find unique reference
                try:
                    # try to use the unique end-to-end transaction reference
                    unique_reference = transaction_soup.txdtls.refs.uetr.get_text()
                except:
                    try:
                        # try to use the account service reference
                        unique_reference = transaction_soup.txdtls.refs.acctsvcrref.get_text()
                    except:
                        # fallback: use tx id
                        try:
                            unique_reference = transaction_soup.txid.get_text()
                        except:
                            # fallback to pmtinfid
                            try:
                                unique_reference = transaction_soup.pmtinfid.get_text()
                            except:
                                try:
                                    if entry_soup.ntryref:
                                        unique_reference = entry_soup.ntryref.get_text()
                                    elif global_account_service_reference != "":
                                        # fallback to group account service reference plus transaction_count
                                        unique_reference = "{0}-{1}".format(global_account_service_reference, transaction_count)
                                    else:
                                        # fallback ntry reference or booking code (wise) (for banks this is often not unique)
                                        unique_reference = entry_soup.bktxcd.prtry.cd.get_text()
                                except:
                                    # fallback to ustrd (do not use)
                                    # unique_reference = transaction_soup.ustrd.get_text()
                                    # fallback to hash
                                    amount = transaction_soup.txdtls.amt.get_text()
                                    try:
                                        party = transaction_soup.nm.get_text()
                                    except:
                                        # fallback for bank internal debits and credits without a party name tag
                                        # first appearance with the Nidwaldner Kantonalbank
                                        # see issue libracore/bimbo#379
                                        party = "Bank internal"
                                    code = "{0}:{1}:{2}".format(date, amount, party)
                                    if settings.debug_mode:
                                        frappe.log_error("Code: {0}".format(code))
                                    unique_reference = hashlib.md5(code.encode("utf-8")).hexdigest()
                # --- find amount and currency
                if cint(settings.always_use_entry_amount):
                    # in this case, we ignore collective transaction parts and book on the entry amount in account currency
                    amount = entry_amount
                    currency = entry_currency
                else:
                    try:
                        # try to find as <TxAmt>
                        amount = float(transaction_soup.txdtls.txamt.amt.get_text())
                        currency = transaction_soup.txdtls.txamt.amt['ccy']
                    except:
                        try:
                            # fallback to pure <AMT>
                            amount = float(transaction_soup.txdtls.amt.get_text())
                            currency = transaction_soup.txdtls.amt['ccy']
                        except:
                            # fallback to amount from entry level
                            amount = entry_amount
                            currency = entry_currency
                # --- exchange rate + original (instructed) amount, when the bank converted (ISO <AmtDtls>)
                # Ex. paiement EUR depuis un compte CHF : <InstdAmt Ccy="EUR"> + <CcyXchg><XchgRate>.
                # Sert a poser le bon montant en devise + le taux reel sur le Payment Entry (gain/perte de change).
                xchg_rate = None
                instructed_amount = None
                instructed_currency = None
                try:
                    amt_dtls = transaction_soup.txdtls.amtdtls
                    if amt_dtls:
                        instd = amt_dtls.find("instdamt")
                        if instd and instd.amt:
                            instructed_amount = float(instd.amt.get_text())
                            instructed_currency = instd.amt.get("ccy")
                    # Le parser HTML de BeautifulSoup "hisse" souvent <XchgRate> hors de <AmtDtls>/<TxDtls>
                    # -> on le cherche dans le transaction_soup, puis au niveau entry_soup en repli.
                    xchg = transaction_soup.find("xchgrate") or entry_soup.find("xchgrate")
                    if xchg:
                        xchg_rate = float(xchg.get_text())
                except:
                    pass
                # FX : la transaction est en DEVISE (ex. TxAmt EUR 5400) mais le compte booke en CHF.
                # On GARDE `amount` en DEVISE -> le MATCHING compare bien 5400 EUR a la facture en EUR.
                # On retient A PART le montant BOOKE en CHF (entry_amount, ex. 4988.93) dans booked_amount,
                # pour poser le bon CHF cote banque dans le Payment Entry (le taux se derive: CHF booke / devise).
                booked_amount = None
                booked_currency = None
                if currency and entry_currency and currency != entry_currency:
                    if not instructed_amount:
                        instructed_amount = float(amount)
                        instructed_currency = currency
                    booked_amount = entry_amount
                    booked_currency = entry_currency
                try:
                    # --- find party IBAN
                    if credit_debit == "DBIT":
                        # use RltdPties:Cdtr
                        party_soup = BeautifulSoup(str(transaction_soup.txdtls.rltdpties.cdtr), 'lxml')
                        try:
                            party_iban = transaction_soup.cdtracct.id.iban.get_text()
                        except:
                            party_iban = ""
                    else:
                        # CRDT: use RltdPties:Dbtr
                        party_soup = BeautifulSoup(str(transaction_soup.txdtls.rltdpties.dbtr), 'lxml')
                        try:
                            party_iban = transaction_soup.dbtracct.id.iban.get_text()
                        except:
                            party_iban = ""
                    try:
                        party_name = party_soup.nm.get_text()
                        if party_soup.strtnm:
                            # parse by street name, ...
                            try:
                                street = party_soup.strtnm.get_text()
                                try:
                                    street_number = party_soup.bldgnb.get_text()
                                    address_line1 = "{0} {1}".format(street, street_number)
                                except:
                                    address_line1 = street

                            except:
                                address_line1 = ""
                            try:
                                plz = party_soup.pstcd.get_text()
                            except:
                                plz = ""
                            try:
                                town = party_soup.twnnm.get_text()
                            except:
                                town = ""
                            address_line2 = "{0} {1}".format(plz, town)
                        else:
                            # parse by address lines
                            try:
                                address_lines = party_soup.find_all("adrline")
                                address_line1 = address_lines[0].get_text()
                                address_line2 = address_lines[1].get_text()
                            except:
                                # in case no address is provided
                                address_line1 = ""
                                address_line2 = ""
                    except:
                        # party is not defined (e.g. DBIT from Bank)
                        try:
                            # this is a fallback for ZKB which does not provide nm tag, but address line
                            address_lines = party_soup.find_all("adrline")
                            party_name = address_lines[0].get_text()
                        except:
                            party_name = "not found"
                        address_line1 = ""
                        address_line2 = ""
                    try:
                        country = party_soup.ctry.get_text()
                    except:
                        country = ""
                    if (address_line1 != "") and (address_line2 != ""):
                        party_address = "{0}, {1}, {2}".format(
                            address_line1,
                            address_line2,
                            country)
                    elif (address_line1 != ""):
                        party_address = "{0}, {1}".format(address_line1, country)
                    else:
                        party_address = "{0}".format(country)
                except:
                    # key related parties not found / no customer info
                    party_name = ""
                    party_address = ""
                    party_iban = ""
                try:
                    charges = float(transaction_soup.chrgs.ttlchrgsandtaxamt[text])
                except:
                    charges = 0.0

                try:
                    # try to find ESR reference
                    transaction_reference = transaction_soup.rmtinf.strd.cdtrrefinf.ref.get_text()
                except:
                    try:
                        # try to find a user-defined reference (e.g. SINV.)
                        transaction_reference = transaction_soup.rmtinf.ustrd.get_text()
                    except:
                        try:
                            # try to find an end-to-end ID
                            transaction_reference = transaction_soup.endtoendid.get_text()
                        except:
                            try:
                                # try to find an AddtlTxInf
                                transaction_reference = transaction_soup.addtltxinf.get_text()
                            except:
                                # in case of numeric only matching, do not fall back to transaction id
                                if cint(settings.numeric_only_debtor_matching) == 1:
                                    transaction_reference = "???"
                                else:
                                    transaction_reference = unique_reference
                # debug: show collected record in error log
                if settings.debug_mode:
                    frappe.log_error("""type:{type}\ndate:{date}\namount:{currency} {amount}\nunique ref:{unique}
                        party:{party}\nparty address:{address}\nparty iban:{iban}\nremarks:{remarks}
                        payment_instruction_id:{payment_instruction_id}""".format(
                        type=credit_debit, date=date, currency=currency, amount=amount, unique=unique_reference,
                        party=party_name, address=party_address, iban=party_iban, remarks=transaction_reference,
                        payment_instruction_id=payment_instruction_id))

                # check if this transaction is already recorded
                _filters = {'reference_no': unique_reference, 'company': company}
                if skip_company_filter:                 # in case the account was not clear, do not filter for company (in multi-company case)
                    _filters.pop('company', None)
                match_payment_entry = frappe.get_all('Payment Entry', 
                    filters=_filters, 
                    fields=['name'])
                if match_payment_entry:
                    if debug or settings.debug_mode:
                        frappe.log_error("Transaction {0} is already imported in {1}.".format(unique_reference, match_payment_entry[0]['name']))
                else:
                    # try to find matching parties & invoices
                    party_match = None
                    employee_match = None
                    invoice_matches = []
                    expense_matches = None
                    matched_amount = 0.0
                    amount_tolerance_used = False   # True si match par montant tolerance (fallback)
                    if credit_debit == "DBIT":
                        # match by payment instruction id
                        possible_pinvs = []
                        if payment_instruction_id:
                            try:
                                payment_instruction_fields = payment_instruction_id.split("-")

                                try:
                                    payment_instruction_row = int(payment_instruction_fields[-1]) + 1
                                except:
                                    # invalid payment instruction id (cannot parse, e.g. on LSV or foreign pain.001 source) - no match
                                    payment_instruction_row = None
                                if len(payment_instruction_fields) > 3:
                                    # revision in payment proposal
                                    payment_proposal_id = "{0}-{1}".format(payment_instruction_fields[1], payment_instruction_fields[2])
                                elif len(payment_instruction_fields) > 1:
                                    payment_proposal_id = payment_instruction_fields[1]
                                else:
                                    payment_proposal_id = None
                                # find original instruction record
                                payment_proposal_payments = frappe.get_all("Payment Proposal Payment",
                                    filters={'parent': payment_proposal_id, 'idx': payment_instruction_row},
                                    fields=['receiver', 'receiver_address_line1', 'receiver_address_line2', 'iban', 'reference', 'receiver_id', 'esr_reference'])
                                # supplier
                                if payment_proposal_payments:
                                    if payment_proposal_payments[0]['receiver_id'] and frappe.db.exists("Supplier", payment_proposal_payments[0]['receiver_id']):
                                        party_match = payment_proposal_payments[0]['receiver_id']
                                    else:
                                        # fallback to supplier name
                                        match_suppliers = frappe.get_all("Supplier", filters={'supplier_name': payment_proposal_payments[0]['receiver']},
                                            fields=['name'])
                                        if match_suppliers and len(match_suppliers) > 0:
                                            party_match = match_suppliers[0]['name']
                                    # purchase invoice reference match (take each part separately)
                                    if payment_proposal_payments[0]['esr_reference']:
                                        # match by esr reference number
                                        possible_pinvs = frappe.get_all("Purchase Invoice",
                                            filters=[['docstatus', '=', 1],
                                                ['outstanding_amount', '>', 0],
                                                ['esr_reference_number', '=', payment_proposal_payments[0]['esr_reference']]
                                            ],
                                            fields=['name', 'supplier', 'outstanding_amount', 'bill_no', 'esr_reference_number'])
                                    else:
                                        # check each individual reference (combined pinvs)
                                        possible_pinvs = frappe.get_all("Purchase Invoice",
                                                filters=[['docstatus', '=', 1],
                                                    ['outstanding_amount', '>', 0],
                                                    ['bill_no', 'IN', payment_proposal_payments[0]['reference']]
                                                ],
                                                fields=['name', 'supplier', 'outstanding_amount', 'bill_no', 'esr_reference_number'])
                            except Exception as err:
                                # this can be the case for malformed instruction ids
                                frappe.log_error(err, "Match payment instruction error")
                        # suppliers
                        if not possible_pinvs:
                            # no payment proposal, try to estimate from other data
                            if not party_match:
                                # find suplier from name
                                match_suppliers = frappe.get_all("Supplier",
                                    filters={'supplier_name': party_name, 'disabled': 0},
                                    fields=['name'])
                                if match_suppliers:
                                    party_match = match_suppliers[0]['name']
                            if party_match:
                                # restrict pinvs to supplier
                                possible_pinvs = frappe.get_all("Purchase Invoice",
                                    filters=[['docstatus', '=', 1], ['outstanding_amount', '>', 0], ['supplier', '=', party_match]],
                                    fields=['name', 'supplier', 'outstanding_amount', 'bill_no', 'esr_reference_number'])
                            else:
                                # purchase invoices
                                possible_pinvs = frappe.get_all("Purchase Invoice",
                                    filters=[['docstatus', '=', 1], ['outstanding_amount', '>', 0]],
                                    fields=['name', 'supplier', 'outstanding_amount', 'bill_no', 'esr_reference_number'])
                        if possible_pinvs:
                            for pinv in possible_pinvs:
                                if ((pinv['name'] in transaction_reference) \
                                    or ((pinv['bill_no'] or pinv['name']) in transaction_reference) \
                                    or (pinv['esr_reference_number'] and (pinv['esr_reference_number'].replace(" ", "") in transaction_reference.replace(" ", ""))) \
                                    or (payment_instruction_id == transaction_reference)):              # this is an override for Postfinance combined transactions that will not relay transaction ids
                                    invoice_matches.append(pinv['name'])
                                    # override party match in case there is one from the sales invoice
                                    party_match = pinv['supplier']
                                    # add total matched amount
                                    matched_amount += float(pinv['outstanding_amount'])
                            # Fallback (bexio) : fournisseur identifie mais pas de match par reference
                            # -> facture ouverte dont le montant est dans la tolerance CHF 5 / 2%.
                            if not invoice_matches and party_match:
                                m_name, m_out = _match_within_tolerance(possible_pinvs, party_match, amount, 'supplier')
                                if m_name:
                                    invoice_matches = [m_name]
                                    matched_amount = m_out
                                    amount_tolerance_used = True
                        # employees
                        match_employees = frappe.get_all("Employee",
                            filters={'employee_name': party_name, 'status': 'active'},
                            fields=['name'])
                        if match_employees:
                            employee_match = match_employees[0]['name']
                        # expense claims
                        possible_expenses = frappe.get_all("Expense Claim",
                            filters=[['docstatus', '=', 1], ['status', '=', 'Unpaid']],
                            fields=['name', 'employee', 'total_claimed_amount'])
                        if possible_expenses:
                            expense_matches = []
                            for exp in possible_expenses:
                                if exp['name'] in transaction_reference:
                                    expense_matches.append(exp['name'])
                                    # override party match in case there is one from the sales invoice
                                    employee_match = exp['employee']
                                    # add total matched amount
                                    matched_amount += float(exp['total_claimed_amount'])
                    else:
                        # customers & sales invoices
                        match_customers = frappe.get_all("Customer", filters={'customer_name': party_name, 'disabled': 0}, fields=['name'])
                        if match_customers:
                            party_match = match_customers[0]['name']
                        # sales invoices
                        possible_sinvs = frappe.get_all("Sales Invoice",
                            filters=[['outstanding_amount', '>', 0], ['docstatus', '=', 1]],
                            fields=['name', 'customer', 'customer_name', 'outstanding_amount', 'esr_reference', 'esr_reference', 'reference_number_full'])
                        if possible_sinvs:
                            invoice_matches = []
                            for sinv in possible_sinvs:
                                is_match = False
                                if sinv['name'] in transaction_reference or ('esr_reference' in sinv and sinv['esr_reference'] and sinv['esr_reference'] == transaction_reference) or ('reference_number_full' in sinv and sinv['reference_number_full'] and sinv['reference_number_full'] == transaction_reference):
                                    # matched exact sales invoice reference or ESR reference or SCOR reference
                                    is_match = True
                                elif cint(settings.numeric_only_debtor_matching) == 1:
                                    # allow the numeric part matching
                                    if get_numeric_only_reference(sinv['name']) in transaction_reference:
                                        # matched numeric part and customer name
                                        is_match = True
                                elif cint(settings.ignore_special_characters) == 1:
                                    if remove_special_characters(sinv['name']) in remove_special_characters(transaction_reference):
                                        # matched without special characters
                                        is_match = True

                                if is_match:
                                    invoice_matches.append(sinv['name'])
                                    # override party match in case there is one from the sales invoice
                                    party_match = sinv['customer']
                                    # add total matched amount
                                    matched_amount += float(sinv['outstanding_amount'])

                            # Fallback (bexio) : pas de match par reference mais client identifie par nom
                            # -> propose sa facture ouverte dont le montant est dans la tolerance CHF 5 / 2%.
                            if not invoice_matches and party_match:
                                m_name, m_out = _match_within_tolerance(possible_sinvs, party_match, amount, 'customer')
                                if m_name:
                                    invoice_matches = [m_name]
                                    matched_amount = m_out
                                    amount_tolerance_used = True

                    # reset invoice matches in case there are no matches
                    try:
                        if len(invoice_matches) == 0:
                            invoice_matches = None
                        if len(expense_matches) == 0:
                            expense_matches = None
                    except:
                        pass
                    new_txn = {
                        'txid': len(txns),
                        'date': date,
                        'currency': currency,
                        'amount': amount,
                        'party_name': party_name,
                        'party_address': party_address,
                        'credit_debit': credit_debit,
                        'party_iban': party_iban,
                        'unique_reference': unique_reference,
                        'transaction_reference': transaction_reference,
                        'party_match': party_match,
                        'invoice_matches': invoice_matches,
                        'matched_amount': round(matched_amount, 2),
                        'employee_match': employee_match,
                        'expense_matches': expense_matches,
                        'amount_tolerance': amount_tolerance_used,
                        'xchg_rate': xchg_rate,
                        'instructed_amount': instructed_amount,
                        'instructed_currency': instructed_currency,
                        'booked_amount': booked_amount,
                        'booked_currency': booked_currency
                    }
                    txns.append(new_txn)
        else:
            # transaction without TxDtls: occurs at CS when transaction is from a pain.001 instruction
            # get unique ID
            try:
                unique_reference = entry_soup.acctsvcrref.get_text()
            except:
                # fallback: use tx id
                try:
                    unique_reference = entry_soup.txid.get_text()
                except:
                    # fallback to pmtinfid
                    try:
                        unique_reference = entry_soup.pmtinfid.get_text()
                    except:
                        # fallback to hash
                        code = "{0}:{1}:{2}".format(date, entry_currency, entry_amount)
                        unique_reference = hashlib.md5(code.encode("utf-8")).hexdigest()
            # check if this transaction is already recorded
            match_payment_entry = frappe.get_all('Payment Entry', filters={'reference_no': unique_reference}, fields=['name'])
            if match_payment_entry:
                if debug or settings.debug_mode:
                    frappe.log_error("Transaction {0} is already imported in {1}.".format(unique_reference, match_payment_entry[0]['name']))
            else:
                # --- find transaction type: paid or received: (DBIT: paid, CRDT: received)
                credit_debit = entry_soup.cdtdbtind.get_text()
                # find payment instruction ID
                try:
                    payment_instruction_id = entry_soup.pmtinfid.get_text()     # instruction ID, PMTINF-[payment proposal]-row
                    payment_instruction_fields = payment_instruction_id.split("-")
                    payment_instruction_row = int(payment_instruction_fields[-1]) + 1
                    payment_proposal_id = payment_instruction_fields[1]
                    # find original instruction record
                    payment_proposal_payments = frappe.get_all("Payment Proposal Payment",
                        filters={'parent': payment_proposal_id, 'idx': payment_instruction_row},
                        fields=['receiver', 'receiver_address_line1', 'receiver_address_line2', 'iban', 'reference'])
                    # suppliers
                    party_match = None
                    if payment_proposal_payments:
                        match_suppliers = frappe.get_all("Supplier", filters={'supplier_name': payment_proposal_payments[0]['receiver']},
                            fields=['name'])
                        if match_suppliers:
                            party_match = match_suppliers[0]['name']
                    # purchase invoices
                    invoice_match = None
                    matched_amount = 0
                    if payment_proposal_payments:
                        match_invoices = frappe.get_all("Purchase Invoice",
                            filters=[['name', '=', payment_proposal_payments[0]['reference']], ['outstanding_amount', '>', 0]],
                            fields=['name', 'grand_total'])
                        if match_invoices:
                            invoice_match = [match_invoices[0]['name']]
                            matched_amount = match_invoices[0]['grand_total']
                    if payment_proposal_payments:
                        new_txn = {
                            'txid': len(txns),
                            'date': date,
                            'currency': entry_currency,
                            'amount': entry_amount,
                            'party_name': payment_proposal_payments[0]['receiver'],
                            'party_address': "{0}, {1}".format(
                                payment_proposal_payments[0]['receiver_address_line1'],
                                payment_proposal_payments[0]['receiver_address_line2']),
                            'credit_debit': credit_debit,
                            'party_iban': payment_proposal_payments[0]['iban'],
                            'unique_reference': unique_reference,
                            'transaction_reference': payment_proposal_payments[0]['reference'],
                            'party_match': party_match,
                            'invoice_matches': invoice_match,
                            'matched_amount': matched_amount
                        }
                        txns.append(new_txn)
                    else:
                        # not matched against payment instruction
                        new_txn = {
                            'txid': len(txns),
                            'date': date,
                            'currency': entry_currency,
                            'amount': entry_amount,
                            'party_name': "???",
                            'party_address': "???",
                            'credit_debit': credit_debit,
                            'party_iban': "???",
                            'unique_reference': unique_reference,
                            'transaction_reference': unique_reference,
                            'party_match': None,
                            'invoice_matches': None,
                            'matched_amount': None
                        }
                        txns.append(new_txn)
                except Exception as err:
                    # no payment instruction
                    new_txn = {
                        'txid': len(txns),
                        'date': date,
                        'currency': entry_currency,
                        'amount': entry_amount,
                        'party_name': "???",
                        'party_address': "???",
                        'credit_debit': credit_debit,
                        'party_iban': "???",
                        'unique_reference': unique_reference,
                        'transaction_reference': unique_reference,
                        'party_match': None,
                        'invoice_matches': None,
                        'matched_amount': None
                    }
                    txns.append(new_txn)

    # check against bank wizard patterns
    patterns = frappe.get_all("Bank Wizard Pattern", filters={'disabled': 0}, fields=['name', 'target_field', 'operator', 'value'])
    if len(patterns) > 0:
        FIELD_MAP = {
            "Transaction Reference": "transaction_reference",
            "Party Name": "party_name",
            "Party Address": "party_address",
            "Amount": "amount",
            "Unallocated_amount": "unallocated_amount"
        }
        for txn in txns:
            txn['unallocated_amount'] = flt(txn['amount']) - flt(txn['matched_amount'])
            txn['amount'] = flt(txn['amount'])
            for p in patterns:
                frappe.log_error("{0}: {1}".format(p['value'], type(p['value'])))
                try:
                    if p['operator'] == "=":
                        if (type(txn[FIELD_MAP[p['target_field']]]) == float and txn[FIELD_MAP[p['target_field']]] == flt(p['value'])) \
                            or txn[FIELD_MAP[p['target_field']]] == p['value']:
                        
                            txn['pattern'] = p['name']
                        break
                    elif p['operator'] == "includes" and p['value'] in txn[FIELD_MAP[p['target_field']]]:
                        txn['pattern'] = p['name']
                        break
                    elif p['operator'] == "&lt;" and type(txn[FIELD_MAP[p['target_field']]]) == float and flt(txn[FIELD_MAP[p['target_field']]]) < flt(p['value']):
                        txn['pattern'] = p['name']
                        break
                except Exception as err:
                    frappe.log_error( err , "Bank Wizard: Pattern Error")
                
                
    return txns

@frappe.whitelist()
def make_payment_entry(amount, date, reference_no, paid_from=None, paid_to=None, type="Receive",
    party=None, party_type=None, references=None, remarks=None, auto_submit=False, exchange_rate=1,
    party_iban=None, company=None, pattern=None, instructed_amount=None, xchg_rate=None,
    booked_amount=None):
    # assert list
    if references:
        references = ast.literal_eval(references)
    if str(auto_submit) == "1":
        auto_submit = True
    reference_type = "Sales Invoice"
    # find company
    if not company:
        if paid_from:
            company = frappe.get_value("Account", paid_from, "company")
        elif paid_to:
            company = frappe.get_value("Account", paid_to, "company")
    # ---- taux de change & montants multi-devises -----------------------------------------------
    # Le cote TIERS (client/fournisseur) peut etre en devise (ex. creancier EUR 2001) ; le cote BANQUE
    # est en general en CHF. `amount` = montant de la transaction (souvent EN DEVISE, ex. EUR 5400 ; sert
    # au MATCHING contre la facture en devise). `booked_amount` = montant reellement BOOKE en CHF (ex.
    # 4988.93, du camt). Pour qu'ERPNext calcule le gain/perte de change : cote tiers = montant EN DEVISE
    # + taux reel, cote banque = CHF booke au taux 1. Taux = <XchgRate> du camt (valide) sinon derive
    # (CHF booke / montant devise).
    company_currency = frappe.get_value("Company", company, "default_currency")
    # Resoudre le VRAI compte tiers (souvent en devise) AVANT la detection de devise. Le bank wizard
    # envoie le compte par defaut generique (2000/1100, en CHF) ; get_party_account rend le compte
    # specifique au tiers (ex. creancier EUR 2001). Sans cette resolution en amont, party_currency est
    # lue sur le compte CHF -> le bloc multi-devises plus bas ne se declenche pas et le taux reste a 1
    # (bug: paiement d'une facture EUR booke a plat en CHF, sans reprise du taux reel du camt).
    resolved_party_account = None
    if references and party and party_type in ("Customer", "Supplier"):
        resolved_party_account = get_party_account(party_type, party, company)
        if resolved_party_account:
            if type == "Receive":
                paid_from = resolved_party_account
            else:
                paid_to = resolved_party_account
    party_account = paid_from if type == "Receive" else paid_to      # cote tiers (client/fournisseur)
    bank_side = paid_to if type == "Receive" else paid_from            # cote banque/caisse
    party_currency = (frappe.get_value("Account", party_account, "account_currency")
                      if party_account else company_currency) or company_currency
    bank_currency = (frappe.get_value("Account", bank_side, "account_currency")
                     if bank_side else company_currency) or company_currency
    # defauts mono-devise : meme montant des deux cotes, un seul taux
    paid_amt = received_amt = float(amount)
    src_rate = tgt_rate = exchange_rate
    if party_currency != company_currency and exchange_rate == 1:
        if party_currency != bank_currency:
            # la banque a CONVERTI : montant devise + taux reel cote tiers, CHF au taux 1 cote banque
            foreign_amount = None
            if instructed_amount:
                foreign_amount = abs(float(instructed_amount))
            elif references:
                ref_dt = "Purchase Invoice" if type == "Pay" else "Sales Invoice"
                try:
                    foreign_amount = sum(flt(frappe.get_value(ref_dt, r, "outstanding_amount")) for r in references)
                except Exception:
                    foreign_amount = None
            # CHF reellement debite/credite : le booked_amount du camt, sinon `amount` (cas manuel ou l'appel
            # passe deja le CHF). C'est ce montant qui va cote BANQUE ; le montant en DEVISE va cote TIERS.
            chf_amount = abs(float(booked_amount)) if booked_amount else abs(float(amount))
            if foreign_amount and abs(foreign_amount) > 0.005:
                real_rate = round(chf_amount / abs(foreign_amount), 6)            # derive (fiable) : CHF / devise
                if xchg_rate and abs(abs(foreign_amount) * float(xchg_rate) - chf_amount) <= max(0.05, chf_amount * 0.02):
                    real_rate = float(xchg_rate)                                  # XchgRate du camt (valide)
                if type == "Receive":
                    paid_amt, src_rate = foreign_amount, real_rate                # paid_from = tiers (devise)
                    received_amt, tgt_rate = chf_amount, 1                         # paid_to = banque (CHF)
                else:
                    paid_amt, src_rate = chf_amount, 1                            # paid_from = banque (CHF)
                    received_amt, tgt_rate = foreign_amount, real_rate            # paid_to = tiers (devise)
            else:
                # pas de montant en devise -> ancien fallback taux du jour
                src_rate = tgt_rate = get_exchange_rate(from_currency=party_currency, to_currency=company_currency, transaction_date=date)
        else:
            # tiers et banque dans la MEME devise etrangere (ex. banque EUR + creancier EUR) : un seul taux
            src_rate = tgt_rate = get_exchange_rate(from_currency=party_currency, to_currency=company_currency, transaction_date=date)
    if type == "Receive":
        # receive
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Receive',
            'party_type': party_type,
            'party': party,
            'paid_to': paid_to,
            'paid_amount': paid_amt,
            'received_amount': received_amt,
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'bank_account_no': party_iban,
            'company': company,
            'source_exchange_rate': src_rate,
            'target_exchange_rate': tgt_rate
        })
    elif type == "Pay":
        # pay
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Pay',
            'party_type': party_type,
            'party': party,
            'paid_from': paid_from,
            'paid_amount': paid_amt,
            'received_amount': received_amt,
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'bank_account_no': party_iban,
            'company': company,
            'source_exchange_rate': src_rate,
            'target_exchange_rate': tgt_rate
        })
        if party_type == "Employee":
            reference_type = "Expense Claim"
        else:
            reference_type = "Purchase Invoice"
    else:
        # internal transfer (against intermediate account)
        payment_entry = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Internal Transfer',
            'paid_from': paid_from,
            'paid_to': paid_to,
            'paid_amount': paid_amt,
            'received_amount': received_amt,
            'reference_no': reference_no,
            'reference_date': date,
            'posting_date': date,
            'remarks': remarks,
            'camt_amount': float(amount),
            'bank_account_no': party_iban,
            'company': company,
            'source_exchange_rate': src_rate,
            'target_exchange_rate': tgt_rate
        })
    if party_type == "Employee":
        payment_entry.paid_to = get_payable_account(company, employee=True)['account'] or paid_to         # note: at creation, this is ignored
    # Rapprochement d'une (ou plusieurs) facture(s) sur un tiers Customer/Supplier : on pose le compte
    # de tiers NORMAL (creance 1100 / dette 2000, ou le compte specifique du tiers) ET on ajoute les
    # references AVANT l'insert. Sans ca, l'option "Book Advance Payments in Separate Party Account"
    # bascule le paiement non alloue sur le compte d'ACOMPTE (2030/1130) au moment de l'insert, puis
    # l'ajout de la reference apres coup produit le mismatch "facture sur 1100 / paiement sur 2030".
    # En mettant les references des l'insert, ERPNext resout le bon compte et ne le reecrit pas.
    # Robuste que la separation soit activee ou non (get_party_account rend deja 1100/2000 sans elle).
    # Un encaissement/decaissement SANS reference (vrai acompte via bouton Customer/Supplier) n'est pas
    # touche -> l'acompte reste correctement sur 2030/1130.
    prebooked_references = False
    if references and party and party_type in ("Customer", "Supplier"):
        # compte tiers deja resolu en tete (resolved_party_account) : on l'affecte au doc pour que la
        # reference s'attache au bon compte des l'insert (evite le mismatch 1100/2030 quand la separation
        # des acomptes est active).
        if resolved_party_account:
            if payment_entry.payment_type == "Receive":
                payment_entry.paid_from = resolved_party_account
            elif payment_entry.payment_type == "Pay":
                payment_entry.paid_to = resolved_party_account
        for reference in references:
            append_reference(payment_entry, reference, reference_type)
        prebooked_references = True
    new_entry = payment_entry.insert()
    # add references after insert (advances / employee : party account not concerned by the mismatch)
    if references and not prebooked_references:
        for reference in references:
            create_reference(new_entry.name, reference, reference_type)
    # pattern matching
    if pattern:
        pattern_entry = frappe.get_doc("Payment Entry", new_entry.name) # include changes from reference
        pattern_definition = frappe.get_doc("Bank Wizard Pattern", pattern)
        amount = pattern_entry.unallocated_amount or pattern_entry.difference_amount
        if pattern_entry.payment_type == "Receive":
            amount = (-1) * amount
        for deduction in pattern_definition.deductions:
            if deduction.company == company:
                pattern_entry.append("deductions", {
                    'account': deduction.deduction_account,
                    'cost_center': deduction.deduction_cost_center,
                    'amount': amount
                })
            pattern_entry.save()
            frappe.db.commit()
            break
    # automatically submit if enabled
    if auto_submit:
        matched_entry = frappe.get_doc("Payment Entry", new_entry.name) # include changes from reference
        if matched_entry.difference_amount != 0:
            # for auto-submit, we need to clear this out to the exchange account
            exchange_account = frappe.get_cached_value("Company", matched_entry.company, "exchange_gain_loss_account")
            cost_center = frappe.get_cached_value("Company", matched_entry.company, "round_off_cost_center")
            matched_entry.append("deductions", {
                'account': exchange_account,
                'cost_center': cost_center,
                'amount': matched_entry.difference_amount
            })
            matched_entry.save()
        matched_entry.submit()
        frappe.db.commit()
    return {'link': get_url_to_form("Payment Entry", new_entry.name), 'payment_entry': new_entry.name}

# appends a reference row to the Payment Entry doc BEFORE insert (so ERPNext resolves the normal
# party account instead of the advance account). Same allocation logic as create_reference.
def append_reference(payment_entry_doc, invoice_reference, invoice_type="Sales Invoice"):
    if "Invoice" in invoice_type:
        total_amount = frappe.get_value(invoice_type, invoice_reference, "base_grand_total")
        outstanding_amount = frappe.get_value(invoice_type, invoice_reference, "outstanding_amount")
    else:
        total_amount = frappe.get_value(invoice_type, invoice_reference, "total_claimed_amount")
        outstanding_amount = total_amount
    # montant du paiement dans la DEVISE DU TIERS (pour plafonner l'allocation) : cote tiers = paid_from
    # pour un Receive (creance), paid_to pour un Pay (dette). En mono-devise, les deux sont egaux.
    if payment_entry_doc.payment_type == "Pay":
        party_amount = payment_entry_doc.received_amount
    else:
        party_amount = payment_entry_doc.paid_amount
    allocated_amount = outstanding_amount if party_amount > outstanding_amount else party_amount
    payment_entry_doc.append("references", {
        "reference_doctype": invoice_type,
        "reference_name": invoice_reference,
        "total_amount": total_amount,
        "outstanding_amount": outstanding_amount,
        "allocated_amount": allocated_amount,
    })


# creates the reference record in a payment entry
def create_reference(payment_entry, invoice_reference, invoice_type="Sales Invoice"):
    # create a new payment entry reference
    reference_entry = frappe.get_doc({"doctype": "Payment Entry Reference"})
    reference_entry.parent = payment_entry
    reference_entry.parentfield = "references"
    reference_entry.parenttype = "Payment Entry"
    reference_entry.reference_doctype = invoice_type
    reference_entry.reference_name = invoice_reference
    if "Invoice" in invoice_type:
        reference_entry.total_amount = frappe.get_value(invoice_type, invoice_reference, "base_grand_total")
        reference_entry.outstanding_amount = frappe.get_value(invoice_type, invoice_reference, "outstanding_amount")
        paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")
        if paid_amount > reference_entry.outstanding_amount:
            reference_entry.allocated_amount = reference_entry.outstanding_amount
        else:
            reference_entry.allocated_amount = paid_amount
    else:
        # expense claim:
        reference_entry.total_amount = frappe.get_value(invoice_type, invoice_reference, "total_claimed_amount")
        reference_entry.outstanding_amount = reference_entry.total_amount
        paid_amount = frappe.get_value("Payment Entry", payment_entry, "paid_amount")
        if paid_amount > reference_entry.outstanding_amount:
            reference_entry.allocated_amount = reference_entry.outstanding_amount
        else:
            reference_entry.allocated_amount = paid_amount
    reference_entry.insert();
    # update unallocated amount
    payment_record = frappe.get_doc("Payment Entry", payment_entry)
    payment_record.unallocated_amount -= reference_entry.allocated_amount
    payment_record.save()
    return

def get_numeric_only_reference(s):
    n = ""
    for c in s:
        if c.isdigit():
            n += c
    return n

def remove_special_characters(s):
    return (s or "").replace(" ", "").replace("-", "")
    
