import asyncio
from time import perf_counter

from app.collectors.tiktok_batch import (
    TikTokBatchCollector,
)


URLS = [
    "https://www.tiktok.com/@kimchungphan20/video/7614484260753345812",

    "https://www.tiktok.com/@luumaianh_/video/7616261799037373703",

    "https://www.tiktok.com/@thanhtuvi555/video/7613370944869977364",

    "https://www.tiktok.com/@giangskincare_/video/7613000093448408338",

    "https://www.tiktok.com/@thaovan088_/video/7612981216257608981",

    "https://www.tiktok.com/@meimi_spt01/video/7618579301566287124",

    "https://www.tiktok.com/@nemlemdep99/video/7615579859720408340",

    "https://www.tiktok.com/@maikamereview/video/7613971835893320967",

    "https://www.tiktok.com/@miamatmoc/video/7617487850875014416",

    "https://www.tiktok.com/@ig.khalac248/video/7615987489454492948",
]


async def main():

    print()
    print("=" * 80)
    print("TIKTOK BATCH TEST")
    print("=" * 80)

    print(
        f"So link: {len(URLS)}"
    )

    collector = TikTokBatchCollector(
        concurrency=5,
        headless=True,
    )

    start = perf_counter()

    results = await collector.collect_many(
        URLS
    )

    total_time = (
        perf_counter()
        - start
    )

    print()
    print("=" * 80)
    print("KET QUA")
    print("=" * 80)

    success = 0

    for i, r in enumerate(
        results,
        start=1,
    ):

        if r.status == "THANH_CONG":
            success += 1

        engagement = None

        if r.view:

            engagement = (
                (
                    (r.like or 0)
                    + (r.comment or 0)
                    + (r.share or 0)
                )
                / r.view
                * 100
            )

        print()
        print(
            f"{i:02d}. "
            f"@{r.username}"
        )

        print(
            "    Status :",
            r.status,
        )

        print(
            "    View   :",
            r.view,
        )

        print(
            "    Like   :",
            r.like,
        )

        print(
            "    Cmt    :",
            r.comment,
        )

        print(
            "    Share  :",
            r.share,
        )

        print(
            "    Save   :",
            r.save,
        )

        if engagement is not None:

            print(
                "    ER     :",
                f"{engagement:.2f}%",
            )

    print()
    print("=" * 80)

    print(
        "Thanh cong:",
        f"{success}/{len(URLS)}",
    )

    print(
        "Tong thoi gian:",
        f"{total_time:.2f} giay",
    )

    print(
        "Trung binh:",
        f"{total_time / len(URLS):.2f} giay/video",
    )

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())