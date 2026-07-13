# Aegis Router

Prototype de recherche sur le routage P2P resilient aux Sybils, avec
apprentissage par renforcement leger (MARL) et crypto post-quantique. Il vise
l'anonymat, mais ne le livre pas encore: le chemin est actuellement en clair.

## Ce que fait le projet

Le coeur du projet evalue des routeurs ou chaque noeud ne voit que ses voisins
directs (latence, perte, stabilite, bande passante). Les routeurs doivent livrer
des paquets sans identite ni topologie globale, face a des noeuds Sybil
malveillants, du churn, et de la congestion. `eigentrust` est l'exception
documentee: une baseline comparative a information globale partagee.

## Solvers disponibles

| Solver | Description |
|---|---|
| `shortest` | Plus court chemin par nombre de sauts (baseline naïve) |
| `qlocal` | Q-learning local (epsilon-greedy) |
| `hybrid` | Scorer déterministe v0.2 (link quality + progress + anti-loop) |
| `risk-aware` | Budget de risque par paquet + réputation online par pair |
| `adaptive-risk` | Budget de risque adaptatif (relaxe si drops, resserre si sybil) |
| `eigentrust` | Baseline EigenTrust a information globale partagee, pre-trust uniforme ou ancres externes explicites |
| `edge` | Apprentissage persistant par edge orienté + chemins trusted 2-3 hops |
| `edge-light` | Variante allégée sans trusted paths |

## Composants

- **Simulateur discret** (`event_sim.py`): trafic Poisson, files d'attente,
  pertes stochastiques, TTL, churn, congestion.
- **Daemon UDP réel** (`daemon.py`): chaque noeud tourne en asyncio UDP sur
  localhost, vraies signatures ML-DSA-44, reçus signés de livraison.
  Même interface `RoutingSolver.next_hop()` que le simulateur.
- **Crypto post-quantique** (`postquantum_crypto.py`): signatures ML-DSA-44
  et encapsulation ML-KEM-768 (Kyber) via `pqcrypto`.
- **Redondance source-path**: copies disjointes d'un même paquet pour
  casser le plafond node_down en cas de churn.
- **Reçus de livraison signés**: la destination signe un accusé qui remonte
  le chemin inverse, preuve non forgeable qu'un paquet est arrivé.
- **Métriques Sybil nuancées**: `touched_transit_sybil` distingue un sybil
  choisi comme relais (action de routage) d'un sybil destination finale.

## Quick start

```bash
# Installer les dépendances
pip install -r requirements.txt

# Simu discrète comparative
python -m aegis_router.event_demo --nodes 80 --duration 8 --traffic-rate 12 \
    --sybil-ratio 0.2 --drain 5

# Avec apprentissage persistant multi-run
python -m aegis_router.event_demo --learn --learn-mode edge --runs 5 \
    --state aegis_state.json --nodes 80 --duration 8 --traffic-rate 12 \
    --sybil-ratio 0.2 --drain 5

# Daemon UDP réel (loopback)
python -m aegis_router.daemon --nodes 40 --duration 15 --traffic-rate 8 \
    --solver edge --sybil-ratio 0.15 --redundancy 2 --receipts

# Benchmark multi-seed avec IC95 et comparaisons appariees
.venv/bin/python3 scripts/real_network_benchmark.py --nodes 60 --topology-seeds 3 \
    --solvers shortest,eigentrust,edge --redundancy 2 --sybil-extra-drop 0.12
```

## Orientation issue de l'etat de l'art

La trajectoire de recherche est volontairement separee en baselines mesurables
et mecanismes deployables:

1. **Phase 0, actuelle:** comparer `edge` a `shortest` et a une baseline
   EigenTrust globale, avec seeds apparies, IC95, exposition Sybil brute et
   transit, livraison et sauts. Le ledger global est un instrument de recherche,
   pas un protocole decentralise. Il n'utilise jamais les labels Sybil caches.
