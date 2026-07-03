from __future__ import annotations

from dataclasses import dataclass, field

from .graph import NodeId


@dataclass
class Packet:
    packet_id: int
    src: NodeId
    dst: NodeId
    created_at: float
    ttl: int
    node: NodeId | None = None
    visited: set[NodeId] = field(default_factory=set)
    # Ordered forwarding chain [src, hop1, hop2, ...], each node appending
    # itself as it forwards. Used by the daemon's delivery-receipt mechanism
    # to route a signed receipt back along the reverse path. Unlike `visited`
    # (an unordered dedup set), order matters here. In a real anonymous
    # deployment this would be onion-layered so no single node sees the whole
    # path; here it is in the clear for research measurement.
    path: list[NodeId] = field(default_factory=list)
    hops: int = 0
    latency: float = 0.0
    queue_delay: float = 0.0
    loss_risk: float = 0.0
    touched_sybil: bool = False
    signature: str | None = None  # base64 ML-DSA-44 signature over immutable fields (see postquantum_crypto)
    last_from: NodeId | None = None
    last_neighbor: NodeId | None = None

    def __post_init__(self) -> None:
        if self.node is None:
            self.node = self.src
