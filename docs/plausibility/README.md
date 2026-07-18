# Contrôle de plausibilité du décompte TVA

> Rapport de contrôle qui **garantit qu'aucune transaction n'échappe au décompte TVA** avant son
> dépôt à l'AFC. Il réconcilie le **décompte** (calculé via les cases `afc_box`) avec le **grand
> livre** (la vérité comptable) et détecte les incohérences de classification, de configuration et
> de saisie.
>
> Code : `erpnextswiss/swiss_vat_config/plausibility.py` (fonction `collect()`).
> UI : Script Report **« Controle plausibilite TVA »**.

---

## Objectif

Le décompte TVA est produit à partir des **cases AFC** (`afc_box`), elles-mêmes alimentées par des
requêtes `viewVAT_<case>` (voir [`../ch_accounting_setup.md`](../ch_accounting_setup.md), §7 & §13).
Le risque : une transaction **taxable mais mal classée** (ou non classée) crédite quand même la TVA
en comptabilité, mais **n'apparaît dans aucune case** → sous-déclaration → **rejet AFC ou
redressement**.

Le contrôle de plausibilité est le **garde-fou avant dépôt** : *« mon décompte colle-t-il à la
compta, et rien n'a-t-il glissé à travers ? »*

---

## Comment le lancer

### Interface (comptable)
`Controle plausibilite TVA` (barre de recherche ⌘K) → filtres **Société · Date début · Date fin** →
tableau PASS/FAIL coloré, cliquable.

### CLI (dev / automatisation)
```bash
bench --site <site> execute erpnextswiss.swiss_vat_config.plausibility.run_checks \
  --kwargs "{'company':'X','start_date':'2026-01-01','end_date':'2026-12-31'}"
```

Les deux appellent la **même** fonction cœur `collect()` — écrite une fois, exposée deux fois.

---

## Le principe : `Décompte` vs `GL`

Chaque ligne compare deux mondes :

| Colonne | Signification |
|---|---|
| **Control** | Le contrôle auquel la ligne appartient (1 à 7) |
| **Item** | L'élément vérifié (compte, template, facture, écriture…) |
| **Declaration** | La valeur **telle que le décompte la calcule** (via `afc_box` / `viewVAT`) |
| **GL / value** | La valeur **issue du grand livre** (réalité comptable) ou la valeur brute de l'élément signalé |
| **Status** | ✅ OK · ❌ Anomalie · ⚠️ À vérifier |
| **Detail** | Écart chiffré, tiers/article coupable, raison |

**Si `Décompte` = `GL` → rien n'a échappé.** Sinon, une transaction s'est glissée à travers.

**Tolérance** : `0.05 CHF` (arrondi 5 centimes suisse). En-dessous, considéré « collé ».

---

## Les 7 contrôles

### 1 · GL ↔ décompte — *la réconciliation maîtresse*

Comparaison **compte par compte** entre ce que le décompte déclare et ce que la compta a réellement
enregistré.

**Ligne « TVA vente (2200) »**
- **Décompte** = TVA calculée des ventes = `viewVAT_303`(base)×8.1% + `viewVAT_313`×2.6% + `viewVAT_343`×3.8%.
- **GL** = crédit net du compte **2200** = Σ(crédit) − Σ(débit) des écritures de la période.
- **Sémantique** : chaque vente crédite 2200 de sa TVA. Le décompte re-calcule cette TVA depuis les
  **bases classées**. Si une vente a crédité 2200 mais que sa base n'a **pas de case**, GL > Décompte.
- **Échec** = une vente taxable a échappé aux cases (voir contrôle 2 pour le coupable).

