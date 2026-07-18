# -*- coding: utf-8 -*-
# Copyright (c) 2026, IAtive and contributors
"""Scénarios de test comptables (chacun = section commentaire fiduciaire + opérations + contrôles).

Chaque fonction `scenario_<nom>(ctx)` :
  - documente en tête POURQUOI, les OPÉRATIONS, les VALEURS ATTENDUES (lisible par un fiduciaire) ;
  - exécute les opérations via les builders de `ctx` ;
  - vérifie les valeurs via les asserters de `ctx` (GL, TVA, résultat, plausibilité).
"""


def scenario_achat_etranger_reverse_charge(ctx):
    """
    ══════════════════════════════════════════════════════════════════════════════
    SCÉNARIO : Achat de prestation à un fournisseur étranger (reverse charge)
    ══════════════════════════════════════════════════════════════════════════════

    POURQUOI CE TEST
      Une prestation de services reçue d'un fournisseur ÉTRANGER, sans TVA suisse.
      Au-delà de 10 000 CHF/an, l'assujetti doit DÉCLARER la TVA (impôt sur les
      acquisitions, art. 45 LTVA) ET peut la DÉDUIRE simultanément. Résultat :
      trésorerie nulle sur la TVA, mais les DEUX montants doivent apparaître au
      décompte (case 383 pour le dû, case 405 pour le préalable déduit).

    OPÉRATIONS EFFECTUÉES
      1. Facture d'achat de 1 000 CHF (net), fournisseur « SCEN Fournisseur Etranger »,
         template TVA « IACE81 » (montage à 2 lignes :
            Add    1171  +81   (impôt préalable, déductible)
            Deduct 2203  −81   (impôt sur les acquisitions, dû)).

    ÉCRITURES ATTENDUES (grand livre)
      Dr Charge (4200) ............. 1 000
      Dr Impôt préalable 1171 .......... 81      → déductible (case 405)
         Cr Fournisseur (2000) ..... 1 000
         Cr Impôt acquisitions 2203 .... 81      → dû (case 383)
      (débits 1 081 = crédits 1 081 ; grand total facture = 1 000)

    DÉCOMPTE TVA ATTENDU
      Case 383 (impôt sur les acquisitions) : base 1 000 · impôt 81
      Case 405 (impôt préalable investissements/CE) : 81
      → effet net sur l'impôt dû : 0 (81 dû − 81 déduit)

    COMPTE DE RÉSULTAT (CO 959b)
      Charges de matériel/marchandises/prestations (classe 4) : −1 000

    PLAUSIBILITÉ : les 7 contrôles doivent être au vert (0 anomalie).

    HYPOTHÈSE FIDUCIAIRE (à valider §15) : compte d'impôt sur les acquisitions = 2203.
    ══════════════════════════════════════════════════════════════════════════════
    """
    pi = ctx.make_purchase_invoice(supplier="SCEN Fournisseur Etranger", net=1000,
                                   tax_template="IACE81")

    # Écritures
    ctx.assert_gl(pi, {"4200": +1000, "1171": +81, "2203": -81, "2000": -1000})
    # Décompte TVA
    ctx.assert_vat(base={"383": 1000}, tax={"383": 81, "405": 81})
    # Compte de résultat
    ctx.assert_pl("CH_MAT", -1000)
    # Cohérence globale
    ctx.assert_plausibilite_ok()


def scenario_vente_taux_normal(ctx):
    """
    SCÉNARIO : Vente au taux normal 8.1% (cas de base)
    POURQUOI : une vente ordinaire alimente le CA (200/303), pose la TVA sur 2200, le produit en classe 3.
    OPÉRATIONS : facture de vente 2 000 CHF net, client CH, template « NC81 » (TN 8.1%).
    ÉCRITURES : Cr Produit 3000 −2 000 · Cr TVA 2200 −162 · Dr Débiteur 2 162.
    DÉCOMPTE : case 200 (CA) 2 000 · case 303 base 2 000 / impôt 162.
    RÉSULTAT : Produits (classe 3) +2 000.
    """
    si = ctx.make_sales_invoice("SCEN Client CH", net=2000, tax_template="NC81")
    ctx.assert_gl(si, {"3000": -2000, "2200": -162})   # l'impôt vente (162) se vérifie sur le GL 2200
    ctx.assert_vat(base={"200": 2000, "303": 2000})
    ctx.assert_pl("PRODUITS", 2000)
    ctx.assert_plausibilite_ok()


