import asyncio
from time import perf_counter

from app.collectors.tiktok_batch import (
    TikTokBatchCollector,
)


URLS = [
    (
        "https://www.tiktok.com/"
        "@sooi.unbox/"
        "video/7616723178567617813"
    )
]


async def main():

    print()
    print("=" * 80)
    print("TEST VIDEO DANG BI LOI")
    print("=" * 80)

    collector = (
        TikTokBatchCollector(
            concurrency=1,
            headless=True,
        )
    )

    start = perf_counter()

    results = (
        await collector.collect_many(
            URLS
        )
    )

    elapsed = (
        perf_counter()
        - start
    )

    for result in results:

        print()
        print("=" * 80)

        print(
            "URL       :",
            result.normalized_url,
        )

        print(
            "Video ID  :",
            result.video_id,
        )

        print(
            "Username  :",
            result.username,
        )

        print(
            "Uploader  :",
            result.uploader,
        )

        print(
            "Title     :",
            result.title,
        )

        print(
            "Release   :",
            result.release_time,
        )

        print(
            "View      :",
            result.view,
        )

        print(
            "Like      :",
            result.like,
        )

        print(
            "Comment   :",
            result.comment,
        )

        print(
            "Share     :",
            result.share,
        )

        print(
            "Save      :",
            result.save,
        )

        print(
            "Status    :",
            result.status,
        )

        print(
            "Collector :",
            result.collector,
        )

        if result.view:

            engagement = (
                (
                    (result.like or 0)
                    + (result.comment or 0)
                    + (result.share or 0)
                )
                / result.view
                * 100
            )

            engagement_save = (
                (
                    (result.like or 0)
                    + (result.comment or 0)
                    + (result.share or 0)
                    + (result.save or 0)
                )
                / result.view
                * 100
            )

            print(
                "ER        :",
                f"{engagement:.2f}%"
            )

            print(
                "ER + Save :",
                f"{engagement_save:.2f}%"
            )

        print(
            "Time      :",
            f"{elapsed:.2f}s"
        )

        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())