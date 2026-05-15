import unittest

from harness.config import _deep_merge_dicts, _repair_legacy_model_aliases, DEFAULT_CONFIG
from harness.daemon.scheduler import SchedulerEngine, _peer_table


class SchedulerRoundRobinTests(unittest.TestCase):
    def setUp(self):
        _peer_table._peers.clear()
        self.engine = SchedulerEngine()

    def tearDown(self):
        _peer_table._peers.clear()

    def test_select_peer_rotates_across_eligible_gamma_peers(self):
        for addr, port in [
            ("10.0.0.1", 8081),
            ("10.0.0.2", 8082),
            ("10.0.0.3", 8083),
        ]:
            _peer_table.add({
                "addr": addr,
                "port": port,
                "hostname": f"peer-{port}",
                "castes": "γ",
                "load": 0,
                "version": "0.1.0",
            })

        self.assertEqual(self.engine._select_peer("γ", 5), "10.0.0.1:8081")
        self.engine._mark_peer_selected("γ", "10.0.0.1:8081")
        self.assertEqual(self.engine._select_peer("γ", 5), "10.0.0.2:8082")
        self.engine._mark_peer_selected("γ", "10.0.0.2:8082")
        self.assertEqual(self.engine._select_peer("γ", 5), "10.0.0.3:8083")
        self.engine._mark_peer_selected("γ", "10.0.0.3:8083")
        self.assertEqual(self.engine._select_peer("γ", 5), "10.0.0.1:8081")

    def test_select_peers_filters_by_caste_and_max_load_before_rotating(self):
        _peer_table.add({
            "addr": "10.0.0.1",
            "port": 8081,
            "hostname": "gamma-only",
            "castes": "γ",
            "load": 1,
            "version": "0.1.0",
        })
        _peer_table.add({
            "addr": "10.0.0.2",
            "port": 8082,
            "hostname": "busy-beta-gamma",
            "castes": "βγ",
            "load": 9,
            "version": "0.1.0",
        })
        _peer_table.add({
            "addr": "10.0.0.3",
            "port": 8083,
            "hostname": "ready-beta-gamma",
            "castes": "βγ",
            "load": 2,
            "version": "0.1.0",
        })

        self.assertEqual(self.engine._select_peers("βγ", 5), ["10.0.0.3:8083"])
        self.assertEqual(
            self.engine._select_peers("γ", 5),
            ["10.0.0.1:8081", "10.0.0.3:8083"],
        )


class ConfigMergeTests(unittest.TestCase):
    def test_deep_merge_preserves_default_delegation_fields(self):
        merged = _deep_merge_dicts(
            {"swarm": {"delegation": {"enabled": True, "max_load": 5, "selection": "round_robin"}}},
            {"swarm": {"delegation": {"max_load": 2}}},
        )

        self.assertEqual(
            merged["swarm"]["delegation"],
            {"enabled": True, "max_load": 2, "selection": "round_robin"},
        )

    def test_repair_legacy_model_aliases_restores_alpha_and_beta_defaults(self):
        cfg = {
            "alpha": {"model": "apple-foundationmodel", "draft_model": "apple-foundationmodel"},
            "beta": {"model": "apple-foundationmodel", "fallback_model": "apple-foundationmodel"},
            "gamma": {"model": "apple-foundationmodel"},
        }

        repaired = _repair_legacy_model_aliases(cfg)

        self.assertTrue(repaired)
        self.assertEqual(cfg["alpha"]["model"], DEFAULT_CONFIG["alpha"]["model"])
        self.assertEqual(cfg["alpha"]["draft_model"], DEFAULT_CONFIG["alpha"]["draft_model"])
        self.assertEqual(cfg["beta"]["model"], DEFAULT_CONFIG["beta"]["model"])
        self.assertEqual(cfg["beta"]["fallback_model"], DEFAULT_CONFIG["beta"]["fallback_model"])
        self.assertEqual(cfg["gamma"]["model"], "apple-foundationmodel")


if __name__ == "__main__":
    unittest.main()
