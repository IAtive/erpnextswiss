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
			"label": "Devise d'origine (FX)",
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
			"description": "Devise d'origine de l'opération (ex. EUR) quand le compte est en CHF.",
		},
		{
			"fieldname": "original_amount",
			"label": "Original Amount",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "original_currency",
			"read_only": 1,
			"description": "Montant dans la devise d'origine (ex. 1440.00 EUR).",
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
			"description": "Taux appliqué par la banque le jour du paiement (montant compte / montant d'origine).",
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


# Traductions de NOS libellés custom (sources en anglais dans les JS).
# En v15, le format translations/*.csv n'est plus lu -> on passe par le doctype
# Translation (chargé en dernier = priorité max). Idempotent.
TRANSLATION_OVERRIDES = [
	{"language": "fr", "source_text": "Import camt / ZIP", "translated_text": "Importer camt / ZIP"},
	# ajouter ici les autres libellés custom + langues (de, it, ...)
]


def apply_translation_overrides():
	for t in TRANSLATION_OVERRIDES:
		if not frappe.db.exists("Translation", {"language": t["language"], "source_text": t["source_text"]}):
			frappe.get_doc({"doctype": "Translation", **t}).insert(ignore_permissions=True)
	frappe.db.commit()


def after_migrate():
	"""Hook after_migrate : traductions custom + (si banking) champs FX & menu ALYF."""
	from erpnextswiss.treasury.utils import is_banking_installed

	apply_translation_overrides()
	if not is_banking_installed():
		return
	create_custom_fields(FX_CUSTOM_FIELDS, ignore_validate=True)
	add_payment_proposal_to_alyf_sidebar()
	frappe.db.commit()
