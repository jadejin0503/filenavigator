import unittest


class TestPMRefreshWorker(unittest.TestCase):
    def test_coerce_tasks_from_malformed_dict(self):
        from app_qt import _PMRefreshWorker

        raw = {"0": {"content": "a", "id": "1"}, "1": "plain string", "x": 99}
        out = _PMRefreshWorker._coerce_tasks(raw)
        self.assertEqual(len(out), 2)
        self.assertIsInstance(out[0], dict)
        self.assertEqual(out[1], "plain string")

    def test_coerce_tasks_from_non_list(self):
        from app_qt import _PMRefreshWorker

        self.assertEqual(_PMRefreshWorker._coerce_tasks(None), [])
        self.assertEqual(_PMRefreshWorker._coerce_tasks(42), [])

    def test_worker_cleans_malformed_subprojects(self):
        from app_qt import _PMRefreshWorker

        pm = {
            "root_ta": "bad",
            "subprojects": {
                "sk1": {
                    "subproject_name": "Trial A",
                    "tasks": {"0": {"id": "t1", "content": "hello", "status": "bogus"}},
                    "milestones": "not-a-dict",
                    "priority": "超高",
                    "status": "unknown",
                },
                "": {"subproject_name": "skip empty key"},
                123: {"subproject_name": "skip non-dict key"},
            },
        }
        worker = _PMRefreshWorker(pm)
        results = []

        def on_finished(data):
            results.append(data)

        worker.signals.finished.connect(on_finished)
        worker.run()
        self.assertEqual(len(results), 1)
        clean = results[0]
        self.assertIsInstance(clean.get("root_ta"), dict)
        subs = clean.get("subprojects", {})
        self.assertIn("sk1", subs)
        info = subs["sk1"]
        self.assertEqual(info["priority"], "中")
        self.assertEqual(info["status"], "未完成")
        self.assertIsInstance(info["tasks"], list)
        self.assertGreaterEqual(len(info["tasks"]), 1)


class TestCoerceTaskEntry(unittest.TestCase):
    def test_string_task_becomes_dict(self):
        from app_qt import QtMainWindow, PFNCore

        w = QtMainWindow.__new__(QtMainWindow)
        out = w._coerce_task_entry("  do something  ", "sk1")
        self.assertIsInstance(out, dict)
        self.assertEqual(out["content"], "do something")
        self.assertEqual(out["status"], "未完成")

    def test_invalid_task_returns_none(self):
        from app_qt import QtMainWindow

        w = QtMainWindow.__new__(QtMainWindow)
        self.assertIsNone(w._coerce_task_entry(None, "sk1"))
        self.assertIsNone(w._coerce_task_entry({"id": "x"}, "sk1"))


if __name__ == "__main__":
    unittest.main()
