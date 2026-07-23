# Copyright (c) 2026, Kramdi and contributors
# For license information, please see license.txt
#
# Garde-fous de cohérence QR sur le compte (plan comptable) :
#   - l'IBAN classique NE DOIT PAS être une QR-IBAN (il alimente le débiteur du
#     pain.001, le créancier du prélèvement et la e-facture) ;
#   - le champ QR-IBAN doit contenir une vraie QR-IBAN ;
#   - la méthode QRR exige une QR-IBAN.
#
# Doc_event : Account.validate.

import re
import frappe
from frappe import _


def is_qr_iban(iban):
	"""True si l'IBAN est une QR-IBAN suisse/liechtensteinoise.

	Une QR-IBAN a une identification d'institution (IID, positions 5-9) dans la
	plage 30000-31999 (donc 5e chiffre = 3).
	"""
	s = re.sub(r"\s", "", (iban or "")).upper()
	if len(s) < 9 or s[:2] not in ("CH", "LI"):
		return False
	iid = s[4:9]
	return iid.isdigit() and 30000 <= int(iid) <= 31999


def validate_account_qr(doc, method=None):
	"""Doc_event Account.validate : cohérence QR-IBAN / IBAN classique / méthode."""
	# l'IBAN classique ne doit jamais être une QR-IBAN
	if doc.get("iban") and is_qr_iban(doc.iban):
		frappe.throw(_(
			"Le champ IBAN contient une QR-IBAN. Placez la QR-IBAN dans le champ "
			"« QR-IBAN » (méthode QRR) et renseignez ici l'IBAN classique, utilisé "
			"pour les paiements (pain.001)."
		))

	# le champ QR-IBAN doit contenir une vraie QR-IBAN
	if doc.get("qr_iban") and not is_qr_iban(doc.qr_iban):
		frappe.throw(_(
			"Le champ QR-IBAN doit contenir une vraie QR-IBAN "
			"(institution 30000–31999, 5e chiffre = 3)."
		))

	# méthode QRR -> QR-IBAN obligatoire
	if doc.get("qr_method") == "QRR" and not doc.get("qr_iban"):
		frappe.throw(_(
			"Méthode QRR : renseignez une QR-IBAN dans le champ « QR-IBAN »."
		))
