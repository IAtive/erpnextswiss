CE RAPPORT a ete produit par claude en partant de STAN_f_DEF_2025-06-30_eCH-0217_V-2.0.0_E-TVA.pdf

# Décompte TVA suisse — Référence des chiffres (positions AFC)

Document de référence pour l'implémentation d'un **rapport de décompte TVA** conforme
à l'Administration fédérale des contributions (AFC).

- **Source normative** : standard eCH-0217 « Interface décompte TVA » v2.0.0 (2025-06-30),
  qui définit la structure XML échangée avec l'application AFC « Décompter la TVA ».
- **Périmètre de ce README** : **méthode effective** (TVA collectée − impôt préalable),
  décompte trimestriel. Les positions propres à la méthode des taux de la dette fiscale
  nette (TDFN) et aux taux forfaitaires sont listées en fin de document mais hors périmètre.
- **Taux légaux en vigueur** (depuis le 01.01.2024) : normal **8.1 %**, réduit **2.6 %**,
  hébergement **3.8 %**. Le numéro de position lié à un taux dépend de la table de taux
  en vigueur pour la période de décompte.

Un « chiffre » (Ziffer / cifra) est une position numérotée du formulaire de décompte.
Certains chiffres sont **déclarés** (saisis), d'autres sont **calculés** à partir des premiers.

---

## Structure générale du décompte

Le décompte se compose de trois parties :

1. **Partie I — Calcul du chiffre d'affaires** : détermine le CA imposable à partir du
   CA total, en déduisant les prestations non imposables (exportations, exclues, diminutions…).
2. **Partie II — Calcul de l'impôt** : impôt dû sur le CA taxable (par taux) + impôt sur les
   acquisitions, moins l'impôt préalable déductible.
3. **Partie III — Autres mouvements de fonds** : montants informatifs sans effet sur l'impôt
   (subventions, dons…).

---

## Partie I — Calcul du chiffre d'affaires (bloc 2xx)

| Chiffre | Identifiant                   | Type    | Description                                                                                                                                                               |
| ------- | ----------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **200** | totalConsideration            | déclaré | Total des contre-prestations : chiffre d'affaires mondial, brut, convenu ou reçu. Inclut tout (prestations optées, transferts, prestations à l'étranger). Base de départ. |
| **205** | opted                         | déclaré | Part des contre-prestations pour lesquelles il a été **opté** (art. 22 LTVA). Sous-ensemble déjà compris dans 200 ; information à part.                                   |
| **220** | suppliesToForeignCountries    | déclaré | Prestations **exonérées** : exportations et prestations exonérées (art. 23 LTVA).                                                                                         |
| **221** | suppliesAbroad                | déclaré | Prestations dont le **lieu est à l'étranger** (non imposables en Suisse).                                                                                                 |
| **225** | transferNotificationProcedure | déclaré | Transferts effectués selon la **procédure de déclaration** (art. 38 LTVA).                                                                                                |
| **230** | suppliesExemptFromTax         | déclaré | Prestations **exclues** du champ de l'impôt, non optées (art. 21 LTVA).                                                                                                   |
| **235** | reductionOfConsideration      | déclaré | **Diminutions** de la contre-prestation : rabais, escomptes, ristournes, pertes sur débiteurs.                                                                            |
| **280** | variousDeduction              | déclaré | Divers : p. ex. valeur du terrain, prix d'achat en imposition de la marge.                                                                                                |
| **299** | _(résultat)_                  | calculé | **Chiffre d'affaires imposable** = `200 − 220 − 221 − 225 − 230 − 235 − 280`.                                                                                             |

---

## Partie II — Calcul de l'impôt

### Impôt dû (blocs 3xx / 38x)

| Chiffre     | Identifiant        | Type    | Description                                                                                                                                                                                                                                   |
| ----------- | ------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **300–379** | suppliesPerTaxRate | déclaré | Chiffre d'affaires taxable **cumulé par taux légal**. Pour chaque taux : base imposable + impôt correspondant. Positions usuelles du formulaire : **302** (taux normal 8.1 %), **312** (taux réduit 2.6 %), **342** (taux hébergement 3.8 %). |
| **38x**     | acquisitionTax     | déclaré | **Impôt sur les acquisitions** (reverse charge, art. 45 LTVA) : prestations de services acquises d'entreprises étrangères, auto-déclarées par le destinataire. Position usuelle **382**. Toujours net, aux taux légaux.                       |
| **399**     | _(résultat)_       | calculé | **Total de l'impôt dû** = impôt sur les positions 3xx + impôt sur 38x.                                                                                                                                                                        |

> Note : l'impôt sur les acquisitions (38x) est généralement **neutre** lorsqu'il est
> intégralement déductible, car le même montant est repris en impôt préalable (bloc 4xx).

### Impôt préalable / déductible (bloc 4xx)

