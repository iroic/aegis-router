# AGENTS.md — Protocole de validation pour agents IA sur Aegis Router

Ce fichier est contraignant. Tout agent IA (ou humain) qui modifie ce projet
doit franchir ces portes AVANT de déclarer une étape « faite » ou de committer.
Il encode des leçons payées cher pendant le développement — ne pas les
re-apprendre.

Principe directeur : **ce projet ne se ment pas à lui-même.** Un résultat qui
a l'air bon mais n'a pas survécu à ces portes n'est pas un résultat.

---

## 0. Environnement (bloquant)

- Lancer les tests avec le venv, JAMAIS le python système :
  `.venv/bin/python3 -m unittest discover -s tests`
  Le python système n'a pas `pqcrypto` → toute la crypto/daemon échoue à
  l'import. Un « test qui passe » sous le mauvais python ne compte pas.
- État de référence actuel : **76 tests, tous verts** (hors erreur préexistante
  d'import si mauvais interpréteur). Une régression = étape invalide.

## 1. Discipline de test (bloquant)

- La suite complète doit passer après chaque changement. Pas « la plupart ».
- Toute nouvelle fonctionnalité OU tout bug corrigé ajoute **un test de
  non-régression qui échoue avant le fix et passe après**. Un fix sans test
  reviendra.
- Les tests réseau réel (`tests/test_daemon_local.py`) valident ce que la
  simulation ne peut pas : sérialisation, sockets, crypto, timeouts. Tout
  changement touchant transport/crypto/reçus DOIT être validé côté daemon,
  pas seulement en simulation. Des bugs réels y sont invisibles en simu.

## 2. Honnêteté de la mesure (le plus important — bloquant)

- **Toute métrique qui s'améliore est SUSPECTE jusqu'à preuve du contraire**
  (loi de Goodhart). Avant de célébrer, demander : qu'est-ce que ce chiffre a
  troqué pour monter ? Exemple vécu : la redondance montait la livraison sans
  bouger le sybil-touch — elle déplaçait le problème.
- **Ne jamais rapporter une métrique seule.** Toujours livraison ET sybil-touch
  (brut ET transit) ET hops côte à côte. Un gain de livraison qui augmente
  l'exposition Sybil n'est pas un gain pour ce projet.
- **Distinguer le contrôlable de l'incompressible.** La métrique brute contient
  un plancher que le routage ne peut pas éviter (paquets adressés À un Sybil).
  Juger la sécurité sur `transit_sybil_touch_ratio`, pas sur le brut. Toujours
  afficher les deux.
- **Un seul seed chanceux n'est pas un résultat.** Un effet doit tenir sur
  plusieurs topologies indépendantes.

## 3. Séparation tune / validation (bloquant pour tout réglage)

- Régler les hyperparamètres sur un lot de seeds (« tune »), valider sur un lot
  **disjoint, jamais touché pendant le réglage** (« held-out »).
  Convention actuelle : tune ≈ seeds 10000/20000 ; validation = 30000-30002.
- **Rejeter le changement s'il échoue sur le held-out, même s'il brillait sur le
  tune.** C'est arrivé (le garde-fou de redondance : 22 % sur le tune,
  incohérent sur le held-out). Le held-out a le dernier mot.
- Comparaisons **appariées** : même seed pour les deux solveurs comparés (même
  topologie, mêmes Sybils, même trafic). Sinon on compare du bruit.
- Rapporter l'écart inter-seed (spread), pas seulement la moyenne.

## 4. Discipline de revert (bloquant)

- Si un changement ne tient pas en validation, **le retirer entièrement** — code
  ET paramètres. Ne pas laisser de complexité morte « au cas où ».
  Précédents : tuning des poids du scorer, scale-scoring → testés, invalidés,
  supprimés. C'est la norme, pas l'exception.

## 5. Sécurité par défaut & compatibilité (bloquant)

- Tout nouveau mécanisme est **opt-in, désactivé par défaut**, de sorte que le
  comportement antérieur reste bit-identique (`receipts=False`,
  `redundancy=1`, `link_retries=0`, etc.). Un test doit prouver que le défaut
  est inerte.
- Ne pas régresser un comportement validé pour un gain marginal non prouvé.

## 6. Honnêteté du modèle de menace (bloquant)

- **Ne jamais affaiblir l'adversaire pour faire briller une fonctionnalité.**
  Si un mécanisme n'aide que contre un dropper trivial neutralisé par l'ARQ,
  ce n'est pas un résultat — c'est un artefact. Documenter le modèle de menace
  exact (`sybil_stealth`, `sybil_extra_drop`, `churn_rate`, `congestion_rate`)
  à côté de chaque chiffre.
- Rappeler dans tout rapport ce que le système NE fait PAS encore : pas d'audit
  de sécurité, PQC non câblée dans la décision de routage (seulement signature
  d'origine + reçus), `path` en clair donc **anonymat non livré**, échelle
  limitée (loopback, ≤80 nœuds réels).

## 7. Git & rapport (bloquant avant merge)

- Brancher, jamais committer directement sur `main`.
- Message de commit qui documente ce qui a été **mesuré**, y compris les
  échecs et les reverts, avec les chiffres tune ET held-out. Pas de « améliore
  le score » sans preuve chiffrée reproductible.
- Ne jamais écrire « résolu », « prêt pour la production », « révolutionnaire ».
  Décrire ce qui est mesuré, dans quel régime, sur combien de seeds.

## 8. Portée (bloquant)

- Chercher les utilitaires existants avant d'écrire du neuf (`PeerScore`,
  `HybridRoutingScorer`, `graph.offline_nodes`, motif de dédup par packet_id…).
  Réutiliser plutôt que dupliquer.
- Ne pas créer de fichier hors des dossiers prévus (`aegis_router/`, `tests/`,
  `scripts/`). Pas de fichiers de travail à la racine.

---

## Check-list rapide (une étape est « faite » seulement si tout est coché)

- [ ] Suite complète verte avec `.venv/bin/python3` (76+ tests)
- [ ] Test de non-régression ajouté pour ce changement
- [ ] Métriques rapportées côte à côte (livraison + sybil brut + sybil transit + hops)
- [ ] Effet validé sur seeds held-out disjoints, pas seulement sur le tune
- [ ] Comparaison appariée (même seed), spread inter-seed reporté
- [ ] Nouveau mécanisme opt-in, défaut inerte prouvé par un test
- [ ] Modèle de menace explicite à côté des chiffres
- [ ] Message de commit chiffré et honnête, sur une branche, PR vers main
- [ ] Rien de mort laissé derrière (revert complet si invalidé)

Si une case ne peut pas être cochée : l'étape n'est PAS validée. S'arrêter et
le dire, plutôt que de maquiller.
