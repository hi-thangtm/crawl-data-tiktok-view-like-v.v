from pprint import pprint
from time import perf_counter

from app.collectors.tiktok_http import collect_tiktok_http
from app.collectors.tiktok_browser import collect_tiktok_browser


TEST_URL = (
    "https://www.tiktok.com/"
    "@kimchungphan20/"
    "video/7614484260753345812"
)


print()
print("=" * 80)
print("TIKTOK COLLECTOR V2")
print("=" * 80)

print()
print("LINK:")
print(TEST_URL)

start = perf_counter()


# ============================================================
# 1. FAST HTTP
# ============================================================

print()
print("-" * 80)
print("BUOC 1: FAST HTTP COLLECTOR")
print("-" * 80)

result = collect_tiktok_http(
    TEST_URL
)


# ============================================================
# 2. BROWSER FALLBACK
# ============================================================

if result.status == "CAN_BROWSER_FALLBACK":

    print()
    print(
        "HTTP khong co du lieu. "
        "Chuyen sang Browser..."
    )

    print()
    print("-" * 80)
    print("BUOC 2: BROWSER FALLBACK")
    print("-" * 80)

    result = collect_tiktok_browser(
        TEST_URL,
        headless=True,
    )


elapsed = perf_counter() - start


# ============================================================
# OUTPUT
# ============================================================

print()
print("=" * 80)
print("KET QUA CUOI CUNG")
print("=" * 80)

pprint(
    result.to_dict(),
    sort_dicts=False,
)

print()
print(
    "THOI GIAN:",
    f"{elapsed:.2f} giay",
)

print()