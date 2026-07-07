"""CDP로 붙어 간단 조작 — browse.py가 띄운 Chromium 원격 조종 (탐색용).

⚠ 탐색(이동/클릭/호버)만. 제출류 버튼은 누르지 않는다.

사용:
  python tools/act.py --goto https://...        # URL 이동
  python tools/act.py --click "특별징수"         # 보이는 요소 텍스트 클릭(첫 매칭)
  python tools/act.py --hover "신고하기"         # 호버(메가메뉴 열기)
  python tools/act.py --hover "신고하기" --click "특별징수"   # 호버 후 클릭
  python tools/act.py --url wetax ...           # URL 부분문자열로 탭 선택
실행 후 현재 URL/제목/본문 앞부분을 출력한다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

CDP = "http://localhost:9222"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="URL 부분 문자열로 탭 선택")
    ap.add_argument("--goto", default="")
    ap.add_argument("--hover", default="")
    ap.add_argument("--click", default="")
    ap.add_argument("--exact", action="store_true", help="클릭 텍스트 정확 일치")
    ap.add_argument("--wait", type=float, default=2.5, help="동작 후 대기(초)")
    args = ap.parse_args()

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP)
        pages = [p for c in browser.contexts for p in c.pages]
        if args.url:
            pages = [p for p in pages if args.url in (p.url or "")]
        if not pages:
            print("[!] 대상 탭 없음")
            return
        page = pages[0]
        await page.bring_to_front()

        if args.goto:
            await page.goto(args.goto, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(int(args.wait * 1000))
        if args.hover:
            loc = page.get_by_text(args.hover, exact=True).first
            await loc.hover(timeout=8000)
            await page.wait_for_timeout(1000)
        if args.click:
            # 보이는 첫 매칭 클릭 (frame 포함)
            clicked = False
            for frame in page.frames:
                try:
                    loc = frame.get_by_text(args.click, exact=args.exact)
                    for i in range(min(await loc.count(), 10)):
                        el = loc.nth(i)
                        if await el.is_visible():
                            await el.click(timeout=6000)
                            clicked = True
                            break
                except Exception:
                    continue
                if clicked:
                    break
            print(f"[{'v' if clicked else '!'}] 클릭 {'성공' if clicked else '실패'}: {args.click}")
            await page.wait_for_timeout(int(args.wait * 1000))

        print(f"URL: {page.url}")
        try:
            print(f"제목: {await page.title()}")
        except Exception:
            pass
        try:
            body = await page.evaluate("() => document.body ? document.body.innerText : ''")
            print(body[:2000])
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
