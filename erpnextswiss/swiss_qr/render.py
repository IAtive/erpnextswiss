# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Rendu LOCAL du bulletin QR suisse (récépissé + section paiement) via python-qrbill.
# Remplace l'appel au service PHP externe (data.libracore.ch / qr-code.2itea.global).
#
# Exposé comme méthode Jinja `get_qr_bill_svg` -> le print format embarque le SVG
# directement (aucune requête réseau, aucune donnée envoyée à un tiers).
#
# La méthode (QRR/SCOR/NON) et l'IBAN sont lus sur le compte de RÉCEPTION
# (Company.default_bank_account) :
#   QRR  -> Account.qr_iban (QR-IBAN)  + référence 27 chiffres
#   SCOR -> Account.iban    (classique) + référence RF
#   NON  -> Account.iban    (classique) + aucune référence

import io
import frappe
from frappe import _

# devises autorisées par le standard Swiss QR-bill
_ALLOWED_CURRENCIES = ("CHF", "EUR")


def _country_code(country_name, default="CH"):
	if not country_name:
		return default
	code = frappe.db.get_value("Country", country_name, "code")
	return (code or default).upper()


def _qrbill_address(party_name, address, mandatory=True):
	"""Construit l'adresse structurée attendue par qrbill à partir d'un doc Address.

	Créancier -> mandatory=True (obligatoire). Débiteur -> mandatory=False : si
	l'adresse est incomplète on renvoie None et le bulletin est émis SANS débiteur
	(le payeur le remplit lui-même), ce que le standard Swiss QR autorise.
	"""
	if not address or not (address.get("pincode") and address.get("city")):
		if mandatory:
			frappe.throw(_(
				"Incomplete address for '{0}': the QR-bill requires a structured "
				"address (street, postal code, town, country)."
			).format(party_name))
		return None
	return {
		"name": (party_name or "")[:70],
		"street": (address.get("address_line1") or "")[:70],
		"pcode": (address.get("pincode") or "").strip()[:16],
		"city": (address.get("city") or "")[:35],
		"country": _country_code(address.get("country")),
	}


def get_qr_bill_svg(sales_invoice):
	"""Méthode Jinja : renvoie le SVG du bulletin QR pour une Sales Invoice.

	SAFE : en cas de configuration incomplète (IBAN/adresse), renvoie un encart
	d'erreur lisible au lieu de casser l'impression. `sales_invoice` = doc ou nom.
	"""
	try:
		return _build_qr_bill_svg(sales_invoice)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Swiss QR bill render")
		return (
			'<div style="border:1px solid #c0392b;color:#c0392b;padding:8px;'
			'font-size:9pt;">{0} {1}</div>'
		).format(_("QR-bill unavailable:"), frappe.utils.escape_html(str(e)))


def _build_qr_bill_svg(sales_invoice):
	"""Construit le SVG du bulletin QR (peut lever une exception)."""
	from qrbill import QRBill
	from erpnextswiss.scripts.crm_tools import (
		get_primary_company_address,
		get_primary_customer_address,
	)

	doc = sales_invoice
	if not hasattr(doc, "doctype"):
		doc = frappe.get_doc("Sales Invoice", sales_invoice)

	if doc.currency not in _ALLOWED_CURRENCIES:
		frappe.throw(_(
			"The QR-bill only supports CHF or EUR (invoice in {0})."
		).format(doc.currency))

	# Source de vérité = le SNAPSHOT figé sur la facture à l'émission (immutable) :
	# méthode + IBAN. Ainsi une facture déjà émise se réimprime à l'identique même
	# si la config du compte change ensuite (ex. SCOR -> QRR).
	method = doc.get("qr_reference_type")
	iban = doc.get("qr_account_iban")

	# Repli sur la config LIVE du compte si le snapshot est absent OU partiel
	# (factures antérieures à l'ajout des champs -> on complète ce qui manque).
	if not method or not iban:
		account_name = frappe.db.get_value("Company", doc.company, "default_bank_account")
		if not account_name:
			frappe.throw(_(
				"Please set a default bank account on company {0}."
			).format(doc.company))
		acc = frappe.db.get_value(
			"Account", account_name, ["qr_method", "iban", "qr_iban"], as_dict=True
		)
		if not method:
			method = (acc.qr_method or "SCOR") if acc else "SCOR"
		if not iban:
			iban = (acc.qr_iban if method == "QRR" else acc.iban) if acc else None

	if not iban:
		frappe.throw(_(
			"Receiving IBAN missing for method {0}."
		).format(method))

	creditor = _qrbill_address(
		frappe.db.get_value("Company", doc.company, "company_name") or doc.company,
		get_primary_company_address(doc.company),
		mandatory=True,
	)
	debtor = _qrbill_address(
		doc.customer_name or doc.customer,
		get_primary_customer_address(doc.customer),
		mandatory=False,
	)

	# langue du bulletin = celle du sélecteur d'impression (frappe.local.lang),
	# sinon la langue de la facture, sinon l'anglais. qrbill : en/de/fr/it.
	lang = (getattr(frappe.local, "lang", None) or doc.get("language") or "en")
	lang = str(lang).split("-")[0].lower()
	if lang not in ("en", "de", "fr", "it"):
		lang = "en"

	kwargs = dict(
		account=(iban or "").replace(" ", ""),
		creditor=creditor,
		amount="{:.2f}".format(doc.rounded_total or doc.grand_total),
		currency=doc.currency,
		language=lang,
		additional_information=(doc.name or "")[:140],
	)
	if debtor:
		kwargs["debtor"] = debtor
	# référence seulement en QRR/SCOR (NON = pas de référence)
	if method != "NON" and doc.get("qr_reference"):
		kwargs["reference_number"] = doc.qr_reference

	bill = QRBill(**kwargs)
	buf = io.StringIO()
	bill.as_svg(buf)
	return buf.getvalue()
