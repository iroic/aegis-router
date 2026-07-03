import unittest

from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import (
    PostQuantumIdentity,
    kyber768_roundtrip,
    sign_packet,
    sign_receipt,
    verify_packet,
    verify_receipt,
)


class PostQuantumCryptoTests(unittest.TestCase):
    def test_ml_dsa_44_signs_and_rejects_tampered_packet(self):
        identity = PostQuantumIdentity.generate()
        packet = Packet(packet_id=1, src=1, dst=2, created_at=0.0, ttl=8)

        sign_packet(packet, identity.signing_secret_key)

        self.assertIsNotNone(packet.signature)
        self.assertTrue(verify_packet(packet, identity.signing_public_key))

        packet.dst = 3
        self.assertFalse(verify_packet(packet, identity.signing_public_key))

    def test_signature_survives_legitimate_per_hop_mutation(self):
        # ttl, loss_risk and touched_sybil legitimately change on every hop
        # (see event_sim.py); the origin-authenticity signature must still
        # verify at the destination after those fields have moved.
        identity = PostQuantumIdentity.generate()
        packet = Packet(packet_id=1, src=1, dst=2, created_at=0.0, ttl=8)
        sign_packet(packet, identity.signing_secret_key)

        packet.ttl -= 3
        packet.loss_risk = 0.42
        packet.touched_sybil = True

        self.assertTrue(verify_packet(packet, identity.signing_public_key))

    def test_delivery_receipt_verifies_only_with_destinations_key(self):
        dst = PostQuantumIdentity.generate()
        sig = sign_receipt(42, 1, 7, 123.0, dst.signing_secret_key)
        self.assertTrue(verify_receipt(42, 1, 7, 123.0, sig, dst.signing_public_key))

        # A sybil trying to forge a receipt for a packet it dropped would need
        # dst's secret key -- its own key does not verify.
        sybil = PostQuantumIdentity.generate()
        self.assertFalse(verify_receipt(42, 1, 7, 123.0, sig, sybil.signing_public_key))

    def test_delivery_receipt_is_bound_to_its_exact_packet(self):
        dst = PostQuantumIdentity.generate()
        sig = sign_receipt(42, 1, 7, 123.0, dst.signing_secret_key)
        # A valid receipt for one packet cannot be replayed for another
        # (different packet_id / created_at) even by the legitimate dst.
        self.assertFalse(verify_receipt(43, 1, 7, 123.0, sig, dst.signing_public_key))
        self.assertFalse(verify_receipt(42, 1, 7, 999.0, sig, dst.signing_public_key))

    def test_ml_kem_768_shared_secret_roundtrip(self):
        identity = PostQuantumIdentity.generate()
        ciphertext, sender_secret, receiver_secret = kyber768_roundtrip(identity.kem_public_key, identity.kem_secret_key)

        self.assertGreater(len(ciphertext), 0)
        self.assertEqual(sender_secret, receiver_secret)
        self.assertEqual(len(sender_secret), 32)


if __name__ == "__main__":
    unittest.main()
