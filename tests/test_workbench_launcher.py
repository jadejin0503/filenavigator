import os
import tempfile
import unittest


class TestWorkbenchLauncher(unittest.TestCase):
    def test_cache_roundtrip(self):
        import workbench_launcher as wl

        with tempfile.TemporaryDirectory() as td:
            cache_path = os.path.join(td, "cache.json")
            wl.save_workbench_cache(cache_path, {"PDTManager": r"C:\x\PDTManager_v1.exe"})
            data = wl.load_workbench_cache(cache_path)
            self.assertEqual(data.get("PDTManager"), r"C:\x\PDTManager_v1.exe")

    def test_choose_exe_prefers_cached_when_exists(self):
        import workbench_launcher as wl

        cached = r"C:\tools\old.exe"
        scanned = r"C:\tools\new.exe"
        chosen = wl.choose_exe_to_launch(cached_exe=cached, scanned_exe=scanned, cached_exists=True, scanned_exists=True)
        self.assertEqual(chosen, cached)

    def test_choose_exe_falls_back_to_scanned_when_no_cached(self):
        import workbench_launcher as wl

        cached = r"C:\tools\old.exe"
        scanned = r"C:\tools\new.exe"
        chosen = wl.choose_exe_to_launch(cached_exe=cached, scanned_exe=scanned, cached_exists=False, scanned_exists=True)
        self.assertEqual(chosen, scanned)

    def test_windows_silent_popen_kwargs(self):
        import workbench_launcher as wl

        kw = wl.build_windows_silent_popen_kwargs()
        # creationflags must exist on Windows; we validate presence, not exact value for portability in CI.
        self.assertIn("creationflags", kw)
        self.assertIn("close_fds", kw)
        self.assertFalse(kw["close_fds"])


if __name__ == "__main__":
    unittest.main()

