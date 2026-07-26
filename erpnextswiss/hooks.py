# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "erpnextswiss"
app_title = "ERPNextSwiss"
app_publisher = "libracore (https://www.libracore.com)"
app_description = "ERPNext application for Switzerland-specific use cases"
app_icon = "fa fa-diamond"
app_color = "#92d050"
app_email = "info@libracore.com"
app_license = "AGPL"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erpnextswiss/css/erpnextswiss.css"
app_include_js = [
    "/assets/erpnextswiss/js/swiss_common.js",
    "/assets/erpnextswiss/js/iban.js",
    "/assets/erpnextswiss/js/email.js",
    # NB: "erpnextswiss_templates.min.js" retiré — bundle legacy non genere par Frappe v16 (404).
    # Rien ne l'utilise cote client (aucun frappe.templates[...]) ; la table est rendue server-side.
]

# include js, css files in header of web template
# web_include_css = "/assets/erpnextswiss/css/erpnextswiss.css"
# web_include_js = "/assets/erpnextswiss/js/erpnextswiss.js"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
    "Item" :                "public/js/item.js",
    "Quotation" :           "public/js/quotation.js",
    "Sales Order" :         "public/js/sales_order.js",
    "Sales Invoice" :       "public/js/sales_invoice.js",
    "Purchase Invoice" :    "public/js/purchase_invoice.js",
    "Fiscal Year":          "public/js/fiscal_year.js",
    "Supplier":             "public/js/supplier.js",
    "Customer":             "public/js/customer.js",
    "Address":              "public/js/address.js",
    "Holiday List":         "public/js/holiday_list.js",
    "Shipment":             "public/js/shipment.js",
    "Exchange Rate Revaluation": "public/js/exchange_rate_revaluation.js",
    "Bank Transaction":     "public/js/bank_transaction.js",
    "Bank Reconciliation Tool Beta": "public/js/bank_reconciliation_tool_beta.js"
}

# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {
    "Purchase Invoice" : "public/js/purchase_invoice_list.js",
    "Bank Transaction" : "public/js/bank_transaction_list.js"
}

# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# adding Jinja environments
jinja = {
    "methods": [

        "erpnextswiss.erpnextswiss.report.kontrolle_mwst.kontrolle_mwst.get_tax_details",
        "erpnextswiss.erpnextswiss.finance.get_account_sheets",
        "erpnextswiss.erpnextswiss.finance.get_customer_ledger",
        "erpnextswiss.erpnextswiss.jinja.get_week_from_date",
        "erpnextswiss.erpnextswiss.jinja.strip_html",
        "erpnextswiss.erpnextswiss.jinja.get_accounts_receivable",
        "erpnextswiss.scripts.crm_tools.get_primary_company_address",
        "erpnextswiss.scripts.crm_tools.get_primary_customer_address",
        "erpnextswiss.scripts.crm_tools.get_primary_supplier_address",
        "erpnextswiss.erpnextswiss.report.kontrolle_mwst.kontrolle_mwst.get_vat_control_details",
        "erpnextswiss.erpnextswiss.planzer.get_planzer_barcode",
        "erpnextswiss.erpnextswiss.planzer.get_planzer_qr_code",
        # Swiss QR : rendu LOCAL du bulletin QR (récépissé + section paiement) via qrbill
        "erpnextswiss.swiss_qr.render.get_qr_bill_svg"
    ]
}

# allow to link incoing mails to EDI File
email_append_to = ["EDI File"]

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#    "Role": "home_page"
# }

# Website user home page (by function)
# get_website_user_home_page = "erpnextswiss.utils.get_home_page"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "erpnextswiss.install.before_install"
after_install = [
    "erpnextswiss.setup.install.after_install",
    "erpnextswiss.swiss_vat_config.vat_setup.after_install",
]

