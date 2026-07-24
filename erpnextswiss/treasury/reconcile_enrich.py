# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Enrichissement des Bank Transactions à l'import (aide au rapprochement ALYF) :
#
#   1. resolve_party(iban, name, credit_debit)
#        IBAN de la contrepartie -> Bank Account -> Customer/Supplier ;
#        fallback nom EXACT (unique) selon le sens. Pré-remplit party_type/party.
#
#   2. resolve_pmtinfid(pmtinfid, amount, company)
#        PmtInfId de TON pain.001 (PMTINF-{proposal}-{count}) -> Payment Proposal
#        -> Payment Entry (départagé par montant). Boucle les paiements sortants.
#
# Constat sur les vrais camt UBS : l'IBAN de la contrepartie est présent sur les
# débits (fournisseurs) mais ABSENT sur les crédits (clients) -> le fallback nom
# est indispensable côté encaissement. On ne devine jamais : party posé seulement
# si résolution NON ambiguë.

import re
import frappe

PAYMENT_REMARKS = "From Payment Proposal {0}"


def _norm_iban(iban):
	return re.sub(r"\s", "", (iban or "")).upper()


def resolve_party(party_iban, party_name, credit_debit):
	"""Retourne (party_type, party) ou (None, None).

	credit_debit : "CRDT" (un tiers te paie -> Customer) ou "DBIT" (tu paies un
	tiers -> Supplier). Stratégie : IBAN d'abord (exact via Bank Account), sinon
	nom exact unique dans le bon doctype.
	"""
	expected_type = "Customer" if credit_debit == "CRDT" else "Supplier"

	# 1) IBAN -> Bank Account -> party (fiable). On privilégie un Bank Account
	#    dont le party est du type attendu par le sens de l'opération.
	iban = _norm_iban(party_iban)
	if iban:
		rows = frappe.get_all(
			"Bank Account",
			filters={"iban": ("in", [iban, party_iban])},
			fields=["party_type", "party"],
		)
		typed = [r for r in rows if r.party and r.party_type == expected_type]
		if len(typed) == 1:
			return (typed[0].party_type, typed[0].party)
		any_party = [r for r in rows if r.party]
		if len(any_party) == 1:
			return (any_party[0].party_type, any_party[0].party)

	# 2) fallback : nom EXACT unique dans le doctype attendu (jamais de fuzzy)
	name = (party_name or "").strip()
	if name:
		field = "customer_name" if expected_type == "Customer" else "supplier_name"
		matches = frappe.get_all(
			expected_type, filters={field: name}, fields=["name"], limit=2
		)
		if len(matches) == 1:
			return (expected_type, matches[0].name)

	return (None, None)


def _proposal_from_pmtinfid(pmtinfid):
	"""Extrait le nom du Payment Proposal d'un PmtInfId 'PMTINF-{nom}-{count}'."""
	if not pmtinfid:
		return None
	m = re.match(r"^PMTINF-(.+)-\d+$", pmtinfid.strip())
	return m.group(1) if m else None


def resolve_pmtinfid(pmtinfid, amount, company=None):
	"""Retourne (party_type, party, payment_entry) ou (None, None, None).

	Boucle un paiement sortant sur le Payment Entry généré par le Payment Proposal
	d'ERPNextSwiss : PmtInfId -> proposal -> Payment Entries (remarks) -> montant.
	"""
	proposal = _proposal_from_pmtinfid(pmtinfid)
	if not proposal:
		return (None, None, None)

	filters = {"remarks": PAYMENT_REMARKS.format(proposal), "docstatus": 1}
	if company:
		filters["company"] = company
	pes = frappe.get_all(
		"Payment Entry", filters=filters,
		fields=["name", "party_type", "party", "paid_amount"],
	)
	if not pes:
		return (None, None, None)

	# départage par montant si fourni (un proposal peut contenir plusieurs paiements)
	if amount is not None:
		amt = round(float(amount), 2)
		exact = [p for p in pes if round((p.paid_amount or 0), 2) == amt]
		if len(exact) == 1:
			p = exact[0]
			return (p.party_type, p.party, p.name)

	if len(pes) == 1:
		p = pes[0]
		return (p.party_type, p.party, p.name)

	return (None, None, None)


def enrich_bank_transaction_values(values, txn):
	"""Complète le dict `values` d'une Bank Transaction avant insertion.

	- stocke le PmtInfId ;
	- pose party_type/party : PmtInfId (sortant) prioritaire, sinon IBAN/nom.
	N'écrase jamais un party déjà présent. Idempotent, silencieux si non résolu.
	"""
	pmtinfid = txn.get("pmtinfid")
	if pmtinfid:
		values["treasury_pmtinfid"] = pmtinfid

	if values.get("party"):
		return values

	party_type = party = None

	# 1) bouclage PmtInfId (paiement sortant émis via Payment Proposal)
	if pmtinfid and txn.get("credit_debit") == "DBIT":
		party_type, party, _pe = resolve_pmtinfid(
			pmtinfid, txn.get("booked_amount"), values.get("company")
		)

	# 2) sinon résolution IBAN/nom
	if not party:
		party_type, party = resolve_party(
			txn.get("party_iban"), txn.get("party_name"), txn.get("credit_debit")
		)

	if party_type and party:
		values["party_type"] = party_type
		values["party"] = party

	return values
