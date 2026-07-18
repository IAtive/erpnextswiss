# Fork ERPNextSwiss — modifications (branche `v16-compat`)

> Ce document trace **toutes les divergences** du fork **`IAtive/erpnextswiss` (branche `v16-compat`)**
> par rapport à l'upstream libracore/erpnextswiss. Objectif : savoir exactement ce qui est modifié
> (indispensable pour les futurs merges upstream) et pourquoi.
>
> **Consolidation (2026-07)** : l'app métier **`swiss_compliance_setup`** a été **fusionnée dans le fork**
> sous le module dédié **`Swiss VAT Config`** (voir §9). Désormais **tout** vit dans erpnextswiss :
> l'**infrastructure** (décompte TVA, QR-facture, ISO 20022, Lohnausweis) **et** la **logique métier /
> config** (codes AFC, plausibilité, print format, `company_setup`). Le module `Swiss VAT Config` isole
> cette partie métier pour garder un merge upstream propre. La doc AFC / plan comptable est dans
> **`docs/ch_accounting_setup.md`** (rapatriée depuis l'ex-app).

---

## 1. Compatibilité ERPNext 16 / Frappe v16 (correctifs)

L'upstream ciblait v13-15. Correctifs ponctuels pour tourner en v16 :

| Fichier | Correctif | Raison |
|---|---|---|
| `doctype/vat_declaration/vat_declaration.py` | `str(self.start_date) < "2024-01-01"` | en v16 `start_date` est un `date`, pas une `str` → `TypeError` à l'export XML |
| `page/bank_wizard/bank_wizard.py` (`get_default_accounts`) | lecture de `default_expense_claim_payable_account` **gardée** par `frappe.get_meta("Company").has_field(...)` | ce champ vient de l'app **hrms** ; erpnextswiss **ne dépend pas** de hrms → crash SQL (colonne inconnue) si hrms absent. Fallback sur le compte fournisseur. |
| `pyproject.toml` | retrait de la dépendance `frappe` | conflit d'install en v16 |
| `zugferd/zugferd.py` | fix import `factur-x` | API de la lib changée |
| `hooks.py` (`app_include_js`) | retrait de `erpnextswiss_templates.min.js` | bundle legacy **non généré** par le build v16 → **404** à chaque page desk. Rien ne l'utilise (aucun `frappe.templates[...]` client ; la table du Bank Wizard est rendue **server-side**). |

---

## 2. Déclaration TVA (`doctype/vat_declaration`) — câblage complet & conformité

### 2.1 Case 205 (opté art. 22) — correction de bug upstream
`vat_declaration.js` : l'upstream **soustrayait** le 205 du 299 (`update_taxable_revenue`). Or le 205
est un **mémo** (prestations optées, **déjà incluses** dans le 200) : il ne doit **pas** être soustrait
(299 = 200 − 289, et 289 n'inclut pas le 205, conforme au formulaire AFC). Corrigé : `get_total(205)`
réactivé, soustraction retirée, champ relibellé.

### 2.2 Câblage des cases manquantes (`get_values`)
L'upstream n'appelait pas certaines cases pourtant alimentées. Ajouté :
```js
get_tax(frm,   "viewVAT_410", 'missing_pretax');            // dégrèvement ultérieur (DUIP) — indispensable
get_tax(frm,   "viewVAT_415", 'pretax_correction_mixed');   // correction préalable
get_tax(frm,   "viewVAT_420", 'pretax_correction_other');   // correction préalable
get_total(frm, "viewVAT_900", 'grants');                    // subventions (Section III)
get_total(frm, "viewVAT_910", 'donations');                 // dons (Section III)
```
> **410 est critique** depuis que la case est portée par la ligne (`DUIP → 410`) : sans ce câblage,
> le 479 raterait le dégrèvement et le 500 serait surévalué.

### 2.3 Ventilation 500 / 510 (à payer / en faveur)
`vat_declaration.js` (`update_payable_tax`) : ventile le net en deux cases **positives et exclusives**
comme le formulaire officiel — `net ≥ 0 → 500 = net, 510 = 0` ; `net < 0 → 500 = 0, 510 = |net|`.
`vat_declaration.py` (`create_transfer_file`) : `z500 = payable_tax − balance` = **net signé** pour le
XML (négatif = crédit, autorisé par eCH-0217 `amountType` sans borne inférieure).

### 2.4 Nomenclature FR officielle + réorganisation de l'écran
`vat_declaration.json` :
- **64 libellés** relibellés en **wording officiel AFC** (`200 · Total des contre-prestations…`,
  `500 · Montant à payer à l'AFC`…) — les `fieldname` **restent inchangés** (JS/XML référencent par fieldname).
- **Réorganisation** : sections **I. Chiffre d'affaires / II. Calcul de l'impôt / III. Autres
  mouvements** ; taux **actuels (2024)** remontés en tête, **anciens taux ≤ 2023** dans une sous-section
  **repliable** ; champ **Société** remonté en **1er**.

---

## 3. Kontrolle MwSt (`report/kontrolle_mwst`) — journal TVA

| Fichier | Modification |
|---|---|
| `kontrolle_mwst.js` | dropdown des cases **data-driven** (généré à partir des `VAT query`) au lieu d'une liste en dur → toutes les cases AFC apparaissent (dont 205) |
| `kontrolle_mwst.py` | colonnes **enrichies** (compte, description, code, devise, montant, taxe) + **ligne de total** native |

Équivalent du « journal de TVA » de bexio.

---

## 4. XSD eCH-0217 v2.0.0 (`public/xsd/`)

Ajout du schéma officiel **`eCH-0217-2-0-0.xsd`** + ses dépendances (eCH-0058, eCH-0108, et transitives
0007/0008/0010/0044/0097/0129) + exemple. Retrait de l'ancien `eCH-0217-1-0.xsd`. Le XML du décompte est
**validé** contre ce XSD v2.

---

## 5. Bank Wizard (`page/bank_wizard`) — matching & design

> 📖 **Guide utilisateur des boutons de rapprochement** (quand chaque bouton s'affiche, quand l'utiliser,
> effet produit) : voir **`page/bank_wizard/README.md`**.

### 5.1 Matching par tolérance + par nom de tiers (inspiré bexio)
`bank_wizard.py` :
- helper **`_match_within_tolerance()`** : rapproche une facture ouverte du tiers dont le montant est
  dans **CHF 5 OU 2 %** (la plus favorable) → gère **escompte, frais, arrondi**. Match **unique** exigé.
- **Fallback** appliqué **vente ET achat** : si aucun match par référence mais **tiers identifié par
  nom**, propose sa facture ouverte dans la tolérance. Flag `amount_tolerance` sur la transaction.
- Le bouton « Book » (rapprochement 1 clic) s'active **aussi en tolérance**, pas seulement au centime.

> Limite connue : l'**auto-booking de l'écart** (escompte) n'est pas encore fait — le Payment Entry
> créé est un **brouillon** que l'utilisateur relit/complète avant Submit.

### 5.2 Refonte du design (theme-aware)
`bank_wizard.html` (page d'accueil) + `transaction_table.html` (tableau) :
- page d'accueil : **carte pro** (icône, zone de dépôt, formats acceptés), largeur adaptative
  (respecte le toggle large/centré) ;
- tableau : colonne **« Rapprochement »** avec **badges de statut** (✓ exact / ≈ tolérance / tiers /
  non identifié), montants colorés entrée/sortie ;
- **couleurs via variables de thème Frappe** (`var(--card-bg)`, `var(--bg-green)`, `var(--text-on-green)`…)
  → **compatible dark mode**.

> ⚠️ **Piège Frappe** : les `.html` de page sont compilés en template JS `frappe.templates["…"] = '…'`
> (chaîne entre **apostrophes simples**). **Jamais d'apostrophe ASCII `'`** dans ces fichiers (casse le
> bundle : `SyntaxError`) → guillemets doubles + `'` (U+2019) ou entités HTML. `bench build --app erpnextswiss`
> après modification.

### 5.3 Compte de tiers au rapprochement de facture (compatibilité « Book Advance in Separate Party Account »)
`bank_wizard.py` (`make_payment_entry`) :
- **Problème** : le Wizard créait le Payment Entry **sans référence**, puis ajoutait la facture **après**
  l'insert. Avec l'option ERPNext **« Book Advance Payments in Separate Party Account »** activée, un
  paiement non alloué est logé sur le **compte d'acompte** (2030 encaissement / 1130 décaissement). La
  facture (sur **1100** / **2000**) ajoutée ensuite provoquait le blocage
  *« Sales Invoice … is associated with 1100 …, but Party Account is 2030 »*.
- **Correctif** : quand il y a des **références de facture** sur un tiers `Customer`/`Supplier`, on pose le
  **compte de tiers normal** via `get_party_account(...)` (**jamais** le compte d'acompte) **et** on ajoute
  les références **AVANT l'insert** (nouvelle fonction **`append_reference()`**, même allocation que
  `create_reference`). ERPNext résout alors le bon compte à l'insert et ne le réécrit pas.
- **Vrai acompte préservé** : un encaissement/décaissement **sans référence** (bouton *Customer/Supplier*)
  n'est **pas** touché → reste sur **2030/1130**. Comportement **robuste que la séparation soit activée ou non**
  (sans elle, `get_party_account` rend déjà 1100/2000).
- Import ajouté : `from erpnext.accounts.party import get_party_account`.

> Côté module `Swiss VAT Config` : le setup épingle `default_receivable_account = 1100` /
> `default_payable_account = 2000` (sinon 2030, typé `Receivable`, est choisi par défaut pour les
> **factures** — bug distinct, corrigé séparément). Voir `docs/ch_accounting_setup.md` §11.

### 5.4 Taux de change au rapprochement d'une facture en devise (gain/perte de change)
`bank_wizard.py` (`read_camt053` + `make_payment_entry`) + `bank_wizard.js` :
- **Problème** : pour une facture en **devise** (ex. créancier EUR 2001) payée depuis une **banque CHF**,
  le Wizard passait le **montant CHF débité** comme montant EUR, au **taux 1** : `received_amount = amount`,
  `source/target_exchange_rate = exchange_rate (1)`. La logique de taux regardait en plus le **mauvais
  compte** (côté banque `paid_from` au lieu du côté tiers). Résultat : **facture mal soldée** (le CHF pris
  pour de l'EUR → allocation partielle) **et gain/perte de change absent ou faux**.
- **Correctif — 3 couches** :
  1. **`read_camt053`** : extrait, par transaction, `xchg_rate` (`<CcyXchg>/<XchgRate>`), `instructed_amount`
     (`<AmtDtls>/<InstdAmt>`, montant d'origine en devise) et **`booked_amount`** = le montant **réellement
     BOOKÉ en CHF** (`<Ntry><Amt>`, ex. 4988.93) quand la transaction est dans une **devise ≠ celle du compte**.
     ⚠️ **`amount` reste EN DEVISE** (le `<TxAmt>`, ex. EUR 5400) — indispensable pour que le **MATCHING**
     compare bien 5400 EUR à la facture en EUR ; le CHF réel voyage à part dans `booked_amount`.
     ⚠️ Le parser HTML de BeautifulSoup **hisse `<XchgRate>` hors de `<TxDtls>`** → cherché dans
     `transaction_soup` puis **en repli au niveau `entry_soup`** (sinon toujours `None`).
  2. **`bank_wizard.js`** : passe `xchg_rate`, `instructed_amount` **et `booked_amount`** à `make_payment_entry`.
  3. **`make_payment_entry`** : identifie le **côté TIERS** (créance pour Receive, dette pour Pay) ; s'il est
     en devise et différent de la banque, pose le **montant EN DEVISE** (`InstdAmt` du camt, sinon l'ouvert
     de la facture) côté tiers, et le **CHF réellement débité** (`booked_amount`, sinon `amount`) côté banque
     au taux 1. Taux tiers = `XchgRate` du camt s'il concorde avec les montants, sinon **dérivé** = CHF booké
     ÷ montant devise (= 4988.93/5400 = **0.923876**, fiable même sans `XchgRate`).
  4. **`append_reference`** : l'allocation est plafonnée par le montant **dans la devise du tiers**
     (`received_amount` pour Pay, `paid_amount` pour Receive), plus par le CHF débité.
  5. **Ordre — résolution du compte tiers AVANT la détection de devise** (correctif clé) : le JS envoie le
     **compte par défaut générique** (`2000`/`1100`, en **CHF**) dans `paid_from`/`paid_to`. La détection de
     devise doit donc appeler `get_party_account(...)` **en tête** de `make_payment_entry` pour obtenir le
     **compte spécifique du tiers** (ex. créancier EUR `2001`) **avant** de lire `party_currency`. Sinon la
     devise du tiers est lue sur le compte CHF générique → `party_currency == company_currency` → le bloc
     multi-devises **ne se déclenche jamais** → `paid_amount`/`target_exchange_rate` restent à plat
     (ex. `5400` CHF / taux `1` au lieu de `4988.93` CHF / `0.923876`). Le compte résolu est réutilisé plus
     bas pour l'`append_reference` (une seule résolution).
- **Résultat** : facture **soldée** dans sa devise, dette/créance soldée en CHF, **gain/perte de change sur
  6999** calculé contre le taux facture. Fallback fiable **même si la banque ne fournit pas `XchgRate`**.
- Robuste en mono-devise (comportement inchangé). Prérequis : les tiers en devise doivent avoir leur compte
  de tiers **en devise** rattaché (Customer/Supplier → *Accounts* : 1101/2001) pour que `get_party_account`
  (§5.3) renvoie le bon compte.

---

## 6. Retrait du doctype `Contract` (collision avec ERPNext natif)

erpnextswiss définissait un doctype **`Contract`** de **même nom** que le Contract natif d'ERPNext (CRM),
qu'il **écrasait** silencieusement. Comme le client n'en a pas besoin, le fork le **retire** pour
restaurer le Contract natif :
- suppression de `doctype/contract/`, `doctype/contract_period/`, `doctype/contract_service/` ;
- retrait du lien Contract dans `workspace/erpnextswiss/erpnextswiss.json` et l'item dans `config/erpnextswiss.py`.

*Service Invoicing (rapport basé Timesheet) est indépendant et conservé.* Sur une install existante,
`bench migrate` re-synchronise le Contract natif ; les doctypes orphelins (`Contract Period/Service`) sont
à supprimer manuellement.

---

## 7. Configuration métier (module `Swiss VAT Config`)

Ces éléments vivent désormais **dans le fork** (module `Swiss VAT Config`, ex-`swiss_compliance_setup` — cf. §9) :

| Élément | Fichier | Rôle |
|---|---|---|
| Print Format **« Décompte TVA (AFC) »** + défini **par défaut** | `swiss_vat_config/print_formats.py` | PDF au format officiel AFC/bexio pour le doctype VAT Declaration (créé à l'install/migrate) |
| Génération des `VAT query` (`viewVAT_*`) en **`COALESCE(ligne, compte)`** | `swiss_vat_config/vat_declaration.py` | alimente le décompte par case (voir `docs/ch_accounting_setup.md` §7) |
| Contrôle de plausibilité (7 contrôles) + report | `swiss_vat_config/plausibility.py` · `swiss_vat_config/report/controle_plausibilite_tva/` | réconciliation GL ↔ décompte, hook validate/before_submit + rapport UI |
| Compte intermédiaire Bank Wizard = **1099** | `swiss_vat_config/company_setup.py` (`set_erpnextswiss_settings`) | pose `ERPNextSwiss Settings.intermediate_account` |

---

## 8. Cours de clôture AFC pour la réévaluation de change (change latent)

**Problème** : la réévaluation de fin d'année (doctype natif *Exchange Rate Revaluation*) doit valoriser
les postes en devise au **cours de clôture** (cours du jour au 31.12), **différent** du cours moyen mensuel
utilisé pour les transactions. Or **stocker** ce cours de clôture dans *Currency Exchange* le ferait
utiliser à tort par les factures datées du 31.12 (incohérence méthode « cours moyen mensuel »).

**Solution — bouton non invasif sur *Exchange Rate Revaluation*** :
- `scripts/swiss_exchange_rates.py` → **`year_end_rates(date, currencies)`** (`@frappe.whitelist`) :
  **lecture seule**, lit le cours du jour BAZG (`xmldaily?d=YYYYMMDD`) via `_parse_estv_xml`, **sans écrire
  aucun Currency Exchange**. Repli sur le **dernier jour ouvré** si la date n'est pas publiée (max 6 j).
- `public/js/exchange_rate_revaluation.js` (hook **`doctype_js`**) : bouton **« Appliquer cours de clôture
  AFC »** qui remplit `new_exchange_rate` sur chaque ligne (par devise) via `frappe.model.set_value` →
  **déclenche le recalcul natif** d'ERPNext (gain/perte). Additif : le contrôleur core n'est pas touché.
- **Cohérence préservée** : le cours de clôture ne vit que dans le formulaire de réévaluation, jamais en
  base → les transactions de décembre restent au cours moyen mensuel. Cf. `ch_accounting_setup.md` §11.

---

## 9. Consolidation : app `swiss_compliance_setup` fusionnée dans le fork (module `Swiss VAT Config`)

L'app métier séparée **`swiss_compliance_setup`** (repo GitLab privé) a été **repliée dans le fork** pour
n'avoir **qu'une seule app** à maintenir. Toute la logique métier vit maintenant sous un **module dédié**
`Swiss VAT Config` (`erpnextswiss/swiss_vat_config/`), isolé des modules upstream (`ERPNextSwiss`, `Scripts`)
pour garder un merge libracore propre.

**Ce qui a migré** (imports repointés `swiss_compliance_setup.*` → `erpnextswiss.swiss_vat_config.*`) :
- **Doctype `AFC VAT Box`** + **report `Controle plausibilite TVA`** (le module `Swiss VAT Config` change
  simplement d'app propriétaire — aucun champ `module` touché).
- **Python** : `company_setup.py`, `vat_setup.py`, `plausibility.py`, `vat_declaration.py`,
  `financial_reports.py`, `print_formats.py`, `escompte.py`.
- **Tests** (`tests/`) et **docs** (→ `docs/`, dont `ch_accounting_setup.md`).

**Hooks fusionnés** (`hooks.py`) :
- `after_install` / `after_migrate` passés en **listes** : `…swiss_exchange_rate_settings…ensure_defaults`
  + `…swiss_vat_config.vat_setup.after_install/after_migrate` (seed AFC VAT Box + custom fields
  `afc_box`/`afc_box_secondary` + templates financiers).
- `doc_events` : `VAT Declaration` → plausibilité (`validate`/`before_submit`) ; `Payment Entry` →
  `escompte.route_purchase_discount_to_4900`.
- `fixtures` : `["Custom Field", "AFC VAT Box"]`.

**Nouveaux chemins** (bench) : `erpnextswiss.swiss_vat_config.company_setup.setup_company`, etc.
**Workspace** : liens **Taxes → `Controle plausibilite TVA`** et **Configuration → `AFC VAT Box`** ajoutés.

> ⚠️ **Ne plus installer `swiss_compliance_setup`** (dépréciée) : elle déclare le même module `Swiss VAT
> Config` → conflit si les deux apps cohabitent sur un site. Une **install neuve** d'erpnextswiss suffit.

## 10. Cours de change AFC — import automatique (Swiss Exchange Rate)

Récupération **programmée** des cours mensuels moyens AFC/BAZG dans `Currency Exchange`, avec écran de
config, suivi et déclenchement manuel. *(À distinguer de §8 `year_end_rates`, qui est le cours de
**clôture** en lecture seule pour la réévaluation.)*

- **Doctypes** : `Swiss Exchange Rate Settings` (Single : config + dernier run + boutons), `Swiss Exchange
  Rate Import Log` (historique), + child `Swiss Exchange Rate Currency` / `Swiss Exchange Rate Import Row`.
- **`scripts/swiss_exchange_rates.py`** : `fetch_and_store()` — parse `xmlavgmonth`, **date au 1er du mois**
  (`<monat>`), **idempotent / jamais d'écrasement**, gère le diviseur (100 JPY) + sens inverse. Wrappers
  compat `read_rates` / `read_daily_rates`.
- **Planification** : `hooks.scheduler_events["daily"]` → `scheduled_fetch()` avec **porte interne**
  (enabled + frequency Daily/Weekly/Monthly). Choix « hook + porte » car `sync_jobs()` supprime les
  Scheduled Job Type hors hooks.
- **`after_migrate` → `ensure_defaults()`** : seed devises EUR/USD/GBP + création du job.
- **Réglages liés** (posés par `company_setup.set_accounting_settings`) : `Accounts Settings.allow_stale = 1`,
  `Currency Exchange Settings.disabled = 1`, et normalisation `Currency CHF` (`fraction = centime`,
  `symbol = CHF`).
- **Workspace** : liens `Swiss Exchange Rate Settings` + `Swiss Exchange Rate Import Log` (Configuration).
- **Doc** : `docs/swiss_exchange_rates.md`.

## Récapitulatif des fichiers du fork modifiés

```
pyproject.toml
zugferd/zugferd.py
erpnextswiss/doctype/vat_declaration/vat_declaration.py        # v16 date fix, z500 net signé
erpnextswiss/doctype/vat_declaration/vat_declaration.js        # 205, câblage 410/415/420/900/910, ventilation 500/510
erpnextswiss/doctype/vat_declaration/vat_declaration.json      # nomenclature FR + réorg sections + Société 1er
erpnextswiss/report/kontrolle_mwst/kontrolle_mwst.js           # dropdown data-driven
erpnextswiss/report/kontrolle_mwst/kontrolle_mwst.py           # colonnes enrichies + total
erpnextswiss/page/bank_wizard/bank_wizard.py                   # hrms fix, tolérance CHF 5/2%, nom de tiers, compte de tiers (§5.3), taux de change camt (§5.4)
erpnextswiss/page/bank_wizard/bank_wizard.html                 # page d'accueil pro, theme-aware
erpnextswiss/page/bank_wizard/transaction_table.html           # tableau + badges, theme-aware
erpnextswiss/public/xsd/                                       # eCH-0217 v2 + dépendances
erpnextswiss/workspace/erpnextswiss/erpnextswiss.json          # retrait lien Contract (§6) ; + liens plausibilité / AFC VAT Box / Swiss Exchange Rate (§9/§10)
erpnextswiss/config/erpnextswiss.py                            # retrait item Contract
erpnextswiss/hooks.py                                          # Exch. Rate Reval. §8 ; retrait templates.min.js §1 ; fusion swiss_vat_config (after_install/migrate, doc_events, fixtures) §9 ; scheduler_events daily §10
erpnextswiss/scripts/swiss_exchange_rates.py                   # year_end_rates() clôture §8 + fetch_and_store()/scheduled_fetch() import auto §10
erpnextswiss/public/js/exchange_rate_revaluation.js            # bouton « Appliquer cours de clôture AFC » (§8)
erpnextswiss/modules.txt                                       # + module « Swiss VAT Config » (§9)
erpnextswiss/swiss_vat_config/                                 # (§9) module métier fusionné (ex-swiss_compliance_setup) :
    doctype/afc_vat_box/                                       #   référentiel des cases AFC
    report/controle_plausibilite_tva/                         #   rapport de plausibilité (lien Taxes)
    company_setup.py · vat_setup.py                            #   setup_company + seed AFC/custom fields
    plausibility.py · vat_declaration.py                       #   contrôles + VAT queries
    financial_reports.py · print_formats.py · escompte.py     #   CO959b, print format TVA, routage escompte
    tests/                                                    #   scénarios
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_settings/     # (§10) config + scheduled_fetch + boutons
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_import_log/   # (§10) historique + bouton
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_currency/     # (§10) child devises
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_import_row/   # (§10) child lignes (read-only)
erpnextswiss/docs/                                             # (§9) doc rapatriée : ch_accounting_setup.md, swiss_exchange_rates.md
(supprimés) erpnextswiss/doctype/contract{,_period,_service}/  # collision Contract natif
```

> Après toute modif de `.js` / `.html` / `.json` de doctype/page : `bench build --app erpnextswiss`
> + `bench --site <site> clear-cache`, puis **redémarrer `bench start`** si une app/hook change.