def scenario_vente_multi_taux(ctx):
    """
    SCÉNARIO : Une facture de vente avec DEUX taux (8.1% + 2.6%)
    POURQUOI : vérifie la discrimination des cases PAR ARTICLE (cœur du mapping par ligne) —
               chaque article porte son code TVA → sa case.
    OPÉRATIONS : facture 2 lignes de 1 000 : art. 1 « NC81 » (8.1%), art. 2 « CR26 » (2.6%),
                 template document « NC81 ».
    ÉCRITURES : Cr Produit 3000 −2 000 · Cr TVA 2200 −107 (81 + 26).
    DÉCOMPTE : 200 = 2 000 · 303 base 1 000 / impôt 81 · 313 base 1 000 / impôt 26.
    RÉSULTAT : Produits +2 000.
    """
    si = ctx.make_sales_invoice("SCEN Client CH", tax_template="NC81", lines=[
        {"net": 1000, "item_tax_template": "NC81"},
        {"net": 1000, "item_tax_template": "CR26"}])
    ctx.assert_gl(si, {"3000": -2000, "2200": -107})   # impôt total (81+26) vérifié sur le GL 2200
    ctx.assert_vat(base={"200": 2000, "303": 1000, "313": 1000})
    ctx.assert_pl("PRODUITS", 2000)
    ctx.assert_plausibilite_ok()


def scenario_vente_export_exoneree(ctx):
    """
    SCÉNARIO : Vente à l'exportation / exonérée (0%)
    POURQUOI : une exportation est dans le CA (200) mais exonérée → déclarée en case 220, sans TVA.
    OPÉRATIONS : facture 3 000 CHF, client CH, template « CEX » (exonéré 0%).
    ÉCRITURES : Cr Produit 3000 −3 000 · pas de TVA.
    DÉCOMPTE : 200 = 3 000 · 220 = 3 000 · impôt 0.
    RÉSULTAT : Produits +3 000.
    """
    si = ctx.make_sales_invoice("SCEN Client CH", net=3000, tax_template="CEX")
    ctx.assert_gl(si, {"3000": -3000})
    ctx.assert_vat(base={"200": 3000, "220": 3000})
    ctx.assert_pl("PRODUITS", 3000)
    ctx.assert_plausibilite_ok()


def scenario_vente_optee_205_303(ctx):
    """
    SCÉNARIO : Prestation optée (art. 22) — double appartenance 303 + 205
    POURQUOI : une prestation exclue mais OPTÉE est imposée (303) ET signalée en mémo opté (205).
               Vérifie le champ afc_box_secondary.
    OPÉRATIONS : facture 2 000 CHF, template « PO81 » (opté 8.1%, case 303 + secondaire 205).
    ÉCRITURES : Cr Produit −2 000 · Cr TVA 2200 −162.
    DÉCOMPTE : 200 = 2 000 · 303 base 2 000 / impôt 162 · 205 (mémo) = 2 000.
    RÉSULTAT : Produits +2 000.
    """
    si = ctx.make_sales_invoice("SCEN Client CH", net=2000, tax_template="PO81")
    ctx.assert_gl(si, {"3000": -2000, "2200": -162})   # impôt vente (162) vérifié sur le GL 2200
    ctx.assert_vat(base={"200": 2000, "303": 2000, "205": 2000})
    ctx.assert_pl("PRODUITS", 2000)
    ctx.assert_plausibilite_ok()


def scenario_achat_materiel_400(ctx):
    """
    SCÉNARIO : Achat de matériel/prestations au taux normal (impôt préalable case 400)
    POURQUOI : achat CH ordinaire → impôt préalable déductible en case 400 (compte 1170).
    OPÉRATIONS : facture d'achat 2 000 CHF net, fournisseur CH, template « IPM81 » (8.1%).
    ÉCRITURES : Dr Charge 4200 +2 000 · Dr Préalable 1170 +162 · Cr Fournisseur −2 162.
    DÉCOMPTE : case 400 = 162.
    RÉSULTAT : Charges matériel (classe 4) −2 000.
    """
    pi = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=2000, tax_template="IPM81")
    ctx.assert_gl(pi, {"4200": +2000, "1170": +162, "2000": -2162})
    ctx.assert_vat(tax={"400": 162})
    ctx.assert_pl("CH_MAT", -2000)
    ctx.assert_plausibilite_ok()


