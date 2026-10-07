"""
tests/test_smoke_main.py - Smoke test verifying src.main imports cleanly
without unhandled NameErrors or missing typing references.
"""

import unittest
import importlib

class TestSmokeMain(unittest.TestCase):
    def test_import_src_main(self):
        try:
            import src.main
            self.assertTrue(hasattr(src.main, "ChalkCoordinator"))
            self.assertTrue(hasattr(src.main, "ChunkSynthesisWorker"))
        except NameError as e:
            self.fail(f"import src.main failed with NameError: {e}")
        except Exception as e:
            # If Qt display server is missing in headless CI, module should still import
            self.fail(f"import src.main raised unexpected error: {e}")

if __name__ == "__main__":
    unittest.main()
