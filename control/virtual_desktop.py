"""
Windows Picture-in-Picture (PiP) Virtual Desktop Sandbox Engine.
Provides non-disruptive computer automation using isolated Windows Desktops (WinSta0\\AIMVR_Sandbox).
Allows the agent to launch applications, inspect UI trees, and execute automation workflows
without stealing the human user's physical mouse cursor, keyboard focus, or interrupting foreground work.
"""

import ctypes
from ctypes import wintypes
import time
import os
import sys
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
ole32 = ctypes.windll.ole32

# Desktop Access Flags
DESKTOP_READOBJECTS = 0x0001
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_CREATEMENU = 0x0004
DESKTOP_HOOKCONTROL = 0x0008
DESKTOP_JOURNALRECORD = 0x0010
DESKTOP_JOURNALPLAYBACK = 0x0020
DESKTOP_ENUMERATE = 0x0040
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100
GENERIC_ALL = 0x10000000
DESKTOP_ALL = (
    DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_HOOKCONTROL
    | DESKTOP_JOURNALRECORD
    | DESKTOP_JOURNALPLAYBACK
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_SWITCHDESKTOP
)

# Win32 Process & Window Constants
STARTF_USESHOWWINDOW = 0x00000001
SW_SHOW = 5
SW_SHOWNORMAL = 1
SW_RESTORE = 9
PW_RENDERFULLCONTENT = 2
COINIT_MULTITHREADED = 0x0

# 64-bit safe signatures
user32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
user32.CreateDesktopW.restype = wintypes.HANDLE

user32.OpenDesktopW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
]
user32.OpenDesktopW.restype = wintypes.HANDLE

user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL

user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
user32.GetThreadDesktop.restype = wintypes.HANDLE

user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

# GDI and User32 64-bit safe prototypes
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL

gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.RealChildWindowFromPoint.argtypes = [wintypes.HWND, wintypes.POINT]
user32.RealChildWindowFromPoint.restype = wintypes.HWND


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wintypes.BOOL


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


DEFAULT_SANDBOX_NAME = "AIMVR_Sandbox"


