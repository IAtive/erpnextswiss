# Tests par scénarios comptables

> Suite de tests d'**acceptation comptable** : chaque scénario reproduit un cas réel (achat
> étranger, TVA douane, multi-taux, escompte…), l'exécute dans ERPNext, puis **vérifie la chaîne
> complète** — écritures (GL), cases du décompte TVA, compte de résultat (CO 959b), bilan, et les
> 7 contrôles de plausibilité. Le but : garantir que l'impact comptable/TVA/reporting est **juste**
> et **cohérent** de bout en bout, et servir de **support de validation fiduciaire**.

---

## 1. Pourquoi

- **Anti-régression** : le refactor codes AFC, les queries du décompte, la plausibilité, le 959b —
  tout est verrouillé par des cas concrets. Un changement qui casse un montant fait virer un scénario au rouge.
- **Documentation vivante** : chaque scénario documente « voici comment se comptabilise ce cas et ce
  qu'il doit produire ». Le **commentaire en tête de scénario** est rédigé pour être lu **par un fiduciaire**.
- **Filet pour la migration ProConcept** : quand les vraies données arriveront, on sait que le moteur est correct.

## 2. Architecture

```
erpnextswiss/swiss_vat_config/tests/
├── runner.py     # reset_test_company · deep_reset · run_one · run_all · render_report
├── helpers.py    # Ctx (builders + asserters) + ensure_masters
└── scenarios.py  # les scénarios : scenario_<nom>(ctx)
```

- **`Ctx`** (helpers.py) porte la société + la période, et expose :
  - des **builders** : `make_purchase_invoice(...)`, `make_sales_invoice(...)` (on en ajoute au besoin) ;
  - des **asserters** : `assert_gl`, `assert_vat`, `assert_pl`, `assert_balance`, `assert_plausibilite_ok`.
  Les asserters **enregistrent** le résultat (ils ne lèvent pas) → tous les contrôles s'exécutent et le rapport les montre tous.
- **`scenarios.py`** : une fonction `scenario_<nom>(ctx)` par cas. Découverte automatique par le runner.

## 3. Prérequis

- Une **société de test** créée et configurée par `setup_company` (chart KMU/bexio + templates TVA +
  `afc_box` + queries `viewVAT_*` + `book_tax_discount_loss` + défauts débiteur/créancier). On passe
  son **nom en paramètre** (ex. `HJD`).
- Le runner **crée automatiquement** les tiers/articles de test manquants (masters, cf. §7), dont la
  _Payment Terms Template_ d'escompte (`_escompte_terms`).

## 4. Comment lancer

**Tous les scénarios** (reset entre chaque, rapport global, rien ne persiste) :
```bash
bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.run_all \
  --kwargs "{'company': 'HJD'}"
```

**Un seul scénario, en LAISSANT les données** dans l'app pour aller inspecter (factures, GL,
décompte, bilan…) — mode `persist` :
```bash
bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.run_one \
  --kwargs "{'company': 'HJD', 'nom': 'achat_etranger_reverse_charge', 'persist': 1}"
```

**Un seul scénario, nettoyé après** (`persist` omis ou `0`) :
```bash
bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.run_one \
  --kwargs "{'company': 'HJD', 'nom': 'achat_etranger_reverse_charge'}"
```

> Le rapport est **imprimé** (pas retourné) : c'est voulu, sinon `bench execute` JSON-échappe la
> sortie (`═`, `\n`). Tu vois donc les cadres et les ✅/❌ correctement.

## 5. Les deux modes + le reset

| Mode | Comportement |
|---|---|
| `run_all` | pour chaque scénario : **reset** → opérations → contrôles → rapport. Société **vierge à la fin**. |
| `run_one(..., persist=1)` | reset → opérations → contrôles → rapport, **données laissées** pour inspection dans l'app. |
| `run_one(...)` (sans persist) | idem mais **reset final** (rien ne reste). |

**Reset** :
- `reset_test_company(company)` : reset **ciblé** — annule + supprime les pièces transactionnelles
  (factures, JE, paiements, GL…). **Synchrone, rapide**, garde le paramétrage (chart, comptes, templates TVA).
