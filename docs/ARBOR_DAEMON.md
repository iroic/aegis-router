# Service Arbor autonome

Le service lance un cycle Codex/Arbor à la fois, attend cinq minutes, puis
reprend la session durable. Après une erreur ou une limite de compte, il attend
trente minutes avant de réessayer.

## Commandes

```bash
systemctl --user status aegis-arbor.service
journalctl --user -u aegis-arbor.service -f
systemctl --user restart aegis-arbor.service
systemctl --user stop aegis-arbor.service
```

Pause sans arrêter le service :

```bash
touch /home/ghost/projects/aegis-router/.arbor/daemon/PAUSE
rm /home/ghost/projects/aegis-router/.arbor/daemon/PAUSE
```

Arrêt durable de la boucle :

```bash
touch /home/ghost/projects/aegis-router/.arbor/daemon/STOP
systemctl --user stop aegis-arbor.service
```

Pour relancer après un arrêt durable :

```bash
rm -f /home/ghost/projects/aegis-router/.arbor/daemon/STOP
systemctl --user start aegis-arbor.service
```

Les journaux par cycle sont conservés dans
`.arbor/daemon/cycle-*.log`. `latest.log` pointe vers le plus récent.

Le service utilise la connexion ChatGPT existante de Codex. Il ne nécessite
pas de clé API séparée, mais il reste soumis aux limites d’utilisation du
compte.
