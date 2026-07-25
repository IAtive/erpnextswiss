# Bulletin QR suisse — configuration & émission

Émission de la **QR-facture** suisse (récépissé + section paiement) avec choix de la méthode par compte,
génération automatique de la référence, et **rendu local** (aucun service externe).

Conçu pour reproduire la clarté de bexio (trois options QR) tout en supprimant l'ambiguïté entre
**QR-IBAN** et **IBAN classique**. Référence technique : `FORK_CHANGES.md` §12.

---

## 1. Les trois méthodes (comme bexio)

La méthode se choisit **sur le compte de réception** (plan comptable), champ **« QR-Bill Method »** :

| Méthode | IBAN utilisé (réception) | Référence | Quand l'utiliser |
| --- | --- | --- | --- |
| **SCOR** | IBAN **classique** | RF… (ISO 11649, créancier) | Cas général, IBAN normal — pas besoin de QR-IBAN |
| **QRR** | **QR-IBAN** | 27 chiffres (structurée) | Si la banque fournit une QR-IBAN et un service de réconciliation QRR |
| **NON** | IBAN **classique** | *(aucune)* | Pas de référence structurée |

- **SCOR** et **QRR** produisent tous deux une référence **unique par facture** → rapprochement automatique
  identique. La QRR n'apporte qu'un écosystème bancaire plus intégré (avis camt.054 par référence).
- **NON** : le payeur inscrit la communication manuellement.

## 2. Où saisir les IBAN (le point important)

Deux champs **distincts** sur le compte de réception, aux rôles **séparés** :

| Champ | Contenu | Sert à |
| --- | --- | --- |
| **IBAN** | IBAN **classique** | Les **paiements** émis (pain.001), le prélèvement, la e-facture — et la réception SCOR/NON |
| **QR-IBAN** | QR-IBAN (institution 30000–31999) | **Uniquement** l'émission de QR-factures **QRR** |

> ⚠️ **Ne jamais mettre une QR-IBAN dans le champ IBAN.** Une QR-IBAN sert à *recevoir* (QRR), pas à *payer* :
> l'utiliser comme débiteur d'un pain.001 est non-standard et peut être rejeté par la banque. Un garde-fou
> **bloque** cette saisie et indique le bon champ.

**Recommandation** : si vous n'avez pas besoin de la QRR, mettez l'**IBAN classique** partout et utilisez
**SCOR** — la référence RF est tout aussi réconciliable, sans QR-IBAN et sans conflit.

## 3. Génération automatique de la référence

À l'enregistrement d'une **facture de vente**, la référence est générée **côté serveur** selon la méthode du
compte de réception, et stockée dans le champ unifié **`qr_reference`** (sans espaces, pour le rapprochement) :

- **SCOR** → `qr_reference` = RF… ; **QRR** → 27 chiffres ; **NON** → vide.
- **Immutabilité** : la méthode, l'IBAN et la référence sont **figés à l'émission**. Si vous changez plus tard
  la méthode du compte, les **factures déjà émises se réimpriment à l'identique** (seules les nouvelles
  prennent la nouvelle méthode).

## 4. Impression du bulletin

Format d'impression **« Swiss QR Invoice »** (facture + bulletin QR) :

- **Rendu local** (bibliothèque `qrbill`) — aucune donnée envoyée à un tiers, fonctionne hors-ligne.
- **Langue** = sélecteur *Language* de l'aperçu (fr / de / it / en ; repli anglais). Le bulletin **et** la
  facture suivent la langue choisie.
- Le bloc **« Payable by »** (payeur) est pré-rempli si l'adresse du client est complète (rue, NPA, localité,
  pays) ; sinon il est laissé **vide** (le payeur le complète) — le bulletin reste valide.
- Le code pays (`CH-`) devant le NPA est ajouté par le standard — comportement normal.

**Prérequis** : un **compte bancaire par défaut** sur la société (`Company.default_bank_account`) avec un IBAN,
une **adresse société complète** (créancier obligatoire), et une facture en **CHF ou EUR**. En cas de
configuration incomplète, l'impression affiche un encart d'erreur explicite au lieu d'échouer.

## 5. Côté achats — factures fournisseurs

Pour rapprocher automatiquement vos **paiements fournisseurs**, la facture d'achat doit porter la référence QR
du fournisseur dans le champ **`esr_reference_number`**. On le remplit en **scannant** le QR-code (ou la ligne
ESR) de la facture reçue (bouton *Scan Invoice*) : la référence, le montant et le fournisseur sont extraits.

Sans scan, le rapprochement retombe sur le montant et le tiers (voir `docs/bank_reconciliation.md`).

## 6. Résumé de la configuration

```
Compte de réception (plan comptable)
├─ IBAN            = IBAN classique   → paiements (pain.001), e-facture, réception SCOR/NON
├─ QR-IBAN         = QR-IBAN          → émission QRR uniquement
└─ QR-Bill Method  = SCOR | QRR | NON → méthode du bulletin

Société
└─ Compte bancaire par défaut → le compte de réception ci-dessus
```
