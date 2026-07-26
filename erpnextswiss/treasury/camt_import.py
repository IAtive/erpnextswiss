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
# Conteneurs ISO 20022 partageant la même structure interne (Acct + Ntry/TxDtls) :
#   Stmt   -> camt.053 (relevé de fin de journée)
#   Ntfctn -> camt.054 (avis de débit/crédit, détail des paiements groupés)
#   Rpt    -> camt.052 (rapport intraday, provisoire)
_CAMT_CONTAINERS = ("Stmt", "Ntfctn", "Rpt")


def parse_camt(xml_bytes):
	"""Retourne une liste de statements : {iban, currency, transactions:[...]}.

	Gère camt.053 / camt.054 / camt.052 (même structure interne). Une écriture
	groupée (camt.054 avec plusieurs <TxDtls>) est éclatée en une transaction par
	paiement -> indispensable au rapprochement fin des encaissements QR-bill.
	"""
	root = ET.fromstring(xml_bytes)
	statements = []
	for container in _CAMT_CONTAINERS:
		for stmt in _iter(root, container):
			acct = _first(stmt, "Acct")
			iban = currency = None
			if acct is not None:
				iban = _text(acct, "Id", "IBAN") or _text(_first(acct, "Id"), "Othr", "Id")
				currency = _text(acct, "Ccy")
			txns = []
			for ntry in _iter(stmt, "Ntry"):
				txns.extend(_parse_entry(ntry, currency))   # liste (batch -> N)
			statements.append({"iban": iban, "currency": currency, "transactions": txns})
	return statements


def _rate_of(el):
	"""Float d'un élément <XchgRate> (ou None)."""
	if el is not None and el.text:
		try:
			return float(el.text.strip())
		except ValueError:
			return None
	return None


def _account_amount_of(txd, account_currency):
	"""Montant d'un <TxDtls> exprimé dans la devise du compte (contre-valeur ou Amt direct).

	Pour un avis groupé, chaque paiement porte son propre montant : on cherche la
	contre-valeur (CntrValAmt, déjà dans la devise du compte) puis, à défaut, un
	<Amt> déjà libellé dans la devise du compte.
	"""
	cv = _find(txd, "AmtDtls", "CntrValAmt", "Amt")
	if cv is not None and cv.attrib.get("Ccy") == account_currency and cv.text:
		try:
			return float(cv.text.strip())
		except ValueError:
			pass
	for amt_e in _iter(txd, "Amt"):
		if amt_e.attrib.get("Ccy") == account_currency and amt_e.text:
			try:
				return float(amt_e.text.strip())
			except ValueError:
				continue
	return None


def _make_txn(date, booked_amount, booked_ccy, cdtdbt, reference, party_name, party_iban,
              pmtinfid, orig_ccy, orig_amount, xchg_rate, dedup_basis):
	"""Assemble un dict transaction (avec FX, normalisation de référence, dédup)."""
	is_fx = bool(orig_ccy and booked_ccy and orig_ccy != booked_ccy)
	# fallback FX : taux = montant compte / montant d'origine
	if is_fx and xchg_rate is None and orig_amount and booked_amount:
		xchg_rate = round(abs(booked_amount) / abs(orig_amount), 9)
	# normalisation : QRR/SCOR sans espaces internes -> égalité EXACTE avec le champ
	# de référence côté matching (qr_reference / esr_reference_number).
	if reference and _is_structured_ref(reference):
		reference = re.sub(r"\s", "", reference)
	basis = dedup_basis or "{0}|{1}|{2}|{3}".format(date, booked_amount, cdtdbt, reference)
	return {
		"date": date,
		"booked_amount": abs(booked_amount) if booked_amount is not None else 0,
		"booked_currency": booked_ccy,
		"credit_debit": cdtdbt,
		"reference": reference,
		"transaction_id": hashlib.md5(basis.encode("utf-8")).hexdigest(),
		"party_name": party_name,
		"party_iban": party_iban,
		"pmtinfid": pmtinfid,
		# FX : renseigné seulement si devise d'origine != devise du compte
		"original_currency": orig_ccy if is_fx else None,
		"original_amount": orig_amount if is_fx else None,
		"bank_exchange_rate": xchg_rate if is_fx else None,
	}


