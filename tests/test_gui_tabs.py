import sys
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui_app import MainWindow
from app.utils.url_parser import parse_tiktok_channel_input


class TestGuiTabs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        if self.window.session_check_thread is not None and self.window.session_check_thread.isRunning():
            self.window.session_check_thread.quit()
            self.window.session_check_thread.wait(2000)
        self.window.deleteLater()


    def test_tabs_presence_and_switching(self):
        self.assertEqual(self.window.tabs.count(), 2)
        self.assertEqual(self.window.tabs.tabText(0), "Hiệu suất video")
        self.assertEqual(self.window.tabs.tabText(1), "Thông tin kênh TikTok")

        # Switch to tab 1 (profiles)
        self.window.tabs.setCurrentIndex(1)
        self.assertEqual(self.window.tabs.currentIndex(), 1)

        # Switch back to tab 0 (videos)
        self.window.tabs.setCurrentIndex(0)
        self.assertEqual(self.window.tabs.currentIndex(), 0)

    def test_profile_input_counter_and_clear(self):
        self.window.profile_url_input.setPlainText(
            "https://www.tiktok.com/@creator1\n"
            "@creator2\n"
            "https://www.tiktok.com/@creator1/video/1234567890\n"
            "creator3"
        )
        self.assertEqual(self.window.profile_card_input.value_label.text(), "3")
        self.assertIn("4 mục • 3 hợp lệ • 3 duy nhất • 1 trùng", self.window.profile_input_info.text())

        # Test clear
        self.window.clear_profile_inputs()
        self.assertEqual(self.window.profile_url_input.toPlainText(), "")
        self.assertEqual(self.window.profile_card_input.value_label.text(), "0")
        self.assertEqual(self.window.profile_table.rowCount(), 0)

    def test_profile_table_preparation(self):
        channels = [
            parse_tiktok_channel_input("@creator1"),
            parse_tiktok_channel_input("@creator2"),
        ]
        self.window.profile_unique_items = channels
        self.window.prepare_profile_table(channels)

        self.assertEqual(self.window.profile_table.rowCount(), 2)
        self.assertEqual(self.window.profile_table.item(0, 1).text(), "creator1")
        self.assertEqual(self.window.profile_table.item(1, 1).text(), "creator2")
        self.assertEqual(self.window.profile_table.item(0, 11).text(), "Chờ xử lý")

    def test_profile_result_updates_table(self):
        channels = [parse_tiktok_channel_input("@creator1")]
        self.window.profile_unique_items = channels
        self.window.prepare_profile_table(channels)

        mock_result = {
            "input_url": "@creator1",
            "profile_url": "https://www.tiktok.com/@creator1",
            "username": "creator1",
            "nickname": "Creator One",
            "user_id": "999888777",
            "follower_count": 50000,
            "following_count": 100,
            "likes_count": 1000000,
            "video_count": 50,
            "verified": True,
            "bio": "Bio description",
            "status": "SUCCESS",
            "source_method": "HTTP/UNIVERSAL_DATA",
            "collected_at": "2026-10-21 15:30:00",
        }

        self.window.on_profile_result(mock_result, retry_mode=False)

        # Verify values in table
        self.assertEqual(self.window.profile_table.item(0, 1).text(), "creator1")
        self.assertEqual(self.window.profile_table.item(0, 2).text(), "Creator One")
        self.assertEqual(self.window.profile_table.item(0, 3).text(), "999888777")
        self.assertEqual(self.window.profile_table.item(0, 4).text(), "50.000")
        self.assertEqual(self.window.profile_table.item(0, 8).text(), "Có")
        self.assertEqual(self.window.profile_table.item(0, 11).text(), "Thành công")

        # Verify KPI cards
        self.assertEqual(self.window.profile_card_processed.value_label.text(), "1")
        self.assertEqual(self.window.profile_card_success.value_label.text(), "1")
        self.assertEqual(self.window.profile_card_other.value_label.text(), "0")

    def test_profile_stop_cancellation(self):
        self.window.is_profile_running = True
        self.window.stop_profile_collect()
        self.assertEqual(self.window.profile_progress_text.text(), "Đang dừng...")
        self.assertFalse(self.window.profile_stop_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
