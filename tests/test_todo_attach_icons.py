import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ensure_qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestTodoAttachIconHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_attach_icon_row_empty_returns_none(self):
        from app_qt import _pfn_todo_attach_icon_row

        self.assertIsNone(_pfn_todo_attach_icon_row([], False, "normal", lambda *a: None))

    def test_attach_icon_button_has_no_tooltip(self):
        import inspect
        from app_qt import _pfn_todo_attach_icon_button

        src = inspect.getsource(_pfn_todo_attach_icon_button)
        self.assertNotIn("setToolTip", src)


class TestTodoClipboardImageImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_mime_png_bytes_without_has_image(self):
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QImage
        from app_qt import _pfn_mime_to_qimage

        img = QImage(4, 4, QImage.Format.Format_RGB32)
        img.fill(0x00FF00)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        mime = MagicMock()
        mime.hasImage.return_value = False
        mime.formats.return_value = ["image/png"]
        mime.data.return_value = buf.data()
        out = _pfn_mime_to_qimage(mime)
        self.assertFalse(out.isNull())

    def test_import_clipboard_image_saves_png(self):
        from PyQt6.QtGui import QImage
        from app_qt import PersonalTodoTaskEditDialog

        with tempfile.TemporaryDirectory() as td:
            cfg = MagicMock()
            root = os.path.join(td, "PFN_Data", "personal_task_attachments")
            tid = "task-paste"
            cfg.ensure_personal_task_attachment_dir = lambda t: (
                os.makedirs(os.path.join(root, t), exist_ok=True) or os.path.join(root, t)
            )
            cfg.abs_path_personal_task_attachment = lambda rel: os.path.normpath(
                os.path.join(root, str(rel).replace("/", os.sep))
            )

            dlg = PersonalTodoTaskEditDialog.__new__(PersonalTodoTaskEditDialog)
            dlg._cfg = cfg
            dlg._task_id = tid
            dlg._project_sub_key = None
            dlg._current = []
            dlg._rels_added_session = set()
            dlg._pending_add_abs = set()
            dlg._thumb_row = None
            dlg._file_list_col = None

            img = QImage(8, 8, QImage.Format.Format_RGB32)
            img.fill(0xFF0000)
            mime = MagicMock()
            mime.hasImage.return_value = True
            mime.image.return_value = img

            with patch.object(dlg, "_rebuild_attachment_widgets"):
                with patch("app_qt.QGuiApplication") as mock_gui:
                    mock_gui.clipboard.return_value.mimeData.return_value = mime
                    self.assertTrue(dlg._import_clipboard_image())

            self.assertEqual(len(dlg._current), 1)
            self.assertTrue(dlg._current[0].endswith("screenshot.png"))
            abs_path = cfg.abs_path_personal_task_attachment(dlg._current[0])
            self.assertTrue(os.path.isfile(abs_path))

    def test_import_clipboard_image_uses_clipboard_image_fallback(self):
        from PyQt6.QtGui import QImage
        from app_qt import PersonalTodoTaskEditDialog

        with tempfile.TemporaryDirectory() as td:
            cfg = MagicMock()
            root = os.path.join(td, "PFN_Data", "personal_task_attachments")
            tid = "task-fallback"
            cfg.ensure_personal_task_attachment_dir = lambda t: (
                os.makedirs(os.path.join(root, t), exist_ok=True) or os.path.join(root, t)
            )
            cfg.abs_path_personal_task_attachment = lambda rel: os.path.normpath(
                os.path.join(root, str(rel).replace("/", os.sep))
            )

            dlg = PersonalTodoTaskEditDialog.__new__(PersonalTodoTaskEditDialog)
            dlg._cfg = cfg
            dlg._task_id = tid
            dlg._project_sub_key = None
            dlg._current = []
            dlg._rels_added_session = set()
            dlg._pending_add_abs = set()
            dlg._thumb_row = None
            dlg._file_list_col = None

            img = QImage(6, 6, QImage.Format.Format_RGB32)
            img.fill(0x0000FF)
            mime = MagicMock()
            mime.hasImage.return_value = False
            mime.formats.return_value = []
            mime.data.return_value = b""

            with patch.object(dlg, "_rebuild_attachment_widgets"):
                with patch("app_qt.QGuiApplication") as mock_gui:
                    mock_gui.clipboard.return_value.mimeData.return_value = mime
                    mock_gui.clipboard.return_value.image.return_value = img
                    self.assertTrue(dlg._import_clipboard_image())

            self.assertEqual(len(dlg._current), 1)

    def test_import_clipboard_image_no_image_returns_false(self):
        from app_qt import PersonalTodoTaskEditDialog

        dlg = PersonalTodoTaskEditDialog.__new__(PersonalTodoTaskEditDialog)
        dlg._cfg = MagicMock()
        dlg._task_id = "t1"
        dlg._project_sub_key = None
        dlg._current = []
        dlg._rels_added_session = set()
        dlg._pending_add_abs = set()

        mime = MagicMock()
        mime.hasImage.return_value = False
        with patch("app_qt.QGuiApplication") as mock_gui:
            mock_gui.clipboard.return_value.mimeData.return_value = mime
            self.assertFalse(dlg._import_clipboard_image())
        self.assertEqual(dlg._current, [])