def scenario_achat_investissement_405(ctx):
    """
    SCÉNARIO : Achat d'investissement / autres charges (impôt préalable case 405)
    POURQUOI : l'impôt préalable sur investissements va en case 405 (compte 1171), distincte du 400.
    OPÉRATIONS : facture d'achat 2 000 CHF net, fournisseur CH, template « IPCE81 » (8.1%).
    ÉCRITURES : Dr Préalable 1171 +162.
    DÉCOMPTE : case 405 = 162 · case 400 = 0.
    NOTE : la charge est imputée en 4200 pour le test ; en réel un investissement irait sur un
           compte d'actif (classe 1), sans impact sur la case 405 (qui vient de 1171).
    """
    pi = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=2000, tax_template="IPCE81")
    ctx.assert_gl(pi, {"1171": +162})
    ctx.assert_vat(tax={"405": 162, "400": 0})
    ctx.assert_plausibilite_ok()


def scenario_achat_degrevement_410(ctx):
    """
    SCÉNARIO : Dégrèvement ultérieur de l'impôt préalable (DUIP → case 410)
    POURQUOI : LE cas qui justifie la case portée par la LIGNE : le compte 1170 doit alimenter
               400 (achat normal) ET 410 (dégrèvement). Vérifie le SPLIT 1170 = 400 + 410.
    OPÉRATIONS : facture d'achat 2 000 CHF net, template « DUIP » (8.1%, ligne 1170 → case 410).
    ÉCRITURES : Dr Charge 4200 +2 000 · Dr Préalable 1170 +162 · Cr Fournisseur −2 162.
    DÉCOMPTE : case 410 = 162 · case 400 = 0 (le montant va bien en 410, PAS en 400).
    RÉSULTAT : Charges matériel −2 000.
    """
    pi = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=2000, tax_template="DUIP")
    ctx.assert_gl(pi, {"4200": +2000, "1170": +162})
    ctx.assert_vat(tax={"410": 162, "400": 0})
    ctx.assert_pl("CH_MAT", -2000)
    ctx.assert_plausibilite_ok()


def scenario_achat_douane_import(ctx):
    """
    SCÉNARIO : TVA à l'import (douane) via le transitaire — case 400
    DÉCISION §15 #9 (aligné bexio) : TVA import 100% → 1170 / case 400, sur la facture du transitaire.
    POURQUOI : les marchandises viennent d'un fournisseur étranger (facture 0%, non incluse ici) ;
               la douane (OFDF) perçoit la TVA import (81 = 8.1% de ~1 000), avancée par le transitaire
               qui la refacture avec ses frais.
    OPÉRATIONS : facture du transitaire = transport 100 CHF (net) + TVA import 81 CHF via code DOUAM (Actual → 1170).
    ÉCRITURES : Dr Transport 4200 +100 · Dr Impôt préalable import 1170 +81 · Cr Transitaire 2000 −181.
    DÉCOMPTE : case 400 = 81.
    RÉSULTAT : Charges (transport, classe 4) −100.
    """
    pi = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=100, expense="4200",
                                   tax_template="DOUAM", actual_tax=81)
    ctx.assert_gl(pi, {"4200": +100, "1170": +81, "2000": -181})
    ctx.assert_vat(tax={"400": 81})
    ctx.assert_pl("CH_MAT", -100)
    ctx.assert_plausibilite_ok()


