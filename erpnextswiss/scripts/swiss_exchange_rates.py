#
# swiss_exchange_rates.py
#
# Copyright (C) libracore, 2017-2025
# https://www.libracore.com or https://github.com/libracore
#
# Récupération des cours de change officiels de l'AFC/OFDF (BAZG) et écriture dans
# le doctype "Currency Exchange".
#
# Points d'entrée (compat rétro, exécutables via bench) :
#    $ bench execute erpnextswiss.scripts.swiss_exchange_rates.read_rates
#    $ bench execute erpnextswiss.scripts.swiss_exchange_rates.read_rates --kwargs "{'currencies': ['EUR', 'USD', 'GBP']}"
#    $ bench execute erpnextswiss.scripts.swiss_exchange_rates.read_daily_rates --kwargs "{'currencies': ['EUR', 'USD', 'GBP']}"
#
# La logique moderne (planification + suivi) passe par le doctype "Swiss Exchange Rate Settings",
# qui appelle fetch_and_store(). Voir aussi add_inverted_rates / add_cross_rates.
#
# Règles clés (conformité AFC) :
#   - Cours mensuel moyen : daté au 1er du mois lu dans <monat> (couvre tout le mois).
#   - On n'écrit QUE les valeurs absentes ; on n'écrase JAMAIS un enregistrement existant.
#
from bs4 import BeautifulSoup
import frappe
from frappe.utils import nowdate, now_datetime
import requests

# Endpoints officiels BAZG (Office fédéral de la douane et de la sécurité des frontières)
ENDPOINTS = {
    "Monthly Average": "https://www.backend-rates.bazg.admin.ch/api/xmlavgmonth",
    "Daily": "https://www.backend-rates.bazg.admin.ch/api/xmldaily",
}


def _parse_estv_xml(url, currencies):
    """Récupère et parse le flux XML AFC SANS rien écrire.

    Retourne (period, [(currency_code, rate_to_chf), ...]).
    - period : contenu de la balise <monat> (ex. '2026-07') si présente (flux mensuel), sinon None.
    - rate_to_chf : cours ramené à 1 unité (gère les libellés type '100 JPY').
    """
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    root = BeautifulSoup(r.text, "lxml")

    period = None
    monat = root.find("monat")
    if monat and monat.get_text(strip=True):
        period = monat.get_text(strip=True)

    wanted = {c.strip().upper() for c in currencies if c}
    out = []
    for devise in root.find_all("devise"):
        name = devise.waehrung.get_text().strip() if devise.waehrung else ""  # '1 EUR' / '100 JPY'
        code = (devise.get("code") or (name.split(" ")[-1] if name else "")).upper()
        if code not in wanted:
            continue
        # diviseur en cas de devises non unitaires (ex. 100 JPY = .. CHF)
        try:
            divisor = float(name.split(" ")[0])
        except (ValueError, IndexError):
            divisor = 1.0
        try:
            rate = float(devise.kurs.get_text()) / (divisor or 1.0)
        except (AttributeError, ValueError, ZeroDivisionError):
            continue
        out.append((code, rate))
    return period, out


