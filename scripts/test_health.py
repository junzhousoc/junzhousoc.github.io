import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from health import record_health


class HealthTests(unittest.TestCase):
    def test_no_content_updates_still_produce_monthly_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'health.json'
            first = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)
            self.assertTrue(record_health(path, 'success', first))
            original = path.read_bytes()
            self.assertFalse(record_health(path, 'success', first.replace(hour=12)))
            self.assertEqual(original, path.read_bytes())
            self.assertTrue(record_health(path, 'success', datetime(2026, 11, 1, tzinfo=timezone.utc)))
            self.assertEqual(json.loads(path.read_text())['month'], '2026-11')

    def test_source_failure_does_not_prevent_monthly_health_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.sync/health.json'
            record_health(path, 'failure', datetime(2026, 12, 1, tzinfo=timezone.utc))
            self.assertEqual(json.loads(path.read_text())['source_sync_outcome'], 'failure')

    def test_year_boundary_advances_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'health.json'
            record_health(path, 'success', datetime(2026, 12, 31, tzinfo=timezone.utc))
            self.assertTrue(record_health(path, 'success', datetime(2027, 1, 1, tzinfo=timezone.utc)))
