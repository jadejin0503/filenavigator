import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ensure_qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestDateEditTeardown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_subproject_editor_teardown_all_ms_rows(self):
        from app_qt import SubprojectTasksEditorDialog

        dlg = SubprojectTasksEditorDialog.__new__(SubprojectTasksEditorDialog)
        de1 = MagicMock()
        de2 = MagicMock()
        row1 = MagicMock(date_edit=de1)
        row2 = MagicMock(date_edit=de2)
        dlg._ms_rows = [row1, row2]
        with patch("app_qt._teardown_pfn_date_edit") as mock_teardown:
            dlg._teardown_all_ms_date_edits()
            self.assertEqual(mock_teardown.call_count, 2)
            mock_teardown.assert_any_call(de1)
            mock_teardown.assert_any_call(de2)

    def test_personal_todo_dialog_done_calls_teardown(self):
        from app_qt import PersonalTodoTaskEditDialog

        dlg = PersonalTodoTaskEditDialog.__new__(PersonalTodoTaskEditDialog)
        dlg.date_due = MagicMock()
        with patch("app_qt._teardown_pfn_date_edit") as mock_teardown:
            with patch("app_qt.QDialog.done", return_value=None):
                PersonalTodoTaskEditDialog.done(dlg, 0)
            mock_teardown.assert_called_once_with(dlg.date_due)

    def test_subproject_dialog_done_calls_teardown(self):
        from app_qt import SubprojectTasksEditorDialog

        dlg = SubprojectTasksEditorDialog.__new__(SubprojectTasksEditorDialog)
        with patch.object(dlg, "_teardown_all_ms_date_edits") as mock_teardown:
            with patch("app_qt.QDialog.done", return_value=None):
                SubprojectTasksEditorDialog.done(dlg, 0)
            mock_teardown.assert_called_once()

    def test_milestone_add_dialog_done_calls_teardown(self):
        from app_qt import MilestoneAddDialog

        dlg = MilestoneAddDialog.__new__(MilestoneAddDialog)
        dlg.date_edit = MagicMock()
        with patch("app_qt._teardown_pfn_date_edit") as mock_teardown:
            with patch("app_qt.QDialog.done", return_value=None):
                MilestoneAddDialog.done(dlg, 0)
            mock_teardown.assert_called_once_with(dlg.date_edit)


if __name__ == "__main__":
    unittest.main()
