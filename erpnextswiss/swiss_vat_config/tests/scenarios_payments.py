# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Scénarios de test — PAIEMENTS & RAPPROCHEMENT.

Couvre : génération des références QR (Swiss QR), garde-fous de configuration,
import camt (normalisation, FX), enrichissement des Bank Transactions (tiers,
PmtInfId), matching de référence bout-en-bout (vente & achat), IBAN de la
e-facture ZUGFeRD, et configuration du rapprochement ALYF.

Même moteur/reset que scenarios.py (importés via `from ... import *`).
Lancement : bench execute erpnextswiss.swiss_vat_config.tests.runner.run_one
            --kwargs "{'company':'HJD','nom':'qr_vente_scor'}"
"""
import frappe
from erpnextswiss.swiss_vat_config.tests.helpers import (
    ensure_payment_masters, build_camt053, build_camt054_batch, TEST_IBAN_NORMAL, TEST_QR_IBAN,
)


# =========================================================================
# A. Génération des références QR (doc_event Sales Invoice.validate)
# =========================================================================
def scenario_qr_vente_scor(ctx):
    """SCÉNARIO : facture de vente, compte de réception en méthode SCOR.
    ATTENDU : qr_reference = référence RF (ISO 11649, sans espaces), type = SCOR."""
    ctx.set_qr_config("1020", "SCOR", iban=TEST_IBAN_NORMAL, qr_iban=None)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    ref = frappe.db.get_value("Sales Invoice", si.name, "qr_reference")
    ctx.assert_field(si, "qr_reference_type", "SCOR")
    ctx._rec("QR-ref", "format RF", "RF…", ref, bool(ref) and ref.startswith("RF") and " " not in ref)


def scenario_qr_vente_qrr(ctx):
    """SCÉNARIO : facture de vente, compte en méthode QRR (QR-IBAN configurée).
    ATTENDU : qr_reference = 27 chiffres (sans espaces), type = QRR."""
    ctx.set_qr_config("1020", "QRR", iban=TEST_IBAN_NORMAL, qr_iban=TEST_QR_IBAN)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    ref = frappe.db.get_value("Sales Invoice", si.name, "qr_reference")
    ctx.assert_field(si, "qr_reference_type", "QRR")
    ctx._rec("QR-ref", "27 chiffres", "27 digits", ref, bool(ref) and ref.isdigit() and len(ref) == 27)


def scenario_qr_vente_non(ctx):
    """SCÉNARIO : facture de vente, compte en méthode NON (sans référence).
    ATTENDU : qr_reference vide, type = NON."""
    ctx.set_qr_config("1020", "NON", iban=TEST_IBAN_NORMAL, qr_iban=None)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    ctx.assert_field(si, "qr_reference_type", "NON")
    ctx.assert_field(si, "qr_reference", None)


def scenario_qr_immutabilite(ctx):
    """SCÉNARIO : une facture émise en SCOR ne change pas si le compte passe en QRR.
    POURQUOI : une facture envoyée au client doit se réimprimer à l'identique.
    ATTENDU : après bascule du compte en QRR, la facture garde type=SCOR + sa réf RF."""
    ctx.set_qr_config("1020", "SCOR", iban=TEST_IBAN_NORMAL, qr_iban=None)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    ref0 = frappe.db.get_value("Sales Invoice", si.name, "qr_reference")
    # bascule le compte en QRR APRÈS émission
    ctx.set_qr_config("1020", "QRR", iban=TEST_IBAN_NORMAL, qr_iban=TEST_QR_IBAN)
    ctx.assert_field(si, "qr_reference_type", "SCOR")     # inchangé
    ctx.assert_field(si, "qr_reference", ref0)            # référence inchangée


# =========================================================================
# B. Garde-fous de configuration du compte (validate_account_qr)
# =========================================================================
def scenario_qr_validation_compte(ctx):
    """SCÉNARIO : garde-fous de cohérence QR-IBAN / IBAN classique / méthode.
    ATTENDU : rejets sur QR-IBAN dans le champ IBAN, qr_iban invalide, QRR sans qr_iban ;
              acceptation des configurations cohérentes."""
    from erpnextswiss.swiss_qr.validation import validate_account_qr

    def d(**kw):
        return frappe._dict(kw)

    ctx.assert_reject("QR-IBAN dans IBAN classique",
                      lambda: validate_account_qr(d(iban=TEST_QR_IBAN, qr_iban=None, qr_method="SCOR")))
    ctx.assert_reject("qr_iban = IBAN normal",
                      lambda: validate_account_qr(d(iban=TEST_IBAN_NORMAL, qr_iban=TEST_IBAN_NORMAL, qr_method="QRR")))
    ctx.assert_reject("QRR sans qr_iban",
                      lambda: validate_account_qr(d(iban=TEST_IBAN_NORMAL, qr_iban=None, qr_method="QRR")))
    # configurations valides -> ne doivent PAS lever
    ok_qrr = True
    try:
        validate_account_qr(d(iban=TEST_IBAN_NORMAL, qr_iban=TEST_QR_IBAN, qr_method="QRR"))
        validate_account_qr(d(iban=TEST_IBAN_NORMAL, qr_iban=None, qr_method="SCOR"))
    except Exception:
        ok_qrr = False
    ctx._rec("Accept", "config cohérente", "accepté", "accepté" if ok_qrr else "rejeté", ok_qrr)


# =========================================================================
# C. Import camt : normalisation de la référence & FX
# =========================================================================
def scenario_camt_reference_normalisee(ctx):
    """SCÉNARIO : une référence QRR espacée dans le camt est stockée SANS espaces.
    POURQUOI : le matching ALYF compare par égalité EXACTE avec qr_reference (sans espaces).
    ATTENDU : BT.reference_number = 27 chiffres compacts."""
    ensure_payment_masters(ctx.company)
    spaced = "00 00000 00000 00000 20260 00911"
    compact = spaced.replace(" ", "")
    xml = build_camt053([{"amount": 500, "cd": "CRDT", "ref": spaced, "party": "SCEN Client CH"}])
    bts = ctx.import_camt(xml)
    bt = ctx.bt_by_reference(bts, compact)
    ctx._rec("Norm", "réf compacte", compact, bt.reference_number if bt else None, bt is not None)


def scenario_camt054_batch(ctx):
    """SCÉNARIO : avis groupé camt.054 (1 écriture, 3 paiements) -> 3 Bank Transactions.
    POURQUOI : les banques regroupent les encaissements QR-bill en une écriture ; le
    détail par référence est dans le camt.054 (conteneur Ntfctn, plusieurs TxDtls).
    Chaque paiement doit devenir une transaction DISTINCTE, rapprochable par sa réf.
    ATTENDU : 3 BT créées, montants 100/300/500, 3 références préservées."""
    ensure_payment_masters(ctx.company)
    xml = build_camt054_batch([
        {"amount": 100, "ref": "000000000000000000000000117", "party": "SCEN Client CH"},
        {"amount": 300, "ref": "RF84202600035", "party": "SCEN Client CH"},
        {"amount": 500, "ref": "000000000000000000000000349", "party": "SCEN Client CH"},
    ])
    bts = ctx.import_camt(xml)
    ctx._rec("camt.054", "nb transactions", 3, len(bts), len(bts) == 3)
    ctx._rec("camt.054", "réfs distinctes", 3, len(set(b.reference_number for b in bts)),
             len(set(b.reference_number for b in bts)) == 3)
    amounts = sorted(b.deposit for b in bts)
    ctx._rec("camt.054", "montants", "[100.0, 300.0, 500.0]", amounts, amounts == [100.0, 300.0, 500.0])


def scenario_camt_import_fx(ctx):
    """SCÉNARIO : encaissement en EUR sur compte CHF (booked CHF + montant EUR + taux).
    ATTENDU : BT enrichie des champs FX (devise/montant d'origine + taux banque)."""
    ensure_payment_masters(ctx.company)
    xml = build_camt053([{
        "amount": 930.00, "cd": "CRDT", "party": "SCEN Client EUR",
        "orig_ccy": "EUR", "orig_amount": 1000.00, "xchg_rate": 0.93,
        "ref": "RF85202600017",
    }])
    bts = ctx.import_camt(xml)
    bt = bts[0] if bts else None
    ctx._rec("FX", "original_currency", "EUR", bt.original_currency if bt else None,
             bool(bt) and bt.original_currency == "EUR")
    ctx._rec("FX", "original_amount", 1000.0, bt.original_amount if bt else None,
             bool(bt) and abs((bt.original_amount or 0) - 1000.0) < 0.01)
    ctx._rec("FX", "bank_exchange_rate", 0.93, bt.bank_exchange_rate if bt else None,
             bool(bt) and abs((bt.bank_exchange_rate or 0) - 0.93) < 0.0001)


# =========================================================================
# D. Enrichissement : résolution du tiers & PmtInfId
# =========================================================================
def scenario_enrich_party_nom(ctx):
    """SCÉNARIO : encaissement client sans IBAN dans le camt, mais nom exact connu.
    POURQUOI : les banques omettent souvent l'IBAN du débiteur → fallback par nom.
    ATTENDU : BT.party_type=Customer, party='SCEN Client CH'."""
    ensure_payment_masters(ctx.company)
    xml = build_camt053([{"amount": 250, "cd": "CRDT", "party": "SCEN Client CH", "ref": "RF11202600011"}])
    bts = ctx.import_camt(xml)
    bt = bts[0] if bts else None
    ctx._rec("Party", "type", "Customer", bt.party_type if bt else None, bool(bt) and bt.party_type == "Customer")
    ctx._rec("Party", "party", "SCEN Client CH", bt.party if bt else None,
             bool(bt) and bt.party == "SCEN Client CH")


def scenario_enrich_pmtinfid(ctx):
    """SCÉNARIO : paiement sortant dont le camt porte un PmtInfId.
    ATTENDU : BT.treasury_pmtinfid renseigné (traçabilité du bouclage sortant)."""
    ensure_payment_masters(ctx.company)
    xml = build_camt053([{
        "amount": 800, "cd": "DBIT", "party": "SCEN Fournisseur CH",
        "pmtinfid": "PMTINF-SCEN-PP-0001-1",
    }])
    bts = ctx.import_camt(xml)
    bt = bts[0] if bts else None
    ctx.assert_field(bt, "treasury_pmtinfid", "PMTINF-SCEN-PP-0001-1")
    ctx._rec("Party", "fournisseur", "SCEN Fournisseur CH", bt.party if bt else None,
             bool(bt) and bt.party == "SCEN Fournisseur CH")


# =========================================================================
# E. Matching bout-en-bout (vente & achat)
# =========================================================================
def scenario_match_vente_qrr(ctx):
    """SCÉNARIO E2E : facture de vente QRR → encaissement camt portant la même référence.
    ATTENDU : BT.reference_number == Sales Invoice.qr_reference (égalité exacte -> match ALYF)."""
    ensure_payment_masters(ctx.company)
    ctx.set_qr_config("1020", "QRR", iban=TEST_IBAN_NORMAL, qr_iban=TEST_QR_IBAN)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    qrr = frappe.db.get_value("Sales Invoice", si.name, "qr_reference")
    xml = build_camt053([{"amount": si.grand_total, "cd": "CRDT", "ref": qrr, "party": "SCEN Client CH"}])
    bts = ctx.import_camt(xml)
    bt = ctx.bt_by_reference(bts, qrr)
    ctx.assert_ref_match(bt, si, "qr_reference")


def scenario_match_achat_qrr(ctx):
    """SCÉNARIO E2E : facture d'achat scannée (esr_reference_number) → paiement camt (débit).
    ATTENDU : BT.reference_number == Purchase Invoice.esr_reference_number (match ALYF achat)."""
    ensure_payment_masters(ctx.company)
    qrr = "000000000000000000000010445"
    pi = ctx.make_purchase_invoice_qr("SCEN Fournisseur CH", net=200, esr_reference=qrr)
    xml = build_camt053([{"amount": pi.grand_total, "cd": "DBIT", "ref": qrr, "party": "SCEN Fournisseur CH"}])
    bts = ctx.import_camt(xml)
    bt = ctx.bt_by_reference(bts, qrr)
    ctx.assert_ref_match(bt, pi, "esr_reference_number")


# =========================================================================
# F. ZUGFeRD & configuration ALYF
# =========================================================================
def scenario_zugferd_iban_reception(ctx):
    """SCÉNARIO : la e-facture ZUGFeRD porte l'IBAN du compte de RÉCEPTION (pas debit_to).
    ATTENDU : data['iban'] == IBAN classique du compte de réception."""
    from erpnextswiss.erpnextswiss.zugferd.zugferd_xml import prepare_data
    ctx.set_qr_config("1020", "SCOR", iban=TEST_IBAN_NORMAL, qr_iban=None)
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000)
    data = prepare_data(si.name)
    ctx._rec("ZUGFeRD", "iban réception", TEST_IBAN_NORMAL, data.get("iban"),
             data.get("iban") == TEST_IBAN_NORMAL)


