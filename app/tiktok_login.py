import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.session_manager import (
    SESSION_STATE_FILE,
    ensure_app_data_dir,
    has_session,
)


class TikTokLoginWorker(QObject):
    """
    Chay Playwright trong QThread rieng.

    Quan trong:
    - Khong dong dialog ngay khi vua bam "Hoan tat dang nhap".
    - Worker se luu session, dong browser/context xong truoc.
    - Sau do GUI moi dong popup dang nhap.

    Cach nay tranh tinh trang QThread/browser van dang shutdown ma dialog
    bi huy som, co the lam ung dung macOS thoat dot ngot.
    """

    browser_ready = Signal()
    result_ready = Signal(str, str)

    RESULT_SAVED = "saved"
    RESULT_FAILED = "failed"
    RESULT_CANCELLED = "cancelled"

    def __init__(self):
        super().__init__()
        self._save_event = threading.Event()
        self._cancel_event = threading.Event()

    def request_save(self):
        self._save_event.set()

    def request_cancel(self):
        self._cancel_event.set()

    @Slot()
    def run(self):
        browser = None
        context = None
        result_type = self.RESULT_CANCELLED
        result_message = ""

        try:
            ensure_app_data_dir()

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        channel="chrome",
                        headless=False,
                    )
                except Exception:
                    browser = p.chromium.launch(
                        headless=False,
                    )

                context_kwargs = {
                    "viewport": {
                        "width": 1400,
                        "height": 900,
                    },
                    "locale": "vi-VN",
                    "timezone_id": "Asia/Ho_Chi_Minh",
                }

                if has_session():
                    context_kwargs["storage_state"] = str(
                        SESSION_STATE_FILE
                    )

                context = browser.new_context(
                    **context_kwargs
                )

                page = context.new_page()

                page.goto(
                    "https://www.tiktok.com/login?lang=vi-VN",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                self.browser_ready.emit()

                while True:
                    if self._cancel_event.wait(0.20):
                        result_type = self.RESULT_CANCELLED
                        result_message = ""
                        break

                    if self._save_event.is_set():
                        context.storage_state(
                            path=str(SESSION_STATE_FILE)
                        )

                        if not SESSION_STATE_FILE.exists():
                            raise RuntimeError(
                                "Không lưu được TikTok session."
                            )

                        if SESSION_STATE_FILE.stat().st_size < 20:
                            raise RuntimeError(
                                "File TikTok session được tạo nhưng không có dữ liệu hợp lệ."
                            )

                        result_type = self.RESULT_SAVED
                        result_message = str(
                            SESSION_STATE_FILE
                        )
                        break

                    try:
                        if page.is_closed():
                            raise RuntimeError(
                                "Cửa sổ TikTok đã bị đóng trước khi lưu phiên đăng nhập."
                            )
                    except RuntimeError:
                        raise
                    except Exception:
                        pass

        except Exception as exc:
            result_type = self.RESULT_FAILED
            result_message = (
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            # Dong Playwright xong HOAN TOAN truoc khi bao GUI ket thuc.
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

        # Signal nay duoc gui sau khi browser/context da dong xong.
        self.result_ready.emit(
            result_type,
            result_message,
        )


class LightAlertDialog(QDialog):
    def __init__(
        self,
        parent=None,
        title="Thông báo",
        message="",
        is_error=False,
    ):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setWindowFlag(
            Qt.WindowContextHelpButtonHint,
            False,
        )
        self.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            22,
            22,
            22,
            18,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)

        icon = QLabel(
            "!" if is_error else "i"
        )
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(52, 52)
        icon.setObjectName(
            "alertIconError"
            if is_error
            else "alertIconInfo"
        )

        text_box = QVBoxLayout()
        text_box.setSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName(
            "alertTitle"
        )

        message_label = QLabel(message)
        message_label.setObjectName(
            "alertMessage"
        )
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        text_box.addWidget(title_label)
        text_box.addWidget(message_label)

        header.addWidget(icon)
        header.addLayout(text_box, 1)

        layout.addLayout(header)

        buttons = QHBoxLayout()
        buttons.addStretch()

        ok_button = QPushButton("OK")
        ok_button.setObjectName(
            "alertPrimaryButton"
        )
        ok_button.clicked.connect(
            self.accept
        )
        buttons.addWidget(ok_button)

        layout.addLayout(buttons)

        self.setStyleSheet(
            """
            QDialog {
                background: #f8fafc;
            }

            QLabel {
                background: transparent;
                color: #111827;
                font-family: Arial;
                font-size: 13px;
            }

            QLabel#alertTitle {
                color: #111827;
                font-size: 18px;
                font-weight: 700;
            }

            QLabel#alertMessage {
                color: #475569;
                font-size: 13px;
            }

            QLabel#alertIconError {
                background: #fee2e2;
                color: #dc2626;
                border: 1px solid #fecaca;
                border-radius: 26px;
                font-size: 24px;
                font-weight: 700;
            }

            QLabel#alertIconInfo {
                background: #e0f2fe;
                color: #0369a1;
                border: 1px solid #bae6fd;
                border-radius: 26px;
                font-size: 22px;
                font-weight: 700;
            }

            QPushButton {
                min-height: 36px;
                padding: 0 16px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                background: #ffffff;
                color: #111827;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #f3f4f6;
            }

            QPushButton#alertPrimaryButton {
                background: #03B0B1;
                color: #ffffff;
                border: none;
                min-width: 80px;
                font-weight: 700;
            }

            QPushButton#alertPrimaryButton:hover {
                background: #07989a;
            }
            """
        )


class TikTokLoginDialog(QDialog):
    session_saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(
            "Đăng nhập TikTok"
        )
        self.setModal(True)
        self.resize(700, 330)
        self.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )
        self.setWindowFlag(
            Qt.WindowContextHelpButtonHint,
            False,
        )

        self._finished = False
        self._worker_result = None
        self._worker_message = ""
        self.thread = None
        self.worker = None

        self.setStyleSheet(
            """
            QDialog {
                background: #f8fafc;
            }

            QLabel {
                background: transparent;
                color: #334155;
                font-family: Arial;
                font-size: 13px;
            }

            QLabel#loginTitle {
                color: #111827;
                font-size: 20px;
                font-weight: 700;
            }

            QLabel#loginDescription {
                color: #475569;
                font-size: 13px;
            }

            QLabel#loginStatus {
                padding: 11px 12px;
                background: #f1f5f9;
                color: #334155;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                font-weight: 600;
            }

            QPushButton {
                min-height: 38px;
                padding: 0 16px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                background: #ffffff;
                color: #111827;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #f3f4f6;
            }

            QPushButton:disabled {
                background: #f1f5f9;
                color: #94a3b8;
                border-color: #e2e8f0;
            }

            QPushButton#loginPrimaryButton {
                background: #03B0B1;
                color: #ffffff;
                border: none;
                min-width: 155px;
                font-weight: 700;
            }

            QPushButton#loginPrimaryButton:hover {
                background: #07989a;
            }

            QPushButton#loginPrimaryButton:disabled {
                background: #99dfe0;
                color: #f8fafc;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )
        layout.setSpacing(14)

        title = QLabel(
            "Đăng nhập TikTok cho máy này"
        )
        title.setObjectName(
            "loginTitle"
        )

        description = QLabel(
            "Tool sẽ mở một cửa sổ TikTok riêng. "
            "Hãy đăng nhập tài khoản TikTok của bạn trong cửa sổ đó.\n\n"
            "Mật khẩu không được nhập vào tool và tool không lưu mật khẩu. "
            "Sau khi TikTok đã đăng nhập xong, quay lại cửa sổ này và bấm "
            "'Hoàn tất đăng nhập'."
        )
        description.setObjectName(
            "loginDescription"
        )
        description.setWordWrap(True)
        description.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        self.status_label = QLabel(
            "Đang mở TikTok..."
        )
        self.status_label.setObjectName(
            "loginStatus"
        )
        self.status_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.status_label)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.cancel_button = QPushButton(
            "Hủy"
        )
        self.finish_button = QPushButton(
            "Hoàn tất đăng nhập"
        )
        self.finish_button.setEnabled(False)
        self.finish_button.setObjectName(
            "loginPrimaryButton"
        )

        self.cancel_button.clicked.connect(
            self.cancel_login
        )
        self.finish_button.clicked.connect(
            self.finish_login
        )

        buttons.addWidget(
            self.cancel_button
        )
        buttons.addWidget(
            self.finish_button
        )
        layout.addLayout(buttons)

        self.start_login_worker()

    def start_login_worker(self):
        self.thread = QThread(self)
        self.worker = TikTokLoginWorker()
        self.worker.moveToThread(
            self.thread
        )

        self.thread.started.connect(
            self.worker.run
        )

        self.worker.browser_ready.connect(
            self.on_browser_ready
        )
        self.worker.result_ready.connect(
            self.on_worker_result
        )

        # Chi yeu cau QThread ket thuc SAU KHI worker da dong browser xong
        # va gui result_ready.
        self.worker.result_ready.connect(
            self.thread.quit
        )

        self.thread.finished.connect(
            self.on_worker_thread_finished
        )
        self.thread.finished.connect(
            self.thread.deleteLater
        )

        self.thread.start()

    @Slot()
    def on_browser_ready(self):
        self.status_label.setText(
            "TikTok đã mở. Hãy đăng nhập trong cửa sổ trình duyệt, "
            "sau đó quay lại đây và bấm 'Hoàn tất đăng nhập'."
        )
        self.status_label.setStyleSheet(
            "padding:11px 12px;"
            "background:#ecfdf5;"
            "color:#047857;"
            "border:1px solid #a7f3d0;"
            "border-radius:8px;"
            "font-weight:600;"
        )
        self.finish_button.setEnabled(True)

    @Slot(str, str)
    def on_worker_result(
        self,
        result_type,
        message,
    ):
        # KHONG dong dialog o day.
        # Cho QThread finished truoc de tranh crash/thoat app tren macOS.
        self._worker_result = result_type
        self._worker_message = message

        self.finish_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

        if result_type == TikTokLoginWorker.RESULT_SAVED:
            self.status_label.setText(
                "Đã lưu TikTok Session. Đang hoàn tất..."
            )
        elif result_type == TikTokLoginWorker.RESULT_CANCELLED:
            self.status_label.setText(
                "Đang đóng cửa sổ đăng nhập..."
            )
        else:
            self.status_label.setText(
                "Không lưu được TikTok Session. Đang hoàn tất..."
            )

    @Slot()
    def on_worker_thread_finished(self):
        # Luc nay browser/context da dong va QThread da dung hoan toan.
        result_type = self._worker_result
        message = self._worker_message

        self.worker = None
        self.thread = None
        self._finished = True

        if result_type == TikTokLoginWorker.RESULT_SAVED:
            self.session_saved.emit()
            self.accept()
            return

        if result_type == TikTokLoginWorker.RESULT_FAILED:
            dialog = LightAlertDialog(
                parent=self,
                title="Không lưu được TikTok Session",
                message=message,
                is_error=True,
            )
            dialog.exec()
            self.reject()
            return

        self.reject()

    def finish_login(self):
        if not self.worker:
            return

        self.finish_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.status_label.setText(
            "Đang lưu TikTok Session và đóng trình duyệt..."
        )
        self.status_label.setStyleSheet(
            "padding:11px 12px;"
            "background:#eff6ff;"
            "color:#1d4ed8;"
            "border:1px solid #bfdbfe;"
            "border-radius:8px;"
            "font-weight:600;"
        )

        self.worker.request_save()

    def cancel_login(self):
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.finish_button.setEnabled(False)
            self.status_label.setText(
                "Đang đóng cửa sổ TikTok..."
            )
            self.worker.request_cancel()
            return

        self._finished = True
        self.reject()

    def closeEvent(self, event):
        if self._finished:
            event.accept()
            return

        if self.worker:
            self.finish_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.worker.request_cancel()
            self.status_label.setText(
                "Đang đóng cửa sổ TikTok..."
            )
            event.ignore()
            return

        event.accept()
