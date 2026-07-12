# Copyright (c) 2026, IAtive and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from erpnextswiss.scripts.swiss_exchange_rates import fetch_and_store

# Jours de semaine dans l'ordre de datetime.weekday() (0 = lundi … 6 = dimanche).
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SwissExchangeRateSettings(Document):
	@frappe.whitelist()
	def run_now(self):
		"""Bouton « Lancer maintenant » : récupère les cours immédiatement (trigger manuel)."""
		return fetch_and_store(
			rate_type=self.rate_type,
			currencies=[r.currency for r in self.currencies],
			create_inverted=self.create_inverted,
			target_currency=self.target_currency or "CHF",
			trigger="Manual",
		)


DEFAULT_CURRENCIES = ("EUR", "USD", "GBP")


def ensure_defaults():
	"""after_migrate : garantit une config par défaut (idempotent).
	Pré-remplit les devises EUR/USD/GBP si aucune n'est configurée, et fixe CHF en cible.
	Note : si les devises ont été vidées volontairement, un migrate les re-sème."""
	if not frappe.db.exists("DocType", "Swiss Exchange Rate Settings"):
		return
	settings = frappe.get_single("Swiss Exchange Rate Settings")
	changed = False
	if not settings.currencies:
		for cur in DEFAULT_CURRENCIES:
			if frappe.db.exists("Currency", cur):
				settings.append("currencies", {"currency": cur})
				changed = True
	if not settings.target_currency:
		settings.target_currency = "CHF"
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()


def scheduled_fetch():
	"""Point d'entrée du scheduler (déclaré dans hooks.scheduler_events['daily']).

	Tourne chaque jour mais applique une PORTE selon la config :
	  - enabled faux            -> ne fait rien ;
	  - Daily                   -> exécute ;
	  - Weekly + weekday        -> exécute seulement le bon jour de semaine ;
	  - Monthly + day_of_month  -> exécute seulement le bon jour du mois.
	Idempotent : fetch_and_store n'écrit que les cours absents (pas d'écrasement)."""
	settings = frappe.get_single("Swiss Exchange Rate Settings")
	if not settings.enabled:
		return

	freq = settings.frequency or "Daily"
	if freq != "Daily":
		today = getdate()
		if freq == "Weekly":
			target = settings.weekday or "Monday"
			if today.weekday() != _WEEKDAYS.index(target):
				return
		elif freq == "Monthly":
			dom = min(max(int(settings.day_of_month or 1), 1), 28)
			if today.day != dom:
				return

	fetch_and_store(
		rate_type=settings.rate_type,
		currencies=[r.currency for r in settings.currencies],
		create_inverted=settings.create_inverted,
		target_currency=settings.target_currency or "CHF",
		trigger="Scheduled",
	)
