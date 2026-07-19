# Configuration comptable & TVA suisse (bexio) pour ERPNext 16 — Stratégie

> Ce document résume **toute la stratégie** appliquée pour configurer une Company ERPNext 16 en
> conformité comptable/TVA suisse, avec un plan comptable et des codes TVA **inspirés de bexio**.
> Il couvre : plan comptable, templates TVA (nomenclature bexio), **mapping des cases du décompte
> TVA (architecture AFC VAT Box)**, reverse charge, change, acomptes, escomptes, et le chantier
> **décompte TVA** (via l'app ERPNextSwiss forkée — divergences tracées dans `FORK_CHANGES.md` à la racine du fork erpnextswiss).
>
> ✅ **Point d'entrée unique** : toute la configuration vit dans l'app Frappe **`erpnextswiss`**
> — `company_setup.setup_company(company)`. Les codes TVA sont nommés **exactement comme bexio**
> (ex. `NC81 - Chiffre d'affaires (TN) 8.10%`), et la case du décompte est portée par un **champ de
> données** (`afc_box`) **sur la ligne de taxe** (le compte servant de défaut/ancre), plus par le nom.
> Le setup est **idempotent** (relançable sans doublon) mais **n'auto-crée pas** la société (`create_company`
> pour ça) et **ne supprime pas** d'éventuels templates créés par un autre script.

---

## Table des matières

