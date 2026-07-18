# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Logique d'escompte (Skonto) — accroché à Payment Entry sans modifier ERPNext.

ERPNext ventile nativement l'escompte de paiement rapide (flag `book_tax_discount_loss`) :
part NETTE → `default_discount_account`, part TVA → compte de taxe de la facture. Mais il n'a
QU'UN compte d'escompte (chez nous 3800, « escomptes accordés », classe 3). Sur un paiement
d'ACHAT, la part nette est un escompte OBTENU → elle doit réduire les CHARGES (4900, classe 4),
pas les produits. Ce hook route donc 3800 → 4900 côté achat. Voir doc §11/§15 #3.

Impact : présentation P&L uniquement (résultat net et TVA inchangés). Réversible.
"""
import frappe


def route_purchase_discount_to_4900(doc, method=None):
    """Sur un paiement d'ACHAT (Pay), bascule la part nette de l'escompte du compte d'escompte par
    défaut (3800) vers 4900 (escomptes obtenus). Sans effet si : pas un achat, 4900 absent, ou pas
    de déduction d'escompte. La reprise TVA (sur le compte d'impôt préalable) n'est pas touchée."""
    if getattr(doc, "payment_type", None) != "Pay":
        return
    default_disc = frappe.get_cached_value("Company", doc.company, "default_discount_account")
    if not default_disc:
        return
    acc4900 = frappe.db.get_value("Account", {"account_number": "4900", "company": doc.company})
    if not acc4900:
        return
    for d in doc.get("deductions", []):
        # part nette de l'escompte (sur le compte d'escompte par défaut, hors ligne de change)
        if d.account == default_disc and not d.get("is_exchange_gain_loss"):
            d.account = acc4900
