# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Compatibilité eu_einvoice (ALYF) : réglages par défaut adaptés au contexte suisse.
#
# eu_einvoice fixe le profil par défaut à « EXTENDED » (sur-ensemble, rarement
# nécessaire) sur DEUX champs : Customer.einvoice_profile ET
# Sales Invoice.einvoice_profile. Comme la facture récupère le profil du client
# (fetch_from, prioritaire), il faut repositionner le défaut sur LES DEUX pour
# obtenir « EN 16931 » — le profil interopérable de référence pour le B2B UE.
# Via Property Setter (survit aux mises à jour d'eu_einvoice, contrairement à une
# édition du custom field). Un profil spécifique (XRECHNUNG…) reste réglable
# par client (Customer.einvoice_profile).
#
# Appelé depuis hooks.after_migrate, gardé « eu_einvoice installé », idempotent.

import frappe

DEFAULT_PROFILE = "EN 16931"

# (doctype, fieldname) portant le défaut « EXTENDED » à repositionner
_PROFILE_FIELDS = (("Customer", "einvoice_profile"), ("Sales Invoice", "einvoice_profile"))


def set_default_einvoice_profile():
	"""Property Setters : défaut du profil e-invoice = EN 16931 (au lieu d'EXTENDED),
	sur le Client (source via fetch_from) ET la facture de vente (repli)."""
	if "eu_einvoice" not in frappe.get_installed_apps():
		return
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for dt, fieldname in _PROFILE_FIELDS:
		# le custom field doit exister (eu_einvoice installé + migré)
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
			continue
		make_property_setter(
			dt, fieldname, "default", DEFAULT_PROFILE, "Data",
			validate_fields_for_doctype=False,
		)


def after_migrate():
	set_default_einvoice_profile()
	frappe.db.commit()
