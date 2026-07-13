"""Explicit-endorsement RepuLink baseline for Aegis Router.

This module follows the two-layer model from arXiv:2606.08851: directed,
first-hand interaction feedback is combined with caller-supplied endorsement
edges. BEPP and BERP propagate negative and positive evidence back through
the endorsement layer. It intentionally centralizes its ledger for evaluation;
distributed gossip is a later phase.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
from typing import Iterable, Mapping

from .agent import _progress_delta
from .graph import NodeId, P2PGraph
from .packet import Packet
from .postquantum_crypto import verify_endorsement

Endorsement = tuple[NodeId, NodeId, float]
EdgeKey = tuple[NodeId, NodeId]


@dataclass(frozen=True)
class SignedEndorsement:
    """An explicit endorsement whose issuer is authenticated with ML-DSA."""

    endorser: NodeId
    endorsee: NodeId
    confidence: float
    issued_at: float
    expires_at: float
    signature: str


@dataclass
class RepuLinkLedger:
    """Sparse interaction and endorsement ledgers with backward accountability.

    Endorsements represent out-of-band domain knowledge. They are never
    inferred from graph topology or from simulator-only Sybil labels.
    """

    nodes: Iterable[NodeId]
    endorsements: Iterable[Endorsement] = ()
    trusted_endorsers: Iterable[NodeId] = ()
    interaction_weight: float = 0.5
    backward_discount: float = 0.5
    signal_sensitivity: float = 0.25
    restart_weight: float = 0.05
    max_backward_hops: int = 8
    tolerance: float = 1e-10
    max_iterations: int = 200
    delivered: defaultdict[EdgeKey, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    drops: defaultdict[EdgeKey, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    iterations: int = field(default=0, init=False)
    residual: float = field(default=math.inf, init=False)
    converged: bool = field(default=False, init=False)
    _endorsements: dict[EdgeKey, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _reputation: dict[NodeId, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _penalty: dict[NodeId, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _reward: dict[NodeId, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _trusted_endorsers: frozenset[NodeId] = field(
        default_factory=frozenset, init=False, repr=False
    )
    _signed_endorsements_accepted: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.nodes = tuple(dict.fromkeys(self.nodes))
        if not self.nodes:
            raise ValueError("RepuLink requires at least one node")
        if not 0.0 <= self.interaction_weight <= 1.0:
            raise ValueError("interaction_weight must be in [0, 1]")
        if not 0.0 <= self.backward_discount < 1.0:
            raise ValueError("backward_discount must be in [0, 1)")
        if self.signal_sensitivity <= 0.0:
            raise ValueError("signal_sensitivity must be positive")
        if not 0.0 < self.restart_weight < 1.0:
            raise ValueError("restart_weight must be in (0, 1)")
        if self.max_backward_hops < 1:
            raise ValueError("max_backward_hops must be at least 1")
        if self.tolerance <= 0.0 or self.max_iterations < 1:
            raise ValueError("invalid RepuLink convergence settings")

        supplied = tuple(self.endorsements)
        self.endorsements = supplied
        trusted = frozenset(self.trusted_endorsers)
        unknown_trusted = trusted - set(self.nodes)
        if unknown_trusted:
            raise ValueError(f"unknown trusted endorsers: {sorted(unknown_trusted)}")
        self.trusted_endorsers = tuple(sorted(trusted))
        self._trusted_endorsers = trusted
        for endorser, endorsee, confidence in supplied:
            self.add_endorsement(endorser, endorsee, confidence)
        self._reputation = self.cold_start()
        self._penalty = {node: 0.0 for node in self.nodes}
        self._reward = {node: 0.0 for node in self.nodes}

    def _require_node(self, node: NodeId) -> None:
        if node not in self.nodes:
            raise ValueError(f"unknown node: {node}")

    def add_endorsement(
        self,
        endorser: NodeId,
        endorsee: NodeId,
        confidence: float,
    ) -> None:
        """Add one explicit directed endorsement, with no duplicate edges."""
        self._require_node(endorser)
        self._require_node(endorsee)
        if endorser == endorsee:
            raise ValueError("self-endorsements are not allowed")
        if not 0.0 < confidence <= 1.0 or not math.isfinite(confidence):
            raise ValueError("endorsement confidence must be finite and in (0, 1]")
        edge = (endorser, endorsee)
        if edge in self._endorsements:
            raise ValueError(f"duplicate endorsement: {endorser}->{endorsee}")
        self._endorsements[edge] = confidence

    def add_signed_endorsement(
        self,
        endorsement: SignedEndorsement,
        *,
        public_keys: Mapping[NodeId, bytes],
        now: float,
    ) -> None:
        """Verify and accept one endorsement from a configured trust anchor.

        A valid ML-DSA signature establishes issuer authenticity, not issuer
        trustworthiness. The separate ``trusted_endorsers`` allowlist is
        therefore mandatory for signed attestations; this prevents a Sybil
        identity from self-authorizing its own reputation.
        """
        self._require_node(endorsement.endorser)
        self._require_node(endorsement.endorsee)
        if endorsement.endorser not in self._trusted_endorsers:
            raise ValueError("endorser is not a configured trust anchor")
        if not math.isfinite(now):
            raise ValueError("endorsement verification time must be finite")
        if now < endorsement.issued_at or now > endorsement.expires_at:
            raise ValueError("endorsement is not currently valid")
        public_key = public_keys.get(endorsement.endorser)
        if public_key is None:
            raise ValueError("missing endorser public key")
        if not verify_endorsement(
            endorsement.endorser,
            endorsement.endorsee,
            endorsement.confidence,
            endorsement.issued_at,
            endorsement.expires_at,
            endorsement.signature,
            public_key,
        ):
            raise ValueError("invalid endorsement signature")
        self.add_endorsement(
            endorsement.endorser,
            endorsement.endorsee,
            endorsement.confidence,
        )
        self._signed_endorsements_accepted += 1

    @property
    def reputation(self) -> dict[NodeId, float]:
        return dict(self._reputation)

    @property
    def endorsement_edges(self) -> dict[EdgeKey, float]:
        return dict(self._endorsements)

    def reputation_score(self, node: NodeId) -> float:
        return self._reputation.get(node, 0.0)

    def _uniform(self) -> dict[NodeId, float]:
        weight = 1.0 / len(self.nodes)
        return {node: weight for node in self.nodes}

    def _project(
        self,
        values: dict[NodeId, float],
        *,
        fallback: dict[NodeId, float] | None = None,
    ) -> dict[NodeId, float]:
        positive = {node: max(0.0, values.get(node, 0.0)) for node in self.nodes}
        total = sum(positive.values())
        if total <= 0.0 or not math.isfinite(total):
            return dict(fallback if fallback is not None else self._uniform())
        return {node: value / total for node, value in positive.items()}

    def endorsement_rows(self) -> dict[NodeId, dict[NodeId, float]]:
        """Return sparse row-normalized endorsement weights."""
        raw: defaultdict[NodeId, dict[NodeId, float]] = defaultdict(dict)
        for (endorser, endorsee), confidence in self._endorsements.items():
            raw[endorser][endorsee] = confidence
        rows: dict[NodeId, dict[NodeId, float]] = {}
        for endorser in self.nodes:
            total = sum(raw[endorser].values())
            rows[endorser] = (
                {
                    endorsee: confidence / total
                    for endorsee, confidence in raw[endorser].items()
                }
                if total > 0.0
                else {}
            )
        return rows

    def interaction_rows(self) -> dict[NodeId, dict[NodeId, float]]:
        """Return sparse local trust from positive first-hand interactions."""
        positive: defaultdict[NodeId, dict[NodeId, float]] = defaultdict(dict)
        for edge in self.delivered.keys() | self.drops.keys():
            source, target = edge
            score = max(
                self.delivered.get(edge, 0.0) - self.drops.get(edge, 0.0),
                0.0,
            )
            if score > 0.0:
                positive[source][target] = score
        rows: dict[NodeId, dict[NodeId, float]] = {}
        for source in self.nodes:
            total = sum(positive[source].values())
            rows[source] = (
                {
                    target: score / total
                    for target, score in positive[source].items()
                }
                if total > 0.0
                else {}
            )
        return rows

    def cold_start(self) -> dict[NodeId, float]:
        """Give endorsed newcomers explainable initial reputation."""
        uniform = self._uniform()
        initial = {node: 0.0 for node in self.nodes}
        for endorser, row in self.endorsement_rows().items():
            for endorsee, weight in row.items():
                initial[endorsee] += uniform[endorser] * weight
        return self._project(initial, fallback=uniform)

    def observe(
        self,
        from_node: NodeId,
        neighbor: NodeId,
        *,
        delivered: bool,
        dropped: bool,
        reason: str | None = None,
    ) -> None:
        """Record a directed first-hand interaction outcome."""
        self._require_node(from_node)
        self._require_node(neighbor)
        if reason == "node_down":
            return
        edge = (from_node, neighbor)
        if delivered:
            self.delivered[edge] += 1.0
        if dropped:
            self.drops[edge] += 1.0

    def _signal(
        self,
        evidence: defaultdict[EdgeKey, float],
    ) -> dict[NodeId, float]:
        totals = {node: 0.0 for node in self.nodes}
        for (_observer, target), value in evidence.items():
            totals[target] += value
        return {
            node: 1.0 - math.exp(-self.signal_sensitivity * totals[node])
            for node in self.nodes
        }

    def _backward(
        self,
        signal: dict[NodeId, float],
        endorsement_rows: dict[NodeId, dict[NodeId, float]],
    ) -> dict[NodeId, float]:
        propagated = {node: 0.0 for node in self.nodes}
        frontier = dict(signal)
        for _ in range(self.max_backward_hops):
            next_frontier = {
                endorser: sum(
                    weight * frontier[endorsee]
                    for endorsee, weight in row.items()
                )
                for endorser, row in endorsement_rows.items()
            }
            frontier = {
                node: self.backward_discount * next_frontier[node]
                for node in self.nodes
            }
            magnitude = sum(abs(value) for value in frontier.values())
            for node, value in frontier.items():
                propagated[node] += value
            if magnitude <= self.tolerance:
                break
        return propagated

    def accountability(self) -> dict[NodeId, dict[str, float]]:
        """Return latest BEPP penalty and BERP reward by endorser."""
        return {
            node: {"penalty": self._penalty[node], "reward": self._reward[node]}
            for node in self.nodes
        }

    def recompute(self) -> dict[NodeId, float]:
        """Apply BEPP/BERP once, then converge the two-layer reputation update."""
        endorsements = self.endorsement_rows()
        interactions = self.interaction_rows()
        drop_signal = self._signal(self.drops)
        delivery_signal = self._signal(self.delivered)
        self._penalty = self._backward(drop_signal, endorsements)
        self._reward = self._backward(delivery_signal, endorsements)
        cold_start = self.cold_start()
        seed = self._project(
            {
                # First-hand evidence changes the target directly. BEPP/BERP
                # then add accountability for entities that endorsed it.
                node: cold_start[node] - drop_signal[node] + delivery_signal[node]
                - self._penalty[node] + self._reward[node]
                for node in self.nodes
            },
            fallback=cold_start,
        )
        current = seed
        self.converged = False
        for iteration in range(1, self.max_iterations + 1):
            updated = {node: 0.0 for node in self.nodes}
            for source in self.nodes:
                # A source with no evidence in one layer retains its mass in
                # that layer. Both row operators therefore remain stochastic
                # on sparse graphs instead of silently losing reputation mass.
                interaction_row = interactions[source] or {source: 1.0}
                endorsement_row = endorsements[source] or {source: 1.0}
                for target, weight in interaction_row.items():
                    updated[target] += self.interaction_weight * current[source] * weight
                for target, weight in endorsement_row.items():
                    updated[target] += (
                        (1.0 - self.interaction_weight) * current[source] * weight
                    )
            updated = {
                node: (1.0 - self.restart_weight) * updated[node]
                + self.restart_weight * seed[node]
                for node in self.nodes
            }
            updated = self._project(updated, fallback=seed)
            self.residual = sum(
                abs(updated[node] - current[node]) for node in self.nodes
            )
            current = updated
            self.iterations = iteration
            if self.residual <= self.tolerance:
                self.converged = True
                break
        self._reputation = current
        return dict(current)

    def diagnostics(self) -> dict[str, float | int | bool]:
        return {
            "converged": self.converged,
            "iterations": self.iterations,
            "residual": self.residual,
            "endorsement_edges": len(self._endorsements),
            "trusted_endorsers": len(self._trusted_endorsers),
            "signed_endorsements_accepted": self._signed_endorsements_accepted,
            "penalty_mass": sum(self._penalty.values()),
            "reward_mass": sum(self._reward.values()),
        }


@dataclass
class RepuLinkSolver:
    """Greedy router using the shared RepuLink reputation vector."""

    ledger: RepuLinkLedger

    def next_hop(self, graph: P2PGraph, packet: Packet) -> NodeId | None:
        assert packet.node is not None
        neighbors = graph.reachable_neighbors(packet.node)
        if not neighbors:
            return None
        if packet.dst in neighbors:
            return packet.dst
        if packet.visited:
            unvisited = [node for node in neighbors if node not in packet.visited]
            if unvisited:
                neighbors = unvisited
        return max(
            neighbors,
            key=lambda node: (
                self.ledger.reputation_score(node),
                _progress_delta(graph, packet.node, node, packet.dst),
                -node,
            ),
        )

    def observe_result(
        self,
        *,
        neighbor: NodeId,
        delivered: bool,
        dropped: bool,
        touched_sybil: bool = False,
        reason: str | None = None,
        from_node: NodeId | None = None,
        receipt_confirmed: bool = False,
    ) -> None:
        if from_node is None:
            return
        self.ledger.observe(
            from_node,
            neighbor,
            delivered=delivered,
            dropped=dropped,
            reason=reason,
        )
