import asyncio
import sys

import app.runtime_env  # noqa: F401 - Configure macOS bundled Playwright path
from time import perf_counter

from PySide6.QtCore import (
    QObject,
    QThread,
    Qt,
    Signal,
    Slot,
    QUrl,
)

from PySide6.QtGui import (
    QColor,
    QBrush,
    QDesktopServices,
)

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.collectors.tiktok_batch import (
    TikTokBatchCollector,
    RETRYABLE_STATUSES,
)

from app.models import TikTokProfileResult

from app.utils.url_parser import (
    parse_tiktok_url,
    parse_tiktok_channel_input,
    deduplicate_channel_inputs,
    TikTokChannelInput,
)

from app.collectors.tiktok_profile_batch import (
    TikTokProfileBatchCollector,
    PROFILE_RETRYABLE_STATUSES,
)


from app.utils.profile_excel import (
    export_profile_excel,
    format_profile_status,
)

from run_batch import (
    deduplicate_urls,
    export_excel,
    status_label,
    get_export_dir,
)


from app.session_manager import (
    SESSION_STATE_FILE,
    SESSION_READY,
    SESSION_MISSING,
    SESSION_INVALID,
    SESSION_EXPIRED,
    SESSION_UNKNOWN,
    check_session_live,
    delete_session,
    has_session,
    inspect_session_local,
    migrate_legacy_session,
)

from app.tiktok_login import (
    TikTokLoginDialog,
)


# ============================================================
# CONFIG
# ============================================================

STATE_FILE = SESSION_STATE_FILE

CONCURRENCY = 3

RETRY_CONCURRENCY = 1

START_INTERVAL = 0.45

RETRY_START_INTERVAL = 1.0

COOLDOWN_403 = 12.0

RETRY_DELAY = 6.0


# ============================================================
# HELPERS
# ============================================================

def format_number(
    value,
):
    if value is None:
        return "-"

    try:
        return f"{int(value):,}".replace(
            ",",
            ".",
        )
    except Exception:
        return str(value)


def calculate_engagement(
    result,
):
    view = result.get(
        "view"
    )

    if not view:
        return None

    value = (
        (
            (result.get("like") or 0)
            + (result.get("comment") or 0)
            + (result.get("share") or 0)
        )
        / view
        * 100
    )

    return value


def is_retryable_status(
    status,
):
    if status in RETRYABLE_STATUSES:
        return True

    if status.startswith(
        "LOI:"
    ):
        return True

    return False


def display_status_label(
    status,
):
    if status == "SESSION_HET_HAN":
        return "TikTok Session hết hạn"

    if status == "CHUA_DANG_NHAP_TIKTOK":
        return "Chưa đăng nhập TikTok"

    return status_label(
        status
    )


# ============================================================
# COLLECTOR CO CALLBACK CHO GUI
#
# Khong sua collector goc.
# Ta ke thua TikTokBatchCollector va bat ket qua tung link.
# ============================================================

class GuiTikTokCollector(
    TikTokBatchCollector
):

    def __init__(
        self,
        result_callback,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        self.result_callback = (
            result_callback
        )

    async def collect_one(
        self,
        *args,
        **kwargs,
    ):
        retry_mode = (
            kwargs.get(
                "retry_mode",
                False,
            )
        )

        result = (
            await super().collect_one(
                *args,
                **kwargs,
            )
        )

        try:
            self.result_callback(
                result,
                retry_mode,
            )
        except Exception:
            pass

        return result


# ============================================================
# WORKER CHAY O THREAD RIENG
#
# Neu chay collector ngay tren GUI thread,
# giao dien se bi treo.
# ============================================================

class CollectorWorker(
    QObject
):

    result_ready = Signal(
        object,
        bool,
    )

    finished = Signal(
        object
    )

    failed = Signal(
        str
    )

    def __init__(
        self,
        urls,
    ):
        super().__init__()

        self.urls = urls

    def emit_result(
        self,
        result,
        retry_mode,
    ):
        self.result_ready.emit(
            result.to_dict(),
            retry_mode,
        )

    async def run_async(
        self,
    ):
        collector = (
            GuiTikTokCollector(
                result_callback=(
                    self.emit_result
                ),

                concurrency=(
                    CONCURRENCY
                ),

                retry_concurrency=(
                    RETRY_CONCURRENCY
                ),

                start_interval=(
                    START_INTERVAL
                ),

                retry_start_interval=(
                    RETRY_START_INTERVAL
                ),

                cooldown_403=(
                    COOLDOWN_403
                ),

                retry_delay=(
                    RETRY_DELAY
                ),

                headless=True,
            )
        )

        start = perf_counter()

        results = (
            await collector.collect_many(
                self.urls
            )
        )

        elapsed = (
            perf_counter()
            - start
        )

        return {
            "results": results,
            "elapsed": elapsed,
        }

    @Slot()
    def run(
        self,
    ):
        try:
            payload = asyncio.run(
                self.run_async()
            )

            self.finished.emit(
                payload
            )

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: "
                f"{exc}"
            )


# ============================================================
# PROFILE WORKER CHAY O THREAD RIENG
# ============================================================

class ProfileCollectorWorker(
    QObject
):

    result_ready = Signal(
        object,
        bool,
    )

    finished = Signal(
        object
    )

    failed = Signal(
        str
    )

    def __init__(
        self,
        channels: list[TikTokChannelInput],
    ):
        super().__init__()
        self.channels = channels
        self.collector = None

    def cancel(self):
        if self.collector is not None:
            self.collector.cancel()

    def emit_result(
        self,
        result: TikTokProfileResult,
        retry_mode: bool,
    ):
        self.result_ready.emit(
            result.to_dict(),
            retry_mode,
        )

    async def run_async(
        self,
    ):
        self.collector = TikTokProfileBatchCollector(
            concurrency=2,
            retry_concurrency=1,
            start_interval=0.5,
            retry_start_interval=1.2,
            cooldown_403=12.0,
            retry_delay=5.0,
            headless=True,
            result_callback=self.emit_result,
        )

        start = perf_counter()

        results = await self.collector.collect_many(
            self.channels
        )

        elapsed = perf_counter() - start

        return {
            "results": results,
            "elapsed": elapsed,
        }

    @Slot()
    def run(
        self,
    ):
        try:
            payload = asyncio.run(
                self.run_async()
            )

            self.finished.emit(
                payload
            )

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


# ============================================================
# SESSION CHECK WORKER
# ============================================================


class SessionCheckWorker(
    QObject
):

    finished = Signal(
        str,
        str,
    )

    failed = Signal(
        str
    )

    @Slot()
    def run(
        self,
    ):
        try:
            status, message = (
                check_session_live()
            )

            self.finished.emit(
                status,
                message,
            )

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


# ============================================================
# KPI CARD
# ============================================================

class StatCard(
    QFrame
):

    def __init__(
        self,
        title,
        value="0",
    ):
        super().__init__()

        self.setObjectName(
            "statCard"
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            16,
            12,
            16,
            12,
        )

        layout.setSpacing(
            4
        )

        self.title_label = QLabel(
            title
        )

        self.title_label.setObjectName(
            "statTitle"
        )

        self.value_label = QLabel(
            value
        )

        self.value_label.setObjectName(
            "statValue"
        )

        layout.addWidget(
            self.title_label
        )

        layout.addWidget(
            self.value_label
        )

    def set_value(
        self,
        value,
    ):
        self.value_label.setText(
            str(value)
        )


# ============================================================
# EXPORT RESULT DIALOG
# ============================================================

