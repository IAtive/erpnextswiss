# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Import camt.053/052 FX-aware, autonome (ElementTree, pas de dépendance fintech
# donc pas de licence joonis requise pour l'upload de fichiers).
#
# Points clés vs l'import ALYF actuel :
#   1. Le montant de la Bank Transaction est TOUJOURS le montant *booké* en devise
#      du compte (<Ntry><Amt Ccy="CHF">) -> plus de rejet "EUR sur compte CHF".
#   2. Le montant d'origine (EUR) + le taux banque (<CcyXchg><XchgRate>) sont
#      conservés dans les champs custom original_amount / original_currency /
#      bank_exchange_rate -> la réconciliation multidevise devient exacte.
#   3. Accepte un ZIP de plusieurs camt (routés par IBAN) ou un seul XML.

import io
import re
import zipfile
import hashlib
from xml.etree import ElementTree as ET

import frappe
from frappe import _


def _is_structured_ref(reference):
	"""True si la référence est une référence structurée QR-bill (QRR ou SCOR).

	QRR = 26-27 chiffres (éventuellement espacés). SCOR/RF = 'RF' + 2 chiffres + corps.
	On nettoie les espaces AVANT de tester pour couvrir les deux formats espacés.
	"""
	compact = re.sub(r"\s", "", reference or "")
	if re.fullmatch(r"\d{26,27}", compact):          # QRR
		return True
	if re.fullmatch(r"RF\d{2}[0-9A-Za-z]{1,21}", compact):  # SCOR (ISO 11649)
		return True
	return False


# ---------------------------------------------------------------------------
# Helpers XML (namespace-agnostic : on compare uniquement le local-name)
# ---------------------------------------------------------------------------
def _local(tag):
	return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(node, *path):
	"""Descend le premier enfant matchant chaque local-name du path."""
	cur = node
	for name in path:
		nxt = None
		for child in cur:
			if _local(child.tag) == name:
				nxt = child
				break
		if nxt is None:
			return None
		cur = nxt
	return cur


def _text(node, *path):
	el = _find(node, *path) if path else node
	return el.text.strip() if (el is not None and el.text) else None


def _iter(node, name):
	for child in node.iter():
		if _local(child.tag) == name:
			yield child


def _first(node, name):
	for el in _iter(node, name):
		return el
	return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_camt(xml_bytes):
	"""Retourne une liste de statements : {iban, currency, transactions:[...]}."""
	root = ET.fromstring(xml_bytes)
	statements = []
	for stmt in _iter(root, "Stmt"):
		acct = _first(stmt, "Acct")
		iban = None
		currency = None
		if acct is not None:
			iban = _text(acct, "Id", "IBAN") or _text(_first(acct, "Id"), "Othr", "Id")
			currency = _text(acct, "Ccy")
		txns = [_parse_entry(ntry, currency) for ntry in _iter(stmt, "Ntry")]
		statements.append({"iban": iban, "currency": currency, "transactions": [t for t in txns if t]})
	return statements


