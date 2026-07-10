"""위택스 지방소득세 특별징수(원천세 지방분) 회계파일신고 — 내비게이션 + 단계.

파일주입/모달/검증/제출/OZ뷰어 출력 기계장치는 yangdo_auto(양도소득분 회계파일신고)에서
라이브 검증된 코드를 그대로 가져왔다.

라이브 확인됨(2026-07-03, CDP 탐색):
  - 특별징수 홈: /etr/lit/b0701/B070101M00.do (한건신고/엑셀파일신고/회계파일신고/신고내역조회)
  - 회계파일신고: /etr/lit/b0701/B070101M31.do
    단계 ①신고서업로드 → ②서식검증 및 제출 → ③제출결과확인.
    ①: 신고인 정보(자동) + '암호화 파일선택*'[파일첨부] + '파일비밀번호*' + [파일변환하기]
  - 신고내역조회 및 납부: /etr/lit/b0701/B070102M01.do
    (행: 납세자명/신고일자/과세대상/금액/납부기한/납부여부 + '출력물 보기' — 양도분과 동일 패턴)
  - 일괄(엑셀/회계)신고목록: /etr/lit/b0701/B070102M02.do
    (일괄신고ID별 검증/제출/취소/전송실패/납부 건수 — 제출 후 검증용)
  - 실무: 업체당 파일 1개씩 건별 제출(오늘 신고내역에서 확인) → 파일 목록 반복 처리

추가 확인(2026-07-06, 사용자 스크린샷):
  - [파일변환하기] 클릭 → JS confirm '업로드 하신 회계 파일의 신고정보를 검증하시겠습니까?'
    → 확인 시 B070101M32.do(서식검증 및 제출)로 전환, '정상 신고 내역 N건' 표 표시
  - 정상 내역 확인 후 [제출하기] → ③제출결과확인. 서식 오류면 오류 표시(해당 건 종료)
  - 파일 예: 20260706A103900.2 (확장자 숫자)

⚠ 남은 LIVE-TODO: 제출결과확인 화면의 완료 문구 확정, 출력물 보기 뷰어(OZ 추정) 확인.
"""
from __future__ import annotations

import asyncio
import re

from . import pdf_save

WETAX_HOME_URL = "https://www.wetax.go.kr"
WETAX_SPECIAL_HOME_URL = "https://www.wetax.go.kr/etr/lit/b0701/B070101M00.do"
WETAX_FILING_URL = "https://www.wetax.go.kr/etr/lit/b0701/B070101M31.do"   # 회계파일신고
WETAX_INQUIRY_URL = "https://www.wetax.go.kr/etr/lit/b0701/B070102M01.do"  # 신고내역조회 및 납부
WETAX_BATCH_LIST_URL = "https://www.wetax.go.kr/etr/lit/b0701/B070102M02.do"  # 일괄신고목록


