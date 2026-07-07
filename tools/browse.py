"""개발용 브라우저 실행 — 영구 프로필 Chromium + CDP 포트.

라이브 화면 탐색(셀렉터 확정)용. 사용자가 이 창에서 로그인/이동하고,
inspect.py가 CDP(localhost:9222)로 붙어 현재 화면을 덤프한다.

실행:  python tools/browse.py [시작URL]
종료:  창 닫기 또는 Ctrl+C
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from automation.browser import PROFILE_DIR

CDP_PORT = 9222


async def main():
    start_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.wetax.go.kr"
    PROFILE_DIR.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                f"--remote-debugging-port={CDP_PORT}",
            ],
            accept_downloads=True,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[!] 시작 URL 이동 실패: {e}")
        print(f"[i] 브라우저 실행됨 (CDP :{CDP_PORT}). 창을 닫으면 종료됩니다.")
        while ctx.pages:
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
