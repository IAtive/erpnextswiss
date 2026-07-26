# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Treasury setup: crée les champs custom FX sur Bank Transaction.
# Appelé depuis hooks.after_migrate (idempotent).

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FX_CUSTOM_FIELDS = {
	"Bank Transaction": [
		{
			"fieldname": "treasury_fx_section",
			"label": "Original Currency (FX)",
			"fieldtype": "Section Break",
			"insert_after": "bank_party_account_number",
			"collapsible": 1,
		},
		{
			"fieldname": "original_currency",
			"label": "Original Currency",
			"fieldtype": "Link",
			"options": "Currency",
			"insert_after": "treasury_fx_section",
			"read_only": 1,
			"description": "Original currency of the transaction when it differs from the account currency.",
		},
		{
			"fieldname": "original_amount",
			"label": "Original Amount",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "original_currency",
			"read_only": 1,
			"description": "Amount expressed in the original currency of the transaction.",
		},
		{
			"fieldname": "treasury_fx_col",
			"fieldtype": "Column Break",
			"insert_after": "original_amount",
		},
		{
			"fieldname": "bank_exchange_rate",
			"label": "Bank Exchange Rate",
			"fieldtype": "Float",
			"precision": "9",
			"insert_after": "treasury_fx_col",
			"read_only": 1,
			"description": "Rate applied by the bank on the payment date (account amount / original amount).",
		},
		{
			"fieldname": "treasury_reconcile_section",
			"label": "Reconciliation (Treasury)",
			"fieldtype": "Section Break",
			"insert_after": "bank_exchange_rate",
			"collapsible": 0,
		},
		{
			"fieldname": "treasury_pmtinfid",
			"label": "Payment Info ID (pain.001)",
			"fieldtype": "Data",
			"insert_after": "treasury_reconcile_section",
			"read_only": 1,
			"description": (
				"Payment block identifier (PmtInfId) from the camt message, "
				"matching the pain.001 order issued via a payment proposal. "
				"Used for automatic reconciliation of outgoing payments."
			),
		},
	]
}


ALYF_SIDEBAR = "ALYF Banking"


def add_payment_proposal_to_alyf_sidebar():
	"""Ajoute 'Payment Proposal' (ERPNextSwiss) au menu latéral d'ALYF, idempotent.

	Mécanisme : on modifie le record 'Workspace Sidebar' d'ALYF EN BASE. À chaque
	migrate, Frappe ré-importe le record standard d'ALYF (sans notre lien), puis ce
	hook (qui tourne APRÈS la synchro) le re-pose -> le lien survit aux updates
	d'ALYF sans jamais toucher aux fichiers d'ALYF.

	NB : en mode développeur, un save() ré-exporte le fichier standard d'ALYF ; on
	le supprime donc de ce contexte (in_migrate) qui suffit en prod. Ce hook ne fait
	rien si l'app banking ou le record ne sont pas là.
	"""
	from erpnextswiss.treasury.utils import is_banking_installed

	if not is_banking_installed() or not frappe.db.exists("Workspace Sidebar", ALYF_SIDEBAR):
		return
	if not frappe.db.exists("DocType", "Payment Proposal"):
		return

	sb = frappe.get_doc("Workspace Sidebar", ALYF_SIDEBAR)
	if any((i.get("link_to") == "Payment Proposal") for i in sb.items):
		return

	sb.append("items", {
		"type": "Link",
		"link_type": "DocType",
		"link_to": "Payment Proposal",
		"label": "Payment Proposal",
		"icon": "send",
		"child": 0,
		"indent": 0,
		"collapsible": 1,
		"keep_closed": 0,
		"show_arrow": 0,
	})
	sb.flags.ignore_permissions = True
	# in_import=True empêche la ré-export du fichier standard d'ALYF en mode dev
	# (cf. frappe/modules/utils.py). Sans effet/inutile en prod (developer_mode off).
	_prev = frappe.flags.in_import
	frappe.flags.in_import = True
	try:
		sb.save(ignore_permissions=True)
	finally:
		frappe.flags.in_import = _prev
	frappe.db.commit()


# NB : les traductions des libellés custom (« Import camt / ZIP », etc.) ne sont
# plus gérées ici via le doctype Translation. Elles vivent dans les fichiers
# erpnextswiss/locale/*.po (mécanisme standard Frappe, livré avec le fork).


