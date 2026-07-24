# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Swiss QR-bill : configuration de la méthode de référence par compte, comme bexio.
# Phase 1 = champs uniquement (purement additif, aucun changement de comportement).
#
#   Account.qr_method  : SCOR | QRR | NON     (méthode du bulletin QR, comme bexio)
#   Account.qr_iban    : QR-IBAN              (seulement si QRR ; l'IBAN classique
#                                              `iban` reste dédié aux paiements pain.001)
#   Sales Invoice.qr_reference       : référence active (QRR ou SCOR) -> print + matching
#   Sales Invoice.qr_reference_type  : snapshot de la méthode utilisée sur la facture
#
# Ces champs existent INDÉPENDAMMENT d'ALYF (le QR-bill est du core suisse), donc
# ce setup n'est PAS gardé par is_banking_installed() (contrairement à Treasury).

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


QR_CUSTOM_FIELDS = {
	"Account": [
		{
			"fieldname": "qr_method",
			"label": "QR-Bill Method",
			"fieldtype": "Select",
			"options": "SCOR\nQRR\nNON",
			"default": "SCOR",
			"insert_after": "bic",
			"description": (
				"QR-bill method: "
				"SCOR = regular IBAN with RF creditor reference; "
				"QRR = QR-IBAN with 27-digit structured reference; "
				"NON = regular IBAN, without reference."
			),
		},
		{
			"fieldname": "qr_iban",
			"label": "QR-IBAN",
			"fieldtype": "Data",
			"insert_after": "qr_method",
			"depends_on": "eval:doc.qr_method=='QRR'",
			"mandatory_depends_on": "eval:doc.qr_method=='QRR'",
			"description": (
				"QR-IBAN (institution identification between 30000 and 31999). "
				"Used exclusively to issue QR-bills with the QRR method. The regular "
				"IBAN remains used for payments (pain.001)."
			),
		},
	],
	"Sales Invoice": [
		{
			"fieldname": "qr_reference",
			"label": "QR Reference",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "reference_number",
			"description": (
				"Active QR-bill reference (QRR or SCOR depending on the receiving "
				"account method). Unified field read by the print format and by bank "
				"reconciliation."
			),
		},
		{
			"fieldname": "qr_reference_type",
			"label": "QR Reference Type",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "qr_reference",
			"description": "Method frozen on the invoice at issuance time (QRR/SCOR/NON).",
		},
		{
			"fieldname": "qr_account_iban",
			"label": "QR Account IBAN",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "qr_reference_type",
			"description": (
				"Receiving IBAN frozen at issuance time (QR-IBAN for the QRR method, "
				"regular IBAN otherwise). Ensures identical reprinting even if the "
				"account configuration changes later."
			),
		},
	],
}


def migrate_classic_qr_iban():
	"""Déplace toute QR-IBAN mal placée dans le champ IBAN classique -> qr_iban.

	Idempotent : ne touche que les comptes où `iban` est une QR-IBAN ET `qr_iban`
	est vide. La QR-IBAN est déplacée dans qr_iban, la méthode passée à QRR, et
	l'IBAN classique vidé (il faut y remettre l'IBAN normal pour les paiements).
	set_value écrit en direct (ne déclenche pas la validation) -> pas de blocage.
	"""
	from erpnextswiss.swiss_qr.validation import is_qr_iban

	moved = 0
	for acc in frappe.get_all("Account", fields=["name", "iban", "qr_iban"]):
		if acc.iban and is_qr_iban(acc.iban) and not acc.qr_iban:
			frappe.db.set_value("Account", acc.name, {
				"qr_iban": acc.iban,
				"qr_method": "QRR",
				"iban": "",
			}, update_modified=False)
			moved += 1
	if moved:
		frappe.logger().info("swiss_qr: QR-IBAN déplacée hors du champ IBAN sur %d compte(s)" % moved)


def after_migrate():
	"""Hook after_migrate : champs de configuration QR-bill + migration (idempotent)."""
	create_custom_fields(QR_CUSTOM_FIELDS, ignore_validate=True)
	migrate_classic_qr_iban()
	frappe.db.commit()
