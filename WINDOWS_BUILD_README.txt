TIKTOK VIDEO PERFORMANCE - BUILD WINDOWS
========================================

Muc tieu
--------
Build ban Windows x64 tu GitHub Actions. Khong can may Windows de build.

File can them vao repository
----------------------------
TikTokVideoPerformance.windows.spec
.github/workflows/build-windows.yml
build/build_windows.bat

Cach build tren GitHub
----------------------
1. Copy cac file vao dung vi tri trong repository.
2. Commit + push len GitHub.
3. Mo repository tren GitHub.
4. Chon tab Actions.
5. Chon workflow "Build Windows".
6. Bam "Run workflow".
7. Cho job build-windows hoan tat.
8. Mo job da build, keo xuong muc Artifacts.
9. Tai "TikTok-Video-Performance-Windows-x64".
10. Giai nen ZIP. Trong thu muc co:
    TikTok Video Performance.exe

Yeu cau tren may nguoi dung Windows
-----------------------------------
- Windows 10/11 64-bit.
- Google Chrome da cai dat.
- Khong can Python.
- Khong can VS Code.

Luu y Playwright
----------------
Tool hien tai mo Google Chrome bang channel="chrome". Workflow KHONG download
Chromium cua Playwright, de package nhe hon va giu dung browser ma collector
dang su dung on dinh tren macOS.

Session Windows
---------------
Session cua moi nguoi dung duoc luu rieng tren may cua ho. Tuyet doi khong commit
file tiktok_state.json vao GitHub.

Ban test dau tien
-----------------
Nen dung dang onedir (mot thu muc chua EXE + cac DLL) thay vi onefile. PySide6 +
Playwright on dinh hon voi onedir. Sau khi test on dinh moi dong thanh installer.

Sau khi build thanh cong
-------------------------
Test tren mot may Windows khac:
1. Giai nen ZIP.
2. Double-click TikTok Video Performance.exe.
3. Dang nhap TikTok.
4. Dong va mo lai tool de kiem tra session.
5. Lay du lieu 1 link.
6. Test 20-60 link.
7. Xuat Excel.

Buoc sau do moi lam installer (.exe setup) bang Inno Setup.
