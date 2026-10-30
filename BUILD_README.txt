TIKTOK VIDEO PERFORMANCE - BUILD MACOS STANDALONE APP (APPLE SILICON ARM64)

1. CÁCH BUILD:
   cd /duong-dan-toi/crawl-data
   bash build_macos.sh
   (hoặc: bash build/build_mac.sh)

2. KẾT QUẢ ĐÓNG GÓI:
   - Ứng dụng .app: dist/TikTok Video Performance.app
   - File ZIP phân phối: dist/TikTokVideoPerformance-macOS-arm64.zip

3. ĐẶC ĐIỂM BẢN BUILD ĐỘC LẬP (STANDALONE):
   - Đã nhúng sẵn Chromium Playwright vào Contents/Resources/ms-playwright.
   - Người nhận KHÔNG cần cài Python, PySide6 hay Playwright.
   - Nếu máy người nhận chưa có Google Chrome, hệ thống tự động chạy Chromium đóng gói sẵn.
   - App tự động cấu hình PLAYWRIGHT_BROWSERS_PATH khi khởi chạy.
   - Ứng dụng được ad-hoc sign sâu (--deep) và xác minh tính toàn vẹn (codesign --verify).

4. LƯU Ý VỀ DỮ LIỆU & BẢO MẬT:
   - File ZIP không chứa cookie hay session cá nhân.
   - Session/cookie của người dùng được lưu tại:
     ~/Library/Application Support/TikTok Video Performance/tiktok_state.json
   - File Excel kết quả được xuất ra:
     ~/Documents/TikTok Video Performance/Exports/

5. KIỂM THỬ:
   - Mở ứng dụng bình thường:
     open "dist/TikTok Video Performance.app"
   - Smoke test kiểm tra runtime:
     "dist/TikTok Video Performance.app/Contents/MacOS/TikTok Video Performance" --smoke-test
   - Test khởi động Playwright từ bản đóng gói:
     "dist/TikTok Video Performance.app/Contents/MacOS/TikTok Video Performance" --test-playwright
