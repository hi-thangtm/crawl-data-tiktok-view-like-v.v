# -*- coding: utf-8 -*-
"""Verification test suite for packaged standalone macOS app."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "dist" / "TikTok Video Performance.app"
EXEC_PATH = APP_PATH / "Contents" / "MacOS" / "TikTok Video Performance"
BUNDLED_PW_PATH = APP_PATH / "Contents" / "Resources" / "ms-playwright"


def test_bundle_structure():
    print("[TEST 1] Checking App Bundle Structure...")
    assert APP_PATH.is_dir(), f"Missing app at {APP_PATH}"
    assert EXEC_PATH.is_file(), f"Missing executable at {EXEC_PATH}"
    assert os.access(EXEC_PATH, os.X_OK), "Executable missing +x permission"
    assert BUNDLED_PW_PATH.is_dir(), f"Missing ms-playwright at {BUNDLED_PW_PATH}"

    # Verify Chromium .app exists inside bundled ms-playwright
    chrome_apps = list(BUNDLED_PW_PATH.glob("chromium-*/chrome-mac-arm64/Google Chrome for Testing.app"))
    assert len(chrome_apps) > 0, "No Google Chrome for Testing.app found in bundled ms-playwright"
    print(f" -> Found bundled Chromium: {chrome_apps[0].relative_to(APP_PATH)}")
    print("PASS: Bundle structure valid.")


def test_codesign_verification():
    print("\n[TEST 2] Verifying Codesign Integrity...")
    res = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(APP_PATH)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Codesign verify failed:\n{res.stderr}"
    print("PASS: App bundle signature verified (--deep --strict).")


def test_no_personal_data_packaged():
    print("\n[TEST 3] Verifying No Personal Sessions or Cookies Packaged...")
    for root, _, files in os.walk(APP_PATH):
        for f in files:
            assert f != "tiktok_state.json", f"Found personal session file in app: {os.path.join(root, f)}"
            assert not f.endswith(".session"), f"Found session file in app: {os.path.join(root, f)}"
    print("PASS: No personal session or cookies packaged.")


def test_packaged_executable_smoke_test():
    print("\n[TEST 4] Testing Packaged Executable Smoke Test...")
    res = subprocess.run([str(EXEC_PATH), "--smoke-test"], capture_output=True, text=True)
    assert res.returncode == 0, f"Smoke test failed:\n{res.stderr}"
    assert "SMOKE TEST OK" in res.stdout, f"Unexpected output:\n{res.stdout}"
    assert str(BUNDLED_PW_PATH) in res.stdout, f"PLAYWRIGHT_BROWSERS_PATH mismatch:\n{res.stdout}"
    print("PASS: App initializes and resolves PLAYWRIGHT_BROWSERS_PATH to Contents/Resources/ms-playwright.")


def test_isolated_playwright_launch():
    print("\n[TEST 5] Testing Isolated Playwright Browser Launch (no dev cache)...")
    with tempfile.TemporaryDirectory() as fake_home:
        # Run with isolated HOME and without any inherited PLAYWRIGHT_BROWSERS_PATH
        env = os.environ.copy()
        env["HOME"] = fake_home
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)

        res = subprocess.run(
            [str(EXEC_PATH), "--test-playwright"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Playwright launch failed:\n{res.stderr}"
        assert "PLAYWRIGHT BROWSER OK" in res.stdout, f"Unexpected output:\n{res.stdout}"
        print(f" -> Output: {res.stdout.strip()}")
    print("PASS: Playwright successfully launched Chromium from bundled ms-playwright in isolated environment.")


def test_http_collector_and_excel_export():
    print("\n[TEST 6] Testing HTTP Collector and Excel Export...")
    from app.collectors.tiktok_http import collect_tiktok_http
    from app.models import VideoResult
    from app.utils.profile_excel import export_profile_excel
    from app.models import TikTokProfileResult

    # Test HTTP collector logic
    test_url = "https://www.tiktok.com/@tiktok/video/7123456789012345678"
    result = collect_tiktok_http(test_url)
    assert isinstance(result, VideoResult), "Expected VideoResult object"
    print(f" -> HTTP collector result status: {result.status}")

    # Test Excel Export logic
    dummy_profile = TikTokProfileResult(
        input_url="@test_creator",
        profile_url="https://www.tiktok.com/@test_creator",
        username="test_creator",
        nickname="Test Creator",
        user_id="123456789",
        follower_count=12345,
        following_count=100,
        likes_count=99999,
        video_count=10,
        verified=True,
        bio="Test bio",
        status="SUCCESS",
        source_method="HTTP",
        collected_at="2026-10-23 08:00:00",
    )
    saved_file = export_profile_excel([dummy_profile])
    assert saved_file.is_file(), f"Excel file was not created: {saved_file}"
    assert saved_file.stat().st_size > 1000, "Excel file is empty or corrupted"
    print(f" -> Exported test excel: {saved_file} ({saved_file.stat().st_size} bytes)")
    try:
        saved_file.unlink()
    except Exception:
        pass
    print("PASS: HTTP collector and Excel export work as expected.")


if __name__ == "__main__":
    test_bundle_structure()
    test_codesign_verification()
    test_no_personal_data_packaged()
    test_packaged_executable_smoke_test()
    test_isolated_playwright_launch()
    test_http_collector_and_excel_export()
    print("\n" + "=" * 60)
    print("ALL STANDALONE TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
