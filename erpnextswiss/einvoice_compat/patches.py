# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Compatibilité eu_einvoice (ALYF) pour les VENDEURS suisses.
#
# Problème : dans eu_einvoice, la construction de l'identifiant TVA du VENDEUR
# (`_set_seller_tax_id`) ne connaît que le format UE (`validate_vat_id`) et
# rebascule un UID suisse (« CHE-…MWST ») en schéma FC → BT-32 (registration
# fiscale) au lieu de VA → BT-31 (identifiant TVA). La règle EN 16931 BR-CO-26
# n'accepte que BT-29/30/31 → une facture émise par une société suisse échoue.
# Le chemin ACHETEUR gère pourtant déjà le suisse (normalize_swiss_vat_id) —
# l'asymétrie est un angle mort germano-centré (cf. PR upstream).
#
# Fix transitoire : on wrappe `validate_vat_id` pour qu'elle reconnaisse aussi un
# UID suisse valide et renvoie sa forme normalisée → le chemin vendeur passe alors
# dans sa branche « VA » (BT-31). Le chemin acheteur teste le suisse AVANT
# d'appeler validate_vat_id → aucun double effet. À retirer une fois le PR mergé.
#
# Porté par ERPNextSwiss (boot_session), gardé « eu_einvoice installé »,
# idempotent, et silencieux si la structure d'eu_einvoice change.

import frappe


def apply_einvoice_patches(bootinfo=None):
	"""boot_session hook : rend le chemin vendeur d'eu_einvoice compatible UID suisse."""
	if "eu_einvoice" not in frappe.get_installed_apps():
		return
	try:
		import eu_einvoice.european_e_invoice.custom.sales_invoice as si_mod
		from eu_einvoice.switzerland import is_valid_swiss_vat_id, normalize_swiss_vat_id
	except Exception:
		return

	# déjà patché (le worker a déjà booté une session) -> ne rien refaire
	if getattr(si_mod.validate_vat_id, "_erpnextswiss_swiss_seller_patch", False):
		return

	_original_validate_vat_id = si_mod.validate_vat_id

	def validate_vat_id_swiss_aware(vat_id):
		# UID suisse valide (clé de contrôle BFS) -> forme normalisée, comme le
		# chemin acheteur. Sinon comportement d'origine (format UE).
		if is_valid_swiss_vat_id(vat_id):
			return normalize_swiss_vat_id(vat_id)
		return _original_validate_vat_id(vat_id)

	validate_vat_id_swiss_aware._erpnextswiss_swiss_seller_patch = True
	si_mod.validate_vat_id = validate_vat_id_swiss_aware