class VirtualDesktopManager:
    """
    Manages isolated desktop lifecycle (creation, process execution, window capture).
    """

    def __init__(self, sandbox_name: str = DEFAULT_SANDBOX_NAME):
        self.sandbox_name = sandbox_name
        self.desktop_mode: str = "interactive"  # "interactive" | "isolated_pip"
        self._sandbox_handle: Optional[int] = None
        self._original_desktop: Optional[int] = None
        self._tracked_pids: List[int] = []

    def set_mode(self, mode: str) -> str:
        """Sets active desktop automation mode ('interactive' or 'isolated_pip')."""
        clean_mode = mode.lower().strip()
        if clean_mode not in ["interactive", "isolated_pip"]:
            raise ValueError(f"Unknown desktop mode '{mode}'. Choose 'interactive' or 'isolated_pip'.")
        self.desktop_mode = clean_mode
        if self.desktop_mode == "isolated_pip":
            self.ensure_sandbox()
        sys.stderr.write(f"[VirtualDesktop] Desktop mode switched to: {self.desktop_mode}\n")
        return self.desktop_mode

    def get_mode(self) -> str:
        """Returns the current desktop automation mode."""
        return self.desktop_mode

    def ensure_sandbox(self) -> int:
        """
        Creates or opens the dedicated isolated sandbox desktop.
        Returns the HDESK handle.
        """
        if self._sandbox_handle:
            return self._sandbox_handle

        # Try opening existing desktop first
        h_desk = user32.OpenDesktopW(self.sandbox_name, 0, False, DESKTOP_ALL)
        if not h_desk:
            # Create new desktop inside WinSta0
            h_desk = user32.CreateDesktopW(
                self.sandbox_name,
                None,
                None,
                0,
                DESKTOP_ALL,
                None,
            )

        if not h_desk:
            raise ctypes.WinError(f"Failed to create or open sandbox desktop '{self.sandbox_name}'.")

        self._sandbox_handle = h_desk
        sys.stderr.write(f"[VirtualDesktop] Sandbox desktop '{self.sandbox_name}' active (handle={h_desk}).\n")
        return self._sandbox_handle

    def run_in_sandbox(self, func, *args, timeout: float = 10.0, **kwargs):
        """
        Executes a callable inside a dedicated clean worker thread attached to the
        isolated sandbox desktop with Multithreaded Apartment (MTA) COM.
        """
        import threading
        self.ensure_sandbox()
        result = [None]
        exc = [None]
        desk_handle = [None]

        def target():
            h_desk = user32.OpenDesktopW(self.sandbox_name, 0, False, DESKTOP_ALL)
            if h_desk:
                desk_handle[0] = h_desk
                user32.SetThreadDesktop(h_desk)
            ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
            try:
                result[0] = func(*args, **kwargs)
            except Exception as e:
                exc[0] = e
            finally:
                ole32.CoUninitialize()

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout=timeout)
        # Close desktop handle in parent thread after worker thread terminates (avoids ERROR_BUSY 170)
        if desk_handle[0]:
            try:
                user32.CloseDesktop(desk_handle[0])
            except Exception:
                pass
        if t.is_alive():
            raise TimeoutError(f"Sandbox worker thread timed out after {timeout}s.")
        if exc[0]:
            raise exc[0]
        return result[0]

    def launch_in_sandbox(self, command_line: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Launches an application directly onto the isolated sandbox desktop using CreateProcessW.
        The window will not appear on the user's physical screen and will not receive physical clicks.
        """
        self.ensure_sandbox()

        # Bind desktop string to local scope to prevent garbage collection before CreateProcessW runs
        desktop_target = f"WinSta0\\{self.sandbox_name}"
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop = desktop_target
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNORMAL

        pi = PROCESS_INFORMATION()

        cmd_buf = ctypes.create_unicode_buffer(command_line)
        cwd_w = wintypes.LPCWSTR(cwd) if cwd else None

        success = kernel32.CreateProcessW(
            None,
            cmd_buf,
            None,
            None,
            False,
            0,
            None,
            cwd_w,
            ctypes.byref(si),
            ctypes.byref(pi),
        )

        if not success:
            err = ctypes.GetLastError()
            return {
                "status": "error",
                "message": f"CreateProcessW failed with error code {err}",
                "command": command_line,
                "desktop": self.sandbox_name,
            }

        pid = int(pi.dwProcessId)
        self._tracked_pids.append(pid)

        # Close process and thread handles to avoid handle leaks
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)

        # Allow time for initial window creation
        time.sleep(0.3)

        return {
            "status": "launched_in_sandbox",
            "pid": pid,
            "command": command_line,
            "desktop": self.sandbox_name,
            "desktop_mode": "isolated_pip",
        }

    # Backward-compatible alias
    launch_process_in_sandbox = launch_in_sandbox

    def list_sandbox_windows(self) -> List[Dict[str, Any]]:
        """
        Enumerates all top-level windows currently open inside the isolated sandbox desktop.
        """
        def _list():
            h_desk = self.ensure_sandbox()
            windows = []

            def enum_cb(hwnd, lparam):
                if not user32.IsWindow(hwnd):
                    return True
                if not user32.IsWindowVisible(hwnd):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()

                if not title:
                    return True

                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                if w > 0 and h > 0:
                    windows.append({
                        "hwnd": int(hwnd),
                        "title": title,
                        "bounds": [int(rect.left), int(rect.top), int(w), int(h)],
                        "pid": int(pid.value),
                    })
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            cb_func = WNDENUMPROC(enum_cb)
            user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, WNDENUMPROC, wintypes.LPARAM]
            user32.EnumDesktopWindows.restype = wintypes.BOOL
            user32.EnumDesktopWindows(h_desk, cb_func, 0)
            return windows

        return self.run_in_sandbox(_list)

    def capture_sandbox_window(self, hwnd: int) -> Image.Image:
        """
        Captures the visual buffer of a window inside the isolated sandbox using PrintWindow.
        """
        def _capture():
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = max(1, rect.right - rect.left)
            height = max(1, rect.bottom - rect.top)

            hdc_screen = user32.GetDC(0)
            hdc_mem = None
            hbm = None
            h_old = None
            try:
                hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
                hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
                h_old = gdi32.SelectObject(hdc_mem, hbm)

                user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)

                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = width
                bmi.biHeight = -height
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0

                buf_size = width * height * 4
                buffer = ctypes.create_string_buffer(buf_size)
                gdi32.GetDIBits(hdc_mem, hbm, 0, height, buffer, ctypes.byref(bmi), 0)

                img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
                return img
            finally:
                if hdc_mem and h_old:
                    gdi32.SelectObject(hdc_mem, h_old)
                if hbm:
                    gdi32.DeleteObject(hbm)
                if hdc_mem:
                    gdi32.DeleteDC(hdc_mem)
                if hdc_screen:
                    user32.ReleaseDC(0, hdc_screen)

        return self.run_in_sandbox(_capture)

    def capture_pip_composite(
        self,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
        max_dim: int = 1024,
        quality: int = 75,
        scale: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Picture-in-Picture composite preview of all windows open in the sandbox.
        Renders them onto a simulated dark desktop background and downsamples for token efficiency.
        """
        import io
        import base64

        if scale is not None and scale > 0:
            max_dim = max(100, int(1024 * scale))

        windows = self.list_sandbox_windows()
        # Create dark slate simulated desktop canvas
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(30, 34, 42))

        rendered_count = 0
        for win in windows:
            try:
                hwnd = win["hwnd"]
                bx, by, bw, bh = win["bounds"]
                w_img = self.capture_sandbox_window(hwnd)
                if w_img and w_img.size[0] > 0 and w_img.size[1] > 0:
                    # Clip coordinates inside canvas bounds
                    paste_x = max(0, min(bx, canvas_width - 10))
                    paste_y = max(0, min(by, canvas_height - 10))
                    canvas.paste(w_img, (paste_x, paste_y))
                    rendered_count += 1
            except Exception as e:
                sys.stderr.write(f"[VirtualDesktop] Window render error: {e}\n")

        # Downsample to max_dim preserving aspect ratio
        scale = 1.0
        orig_w, orig_h = canvas.size
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = int(round(orig_w * scale))
            new_h = int(round(orig_h * scale))
            proc_img = canvas.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            proc_img = canvas

        buf = io.BytesIO()
        proc_img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {
            "status": "pip_preview",
            "desktop": self.sandbox_name,
            "mode": self.desktop_mode,
            "windows_count": len(windows),
            "rendered_windows": rendered_count,
            "width": proc_img.size[0],
            "height": proc_img.size[1],
            "scale": scale,
            "image_b64": b64,
            "windows": windows,
        }

    def capture_pip_canvas(
        self,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
    ) -> Tuple[Image.Image, List[Dict[str, Any]]]:
        """
        Creates and returns the direct PIL Image canvas and window list of all windows
        open in the sandbox desktop without JPEG compression or base64 encoding.
        """
        windows = self.list_sandbox_windows()
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(30, 34, 42))
        for win in windows:
            try:
                hwnd = win["hwnd"]
                bx, by, bw, bh = win["bounds"]
                w_img = self.capture_sandbox_window(hwnd)
                if w_img and w_img.size[0] > 0 and w_img.size[1] > 0:
                    paste_x = max(0, min(bx, canvas_width - 10))
                    paste_y = max(0, min(by, canvas_height - 10))
                    canvas.paste(w_img, (paste_x, paste_y))
            except Exception as e:
                sys.stderr.write(f"[VirtualDesktop] Window render error: {e}\n")
        return canvas, windows

    def find_sandbox_window(self, target: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Finds a top-level window inside the sandbox desktop matching target substring."""
        windows = self.list_sandbox_windows()
        if not windows:
            return None
        if not target:
            return windows[0]
        target_lower = target.lower().strip()
        for win in windows:
            if target_lower in win["title"].lower():
                return win
        return windows[0] if windows else None

    def _get_input_target_hwnd(self, hwnd: int) -> int:
        """Finds the most suitable child control window (e.g. RichEdit, Edit) or falls back to hwnd."""
        child_hwnds: List[int] = []

        def enum_child_cb(h_child, lparam):
            if user32.IsWindow(h_child) and user32.IsWindowVisible(h_child):
                child_hwnds.append(h_child)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        cb_func = WNDENUMPROC(enum_child_cb)
        user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
        user32.EnumChildWindows.restype = wintypes.BOOL
        user32.EnumChildWindows(hwnd, cb_func, 0)

        # Priority 1: RichEdit control (modern Notepad, WordPad, etc.)
        for ch in child_hwnds:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ch, buf, 256)
            cname = buf.value.lower()
            if "richedit" in cname:
                return ch

        # Priority 2: Standard Win32 Edit or Scintilla
        for ch in child_hwnds:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ch, buf, 256)
            cname = buf.value.lower()
            if cname == "edit" or "scintilla" in cname:
                return ch

        # Priority 3: TextBox or Document controls (excluding non-client/sink windows)
        for ch in child_hwnds:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ch, buf, 256)
            cname = buf.value.lower()
            if ("textbox" in cname or "document" in cname) and not any(k in cname for k in ["nonclient", "sink"]):
                return ch

        # Priority 4: First non-sink child
        for ch in child_hwnds:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ch, buf, 256)
            cname = buf.value.lower()
            if not any(k in cname for k in ["nonclient", "sink", "bridge", "site"]):
                return ch

        return child_hwnds[0] if child_hwnds else hwnd

    def click_sandbox_window(
        self,
        target: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
    ) -> bool:
        """Dispatches mouse click message to target window in the sandbox desktop via PostMessageW."""
        win = self.find_sandbox_window(target)
        if not win:
            return False
        hwnd = win["hwnd"]
        bx, by, bw, bh = win["bounds"]

        if x is not None and y is not None:
            if x >= bx and y >= by:
                client_x = x - bx
                client_y = y - by
            else:
                client_x = x
                client_y = y
        else:
            client_x = max(10, bw // 2)
            client_y = max(10, bh // 2)

        lParam = (int(client_y) << 16) | (int(client_x) & 0xFFFF)
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        WM_RBUTTONDOWN = 0x0204
        WM_RBUTTONUP = 0x0205
        WM_MOUSEMOVE = 0x0200
        MK_LBUTTON = 0x0001
        MK_RBUTTON = 0x0002

        msg_down = WM_RBUTTONDOWN if button == "right" else WM_LBUTTONDOWN
        msg_up = WM_RBUTTONUP if button == "right" else WM_LBUTTONUP
        mk_btn = MK_RBUTTON if button == "right" else MK_LBUTTON

        target_hwnd = hwnd
        pt = wintypes.POINT(int(client_x), int(client_y))
        child = user32.RealChildWindowFromPoint(hwnd, pt)
        if child and child != hwnd:
            target_hwnd = child

        for _ in range(clicks):
            user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, 0, lParam)
            user32.PostMessageW(target_hwnd, msg_down, mk_btn, lParam)
            time.sleep(0.02)
            user32.PostMessageW(target_hwnd, msg_up, 0, lParam)
            if clicks > 1:
                time.sleep(0.05)
        return True

    def type_in_sandbox(self, target: Optional[str] = None, text: str = "", interval: float = 0.01) -> bool:
        """Dispatches text characters directly to target window/control via WM_CHAR messages."""
        win = self.find_sandbox_window(target)
        if not win:
            return False
        target_hwnd = self._get_input_target_hwnd(win["hwnd"])

        # Send a brief focus click to target control to activate caret
        lParam = (20 << 16) | 20
        WM_MOUSEMOVE = 0x0200
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, 0, lParam)
        user32.PostMessageW(target_hwnd, WM_LBUTTONDOWN, 1, lParam)
        time.sleep(0.02)
        user32.PostMessageW(target_hwnd, WM_LBUTTONUP, 0, lParam)
        time.sleep(0.04)

        WM_CHAR = 0x0102
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        VK_RETURN = 0x0D

        # Maintain a visible typing cadence so streaming is perceptible in PiP window (15-20 frames)
        char_interval = max(0.04, interval)

        for char in text:
            if char in ("\n", "\r"):
                user32.PostMessageW(target_hwnd, WM_KEYDOWN, VK_RETURN, 0)
                user32.PostMessageW(target_hwnd, WM_KEYUP, VK_RETURN, 0)
            else:
                user32.PostMessageW(target_hwnd, WM_CHAR, ord(char), 0)
            time.sleep(char_interval)
        return True

    def paste_in_sandbox(self, target: Optional[str] = None, text: str = "") -> bool:
        """Copies text to clipboard and posts WM_PASTE to sandbox window."""
        from control.clipboard import default_clipboard
        default_clipboard.set_text(text)
        win = self.find_sandbox_window(target)
        if not win:
            return False
        target_hwnd = self._get_input_target_hwnd(win["hwnd"])

        # Send focus click
        lParam = (20 << 16) | 20
        user32.PostMessageW(target_hwnd, 0x0200, 0, lParam)
        user32.PostMessageW(target_hwnd, 0x0201, 1, lParam)
        time.sleep(0.02)
        user32.PostMessageW(target_hwnd, 0x0202, 0, lParam)
        time.sleep(0.04)

        WM_PASTE = 0x0302
        user32.SendMessageW(target_hwnd, WM_PASTE, 0, 0)
        return True

    def press_key_in_sandbox(self, target: Optional[str] = None, key: str = "enter") -> bool:
        """Dispatches virtual key message to target window in sandbox."""
        win = self.find_sandbox_window(target)
        if not win:
            return False
        target_hwnd = self._get_input_target_hwnd(win["hwnd"])

        key_map = {
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "esc": 0x1B,
            "escape": 0x1B,
            "backspace": 0x08,
            "space": 0x20,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "delete": 0x2E,
        }
        vk = key_map.get(key.lower(), 0x0D)
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        user32.PostMessageW(target_hwnd, WM_KEYDOWN, vk, 0)
        time.sleep(0.02)
        user32.PostMessageW(target_hwnd, WM_KEYUP, vk, 0)
        return True

    def hotkey_in_sandbox(self, target: Optional[str] = None, keys: Optional[List[str]] = None) -> bool:
        """Dispatches common hotkeys to sandbox window via messages."""
        if not keys:
            return False
        win = self.find_sandbox_window(target)
        if not win:
            return False
        target_hwnd = self._get_input_target_hwnd(win["hwnd"])

        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        WM_PASTE = 0x0302
        WM_COPY = 0x0301
        WM_CUT = 0x0300

        lower_keys = [k.lower() for k in keys]
        if "ctrl" in lower_keys or "control" in lower_keys:
            other_keys = [k for k in lower_keys if k not in ("ctrl", "control")]
            if other_keys:
                letter = other_keys[0].upper()
                if letter == "A":
                    EM_SETSEL = 0x00B1
                    user32.SendMessageW(target_hwnd, EM_SETSEL, 0, -1)
                elif letter == "C":
                    user32.SendMessageW(target_hwnd, WM_COPY, 0, 0)
                elif letter == "V":
                    user32.SendMessageW(target_hwnd, WM_PASTE, 0, 0)
                elif letter == "X":
                    user32.SendMessageW(target_hwnd, WM_CUT, 0, 0)
                else:
                    vk_ctrl = 0x11
                    vk_letter = ord(letter) if len(letter) == 1 else 0x41
                    user32.PostMessageW(target_hwnd, WM_KEYDOWN, vk_ctrl, 0)
                    user32.PostMessageW(target_hwnd, WM_KEYDOWN, vk_letter, 0)
                    time.sleep(0.02)
                    user32.PostMessageW(target_hwnd, WM_KEYUP, vk_letter, 0)
                    user32.PostMessageW(target_hwnd, WM_KEYUP, vk_ctrl, 0)
                return True
        return False

    def close_sandbox_window(self, target: str, force: bool = False) -> bool:
        """Sends WM_CLOSE or force-kills matching windows inside the sandbox desktop."""
        target_lower = target.lower().strip()
        windows = self.list_sandbox_windows()
        closed_count = 0
        pids_to_kill = set()

        for win in windows:
            title_lower = win["title"].lower()
            if target_lower in title_lower or target_lower in ("all", "*"):
                hwnd = win["hwnd"]
                pid = win.get("pid")
                if force and pid:
                    pids_to_kill.add(pid)
                else:
                    WM_CLOSE = 0x0010
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                closed_count += 1

        if force and pids_to_kill:
            import subprocess
            for pid in pids_to_kill:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                except Exception:
                    pass

        return closed_count > 0

    def destroy_sandbox(self) -> Dict[str, Any]:
        """
        Terminates all tracked and active sandbox processes, clears zombie windows,
        and cleans up desktop handles.
        """
        import subprocess
        # Collect any remaining processes owning windows inside the sandbox desktop
        try:
            active_wins = self.list_sandbox_windows()
            for w in active_wins:
                w_pid = w.get("pid")
                if w_pid and w_pid not in self._tracked_pids:
                    self._tracked_pids.append(w_pid)
        except Exception:
            pass

        for pid in list(self._tracked_pids):
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            except Exception:
                pass
        self._tracked_pids.clear()

        # Terminate any lingering background notepad instances
        try:
            subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
        except Exception:
            pass

        if self._sandbox_handle:
            user32.CloseDesktop(self._sandbox_handle)
            self._sandbox_handle = None

        self.desktop_mode = "interactive"
        return {
            "status": "destroyed",
            "desktop": self.sandbox_name,
            "mode": "interactive",
        }


# Global default instance
default_virtual_desktop = VirtualDesktopManager()
