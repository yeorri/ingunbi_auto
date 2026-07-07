"""CDP로 붙어 현재 화면 덤프 — browse.py가 띄운 Chromium 검사용.

사용:
  python tools/peek.py                 # 모든 탭: URL/제목 + 본문 텍스트 요약
  python tools/peek.py --shot out.png  # 첫 탭(또는 --url 매칭 탭) 스크린샷
  python tools/peek.py --url wetax     # URL에 문자열이 든 탭만
  python tools/peek.py --links         # 보이는 링크/버튼 텍스트 목록
  python tools/peek.py --html out.html # 페이지 HTML 저장
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")  # PowerShell cp949 콘솔에서 한글 깨짐 방지

from playwright.async_api import async_playwright

CDP = "http://localhost:9222"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="URL 부분 문자열로 탭 필터")
    ap.add_argument("--shot", default="", help="스크린샷 저장 경로(png)")
    ap.add_argument("--html", default="", help="HTML 저장 경로")
    ap.add_argument("--links", action="store_true", help="보이는 링크/버튼 텍스트 나열")
    ap.add_argument("--text", action="store_true", help="본문 전체 텍스트 출력")
    args = ap.parse_args()

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP)
        pages = [p for c in browser.contexts for p in c.pages]
        if args.url:
            pages = [p for p in pages if args.url in (p.url or "")]
        if not pages:
            print("[!] 대상 탭 없음")
            return
        for i, page in enumerate(pages):
            print(f"\n===== 탭 {i}: {await page.title()} =====")
            print(f"URL: {page.url}")
            if args.shot and i == 0:
                await page.screenshot(path=args.shot, full_page=False)
                print(f"[v] 스크린샷: {args.shot}")
            if args.html and i == 0:
                content = await page.content()
                with open(args.html, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"[v] HTML 저장: {args.html} ({len(content)}자)")
            if args.links:
                items = await page.evaluate("""() => {
                    const out=[];
                    for(const e of document.querySelectorAll('a,button,input[type=button],input[type=submit]')){
                        const r=e.getBoundingClientRect();
                        if(r.width<2||r.height<2) continue;
                        const t=(e.innerText||e.value||e.title||'').trim().replace(/\\s+/g,' ');
                        if(t) out.push({t, href:(e.getAttribute('href')||e.getAttribute('onclick')||'').slice(0,120)});
                    }
                    return out;
                }""")
                for it in items:
                    print(f"  [{it['t']}]  {it['href']}")
            if args.text:
                body = await page.evaluate("() => document.body ? document.body.innerText : ''")
                print(body[:8000])
            if not (args.links or args.text or args.shot or args.html):
                body = await page.evaluate("() => document.body ? document.body.innerText : ''")
                print(body[:1500])


if __name__ == "__main__":
    asyncio.run(main())
