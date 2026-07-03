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

from .graph import NodeId, P2PGraph, generate_random_graph
from .packet import Packet
from .postquantum_crypto import PostQuantumIdentity, sign_packet, verify_packet
from .solvers import EdgeLearningSolver, RoutingSolver, ShortestPathSolver

Registry = dict[NodeId, tuple[str, int]]
PubkeyRegistry = dict[NodeId, bytes]


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

    def record_generated(self) -> None:
        self.generated += 1

    def record_delivery(self, pkt: Packet) -> None:
        self.delivered.append(pkt)

    def record_drop(self, reason: str) -> None:
        self.dropped[reason] += 1

    def summary(self) -> dict:
        n = len(self.delivered)
        return {
            "generated": self.generated,
            "delivered": n,
            "delivery_ratio": n / max(1, self.generated),
            "dropped": dict(self.dropped),
            "avg_hops": mean(p.hops for p in self.delivered) if n else None,
            "avg_latency": mean(p.latency for p in self.delivered) if n else None,
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
        self.loop = loop
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        pkt = packet_from_wire(json.loads(data.decode("utf-8")))
        self._handle_arrival(pkt)

    def send_new_packet(self, dst: NodeId, packet_id: int) -> None:
        pkt = Packet(packet_id=packet_id, src=self.node_id, dst=dst, created_at=time.monotonic(), ttl=self.ttl, node=self.node_id)
        sign_packet(pkt, self.identity.signing_secret_key)
        self._handle_arrival(pkt)

    def _handle_arrival(self, pkt: Packet) -> None:
        pkt.node = self.node_id
        if pkt.node == pkt.dst:
            if not verify_packet(pkt, self.pubkeys[pkt.src]):
                self.stats.record_drop("bad_signature")
                return
            pkt.latency = time.monotonic() - pkt.created_at
            self.stats.record_delivery(pkt)
            return
        if pkt.node in pkt.visited:
            self.stats.record_drop("loop")
            return
        if pkt.ttl <= 0:
            self.stats.record_drop("ttl_expired")
            return
        pkt.visited.add(pkt.node)
        nxt = self.solver.next_hop(self.graph, pkt)
        if nxt is None or nxt not in self.graph.adj.get(pkt.node, {}):
            self.stats.record_drop("no_route")
            return
        self._forward(pkt, nxt)

    def _forward(self, pkt: Packet, nxt: NodeId) -> None:
        m = self.graph.metrics(pkt.node, nxt)
        extra = self.sybil_extra_drop if nxt in self.graph.sybil_nodes else 0.0
        effective_loss = min(0.95, m.loss + extra)
        success = self.rng.random() >= effective_loss
        self._observe_own_link(nxt, success=success)
        if not success:
            reason = "sybil_drop" if nxt in self.graph.sybil_nodes else "link_loss"
            self.stats.record_drop(reason)
            return
        pkt.touched_sybil = pkt.touched_sybil or nxt in self.graph.sybil_nodes
        pkt.last_from = pkt.node
        pkt.last_neighbor = nxt
        pkt.hops += 1
        pkt.ttl -= 1
        payload = json.dumps(packet_to_wire(pkt)).encode("utf-8")
        # Emulate the declared link latency as a real scheduling delay so
        # avg_latency reflects something other than loopback noise; the
        # datagram itself is still sent over a real socket.
        self.loop.call_later(m.latency, self._send_now, payload, nxt)

    def _observe_own_link(self, nxt: NodeId, *, success: bool) -> None:
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
        observer(
            neighbor=nxt,
            delivered=success,
            dropped=not success,
            touched_sybil=nxt in self.graph.sybil_nodes,
            reason=None if success else ("sybil_drop" if nxt in self.graph.sybil_nodes else "link_loss"),
            from_node=self.node_id,
        )

    def _send_now(self, payload: bytes, nxt: NodeId) -> None:
        assert self.transport is not None
        host, port = self.registry[nxt]
        self.transport.sendto(payload, (host, port))


def _make_solver(name: str, *, seed: int) -> RoutingSolver:
    if name == "shortest":
        return ShortestPathSolver()
    if name == "edge":
        return EdgeLearningSolver(state_path=f"/tmp/aegis_daemon_node_state_{seed}.json", edge_penalty=1.0, risk_budget=0.35)
    raise ValueError(f"unknown solver: {name}")


async def run_local_cluster(
    *,
    nodes: int = 8,
    degree: int = 3,
    sybil_ratio: float = 0.2,
    duration: float = 5.0,
    drain: float = 2.0,
    traffic_rate: float = 3.0,
    ttl: int = 12,
    sybil_extra_drop: float = 0.12,
    solver_name: str = "edge",
    seed: int = 7,
    base_port: int = 19000,
) -> ClusterStats:
    graph = generate_random_graph(nodes=nodes, degree=degree, sybil_ratio=sybil_ratio, seed=seed)
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
            random.Random(seed + 100 + n), sybil_extra_drop, ttl, loop,
        )
        transport, _ = await loop.create_datagram_endpoint(lambda p=protocol: p, local_addr=registry[n])
        protocols[n] = protocol
        transports.append(transport)

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
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--drain", type=float, default=2.0)
    p.add_argument("--traffic-rate", type=float, default=3.0)
    p.add_argument("--ttl", type=int, default=12)
    p.add_argument("--solver", choices=["shortest", "edge"], default="edge")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--base-port", type=int, default=19000)
    args = p.parse_args()

    stats = asyncio.run(run_local_cluster(
        nodes=args.nodes, degree=args.degree, sybil_ratio=args.sybil_ratio,
        duration=args.duration, drain=args.drain, traffic_rate=args.traffic_rate,
        ttl=args.ttl, solver_name=args.solver, seed=args.seed, base_port=args.base_port,
    ))
    print(json.dumps(stats.summary(), indent=2))


if __name__ == "__main__":
    main()