def _insert_if_missing(from_currency, to_currency, rate, value_date, rows):
    """Insère un Currency Exchange UNIQUEMENT s'il n'existe pas déjà pour (from, to, date).
    Ne modifie jamais un enregistrement existant. Retourne 1 si inséré, 0 si ignoré."""
    exists = frappe.db.exists("Currency Exchange", {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "date": value_date,
    })
    if exists:
        rows.append({"from_currency": from_currency, "to_currency": to_currency,
                     "exchange_rate": rate, "value_date": value_date, "action": "Skipped"})
        return 0
    doc = frappe.get_doc({
        "doctype": "Currency Exchange",
        "date": value_date,
        "from_currency": from_currency,
        "to_currency": to_currency,
        "exchange_rate": rate,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    rows.append({"from_currency": from_currency, "to_currency": to_currency,
                 "exchange_rate": rate, "value_date": value_date, "action": "Inserted"})
    return 1


def fetch_and_store(rate_type="Monthly Average", currencies=None, create_inverted=True,
                    target_currency="CHF", trigger="Manual"):
    """Récupère les cours AFC et les écrit dans Currency Exchange (idempotent, sans écrasement).

    - rate_type      : 'Monthly Average' (xmlavgmonth) ou 'Daily' (xmldaily).
    - currencies     : liste de devises (ex. ['EUR','USD','GBP']).
    - create_inverted: crée aussi CHF -> devise.
    - trigger        : 'Manual' / 'Scheduled' (pour le log).

    Écrit un "Swiss Exchange Rate Import Log" et met à jour les champs last_* du Single.
    Retourne un dict de résumé.
    """
    target_currency = (target_currency or "CHF").upper()
    currencies = currencies or []
    inserted = skipped = 0
    rows = []
    period = None
    value_date = None
    status = "Success"
    message = ""

    try:
        url = ENDPOINTS.get(rate_type) or ENDPOINTS["Monthly Average"]
        period, pairs = _parse_estv_xml(url, currencies)

        # Date de valeur : cours mensuel -> 1er du mois lu dans <monat> ; sinon date du jour.
        if rate_type == "Monthly Average" and period:
            value_date = period + "-01"
        else:
            value_date = nowdate()
            period = period or value_date[:7]

        if not pairs:
            status = "Error"
            message = "Aucune devise trouvée dans le flux {0} (demandées : {1}).".format(
                rate_type, ", ".join(currencies) or "aucune")
        else:
            for code, rate in pairs:
                _insert_if_missing(code, target_currency, rate, value_date, rows)
                if create_inverted and rate:
                    _insert_if_missing(target_currency, code, 1.0 / rate, value_date, rows)
            inserted = sum(1 for x in rows if x["action"] == "Inserted")
            skipped = sum(1 for x in rows if x["action"] == "Skipped")
            found = {c for c, _ in pairs}
            missing = [c for c in (x.upper() for x in currencies) if c not in found]
            if missing:
                status = "Partial"
            message = "{0} inséré(s), {1} déjà présent(s) pour {2}.".format(inserted, skipped, period)
            if missing:
                message += " Devises introuvables dans le flux : {0}.".format(", ".join(missing))
    except Exception as err:
        status = "Error"
        message = "Échec de récupération : {0}".format(err)
        frappe.log_error(frappe.get_traceback(), "Swiss Exchange Rate import failed")

    _write_log_and_settings(trigger, status, rate_type, period, value_date,
                            inserted, skipped, message, rows)
    frappe.db.commit()
    return {"status": status, "period": period, "value_date": value_date,
            "inserted": inserted, "skipped": skipped, "message": message}


def _write_log_and_settings(trigger, status, rate_type, period, value_date,
                            inserted, skipped, message, rows):
    """Crée le log d'import et met à jour les champs last_* du Single."""
    try:
        log = frappe.get_doc({
            "doctype": "Swiss Exchange Rate Import Log",
            "run_datetime": now_datetime(),
            "trigger": trigger,
            "status": status,
            "rate_type": rate_type,
            "period": period,
            "value_date": value_date,
            "inserted_count": inserted,
            "skipped_count": skipped,
            "message": message,
            "rows": rows,
        })
        log.flags.ignore_permissions = True
        log.insert()
        if frappe.db.exists("DocType", "Swiss Exchange Rate Settings"):
            settings = frappe.get_single("Swiss Exchange Rate Settings")
            settings.db_set({
                "last_run": log.run_datetime,
                "last_status": status,
                "last_period": period,
                "last_inserted": inserted,
                "last_skipped": skipped,
                "last_message": message,
            }, update_modified=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Swiss Exchange Rate log write failed")


# ------------------------------------------------------------------ compat ----
def read_rates(currencies=["EUR"]):
    """Compat : import des cours mensuels moyens (délègue à fetch_and_store)."""
    return fetch_and_store(rate_type="Monthly Average", currencies=currencies, trigger="Manual")


def read_daily_rates(currencies=["EUR"]):
    """Compat : import des cours du jour (délègue à fetch_and_store)."""
    return fetch_and_store(rate_type="Daily", currencies=currencies, trigger="Manual")


"""
Import du taux inverse (CHF -> devise), basé sur le dernier cours devise -> CHF en base.
Conservé pour usage manuel ; fetch_and_store gère déjà l'inverse via create_inverted.
"""
def add_inverted_rates(currencies=["EUR"]):
    to_currency = "CHF"
    for currency in currencies:
        base_rates = frappe.get_all(
            "Currency Exchange",
            filters={"from_currency": currency, "to_currency": to_currency},
            fields=["exchange_rate", "date"],
            order_by="date desc",
            limit=1,
        )
        base_rate = base_rates[0]["exchange_rate"] if base_rates else 1
        value_date = base_rates[0]["date"] if base_rates else nowdate()
        _insert_if_missing(to_currency, currency, float(1 / base_rate), value_date, [])
    frappe.db.commit()


"""
Import du taux croisé (from -> to) via le pivot CHF.
"""
def add_cross_rates(from_currency="USD", to_currency="EUR"):
    def _last_to_chf(cur):
        r = frappe.get_all(
            "Currency Exchange",
            filters={"from_currency": cur, "to_currency": "CHF"},
            fields=["exchange_rate", "date"],
            order_by="date desc",
            limit=1,
        )
        return (r[0]["exchange_rate"], r[0]["date"]) if r else (1, nowdate())

    from_rate, value_date = _last_to_chf(from_currency)
    to_rate, _ = _last_to_chf(to_currency)
    _insert_if_missing(from_currency, to_currency, float(from_rate / to_rate), value_date, [])
    frappe.db.commit()
