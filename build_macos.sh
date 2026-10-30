#!/usr/bin/env bash
# ==============================================================================
# TikTok Video Performance - macOS Build Script (Apple Silicon arm64)
# ==============================================================================
# This script packages the PySide6 + Playwright application into a standalone
# macOS .app bundle containing its own bundled Chromium browser.
# ==============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "===================================================================="
echo " TIKTOK VIDEO PERFORMANCE - MACOS PACKAGING PIPELINE"
echo "===================================================================="
echo "Project Root: $PROJECT_ROOT"
echo

# ------------------------------------------------------------------------------
# 1. Detect and verify Python environment
# ------------------------------------------------------------------------------
echo "[1/9] Checking Python environment..."

if [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON="$PYTHON_BIN"
elif [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "ERROR: Python 3 not found. Please activate .venv or set PYTHON_BIN." >&2
    exit 1
fi

PY_VER="$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")"
PY_PLAT="$("$PYTHON" -c "import sys, platform; print(f'{sys.platform}-{platform.machine()}')")"

echo "Using Python: $PYTHON"
echo "Python Version: $PY_VER ($PY_PLAT)"

if [ "$("$PYTHON" -c "import sys; print(int(sys.platform == 'darwin'))")" != "1" ]; then
    echo "ERROR: This script must be executed on macOS." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# 2. Check dependencies and validate source syntax
# ------------------------------------------------------------------------------
echo
echo "[2/9] Checking dependencies and syntax..."

REQUIRED_MODULES=("PyInstaller" "playwright" "PySide6" "openpyxl" "httpx" "bs4")
for mod in "${REQUIRED_MODULES[@]}"; do
    if ! "$PYTHON" -c "import $mod" >/dev/null 2>&1; then
        echo "ERROR: Required Python module '$mod' is not installed in $PYTHON." >&2
        echo "Install dependencies first (e.g. pip install -r requirements.txt or pip install $mod)." >&2
        exit 1
    fi
done

PYI_VER="$("$PYTHON" -m PyInstaller --version)"
PW_VER="$("$PYTHON" -c "import importlib.metadata; print(importlib.metadata.version('playwright'))")"
echo "PyInstaller Version: $PYI_VER"
echo "Playwright Version:  $PW_VER"

echo "Validating syntax of Python files..."
"$PYTHON" -m py_compile \
    gui_app.py \
    rthook_playwright.py \
    app/__init__.py \
    app/runtime_env.py \
    app/models.py \
    app/session_manager.py \
    app/tiktok_login.py \
    app/collectors/tiktok_batch.py \
    app/collectors/tiktok_browser.py \
    app/collectors/tiktok_http.py \
    app/collectors/tiktok_profile_batch.py \
    app/collectors/tiktok_profile_http.py \
    app/utils/url_parser.py \
    app/utils/profile_excel.py
echo "All files passed syntax validation."

# ------------------------------------------------------------------------------
# 3. Prepare Chromium browser distribution
# ------------------------------------------------------------------------------
echo
echo "[3/9] Preparing Chromium browser distribution..."

BROWSER_STAGING_DIR="$PROJECT_ROOT/build/ms-playwright-cache"
mkdir -p "$BROWSER_STAGING_DIR"

# Check if browser is already cached in staging
HAS_STAGED_CHROMIUM=0
if compgen -G "$BROWSER_STAGING_DIR/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app" >/dev/null; then
    HAS_STAGED_CHROMIUM=1
fi

if [ "$HAS_STAGED_CHROMIUM" -eq 1 ]; then
    echo "Found existing staged Chromium in $BROWSER_STAGING_DIR."
else
    # Look for existing local cache to avoid unnecessary network download
    LOCAL_PKG_BROWSERS="$PROJECT_ROOT/.venv/lib/python$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")/site-packages/playwright/driver/package/.local-browsers"
    USER_CACHE_BROWSERS="$HOME/Library/Caches/ms-playwright"

    COPIED_FROM_CACHE=0
    if compgen -G "$LOCAL_PKG_BROWSERS/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app" >/dev/null; then
        echo "Copying Chromium from package .local-browsers cache..."
        cp -a "$LOCAL_PKG_BROWSERS/"* "$BROWSER_STAGING_DIR/"
        [ -d "$LOCAL_PKG_BROWSERS/.links" ] && cp -a "$LOCAL_PKG_BROWSERS/.links" "$BROWSER_STAGING_DIR/"
        COPIED_FROM_CACHE=1
    elif compgen -G "$USER_CACHE_BROWSERS/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app" >/dev/null; then
        echo "Copying Chromium from ~/Library/Caches/ms-playwright..."
        cp -a "$USER_CACHE_BROWSERS/"* "$BROWSER_STAGING_DIR/"
        [ -d "$USER_CACHE_BROWSERS/.links" ] && cp -a "$USER_CACHE_BROWSERS/.links" "$BROWSER_STAGING_DIR/"
        COPIED_FROM_CACHE=1
    fi

    if [ "$COPIED_FROM_CACHE" -eq 0 ]; then
        echo "Downloading matching Chromium via Playwright CLI..."
        PLAYWRIGHT_BROWSERS_PATH="$BROWSER_STAGING_DIR" "$PYTHON" -m playwright install chromium
    fi
