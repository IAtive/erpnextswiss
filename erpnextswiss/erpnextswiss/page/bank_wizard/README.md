# Bank Wizard — écran de rapprochement bancaire

Le Bank Wizard importe un relevé **camt.053** (ISO 20022) et propose, **ligne par ligne**, de
comptabiliser la transaction (Payment Entry). Cette page décrit **chaque bouton d'action** : quand il
s'affiche, quand l'utiliser, et l'effet exact qu'il produit.

> Ce fichier documente le comportement **du fork IAtive** (voir `../../../FORK_CHANGES.md` §5).

---

## 1. Lire la colonne « Rapprochement » (badges)

Avant d'agir, le Wizard indique son niveau de confiance :

| Badge | Sens | Origine |
|---|---|---|
| **✓** (vert) | facture(s) rapprochée(s), **montant exact** | référence de paiement ou QR‑facture + montant au centime |
| **≈** (orange) | facture(s) rapprochée(s), **écart de montant** | tolérance **CHF 5 OU 2 %** (escompte / frais / arrondi) |
| **tiers** (bleu) | **tiers identifié** (par nom), pas de facture précise | nom du donneur d'ordre reconnu |
| _(rien)_ | **non identifié** | ni facture ni tiers |

## 2. Deux familles de boutons

- **Rapide — « Book » (⟶) et « Pattern » (🪄)** : crée **ET soumet** le Payment Entry immédiatement
  (`auto_submit`). À réserver aux rapprochements **sûrs** (badge ✓ ou ≈).
- **Ciblée / repli — boutons nommés** (Sales Invoice, Customer, Receivables, Intermediate…) : crée un
  **brouillon** que tu relis/complètes avant *Submit*. Rien n'est soumis automatiquement.

> Rappel : les boutons **Book/Pattern** produisent une écriture **soumise** (pour l'annuler il faut la
> *Cancel*). Les boutons nommés laissent un **brouillon** modifiable.

---

## 3. Ligne ENTRANTE — CRDT (encaissement, un client te paie)

| Bouton | S'affiche quand | Quand l'utiliser | Effet |
|---|---|---|---|
| **Book** ⟶ | facture(s) client rapprochée(s) **et** montant exact **ou** dans la tolérance ≈ | rapprochement sûr, en 1 clic | Payment Entry (Receive) **avec référence** à la/les facture(s), compte **1100**, **soumis** → facture(s) soldée(s) |
| 🪄 **Pattern** | un *Bank Wizard Pattern* correspond | frais/déductions récurrents (ex. commissions) | applique le **modèle** de déductions prédéfini **+ soumet** |
| **Sales Invoice** | facture(s) client rapprochée(s) | tu veux **relire** avant de valider | paiement **avec référence** (1100), en **brouillon** |
| **Customer** | tiers **client identifié**, sans facture précise | encaissement **sans facture** (acompte, à allouer plus tard) | paiement **on‑account** sur le client → **2030** si séparation activée (sinon 1100) ; **brouillon** |
| **Receivables** | **toujours** | tiers **inconnu**, à imputer sur un client générique | paiement on‑account sur le **client par défaut** ; brouillon |
| **Intermediate** | **toujours** | rien ne colle / à clarifier plus tard | parque le montant sur le **compte d'attente (1099)** ; brouillon |

## 4. Ligne SORTANTE — DBIT (décaissement, tu paies quelqu'un)

| Bouton | S'affiche quand | Quand l'utiliser | Effet |
|---|---|---|---|
| **Book** ⟶ | facture(s) fournisseur rapprochée(s) **et** montant exact **ou** tolérance ≈ | rapprochement sûr | Payment Entry (Pay) **avec référence**, compte **2000**, **soumis** → facture(s) soldée(s) |
| ⟶ **Expense** | note de frais rapprochée **et** montant exact | remboursement de note de frais sûr | paiement **avec référence Expense Claim**, **soumis** |
| 🪄 **Pattern** | un *Bank Wizard Pattern* correspond | frais récurrents | applique le **modèle** + soumet |
| **Purchase Invoice** | facture(s) fournisseur rapprochée(s) | relire avant de valider | paiement **avec référence** (2000), **brouillon** |
| **Supplier** | tiers **fournisseur identifié**, sans facture | décaissement **sans facture** (acompte) | paiement **on‑account** fournisseur → **1130** si séparation activée (sinon 2000) ; brouillon |
| **Expense Claim** | note de frais rapprochée | imputer sur une note de frais | paiement **avec référence Expense Claim**, brouillon |
| **Employee** | **employé identifié** | frais / avance employé | paiement on‑account sur l'**employé** ; brouillon |
| **Payables** | **toujours** | fournisseur inconnu | on‑account sur le **fournisseur par défaut** ; brouillon |
| **Intermediate** | **toujours** | à clarifier plus tard | compte d'attente **1099** ; brouillon |

