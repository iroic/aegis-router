from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from pqcrypto.kem import ml_kem_768
from pqcrypto.sign import ml_dsa_44

from .packet import Packet

SIGNATURE_PREFIX = "ml-dsa-44:"


@dataclass(frozen=True)
class PostQuantumIdentity:
    """Node identity using NIST post-quantum primitives.

    ML-DSA-44 is the standardized successor of Dilithium-2 for signatures.
    ML-KEM-768 is the standardized successor of Kyber-768 for key exchange.
    """

    signing_public_key: bytes
    signing_secret_key: bytes
    kem_public_key: bytes
    kem_secret_key: bytes

    @classmethod
    def generate(cls) -> "PostQuantumIdentity":
        signing_public_key, signing_secret_key = ml_dsa_44.generate_keypair()
        kem_public_key, kem_secret_key = ml_kem_768.generate_keypair()
        return cls(
            signing_public_key=signing_public_key,
            signing_secret_key=signing_secret_key,
            kem_public_key=kem_public_key,
            kem_secret_key=kem_secret_key,
        )


def _origin_signing_bytes(packet_id: int, src: int, dst: int, created_at: float) -> bytes:
    """Canonical bytes for the origin-fixed fields of a packet.

    Shared by both the origin-authenticity signature (sign_packet, made by
    src) and the delivery receipt (sign_receipt, made by dst) so a receipt
    provably refers to exactly one originated packet. Only fields that never
    change after origination are covered: ttl/loss_risk/touched_sybil mutate
    every hop and so cannot be part of an end-to-end signature.
    """
    payload = {
        "packet_id": packet_id,
        "src": src,
        "dst": dst,
        "created_at": created_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def packet_signing_bytes(packet: Packet) -> bytes:
    """Stable packet bytes covered by the origin-authenticity signature."""
    return _origin_signing_bytes(packet.packet_id, packet.src, packet.dst, packet.created_at)


def sign_packet(packet: Packet, signing_secret_key: bytes) -> str:
    signature = ml_dsa_44.sign(signing_secret_key, packet_signing_bytes(packet))
    encoded = base64.b64encode(signature).decode("ascii")
    packet.signature = f"{SIGNATURE_PREFIX}{encoded}"
    return packet.signature


def verify_packet(packet: Packet, signing_public_key: bytes) -> bool:
    if not packet.signature or not packet.signature.startswith(SIGNATURE_PREFIX):
        return False
    encoded = packet.signature[len(SIGNATURE_PREFIX) :]
    try:
        signature = base64.b64decode(encoded, validate=True)
        return bool(ml_dsa_44.verify(signing_public_key, packet_signing_bytes(packet), signature))
    except Exception:
        return False


def sign_receipt(packet_id: int, src: int, dst: int, created_at: float, signing_secret_key: bytes) -> str:
    """A delivery receipt: the destination signs the packet's origin fields,
    producing unforgeable proof that this exact packet reached its dst. Sent
    back along the reverse path so every forwarding node learns the
    end-to-end fate of what it relayed, not just whether its own next-hop
    link accepted the frame.
    """
    signature = ml_dsa_44.sign(signing_secret_key, _origin_signing_bytes(packet_id, src, dst, created_at))
    return f"{SIGNATURE_PREFIX}{base64.b64encode(signature).decode('ascii')}"


def verify_receipt(packet_id: int, src: int, dst: int, created_at: float, receipt_signature: str, dst_public_key: bytes) -> bool:
    """Verify a delivery receipt against the claimed destination's public key.

    A sybil cannot forge this: it would need dst's secret key. That is what
    makes receipt-derived reputation evidence rather than opinion, unlike
    peer-gossiped reputation which a sybil can lie into.
    """
    if not receipt_signature or not receipt_signature.startswith(SIGNATURE_PREFIX):
        return False
    encoded = receipt_signature[len(SIGNATURE_PREFIX):]
    try:
        signature = base64.b64decode(encoded, validate=True)
        return bool(ml_dsa_44.verify(dst_public_key, _origin_signing_bytes(packet_id, src, dst, created_at), signature))
    except Exception:
        return False


def kyber768_roundtrip(kem_public_key: bytes, kem_secret_key: bytes) -> tuple[bytes, bytes, bytes]:
    """Exercise ML-KEM-768/Kyber-768: encapsulate then decapsulate."""

    ciphertext, sender_secret = ml_kem_768.encrypt(kem_public_key)
    receiver_secret = ml_kem_768.decrypt(kem_secret_key, ciphertext)
    return ciphertext, sender_secret, receiver_secret