def _parse_entry(ntry, account_currency):
	"""Retourne une LISTE de transactions pour une écriture <Ntry>.

	- 0 ou 1 <TxDtls> : une transaction (montant booké de l'écriture) — inchangé.
	- N <TxDtls> (avis groupé camt.054) : une transaction PAR paiement, avec son
	  propre montant / référence / tiers / FX.
	"""
	# statut : garder les écritures comptabilisées (BOOK) ET les avis en attente
	# (PDNG) — un camt.054 notifie souvent le crédit AVANT son booking définitif.
	# Le dedup par AcctSvcrRef empêche le double-import quand la version BOOK arrive.
	# On écarte seulement l'informatif pur (INFO).
	sts = (_text(ntry, "Sts") or _text(ntry, "Sts", "Cd") or "").strip().upper()
	if sts and sts not in ("BOOK", "PDNG"):
		return []

	amt_el = _first(ntry, "Amt")
	entry_booked = None
	if amt_el is not None and amt_el.text:
		try:
			entry_booked = float(amt_el.text.strip())
		except ValueError:
			entry_booked = None
	entry_ccy = ((amt_el.attrib.get("Ccy") if amt_el is not None else None) or account_currency or "").strip()
	entry_cdtdbt = (_text(ntry, "CdtDbtInd") or "CRDT").upper()

	date = _text(ntry, "BookgDt", "Dt") or _text(ntry, "BookgDt", "DtTm") \
		or _text(ntry, "ValDt", "Dt")
	if date and len(date) > 10:
		date = date[:10]

	entry_acct_svcr_ref = _text(ntry, "AcctSvcrRef")
	# taux au niveau écriture (mono-crédit FX : XchgRate hors TxDtls)
	entry_rate = _rate_of(_first(ntry, "XchgRate"))

	txdtls_list = list(_iter(ntry, "TxDtls"))

	# aucun détail -> une transaction depuis l'écriture (montant global)
	if not txdtls_list:
		if entry_booked is None:
			return []
		return [_make_txn(date, entry_booked, entry_ccy, entry_cdtdbt, entry_acct_svcr_ref,
		                  None, None, None, None, None, entry_rate, entry_acct_svcr_ref)]

	batch = len(txdtls_list) > 1
	out = []
	for i, txd in enumerate(txdtls_list):
		cdtdbt = (_text(txd, "CdtDbtInd") or entry_cdtdbt).upper()
		# référence : QRR/SCOR structurée en priorité, sinon EndToEndId, sinon AcctSvcrRef
		reference = _text(txd, "RmtInf", "Strd", "CdtrRefInf", "Ref") \
			or _text(txd, "Refs", "EndToEndId") \
			or _text(txd, "Refs", "AcctSvcrRef") \
			or entry_acct_svcr_ref
		# tiers : débit -> créancier ; crédit -> débiteur
		party_name = party_iban = None
		rlt = _first(txd, "RltdPties")
		if rlt is not None:
			if cdtdbt == "DBIT":
				party_name = _text(rlt, "Cdtr", "Nm") or _text(rlt, "Cdtr", "Pty", "Nm")
				party_iban = _text(rlt, "CdtrAcct", "Id", "IBAN")
			else:
				party_name = _text(rlt, "Dbtr", "Nm") or _text(rlt, "Dbtr", "Pty", "Nm")
				party_iban = _text(rlt, "DbtrAcct", "Id", "IBAN")
		pmtinfid = _text(txd, "Refs", "PmtInfId")

		# FX : montant d'origine (devise != compte) DANS ce détail
		orig_ccy = orig_amount = None
		for amt_e in _iter(txd, "Amt"):
			ccy = amt_e.attrib.get("Ccy")
			if ccy and account_currency and ccy != account_currency and amt_e.text:
				try:
					orig_amount = float(amt_e.text.strip())
					orig_ccy = ccy
					break
				except ValueError:
					continue
		xchg_rate = _rate_of(_first(txd, "XchgRate")) or entry_rate

		# montant booké de LA transaction :
		#  - batch : montant propre du détail, dans la devise du compte
		#  - mono  : montant booké de l'écriture (le détail porte souvent la devise d'origine)
		if batch:
			booked = _account_amount_of(txd, account_currency)
			if booked is None:  # détail sans montant en devise compte -> dérive du FX
				booked = round(abs(orig_amount) * xchg_rate, 2) if (orig_amount and xchg_rate) else orig_amount
			booked_ccy = account_currency
		else:
			booked = entry_booked
			booked_ccy = entry_ccy

		# dédup : AcctSvcrRef du détail, sinon (batch) hash incluant l'index
		txd_ref = _text(txd, "Refs", "AcctSvcrRef")
		if txd_ref:
			dedup = txd_ref
		elif not batch:
			dedup = entry_acct_svcr_ref
		else:
			dedup = "{0}|{1}|{2}|{3}|{4}".format(entry_acct_svcr_ref, i, date, booked, reference)

		if booked is None:
			continue
		out.append(_make_txn(date, booked, booked_ccy, cdtdbt, reference, party_name,
		                     party_iban, pmtinfid, orig_ccy, orig_amount, xchg_rate, dedup))
	return out


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
			errors.append(_("No Bank Account found for IBAN {0}.").format(stmt.get("iban")))
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
		frappe.throw(_("The ALYF Banking app is not installed."))
	files = frappe.request.files
	if not files or "file" not in files:
		frappe.throw(_("No file provided."))
	content = files["file"].read()
	return import_zip_or_xml(content, fallback_bank_account=fallback_bank_account)