| Chiffre | Identifiant                 | Type    | Description                                                                                                                 |
| ------- | --------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| **400** | inputTaxMaterialAndServices | déclaré | Impôt préalable sur **matériel et prestations de services**.                                                                |
| **405** | inputTaxInvestments         | déclaré | Impôt préalable sur **investissements et autres charges d'exploitation**.                                                   |
| **410** | subsequentInputTaxDeduction | déclaré | **Dégrèvement ultérieur** de l'impôt préalable (art. 32 LTVA).                                                              |
| **415** | inputTaxCorrections         | déclaré | **Corrections** de l'impôt préalable : double affectation (art. 30), prestations à soi-même (art. 31). Réduit le préalable. |
| **420** | inputTaxReductions          | déclaré | **Réductions** de la déduction liées aux subventions et autres (art. 33 al. 2 LTVA). Réduit le préalable.                   |
| **479** | _(résultat)_                | calculé | **Total de l'impôt préalable** = `400 + 405 + 410 − 415 − 420`.                                                             |

---

## Résultat du décompte (bloc 5xx)

| Chiffre | Identifiant    | Type    | Description                                      |
| ------- | -------------- | ------- | ------------------------------------------------ |
| **500** | payableTax (+) | calculé | **Montant à payer** à l'AFC (si positif).        |
| **510** | payableTax (−) | calculé | **Avoir** en faveur de l'assujetti (si négatif). |

**Formule de résultat :**

```
payableTax = 399                       (total impôt dû sur prestations)
           + impôt(38x)                (impôt sur les acquisitions)
           − 400                       (préalable matériel & services)
           − 405                       (préalable investissements)
           − 410                       (dégrèvement ultérieur)
           + 415                       (corrections préalable)
           + 420                       (réductions préalable)

payableTax > 0  → chiffre 500 (à payer)
payableTax < 0  → chiffre 510 (avoir)
```

---

## Partie III — Autres mouvements de fonds (bloc 9xx)

Informatif uniquement — **aucun impact sur l'impôt dû**, mais requis par l'AFC.

| Chiffre | Identifiant | Type    | Description                                                                                                                                          |
| ------- | ----------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **900** | subsidies   | déclaré | Subventions, taxes touristiques, contributions aux fonds pour l'élimination des déchets et l'approvisionnement en eau (art. 18 al. 2 let. a–c LTVA). |
| **910** | donations   | déclaré | Dons, dividendes, dédommagements et autres flux non imposables (art. 18 al. 2 let. d–l LTVA).                                                        |

---

## Règles de calcul et d'arrondi

Ces règles sont **impératives** — l'application AFC recalcule et rejette un décompte non conforme.

1. **Calcul au centime, sans arrondi intermédiaire.** Toutes les étapes intermédiaires
   (impôt par taux, totaux) se calculent avec 2 décimales, sans arrondir en cours de route.
2. **Arrondi final aux 5 centimes, en faveur de l'assujetti**, uniquement sur le résultat
   500/510 :
   - Montant **à payer** (500) : arrondi vers le bas.
     Ex. `950.54 → 950.50`, `950.59 → 950.55`.
   - **Avoir** (510) : arrondi vers le haut.
     Ex. `950.51 → 950.55`, `950.56 → 950.60`.
3. **Montants négatifs** admis sur les positions de chiffre d'affaires et d'impôt
   (p. ex. période avec plus d'avoirs/retours que de ventes).

---

## Contrôles de plausibilité (à implémenter dans le rapport)

Reproduire ces vérifications évite un rejet côté AFC :

- **Cohérence CA imposable** : la somme des bases des positions 300–34x doit être
  cohérente avec le chiffre d'affaires imposable **299**. Un écart déclenche un rejet.
- **Cohérence impôt dû** : **399** doit égaler la somme des impôts calculés par taux + 38x.
- **Cohérence préalable** : **479** doit respecter `400 + 405 + 410 − 415 − 420`.
- **Résultat** : **500/510** doit respecter la formule payableTax ci-dessus.
- Un seul des deux (500 ou 510) est renseigné selon le signe du résultat.

---

## Chiffres hors périmètre (TDFN / taux forfaitaires)

À **ne pas** implémenter pour un assujetti en méthode effective. Listés pour complétude :

| Chiffre       | Contexte   | Description                                                                                                                      |
| ------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **470 / 471** | TDFN / TaF | Imputations spécifiques : exportations, impôt préalable fictif, imposition de la marge (anciens formulaires 1050 / 1055 / 1056). |

> Les formulaires 1050 / 1055 / 1056 sont **supprimés pour les périodes de décompte à partir
> du 01.01.2025**. En méthode effective, ces positions ne s'appliquent de toute façon pas.

---

## Récapitulatif : positions déclarées vs calculées

**Déclarées (saisies / dérivées des transactions)** :
`200, 205, 220, 221, 225, 230, 235, 280, 300–34x (par taux), 38x, 400, 405, 410, 415, 420, 900, 910`

**Calculées (dérivées par le rapport)** :
`299, 399, 479, 500/510`

**Signe dans la formule de résultat** (pour référence de codage) :

| Position             | Signe |
| -------------------- | ----- |
| impôt(300–34x) → 399 | +     |
| impôt(38x)           | +     |
| 400                  | −     |
| 405                  | −     |
| 410                  | −     |
| 415                  | +     |
| 420                  | +     |
