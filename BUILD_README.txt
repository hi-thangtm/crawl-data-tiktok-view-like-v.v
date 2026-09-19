TIKTOK VIDEO PERFORMANCE - BUILD MACOS DEV APP

1. Dat 2 file/folder sau vao project crawl-data:
   TikTokVideoPerformance.spec
   build/build_mac.sh

2. Cau truc can co:
   crawl-data/
     gui_app.py
     run_batch.py
     TikTokVideoPerformance.spec
     app/
       __init__.py
       session_manager.py
       tiktok_login.py
       collectors/
         __init__.py
         tiktok_batch.py
         tiktok_browser.py
         tiktok_http.py
       utils/
         __init__.py
         url_parser.py
     build/
       build_mac.sh

3. Terminal:
   cd duong-dan-toi/crawl-data
   source .venv/bin/activate
   python -m pip install -U pyinstaller
   bash build/build_mac.sh

4. App tao tai:
   dist/TikTok Video Performance.app

5. Test:
   open "dist/TikTok Video Performance.app"

LUU Y:
- Day la ban build dev chua ky/notarize.
- Collector hien dung Google Chrome (channel="chrome"), vi vay may test phai co Google Chrome.
- Session cua tung nguoi van nam ngoai app trong ~/Library/Application Support/TikTok Video Performance/.
- Excel van xuat ra Documents/TikTok Video Performance/Exports/.
- Khong copy tiktok_state.json vao goi app.