async def _body(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


async def close_popups(page, log=print) -> None:
    """키보드보안 등 안내 팝업 닫기 (best-effort)."""
    for txt in ["오늘하루 그만보기", "오늘 하루 그만보기", "닫기"]:
        try:
            loc = page.get_by_text(txt, exact=False)
            for i in range(await loc.count()):
                el = loc.nth(i)
                if await el.is_visible():
                    await el.click(timeout=2000)
                    await page.wait_for_timeout(400)
        except Exception:
            pass


async def navigate_to_filing(page, log=print) -> bool:
    """특별징수 회계파일신고 화면으로 직접 URL 이동. (URL 라이브 확인됨)"""
    try:
        await page.goto(WETAX_FILING_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (위택스) goto 실패: {str(e)[:60]}")
    await close_popups(page, log)
    b = await _body(page)
    if "회계파일신고" in b and ("파일비밀번호" in b or "신고서업로드" in b):
        log("[v] (위택스) 특별징수 회계파일신고 화면 도달")
        return True
    log("[!] (위택스) 회계파일신고 화면 도달 실패")
    return False


async def inject_file(page, file_path: str, log=print) -> bool:
    """숨은 input[type=file]에 파일 직접 주입 (홈택스와 동일)."""
    for fi, frame in enumerate(page.frames):
        try:
            inp = frame.locator("input[type=file]")
            if await inp.count() > 0:
                await inp.first.set_input_files(file_path, timeout=8000)
                log(f"[v] (위택스) 파일 주입: {file_path}")
                return True
        except Exception:
            continue
    log("[!] (위택스) input[type=file]를 못 찾음")
    return False


async def fill_file_password(page, password: str, log=print) -> bool:
    """①신고서업로드 화면의 '파일비밀번호*' 입력 (라이브 확인: password 타입 입력칸)."""
    for frame in page.frames:
        try:
            pwl = frame.locator("input[type=password]")
            for i in range(await pwl.count()):
                el = pwl.nth(i)
                if await el.is_visible():
                    await el.fill(password)
                    log("[i] (위택스) 파일비밀번호 입력")
                    return True
        except Exception:
            continue
    log("[!] (위택스) 파일비밀번호 칸 못 찾음")
    return False


from .hometax import button_visible, click_button_text  # 버튼 요소만 정확 일치(검증됨)


async def _confirm_modals(page, log=print, rounds: int = 3) -> None:
    """보이는 모달의 긍정 버튼(확인/예/제출) 클릭 (best-effort)."""
    for _ in range(rounds):
        clicked = False
        for frame in page.frames:
            try:
                wins = frame.locator(".w2window, .modal, [role=dialog], .popup, .layer")
                for i in range(await wins.count()):
                    win = wins.nth(i)
                    if not await win.is_visible():
                        continue
                    btns = win.locator("a, button, input[type=button], input[type=submit]")
                    for b in range(await btns.count()):
                        el = btns.nth(b)
                        if not await el.is_visible():
                            continue
                        t = (await el.inner_text()).strip() or (await el.get_attribute("value") or "")
                        if t.strip() in ("확인", "예", "제출"):
                            await el.click()
                            await page.wait_for_timeout(1000)
                            clicked = True
                            break
                    if clicked:
                        break
                if clicked:
                    break
            except Exception:
                continue
        if not clicked:
            break


# M32 '정상 신고 내역' 표에서 (성명, 과세연월, 세액) 추출 — 주민번호는 마스킹이라 제외
_M32_ROWS_JS = """() => {
    const out = [];
    for (const row of document.querySelectorAll('tr')) {
        const cells = [...row.querySelectorAll('td')].map(td => (td.textContent || '').trim());
        if (cells.length < 6) continue;
        const ymi = cells.findIndex(c => /^20\\d\\d-\\d{2}$/.test(c));
        if (ymi < 2) continue;   // [주민(법인)번호, 성명, 과세연월, ...] 구조 확인용
        out.push({ name: cells[ymi - 1], taxym: cells[ymi],
                   amount: (cells[cells.length - 1] || '').replace(/[^0-9]/g, '') });
    }
    return out;
}"""


async def convert_and_verify(page, log=print, timeout: int = 120) -> tuple[bool, list]:
    """[파일변환하기] 클릭 → JS 확인창 자동수락 → M32 '정상 신고 내역 N건' 확인.

    반환: (통과 여부, 정상 내역 행 목록 [{name, taxym, amount}]) — 행 목록은
    '이 파일로 방금 신고한 업체 명단'으로 작업 대장에 기록된다(납부서 출력용).
    """
    if not await click_button_text(page, "파일변환하기", log):
        # 화살표 포함 표기(파일변환하기 →) 대비 폴백
        try:
            await page.get_by_text("파일변환하기", exact=False).last.click(timeout=6000)
        except Exception as e:
            log(f"[!] (위택스) '파일변환하기' 클릭 실패: {str(e)[:60]}")
            return False, []
    log("[i] (위택스) 파일변환하기 — 검증 확인창 자동수락 후 결과 대기")
    for sec in range(0, timeout, 2):
        body = await _body(page)
        m = re.search(r"정상\s*신고\s*내역\s*(\d+)\s*건", body)
        if m:
            n = int(m.group(1))
            if n < 1:
                log("[!] (위택스) 정상 신고 내역 0건 — 제출 불가")
                return False, []
            rows: list = []
            for frame in page.frames:
                try:
                    rows = await frame.evaluate(_M32_ROWS_JS)
                except Exception:
                    continue
                if rows:
                    break
            log(f"[v] (위택스) 서식검증 통과 — 정상 신고 내역 {n}건"
                + (f" ({[r['name'] for r in rows[:8]]}{' …' if len(rows) > 8 else ''})"
                   if rows else ""))
            return True, rows or []
        if "오류" in body and ("서식" in body or "오류 내역" in body or "신고 내역" in body):
            snippet = " ".join(body.split())
            idx = snippet.find("오류")
            log(f"[!] (위택스) 서식 오류: …{snippet[max(0, idx - 20):idx + 80]}…")
            return False, []
        await asyncio.sleep(2)
    log("[!] (위택스) 검증 결과 화면 미확인(시간초과)")
    return False, []


async def submit_filing(page, log=print, timeout: int = 60) -> bool:
    """서식검증 및 제출 화면(M32)에서 [제출하기] 클릭 → 제출결과확인 도달 대기.

    ⚠ 실제·비가역. 확인 다이얼로그(JS)는 자동수락. 성공 판정: 페이지 전환 +
    완료 문구(정상적으로/제출이 완료/전자납부번호/제출결과) 감지.
    """
    prev_url = page.url
    if not await click_button_text(page, "제출하기", log):
        log("[!] (위택스) '제출하기' 버튼 못 찾음")
        return False
    await page.wait_for_timeout(1500)
    await _confirm_modals(page, log)  # WebSquare식 모달이면 확인 (JS confirm은 자동수락)
    for sec in range(0, timeout, 2):
        body = await _body(page)
        if any(k in body for k in ("정상적으로", "제출이 완료", "제출되었습니다", "전자납부번호")):
            log(f"[v] (위택스) 제출 완료 ({sec}s)")
            return True
        if page.url != prev_url and "제출결과" in body:
            log(f"[v] (위택스) 제출결과 화면 도달 ({sec}s)")
            return True
        await asyncio.sleep(2)
    log("[!] (위택스) 제출 완료 표시 미확인 — 화면 확인 필요")
    return False


# ─────────────────── 위택스 서류 PDF저장/출력 ───────────────────
# 화면 구조(라이브 확인, 2026-07-06): 특별징수 신고내역(B070102M01)은 사무소 계정 전체
# 내역이 쌓여 여러 페이지 — 페이지 순회 대신 '상세검색'에 사업자등록번호를 넣어 1건으로
# 필터한 뒤, 행 체크박스 선택 → 하단 [신고결과서출력]/[납부서출력] 버튼으로 출력한다.
# (개인사업자는 납세자명이 대표자 이름으로 떠서 이름 매칭 대신 사업자번호를 쓴다.)

async def open_inquiry(page, log=print) -> bool:
    """특별징수 신고내역조회 및 납부(B070102M01)로 직접 URL 이동. (URL 라이브 확인됨)"""
    try:
        await page.goto(WETAX_INQUIRY_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (위택스) 신고내역 goto 실패: {str(e)[:60]}")
        return False
    await close_popups(page, log)
    log("[v] (위택스) 특별징수 신고내역 화면")
    return True


async def search_by_bizno(page, biz_no: str, log=print) -> int:
    """'상세검색' 열기 → 납세자 사업자등록번호 입력 → [검색]. 반환: 결과 건수(-1 실패).

    입력칸은 placeholder '납세자 사업자등록번호 입력'(라이브 확인).
    """
    digits = "".join(c for c in (biz_no or "") if c.isdigit())
    try:
        await page.get_by_text("상세검색", exact=True).first.click(timeout=6000)
        await page.wait_for_timeout(1000)
    except Exception as e:
        log(f"[!] (위택스) 상세검색 열기 실패: {str(e)[:60]}")
        return -1
    filled = False
    try:
        loc = page.get_by_placeholder("납세자 사업자등록번호 입력")
        if await loc.count():
            await loc.first.fill(digits)
            filled = True
    except Exception:
        pass
    if not filled:
        # 폴백: '사업자등록번호' 라벨 근처 입력칸
        try:
            loc = page.locator("input[placeholder*='사업자등록번호']")
            if await loc.count():
                await loc.first.fill(digits)
                filled = True
        except Exception:
            pass
    if not filled:
        log("[!] (위택스) 사업자등록번호 검색칸 못 찾음")
        return -1
    log(f"[i] (위택스) 사업자번호 검색 {digits[:3]}-**-*****")
    if not await click_button_text(page, "검색", log):
        try:
            await page.get_by_role("button", name="검색").first.click(timeout=5000)
        except Exception as e:
            log(f"[!] (위택스) 검색 클릭 실패: {str(e)[:60]}")
            return -1
    await page.wait_for_timeout(2500)
    m = re.search(r"검색결과\s*(\d+)\s*건", await _body(page))
    n = int(m.group(1)) if m else -1
    log(f"[i] (위택스) 검색결과 {n}건")
    return n


async def search_by_name(page, name: str, log=print) -> int:
    """'상세검색' → 납세자명으로 검색. 반환: 결과 건수(-1 실패).

    공용 인증서라 신고내역에 다른 직원 신고가 섞이므로, 대장에 기록된 납세자명으로
    좁힌 뒤 신고일자까지 맞는 행만 출력한다.
    """
    try:
        await page.get_by_text("상세검색", exact=True).first.click(timeout=6000)
        await page.wait_for_timeout(1000)
    except Exception as e:
        log(f"[!] (위택스) 상세검색 열기 실패: {str(e)[:60]}")
        return -1
    filled = False
    try:
        loc = page.get_by_placeholder("납세자명 입력")
        if await loc.count():
            await loc.first.fill(name)
            filled = True
    except Exception:
        pass
    if not filled:
        try:
            loc = page.locator("input[placeholder*='납세자명']")
            if await loc.count():
                await loc.first.fill(name)
                filled = True
        except Exception:
            pass
    if not filled:
        log("[!] (위택스) 납세자명 검색칸 못 찾음")
        return -1
    if not await click_button_text(page, "검색", log):
        try:
            await page.get_by_role("button", name="검색").first.click(timeout=5000)
        except Exception as e:
            log(f"[!] (위택스) 검색 클릭 실패: {str(e)[:60]}")
            return -1
    await page.wait_for_timeout(2500)
    m = re.search(r"검색결과\s*(\d+)\s*건", await _body(page))
    return int(m.group(1)) if m else -1


async def _open_popover_for_row(page, name: str, filed_date: str, log=print) -> bool:
    """납세자명(+신고일자) 행의 발급출력 아이콘 클릭 → 팝오버.

    신고일자까지 일치하는 행 우선, 없으면(수기 등록 등으로 날짜가 다르면)
    이름이 일치하는 행 중 가장 최근 신고일자 행으로 폴백.
    """
    ok = False
    for frame in page.frames:
        try:
            ok = bool(await frame.evaluate("""(arg) => {
                const vis = e => { const r = e.getBoundingClientRect();
                    return r.width > 1 && r.height > 1; };
                const cand = [];
                for (const row of document.querySelectorAll('tr')) {
                    const t = (row.innerText || '');
                    if (!t.includes(arg.name)) continue;
                    const els = [...row.querySelectorAll('a, button')].filter(vis);
                    if (!els.length) continue;
                    const dm = t.match(/20\\d\\d-\\d\\d-\\d\\d/);
                    cand.push({ el: els[els.length - 1], date: dm ? dm[0] : '' });
                }
                if (!cand.length) return false;
                let pick = arg.date ? cand.find(c => c.date === arg.date) : null;
                if (!pick)   // 날짜 불일치 → 가장 최근 신고일자 행으로 폴백
                    pick = cand.sort((a, b) => (b.date || '').localeCompare(a.date || ''))[0];
                pick.el.click();
                return true;
            }""", {"name": name, "date": filed_date}))
            if ok:
                break
        except Exception:
            continue
    if not ok:
        log(f"[!] (위택스) '{name}' 행을 못 찾음")
    else:
        await page.wait_for_timeout(1000)
    return ok


async def print_napbu_for(ctx, page, pdf_dir, wt_name: str, filed_date: str,
                          fname: str, output_mode: str = "pdf", log=print) -> str:
    """대장 항목 1건의 위택스 납부서 출력. 반환: "done" | "none" | ""(실패).

    신고내역 → 납세자명 검색 → (이름+신고일자) 행 팝오버 → [납부서] 없으면 0원/미생성.
    """
    from pathlib import Path
    if not await open_inquiry(page, log):
        return ""
    n = await search_by_name(page, wt_name, log)
    if n == 0:
        log(f"[i] (위택스) '{wt_name}' 검색 결과 없음 — 건너뜀")
        return "none"
    if n < 0:
        return ""
    if not await _open_popover_for_row(page, wt_name, filed_date, log):
        return ""
    if not await button_visible(page, "납부서"):
        log(f"[i] (위택스) '{wt_name}' 납부서 없음(0원/가상계좌 미생성) — 건너뜀")
        return "none"
    try:
        async with ctx.expect_page(timeout=12000) as info:
            if not await click_button_text(page, "납부서", log):
                raise RuntimeError("납부서 버튼 클릭 실패")
        oz = await info.value
        await oz.wait_for_timeout(2500)
        ok = await _oz_print(oz, Path(pdf_dir) / fname, log, save=(output_mode == "pdf"))
        try:
            await oz.close()
        except Exception:
            pass
        return "done" if ok else ""
    except Exception as e:
        log(f"[!] (위택스) '{wt_name}' 납부서 실패: {str(e)[:70]}")
        return ""


async def _open_row_print_popover(page, log=print) -> bool:
    """첫 데이터 행의 '발급출력' 아이콘 클릭 → [신고서]/[납부서] 팝오버 열기.

    하단 [신고결과서출력]/[납부서출력] 버튼은 납부세액 0원이어도 납부서를 출력해버리는
    반면, 이 팝오버는 세액이 없으면 [납부서] 버튼 자체가 안 떠서 실수 방지가 된다
    (라이브 확인) → 팝오버 방식 사용. 행 체크박스 선택도 불필요.
    """
    ok = False
    for frame in page.frames:
        try:
            ok = bool(await frame.evaluate("""() => {
                const vis = e => { const r = e.getBoundingClientRect();
                    return r.width > 1 && r.height > 1; };
                for (const row of document.querySelectorAll('tr')) {
                    // 데이터 행 판별: 날짜(신고일자)가 있는 행
                    if (!/20\\d\\d-\\d\\d-\\d\\d/.test(row.innerText || '')) continue;
                    const els = [...row.querySelectorAll('a, button')].filter(vis);
                    if (!els.length) continue;
                    // 발급출력 아이콘 = 행 안의 마지막 버튼형 요소
                    els[els.length - 1].click();
                    return true;
                }
                return false;
            }"""))
            if ok:
                break
        except Exception:
            continue
    if not ok:
        log("[!] (위택스) 발급출력 아이콘 못 찾음")
    else:
        await page.wait_for_timeout(1000)
    return ok


async def _row_due_date(page) -> str:
    """첫 데이터 행에서 납부기한(마지막 날짜) 추출 → 파일명용."""
    try:
        raw = await page.evaluate("""() => {
            for (const row of document.querySelectorAll('tr')) {
                if (!row.querySelector("input[type=checkbox]")) continue;
                const ds = (row.innerText || '').match(/20\\d\\d-\\d\\d-\\d\\d/g) || [];
                if (ds.length) return ds[ds.length - 1];
            }
            return '';
        }""")
        return pdf_save.fmt_due(raw or "")
    except Exception:
        return ""


async def _click_text_js(scope, text: str) -> bool:
    return await scope.evaluate("""(text) => {
        for(const e of document.querySelectorAll('input,button,a,img')){
            const t=(e.value||e.title||e.getAttribute('alt')||e.innerText||'').trim();
            if(t===text){ e.click(); return true; }
        }
        return false;
    }""", text)


async def _oz_print(oz, target, log=print, save: bool = True) -> bool:
    """OZ 뷰어: [인쇄] → 인쇄옵션 [확인] → (save면) Microsoft Print to PDF 저장."""
    await oz.wait_for_timeout(1500)
    if not await _click_text_js(oz, "인쇄"):
        log("  [!] (위택스) OZ 인쇄 버튼 못 찾음")
        return False
    await oz.wait_for_timeout(1500)
    await _click_text_js(oz, "확인")   # OZ 인쇄옵션 창의 확인 → 실제 인쇄
    if not save:
        await oz.wait_for_timeout(2500)
        return True
    from pathlib import Path as _P
    _P(target).parent.mkdir(parents=True, exist_ok=True)
    # 저장 다이얼로그 내부 진행 로그는 사용자에게 불필요 → log=None (실패 사유는 err로 받음)
    ok, err = await asyncio.to_thread(pdf_save.fill_and_save, target, 25.0, None)
    if not ok:
        log(f"  [!] (위택스) PDF 저장 실패: {err}")
    return ok


async def _print_reports(ctx, page, pdf_dir, biz_no: str, name: str, kinds: list,
                         output_mode: str, include_name: bool, log=print) -> dict:
    """신고내역 → 상세검색(사업자번호) → 발급출력 아이콘 → 팝오버 [신고서]/[납부서] → OZ 저장.

    파일명: [신고서]{이름}_지방세 / [납부서]{이름}_지방세_{납부기한}. {saved, failed} 반환.
    납부세액 0원이면 팝오버에 [납부서] 버튼이 없음 → '없음'으로 정상 처리(라이브 확인).
    """
    from pathlib import Path
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    if not await open_inquiry(page, log):
        return result
    n = await search_by_bizno(page, biz_no, log)
    if n == 0:
        log("[i] (위택스) 검색 결과 없음 — 건너뜀")
        return result
    if n < 0:
        result["failed"].append("검색실패")
        return result
    due = await _row_due_date(page) if "납부서" in kinds else ""

    specs = []
    if "신고서" in kinds:
        specs.append(("신고서", pdf_save.doc_name("신고서", ["지방세"], include_name, name)))
    if "납부서" in kinds:
        specs.append(("납부서", pdf_save.doc_name("납부서", ["지방세", due], include_name, name)))

    for kind, fname in specs:
        # 팝오버는 클릭 후 닫힐 수 있어 종류마다 다시 연다.
        if not await _open_row_print_popover(page, log):
            result["failed"].append(kind)
            continue
        if not await button_visible(page, kind):
            if kind == "납부서":
                log("[i] (위택스) 팝오버에 [납부서] 없음 — 납부세액 0원/가상계좌 미생성, 건너뜀")
            else:
                log(f"[!] (위택스) 팝오버에 [{kind}] 버튼 없음")
                result["failed"].append(kind)
            continue
        try:
            async with ctx.expect_page(timeout=12000) as info:
                if not await click_button_text(page, kind, log):
                    raise RuntimeError(f"'{kind}' 버튼 클릭 실패")
            oz = await info.value
            await oz.wait_for_timeout(2500)
            tgt = pdf_dir / fname
            if await _oz_print(oz, tgt, log, save=save):
                result["saved"].append(fname)
                log(f"[v] (위택스) {kind} {'저장' if save else '출력'}: {fname}")
            else:
                result["failed"].append(kind)
            try:
                await oz.close()
            except Exception:
                pass
        except Exception as e:
            log(f"[!] (위택스) {kind} 실패: {str(e)[:70]}")
            result["failed"].append(kind)
        await page.wait_for_timeout(1500)
    return result


async def print_singo(ctx, page, pdf_dir, biz_no: str, name: str, output_mode: str = "pdf",
                      include_name: bool = False, log=print) -> dict:
    """위택스 지방세 신고서(신고결과서)만 출력(가상계좌 무관)."""
    return await _print_reports(ctx, page, pdf_dir, biz_no, name, ["신고서"],
                                output_mode, include_name, log)


async def print_napbu(ctx, page, pdf_dir, biz_no: str, name: str, output_mode: str = "pdf",
                      include_name: bool = False, log=print) -> dict:
    """위택스 지방세 납부서(가상계좌)만 출력. 0원/가상계좌 미생성이면 실패로 기록될 수 있음."""
    return await _print_reports(ctx, page, pdf_dir, biz_no, name, ["납부서"],
                                output_mode, include_name, log)
