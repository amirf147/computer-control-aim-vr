"""
Floating Picture-in-Picture (PiP) Sandbox Viewer (AIM-VR 3.0).

Opens an Always-On-Top floating preview window on the primary Windows desktop.
Renders real-time visual output of the isolated background sandbox desktop
(WinSta0\\AIMVR_Sandbox) without interfering with user interaction.
"""

import argparse
import sys
import time
from typing import List, Dict, Any, Optional
from PIL import Image

from PySide2 import QtCore, QtGui, QtWidgets
from control.virtual_desktop import default_virtual_desktop


class CaptureThread(QtCore.QThread):
    """Background polling thread capturing sandbox window buffers."""
    frame_ready = QtCore.Signal(object, list)

    def __init__(self, fps: int = 10, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.fps = max(1, min(fps, 30))
        self._running = True

    def run(self):
        default_virtual_desktop.ensure_sandbox()
        interval = 1.0 / self.fps
        while self._running:
            t0 = time.perf_counter()
            try:
                canvas, windows = default_virtual_desktop.capture_pip_canvas(
                    canvas_width=1920,
                    canvas_height=1080
                )
                self.frame_ready.emit(canvas, windows)
            except Exception as e:
                sys.stderr.write(f"[PiPViewer] Capture error: {e}\n")

            elapsed = time.perf_counter() - t0
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    def stop(self):
        self._running = False
        self.wait(1500)


class FloatingPipWindow(QtWidgets.QWidget):
    """Always-On-Top floating Picture-in-Picture preview window."""

    def __init__(
        self,
        fps: int = 10,
        width: int = 480,
        height: int = 270,
        opacity: float = 0.95,
    ):
        super().__init__()
        self.fps = fps
        self.aspect_ratio = 16.0 / 9.0
        self._last_pixmap: Optional[QtGui.QPixmap] = None

        self.setWindowTitle("AIM-VR Sandbox (Picture-in-Picture)")
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowCloseButtonHint
        )
        self.setWindowOpacity(max(0.2, min(opacity, 1.0)))
        self.resize(width, height)
        self.setMinimumSize(240, 135)

        # Position window in bottom-right corner of primary screen
        primary_screen = QtWidgets.QApplication.primaryScreen()
        if primary_screen:
            geo = primary_screen.availableGeometry()
            pos_x = geo.x() + geo.width() - width - 24
            pos_y = geo.y() + geo.height() - height - 48
            self.move(max(geo.x(), pos_x), max(geo.y(), pos_y))

        # Main UI layout
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Frame viewport
        self.viewport_label = QtWidgets.QLabel(self)
        self.viewport_label.setAlignment(QtCore.Qt.AlignCenter)
        self.viewport_label.setStyleSheet("background-color: #1a1d24; color: #7f8c8d; font-family: Segoe UI, sans-serif; font-size: 12px;")
        self.viewport_label.setText("Connecting to isolated desktop (WinSta0\\AIMVR_Sandbox)...")
        root_layout.addWidget(self.viewport_label, 1)

        # Bottom compact status bar
        self.status_bar = QtWidgets.QWidget(self)
        self.status_bar.setFixedHeight(22)
        self.status_bar.setStyleSheet("background-color: #111317; color: #bdc3c7; font-family: Consolas, monospace; font-size: 11px;")
        status_layout = QtWidgets.QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(8, 0, 8, 0)

        self.status_label = QtWidgets.QLabel("Desktop: AIMVR_Sandbox | Windows: 0", self.status_bar)
        self.fps_label = QtWidgets.QLabel(f"{self.fps} FPS", self.status_bar)
        self.fps_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.fps_label, 0)
        root_layout.addWidget(self.status_bar, 0)

        # Start capture worker thread
        self.worker = CaptureThread(fps=self.fps, parent=self)
        self.worker.frame_ready.connect(self.on_frame_ready)
        self.worker.start()

    def on_frame_ready(self, canvas: Image.Image, windows: List[Dict[str, Any]]):
        if not canvas:
            return

        w, h = canvas.size
        raw_bytes = canvas.tobytes("raw", "RGB")
        qimg = QtGui.QImage(raw_bytes, w, h, w * 3, QtGui.QImage.Format_RGB888)
        self._last_pixmap = QtGui.QPixmap.fromImage(qimg)
        self._render_current_frame()

        win_count = len(windows)
        top_title = f" ('{windows[0]['title'][:18]}...')" if win_count > 0 else ""
        self.status_label.setText(f"Desktop: AIMVR_Sandbox | Windows: {win_count}{top_title}")

    def _render_current_frame(self):
        if not self._last_pixmap:
            return
        target_size = self.viewport_label.size()
        scaled = self._last_pixmap.scaled(
            target_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.viewport_label.setPixmap(scaled)

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        self._render_current_frame()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        menu = QtWidgets.QMenu(self)

        # Opacity actions
        opacity_menu = menu.addMenu("Opacity")
        for val in [100, 90, 75, 50]:
            act = opacity_menu.addAction(f"{val}%")
            act.triggered.connect(lambda checked=False, v=val: self.setWindowOpacity(v / 100.0))

        # Refresh rate actions
        rate_menu = menu.addMenu("Refresh Rate")
        for rate in [5, 10, 15, 20]:
            act = rate_menu.addAction(f"{rate} FPS")
            act.triggered.connect(lambda checked=False, r=rate: self._change_rate(r))

        menu.addSeparator()
        close_act = menu.addAction("Close Viewer")
        close_act.triggered.connect(self.close)
        menu.exec_(event.globalPos())

    def _change_rate(self, new_fps: int):
        self.fps = new_fps
        self.fps_label.setText(f"{self.fps} FPS")
        if self.worker:
            self.worker.fps = new_fps

    def closeEvent(self, event: QtGui.QCloseEvent):
        if self.worker:
            self.worker.stop()
        event.accept()


def parse_cli_args(args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Floating Picture-in-Picture Sandbox Preview Viewer")
    parser.add_argument("--fps", type=int, default=10, help="Refresh frame rate (default: 10 FPS)")
    parser.add_argument("--width", type=int, default=480, help="Window initial width in pixels (default: 480)")
    parser.add_argument("--height", type=int, default=270, help="Window initial height in pixels (default: 270)")
    parser.add_argument("--opacity", type=float, default=0.95, help="Window opacity between 0.2 and 1.0 (default: 0.95)")
    parsed, _ = parser.parse_known_args(args)
    return parsed


def main(argv: Optional[List[str]] = None):
    args = parse_cli_args(argv)
    app = QtWidgets.QApplication.instance()
    owns_app = False
    if not app:
        app = QtWidgets.QApplication(sys.argv)
        owns_app = True

    viewer = FloatingPipWindow(
        fps=args.fps,
        width=args.width,
        height=args.height,
        opacity=args.opacity,
    )
    viewer.show()

    if owns_app:
        sys.exit(app.exec_())
    return viewer


if __name__ == "__main__":
    main()

