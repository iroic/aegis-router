from __future__ import annotations

from dataclasses import dataclass
import heapq
import itertools
import random
from collections import Counter
from statistics import mean
from typing import Callable

from .graph import NodeId, P2PGraph
from .packet import Packet
from .solvers import RoutingSolver


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
    ) -> None:
        try:
            from .postquantum_crypto import PostQuantumIdentity
        except ImportError:
            PostQuantumIdentity = None  # Fallback when post‑quantum libs are unavailable
        self.graph = graph
        self.solver = solver
        self.rng = random.Random(seed)
        self.ttl = ttl
        self.queue_service_time = queue_service_time
        self.sybil_extra_drop = sybil_extra_drop
        self._events: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self._packets: dict[int, Packet] = {}
        self._link_available: dict[tuple[NodeId, NodeId], float] = {}
        self._delivered: list[Packet] = []
        self._dropped: list[Packet] = []
        self._drop_reasons: Counter[str] = Counter()
        self._in_flight: list[Packet] = []
        # Generate a single post‑quantum identity for the whole simulator (nodes share the same keys for demo purposes)
        if PostQuantumIdentity is not None:
            self._pq_identity = PostQuantumIdentity.generate()
        else:
            self._pq_identity = None  # PQ disabled


    def run(self, *, duration: float, traffic_rate: float, drain_time: float = 0.0) -> EventStats:
        end_time = duration + max(0.0, drain_time)
        self._schedule(Event(0.0, "generate"))
        while self._events:
            time, _, event = heapq.heappop(self._events)
            if time > end_time:
                break
            if event.kind == "generate":
                if time <= duration:
                    self._handle_generate(time, duration, traffic_rate)
            elif event.kind == "arrive" and event.packet_id is not None:
                self._handle_arrive(time, event.packet_id)
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
                touched_sybil=pkt.touched_sybil,
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
