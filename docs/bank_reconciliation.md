# Rapprochement bancaire — import camt & matching

Import de relevés **camt.053** (avec ou sans l'app ALYF Banking), correct en **multidevises**, et
rapprochement automatique des factures via la **référence QR** et le **tiers**.

Référence technique : `FORK_CHANGES.md` §13 (import & enrichissement), §14 (intégration ALYF).

---

## 1. Vue d'ensemble

```
VENTE  : facture QRR/SCOR ──► qr_reference ──► QR-facture ──► client paie
                                                      │
ACHAT  : facture scannée  ──► esr_reference_number ──► paiement (pain.001)
                                                      │
                              relevé camt ◄───────────┘
                                    │
                     Import (Treasury) ──► Bank Transaction
                          · référence normalisée (sans espaces)
                          · tiers résolu (IBAN / nom)
                          · montant/taux FX
                                    │
                     Écran de réconciliation ──► la bonne facture proposée en tête
```

## 2. Import d'un relevé camt / ZIP

Bouton **« Import camt / ZIP »** (liste des Bank Transaction, ou écran de réconciliation ALYF) :

- Accepte un **XML** unique ou un **ZIP** de plusieurs relevés ; routage automatique **par IBAN** vers le
  bon compte bancaire.
- Autonome : **aucune licence fintech** requise.
- **Multidevises correct** : le montant et la devise de la Bank Transaction sont **toujours ceux du compte**
  (montant booké). Quand la devise d'origine diffère (ex. encaissement EUR sur compte CHF), l'opération est
  enrichie de la **devise d'origine**, du **montant d'origine** et du **taux appliqué par la banque**
  (section *Devise d'origine (FX)*).

Un récapitulatif indique le nombre d'écritures **importées / doublons ignorés / erreurs**.

## 3. Enrichissement automatique (aide au matching)

Chaque Bank Transaction importée est enrichie pour faciliter le rapprochement :

- **Référence** : la référence structurée (QRR/SCOR) du relevé est stockée **sans espaces** dans
  `reference_number` → **égalité exacte** avec `qr_reference` (vente) / `esr_reference_number` (achat).
- **Tiers** (`party`) : résolu par l'**IBAN** de la contrepartie (via son Bank Account) ou, à défaut, par son
  **nom exact** (client pour un encaissement, fournisseur pour un décaissement). Utile même **sans référence**.
  Aucune résolution ambiguë (pas de correspondance approximative).
- **PmtInfId** (section *Rapprochement (Treasury)*) : identifiant du bloc de paiement de votre pain.001, pour
  le bouclage des **paiements sortants** émis via la proposition de paiement.

> **Pour maximiser la résolution du tiers** : renseignez l'IBAN de vos clients/fournisseurs dans leur
> **Bank Account** — sinon seule la correspondance par nom exact s'applique.

## 4. Matching par référence

Le rapprochement compare la référence du relevé au bon champ de la facture :

| Flux | Champ facture | Source de la référence |
| --- | --- | --- |
| Vente → encaissement | `qr_reference` (QRR/SCOR) | généré à l'émission (voir `docs/swiss_qr_bill.md`) |
| Achat → décaissement | `esr_reference_number` | **scan** de la facture fournisseur |

Avec l'app **ALYF Banking**, ce mapping est **configuré automatiquement** (`Banking Settings` →
*Reference Fields*), de même que la pré-activation des types **Facture de vente + Facture d'achat**. Aucune
saisie manuelle à l'installation.

## 5. Rapprochement au taux banque (change)

Pour une transaction FX enrichie, le bouton **« Reconcile at bank rate »** crée le paiement alloué à la
facture **au taux exact de la banque** : l'écart de change est comptabilisé automatiquement en **6999**, sans
saisie de taux. La facture est soldée dans sa devise, la créance/dette en CHF.

## 6. Avec ou sans ALYF Banking

| | Sans ALYF | Avec ALYF |
| --- | --- | --- |
| Import camt / ZIP | ✅ (liste Bank Transaction) | ✅ (bouton sur l'écran ALYF) |
| Enrichissement (réf, tiers, FX, PmtInfId) | ✅ | ✅ |
| Écran de réconciliation | natif ERPNext | ALYF (config matching auto) |
| Rapprochement au taux banque | ✅ | ✅ |

Toute la partie ALYF est **gardée** : en son absence, ERPNextSwiss fonctionne de manière autonome.

## 7. Prérequis & rappels

- Un **Bank Account** par compte, avec l'**IBAN** figurant dans le relevé (routage).
- Pour la résolution du tiers par IBAN : IBAN renseigné sur les Bank Accounts des clients/fournisseurs.
- Pour le matching achat : **scanner** les factures fournisseurs (remplit `esr_reference_number`).
- Après déploiement de traductions : `bench --site <site> clear-cache`.