def scenario_achat_import_biens_eur(ctx):
    """
    SCÉNARIO : Import de BIENS d'un fournisseur étranger, payé en EUR, avec TVA à l'import (douane)
    DÉCISION §15 #9 : des biens physiques importés → TVA à l'IMPORT (case 400 via la douane), et NON
                      un reverse charge (celui-ci vise les SERVICES). §15 #12 : facture/dette en EUR,
                      écart de change au paiement → 6999 (financier, la TVA reste au taux facture).
    POURQUOI : distinguer nettement l'import de BIENS (douane, case 400) du reverse charge des SERVICES,
               et vérifier le cycle multi-devises complet (dette EUR soldée, perte de change réalisée).
    OPÉRATIONS :
      1) facture fournisseur étranger : 1 000 EUR de marchandises, taux 0.95 → 950 CHF, SANS TVA suisse,
         dette sur 2001 (Dettes fournisseurs EUR) ;
      2) TVA à l'import via le transitaire (CHF) : transport 100 + TVA import 76.95 (DOUAM Actual → 1170) ;
      3) paiement du fournisseur : 1 000 EUR depuis la banque CHF, taux 1.00 → 1 000 CHF (l'EUR s'apprécie).
    ÉCRITURES :
      - biens   : Dr 4200 +950 · Cr 2001 −950 (1 000 EUR) ; AUCUNE TVA ;
      - douane  : Dr 4200 +100 (transport) · Dr 1170 +76.95 · Cr 2000 −176.95 ;
      - paiement: dette 2001 soldée (0 EUR / 0 CHF) ; perte de change = 1 000 − 950 = 50 → 6999.
    DÉCOMPTE : case 400 = 76.95 (TVA import déductible). PAS de case 383/405 (ce n'est pas du reverse charge).
    """
    # 1) marchandises EUR, sans TVA suisse (fournisseur étranger)
    pi = ctx.make_purchase_invoice("SCEN Fournisseur EUR", net=1000, expense="4200",
                                   currency="EUR", conversion_rate=0.95, credit_to="2001")
    ctx.assert_gl(pi, {"4200": 950, "2001": -950})
    # 2) TVA à l'import sur la facture du transitaire (CHF)
    imp = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=100, expense="4200",
                                    tax_template="DOUAM", actual_tax=76.95)
    ctx.assert_gl(imp, {"4200": 100, "1170": 76.95, "2000": -176.95})
    ctx.assert_vat(tax={"400": 76.95})          # TVA import déductible (PAS de reverse charge)
    # 3) paiement des 1 000 EUR depuis la banque CHF au taux 1.00 → perte de change réalisée
    ctx.make_payment("Purchase Invoice", pi.name, exchange_rate=1.00, bank="1020")
    ctx.assert_balance("2001", 0)               # dette EUR soldée (0 en CHF comme en EUR)
    ctx.assert_balance("6999", 50)              # perte de change réalisée = 1 000 − 950 (débit)
    ctx.assert_plausibilite_ok()


def scenario_bank_wizard_paiement_eur(ctx):
    """
    SCÉNARIO : Rapprochement Bank Wizard d'une facture d'ACHAT EUR payée depuis une banque CHF
    DÉCISION §15 #12 + fork §5.4 : le Bank Wizard doit reprendre le montant EN DEVISE + le taux réel
                       (XchgRate du camt, sinon dérivé du montant CHF débité) pour que le gain/perte de
                       change se calcule. Sans ça : le wizard prend le CHF débité pour de l'EUR au taux 1
                       → facture mal soldée + change faux. Ce scénario verrouille le fix.
    OPÉRATIONS : facture 1 000 EUR (taux 0.95 → dette 950 CHF) ; paiement via `make_payment_entry`
                 (fonction du wizard) depuis banque CHF, 930 CHF débités, camt InstdAmt=1000 / XchgRate=0.93.
    ÉCRITURES : facture soldée (0 EUR) ; dette 2001 soldée (0 CHF) ; GAIN de change 20 → 6999
                (on décaisse 930 CHF pour une dette inscrite à 950).
    """
    import frappe
    from erpnextswiss.erpnextswiss.page.bank_wizard.bank_wizard import make_payment_entry
    from erpnextswiss.swiss_vat_config.tests.helpers import _acc
    pi = ctx.make_purchase_invoice("SCEN Fournisseur EUR", net=1000, expense="4200",
                                   currency="EUR", conversion_rate=0.95, credit_to="2001")
    ctx.assert_gl(pi, {"4200": 950, "2001": -950})
    # paiement façon Bank Wizard, fidèle à read_camt053 : `amount` = 1000 EUR (montant transaction, sert au
    # MATCHING contre la facture EUR) · `booked_amount` = 930 CHF (réellement débité) · taux DÉRIVÉ 930/1000.
    make_payment_entry(1000, "2026-06-16", frappe.generate_hash(length=8),
                       paid_from=_acc(ctx.company, "1020"), paid_to=_acc(ctx.company, "2001"),
                       type="Pay", party="SCEN Fournisseur EUR", party_type="Supplier",
                       references=str([pi.name]), company=ctx.company, auto_submit=1,
                       instructed_amount=1000, booked_amount=930, xchg_rate=None)
    ctx.assert_balance("2001", 0)      # dette EUR soldée (CHF) → facture bien payée
    ctx.assert_balance("6999", -20)    # gain de change (crédit) : 930 payés pour 950 dus
    ctx.assert_plausibilite_ok()


def scenario_vente_avoir(ctx):
    """
    SCÉNARIO : Avoir / note de crédit client (annulation d'une vente)
    POURQUOI : un avoir reverse une vente → produit, TVA et cases du décompte deviennent NÉGATIFS.
    OPÉRATIONS : avoir de 2 000 CHF (net), client CH, template « NC81 » (8.1%).
    ÉCRITURES : Dr Produit 3000 +2 000 · Dr TVA 2200 +162 · Cr Débiteur −2 162 (tout inversé).
    DÉCOMPTE : case 200 = −2 000 · case 303 base = −2 000.
    RÉSULTAT : Produits −2 000.
    """
    cn = ctx.make_sales_invoice("SCEN Client CH", net=2000, tax_template="NC81", is_return=True)
    ctx.assert_gl(cn, {"3000": +2000, "2200": +162})
    ctx.assert_vat(base={"200": -2000, "303": -2000})
    ctx.assert_pl("PRODUITS", -2000)
    ctx.assert_plausibilite_ok()


