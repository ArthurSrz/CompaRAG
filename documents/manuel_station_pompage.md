# Manuel de maintenance — Station de pompage de Vaux-sur-Orge

Document interne. Version 4.2 — mise à jour du 14 mars 2025.
Rédacteur : M. Berthier, responsable exploitation.

## 1. Identification des équipements

La station comporte quatre organes principaux, repérés sur le synoptique du
local technique. Chaque numéro de série est gravé sur la plaque signalétique
fixée au carter.

| Repère | Équipement | Numéro de série | Mise en service |
|---|---|---|---|
| P1 | Pompe de relevage n°1 | VX-88114-A | juin 2018 |
| P2 | Pompe de relevage n°2 | VX-88115-A | juin 2018 |
| T3 | Turbine de recirculation | VX-21007-C | mars 2021 |
| V4 | Vanne motorisée amont | VX-44902-M | mars 2021 |

Les deux pompes de relevage fonctionnent en alternance hebdomadaire. Le
basculement est automatique ; il peut être forcé depuis l'armoire de commande.

## 2. Pièces de rechange référencées

Les références ci-dessous sont celles du magasin central. Toute commande passe
par le formulaire interne et doit mentionner la référence exacte : plusieurs
organes se ressemblent et ne sont pas interchangeables.

| Organe | Référence | Stock magasin |
|---|---|---|
| Palier avant turbine T3 | PAL-3300-A | 2 |
| Palier arrière turbine T3 | PAL-3300-B | 1 |
| Garniture mécanique P1 / P2 | GAR-1180-K | 4 |
| Membrane de vase d'expansion | MEM-0475-E | 0 |
| Carte de commande V4 | CMD-7720-R | 1 |
| Joint torique de bride DN150 | JTO-0150-N | 12 |

La membrane MEM-0475-E est en rupture depuis janvier 2025. Délai annoncé par
le fournisseur : six semaines.

## 3. Seuils d'alarme et codes défaut

L'automate remonte les défauts sous forme de codes à trois chiffres précédés
de la lettre E. Un code actif s'affiche en rouge sur le pupitre et déclenche
l'envoi d'un message à l'astreinte.

| Code | Condition | Conduite à tenir |
|---|---|---|
| E-204 | Niveau vibratoire supérieur à 4,5 mm/s | Alerte. Planifier un contrôle sous quinzaine. |
| E-207 | Niveau vibratoire supérieur à 9,0 mm/s | Arrêt immédiat de la machine concernée. |
| E-112 | Température de palier supérieure à 85 °C | Arrêt immédiat. Vérifier le graissage. |
| E-330 | Défaut d'isolement moteur inférieur à 0,5 MΩ | Consignation électrique obligatoire avant toute intervention. |
| E-451 | Perte de signal du capteur de niveau amont | Passer en commande manuelle. Surveillance visuelle. |

Le seuil E-204 a été abaissé de 6,0 à 4,5 mm/s en septembre 2024, après
l'incident sur la turbine T3.

## 4. Conduite à tenir en cas d'incident

### Dépassement de la cote amont

Lorsque le niveau amont franchit la cote 12,40 m NGF alors que les deux pompes
de relevage tournent déjà, l'excédent s'évacue par le trop-plein vers le bassin
tampon. Ce fonctionnement est normal et ne demande aucune action.

Si le déversement gagne la passerelle de service, la situation n'est plus
normale. Il faut alors fermer la vanne motorisée V4, consigner l'installation
et prévenir l'astreinte au 06 12 34 56 78. Ne jamais emprunter la passerelle
tant que le déversement n'a pas cessé : le revêtement devient glissant et le
garde-corps ne protège pas d'une chute vers le bassin.

### Démarrage impossible d'une pompe

Vérifier dans l'ordre : la position du sectionneur en armoire, la présence du
code E-330, l'état du relais thermique, puis la rotation libre de l'arbre à la
main. Si l'arbre ne tourne pas librement, ne pas forcer : la garniture
mécanique est probablement grippée et son remplacement relève de l'atelier.

### Bruit anormal sur la turbine

Un sifflement continu signale généralement une cavitation, liée à un niveau
amont trop bas. Un claquement périodique, lui, oriente vers un palier. Relever
le niveau vibratoire avant toute dépose : si la valeur reste sous 4,5 mm/s, le
bruit peut être surveillé une semaine avant décision.

## 5. Entretien périodique

| Opération | Périodicité | Durée |
|---|---|---|
| Relevé vibratoire des quatre organes | Mensuelle | 45 min |
| Graissage des paliers de turbine | Trimestrielle | 1 h |
| Contrôle de la pression du vase d'expansion | Semestrielle | 30 min |
| Mesure d'isolement des moteurs | Annuelle | 2 h |
| Épreuve du clapet anti-retour | Annuelle | 3 h |

La pression du vase d'expansion doit rester comprise entre 1,0 et 1,5 bar à
froid. Un écart persistant signale une membrane percée et impose le
remplacement du vase complet, la membrane seule n'étant pas démontable sur ce
modèle.

## 6. Journal des interventions

**14 mars 2025** — Relevé vibratoire. Turbine T3 à 7,2 mm/s, au-delà du seuil
d'alerte. Les trois autres organes sont conformes. Préconisation : arrêt
programmé sous quinzaine et remplacement du palier arrière, référence
PAL-3300-B, disponible en magasin.

**8 février 2025** — Remplacement de la garniture mécanique de P2, référence
GAR-1180-K. Intervention de 3 h, station à l'arrêt. Essais concluants.

**19 janvier 2025** — Apparition du code E-451 pendant quatre heures. Capteur
de niveau amont encrassé. Nettoyage et remise en service sans remplacement.

**6 décembre 2024** — Contrôle d'isolement annuel. P1 à 42 MΩ, P2 à 38 MΩ,
T3 à 51 MΩ. Aucune valeur proche du seuil E-330.
