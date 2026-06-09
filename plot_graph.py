#!/usr/bin/env python3
import json
import matplotlib.pyplot as plt
import networkx as nx
from pathlib import Path

STATE_PATH = Path('aegis_state_grid.json')
OUT_PNG = Path('graph_edges.png')

with STATE_PATH.open() as f:
    data = json.load(f)

edges = data.get('edges', {})
G = nx.DiGraph()
for key, val in edges.items():
    src, dst = map(int, key.split('->'))
    # compute badness as in PeerScore.badness
    total = max(1, val.get('delivered', 0) + val.get('drops', 0))
    badness = (
        (val.get('drops', 0) / total)
        + 0.7 * (val.get('sybil_touches', 0) / total)
        + 0.35 * (val.get('link_losses', 0) / total)
        + 0.5 * (val.get('loops', 0) / total)
        + 0.25 * (val.get('ttl_expired', 0) / total)
    )
    G.add_edge(src, dst, weight=badness)

pos = nx.spring_layout(G, seed=42)
colors = [plt.cm.RdYlGn(1 - G[u][v]['weight']) for u, v in G.edges()]

plt.figure(figsize=(10, 8))
nx.draw_networkx_nodes(G, pos, node_size=80, node_color='#2b8cbe')
nx.draw_networkx_edges(G, pos, arrowstyle='->', arrowsize=10, edge_color=colors, width=2)
plt.title('Aegis Router – Edge Badness')
plt.axis('off')
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=150)
print(f'Graph saved to {OUT_PNG}')