def scenario_alyf_config(ctx):
    """SCÉNARIO : la configuration ALYF de rapprochement est bien posée (idempotente).
    ATTENDU : reference_fields SI->qr_reference, PI->esr_reference_number ;
              voucher_matching_defaults contient Sales + Purchase Invoice."""
    from erpnextswiss.treasury.utils import is_banking_installed
    if not is_banking_installed():
        ctx._rec("ALYF", "banking", "installé", "absent", True, detail="ALYF non installé — test ignoré")
        return
    from erpnextswiss.treasury import setup as tsetup
    tsetup.configure_alyf_reference_fields()
    tsetup.configure_alyf_voucher_defaults()
    tsetup.configure_alyf_reference_fields()  # 2e passage : idempotence
    s = frappe.get_single("Banking Settings")
    refs = {r.document_type: r.field_name for r in s.get("reference_fields", [])}
    vdef = {r.document_type for r in s.get("voucher_matching_defaults", [])}
    ctx._rec("ALYF", "SI->qr_reference", "qr_reference", refs.get("Sales Invoice"),
             refs.get("Sales Invoice") == "qr_reference")
    ctx._rec("ALYF", "PI->esr_ref", "esr_reference_number", refs.get("Purchase Invoice"),
             refs.get("Purchase Invoice") == "esr_reference_number")
    ctx._rec("ALYF", "defaults", "SI+PI", ",".join(sorted(vdef)),
             "Sales Invoice" in vdef and "Purchase Invoice" in vdef)
