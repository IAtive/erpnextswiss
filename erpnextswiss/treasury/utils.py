# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Treasury: adaptations bancaires (import camt FX/ZIP, réconciliation multidevise)
# posées par-dessus l'app ALYF `banking` sans la modifier.

import frappe


def is_banking_installed():
	"""ERPNextSwiss doit rester fonctionnel SANS l'app ALYF `banking`.
	Toute logique qui touche `banking` est gardée par cet appel."""
	try:
		return "banking" in frappe.get_installed_apps()
	except Exception:
		return False
