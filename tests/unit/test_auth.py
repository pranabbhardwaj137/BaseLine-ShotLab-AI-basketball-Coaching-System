"""
test_auth.py - Unit tests for ShotLabDB user authentication, profile, and onboarding.
"""

import os
import unittest
from basketball.persistence.shot_lab_db import ShotLabDB


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_auth_shot_lab.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.db = ShotLabDB(self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_create_and_verify_user(self):
        user = self.db.create_user(
            email="shooter@example.com",
            password="secretpassword123",
            name="Steph Marksman",
            skill_level="advanced",
            handedness="right",
            shot_style="jump_shot",
            height_cm=191.0,
            wingspan_cm=198.0,
            goals="Consistent arc and quick release"
        )
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "shooter@example.com")
        self.assertEqual(user["name"], "Steph Marksman")
        self.assertEqual(user["skill_level"], "advanced")
        self.assertEqual(user["handedness"], "right")
        self.assertFalse(user["onboarding_completed"])
        self.assertNotIn("password_hash", user)

        # Verify correct credentials
        verified = self.db.verify_user_credentials("shooter@example.com", "secretpassword123")
        self.assertIsNotNone(verified)
        self.assertEqual(verified["id"], user["id"])

        # Verify case insensitivity for email
        verified_upper = self.db.verify_user_credentials("SHOOTER@EXAMPLE.COM", "secretpassword123")
        self.assertIsNotNone(verified_upper)

        # Verify incorrect credentials
        wrong_pwd = self.db.verify_user_credentials("shooter@example.com", "wrongpassword")
        self.assertIsNone(wrong_pwd)
        non_existent = self.db.verify_user_credentials("nonexistent@example.com", "secretpassword123")
        self.assertIsNone(non_existent)

    def test_duplicate_email_rejected(self):
        self.db.create_user("player1@example.com", "password123", "Player One")
        with self.assertRaises(Exception):
            self.db.create_user("player1@example.com", "differentpass", "Player Two")

    def test_update_profile_and_onboarding(self):
        user = self.db.create_user("rookie@example.com", "pass12345", "Rookie Shooter")
        self.assertFalse(user["onboarding_completed"])

        updated = self.db.update_user_profile(user["id"], {
            "skill_level": "intermediate",
            "handedness": "left",
            "height_cm": 185.0,
            "goals": "Fix elbow flare on catch-and-shoot",
            "onboarding_completed": True
        })
        self.assertTrue(updated["onboarding_completed"])
        self.assertEqual(updated["handedness"], "left")
        self.assertEqual(updated["skill_level"], "intermediate")
        self.assertEqual(updated["height_cm"], 185.0)

        # Verify players table was synced
        player = self.db.get_player(updated["player_id"])
        self.assertIsNotNone(player)
        self.assertAlmostEqual(player["height_m"], 1.85, places=2)

    def test_session_lifecycle(self):
        user = self.db.create_user("session_test@example.com", "pass12345", "Session Player")
        token = self.db.create_user_session(user["id"])
        self.assertTrue(len(token) >= 32)

        retrieved = self.db.get_user_by_session(token)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["id"], user["id"])

        # Logout / delete session
        deleted = self.db.delete_user_session(token)
        self.assertTrue(deleted)
        after_logout = self.db.get_user_by_session(token)
        self.assertIsNone(after_logout)

    def test_demo_accounts_seed_and_retrieve(self):
        """Verify the 4 canonical demo accounts can be seeded, queried, and authenticated."""
        demo_accounts = self.db.get_demo_accounts()
        self.assertEqual(len(demo_accounts), 4)

        names = [a["name"] for a in demo_accounts]
        self.assertIn("Pranab", names)
        self.assertIn("Pavan", names)
        self.assertIn("Pracheth", names)
        self.assertIn("Puneeth", names)

        # Test querying each demo athlete
        pranab = self.db.get_demo_user("pranab")
        self.assertIsNotNone(pranab)
        self.assertEqual(pranab["name"], "Pranab")
        self.assertEqual(pranab["handedness"], "right")
        self.assertEqual(pranab["skill_level"], "intermediate")
        self.assertEqual(pranab["shot_style"], "jump_shot")
        self.assertEqual(pranab["height_cm"], 182.0)
        self.assertEqual(pranab["wingspan_cm"], 188.0)
        self.assertFalse(pranab["pain_reported"])
        self.assertTrue(pranab["onboarding_completed"])
        # Verify 123456 credential
        self.assertIsNotNone(self.db.verify_user_credentials(pranab["email"], "123456"))

        pavan = self.db.get_demo_user("pavan")
        self.assertIsNotNone(pavan)
        self.assertEqual(pavan["name"], "Pavan")
        self.assertEqual(pavan["skill_level"], "advanced")
        self.assertEqual(pavan["height_cm"], 186.0)
        self.assertFalse(pavan["pain_reported"])
        self.assertIsNotNone(self.db.verify_user_credentials(pavan["email"], "123456"))

        pracheth = self.db.get_demo_user("pracheth")
        self.assertIsNotNone(pracheth)
        self.assertEqual(pracheth["name"], "Pracheth")
        self.assertEqual(pracheth["handedness"], "left")
        self.assertEqual(pracheth["shot_style"], "set_shot")
        self.assertEqual(pracheth["height_cm"], 178.0)
        self.assertFalse(pracheth["pain_reported"])
        self.assertIsNotNone(self.db.verify_user_credentials(pracheth["email"], "123456"))

        puneeth = self.db.get_demo_user("puneeth")
        self.assertIsNotNone(puneeth)
        self.assertEqual(puneeth["name"], "Puneeth")
        self.assertEqual(puneeth["skill_level"], "developing")
        self.assertEqual(puneeth["height_cm"], 175.0)
        self.assertTrue(puneeth["pain_reported"])
        self.assertIsNotNone(self.db.verify_user_credentials(puneeth["email"], "123456"))


if __name__ == "__main__":
    unittest.main()

