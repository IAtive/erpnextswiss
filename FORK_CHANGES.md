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

## 11. TVA sur écriture manuelle (« code TVA sur Journal Entry », à la bexio)

Permet de comptabiliser la TVA via une **écriture manuelle** taguée (pas seulement via des factures), pour
les cas qui ne rentrent pas dans une facture : **prestations à soi-même / part privée (indépendant)**,
**dégrèvement (410)**, **corrections (415/420)**, cadeaux > 500, prélèvements. Équivalent du code TVA sur
écriture de bexio. **Account-agnostic** (le tag est sur la ligne, pas le compte). Détail : `docs/ch_accounting_setup.md` §22.

- **Référentiel `AFC VAT Box`** (2 champs) : **`reduces_total`** (dérive le signe : réduction → crédit, sinon
  débit) + **`je_taggable`** (filtre du menu). Seedés dans `vat_setup.py` (`REDUCES_TOTAL`/`JE_TAGGABLE`).
- **Custom field** `afc_box` sur **`Journal Entry Account`** (`vat_setup.CUSTOM_FIELDS`), filtré `je_taggable = 1`.
- **`vat_declaration.py`** : pattern **`PAT_JE_TAGGED_TAX`** union-é dans `_sql_for` pour les cases d'impôt
  taguables ; signe piloté par `reduces_total` (substitué avant `.format`). `generate_vat_queries` fetch les
  2 nouveaux champs.
- **`plausibility.py`** : Contrôle 1 exclut les Journal Entries du mouvement par compte (`exclude_je`) et
  soustrait la **part écriture** (`_je_tagged_amount`) — GL ↔ décompte cohérents, account-agnostic ;
  Contrôle 5 ignore les JE **taguées** (feature légitime).
- **`company_setup.py`** : templates **IPPS / RIP / DUIP supprimés** de `PURCHASE` (corrections inadaptées au
  modèle facture — signe inversé / dette fantôme) + `cleanup_obsolete_templates()` (suppression sur société existante).
- **Tests** : `scenario_correction_tva_ecriture` (415), `scenario_achat_degrevement_410` (410, réécrit en écriture),
  helper `Ctx.make_journal_entry`.
- **Phase 1** = cases d'impôt/correction (410/415/420). Extensible (cocher `je_taggable`) sans re-coder.

---

## 12. Bulletin QR local & configuration par compte (module `Swiss QR`)

Nouveau module `swiss_qr/` : la QR-facture suisse était générée par un **service PHP externe**
(`data.libracore.ch` / `qr-code.2itea.global`, dont un en **HTTP simple**), qui recevait IBAN, montant et
adresses en clair à chaque impression, sans repli. Le fork **remplace ce service par un rendu LOCAL** et
**explicite le choix de méthode** (comme bexio), tout en supprimant l'ambiguïté QR-IBAN / IBAN classique.
Détail utilisateur : `docs/swiss_qr_bill.md`.

### 12.1 Trois méthodes explicites par compte (comme bexio)
Custom fields sur **`Account`** (`swiss_qr/setup.py`) : **`qr_method`** (Select `SCOR`/`QRR`/`NON`, défaut SCOR),
**`qr_iban`** (QR-IBAN, visible/obligatoire si QRR).
- **SCOR** = IBAN classique + référence créancier RF (ISO 11649).
- **QRR** = QR-IBAN + référence structurée à 27 chiffres.
- **NON** = IBAN classique, sans référence.
- **Séparation stricte** : `iban` (classique) reste dédié aux **paiements** (pain.001 débiteur, prélèvement,
  e-facture) ; `qr_iban` sert **uniquement** à l'émission QRR. Fin du conflit « une QR-IBAN dans `iban`
  casse le débiteur du pain.001 ».

