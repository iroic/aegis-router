# Aegis Router

Prototype d'IA de routage decentralisee pour reseaux P2P anonymes.

Objectif: router des paquets chiffres entre noeuds sans utiliser de LLM lourd. Le projet demarre avec un simulateur MARL leger et extensible:

- Graphe P2P dynamique
- Observations locales uniquement: latence, bande passante, perte, stabilite
- Agent Q-learning local avec exploration epsilon-greedy
- Penalisation des noeuds lents/perdants, utile contre les comportements Sybil suspects
- Demo comparative: shortest-path vs agent appris

Ce premier jalon est volontairement sans dependances lourdes pour tourner immediatement sur le VPS. La branche suivante pourra ajouter PyTorch Geometric + RLlib pour le GNN-DQN complet.

## Lancer la demo rapide

```bash
cd /home/ghost/aegis-router
python3 -m aegis_router.demo --nodes 80 --episodes 300 --packets 250 --sybil-ratio 0.15
```

## Lancer la demo event-driven v0.3

```bash
cd /home/ghost/aegis-router
python3 -m aegis_router.event_demo --nodes 80 --duration 8 --traffic-rate 12 --sybil-ratio 0.2 --drain 5
```

## Lancer avec apprentissage persistant

```bash
cd /home/ghost/aegis-router
python3 -m aegis_router.event_demo --learn --runs 5 --state aegis_state.json --nodes 80 --duration 8 --traffic-rate 12 --sybil-ratio 0.2 --drain 5
```

Le fichier `aegis_state.json` sauvegarde la reputation des voisins: livraisons,
drops, touches Sybil et budget de risque. En relancant avec le meme `--state`,
le routeur reprend ce qu'il a appris et evite progressivement les mauvais hops.
`--drain` laisse le reseau vider les paquets deja en vol apres la periode de
generation, ce qui evite de compter ces paquets comme des pertes dures.

Cette simulation ajoute trafic Poisson, files d'attente, pertes stochastiques,
TTL et paquets comme episodes asynchrones. Elle compare aussi des solvers
risk-aware/adaptive-risk avec budget de risque et reputation dynamique par
voisin. Elle est inspiree des simulateurs MA-DRL/risk-aware routing trouves dans
SatCom-TELMA et skypitcher.

## Lancer les tests

```bash
cd /home/ghost/aegis-router
python3 -m unittest discover -s tests -v
```

## Structure

- `aegis_router/graph.py`: graphe P2P et generation de reseaux
- `aegis_router/agent.py`: agent Q-learning local
- `aegis_router/sim.py`: simulation d'episodes et comparaison de politiques
- `aegis_router/demo.py`: CLI de demonstration
- `tests/`: tests unitaires

## Prochaines etapes

1. Ajouter backend PyTorch pour DQN.
2. Ajouter encodeur GNN PyTorch Geometric.
3. Export TorchScript/ONNX pour runtime leger.
4. Ajouter apprentissage en ligne par noeud.
5. Publier sur GitHub si souhaite.
