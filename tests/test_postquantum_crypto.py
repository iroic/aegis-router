import unittest

from aegis_router.packet import Packet
from aegis_router.postquantum_crypto import PostQuantumIdentity, sign_packet, verify_packet, kyber768_roundtrip


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

    def test_ml_kem_768_shared_secret_roundtrip(self):
        identity = PostQuantumIdentity.generate()
        ciphertext, sender_secret, receiver_secret = kyber768_roundtrip(identity.kem_public_key, identity.kem_secret_key)

        self.assertGreater(len(ciphertext), 0)
        self.assertEqual(sender_secret, receiver_secret)
        self.assertEqual(len(sender_secret), 32)


if __name__ == "__main__":
    unittest.main()