1. [Architecture & fichiers](#1-architecture--fichiers)
2. [Données source (bexio)](#2-données-source-bexio)
3. [Les 3 types de templates ERPNext](#3-les-3-types-de-templates-erpnext)
4. [Le problème : les templates par défaut d'ERPNext](#4-le-problème--les-templates-par-défaut-derpnext)
5. [Ce que fait `setup_company`](#5-ce-que-fait-setup_company)
6. [Nomenclature & mapping bexio complet](#6-nomenclature--mapping-bexio-complet)
7. [Architecture AFC VAT Box (mapping des cases, data-driven)](#7-architecture-afc-vat-box-mapping-des-cases-data-driven)
8. [Reverse charge : impôt sur les acquisitions](#8-reverse-charge--impôt-sur-les-acquisitions)
9. [TVA à l'import (douane)](#9-tva-à-limport-douane)
10. [Comptes techniques du décompte (2201, 1172, 2202)](#10-comptes-techniques-du-décompte-2201-1172-2202)
11. [Décisions comptes : change, acomptes, escomptes](#11-décisions-comptes--change-acomptes-escomptes)
12. [Comment appliquer](#12-comment-appliquer)
13. [Le décompte TVA (ERPNextSwiss + VAT query)](#13-le-décompte-tva-erpnextswiss--vat-query)
14. [Points ouverts / à faire](#14-points-ouverts--à-faire)
15. [Points de validation avec le fiduciaire ⚠️](#15-points-de-validation-avec-le-fiduciaire-)
16. [Saisir une facture d'achat (net, TTC, ajustement TVA)](#16-saisir-une-facture-dachat-net-ttc-ajustement-tva)
17. [Compte banque CHF unique & modes de paiement](#17-compte-banque-chf-unique--modes-de-paiement)
18. [Paramétrage manuel requis (après le setup)](#18-paramétrage-manuel-requis-après-le-setup)
19. [Gestion des salaires (paie externe → comptabilisation ERPNext)](#19-gestion-des-salaires-paie-externe--comptabilisation-erpnext)
20. [Gestion de la clôture (bouclement)](#20-gestion-de-la-clôture-bouclement)
21. [Gestion des stocks — inventaire perpétuel (négoce)](#21-gestion-des-stocks--inventaire-perpétuel-négoce)
20. [Gestion de la clôture (bouclement)](#20-gestion-de-la-clôture-bouclement)

---

## 1. Architecture & fichiers

Toute la configuration vit dans **l'app `erpnextswiss`** (module « Swiss VAT Config »).

| Élément                                       | Rôle                                                                                                                               |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **`erpnextswiss/swiss_vat_config/company_setup.py`** | **Point d'entrée** : `setup_company(company)` — tout le setup comptable/TVA                                                        |
| `erpnextswiss/swiss_vat_config/vat_setup.py`         | Doctype `AFC VAT Box` (seed des cases), custom fields `afc_box` / `afc_box_secondary`, hooks after_install/after_migrate, fixtures |
| doctype **`AFC VAT Box`**                     | Référentiel des cases du décompte AFC (200, 303, 400…) — voir §7                                                                   |
| `generate_coa.py` (documentation)             | Génère le plan comptable JSON depuis l'export bexio                                                                                |
| `ch_pme_fr.json`                              | Plan comptable ERPNext (à déposer dans `erpnext/.../verified/`)                                                                    |
| `bexio-tax-rates.xlsx`                        | Export bexio **avec la colonne « Code TVA »** (NC81, IPM81…) — source des noms                                                     |

**Prérequis** : le **plan comptable bexio** doit être importé (comptes 1170/1171/2200/2203/6945/
6999/4800/2030/1130 présents) **et** l'app `erpnextswiss` installée (doctype AFC VAT Box +
champs seedés).

---

## 2. Données source (bexio)

`bexio-tax-rates.xlsx` contient **26 codes TVA** (13 actifs, 13 inactifs). Colonnes clés :

| Colonne bexio | Signification                                                                          |
| ------------- | -------------------------------------------------------------------------------------- |
| **Code TVA**  | le code bexio (ex. `NC81`, `IPM81`, `IAM81`, `DOUAM`) → **préfixe du nom du template** |
| Description   | libellé (ex. « Chiffre d'affaires (TN) », « Mat./Ser. (TN) »)                          |
| Chiffre       | **case du décompte AFC** (303, 400, 205.303, 383…) → alimente `afc_box`                |
| Compte        | compte de TVA (1170 / 1171 / 1173 / 1174 / 2200)                                       |
| Actif         | Oui/Non → template `disabled = 0/1`                                                    |

Taux : **8.1 %** (TN), **2.6 %** (TR), **3.8 %** (TS/hébergement), **0 %**, **100 %** (douane).

**Règle clé** : chaque code bexio ne cite **qu'un compte**, sauf l'impôt sur acquisitions
(`IAM81`/`IACE81`) qui implique **2203** en plus (reverse charge, §8).

---

## 3. Les 3 types de templates ERPNext

| Template                                | S'applique sur         | Rôle                                                                        | Niveau       |
| --------------------------------------- | ---------------------- | --------------------------------------------------------------------------- | ------------ |
| **Sales Taxes and Charges Template**    | Documents de **vente** | Lignes de taxe du document (TVA due → 2200)                                 | **Document** |
| **Purchase Taxes and Charges Template** | Documents d'**achat**  | Impôt préalable → 1170/1171 ; gère `Add/Deduct`                             | **Document** |
| **Item Tax Template**                   | Un **article** / ligne | **Surcharge le taux** pour cet article (le « code » par ligne, façon bexio) | **Ligne**    |

Sur une facture : le template Sales/Purchase (document) fixe les comptes ; l'Item Tax Template
**écrase le taux par ligne** → gère les factures **multi-taux**. C'est le pendant ERPNext du « code
TVA par ligne » de bexio.

---

## 4. Le problème : les templates par défaut d'ERPNext

À la création d'une Company (pays = Switzerland), ERPNext crée **9 templates par défaut** (3 Sales +
3 Purchase + 3 Item) **+ des comptes génériques « VAT 8.1% »** sous « Duties and Taxes ». Défauts :

1. **Comptes génériques** (pas 1170/2200) → plan pollué.
2. **Même compte vente ET achat** (or 1170 ≠ 2200 en Suisse).
3. **Incomplet** (pas de 0 %, matériel/investissement, import, reverse charge).

→ Stratégie **« clean slate »** : supprimer ces défauts et recréer proprement (`cleanup_defaults`).
Garde-fou : un compte avec écritures est **désactivé** (pas supprimé).

---

## 5. Ce que fait `setup_company`

`erpnextswiss.swiss_vat_config.company_setup.setup_company(company)` exécute :

1. **Nettoyage** des 9 templates + comptes génériques ERPNext.
2. **11 Sales Templates** (compte 2200) — noms bexio + `afc_box` (+ `afc_box_secondary`) **posés sur la ligne de taxe** à la création.
3. **13 Purchase Templates** simples (1170/1171/1173/1174, imports douane en `Actual`) — `afc_box` **sur la ligne** (dont **DUIP → 410**).
4. **2 Purchase reverse charge** à double ligne (Add 1170/1171 → 400/405 + Deduct 2203 → 383, `afc_box` par ligne) — §8.
5. **9 Item Tax Templates** (codes ventes = classification ligne, avec `afc_box`).
6. **Tag des comptes** (`afc_box` = **défaut / ancre de réconciliation**) : 1170→400, 1171→405, 1173→420, 1174→415, **2203→383**.
7. **Défauts Company** : Round Off 6945, Exchange 6999, Stock Adjustment 4800, Payment Discount 3800,
   **débiteur 1100 / créancier 2000** (épinglés — sinon 2030 est choisi par erreur, cf. §11).
8. **Accounts Settings (global)** : `book_tax_discount_loss = 1` — ventilation TVA des escomptes (§11/§15 #3).
9. **Comptes multi-devises EUR** : 1101 (créances) / 2001 (dettes). **Pas de banque EUR** par défaut — la société paie/encaisse l'EUR via son compte CHF (1020) ; ajouter 1021 uniquement si elle détient un compte bancaire EUR.
10. **Compte de change latent** : crée **6998 « Différences de change non réalisées »** (frère de 6999) et le pose comme `unrealized_exchange_gain_loss_account` — requis par l'outil _Exchange Rate Revaluation_ (§11).
11. **Banque CHF unique** : renomme 1020 → **« Banque CHF »** si besoin (migration d'une société née de l'ancien chart ; le chart corrigé ne crée plus qu'un compte banque CHF, sans 1029) (§17).
12. **Modes de paiement** : traduits en FR, seuls **Carte de crédit** + **Virement bancaire** actifs, mappés sur **1020** (§17).
13. **Désactive 6949** (Option A change, §11).
14. **Acomptes** : type 2030 Receivable / 1130 Payable + « Book Advance in Separate Party Account ».
15. `commit()`.

**Runtime** : un hook sur `Payment Entry` (`escompte.route_purchase_discount_to_4900`) route la part
nette d'un escompte **obtenu** (achat) de 3800 vers **4900** — présentation P&L (§11).

**Total : 11 sales + 15 purchase (dont 2 reverse charge) + 9 item.** Inactifs bexio créés puis
`disabled = 1` (réactivables). **Idempotent** (skip par titre ; reverse charge recréé).

---

## 6. Nomenclature & mapping bexio complet

**Format des noms** : `{CODE} - {Description} {taux}%` (ex. `NC81 - Chiffre d'affaires (TN) 8.10%`),
repris **exactement** de la colonne « Code TVA » de l'export bexio.

**VENTES (compte 2200) :**
| Code | Description | Taux | Case (afc_box) | Actif |
|---|---|---|---|---|
| **NC81** | Chiffre d'affaires (TN) | 8.10% | 303 | ✅ (défaut) |
| **CR26** | Chiffre d'affaires (TR) | 2.60% | 313 | ✅ |
| **CS38** | Chiffre d'affaires (TS) | 3.80% | 343 | — |
| **PO81** | Imposition d'opération par option | 8.10% | 303 **+ 205** (secondaire) | — |
| **C00** | Sans TVA | 0% | — | — |
| **CEX** | Exportation / Exonéré | 0% | 220 | ✅ |
| **CSE** | Prestations fournies à l'étranger | 0% | 221 | — |
| **ANN** | Transfert (procédure d'annonce) | 0% | 225 | — |
| **OEX** | Opérations exclues | 0% | 230 | — |
| **SUB** | Subventions, taxes de séjour | 0% | 900 | — |
| **DON** | Dons, dividendes, rémunérations | 0% | 910 | — |

**ACHATS (case portée par la LIGNE de taxe — le compte reste le défaut/ancre) :**
| Code | Description | Taux | Case | Compte | Actif |
|---|---|---|---|---|---|
| **IPM81** | Mat./Ser. (TN) | 8.10% | 400 | 1170 | ✅ (défaut) |
| **IPM26** | Mat./Ser. (TR) | 2.60% | 400 | 1170 | ✅ |
| **IPM38** | Mat./Ser. (TS) | 3.80% | 400 | 1170 | — |
| **IPIM** | Importation | 0% | 400 | 1170 | ✅ |
| **DOUAM** | Entrée mat./ser. (douane) | 100% | 400 | 1170 | ✅ (Actual) |
| **IPCE81** | Inv./CE (TN) | 8.10% | 405 | 1171 | ✅ |
| **IPCE26** | Inv./CE (TR) | 2.60% | 405 | 1171 | ✅ |
| **IPCE38** | Inv./CE (TS) | 3.80% | 405 | 1171 | — |
| **IP00** | Sans TVA | 0% | 000 | 1171 | ✅ |
| **DOUACE** | Entrée inv./CE (douane) | 100% | 405 | 1171 | ✅ (Actual) |
| **IAM81** | Impôt sur les acquisitions Mat./Ser. | 8.10% | 383 | 1170 (+2203) | ✅ (reverse) |
| **IACE81** | Impôt sur les acquisitions Inv./CE | 8.10% | 383 | 1171 (+2203) | ✅ (reverse) |
| **DUIP** | Déduction ultérieure impôt préalable | 8.10% | 410 | 1170 | — |
| **RIP** | Réductions de l'impôt préalable | 8.10% | 420 | 1173 | — |
| **IPPS** | Correction prestation à soi-même | 8.10% | 415 | 1174 | — |

Les **Item Tax Templates** reprennent les **codes ventes** (NC81, CR26, CS38, PO81, CEX, CSE, ANN,
OEX, C00) avec leur `afc_box` — c'est le « code par ligne ».

---

## 7. Architecture AFC VAT Box (mapping des cases, data-driven)

**La décision structurante récente.** La case du décompte n'est **plus** encodée dans le nom du
template ni déduite du taux en dur : elle est **une donnée**, portée par des champs, lue par des
queries génériques. Objectif : **tout configurable dans l'UI, sans toucher au code ni au SQL**,
résilient au renommage / aux nouveaux comptes/templates / au changement de plan comptable.

> **⚑ Évolution structurante (la case est portée par la LIGNE de taxe).** À l'origine, l'achat lisait
> la case **sur le compte** et la vente sur le **header du template**. Désormais la case vit **sur la
> ligne de taxe** (child _Sales / Purchase Taxes and Charges_), copiée du template vers la facture ;
> le **compte** ne sert plus que de **défaut** et d'**ancre de réconciliation**. Résolution unique :
> **`COALESCE(afc_box de la ligne, afc_box du compte)`**.

### Les briques

| Élément                                                        | Rôle                                                                                                                                                |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Doctype **`AFC VAT Box`**                                      | Référentiel des cases (box_code, label, part, side, amount_type, computation, rate, eCH-0217 id…). Seedé : 23 cases (200, 220, 299, 303, 400, 500…) |
| Champ **`afc_box`** sur **Item Tax Template** (header)         | case **par article** (vente) — le « code » bexio                                                                                                    |
| Champ **`afc_box`** sur **Sales Taxes and Charges** (ligne)    | case **fallback vente** (lignes sans Item Tax Template) — **portée par la ligne**, copiée du template vers la facture                               |
| Champ **`afc_box`** sur **Purchase Taxes and Charges** (ligne) | case **achat** — **prime** sur le compte (override). Permet à un compte de se **splitter** (ex. 1170 = 400 **et** 410)                              |
| Champ **`afc_box`** sur **Account**                            | case **par défaut** achat (1170→400, 1171→405…) **+ ancre de la réconciliation** de plausibilité                                                    |
| Champ **`afc_box_secondary`** (vente)                          | **double appartenance** (ex. opté PO81 → primaire 303 + secondaire 205)                                                                             |

### La règle de résolution (par les queries)

| Type de case                                                       | Discriminant (COALESCE)                                                            | Où vit le mapping                  |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ---------------------------------- |
| **Ventes** (200, 220, 221, 225, 230, 303, 313, 343, 205, 900, 910) | `afc_box` de l'**article** (Item Tax Template), sinon de la **ligne de taxe 2200** | article + ligne de taxe            |
| **Achats** (400, 405, 415, 420, 383, **410**)                      | `afc_box` de la **ligne de taxe**, sinon du **compte**                             | ligne (override) + compte (défaut) |
| **Cases calculées** (299, 399, 479, 500/510)                       | formule dans le décompte                                                           | doctype AFC VAT Box                |

→ Aucun **nom de template**, **numéro de compte** ou **taux** en dur dans les queries : tout par
**`COALESCE(afc_box de la ligne, afc_box du compte)`**. Un nouveau template/compte ? On lui met son
`afc_box`, il est compté automatiquement.

### Pourquoi la ligne, et plus seulement le compte (le cas 410)

Avec la case **sur le compte**, un compte = **une seule** case. Or **1170** doit alimenter **400**
(impôt préalable normal) **ET 410** (dégrèvement ultérieur, art. 32 — code `DUIP`) : impossible au
niveau compte. En portant la case **sur la ligne**, la ligne `DUIP` sur 1170 porte **410** tandis que
`IPM81` sur 1170 porte **400** → le **même compte se splitte** proprement. Le `COALESCE(ligne, compte)`
garde le compte comme **défaut** (95 % des lignes) et n'exige un `afc_box` de ligne **que pour
l'exception** (DUIP → 410). Le reverse charge en bénéficie aussi : ligne 1171 → **405**, ligne 2203 → **383**.

### Réconciliation (plausibilité) adaptée

Comme un compte peut alimenter **plusieurs** cases (1170 = 400 + 410), le **contrôle 1** de plausibilité
réconcilie chaque compte contre **la somme des cases** que ses lignes résolvent (« compte 1170 →
case(s) 400, 410 »), au lieu de « 1 compte = 1 case ».

### Migration des sociétés existantes

`erpnextswiss.swiss_vat_config.company_setup.migrate_afc_to_lines(company)` reporte l'`afc_box` sur les
**lignes** des templates déjà créés (header vente → ligne 2200 ; compte achat → ligne, + `DUIP → 410`).
Les **nouvelles** sociétés ont la case sur les lignes **dès la création** (`setup_company`).

### Le cas des 0 % (pourquoi `afc_box` est indispensable)

Les cases **220/221/225/230** ont **toutes le taux 0** → le taux ne les distingue pas. Seul `afc_box`
le fait. D'où les **codes 0 % par catégorie** (CEX/CSE/ANN/OEX) au **niveau ligne** (Item Tax
Template), pour ventiler correctement les **factures multi-catégories**.

### Le cas de l'opté 205.303 (double appartenance)

Une prestation optée (PO81) est **à la fois** taxable (303) **et** déclarée en mémo opté (205). Le
champ **`afc_box_secondary`** porte la 2ᵉ case → PO81 = `afc_box=303` + `afc_box_secondary=205`. Les
queries somment sur `afc_box OR afc_box_secondary`. C'est l'équivalent exact du `digit 205.303` de
bexio.

---

## 8. Reverse charge : impôt sur les acquisitions

Autoliquidation (_Bezugsteuer_, art. 45 LTVA) : pour des **prestations reçues de fournisseurs
étrangers sans TVA suisse**, l'acheteur déclare **et** déduit la TVA (seuil > 10 000 CHF/an).

**Double écriture** (conseil 1 000 CHF, 8.1 %) :

```
Dr Charge 1 000 · Dr Impôt préalable (1170/1171) 81
   Cr Fournisseur 1 000 · Cr Impôt sur acquisitions (2203) 81
```

Trésorerie nulle, mais **les deux montants** au décompte (**383** dû + 400/405 déduit).

> **382 vs 383** : la case des acquisitions est **dédoublée** depuis le changement de taux 2024 —
> **383** = taux actuels (ce que la société utilise), **382** = anciens taux (≤ 2023, corrections).
> On tague donc 2203 → **383** (conforme à bexio + au formulaire officiel AFC).

**Solution ERPNext** — template Purchase à **2 lignes** (codes `IAM81`/`IACE81`), chaque ligne portant
sa case (`afc_box`) :
| Ligne | Compte | Add/Deduct | afc_box (ligne) |
|---|---|---|---|
| 1 | 1170 (ou 1171) | **Add** | 400 (ou 405) — déduit |
| 2 | 2203 | **Deduct** | 383 — dû |

→ Un **seul** template alimente **deux** cases (405 **et** 383), ce que seule la case **par ligne**
permet (le compte, lui, ne pouvait en porter qu'une). C'est l'un des cas qui justifient le passage
de la case du compte à la ligne (§7).

→ Total facture inchangé, GL `Dr 1170/1171 / Cr 2203`. À **sélectionner manuellement** sur les
factures d'achat étrangères. Compte de dû **2203** à valider avec le fiduciaire.

---

## 9. TVA à l'import (douane)

La TVA import est perçue par la **douane** sur la valeur douanière (pas la facture fournisseur),
**récupérable** (1170/1171), saisie **en montant** (décision douanière). Dans bexio : codes `DOUAM`/
`DOUACE` (value 100). Dans ERPNext : ligne **`charge_type = Actual`** (montant saisi). Les droits de
douane (non récupérables) → valeur stock / charge.

---

## 10. Comptes techniques du décompte (2201, 1172, 2202)

Trois comptes système bexio ne sont **ni** des comptes de transaction **ni** portés par un template :

- **2201 « Décompte TVA »** — compte de **règlement périodique**. En fin de période, on **solde** 2200
  (TVA due) et 1170/1171 (préalable) vers 2201 (= dette nette AFC), puis on paie l'AFC depuis 2201.
  Dans ERPNext : **Journal Entry manuel** (pas de décompte natif). Nécessaire, s'active avec §13.
- **1172 / 2202** — réconciliation lors d'un **changement de méthode TVA** (rare). **Dormants** tant
  que la méthode ne change pas (COMPANY = méthode effective).

Rien à configurer aujourd'hui ; schéma exact du décompte à confirmer avec le fiduciaire.

---

## 11. Décisions comptes : change, acomptes, escomptes

### Change — désactivation de 6949 (Option A)

bexio a 6999 (gains) **et** 6949 (pertes). ERPNext n'a **qu'un** `exchange_gain_loss_account` → tout
sur **6999**, **6949 désactivé**. Impact comptable **nul** (résultat/bilan identiques ; présentation
CO 959b nette). Réversible. Mise en œuvre : `disable_unused_accounts` (le chart `verified/` ne peut
pas porter `disabled`, documenté dans `generate_coa.py`).

### Change — gain/perte **réalisé** vs **latent** (arbitrage)

Quand une facture en EUR est encaissée à un **cours différent** de celui de la facture, l'écart de
change peut être traité de **deux façons légitimes**. ERPNext (comme la pratique comptable) distingue
selon **où atterrit l'encaissement** :

| Cas         | Flux                                                                   | Traitement                                                     | Écriture au règlement                                                                                                                                                                    |
| ----------- | ---------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Réalisé** | encaissement **converti en CHF** (banque CHF)                          | l'écart est **matérialisé** en CHF → gain/perte **réalisé**    | la créance EUR se solde à sa **valeur comptable** (cours facture), la banque reçoit les CHF réellement convertis (cours du jour), le **bouclon → 6999**                                  |
| **Latent**  | encaissement **sur une banque en devise** (les EUR **restent** en EUR) | rien n'est converti → **aucun** gain/perte réalisé au paiement | la créance EUR se solde en EUR (solde EUR = 0) ; l'écart reste **latent** en CHF sur le compte, **repris par la réévaluation de change** (_Exchange Rate Revaluation_) en fin de période |

**Mécanique ERPNext** (vérifiée en source, `payment_entry.py`) : le montant posté sur 6999 = `base_paid_amount − base_received_amount`. Il n'est **non nul que si les deux côtés du paiement diffèrent en CHF** — c'est-à-dire quand on **convertit** vers le CHF. Vers une banque en devise, les deux côtés sont en EUR au même cours → **écart nul au paiement**, le gain/perte est **différé** à la réévaluation.

**Ce qu'on applique aujourd'hui** : traitement **réalisé à l'encaissement** — l'écart de change tombe sur **6999 dès le paiement** (modèle « la banque encaisse en CHF »). C'est le choix par défaut et le plus simple à lire pour la fiduciaire (le résultat de change apparaît à la date de règlement, pas au bouclement). Un **compte banque EUR (ex. 1021, non créé par défaut)** peut être ajouté si le client choisit de **garder des liquidités en EUR** ; dans ce cas le gain devient **latent** et il faudra **planifier une réévaluation de change périodique** (mensuelle/trimestrielle/au bouclement). → **Décision fiduciaire §15 #12** : réalise-t-on le change à chaque encaissement (conversion CHF) ou tient-on des soldes en devise avec réévaluation périodique ? Impact **présentation/périodicité** du résultat de change, **pas** sur le résultat total de l'exercice.

### Change — réévaluation des postes ouverts au bouclement (change latent, compte 6998)

Toute **créance / dette / banque en devise encore ouverte** à la clôture doit être valorisée au **cours de clôture** (CO art. 958c/960a), pas au cours de la facture. L'écart = **gain/perte de change LATENT** (aucun cash bougé). ERPNext le fait via l'outil natif **_Exchange Rate Revaluation_**.

- **Compte requis** : ERPNext utilise un **second** compte, distinct du réalisé — `Company.unrealized_exchange_gain_loss_account`. Sans lui, l'outil **refuse de tourner** (`frappe.throw`). Le setup crée et pose **`6998 « Différences de change non réalisées »`** (frère de 6999, sous _Produits financiers_) — cf. `setup_fx_revaluation_account`. On **ne réutilise pas** 6949 (qui reste le « Pertes de change » standard désactivé).
- **Pourquoi un compte séparé (6999 réalisé / 6998 latent)** : sous le CO, valoriser au cours de clôture fait que les **gains latents augmentent le bénéfice** (donc l'impôt) alors que rien n'est encaissé. Les isoler sur 6998 permet de les **repérer et neutraliser** par une **réserve latente** (prudence). Le client (ProConcept) a d'ailleurs un compte de réévaluation dédié (`200009`).
- **Écriture** (validée en test) : l'outil réajuste chaque solde tiers/banque en devise à sa valeur CHF de clôture (**bilan**) et poste le **net** du gain/perte latent sur **6998** (**résultat**). Ex. dette 10'000 EUR bookée à 0.95 (9'500 CHF), cours de clôture 0.93 → dette 9'300 CHF → **gain latent 200 CHF** au crédit de 6998.
- **Contre-passation** : on **contre-passe** l'écriture au 1er de la période suivante (on repart de la valeur d'origine) ; le vrai écart se fige au paiement (**réalisé → 6999**). Évite le double comptage.
- **Aucune case AFC** sur 6998 (ni 6999) : le change est **purement financier**, **zéro impact TVA** (TVA figée au cours facture, contre-prestations convenues, §15 #8).

#### Cours de clôture ≠ cours mensuel — et pourquoi on ne le **stocke pas**
- Le cours de clôture est le **cours du jour au 31.12** (AFC/BAZG `xmldaily`), **différent** du **cours moyen mensuel** (`xmlavgmonth`) qui sert aux transactions. C'est un **taux distinct**, pas le dernier mensuel.
- ⚠️ **Ne pas** créer de `Currency Exchange` au 31.12 : sinon `get_exchange_rate` le prendrait pour **toute facture datée du 31.12**, au lieu du **moyen de décembre** → incohérence (méthode « cours moyen mensuel » AFC). Le cours de clôture ne doit exister **que dans le formulaire de réévaluation**.
- **Procédure pas-à-pas** (créer la réévaluation, appliquer le cours de clôture, générer et soumettre l'écriture, contre-passer) : voir **§20 — Gestion de la clôture**.

### Change — récupération des cours AFC (cours mensuels, fréquence, réglages)

Les taux qui servent à convertir les factures en devise (et donc à alimenter le **décompte TVA**)
doivent provenir des **cours officiels de l'AFC**, pas d'un cours de marché ou BCE
(art. 45 OTVA ; Info TVA 07/16). La récupération est industrialisée par l'app **`erpnextswiss`**
(doctype **Swiss Exchange Rate Settings** + logs) ; `setup_company` pose de son côté les deux réglages
ERPNext qui garantissent que ces cours sont réellement utilisés.

**D'où viennent les cours.** Flux XML officiels BAZG/OFDF :
`…/api/xmlavgmonth` (cours **mensuel moyen**, recommandé) ou `…/api/xmldaily` (cours du jour, devises
vente). Sens écrit : **devise → CHF** (+ **CHF → devise**). Devises par défaut : EUR, USD, GBP.

**Datation = 1er du mois.** Le cours mensuel est daté au **1er du mois** (`<monat>` du flux, ex.
`2026-07-01`), pas à la date d'exécution. Combiné au lookup d'ERPNext (le cours le plus récent avec
`date <= date_facture`), un cours mensuel **couvre tout le mois**. Le cours de juillet est publié par
l'AFC le **25 juin** et est **définitif dès le 1er** → aucun cours provisoire.

**Fréquence.** Le job tourne **chaque jour** (`hooks.scheduler_events["daily"]`) avec une porte :
`Enabled` faux → rien ; `Daily` → exécute ; `Weekly`/`Monthly` → seulement le jour configuré.
Import **idempotent** : on n'écrit que les cours **absents**, on **n'écrase jamais** un cours existant
(donc **on ne supprime jamais** l'historique — nécessaire pour les factures rétro-datées, notes de
crédit et l'auditabilité AFC). Configuration + suivi : **ERPNextSwiss → Configuration → Swiss Exchange
Rate Settings** (bouton _Lancer maintenant_, historique dans _Swiss Exchange Rate Import Log_).
Détail complet : `apps/erpnextswiss/docs/swiss_exchange_rates.md`.

**Les deux réglages posés par `set_accounting_settings()`** (dans `company_setup.py`) :

| Réglage                                                            | Valeur        | Pourquoi                                                                                                                                                                                                                        |
| ------------------------------------------------------------------ | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Accounts Settings → `allow_stale`** (Allow Stale Exchange Rates) | **coché (1)** | Sinon un cours daté du 1er est rejeté après `stale_days` (défaut **1 jour**) et ERPNext irait chercher un cours **en ligne** (BCE/Frankfurter) **non conforme**. Coché ⇒ le cours mensuel couvre tout le mois.                  |
| **Currency Exchange Settings → `disabled`**                        | **coché (1)** | Coupe le **fallback API en ligne**. Un cours manquant ⇒ `get_exchange_rate` renvoie `0.00` + invite à créer un `Currency Exchange` → **transaction bloquée (sûr)** plutôt qu'un taux non conforme comptabilisé silencieusement. |

⚠️ **Ordre d'activation** : comme le fallback en ligne est coupé, il faut que l'import AFC ait **au moins
un run** (cours du mois en base) **avant** de saisir des factures en devise, sinon elles seront bloquées.
Active le scheduler (`Enabled`) et/ou lance un import manuel juste après `setup_company`.

### Acomptes — typage 2030 / 1130 + compte de tiers séparé

Option « Book Advance Payments in Separate Party Account » + :
| Compte | root_type | `account_type` | Champ Company |
|---|---|---|---|
| **2030** Acomptes reçus | Liability | **Receivable** | `default_advance_received_account` |
| **1130** Acomptes versés | Asset | **Payable** | `default_advance_paid_account` |

L'« inversion » (Receivable sous Passif / Payable sous Actif) est **volontaire et conforme au pattern
ERPNext** : `account_type` = lien PARTY (Receivable→client, Payable→fournisseur), `root_type` = côté
bilan. Aucun conflit de validation.

> ⚠️ **Effet de bord corrigé** : comme 2030 est typé `Receivable`, ERPNext le choisissait comme
> `default_receivable_account` de la société → les **créances clients** atterrissaient sur le compte
> d'**acompte** (2030) au lieu de **1100**. Le setup **épingle donc explicitement** `default_receivable_account
= 1100` et `default_payable_account = 2000` (les acomptes gardent leurs champs dédiés
> `default_advance_received_account = 2030` / `default_advance_paid_account = 1130`). Bug révélé par la
> suite de tests par scénarios.

**Bank Wizard & rapprochement** : avec la séparation activée, un paiement **non alloué** va sur le compte
d'acompte (2030/1130). Le Bank Wizard créait le paiement **sans référence** puis rattachait la facture
après → le paiement restait sur 2030 alors que la facture est sur 1100 → blocage au _Book_. **Corrigé
dans le fork** (`bank_wizard.make_payment_entry`, cf. `FORK_CHANGES.md` §5.3) : au **rapprochement d'une
facture**, le compte de tiers **normal** (1100/2000) est posé et les références ajoutées **avant l'insert**.
Un **vrai acompte** (encaissement sans facture, bouton _Customer/Supplier_) reste sur **2030/1130**.

- Cas résiduel : si l'on crée d'abord un acompte (2030) **puis** qu'on lui rattache une facture à la main,
  ERPNext bloque (il ne re-route pas le compte automatiquement — c'est voulu). La voie supportée est alors
  **Payment Reconciliation** (transfert 2030 → 1100). Décision : garder la **séparation en continu** (pas de
  reclassement fiduciaire) ; à réévaluer selon le volume réel d'acomptes.

#### Variante : DÉSACTIVER la séparation (acomptes sur les comptes de tiers normaux)

Si un client **ne veut pas** de séparation en continu (peu ou pas d'acomptes, priorité à la simplicité et
zéro friction Bank Wizard), voici la marche à suivre — **c'est un choix parfaitement conforme** (la norme
CO 959a porte sur la **présentation au bilan**, pas sur le routage de chaque paiement).

**1. Comment faire** — _Accounts Settings_ :

- **Décocher** « Book Advance Payments in Separate Party Account ».
- Laisser les champs _Default Advance Received/Paid Account_ tels quels (ils deviennent sans effet) —
  **ne PAS** les pointer vers 1100/2000 (config contradictoire, moins testée : soit on décoche, soit on
  garde 2030/1130).

**2. Conséquence comptable**

- Tout paiement client/fournisseur passe par **1100 / 2000**.
- Un acompte (paiement **avant** facture) reste en **solde du tiers** : un client qui prépaie apparaît en
  **solde créditeur sur 1100** ; un fournisseur prépayé en **solde débiteur sur 2000**.
- **2030 / 1130 restent dans le plan** (disponibles), mais ne sont plus **alimentés automatiquement**.
- Le Bank Wizard n'a **plus aucune friction** (le mismatch 2030 ne peut plus se produire).

**3. Travail manuel fiduciaire — uniquement à la CLÔTURE**
Le CO 959a exige de présenter les acomptes **reçus** (passif) et **versés** (actif) séparément des
créances/dettes commerciales. En cours d'année : **rien à faire**. À la clôture, **si un acompte est
matériel**, le fiduciaire le **reclasse** par une écriture ponctuelle :

| Acompte                    | Écriture de reclassement à la clôture | Effet                                                                 |
| -------------------------- | ------------------------------------- | --------------------------------------------------------------------- |
| **reçu** d'un client       | **Dr 1100** / **Cr 2030**             | sort le solde créditeur du débiteur → passif « acomptes clients »     |
| **versé** à un fournisseur | **Dr 1130** / **Cr 2000**             | sort le solde débiteur du créancier → actif « acomptes fournisseurs » |

En général quelques lignes au bouclement (souvent contre-passées à l'ouverture de l'exercice suivant).

**4. Le fix Bank Wizard reste valable** dans les deux configurations : `get_party_account` rend déjà
1100/2000 quand la séparation est désactivée → aucun code à retoucher si on bascule d'un mode à l'autre.

**En résumé — comment choisir :**

|                          | Séparation **activée** (défaut actuel)                    | Séparation **désactivée**                    |
| ------------------------ | --------------------------------------------------------- | -------------------------------------------- |
| Acompte en cours d'année | isolé sur 2030/1130                                       | solde du tiers (1100/2000)                   |
| Bilan CO 959a            | correct **en continu**                                    | correct **après reclassement à la clôture**  |
| Travail fiduciaire       | nul                                                       | reclassement ponctuel des acomptes matériels |
| Friction Bank Wizard     | gérée (fix + Payment Reconciliation pour le cas résiduel) | **aucune**                                   |
| Quand la préférer        | acomptes = **flux réel** et régulier                      | acomptes **rares** / priorité simplicité     |

### Escomptes — ventilation TVA native + reprise au décompte

Un escompte (Skonto) est, au sens TVA suisse, une **diminution de la contre-prestation** : il réduit
la base imposable **et** reprend la TVA proportionnelle. Le traitement est **automatique** dès lors que :

1. **`book_tax_discount_loss = 1`** (Accounts Settings) est activé — posé par le setup ;
2. l'escompte est appliqué via une **Payment Terms Template** (escompte paiement rapide), **pas** une
   déduction manuelle ; ERPNext l'applique si le paiement tombe **dans le délai** (`reference_date ≤
date-limite d'escompte`).

ERPNext ventile alors seul la déduction : **part nette** → compte d'escompte ; **part TVA** → le compte
de taxe de la facture (2200 en vente, impôt préalable en achat), au prorata du % d'escompte.

**Grand livre (natif, vérifié)** — exemple 10% sur une facture 1 000 + TVA :

|                           | Part nette      | Reprise TVA                                    | Compte tiers      |
| ------------------------- | --------------- | ---------------------------------------------- | ----------------- |
| **Accordé** (vente, NC81) | Dr **3800** 100 | Dr **2200** 8.10 (→ TVA nette 72.90)           | Cr **1100** 1 081 |
| **Obtenu** (achat, IPM81) | Cr **4900** 100 | Cr **1170** 8.10 (→ impôt préalable net 72.90) | Dr **2000** 1 081 |

**3800 vs 4900** : ERPNext n'a **qu'un** `default_discount_account` (3800, escomptes accordés, classe 3).
Sur un paiement d'**achat**, la part nette est un escompte **obtenu** → un hook la route vers **4900**
(escomptes obtenus, classe 4). Résultat net et TVA **inchangés** ; seule la **présentation P&L** est
correcte (CA net vs marge). Voir §15 #3.

**Décompte** : les cases sont normalement alimentées par les **lignes de facture** ; un escompte vit sur
une **déduction de paiement**, invisible pour ces requêtes. Deux extensions (dans `vat_declaration.py`,
côté app — **aucune** divergence de fork) captent l'escompte :

- **`viewVAT_235`** (vente) : additionne les escomptes accordés nets → **case 235** (diminution). La TVA
  du décompte suit automatiquement (TVA vente dérivée = base × taux).
- **`viewVAT_400`/`405`** (achat) : soustrait la reprise d'impôt préalable → **case 400/405 nette**.

Ainsi **grand livre et décompte restent cohérents** (réconciliation de plausibilité au vert des deux côtés).

> **Limite connue** : les extensions supposent l'escompte au **taux normal** (il suit le taux de la
> vente/l'achat) ; un escompte à **taux réduit** exigerait un suivi par taux (non nécessaire au vu du
> mix d'opérations). À revoir si des escomptes à 2.6% deviennent significatifs.

⚠️ Ces choix (2203, 6949, escompte/TVA, 3800↔4900) à **confirmer avec le fiduciaire**.

---

## 12. Comment appliquer

L'app `erpnextswiss` étant **installée**, plus besoin de copier un fichier dans erpnext.

```bash
# 1. Créer la société avec le plan comptable bexio
bench --site <site> execute erpnextswiss.swiss_vat_config.company_setup.create_company \
  --kwargs "{'company_name':'X','abbr':'X'}"

# 2. Tout configurer (templates bexio + afc_box + défauts + acomptes + 6949 + reverse charge)
bench --site <site> execute erpnextswiss.swiss_vat_config.company_setup.setup_company \
  --kwargs "{'company':'X'}"
```

En Docker : `docker compose ... exec frappe bash -lc "cd /workspace/development/frappe-bench && <cmd>"`.
En Kubernetes : `kubectl exec ... -- bash -lc "cd /home/frappe/frappe-bench && <cmd>"`.

**Multi-société** : relancer `setup_company` par société (agit uniquement sur la société passée).
Prérequis : le plan comptable bexio (comptes présents) + l'app installée.

---

## 13. Le décompte TVA (ERPNextSwiss + VAT query)

Le décompte officiel (formulaire AFC / eCH-0217 XML) **n'est pas natif** ERPNext. Stratégie retenue :
**app communautaire [ERPNextSwiss](https://github.com/libracore/erpnextswiss)** (forkée → `IAtive/
erpnextswiss`, branche `v16-compat` avec 2 fixes de compat v16).

- Doctype **`VAT Declaration`** (formulaire, cases z200…z510) + **export XML eCH-0217** + moteur de calcul.
- Les cases sont alimentées par des **`VAT query`** (SQL par case, nommées `viewVAT_<code>`).
- **Notre apport** : des `VAT query` **génériques** qui filtrent par **`afc_box`** (`OR
afc_box_secondary`) côté vente, et par **compte** côté achat — donc **jamais** de nom/compte en dur.
- Réf. normatives : `README_decompte_tva_suisse.md` + spec `eCH-0217 v2.0.0` (dans `documentation/TVA`).

Le décompte s'appuie sur les `afc_box` (§7) → cohérent avec toute la configuration.

### Ce qui est en place (validé de bout en bout)

- ✅ **Queries `viewVAT_<box>` génériques** générées depuis le référentiel (`vat_declaration.py`) :
  base ventes par `afc_box` (+ secondaire), impôt achats par compte, acquisitions base+tax (383).
- ✅ **Reverse charge (383)** : facture d'achat étrangère → base + impôt en 383, déductible en 400/405,
  réconcilié au grand livre.
- ✅ **Export XML eCH-0217 v2** : le fichier de transfert est **validé contre le XSD officiel v2.0.0**
  (bundlé dans `erpnextswiss/public/xsd/`).
- ✅ **Journal TVA** (report « Kontrolle MwSt ») enrichi façon bexio (réf., compte, description, code,
  TVA, total) + dropdown des codes **data-driven**.
- ✅ **Contrôle de plausibilité** (7 tests) : réconciliation GL ↔ décompte, lignes non classées,
  config, taux ligne↔case, écritures manuelles, brouillons, CA hors facturation.
  → CLI + **Script Report UI** + **hook** sur `VAT Declaration` (avertit à l'enregistrement, bloque
  la soumission d'un décompte non plausible). Détail : [`plausibility/README.md`](./plausibility/README.md).

---

## 14. Points ouverts / à faire

**Chantier TVA : bouclé.** Restent des chantiers connexes / opérationnels :

- ⏳ **Item Tax Templates → articles** : tagger les articles (ou Item Groups) pour l'auto-application
  du bon code par ligne.
- ⏳ **Écriture de solde vers 2201** (règlement TVA périodique) + paiement AFC (Journal Entry manuel, §10).
- ✅ **Escomptes** (vente & achat) : ventilation TVA native + reprise au décompte (cases 235 / 400·405),
  routage 3800→4900 achat. Reste **opérationnel** : créer les _Payment Terms Templates_ réelles (conditions
  d'escompte du client) — le mécanisme, lui, est en place (§11 / §15 #3).
- ⏳ **Compte de résultat statutaire** (CO 959b) : _Financial Report Template_ (voir `ch_pme_fr.md`).
- ⏳ **Migration ProConcept** : reprise du plan réel, tiers et soldes d'ouverture (finalité du projet).
- 🧾 **Validation fiduciaire** : voir la section dédiée **§15**.

---

## 15. Points de validation avec le fiduciaire ⚠️

Cette configuration reproduit le modèle **bexio / la pratique suisse** dans ERPNext, dont les
contraintes imposent quelques **choix qui s'écartent légèrement de la comptabilité classique**. Ils
sont **volontaires, documentés et réversibles**, mais doivent être **présentés et validés avec le
fiduciaire du client à l'installation**. Aucun n'affecte le **résultat net** ni le **bilan** ; ils
touchent la **présentation**, la **traçabilité** ou le **mécanisme**.

| #   | Décision                                                            | Écart vs compta classique                                                                                                                                                                                                                                                                                                                                                         | À valider                                                                                                                                                                                                                                                                                               |
| --- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Reverse charge sur 2203**                                         | reconstruit avec un template à 2 lignes (Add 1170/1171 + Deduct **2203**) faute de code natif                                                                                                                                                                                                                                                                                     | le compte de dû (2203) et le mécanisme ; **quels achats** sont concernés (prestations étrangères > 10 000 CHF/an)                                                                                                                                                                                       |
| 2   | **6949 désactivé** (change)                                         | un **seul** compte de change (**6999**) : gains **et** pertes ; perte de la vue _brute_ gains/pertes                                                                                                                                                                                                                                                                              | acceptable de ne pas séparer brut gains/pertes (le net est correct ; présentation CO 959b nette)                                                                                                                                                                                                        |
| 3   | **Escomptes : ventilation TVA native + reprise au décompte**        | via _Payment Terms Template_ + `book_tax_discount_loss` → ERPNext ventile net/TVA seul (reprise 2200 en vente, impôt préalable en achat) ; un hook route la part nette **achat** 3800→**4900** ; extensions `viewVAT_235`/`400`/`405` pour le décompte                                                                                                                            | le **schéma** (une _Payment Terms Template_ par condition d'escompte), le **routage 4900**, et l'hypothèse « escompte au taux normal » (§11)                                                                                                                                                            |
| 4   | **4 comptes « produit » classés en charge**                         | 4 comptes de nature produit vivant sous des groupes de **charges** (classes 6 et 8) → `root_type = Expense` (hérité du parent)                                                                                                                                                                                                                                                    | acceptable au **compte de résultat** (ils apparaissent côté charges) ; sinon reclassement. Liste dans [`ch_pme_fr.md`]                                                                                                                                                                                  |
| 5   | **Acomptes 2030/1130 « inversés »**                                 | 2030 (passif) typé **Receivable**, 1130 (actif) typé **Payable**                                                                                                                                                                                                                                                                                                                  | c'est le **pattern ERPNext** (type = lien tiers, root_type = côté bilan) — pas une erreur, mais à expliquer                                                                                                                                                                                             |
| 6   | **Case 205 (opté) sans compte dédié**                               | l'opté est comptabilisé sur 3200/2200 comme une vente normale ; le « 205 » vit sur l'`afc_box`, pas sur un compte                                                                                                                                                                                                                                                                 | auditable via le **journal TVA** (drill-down), **pas** par un solde de compte → OK, ou créer un compte produit dédié si audit « au solde » exigé                                                                                                                                                        |
| 7   | **Règlement TVA vers 2201 — manuel**                                | pas de décompte natif → l'écriture de solde périodique (2200/1170/1171 → **2201**) puis le paiement AFC sont un **Journal Entry manuel**                                                                                                                                                                                                                                          | le **schéma** (comptes soldés, périodicité) avant la 1re clôture TVA réelle                                                                                                                                                                                                                             |
| 8   | **Méthode de décompte : effective, contre-prestations _convenues_** | méthode **effective** (pas taux de la dette fiscale nette / forfaitaire) **et** TVA due à la **facturation** (_convenues_), pas à l'encaissement (_reçues_) → **pas de TVA sur les acomptes**                                                                                                                                                                                     | la **méthode TVA réelle** : effective/forfaitaire **et** convenu/reçu                                                                                                                                                                                                                                   |
| 9   | **TVA import en mode douane classique** _(aligné bexio)_            | report de l'impôt à l'import (art. 63 LTVA) **non** activé → TVA import déductible en **case 400** (compte **1170**), via un code douane **100%** (**DOUAM/DOUACE**, exactement comme bexio), porté sur la **facture du transitaire** (fournisseur normal, contrepartie 2000)                                                                                                     | si la société a l'**autorisation de report** (sinon rien à faire — c'est le mode standard)                                                                                                                                                                                                              |
| 10  | **Méthode d'inventaire : PERPÉTUEL** (stock = cœur de métier)        | on retient l'**inventaire perpétuel** : le stock est valorisé **en temps réel** (réception → Dr 1200 ; livraison → Dr 4200 COGS / Cr 1200), **COGS et marge connus par vente**. Deux **comptes techniques** ajoutés (**2301 SRBNB**, **2302 EIIV**) en **passif de régularisation** (famille 230, CO 958b). **Impact TVA : aucun.** Flux à **2 documents** (réception + facture / livraison + facture). | **confirmer avec la fiduciaire** : la **méthode retenue (perpétuel)**, l'**emplacement des 2 comptes** (230 régularisation = norme-correct ; alternative près des créanciers 2005), et le **changement opérationnel** (réceptions + bons de livraison saisis en continu). Détail, écritures et impact : **cf. détail #10 + §21**. |
| 11  | **Bouclement du résultat de l'exercice** _(aligné bexio)_           | à la clôture, le résultat du compte de résultat est viré sur **2979 « Bénéfice/perte de l'exercice »** (comme la fonction _Comptabilisation des résultats_ de bexio) via un **Period Closing Voucher** ; l'**affectation** (2979 → 2970 reporté / réserves / dividende) est **séparée** (post-AG)                                                                                 | la **périodicité** de bouclement et le schéma d'**affectation** du résultat                                                                                                                                                                                                                             |
| 12  | **Multi-devises : CHF + EUR (achat & vente)**                       | comptes créance/dette **en EUR** (**1101** / **2001**) créés hors chart (car `account_currency` est ignoré sur un chart `verified`) ; **pas de banque EUR par défaut** (paiement/encaissement EUR via le compte CHF — 1021 à ajouter seulement si compte bancaire EUR réel, voir §11) ; la **TVA reste en CHF** (taux facture) ; l'**écart de change** au règlement → **6999**, en mode **réalisé à l'encaissement** (conversion CHF) — alternative : soldes en devise + **réévaluation périodique** (voir §11)   | **quelles devises** le client utilise réellement (EUR seul ? + USD ?), **quels sens** (vente/achat), et **réalisé à l'encaissement ou réévaluation périodique** ?                                                                                                                                       |
| 13  | **Acomptes : compte de tiers séparé (2030/1130) — ON ou OFF**       | option _Book Advance Payments in Separate Party Account_ **activée par défaut** → acomptes isolés **en continu** sur **2030/1130**. Alternative : **désactiver** → acomptes en **solde du tiers** (1100/2000) + **reclassement à la clôture** des acomptes matériels. **Conforme CO 959a dans les deux cas** ; détails, écritures de reclassement et arbitrage complet au **§11** | le **volume réel d'acomptes** (reçus de clients / versés à des fournisseurs) : flux **régulier** → garder la **séparation** (bilan propre en continu) ; **rares** → **désactiver** (plus simple, zéro friction Bank Wizard, reclassement ponctuel au bouclement)                                        |
| 14  | **Cours de change : moyennes mensuelles AFC**                       | on utilise **actuellement** le **cours mensuel moyen de l'AFC** (daté du 1er du mois, importé automatiquement), **pas** le cours du jour ni un cours de marché/BCE ; fallback en ligne coupé (`Currency Exchange Settings.disabled`) et cours « périmés » autorisés (`allow_stale`) — cf. §11                                                                                     | que le **cours mensuel moyen AFC** convient pour le décompte TVA (art. 45 OTVA autorise **mensuel moyen _ou_ cours du jour, devises vente** — la méthode doit être **conservée durant toute une période fiscale**) ; sinon basculer sur **cours du jour** (`rate_type = Daily`) dès le début de période |
| 15  | **Prestations à soi-même / part privée** _(spécifique métier)_ | usage privé de biens/services déduits (**véhicule**, **cadeaux > ~500 CHF**, **échantillons/PLV prélevés**) → correction TVA. **Deux méthodes** : **(A) produit imposable** — part privée = CA (case 200/301) + TVA due 2200, *recommandée véhicule* ; **(B) correction d'impôt préalable** — case 415 via 1174 (approche ProConcept 106100). ⚠️ **Lacune vérifiée** de la méthode B : le mécanisme actuel (template **IPPS** sur facture d'achat) donne le **bon chiffre** de décompte mais une **écriture GL au signe inversé**, et `viewVAT_415` ne lit **que les factures d'achat** (l'écriture correcte n'est pas captée) → **à corriger** (extension `viewVAT_415`, façon escompte) avant usage. Détail : **§20.2**. | la **méthode** (produit imposable vs correction préalable) ; la **base véhicule** (forfait **0,8 %/mois** vs effectif) ; le **seuil cadeaux** (~500 CHF) ; la politique **échantillons/testers** ; **et faire corriger le mécanisme case 415** |

### Détail des points principaux

**1. Reverse charge (2203)** — L'impôt sur les acquisitions (_Bezugsteuer_, art. 45 LTVA) est déclaré
**et** déduit par l'acheteur. ERPNext n'ayant pas de code TVA « intelligent », on le reconstruit avec
un template Purchase à 2 lignes (§8). Le compte **2203** porte l'impôt dû (case **383**) ; la
déduction va en 1170/1171 (cases 400/405). Trésorerie nulle, mais les deux montants figurent au
décompte. → **Confirmer le compte 2203 et lister les fournisseurs/opérations concernés.**

**2. Change — 6949 désactivé** — bexio distingue 6999 (gains) et 6949 (pertes) ; ERPNext n'a qu'un
`exchange_gain_loss_account`. On met tout sur **6999** et on désactive 6949. **Résultat net et bilan
identiques** (un gain crédite 6999, une perte le débite → le solde = le résultat de change). On perd
seulement la vue _brute_ gains vs pertes, sans incidence sur la présentation CO 959b (nette).
**Réversible** (réactiver 6949 = Option B, avec reclassement manuel).

**4. Les 4 comptes 6/8 classés en Expense** — Dans le plan bexio, quatre comptes de nature _produit_
sont rangés sous des groupes de **charges** (classes 6 et 8). ERPNext hérite le `root_type` du groupe
parent → ils sont `Expense`. Ils apparaissent donc **côté charges** du compte de résultat (montants
généralement négatifs). **Le résultat net est inchangé** (vérifié). La liste précise et l'analyse
d'impact sont dans [`accounting/erpNext16-ch-chart-of-accounts/ch_pme_fr.md`]. → **Confirmer que cette
présentation convient**, sinon reclasser.

**7. Règlement TVA (2201)** — ERPNext ne génère pas l'écriture de décompte suisse. En fin de période,
on solde manuellement 2200 (TVA due) et 1170/1171 (préalable) vers **2201** (dette nette AFC), puis on
paie l'AFC depuis 2201 (§10). → **Valider le schéma exact et la périodicité** avec le fiduciaire avant
la première clôture réelle.

**8. Méthode effective + contre-prestations _convenues_** — Le paramétrage suppose la méthode
**effective** (impôt dû − impôt préalable, par opposition au taux de la dette fiscale nette /
forfaitaire) **et** le décompte selon les contre-prestations **convenues** (TVA due dès la
**facturation**, pas à l'encaissement). Conséquence directe : **un acompte reçu/versé ne génère pas
de TVA** — celle-ci naît à l'émission de la facture. → **Confirmer avec le fiduciaire la méthode
réelle de la société sur les deux axes** (effective/forfaitaire ET convenu/reçu). Si la société est
au _reçu_, le traitement des acomptes changera (TVA à l'encaissement).

**10. Inventaire PERPÉTUEL & comptes de stock** — La gestion du stock étant le **cœur de métier**
(négoce / revendeur), on retient l'**inventaire perpétuel** : le stock est valorisé **en temps réel**
(chaque réception l'entre, chaque livraison en sort le coût), et la **marge est connue par vente**. Le
setup **active** « Enable Perpetual Inventory » et pose **2 comptes techniques** — les autres existent
déjà (**1200** stock, **4200** COGS, **4208** ajustement) :

- **2301 SRBNB « Marchandises reçues, non facturées »** — tampon **réception ↔ facture** (`account_type`
  *Stock Received But Not Billed*, champ Company `stock_received_but_not_billed`).
- **2302 EIIV « Frais accessoires inclus dans la valorisation »** — tampon **landed cost ↔ facture** du
  transporteur (`account_type` *Expenses Included In Valuation*, **trouvé par account_type**, pas de
  champ Company).

**Emplacement normatif** : les deux sont des « **reçu / engagé, pas encore facturé** » → des **passifs
de régularisation** (**famille 230**, CO art. 958b) ; ils **tendent vers zéro** (`2301 + 2302 = 0` ⇒ tout
ce qui est reçu a été facturé). Alternative acceptée : près des créanciers (`2005`), à l'appréciation du
fiduciaire. **Impact TVA : aucun** (la TVA reste sur les factures ; les mouvements de stock n'en portent
pas). Le **détail du fonctionnement, des flux et des écritures** est au **§21**.

**11. Bouclement du résultat _(aligné bexio)_** — À la clôture, ERPNext vire le solde du compte de
résultat (classes 3 à 8) sur les **capitaux propres** via un **Period Closing Voucher**. Compte cible :
**2979 « Bénéfice ou perte de l'exercice »** — c'est **exactement** ce que fait bexio via sa fonction
**« Comptabilisation des résultats »** : le résultat de l'année est **isolé sur 2979** (ligne distincte
au bilan CO 959a). Le compte de résultat repart à zéro pour l'exercice suivant. L'**affectation**
ultérieure — **2979 → 2970 « Bénéfice reporté »** / réserves / dividende, **après décision de l'AG** —
est une **écriture séparée** (faite par le fiduciaire). → **Confirmer la périodicité (annuelle) et le
schéma d'affectation du résultat** avant la 1re clôture d'exercice.

**12. Multi-devises (CHF + EUR)** — Le client opère en **CHF et EUR**, à l'**achat** et à la **vente**.
Pour suivre des créances/dettes en devise et calculer l'**écart de change au règlement**, ERPNext exige
des comptes **dans la devise** (une créance EUR se tient en EUR). On ajoute donc **1101 Créances clients
EUR** et **2001 Dettes fournisseurs EUR** — créés par `setup_currency_accounts`, car
le chart `verified` **ignore `account_currency`** (§3.6 du plan comptable). Fonctionnement : la facture
EUR inscrit la créance/dette **en EUR** ; au paiement (à un autre cours), ERPNext sort **seul** le
gain/perte de change → **6999** ; la **TVA reste en CHF** au taux de la facture. Ces comptes se
**rattachent aux tiers** (Customer/Supplier → onglet _Accounts_) ou se choisissent **par facture**
(_Debit To / Credit To_). Le gain/perte est **réalisé à l'encaissement** si l'on **convertit en CHF**,
ou **latent** (repris par réévaluation périodique) si l'on **garde les liquidités en devise** — cet
arbitrage et ce qu'on applique aujourd'hui sont détaillés au **§11 « Change — réalisé vs latent »**.
→ **Confirmer les devises réellement utilisées** (EUR seul, ou aussi USD…) **et les sens** (vente/achat)
**et le mode** (réalisé à l'encaissement / réévaluation) ; toute devise supplémentaire = un jeu de comptes équivalent.

> **En résumé** : ces choix rapprochent bexio d'ERPNext sans fausser la comptabilité. Ils doivent être
> **présentés au fiduciaire à l'installation** pour accord formel — en particulier **1, 4 et 7** qui
> touchent la présentation légale ou le mécanisme du décompte.

---

## 16. Saisir une facture d'achat (net, TTC, ajustement TVA)

Guide pratique de saisie d'une facture d'achat / dépense. **Principe** : on **recopie ce que dit la
facture**. Trois cas selon ce qu'on a en main.

### 16.1 Cas par défaut — saisir le montant NET (recommandé)

Une facture fournisseur suisse affiche **net (HT) + TVA + total (TTC)**. On saisit le **net** en ligne,
et le template TVA (IPM81 = « On Net Total », **tax-exclusif**) **ajoute** la TVA par-dessus → le total
retombe sur le TTC.

- Ligne d'article/charge : **Rate = montant HT** de la facture.
- **Taxes and Charges Template** = code d'achat (ex. **IPM81** 8.1 %, case 400).
- Résultat : `HT + TVA = TTC`, fidèle à la facture, TVA (case 400) = celle facturée.

C'est le mode **standard et le plus fidèle** : le net et la TVA de la facture sont reproduits tels quels.

### 16.2 Si tu n'as que le TTC — cocher `included_in_print_rate`

Pour une **dépense carte / un reçu** où tu n'as que le **montant brut payé** (pas le détail HT/TVA), tu
peux saisir directement le **TTC** et demander à ERPNext d'**extraire** la TVA :

- Ligne d'article/charge : **Rate = montant TTC** (ce que la carte a débité).
- Sur la **ligne de taxe**, coche **« Considered Tax included in Basic Rate? »** (`included_in_print_rate`).
- ERPNext calcule alors `TVA = TTC × taux / (100 + taux)` et en déduit le net.
  Ex. 108.10 TTC à 8.1 % → net 100.00, TVA 8.10.

> À réserver aux cas « je n'ai que le total ». Pour une **vraie facture détaillée**, préfère le **net**
> (§16.1) — plus fidèle, et évite les écarts d'arrondi (§16.3).

### 16.3 Ajuster la TVA quand le calcul d'ERPNext diffère de la facture

Le montant de TVA d'une facture **n'est pas toujours** exactement `net × taux` : le fournisseur applique
**son propre arrondi** (souvent par ligne/par période). Exemple réel (Infomaniak, abonnement annuel) :

|               | Facture   | `net × 8.1 %` (ERPNext) |
| ------------- | --------- | ----------------------- |
| HT            | 405.53    | 405.53                  |
| **TVA 8.1 %** | **32.87** | 32.85 (≠)               |
| TTC           | 438.40    | 438.38 (≠)              |

Un calcul automatique (net×taux **ou** extraction TTC) donne **32.85** — mais la facture dit **32.87**.
**Règle suisse** : l'impôt préalable déductible est la **TVA effectivement facturée** (32.87). Il faut
donc **forcer** ce montant :

- Passe la **ligne de taxe** en **`Actual`** (charge type = _Actual_, taux 0) et saisis le **montant
  exact** de la facture (**32.87**) sur le compte d'impôt préalable (**1170**).
- Résultat : `405.53 + 32.87 = 438.40` → correspond **à la facture ET au débit carte**, et **case 400 =
  32.87** (la TVA réellement facturée).

C'est le **même mécanisme** que la TVA douane (§9, code DOUAM en `Actual`).

> Pour la **plupart** des factures, `net × taux` = la TVA facturée → §16.1 suffit. Le mode `Actual`
> (§16.3) ne sert que pour les **écarts d'arrondi fournisseur** (souvent 1–2 rappens).

### 16.4 Rappels

- **Fournisseur étranger sans TVA (reverse charge)** : **jamais** en TTC. Le montant est **net**, la TVA
  suisse s'**auto-liquide** en sus (cases 383 + 400, trésorerie nulle). → template reverse charge (§8).
- **Déjà payé (carte / e-banking)** : coche **« Is Paid »** et indique le **compte carte/banque** →
  écriture directe charge + TVA + banque, **sans dette ouverte** (équivalent de la « dépense » bexio).
  À réserver aux paiements immédiats ; les vraies factures à échéance restent en dette (2000) + paiement.
  ⚠️ **Si tu réconcilies via camt (Bank Wizard)** : n'utilise **pas** « Is Paid » pour un paiement qui
  figurera sur le relevé bancaire (carte **ou** virement, tous deux sur le même compte). « Is Paid » crédite
  déjà la banque ; si le Bank Wizard crée en plus un paiement depuis le camt → **double débit**. Dans ce cas :
  facture en **créancier**, puis **Bank Wizard → Purchase Invoice** solde la dette (un seul mouvement, §17).

---

## 17. Compte banque CHF unique & modes de paiement

Décision (mono-société, un seul compte bancaire CHF ; la carte débite ce même compte immédiatement) :
**tout paiement passe par 1020**, et les modes de paiement sont réduits/traduits.

### 17.1 Banque CHF unique

- **Source du chart (nouvelles sociétés)** — c'est la correction principale : `generate_coa.py` porte
  `ACCOUNT_RENAME = {"1020": "Banque CHF"}` et `EXCLUDE_ACCOUNTS = {"1029"}` → le plan (`ch_pme_fr.json`)
  ne crée **plus qu'un** compte banque CHF, déjà nommé **« Banque CHF »**, **sans** le placeholder « Bank »/1029.
  Une société créée avec ce chart n'a donc **jamais** de 1029 à supprimer.
- **Migration d'une société née de l'ancien chart** — `cleanup_bank_accounts(company)` : si le compte 1020
  s'appelle encore autrement (ex. « Banque UBS CHF »), il est **renommé « Banque CHF »** via
  `erpnext…account.update_account_number` (met à jour le libellé **et cascade tous les liens** : GL Entry,
  `Company.default_bank_account`, Mode of Payment Account…). **No-op silencieux** pour une société née du
  chart corrigé. _(Le placeholder 1029 n'est plus géré ici : le chart ne le produit plus.)_

### 17.2 Modes de paiement — `setup_modes_of_payment(company)`

- **Tous** les modes sont **traduits en FR** par renommage : `Credit Card → Carte de crédit`,
  `Wire Transfer → Virement bancaire`, `Cash → Espèces`, `Cheque → Chèque`, `Bank Draft → Traite bancaire`.
- Seuls **« Carte de crédit »** et **« Virement bancaire »** sont **actifs** (les trois autres désactivés).
- Les deux modes actifs sont **mappés sur `1020`** (compte par défaut, par société) ; les mappings devenus
  inutiles (ex. `Espèces → 1000`) sont retirés pour la société.
- ⚠️ **Collation MariaDB accent-insensible** : `exists("Chèque")` renvoie « Cheque ». Le renommage
  accent-seul (`Cheque → Chèque`) ne peut donc pas se garder sur `not exists(fr)` (il sauterait à tort) ;
  on lit le **nom réellement stocké** (`get_value(..., "name")`) et on ne renomme que s'il diffère exactement.
- ⚠️ **Mode of Payment est un master GLOBAL** (partagé par tout le bench) : le **renommage** et
  l'**activation** valent pour toutes les sociétés/sites ; seul le **mapping du compte** est par société.
  Acceptable ici car déploiement **mono-client**. Fonctions **idempotentes**.

---

## 18. Paramétrage manuel requis (après le setup)

Le setup automatise l'essentiel, mais **certains éléments dépendent des données réelles de la société**
et doivent être complétés/vérifiés à la main. Le script l'affiche en fin d'exécution.

### 18.1 Banque & compte bancaire de la société

- Le setup **crée automatiquement** (`setup_bank`) : la **banque « UBS Switzerland AG »** (BIC `UBSW`) et
  un **compte bancaire d'entreprise « UBS CHF »** rattaché au compte **1020 - Banque CHF**, marqué
  **Is Default** + **Is Company Account** (ce dernier est requis pour le **rapprochement bancaire**).
- À compléter **manuellement** :
  - **IBAN** du compte bancaire — laissé **vide** par le setup (spécifique à la société).
  - **BIC complet** de la banque si besoin (UBS = `UBSWCHZH80A` ; le setup pose `UBSW`).
  - Vérifier que la **banque** et le **compte** rattachés sont corrects (autre banque que UBS, second
    compte, etc.).

### 18.2 Comptes de tiers (fournisseurs / clients)

- Pour chaque **fournisseur / client en devise**, renseigner son **compte de tiers** (onglet _Accounts_
  du Supplier/Customer) : **EUR → 2001** (dettes) / **1101** (créances). Sans ça, ERPNext utilise le
  compte par défaut en CHF (2000/1100) et le calcul du change au règlement est faussé (cf. §5.4 du fork,
  Bank Wizard). Les tiers en **CHF** peuvent rester sur le compte par défaut.

### 18.3 Renommer les comptes génériques du plan

- Certains comptes du plan bexio sont **génériques** et gagnent à être renommés selon la réalité de la
  société — typiquement le **compte bancaire** (ex. `1020 « Banque CHF »` → nom de la banque réelle)
  ou d'autres comptes portant un libellé neutre.
- Renommage sûr via **Compte → menu → Rename** (ou `update_account_number`) : le **libellé change et tous
  les liens sont mis à jour**, les écritures sont conservées (le **numéro** de compte, lui, ne change pas).

### 18.4 Changer les comptes liés aux méthodes de paiement

- Si les methodes de paiement préconfigurés n'utilisent pas les mêmes comptes, changer le paramétrage.

### 18.5 Tiers & comptes bancaires — prérequis à la synchro bancaire

Pour que la **synchronisation bancaire** fonctionne (envoi des paiements en `pain.001` et rapprochement
des relevés `camt.053/054`), les **données maîtres des tiers** doivent être complètes. Le setup ne les
crée pas (elles dépendent des vrais fournisseurs/clients) → **à saisir manuellement**.

**Fournisseurs (flux SORTANT — génération du `pain.001`)** :

- **Adresse valide** sur chaque fournisseur (rue, NPA, ville, pays) marquée comme adresse principale.
  Le fichier `pain.001` (ISO 20022) transporte le **nom + adresse du bénéficiaire** ; une adresse
  manquante/incomplète peut faire **rejeter** le fichier par la banque (ou en dégrader le traitement STP).
- **Fiche Bank Account avec IBAN** par fournisseur : doctype **Bank Account** lié au fournisseur
  (`party_type = Supplier`, **« Is Company Account » décoché**), avec l'**IBAN** (+ BIC si hors CH).
  C'est **la** donnée qui permet à **Payment Proposal → `pain.001`** de générer le virement — **sans IBAN,
  pas de paiement automatique**.
- **QR-IBAN vs IBAN** : les factures suisses se paient souvent sur un **QR-IBAN** avec une **QR-référence**
  (≠ IBAN classique + communication) → saisir le bon type.
- 🇨🇭 Alternative : pour une facture ponctuelle, l'IBAN + la référence peuvent être **récupérés en scannant
  la QR-facture** du fournisseur (ZUGFeRD/QR Wizard d'ERPNextSwiss) — pas besoin de tout pré-saisir ; mais
  pour un fournisseur **récurrent**, enregistrer sa fiche Bank Account une fois est plus fiable.

**Clients (flux ENTRANT — rapprochement des `camt`)** :

- **Pas besoin de l'IBAN du client** pour **encaisser** : le rapprochement `camt.053/054` (Bank Wizard)
  se fait via **TA QR-référence** posée sur tes **factures de vente** → veiller donc à **émettre des
  QR-factures** correctement référencées (c'est ça le prérequis côté vente, pas l'IBAN client).
- **Exception** : le **prélèvement LSV / Direct Debit** (`pain.008`) nécessite l'**IBAN du client + un
  mandat** → à saisir uniquement si tu prélèves.

**Résumé** : synchro OK ⇔ fournisseurs avec **adresse + IBAN** (sortant `pain.001`) **et** factures de
vente en **QR-facture** bien référencées (entrant `camt`). L'IBAN **client** n'est requis que pour le
prélèvement LSV. Les lignes bancaires non identifiées au rapprochement restent parquées sur **1099**
(compte d'attente) en attendant clarification.

### 18.6 Ajouter une nouvelle devise (USD, JPY, …)

Le setup crée par défaut les comptes **EUR** (1101 / 2001). Pour opérer dans une **autre devise**, ajouter :

1. **Comptes de tiers dans la devise** (créés « hors chart », comme 1101/2001, rangés sous le même
   groupe que leur homologue CHF — 1100 / 2000 — avec **`account_currency` = la devise**) :
   - **Créance `11xx`** (type *Receivable*) — si tu **vends** dans cette devise ;
   - **Dette `20xx`** (type *Payable*) — si tu **achètes** dans cette devise.
   - Convention de numérotation : **EUR** 1101/2001 · **USD** 1102/2002 · **JPY** 1103/2003 · etc.
   - Ne créer que le(s) **sens réellement utilisé(s)** (achat → dette seule ; vente → créance seule).

2. **Cours AFC** : ajouter la devise dans **Swiss Exchange Rate Settings → Currencies** → les cours
   mensuels moyens AFC seront importés. (Le JPY est coté /100 par l'AFC — le diviseur est géré
   automatiquement, le taux stocké est bien par 1 unité.)

3. **(Optionnel) Compte de tiers par défaut** : rattacher le compte devise (ex. 2002) comme compte
   par défaut d'un fournisseur/client **uniquement s'il est mono-devise** (un compte en USD ne porte
   que des transactions USD). Tiers multi-devises → laisser le défaut CHF (ERPNext convertit).

4. **Vérifier** que la **Currency** (USD, JPY…) est **activée** dans ERPNext.

L'écart de change (→ **6999**) et la TVA (base convertie en CHF au cours de la facture) fonctionnent
pour toute devise sans réglage supplémentaire.

### 18.7 Établir le décompte TVA — étapes

Procédure **récurrente** (par trimestre en général) pour produire et déclarer le décompte TVA à l'AFC.
Le **mécanisme** (doctype `VAT Declaration`, requêtes `viewVAT_<case>`, export XML eCH-0217) est décrit en
**§13** ; l'**architecture des cases** en **§7** ; le **règlement 2201** en **§10**. Ici : les **étapes**.

> Méthode : **contre-prestations convenues** (§15 #8) → la TVA est due dès la **facture** (docstatus = 1),
> pas au paiement. Le décompte prend donc toutes les pièces **soumises** de la période.

**Étapes :**
1. **Prérequis** : toutes les factures / avoirs de la période **soumis** (docstatus = 1) ; cours AFC importés
   (§11) ; escomptes appliqués via _Payment Terms Templates_ (§11).
2. **Créer le décompte** : _VAT Declaration_ → **New** → **Company**, **période** (date de début / fin du
   trimestre), titre.
3. **Calculer** : les cases se remplissent **automatiquement** via les requêtes `viewVAT_<case>` (§13) —
   chiffre d'affaires (200-289), TVA due (300-399), impôt préalable (400/405), acquisitions/reverse charge
   (382/383), escomptes (235 / 400·405), net à payer/en faveur (500/510). **Contrôle chaque case**.
4. **⚠️ Contrôle de plausibilité TVA** — à l'**enregistrement**, le **hook** lance les **7 contrôles**
   (réconciliation GL ↔ décompte, lignes **non classées**, config, taux **ligne ↔ case**, écritures
   **manuelles**, **brouillons** oubliés, CA hors facturation). Un décompte **non plausible** →
   **avertissement** à l'enregistrement et **soumission BLOQUÉE** tant qu'il reste une anomalie.
   - Consultable aussi via le **Script Report de plausibilité** (UI) et en **CLI**. Détail et résolution
     des anomalies : [`plausibility/README.md`](./plausibility/README.md).
   - **Corriger les anomalies** (ligne sans `afc_box`, brouillon oublié, écriture manuelle non classée…)
     **avant** de continuer.
5. **Rapprocher** (recommandé) : croiser avec le **journal TVA** (report _Kontrolle MwSt_) et vérifier les
   soldes des comptes **2200 / 1170 / 1171** et des **227x** (§10).
6. **Exporter** : générer le **XML eCH-0217 v2** (validé contre le XSD officiel) pour le dépôt en ligne, et/ou
   le **PDF** (print format « Décompte TVA (AFC) »).
7. **Soumettre** le décompte dans ERPNext (docstatus = 1) — **impossible si non plausible** (cf. étape 4).
8. **Transmettre à l'AFC** via le portail **e-TVA** (dépôt du XML / saisie du montant).
9. **Comptabiliser le règlement** (§10 / §15 #7) : **Journal Entry manuel**, en **deux temps**.

   **① Solder les comptes de TVA vers 2201** (fin de période). Exemple — TVA due 8'100, impôt préalable
   3'200 (Mat./Ser.) + 800 (Inv./CE) :
   ```
   Débit    2200  TVA due                       8'100.00
     Crédit   1170  Impôt préalable Mat./Ser.            3'200.00
     Crédit   1171  Impôt préalable Inv./CE                800.00
     Crédit   2201  Décompte TVA (dette AFC)            4'100.00
   ```
   → 2200, 1170 et 1171 reviennent à **0** ; **2201** porte la **dette nette** = 8'100 − 3'200 − 800 = **4'100**.

   **② Payer l'AFC** depuis la banque :
   ```
   Débit    2201  Décompte TVA                  4'100.00
     Crédit   1020  Banque CHF                          4'100.00
   ```
   → **2201** revient à **0**.

   - **Position créditrice** (impôt préalable > TVA due) : 2201 est **débiteur** → l'AFC **rembourse** →
     `Débit 1020 / Crédit 2201`.
   - **Reverse charge** (impôt sur les acquisitions) : le **dû** sur **2203** (case 383) est **aussi** soldé
     (`Débit 2203`), sa contrepartie **déductible** étant déjà dans 1170/1171 → **effet net nul** sur le
     montant à payer (§8 / §10).
10. **Contrôle récurrent** : après règlement, les comptes de TVA (**227x**, 2200, 1170/1171) doivent revenir
    à zéro pour la période soldée — **un solde résiduel = une anomalie à investiguer**.

---

## 19. Gestion des salaires (paie externe → comptabilisation ERPNext)

> **Cadre de ce chapitre.** La paie — **calcul**, fiches de salaire, **déclarations légales** — est
> réalisée dans un **logiciel de paie externe certifié Swissdec**. ERPNext ne sert **qu'à la
> comptabilisation** : enregistrer le journal de paie, payer le net et les cotisations, réconcilier.
> Ce chapitre est un **tutoriel pas-à-pas destiné au comptable / fiduciaire** : le paiement d'un
> salaire du **début à la fin**, avec les **obligations légales**.

### 19.1 Qui fait quoi

| Étape | Logiciel de paie (certifié Swissdec) | ERPNext |
| --- | --- | --- |
| Calcul brut → retenues → net | ✅ | — |
| Fiches de salaire (mensuel) | ✅ | — |
| **Comptabilisation** (journal de paie) | — | ✅ |
| **Paiement** du net + des cotisations | (peut générer le `pain.001`) | ✅ (écriture + banque) |
| **Certificat de salaire** (form 11, annuel) | ✅ | — |
| **Déclarations légales ELM** (AVS, impôt source, LAA, LPP, IJM, OFS) | ✅ | — |
| Réconciliation des comptes sociaux | — | ✅ |

**Règle d'or** : ERPNext ne **déclare** rien aux autorités. Il **comptabilise** et **paie**. Les
**déclarations** (Swissdec/ELM) et le **certificat de salaire** sont produits par le logiciel de paie.

### 19.2 De quoi se compose un salaire (rappel)

- **Salaire brut** : la base.
- **Retenues salariales** (déduites du brut, à la charge de l'**employé**) : AVS/AI/APG, AC (chômage),
  LAA non-professionnel (AANP), LPP (part employé), et **impôt à la source** si l'employé y est soumis.
- **Salaire net** = brut − retenues → c'est ce qui est **versé** à l'employé.
- **Charges patronales** (en **plus**, à la charge de l'**employeur**) : AVS/AI/APG, AC, LAA
  professionnel (AAP), LPP (part employeur), CAF (allocations familiales), IJM (indemnité maladie).

⚠️ Les **taux et plafonds changent chaque année** — ils sont gérés par le **logiciel de paie**, pas
par ERPNext.

### 19.3 Les comptes utilisés (déjà présents dans le plan bexio)

**Charges de personnel (classe 5, `Expense`)** :

| Compte | Usage |
| --- | --- |
| **5000** | Salaires (brut) |
| **5700** | AVS, AI, APG, AC (part patronale) |
| **5710** | Caisse d'allocations familiales (CAF) |
| **5720** | Prévoyance professionnelle — LPP (part patronale) |
| **5730** | Assurance-accidents — LAA (part patronale) |
| **5740** | Assurance maladie — IJM (part patronale) |
| **5790** | Impôts à la source (charge, si à charge employeur) |

**Dettes envers les caisses (passifs, comptes courants)** :

| Compte | Destinataire |
| --- | --- |
| **2271** | C/C AVS, AI, APG, AC → **caisse de compensation** |
| **2272** | C/C Caisse d'allocations familiales (CAF) → caisse de compensation |
| **2270** | C/C Prévoyance professionnelle → **caisse de pension (LPP)** |
| **2279** | C/C Impôt à la source → **administration fiscale cantonale** |
| *(2273 à créer)* | *C/C Assurance-accidents/maladie (LAA/IJM) → assureur* — optionnel |
| *(2069 à créer)* | *C/C Saisie sur salaire → créancier* — **seulement si saisie réelle** |

### 19.4 Le paiement d'un salaire, étape par étape

**Étape 1 — Calcul (logiciel de paie).** Le logiciel calcule brut → retenues → net, édite la
**fiche de salaire** du mois et la remet à l'employé (obligation, art. 323b CO).

**Étape 2 — Comptabilisation dans ERPNext.** On enregistre **une écriture mensuelle** (Journal Entry)
qui : débite les **charges** (5xxx), crédite les **dettes sociales** (227x) et crédite la **banque**
(le net). → *voir §19.5 pour l'écriture chiffrée.* Le mieux : **importer le journal comptable exporté
par le logiciel de paie** (la plupart le proposent) plutôt que le ressaisir.

**Étape 3 — Versement du NET au salarié.** Payé depuis **1020** (banque), en général en fin de mois
(échéance contractuelle). Peut se faire via un fichier **`pain.001`** (généré par le logiciel de paie
ou par ERPNext). *Obligation contractuelle* (le salaire est dû à l'échéance convenue).

**Étape 4 — Versement des cotisations sociales aux caisses.** Selon la périodicité de chaque caisse :
- **AVS/AI/APG/AC + CAF** → caisse de compensation (souvent **acomptes** trimestriels + **décompte
  annuel**) ;
- **LPP** → caisse de pension (selon caisse) ;
- **LAA/IJM** → assureur (**prime annuelle**, avec acomptes).
Chaque paiement **solde** le compte courant correspondant (Débit 227x / Crédit 1020).

**Étape 5 — Reversement de l'impôt à la source.** L'employeur reverse l'impôt retenu à
l'**administration fiscale cantonale**, en général **dans les 30 jours** suivant l'échéance mensuelle
(mensuel ou trimestriel **selon le canton**). Écriture : Débit **2279** / Crédit **1020**.

**Étape 6 — Réconciliation.** Chaque mois, les **soldes des comptes 227x** doivent correspondre à ce
que réclament les caisses/le canton. Un solde 227x non nul = une dette encore à payer.

**Étape 7 — Obligations annuelles (par le logiciel de paie / l'employeur).**
- **Certificat de salaire** (form 11) → remis à chaque salarié **et** au fisc, au **31 janvier**.
- **Décompte annuel AVS** → caisse de compensation, au **30 janvier**.
- **Décomptes annuels LAA / IJM** → assureurs.
- **Statistique des salaires OFS (LSE)** → périodique.
- Tout ceci est transmis en **un seul envoi Swissdec/ELM** (ELM 5 **obligatoire pour l'impôt à la
  source dès 2026**). **ERPNext n'intervient pas** dans ces déclarations.

### 19.5 Les écritures comptables (exemple chiffré)

Salaire brut **10 000**, employé soumis à l'impôt à la source. *(Montants illustratifs — les vrais
viennent du logiciel de paie.)*

**Écriture mensuelle de paie** (Journal Entry) :

| Compte | Libellé | Débit | Crédit |
| --- | --- | ---: | ---: |
| **5000** | Salaires (brut) | 10 000 | |
| **5700** | AVS/AI/APG/AC (patronale) | 640 | |
| **5710** | CAF (patronale) | 160 | |
| **5720** | LPP (patronale) | 500 | |
| **5730** | LAA (patronale) | 80 | |
| **2271** | C/C AVS/AI/APG/AC (retenue 640 + patronale 640) | | 1 280 |
| **2272** | C/C CAF (patronale) | | 160 |
| **2270** | C/C LPP (retenue 500 + patronale 500) | | 1 000 |
| **2273** | C/C LAA/IJM (retenue 160 + patronale 80) | | 240 |
| **2279** | C/C Impôt à la source (retenue) | | 800 |
| **1020** | Banque — **net versé au salarié** | | 7 900 |
| | **Totaux** | **11 380** | **11 380** |

> Le **net** (7 900) = brut − retenues salariales (640 AVS/AC + 500 LPP + 160 LAA/IJM + 800 impôt
> source). Les **charges patronales** (1 380) s'ajoutent en charge **sans** réduire le net.
> *Variante* : si le net n'est pas payé le jour même, créditer un compte **« Salaires à payer »**
> plutôt que 1020, puis solder ce compte au paiement.

**Écritures de règlement** (quand on paie les caisses/le canton) :

| Règlement | Écriture |
| --- | --- |
| Caisse de compensation (AVS/AC + CAF) | Débit **2271** 1 280 + **2272** 160 / Crédit **1020** 1 440 |
| Caisse de pension (LPP) | Débit **2270** 1 000 / Crédit **1020** |
| Assureur (LAA/IJM) | Débit **2273** 240 / Crédit **1020** |
| Administration fiscale (impôt source) | Débit **2279** 800 / Crédit **1020** |

Après ces règlements, les comptes courants sociaux reviennent à **zéro** (réconciliation OK).

### 19.6 Obligations légales & échéances

| Obligation | Destinataire | Échéance | Qui l'exécute |
| --- | --- | --- | --- |
| Fiche de salaire | salarié | chaque mois | logiciel de paie |
| Versement du **net** | salarié | échéance contractuelle | **ERPNext** (banque) |
| Cotisations AVS/AC/CAF | caisse de compensation | acomptes + décompte annuel | **ERPNext** paie ; **paie** déclare |
| **Impôt à la source** | administration cantonale | **≤ 30 jours** (mensuel/trimestriel) | **ERPNext** paie ; **paie** déclare (ELM 5) |
| Primes LAA / IJM | assureur | prime annuelle | **ERPNext** paie ; **paie** déclare |
| **Certificat de salaire** (form 11) | salarié + fisc | **31 janvier** | logiciel de paie |
| **Décompte annuel AVS** | caisse de compensation | **30 janvier** | logiciel de paie |
| Statistique OFS (LSE) | OFS | périodique | logiciel de paie |

### 19.7 Points d'attention

- 🚫 **Salaires = HORS champ TVA.** Aucune écriture de paie ne porte de code TVA / d'`afc_box` — ça
  n'apparaît **pas** dans le décompte TVA.
- 🔁 **Réconciliation mensuelle des 227x** : c'est le contrôle clé. Un solde résiduel = une dette non
  encore réglée à une caisse. Le **logiciel de paie reste la source de vérité** ; ERPNext doit **coller**.
- 📥 **Importer** le journal de paie exporté par le logiciel (plutôt que ressaisir) → zéro erreur de
  recopie, montants exacts.
- 🧾 **Certificat de salaire & déclarations ELM** : produits par le **logiciel de paie**, **jamais**
  par ERPNext (non certifié Swissdec).
- ➕ **Comptes à créer au besoin** : `2273` (C/C LAA/IJM) pour suivre l'assureur séparément ;
  `2069`/`227x` (C/C Saisie sur salaire) **uniquement** en cas de saisie réelle.
- 🏷️ Les charges de personnel portent un **cost center** (ex. `Main`) comme toute charge.

---

## 20. Gestion de la clôture (bouclement)

Le bouclement de fin d'exercice (ou de période) enchaîne plusieurs opérations. Cette section est une
**check-list opérationnelle** ; le « pourquoi » comptable de chaque point est détaillé dans les sections
référencées (pas de doublon ici).

**Ordre recommandé :**
1. **Saisir toutes les pièces** de la période (factures, paiements, avoirs) — les devises au **cours moyen mensuel** AFC (§11).
2. **Réévaluation de change** des postes ouverts en devise (change latent) → **§20.1** ci-dessous.
3. **Reclassement des acomptes** — uniquement si la séparation 2030/1130 est **désactivée** (§11 acomptes / §15 #13).
4. **Règlement TVA** de la période : écriture de solde 2200/1170/1171 → **2201**, puis paiement AFC (§15 #7).
5. **Réserves latentes** fiduciaires (réserve marchandises 1/3, ducroire) — écritures manuelles.
6. **Bouclement du résultat** : virement du résultat sur **2979** via **Period Closing Voucher** ; l'**affectation** (2979 → 2970 reporté / réserves / dividende) est **séparée**, post-AG (§15 #11).

> Les écritures des points 2, 3 et 5 sont en général **contre-passées** à l'ouverture de l'exercice suivant.

### 20.1 Réévaluation de change des postes ouverts (change latent) — guide pas à pas

**Ce que ça fait** *(rappel — concept complet en §11)* : valorise les créances / dettes / banques **en devise
encore ouvertes** au **cours de clôture** (côté **bilan**) et porte le **gain/perte latent** net sur **6998**
(côté **résultat**). **Aucun impact TVA** (le change est purement financier).

**Prérequis** *(posés par le setup)* : le compte **6998 « Différences de change non réalisées »** est créé et
rattaché à `Company.unrealized_exchange_gain_loss_account` — sans lui, l'outil **refuse de tourner**.

**Étapes :**
1. **Comptabilité → Exchange Rate Revaluation → New.**
2. Renseigne **Company** et **Posting Date** = date de clôture (ex. `31.12.2026`).
3. Clique **Get Entries** → l'outil liste tous les **soldes ouverts en devise** (par compte + tiers) à leur valeur CHF actuelle (cours d'origine).
4. Clique **« Appliquer cours de clôture AFC »** *(bouton ajouté par erpnextswiss)* → il remplit `new_exchange_rate` sur chaque ligne avec le **cours du jour AFC** de la date de clôture (**lecture seule — rien n'est stocké** dans _Currency Exchange_), et le **gain/perte se recalcule** tout seul.
   - *Jour non publié* (week-end/férié au 31.12) → repli automatique sur le **dernier jour ouvré**.
   - *Sans le bouton* → saisir `new_exchange_rate` à la main sur chaque ligne (cours lu sur `…/api/xmldaily?d=AAAAMMJJ`).
5. **Vérifie** le gain/perte (colonne _Gain/Loss_ + le _Total Gain/Loss_).
6. **Submit** l'Exchange Rate Revaluation. ⚠️ **À ce stade, aucune écriture** au grand livre — ce document n'est qu'une **analyse**.
7. Un bouton **Create → Journal Entries** apparaît → clique-le → une **Journal Entry en BROUILLON** est créée (message « Journal entries have been created »).
8. **Ouvre cette Journal Entry**, contrôle les lignes (**6998** = gain/perte latent net ; comptes tiers/banque revalorisés au cours de clôture), puis **Submit** → **c'est seulement ici** que le bilan et le résultat sont impactés.
9. **Contre-passation** : à l'ouverture de l'exercice suivant, ouvre la Journal Entry de réévaluation → **Reverse Journal Entry** → date `01.01` → Submit. On repart de la valeur d'origine ; le vrai écart se figera au **paiement** (réalisé → **6999**), sans double comptage.

**Rappels :** cours de clôture ≠ cours moyen mensuel · **jamais** de case AFC sur 6998 · **ne pas** stocker le cours de clôture dans _Currency Exchange_ (sinon il polluerait les transactions du 31.12) — tout est expliqué en **§11**.

---

### 20.2 Prestations à soi-même / part privée

**Concept** — quand des biens/services dont tu as **déduit l'impôt préalable** servent finalement à des fins
**non imposables** (usage **privé**, **cadeaux**, **prélèvements** gratuits), la TVA doit être **corrigée**
(art. 31 LTVA). Deux familles : **part privée** (bien à usage **mixte** privé/professionnel, ex. véhicule)
et **prélèvement / prestation à soi-même** (biens **sortis** du cadre imposable).

**Spécifique à ce métier (distribution cosmétique)** — deux gros postes :
- **Véhicules** utilisés aussi en privé → **part privée véhicule** (correction **récurrente**).
- **Échantillons / testers / factices / cadeaux / PLV prélevée sur stock** : échantillons & testers pour
  **promouvoir la vente** = **déductibles** (publicité) ; **cadeaux > ~500 CHF/destinataire/an** → correction ;
  **prélèvement de produits finis** hors cadre imposable → correction.

**Deux méthodes — à trancher avec la fiduciaire (§15 #15) :**

**A. Produit imposable (recommandée pour le véhicule).** La part privée est une **prestation imposable**
→ déclarée en **chiffre d'affaires** (case 200/301) avec **TVA due** (2200). Économiquement correcte,
**réconciliée** proprement (GL ↔ décompte, plausibilité au vert).
- *Forfait véhicule* : **0,8 %/mois** du prix d'achat **HT** (min. ~150 CHF/mois) = montant **TTC** de la part privée.
- Exemple — voiture 40'000 HT → 0,8 %/mois = 320 → **3'840 TTC/an** → net 3'552.27 + TVA 8,1 % = **287.73** :
  ```
  Débit    C/C actionnaire (bénéficiaire)      3'840.00
    Crédit   Produit part privée véhicule (CA)          3'552.27
    Crédit   2200  TVA due (case 301)                     287.73
  ```

**B. Correction de l'impôt préalable (case 415).** Réduit la **déduction** (le formulaire **soustrait** la
case 415 du total 479). C'est l'approche du client sur ProConcept (compte `106100`).
- ⚠️ **Limite ACTUELLE de notre config** *(vérifiée empiriquement)* : le mécanisme (template **IPPS** appliqué
  à une **facture d'achat** → compte **1174**, case 415) donne le **bon chiffre** de décompte (case 415 = +TVA)
  **mais** une **écriture GL au signe inversé** — l'IPPS **débite** 1174 (comme un achat qui *augmente* la
  déduction), alors qu'une correction doit la **réduire** ; au règlement, GL et décompte **divergent**. De plus
  `viewVAT_415` ne lit **que les factures d'achat**, donc l'écriture **correcte** (un Journal Entry qui
  **crédite** 1174) **n'est pas captée**. → **À corriger** avant usage : étendre `viewVAT_415` pour capter la
  correction (sur le **modèle de l'escompte** — union d'un Journal Entry / mouvement GL sur 1174).

**Périodicité** — c'est une écriture de **bouclement** (trimestrielle/annuelle), en général **contre-passée**
à l'ouverture suivante si provisoire. Les cadres exacts (méthode, base véhicule, seuil cadeaux, politique
échantillons) sont un **point de validation fiduciaire (§15 #15)**.

---

## 21. Gestion des stocks — inventaire PERPÉTUEL (négoce)

> **Cadre.** La gestion du stock est le **cœur de métier** (achat-revente de marchandises). On retient
> donc l'**inventaire perpétuel** : la comptabilité de stock suit la logistique **en temps réel**. Le
> setup (`setup_perpetual_inventory`) l'**active par défaut** et crée les comptes techniques.
> **Impact TVA : aucun** (§21.5).

### 21.1 Le principe

- **Périodique** (non retenu) : le stock au bilan n'est juste qu'**à la clôture** ; la marge est globale.
- **Perpétuel** (retenu) : **chaque mouvement physique** touche la compta → stock au bilan **toujours
  juste**, **COGS et marge connus par vente**, clôture **automatique** (plus d'écriture de variation
  manuelle). ERPNext ne génère ces écritures que pour les **articles de stock** (`is_stock_item = 1`).

### 21.2 Les comptes (posés par le setup)

| Compte | Rôle | Paramétrage |
|---|---|---|
| **1200** Stocks de marchandises | valeur du stock (bilan) | `account_type = Stock` · Company `default_inventory_account` |
| **4200** Achats de marchandises | **COGS** (coût des ventes) | `default_expense_account` (déjà en place) |
| **4208** Variations de stocks | ajustement de stock | `account_type = Stock Adjustment` · Company `stock_adjustment_account` |
| **2301** SRBNB « Marchandises reçues, non facturées » | tampon **réception ↔ facture** | `account_type = Stock Received But Not Billed` · Company `stock_received_but_not_billed` |
| **2302** EIIV « Frais accessoires inclus dans la valorisation » | tampon **landed cost ↔ facture** | `account_type = Expenses Included In Valuation` (**trouvé par account_type**, pas de champ Company) |

**2301 et 2302** sont des **passifs de régularisation** (famille **230**, CO art. 958b) — « reçu / engagé,
pas encore facturé ». Ils **tendent vers zéro** : `2301 + 2302 = 0` ⇔ tout ce qui est reçu/engagé a été
facturé (contrôle de réconciliation simple). *Alternative fiduciaire :* près des créanciers (`2005`).

### 21.3 Flux ACHAT (2 documents)

Marchandise **1000** net + 81 TVA :
```
1) Purchase Receipt (réception)      Dr 1200 Stock            1000
                                        Cr 2301 SRBNB               1000     ← au net, SANS TVA
2) Purchase Invoice (liée)           Dr 2301 SRBNB            1000
                                     Dr 1170 Impôt préalable    81
                                        Cr 2000 Dette fournisseur    1081
```
*(Écriture de réception **validée en réel** : Dr 1200 / Cr 2301.)* Le SRBNB (2301) revient à **zéro** dès
la facture saisie.

### 21.4 Flux VENTE (2 documents)

Vente **2000** + 162 TVA, coût du stock vendu **1200** :
```
1) Delivery Note (bon de livraison)  Dr 4200 COGS             1200
                                        Cr 1200 Stock              1200     ← sortie au coût, SANS TVA
2) Sales Invoice (liée)              Dr 1100 Client           2162
                                        Cr 3200 Ventes             2000
                                        Cr 2200 TVA due             162
```

### 21.5 Frais accessoires (landed cost) → EIIV

Transport / douane à **capitaliser dans le stock** (le vrai coût = prix + fret + douane) :
```
Landed Cost Voucher (sur la réception)  Dr 1200 Stock          80
                                           Cr 2302 EIIV              80
Facture du transporteur                 Dr 2302 EIIV           80
                                        Dr 1170 Impôt préalable  …      ← TVA du transport, normale
                                           Cr 2000 Transporteur        …
```
Le stock est valorisé **prix + frais** ; l'EIIV (2302) revient à **zéro**. *(Droits de douane = coût du
stock, **pas** de la TVA ; **TVA à l'import** = impôt préalable normal, case 400.)*

### 21.6 Impact TVA : **aucun**

La TVA vit sur les **factures** (achat / vente). Les **mouvements de stock** (réception, livraison, COGS,
landed cost) **ne portent aucune TVA**. Le **décompte TVA est identique** au mode périodique. Les comptes
1200 / 2301 / 2302 / 4200 ne sont **pas** des comptes de TVA → pas d'`afc_box`, **aucun effet** sur le
décompte ni sur les contrôles de plausibilité.

### 21.7 Articles de stock vs services

Le perpétuel **n'agit que sur `is_stock_item = 1`**. Les **services / prestations / frais** (`is_stock_item
= 0`) se facturent **directement** (facture d'achat / vente, sans réception ni livraison, sans COGS). On
peut **mélanger** stock et services sur la **même facture** — ERPNext traite ligne par ligne. *(Laisser
`Enable Provisional Accounting for Non-Stock Items` **désactivé**.)*

### 21.8 Le changement opérationnel (à valider fiduciaire / client)

- **Flux achat** : réception (**Purchase Receipt**) **puis** facture — 2 documents.
- **Flux vente** : bon de livraison (**Delivery Note**) **puis** facture — 2 documents.
- **Discipline** : tout mouvement physique = un document, **en continu** (sinon le stock GL diverge du réel).
- **Ordre** : réceptionner **avant** de vendre (sinon stock négatif).
- **Entrepôts** deviennent des **entités comptables** ; **articles** en `is_stock_item = 1`, valorisation
  **FIFO** (négoce).
- **Raccourci** : une facture avec la case **« Update Stock »** fait réception+facture (ou livraison+facture)
  **en un seul document** — pratique si réception = facturation le même jour ; mais le **flux 2-documents**
  reste requis pour les **frais accessoires** (Landed Cost) et les livraisons décalées.

---

_Document produit dans le cadre de la configuration ERPNext 16 (compta suisse inspirée de bexio).
Les comportements d'ERPNext sont vérifiés dans le code source (`apps/erpnext`, `apps/erpnextswiss`).
Les règles de TVA suisse (reverse charge, import, décompte, opté) relèvent de la connaissance métier
et doivent être confirmées avec le fiduciaire avant mise en production._
