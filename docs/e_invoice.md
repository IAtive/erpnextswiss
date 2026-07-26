# E-facturation (e-invoice) — EN 16931 / Factur-X

Émission et lecture de **factures électroniques structurées** (EN 16931 / Factur-X / XRechnung) pour les
échanges avec l'UE, via l'app **`eu_einvoice`** (ALYF, optionnelle) et les adaptations suisses du fork.

Référence technique : `FORK_CHANGES.md` §18. À ne pas confondre avec la **QR-facture** suisse
(`docs/swiss_qr_bill.md`) : la QR-facture sert à **payer** en Suisse, l'e-invoice porte les **données
structurées** de la facture pour l'UE.

---

## 1. Quand l'e-invoice s'applique (rappel)

| Tu factures… | e-invoice ? |
| --- | --- |
| Client **suisse** privé | ❌ Non — QR-facture (voir `docs/swiss_qr_bill.md`) |
| **Administration fédérale CH** (B2G > 5 000 CHF) | ✅ Oui |
| Client **UE** (DE, FR…) | 🟡 De plus en plus exigé par le client (mandats UE 2025-2030) |

C'est **surtout pour le cross-border UE**. En Suisse domestique, la QR-facture suffit.

## 2. Comment ça marche ici

- L'e-invoice est produite par l'app **`eu_einvoice`** (si installée). Elle **valide** la facture contre les
  règles métier EN 16931 (**Schematron**, plus strict qu'un simple contrôle de structure).
- Le fork ajoute deux adaptations suisses (`einvoice_compat`, §18) :
  - le **numéro TVA suisse (UID)** du vendeur est correctement émis comme **identifiant TVA (BT-31)** ;
  - le **profil par défaut** est **EN 16931** (au lieu d'EXTENDED), sur le Client et la facture.
- Un onglet **« E Invoicing »** apparaît sur la Sales Invoice, le Customer, le Supplier et la Company.

## 3. Informations REQUISES pour une e-invoice valide

La validation EN 16931 échoue tant que ces informations manquent. Les principales :

| Donnée | Où | Règle EN 16931 |
| --- | --- | --- |
| **Numéro TVA du vendeur** (UID `CHE-…MWST`) | Company → **Tax ID** | BT-31 · BR-CO-26, BR-S-02 |
| **Adresse société complète** (rue, NPA, localité, pays) | Company (adresse liée) | BG-4 |
| **Adresse client complète** | Customer (adresse liée) | BG-7 |
| **Numéro TVA du client** (si assujetti) | Customer → **Tax ID** | BT-48 |
| **TVA correcte sur les lignes** (ex. 8.1 % si « taux normal ») | Taxes de la facture | BR-S-05, BR-S-08 |
| **Devise, date d'échéance, totaux** | Sales Invoice | BG-22, BT-9 |
| **Référence acheteur** (`buyer_reference`) | Customer / Sales Invoice | BT-10 (obligatoire pour le B2G allemand : Leitweg-ID) |

> ⚠️ Le **numéro TVA (UID)** de la société est le point le plus souvent oublié : sans lui, la facture est
> **rejetée** (BR-CO-26). Format : `CHE-123.456.789 MWST` (la **clé de contrôle** doit être valide).

## 4. Choisir le profil

Le profil se règle **par client** (Customer → E Invoicing → *E Invoice Profile*), la facture en hérite.

| Profil | Quand |
| --- | --- |
| **EN 16931** | ✅ Défaut — cas général B2B UE, accepté partout |
| **XRECHNUNG** | Secteur **public allemand** (B2G) ou client DE qui l'exige |
| **EXTENDED** | Seulement si un client réclame des champs hors du cœur EN 16931 (rare) |
| **BASIC** | Quasi jamais |

## 5. Si tu n'utilises PAS l'e-invoice — désactiver les erreurs/avertissements

Par défaut, `eu_einvoice` **valide chaque facture au save et au submit** et affiche les erreurs. Si tu ne
fais pas d'e-invoice (ex. clients suisses uniquement), désactive la validation dans **E Invoice Settings** :

| Réglage | Effet | Pour ne pas être gêné |
| --- | --- | --- |
| **Validate Sales Invoice on Save** | valide à l'enregistrement | **décocher** |
| **Validate Sales Invoice on Submit** | valide à la validation | **décocher** |
| **Action on Validation Error during Save** | *(vide)* / Warning Message / Error Message | mettre **(vide)** ou **Warning** (jamais bloquant) |
| **Action on Validation Error during Submit** | *(vide)* / Warning Message / Error Message | mettre **(vide)** ou **Warning** |

- **Décocher les deux « Validate »** → plus aucune validation ni message e-invoice sur les factures.
- Ou garder la validation mais mettre l'action sur **(vide)** / **Warning Message** → les erreurs
  s'affichent sans **bloquer** le save/submit (`Error Message` = bloquant).

→ Ainsi, une PME 100 % suisse peut installer l'app (ou la laisser installée) **sans être bloquée** par les
règles EN 16931 sur des factures qui n'en ont pas besoin.

## 6. Émettre / importer

- **Émettre** : Sales Invoice → onglet E Invoicing → profil → menu **⋮ → « Download eInvoice »** (Factur-X
  PDF ou XML). L'XML peut aussi s'attacher automatiquement au submit (E Invoice Settings → *Auto-attach XML*).
- **Importer** : nouveau **« E Invoice Import »** → uploader le XML/PDF reçu → crée la **Purchase Invoice**.
  (Le **ZUGFeRD Wizard** interne du fork lit en plus le **QR-bill suisse** et le **QR UE**.)

## 7. Récapitulatif

```
Pré-requis e-invoice valide (EN 16931) :
├─ Company.Tax ID = UID suisse (CHE-…MWST, clé valide)   ← indispensable (BT-31)
├─ Adresses société + client complètes
├─ TVA correcte sur les lignes (8.1 % / 2.6 % / 3.8 %)
└─ Profil = EN 16931 (défaut) ; XRECHNUNG pour le public allemand

Pas d'e-invoice ? → E Invoice Settings : décocher « Validate on Save/Submit »
                    (ou action = vide / Warning, jamais Error/bloquant)
```