after_migrate = [
    "erpnextswiss.erpnextswiss.doctype.swiss_exchange_rate_settings.swiss_exchange_rate_settings.ensure_defaults",
    "erpnextswiss.swiss_vat_config.vat_setup.after_migrate",
    "erpnextswiss.treasury.setup.after_migrate",
    "erpnextswiss.swiss_qr.setup.after_migrate",
    "erpnextswiss.einvoice_compat.setup.after_migrate",
]

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erpnextswiss.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#     "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#     "Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#     "*": {
#         "on_update": "method",
#         "on_cancel": "method",
#         "on_trash": "method"
#    }
# }
doc_events = {
    "Contact": {
        "on_update": "erpnextswiss.erpnextswiss.nextcloud.contacts.send_contact_to_nextcloud",
        "on_trash": "erpnextswiss.erpnextswiss.nextcloud.contacts.delete_contact_from_nextcloud"
    },
    # Swiss VAT Config : garde-fou de plausibilité du décompte TVA + routage des escomptes achat.
    "VAT Declaration": {
        "validate": "erpnextswiss.swiss_vat_config.plausibility.vat_declaration_warn",
        "before_submit": "erpnextswiss.swiss_vat_config.plausibility.vat_declaration_block",
    },
    "Payment Entry": {
        "validate": [
            "erpnextswiss.swiss_vat_config.escompte.route_purchase_discount_to_4900",
            # Treasury : montant tiers réel + taux banque sur un paiement on-account
            # créé depuis une transaction FX enrichie (sur-ensemble strict, gardé).
            "erpnextswiss.treasury.overrides.payment_entry_apply_bank_fx",
        ],
    },
    # Swiss QR : génère la référence du bulletin QR (QRR/SCOR/NON) selon la méthode
    # du compte de réception. Remplace l'ancienne génération cliente onload.
    "Sales Invoice": {
        "validate": "erpnextswiss.swiss_qr.references.set_qr_reference",
    },
    # Swiss QR : cohérence QR-IBAN / IBAN classique / méthode sur le compte.
    "Account": {
        "validate": "erpnextswiss.swiss_qr.validation.validate_account_qr",
    },
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
#     "all": [
#         "erpnextswiss.tasks.all"
#     ],
#     "daily": [
#         "erpnextswiss.tasks.daily"
#     ],
#     "hourly": [
#         "erpnextswiss.tasks.hourly"
#     ],
#     "weekly": [
#         "erpnextswiss.tasks.weekly"
#     ]
#     "monthly": [
#         "erpnextswiss.tasks.monthly"
#     ]
# }
scheduler_events = {
    "daily": [
        "erpnextswiss.erpnextswiss.doctype.inspection_equipment.inspection_equipment.check_calibration_status",
        "erpnextswiss.erpnextswiss.ebics.background_sync",
        "erpnextswiss.erpnextswiss.doctype.swiss_exchange_rate_settings.swiss_exchange_rate_settings.scheduled_fetch"
    ],
    "hourly": [
        "erpnextswiss.erpnextswiss.edi.process_incoming"
    ]
}

# Testing
# -------

# before_tests = "erpnextswiss.install.before_tests"

# Overriding Whitelisted Methods
# ------------------------------
#
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "erpnextswiss.event.get_events"
# }

# Treasury : pré-remplit le prompt de réconciliation ALYF avec le taux banque.
# (L'upload camt, lui, court-circuite les overrides -> traité par monkeypatch, cf. boot_session.)
override_whitelisted_methods = {
    "banking.klarna_kosma_integration.doctype.bank_reconciliation_tool_beta.bank_reconciliation_tool_beta.get_reconcile_amount_context": "erpnextswiss.treasury.overrides.get_reconcile_amount_context",
}

# Monkeypatches appliqués au boot (gardés « app installée », idempotents) :
# - Treasury : upload camt d'ALYF (court-circuite override_whitelisted_methods)
#   -> l'écran ALYF utilise notre import FX/ZIP.
# - eu_einvoice : identifiant TVA du vendeur suisse (BT-31 au lieu de BT-32).
boot_session = [
    "erpnextswiss.treasury.overrides.apply_monkeypatches",
    "erpnextswiss.einvoice_compat.patches.apply_einvoice_patches",
]

# Fixtures (to import DocType customisations)
# --------
fixtures = ["Custom Field", "AFC VAT Box"]

domains = {
    'HLK': 'erpnextswiss.domains.hlk'
}
