import unittest
from agy_metrics.clock import FakeClock
from agy_metrics.schema import NULL, UNKNOWN, SCHEMA_VERSION, Completeness

class TestFoundation(unittest.TestCase):
    def test_fake_clock_is_deterministic(self):
        c = FakeClock(1000)
        self.assertEqual(c.now_ms(), 1000)
        c.advance(250)
        self.assertEqual(c.now_ms(), 1250)
        c.set(5000)
        self.assertEqual(c.now_ms(), 5000)

    def test_sentinels_are_distinct(self):
        self.assertIsNone(NULL)
        self.assertEqual(UNKNOWN, "unknown")
        self.assertNotEqual(NULL, UNKNOWN)

    def test_schema_version(self):
        self.assertEqual(SCHEMA_VERSION, 1)

if __name__ == "__main__":
    unittest.main()
