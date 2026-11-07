from __future__ import annotations

import http.client
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QMessageBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)


HOST = "speed.cloudflare.com"
DOWNLOAD_BYTES = 25_000_000
UPLOAD_BYTES = 10_000_000
CHUNK_SIZE = 64 * 1024
REQUEST_TIMEOUT = 10
UPDATE_INTERVAL = 0.2
HEADERS = {
    "User-Agent": "SpeedTest/1.0",
    "Accept-Encoding": "identity",
}


class TestCancelled(Exception):
    pass


def connection_quality(download_mbps: float, latency_ms: float) -> str:
    if download_mbps < 5 or latency_ms >= 200:
        return "Slow connection"
    if download_mbps >= 100 and latency_ms < 40:
        return "Very fast connection"
    if download_mbps >= 25:
        return "Good connection"
    return "Limited connection"


def format_speed(mbps: float) -> str:
    return f"{mbps:,.1f}"


class SpeedTestWorker(QObject):
    status_changed = Signal(str)
    progress_changed = Signal(str, float, int)
    metric_changed = Signal(str, float)
    completed = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()

    @Slot()
    def run(self) -> None:
        try:
            latency = self._measure_latency()
            self.metric_changed.emit("latency", latency)
            self.status_changed.emit("Downloading")
            download = self._measure_transfer("GET", DOWNLOAD_BYTES)
            self.metric_changed.emit("download", download)
            self.status_changed.emit("Uploading")
            upload = self._measure_transfer("POST", UPLOAD_BYTES)
            self.metric_changed.emit("upload", upload)
            self.completed.emit(
                {"latency": latency, "download": download, "upload": upload}
            )
        except TestCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"Speed test failed: {exc}")

    def _check_cancelled(self) -> None:
        if QThread.currentThread().isInterruptionRequested():
            raise TestCancelled

    def _measure_latency(self) -> float:
        self.status_changed.emit("Checking latency")
        connection = http.client.HTTPSConnection(HOST, timeout=REQUEST_TIMEOUT)
        try:
            connection.request("GET", "/__down?bytes=1", headers=HEADERS)
            warmup = connection.getresponse()
            if warmup.status >= 400:
                raise RuntimeError(f"Speed test service returned HTTP {warmup.status}")
            warmup.read()

            samples = []
            for index in range(3):
                self._check_cancelled()
                started = time.perf_counter()
                connection.request("GET", "/__down?bytes=0", headers=HEADERS)
                response = connection.getresponse()
                response.read()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Speed test service returned HTTP {response.status}"
                    )
                samples.append((time.perf_counter() - started) * 1000)
                self.metric_changed.emit("latency", sum(samples) / len(samples))
                self.status_changed.emit(f"Checking latency ({index + 1}/3)")
            return sum(samples) / len(samples)
        finally:
            connection.close()

    def _measure_transfer(self, method: str, expected_bytes: int) -> float:
        phase = "DOWNLOAD" if method == "GET" else "UPLOAD"
        started = time.perf_counter()
        last_update = started
        last_bytes = 0
        transferred = 0
        connection = http.client.HTTPSConnection(HOST, timeout=REQUEST_TIMEOUT)
        try:
            if method == "GET":
                connection.request(
                    "GET", f"/__down?bytes={expected_bytes}", headers=HEADERS
                )
                response = connection.getresponse()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Speed test service returned HTTP {response.status}"
                    )
                while True:
                    self._check_cancelled()
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    transferred += len(chunk)
                    last_update, last_bytes = self._emit_progress(
                        phase, transferred, expected_bytes, last_update, last_bytes
                    )
                if transferred != expected_bytes:
                    raise RuntimeError(
                        f"Download ended after {transferred:,} of "
                        f"{expected_bytes:,} bytes"
                    )
            else:
                connection.putrequest("POST", "/__up")
                for name, value in HEADERS.items():
                    connection.putheader(name, value)
                connection.putheader("Content-Type", "application/octet-stream")
                connection.putheader("Content-Length", str(expected_bytes))
                connection.endheaders()
                block = b"\0" * CHUNK_SIZE
                while transferred < expected_bytes:
                    self._check_cancelled()
                    amount = min(CHUNK_SIZE, expected_bytes - transferred)
                    connection.send(block[:amount])
                    transferred += amount
                    last_update, last_bytes = self._emit_progress(
                        phase, transferred, expected_bytes, last_update, last_bytes
                    )
                response = connection.getresponse()
                response.read()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Speed test service returned HTTP {response.status}"
                    )
        finally:
            connection.close()

        duration = max(time.perf_counter() - started, 0.001)
        return transferred * 8 / duration / 1_000_000

    def _emit_progress(
        self,
        phase: str,
        transferred: int,
        expected_bytes: int,
        last_update: float,
        last_bytes: int,
    ) -> tuple[float, int]:
        now = time.perf_counter()
        if now - last_update >= UPDATE_INTERVAL or transferred >= expected_bytes:
            elapsed = max(now - last_update, 0.001)
            mbps = (transferred - last_bytes) * 8 / elapsed / 1_000_000
            percent = min(100, int(transferred * 100 / expected_bytes))
            self.progress_changed.emit(phase, mbps, percent)
            return now, transferred
        return last_update, last_bytes


class SpeedTestWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Speed Test")
        self.setFixedSize(410, 390)
        self._thread: QThread | None = None
        self._worker: SpeedTestWorker | None = None
        self._tray: QSystemTrayIcon | None = None
        self._quit_after_test = False

        self._build_ui()
        self._set_ready_state()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0b0b0b; color: #ffffff; }
            QLabel { color: #ffffff; background: transparent; }
            QFrame#readout {
                background: #151515;
                border: 1px solid #3a3a3a;
            }
            QFrame#readout QLabel { color: #ffffff; }
            QProgressBar {
                background: #242424;
                border: 1px solid #555555;
                min-height: 5px;
                max-height: 5px;
                text-align: center;
            }
            QProgressBar::chunk { background: #ffffff; }
            QPushButton {
                background: #202020;
                color: #ffffff;
                border: 1px solid #555555;
                min-height: 46px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover { background: #333333; }
            QPushButton:focus { border: 2px solid #ffffff; }
            QPushButton:disabled { color: #888888; border-color: #444444; }
            """
        )

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(15)

        heading = QHBoxLayout()
        title = QLabel("Speed test")
        title.setFont(QFont("Segoe UI", 19, QFont.Weight.Bold))
        heading.addWidget(title)
        heading.addStretch()
        self.connection_label = QLabel("READY")
        self.connection_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        heading.addWidget(self.connection_label)
        layout.addLayout(heading)

        readout = QFrame()
        readout.setObjectName("readout")
        readout_layout = QVBoxLayout(readout)
        readout_layout.setContentsMargins(17, 15, 17, 14)
        readout_layout.setSpacing(7)
        metric_row = QHBoxLayout()
        self.metric_label = QLabel("---")
        self.metric_label.setFont(QFont("Segoe UI", 52, QFont.Weight.Bold))
        self.metric_label.setMinimumWidth(280)
        self.unit_label = QLabel("Mb/s")
        self.unit_label.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self.unit_label.setAlignment(Qt.AlignmentFlag.AlignBottom)
        metric_row.addWidget(self.metric_label)
        metric_row.addWidget(self.unit_label)
        metric_row.addStretch()
        readout_layout.addLayout(metric_row)

        self.phase_label = QLabel("Click the tray icon to begin")
        self.phase_label.setFont(QFont("Segoe UI", 10))
        readout_layout.addWidget(self.phase_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        readout_layout.addWidget(self.progress)
        layout.addWidget(readout)

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 1, 0, 1)
        stats.setSpacing(0)
        self.stat_values: dict[str, QLabel] = {}
        for index, (key, label, unit) in enumerate(
            (
                ("download", "DOWNLOAD", "Mb/s"),
                ("upload", "UPLOAD", "Mb/s"),
                ("latency", "PING", "ms"),
            )
        ):
            if index:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setStyleSheet("color: #3a3a3a;")
                stats.addWidget(separator)
            column = QVBoxLayout()
            column.setContentsMargins(10, 0, 10, 0)
            column.setSpacing(3)
            caption = QLabel(label)
            caption.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            value = QLabel(f"-- {unit}")
            value.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
            column.addWidget(caption)
            column.addWidget(value)
            stats.addLayout(column, 1)
            self.stat_values[key] = value
        layout.addLayout(stats)

        self.detail_label = QLabel("No background testing or monitoring")
        self.detail_label.setFont(QFont("Segoe UI", 9))
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.action_button = QPushButton("Start test")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.clicked.connect(self._toggle_test)
        layout.addWidget(self.action_button)

        self.setCentralWidget(central)

    def set_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def _set_ready_state(self) -> None:
        self.connection_label.setText("READY")
        self.metric_label.setText("---")
        self.unit_label.setText("Mb/s")
        self.phase_label.setText("Click the tray icon to begin")
        self.progress.setValue(0)
        self.detail_label.setText("No background testing or monitoring")
        self.action_button.setText("Start test")

    @Slot()
    def _toggle_test(self) -> None:
        if self._thread is not None:
            self._thread.requestInterruption()
            self.action_button.setText("Stopping…")
            self.action_button.setEnabled(False)
            self.phase_label.setText("Stopping test")
            return
        self._start_test()

    def _start_test(self) -> None:
        self.connection_label.setText("TESTING")
        self.metric_label.setText("0.0")
        self.unit_label.setText("Mb/s")
        self.phase_label.setText("Checking latency")
        self.progress.setValue(0)
        self.detail_label.setText("By Hiroshi Kelner")
        self.action_button.setText("Cancel test")
        self.action_button.setEnabled(True)
        if self._tray is not None:
            self._tray.setToolTip("Speed Test · test running")
        for key, unit in (("download", "Mb/s"), ("upload", "Mb/s"), ("latency", "ms")):
            self.stat_values[key].setText(f"-- {unit}")

        self._thread = QThread(self)
        self._worker = SpeedTestWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self._on_status)
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.metric_changed.connect(self._on_metric)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    @Slot(str)
    def _on_status(self, status: str) -> None:
        self.phase_label.setText(status)

    @Slot(str, float, int)
    def _on_progress(self, phase: str, mbps: float, percent: int) -> None:
        self.metric_label.setText(format_speed(mbps))
        self.phase_label.setText("Downloading" if phase == "DOWNLOAD" else "Uploading")
        self.progress.setValue(percent)

    @Slot(str, float)
    def _on_metric(self, key: str, value: float) -> None:
        unit = "ms" if key == "latency" else "Mb/s"
        formatted = f"{value:.0f}" if key == "latency" else format_speed(value)
        self.stat_values[key].setText(f"{formatted} {unit}")

    @Slot(dict)
    def _on_completed(self, result: dict) -> None:
        download = result["download"]
        upload = result["upload"]
        latency = result["latency"]
        quality = connection_quality(download, latency)

        self.connection_label.setText(quality.upper())
        self.metric_label.setText(format_speed(download))
        self.phase_label.setText("Test complete")
        self.progress.setValue(100)
        self.stat_values["download"].setText(f"{format_speed(download)} Mb/s")
        self.stat_values["upload"].setText(f"{format_speed(upload)} Mb/s")
        self.stat_values["latency"].setText(f"{latency:.0f} ms")
        self.detail_label.setText(quality)
        self.action_button.setText("Run again")

        if self._tray is not None:
            self._tray.setToolTip(
                f"Speed Test · {quality} · ↓ {format_speed(download)} Mb/s "
                f"↑ {format_speed(upload)} Mb/s"
            )

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.connection_label.setText("TEST FAILED")
        self.phase_label.setText("Could not complete the test")
        self.detail_label.setText(message)
        self.action_button.setText("Try again")
        if self._tray is not None:
            self._tray.setToolTip("Speed Test · test failed, click to retry")

    @Slot()
    def _on_cancelled(self) -> None:
        self.connection_label.setText("CANCELLED")
        self.phase_label.setText("Test cancelled")
        self.detail_label.setText("No result was saved")
        self.action_button.setText("Start test")
        if self._tray is not None:
            self._tray.setToolTip("Speed Test · test cancelled, click to run")

    @Slot()
    def _on_thread_finished(self) -> None:
        self._worker = None
        self._thread = None
        self.action_button.setEnabled(True)
        if self._quit_after_test:
            QApplication.quit()

    def start_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        if self._thread is None:
            self._start_test()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def quit_application(self) -> None:
        if self._thread is not None:
            self._quit_after_test = True
            self._thread.requestInterruption()
            self.action_button.setEnabled(False)
            self.phase_label.setText("Stopping before exit")
        else:
            QApplication.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Speed Test")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0b0b0b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111111"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#191919"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111111"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#888888"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#888888"),
    )
    app.setPalette(palette)

    icon_path = Path(__file__).with_name("icon.svg")
    icon = QIcon(str(icon_path))
    window = SpeedTestWindow()
    window.setWindowIcon(icon)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Speed Test — click to run a test")
    menu = QMenu()
    menu.setStyleSheet(
        """
        QMenu {
            background: #111111;
            color: #ffffff;
            border: 1px solid #444444;
            padding: 4px;
        }
        QMenu::item { padding: 7px 24px; }
        QMenu::item:selected { background: #333333; }
        QMenu::separator {
            height: 1px;
            background: #444444;
            margin: 4px 8px;
        }
        """
    )
    test_action = QAction("Run speed test", menu)
    test_action.triggered.connect(window.start_from_tray)
    show_action = QAction("Show results", menu)
    show_action.triggered.connect(window.show)
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(window.quit_application)
    menu.addAction(test_action)
    menu.addAction(show_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.start_from_tray()
        if reason
        in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        )
        else None
    )
    window.set_tray(tray)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
    else:
        window.show()
        window.detail_label.setText("System tray unavailable — use this window")

    stop_file = Path(__file__).with_name("stop.txt")
    if not stop_file.exists():
        help_dialog = QMessageBox(QMessageBox.Icon.Information, "How to use Speed Test", "Click the Speed Test icon in the system tray to start a speed test. Right-click the icon to show results or quit.")
        stop_button = help_dialog.addButton("Don't show this again", QMessageBox.ButtonRole.ActionRole)
        help_dialog.addButton(QMessageBox.StandardButton.Ok)
        help_dialog.exec()
        if help_dialog.clickedButton() is stop_button:
            stop_file.touch()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
