# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Script Report « Contrôle de plausibilité TVA ».

Enveloppe UI de erpnextswiss.swiss_vat_config.plausibility.collect() : le comptable choisit
société + période et voit le tableau PASS/FAIL (réconciliation GL, lignes non classées, config).
"""
import frappe
from frappe import _
from erpnextswiss.swiss_vat_config.plausibility import collect


def execute(filters=None):
    filters = filters or {}
    columns = [
        {"label": _("Control"), "fieldname": "control", "fieldtype": "Data", "width": 170},
        {"label": _("Item"), "fieldname": "item", "fieldtype": "Data", "width": 260},
        {"label": _("Declaration"), "fieldname": "expected", "fieldtype": "Currency", "width": 120},
        {"label": _("GL / value"), "fieldname": "actual", "fieldtype": "Currency", "width": 120},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
        {"label": _("Detail"), "fieldname": "detail", "fieldtype": "Data", "width": 340},
    ]
    company = filters.get("company")
    start = filters.get("from_date")
    end = filters.get("to_date")
    if not (company and start and end):
        return columns, []
    return columns, collect(company, start, end)