def scenario_achat_avoir_fournisseur(ctx):
    """
    SCÉNARIO : Avoir / note de crédit fournisseur (retour d'achat)
    POURQUOI : un avoir fournisseur reverse un achat → charge, impôt préalable et case 400 NÉGATIFS.
    OPÉRATIONS : avoir d'achat de 2 000 CHF (net), fournisseur CH, template « IPM81 » (8.1%).
    ÉCRITURES : Cr Charge 4200 −2 000 · Cr Impôt préalable 1170 −162 · Dr Fournisseur +2 162.
    DÉCOMPTE : case 400 = −162.
    RÉSULTAT : Charges matériel +2 000 (charge réduite).
    """
    dn = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=2000, tax_template="IPM81", is_return=True)
    ctx.assert_gl(dn, {"4200": -2000, "1170": -162})
    ctx.assert_vat(tax={"400": -162})
    ctx.assert_pl("CH_MAT", +2000)
    ctx.assert_plausibilite_ok()


def scenario_vente_acompte_client(ctx):
    """
    SCÉNARIO : Acompte reçu d'un client (avant facturation)
    DÉCISION §15 #5 (compte 2030) + #8 (convenu → PAS de TVA sur l'acompte).
    POURQUOI : en méthode « convenue », un acompte reçu est un simple encaissement sur compte d'attente
               client (2030), SANS TVA (celle-ci naît à la facture).
    OPÉRATIONS : encaissement d'un acompte de 1 000 CHF du client CH.
    ÉCRITURES : Dr Banque 1020 +1 000 · Cr Acomptes reçus 2030 −1 000.
    DÉCOMPTE : aucune case ne bouge (pas de TVA, pas de CA).
    """
    pe = ctx.make_advance_payment("Customer", "SCEN Client CH", 1000)
    ctx.assert_gl(pe, {"1020": +1000, "2030": -1000})
    ctx.assert_vat(base={"200": 0})
    ctx.assert_plausibilite_ok()


def scenario_achat_acompte_fournisseur(ctx):
    """
    SCÉNARIO : Acompte versé à un fournisseur (avant facturation)
    DÉCISION §15 #5 (compte 1130) + #8 (convenu → pas d'impôt préalable sur l'acompte).
    POURQUOI : un acompte versé est un paiement anticipé (1130), sans TVA (le préalable naît à la facture).
    OPÉRATIONS : versement d'un acompte de 1 000 CHF au fournisseur CH.
    ÉCRITURES : Dr Paiements anticipés 1130 +1 000 · Cr Banque 1020 −1 000.
    DÉCOMPTE : aucune case ne bouge.
    """
    pe = ctx.make_advance_payment("Supplier", "SCEN Fournisseur CH", 1000)
    ctx.assert_gl(pe, {"1130": +1000, "1020": -1000})
    ctx.assert_vat(tax={"400": 0})
    ctx.assert_plausibilite_ok()


def scenario_bouclement_resultat(ctx):
    """
    SCÉNARIO : Bouclement du résultat vers les capitaux propres
    DÉCISION §15 #11 (aligné bexio) : résultat de l'exercice → compte 2979 via Period Closing Voucher.
    POURQUOI : à la clôture, le solde du compte de résultat (bénéfice) est viré en capitaux propres
               (2979 « Bénéfice/perte de l'exercice ») ; le compte de résultat repart à zéro.
    OPÉRATIONS : 1) vente 2 000 (NC81) · 2) achat 1 000 (IPM81) → bénéfice 1 000 · 3) Period Closing Voucher.
    ÉCRITURES (clôture) : solde des produits/charges viré, contrepartie Cr 2979 +1 000.
    RÉSULTAT après clôture :
      - solde 2979 = 1 000 (crédit) → LE contrôle du bouclement : le résultat est en capitaux propres ;
      - le compte de résultat 959b montre toujours BÉNÉFICE = 1 000 (le rapport P&L affiche le résultat
        de l'année et EXCLUT les écritures de clôture — c'est le comportement correct).
    """
    ctx.make_sales_invoice("SCEN Client CH", net=2000, tax_template="NC81")
    ctx.make_purchase_invoice("SCEN Fournisseur CH", net=1000, tax_template="IPM81")
    ctx.make_period_closing(closing="2979")
    ctx.assert_balance("2979", -1000)   # LE contrôle clé : bénéfice viré en capitaux propres
    ctx.assert_pl("BENEFICE", 1000)     # le rapport 959b montre le résultat de l'année (hors clôture)
    ctx.assert_plausibilite_ok()


