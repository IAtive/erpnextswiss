#!/usr/bin/env python3
"""
Génère le plan comptable ERPNext (format verified/*.json) à partir de l'export bexio.

Règles appliquées (validées avec l'utilisateur) :
- Branche "9 Clôture" (classification Complete) : EXCLUE.
- Groupe "28 Capitaux propres" : PROMU en racine de premier niveau -> root_type = Equity
  (détaché de "2 Passifs"), car ERPNext ne lit root_type qu'au sommet de l'arbre.
- Comptes "Income" nichés sous des racines de charges (6/8) : héritent de Expense
  (fidèle à la structure suisse ; résultat net exact, cf. code ERPNext).
- account_type posé sur les comptes système + les comptes fonctionnels obligatoires.
- Ajout de 1000 "Caisse" (Cash), absent de bexio.
- 4800 "Variation des stocks de marchandises" mappé en Stock Adjustment.
"""
import json, os

SRC = os.path.join(os.path.dirname(__file__), "accounts-groups.json")
OUT = os.path.join(os.path.dirname(__file__), "ch_pme_fr.json")

d = json.load(open(SRC, encoding="utf-8"))
groups = d["groups"]
accounts = d["accounts"]
gById = {g["id"]: g for g in groups}

# ---- 1. Exclure la branche "9 Clôture" -------------------------------------
def descendants(gid):
    res = [gid]
    for g in groups:
        if g["parent_accounts_group_id"] == gid:
            res += descendants(g["id"])
    return res

g9 = next(g for g in groups if g["number"] == "9")
EXCL = set(descendants(g9["id"]))

# ---- 2. account_type par numéro de compte ----------------------------------
ACCOUNT_TYPE = {
    "1000": "Cash",              # ajouté
    "1020": "Bank",
    "1029": "Bank",
    "1100": "Receivable",
    # Comptes d'ACOMPTE : le type suit le LIEN PARTY, pas le côté bilan (pattern officiel ERPNext).
    #   1130 acompte VERSÉ fournisseur (Actif)  -> "Payable"   = lien fournisseur
    #   2030 acompte REÇU  client     (Passif)  -> "Receivable"= lien client
    # (utilisés avec l'option Company "Book Advance Payments in Separate Party Account")
    "1130": "Payable",
    "1170": "Tax", "1171": "Tax", "1172": "Tax", "1173": "Tax", "1174": "Tax",
    "1200": "Stock",
    "1500": "Fixed Asset", "1510": "Fixed Asset", "1520": "Fixed Asset", "1530": "Fixed Asset",
    "2000": "Payable",
    "2030": "Receivable",   # acompte reçu client (Passif) typé Receivable — voir note sur 1130
    "2200": "Tax", "2201": "Tax", "2202": "Tax", "2203": "Tax",
    "3200": "Income Account",
    "4200": "Cost of Goods Sold",
    "4800": "Stock Adjustment",
    "6945": "Round Off",
}

# ---- 2bis. Renommage / exclusion de comptes (vs noms bruts bexio) -----------
# Un SEUL compte banque CHF : 1020 renommé "Banque CHF", et le placeholder générique
# "Bank" (1029) est retiré du plan (jamais utilisé).
ACCOUNT_RENAME = {
    "1020": "Banque CHF",
}
EXCLUDE_ACCOUNTS = {"1029"}

# --- Comptes désactivés par défaut (Option A : modèle mono-compte de change d'ERPNext) ---
# 6949 "Pertes de change" : ERPNext utilise UN SEUL compte pour les gains ET les pertes de change
# (Company.exchange_gain_loss_account = 6999). 6949 ne recevrait donc jamais d'écriture.
# Impact comptable NUL (résultat net et bilan identiques ; on perd seulement la vue séparée
# gains/pertes bruts, la présentation suisse CO 959b étant de toute façon nette).
#
# ⚠️ Le format des charts "verified/" NE SUPPORTE PAS de flag `disabled` (create_charts l'ignore et
# une clé "disabled" serait interprétée comme un compte enfant → import cassé). On GARDE donc 6949
# dans le plan (fidélité bexio, réactivable), et sa DÉSACTIVATION effective est appliquée APRÈS
# création par `erpnextswiss.swiss_vat_config.company_setup` (disable_unused_accounts). Constante ci-dessous
# = simple documentation de la décision.
DISABLED_BY_DEFAULT = ["6949"]  # désactivé post-création par company_setup.disable_unused_accounts (le JSON ne peut pas le porter)

# ---- 3. Racines de premier niveau et leur root_type ------------------------
ROOT_TYPE = {
    "1": "Asset",
    "2": "Liability",
    "28": "Equity",   # promu
    "3": "Income",
    "4": "Expense",
    "5": "Expense",
    "6": "Expense",
    "8": "Expense",
}

g28 = next(g for g in groups if g["number"] == "28")

# enfants (groupes) par parent, en retirant 28 de sous 2 et en excluant la branche 9
child_groups = {}
for g in groups:
    if g["id"] in EXCL:
        continue
    parent = g["parent_accounts_group_id"]
    if g["id"] == g28["id"]:
        parent = None  # promotion : 28 devient racine
    child_groups.setdefault(parent, []).append(g)

# comptes par groupe
child_accts = {}
for a in accounts:
    if a["accounts_group_id"] in EXCL:
        continue
    child_accts.setdefault(a["accounts_group_id"], []).append(a)

# ---- 4. Construction récursive de l'arbre ----------------------------------
def build_group(g, is_root=False):
    node = {"account_number": g["number"], "is_group": 1}
    if is_root:
        node["root_type"] = ROOT_TYPE[g["number"]]
    # sous-groupes puis comptes, triés par numéro
    subs = sorted(child_groups.get(g["id"], []), key=lambda x: x["number"])
    accs = sorted(child_accts.get(g["id"], []), key=lambda x: x["number"])
    for sg in subs:
        node[sg["name"]] = build_group(sg)
    for a in accs:
        if a["number"] in EXCLUDE_ACCOUNTS:
            continue
        leaf = {"account_number": a["number"]}
        at = ACCOUNT_TYPE.get(a["number"])
        if at:
            leaf["account_type"] = at
        node[ACCOUNT_RENAME.get(a["number"], a["name"])] = leaf
    return node

tree = {}
roots = sorted(child_groups.get(None, []), key=lambda x: x["number"])
for r in roots:
    tree[r["name"]] = build_group(r, is_root=True)

# ---- 5. Ajout du compte 1000 "Caisse" sous "Trésorerie" (groupe 100) -------
def find_group_node(node, number):
    if node.get("account_number") == number:
        return node
    for k, v in node.items():
        if isinstance(v, dict):
            r = find_group_node(v, number)
            if r:
                return r
    return None

tresorerie = None
for r in tree.values():
    tresorerie = find_group_node(r, "100")
    if tresorerie:
        break
assert tresorerie is not None, "Groupe 100 (Trésorerie) introuvable"
# insérer la Caisse en tête des comptes de trésorerie
caisse = {"Caisse": {"account_number": "1000", "account_type": "Cash"}}
# reconstruire le dict pour garder la Caisse juste après les métadonnées
rebuilt = {}
for k, v in tresorerie.items():
    rebuilt[k] = v
    if k == "is_group":
        rebuilt["Caisse"] = caisse["Caisse"]
tresorerie.clear()
tresorerie.update(rebuilt)

chart = {
    "country_code": "ch",
    "name": "Suisse - Plan comptable PME (Bexio) - FR",
    "tree": tree,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(chart, f, indent=2, ensure_ascii=False)

print("Écrit :", OUT)
