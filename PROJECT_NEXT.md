## Project Aegis Router – Roadmap & Next Steps

### 1️⃣ Architecture & Code‑base
- 1.1 Modulariser l’algorithme d’optimisation : séparer trainer.py en modules env, policy, runner.
- 1.2 Ajouter un Dockerfile pour le container nousresearch/hermes‑3.
- 1.3 Enrichir l’API socket pour récupérer en temps réel les métriques d’entraînement.
- 1.4 Réécrire evaluate_policy pour qu’elle accepte un graphe générique + hyper‑paramètres de test.
- 1.5 Refactoriser la génération de graphes : intégrer networkx pour des topologies plus réalistes.

### 2️⃣ Data et Métriques
- 2.1 Logging centralisé : envoyer les métriques (delivery, drop, risk, sybil, speed) dans Prometheus + Grafana.
- 2.2 Constructeur de dataset synthétique pour entraîner le GNN‑Critic.
- 2.3 Annotation de graphes réels (ex. pré‑enregistrés d’iSCSI/InfiniBand).
- 2.4 Automatiser la validité : script de Sanity‑Check qui exécute 5 random episodes et signale anomalies.

### 3️⃣ Sécurité P2P & Post‑Quantum
- 3.1 Implémenter signatures Dilithium‑2 et encapsulation Kyber‑768 dans postquantum_crypto.py.
- 3.2 Intégrer un Dual‑Facing : le peer doit valider le certificat avant de s’appeler.
- 3.3 Déployer un test de résistance sybil (10 k nœuds fake) et mesurer sybil‑touch.
- 3.4 Audit de sécurité (Open Source) de la couche TLS 1.3 + PQC.

### 4️⃣ Learning‑More & RL Advanced
- 4.1 Tester R‑PPO (LSTM‑policy) pour la dépendance temporelle.
- 4.2 Intégrer XGBoost pour un critic hybride GNN‑XGBoost.
- 4.3 Distribuer l’apprentissage (Ray‑RLlib) pour tester 512 trials en parquet.
- 4.4 Benchmark Sur‑avec MAB‑RL (Multi‑Armed Bandit) pour tuner hyper‑para.

### 5️⃣ CI / CD & Déploiement
- 5.1 GitHub Actions : pipeline train.yml qui lance le job dans MCP, récupère logs, et pousse le modèle dans GCS/S3.
- 5.2 Helm chart pour déployer le service router‑svc dans Kubernetes.
- 5.3 ArgoCD auto‑sync de l’infrastructure et des modèles.
- 5.4 Auto‑scale basé sur métriques de Prometheus.
- 5.5 Rollback : script undo_bad_training.sh qui restaure le dernier modèle stable.

### 6️⃣ Documentation & Formation
- 6.1 Doc API (OpenAPI) pour la fonction evaluate_policy.
- 6.2 Tutoriel vidéo (5 min) présentant le flux training → eval → prod.
- 6.3 Guide d’utilisation (pour CTO) : tableau de bord metrics + KPI.
- 6.4 FAQ : debug courants, métriques aberrantes, limites de PQC.

### 7️⃣ Tests & Monitoring
- 7.1 Unit tests > 90 % coverage.
- 7.2 Integration tests (docker‑compose) sur 100 nœuds.
- 7.3 Chaos tests (simuler node‑fails) avec Litmus.
- 7.4 Alerting : alertes Slack/Telegram quand drop > 23 % ou sybiling > 5 %.

### 8️⃣ Road‑Map de version
- v0.1 : Prototype RL‑based training, basic graph simulation.
- v0.2 : GNN‑Critic, callback logging, Docker packaging.
- v0.3 : PQC & Sybil‑Defence, GPU‑optimized transport.
- v1.0 : Production‑ready API + Auto‑scaling + CI/CD.
- v1.1 : R‑PPO + XGBoost hybrid.
- v2.0 : Multi‑domain RL (Web‑Socket, REST, MQTT).

### 9️⃣ Check‑list de validation finale
- Code : lint (flake8), type‑check (mypy), test coverage > 85 %.
- Security : audit PQC, sybil‑resistance.
- Performance : delivery ≥ 58 %, drop ≤ 20 %, risk ≤ 0.02, sybil ≤ 5 %.
- CI : GitHub Actions build 100 % pass, docker image tag <sha>.
- Deployment : Helm chart v1.0, auto‑update via ArgoCD.
- Monitoring : Grafana dashboard live, alerting configurée.
- Documentation : README, API, tutorials, release notes.

---

Copiez ce fichier dans le dépôt, ajoutez‑le au versionnage (`git add PROJECT_NEXT.md && git commit -m "Add roadmap for Aegis Router"`).