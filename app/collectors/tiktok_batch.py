import asyncio
import json
import time

from datetime import datetime
from pathlib import Path
from time import perf_counter

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.models import VideoResult
from app.session_manager import (
    SESSION_STATE_FILE,
    SESSION_READY,
    inspect_session_local,
)
from app.utils.url_parser import parse_tiktok_url

from app.collectors.tiktok_http import (
    find_item_struct,
    extract_json_from_html,
    get_author_data,
    format_release_time,
    to_int,
)


# ============================================================
# CONFIG
# ============================================================

STATE_FILE = SESSION_STATE_FILE


RETRYABLE_STATUSES = {
    "CAN_RETRY",
    "CAN_RETRY_403",
    "TAM_BI_GIOI_HAN_403",
    "TIMEOUT",
}


# ============================================================
# DEBUG
# ============================================================

def save_debug_html(
    video_id: str,
    html: str,
    suffix: str,
):
    debug_dir = Path(
        "data/debug"
    )

    debug_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        debug_dir
        / f"{video_id}_{suffix}.html"
    )

    try:
        path.write_text(
            html,
            encoding="utf-8",
        )
    except Exception:
        pass


# ============================================================
# RATE GATE
# ============================================================

class StartGate:
    """
    Giam burst request khi chay batch.

    - Giu khoang cach toi thieu giua cac lan bat dau URL.
    - Neu gap nhieu 403 lien tiep thi cooldown.
    """

    def __init__(
        self,
        min_interval: float,
        cooldown_403: float,
    ):
        self.min_interval = (
            min_interval
        )

        self.cooldown_403 = (
            cooldown_403
        )

        self.lock = asyncio.Lock()

        self.last_start = 0.0

        self.pause_until = 0.0

        self.consecutive_403 = 0

    async def wait_turn(
        self,
    ):
        async with self.lock:
            now = time.monotonic()

            if now < self.pause_until:
                wait_time = (
                    self.pause_until
                    - now
                )

                print(
                    f"[GATE] Cooldown "
                    f"{wait_time:.1f}s"
                )

                await asyncio.sleep(
                    wait_time
                )

            now = time.monotonic()

            elapsed = (
                now
                - self.last_start
            )

            if (
                self.last_start > 0
                and elapsed
                < self.min_interval
            ):
                await asyncio.sleep(
                    self.min_interval
                    - elapsed
                )

            self.last_start = (
                time.monotonic()
            )

    async def report_403(
        self,
    ):
        async with self.lock:
            self.consecutive_403 += 1

            if self.consecutive_403 >= 2:
                self.pause_until = (
                    time.monotonic()
                    + self.cooldown_403
                )

                print()
                print(
                    "[GATE] Phat hien nhieu HTTP 403."
                )

                print(
                    f"[GATE] Tam nghi "
                    f"{self.cooldown_403:.0f}s."
                )

                self.consecutive_403 = 0

    async def report_ok(
        self,
    ):
        async with self.lock:
            self.consecutive_403 = 0


# ============================================================
# TIKTOK BATCH COLLECTOR
# ============================================================

