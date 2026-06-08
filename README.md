# Aegis Router

Prototype d'IA de routage decentralisee pour reseaux P2P anonymes.

Objectif: router des paquets chiffres entre noeuds sans utiliser de LLM lourd. Le projet demarre avec un simulateur MARL leger et extensible:

- Graphe P2P dynamique
- Observations locales uniquement: latence, bande passante, perte, stabilite
- Agent Q-learning local avec exploration epsilon-greedy
- Penalisation des noeuds lents/perdants, utile contre les comportements Sybil suspects
- Demo comparative: shortest-path vs agent appris

Ce premier jalon est volontairement sans dependances lourdes pour tourner immediatement sur le VPS. La branche suivante pourra ajouter PyTorch Geometric + RLlib pour le GNN-DQN complet.

## Lancer la demo

```bash
cd /home/ghost/aegis-router
python3 -m aegis_router.demo --nodes 80 --episodes 300 --packets 250 --sybil-ratio 0.15
```

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