fi

# Verify staging directory contents
CHROMIUM_APP_PATH="$(compgen -G "$BROWSER_STAGING_DIR/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app" | head -n 1 || true)"
if [ -z "$CHROMIUM_APP_PATH" ] || [ ! -d "$CHROMIUM_APP_PATH" ]; then
    echo "ERROR: Failed to prepare Google Chrome for Testing.app in $BROWSER_STAGING_DIR." >&2
    exit 1
fi
echo "Verified Chromium app at: $CHROMIUM_APP_PATH"

# ------------------------------------------------------------------------------
# 4. Build Application with PyInstaller
# ------------------------------------------------------------------------------
echo
echo "[4/9] Building PyInstaller onedir application..."

rm -rf "$PROJECT_ROOT/build/pyinstaller-work"
rm -rf "$PROJECT_ROOT/dist"
mkdir -p "$PROJECT_ROOT/build/pyinstaller-work"

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$PROJECT_ROOT/dist" \
    --workpath "$PROJECT_ROOT/build/pyinstaller-work" \
    "$PROJECT_ROOT/TikTokVideoPerformance.spec"

APP_PATH="$PROJECT_ROOT/dist/TikTok Video Performance.app"
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: PyInstaller failed to generate $APP_PATH" >&2
    exit 1
fi
echo "PyInstaller build succeeded."

# ------------------------------------------------------------------------------
# 5. Copy Chromium into Contents/Resources/ms-playwright
# ------------------------------------------------------------------------------
echo
echo "[5/9] Embedding Chromium into application bundle..."

TARGET_PW_DIR="$APP_PATH/Contents/Resources/ms-playwright"
rm -rf "$TARGET_PW_DIR"
mkdir -p "$TARGET_PW_DIR"

echo "Copying browser distribution into: $TARGET_PW_DIR"
cp -a "$BROWSER_STAGING_DIR/"* "$TARGET_PW_DIR/"
if [ -d "$BROWSER_STAGING_DIR/.links" ]; then
    cp -a "$BROWSER_STAGING_DIR/.links" "$TARGET_PW_DIR/"
fi

# Ensure executable permissions are preserved
find "$TARGET_PW_DIR" -type f -name "Google Chrome for Testing" -exec chmod +x {} +
find "$TARGET_PW_DIR" -type f -name "chrome-headless-shell" -exec chmod +x {} +
find "$TARGET_PW_DIR" -type f -name "ffmpeg" -exec chmod +x {} + 2>/dev/null || true

