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


def packet_signing_bytes(packet: Packet) -> bytes:
    """Stable packet bytes covered by the post-quantum signature.

    Only fields that never change after the origin creates the packet are
    signed. ttl, loss_risk and touched_sybil are NOT included even though an
    earlier version of this function signed them: event_sim.py legitimately
    mutates all three on every hop (ttl decrements, loss_risk/touched_sybil
    accumulate), so a signature covering them could only ever verify at the
    very first hop. This is the origin-authenticity signature checked by the
    final recipient, not a per-hop transit MAC.
    """

    payload = {
        "packet_id": packet.packet_id,
        "src": packet.src,
        "dst": packet.dst,
        "created_at": packet.created_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def kyber768_roundtrip(kem_public_key: bytes, kem_secret_key: bytes) -> tuple[bytes, bytes, bytes]:
    """Exercise ML-KEM-768/Kyber-768: encapsulate then decapsulate."""

    ciphertext, sender_secret = ml_kem_768.encrypt(kem_public_key)
    receiver_secret = ml_kem_768.decrypt(kem_secret_key, ciphertext)
    return ciphertext, sender_secret, receiver_secret
