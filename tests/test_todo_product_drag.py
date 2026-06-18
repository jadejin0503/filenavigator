import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestTodoDragHelpers(unittest.TestCase):
    def test_should_start_drag(self):
        from app_qt import _pfn_todo_should_start_drag

        self.assertFalse(_pfn_todo_should_start_drag(3, 5))
        self.assertTrue(_pfn_todo_should_start_drag(6, 5))

    def test_insert_index(self):
        from app_qt import _pfn_todo_insert_index

        mids = [50, 150, 250]
        self.assertEqual(_pfn_todo_insert_index(30, mids), 0)
        self.assertEqual(_pfn_todo_insert_index(100, mids), 1)
        self.assertEqual(_pfn_todo_insert_index(200, mids), 2)
        self.assertEqual(_pfn_todo_insert_index(300, mids), 3)
        self.assertEqual(_pfn_todo_insert_index(0, []), 0)


class TestTodoDragRegression(unittest.TestCase):
    def test_no_grab_mouse_in_drag_handlers(self):
        from app_qt import QtMainWindow

        for name in (
            "_todo_begin_product_drag",
            "_todo_finish_product_drag",
            "_todo_reset_product_drag_ui",
        ):
            src = inspect.getsource(getattr(QtMainWindow, name))
            self.assertNotIn("grabMouse", src, msg=name)
            self.assertNotIn("releaseMouse", src, msg=name)

    def test_app_filter_session_present(self):
        from app_qt import QtMainWindow

        src = inspect.getsource(QtMainWindow)
        self.assertIn("_todo_install_drag_app_filter", src)
        self.assertIn("_todo_remove_drag_app_filter", src)
        self.assertIn("_todo_drag_session_event", src)
        self.assertIn("_todo_dnd_app_filter_active", src)

    def test_event_filter_delegates_drag_session_first(self):
        from app_qt import QtMainWindow

        src = inspect.getsource(QtMainWindow.eventFilter)
        idx_session = src.index("_todo_drag_session_event")
        idx_handle = src.index("_todo_product_drag_handle_event")
        self.assertLess(idx_session, idx_handle)


if __name__ == "__main__":
    unittest.main()
