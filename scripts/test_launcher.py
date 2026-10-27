"""Launcher failure-path checks; no real services or operational data are modified."""
import io
import unittest
from unittest.mock import patch, Mock
import launch


class LauncherTests(unittest.TestCase):
    def test_health_rejects_other_app(self):
        with patch('launch.urllib.request.urlopen', return_value=io.BytesIO(b'{"status":"healthy","app":"Other"}')):
            self.assertFalse(launch.healthy(3000))

    def test_health_rejects_unavailable_database(self):
        with patch('launch.urllib.request.urlopen', return_value=io.BytesIO(b'{"status":"not_ready","app":"College Fleet Command"}')):
            self.assertFalse(launch.healthy(8000))

    def test_health_accepts_correct_service(self):
        with patch('launch.urllib.request.urlopen', return_value=io.BytesIO(b'{"status":"healthy","app":"College Fleet Command"}')):
            self.assertTrue(launch.healthy(8000))

    def test_health_handles_invalid_json(self):
        with patch('launch.urllib.request.urlopen', return_value=io.BytesIO(b'<html>wrong service</html>')):
            self.assertFalse(launch.healthy(3000))

    def test_failed_process_does_not_claim_ready(self):
        child = Mock(); child.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            launch.wait_for(lambda: True, 'api', child)

    def test_readiness_timeout(self):
        with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
            launch.wait_for(lambda: False, 'api', seconds=0)


if __name__ == '__main__': unittest.main()