def _parse_entry(ntry, account_currency):
	# statut : ne garder que les écritures comptabilisées (BOOK)
	sts = _text(ntry, "Sts") or _text(ntry, "Sts", "Cd")
	if sts and sts.upper() not in ("BOOK", "BOOK "):
		return None

	amt_el = _first(ntry, "Amt")
	if amt_el is None:
		return None
	booked_amount = float(amt_el.text.strip())
	booked_ccy = (amt_el.attrib.get("Ccy") or account_currency or "").strip()
	cdtdbt = (_text(ntry, "CdtDbtInd") or "CRDT").upper()

	date = _text(ntry, "BookgDt", "Dt") or _text(ntry, "BookgDt", "DtTm") \
		or _text(ntry, "ValDt", "Dt")
	if date and len(date) > 10:
		date = date[:10]

	acct_svcr_ref = _text(ntry, "AcctSvcrRef")

	# --- détails transaction (premier TxDtls) ---
	txdtls = _first(ntry, "TxDtls")
	reference = None
	party_name = None
	party_iban = None
	pmtinfid = None
	orig_ccy = None
	orig_amount = None
	xchg_rate = None

	if txdtls is not None:
		# référence : QRR structurée en priorité, sinon EndToEndId, sinon AcctSvcrRef
		reference = _text(txdtls, "RmtInf", "Strd", "CdtrRefInf", "Ref") \
			or _text(txdtls, "Refs", "EndToEndId") \
			or _text(txdtls, "Refs", "AcctSvcrRef") \
			or acct_svcr_ref
		# tiers : pour un débit -> créancier (fournisseur) ; pour un crédit -> débiteur (client)
		rlt = _first(txdtls, "RltdPties")
		if rlt is not None:
			if cdtdbt == "DBIT":
				party_name = _text(rlt, "Cdtr", "Nm") or _text(rlt, "Cdtr", "Pty", "Nm")
				party_iban = _text(rlt, "CdtrAcct", "Id", "IBAN")
			else:
				party_name = _text(rlt, "Dbtr", "Nm") or _text(rlt, "Dbtr", "Pty", "Nm")
				party_iban = _text(rlt, "DbtrAcct", "Id", "IBAN")
			# PmtInfId : identifiant du bloc de paiement de TON pain.001 (UBS le
			# renvoie dans Refs/PmtInfId) -> bouclage des paiements sortants.
			pmtinfid = _text(txdtls, "Refs", "PmtInfId")
		# FX : on cherche, dans les détails, le premier montant dont la devise
		# diffère de celle du compte (= le montant d'origine, ex. EUR).
		for amt_e in _iter(txdtls, "Amt"):
			ccy = amt_e.attrib.get("Ccy")
			if ccy and account_currency and ccy != account_currency and amt_e.text:
				try:
					orig_amount = float(amt_e.text.strip())
					orig_ccy = ccy
					break
				except ValueError:
					continue
		# le taux peut être au niveau Ntry/AmtDtls (hors TxDtls) -> chercher dans toute l'écriture
		rate_el = _first(ntry, "XchgRate")
		if rate_el is not None and rate_el.text:
			try:
				xchg_rate = float(rate_el.text.strip())
			except ValueError:
				xchg_rate = None

	# fallback : FX détecté sans taux explicite -> taux = montant compte / montant d'origine
	if xchg_rate is None and orig_amount and orig_ccy and orig_ccy != booked_ccy and orig_amount != 0:
		xchg_rate = round(abs(booked_amount) / abs(orig_amount), 9)

	reference = reference or acct_svcr_ref
	# normalisation : QRR/SCOR sans espaces internes -> égalité EXACTE avec
	# Sales Invoice.qr_reference (stocké sans espaces) côté matching ALYF.
	# Certaines banques livrent la référence structurée espacée -> on nettoie.
	if reference and _is_structured_ref(reference):
		reference = re.sub(r"\s", "", reference)

	# transaction_id stable pour la déduplication
	basis = acct_svcr_ref or "{0}|{1}|{2}|{3}".format(date, booked_amount, cdtdbt, reference)
	transaction_id = hashlib.md5(basis.encode("utf-8")).hexdigest()

	return {
		"date": date,
		"booked_amount": abs(booked_amount),
		"booked_currency": booked_ccy,
		"credit_debit": cdtdbt,
		"reference": reference,
		"transaction_id": transaction_id,
		"party_name": party_name,
		"party_iban": party_iban,
		"pmtinfid": pmtinfid,
		# FX : renseigné seulement si devise d'origine != devise du compte
		"original_currency": orig_ccy if (orig_ccy and orig_ccy != booked_ccy) else None,
		"original_amount": orig_amount if (orig_ccy and orig_ccy != booked_ccy) else None,
		"bank_exchange_rate": xchg_rate if (orig_ccy and orig_ccy != booked_ccy) else None,
	}


