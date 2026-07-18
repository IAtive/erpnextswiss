# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Runner des scénarios de test comptables.

Deux modes :
  - run_all(company)                  : lance TOUS les scénarios, reset entre chaque, rapport global.
  - run_one(company, nom, persist=1)  : lance UN scénario ; si persist, laisse les données en place
                                        dans la société pour inspection dans l'app (pas de reset final).

Reset :
  - reset_test_company(company) : reset CIBLÉ léger (annule+supprime les pièces transactionnelles) —
    synchrone, rapide, garde le paramétrage (chart, templates TVA, comptes).
  - deep_reset(company)         : reset PROFOND via le Transaction Deletion Record natif (async).

Usage :
  bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.run_all --kwargs "{'company':'HJD'}"
  bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.run_one --kwargs "{'company':'HJD','nom':'achat_etranger_reverse_charge','persist':1}"
"""
import frappe
from erpnextswiss.swiss_vat_config.tests.helpers import Ctx, ensure_masters

# pièces transactionnelles créées par les scénarios (ordre d'annulation : dépendances d'abord)
_TXN_DOCTYPES = ["Period Closing Voucher", "Payment Entry", "Sales Invoice", "Purchase Invoice",
                 "Exchange Rate Revaluation", "Journal Entry", "Delivery Note", "Purchase Receipt",
                 "Stock Entry", "VAT Declaration"]


def reset_test_company(company):
    """Reset ciblé : annule puis supprime les pièces transactionnelles de la société.
    Garde intact le paramétrage (chart, comptes, templates TVA)."""
    # passe 1 : tout annuler
    for dt in _TXN_DOCTYPES:
        for name in frappe.get_all(dt, filters={"company": company, "docstatus": 1}, pluck="name"):
            try:
                frappe.get_doc(dt, name).cancel()
            except Exception:
                pass
    # passe 2 : tout supprimer (force → emporte les GL Entry liées)
    for dt in _TXN_DOCTYPES:
        for name in frappe.get_all(dt, filters={"company": company}, pluck="name"):
            try:
                frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
            except Exception:
                pass
    frappe.db.commit()


def deep_reset(company):
    """Reset profond via le Transaction Deletion Record natif (asynchrone, filet de sécurité)."""
    tdr = frappe.get_doc({"doctype": "Transaction Deletion Record", "company": company})
    tdr.insert(ignore_permissions=True)
    tdr.submit()
    frappe.db.commit()
    return f"Transaction Deletion Record {tdr.name} soumis (tâche de fond). Vérifier son statut."


def _run(ctx, name):
    from erpnextswiss.swiss_vat_config.tests import scenarios
    fn = getattr(scenarios, "scenario_" + name, None)
    if not fn:
        ctx._rec("ERREUR", "scénario", None, f"scenario_{name} introuvable", False)
        return ctx
    try:
        fn(ctx)
    except Exception:
        ctx._rec("ERREUR", "exécution", None, frappe.get_traceback(with_context=False), False)
    return ctx


def run_one(company, nom, persist=0):
    reset_test_company(company)
    ensure_masters(company)
    ctx = Ctx(company, nom)
    _run(ctx, nom)
    frappe.db.commit()
    report = render_report([ctx])
    if not int(persist):
        reset_test_company(company)
    else:
        report += (f"\n\n>>> Mode PERSIST : données laissées dans « {company} » pour inspection.\n"
                   f"    (relance run_one/run_all pour nettoyer)")
    print("\n" + report + "\n")   # print = affichage brut lisible via bench execute
    return


def run_all(company):
    from erpnextswiss.swiss_vat_config.tests import scenarios
    names = sorted(n[len("scenario_"):] for n in dir(scenarios) if n.startswith("scenario_"))
    ctxs = []
    for nom in names:
        reset_test_company(company)
        ensure_masters(company)
        ctx = Ctx(company, nom)
        _run(ctx, nom)
        frappe.db.commit()
        ctxs.append(ctx)
    reset_test_company(company)
    print("\n" + render_report(ctxs, summary=True) + "\n")
    return


# --- Rapport ------------------------------------------------------------------
def render_report(ctxs, summary=False):
    out = []
    n_scen_ok = 0
    for ctx in ctxs:
        res = ctx.results
        n_ok = sum(1 for r in res if r["ok"])
        scen_ok = res and n_ok == len(res)
        n_scen_ok += 1 if scen_ok else 0
        head = "✅ OK" if scen_ok else f"❌ {len(res) - n_ok} échec(s)"
        out.append("═" * 78)
        out.append(f"SCÉNARIO : {ctx.name}   {head}   ({n_ok}/{len(res)})")
        out.append("─" * 78)
        for r in res:
            icon = "✅" if r["ok"] else "❌"
            line = (f"  {icon} {r['layer']:<12} {r['target']:<10} "
                    f"attendu {str(r['expected']):>11}  obtenu {str(r['actual']):>11}")
            out.append(line)
            if r["detail"] and not r["ok"]:
                out.append(f"        ↳ {r['detail']}")
    if summary:
        out.append("═" * 78)
        out.append(f"RÉSUMÉ : {n_scen_ok}/{len(ctxs)} scénario(s) au vert")
    return "\n".join(out)
