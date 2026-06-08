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
    hops: int = 0
    latency: float = 0.0
    queue_delay: float = 0.0
    loss_risk: float = 0.0
    touched_sybil: bool = False

    def __post_init__(self) -> None:
        if self.node is None:
            self.node = self.src
