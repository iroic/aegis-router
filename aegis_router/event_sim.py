from __future__ import annotations

from dataclasses import dataclass
import heapq
import itertools
import random
from collections import Counter
from statistics import mean
from typing import Callable

from .graph import LinkMetrics, NodeId, P2PGraph
from .packet import Packet
from .solvers import RoutingSolver


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class Event:
    time: float
    kind: str
    packet_id: int | None = None


@dataclass
class EventStats:
    generated: int
    delivered: int
    dropped: int
    in_flight: int
    drop_reasons: dict[str, int]
    avg_hops: float
    avg_latency: float
    avg_queue_delay: float
    avg_loss_risk: float
    sybil_touch_ratio: float

    @property
    def delivery_ratio(self) -> float:
        return self.delivered / max(1, self.generated)

    @property
    def drop_ratio(self) -> float:
        return self.dropped / max(1, self.generated)


class EventDrivenSimulator:
    """Small event-driven packet simulator inspired by MA-DRL satellite routers.

    Every packet is its own asynchronous episode. Nodes make a routing decision
    only when the packet arrives. Link queues add delay, lossy links may drop,
    and TTL prevents loops from becoming infinite.
    """

    def __init__(
        self,
        graph: P2PGraph,
        solver: RoutingSolver,
        *,
        seed: int | None = None,
        ttl: int = 18,
        queue_service_time: float = 0.025,
        sybil_extra_drop: float = 0.12,
        congestion_rate: float = 0.0,
        congestion_jitter: float = 0.15,
        churn_rate: float = 0.0,
        churn_recovery: float = 0.4,
        perturb_interval: float = 0.5,
    ) -> None:
        self.graph = graph
        self.solver = solver
        self.rng = random.Random(seed)
        self.ttl = ttl
        self.queue_service_time = queue_service_time
        self.sybil_extra_drop = sybil_extra_drop
        # Dynamic conditions (all default off → legacy static behaviour).
        self.congestion_rate = congestion_rate    # fraction of edges perturbed per tick
        self.congestion_jitter = congestion_jitter  # max absolute drift per perturbed metric
        self.churn_rate = churn_rate               # P(up node goes down) per tick
        self.churn_recovery = churn_recovery       # P(down node recovers) per tick
        self.perturb_interval = perturb_interval   # seconds between perturbation ticks
        self._events: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self._packets: dict[int, Packet] = {}
        self._link_available: dict[tuple[NodeId, NodeId], float] = {}
        self._delivered: list[Packet] = []
        self._dropped: list[Packet] = []
        self._drop_reasons: Counter[str] = Counter()
        self._in_flight: list[Packet] = []
        self._down_nodes: set[NodeId] = set()
        self._edges: list[tuple[NodeId, NodeId]] = [
            (a, b) for a in self.graph.adj for b in self.graph.adj[a] if a < b
        ]
        # NOTE: post-quantum identities are NOT wired into routing yet. The
        # postquantum_crypto module (per-packet ML-DSA-44 signatures, ML-KEM-768
        # key exchange) currently stands alone as a verified PoC. Wiring per-node
        # identities + verify-at-each-hop as a real Sybil gate is tracked work,
        # not done here. Previously this constructor generated one shared keypair
        # that was never used; that dead code is removed.


    def run(self, *, duration: float, traffic_rate: float, drain_time: float = 0.0) -> EventStats:
        end_time = duration + max(0.0, drain_time)
        self._schedule(Event(0.0, "generate"))
        if self._dynamics_enabled() and self.perturb_interval > 0:
            self._schedule(Event(self.perturb_interval, "perturb"))
        while self._events:
            time, _, event = heapq.heappop(self._events)
            if time > end_time:
                break
            if event.kind == "generate":
                if time <= duration:
                    self._handle_generate(time, duration, traffic_rate)
            elif event.kind == "arrive" and event.packet_id is not None:
                self._handle_arrive(time, event.packet_id)
            elif event.kind == "perturb":
                self._handle_perturb(time, end_time)
        # In-flight packets are tracked separately, not counted as hard drops.
        completed = {p.packet_id for p in self._delivered + self._dropped}
        for pkt in self._packets.values():
            if pkt.packet_id not in completed:
                self._in_flight.append(pkt)
        return self._stats()

    def _schedule(self, event: Event) -> None:
        heapq.heappush(self._events, (event.time, next(self._counter), event))

    def _drop(self, pkt: Packet, reason: str, *, notify: bool = True) -> None:
        if notify:
            self._notify_solver(pkt, delivered=False, dropped=True, reason=reason)
        self._drop_reasons[reason] += 1
        self._dropped.append(pkt)

    def _dynamics_enabled(self) -> bool:
        return self.congestion_rate > 0.0 or self.churn_rate > 0.0

    def _handle_perturb(self, time: float, end_time: float) -> None:
        """Periodic network dynamics: congestion drift and node churn."""
        if self.congestion_rate > 0.0 and self._edges:
            k = max(1, int(self.congestion_rate * len(self._edges)))
            for a, b in self.rng.sample(self._edges, min(k, len(self._edges))):
                self._drift_edge(a, b)
        if self.churn_rate > 0.0:
            for node in self.graph.adj:
                if node in self._down_nodes:
                    if self.rng.random() < self.churn_recovery:
                        self._down_nodes.discard(node)
                elif self.rng.random() < self.churn_rate:
                    self._down_nodes.add(node)
        nxt = time + self.perturb_interval
        if nxt <= end_time:
            self._schedule(Event(nxt, "perturb"))

    def _drift_edge(self, a: NodeId, b: NodeId) -> None:
        m = self.graph.metrics(a, b)
        j = self.congestion_jitter
        drifted = LinkMetrics(
            latency=_clamp(m.latency + self.rng.uniform(-j, j), 0.02, 1.5),
            bandwidth=_clamp(m.bandwidth + self.rng.uniform(-j, j), 0.05, 1.0),
            loss=_clamp(m.loss + self.rng.uniform(-j, j), 0.0, 0.7),
            stability=_clamp(m.stability + self.rng.uniform(-j, j), 0.05, 1.0),
        )
        self.graph.add_edge(a, b, drifted)

    def _handle_generate(self, time: float, duration: float, traffic_rate: float) -> None:
        nodes = self.graph.nodes()
        src, dst = self.rng.sample(nodes, 2)
        pkt = Packet(packet_id=len(self._packets), src=src, dst=dst, created_at=time, ttl=self.ttl)
        pkt.touched_sybil = src in self.graph.sybil_nodes
        self._packets[pkt.packet_id] = pkt
        self._schedule(Event(time, "arrive", pkt.packet_id))
        if traffic_rate > 0:
            delay = self.rng.expovariate(traffic_rate)
            if time + delay <= duration:
                self._schedule(Event(time + delay, "generate"))

    def _handle_arrive(self, time: float, packet_id: int) -> None:
        pkt = self._packets[packet_id]
        if pkt.node == pkt.dst:
            self._notify_solver(pkt, delivered=True, dropped=False)
            self._delivered.append(pkt)
            return
        # The packet arrived at a node that has since churned offline. The hop
        # that delivered us here is not to blame, so do not penalise it.
        if pkt.node in self._down_nodes:
            self._drop(pkt, "node_down", notify=False)
            return
        if pkt.ttl <= 0:
            self._drop(pkt, "ttl_expired")
            return
        if pkt.node in pkt.visited:
            self._drop(pkt, "loop")
            return
        assert pkt.node is not None
        pkt.visited.add(pkt.node)
        nxt = self.solver.next_hop(self.graph, pkt)
        if nxt is None or nxt not in self.graph.adj.get(pkt.node, {}):
            self._drop(pkt, "no_route")
            return
        # Chosen next hop is offline: the route is dead. Attribute it to the hop
        # so reputation/edge learners can adapt to a flaky peer.
        if nxt in self._down_nodes:
            pkt.last_from = pkt.node
            pkt.last_neighbor = nxt
            self._drop(pkt, "node_down")
            return
        metrics = self.graph.metrics(pkt.node, nxt)
        extra_drop = self.sybil_extra_drop if nxt in self.graph.sybil_nodes else 0.0
        effective_loss = min(0.95, metrics.loss + extra_drop)
        if self.rng.random() < effective_loss:
            pkt.loss_risk = 1.0 - ((1.0 - pkt.loss_risk) * (1.0 - effective_loss))
            pkt.touched_sybil = pkt.touched_sybil or nxt in self.graph.sybil_nodes
            pkt.last_from = pkt.node
            pkt.last_neighbor = nxt
            reason = "sybil_drop" if nxt in self.graph.sybil_nodes else "link_loss"
            self._drop(pkt, reason)
            return
        key = (pkt.node, nxt)
        available = self._link_available.get(key, time)
        start = max(time, available)
        queue_delay = start - time
        service = self.queue_service_time / max(0.05, metrics.bandwidth)
        self._link_available[key] = start + service
        pkt.queue_delay += queue_delay
        pkt.latency += metrics.latency + queue_delay + service
        pkt.loss_risk = 1.0 - ((1.0 - pkt.loss_risk) * (1.0 - effective_loss))
        pkt.touched_sybil = pkt.touched_sybil or nxt in self.graph.sybil_nodes
        pkt.last_from = pkt.node
        pkt.node = nxt
        pkt.last_neighbor = nxt
        pkt.hops += 1
        pkt.ttl -= 1
        self._schedule(Event(start + service + metrics.latency, "arrive", pkt.packet_id))

    def _notify_solver(self, pkt: Packet, *, delivered: bool, dropped: bool, reason: str | None = None) -> None:
        observer = getattr(self.solver, "observe_result", None)
        neighbor = getattr(pkt, "last_neighbor", None)
        from_node = getattr(pkt, "last_from", None)
        if observer is not None and neighbor is not None:
            observer(
                neighbor=neighbor,
                delivered=delivered,
                dropped=dropped,
                # Blame the sybil touch only on the hop where it happened.
                # pkt.touched_sybil is path-cumulative: passing it here poisons
                # the reputation of honest hops that merely came after a sybil.
                touched_sybil=(reason == "sybil_drop"),
                reason=reason,
                from_node=from_node,
            )

    def _stats(self) -> EventStats:
        all_packets = list(self._packets.values())
        delivered = self._delivered
        return EventStats(
            generated=len(all_packets),
            delivered=len(delivered),
            dropped=len(self._dropped),
            in_flight=len(self._in_flight),
            drop_reasons=dict(self._drop_reasons),
            avg_hops=mean([p.hops for p in delivered]) if delivered else float("inf"),
            avg_latency=mean([p.latency for p in delivered]) if delivered else float("inf"),
            avg_queue_delay=mean([p.queue_delay for p in all_packets]) if all_packets else 0.0,
            avg_loss_risk=mean([p.loss_risk for p in all_packets]) if all_packets else 0.0,
            sybil_touch_ratio=sum(1 for p in all_packets if p.touched_sybil) / max(1, len(all_packets)),
        )
