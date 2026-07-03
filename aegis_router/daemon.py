from __future__ import annotations

"""Real-socket local network test harness.

Runs each simulated node as its own asyncio UDP endpoint on localhost,
exercising the actual wire path (JSON serialization, real socket send/recv,
ML-DSA-44 origin signing verified at the destination) instead of the
discrete-event simulator's in-process arithmetic. Routing decisions reuse the
existing solvers unchanged via the same RoutingSolver.next_hop(graph, packet)
interface -- only the transport around them is real.

This is a same-machine loopback test. Pointing `registry` entries at real
remote addresses (e.g. across a VPN link) instead of 127.0.0.1 requires no
code change here, only how the registry is built.
"""

import argparse
import asyncio
from collections import Counter
import itertools
import json
import random
import time
from dataclasses import dataclass, field
from statistics import mean

from .graph import LinkMetrics, NodeId, P2PGraph, generate_random_graph
from .packet import Packet
from .postquantum_crypto import PostQuantumIdentity, sign_packet, verify_packet
from .solvers import AdaptiveRiskSolver, EdgeLearningSolver, RiskAwareHybridSolver, RoutingSolver, ShortestPathSolver

Registry = dict[NodeId, tuple[str, int]]
PubkeyRegistry = dict[NodeId, bytes]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def packet_to_wire(pkt: Packet) -> dict:
    return {
        "packet_id": pkt.packet_id,
        "src": pkt.src,
        "dst": pkt.dst,
        "created_at": pkt.created_at,
        "ttl": pkt.ttl,
        "node": pkt.node,
        "visited": sorted(pkt.visited),
        "hops": pkt.hops,
        "latency": pkt.latency,
        "queue_delay": pkt.queue_delay,
        "loss_risk": pkt.loss_risk,
        "touched_sybil": pkt.touched_sybil,
        "signature": pkt.signature,
        "last_from": pkt.last_from,
        "last_neighbor": pkt.last_neighbor,
    }


def packet_from_wire(data: dict) -> Packet:
    pkt = Packet(
        packet_id=data["packet_id"],
        src=data["src"],
        dst=data["dst"],
        created_at=data["created_at"],
        ttl=data["ttl"],
        node=data["node"],
    )
    pkt.visited = set(data["visited"])
    pkt.hops = data["hops"]
    pkt.latency = data["latency"]
    pkt.queue_delay = data["queue_delay"]
    pkt.loss_risk = data["loss_risk"]
    pkt.touched_sybil = data["touched_sybil"]
    pkt.signature = data["signature"]
    pkt.last_from = data["last_from"]
    pkt.last_neighbor = data["last_neighbor"]
    return pkt


@dataclass
class ClusterStats:
    generated: int = 0
    delivered: list[Packet] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)
    retransmissions: int = 0
    # Packets that touched >=1 sybil node at any point, delivered or not --
    # not the same as sybil_drop count, which only counts packets killed
    # AT a sybil hop. A packet can touch a sybil and still succeed, or fail
    # later for an unrelated reason; this is the security-relevant exposure
    # metric (matches EventStats.sybil_touch_ratio in event_sim.py).
    sybil_touched: int = 0
    # Extra copies sent for source-path redundancy, beyond the first (the
    # first copy of every packet is "free" -- it's what non-redundant mode
    # also sends). Bandwidth overhead accounting, parallel to retransmissions.
    redundant_copies: int = 0

    def record_generated(self) -> None:
        self.generated += 1

    def record_delivery(self, pkt: Packet) -> None:
        self.delivered.append(pkt)
        if pkt.touched_sybil:
            self.sybil_touched += 1

    def record_drop(self, reason: str, pkt: Packet | None = None) -> None:
        self.dropped[reason] += 1
        if pkt is not None and pkt.touched_sybil:
            self.sybil_touched += 1

    def record_retransmissions(self, n: int) -> None:
        self.retransmissions += n

    def record_redundant_copy(self) -> None:
        self.redundant_copies += 1

    @property
    def delivery_ratio(self) -> float:
        return len(self.delivered) / max(1, self.generated)

    @property
    def sybil_touch_ratio(self) -> float:
        return self.sybil_touched / max(1, self.generated)

    def summary(self) -> dict:
        n = len(self.delivered)
        return {
            "generated": self.generated,
            "delivered": n,
            "delivery_ratio": self.delivery_ratio,
            "dropped": dict(self.dropped),
            "avg_hops": mean(p.hops for p in self.delivered) if n else None,
            "avg_latency": mean(p.latency for p in self.delivered) if n else None,
            "retransmissions": self.retransmissions,
            "sybil_touch_ratio": self.sybil_touch_ratio,
            "redundant_copies": self.redundant_copies,
        }


