import unittest
from test_scheduler_router_reuse import SchedulerSelfModTests
loader = unittest.TestLoader()
suite = loader.loadTestsFromTestCase(SchedulerSelfModTests)
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
