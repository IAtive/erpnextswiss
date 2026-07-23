# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Overrides posés sur des méthodes ALYF (banking) via hooks.override_whitelisted_methods.
# Toute la logique est déléguée au module treasury -> ALYF n'est jamais modifié.

import frappe


def apply_monkeypatches(bootinfo=None):
	"""Les uploads Frappe (frappe.handler.upload_file) appellent la méthode via
	get_attr() -> ils COURT-CIRCUITENT override_whitelisted_methods. Pour que
	l'upload camt de l'écran ALYF utilise quand même notre import FX/ZIP, on
	remplace la fonction dans le module banking (monkeypatch). Idempotent, gardé
	par is_banking_installed. Branché sur boot_session (s'exécute au chargement du
	desk, avant tout upload).
	"""
	from erpnextswiss.treasury.utils import is_banking_installed

	if not is_banking_installed():
		return
	try:
		import banking.ebics.utils as banking_utils

		banking_utils.upload_camt_file = upload_camt_file
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Treasury: monkeypatch upload_camt_file")


@frappe.whitelist()
def upload_camt_file():
	"""Remplace banking.ebics.utils.upload_camt_file par l'import Treasury :
	- FX correct (montant en devise du compte + taux banque conservé),
	- accepte un ZIP de plusieurs camt (routés par IBAN) ou un seul XML,
	- pas de dépendance fintech (donc pas de licence joonis pour l'upload).

	Conserve l'interface d'ALYF : `frappe.local.uploaded_file` (bytes) +
	`frappe.form_dict.docname` (Bank Account sélectionné) comme fallback.
	"""
	frappe.has_permission("Bank Transaction", "create", throw=True)

	from erpnextswiss.treasury.camt_import import import_zip_or_xml

	file_bytes = frappe.local.uploaded_file
	bank_account = frappe.form_dict.get("docname")
	result = import_zip_or_xml(file_bytes, fallback_bank_account=bank_account)

	# récap visible pour l'utilisateur (sinon les "ignorés" sont silencieux)
	msg = frappe._("Importées: {0} · Doublons ignorés: {1} · Erreurs: {2}").format(
		len(result["created"]), len(result["skipped"]), len(result["errors"])
	)
	if result["errors"]:
		msg += "<br><br><b>" + frappe._("Erreurs") + " :</b><br>" + "<br>".join(
			frappe.utils.escape_html(e) for e in result["errors"][:15]
		)
	frappe.msgprint(msg, title=frappe._("Import camt / ZIP"), indicator="orange" if result["errors"] else "green")
	return result


def payment_entry_apply_bank_fx(doc, method=None):
	"""doc_event Payment Entry (validate) : quand un paiement ON-ACCOUNT est créé depuis
	une transaction bancaire FX enrichie par Treasury, impose le montant tiers RÉEL
	(ex. EUR 1440) et le TAUX BANQUE exact — au lieu de la recopie du montant compte.

	Sur-ensemble STRICT : ne fait rien sauf si TOUTES ces conditions sont réunies :
	  - app banking installée,
	  - PE en cours de création (is_new),
	  - PE on-account (aucune allocation de facture -> pas d'interférence avec le flux facture),
	  - PE lié à une Bank Transaction (created_from_bank_transaction),
	  - cette transaction a original_amount + bank_exchange_rate (données Treasury),
	  - multidevise (devise du compte tiers != devise de la transaction).
	Tous les autres cas (CHF, sans données Treasury, avec facture) : AUCUN changement.
	"""
	from erpnextswiss.treasury.utils import is_banking_installed

	if not is_banking_installed():
		return
	if not doc.is_new() or doc.get("references"):
		return
	bt_name = doc.get("created_from_bank_transaction")
	if not bt_name:
		return
	bt = frappe.db.get_value(
		"Bank Transaction", bt_name, ["currency", "original_amount", "bank_exchange_rate"], as_dict=True
	)
	if not bt or not bt.original_amount or not bt.bank_exchange_rate:
		return

	if doc.payment_type == "Pay" and doc.paid_to_account_currency and doc.paid_to_account_currency != bt.currency:
		doc.received_amount = bt.original_amount
		doc.target_exchange_rate = bt.bank_exchange_rate
		doc.set_amounts()
	elif doc.payment_type == "Receive" and doc.paid_from_account_currency and doc.paid_from_account_currency != bt.currency:
		doc.paid_amount = bt.original_amount
		doc.source_exchange_rate = bt.bank_exchange_rate
		doc.set_amounts()


@frappe.whitelist()
def get_reconcile_amount_context(bank_transaction_name, voucher_doctype, voucher_name):
	"""Override du contexte de conversion d'ALYF : si la Bank Transaction porte le
	taux banque (transaction FX importée par Treasury), on pré-remplit le prompt de
	réconciliation avec CE taux au lieu du taux système -> l'utilisateur confirme
	le taux réel de la banque, écart de change exact en 6999, sans ressaisie.

	Le dialog ALYF calcule target = source * exchange_rate (EUR = CHF * rate), donc
	exchange_rate attendu = devise_cible / devise_source = 1 / bank_exchange_rate
	(car bank_exchange_rate = montant_compte / montant_origine).
	"""
	from banking.klarna_kosma_integration.doctype.bank_reconciliation_tool_beta.bank_reconciliation_tool_beta import (
		get_reconcile_amount_context as alyf_get_context,
	)

	ctx = alyf_get_context(bank_transaction_name, voucher_doctype, voucher_name)
	bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
	rate = bt.get("bank_exchange_rate")
	# devise cible du prompt = devise de la facture (clé "voucher_currency")
	target_currency = ctx.get("voucher_currency") or ctx.get("target_currency")
	# n'injecter que si le taux banque existe et que la devise d'origine == devise cible
	if rate and bt.get("original_currency") == target_currency:
		ctx["exchange_rate"] = round(1.0 / rate, 9)
		ctx["treasury_bank_rate"] = 1
	return ctx
