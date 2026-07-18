# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Print Format « Décompte TVA (AFC) » — reproduit la mise en page officielle AFC/bexio
pour le doctype VAT Declaration (fork erpnextswiss).

Usage :
  bench --site <site> execute erpnextswiss.swiss_vat_config.print_formats.create_vat_print_format
"""
import frappe

PF_NAME = "Decompte TVA (AFC)"

# Jinja : `doc` = VAT Declaration. Formatage suisse (apostrophe milliers, 2 decimales).
HTML = r"""
{%- macro fmt(v) -%}{{ "{:,.2f}".format(v or 0).replace(",", "'") }}{%- endmacro -%}
<style>
  .tva { font-family: Helvetica, Arial, sans-serif; color:#222; font-size:11px; }
  .tva h1 { font-size:16px; margin:0 0 2px 0; }
  .tva h2 { font-size:12px; margin:0 0 12px 0; color:#555; font-weight:normal; }
  .tva .sec { font-weight:bold; font-size:12px; background:#f2f2f2; padding:5px 8px;
              border:1px solid #ccc; margin-top:14px; }
  .tva table { width:100%; border-collapse:collapse; }
  .tva td { padding:4px 6px; border-bottom:1px solid #eee; vertical-align:top; }
  .tva .lbl { width:62%; }
  .tva .num { width:52px; text-align:center; color:#666; font-variant-numeric:tabular-nums; }
  .tva .op  { width:16px; text-align:center; color:#999; }
  .tva .amt { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .tva .box { border:1px solid #bbb; background:#fafafa; padding:3px 6px; border-radius:2px;
              display:inline-block; min-width:78px; text-align:right; }
  .tva .tot { font-weight:bold; }
  .tva .rate { color:#888; width:34px; text-align:right; }
  .tva .head th { font-size:9px; color:#777; font-weight:normal; text-align:right;
                  border-bottom:1px solid #ccc; padding:3px 6px; }
  .tva .foot { margin-top:16px; text-align:center; color:#888; font-size:9px;
               border-top:1px solid #ccc; padding-top:8px; }
</style>

<div class="tva">
  <h1>Décompte TVA — {{ doc.company }}</h1>
  <h2>{{ doc.title }} &nbsp;·&nbsp; du {{ doc.get_formatted("start_date") }}
      au {{ doc.get_formatted("end_date") }}</h2>

  <div class="sec">I. Chiffre d'affaires <span style="font-weight:normal;color:#888">(loi TVA du 12.06.2009)</span></div>
  <table>
    <tr><td class="lbl">Total des contre-prestations convenues ou reçues (art. 39), y c. transferts et prestations à l'étranger</td>
        <td class="num">200</td><td class="op"></td><td class="amt"><span class="box">{{ fmt(doc.total_revenue) }}</span></td></tr>
    <tr><td class="lbl">Contre-prestations optées selon l'art. 22 (déjà comprises dans le ch. 200)</td>
        <td class="num">205</td><td class="op"></td><td class="amt">{{ fmt(doc.non_taxable_revenue) }}</td></tr>
    <tr><td class="lbl"><b>Déductions :</b> Prestations exonérées (exportations, art. 23 ; art. 107 al. 1 let. a)</td>
        <td class="num">220</td><td class="op"></td><td class="amt">{{ fmt(doc.tax_free_services) }}</td></tr>
    <tr><td class="lbl">Prestations fournies à l'étranger</td>
        <td class="num">221</td><td class="op">+</td><td class="amt">{{ fmt(doc.revenue_abroad) }}</td></tr>
    <tr><td class="lbl">Transferts avec la procédure de déclaration (art. 38, formulaire n° 764)</td>
        <td class="num">225</td><td class="op">+</td><td class="amt">{{ fmt(doc.transfers) }}</td></tr>
    <tr><td class="lbl">Prestations exclues du champ de l'impôt (art. 21) sans option</td>
        <td class="num">230</td><td class="op">+</td><td class="amt">{{ fmt(doc.non_taxable_services) }}</td></tr>
    <tr><td class="lbl">Diminutions de la contre-prestation</td>
        <td class="num">235</td><td class="op">+</td><td class="amt">{{ fmt(doc.losses) }}</td></tr>
    <tr><td class="lbl">Divers (p. ex. valeur du terrain)</td>
        <td class="num">280</td><td class="op">+</td><td class="amt">{{ fmt(doc.misc) }}</td></tr>
    <tr><td class="lbl">Total des déductions (ch. 220 à 280)</td>
        <td class="num">289</td><td class="op">=</td><td class="amt tot">{{ fmt(doc.total_deductions) }}</td></tr>
    <tr><td class="lbl tot">Total du chiffre d'affaires imposable (ch. 200 moins ch. 289)</td>
        <td class="num">299</td><td class="op">=</td><td class="amt"><span class="box tot">{{ fmt(doc.taxable_revenue) }}</span></td></tr>
  </table>

  <div class="sec">II. Calcul de l'impôt</div>
  <table>
    <tr class="head"><th style="text-align:left">&nbsp;</th><th>Ch.</th><th>Prestations CHF</th><th>Impôt CHF / ct.</th><th>Taux</th></tr>
    <tr><td class="lbl">Taux normal</td><td class="num">303</td><td class="amt">{{ fmt(doc.normal_amount_2024) }}</td><td class="amt">{{ fmt(doc.normal_tax_2024) }}</td><td class="rate">{{ fmt(doc.normal_rate_2024) }}%</td></tr>
    <tr><td class="lbl">Taux réduit</td><td class="num">313</td><td class="amt">{{ fmt(doc.reduced_amount_2024) }}</td><td class="amt">{{ fmt(doc.reduced_tax_2024) }}</td><td class="rate">{{ fmt(doc.reduced_rate_2024) }}%</td></tr>
    <tr><td class="lbl">Taux spécial hébergement</td><td class="num">343</td><td class="amt">{{ fmt(doc.lodging_amount_2024) }}</td><td class="amt">{{ fmt(doc.lodging_tax_2024) }}</td><td class="rate">{{ fmt(doc.lodging_rate_2024) }}%</td></tr>
    <tr><td class="lbl">Impôt sur les acquisitions</td><td class="num">383</td><td class="amt">{{ fmt(doc.additional_amount_2024) }}</td><td class="amt">{{ fmt(doc.additional_tax_2024) }}</td><td class="rate"></td></tr>
    {% if (doc.normal_amount or 0) or (doc.reduced_amount or 0) or (doc.lodging_amount or 0) or (doc.additional_amount or 0) %}
    <tr><td class="lbl" style="color:#888">Anciens taux (≤ 31.12.2023) — normal / réduit / hébergement / acquisitions</td>
        <td class="num">302…382</td><td class="amt" style="color:#888">{{ fmt((doc.normal_amount or 0)+(doc.reduced_amount or 0)+(doc.lodging_amount or 0)+(doc.additional_amount or 0)) }}</td>
        <td class="amt" style="color:#888">{{ fmt((doc.normal_tax or 0)+(doc.reduced_tax or 0)+(doc.lodging_tax or 0)+(doc.additional_tax or 0)) }}</td><td class="rate"></td></tr>
    {% endif %}
    <tr><td class="lbl tot">Total de l'impôt dû (ch. 302 à 383)</td><td class="num">399</td><td class="amt"></td>
        <td class="amt"><span class="box tot">{{ fmt(doc.total_tax) }}</span></td><td class="rate"></td></tr>
  </table>
  <table>
    <tr><td class="lbl">Impôt préalable sur les coûts en matériel et en prestations de services</td>
        <td class="num">400</td><td class="op"></td><td class="amt">{{ fmt(doc.pretax_material) }}</td></tr>
    <tr><td class="lbl">Impôt préalable sur les investissements et autres charges d'exploitation</td>
        <td class="num">405</td><td class="op">+</td><td class="amt">{{ fmt(doc.pretax_investments) }}</td></tr>
    <tr><td class="lbl">Dégrèvement ultérieur de l'impôt préalable (art. 32)</td>
        <td class="num">410</td><td class="op">+</td><td class="amt">{{ fmt(doc.missing_pretax) }}</td></tr>
    <tr><td class="lbl">Corrections : double affectation (art. 30), prestations à soi-même (art. 31)</td>
        <td class="num">415</td><td class="op">−</td><td class="amt">{{ fmt(doc.pretax_correction_mixed) }}</td></tr>
    <tr><td class="lbl">Réductions : subventions, taxes touristiques, etc. (art. 33 al. 2)</td>
        <td class="num">420</td><td class="op">−</td><td class="amt">{{ fmt(doc.pretax_correction_other) }}</td></tr>
    <tr><td class="lbl tot">Total de l'impôt préalable (ch. 400 à 420)</td>
        <td class="num">479</td><td class="op">=</td><td class="amt"><span class="box tot">{{ fmt(doc.total_pretax_reductions) }}</span></td></tr>
    <tr><td class="lbl tot">Montant à payer à l'Administration fédérale des contributions</td>
        <td class="num">500</td><td class="op">=</td><td class="amt"><span class="box tot">{{ fmt(doc.payable_tax) }}</span></td></tr>
    <tr><td class="lbl tot">Solde en faveur de l'assujetti</td>
        <td class="num">510</td><td class="op">=</td><td class="amt"><span class="box tot">{% if (doc.balance or 0) %}{{ fmt(doc.balance) }}{% endif %}</span></td></tr>
  </table>

  <div class="sec">III. Autres mouvements de fonds (art. 18 al. 2)</div>
  <table>
    <tr><td class="lbl">Subventions, taxes touristiques, contributions élimination des déchets / eau (let. a à c)</td>
        <td class="num">900</td><td class="op"></td><td class="amt">{{ fmt(doc.grants) }}</td></tr>
    <tr><td class="lbl">Dons, dividendes, dédommagements, etc. (let. d à l)</td>
        <td class="num">910</td><td class="op"></td><td class="amt">{{ fmt(doc.donations) }}</td></tr>
  </table>

  <div class="foot">Pour vos archives uniquement. Pour soumettre votre déclaration, utilisez le portail de l'AFC (fichier XML eCH-0217).</div>
</div>
"""


def create_vat_print_format():
    if frappe.db.exists("Print Format", PF_NAME):
        frappe.delete_doc("Print Format", PF_NAME, ignore_permissions=True, force=True)
    doc = frappe.get_doc({
        "doctype": "Print Format",
        "name": PF_NAME,
        "doc_type": "VAT Declaration",
        "module": "Erpnextswiss",
        "print_format_type": "Jinja",
        "standard": "No",
        "custom_format": 1,
        "disabled": 0,
        "html": HTML,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    # définit ce format comme format d'impression PAR DÉFAUT du doctype (Property Setter)
    frappe.make_property_setter({
        "doctype": "VAT Declaration",
        "doctype_or_field": "DocType",
        "property": "default_print_format",
        "value": PF_NAME,
        "property_type": "Data",
    }, ignore_validate=True)
    frappe.db.commit()
    return f"Print Format '{PF_NAME}' cree et defini par defaut (doctype VAT Declaration)."