2. **Phase 1:** introduire un graphe d'endossements explicite et etudier la
   responsabilite avec propagation arriere de RepuLink
   ([arXiv:2606.08851](https://arxiv.org/abs/2606.08851)). Solidago
   ([arXiv:2211.01179](https://arxiv.org/abs/2211.01179)) motive le pre-trust
   explicite et une future baseline LipschiTrust, pas l'ajout d'un oracle.
3. **Phase 2:** distribuer les calculs par gossip et mesurer les transitions de
   phase de la transitivite de confiance
   ([arXiv:1012.1358](https://arxiv.org/abs/1012.1358)). BASALT
   ([arXiv:2102.04063](https://arxiv.org/abs/2102.04063)) appartient a la
   selection de pairs resistante aux attaques Eclipse, en amont du routage.
4. **Phase exploratoire:** reprendre les variables locales utiles de
   Agentic-SecPBFT ([arXiv:2607.03269](https://arxiv.org/abs/2607.03269)) sans
   transposer PBFT, les labels malveillants connus ni l'entrainement global de
   son cadre experimental.

Limites actuelles: aucun audit de securite, chemin `path` en clair donc anonymat
non livre, PQC utilisee pour les signatures et recus mais pas dans la decision de
routage, et validation reseau limitee au loopback sur au plus 80 noeuds.

## Validation Phase 0 (2026-07-13)

Campagne UDP loopback held-out sur les seeds `30000-30009`, appariees entre
solveurs. Regime: 40 noeuds, degree 4, 20 s + 5 s de drain, trafic 12/s,
`sybil_ratio=0.15`, `sybil_stealth=0.5`, `sybil_extra_drop=0.65`,
`churn_rate=0.05`, `congestion_rate=0.1`, ARQ=2, redondance=1, sans recus.
EigenTrust utilise le pre-trust uniforme. Edge repart d'un etat propre par seed,
effectue 4 runs d'apprentissage, puis contribue une seule moyenne tail-2.

```bash
.venv/bin/python3 scripts/real_network_benchmark.py \
  --nodes 40 --degree 4 --duration 20 --drain 5 --traffic-rate 12 \
  --sybil-ratio 0.15 --sybil-stealth 0.5 --sybil-extra-drop 0.65 \
  --churn-rate 0.05 --congestion-rate 0.1 --link-retries 2 --redundancy 1 \
  --topology-seeds 10 --base-seed 30000 --learn-runs 4 --tail 2 \
  --solvers shortest,eigentrust,edge
```

| Solver | Livraison IC95 | Sybil brut IC95 | Sybil transit IC95 | Hops IC95 |
|---|---:|---:|---:|---:|
| `shortest` | 54.0% [50.22; 57.81] | 26.6% [20.87; 32.23] | 17.5% [12.28; 22.72] | 2.68 [2.63; 2.74] |
| `eigentrust` | 47.0% [43.14; 50.78] | 28.2% [19.71; 36.63] | 20.6% [12.77; 28.36] | 4.82 [4.52; 5.12] |
| `edge` | 66.4% [62.24; 70.49] | 22.4% [18.30; 26.41] | 10.9% [7.92; 13.95] | 3.57 [3.43; 3.72] |

Spreads inter-seed, dans le meme ordre de metriques:

| Solver | Livraison | Sybil brut | Sybil transit | Hops |
|---|---:|---:|---:|---:|
| `shortest` | 17.49 pp | 24.60 pp | 22.25 pp | 0.25 |
| `eigentrust` | 16.30 pp | 36.08 pp | 36.37 pp | 1.50 |
| `edge` | 15.16 pp | 17.00 pp | 13.01 pp | 0.72 |

Ecarts apparies contre `shortest`, positifs quand ils constituent un gain:

- `edge`: livraison `+12.35 pp [9.94; 14.75]`, reduction Sybil brute
  `+4.20 pp [1.29; 7.11]`, reduction Sybil transit
  `+6.56 pp [3.57; 9.56]`, tous significatifs. Cout significatif:
  `+0.89 hop [0.75; 1.03]`.
- `eigentrust`: livraison `-7.06 pp [-9.52; -4.59]` et
  `+2.13 hops [1.84; 2.43]`, regressions significatives. Les variations Sybil
  brute et transit ne sont pas significatives.

Conclusion limitee a ce regime: edge est au-dessus des deux baselines pour la
livraison et l'exposition Sybil transit, au prix de chemins plus longs.
EigenTrust global glouton est une baseline informative mais pas une direction de
deploiement en l'etat. Cette campagne ne prouve ni anonymat, ni securite en
environnement distribue, ni generalisation au-dela du loopback et de cette
echelle.

## Tests

```bash
# Suite complete obligatoire dans le venv
.venv/bin/python3 -m unittest discover -s tests
```

Les tests du daemon UDP (`test_daemon_local.py`) tournent en vrai sur
loopback et couvrent: livraison, drops sybil, churn, congestion,
redondance, reçus signés, et les nouvelles métriques transit_sybil.

## Structure

```
aegis_router/
  graph.py              Graphe P2P + génération aléatoire
  packet.py             Structure de paquet
  agent.py              Q-learning local + scorer hybride
  solvers.py            Chaîne de solvers (ShortestPath → EdgeLearning)
  event_sim.py          Simulateur discret événementiel
  daemon.py             Daemon UDP réel avec reçus signés
  sim.py                Ancien simulateur par épisodes
  postquantum_crypto.py Crypto ML-DSA-44 / ML-KEM-768
  auto_opt/             Optimisation hyperparamètres (Optuna + SB3/PPO)
tests/                  Suite unittest unitaire et integration reseau
scripts/
  real_network_benchmark.py  Benchmark UDP multi-seed multi-solver
  heavy_secure_search.py     Grid search hyperparamètres
```

## Dépendances

- `pqcrypto` — signatures ML-DSA-44, encapsulation ML-KEM-768
- `networkx` — génération de graphes
- `numpy` — calcul numérique
- `matplotlib` — optionnel, pour `plot_graph.py`

Pour `auto_opt/`: `optuna`, `gymnasium`, `stable-baselines3` (non listés
dans requirements.txt).

## Licence

MIT