def scenario_vente_en_devise_change(ctx):
    """
    SCÉNARIO : Vente en devise (EUR) avec différence de change au paiement
    DÉCISION §15 #12 : gain/perte de change → compte 6999 (Option A) ; la TVA reste en CHF au taux facture.
    POURQUOI : une facture en EUR expose à une différence de change entre facturation et encaissement.
               La TVA suisse est déclarée en CHF au taux de la facture ; l'écart de change réalisé → 6999.
    OPÉRATIONS : 1) facture 1 000 EUR net (NC81 8.1%) → total 1 081 EUR, taux facture 0.95 → base 950 CHF,
                    TVA 76.95 CHF, créance de 1 081 EUR sur 1101 (Créances clients EUR) valorisée 1 026.95 CHF ;
                    2) encaissement converti en CHF sur la banque, taux du jour 1.00 → 1 081 CHF réellement reçus.
    DÉCOMPTE : case 303 base = 950 CHF (au taux de la facture) · TVA 2200 = 76.95 CHF.
    CHANGE : créance valorisée 1 026.95 CHF (taux 0.95) soldée pour 1 081 CHF encaissés (taux 1.00) →
             l'EUR s'apprécie → GAIN de change RÉALISÉ 54.05 CHF = crédit 6999.
             (Encaissé sur une banque EUR, le gain resterait LATENT jusqu'à la réévaluation de fin de période.)
    DÉCISIONS §15 : #12 (comptes multi-devises EUR 1101/2001/1021 · change → 6999, réalisé/latent §11).
    """
    si = ctx.make_sales_invoice("SCEN Client EUR", net=1000, tax_template="NC81",
                                currency="EUR", conversion_rate=0.95, debit_to="1101")
    ctx.assert_gl(si, {"3000": -950, "2200": -76.95})   # base et TVA converties en CHF (taux 0.95)
    ctx.assert_vat(base={"303": 950})
    # encaissement converti en CHF (banque CHF par défaut) au taux 1.00 → gain de change RÉALISÉ
    pe = ctx.make_payment("Sales Invoice", si.name, exchange_rate=1.00)
    # La créance EUR (1101) doit se solder à 0 : le paiement en EUR l'apure correctement.
    ctx.assert_balance("1101", 0)
    # Gain de change réalisé : créance inscrite à 1 026.95 CHF (taux 0.95), encaissée pour 1 081 EUR
    #   valant 1 081 CHF (taux 1.00) → GAIN de 54.05 CHF = CRÉDIT sur 6999 (dérivé de la règle, non tuné).
    ctx.assert_gl(pe, {"6999": -54.05})
    ctx.assert_plausibilite_ok()


def scenario_reevaluation_change_latent(ctx):
    """
    SCÉNARIO : Réévaluation de change des postes ouverts en devise (change LATENT) au bouclement
    DÉCISION §11 : une créance/dette en devise ENCORE OUVERTE à la clôture est valorisée au cours de
                   clôture (CO 958c/960a) ; l'écart NON RÉALISÉ → 6998 (unrealized_exchange_gain_loss_
                   account), distinct du réalisé (6999). AUCUN impact TVA (change purement financier).
    POURQUOI : une dette EUR non payée change de valeur CHF quand le cours bouge ; le bilan doit
               l'afficher au cours de clôture, et le gain/perte latent passe au résultat.
    OPÉRATIONS : 1) facture d'achat 10 000 EUR, taux facture 0.95 → dette de 9 500 CHF sur 2001 ;
                 2) réévaluation au cours de clôture 0.93 → dette = 9 300 CHF.
    CHANGE : la dette baisse de 9 500 → 9 300 CHF (on doit moins en CHF) → GAIN LATENT de 200 CHF =
             CRÉDIT sur 6998 ; le tiers (2001) est revalorisé à -9 300 CHF au bilan.
             Dérivé (non tuné) : 10 000 EUR × (0.95 − 0.93) = 200 CHF.
    DÉCISIONS §11 : réévaluation de change (change latent) ; compte 6998 ; contre-passation période +1.
    """
    ctx.make_purchase_invoice("SCEN Fournisseur EUR", 10000, currency="EUR",
                              conversion_rate=0.95, credit_to="2001")
    # dette EUR inscrite à 9 500 CHF (taux facture 0.95) avant réévaluation
    ctx.assert_balance("2001", -9500)
    # réévaluation au cours de clôture 0.93
    jv = ctx.make_exchange_revaluation("2026-12-31", {"EUR": 0.93})
    # BILAN : dette 2001 revalorisée à sa valeur de clôture (-9 300 CHF)
    ctx.assert_balance("2001", -9300)
    # RÉSULTAT : gain LATENT de 200 CHF = CRÉDIT sur 6998
    ctx.assert_balance("6998", -200)
    # écriture de réévaluation : crédite 6998 de 200 (gain) et débite 2001 de 200 (dette réduite)
    ctx.assert_gl(jv, {"6998": -200, "2001": 200})


