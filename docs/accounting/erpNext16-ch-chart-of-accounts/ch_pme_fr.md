# Plan comptable `ch_pme_fr.json` — Documentation de conception

> Plan comptable ERPNext 16 (Suisse, PME, français) généré à partir de l'export bexio.
> Ce document explique **comment** il a été construit, **quels compromis** ont été faits,
> **quelles conséquences** ils ont, et **comment les corriger** si besoin.

---

## Table des matières

1. [Objectif et fichiers](#1-objectif-et-fichiers)
2. [Données source (bexio)](#2-données-source-bexio)
3. [Comment ERPNext lit un plan comptable (contraintes du code)](#3-comment-erpnext-lit-un-plan-comptable-contraintes-du-code)
4. [Règles de génération appliquées](#4-règles-de-génération-appliquées)
5. [Décisions & compromis](#5-décisions--compromis)
6. [Le compromis principal : les 4 comptes « produits » en racine Expense](#6-le-compromis-principal--les-4-comptes-produits-en-racine-expense)
7. [Conséquences détaillées (avec exemple chiffré)](#7-conséquences-détaillées-avec-exemple-chiffré)
8. [Comment changer cela si ça pose problème — les approches](#8-comment-changer-cela-si-ça-pose-problème--les-approches)
9. [Résultats de validation](#9-résultats-de-validation)
10. [Étapes post-import](#10-étapes-post-import)
11. [Régénérer le fichier](#11-régénérer-le-fichier)

---

## 1. Objectif et fichiers

ERPNext 16 ne fournit pas de plan comptable suisse PME en français. Nous l'avons donc
construit à partir du plan comptable exporté de **bexio**.

| Fichier                          | Rôle                                                       |
| -------------------------------- | ---------------------------------------------------------- |
| `accounts-groups.json`           | Export bexio : 96 groupes + 132 comptes (source de vérité) |
| `bexio-chart-of-accounts.xlsx`   | Même contenu, format Excel                                 |
| `bexio-tax-rates.json` / `.xlsx` | Taux de TVA bexio (pour l'étape _tax templates_, séparée)  |
| `generate_coa.py`                | Script qui transforme l'export bexio en JSON ERPNext       |
| **`ch_pme_fr.json`**             | **Le plan comptable généré (livrable)**                    |
| `ch_pme_fr.md`                   | Ce document                                                |

**Emplacement d'activation dans ERPNext** :
`apps/erpnext/erpnext/accounts/doctype/account/chart_of_accounts/verified/`
→ à la création d'une Company (pays = Switzerland), le plan apparaît dans la liste déroulante
« Chart of Accounts ». Aucun nom de société n'est requis pour ce fichier (l'abréviation, ex.
`- CPM`, est ajoutée automatiquement à la création de la société).

---

## 2. Données source (bexio)

`accounts-groups.json` contient deux listes :

- **`groups`** (96) : hiérarchie de groupes, reliés par `parent_accounts_group_id`
  (ex. `1 Actifs` → `10 Actifs circulants` → `100 Trésorerie`).
- **`accounts`** (132) : comptes-feuilles, rattachés à un groupe par `accounts_group_id`,
  avec `number`, `name`, `account_classification` (Asset / Liability / Income / Expense / **Complete**),
  `is_system_account`, `standard_tax_rate` (null partout).

**Intégrité vérifiée** : 0 compte orphelin, 0 groupe orphelin, 0 doublon de numéro,
0 collision entre numéros de comptes et de groupes, 0 collision de noms entre frères.

Structure des racines bexio (groupes de premier niveau) :

| N°  | Nom                                          | Classification dominante                    |
| --- | -------------------------------------------- | ------------------------------------------- |
| 1   | Actifs                                       | Asset                                       |
| 2   | Passifs                                      | Liability (+ Equity dans le sous-groupe 28) |
| 3   | Produits nets des ventes                     | Income                                      |
| 4   | Charges de matériel/marchandises             | Expense                                     |
| 5   | Charges de personnel                         | Expense                                     |
| 6   | Autres charges d'exploitation                | Expense (+ 2 comptes Income)                |
| 8   | Résultats exceptionnels et hors exploitation | Expense (+ 2 comptes Income)                |
| 9   | Clôture                                      | Complete                                    |

---

## 3. Comment ERPNext lit un plan comptable (contraintes du code)

Ces contraintes ont **dicté** la construction. Références : app `erpnext`.

### 3.1 `root_type` n'est lu **qu'à la racine** de l'arbre

`accounts/doctype/account/chart_of_accounts/chart_of_accounts.py` → `create_charts._import_accounts` :

```python
def _import_accounts(children, parent, root_type, root_account=False):
    for account_name, child in children.items():
        if root_account:                 # UNIQUEMENT au 1er niveau
            root_type = child.get("root_type")
        ...
        _import_accounts(child, account.name, root_type)   # les enfants HÉRITENT
```

→ **`root_type` doit être posé sur les nœuds de premier niveau uniquement ; tous les descendants héritent.**
Écrire `root_type` sur un nœud intermédiaire est **ignoré**.

### 3.2 Le `root_type` d'un compte est **forcé** par son parent (verrou permanent)

`accounts/doctype/account/account.py` → `set_root_and_report_type` (appelé à **chaque** `validate()`) :

```python
if self.parent_account:
    par = frappe.get_cached_value("Account", self.parent_account, ["report_type","root_type"])
    if par.root_type:
        self.root_type = par.root_type    # écrase TOUJOURS avec celui du parent
if cint(self.is_group) and self.root_type != db_value.root_type:
    # propage le changement vers TOUS les descendants (lft/rgt)
```

→ Conséquences majeures :

- On **ne peut PAS** donner à un sous-groupe (ni à un compte) un `root_type` différent de son parent.
  Même en le modifiant à la main dans l'UI, ERPNext le réécrase.
- **Le seul nœud dont le `root_type` est libre est un compte RACINE** (`parent_account` vide).
- `report_type` (Balance Sheet / Profit and Loss) est dérivé du `root_type` :
  `Asset/Liability/Equity` → Balance Sheet ; `Income/Expense` → Profit and Loss.

### 3.3 `is_group` est auto-détecté

`chart_of_accounts.py` → `identify_is_group` : un nœud avec des enfants (clés hors métadonnées)
est un groupe ; sinon c'est un compte-feuille. On pose quand même `is_group: 1` explicitement
sur les groupes pour la lisibilité.

### 3.4 Clés de métadonnées reconnues

`chart_of_accounts.py` → `get_chart_metadata_fields` :
`account_name, account_number, account_type, account_category, root_type, is_group, tax_rate, account_currency`.
Toute autre clé est traitée comme un **compte enfant**. Nos clés respectent cette liste.

### 3.5 `account_type` est **facultatif**

`account.json` → champ `account_type` : `Select`, `reqd = None`, 1re option vide.
31 valeurs possibles. Facultatif au niveau du champ, mais **fonctionnellement requis** pour
certains rôles (Receivable, Payable, Bank, Cash, Tax, Round Off, Stock…), sinon le compte
n'est pas sélectionnable dans les transactions ni comme _Default Account_ de la Company.

### 3.6 `account_currency` ignoré sur les charts `verified/`

Pour un chart du dossier `verified/`, `create_charts` met **la devise de la société** sur tous
les comptes (le champ `account_currency` du JSON n'est pris en compte que pour un _custom chart_
uploadé). Le multidevise (ex. compte bancaire EUR) s'ajuste **après** création.

---

## 4. Règles de génération appliquées

Le script `generate_coa.py` applique :

1. **Exclusion de la branche « 9 Clôture »** (classification `Complete`) — voir §5.1.
2. **Promotion du groupe « 28 Capitaux propres » en racine `Equity`** — voir §5.2.
3. **Racines de premier niveau** et leur `root_type` :
   `1→Asset`, `2→Liability`, `28→Equity`, `3→Income`, `4/5/6/8→Expense`.
4. **`account_type`** posé sur les comptes système + les comptes fonctionnels obligatoires — voir §5.4.
5. **Ajout du compte `1000 Caisse`** (type `Cash`), absent de bexio — voir §5.5.
6. **Mapping de `4800 Variation des stocks` en `Stock Adjustment`** — voir §5.5.
7. Tri des enfants par numéro ; `is_group: 1` sur les groupes.

---

## 5. Décisions & compromis

### 5.1 Exclusion de la classe 9 (Clôture / `Complete`)

**Comptes exclus** : 9000 Compte de résultat, 9100 Bilan d'ouverture, 9101 Bilan de clôture,
9200 Bénéfice/perte de l'exercice, 9900 Corrections, 9901 Transfert de soldes.

**Pourquoi** : ERPNext ne matérialise pas de comptes de bouclement permanents. L'ouverture,
la clôture et le report du résultat sont gérés nativement (_Period Closing Voucher_ + compte
de report en `Equity`). Les recréer n'ajouterait que des comptes inutilisés.

**Réversible ?** Oui : on peut les rajouter en `account_type: Temporary` si un besoin précis apparaît.

### 5.2 Promotion du groupe 28 (Capitaux propres) en racine `Equity`

En bexio, le groupe 28 est **sous** « 2 Passifs » et ses comptes sont classés `Liability`.
ERPNext a un `root_type` dédié `Equity`. Comme `root_type` n'est lu qu'à la racine (§3.1),
**pour obtenir `Equity`, il faut que 28 soit une racine de premier niveau**. On l'a donc
**détaché de « 2 Passifs »**. Comptes concernés : 2800 Capital, 2950 Réserve légale,
2970 Bénéfice reporté, 2979 Bénéfice de l'exercice.

### 5.3 Les 4 comptes « produits » des sections 6 et 8 → racine `Expense`

**C'est le compromis principal. Détaillé au §6.**

### 5.4 Mapping `account_type` (comptes système + obligatoires)

| Numéro    | Nom                                  | `account_type`       |
| --------- | ------------------------------------ | -------------------- |
| 1000      | Caisse _(ajouté)_                    | `Cash`               |
| 1020      | Banque UBS CHF                       | `Bank`               |
| 1029      | Bank                                 | `Bank`               |
| 1100      | Créances suisses                     | `Receivable`         |
| 1170–1174 | Impôt préalable (TVA déductible)     | `Tax`                |
| 1200      | Stocks de marchandises               | `Stock`              |
| 1500–1530 | Machines, mobilier, véhicules        | `Fixed Asset`        |
| 2000      | Dettes fournisseurs                  | `Payable`            |
| 2200–2203 | TVA due / décompte / acquisitions    | `Tax`                |
| 3200      | Ventes de marchandises               | `Income Account`     |
| 4200      | Achats de marchandises               | `Cost of Goods Sold` |
| 4800      | Variation des stocks de marchandises | `Stock Adjustment`   |
| 6945      | Différence d'arrondi                 | `Round Off`          |

Tous les autres comptes ont `account_type` **vide** (comme les plans comptables officiels
d'ERPNext). Les comptes de capitaux propres (28xx) tirent leur nature du `root_type: Equity`.

> Note : le champ `is_system_account` de bexio **n'a pas d'équivalent** dans ERPNext. La notion
> est éclatée entre `account_type` (le rôle) et les champs `default_*_account` de la Company
> (quel compte joue ce rôle). Voir §10.

### 5.5 Comptes ajoutés / remappés pour la conformité fonctionnelle ERPNext

- **`1000 Caisse` (Cash)** : ajouté sous « 100 Trésorerie ». bexio n'a que des comptes bancaires ;
  ERPNext a besoin d'au moins un compte `Cash` (caisse) pour `default_cash_account`.
- **`4800 → Stock Adjustment`** : au lieu d'ajouter un compte, on a mappé l'existant
  « Variation des stocks de marchandises » sur le type `Stock Adjustment` (c'est exactement son rôle),
  requis pour la réconciliation d'inventaire.

### 5.6 Comptes multi-devises (EUR) — créés hors chart, par `setup_currency_accounts`

**Décision (client) : opérations en CHF _et_ EUR (achat et vente).** Suivre des créances/dettes en
devise étrangère et calculer l'**écart de change au règlement** (→ 6999) impose des comptes **dans la
bonne devise** (`account_currency`). Or (cf. **§3.6**) sur un chart `verified/` ERPNext **ignore
`account_currency`** → impossible de les définir dans `ch_pme_fr.json`.

→ Ils sont donc créés **programmatiquement** par
`erpnextswiss.swiss_vat_config.company_setup.setup_currency_accounts` (appelé par `setup_company`), avec la
devise **réellement** appliquée :

| Compte | Type | Devise | Sous le groupe de… | Rôle |
|---|---|---|---|---|
| **1101 Créances clients EUR** | Receivable | EUR | 1100 (Créances) | créance client libellée en EUR (**vente** en EUR) |
| **2001 Dettes fournisseurs EUR** | Payable | EUR | 2000 (Dettes) | dette fournisseur libellée en EUR (**achat** en EUR) |
| **1021 Banque EUR** | Bank | EUR | 100 (Trésorerie) | avoir bancaire en EUR (option, si compte bancaire EUR) |

Chaque compte est rangé **sous le même groupe** que son homologue CHF. La **TVA reste toujours en
CHF** (au taux de la facture) — ces comptes ne concernent **que** le suivi des postes ouverts en devise
et le change. Voir le **point §15 de validation fiduciaire** (choix des devises).

**Autres devises (USD…)** : mêmes comptes, par devise — à ajouter dans la constante `CURRENCY_ACCOUNTS`
si le client le confirme.

---

## 6. Le compromis principal : les 4 comptes « produits » en racine Expense

### 6.1 Le problème

bexio distingue **deux informations séparées** par compte :

1. **où il est rangé** dans l'arbre (→ sa racine) ;
2. **sa nature** (`account_classification`), déclarée indépendamment.

Ces deux infos **divergent** pour 4 comptes : ils sont rangés sous des racines de **charges**
(6 ou 8) mais déclarés `Income` :

| Compte | Nom                                      | Sous racine | Nature bexio | Sous-groupe                          |
| ------ | ---------------------------------------- | ----------- | ------------ | ------------------------------------ |
| 6950   | Produits financiers sur avoirs en banque | 6           | Income       | 695 Produits financiers              |
| 6999   | Gains de change                          | 6           | Income       | 695 Produits financiers              |
| 8100   | Produits hors exploitation               | 8           | Income       | 80 Résultats hors exploitation       |
| 8514   | Bénéfices exceptionnels sur aliénations  | 8           | Income       | 85 Charges et produits exceptionnels |

### 6.2 Pourquoi ils héritent de `Expense`

ERPNext n'a **qu'un** `root_type` par compte, lu à la racine (§3.1) et **forcé** par le parent (§3.2).
Les racines 6 et 8 étant `Expense`, leurs descendants — dont ces 4 comptes — **héritent obligatoirement
de `Expense`**. Il est **techniquement impossible** de leur donner `Income` sans changer leur position
dans l'arbre (voir §8).

### 6.3 Pourquoi on a accepté ce compromis

- C'est **fidèle à la structure du plan comptable suisse** : le résultat financier (69) et le résultat
  exceptionnel (8) sont, par convention suisse (CO art. 959b), **hors du chiffre d'affaires** (classe 3).
- L'alternative (déplacer ces comptes en Income) **casserait** la numérotation suisse et/ou la
  correspondance avec bexio (voir §8).
- L'impact est **cosmétique** et porte sur des montants généralement faibles pour une PME.

---

## 7. Conséquences détaillées (avec exemple chiffré)

**Hypothèse** : Ventes (classe 3) = 500 000 ; somme des 4 comptes « produits mal placés » = 10 000.

### 7.1 Ce qui est **identique** (aucun impact)

| Élément                              | Détail                                                                                                                                                   |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Résultat net / bénéfice**          | `net = Total Income − Total Expense`. Un produit rangé en « charge négative » réduit les charges du même montant → le bénéfice est **exact au centime**. |
| **Bilan**                            | Ces 4 comptes sont `report_type = Profit and Loss` → **jamais** au bilan.                                                                                |
| **Fonds propres / report à nouveau** | Dérivent du résultat net → identiques.                                                                                                                   |
| **Écritures comptables (GL)**        | `root_type` ne change pas la façon de comptabiliser.                                                                                                     |
| **TVA, budgets, clôture, paiements** | Aucun impact.                                                                                                                                            |
| **Chiffre d'affaires (classe 3)**    | Ces comptes n'ont jamais fait partie du CA. CA identique à bexio.                                                                                        |

Preuve (code) : `accounts/report/profit_and_loss_statement/profit_and_loss_statement.py`
→ `get_net_profit_loss` : `net_profit = total_income − total_expense`.

### 7.2 Ce qui **diffère** (impact cosmétique / reporting)

Présentation dans le **P&L standard ERPNext** (2 blocs : Income / Expense) :

```
PRODUITS (Income)
  Ventes de marchandises .................  500 000
  Total Income ...........................  500 000   ← CA « pur » (= CA bexio)

CHARGES (Expense)
  Charges d'exploitation .................  400 000
  Gains de change ........................   -3 000   ← produit en charge négative
  Produits financiers ....................   -2 000
  Produits hors exploitation .............   -1 000
  Bénéfices exceptionnels ................   -4 000
  Total Expense ..........................  390 000   ← minoré de 10 000

RÉSULTAT NET ...........................   110 000   ✅
```

| Chiffre affiché                | Valeur               | Remarque                                                           |
| ------------------------------ | -------------------- | ------------------------------------------------------------------ |
| **Total Income**               | 500 000              | N'inclut pas les 4 comptes (ils sont en Expense)                   |
| **Total Expense**              | 390 000              | Minoré de 10 000 (produits en négatif)                             |
| **Lignes 6950/6999/8100/8514** | négatives            | Apparaissent dans la section Charges                               |
| **KPI « Total Revenue »**      | 500 000              | Les dashboards agrégeant `root_type=Income` excluent ces 4 comptes |
| **Ratios de marge**            | dénominateur 500 000 | Légèrement différents d'une présentation « Income »                |

### 7.3 Comparaison bexio ↔ ERPNext (pour la migration)

| Chiffre                                  | bexio   | ERPNext (choix actuel) | Identique ?         |
| ---------------------------------------- | ------- | ---------------------- | ------------------- |
| CA / produit net des ventes (classe 3)   | 500 000 | 500 000                | ✅                  |
| Résultat net                             | X       | X                      | ✅                  |
| « Total des produits » (tout tag Income) | 510 000 | 500 000                | ❌ (écart = 10 000) |

> À retenir : le **CA** et le **résultat net** sont identiques. Seul l'agrégat large
> « total des produits » diffère — mais il n'a **pas de portée statutaire** (on ne présente jamais
> « ventes + gains de change » sur une même ligne). Pour valider la migration, rapprocher **le CA
> (classe 3)** et **le résultat net**.

---

## 8. Comment changer cela si ça pose problème — les approches

> Rappel du verrou (§3.2) : on **ne peut pas** simplement éditer le `root_type` du compte dans
> l'UI — ERPNext le réécrase avec celui du parent. Toute correction passe par un **changement de
> position dans l'arbre** (re-parentage) ou par un **rapport personnalisé**.

### Approche A — Ne rien changer + construire un _Financial Report Template_ (RECOMMANDÉ)

**Principe** : garder le plan tel quel et produire le compte de résultat **légal suisse** via la
fonctionnalité native **`Financial Report Template`** (doctype ERPNext 16, avec table
`Financial Report Row`).

Les lignes du rapport récupèrent les comptes par **filtre de plages de numéros** (et non par
`root_type`), avec sous-totaux calculés, indentation, et case **`Reverse Sign`** pour le signe.
Résultat : la présentation statutaire est correcte **quel que soit** le `root_type` des 4 comptes.

Exemple de structure (CO art. 959b) :

```
Produit net des ventes            Account Data       comptes 3xxx
− Charges de marchandises         Account Data       comptes 4xxx
− Charges de personnel            Account Data       comptes 5xxx
− Autres charges d'exploitation   Account Data       comptes 60xx-66xx
− Amortissements                  Account Data       comptes 68xx
= Résultat d'exploitation (EBIT)  Calculated Amount  (formule)
± Résultat financier              Account Data       comptes 69xx (690 + 695)
= Résultat avant impôts           Calculated Amount  (formule)
± Résultat exceptionnel/hors expl Account Data       comptes 80xx, 85xx
− Impôts                          Account Data       comptes 89xx
= Bénéfice / perte de l'exercice  Calculated Amount  (formule)
```

**Avantages** : ne touche ni aux numéros, ni au `root_type`, ni à l'arbre ; produit la vraie
présentation légale ; fonctionne par-dessus le choix actuel.
**Coût** : construire le template une fois. Emplacement : `Accounting` → _Financial Report Template_.

### Approche B — Promouvoir le sous-groupe `695 Produits financiers` en racine `Income`

**Principe** : détacher le sous-groupe **695** (qui ne contient QUE des produits : 6950, 6999) de
son parent 69 et le remonter en **nœud de premier niveau** avec `root_type: Income`.

Avant :

```
6 Autres charges d'exploitation (Expense)
└── 69 Charges et produits financiers
    ├── 690 Charges financières       → 6900, 6940, 6945, 6949  (restent Expense)
    └── 695 Produits financiers       → 6950, 6999               (voulus Income)
```

Après :

```
6 Autres charges d'exploitation (Expense)
└── 69 Charges et produits financiers
    └── 690 Charges financières       → 6900, 6940, 6945, 6949  (Expense) ✅

695 Produits financiers (RACINE, Income)   ← remonté au 1er niveau
    → 6950, 6999  (Income) ✅
```

Dans le JSON : sortir le bloc `"Produits financiers"` (695) de sous « Autres charges
d'exploitation » et le placer au niveau de `tree`, avec `"root_type": "Income"`.

**Avantages** : corrige 6950 et 6999 (dont les gains de change) proprement ; **garde les numéros** ;
ne touche pas aux charges financières.
**Coût** : un petit nœud racine « Produits financiers » « flotte » au sommet de l'arbre (inhabituel
visuellement). **Ne règle pas** 8100/8514 (voir §8, cas 8).

### Approche C — Re-parenter les comptes **individuellement** sous une racine `Income`

**Principe** : créer (ou réutiliser) une racine `Income`, puis y déplacer les comptes voulus
(via `Parent Account` dans l'UI, ou dans le JSON). Le numéro du compte reste inchangé ; seule sa
position change.

**Avantages** : granularité maximale ; garde les numéros.
**Coût** : les comptes se retrouvent sous une racine dont le numéro ne « colle » plus (ex. 6999
sous une branche Income) — cohérence visuelle des numéros dégradée. À réserver aux cas isolés
(ex. 8100, 8514 qui n'ont pas de sous-groupe « produits only »).

### Approche D — Renuméroter les comptes (⚠️ DÉCONSEILLÉ)

**Principe** : changer le numéro (ex. 6999 → 3xxx) pour que le compte tombe « naturellement » sous
une racine Income.

**Pourquoi c'est déconseillé** :

- Casse la **norme suisse** (69xx = résultat financier chez toutes les entreprises suisses).
- Casse la **correspondance avec bexio** (toute reprise/rapprochement se fait par numéro).
- Casse le **rapport statutaire par plages** (un 6999 devenu 3xxx tomberait dans la section CA — l'erreur
  qu'on veut éviter).
- Perturbe le comptable/fiduciaire (le numéro est un langage partagé).
- **N'apporte rien de plus** que les approches B/C : dans ERPNext, numéro et position dans l'arbre
  sont **indépendants** — on n'a pas besoin de renuméroter pour changer le `root_type`.

### Cas particulier des comptes 8100 et 8514

Contrairement à 695, les groupes 80 et 85 **mélangent** charges et produits au même niveau
(pas de sous-groupe « produits only ») :

```
80 Résultats hors exploitation    → 8000 (charge) + 8100 (produit)
85 Charges et produits except.    → 8505 (charge) + 8514 (produit)
```

Il n'existe donc **pas** de sous-groupe promouvable proprement (Approche B impossible ici).
Options : Approche C (re-parenter 8100 et 8514 individuellement), ou créer des sous-groupes
« produits » artificiels, ou — le plus simple — les laisser en Expense et compter sur le
**Financial Report Template** (Approche A). Ces comptes étant rares/exceptionnels, l'Approche A
est généralement suffisante.

### Tableau de synthèse des approches

| Approche                   | root_type Income | Garde numéros | Garde structure    | Règle 6950/6999   | Règle 8100/8514   | Verdict             |
| -------------------------- | ---------------- | ------------- | ------------------ | ----------------- | ----------------- | ------------------- |
| **A. Report Template**     | (indifférent)    | ✅            | ✅                 | ✅ (présentation) | ✅ (présentation) | 👍 recommandé       |
| **B. Promouvoir 695**      | ✅               | ✅            | 🟡 (nœud flottant) | ✅                | ❌                | 👍 propre (partiel) |
| **C. Re-parenter comptes** | ✅               | ✅            | 🟡                 | ✅                | ✅                | 🟠 cas isolés       |
| **D. Renuméroter**         | ✅               | ❌            | ❌                 | ✅                | ✅                | 👎 à éviter         |

**Recommandation** : **A** (report template) pour la présentation légale, éventuellement combinée
à **B** (promotion de 695) si l'on veut que les gains de change / produits financiers soient aussi
correctement classés dans les KPI. Ne **jamais** renuméroter (D).

---

## 9. Résultats de validation

Validation du JSON généré en rejouant la logique d'import d'ERPNext :

| Contrôle                               | Résultat                                                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Structure                              | 8 racines, 94 groupes, 127 comptes (126 bexio + 1 Caisse)                                                      |
| `root_type` présent sur tous les nœuds | ✅ (Asset 39, Liability 27, Equity 7, Income 27, Expense 121)                                                  |
| `root_type` / `account_type` valides   | ✅ 0 invalide                                                                                                  |
| `account_type` fonctionnels présents   | ✅ Bank, Cash, Receivable, Payable, Stock, Fixed Asset, COGS, Stock Adjustment, Round Off, Tax, Income Account |
| Capitaux propres (28xx) → Equity       | ✅ (7 nœuds)                                                                                                   |
| 4 comptes 6/8 « Income » → Expense     | ✅ (choix retenu)                                                                                              |
| Doublons de numéros                    | ✅ aucun                                                                                                       |
| Classe 9 (Complete)                    | ✅ exclue                                                                                                      |
| Caisse 1000 (Cash)                     | ✅ ajoutée sous groupe 100                                                                                     |

---

## 10. Étapes post-import

Après création de la Company avec ce plan :

1. **Comptes par défaut de la société** (`Accounting → Company → <société>`) :
   - Default Bank / Cash / Receivable / Payable / Income / Cost of Goods Sold Account
   - `Round Off Account` → 6945
   - `Exchange Gain / Loss Account` → 6949 / 6999
   - `Stock Adjustment Account` → 4800
2. **TVA** (`Accounting → Taxes`) : créer les _Sales / Purchase / Item Tax Templates_ à partir de
   `bexio-tax-rates.json`. Les comptes `Tax` (1170–1174, 2200–2203) doivent exister (déjà le cas).
   ⚠️ Le **décompte TVA suisse** (cases 303, 313, 400, 405…) n'existe pas nativement dans ERPNext →
   prévoir une app tierce ou un rapport custom.
3. **TVA à l'import (douane)** : se saisit en ligne de type **`Actual`** (montant), pas en pourcentage
   (équivalent du taux « 100 » de bexio).
4. **Compte de résultat statutaire** : construire un _Financial Report Template_ (Approche A, §8).

---

## 11. Régénérer le fichier

```bash
cd accounting/
python3 generate_coa.py         # relit accounts-groups.json → réécrit ch_pme_fr.json
```

Le mapping `account_type`, les racines et leurs `root_type`, l'exclusion de la classe 9 et la
promotion du groupe 28 sont paramétrés en tête de `generate_coa.py` (dictionnaires
`ACCOUNT_TYPE`, `ROOT_TYPE`, et la logique `EXCL` / promotion de 28).

Pour activer : copier `ch_pme_fr.json` dans
`apps/erpnext/erpnext/accounts/doctype/account/chart_of_accounts/verified/`, puis
`bench --site <site> clear-cache`.

---

_Document généré dans le cadre de la migration bexio → ERPNext 16. Toutes les affirmations sur le
comportement d'ERPNext sont vérifiées dans le code source (`apps/erpnext`). Les affirmations sur le
plan comptable suisse (CO art. 959b, structure KMU) relèvent de la connaissance métier et devraient
être confirmées avec le fiduciaire pour la présentation statutaire finale._
