# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Réconciliation multidevise au TAUX DE LA BANQUE.
#
# On part de la Bank Transaction (montant compte, ex. CHF 1339.20) enrichie du
# montant d'origine (EUR 1440) et du taux banque (0.930001). On crée le Payment
# Entry alloué à la facture en imposant montant compte + montant tiers -> le taux
# effectif = celui de la banque, et ERPNext book l'écart de change (facture vs
# banque) sur Company.exchange_gain_loss_account (ex. 6999) AUTOMATIQUEMENT.
# => plus aucune saisie manuelle de taux.

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def reconcile_at_bank_rate(bank_transaction_name, voucher_type, voucher_name):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
	if bt.docstatus != 1:
		frappe.throw(_("La transaction bancaire doit être soumise."))

	company_bank_account = frappe.db.get_value("Bank Account", bt.bank_account, "account")
	bank_amount = flt(bt.withdrawal) or flt(bt.deposit)
	payment_type = "Receive" if flt(bt.deposit) > 0 else "Pay"

	# montant côté tiers : le montant d'origine (EUR) si FX, sinon l'outstanding
	outstanding = flt(frappe.db.get_value(voucher_type, voucher_name, "outstanding_amount"))
	party_amount = flt(bt.original_amount) or outstanding

	pe = get_payment_entry(
		voucher_type,
		voucher_name,
		party_amount=party_amount,
		bank_account=company_bank_account,
		bank_amount=bank_amount,
		payment_type=payment_type,
	)
	pe.reference_no = bt.reference_number or voucher_name
	pe.reference_date = bt.date
	pe.posting_date = bt.date
	pe.insert(ignore_permissions=True)
	pe.submit()

	# lier la Bank Transaction au PE (réconciliation)
	bt.append("payment_entries", {
		"payment_document": "Payment Entry",
		"payment_entry": pe.name,
		"allocated_amount": bank_amount,
	})
	bt.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"payment_entry": pe.name,
		"paid_amount": pe.paid_amount,
		"received_amount": pe.received_amount,
		"source_exchange_rate": pe.source_exchange_rate,
		"target_exchange_rate": pe.target_exchange_rate,
	}
