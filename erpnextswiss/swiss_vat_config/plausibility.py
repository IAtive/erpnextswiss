# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Contrôle de plausibilité du décompte TVA.

Garantit qu'aucune transaction n'échappe au décompte :
  - Contrôle 1 : réconciliation GRAND LIVRE <-> décompte (le maître, data-driven).
  - Contrôle 2 : lignes taxables NON classées (ventes / achats sans afc_box).
  - Contrôle 3 : sanité de la CONFIGURATION (templates / comptes de TVA sans afc_box).

`collect()` renvoie une liste structurée de résultats, réutilisée par le CLI (`run_checks`) et
le Script Report UI « Contrôle de plausibilité TVA ».

Usage CLI :
  bench --site <site> execute erpnextswiss.swiss_vat_config.plausibility.run_checks \
    --kwargs "{'company':'X','start_date':'2026-01-01','end_date':'2026-12-31'}"
"""
import json
import frappe

TOL = 0.05  # tolérance (arrondi 5 centimes)
OK, KO, WARN = "✅ OK", "❌ Anomalie", "⚠️ À vérifier"
# comptes de TVA qui n'ont légitimement PAS d'afc_box (gérés autrement / techniques)
SAFE_NO_AFC_BOX = ["2200", "2201", "2202", "1172"]


def _acc(company, num):
    return frappe.db.get_value("Account", {"account_number": num, "company": company})


def _gl_movement(company, account, start, end):
    r = frappe.db.sql("""SELECT IFNULL(SUM(debit),0), IFNULL(SUM(credit),0)
        FROM `tabGL Entry`
        WHERE company=%s AND account=%s AND posting_date BETWEEN %s AND %s AND is_cancelled=0""",
                      (company, account, start, end))
    return float(r[0][0]), float(r[0][1])


def _row(control, item, expected, actual, status, detail=""):
    return {"control": control, "item": item, "expected": expected,
            "actual": actual, "status": status, "detail": detail}


def collect(company, start_date, end_date):
    """Exécute les 3 contrôles et renvoie une liste de dicts (control, item, expected, actual, status, detail)."""
    from erpnextswiss.erpnextswiss.doctype.vat_declaration.vat_declaration import (
        get_view_total, get_view_tax)
    rows = []

    # ===================== Contrôle 1 : réconciliation GL <-> décompte =====================
    C1 = "1 · GL ↔ décompte"
    acc2200 = _acc(company, "2200")
    if acc2200:
        d, c = _gl_movement(company, acc2200, start_date, end_date)
        gl_sales_vat = c - d
        computed = 0.0
        normal_rate = 0.0
        for b in frappe.get_all("AFC VAT Box",
                                filters={"side": "Sales", "amount_type": "Base",
                                         "computation": "Declared", "rate": [">", 0]},
                                fields=["box_code", "rate"]):
            base = get_view_total(f"viewVAT_{b.box_code}", start_date, end_date, company)["total"] or 0
            computed += base * b.rate / 100
            normal_rate = max(normal_rate, b.rate)
        # Diminutions de la contre-prestation (case 235 : escomptes/rabais/ristournes) : elles réduisent
        # la base imposable ET la TVA due. On les soustrait au taux normal (l'escompte suit le taux de la
        # vente ; un escompte à taux réduit exigerait un suivi par taux, non nécessaire pour ce contrôle).
        dim235 = get_view_total("viewVAT_235", start_date, end_date, company)["total"] or 0
        computed -= dim235 * normal_rate / 100
        ok = abs(gl_sales_vat - computed) < TOL
        rows.append(_row(C1, "TVA vente (2200)", round(computed, 2), round(gl_sales_vat, 2),
                         OK if ok else KO, "" if ok else f"écart {gl_sales_vat - computed:.2f}"))

    for a in frappe.get_all("Account", filters={"company": company, "afc_box": ["is", "set"]},
                            fields=["name", "account_number", "afc_box", "root_type"]):
        d, c = _gl_movement(company, a.name, start_date, end_date)
        movement = (d - c) if a.root_type == "Asset" else (c - d)
        # un compte peut alimenter PLUSIEURS cases (override ligne, ex. 1170 = 400 + 410 via DUIP) :
        # on somme les viewVAT de toutes les cases que ses lignes de taxe résolvent.
        boxes = [r[0] for r in frappe.db.sql("""
            SELECT DISTINCT COALESCE(ptc.afc_box, %(dft)s)
            FROM `tabPurchase Taxes and Charges` ptc
            JOIN `tabPurchase Invoice` pi ON pi.name = ptc.parent
            WHERE pi.docstatus = 1 AND pi.company = %(c)s AND ptc.account_head = %(acc)s
              AND pi.posting_date BETWEEN %(s)s AND %(e)s""",
            {"dft": a.afc_box, "c": company, "acc": a.name, "s": start_date, "e": end_date})] or [a.afc_box]
        vtax = sum(get_view_tax(f"viewVAT_{b}", start_date, end_date, company)["total"] or 0 for b in boxes)
        ok = abs(movement - vtax) < TOL
        rows.append(_row(C1, f"compte {a.account_number} → case(s) {', '.join(sorted(boxes))}",
                         round(vtax, 2), round(movement, 2), OK if ok else KO,
                         "" if ok else f"écart {movement - vtax:.2f}"))

    # ===================== Contrôle 2 : lignes taxables NON classées =====================
    C2 = "2 · Lignes non classées"
    unclassified = frappe.db.sql("""
        SELECT si.name AS inv, si.customer AS tiers, sii.item_code AS item,
               sii.base_net_amount AS ht, sii.item_tax_rate AS itr
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem Tax Template` itt ON itt.name = sii.item_tax_template
        LEFT JOIN `tabSales Taxes and Charges Template` stct ON stct.name = si.taxes_and_charges
        WHERE si.docstatus = 1 AND si.company = %(c)s
          AND si.posting_date BETWEEN %(s)s AND %(e)s
          AND COALESCE(itt.afc_box, stct.afc_box) IS NULL
    """, {"c": company, "s": start_date, "e": end_date}, as_dict=True)
    taxable = []
    for r in unclassified:
        rate = 0
        if r.itr:
            try:
                vals = list(json.loads(r.itr).values())
                rate = max(vals) if vals else 0
            except Exception:
                rate = 0
        if rate > 0:
            taxable.append(r)
    if taxable:
        for r in taxable[:50]:
            rows.append(_row(C2, f"vente {r.inv}", None, round(r.ht or 0, 2), KO,
                             f"{r.tiers} · {r.item} — taxable sans case"))
    else:
        rows.append(_row(C2, "Ventes taxables sans case", None, 0, OK,
                         f"{len(unclassified)} ligne(s) 0% sans case (sans impact)"))

    p_unclassified = frappe.db.sql("""
        SELECT pi.name AS inv, ptc.account_head AS acc, ptc.base_tax_amount AS tax
        FROM `tabPurchase Taxes and Charges` ptc
        JOIN `tabPurchase Invoice` pi ON pi.name = ptc.parent
        JOIN `tabAccount` a ON a.name = ptc.account_head
        WHERE pi.docstatus = 1 AND pi.company = %(c)s
          AND pi.posting_date BETWEEN %(s)s AND %(e)s
          AND a.account_type = 'Tax' AND (a.afc_box IS NULL OR a.afc_box = '')
    """, {"c": company, "s": start_date, "e": end_date}, as_dict=True)
    if p_unclassified:
        for r in p_unclassified[:50]:
            rows.append(_row(C2, f"achat {r.inv}", None, round(r.tax or 0, 2), KO,
                             f"{r.acc} — TVA sur compte sans case"))
    else:
        rows.append(_row(C2, "Achats TVA sur compte sans case", None, 0, OK, ""))

    # ===================== Contrôle 3 : sanité de la configuration =====================
    C3 = "3 · Configuration"
    for dt, child, ratef in [("Sales Taxes and Charges Template", "Sales Taxes and Charges", "rate"),
                             ("Item Tax Template", "Item Tax Template Detail", "tax_rate")]:
        bad = frappe.db.sql(f"""
            SELECT p.name, MAX(t.`{ratef}`) AS rate
            FROM `tab{dt}` p JOIN `tab{child}` t ON t.parent = p.name
            WHERE p.company = %s AND p.disabled = 0 AND (p.afc_box IS NULL OR p.afc_box = '')
            GROUP BY p.name HAVING MAX(t.`{ratef}`) > 0
        """, company, as_dict=True)
        for b in bad:
            rows.append(_row(C3, f"template {b.name}", None, b.rate, KO,
                             "actif, taux > 0, SANS afc_box → piège potentiel"))

    safe = "','".join(SAFE_NO_AFC_BOX)
    moved = frappe.db.sql(f"""
        SELECT a.account_number AS num, IFNULL(SUM(g.debit),0)+IFNULL(SUM(g.credit),0) AS mvt
        FROM `tabAccount` a JOIN `tabGL Entry` g ON g.account = a.name
        WHERE a.company = %(c)s AND a.account_type = 'Tax' AND a.disabled = 0
          AND (a.afc_box IS NULL OR a.afc_box = '') AND a.account_number NOT IN ('{safe}')
          AND g.posting_date BETWEEN %(s)s AND %(e)s AND g.is_cancelled = 0
        GROUP BY a.name HAVING mvt > 0
    """, {"c": company, "s": start_date, "e": end_date}, as_dict=True)
    for m in moved:
        rows.append(_row(C3, f"compte {m.num}", None, round(m.mvt, 2), WARN,
                         "compte de TVA mouvementé, SANS afc_box"))
    # ligne de synthèse config si tout est bon
    if not any(r["control"] == C3 for r in rows):
        rows.append(_row(C3, "Templates & comptes de TVA", None, None, OK, "tous correctement mappés"))

    # ===================== Contrôle 4 : taux de la ligne <-> taux de la case =====================
    C4 = "4 · Taux ligne ↔ case"
    box_rate = {b.box_code: b.rate for b in frappe.get_all(
        "AFC VAT Box", filters={"side": "Sales", "amount_type": "Base", "rate": [">", 0]},
        fields=["box_code", "rate"])}
    boxes_t = tuple(box_rate.keys()) or ("",)
    lines = frappe.db.sql("""
        SELECT si.name AS inv, sii.item_code AS item, sii.item_tax_rate AS itr,
               COALESCE(itt.afc_box, stct.afc_box) AS box
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem Tax Template` itt ON itt.name = sii.item_tax_template
        LEFT JOIN `tabSales Taxes and Charges Template` stct ON stct.name = si.taxes_and_charges
        WHERE si.docstatus = 1 AND si.company = %(c)s AND si.posting_date BETWEEN %(s)s AND %(e)s
          AND COALESCE(itt.afc_box, stct.afc_box) IN %(boxes)s
    """, {"c": company, "s": start_date, "e": end_date, "boxes": boxes_t}, as_dict=True)
    mism = []
    for r in lines:
        exp = box_rate.get(r.box)
        act = 0
        if r.itr:
            try:
                vals = list(json.loads(r.itr).values())
                act = max(vals) if vals else 0
            except Exception:
                act = 0
        if exp is not None and abs(act - exp) > 0.001:
            mism.append((r, exp, act))
    if mism:
        for r, exp, act in mism[:50]:
            rows.append(_row(C4, f"vente {r.inv}", None, None, KO,
                             f"{r.item} · classée case {r.box} ({exp}%) mais taux réel {act}%"))
    else:
        rows.append(_row(C4, "Cohérence taux / case", None, None, OK,
                         "tous les taux correspondent à leur case"))

    # ===================== Contrôle 5 : écritures manuelles (JE) sur comptes de TVA =====================
    C5 = "5 · Écritures manuelles"
    decompte_accts = [acc2200] + [a.name for a in frappe.get_all(
        "Account", filters={"company": company, "afc_box": ["is", "set"]}, fields=["name"])]
    decompte_accts = tuple(a for a in decompte_accts if a) or ("",)
    je = frappe.db.sql("""
        SELECT g.voucher_no AS vno, g.account AS acc, g.debit AS d, g.credit AS c
        FROM `tabGL Entry` g
        WHERE g.company = %(c)s AND g.voucher_type = 'Journal Entry' AND g.is_cancelled = 0
          AND g.posting_date BETWEEN %(s)s AND %(e)s AND g.account IN %(accts)s
    """, {"c": company, "s": start_date, "e": end_date, "accts": decompte_accts}, as_dict=True)
    if je:
        for r in je[:50]:
            rows.append(_row(C5, f"JE {r.vno}", None, round((r.d or r.c), 2), WARN,
                             f"{r.acc} — écriture manuelle sur un compte de TVA"))
    else:
        rows.append(_row(C5, "Écritures manuelles sur comptes de TVA", None, 0, OK, ""))

    # ===================== Contrôle 6 : documents en brouillon dans la période =====================
    C6 = "6 · Documents en brouillon"
    drafts = []
    for dt, label in [("Sales Invoice", "vente"), ("Purchase Invoice", "achat")]:
        for d in frappe.get_all(dt, filters={"company": company, "docstatus": 0,
                                             "posting_date": ["between", [start_date, end_date]]},
                                fields=["name", "grand_total"]):
            drafts.append((label, d.name, d.grand_total))
    if drafts:
        for label, name, gt in drafts[:50]:
            rows.append(_row(C6, f"{label} {name}", None, round(gt or 0, 2), WARN,
                             "brouillon dans la période — à soumettre ?"))
    else:
        rows.append(_row(C6, "Documents en brouillon dans la période", None, 0, OK, ""))

    # ===================== Contrôle 7 : CA hors facturation (case 200 vs produits) =====================
    C7 = "7 · CA hors facturation"
    box200 = get_view_total("viewVAT_200", start_date, end_date, company)["total"] or 0
    inc = frappe.db.sql("""
        SELECT IFNULL(SUM(g.credit),0) - IFNULL(SUM(g.debit),0)
        FROM `tabGL Entry` g JOIN `tabAccount` a ON a.name = g.account
        WHERE g.company = %(c)s AND a.root_type = 'Income' AND g.is_cancelled = 0
          AND g.posting_date BETWEEN %(s)s AND %(e)s
    """, {"c": company, "s": start_date, "e": end_date})
    income_credit = float(inc[0][0])
    gap = income_credit - box200
    ok = abs(gap) < TOL
    rows.append(_row(C7, "Produits (classe 3) vs case 200", round(box200, 2), round(income_credit, 2),
                     OK if ok else WARN, "" if ok else f"écart {gap:.2f} — CA possiblement hors facture"))

    return rows


# ============================== Hook VAT Declaration (garde-fou auto) ==============================
def _issues_for_doc(doc):
    if not (doc.get("company") and doc.get("start_date") and doc.get("end_date")):
        return [], []
    rows = collect(doc.company, str(doc.start_date), str(doc.end_date))
    return ([r for r in rows if r["status"] == KO],
            [r for r in rows if r["status"] == WARN])


def _fmt_issues(rows):
    return "<br>".join(f"• [{r['control']}] {r['item']} — {r['detail'] or r['status']}" for r in rows)


def vat_declaration_warn(doc, method=None):
    """Hook `validate` : avertit (non bloquant) si le décompte présente des anomalies / points à vérifier."""
    anomalies, warnings = _issues_for_doc(doc)
    if not (anomalies or warnings):
        return
    parts = []
    if anomalies:
        parts.append(f"<b>{len(anomalies)} anomalie(s) à corriger :</b><br>{_fmt_issues(anomalies)}")
    if warnings:
        parts.append(f"<b>{len(warnings)} point(s) à vérifier :</b><br>{_fmt_issues(warnings)}")
    frappe.msgprint("<br><br>".join(parts), title="Contrôle de plausibilité TVA",
                    indicator="red" if anomalies else "orange")


def vat_declaration_block(doc, method=None):
    """Hook `before_submit` : bloque la soumission tant qu'il reste des anomalies dures (❌)."""
    anomalies, _w = _issues_for_doc(doc)
    if anomalies:
        frappe.throw(
            f"Décompte non plausible : {len(anomalies)} anomalie(s) à corriger avant soumission.<br>"
            f"{_fmt_issues(anomalies)}", title="Contrôle de plausibilité TVA")


def run_checks(company, start_date, end_date):
    """Version CLI : texte lisible à partir de collect()."""
    rows = collect(company, start_date, end_date)
    anomalies = sum(1 for r in rows if r["status"] == KO)
    warns = sum(1 for r in rows if r["status"] == WARN)
    out, current = [], None
    for r in rows:
        if r["control"] != current:
            current = r["control"]
            out.append(f"\n=== Contrôle {current} ===")
        exp = f"{r['expected']:.2f}" if isinstance(r["expected"], (int, float)) else "—"
        act = f"{r['actual']:.2f}" if isinstance(r["actual"], (int, float)) else "—"
        line = f"  {r['status']}  {r['item']:<32} décompte {exp:>10}  |  GL/valeur {act:>10}"
        if r["detail"]:
            line += f"   ({r['detail']})"
        out.append(line)
    bilan = "✅ TOUT PLAUSIBLE" if anomalies == 0 else f"❌ {anomalies} anomalie(s)"
    if warns:
        bilan += f" · {warns} à vérifier"
    out.append(f"\n=== BILAN : {bilan} ===")
    return "\n".join(out)