---

## 5. Points importants

- **Facture vs acompte** :
  - **Book / Sales Invoice / Purchase Invoice** = rapprochement d'une **facture** → compte de tiers
    **normal 1100 / 2000** (le fork pose ce compte **et** la référence avant l'insert, cf.
    `FORK_CHANGES.md` §5.3).
  - **Customer / Supplier** = encaissement/décaissement **on‑account** (sans facture) → compte
    **d'acompte 2030 / 1130** si l'option *Book Advance Payments in Separate Party Account* est activée.
    C'est **volontaire** : un paiement non alloué est un acompte.
- **Appliquer un acompte à une facture APRÈS coup** : ne rattache pas la facture au paiement à la main
  (ERPNext bloque : comptes 2030 ≠ 1100). Utilise **Accounts → Payment Reconciliation**, qui génère le
  transfert 2030 → 1100 et solde la facture.
- **Intermediate (1099)** : compte d'attente paramétré dans *ERPNextSwiss Settings*. Sert de **parking**
  pour les lignes non identifiées ; à solder ensuite par une réaffectation.
- **Tolérance ≈** : le bouton *Book* s'active aussi quand l'écart est dans **CHF 5 / 2 %** (escompte,
  frais bancaires, arrondi). L'écart n'est **pas** encore auto‑ventilé — relis le brouillon si besoin
  (ou utilise un *Pattern* pour les frais récurrents).
- **Multi‑devises** : le taux de change est repris/recalculé automatiquement selon la devise du compte
  bancaire.

## 6. En cas d'erreur « associated with 1100, but Party Account is 2030 »

**Quand ça arrive** : cette erreur ne se produit **que si l'option « Book Advance Payments in Separate
Party Account » est activée** (*Accounts Settings*). C'est elle qui route les paiements **non alloués**
vers un **compte d'acompte séparé** (2030 en encaissement / 1130 en décaissement). Si l'option est
**désactivée**, les paiements on‑account passent directement par 1100 / 2000 → **cette erreur n'existe pas**.

**Cause** : avec l'option activée, un paiement créé **on‑account** (bouton *Customer / Supplier*) est logé
sur le **compte d'acompte** (2030 / 1130). Quand tu lui **rattaches une facture ensuite**, ERPNext **ne met
PAS à jour le compte automatiquement** — il **garde le compte d'acompte**, alors que la facture est sur
1100 / 2000 → mismatch au moment d'enregistrer.

**Correctif (paiement encore en brouillon)** : dans le Payment Entry, **change le compte de tiers à la
main** pour qu'il corresponde à la facture, puis enregistre :

| Sens du paiement | Champ à modifier | Changement |
|---|---|---|
| **Encaissement** (Receive) | **« Account Paid From »** (Compte payé depuis) | **2030 → 1100** (Créances suisses) |
| **Décaissement** (Pay) | **« Account Paid To »** (Compte payé vers) | **1130 → 2000** (Dettes fournisseurs) |

Une fois le compte aligné sur celui de la facture, l'enregistrement passe.

> ERPNext **ne le fait pas tout seul** : passer de 2030 à 1100, ce n'est pas « corriger un champ », c'est
> **déplacer de l'argent** de l'acompte vers la créance — il ne le modifie pas dans ton dos, il te
> signale l'incohérence et te laisse trancher.

**Alternatives** :
- **C'était un vrai acompte** (à garder sur 2030/1130) que tu veux appliquer à une facture, **ou** le
  paiement est **déjà soumis** : ne touche pas les comptes → utilise **Accounts → Payment Reconciliation**,
  qui génère le transfert **2030 → 1100** proprement.
- Au **rapprochement direct** (boutons **Book / Sales Invoice / Purchase Invoice**), le fork (§5.3) pose
  déjà le bon compte → cette manip n'est **jamais** nécessaire. Elle ne concerne que le cas
  *Customer/Supplier puis facture rattachée à la main*.
