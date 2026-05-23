import unittest
from unittest.mock import Mock, patch

from harness.swarm.discovery import DiscoveryService
from harness.swarm.peer import PeerTable


class DiscoveryRefreshTests(unittest.TestCase):
    def test_refresh_rebuilds_socket_when_interfaces_change(self):
        peer_table = PeerTable()
        service = DiscoveryService(8083, peer_table)
        service._running = True
        first_sock = Mock()
        second_sock = Mock()

        with patch.object(service, "_make_socket", side_effect=[first_sock, second_sock]):
            service._refresh_interfaces(force=True, interfaces=[
                {"ip": "192.168.1.10", "bcast": "192.168.1.255"},
            ])
            self.assertEqual(service._local_ips, ["192.168.1.10"])
            service._refresh_interfaces(force=True, interfaces=[
                {"ip": "192.168.1.11", "bcast": "192.168.1.255"},
            ])
            self.assertEqual(service._local_ips, ["192.168.1.11"])
        self.assertEqual(service._bcasts, ["192.168.1.255"])
        self.assertIs(service._sock, second_sock)
        first_sock.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
