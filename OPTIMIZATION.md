# Aegis Router - optimisation IA

## Etat actuel verifie

Commande lancee:

```bash
python3 -m unittest discover -s tests -v
python3 -m aegis_router.demo --nodes 80 --episodes 3000 --packets 400 --sybil-ratio 0.15
```

Resultat mesure:

- shortest-path: livraison 100.0%, hops 2.90, latence 1.163, risque_perte 0.311, touch_sybil 46.5%
- agent Q-local: livraison 97.8%, hops 14.70, latence 4.224, risque_perte 0.506, touch_sybil 37.2%

Conclusion: l'agent local commence a eviter les Sybil, mais il paie trop cher en detours, latence et risque cumule.

## Ce qu'il faut optimiser en priorite

1. Signal de destination local
   - Probleme: l'agent ne connait que ses voisins, donc il evite les mauvais liens mais peut tourner longtemps.
   - Solution: ajouter un hint de progression anonyme: distance de rendezvous hash, niveau onion, TTL restant, ou embedding de destination non-identifiant.

2. Fonction de recompense
   - Objectif: penaliser fortement les routes longues et la perte cumulee.
   - Formule cible:
     reward = delivery_bonus - hop_penalty - latency*w1 - cumulative_loss*w2 - sybil_suspicion*w3 + stability*w4
   - A optimiser par grille: hop_penalty, loss_weight, delivery_bonus.

3. Memoire de route et anti-boucle
   - Garder un petit bloom filter/nonce des derniers hops.
   - Penaliser immediatement un voisin deja visite.
   - Ajouter TTL dur pour forcer fallback.

4. Generalisation du modele
   - Le Q-table actuel apprend par noeud, donc il generalise mal.
   - Remplacer par DQN avec features de voisins, puis GNN-DQN pour message passing 1-hop/2-hop.

5. Simulation adversariale plus realiste
   - Sybil qui ment sur bande passante.
   - Sybil qui drop seulement certains paquets.
   - Churn: noeuds qui entrent/sortent.
   - Congestion variable dans le temps.

6. Objectifs mesurables avant v0.2
   - livraison >= 98%
   - touch_sybil reduit d'au moins 30% vs shortest-path
   - risque_perte <= shortest-path + 10%
   - hops <= 2.5x shortest-path

## Prochaine implementation conseillee

v0.2: remplacer le choix Q-table pur par un scorer hybride trainable:

score(voisin) = model(features_voisin) + progress_hint - loop_penalty - ttl_penalty

Puis v0.3: DQN PyTorch.
Puis v0.4: GNN avec PyTorch Geometric.
