# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Génération SERVEUR de la référence du bulletin QR (QRR ou SCOR), selon la
# méthode configurée sur le compte de RÉCEPTION de la société
# (Company.default_bank_account -> Account.qr_method).
#
# Doc_event : Sales Invoice.validate (idempotent). Remplace l'ancienne génération
# cliente onload (RF aléatoire, non conditionnel) de public/js/sales_invoice.js.
#
#   qr_reference       : référence ACTIVE, stockée SANS espaces (matching camt) ->
#                        QRR = 27 chiffres, SCOR = RF + 2 check + corps
#   qr_reference_type  : QRR | SCOR | NON  (snapshot de la méthode utilisée)
#
# Les champs legacy (esr_reference / reference_number / reference_number_full) sont
# alimentés en miroir pour ne pas casser les print formats existants.

import re
import frappe
from erpnextswiss.erpnextswiss.common_functions import get_scor_reference
from erpnextswiss.scripts.esr_qr_tools import add_check_digit_to_esr_reference


def _receiving_config(company):
	"""(méthode, IBAN) du compte de réception de la société (None,None si non configuré).

	L'IBAN retourné est déjà résolu selon la méthode : QR-IBAN en QRR, IBAN
	classique sinon.
	"""
	if not company:
		return (None, None)
	account = frappe.db.get_value("Company", company, "default_bank_account")
	if not account:
		return (None, None)
	acc = frappe.db.get_value("Account", account, ["qr_method", "iban", "qr_iban"], as_dict=True)
	if not acc:
		return (None, None)
	method = acc.qr_method or "SCOR"
	iban = (acc.qr_iban if method == "QRR" else acc.iban) or ""
	return (method, iban)


def _esr_raw_from_name(name):
	"""Raw QRR de 26 chiffres, unique, dérivé du nom de la facture (année + n°)."""
	digits = re.sub(r"\D", "", name or "") or "0"
	return digits[-26:].rjust(26, "0")


def _scor_seed_from_name(name):
	"""Graine SCOR (chiffres du nom, <= 21) -> déterministe et unique par facture."""
	return (re.sub(r"\D", "", name or "") or "0")[-21:]


def _format_spaced(reference):
	"""Groupe une référence en blocs de 4 pour l'affichage (RF48 5000 0567 8901)."""
	return re.sub(r"(.{4})(?=.)", r"\1 ", reference)


def set_qr_reference(doc, method=None):
	"""Doc_event Sales Invoice.validate : fige le bulletin QR sur la facture.

	SNAPSHOT immuable : méthode (qr_reference_type) + IBAN (qr_account_iban) +
	référence (qr_reference) sont posés UNE fois, à l'émission. Une facture déjà
	émise se réimprime à l'identique même si la config du compte change ensuite.
	"""
	# snapshot déjà pris -> figé, on ne touche plus
	if doc.get("qr_reference_type"):
		return

	qr_method, iban = _receiving_config(doc.company)

	# aucun compte de réception configuré -> on ne fige rien (rendu = repli live)
	if not qr_method:
		return

	# QRR/SCOR dérivent la référence du nom (attribué au validate lors d'un insert) ;
	# garde-fou : si le nom manque encore, on ne fige rien et on repose au prochain save.
	if qr_method != "NON" and not doc.name:
		return

	# --- snapshot méthode + IBAN de réception (immutabilité) ---
	doc.qr_reference_type = qr_method
	doc.qr_account_iban = iban

	if qr_method == "QRR":
		raw26 = _esr_raw_from_name(doc.name)
		doc.qr_reference = add_check_digit_to_esr_reference(raw26, formatted=False)  # 27 chiffres
		doc.esr_reference = add_check_digit_to_esr_reference(raw26, formatted=True)  # legacy (affichage)
	elif qr_method == "SCOR":
		scor = get_scor_reference(_scor_seed_from_name(doc.name))  # RF... sans espaces
		doc.qr_reference = scor
		doc.reference_number_full = scor                # legacy (payload print format B)
		doc.reference_number = _format_spaced(scor)     # legacy (affichage)
	# NON : pas de référence (mais méthode + IBAN figés)