# Verify embedded browser
EMBEDDED_CHROME="$(compgen -G "$TARGET_PW_DIR/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app" | head -n 1 || true)"
if [ -z "$EMBEDDED_CHROME" ] || [ ! -d "$EMBEDDED_CHROME" ]; then
    echo "ERROR: Embedded Google Chrome for Testing.app not found in $TARGET_PW_DIR." >&2
    exit 1
fi
echo "Embedded Chromium verified: $EMBEDDED_CHROME"

# ------------------------------------------------------------------------------
# 6. Perform Code Signing
# ------------------------------------------------------------------------------
echo
echo "[6/9] Performing code signing..."

# Remove quarantine and metadata extended attributes
xattr -cr "$APP_PATH"

SIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
echo "Signing with identity: '$SIGN_IDENTITY'"

if ! codesign --force --deep --sign "$SIGN_IDENTITY" "$APP_PATH"; then
    echo "ERROR: Code signing failed on $APP_PATH!" >&2
    exit 1
fi

echo "Code signing completed successfully."

# ------------------------------------------------------------------------------
# 7. Verify Application Bundle
# ------------------------------------------------------------------------------
echo
echo "[7/9] Verifying application bundle integrity..."

if ! codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1; then
    echo "ERROR: Code signature verification failed on $APP_PATH!" >&2
    exit 1
fi
echo "Application bundle passed strict deep signature verification."

# ------------------------------------------------------------------------------
# 8. Smoke Test the Packaged Application
# ------------------------------------------------------------------------------
echo
echo "[8/9] Testing packaged executable & embedded Playwright..."

EXEC_BIN="$APP_PATH/Contents/MacOS/TikTok Video Performance"
if [ ! -x "$EXEC_BIN" ]; then
    echo "ERROR: Application binary $EXEC_BIN is not executable." >&2
    exit 1
fi

# Test runtime initialization and path resolution
echo "Running smoke test on packaged app..."
SMOKE_OUTPUT="$("$EXEC_BIN" --smoke-test)"
echo "$SMOKE_OUTPUT"

# Test embedded Playwright Chromium launch with isolated environment
echo "Running isolated Playwright launch test from packaged app..."
# Clear external cache vars to prove self-reliance
TEST_OUTPUT="$(env -u PLAYWRIGHT_BROWSERS_PATH "$EXEC_BIN" --test-playwright)"
echo "$TEST_OUTPUT"

if ! echo "$TEST_OUTPUT" | grep -q "PLAYWRIGHT BROWSER OK"; then
    echo "ERROR: Playwright failed to launch bundled Chromium browser!" >&2
    exit 1
fi
echo "Embedded Playwright test passed successfully."

# ------------------------------------------------------------------------------
# 9. Create Distribution ZIP
# ------------------------------------------------------------------------------
echo
echo "[9/9] Creating distribution ZIP archive..."

ZIP_NAME="TikTokVideoPerformance-macOS-arm64.zip"
ZIP_PATH="$PROJECT_ROOT/dist/$ZIP_NAME"
rm -f "$ZIP_PATH"

cd "$PROJECT_ROOT/dist"
ditto -c -k --keepParent "TikTok Video Performance.app" "$ZIP_NAME"
cd "$PROJECT_ROOT"

if [ ! -f "$ZIP_PATH" ]; then
    echo "ERROR: Failed to create ZIP archive $ZIP_PATH" >&2
    exit 1
fi

ZIP_SIZE="$(du -h "$ZIP_PATH" | cut -f1)"

echo
echo "===================================================================="
echo " BUILD SUCCESSFUL!"
echo "===================================================================="
echo "Application: $APP_PATH"
echo "Package ZIP: $ZIP_PATH ($ZIP_SIZE)"
echo
echo "You can distribute '$ZIP_NAME' directly to any macOS Apple Silicon user."
echo "No Python or Playwright installation is required by the recipient."
echo "===================================================================="
