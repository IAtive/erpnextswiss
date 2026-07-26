# Proposition de paiement (pain.001)

Génération d'un fichier de paiement **pain.001** à partir des factures fournisseurs ouvertes,
des notes de frais et des salaires, avec sélection automatique des pièces à payer selon leur
échéance.

Le paramétrage se fait dans **ERPNextSwiss Settings → Automated Payments**.

---

## 1. Vue d'ensemble

Une proposition de paiement (`Payment Proposal`) rassemble, pour une société donnée, les
engagements à régler :

- **Factures d'achat** soumises et non soldées (`outstanding_amount > 0`) ;
- **Notes de frais** (`Expense Claim`) approuvées et impayées ;
- **Salaires** en attente de paiement.

La proposition produit ensuite un fichier **pain.001** transmis à la banque (e-banking), et
marque les pièces reprises (`is_proposed = 1`) pour éviter de les proposer deux fois.

## 2. Période de planification (jours)

**Champ :** `planning_days` — *ERPNextSwiss Settings → Automated Payments* → **« Période de
planification (jours) »** · **Défaut : 7**

Ce paramètre définit **l'horizon d'anticipation** de la proposition : à sa création (sans date
imposée), la date de référence est fixée à **aujourd'hui + N jours**.

Règle de sélection appliquée aux factures d'achat :

| Échéance de la facture | Reprise dans la proposition ? |
| --- | --- |
| Déjà échue (échéance passée) | ✅ oui |
| Échéance ≤ aujourd'hui + N jours | ✅ oui |
| **Échéance > aujourd'hui + N jours** | ❌ **non** |

Autrement dit : **les paiements dont l'échéance dépasse ce délai ne sont pas proposés.** Ils le
seront automatiquement lorsqu'ils entreront dans la fenêtre, lors d'une prochaine proposition.

> **Escompte (skonto).** Si une facture bénéficie d'un délai d'escompte, c'est la **date
> d'escompte** qui est prise en compte lorsqu'elle est plus proche que l'échéance : une facture
> est donc reprise dès que sa date d'escompte tombe dans l'horizon, afin de ne pas perdre la
> remise même si l'échéance nette est plus lointaine.

**Choisir la valeur.** Elle doit correspondre à la **fréquence à laquelle on lance les
paiements** :

- paiements **hebdomadaires** → 7 jours (défaut) : chaque semaine on prépare ce qui arrive à
  échéance dans les 7 jours ;
- paiements **bihebdomadaires** → 14 ; **mensuels** → 30/31.

Une valeur trop **faible** fait manquer des échéances entre deux exécutions (risque de retard) ;
une valeur trop **élevée** anticipe des paiements et pèse inutilement sur la trésorerie.

> **Champ obligatoire.** Sans valeur (`0` ou vide), la création d'une proposition échoue avec le
> message *« Please configure the planning period in ERPNextSwiss Settings »*. Le **contrôle de
> configuration** (rapport *Controle de configuration*) le signale.

## 3. Numéro de participant (BVR/ESR)

**Champ :** `participant_number` — *ERPNextSwiss Settings → Automated Payments*.

Numéro d'adhérent utilisé pour les paiements de type BVR/ESR sortants. À renseigner uniquement si
ce mode de paiement est utilisé.

---

Référence technique : doctype `Payment Proposal`
(`erpnextswiss/erpnextswiss/doctype/payment_proposal/payment_proposal.py`).
