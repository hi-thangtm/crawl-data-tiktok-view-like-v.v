import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Callable, Optional

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from app.models import TikTokProfileResult
from app.session_manager import (
    SESSION_STATE_FILE,
)
from app.utils.url_parser import (
    parse_tiktok_channel_input,
    TikTokChannelInput,
)
from app.collectors.tiktok_batch import StartGate
from app.collectors.tiktok_profile_http import (
    collect_profile_http,
    extract_profile_from_html,
    find_user_info_struct,
    build_profile_result_from_data,
)


PROFILE_RETRYABLE_STATUSES = {
    "CAN_RETRY",
    "TIMEOUT",
    "NETWORK_ERROR",
    "CAN_BROWSER_FALLBACK",
}


class TikTokProfileBatchCollector:
    """
    Batch Collector thu thap thong tin kenh TikTok.
    - Uu tien Fast HTTP de toi uu toc do.
    - Tu dong fallback sang Playwright Browser neu HTTP bi chan/thieu JSON.
    - Concurrency mac dinh = 2 (tuy bien duoc).
    - Rate limiting qua StartGate de tranh bi block.
    - Ho tro cooperative cancellation khi nguoi dung nhan Dung.
    """

    def __init__(
        self,
        concurrency: int = 2,
        retry_concurrency: int = 1,
        start_interval: float = 0.5,
        retry_start_interval: float = 1.2,
        cooldown_403: float = 12.0,
        retry_delay: float = 5.0,
        headless: bool = True,
        result_callback: Optional[Callable[[TikTokProfileResult, bool], None]] = None,
    ):
        self.concurrency = concurrency
        self.retry_concurrency = retry_concurrency
        self.start_interval = start_interval
        self.retry_start_interval = retry_start_interval
        self.cooldown_403 = cooldown_403
        self.retry_delay = retry_delay
        self.headless = headless
        self.result_callback = result_callback

        self._cancelled = False

    def cancel(self):
        """Yeu cau dung tien trinh thu thap."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def should_retry(self, result: TikTokProfileResult) -> bool:
        return result.status in PROFILE_RETRYABLE_STATUSES

    async def create_browser_context(self, browser):
        kwargs = {
            "viewport": {
                "width": 1280,
                "height": 800,
            },
            "locale": "vi-VN",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "extra_http_headers": {
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        }

        if SESSION_STATE_FILE.exists():
            kwargs["storage_state"] = str(SESSION_STATE_FILE)

        return await browser.new_context(**kwargs)

    async def detect_browser_page_status(self, page) -> str | None:
        """Kiem tra text hien thi de phat hien trang thai khong binh thuong."""
        try:
            body_text = await page.locator("body").inner_text(timeout=2500)
            text = " ".join(body_text.lower().split())
        except Exception:
            return None

        # Captcha / Verification
        challenge_phrases = [
            "captcha",
            "verify to continue",
            "security verification",
            "xác minh để tiếp tục",
        ]
        for phrase in challenge_phrases:
            if phrase in text:
                return "CAPTCHA_REQUIRED"

        # Not found
        not_found_phrases = [
            "couldn't find this account",
            "could not find this account",
            "không tìm thấy tài khoản",
            "không thể tìm thấy tài khoản",
            "user not found",
        ]
        for phrase in not_found_phrases:
            if phrase in text:
                return "NOT_FOUND"

        # Private
        private_phrases = [
            "this account is private",
            "tài khoản này là riêng tư",
        ]
        for phrase in private_phrases:
            if phrase in text:
                return "PRIVATE"

        # Session expired / Login redirect
        login_phrases = [
            "log in to tiktok",
            "đăng nhập vào tiktok",
        ]
        try:
            url_lower = (page.url or "").lower()
            if "/login" in url_lower or "login?" in url_lower:
                return "SESSION_EXPIRED"
        except Exception:
            pass

        return None

    async def collect_one_browser(
        self,
        context,
        channel: TikTokChannelInput,
        gate: StartGate,
    ) -> TikTokProfileResult:
        """Fallback qua trinh duyet Playwright."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = TikTokProfileResult(
            input_url=channel.raw_input,
            profile_url=channel.normalized_url,
            username=channel.username,
            collected_at=now_str,
            source_method="BROWSER",
        )

        page = await context.new_page()
        try:
            await gate.wait_turn()
            if self._cancelled:
                result.status = "CANCELLED"
                return result

            response = await page.goto(
                channel.normalized_url,
                wait_until="domcontentloaded",
                timeout=18000,
            )

            status_code = response.status if response else None
            if status_code in {403, 429}:
                await gate.report_403()
                result.status = "RATE_LIMITED"
                result.error_message = f"Browser nhận HTTP {status_code}"
                return result

            if status_code == 404:
                result.status = "NOT_FOUND"
                result.error_message = "HTTP 404 Not Found"
                return result

            await gate.report_ok()

            # Cho rehydration script
            try:
                await page.wait_for_selector(
                    "script#__UNIVERSAL_DATA_FOR_REHYDRATION__",
                    state="attached",
                    timeout=3000,
                )
            except PlaywrightTimeoutError:
                pass

            # Kiem tra status text
            detected_status = await self.detect_browser_page_status(page)
            if detected_status:
                result.status = detected_status
                if detected_status == "NOT_FOUND":
                    result.error_message = "Không tìm thấy hồ sơ hoặc tài khoản đã bị khóa"
                elif detected_status == "CAPTCHA_REQUIRED":
                    result.error_message = "TikTok yêu cầu xác minh Captcha"
                elif detected_status == "PRIVATE":
                    result.private_account = True
                    result.status = "PRIVATE"
                elif detected_status == "SESSION_EXPIRED":
                    result.error_message = "Phiên đăng nhập TikTok đã hết hạn"
                return result

            # Thu parse tu script rehydration
            locator = page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__")
            if await locator.count() > 0:
                try:
                    json_str = await locator.first.text_content()
                    if json_str:
                        data = json.loads(json_str, strict=False)
                        u, s2, s, src = find_user_info_struct(data, expected_username=channel.username)
                        if u:
                            return build_profile_result_from_data(
                                input_url=channel.raw_input,
                                normalized_url=channel.normalized_url,
                                user_node=u,
                                stats_v2=s2,
                                stats_node=s,
                                source_method=f"BROWSER/{src or 'UNIVERSAL_DATA'}",
                                target_username=channel.username,
                            )
                except Exception:
                    pass

            # Thu parse toan bo html cua page
            try:
                html = await page.content()
                u, s2, s, src = extract_profile_from_html(
                    html,
                    expected_username=channel.username,
                )
                if u:
                    return build_profile_result_from_data(
                        input_url=channel.raw_input,
                        normalized_url=channel.normalized_url,
                        user_node=u,
                        stats_v2=s2,
                        stats_node=s,
                        source_method=f"BROWSER/{src or 'HTML'}",
                        target_username=channel.username,
                    )
            except Exception:
                pass

            # Kiem tra lai text status sau khi render
            detected_status = await self.detect_browser_page_status(page)
            if detected_status:
                result.status = detected_status
                return result

            result.status = "CAN_RETRY"
            result.error_message = "Không tìm thấy cấu trúc JSON hồ sơ trong Browser"
            return result

        except PlaywrightTimeoutError:
            result.status = "TIMEOUT"
            result.error_message = "Browser timeout khi tải trang"
            return result
        except Exception as exc:
            result.status = "NETWORK_ERROR"
            result.error_message = f"{type(exc).__name__}: {exc}"
            return result
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def collect_one(
        self,
        channel: TikTokChannelInput,
        context,
        semaphore: asyncio.Semaphore,
        gate: StartGate,
        retry_mode: bool = False,
    ) -> TikTokProfileResult:
        """
        Xu ly 1 kenh TikTok:
        1. Kiem tra hop le
        2. Chay Fast HTTP
        3. Neu can, chay Browser fallback
        4. Thong bao callback cho GUI
        """
        async with semaphore:
            try:
                if self._cancelled:
                    return TikTokProfileResult(
                        input_url=channel.raw_input,
                        profile_url=channel.normalized_url,
                        username=channel.username,
                        status="CANCELLED",
                        error_message="Người dùng đã dừng tiến trình",
                    )

                # 1. Kiem tra tinh hop le cua input
                if not channel.valid:
                    res = TikTokProfileResult(
                        input_url=channel.raw_input,
                        profile_url=channel.normalized_url,
                        username=channel.username,
                        status=channel.status,
                        error_message=f"Đầu vào không hợp lệ ({channel.status})",
                    )
                    if self.result_callback:
                        try:
                            self.result_callback(res, retry_mode)
                        except Exception:
                            pass
                    return res

                # 2. Fast HTTP attempt truoc (chay trong thread pool de khong block loop)
                await gate.wait_turn()
                if self._cancelled:
                    return TikTokProfileResult(
                        input_url=channel.raw_input,
                        profile_url=channel.normalized_url,
                        username=channel.username,
                        status="CANCELLED",
                        error_message="Người dùng đã dừng tiến trình",
                    )

                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(None, collect_profile_http, channel)

                # Neu HTTP lay duoc du lieu hoac xac dinh ro NOT_FOUND / PRIVATE
                if res.status in {"SUCCESS", "PARTIAL", "NOT_FOUND", "PRIVATE"}:
                    await gate.report_ok()
                    if self.result_callback:
                        try:
                            self.result_callback(res, retry_mode)
                        except Exception:
                            pass
                    return res

                # Neu HTTP bi 403 hoac khong co JSON, fallback qua Browser
                if self._cancelled:
                    return TikTokProfileResult(
                        input_url=channel.raw_input,
                        profile_url=channel.normalized_url,
                        username=channel.username,
                        status="CANCELLED",
                        error_message="Người dùng đã dừng tiến trình",
                    )

                if context is not None:
                    browser_res = await self.collect_one_browser(
                        context=context,
                        channel=channel,
                        gate=gate,
                    )
                    # Neu browser tra ve thanh cong hoac co trang thai ro rang hon
                    if browser_res.status in {"SUCCESS", "PARTIAL", "NOT_FOUND", "PRIVATE", "CAPTCHA_REQUIRED", "SESSION_EXPIRED"}:
                        res = browser_res
                    elif browser_res.status != "CAN_RETRY":
                        res = browser_res

                if self.result_callback:
                    try:
                        self.result_callback(res, retry_mode)
                    except Exception:
                        pass

                return res
            except Exception as exc:
                err_res = TikTokProfileResult(
                    input_url=channel.raw_input,
                    profile_url=channel.normalized_url,
                    username=channel.username,
                    status="UNEXPECTED_ERROR",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                if self.result_callback:
                    try:
                        self.result_callback(err_res, retry_mode)
                    except Exception:
                        pass
                return err_res

    async def collect_many(
        self,
        channels: list[TikTokChannelInput],
    ) -> list[TikTokProfileResult]:
        """
        Chay thu thap danh sach kenh (Pass 1 + Retry Pass neu can).
        """
        self._cancelled = False
        gate = StartGate(
            min_interval=self.start_interval,
            cooldown_403=self.cooldown_403,
        )

        semaphore = asyncio.Semaphore(self.concurrency)

        results_by_url: dict[str, TikTokProfileResult] = {}

        # Khoi tao Playwright browser dung chung
        async with async_playwright() as p:
            browser = None
            context = None
            try:
                try:
                    browser = await p.chromium.launch(
                        channel="chrome",
                        headless=self.headless,
                    )
                except Exception:
                    browser = await p.chromium.launch(
                        headless=self.headless,
                    )

                context = await self.create_browser_context(browser)

                # ====================================================
                # PASS 1: FAST RUN
                # ====================================================
                tasks = [
                    self.collect_one(
                        channel=ch,
                        context=context,
                        semaphore=semaphore,
                        gate=gate,
                        retry_mode=False,
                    )
                    for ch in channels
                ]

                pass1_results = await asyncio.gather(*tasks, return_exceptions=True)
                for ch, r in zip(channels, pass1_results):
                    if isinstance(r, Exception):
                        r = TikTokProfileResult(
                            input_url=ch.raw_input,
                            profile_url=ch.normalized_url,
                            username=ch.username,
                            status="UNEXPECTED_ERROR",
                            error_message=f"{type(r).__name__}: {r}",
                        )
                    results_by_url[r.input_url] = r

                # ====================================================
                # PASS 2: RETRY RUN (neu co kenh bi loi retry duoc va chua bi cancel)
                # ====================================================
                if not self._cancelled:
                    retry_channels = [
                        ch for ch in channels
                        if ch.valid and self.should_retry(results_by_url.get(ch.raw_input, None))
                    ]

                    if retry_channels:
                        print(f"[PROFILE] Bắt đầu thử lại cho {len(retry_channels)} kênh...")
                        await asyncio.sleep(self.retry_delay)

                        retry_gate = StartGate(
                            min_interval=self.retry_start_interval,
                            cooldown_403=self.cooldown_403,
                        )
                        retry_semaphore = asyncio.Semaphore(self.retry_concurrency)

                        retry_tasks = [
                            self.collect_one(
                                channel=ch,
                                context=context,
                                semaphore=retry_semaphore,
                                gate=retry_gate,
                                retry_mode=True,
                            )
                            for ch in retry_channels
                        ]

                        pass2_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
                        for ch, r in zip(retry_channels, pass2_results):
                            if isinstance(r, Exception):
                                r = TikTokProfileResult(
                                    input_url=ch.raw_input,
                                    profile_url=ch.normalized_url,
                                    username=ch.username,
                                    status="UNEXPECTED_ERROR",
                                    error_message=f"{type(r).__name__}: {r}",
                                )
                            results_by_url[r.input_url] = r

            finally:
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass

        # Tra ve theo thu tu ban dau
        return [
            results_by_url.get(ch.raw_input, TikTokProfileResult(input_url=ch.raw_input, status="CHUA_XU_LY"))
            for ch in channels
        ]