**Lignes « compte 1170 → case 400 » (et 1171→405, 1173→420, 1174→415, 2203→383)**
- **Décompte** = `viewVAT_<case>` (impôt) — la valeur que le décompte met dans la case.
- **GL** = mouvement net du compte, **signé selon le côté du bilan** :
  - Compte d'**actif** (1170/1171/1173/1174) → Σ(débit) − Σ(crédit) *(l'impôt préalable augmente le débit)*
  - Compte de **passif** (2203) → Σ(crédit) − Σ(débit) *(l'impôt dû augmente le crédit)*
- **Sémantique** : chaque compte est « possédé » par **une seule case** (via son `afc_box`). La valeur
  décompte = la requête sur ce compte ; la valeur GL = **tout** ce qui y a été posté.
- **Échec** = une écriture manuelle (JE) ou un mouvement non capté a touché le compte (voir contrôle 5).

> **Pourquoi ce contrôle attrape presque tout** : il compare le mouvement GL *réel* au décompte. Toute
> divergence (JE, mauvaise classification agrégée, montant faux) fait apparaître un écart, quelle
> qu'en soit la cause. Les contrôles suivants servent surtout à **nommer le coupable**.

### 2 · Lignes non classées — *le « qui » côté transactions*

- **Ventes** : lignes `Sales Invoice Item` où `COALESCE(afc_box ligne, afc_box document)` est **NULL**.
  On lit ensuite `item_tax_rate` (JSON) : si le taux max > 0 → **taxable ET non classée** = ❌.
  *(Les lignes 0% sans case n'affectent pas la TVA → signalées en synthèse, sans impact.)*
- **Achats** : lignes `Purchase Taxes and Charges` postées sur un compte `account_type='Tax'` **sans
  `afc_box`** → impôt préalable non déclaré.
- **Colonne GL/value** = HT de la ligne (vente) ou montant de TVA (achat).
- **Sémantique** : c'est le détail qui **nomme les factures** responsables de l'écart du contrôle 1.
- **Correction** : classer la ligne (Item Tax Template avec `afc_box`) ou tagger le compte.

### 3 · Configuration — *préventif, avant même la transaction*

- **Templates** : templates de taxe **actifs** (Sales / Item) avec un **taux > 0** mais **sans
  `afc_box`** → ❌. Un template mal configuré est la **cause n°1** d'une ligne piégée.
- **Comptes** : comptes `account_type='Tax'` **mouvementés**, **sans `afc_box`**, en **excluant** les
  comptes légitimement non taggés — **2200** (TVA vente, gérée par les cases de taux) et
  **2201/2202/1172** (techniques) → ⚠️.
- **Sémantique** : attrape la source d'un futur piège **avant** qu'une facture ne le déclenche.

### 4 · Taux ligne ↔ case — *cohérence de classification fine*

- Pour chaque ligne de vente **classée dans une case de taux** (303/313/343), on compare le **taux
  réel** de la ligne (`item_tax_rate` JSON) au **taux attendu** de la case.
- **Sémantique** : une ligne classée `303` (8.1%) mais dont la TVA réelle est `2.6%` est **mal
  classée**. Le contrôle 1 ne verrait qu'un écart agrégé ; celui-ci pointe **la ligne exacte**.
- **Échec** = mauvaise case ou mauvais taux appliqué → risque de rejet AFC (base au mauvais taux).

### 5 · Écritures manuelles (Journal Entries) — *le « qui » côté écritures*

- Liste les `GL Entry` de type **`Journal Entry`** touchant un compte alimentant le décompte
  (**2200** ou tout compte porteur d'un `afc_box`).
- **Colonne GL/value** = montant de l'écriture. **Statut ⚠️** (pas forcément faux).
- **Sémantique** : une écriture manuelle sur un compte de TVA **contourne** les requêtes basées sur les
  factures. Elle peut être légitime (correction, régularisation) **ou** fausser le décompte → **à
  revoir**. C'est le pendant du contrôle 2, côté écritures manuelles.

### 6 · Documents en brouillon — *omissions*

- Factures **vente / achat** en **`docstatus=0` (brouillon)** dont la `posting_date` tombe dans la
  période.
- **Sémantique** : un brouillon n'entre **pas** dans le décompte (correct, non soumis) — mais s'il
  aurait dû être soumis, c'est un **oubli** → CA/TVA manquant. **Statut ⚠️** : à soumettre ?

### 7 · CA hors facturation — *complétude du chiffre d'affaires*

- Compare la **case 200** (CA facturé, `viewVAT_200`) au **crédit net des comptes de produits**
  (`root_type='Income'`, Σ crédit − Σ débit) sur la période.
- **Sémantique** : la case 200 ne voit que les **factures de vente**. Du chiffre d'affaires passé en
  **écriture directe** (Journal Entry sur un compte de produit) n'y figure pas → potentiellement **non
  déclaré**. Un écart → ⚠️.
- **Limite** : les comptes de produits peuvent inclure des éléments **non-CA** (produits financiers,
  etc.) → contrôle **indicatif**, à interpréter.

---

## Interprétation des statuts

| Statut | Signification | Action |
|---|---|---|
| **✅ OK** | Décompte et compta concordent (ou rien à signaler) | rien |
| **❌ Anomalie** | Écart réel qui **fausse le décompte** — à corriger avant dépôt | corriger la ligne / le template / l'écriture |
| **⚠️ À vérifier** | Situation **potentiellement** problématique (JE, brouillon, écart CA) | vérifier si légitime |

**Règle de dépôt** : ne déposer qu'avec **0 anomalie ❌**. Les ⚠️ doivent être **justifiés**.

---

## Ce qui n'est **pas** couvert (limites connues)

- **Reverse charge oublié** : un achat étranger qui *aurait dû* être en impôt sur acquisitions mais ne
  l'est pas → non détecté (nécessite le pays du fournisseur + jugement métier).
- **Décompte périmé** : si un `VAT Declaration` a été **enregistré** puis qu'une facture a été ajoutée
  après coup, le contrôle recalcule le « vrai » décompte mais ne compare pas au document sauvegardé.
- **Cut-off / rattachement** : une facture datée dans la période mais qui relève économiquement d'une
  autre période n'est pas détectée.
- **Multi-devise / arrondi 5 ct** : la conversion est gérée par ERPNext ; l'arrondi final est cosmétique.

---

## Architecture

```
plausibility.collect(company, start, end)        ← le cœur : les 7 contrôles, renvoie une liste structurée
   ├── run_checks(company, start, end)           → sortie TEXTE (CLI / bench execute)
   └── report .../controle_plausibilite_tva       → Script Report UI (tableau coloré, le comptable)
```

- `collect()` renvoie une liste de dicts `{control, item, expected, actual, status, detail}`.
- Le CLI (`run_checks`) et le report UI **formatent** cette même liste — aucune logique dupliquée.
- Data-driven : les cases, comptes taggés et taux sont **lus** depuis le référentiel `AFC VAT Box` et
  les `afc_box` des comptes/templates — **rien en dur**.

---

*Contrôle produit dans le cadre de la configuration TVA suisse (ERPNext 16). La conformité finale du
décompte doit être validée par un fiduciaire avant dépôt à l'AFC.*