### 12.2 Génération serveur de la référence (`references.py`)
`doc_event` **Sales Invoice.validate** (`set_qr_reference`) — remplace l'ancienne génération cliente `onload`
(RF aléatoire, non conditionnel, cassée pour QRR). Selon `qr_method` du compte de réception
(`Company.default_bank_account`) : QRR via `esr_qr_tools.add_check_digit_to_esr_reference` (27 chiffres),
SCOR via `common_functions.get_scor_reference` (RF). Champ **unifié `qr_reference`** (stocké **sans espaces**)
lu par le print format et le rapprochement ; champs legacy (`esr_reference`/`reference_number`) alimentés en
miroir. **Immutabilité** : `qr_reference_type` + `qr_account_iban` figés à l'émission → une facture émise se
réimprime à l'identique même si la config du compte change ensuite.

### 12.3 Rendu local via `qrbill` (`render.py`)
Méthode Jinja **`get_qr_bill_svg`** (dépendance `qrbill>=1.2`, ajoutée au `pyproject.toml`) : dessine le
bulletin complet (récépissé + section paiement) en **SVG**, **aucune requête réseau**. Lit le **snapshot** de
la facture (repli config live pour les factures antérieures) ; **langue** = sélecteur d'impression
(`frappe.local.lang`, en/de/fr/it, repli anglais) ; débiteur optionnel si adresse client incomplète ;
encart d'erreur lisible (jamais de crash). Validation métier gratuite (qrbill refuse QRR sur IBAN normal).

### 12.4 Garde-fous & migration (`validation.py`)
`doc_event` **Account.validate** : rejette une QR-IBAN dans le champ `iban`, un `qr_iban` non-QR-IBAN
(institution hors 30000–31999), une méthode QRR sans `qr_iban`. Migration idempotente
(`migrate_classic_qr_iban`) : déplace toute QR-IBAN mal placée `iban` → `qr_iban` et bascule en QRR.

### 12.5 Print format unique & suppression des formats externes
Nouveau **« Swiss QR Invoice »** (`print_format/swiss_qr_invoice/`, type Jinja) : facture + bulletin QR local,
branché sur `qr_method`. **Supprimés** : `qr_sales_invoice/` (QRR cassé : envoyait `doc.name`),
`qr_sales_invoice_switzerland_rounding_description_details/` (SCOR externe) et le template mort
`templates/qrr_invoice/`.

## 13. Import camt & enrichissement du rapprochement (module `Treasury`)

Nouveau module `treasury/` : import de relevés **camt.053** autonome (parser ElementTree, **sans licence
fintech**), correct en **multidevises**, avec enrichissement des Bank Transactions pour le rapprochement.
Détail utilisateur : `docs/bank_reconciliation.md`.

### 13.1 Import camt.053 / ZIP avec FX correct (`camt_import.py`)
`upload_camt_file` (ZIP multi-relevés ou XML, routage par IBAN) crée des **Bank Transaction natives**.
- **Montant/devise TOUJOURS en devise du compte** (montant BOOKÉ `<Ntry><Amt>`) → plus d'erreur
  « Transaction currency EUR cannot be different from CHF ».
- **Champs FX** (custom fields sur Bank Transaction) : `original_currency`, `original_amount`,
  `bank_exchange_rate` renseignés quand la devise d'origine ≠ devise du compte (taux `<XchgRate>`, sinon
  dérivé booké/origine).
- **Priorité de référence** : QRR structurée (`RmtInf/Strd/CdtrRefInf/Ref`) > `EndToEndId` > `AcctSvcrRef`.
- **Normalisation** : une référence structurée (QRR/SCOR) est stockée **sans espaces** → égalité exacte avec
  `qr_reference` / `esr_reference_number` côté matching. Déduplication par `transaction_id` (md5 stable).

### 13.2 Enrichissement : tiers & PmtInfId (`reconcile_enrich.py`)
À l'import, pose `party_type`/`party` sur la Bank Transaction (aide le classement ALYF, utile même **sans**
référence) :
- **`resolve_party`** : IBAN de la contrepartie → Bank Account → tiers ; **fallback nom EXACT unique** selon
  le sens (CRDT → Customer, DBIT → Supplier). Constat terrain : les banques omettent souvent l'IBAN du
  **débiteur** sur les encaissements → le fallback nom est indispensable côté ventes. Jamais de résolution
  ambiguë (aucun fuzzy).