class TestTodoTaskAttachmentEntries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_personal_task_mixed_attachments(self):
        from app_qt import QtMainWindow

        with tempfile.TemporaryDirectory() as td:
            cfg = MagicMock()
            root = os.path.join(td, "PFN_Data", "personal_task_attachments")
            tid = "task-1"
            os.makedirs(os.path.join(root, tid), exist_ok=True)
            img = os.path.join(root, tid, "shot.png")
            doc = os.path.join(root, tid, "note.pdf")
            open(img, "wb").close()
            open(doc, "wb").close()
            cfg.abs_path_personal_task_attachment = lambda rel: os.path.normpath(
                os.path.join(root, str(rel).replace("/", os.sep))
            )
            core = MagicMock()
            core.config = cfg
            w = QtMainWindow.__new__(QtMainWindow)
            w.core = core
            task = {
                "id": tid,
                "attachments": [f"{tid}/shot.png", f"{tid}/note.pdf"],
            }
            entries = w._todo_task_attachment_entries(task, sub_key="")
            self.assertEqual(len(entries), 2)
            imgs = [e for e in entries if e["is_image"]]
            files = [e for e in entries if not e["is_image"]]
            self.assertEqual(len(imgs), 1)
            self.assertEqual(len(files), 1)
            self.assertTrue(all(e["exists"] for e in entries))

    def test_malformed_attachments_returns_empty(self):
        from app_qt import QtMainWindow

        core = MagicMock()
        core.config = MagicMock()
        w = QtMainWindow.__new__(QtMainWindow)
        w.core = core
        entries = w._todo_task_attachment_entries({"id": "t1", "attachments": "bad"}, sub_key="")
        self.assertEqual(entries, [])


class TestTodoAttachClickBranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def test_single_entry_opens_directly(self):
        from app_qt import QtMainWindow

        w = QtMainWindow.__new__(QtMainWindow)
        w.statusBar = MagicMock(return_value=MagicMock())
        entry = {"abs": "/x/a.png", "name": "a.png", "is_image": True, "exists": True}
        btn = MagicMock()
        with patch.object(w, "_open_todo_attachment_entry") as mock_open:
            with patch.object(w, "_show_todo_attachment_menu") as mock_menu:
                w._on_todo_attach_icons_clicked([entry], btn)
                mock_open.assert_called_once_with(entry)
                mock_menu.assert_not_called()

    def test_multiple_entries_shows_menu(self):
        from app_qt import QtMainWindow

        w = QtMainWindow.__new__(QtMainWindow)
        entries = [
            {"abs": "/x/a.png", "name": "a.png", "is_image": True, "exists": True},
            {"abs": "/x/b.png", "name": "b.png", "is_image": True, "exists": True},
        ]
        btn = MagicMock()
        with patch.object(w, "_open_todo_attachment_entry") as mock_open:
            with patch.object(w, "_show_todo_attachment_menu") as mock_menu:
                w._on_todo_attach_icons_clicked(entries, btn)
                mock_open.assert_not_called()
                mock_menu.assert_called_once()
                args = mock_menu.call_args[0]
                self.assertEqual(args[0], entries)


if __name__ == "__main__":
    unittest.main()
