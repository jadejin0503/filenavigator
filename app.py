import os
from config_manager import ConfigManager
from zdrive_scanner import ZDriveScanner
from file_matcher import FileMatcher
from ui_main import MainWindow
import tkinter as tk
import subprocess
import shutil
import winreg
import ctypes

class PFNApp:
    def __init__(self):
        self.config = ConfigManager()
        self.scanner = ZDriveScanner()
        self.matcher = FileMatcher()
        self.root = tk.Tk()
        self.ui = MainWindow(self)

    def run(self):
        self.root.mainloop()

    def scan_projects(self):
        # Deprecated: The UI now calls list_children directly
        return {}

    def list_children(self, path=None):
        return self.scanner.list_children(path, ["projects", "unblinded", "users"])

    def add_favorite(self, project):
        self.config.add_favorite(project)
        self.config.save()

    def remove_favorite(self, favorite_id):
        self.config.remove_favorite(favorite_id)
        self.config.save()

    def get_favorites(self):
        return self.config.get_favorites()
    
    def get_fixed_paths(self):
        return self.config.get_fixed_paths()
    
    def set_fixed_paths(self, paths):
        self.config.set_fixed_paths(paths)

    def match_files(self, project_path):
        return self.matcher.match(project_path, self.config.rules)

    def open_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in [".xlsx", ".xls", ".csv", ".xml"]:
            excel = shutil.which("excel") or self._find_excel()
            if excel:
                try:
                    subprocess.Popen([excel, path], shell=False)
                    return
                except Exception:
                    try:
                        subprocess.Popen([excel], shell=False)
                        import time
                        time.sleep(1.2)
                        if self._shell_open(path):
                            return
                        return
                    except Exception:
                        pass
            excel_lnk = self._find_excel_shortcut()
            if excel_lnk and os.path.exists(excel_lnk):
                try:
                    target = self._resolve_shortcut_target(excel_lnk)
                    if target and os.path.exists(target):
                        subprocess.Popen([target, path], shell=False)
                        return
                except Exception:
                    pass
            if self._shell_open(path):
                return
            if self._open_excel_com(path):
                return
        if ext in [".sas", ".egp"]:
            eg = self._find_sas_eg()
            if eg:
                subprocess.Popen([eg, path], shell=False)
                return
        if ext in [".doc", ".docx"]:
            word = self._find_word()
            if word:
                try:
                    subprocess.Popen([word, path], shell=False)
                    return
                except Exception:
                    try:
                        subprocess.Popen([word], shell=False)
                        import time
                        time.sleep(1.2)
                        if self._shell_open(path):
                            return
                        return
                    except Exception:
                        pass
            word_lnk = self._find_word_shortcut()
            if word_lnk and os.path.exists(word_lnk):
                try:
                    target = self._resolve_shortcut_target(word_lnk)
                    if target and os.path.exists(target):
                        subprocess.Popen([target, path], shell=False)
                        return
                except Exception:
                    pass
            if self._shell_open(path):
                return
            if self._open_word_com(path):
                return
        if not self._shell_open(path):
            os.startfile(path)
    
    def open_folder(self, folder_path):
        if not os.path.exists(folder_path):
            raise FileNotFoundError("路径不可访问")
        os.startfile(folder_path)
    
    def open_pdf_with_adobe(self, path):
        candidates = [
            r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        ]
        exe = None
        for p in candidates:
            if os.path.exists(p):
                exe = p
                break
        if exe:
            subprocess.Popen([exe, path], shell=False)
        else:
            os.startfile(path)
    
    def open_pdf_in_browser(self, path):
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        exe = None
        for p in candidates:
            if os.path.exists(p):
                exe = p
                break
        if exe:
            subprocess.Popen([exe, path], shell=False)
        else:
            os.startfile(path)

    def _find_excel(self):
        reg = self._find_app_via_registry("excel.exe")
        if reg and os.path.exists(reg):
            return reg
        candidates = [
            r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\root\Office15\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office15\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office16\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\Office15\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office15\EXCEL.EXE",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None
    
    def _find_excel_shortcut(self):
        base = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
        try:
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.lower().endswith(".lnk") and "excel" in f.lower():
                        return os.path.join(root, f)
        except Exception:
            pass
        return None
    
    def has_excel(self):
        return bool(shutil.which("excel") or self._find_excel())

    def _find_sas_eg(self):
        candidates = [
            r"C:\Program Files\SaS\SASHome\SASEnterpriseGuide\8\SEGuide.exe"

        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _find_vscode(self):
        """查找 VS Code 可执行文件，供 .sas 打开方式选择使用。"""
        code = shutil.which("code") or shutil.which("code.cmd")
        if code:
            return code
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                return p
        return None
    
    def _find_word(self):
        reg = self._find_app_via_registry("winword.exe")
        if reg and os.path.exists(reg):
            return reg
        candidates = [
            r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files\Microsoft Office\root\Office15\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office15\WINWORD.EXE",
            r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office16\WINWORD.EXE",
            r"C:\Program Files\Microsoft Office\Office15\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office15\WINWORD.EXE",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None
    
    def _find_word_shortcut(self):
        base = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
        try:
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.lower().endswith(".lnk") and ("word" in f.lower() or "winword" in f.lower()):
                        return os.path.join(root, f)
        except Exception:
            pass
        return None
    
    def _find_app_via_registry(self, app_exe_name):
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{}".format(app_exe_name)),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{}".format(app_exe_name)),
        ]
        for hive, subkey in keys:
            try:
                k = winreg.OpenKey(hive, subkey)
                val, _ = winreg.QueryValueEx(k, "")
                winreg.CloseKey(k)
                if val and os.path.exists(val):
                    return val
            except Exception:
                continue
        return None
    
    def _resolve_shortcut_target(self, lnk_path):
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command",
                "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('{}'); Write-Output $sc.TargetPath".format(lnk_path.replace("'", "''"))
            ]
            out = subprocess.check_output(cmd, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
            target = out.decode("utf-8", errors="ignore").strip()
            return target
        except Exception:
            return None
    
    def _shell_open(self, path):
        try:
            r = ctypes.windll.Shell32.ShellExecuteW(None, "open", path, None, None, 1)
            return r > 32
        except Exception:
            return False
    
    def _open_excel_com(self, path):
        try:
            import win32com.client  # type: ignore
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = True
            xl.Workbooks.Open(path)
            return True
        except Exception:
            # Powershell COM fallback
            try:
                ps = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-Command",
                    "$xl = New-Object -ComObject Excel.Application; $xl.Visible = $true; $xl.Workbooks.Open('{}')".format(path.replace("'", "''"))
                ]
                subprocess.Popen(ps, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
                return True
            except Exception:
                return False
    
    def _open_word_com(self, path):
        try:
            import win32com.client  # type: ignore
            wd = win32com.client.DispatchEx("Word.Application")
            wd.Visible = True
            wd.Documents.Open(path)
            return True
        except Exception:
            try:
                ps = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-Command",
                    "$wd = New-Object -ComObject Word.Application; $wd.Visible = $true; $wd.Documents.Open('{}')".format(path.replace("'", "''"))
                ]
                subprocess.Popen(ps, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
                return True
            except Exception:
                return False

if __name__ == "__main__":
    PFNApp().run()