def scenario_paiement_avec_escompte(ctx):
    """
    SCÉNARIO : Paiement d'une facture de VENTE avec escompte accordé (Skonto)
    DÉCISION §15 #3 : un escompte est une DIMINUTION de la contre-prestation → il réduit la base
                      (case 235) ET reprend la TVA proportionnelle.
    POURQUOI : vérifier que l'escompte accordé est traité correctement au sens TVA suisse.
    OPÉRATIONS : 1) vente 1 000 net (NC81) + escompte 10% dans 30 j (Payment Terms) → total 1 081 ;
                 2) encaissement dans le délai → ERPNext applique l'escompte natif (108.10 = net 100 + TVA 8.10).
    MÉCANIQUE : flag `book_tax_discount_loss` (Accounts Settings) → ventilation native : part nette → 3800,
                reprise TVA → 2200. La case 235 est alimentée par l'extension `viewVAT_235` (escomptes des
                paiements de vente). La TVA du décompte suit (dérivée = base × taux).
    ATTENDU :
      - GL : part nette 100 → 3800, reprise TVA 8.10 → 2200 ; solde net 2200 = −72.90 (81 − 8.10) ;
      - case 235 = 100 (diminution) → base imposable nette 900 → TVA décompte 72.90 = GL (plausibilité OK).
    """
    from erpnextswiss.swiss_vat_config.tests.helpers import _escompte_terms
    si = ctx.make_sales_invoice("SCEN Client CH", net=1000, tax_template="NC81",
                                payment_terms_template=_escompte_terms())   # escompte 10% dans 30 j
    pe = ctx.make_payment("Sales Invoice", si.name)   # payé dans le délai → escompte natif appliqué
    ctx.assert_gl(pe, {"3800": 100, "2200": 8.10})     # escompte net 100 + reprise TVA 8.10
    ctx.assert_balance("2200", -72.90)                 # TVA nette après reprise (81 − 8.10)
    ctx.assert_vat(base={"235": 100})                  # diminution de contre-prestation alimentée
    ctx.assert_plausibilite_ok()


def scenario_paiement_achat_escompte(ctx):
    """
    SCÉNARIO : Paiement d'une facture d'ACHAT avec escompte obtenu (miroir de la vente)
    DÉCISION §15 #3 : un escompte obtenu réduit la contre-prestation → il DIMINUE l'impôt préalable
                      (case 400/405) ; le net réduit la charge (4900 « escomptes obtenus »).
    POURQUOI : vérifier la symétrie côté achat (reprise d'impôt préalable au sens TVA suisse).
    OPÉRATIONS : 1) achat 1 000 net (IPM81 8.1%, case 400) + escompte 10% dans 30 j → total 1 081,
                    impôt préalable 81 sur 1170 ; 2) paiement dans le délai → escompte natif
                    (108.10 = net 100 + TVA 8.10).
    MÉCANIQUE : ventilation native → part nette → 4900 (routée depuis 3800 par le hook achat),
                reprise impôt préalable → 1170. L'extension `viewVAT_400` soustrait la reprise
                d'impôt préalable des escomptes d'achat → case 400 nette.
    ATTENDU :
      - GL : reprise impôt préalable 8.10 → crédit 1170 ; net 100 → crédit 4900 ;
      - case 400 = 72.90 (81 − 8.10) ; solde 1170 = 72.90 (impôt préalable net réellement déductible).
    """
    from erpnextswiss.swiss_vat_config.tests.helpers import _escompte_terms
    pi = ctx.make_purchase_invoice("SCEN Fournisseur CH", net=1000, tax_template="IPM81",
                                   payment_terms_template=_escompte_terms())
    pe = ctx.make_payment("Purchase Invoice", pi.name)   # payé dans le délai → escompte natif
    ctx.assert_gl(pe, {"1170": -8.10, "4900": -100})     # reprise impôt préalable + net escompte obtenu
    ctx.assert_balance("1170", 72.90)                    # impôt préalable net (81 − 8.10)
    ctx.assert_vat(tax={"400": 72.90})                   # case 400 nette de l'escompte
    ctx.assert_plausibilite_ok()


