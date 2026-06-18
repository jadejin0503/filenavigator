import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestSubprojectStatusIsDone(unittest.TestCase):
    def test_done_statuses(self):
        from app_qt import _pfn_subproject_status_is_done

        for s in ("已完成", "完成", "done", "Done", "DONE"):
            self.assertTrue(_pfn_subproject_status_is_done(s), msg=s)

    def test_not_done_statuses(self):
        from app_qt import _pfn_subproject_status_is_done

        for s in ("未完成", "", None, "进行中", "todo"):
            self.assertFalse(_pfn_subproject_status_is_done(s), msg=repr(s))


class TestFavTrialDoneBadgeLayout(unittest.TestCase):
    def test_badge_right_aligned_with_padding(self):
        from app_qt import (
            _PFN_FAV_TRIAL_DONE_BADGE_SIZE,
            _PFN_FAV_TRIAL_DONE_RIGHT_PAD,
            _pfn_fav_trial_done_badge_x,
        )

        row_left, row_right = 40, 280
        text_end = 130
        x = _pfn_fav_trial_done_badge_x(row_left, row_right, text_end)
        self.assertEqual(x, row_right - _PFN_FAV_TRIAL_DONE_BADGE_SIZE - _PFN_FAV_TRIAL_DONE_RIGHT_PAD)
        self.assertGreaterEqual(x, text_end + 10)

    def test_badge_keeps_text_gap_when_row_is_wide_enough(self):
        from app_qt import _pfn_fav_trial_done_badge_x

        row_left, row_right = 10, 220
        text_end = 105
        x = _pfn_fav_trial_done_badge_x(row_left, row_right, text_end)
        self.assertGreaterEqual(x, text_end + 10)


class TestTrialDoneFromPmSub(unittest.TestCase):
    def test_done_subproject(self):
        from app_qt import _pfn_trial_done_from_pm_sub

        subs = {"z:\\projects\\hrs1301\\shr2004_301": {"status": "已完成"}}
        self.assertTrue(_pfn_trial_done_from_pm_sub("z:\\projects\\hrs1301\\shr2004_301", subs))

    def test_todo_subproject(self):
        from app_qt import _pfn_trial_done_from_pm_sub

        subs = {"z:\\projects\\hrs1301\\shr2004_302": {"status": "未完成"}}
        self.assertFalse(_pfn_trial_done_from_pm_sub("z:\\projects\\hrs1301\\shr2004_302", subs))

    def test_missing_sub_key(self):
        from app_qt import _pfn_trial_done_from_pm_sub

        self.assertFalse(_pfn_trial_done_from_pm_sub("", {"a": {"status": "已完成"}}))
        self.assertFalse(_pfn_trial_done_from_pm_sub("z:\\x", {}))


class TestTodoRowClickBehavior(unittest.TestCase):
    def test_should_not_focus_tree_on_click(self):
        from app_qt import _pfn_todo_row_should_focus_tree_on_click

        self.assertFalse(_pfn_todo_row_should_focus_tree_on_click())

    def test_event_filter_has_no_focus_tree_timer(self):
        from app_qt import QtMainWindow

        src = inspect.getsource(QtMainWindow.eventFilter)
        self.assertNotIn("_pfn_todo_focus_tree_timer", src)
        self.assertNotIn("_pfn_todo_run_pending_tree_focus", src)
        self.assertNotIn("MouseButtonPress", src)

    def test_fav_trial_done_role_constant(self):
        from PyQt6.QtCore import Qt

        from app_qt import _PFN_FAV_TRIAL_DONE_ROLE

        self.assertEqual(_PFN_FAV_TRIAL_DONE_ROLE, Qt.ItemDataRole.UserRole + 7)

    def test_trial_context_menu_uses_triggered_for_status(self):
        from app_qt import QtMainWindow

        src = inspect.getsource(QtMainWindow._on_fav_context)
        self.assertIn("act_status_done.triggered.connect", src)
        self.assertIn("trial_submenu_applied", src)


if __name__ == "__main__":
    unittest.main()