- `deep_reset(company)` : reset **profond** via le `Transaction Deletion Record` natif d'ERPNext
  (**asynchrone**, filet de sécurité si un doctype inattendu a été créé) :
  ```bash
  bench --site <site> execute erpnextswiss.swiss_vat_config.tests.runner.deep_reset --kwargs "{'company': 'HJD'}"
  ```

⚠️ Le reset **supprime toutes les transactions de la société ciblée** — n'utiliser que sur une
société de **test/démo** (ici HJD), **jamais** une société avec de vraies données.

## 6. Lire le rapport

```
══════════════════════════════════════════════════════════════════════════════
SCÉNARIO : achat_etranger_reverse_charge   ✅ OK   (9/9)
──────────────────────────────────────────────────────────────────────────────
  ✅ GL           4200       attendu       1000   obtenu     1000.0
  ✅ TVA-impôt    383        attendu         81   obtenu       81.0
  ❌ Résultat     CH_MAT     attendu      -1000   obtenu       None
        ↳ (détail affiché sur échec)
  ✅ Plausibilité 7 contrôles attendu 0 anomalie  obtenu 0 anomalie(s)
══════════════════════════════════════════════════════════════════════════════
RÉSUMÉ : 1/1 scénario(s) au vert
```

Chaque ligne = une **couche vérifiée** :

| Couche | Ce qui est vérifié |
|---|---|
| **GL** | écriture (débit−crédit) sur un compte, pour la pièce |
| **TVA-base / TVA-impôt** | montant d'une case du décompte (via `viewVAT_*`) |
| **Résultat** | un palier du compte de résultat CO 959b (CH_MAT, EBIT, BENEFICE…) |
| **Solde** | solde cumulé d'un compte de bilan |
| **Plausibilité** | les 7 contrôles GL ↔ décompte → 0 anomalie |

Sur un **échec**, le détail réel est affiché (composition de la case, anomalie de plausibilité…).

## 7. Masters de test (créés automatiquement, préfixe « SCEN »)

- Clients : `SCEN Client CH`, `SCEN Client EUR` (devise EUR, pour les opérations multi-devises)
- Fournisseurs : `SCEN Fournisseur CH`, `SCEN Fournisseur Etranger`
- Articles : `SCEN Service`, `SCEN Marchandise` (non stockés)
- _Payment Terms Template_ : `SCEN Escompte 10%` (escompte paiement rapide, via `_escompte_terms`)

`ensure_masters(company)` les crée s'ils manquent (feuilles de groupe résolues dynamiquement).

## 8. Ajouter un scénario

Dans `scenarios.py`, une fonction `scenario_<nom>(ctx)` avec **une section commentaire fiduciaire**
en tête (POURQUOI · OPÉRATIONS · ÉCRITURES ATTENDUES · DÉCOMPTE · RÉSULTAT · PLAUSIBILITÉ), puis les
opérations et les contrôles :

```python
def scenario_achat_etranger_reverse_charge(ctx):
    """
    SCÉNARIO : Achat de prestation à un fournisseur étranger (reverse charge)

    POURQUOI CE TEST ...
    OPÉRATIONS ...
    ÉCRITURES ATTENDUES ...
    DÉCOMPTE TVA ATTENDU ...
    COMPTE DE RÉSULTAT ...
    PLAUSIBILITÉ : 0 anomalie.
    """
    pi = ctx.make_purchase_invoice(supplier="SCEN Fournisseur Etranger", net=1000,
                                   tax_template="IACE81")
    ctx.assert_gl(pi, {"4200": +1000, "1171": +81, "2203": -81, "2000": -1000})
    ctx.assert_vat(base={"383": 1000}, tax={"383": 81, "405": 81})
    ctx.assert_pl("CH_MAT", -1000)
    ctx.assert_plausibilite_ok()
```

Le nom du scénario passé à `run_one` = la partie après `scenario_` (ici `achat_etranger_reverse_charge`).
`run_all` les découvre tous automatiquement.

> **Convention de signe** : `assert_gl` attend un montant **signé** (`+` = débit net, `−` = crédit net).
> `assert_pl` attend le palier avec le signe du 959b (produits positifs, charges négatives).
