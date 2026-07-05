# Copyright (c) 2016-2024, libracore and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _

def execute(filters=None):
    columns, data = [], []
    
    if not filters.from_date:
        filters.from_date = "2000-01-01"
    if not filters.end_date:
        filters.end_date = "2999-12-31"
    if not filters.code:
        filters.code = "200"

    # define columns (journal TVA facon bexio : reference, compte, description, code, net, TVA, total)
    columns = [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 90},
        {"label": _("Reference"), "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 150},
        {"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 150},
        {"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 220},
        {"label": _("Tax code"), "fieldname": "tax_code", "fieldtype": "Data", "width": 200},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 70},
        {"label": _("Net amount"), "fieldname": "base_grand_total", "fieldtype": "Currency", "options": "currency", "width": 120},
        {"label": _("VAT"), "fieldname": "tax_amount", "fieldtype": "Currency", "options": "currency", "width": 110},
        {"label": _("Total"), "fieldname": "total_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
    ]

    data = get_data(filters.from_date, filters.end_date, filters.code, filters.company)
    # Le total est fourni par Frappe (add_total_row = 1 dans le report) -> pas de ligne manuelle.
    return columns, data

def get_data(from_date, end_date, code, company="%"):
    # try to fetch data from VAT query
    if frappe.db.exists("VAT query", "viewVAT_{code}".format(code=code)):
        sql_query = ("""SELECT * 
                FROM ({query}) AS `s` 
                WHERE `s`.`posting_date` >= '{start_date}' 
                AND `s`.`posting_date` <= '{end_date}'""".format(
                query=frappe.get_value("VAT query", "viewVAT_{code}".format(code=code), "query"),
                start_date=from_date, end_date=end_date).replace("{company}", company))      
    else:
        # fallback database view
        sql_query = """SELECT
                    *
                FROM `viewVAT_{code}`
                WHERE
                    `posting_date` >= \"{start_date}\"
                    AND `posting_date` <= \"{end_date}\"
                ORDER BY
                    `posting_date`;""".format(
                    start_date=from_date, end_date=end_date, code=code)     
    try:
        data = frappe.db.sql(sql_query, as_dict = True)
    except:
        return []
    return data

# v15 wrapper for jinja/get_data (incompatible function name rewrite)
def get_tax_details(from_date, end_date, code, company="%"):
    return get_data(from_date, end_date, code, company)

# this is an endpoint for the jinja environment
def get_vat_control_details(from_date, end_date, code, company="%"):
    return get_data(from_date, end_date, code, company)