# ---------------------------------------------------------------------------
# Création des Bank Transaction natives
# ---------------------------------------------------------------------------
def _get_bank_account(iban):
	if not iban:
		return None
	return frappe.db.get_value("Bank Account", {"iban": iban, "is_company_account": 1}, "name") \
		or frappe.db.get_value("Bank Account", {"iban": iban}, "name")


def create_bank_transactions(statements, fallback_bank_account=None):
	created, skipped, errors = [], [], []
	for stmt in statements:
		bank_account = _get_bank_account(stmt.get("iban")) or fallback_bank_account
		if not bank_account:
			errors.append(_("Aucun Bank Account pour l'IBAN {0}").format(stmt.get("iban")))
			continue
		company = frappe.db.get_value("Bank Account", bank_account, "company")
		account_currency = frappe.db.get_value(
			"Account", frappe.db.get_value("Bank Account", bank_account, "account"), "account_currency"
		)
		for t in stmt["transactions"]:
			if frappe.db.exists("Bank Transaction", {"transaction_id": t["transaction_id"]}):
				skipped.append(t["transaction_id"])
				continue
			try:
				values = {
					"doctype": "Bank Transaction",
					"date": t["date"],
					"bank_account": bank_account,
					"company": company,
					# devise/montant TOUJOURS en devise du compte (montant booké)
					"currency": account_currency,
					"deposit": t["booked_amount"] if t["credit_debit"] == "CRDT" else 0,
					"withdrawal": t["booked_amount"] if t["credit_debit"] == "DBIT" else 0,
					"reference_number": t["reference"],
					"transaction_id": t["transaction_id"],
					"description": t["reference"],
					"bank_party_name": t["party_name"],
					"bank_party_iban": t["party_iban"],
					# champs FX (Treasury)
					"original_currency": t["original_currency"],
					"original_amount": t["original_amount"],
					"bank_exchange_rate": t["bank_exchange_rate"],
				}
				# enrichissement rapprochement : PmtInfId + résolution du tiers
				# (silencieux si non résolu ou si les champs custom sont absents)
				try:
					from erpnextswiss.treasury.reconcile_enrich import enrich_bank_transaction_values
					enrich_bank_transaction_values(values, t)
				except Exception:
					frappe.log_error(frappe.get_traceback(), "Treasury reconcile enrich")
				bt = frappe.get_doc(values)
				bt.insert(ignore_permissions=True)
				bt.submit()
				created.append(bt.name)
			except Exception as e:
				errors.append("{0}: {1}".format(t.get("reference"), str(e)))
	return {"created": created, "skipped": skipped, "errors": errors}


def import_camt_bytes(xml_bytes, fallback_bank_account=None):
	return create_bank_transactions(parse_camt(xml_bytes), fallback_bank_account)


def import_zip_or_xml(content, filename=None, fallback_bank_account=None):
	"""Accepte un ZIP (plusieurs camt) ou un seul XML. Route par IBAN."""
	result = {"created": [], "skipped": [], "errors": []}
	is_zip = zipfile.is_zipfile(io.BytesIO(content))
	if is_zip:
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			for name in zf.namelist():
				if not name.lower().endswith(".xml"):
					continue
				r = import_camt_bytes(zf.read(name), fallback_bank_account)
				for k in result:
					result[k] += r[k]
	else:
		r = import_camt_bytes(content, fallback_bank_account)
		for k in result:
			result[k] += r[k]
	return result


@frappe.whitelist()
def upload_camt(fallback_bank_account=None):
	"""Endpoint d'upload : ZIP ou XML, via le fichier joint à la requête."""
	from erpnextswiss.treasury.utils import is_banking_installed
	if not is_banking_installed():
		frappe.throw(_("L'app banking (ALYF) n'est pas installée."))
	files = frappe.request.files
	if not files or "file" not in files:
		frappe.throw(_("Aucun fichier fourni."))
	content = files["file"].read()
	return import_zip_or_xml(content, fallback_bank_account=fallback_bank_account)
