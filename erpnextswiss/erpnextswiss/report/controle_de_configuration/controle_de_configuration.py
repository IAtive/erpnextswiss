# -*- coding: utf-8 -*-
# Copyright (c) 2026, Kramdi and contributors
"""Script Report « Contrôle de configuration ».

Enveloppe UI de erpnextswiss.erpnextswiss.config_readiness.collect(). Rendu en ARBRE
repliable par catégorie (Société / Comptes bancaires / Clients / Fournisseurs /
Paramètres) : chaque catégorie est une ligne-groupe repliée (avec un résumé du
statut) qu'on déplie pour voir ses contrôles — indispensable quand il y a des
milliers de clients/fournisseurs.
"""
import frappe
from frappe import _
from erpnextswiss.erpnextswiss.config_readiness import (
    collect, OK, KO, WARN, G_COMPANY, G_BANK, G_PARTY_ACC, G_CUSTOMER, G_SUPPLIER, G_SETTINGS, G_FX,
)

_GROUP_ORDER = [G_COMPANY, G_BANK, G_PARTY_ACC, G_CUSTOMER, G_SUPPLIER, G_FX, G_SETTINGS]


def _build_tree(rows):
    """Transforme la liste plate en arbre : une ligne-groupe par catégorie (indent 0,
    avec résumé de statut) + une ligne par contrôle (indent 1)."""
    by_group = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)

    tree, seen = [], set()
    for g in _GROUP_ORDER:
        grp = by_group.get(g)
        if not grp:
            continue
        n_ko = sum(1 for r in grp if r["status"].startswith("❌"))
        n_warn = sum(1 for r in grp if r["status"].startswith("⚠"))
        if n_ko:
            summary = "❌ %d Anomalie(s)" % n_ko
        elif n_warn:
            summary = "⚠️ %d à vérifier" % n_warn
        else:
            summary = OK
        # ligne-groupe (repliable)
        tree.append({"label": g, "status": summary, "impact": "", "link_url": "",
                     "indent": 0, "parent_id": ""})
        # lignes de détail
        for r in grp:
            lbl = r["check"]
            if r["entity"] and r["entity"] != "—":
                lbl = "%s · %s" % (r["check"], r["entity"])
            base, k = lbl, 2
            while lbl in seen:                     # garantit l'unicité (name_field)
                lbl = "%s (%d)" % (base, k)
                k += 1
            seen.add(lbl)
            tree.append({"label": lbl, "status": r["status"], "impact": r["impact"],
                         "link_url": r.get("link_url", ""), "indent": 1, "parent_id": g})
    return tree


def execute(filters=None):
    filters = filters or {}
    columns = [
        {"label": _("Domain / Check"), "fieldname": "label", "fieldtype": "Data", "width": 420},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
        {"label": _("Open"), "fieldname": "link_url", "fieldtype": "Data", "width": 90},
        {"label": _("Impact if misconfigured"), "fieldname": "impact", "fieldtype": "Data", "width": 540},
    ]
    company = filters.get("company")
    if not company:
        return columns, []
    return columns, _build_tree(collect(company))