- **`resolve_pmtinfid`** : `Refs/PmtInfId` (custom field `treasury_pmtinfid`) ; format `PMTINF-{proposal}-{n}`
  → Payment Proposal → Payment Entry (départagé par montant) → bouclage des **paiements sortants** émis via
  le Payment Proposal ERPNextSwiss.

### 13.3 Réconciliation FX au taux banque (`fx_reconcile.py`)
`reconcile_at_bank_rate` + bouton `bank_transaction.js` : pour une transaction FX enrichie, crée le Payment
Entry alloué à la facture **au taux exact de la banque** → écart de change auto en **6999**, sans saisie de
taux. Doc_event `payment_entry_apply_bank_fx` (validate) pour un paiement on-account issu d'une transaction FX.

## 14. Intégration ALYF Banking (module `Treasury`, gardé `is_banking_installed`)

Glue **non-invasive** entre ERPNextSwiss et l'app ALYF Banking (aucune modif des fichiers ALYF) :
- **Config auto** (`after_migrate`, idempotente) : `Banking Settings.reference_fields`
  (**Sales Invoice → `qr_reference`**, **Purchase Invoice → `esr_reference_number`**) pour le matching par
  référence QR ; `voucher_matching_defaults` (**Facture de vente + d'achat** pré-activées).
- **Upload camt** : les uploads court-circuitent `override_whitelisted_methods` → **monkeypatch** de
  `banking.ebics.utils.upload_camt_file` au `boot_session` → l'écran ALYF utilise notre import FX/ZIP.
- **UI** : boutons *Import camt / ZIP* et *Reconcile* sur l'écran de réconciliation ; lien *Payment Proposal*
  auto-ajouté à la sidebar ALYF (re-posé après chaque migrate).
- **Pré-remplissage du taux** : `get_reconcile_amount_context` injecte le taux banque dans le dialogue ALYF.
- Tout est **gardé** `is_banking_installed()` → ERPNextSwiss reste autonome sans ALYF.

## 15. e-facture ZUGFeRD — IBAN du compte de réception (`zugferd/zugferd_xml.py`)

- **Problème** : l'IBAN de la e-facture était lu sur `sinv.debit_to` (compte de **créance** 1100, sans IBAN)
  → balise `<IBANID>` **toujours vide** (le client n'avait pas l'IBAN pour payer).
- **Correctif** : helper `_receiving_iban(company)` → IBAN classique du **compte de réception**
  (`Company.default_bank_account`), jamais la QR-IBAN (une e-facture ZUGFeRD/Factur-X est SEPA).
- Cohérence avec le bulletin QR (§12) : les deux pointent le compte de réception, chacun avec le bon IBAN.

## 16. Internationalisation — mécanisme `.po` (`locale/`)

Le format `translations/*.csv` n'est **plus lu** en v15+. Le fork migre vers le mécanisme **`.po` standard** :
- `migrate-csv-to-po` + merge : **revival** des ~600 traductions de/fr existantes (auparavant inertes).
- **Sources anglaises** dans le code (`_()` Python, `__()` JS, labels & descriptions de champs) ;
  traductions **fr/de/it** dans `locale/{fr,de,it}.po` (+ `main.pot`).
- Tous les messages des modules `swiss_qr`/`treasury` : sources anglaises **formelles et génériques** (aucune
  référence produit/plateforme), traduits fr/de/it.
- Workflow : `bench generate-pot-file` → `update-po-files` → remplir les `.po` → `compile-po-to-mo`
  (+ `clear-cache` après déploiement).

## 17. Scénarios de test — paiements & rapprochement (`swiss_vat_config/tests/`)

Extension du framework de scénarios existant (même `runner.py` / `reset_test_company` / `Ctx`) :
- **`scenarios_payments.py`** : 13 scénarios e2e (génération QR SCOR/QRR/NON, immutabilité, garde-fous de
  validation, import camt normalisation/FX, enrichissement tiers/PmtInfId, matching vente & achat, IBAN
  ZUGFeRD, config ALYF), découverts via `from scenarios_payments import *` dans `scenarios.py` (runner inchangé).
- **`helpers.py`** : builder **`build_camt053`** (camt.053 minimal **anonymisé**, paramétrable), masters
  bancaires de test (`ensure_payment_masters`), asserters `assert_field`/`assert_reject`/`assert_ref_match`,
  `import_camt`. `runner.py` : `Bank Transaction` ajouté au reset transactionnel.
- **Résultat** : **42/42** scénarios au vert (29 TVA existants + 13 paiement), aucune régression.

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
pyproject.toml                                                 # (§12) + dépendance qrbill>=1.2
erpnextswiss/hooks.py                                          # (§12/§13/§14) after_migrate swiss_qr/treasury ; doc_events Sales Invoice+Account ; jinja get_qr_bill_svg ; boot_session monkeypatch ; override get_reconcile_amount_context ; doctype_js/list_js Bank Transaction
erpnextswiss/swiss_qr/                                         # (§12) config QR par compte, génération réf serveur, rendu qrbill local, validation, migration
    setup.py · references.py · render.py · validation.py       #   champs · génération · SVG local · garde-fous
erpnextswiss/erpnextswiss/print_format/swiss_qr_invoice/       # (§12) print format unique (Jinja + SVG local)
erpnextswiss/treasury/                                         # (§13/§14) module rapprochement (gardé is_banking_installed pour la partie ALYF)
    camt_import.py                                             #   import camt.053/ZIP, FX correct, normalisation réf, PmtInfId
    reconcile_enrich.py                                        #   résolution tiers (IBAN/nom) + bouclage PmtInfId
    fx_reconcile.py · overrides.py                             #   réconciliation au taux banque · monkeypatch upload + doc_event FX
    setup.py · utils.py                                        #   champs FX/PmtInfId, config ALYF (reference_fields, voucher_defaults), sidebar
erpnextswiss/public/js/bank_transaction.js                     # (§13) bouton « Reconcile at bank rate »
erpnextswiss/public/js/bank_transaction_list.js               # (§13/§14) menu Import camt / ZIP
erpnextswiss/public/js/bank_reconciliation_tool_beta.js       # (§14) boutons Import / Reconcile sur l'écran ALYF
erpnextswiss/erpnextswiss/zugferd/zugferd_xml.py               # (§15) IBAN du compte de réception (au lieu de debit_to)
erpnextswiss/public/js/sales_invoice.js                        # (§12) retrait génération cliente onload (→ serveur)
erpnextswiss/locale/                                           # (§16) fr.po / de.po / it.po / main.pot (mécanisme .po)
erpnextswiss/swiss_vat_config/tests/scenarios_payments.py     # (§17) 13 scénarios paiement & rapprochement
erpnextswiss/swiss_vat_config/tests/helpers.py                # (§17) build_camt053, ensure_payment_masters, asserters paiement
erpnextswiss/swiss_vat_config/tests/{scenarios.py,runner.py}  # (§17) wiring module frère + Bank Transaction au reset
erpnextswiss/modules.txt                                       # (§13) + module « Treasury »
erpnextswiss/docs/swiss_qr_bill.md · docs/bank_reconciliation.md  # (§12/§13) guides utilisateur
(supprimés) erpnextswiss/doctype/contract{,_period,_service}/  # collision Contract natif
(supprimés) erpnextswiss/erpnextswiss/print_format/qr_sales_invoice{,_switzerland_rounding_description_details}/  # (§12) formats QR externes
(supprimés) erpnextswiss/templates/qrr_invoice/                # (§12) template QR externe mort
(supprimés) erpnextswiss/translations/{fr,de}.csv              # (§16) migrés vers locale/*.po
```

> Après toute modif de `.js` / `.html` / `.json` de doctype/page : `bench build --app erpnextswiss`
> + `bench --site <site> clear-cache`, puis **redémarrer `bench start`** si une app/hook change.
