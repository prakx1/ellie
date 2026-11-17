import unittest

from ellie.redact import redact


class RedactionTests(unittest.TestCase):
    def test_patterns_and_multiline_key(self):
        samples = ["AKIA" + "A" * 16, "sk-" + "x" * 32, "ghp_" + "x" * 36,
                   "password=example", 'PASSWORD="some words"',
                   "-----BEGIN RSA PRIVATE KEY-----\nfixture\n-----END RSA PRIVATE KEY-----"]
        for sample in samples:
            self.assertEqual(redact(sample), "[redacted]")

    def test_ordinary_text_unchanged(self):
        self.assertEqual(redact("Use Redis for counters 🐘"), "Use Redis for counters 🐘")