class ExportResultDialog(
    QDialog
):

    def __init__(
        self,
        parent,
        title,
        message,
        file_path=None,
        is_error=False,
    ):
        super().__init__(parent)

        self.file_path = file_path

        self.setModal(True)
        self.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )
        self.setWindowTitle(title)
        self.setMinimumWidth(580)
        self.setWindowFlag(
            Qt.WindowContextHelpButtonHint,
            False,
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            24,
            22,
            24,
            20,
        )

        layout.setSpacing(
            16
        )

        header = QHBoxLayout()
        header.setSpacing(14)

        self.icon_label = QLabel(
            "!" if is_error else "✓"
        )

        self.icon_label.setAlignment(
            Qt.AlignCenter
        )

        self.icon_label.setFixedSize(
            58,
            58,
        )

        self.icon_label.setObjectName(
            "exportErrorIcon"
            if is_error
            else "exportSuccessIcon"
        )

        text_wrap = QVBoxLayout()
        text_wrap.setSpacing(5)

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "exportDialogTitle"
        )

        message_label = QLabel(
            message
        )

        message_label.setObjectName(
            "exportDialogMessage"
        )

        message_label.setWordWrap(
            True
        )

        text_wrap.addWidget(
            title_label
        )

        text_wrap.addWidget(
            message_label
        )

        header.addWidget(
            self.icon_label
        )

        header.addLayout(
            text_wrap,
            1,
        )

        layout.addLayout(
            header
        )

        if self.file_path:

            path_title = QLabel(
                "Đường dẫn file"
            )

            path_title.setObjectName(
                "exportPathTitle"
            )

            layout.addWidget(
                path_title
            )

            self.path_box = QPlainTextEdit()

            self.path_box.setReadOnly(
                True
            )

            self.path_box.setPlainText(
                str(
                    self.file_path.resolve()
                )
            )

            self.path_box.setFixedHeight(
                76
            )

            self.path_box.setObjectName(
                "exportPathBox"
            )

            layout.addWidget(
                self.path_box
            )

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()

        if self.file_path:

            copy_button = QPushButton(
                "Sao chép đường dẫn"
            )

            copy_button.clicked.connect(
                self.copy_path
            )

            buttons.addWidget(
                copy_button
            )

            folder_button = QPushButton(
                "Mở thư mục"
            )

            folder_button.setObjectName(
                "exportPrimaryButton"
            )

            folder_button.clicked.connect(
                self.open_folder
            )

            buttons.addWidget(
                folder_button
            )

        ok_button = QPushButton(
            "OK"
        )

        ok_button.setObjectName(
            "exportPrimaryButton"
        )

        ok_button.clicked.connect(
            self.accept
        )

        buttons.addWidget(
            ok_button
        )

        layout.addLayout(
            buttons
        )

        self.setStyleSheet(
            """
            QDialog {
                background: #f8fafc;
            }

            QLabel {
                background: transparent;
                color: #111827;
            }

            QLabel {
                color: #111827;
                font-family: Arial;
                font-size: 13px;
            }

            QLabel#exportDialogTitle {
                color: #0f172a;
                font-size: 19px;
                font-weight: 700;
            }

            QLabel#exportDialogMessage {
                color: #475569;
                font-size: 13px;
            }

            QLabel#exportPathTitle {
                color: #334155;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#exportSuccessIcon {
                background: #dcfce7;
                color: #15803d;
                border: 1px solid #bbf7d0;
                border-radius: 29px;
                font-size: 29px;
                font-weight: 700;
            }

            QLabel#exportErrorIcon {
                background: #fee2e2;
                color: #dc2626;
                border: 1px solid #fecaca;
                border-radius: 29px;
                font-size: 28px;
                font-weight: 700;
            }

            QPlainTextEdit#exportPathBox {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #d1d5db;
                border-radius: 9px;
                padding: 9px;
                selection-background-color: #bceff0;
                selection-color: #111827;
            }

            QPushButton {
                min-height: 36px;
                padding: 0 14px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                background: #ffffff;
                color: #111827;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #f3f4f6;
            }

            QPushButton#exportPrimaryButton {
                background: #03B0B1;
                color: #ffffff;
                border: none;
                padding: 0 18px;
                font-weight: 700;
            }

            QPushButton#exportPrimaryButton:hover {
                background: #07989a;
            }
            """
        )

    def copy_path(
        self,
    ):
        if not self.file_path:
            return

        QApplication.clipboard().setText(
            str(
                self.file_path.resolve()
            )
        )

    def open_folder(
        self,
    ):
        if not self.file_path:
            return

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(
                str(
                    self.file_path.parent.resolve()
                )
            )
        )


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(
    QMainWindow
):

    def __init__(
        self,
    ):
        super().__init__()

        self.setWindowTitle(
            "TikTok Video Performance Tool"
        )

        self.resize(
            1500,
            900,
        )

        self.thread = None
        self.worker = None

        self.session_check_thread = None
        self.session_check_worker = None
        self.session_status = SESSION_MISSING
        self.session_message = ""

        # Giu reference popup dang nhap de tranh bi huy khi worker/QThread
        # van dang dong Playwright tren macOS.
        self.login_dialog = None

        self.is_running = False

        self.unique_urls = []

        self.duplicate_urls = []

        self.original_count = 0

        self.row_by_url = {}

        self.latest_status = {}

        self.finalized_urls = set()

        self.last_results = []

        self.last_elapsed = 0

        # Profile tab state
        self.profile_thread = None
        self.profile_worker = None
        self.is_profile_running = False
        self.profile_unique_items = []
        self.profile_duplicate_urls = []
        self.profile_original_count = 0
        self.profile_row_by_key = {}
        self.profile_latest_status = {}
        self.profile_finalized_keys = set()
        self.profile_last_results = []
        self.profile_last_elapsed = 0

        # Chuyen session cu sang thu muc rieng cua user (chi 1 lan).
        migrate_legacy_session()

        self.build_ui()

        self.apply_style()

        self.update_session_status()

        self.start_session_check()

        self.update_input_counter()

        self.update_profile_input_counter()


    # ========================================================
    # UI
    # ========================================================

    def build_ui(
        self,
    ):
        central = QWidget()

        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(
            central
        )

        main_layout.setContentsMargins(
            22,
            18,
            22,
            18,
        )

        main_layout.setSpacing(
            14
        )

        # ====================================================
        # HEADER
        # ====================================================

        header = QHBoxLayout()

        title_box = QVBoxLayout()

        title = QLabel(
            "TikTok Video Performance"
        )

        title.setObjectName(
            "mainTitle"
        )

        subtitle = QLabel(
            "Paste danh sách video TikTok và lấy "
            "View / Like / Comment / Share / Save"
        )

        subtitle.setObjectName(
            "subtitle"
        )

        title_box.addWidget(
            title
        )

        title_box.addWidget(
            subtitle
        )

        header.addLayout(
            title_box
        )

        header.addStretch()

        self.session_label = QLabel()

        self.session_label.setObjectName(
            "sessionLabel"
        )

        header.addWidget(
            self.session_label
        )

        self.login_button = QPushButton(
            "Đăng nhập TikTok"
        )

        self.login_button.clicked.connect(
            self.open_tiktok_login
        )

        header.addWidget(
            self.login_button
        )

        main_layout.addLayout(
            header
        )

        # ====================================================
        # TABS
        # ====================================================

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        self.tab_videos = self.build_video_tab()
        self.tabs.addTab(
            self.tab_videos,
            "Hiệu suất video",
        )

        self.tab_profiles = self.build_profile_tab()
        self.tabs.addTab(
            self.tab_profiles,
            "Thông tin kênh TikTok",
        )

        main_layout.addWidget(
            self.tabs,
            1,
        )

    # ========================================================
    # TAB 1: VIDEO PERFORMANCE (GIU NGUYEN 100%)
    # ========================================================

    def build_video_tab(
        self,
    ) -> QWidget:
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(12)

        # ====================================================
        # KPI
        # ====================================================

        cards = QHBoxLayout()


        cards.setSpacing(
            10
        )

        self.card_input = StatCard(
            "URL đã nhập"
        )

        self.card_processed = StatCard(
            "Đã xử lý"
        )

        self.card_success = StatCard(
            "Có dữ liệu"
        )

        self.card_other = StatCard(
            "Không lấy được"
        )

        cards.addWidget(
            self.card_input
        )

        cards.addWidget(
            self.card_processed
        )

        cards.addWidget(
            self.card_success
        )

        cards.addWidget(
            self.card_other
        )

        layout.addLayout(
            cards
        )

        # ====================================================
        # SPLITTER
        # ====================================================

        splitter = QSplitter(
            Qt.Vertical
        )

        # ====================================================
        # INPUT AREA
        # ====================================================

        input_frame = QFrame()

        input_frame.setObjectName(
            "panel"
        )

        input_layout = QVBoxLayout(
            input_frame
        )

        input_layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )

        input_header = QHBoxLayout()

        input_title = QLabel(
            "Danh sách URL"
        )

        input_title.setObjectName(
            "sectionTitle"
        )

        self.input_info = QLabel(
            "0 URL"
        )

        self.input_info.setObjectName(
            "inputInfo"
        )

        input_header.addWidget(
            input_title
        )

        input_header.addStretch()

        input_header.addWidget(
            self.input_info
        )

        input_layout.addLayout(
            input_header
        )

        self.url_input = QPlainTextEdit()

        self.url_input.setPlaceholderText(
            "Paste URL tại đây, mỗi dòng 1 link...\n\n"
            "https://www.tiktok.com/@abc/video/...\n"
            "https://www.tiktok.com/@xyz/video/..."
        )

        self.url_input.setMinimumHeight(
            135
        )

        self.url_input.textChanged.connect(
            self.update_input_counter
        )

        input_layout.addWidget(
            self.url_input
        )

        # ====================================================
        # BUTTONS
        # ====================================================

        buttons = QHBoxLayout()

        self.paste_button = QPushButton(
            "Dán từ Clipboard"
        )

        self.clear_button = QPushButton(
            "Xóa danh sách"
        )

        self.start_button = QPushButton(
            "BẮT ĐẦU LẤY DỮ LIỆU"
        )

        self.start_button.setObjectName(
            "primaryButton"
        )

        self.export_button = QPushButton(
            "Xuất Excel"
        )

        self.export_button.setEnabled(
            False
        )

        self.paste_button.clicked.connect(
            self.paste_clipboard
        )

        self.clear_button.clicked.connect(
            self.clear_urls
        )

        self.start_button.clicked.connect(
            self.start_collect
        )

        self.export_button.clicked.connect(
            self.export_results
        )

        buttons.addWidget(
            self.paste_button
        )

        buttons.addWidget(
            self.clear_button
        )

        buttons.addStretch()

        buttons.addWidget(
            self.export_button
        )

        buttons.addWidget(
            self.start_button
        )

        input_layout.addLayout(
            buttons
        )

        # ====================================================
        # PROGRESS
        # ====================================================

        progress_row = QHBoxLayout()

        self.progress_bar = QProgressBar()

        self.progress_bar.setRange(
            0,
            100,
        )

        self.progress_bar.setValue(
            0
        )

        self.progress_bar.setTextVisible(
            True
        )

        self.progress_text = QLabel(
            "Sẵn sàng"
        )

        self.progress_text.setMinimumWidth(
            240
        )

        progress_row.addWidget(
            self.progress_bar,
            1,
        )

        progress_row.addWidget(
            self.progress_text
        )

        input_layout.addLayout(
            progress_row
        )

        splitter.addWidget(
            input_frame
        )

        # ====================================================
        # TABLE
        # ====================================================

        table_frame = QFrame()

        table_frame.setObjectName(
            "panel"
        )

        table_layout = QVBoxLayout(
            table_frame
        )

        table_layout.setContentsMargins(
            10,
            10,
            10,
            10,
        )

        table_title = QLabel(
            "Kết quả"
        )

        table_title.setObjectName(
            "sectionTitle"
        )

        table_layout.addWidget(
            table_title
        )

        self.table = QTableWidget()

        self.table.setColumnCount(
            14
        )

        self.table.setHorizontalHeaderLabels(
            [
                "STT",
                "Link video",
                "Title / Caption",
                "Creator",
                "Username",
                "Thời gian đăng",
                "View",
                "Like",
                "Comment",
                "Share",
                "Save",
                "Thời gian lấy",
                "Trạng thái",
                "Engagement",
            ]
        )

        self.table.setAlternatingRowColors(
            True
        )

        self.table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.table.verticalHeader().setVisible(
            False
        )

        self.table.setSortingEnabled(
            False
        )

        header_view = (
            self.table.horizontalHeader()
        )

        header_view.setSectionResizeMode(
            QHeaderView.Interactive
        )

        widths = [
            55,
            340,
            330,
            160,
            160,
            160,
            110,
            100,
            100,
            100,
            100,
            160,
            200,
            120,
        ]

        for index, width in enumerate(
            widths
        ):
            self.table.setColumnWidth(
                index,
                width,
            )

        table_layout.addWidget(
            self.table
        )

        splitter.addWidget(
            table_frame
        )

        splitter.setSizes(
            [
                260,
                580,
            ]
        )

        layout.addWidget(
            splitter,
            1,
        )

        return tab_widget

    # ========================================================
    # TAB 2: PROFILE ANALYTICS (THÔNG TIN KÊNH TIKTOK)
    # ========================================================

    def build_profile_tab(
        self,
    ) -> QWidget:
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(12)

        # ====================================================
        # KPI PROFILE
        # ====================================================

        cards = QHBoxLayout()
        cards.setSpacing(10)

        self.profile_card_input = StatCard(
            "Kênh đã nhập"
        )

        self.profile_card_processed = StatCard(
            "Đã xử lý"
        )

        self.profile_card_success = StatCard(
            "Thành công"
        )

        self.profile_card_other = StatCard(
            "Không lấy được"
        )

        cards.addWidget(self.profile_card_input)
        cards.addWidget(self.profile_card_processed)
        cards.addWidget(self.profile_card_success)
        cards.addWidget(self.profile_card_other)

        layout.addLayout(cards)

        # ====================================================
        # SPLITTER PROFILE
        # ====================================================

        splitter = QSplitter(Qt.Vertical)

        # ====================================================
        # INPUT AREA PROFILE
        # ====================================================

        input_frame = QFrame()
        input_frame.setObjectName("panel")

        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 14, 16, 14)

        input_header = QHBoxLayout()

        input_title = QLabel("Danh sách kênh / Creator TikTok")
        input_title.setObjectName("sectionTitle")

        self.profile_input_info = QLabel("0 kênh")
        self.profile_input_info.setObjectName("inputInfo")

        input_header.addWidget(input_title)
        input_header.addStretch()
        input_header.addWidget(self.profile_input_info)

        input_layout.addLayout(input_header)

        self.profile_url_input = QPlainTextEdit()
        self.profile_url_input.setPlaceholderText(
            "Nhập link kênh, @username hoặc link video (mỗi dòng 1 kênh)...\n\n"
            "https://www.tiktok.com/@kimchungphan20\n"
            "@kimchungphan20\n"
            "kimchungphan20\n"
            "https://www.tiktok.com/@kimchungphan20/video/7614484260753345812"
        )
        self.profile_url_input.setMinimumHeight(135)
        self.profile_url_input.textChanged.connect(
            self.update_profile_input_counter
        )

        input_layout.addWidget(self.profile_url_input)

        # ====================================================
        # BUTTONS PROFILE
        # ====================================================

        buttons = QHBoxLayout()

        self.profile_paste_button = QPushButton("Dán từ Clipboard")
        self.profile_clear_button = QPushButton("Xóa danh sách")

        self.profile_open_dir_button = QPushButton("Mở thư mục")
        self.profile_export_button = QPushButton("Xuất Excel")
        self.profile_export_button.setEnabled(False)

        self.profile_stop_button = QPushButton("Dừng")
        self.profile_stop_button.setObjectName("stopButton")
        self.profile_stop_button.setEnabled(False)

        self.profile_start_button = QPushButton("BẮT ĐẦU QUÉT")
        self.profile_start_button.setObjectName("primaryButton")

        self.profile_paste_button.clicked.connect(self.paste_profile_clipboard)
        self.profile_clear_button.clicked.connect(self.clear_profile_inputs)
        self.profile_open_dir_button.clicked.connect(self.open_export_dir_clicked)
        self.profile_export_button.clicked.connect(self.export_profile_results)
        self.profile_stop_button.clicked.connect(self.stop_profile_collect)
        self.profile_start_button.clicked.connect(self.start_profile_collect)

        buttons.addWidget(self.profile_paste_button)
        buttons.addWidget(self.profile_clear_button)
        buttons.addStretch()
        buttons.addWidget(self.profile_open_dir_button)
        buttons.addWidget(self.profile_export_button)
        buttons.addWidget(self.profile_stop_button)
        buttons.addWidget(self.profile_start_button)

        input_layout.addLayout(buttons)

        # ====================================================
        # PROGRESS PROFILE
        # ====================================================

        progress_row = QHBoxLayout()

        self.profile_progress_bar = QProgressBar()
        self.profile_progress_bar.setRange(0, 100)
        self.profile_progress_bar.setValue(0)
        self.profile_progress_bar.setTextVisible(True)

        self.profile_progress_text = QLabel("Sẵn sàng")
        self.profile_progress_text.setMinimumWidth(240)

        progress_row.addWidget(self.profile_progress_bar, 1)
        progress_row.addWidget(self.profile_progress_text)

        input_layout.addLayout(progress_row)

        splitter.addWidget(input_frame)

        # ====================================================
        # TABLE PROFILE
        # ====================================================

        table_frame = QFrame()
        table_frame.setObjectName("panel")

        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(10, 10, 10, 10)

        table_title = QLabel("Kết quả thông tin kênh")
        table_title.setObjectName("sectionTitle")
        table_layout.addWidget(table_title)

        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(14)
        self.profile_table.setHorizontalHeaderLabels([
            "STT",
            "Username",
            "Tên kênh",
            "ID kênh",
            "Follower",
            "Following",
            "Likes",
            "Videos",
            "Verified",
            "Bio",
            "Link kênh",
            "Trạng thái",
            "Phương thức lấy dữ liệu",
            "Thời gian lấy",
        ])

        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profile_table.horizontalHeader().setStretchLastSection(True)

        profile_widths = [
            50,   # STT
            130,  # Username
            150,  # Tên kênh
            160,  # ID kênh
            100,  # Follower
            90,   # Following
            100,  # Likes
            80,   # Videos
            80,   # Verified
            230,  # Bio
            180,  # Link kênh
            140,  # Trạng thái
            140,  # Phương thức
            140,  # Thời gian lấy
        ]

        for index, width in enumerate(profile_widths):
            self.profile_table.setColumnWidth(index, width)

        table_layout.addWidget(self.profile_table)
        splitter.addWidget(table_frame)

        splitter.setSizes([260, 580])
        layout.addWidget(splitter, 1)

        return tab_widget


    # ========================================================
    # STYLE
    # ========================================================

    def apply_style(
        self,
    ):
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f5f7f8;
            }

            QDialog {
                background: #f8fafc;
                color: #111827;
            }

            QWidget {
                font-family: Arial;
                font-size: 13px;
                color: #182026;
            }

            QLabel#mainTitle {
                font-size: 25px;
                font-weight: 700;
                color: #111827;
            }

            QLabel#subtitle {
                font-size: 13px;
                color: #6b7280;
            }

            QLabel#sessionLabel {
                padding: 8px 12px;
                border-radius: 8px;
                background: #ffffff;
                font-weight: 600;
            }

            QFrame#panel {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }

            QFrame#statCard {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }

            QLabel#statTitle {
                color: #6b7280;
                font-size: 12px;
            }

            QLabel#statValue {
                color: #111827;
                font-size: 24px;
                font-weight: 700;
            }

            QLabel#sectionTitle {
                color: #111827;
                font-size: 15px;
                font-weight: 700;
            }

            QLabel#inputInfo {
                color: #6b7280;
                font-weight: 600;
            }

            QPlainTextEdit {
                background: #fafafa;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                padding: 10px;
                selection-background-color: #03B0B1;
            }

            QPushButton {
                min-height: 34px;
                padding: 0 14px;
                border: 1px solid #d1d5db;
                border-radius: 7px;
                background: #ffffff;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #f3f4f6;
            }

            QPushButton:disabled {
                color: #9ca3af;
                background: #f3f4f6;
            }

            QPushButton#primaryButton {
                min-height: 38px;
                padding: 0 22px;
                color: white;
                border: none;
                background: #03B0B1;
                font-weight: 700;
            }

            QPushButton#primaryButton:hover {
                background: #07989a;
            }

            QPushButton#stopButton {
                min-height: 38px;
                padding: 0 18px;
                color: white;
                border: none;
                background: #ef4444;
                font-weight: 700;
                border-radius: 7px;
            }

            QPushButton#stopButton:hover {
                background: #dc2626;
            }

            QPushButton#stopButton:disabled {
                background: #fca5a5;
                color: #fef2f2;
            }

            QTabWidget::pane {
                border: 1px solid #e5e7eb;
                background: #f5f7f8;
                border-radius: 8px;
                top: -1px;
            }

            QTabBar::tab {
                background: #e5e7eb;
                color: #4b5563;
                font-size: 13px;
                font-weight: 700;
                padding: 10px 24px;
                margin-right: 6px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid #d1d5db;
                border-bottom: none;
            }

            QTabBar::tab:selected {
                background: #03B0B1;
                color: #ffffff;
                border-color: #03B0B1;
            }

            QTabBar::tab:hover:!selected {
                background: #dbeafe;
                color: #1e3a8a;
            }

            QProgressBar {
                min-height: 19px;
                border: none;
                border-radius: 7px;
                background: #e5e7eb;
                text-align: center;
            }


            QProgressBar::chunk {
                border-radius: 7px;
                background: #03B0B1;
            }

            QTableWidget {
                background: #ffffff;
                alternate-background-color: #fafafa;
                border: none;
                gridline-color: #eeeeee;
                selection-background-color: #dff7f7;
                selection-color: #111827;
            }

            QHeaderView::section {
                background: #f3f4f6;
                color: #374151;
                border: none;
                border-bottom: 1px solid #d1d5db;
                padding: 8px;
                font-weight: 700;
            }
            """
        )

    def show_light_dialog(
        self,
        title,
        message,
        is_error=False,
    ):
        dialog = ExportResultDialog(
            parent=self,
            title=title,
            message=message,
            file_path=None,
            is_error=is_error,
        )
        dialog.exec()

    # ========================================================
    # SESSION
    # ========================================================

    def apply_session_status(
        self,
        status,
        message="",
    ):
        self.session_status = status
        self.session_message = message

        self.session_label.setToolTip(
            message
        )

        if status == SESSION_READY:
            self.session_label.setText(
                "● TikTok Session: Sẵn sàng"
            )
            self.session_label.setStyleSheet(
                "color:#047857;"
            )
            self.login_button.setText(
                "Đăng nhập lại"
            )
            self.login_button.setEnabled(
                True
            )

            if not self.is_running:
                self.start_button.setEnabled(
                    True
                )

        elif status == SESSION_MISSING:
            self.session_label.setText(
                "● TikTok: Chưa đăng nhập"
            )
            self.session_label.setStyleSheet(
                "color:#b45309;"
            )
            self.login_button.setText(
                "Đăng nhập TikTok"
            )
            self.login_button.setEnabled(
                True
            )

            if not self.is_running:
                self.start_button.setEnabled(
                    False
                )

        elif status in {
            SESSION_INVALID,
            SESSION_EXPIRED,
        }:
            self.session_label.setText(
                "● TikTok: Cần đăng nhập lại"
            )
            self.session_label.setStyleSheet(
                "color:#dc2626;"
            )
            self.login_button.setText(
                "Đăng nhập lại"
            )
            self.login_button.setEnabled(
                True
            )

            if not self.is_running:
                self.start_button.setEnabled(
                    False
                )

        else:
            self.session_label.setText(
                "● TikTok: Chưa xác minh phiên"
            )
            self.session_label.setStyleSheet(
                "color:#b45309;"
            )
            self.login_button.setText(
                "Kiểm tra / Đăng nhập lại"
            )
            self.login_button.setEnabled(
                True
            )

            # UNKNOWN thường là lỗi mạng / TikTok phản hồi chậm. Nếu file
            # session cục bộ vẫn hợp lệ thì cho phép collector thử chạy.
            if not self.is_running:
                self.start_button.setEnabled(
                    has_session()
                )

    def update_session_status(
        self,
    ):
        status, message = (
            inspect_session_local()
        )

        self.apply_session_status(
            status,
            message,
        )

    def start_session_check(
        self,
    ):
        if self.is_running:
            return

        local_status, local_message = (
            inspect_session_local()
        )

        if local_status != SESSION_READY:
            self.apply_session_status(
                local_status,
                local_message,
            )
            return

        if (
            self.session_check_thread is not None
            and self.session_check_thread.isRunning()
        ):
            return

        self.session_label.setText(
            "● TikTok: Đang kiểm tra session..."
        )
        self.session_label.setStyleSheet(
            "color:#475569;"
        )
        self.session_label.setToolTip(
            "Đang xác minh TikTok Session."
        )
        self.login_button.setEnabled(
            False
        )
        self.start_button.setEnabled(
            False
        )

        self.session_check_thread = QThread(
            self
        )
        self.session_check_worker = (
            SessionCheckWorker()
        )
        self.session_check_worker.moveToThread(
            self.session_check_thread
        )

        self.session_check_thread.started.connect(
            self.session_check_worker.run
        )
        self.session_check_worker.finished.connect(
            self.on_session_checked
        )
        self.session_check_worker.failed.connect(
            self.on_session_check_failed
        )

        self.session_check_worker.finished.connect(
            self.session_check_thread.quit
        )
        self.session_check_worker.failed.connect(
            self.session_check_thread.quit
        )

        self.session_check_worker.finished.connect(
            self.session_check_worker.deleteLater
        )
        self.session_check_worker.failed.connect(
            self.session_check_worker.deleteLater
        )

        self.session_check_thread.finished.connect(
            self.on_session_check_thread_finished
        )
        self.session_check_thread.finished.connect(
            self.session_check_thread.deleteLater
        )

        self.session_check_thread.start()

    @Slot(
        str,
        str,
    )
    def on_session_checked(
        self,
        status,
        message,
    ):
        self.apply_session_status(
            status,
            message,
        )

    @Slot(
        str
    )
    def on_session_check_failed(
        self,
        error,
    ):
        self.apply_session_status(
            SESSION_UNKNOWN,
            (
                "Không thể xác minh TikTok Session lúc này: "
                f"{error}"
            ),
        )

    @Slot()
    def on_session_check_thread_finished(
        self,
    ):
        self.session_check_worker = None
        self.session_check_thread = None

    def open_tiktok_login(
        self,
    ):
        if self.is_running:
            self.show_light_dialog(
                "Tool đang chạy",
                "Hãy chờ quá trình lấy dữ liệu hoàn tất rồi đăng nhập lại TikTok.",
                is_error=False,
            )
            return

        # Neu popup dang nhap da mo thi chi dua no len truoc,
        # khong tao them worker/browser thu hai.
        if self.login_dialog is not None:
            try:
                if self.login_dialog.isVisible():
                    self.login_dialog.raise_()
                    self.login_dialog.activateWindow()
                    return
            except RuntimeError:
                self.login_dialog = None

        self.login_dialog = TikTokLoginDialog(
            self
        )

        self.login_dialog.session_saved.connect(
            self.on_tiktok_session_saved
        )
        self.login_dialog.finished.connect(
            self.on_tiktok_login_finished
        )

        # Dung open() thay vi exec() de khong tao nested event loop.
        # Day la cach on dinh hon tren macOS khi popup dang chay QThread
        # va Playwright browser song song.
        self.login_dialog.open()

    @Slot()
    def on_tiktok_session_saved(
        self,
    ):
        self.update_session_status()

    @Slot(int)
    def on_tiktok_login_finished(
        self,
        result,
    ):
        dialog = self.login_dialog
        self.login_dialog = None

        self.update_session_status()

        if result == QDialog.Accepted:
            self.start_session_check()

        if dialog is not None:
            dialog.deleteLater()

    # ========================================================
    # URL INPUT
    # ========================================================

    def get_raw_urls(
        self,
    ):
        text = (
            self.url_input
            .toPlainText()
        )

        return [
            line.strip()

            for line in text.splitlines()

            if line.strip()
        ]

    def update_input_counter(
        self,
    ):
        raw_urls = (
            self.get_raw_urls()
        )

        if not raw_urls:

            self.input_info.setText(
                "0 URL"
            )

            self.card_input.set_value(
                "0"
            )

            return

        unique_urls, duplicates = (
            deduplicate_urls(
                raw_urls
            )
        )

        self.input_info.setText(
            f"{len(raw_urls)} URL"
            f" • {len(unique_urls)} duy nhất"
            f" • {len(duplicates)} trùng"
        )

        self.card_input.set_value(
            len(unique_urls)
        )

    def paste_clipboard(
        self,
    ):
        clipboard = (
            QApplication.clipboard()
        )

        text = clipboard.text()

        if text:

            current = (
                self.url_input
                .toPlainText()
                .strip()
            )

            if current:

                self.url_input.appendPlainText(
                    text
                )

            else:

                self.url_input.setPlainText(
                    text
                )

    def clear_urls(
        self,
    ):
        if self.is_running:
            return

        self.url_input.clear()

        self.table.setRowCount(
            0
        )

        self.row_by_url.clear()

        self.latest_status.clear()

        self.finalized_urls.clear()

        self.last_results = []

        self.progress_bar.setValue(
            0
        )

        self.progress_text.setText(
            "Sẵn sàng"
        )

        self.card_processed.set_value(
            0
        )

        self.card_success.set_value(
            0
        )

        self.card_other.set_value(
            0
        )

        self.export_button.setEnabled(
            False
        )

    # ========================================================
    # TABLE PREPARE
    # ========================================================

    def prepare_table(
        self,
        urls,
    ):
        self.table.setRowCount(
            len(urls)
        )

        self.row_by_url = {}

        self.latest_status = {}

        self.finalized_urls = set()

        for index, url in enumerate(
            urls
        ):
            self.row_by_url[
                url
            ] = index

            parsed = (
                parse_tiktok_url(
                    url
                )
            )

            values = [
                str(index + 1),
                url,
                "",
                "",
                (
                    parsed.username
                    or ""
                ),
                "",
                "-",
                "-",
                "-",
                "-",
                "-",
                "",
                "Chờ xử lý",
                "-",
            ]

            for col, value in enumerate(
                values
            ):
                item = QTableWidgetItem(
                    str(value)
                )

                if col in {
                    0,
                    6,
                    7,
                    8,
                    9,
                    10,
                    13,
                }:
                    item.setTextAlignment(
                        Qt.AlignCenter
                    )

                self.table.setItem(
                    index,
                    col,
                    item,
                )

    # ========================================================
    # RUN
    # ========================================================

    def start_collect(
        self,
    ):
        if self.is_running or self.is_profile_running:
            if self.is_profile_running:
                self.show_light_dialog(
                    "Đang quét thông tin kênh",
                    "Tiến trình quét thông tin kênh đang chạy. Vui lòng đợi hoặc dừng tiến trình trước khi phân tích video.",
                    is_error=False,
                )
            return

        if (
            self.session_status in {
                SESSION_MISSING,
                SESSION_INVALID,
                SESSION_EXPIRED,
            }
            or not has_session()
        ):
            dialog = ExportResultDialog(
                parent=self,
                title="Cần đăng nhập TikTok",
                message=(
                    "TikTok Session trên máy này chưa sẵn sàng. "
                    "Hãy bấm 'Đăng nhập TikTok' ở góc trên bên phải, "
                    "đăng nhập tài khoản của bạn rồi thử lại."
                ),
                file_path=None,
                is_error=True,
            )
            dialog.exec()
            return

        raw_urls = (
            self.get_raw_urls()
        )

        if not raw_urls:

            self.show_light_dialog(
                "Chưa có URL",
                "Hãy paste danh sách TikTok URL.",
                is_error=False,
            )

            return

        (
            unique_urls,
            duplicates,
        ) = deduplicate_urls(
            raw_urls
        )

        if not unique_urls:

            self.show_light_dialog(
                "Không có URL",
                "Không có URL nào để xử lý.",
                is_error=False,
            )

            return

        self.original_count = (
            len(raw_urls)
        )

        self.unique_urls = (
            unique_urls
        )

        self.duplicate_urls = (
            duplicates
        )

        self.last_results = []

        self.last_elapsed = 0

        self.prepare_table(
            unique_urls
        )

        self.is_running = True

        self.start_button.setEnabled(
            False
        )

        self.paste_button.setEnabled(
            False
        )

        self.clear_button.setEnabled(
            False
        )

        self.export_button.setEnabled(
            False
        )

        self.url_input.setReadOnly(
            True
        )

        self.progress_bar.setRange(
            0,
            len(unique_urls),
        )

        self.progress_bar.setValue(
            0
        )

        self.progress_text.setText(
            f"Đang xử lý 0/{len(unique_urls)}"
        )

        self.card_processed.set_value(
            0
        )

        self.card_success.set_value(
            0
        )

        self.card_other.set_value(
            0
        )

        # ====================================================
        # THREAD
        # ====================================================

        self.thread = QThread()

        self.worker = CollectorWorker(
            unique_urls
        )

        self.worker.moveToThread(
            self.thread
        )

        self.thread.started.connect(
            self.worker.run
        )

        self.worker.result_ready.connect(
            self.on_result
        )

        self.worker.finished.connect(
            self.on_finished
        )

        self.worker.failed.connect(
            self.on_failed
        )

        self.worker.finished.connect(
            self.thread.quit
        )

        self.worker.failed.connect(
            self.thread.quit
        )

        self.worker.finished.connect(
            self.worker.deleteLater
        )

        self.worker.failed.connect(
            self.worker.deleteLater
        )

        self.thread.finished.connect(
            self.thread.deleteLater
        )

        self.thread.start()

    # ========================================================
    # RESULT REALTIME
    # ========================================================

    @Slot(
        object,
        bool,
    )
    def on_result(
        self,
        result,
        retry_mode,
    ):
        url = result.get(
            "link"
        )

        if url not in self.row_by_url:
            return

        row = self.row_by_url[
            url
        ]

        status = (
            result.get(
                "status"
            )
            or ""
        )

        self.latest_status[
            url
        ] = status

        engagement = (
            calculate_engagement(
                result
            )
        )

        values = {
            1: (
                result.get(
                    "normalized_url"
                )
                or url
            ),

            2: (
                result.get(
                    "title"
                )
                or ""
            ),

            3: (
                result.get(
                    "uploader"
                )
                or ""
            ),

            4: (
                result.get(
                    "username"
                )
                or ""
            ),

            5: (
                result.get(
                    "release_time"
                )
                or ""
            ),

            6: format_number(
                result.get("view")
            ),

            7: format_number(
                result.get("like")
            ),

            8: format_number(
                result.get("comment")
            ),

            9: format_number(
                result.get("share")
            ),

            10: format_number(
                result.get("save")
            ),

            11: (
                result.get(
                    "retrieval_time"
                )
                or ""
            ),

            12: display_status_label(
                status
            ),

            13: (
                f"{engagement:.2f}%"
                if engagement
                is not None
                else "-"
            ),
        }

        if (
            not retry_mode
            and is_retryable_status(
                status
            )
        ):
            values[
                12
            ] = (
                display_status_label(status)
                + " • đang chờ thử lại"
            )

        for col, value in (
            values.items()
        ):
            item = QTableWidgetItem(
                str(value)
            )

            if col in {
                6,
                7,
                8,
                9,
                10,
                13,
            }:
                item.setTextAlignment(
                    Qt.AlignCenter
                )

            self.table.setItem(
                row,
                col,
                item,
            )

        # ====================================================
        # STATUS COLOR
        # ====================================================

        status_item = (
            self.table.item(
                row,
                12,
            )
        )

        if status == "THANH_CONG":

            status_item.setBackground(
                QBrush(
                    QColor(
                        "#DCFCE7"
                    )
                )
            )

        elif status in {
            "VIDEO_KHONG_KHA_DUNG",
            "VIDEO_RIENG_TU",
        }:

            status_item.setBackground(
                QBrush(
                    QColor(
                        "#F3F4F6"
                    )
                )
            )

        elif is_retryable_status(
            status
        ):

            status_item.setBackground(
                QBrush(
                    QColor(
                        "#FEF3C7"
                    )
                )
            )

        else:

            status_item.setBackground(
                QBrush(
                    QColor(
                        "#FEE2E2"
                    )
                )
            )

        # ====================================================
        # FINAL PROGRESS
        # ====================================================

        final_result = False

        if retry_mode:

            final_result = True

        elif not is_retryable_status(
            status
        ):

            final_result = True

        if (
            final_result
            and url
            not in self.finalized_urls
        ):

            self.finalized_urls.add(
                url
            )

        self.refresh_progress()

    # ========================================================
    # REFRESH KPI
    # ========================================================

    def refresh_progress(
        self,
    ):
        processed = len(
            self.finalized_urls
        )

        total = len(
            self.unique_urls
        )

        success = 0

        other = 0

        for url in self.finalized_urls:

            status = (
                self.latest_status
                .get(
                    url,
                    "",
                )
            )

            if status == "THANH_CONG":
                success += 1
            else:
                other += 1

        self.progress_bar.setValue(
            processed
        )

        self.progress_text.setText(
            f"Đã xử lý {processed}/{total}"
        )

        self.card_processed.set_value(
            processed
        )

        self.card_success.set_value(
            success
        )

        self.card_other.set_value(
            other
        )

    # ========================================================
    # FINISHED
    # ========================================================

    @Slot(
        object
    )
    def on_finished(
        self,
        payload,
    ):
        self.last_results = (
            payload.get(
                "results",
                [],
            )
        )

        self.last_elapsed = (
            payload.get(
                "elapsed",
                0,
            )
        )

        # Dam bao progress = 100%
        self.finalized_urls = set(
            self.unique_urls
        )

        # Cap nhat status cuoi cung
        for result in (
            self.last_results
        ):
            self.latest_status[
                result.link
            ] = (
                result.status
            )

        self.refresh_progress()

        self.progress_text.setText(
            (
                f"Hoàn tất "
                f"{len(self.unique_urls)} link"
                f" • {self.last_elapsed:.1f} giây"
            )
        )

        session_expired = any(
            result.status
            == "SESSION_HET_HAN"
            for result in self.last_results
        )

        if session_expired:
            delete_session()
            self.apply_session_status(
                SESSION_EXPIRED,
                "TikTok đã yêu cầu đăng nhập lại.",
            )
            self.export_button.setEnabled(
                False
            )
            self.finish_run_state()

            dialog = ExportResultDialog(
                parent=self,
                title="TikTok Session đã hết hạn",
                message=(
                    "TikTok đã yêu cầu đăng nhập lại. "
                    "Hãy bấm 'Đăng nhập lại' ở góc trên bên phải, "
                    "sau đó chạy lại danh sách URL."
                ),
                file_path=None,
                is_error=True,
            )
            dialog.exec()
            return

        self.export_button.setEnabled(
            True
        )

        self.finish_run_state()

    # ========================================================
    # FAILED
    # ========================================================

    @Slot(
        str
    )
    def on_failed(
        self,
        error,
    ):
        self.finish_run_state()

        self.progress_text.setText(
            "Đã xảy ra lỗi"
        )

        self.show_light_dialog(
            "Lỗi Collector",
            error,
            is_error=True,
        )

    # ========================================================
    # FINISH STATE
    # ========================================================

    def finish_run_state(
        self,
    ):
        self.is_running = False

        self.start_button.setEnabled(
            (
                self.session_status
                in {
                    SESSION_READY,
                    SESSION_UNKNOWN,
                }
                and has_session()
            )
        )

        self.paste_button.setEnabled(
            True
        )

        self.clear_button.setEnabled(
            True
        )

        self.url_input.setReadOnly(
            False
        )

    # ========================================================
    # EXPORT
    # ========================================================

    def show_export_success_dialog(
        self,
        output_file,
    ):
        dialog = ExportResultDialog(
            parent=self,
            title="Xuất Excel thành công",
            message=(
                "File Excel đã được tạo thành công. "
                "Bạn có thể mở thư mục chứa file hoặc "
                "sao chép đường dẫn bên dưới."
            ),
            file_path=output_file,
            is_error=False,
        )

        dialog.exec()

    def show_export_error_dialog(
        self,
        title,
        message,
    ):
        dialog = ExportResultDialog(
            parent=self,
            title=title,
            message=message,
            file_path=None,
            is_error=True,
        )

        dialog.exec()

    def export_results(
        self,
    ):
        if not self.last_results:

            self.show_export_error_dialog(
                "Chưa có dữ liệu",
                "Chưa có kết quả để xuất Excel.",
            )

            return

        try:

            output_file = export_excel(

                results=(
                    self.last_results
                ),

                duplicate_urls=(
                    self.duplicate_urls
                ),

                original_count=(
                    self.original_count
                ),

                elapsed=(
                    self.last_elapsed
                ),
            )

            self.show_export_success_dialog(
                output_file
            )

        except Exception as exc:

            self.show_export_error_dialog(
                "Không xuất được Excel",
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

    # ========================================================
    # PROFILE TAB METHODS
    # ========================================================

    def get_raw_profile_inputs(
        self,
    ) -> list[str]:
        text = (
            self.profile_url_input
            .toPlainText()
        )
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

    def update_profile_input_counter(
        self,
    ):
        raw_lines = self.get_raw_profile_inputs()
        if not raw_lines:
            self.profile_input_info.setText("0 kênh")
            self.profile_card_input.set_value("0")
            return

        unique_items, duplicates = deduplicate_channel_inputs(raw_lines)
        valid_count = sum(1 for ch in unique_items if ch.valid)

        self.profile_input_info.setText(
            f"{len(raw_lines)} mục • {valid_count} hợp lệ • {len(unique_items)} duy nhất • {len(duplicates)} trùng"
        )
        self.profile_card_input.set_value(len(unique_items))

    def paste_profile_clipboard(
        self,
    ):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            current = self.profile_url_input.toPlainText().strip()
            if current:
                self.profile_url_input.appendPlainText(text)
            else:
                self.profile_url_input.setPlainText(text)

    def clear_profile_inputs(
        self,
    ):
        if self.is_profile_running:
            return

        self.profile_url_input.clear()
        self.profile_table.setRowCount(0)
        self.profile_row_by_key.clear()
        self.profile_latest_status.clear()
        self.profile_finalized_keys.clear()
        self.profile_last_results = []
        self.profile_progress_bar.setValue(0)
        self.profile_progress_text.setText("Sẵn sàng")

        self.profile_card_processed.set_value(0)
        self.profile_card_success.set_value(0)
        self.profile_card_other.set_value(0)
        self.profile_export_button.setEnabled(False)

    def prepare_profile_table(
        self,
        channels: list[TikTokChannelInput],
    ):
        self.profile_table.setRowCount(len(channels))
        self.profile_row_by_key = {}
        self.profile_latest_status = {}
        self.profile_finalized_keys = set()

        for index, ch in enumerate(channels):
            if ch.username:
                self.profile_row_by_key[ch.username.lower()] = index
            self.profile_row_by_key[ch.raw_input] = index
            if ch.normalized_url:
                self.profile_row_by_key[ch.normalized_url] = index

            initial_status = "Chờ xử lý" if ch.valid else "Link không hợp lệ"
            values = [
                str(index + 1),
                ch.username or "",
                "",
                "",
                "-",
                "-",
                "-",
                "-",
                "-",
                "",
                ch.normalized_url or ch.raw_input,
                initial_status,
                "-",
                "-",
            ]

            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col in {0, 4, 5, 6, 7, 8, 11, 12, 13}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.profile_table.setItem(index, col, item)

    def start_profile_collect(
        self,
    ):
        if self.is_profile_running or self.is_running:
            if self.is_running:
                self.show_light_dialog(
                    "Đang phân tích video",
                    "Tiến trình phân tích video đang chạy. Vui lòng đợi hoặc dừng tiến trình trước khi quét thông tin kênh.",
                    is_error=False,
                )
            return

        raw_lines = self.get_raw_profile_inputs()
        if not raw_lines:
            self.show_light_dialog(
                "Chưa có đầu vào",
                "Hãy nhập hoặc dán danh sách URL kênh, @username hoặc URL video.",
                is_error=False,
            )
            return

        unique_channels, duplicates = deduplicate_channel_inputs(raw_lines)
        if not unique_channels:
            self.show_light_dialog(
                "Không có kênh",
                "Không có kênh nào để xử lý.",
                is_error=False,
            )
            return

        self.profile_original_count = len(raw_lines)
        self.profile_unique_items = unique_channels
        self.profile_duplicate_urls = duplicates
        self.profile_last_results = []
        self.profile_last_elapsed = 0

        self.prepare_profile_table(unique_channels)

        self.is_profile_running = True
        self.profile_start_button.setEnabled(False)
        self.profile_stop_button.setEnabled(True)
        self.profile_paste_button.setEnabled(False)
        self.profile_clear_button.setEnabled(False)
        self.profile_export_button.setEnabled(False)
        self.profile_url_input.setReadOnly(True)

        self.profile_progress_bar.setRange(0, len(unique_channels))
        self.profile_progress_bar.setValue(0)
        self.profile_progress_text.setText(f"Đang xử lý 0/{len(unique_channels)}")

        self.profile_card_processed.set_value(0)
        self.profile_card_success.set_value(0)
        self.profile_card_other.set_value(0)

        # Worker & Thread
        self.profile_thread = QThread()
        self.profile_worker = ProfileCollectorWorker(unique_channels)
        self.profile_worker.moveToThread(self.profile_thread)

        self.profile_thread.started.connect(self.profile_worker.run)
        self.profile_worker.result_ready.connect(self.on_profile_result)
        self.profile_worker.finished.connect(self.on_profile_finished)
        self.profile_worker.failed.connect(self.on_profile_failed)

        self.profile_worker.finished.connect(self.profile_thread.quit)
        self.profile_worker.failed.connect(self.profile_thread.quit)
        self.profile_worker.finished.connect(self.profile_worker.deleteLater)
        self.profile_worker.failed.connect(self.profile_worker.deleteLater)
        self.profile_thread.finished.connect(self.profile_thread.deleteLater)

        self.profile_thread.start()

    def stop_profile_collect(
        self,
    ):
        if not self.is_profile_running:
            return
        if self.profile_worker is not None:
            self.profile_worker.cancel()
        self.profile_stop_button.setEnabled(False)
        self.profile_progress_text.setText("Đang dừng...")

    @Slot(object, bool)
    def on_profile_result(
        self,
        result_dict,
        retry_mode,
    ):
        raw_input = result_dict.get("input_url") or ""
        username = (result_dict.get("username") or "").lower()

        row = self.profile_row_by_key.get(username)
        if row is None:
            row = self.profile_row_by_key.get(raw_input)
        if row is None:
            row = self.profile_row_by_key.get(result_dict.get("profile_url"))
        if row is None:
            return

        status = result_dict.get("status") or ""
        key = username or raw_input
        self.profile_latest_status[key] = status

        verified_val = result_dict.get("verified")
        verified_str = "Có" if verified_val is True else ("Không" if verified_val is False else "-")

        bio_clean = (result_dict.get("bio") or "").replace("\n", " ")

        values = {
            1: result_dict.get("username") or "",
            2: result_dict.get("nickname") or "",
            3: str(result_dict.get("user_id") or ""),
            4: format_number(result_dict.get("follower_count")),
            5: format_number(result_dict.get("following_count")),
            6: format_number(result_dict.get("likes_count")),
            7: format_number(result_dict.get("video_count")),
            8: verified_str,
            9: bio_clean,
            10: result_dict.get("profile_url") or "",
            11: format_profile_status(status),
            12: result_dict.get("source_method") or "",
            13: result_dict.get("collected_at") or "",
        }

        if not retry_mode and status in PROFILE_RETRYABLE_STATUSES:
            values[11] = format_profile_status(status) + " • chờ thử lại"

        for col, val in values.items():
            item = QTableWidgetItem(str(val))
            if col in {4, 5, 6, 7, 8, 11, 12, 13}:
                item.setTextAlignment(Qt.AlignCenter)
            self.profile_table.setItem(row, col, item)

        status_item = self.profile_table.item(row, 11)
        if status_item:
            if status == "SUCCESS":
                status_item.setBackground(QBrush(QColor("#DCFCE7")))
            elif status in {"PARTIAL", "PRIVATE"}:
                status_item.setBackground(QBrush(QColor("#FEF3C7")))
            elif status in {
                "NOT_FOUND",
                "CAPTCHA_REQUIRED",
                "RATE_LIMITED",
                "SESSION_EXPIRED",
                "TIMEOUT",
                "NETWORK_ERROR",
                "PARSE_ERROR",
                "LINK_TIKTOK_KHONG_HOP_LE",
                "KHONG_HO_TRO_NEN_TANG",
            }:
                status_item.setBackground(QBrush(QColor("#FEE2E2")))
            else:
                status_item.setBackground(QBrush(QColor("#F3F4F6")))

        if retry_mode or status not in PROFILE_RETRYABLE_STATUSES:
            self.profile_finalized_keys.add(key)

        self.refresh_profile_progress()

    def refresh_profile_progress(
        self,
    ):
        processed = len(self.profile_finalized_keys)
        total = len(self.profile_unique_items)

        success = 0
        other = 0
        for key in self.profile_finalized_keys:
            st = self.profile_latest_status.get(key, "")
            if st == "SUCCESS":
                success += 1
            else:
                other += 1

        self.profile_progress_bar.setValue(processed)
        self.profile_progress_text.setText(f"Đã xử lý {processed}/{total}")
        self.profile_card_processed.set_value(processed)
        self.profile_card_success.set_value(success)
        self.profile_card_other.set_value(other)

    @Slot(object)
    def on_profile_finished(
        self,
        payload,
    ):
        self.profile_last_results = payload.get("results", [])
        self.profile_last_elapsed = payload.get("elapsed", 0)

        for ch in self.profile_unique_items:
            k = (ch.username.lower() if ch.username else ch.raw_input)
            self.profile_finalized_keys.add(k)

        for res in self.profile_last_results:
            k = (res.username.lower() if res.username else res.input_url)
            self.profile_latest_status[k] = res.status

        self.refresh_profile_progress()
        self.profile_progress_text.setText(
            f"Hoàn tất {len(self.profile_unique_items)} kênh • {self.profile_last_elapsed:.1f} giây"
        )

        has_expired = any(r.status == "SESSION_EXPIRED" for r in self.profile_last_results)
        if has_expired:
            delete_session()
            self.apply_session_status(SESSION_EXPIRED, "TikTok đã yêu cầu đăng nhập lại.")
            self.finish_profile_run_state()
            dialog = ExportResultDialog(
                parent=self,
                title="TikTok Session đã hết hạn",
                message=(
                    "TikTok đã yêu cầu đăng nhập lại. "
                    "Hãy bấm 'Đăng nhập lại' ở góc trên bên phải, sau đó quét lại danh sách kênh."
                ),
                file_path=None,
                is_error=True,
            )
            dialog.exec()
            return

        self.profile_export_button.setEnabled(True)
        self.finish_profile_run_state()

    @Slot(str)
    def on_profile_failed(
        self,
        error,
    ):
        self.finish_profile_run_state()
        self.profile_progress_text.setText("Đã xảy ra lỗi")
        self.show_light_dialog(
            "Lỗi Profile Collector",
            error,
            is_error=True,
        )

    def finish_profile_run_state(
        self,
    ):
        self.is_profile_running = False
        self.profile_start_button.setEnabled(True)
        self.profile_stop_button.setEnabled(False)
        self.profile_paste_button.setEnabled(True)
        self.profile_clear_button.setEnabled(True)
        self.profile_url_input.setReadOnly(False)

    def export_profile_results(
        self,
    ):
        if not self.profile_last_results:
            self.show_export_error_dialog(
                "Chưa có dữ liệu",
                "Chưa có kết quả để xuất Excel.",
            )
            return

        try:
            output_file = export_profile_excel(
                results=self.profile_last_results,
                duplicate_count=len(self.profile_duplicate_urls),
                original_count=self.profile_original_count,
                elapsed=self.profile_last_elapsed,
            )
            self.show_export_success_dialog(output_file)
        except Exception as exc:
            self.show_export_error_dialog(
                "Không xuất được Excel",
                f"{type(exc).__name__}: {exc}",
            )

    def open_export_dir_clicked(
        self,
    ):
        try:
            export_dir = get_export_dir()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_dir)))
        except Exception as exc:
            self.show_light_dialog("Lỗi", f"Không thể mở thư mục: {exc}", is_error=True)

    # ========================================================
    # CLOSE
    # ========================================================

    def closeEvent(
        self,
        event,
    ):
        if self.is_running or self.is_profile_running:
            self.show_light_dialog(
                "Tool đang chạy",
                (
                    "Một tác vụ đang lấy dữ liệu.\n"
                    "Hãy chờ xử lý xong hoặc bấm Dừng trước khi đóng ứng dụng."
                ),
                is_error=False,
            )
            event.ignore()
            return

        event.accept()



# ============================================================
# MAIN
# ============================================================

def main():
    if "--smoke-test" in sys.argv:
        import os
        print("SMOKE TEST OK: App initialized successfully.")
        print("PLAYWRIGHT_BROWSERS_PATH:", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
        sys.exit(0)

    if "--test-playwright" in sys.argv:
        import os
        print("TEST PLAYWRIGHT: Verifying bundled browser launch...")
        print("PLAYWRIGHT_BROWSERS_PATH:", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            print("PLAYWRIGHT BROWSER OK: Version", b.version)
            b.close()
        sys.exit(0)

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        "TikTok Video Performance Tool"
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()