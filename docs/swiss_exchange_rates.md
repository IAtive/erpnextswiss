# Swiss Exchange Rates — récupération automatique des cours AFC

Import programmé des cours de change officiels de l'**AFC / OFDF (BAZG)** dans le doctype
`Currency Exchange` d'ERPNext, avec écran de configuration, suivi (logs) et déclenchement manuel.

Conçu pour la **conformité TVA suisse** : le décompte doit utiliser les cours de l'AFC (cours mensuel
moyen ou cours du jour « devises vente »), pas un cours de marché ou BCE (art. 45 OTVA, Info TVA 07/16).

---

## 1. D'où viennent les taux

Endpoints XML officiels (BAZG) :

| Type | Endpoint | Usage |
| --- | --- | --- |
| **Cours mensuel moyen** (recommandé) | `https://www.backend-rates.bazg.admin.ch/api/xmlavgmonth` | Un cours par mois, publié le 25 du mois précédent, **définitif** dès le 1er |
| Cours du jour | `https://www.backend-rates.bazg.admin.ch/api/xmldaily` | Cours du jour (devises vente) |

Le flux renvoie ~120 devises pour **un** mois (`<monat>`, ex. `2026-07`). On n'importe que les devises
configurées. Direction écrite : **devise → CHF** (+ **CHF → devise** si `Create Inverted Rates`).

## 2. Datation des enregistrements (clé de conformité)

Le cours est daté au **1er du mois lu dans `<monat>`** (ex. `2026-07-01`), **pas** à la date d'exécution.
Raison : le lookup d'ERPNext (`erpnext/setup/utils.py::get_exchange_rate`) prend le cours le plus récent
avec `date <= date_document`. Dater au 1er fait qu'un cours mensuel **couvre tout le mois**, sans trou
entre le 1er et le jour du run.

## 3. Idempotence — jamais d'écrasement

Pour chaque (devise, sens, date) : si un `Currency Exchange` existe déjà → **ignoré** ; sinon **inséré**.
Aucun enregistrement existant n'est jamais modifié. Relancer autant de fois qu'on veut est sans effet
de bord (les runs comptent `inserted` / `skipped`).

## 4. Doctypes

| Doctype | Type | Rôle |
| --- | --- | --- |
| **Swiss Exchange Rate Settings** | Single | Config + contrôle + résumé du dernier run |
| **Swiss Exchange Rate Import Log** | — | Historique : 1 enregistrement par run (période, insérés, ignorés, détail par ligne) |
| Swiss Exchange Rate Currency | child | Devises à importer |
| Swiss Exchange Rate Import Row | child | Détail des lignes d'un run (lecture seule) |

Accessibles via le workspace **ERPNextSwiss → Configuration**.

## 5. Configuration (Swiss Exchange Rate Settings)

- **Enabled** : active/désactive la récupération programmée (porte du scheduler).
- **Rate Type** : `Monthly Average` (défaut) ou `Daily`.
- **Target Currency** : devise cible (défaut `CHF`).
- **Create Inverted Rates** : crée aussi `CHF → devise`.
- **Currencies** : liste des devises (défaut semé : EUR, USD, GBP).
- **Frequency** : `Daily` (recommandé) / `Weekly` (+ `Weekday`) / `Monthly` (+ `Day of Month`).
- **Dernier run** (lecture seule) : `last_run`, `last_status`, `last_period`, `last_inserted`,
  `last_skipped`, `last_message`.

Boutons : **Lancer maintenant**, **Voir l'historique**, **Voir les Currency Exchange**.
Depuis un **Import Log** : bouton **Voir les Currency Exchange** (filtré sur la date de valeur du run).

## 6. Planification (comment ça tourne)

Déclaré dans `hooks.scheduler_events["daily"]` → `…swiss_exchange_rate_settings.scheduled_fetch`.
Le job tourne **chaque jour** ; une **porte interne** décide de l'exécution réelle :

- `Enabled` faux → ne fait rien ;
- `Daily` → exécute ;
- `Weekly` → seulement le `Weekday` configuré ;
- `Monthly` → seulement le `Day of Month` configuré.

> **Pourquoi pas un Scheduled Job Type dédié ?** `sync_jobs()` supprime à chaque `migrate` tout
> Scheduled Job Type absent des hooks, et un cron configurable ne peut pas être figé dans les hooks.
> L'approche « hook daily + porte » survit aux migrations et reste pilotable depuis l'UI.
>
> L'heure exacte n'est pas paramétrable ici : le tick « daily » tourne à l'heure du scheduler système.
> Comme l'import est idempotent, tourner tôt chaque jour suffit (le cours du mois est déjà publié).

## 7. Utilisation en ligne de commande

```bash
# Import manuel (cours mensuels moyens)
bench --site <site> execute erpnextswiss.scripts.swiss_exchange_rates.fetch_and_store \
  --kwargs "{'rate_type':'Monthly Average','currencies':['EUR','USD','GBP'],'trigger':'Manual'}"

# Compat historique
bench --site <site> execute erpnextswiss.scripts.swiss_exchange_rates.read_rates \
  --kwargs "{'currencies': ['EUR','USD','GBP']}"
bench --site <site> execute erpnextswiss.scripts.swiss_exchange_rates.read_daily_rates
```

## 8. Fichiers

```
erpnextswiss/scripts/swiss_exchange_rates.py            # parsing + fetch_and_store (cœur)
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_settings/     # Single + JS (boutons) + scheduled_fetch
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_import_log/   # historique + JS (bouton)
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_currency/     # child devises
erpnextswiss/erpnextswiss/doctype/swiss_exchange_rate_import_row/   # child lignes (read-only)
hooks.py            # scheduler_events["daily"] + after_migrate = ensure_defaults
```

## 9. Lien avec la conformité TVA

Pour que ces cours soient réellement utilisés par ERPNext (et pas un cours en ligne type BCE/Frankfurter) :

- **Accounts Settings → Allow Stale Exchange Rates = coché** : sinon un cours daté du 1er est rejeté
  après `stale_days` (défaut 1 jour) et ERPNext irait chercher un cours en ligne.
- **Currency Exchange Settings → Disabled = coché** : coupe le fallback API en ligne ; un cours manquant
  bloque la transaction (sûr) au lieu de booker un taux non conforme.

Ces deux réglages sont posés par l'app **`erpnextswiss`** (`setup_company`). Voir sa
documentation `documentation/ch_accounting_setup.md`.
