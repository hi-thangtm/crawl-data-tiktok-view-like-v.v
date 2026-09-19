from pathlib import Path

from playwright.sync_api import sync_playwright


STATE_FILE = Path(
    "data/tiktok_state.json"
)

STATE_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)


print()
print("=" * 70)
print("TAO PHIEN TIKTOK CHO TOOL")
print("=" * 70)
print()
print(
    "Chrome se mo."
)
print(
    "Neu TikTok yeu cau dang nhap, hay dang nhap binh thuong."
)
print(
    "Sau khi vao duoc TikTok, quay lai Terminal va nhan Enter."
)
print()


with sync_playwright() as p:

    browser = p.chromium.launch(
        channel="chrome",
        headless=False,
    )

    context = browser.new_context(
        viewport={
            "width": 1440,
            "height": 900,
        },
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
    )

    page = context.new_page()

    page.goto(
        "https://www.tiktok.com/",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    input(
        "\nDang nhap/xac nhan xong thi nhan ENTER tai day..."
    )

    context.storage_state(
        path=str(
            STATE_FILE
        )
    )

    print()
    print(
        "DA LUU SESSION:"
    )

    print(
        STATE_FILE.resolve()
    )

    context.close()
    browser.close()


print()
print(
    "HOAN TAT."
)