class LocalNodeProtocol(asyncio.DatagramProtocol):
    """One simulated node: a real UDP endpoint that signs, verifies, and
    forwards packets using an unmodified RoutingSolver."""

    def __init__(
        self,
        node_id: NodeId,
        graph: P2PGraph,
        solver: RoutingSolver,
        registry: Registry,
        pubkeys: PubkeyRegistry,
        identity: PostQuantumIdentity,
        stats: ClusterStats,
        rng: random.Random,
        sybil_extra_drop: float,
        ttl: int,
        link_retries: int,
        redundancy: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.node_id = node_id
        self.graph = graph
        self.solver = solver
        self.registry = registry
        self.pubkeys = pubkeys
        self.identity = identity
        self.stats = stats
        self.rng = rng
        self.sybil_extra_drop = sybil_extra_drop
        self.ttl = ttl
        self.link_retries = max(0, link_retries)
        self.redundancy = max(1, redundancy)
        self.loop = loop
        self.transport: asyncio.DatagramTransport | None = None
        # Dedup for redundant copies of the same packet_id arriving via
        # different paths: only the first arrival counts as delivery.
        self._delivered_ids: set[int] = set()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        pkt = packet_from_wire(json.loads(data.decode("utf-8")))
        self._handle_arrival(pkt)

    def send_new_packet(self, dst: NodeId, packet_id: int) -> None:
        # Source-only path redundancy: send up to `redundancy` copies of the
        # same packet_id. Copies are biased toward a DIFFERENT first hop via
        # the existing hard-exclusion-of-visited-nodes logic (added earlier
        # this session to kill routing loops), with no new solver-side code
        # -- but only for solvers whose next_hop() actually reads
        # packet.visited (RiskAwareHybridSolver and its edge/adaptive-risk
        # descendants). ShortestPathSolver.next_hop() is a pure BFS that
        # ignores visited entirely, so for it every copy is a fresh
        # whole-path retry with independent randomness rather than a
        # genuinely different route -- still a real, measured effect (each
        # copy re-rolls its own link_loss/sybil_drop/churn-timing draws
        # along the way), just a different mechanism.
        #
        # Targets the node_down failure mode diagnosed under churn: a
        # packet correctly routed toward a node that dies mid-transit.
        # Independent attempts rarely die to the same churn event, so
        # redundancy recovers most of that loss at the cost of
        # (redundancy - 1) extra copies of wire traffic.
        chosen_first_hops: set[NodeId] = set()
        for i in range(self.redundancy):
            pkt = Packet(packet_id=packet_id, src=self.node_id, dst=dst, created_at=time.monotonic(), ttl=self.ttl, node=self.node_id)
            sign_packet(pkt, self.identity.signing_secret_key)
            nxt = self._handle_arrival(pkt, extra_exclude=chosen_first_hops)
            if nxt is None:
                break  # no route at all for this copy; further copies would fare no better
            chosen_first_hops.add(nxt)
            # Every copy beyond the first is overhead, whether or not it
            # landed on a genuinely new hop -- a low-degree node may have no
            # alternative to offer, in which case this is a plain duplicate,
            # not wasted-but-still-a-cost bandwidth.
            if i > 0:
                self.stats.record_redundant_copy()

    def _handle_arrival(self, pkt: Packet, *, extra_exclude: set[NodeId] | None = None) -> NodeId | None:
        """Process an arriving (or freshly originated) packet.

        Returns the next hop it was forwarded to, or None if it was
        delivered, deduplicated, or dropped without forwarding -- used by
        send_new_packet() to pick a distinct first hop for each redundant copy.

        `extra_exclude` is ONLY ever passed by send_new_packet(), for a
        packet's very first decision at its own origin. It biases just that
        one next_hop() call away from hops already claimed by sibling
        redundant copies, then is stripped again before the packet is
        forwarded -- it must never leak into the packet's real, persistent
        `visited` set, or this copy's own later, perfectly legitimate visit
        to one of those nodes (it has never actually been there) would be
        misreported as a loop several hops into a completely different path.
        """
        pkt.node = self.node_id
        if pkt.node == pkt.dst:
            if pkt.packet_id in self._delivered_ids:
                return None  # a redundant copy arrived after the first; not a failure, just discard
            if not verify_packet(pkt, self.pubkeys[pkt.src]):
                self.stats.record_drop("bad_signature", pkt)
                return None
            self._delivered_ids.add(pkt.packet_id)
            pkt.latency = time.monotonic() - pkt.created_at
            self.stats.record_delivery(pkt)
            return None
        # Arrived at a node that has since churned offline. The hop that
        # delivered us here made a decision that was correct at the time;
        # not its fault, so no observe_result call (matches event_sim.py).
        if self.node_id in self.graph.offline_nodes:
            self.stats.record_drop("node_down", pkt)
            return None
        if pkt.node in pkt.visited:
            self.stats.record_drop("loop", pkt)
            return None
        if pkt.ttl <= 0:
            self.stats.record_drop("ttl_expired", pkt)
            return None
        pkt.visited.add(pkt.node)
        if extra_exclude:
            pkt.visited |= extra_exclude
        nxt = self.solver.next_hop(self.graph, pkt)
        if extra_exclude:
            pkt.visited -= extra_exclude
        if nxt is None or nxt not in self.graph.adj.get(pkt.node, {}):
            self.stats.record_drop("no_route", pkt)
            return None
        self._forward(pkt, nxt)
        return nxt

    def _forward(self, pkt: Packet, nxt: NodeId) -> None:
        # The solver decided on `nxt` from a snapshot of graph.offline_nodes
        # that can already be stale (chosen just before a churn tick, or the
        # only reachable candidate went down in the gap between decision and
        # send). Attribute this to the hop, unlike the arrival-side check,
        # matching event_sim.py's distinction between the two cases.
        if nxt in self.graph.offline_nodes:
            self._observe_own_link(nxt, success=False, reason="node_down")
            self.stats.record_drop("node_down", pkt)
            return
        m = self.graph.metrics(pkt.node, nxt)
        extra = self.sybil_extra_drop if nxt in self.graph.sybil_nodes else 0.0
        effective_loss = min(0.95, m.loss + extra)
        # Hop-by-hop ARQ: retry a lost frame on the same link before giving
        # up. Ported from event_sim.py, where it broke the (1-loss)^hops
        # delivery ceiling; ~200-line link_loss dominance at low sybil ratio
        # is exactly that ceiling showing up on real sockets. Each failed
        # try costs one extra link-latency round, same as the simulator.
        failed_tries = 0
        success = False
        for _ in range(1 + self.link_retries):
            if self.rng.random() >= effective_loss:
                success = True
                break
            failed_tries += 1
        # Retransmissions = transmissions beyond the first attempt. A single
        # failed try with no retries left is NOT a retransmission -- it's
        # just the one attempt everyone always makes.
        transmissions = failed_tries + (1 if success else 0)
        self.stats.record_retransmissions(max(0, transmissions - 1))
        self._observe_own_link(nxt, success=success)
        # Set before the outcome branch: a packet dropped BY a sybil hop
        # must still count as sybil-touched (a prior bug here only updated
        # this on the success path, undercounting real exposure).
        pkt.touched_sybil = pkt.touched_sybil or nxt in self.graph.sybil_nodes
        if not success:
            reason = "sybil_drop" if nxt in self.graph.sybil_nodes else "link_loss"
            self.stats.record_drop(reason, pkt)
            return
        pkt.last_from = pkt.node
        pkt.last_neighbor = nxt
        pkt.hops += 1
        pkt.ttl -= 1
        payload = json.dumps(packet_to_wire(pkt)).encode("utf-8")
        # Emulate the declared link latency as a real scheduling delay so
        # avg_latency reflects something other than loopback noise; the
        # datagram itself is still sent over a real socket. Failed tries
        # before the eventual success each cost one extra latency round.
        delay = m.latency * (1 + failed_tries)
        self.loop.call_later(delay, self._send_now, payload, nxt)

    def _observe_own_link(self, nxt: NodeId, *, success: bool, reason: str | None = None) -> None:
        """Feed the local solver's reputation learner from THIS hop's own
        outcome, not the packet's eventual end-to-end fate.

        A real node has no free ACK channel telling it whether a packet it
        forwarded was delivered several hops later (event_sim.py's shared,
        single-solver model gets to assume that global view; each daemon
        node here has its own independent, local-only solver instance and
        state file, which is the more realistic assumption for a real
        decentralized network). What a node genuinely knows is whether its
        own transmission onto the wire to `nxt` succeeded or was dropped --
        that is what gets reported here.
        """
        observer = getattr(self.solver, "observe_result", None)
        if observer is None:
            return
        if reason is None and not success:
            reason = "sybil_drop" if nxt in self.graph.sybil_nodes else "link_loss"
        observer(
            neighbor=nxt,
            delivered=success,
            dropped=not success,
            touched_sybil=nxt in self.graph.sybil_nodes,
            reason=reason,
            from_node=self.node_id,
        )

    def _send_now(self, payload: bytes, nxt: NodeId) -> None:
        # A delayed call_later (ARQ retries and per-hop latency both push
        # the actual send past the drain window) can still be pending when
        # run_local_cluster closes every transport at shutdown. Firing into
        # an already-closed transport isn't an error worth crashing over --
        # the packet is simply lost past the measurement window.
        if self.transport is None or self.transport.is_closing():
            return
        host, port = self.registry[nxt]
        self.transport.sendto(payload, (host, port))


def _make_solver(name: str, *, seed: int) -> RoutingSolver:
    if name == "shortest":
        return ShortestPathSolver()
    if name == "risk-aware":
        return RiskAwareHybridSolver()
    if name == "adaptive-risk":
        return AdaptiveRiskSolver()
    if name == "edge":
        return EdgeLearningSolver(state_path=f"/tmp/aegis_daemon_node_state_{seed}.json", edge_penalty=1.0, risk_budget=0.35)
    raise ValueError(f"unknown solver: {name}")


async def _perturb_loop(
    graph: P2PGraph,
    node_ids: list[NodeId],
    *,
    perturb_interval: float,
    congestion_rate: float,
    congestion_jitter: float,
    churn_rate: float,
    churn_recovery: float,
    rng: random.Random,
) -> None:
    """Periodic real-time network dynamics, ported from event_sim.py's
    _handle_perturb: congestion drift on a sample of edges, and node churn
    via the same graph.offline_nodes set every solver already respects.
    Runs for the lifetime of the cluster; cancelled by the caller.
    """
    edges = [(a, b) for a in graph.adj for b in graph.adj[a] if a < b]
    while True:
        await asyncio.sleep(perturb_interval)
        if congestion_rate > 0.0 and edges:
            k = max(1, int(congestion_rate * len(edges)))
            for a, b in rng.sample(edges, min(k, len(edges))):
                m = graph.metrics(a, b)
                j = congestion_jitter
                drifted = LinkMetrics(
                    latency=_clamp(m.latency + rng.uniform(-j, j), 0.02, 1.5),
                    bandwidth=_clamp(m.bandwidth + rng.uniform(-j, j), 0.05, 1.0),
                    loss=_clamp(m.loss + rng.uniform(-j, j), 0.0, 0.7),
                    stability=_clamp(m.stability + rng.uniform(-j, j), 0.05, 1.0),
                )
                graph.add_edge(a, b, drifted)
        if churn_rate > 0.0:
            for node in node_ids:
                if node in graph.offline_nodes:
                    if rng.random() < churn_recovery:
                        graph.offline_nodes.discard(node)
                elif rng.random() < churn_rate:
                    graph.offline_nodes.add(node)


async def run_local_cluster(
    *,
    nodes: int = 8,
    degree: int = 3,
    sybil_ratio: float = 0.2,
    sybil_stealth: float = 0.0,
    duration: float = 5.0,
    drain: float = 2.0,
    traffic_rate: float = 3.0,
    ttl: int = 12,
    sybil_extra_drop: float = 0.12,
    link_retries: int = 0,
    redundancy: int = 1,
    churn_rate: float = 0.0,
    churn_recovery: float = 0.4,
    congestion_rate: float = 0.0,
    congestion_jitter: float = 0.15,
    perturb_interval: float = 0.5,
    solver_name: str = "edge",
    seed: int = 7,
    base_port: int = 19000,
) -> ClusterStats:
    graph = generate_random_graph(nodes=nodes, degree=degree, sybil_ratio=sybil_ratio, sybil_stealth=sybil_stealth, seed=seed)
    node_ids = graph.nodes()
    registry: Registry = {n: ("127.0.0.1", base_port + n) for n in node_ids}
    identities = {n: PostQuantumIdentity.generate() for n in node_ids}
    pubkeys: PubkeyRegistry = {n: identities[n].signing_public_key for n in node_ids}
    stats = ClusterStats()
    rng = random.Random(seed + 1)

    loop = asyncio.get_running_loop()
    protocols: dict[NodeId, LocalNodeProtocol] = {}
    transports: list[asyncio.BaseTransport] = []
    for n in node_ids:
        solver = _make_solver(solver_name, seed=seed * 1000 + n)
        protocol = LocalNodeProtocol(
            n, graph, solver, registry, pubkeys, identities[n], stats,
            random.Random(seed + 100 + n), sybil_extra_drop, ttl, link_retries, redundancy, loop,
        )
        transport, _ = await loop.create_datagram_endpoint(lambda p=protocol: p, local_addr=registry[n])
        protocols[n] = protocol
        transports.append(transport)

    perturb_task: asyncio.Task | None = None
    if churn_rate > 0.0 or congestion_rate > 0.0:
        perturb_task = asyncio.create_task(_perturb_loop(
            graph, node_ids, perturb_interval=perturb_interval,
            congestion_rate=congestion_rate, congestion_jitter=congestion_jitter,
            churn_rate=churn_rate, churn_recovery=churn_recovery,
            rng=random.Random(seed + 500),
        ))

    packet_ids = itertools.count()
    end_time = loop.time() + duration
    try:
        while loop.time() < end_time:
            src, dst = rng.sample(node_ids, 2)
            protocols[src].send_new_packet(dst, next(packet_ids))
            stats.record_generated()
            await asyncio.sleep(rng.expovariate(traffic_rate))
        await asyncio.sleep(drain)
    finally:
        if perturb_task is not None:
            perturb_task.cancel()
            try:
                await perturb_task
            except asyncio.CancelledError:
                pass
        for t in transports:
            t.close()
        # transport.close() schedules the underlying socket close on the
        # event loop rather than releasing it synchronously; without this,
        # a second run reusing the same ports can race and hit
        # "Address already in use".
        await asyncio.sleep(0.1)
        # Persist learned reputation so a subsequent run (same seed) resumes
        # from it -- without this, EdgeLearningSolver's load() would always
        # see the same untouched state, and "learning across runs" would be
        # a no-op despite the state file existing.
        for protocol in protocols.values():
            saver = getattr(protocol.solver, "save", None)
            if callable(saver):
                saver()
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description="Aegis Router real-socket local network test")
    p.add_argument("--nodes", type=int, default=8)
    p.add_argument("--degree", type=int, default=3)
    p.add_argument("--sybil-ratio", type=float, default=0.2)
    p.add_argument("--sybil-stealth", type=float, default=0.0, help="0=obvious sybil links, 1=sybil links advertise honest-looking metrics")
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--drain", type=float, default=2.0)
    p.add_argument("--traffic-rate", type=float, default=3.0)
    p.add_argument("--ttl", type=int, default=12)
    p.add_argument("--link-retries", type=int, default=0, help="hop-by-hop ARQ: retransmissions allowed per link before the hop counts as lost")
    p.add_argument("--redundancy", type=int, default=1, help="source-path redundancy: number of disjoint-first-hop copies sent per packet")
    p.add_argument("--churn-rate", type=float, default=0.0, help="probability an up node goes offline per perturbation tick")
    p.add_argument("--churn-recovery", type=float, default=0.4, help="probability a down node recovers per perturbation tick")
    p.add_argument("--congestion-rate", type=float, default=0.0, help="fraction of edges whose metrics drift per perturbation tick")
    p.add_argument("--congestion-jitter", type=float, default=0.15)
    p.add_argument("--perturb-interval", type=float, default=0.5, help="seconds between churn/congestion ticks")
    p.add_argument("--solver", choices=["shortest", "risk-aware", "adaptive-risk", "edge"], default="edge")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--base-port", type=int, default=19000)
    args = p.parse_args()

    stats = asyncio.run(run_local_cluster(
        nodes=args.nodes, degree=args.degree, sybil_ratio=args.sybil_ratio,
        sybil_stealth=args.sybil_stealth, duration=args.duration, drain=args.drain,
        traffic_rate=args.traffic_rate, ttl=args.ttl, link_retries=args.link_retries,
        redundancy=args.redundancy,
        churn_rate=args.churn_rate, churn_recovery=args.churn_recovery,
        congestion_rate=args.congestion_rate, congestion_jitter=args.congestion_jitter,
        perturb_interval=args.perturb_interval, solver_name=args.solver,
        seed=args.seed, base_port=args.base_port,
    ))
    print(json.dumps(stats.summary(), indent=2))


if __name__ == "__main__":
    main()