class TikTokBatchCollector:

    def __init__(
        self,
        concurrency: int = 3,
        retry_concurrency: int = 1,
        start_interval: float = 0.45,
        retry_start_interval: float = 1.0,
        cooldown_403: float = 12.0,
        retry_delay: float = 6.0,
        headless: bool = True,
    ):
        self.concurrency = (
            concurrency
        )

        self.retry_concurrency = (
            retry_concurrency
        )

        self.start_interval = (
            start_interval
        )

        self.retry_start_interval = (
            retry_start_interval
        )

        self.cooldown_403 = (
            cooldown_403
        )

        self.retry_delay = (
            retry_delay
        )

        self.headless = (
            headless
        )

    # ========================================================
    # RETRY DECISION
    # ========================================================

    def should_retry_result(
        self,
        result,
    ) -> bool:
        status = (
            result.status
            or ""
        )

        if status in RETRYABLE_STATUSES:
            return True

        if status.startswith(
            "LOI:"
        ):
            return True

        return False

    # ========================================================
    # CONTEXT
    # ========================================================

    async def create_context(
        self,
        browser,
    ):
        kwargs = {
            "viewport": {
                "width": 1280,
                "height": 800,
            },
            "locale": "vi-VN",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "extra_http_headers": {
                "Accept-Language": (
                    "vi-VN,vi;q=0.9,"
                    "en-US;q=0.8,en;q=0.7"
                ),
            },
        }

        if STATE_FILE.exists():
            kwargs[
                "storage_state"
            ] = str(
                STATE_FILE
            )
        else:
            print()
            print(
                "[CANH BAO] "
                "Chua co TikTok session."
            )

            print(
                "[CANH BAO] "
                "Nguoi dung can dang nhap TikTok trong tool truoc."
            )

        return await browser.new_context(
            **kwargs
        )

    # ========================================================
    # SESSION STATUS
    # ========================================================

    async def detect_session_expired(
        self,
        page,
    ) -> bool:
        """
        Detect a real TikTok login redirect/form.

        HTTP 403 is intentionally NOT treated as an expired session because
        TikTok can return temporary 403 responses while the login is still
        valid.
        """
        try:
            current_url = (
                page.url
                or ""
            ).lower()
        except Exception:
            current_url = ""

        if (
            "/login" in current_url
            or "login?" in current_url
            or "/signup" in current_url
        ):
            return True

        # Only use visible login-form controls as a fallback. Generic text
        # such as "Log in" is not enough because public TikTok pages can
        # show login buttons even when video data is available.
        try:
            password_inputs = page.locator(
                'input[type="password"]'
            )

            count = await password_inputs.count()

            for index in range(
                min(count, 3)
            ):
                try:
                    if await password_inputs.nth(
                        index
                    ).is_visible():
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        return False

    # ========================================================
    # VISIBLE STATUS
    # ========================================================

    async def detect_visible_status(
        self,
        page,
    ) -> str:
        try:
            body_text = (
                await page.locator(
                    "body"
                ).inner_text(
                    timeout=2500
                )
            )

            normalized = (
                " ".join(
                    body_text
                    .lower()
                    .split()
                )
            )
        except Exception:
            return "CAN_RETRY"

        unavailable_texts = [
            "video hiện không khả dụng",
            "video không khả dụng",
            "this video is unavailable",
            "video currently unavailable",
            "couldn't find this video",
            "could not find this video",
        ]

        for phrase in unavailable_texts:
            if phrase in normalized:
                return (
                    "VIDEO_KHONG_KHA_DUNG"
                )

        private_texts = [
            "this video is private",
            "this account is private",
            "video này là riêng tư",
            "tài khoản này là riêng tư",
        ]

        for phrase in private_texts:
            if phrase in normalized:
                return (
                    "VIDEO_RIENG_TU"
                )

        challenge_texts = [
            "captcha",
            "verify to continue",
            "security verification",
            "xác minh để tiếp tục",
        ]

        for phrase in challenge_texts:
            if phrase in normalized:
                return (
                    "ACCESS_CHALLENGE"
                )

        return "CAN_RETRY"

    # ========================================================
    # RESULT MAPPING
    # ========================================================

    def fill_result(
        self,
        result: VideoResult,
        parsed,
        item: dict,
        source: str,
    ) -> VideoResult:
        stats = (
            item.get("stats")
            or item.get("statsV2")
            or {}
        )

        (
            username,
            uploader,
        ) = get_author_data(
            item
        )

        result.title = (
            item.get("desc")
            or item.get("title")
            or ""
        )

        result.username = (
            username
            or parsed.username
        )

        result.uploader = (
            uploader
            or result.username
        )

        result.release_time = (
            format_release_time(
                item.get(
                    "createTime"
                )
                or item.get(
                    "create_time"
                )
            )
        )

        result.view = to_int(
            stats.get(
                "playCount"
            )
        )

        result.like = to_int(
            stats.get(
                "diggCount"
            )
        )

        result.comment = to_int(
            stats.get(
                "commentCount"
            )
        )

        result.share = to_int(
            stats.get(
                "shareCount"
            )
        )

        if (
            stats.get(
                "collectCount"
            )
            is not None
        ):
            result.save = to_int(
                stats.get(
                    "collectCount"
                )
            )

        elif (
            stats.get(
                "saveCount"
            )
            is not None
        ):
            result.save = to_int(
                stats.get(
                    "saveCount"
                )
            )

        elif (
            stats.get(
                "favoriteCount"
            )
            is not None
        ):
            result.save = to_int(
                stats.get(
                    "favoriteCount"
                )
            )

        result.status = (
            "THANH_CONG"
        )

        result.collector = (
            f"BROWSER/{source}"
        )

        return result

    # ========================================================
    # UNIVERSAL DATA
    # ========================================================

    async def try_universal(
        self,
        page,
        video_id: str,
    ):
        locator = page.locator(
            "script#__UNIVERSAL_DATA_FOR_REHYDRATION__"
        )

        try:
            if (
                await locator.count()
                == 0
            ):
                return (
                    None,
                    None,
                )

            json_text = (
                await locator
                .first
                .text_content()
            )

            if not json_text:
                return (
                    None,
                    None,
                )

            data = json.loads(
                json_text
            )

            item = find_item_struct(
                data,
                expected_video_id=(
                    video_id
                ),
            )

            if item:
                return (
                    item,
                    "UNIVERSAL_DATA",
                )

        except Exception:
            pass

        return (
            None,
            None,
        )

    # ========================================================
    # FULL HTML
    # ========================================================

    async def try_html(
        self,
        page,
        video_id: str,
    ):
        try:
            html = (
                await page.content()
            )
        except Exception:
            return (
                None,
                None,
                "",
            )

        try:
            (
                item,
                source,
            ) = extract_json_from_html(
                html,
                video_id,
            )
        except Exception:
            item = None
            source = None

        return (
            item,
            source,
            html,
        )

    # ========================================================
    # COLLECT ONE
    # ========================================================

    async def collect_one(
        self,
        context,
        url: str,
        semaphore,
        gate,
        retry_mode: bool = False,
    ) -> VideoResult:
        async with semaphore:
            start = perf_counter()

            parsed = (
                parse_tiktok_url(
                    url
                )
            )

            result = VideoResult(
                link=url,
                retrieval_time=(
                    datetime.now()
                    .strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                ),
            )

            if not parsed.valid:
                result.status = (
                    parsed.status
                )

                return result

            result.video_id = (
                parsed.video_id
            )

            result.username = (
                parsed.username
            )

            result.normalized_url = (
                parsed.normalized_url
            )

            result.collector = (
                "BROWSER"
            )

            page = (
                await context.new_page()
            )

            last_html = ""

            try:
                await gate.wait_turn()

                response = (
                    await page.goto(
                        parsed.normalized_url,
                        wait_until=(
                            "domcontentloaded"
                        ),
                        timeout=15000,
                    )
                )

                response_status = (
                    response.status
                    if response
                    else None
                )

                if await self.detect_session_expired(
                    page
                ):
                    result.status = (
                        "SESSION_HET_HAN"
                    )

                    return result

                if response_status == 403:
                    result.status = (
                        "TAM_BI_GIOI_HAN_403"
                    )

                    await gate.report_403()

                    return result

                await gate.report_ok()

                try:
                    await page.wait_for_selector(
                        (
                            "script#"
                            "__UNIVERSAL_DATA_FOR_REHYDRATION__"
                        ),
                        state="attached",
                        timeout=2500,
                    )
                except PlaywrightTimeoutError:
                    pass

                visible_status = (
                    await self.detect_visible_status(
                        page
                    )
                )

                if visible_status in {
                    "VIDEO_KHONG_KHA_DUNG",
                    "VIDEO_RIENG_TU",
                    "ACCESS_CHALLENGE",
                }:
                    result.status = (
                        visible_status
                    )

                    return result

                (
                    item,
                    source,
                ) = await self.try_universal(
                    page,
                    parsed.video_id,
                )

                if not item:
                    (
                        item,
                        source,
                        last_html,
                    ) = await self.try_html(
                        page,
                        parsed.video_id,
                    )

                if not item:
                    await page.wait_for_timeout(
                        700
                    )

                    (
                        item,
                        source,
                        last_html,
                    ) = await self.try_html(
                        page,
                        parsed.video_id,
                    )

                if item:
                    return self.fill_result(
                        result=result,
                        parsed=parsed,
                        item=item,
                        source=(
                            source
                            or "UNKNOWN"
                        ),
                    )

                if await self.detect_session_expired(
                    page
                ):
                    result.status = (
                        "SESSION_HET_HAN"
                    )

                    return result

                visible_status = (
                    await self.detect_visible_status(
                        page
                    )
                )

                if visible_status != "CAN_RETRY":
                    result.status = (
                        visible_status
                    )
                else:
                    result.status = (
                        "CAN_RETRY"
                    )

                if not last_html:
                    try:
                        last_html = (
                            await page.content()
                        )
                    except Exception:
                        last_html = ""

                if last_html:
                    save_debug_html(
                        parsed.video_id,
                        last_html,
                        (
                            "retry_failed"
                            if retry_mode
                            else "batch_failed"
                        ),
                    )

                return result

            except PlaywrightTimeoutError:
                result.status = (
                    "TIMEOUT"
                )

                return result

            except Exception as exc:
                result.status = (
                    "LOI:"
                    + type(exc).__name__
                )

                print(
                    f"[{parsed.video_id}] "
                    f"{repr(exc)}"
                )

                return result

            finally:
                elapsed = (
                    perf_counter()
                    - start
                )

                mode = (
                    "RETRY"
                    if retry_mode
                    else "FAST"
                )

                print(
                    f"[{mode}] "
                    f"[{parsed.video_id}] "
                    f"{result.status} "
                    f"- {elapsed:.2f}s"
                )

                try:
                    await page.close()
                except Exception:
                    pass

    # ========================================================
    # RUN PASS
    # ========================================================

    async def run_pass(
        self,
        context,
        urls,
        concurrency,
        gate,
        retry_mode,
    ):
        semaphore = (
            asyncio.Semaphore(
                concurrency
            )
        )

        tasks = [
            self.collect_one(
                context=context,
                url=url,
                semaphore=semaphore,
                gate=gate,
                retry_mode=retry_mode,
            )
            for url in urls
        ]

        return await asyncio.gather(
            *tasks
        )

    # ========================================================
    # COLLECT MANY
    # ========================================================

    async def collect_many(
        self,
        urls,
    ):
        session_status, _ = inspect_session_local()

        if session_status != SESSION_READY:
            results = []

            for url in urls:
                parsed = parse_tiktok_url(
                    url
                )

                result = VideoResult(
                    link=url,
                    retrieval_time=(
                        datetime.now()
                        .strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    ),
                )

                if parsed.valid:
                    result.video_id = parsed.video_id
                    result.username = parsed.username
                    result.normalized_url = parsed.normalized_url

                result.collector = "SESSION"
                result.status = "SESSION_HET_HAN"

                results.append(
                    result
                )

            return results

        async with async_playwright() as p:
            browser = (
                await p.chromium.launch(
                    channel="chrome",
                    headless=(
                        self.headless
                    ),
                )
            )

            # =================================================
            # PASS 1 - FAST
            # =================================================

            print()
            print("=" * 80)
            print(
                "PASS 1 - FAST COLLECT"
            )
            print(
                "Concurrency:",
                self.concurrency,
            )
            print(
                "Start interval:",
                self.start_interval,
            )
            print("=" * 80)

            context = (
                await self.create_context(
                    browser
                )
            )

            gate = StartGate(
                min_interval=(
                    self.start_interval
                ),
                cooldown_403=(
                    self.cooldown_403
                ),
            )

            results = (
                await self.run_pass(
                    context=context,
                    urls=urls,
                    concurrency=(
                        self.concurrency
                    ),
                    gate=gate,
                    retry_mode=False,
                )
            )

            try:
                await context.close()
            except Exception:
                pass

            # =================================================
            # PASS 2 - RETRY
            # =================================================

            retry_indexes = [
                index
                for index, result
                in enumerate(results)
                if self.should_retry_result(
                    result
                )
            ]

            if retry_indexes:
                print()
                print("=" * 80)
                print(
                    "PASS 2 - RETRY"
                )
                print(
                    "So link can retry:",
                    len(retry_indexes),
                )
                print(
                    "Cho truoc retry:",
                    f"{self.retry_delay}s",
                )
                print("=" * 80)

                await asyncio.sleep(
                    self.retry_delay
                )

                retry_urls = [
                    urls[index]
                    for index
                    in retry_indexes
                ]

                retry_context = (
                    await self.create_context(
                        browser
                    )
                )

                retry_gate = StartGate(
                    min_interval=(
                        self.retry_start_interval
                    ),
                    cooldown_403=(
                        self.cooldown_403
                    ),
                )

                retry_results = (
                    await self.run_pass(
                        context=retry_context,
                        urls=retry_urls,
                        concurrency=(
                            self.retry_concurrency
                        ),
                        gate=retry_gate,
                        retry_mode=True,
                    )
                )

                try:
                    await retry_context.close()
                except Exception:
                    pass

                for (
                    original_index,
                    retry_result,
                ) in zip(
                    retry_indexes,
                    retry_results,
                ):
                    results[
                        original_index
                    ] = retry_result

            # =================================================
            # PASS 3 - RESCUE
            # =================================================

            rescue_indexes = [
                index
                for index, result
                in enumerate(results)
                if self.should_retry_result(
                    result
                )
            ]

            if rescue_indexes:
                print()
                print("=" * 80)
                print(
                    "PASS 3 - RESCUE"
                )
                print(
                    "So link can cuu:",
                    len(rescue_indexes),
                )
                print(
                    "Moi link se duoc chay rieng "
                    "tren browser moi."
                )
                print("=" * 80)

                # Cho session / TikTok nghi truoc khi rescue.
                await asyncio.sleep(
                    8.0
                )

                rescue_urls = [
                    urls[index]
                    for index
                    in rescue_indexes
                ]

                rescue_browser = (
                    await p.chromium.launch(
                        channel="chrome",
                        headless=(
                            self.headless
                        ),
                    )
                )

                try:
                    rescue_context = (
                        await self.create_context(
                            rescue_browser
                        )
                    )

                    rescue_gate = StartGate(
                        min_interval=1.2,
                        cooldown_403=20.0,
                    )

                    rescue_results = (
                        await self.run_pass(
                            context=rescue_context,
                            urls=rescue_urls,
                            concurrency=1,
                            gate=rescue_gate,
                            retry_mode=True,
                        )
                    )

                    try:
                        await rescue_context.close()
                    except Exception:
                        pass

                    for (
                        original_index,
                        rescue_result,
                    ) in zip(
                        rescue_indexes,
                        rescue_results,
                    ):
                        results[
                            original_index
                        ] = rescue_result

                finally:
                    try:
                        await rescue_browser.close()
                    except Exception:
                        pass

            # =================================================
            # CLOSE MAIN BROWSER
            # =================================================

            try:
                await browser.close()
            except Exception:
                pass

            return results