def scenario_lot_mixte_escomptes(ctx):
    """
    SCÉNARIO D'INTÉGRATION : lot d'opérations mixtes (ventes/achats, avec et sans escompte)
    DÉCISION §15 #3 : vérifier que sur un VOLUME d'opérations mêlant escomptes et ventes/achats
                      normaux, les AGRÉGATS (GL, cases TVA, plausibilité) restent justes de bout en bout.
    POURQUOI : les scénarios unitaires valident chaque cas ; celui-ci valide qu'ils se CUMULENT
               correctement (pas d'interférence entre escomptes, normaux, vente et achat).
    OPÉRATIONS (toutes à 8.1% ; escompte = 10% via Payment Terms, payé dans le délai) :
      Ventes  : S1 2000 normale · S2 1000 + escompte · S3 1500 + escompte   (client CH)
      Achats  : P1 800 normal   · P2 1000 + escompte · P3 500 + escompte    (fournisseur CH)
      Les 6 factures sont PAYÉES (normales : plein ; escompte : ventilation native + reprise TVA).
    AGRÉGATS ATTENDUS (dérivés à la main, cumul période) :
      - Produits 3000 = 4500 (2000+1000+1500) · Charges 4200 = 2300 (800+1000+500)
      - TVA vente 2200 = 344.25 = 162 + (81−8.10) + (121.50−12.15)
      - Impôt préalable 1170 = 174.15 = 64.80 + (81−8.10) + (40.50−4.05)
      - Escomptes accordés 3800 = 250 (100+150) · obtenus 4900 = 150 (100+50)
      - Décompte : case 303 = 4500 (base brute) · case 235 = 250 (diminutions) · case 400 = 174.15
    PLAUSIBILITÉ : C1 = (4500−250)×8.1% = 344.25 = 2200 ✓ ; C2 : mouvement 1170 = case 400 = 174.15 ✓.
    """
    from erpnextswiss.swiss_vat_config.tests.helpers import _escompte_terms
    esc = _escompte_terms()
    CLI, FRN = "SCEN Client CH", "SCEN Fournisseur CH"

    # --- Ventes ---
    s1 = ctx.make_sales_invoice(CLI, net=2000, tax_template="NC81")                              # normale
    ctx.make_payment("Sales Invoice", s1.name)                                                   # payée plein
    s2 = ctx.make_sales_invoice(CLI, net=1000, tax_template="NC81", payment_terms_template=esc)  # + escompte
    ctx.make_payment("Sales Invoice", s2.name)
    s3 = ctx.make_sales_invoice(CLI, net=1500, tax_template="NC81", payment_terms_template=esc)  # + escompte
    ctx.make_payment("Sales Invoice", s3.name)

    # --- Achats ---
    p1 = ctx.make_purchase_invoice(FRN, net=800, tax_template="IPM81")                            # normal
    ctx.make_payment("Purchase Invoice", p1.name)                                                 # payé plein
    p2 = ctx.make_purchase_invoice(FRN, net=1000, tax_template="IPM81", payment_terms_template=esc)
    ctx.make_payment("Purchase Invoice", p2.name)
    p3 = ctx.make_purchase_invoice(FRN, net=500, tax_template="IPM81", payment_terms_template=esc)
    ctx.make_payment("Purchase Invoice", p3.name)

    # --- Agrégats (soldes cumulés sur la période) ---
    ctx.assert_balance("3000", -4500)      # produits (crédit)
    ctx.assert_balance("4200", 2300)       # charges (débit)
    ctx.assert_balance("2200", -344.25)    # TVA due nette
    ctx.assert_balance("1170", 174.15)     # impôt préalable net (débit)
    ctx.assert_balance("3800", 250)        # escomptes accordés (débit)
    ctx.assert_balance("4900", -150)       # escomptes obtenus (crédit)
    # --- Décompte ---
    ctx.assert_vat(base={"303": 4500, "235": 250})   # base brute + diminutions
    ctx.assert_vat(tax={"400": 174.15})              # impôt préalable net
    ctx.assert_plausibilite_ok()