# Mapping de référence pour le rapprochement ALYF : {document_type: field_name}.
# ALYF (Banking Settings.reference_fields -> get_reference_field_map) compare
# Bank Transaction.reference_number à ce champ du document. On pointe la Sales
# Invoice sur qr_reference (QRR/SCOR unifié, stocké sans espaces) -> les
# encaissements clients se rapprochent automatiquement par la référence QR.
ALYF_REFERENCE_FIELDS = {
	"Sales Invoice": "qr_reference",
	"Purchase Invoice": "esr_reference_number",
}


# Types de documents pré-activés par défaut dans l'onglet de rapprochement ALYF
# (Banking Settings.voucher_matching_defaults). Vente + achat = les pièces qu'on
# rapproche principalement.
ALYF_VOUCHER_DEFAULTS = ["Sales Invoice", "Purchase Invoice"]


def configure_alyf_reference_fields():
	"""Ajoute nos mappings de référence à Banking Settings, idempotent.

	N'écrase JAMAIS un mapping existant pour un document_type déjà configuré
	(respect d'un choix manuel de l'utilisateur). N'ajoute que ce qui manque.
	"""
	if not frappe.db.exists("DocType", "Banking Reference Mapping"):
		return
	settings = frappe.get_single("Banking Settings")
	existing = {row.document_type for row in settings.get("reference_fields", [])}
	changed = False
	for doctype, field_name in ALYF_REFERENCE_FIELDS.items():
		if doctype in existing:
			continue  # déjà configuré (peut-être manuellement) -> on ne touche pas
		settings.append("reference_fields", {"document_type": doctype, "field_name": field_name})
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)


def configure_alyf_voucher_defaults():
	"""Pré-active Facture de vente + Facture d'achat dans le rapprochement ALYF.

	Même philosophie que le patch ALYF (set_voucher_matching_defaults) : on ne
	peuple QUE si la liste est vide -> un choix manuel (même partiel) est respecté,
	et un fresh install obtient bien les deux types par défaut.
	"""
	if not frappe.db.exists("DocType", "Voucher Matching Default"):
		return
	settings = frappe.get_single("Banking Settings")
	if settings.get("voucher_matching_defaults"):
		return  # déjà configuré (ALYF ou manuel) -> on ne touche pas
	for doctype in ALYF_VOUCHER_DEFAULTS:
		settings.append("voucher_matching_defaults", {"document_type": doctype})
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


# Défauts de génération des fichiers de paiement (pain.001) sur ERPNextSwiss
# Settings. Cœur ERPNextSwiss (indépendant d'ALYF) :
#   - validate_xml = 1 : valide le pain.001 contre le XSD à la génération du
#     Payment Proposal (attrape les fichiers non conformes avant envoi banque) ;
#   - xml_version = "09" : pain.001.001.09.ch.03 = ADRESSES STRUCTURÉES (type S),
#     conformité SIX (obligatoire depuis nov. 2025). Les versions 03/05 utilisent
#     l'adresse combinée (type K), retirée.
PAIN001_DEFAULT_VERSION = "09"


def ensure_pain001_defaults():
	"""Active la validation XML et force la version pain.001 « 09 » (conformité).

	Idempotent. Applique nos défauts de fork (validation ON + adresses structurées).
	"""
	if not frappe.db.exists("DocType", "ERPNextSwiss Settings"):
		return
	settings = frappe.get_single("ERPNextSwiss Settings")
	changed = False
	if not settings.get("validate_xml"):
		settings.validate_xml = 1
		changed = True
	if settings.get("xml_version") != PAIN001_DEFAULT_VERSION:
		settings.xml_version = PAIN001_DEFAULT_VERSION
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)


def after_migrate():
	"""Hook after_migrate : défauts pain.001 (core) + (si banking) FX, menu & mappings ALYF."""
	from erpnextswiss.treasury.utils import is_banking_installed

	# core ERPNextSwiss (indépendant d'ALYF) : conformité pain.001
	ensure_pain001_defaults()

	if not is_banking_installed():
		frappe.db.commit()
		return
	create_custom_fields(FX_CUSTOM_FIELDS, ignore_validate=True)
	add_payment_proposal_to_alyf_sidebar()
	configure_alyf_reference_fields()
	configure_alyf_voucher_defaults()
	frappe.db.commit()
