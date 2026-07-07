"""홈택스 원천세 파일변환신고 + 간이지급명세서 제출 — 메뉴 내비게이션 + 화면 셀렉터.

파일변환신고 기계장치(파일주입/검증/모달/제출/clipreport 출력)는 yangdo_auto에서
라이브 검증된 코드를 그대로 가져왔다.

라이브 확인됨(2026-07-03, Chrome 탐색):
  - 원천세: 신고/납부[호버] → 원천세[클릭] → '파일변환신고' 카드 → 전자파일변환 화면
    (세목 공통 화면 — 화면 안내 변환순서: [파일선택] → [파일검증하기] → 비밀번호 입력
     → 검증결과내역 확인 → [제출하러 가기] → '일괄접수증' → [신고내역 조회(접수증·납부서)])
  - 변환파일 확장자 .01.enc(암호화) → 검증 과정에 파일 비밀번호 입력 단계 있음
  - 간이지급명세서: 신청/제출[호버] → '(일용·간이·용역) 변환파일 제출' → 자체 제출 화면
    ((지급)명세서 종류 드롭다운 + 제출구분 라디오 + 귀속년월 + 파일선택 + [파일검증 시작하기])
  - 신고내역 조회(접수증·납부서) 모달: 신고일자 범위/사업자번호 조회,
    '접수증 일괄조회 및 인쇄'·'개별접수증 일괄 출력' 버튼, 행별 접수증/납부서 보기

⚠ 남은 LIVE-TODO:
  - 원천세 검증 시 비밀번호 입력 UI의 정확한 형태(모달/인라인) — 첫 실행에서 확정
  - 간이지급명세서 검증 후 제출 버튼/흐름 — 첫 실행에서 확정
  - 일괄 파일(여러 업체) 신고 시 신고내역·납부서 다건 반복 처리

⚠ WebSquare 숫자 id는 매번 바뀌므로(동적) 텍스트 기반 셀렉터를 쓴다.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from . import pdf_save
from .browser import HOMETAX_URL

# 접수번호 패턴 (예: 212-2026-2-505316384006)
RECEIPT_NO_RE = re.compile(r"\d{3}-\d{4}-\d-\d{3,}")


def _due_from_period(period: str) -> str:
    """과세기간('2026년1월') → 원천세 납부기한(다음달 10일, '2026-02-10').

    정기신고 기준 규칙 계산 — 납부서 화면에서 직접 추출 실패 시 폴백용.
    """
    m = re.match(r"(20\d\d)년\s*(\d{1,2})월", period or "")
    if not m:
        return ""
    y, mo = int(m.group(1)), int(m.group(2)) + 1
    if mo == 13:
        y, mo = y + 1, 1
    return f"{y:04d}-{mo:02d}-10"


async def _win_due_date(win) -> str:
    """납부서 창 텍스트에서 '납부기한' 옆 날짜 추출('YYYY-MM-DD'). 실패 시 ''.

    납부서에는 납부기한이 반드시 인쇄돼 있어 기한후신고 등 예외에도 정확하다.
    (clipreport가 캔버스로 렌더링하면 텍스트가 안 잡힐 수 있음 → 호출측에서 규칙 계산 폴백.)
    """
    for fr in win.frames:
        try:
            t = await fr.evaluate("() => document.body ? document.body.innerText : ''")
            m = re.search(r"납부\s*기한[^0-9]{0,15}(20\d\d)[.\-/년\s]{1,3}"
                          r"(\d{1,2})[.\-/월\s]{1,3}(\d{1,2})", t or "")
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except Exception:
            continue
    return ""
# clipreport 리포트 데이터 로딩 완료 감지 JS
_CLIPREPORT_LOADED = """() => {
    const t = document.querySelector('[id^="re_totalCountNumber"]');
    const p = document.querySelector('[id^="re_progressImg"]');
    const m = t && (t.value||'').match(/\\/\\s*(\\d+)/);
    return (m && parseInt(m[1])>0) || (p && getComputedStyle(p).display==='none');
}"""


_BTN_SELECTOR = "a, button, input[type=button], input[type=submit]"

# 브라우저 안에서 버튼형 요소를 한 번에 스캔해 일치하는 첫 보이는 요소의
# 인덱스를 반환 — 요소별 왕복(수백 회) 대신 frame당 왕복 1회로 단축.
# 위택스 버튼은 <a>제출하기<i>…움직이는 화살표…</i></a>처럼 장식 자식 태그의 숨김
# 텍스트가 innerText에 섞임(라이브 확인) → ①자식 태그 제외 직접 텍스트 ②innerText/value
# 두 기준으로 비교. 끝의 화살표 문자·공백도 무시. (버튼 요소만 대상 — 제목 오클릭 없음)
_FIND_BTN_JS = """(text) => {
    const els = document.querySelectorAll("a, button, input[type=button], input[type=submit]");
    const norm = x => ((x || '') + '').trim().replace(/[\\s\\u2190-\\u21FF>»›]+$/, '').trim();
    for (let i = 0; i < els.length; i++) {
        const e = els[i];
        const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility === 'hidden') continue;
        const direct = [...e.childNodes].filter(n => n.nodeType === 3)
            .map(n => n.textContent).join('');
        if (norm(direct) === text || norm(e.innerText || e.value) === text) return i;
    }
    return -1;
}"""


async def click_button_text(page, text: str, log=print) -> bool:
    """모든 frame에서 버튼형 요소(a/button/input)만 골라 텍스트 정확 일치 클릭.

    홈택스 화면엔 같은 문구가 제목/안내문에도 흔해서 get_by_text().first가 버튼이
    아닌 요소에 걸리는 사고가 반복됨(파일 업로드/확인/제출하기 3회 라이브 확인)
    → 버튼 클릭은 반드시 이 함수를 쓴다.
    탐색은 frame당 JS 1회(빠름), 클릭은 검증된 Playwright click 유지.
    """
    for frame in page.frames:
        try:
            idx = await frame.evaluate(_FIND_BTN_JS, text)
            if idx is not None and idx >= 0:
                await frame.locator(_BTN_SELECTOR).nth(idx).click(timeout=6000)
                return True
        except Exception:
            continue
    return False


async def button_visible(page, text: str) -> bool:
    """버튼형 요소 중 텍스트 정확 일치가 보이는지. (frame당 JS 1회)"""
    for frame in page.frames:
        try:
            idx = await frame.evaluate(_FIND_BTN_JS, text)
            if idx is not None and idx >= 0:
                return True
        except Exception:
            continue
    return False


async def _click_first_visible(locator, timeout: int = 4000) -> bool:
    """locator 중 보이는 첫 요소를 클릭. 성공하면 True."""
    n = await locator.count()
    for i in range(n):
        try:
            el = locator.nth(i)
            if await el.is_visible():
                await el.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def _open_and_click_submenu(page, parent_text: str, child_text: str,
                                  log=print, attempts: int = 5) -> bool:
    """메가메뉴: parent를 호버(필요시 클릭)해 드롭다운을 열고 child를 클릭. 재시도 포함.

    홈택스 메뉴는 호버로 열릴 때도, 클릭해야 열릴 때도 있고 클릭 시 페이지가 이동하며
    드롭다운이 닫히는 레이스가 있어 불안정 → child가 보일 때까지 재시도.
    """
    parent = page.get_by_text(parent_text, exact=True).first
    child = page.get_by_text(child_text, exact=True)
    # 페이지(WebSquare 메뉴)가 렌더될 때까지 parent가 보이길 먼저 기다린다(goto 직후 레이스 방지).
    try:
        await parent.wait_for(state="visible", timeout=15000)
        await page.wait_for_timeout(600)
    except Exception:
        log(f"  [!] (홈택스) '{parent_text}' 메뉴가 안 보임(렌더 지연?)")
    for a in range(attempts):
        try:
            await parent.hover(timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(800)
        if await _click_first_visible(child):
            return True
        # 호버로 안 열리면 parent 클릭으로 펼침 시도
        try:
            await parent.click(timeout=5000)
            await page.wait_for_timeout(1200)
        except Exception:
            pass
        if await _click_first_visible(child):
            return True
        log(f"  ... (홈택스) '{child_text}' 진입 재시도 {a + 1}/{attempts}")
        await page.wait_for_timeout(1000)
    return False


async def reset_to_home(page, log=print) -> None:
    """phase 시작용 하드 리셋 — 홈택스 홈으로 goto.

    goto는 DOM·모달·오버레이 잔재를 통째로 날려, 앞 phase의 끝 상태와 무관하게
    깨끗한 상태에서 시작하게 한다(배치/독립 실행 동일). 로그인 세션은 유지됨.
    """
    try:
        await page.goto(HOMETAX_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        log(f"[!] (홈택스) 홈 리셋 실패: {str(e)[:60]}")


# ─────────────────── 원천세 파일변환신고 (경로 라이브 확인됨) ───────────────────

MENU_PARENT = "신고/납부"
MENU_WONCHEON = "원천세"           # 확인됨: 세금신고 드롭다운의 '원천세'
CARD_FILE_CONVERT = "파일변환신고"  # 확인됨: 원천세 신고 화면의 카드 텍스트

# 원천세 신고 화면 딥링크 (라이브 확인: 메뉴 클릭 후 URL — tmIdx 파라미터로 직행 가능)
WONCHEON_MENU_URL = ("https://hometax.go.kr/websquare/websquare.html"
                     "?w2xPath=/ui/pp/index_pp.xml&tmIdx=04&tm2lIdx=0405000000&tm3lIdx=0405030000")


async def navigate_to_file_convert(page, log=print) -> bool:
    """원천세 신고 화면 → 파일변환신고 카드 → 전자파일변환 화면.

    딥링크(goto) 우선 — 실패 시 홈 리셋 후 메뉴 호버 경로 폴백. (둘 다 라이브 확인)
    """
    reached = False
    try:
        await page.goto(WONCHEON_MENU_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        body = await page.locator("body").inner_text(timeout=5000)
        reached = "원천세 신고" in body and CARD_FILE_CONVERT in body
        if reached:
            log("[v] (홈택스) 원천세 신고 화면 도달(딥링크)")
    except Exception:
        pass
    if not reached:
        await reset_to_home(page, log)
        log(f"[i] (홈택스) {MENU_PARENT} → {MENU_WONCHEON} → {CARD_FILE_CONVERT}")
        if not await _open_and_click_submenu(page, MENU_PARENT, MENU_WONCHEON, log):
            log("[!] (홈택스) 원천세 메뉴 진입 실패")
            return False
        await page.wait_for_timeout(1500)
    for a in range(3):
        try:
            await page.get_by_text(CARD_FILE_CONVERT, exact=True).first.click(timeout=8000)
            await page.wait_for_timeout(2500)
            log("[v] (홈택스) 전자파일변환 화면 도달")
            return True
        except Exception as e:
            log(f"  ... (홈택스) {CARD_FILE_CONVERT} 클릭 재시도 {a + 1}/3: {str(e)[:50]}")
            await page.wait_for_timeout(1000)
    log(f"[!] (홈택스) {CARD_FILE_CONVERT} 카드 클릭 실패")
    return False


# 파일변환신고 화면의 버튼/링크 텍스트 — 세목 공통(양도세에서 라이브 검증됨)
BTN_FILE_SELECT = "파일선택"
BTN_VERIFY = "파일검증하기"
BTN_GO_SUBMIT = "제출하러 가기"
BTN_SUBMIT = "전자파일 제출하기"     # 공백 포함(라이브 확인)


async def inject_convert_file(page, file_path: str, log=print) -> bool:
    """KUpload 대응: 숨은 input[type=file]에 파일을 직접 주입(라이브 검증됨).

    filechooser/OS 다이얼로그 없이 set_input_files로 바로 꽂힌다.
    """
    for fi, frame in enumerate(page.frames):
        try:
            inp = frame.locator("input[type=file]")
            if await inp.count() > 0:
                await inp.first.set_input_files(file_path, timeout=8000)
                log(f"[v] (홈택스) 파일 주입 성공: {file_path}")
                return True
        except Exception as e:
            log(f"[!] (홈택스) 파일 주입 실패(frame {fi}): {str(e)[:70]}")
    log("[!] (홈택스) input[type=file]를 찾지 못함")
    return False


async def handle_prev_record_modal(page, log=print) -> bool:
    """'이미 검증된 자료가 존재합니다. 다시 하시겠습니까?' 모달 → '확인'.

    종전 신고내역이 있을 때만 뜬다(없으면 안 뜸). 닫기/취소는 누르지 않는다.
    """
    for frame in page.frames:
        try:
            wins = frame.locator(".w2window")
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
                    if t == "확인" or (("확인" in t or "예" in t) and "닫기" not in t):
                        await el.click()
                        log(f"[i] (홈택스) 종전내역 모달 '{t}' 클릭")
                        await page.wait_for_timeout(1000)
                        return True
        except Exception:
            continue
    return False


async def fill_file_password(page, password: str, log=print, wait_sec: int = 8) -> bool:
    """암호화 변환파일(.enc) 비밀번호 입력 — '변환파일 정보입력' 모달(라이브 확인).

    [파일검증하기] 클릭 후 비밀번호 모달이 뜨면 채우고 [확인].
    (간이지급명세서와 동일 모달 — 검증된 _click_modal_confirm 방식 사용.)
    모달이 wait_sec 안에 안 뜨면(평문 파일) False로 조용히 통과.
    """
    if not password:
        return False
    for _ in range(wait_sec):
        for frame in page.frames:
            try:
                pwl = frame.locator("input[type=password]")
                for i in range(await pwl.count()):
                    el = pwl.nth(i)
                    if not await el.is_visible():
                        continue
                    await el.fill(password)
                    log("[i] (홈택스) 파일 비밀번호 입력")
                    clicked = await _click_modal_confirm(page, must_contain="비밀번호", log=log)
                    if not clicked:
                        clicked = await _click_modal_confirm(page, must_contain="변환파일", log=log)
                    if not clicked:
                        # 폴백: 같은 frame의 보이는 '확인' 버튼 요소 클릭
                        try:
                            btns = frame.locator(
                                "a, button, input[type=button], input[type=submit]")
                            for b in range(await btns.count()):
                                bel = btns.nth(b)
                                if not await bel.is_visible():
                                    continue
                                t = ((await bel.inner_text()) or
                                     (await bel.get_attribute("value")) or "").strip()
                                if t == "확인":
                                    await bel.click(timeout=3000)
                                    log("[i] (홈택스) 비밀번호 모달 '확인' 클릭(폴백)")
                                    break
                        except Exception:
                            pass
                    await page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
        await page.wait_for_timeout(1000)
    return False


async def verify_and_wait(page, log=print, timeout: int = 150, file_password: str = "") -> str:
    """파일검증하기 클릭 → 종전내역 모달 처리 → (암호화 파일이면 비밀번호 입력)
    → '검증 중' 오버레이가 사라질 때까지 대기.

    반환: "완료" | "시간초과". (오류/정상 판정은 호출측에서 화면 파싱.)
    """
    try:
        await page.get_by_text(BTN_VERIFY, exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(1200)
    except Exception as e:
        log(f"[!] (홈택스) 파일검증하기 클릭 실패: {str(e)[:80]}")
        return "시간초과"
    await handle_prev_record_modal(page, log)
    await fill_file_password(page, file_password, log)

    # '검증 중입니다' 오버레이가 사라지면 완료. (제출하러 가기 버튼은 검증중에도 존재하므로 기준 X)
    for sec in range(0, timeout, 2):
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        validating = "검증 중입니다" in body or "검증중입니다" in body
        if not validating and ("내용검증" in body or "제출하러 가기" in body):
            # 오버레이 없음 + 결과 영역 존재 = 완료
            log(f"[v] (홈택스) 검증 완료 ({sec}s)")
            return "완료"
        if sec % 10 == 0:
            log(f"  ... (홈택스) 검증 대기 ({sec}s)")
        await asyncio.sleep(2)
    return "시간초과"


async def _click_modal_confirm(page, must_contain: str, log=print) -> bool:
    """텍스트에 must_contain이 든 보이는 WebSquare 모달의 '확인'을 클릭."""
    for frame in page.frames:
        try:
            wins = frame.locator(".w2window")
            for i in range(await wins.count()):
                win = wins.nth(i)
                if not await win.is_visible():
                    continue
                txt = await win.inner_text()
                if must_contain and must_contain not in txt:
                    continue
                btns = win.locator("a, button, input[type=button], input[type=submit]")
                for b in range(await btns.count()):
                    el = btns.nth(b)
                    if not await el.is_visible():
                        continue
                    t = (await el.inner_text()).strip() or (await el.get_attribute("value") or "")
                    if t.strip() == "확인":
                        await el.click()
                        log(f"[i] (홈택스) 모달 '확인' ({must_contain})")
                        await page.wait_for_timeout(1000)
                        return True
        except Exception:
            continue
    return False


async def _receipt_visible(page) -> bool:
    """접수증 모달이 지금 보이는지 1회 스캔(대기 없음)."""
    for frame in page.frames:
        try:
            wins = frame.locator(".w2window")
            for i in range(await wins.count()):
                win = wins.nth(i)
                if not await win.is_visible():
                    continue
                txt = await win.inner_text()
                if "접수증" in txt or "접수내용" in txt or "접수 되었습니다" in txt:
                    return True
        except Exception:
            continue
    return False


async def _wait_receipt_modal(page, log=print, timeout: int = 25) -> bool:
    """접수증 모달이 뜰 때까지 대기. 등장 = 제출 성공 신호.

    닫지 않고 화면에 남겨 둔다 — 다음 phase가 reset_to_home로 정리하고,
    사용자는 접수증 화면으로 제출 성공을 눈으로 확인할 수 있다(phase 시작-리셋 원칙).
    """
    for _ in range(timeout):
        if await _receipt_visible(page):
            log("[v] (홈택스) 접수증 확인 — 제출 완료 (화면 유지)")
            return True
        await page.wait_for_timeout(1000)
    return False


async def submit_filing(page, log=print) -> bool:
    """검증완료 화면 → [제출하러 가기] → [전자파일 제출하기] → 제출확인 → 접수증 등장 확인.

    ⚠ 실제·비가역 제출. 접수증 모달 등장 = 제출 성공(닫지 않고 화면에 남겨 둠).
    """
    try:
        await page.get_by_text(BTN_GO_SUBMIT, exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(2500)
    except Exception as e:
        log(f"[!] (홈택스) '제출하러 가기' 실패: {str(e)[:80]}")
        return False
    try:
        await page.get_by_text(BTN_SUBMIT, exact=True).first.click(timeout=8000)
    except Exception as e:
        log(f"[!] (홈택스) '{BTN_SUBMIT}' 실패: {str(e)[:80]}")
        return False
    await page.wait_for_timeout(1500)
    # 제출 확인 모달이 연달아 2개 뜸(원천세 라이브 확인):
    #   ① '정상 변환된 신고서를 제출하시겠습니까?' → 확인
    #   ② '신고서를 제출하시겠습니까?' → 확인
    # 개수를 단정하지 않고, 접수증이 뜰 때까지 '제출' 모달의 확인을 반복 처리한다.
    # (접수증 검사는 대기 없는 1회 스캔 — 모달 클릭을 지연시키지 않도록)
    for _ in range(20):
        if await _receipt_visible(page):
            log("[v] (홈택스) 접수증 확인 — 제출 완료 (화면 유지)")
            return True
        await _click_modal_confirm(page, must_contain="제출", log=log)
        await page.wait_for_timeout(500)
    # 마지막으로 접수증 등장 대기(늦게 뜨는 경우). 닫지 않고 그대로 둔다(다음 phase가 리셋).
    if await _wait_receipt_modal(page, log, timeout=10):
        return True
    log("[!] (홈택스) 제출됨(추정) 그러나 접수증 모달 미확인 — 화면 확인 필요")
    return True


# ─────────────────── 간이지급명세서 제출 (경로·화면 라이브 확인됨) ───────────────────

# 확인됨: 신청/제출[호버] → '(일용·간이·용역) 소득자료 제출' 컬럼의 '(일용·간이·용역) 변환파일 제출'
# 화면: "일용·간이지급명세서/사업장제공자 등의 과세자료 제출명세서 제출 (매월·반기)"
#   탭[직접작성 제출|변환파일 제출|제출내역 조회|최종수록 자료]
#   ① (지급)명세서 선택 드롭다운 ② 제출구분(정기/수정/기한후) ③ 귀속년도-지급월(자동)
#   ④ [파일선택] ⑤ [파일검증 시작하기]  (검증 후 제출 버튼은 LIVE-TODO)
JIGUP_MENU_PARENT = "신청/제출"
JIGUP_MENU_CHILD = "(일용·간이·용역) 변환파일 제출"

# (지급)명세서 선택 드롭다운 옵션 (라이브 확인, 2026-07)
JIGUP_TYPES = [
    "일용근로소득 지급명세서",
    "간이지급명세서(근로소득)",
    "간이지급명세서(거주자의 사업소득)",
    "간이지급명세서(거주자의 기타소득)",
    "사업장 제공자 등의 과세자료 제출명세서",
    "간이지급명세서(연말정산 사업소득)",
    "간이지급명세서(비거주자의 사업소득)",
]
BTN_JIGUP_VERIFY = "파일검증 시작하기"


async def navigate_to_jigup(page, log=print) -> bool:
    """홈 리셋 → 신청/제출 → (일용·간이·용역) 변환파일 제출 화면. (경로 확인됨)"""
    await reset_to_home(page, log)
    log(f"[i] (홈택스) {JIGUP_MENU_PARENT} → {JIGUP_MENU_CHILD}")
    if not await _open_and_click_submenu(page, JIGUP_MENU_PARENT, JIGUP_MENU_CHILD, log):
        log("[!] (홈택스) 변환파일 제출 메뉴 진입 실패")
        return False
    await page.wait_for_timeout(2000)
    # 도달 검증: 화면 타이틀/탭 텍스트
    try:
        body = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        body = ""
    if "변환파일 제출" in body and ("명세서 선택" in body or "파일검증" in body):
        log("[v] (홈택스) 간이지급명세서 변환파일 제출 화면 도달")
        return True
    log("[!] (홈택스) 변환파일 제출 화면 확인 실패")
    return False


async def jigup_select_type(page, type_label: str, log=print) -> bool:
    """(지급)명세서 선택 드롭다운에서 type_label 선택.

    선택 직후 '이전에 수행한 변환파일 검증내역이 있습니다…' 팝업이 뜰 수 있음 → 확인.
    WebSquare 커스텀 셀렉트일 수 있어 2단 전략: ① select 요소면 select_option
    ② 아니면 드롭다운 열고 옵션 텍스트 클릭.
    """
    picked = False
    # ① 표준 select
    for frame in page.frames:
        try:
            sels = frame.locator("select")
            for i in range(await sels.count()):
                el = sels.nth(i)
                if not await el.is_visible():
                    continue
                opts = await el.evaluate("e => [...e.options].map(o => o.text.trim())")
                if any(type_label in o for o in opts):
                    await el.select_option(label=next(o for o in opts if type_label in o))
                    picked = True
                    break
        except Exception:
            continue
        if picked:
            break
    # ② 커스텀 드롭다운: 플레이스홀더 클릭 → 옵션 클릭
    if not picked:
        try:
            await page.get_by_text("명세서를 선택하세요", exact=False).first.click(timeout=5000)
            await page.wait_for_timeout(600)
            await page.get_by_text(type_label, exact=True).first.click(timeout=5000)
            picked = True
        except Exception as e:
            log(f"[!] (홈택스) 명세서 선택 실패({type_label}): {str(e)[:60]}")
            return False
    log(f"[v] (홈택스) 명세서 선택: {type_label}")
    await page.wait_for_timeout(1000)
    # '이전에 수행한 변환파일 검증내역이 있습니다. 처음부터 다시 시작하려면 [파일선택]…' → 확인
    await _click_modal_confirm(page, must_contain="검증내역", log=log)
    return True


async def _find_upload_scope(ctx, page):
    """'변환할 지급명세서 파일 선택' 팝업 창의 scope 반환. 없으면 None.

    라이브 확인: 별도 Chrome 창(popup.html?w2xPath=…), 제목 '파일 업로드',
    [파일찾기] + 드래그영역 + 하단 [닫기][파일 업로드]. 최대 1개 300MB.
    """
    # 새 창(popup page)인 경우 — URL/본문으로 식별
    for p in ctx.pages:
        if p is page:
            continue
        try:
            if "popup" in (p.url or ""):
                return p
            body = await p.locator("body").inner_text(timeout=1500)
            if "지급명세서 파일 선택" in body or "파일 업로드" in body:
                return p
        except Exception:
            continue
    # 폴백: 같은 page 안의 레이어/iframe인 경우
    for frame in page.frames:
        try:
            if await frame.locator("input[type=file]").count() > 0:
                return frame
        except Exception:
            continue
    return None


async def jigup_upload_file(ctx, page, file_path: str, log=print) -> bool:
    """[파일선택] 클릭 → (진행중 파일 취소 확인 팝업) → '변환할 지급명세서 파일 선택' 창
    → 파일 주입 → [파일 업로드] 클릭 → 창 닫힘/등록 확인. (사용자 확인 흐름 기반)"""
    try:
        await page.get_by_text("파일선택", exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        log(f"[!] (홈택스) '파일선택' 클릭 실패: {str(e)[:60]}")
        return False
    # '진행중 파일이 있습니다… 진행하시겠습니까?' → 확인 (뜰 때만)
    await _click_modal_confirm(page, must_contain="진행", log=log)
    await page.wait_for_timeout(1500)

    scope = None
    for _ in range(8):  # 팝업 창이 늦게 뜰 수 있어 최대 8초 재시도
        scope = await _find_upload_scope(ctx, page)
        if scope is not None:
            break
        await page.wait_for_timeout(1000)
    if scope is None:
        log("[!] (홈택스) 파일 선택 창을 못 찾음")
        return False
    # 파일 주입 (수동은 파일찾기 다이얼로그, 자동화는 input에 직접 주입)
    injected = False
    frames = scope.frames if hasattr(scope, "frames") else [scope]
    for fr in frames:
        try:
            fin = fr.locator("input[type=file]")
            if await fin.count() > 0:
                await fin.first.set_input_files(file_path, timeout=10000)
                injected = True
                break
        except Exception:
            continue
    if not injected:
        log("[!] (홈택스) 파일 선택 창의 input[type=file] 못 찾음")
        return False
    log(f"[v] (홈택스) 지급명세서 파일 주입: {file_path}")
    await page.wait_for_timeout(1000)
    # [파일 업로드] 클릭 — 팝업 상단 제목도 '파일 업로드'라서 텍스트 매칭이 제목에 걸림(라이브 확인).
    # 실제 버튼 요소(a/button/input)만 대상으로 정확 일치 클릭.
    uploaded = False
    for fr in frames:
        try:
            els = fr.locator("a, button, input[type=button], input[type=submit]")
            for i in range(await els.count()):
                el = els.nth(i)
                if not await el.is_visible():
                    continue
                t = ((await el.inner_text()) or (await el.get_attribute("value")) or "").strip()
                if t == "파일 업로드":
                    await el.click(timeout=6000)
                    uploaded = True
                    break
        except Exception:
            continue
        if uploaded:
            break
    if not uploaded:
        log("[!] (홈택스) '파일 업로드' 버튼 못 찾음")
        return False
    await page.wait_for_timeout(2500)
    await _click_modal_confirm(page, must_contain="", log=log)  # 업로드 완료 알림(있으면)
    # 등록 검증: 메인 화면 '변환파일 선택' 영역에 파일명이 표시되는지 확인
    # (라이브 확인: 업로드 완료 시 "'SF1690900.433' (1,105 byte)" 형태로 표시됨)
    fname = Path(file_path).name
    for _ in range(10):
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if fname in body:
            log(f"[v] (홈택스) 파일 업로드 완료 — 메인 화면 등록 확인: {fname}")
            return True
        await page.wait_for_timeout(1000)
    log("[!] (홈택스) 업로드 후 메인 화면에서 파일명 미확인 — 등록 실패 가능(중단)")
    return False


async def jigup_set_report_type(page, report_type: str = "정기신고",
                                pay_ym: str = "", log=print) -> bool:
    """제출구분 라디오 선택. 정기신고는 지급연도-월 자동, 수정·기한후는 pay_ym(YYYY-MM) 입력.

    정기신고가 기본 선택돼 있어도 명시 클릭(안전). 수정·기한후의 연/월 입력 UI는
    첫 사용 시 확정(LIVE-TODO) — select 두 개(연도/월)로 추정하고 best-effort.
    """
    try:
        await page.get_by_text(report_type, exact=True).first.click(timeout=5000)
        await page.wait_for_timeout(800)
        log(f"[i] (홈택스) 제출구분: {report_type}")
    except Exception as e:
        log(f"[!] (홈택스) 제출구분 '{report_type}' 클릭 실패: {str(e)[:50]}")
        return False
    if report_type != "정기신고" and pay_ym:
        year, _, month = pay_ym.partition("-")
        month = month.lstrip("0") or month
        done = 0
        for frame in page.frames:
            try:
                sels = frame.locator("select")
                for i in range(await sels.count()):
                    el = sels.nth(i)
                    if not await el.is_visible():
                        continue
                    opts = await el.evaluate("e => [...e.options].map(o => o.text.trim())")
                    if year in opts:
                        await el.select_option(label=year)
                        done += 1
                    elif any(o.lstrip("0") == month for o in opts if o):
                        await el.select_option(
                            label=next(o for o in opts if o.lstrip("0") == month))
                        done += 1
            except Exception:
                continue
        log(f"[{'v' if done >= 2 else '!'}] (홈택스) 지급연월 {pay_ym} 설정({done}/2) "
            f"{'' if done >= 2 else '— 화면 확인 필요(LIVE-TODO)'}")
    return True


async def jigup_verify(ctx, page, file_password: str, log=print, timeout: int = 600) -> bool:
    """[파일검증 시작하기] → 암호입력 모달(암호 입력+확인) → 검증 완료([제출하기] 등장) 대기.

    - 암호 미입력 상태면 사용자가 브라우저에서 직접 입력할 때까지 대기(2분).
    - 오류 팝업('오류' 포함 모달) 뜨면 실패로 종료.
    - 안내문 '1만라인 당 10분 소요' — timeout 기본 10분.
    """
    try:
        await page.get_by_text(BTN_JIGUP_VERIFY, exact=True).first.click(timeout=8000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        log(f"[!] (홈택스) '{BTN_JIGUP_VERIFY}' 클릭 실패: {str(e)[:60]}")
        return False

    # 암호입력 모달 처리
    pw_done = False
    for _ in range(8):
        filled = False
        for frame in page.frames:
            try:
                pwl = frame.locator("input[type=password]")
                for i in range(await pwl.count()):
                    el = pwl.nth(i)
                    if not await el.is_visible():
                        continue
                    if file_password:
                        await el.fill(file_password)
                        log("[i] (홈택스) 파일 암호 입력")
                        # '변환파일 정보입력' 모달(비밀번호 안내 문구 포함)의 [확인] 클릭
                        # — 버튼 요소만 골라 누르는 검증된 모달 처리 사용(라이브 확인).
                        clicked = await _click_modal_confirm(page, must_contain="비밀번호", log=log)
                        if not clicked:
                            # 폴백: 비밀번호 칸과 같은 frame의 보이는 '확인' 버튼 요소 클릭
                            try:
                                btns = frame.locator(
                                    "a, button, input[type=button], input[type=submit]")
                                for b in range(await btns.count()):
                                    bel = btns.nth(b)
                                    if not await bel.is_visible():
                                        continue
                                    t = ((await bel.inner_text()) or
                                         (await bel.get_attribute("value")) or "").strip()
                                    if t == "확인":
                                        await bel.click(timeout=3000)
                                        log("[i] (홈택스) 암호 모달 '확인' 클릭(폴백)")
                                        break
                            except Exception:
                                pass
                        pw_done = True
                    else:
                        log("[i] (홈택스) 암호 모달 감지 — 브라우저에서 직접 입력하세요 (최대 2분 대기)")
                        for _w in range(120):
                            await asyncio.sleep(1)
                            try:
                                if not await el.is_visible():
                                    break
                            except Exception:
                                break
                        pw_done = True
                    filled = True
                    break
            except Exception:
                continue
            if filled:
                break
        if pw_done:
            break
        await page.wait_for_timeout(1000)
    if not pw_done:
        log("[i] (홈택스) 암호 모달 미등장(평문 파일?) — 계속 진행")

    # 검증 완료 대기: [제출하기] 등장 = 성공, '오류' 모달 = 실패
    for sec in range(0, timeout, 3):
        # 오류 팝업 감지
        for frame in page.frames:
            try:
                wins = frame.locator(".w2window")
                for i in range(await wins.count()):
                    win = wins.nth(i)
                    if await win.is_visible():
                        txt = await win.inner_text()
                        if "오류" in txt and "확인" in txt:
                            log(f"[!] (홈택스) 검증 오류 팝업: {' '.join(txt.split())[:120]}")
                            await _click_modal_confirm(page, must_contain="오류", log=log)
                            return False
            except Exception:
                continue
        try:
            if await button_visible(page, "제출하기"):
                log(f"[v] (홈택스) 지급명세서 검증 완료 — 제출하기 버튼 등장 ({sec}s)")
                return True
        except Exception:
            pass
        if sec and sec % 30 == 0:
            log(f"  ... (홈택스) 지급명세서 검증 대기 ({sec}s)")
        await asyncio.sleep(3)
    log("[!] (홈택스) 지급명세서 검증 완료 미확인(시간초과)")
    return False


async def jigup_submit(page, log=print, timeout: int = 40) -> str:
    """'위 내용을 확인하고 제출합니다' 체크 → [제출하기] → 완료 확인.

    ⚠ 실제·비가역 제출. 반환: 접수번호(성공) | ""(실패).
    확인 팝업(법정제출기한 안내 → '제출이 완료되었습니다')은 JS 다이얼로그라 자동 수락됨.
    성공 판정은 페이지가 접수번호 화면으로 바뀌는 것(라이브 확인).
    """
    # 체크박스 '위 내용을 확인하고 제출합니다' — 검증결과 표에도 체크박스(전체선택)가
    # 있어 주변 텍스트 매칭으로 대상 선정. WebSquare 체크박스는 input 위에 꾸밈 요소가
    # 덮여 있어 Playwright check()가 스크롤 재시도를 반복(화면 흔들림) → 탐색부터 클릭까지
    # frame당 JS 1회로 처리(빠르고 흔들림 없음).
    _CHECK_JS = """(requireLabel) => {
        const vis = e => { const r = e.getBoundingClientRect();
            const s = getComputedStyle(e);
            return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden'; };
        const cbs = [...document.querySelectorAll("input[type=checkbox]")].filter(vis);
        let target = cbs.find(e =>
            ((e.closest('label,span,div,td')?.innerText) || '').includes('위 내용을 확인'));
        if (!target && !requireLabel) target = cbs[0];
        if (!target) return null;
        target.scrollIntoView({block: 'center'});
        if (!target.checked) target.click();
        return target.checked;
    }"""
    checked = False
    for require_label in (True, False):
        for frame in page.frames:
            try:
                result = await frame.evaluate(_CHECK_JS, require_label)
                if result:
                    checked = True
                    break
            except Exception:
                continue
        if checked:
            break
    if not checked:
        # 폴백: 라벨 텍스트 클릭 (숨은 input + 커스텀 렌더링 대비)
        try:
            await page.get_by_text("위 내용을 확인하고 제출합니다", exact=False).first.click(timeout=5000)
            checked = True
        except Exception:
            pass
    if not checked:
        log("[!] (홈택스) 제출 확인 체크박스 못 찾음")
        return False
    await page.wait_for_timeout(500)

    # 제출 중 뜨는 확인/완료 팝업은 JS 다이얼로그라 ctx 핸들러가 자동 수락 —
    # 메시지 기록용 리스너만 추가(성공 판정 보조).
    dmsgs: list = []
    try:
        page.on("dialog", lambda d: dmsgs.append(d.message))
    except Exception:
        pass

    # 섹션 제목도 '제출하기'라서 반드시 버튼 요소만 클릭 (라이브 확인)
    if not await click_button_text(page, "제출하기", log):
        log("[!] (홈택스) '제출하기' 버튼 클릭 실패")
        return ""
    log("[i] (홈택스) 제출하기 버튼 클릭 — 완료 확인 중")

    # 성공 판정(라이브 확인): 제출 완료 시 페이지가 '(지급)명세서 제출 내용' 화면으로
    # 바뀌며 접수번호(예: 135-2026-4-502810605410)가 표시됨. 팝업은 자동 수락되므로
    # 페이지 접수번호 등장 = 성공. WebSquare 모달로 뜨는 확인창은 별도로 눌러준다.
    for _ in range(timeout):
        # WebSquare 모달 확인(있으면) — '법정제출기한' 안내 등
        await _click_modal_confirm(page, must_contain="제출", log=log)
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if "접수번호" in body:
            m = RECEIPT_NO_RE.search(body)
            receipt = m.group(0) if m else "접수확인"
            log(f"[v] (홈택스) 지급명세서 제출 완료 — 접수번호 {receipt}")
            return receipt
        if any("제출이 완료" in m for m in dmsgs):
            log("[v] (홈택스) 지급명세서 제출 완료(알림 확인) — 접수번호 화면 대기")
        await page.wait_for_timeout(1000)
    if dmsgs:
        log(f"[i] (홈택스) 제출 응답: {' / '.join(m[:50] for m in dmsgs[-3:])}")
    log("[!] (홈택스) 접수번호 미확인 — 화면 확인 필요")
    return ""


# ─────────────────── 신고내역 조회(접수증·납부서) — 원천세 ───────────────────

LINK_RECEIPT_INQUIRY = "신고내역 조회(접수증·납부서)"


async def navigate_to_inquiry(page, log=print) -> bool:
    """원천세 신고 화면(딥링크 우선) → '신고내역 조회(접수증·납부서)' 모달. (라이브 확인)"""
    reached = False
    try:
        await page.goto(WONCHEON_MENU_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        body = await page.locator("body").inner_text(timeout=5000)
        reached = "원천세 신고" in body
    except Exception:
        pass
    if not reached:
        await reset_to_home(page, log)
        if not await _open_and_click_submenu(page, MENU_PARENT, MENU_WONCHEON, log):
            log("[!] (홈택스) 원천세 진입 실패")
            return False
        await page.wait_for_timeout(1500)
    for label in [LINK_RECEIPT_INQUIRY, "신고내역 조회", "접수증·납부서"]:
        try:
            loc = page.get_by_text(label, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=5000)
                await page.wait_for_timeout(2500)
                log("[v] (홈택스) 신고내역 조회 모달 열림")
                return True
        except Exception:
            continue
    log("[!] (홈택스) 신고내역 조회 링크 못 찾음")
    return False


# '사업자등록번호/주민등록번호' 라벨이 붙은 입력칸의 인덱스를 frame 안에서 찾는다.
# 조회 모달엔 신고일자(달력) 등 다른 text 입력이 있어 라벨 기준으로 정밀 타겟팅.
_FIND_BIZNO_JS = """() => {
    const els = [...document.querySelectorAll("input[type=text], input[type=password]")];
    for (let i = 0; i < els.length; i++) {
        const e = els[i];
        const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        // 라벨 셀(이전 형제/부모의 직전 형제)에 '사업자등록번호' 텍스트가 있는지
        let n = e, found = false;
        for (let d = 0; d < 4 && n && !found; d++) {
            let sib = n.previousElementSibling;
            for (let s = 0; s < 3 && sib && !found; s++) {
                if ((sib.innerText || '').includes('사업자등록번호')) found = true;
                sib = sib.previousElementSibling;
            }
            n = n.parentElement;
        }
        if (found) return i;
    }
    return -1;
}"""


async def _fill_inquiry_bizno(page, biz_no: str, log=print) -> bool:
    """신고내역 조회 모달: '사업자등록번호/주민등록번호' 칸에 10자리(하이픈 없이) 입력."""
    digits = "".join(c for c in (biz_no or "") if c.isdigit())
    for frame in page.frames:
        try:
            idx = await frame.evaluate(_FIND_BIZNO_JS)
            if idx is not None and idx >= 0:
                await frame.locator("input[type=text], input[type=password]").nth(idx).fill(digits)
                log(f"[i] (홈택스) 사업자번호 입력 {digits[:3]}-**-*****")
                return True
        except Exception:
            continue
    # 폴백: 보이는 password 칸(양도세식 모달 대비)
    for frame in page.frames:
        try:
            pwl = frame.locator("input[type=password]")
            for i in range(await pwl.count()):
                el = pwl.nth(i)
                if await el.is_visible():
                    await el.fill(digits)
                    return True
        except Exception:
            continue
    log("[!] (홈택스) 조회 사업자번호 칸 못 찾음")
    return False


async def query_inquiry(page, biz_no: str, log=print) -> bool:
    """신고내역 조회 모달: 사업자번호 입력 → 조회 → 조회완료 알림 확인."""
    if not await _fill_inquiry_bizno(page, biz_no, log):
        return False
    await page.wait_for_timeout(400)
    if not await click_button_text(page, "조회", log):
        try:
            await page.get_by_role("button", name="조회").first.click(timeout=5000)
        except Exception as e:
            log(f"[!] (홈택스) 조회 클릭 실패: {str(e)[:60]}")
            return False
    await page.wait_for_timeout(2500)
    await _click_modal_confirm(page, must_contain="완료", log=log)
    await page.wait_for_timeout(1000)
    return True


async def open_receipt_docs(ctx, page, biz_no: str, log=print) -> bool:
    """사업자번호 조회 → 접수번호 링크 클릭(접수증/신고서/공개여부 창들 오픈)."""
    if not await query_inquiry(page, biz_no, log):
        return False
    try:
        await page.get_by_text(RECEIPT_NO_RE).first.click(timeout=6000)
    except Exception as e:
        log(f"[!] (홈택스) 접수번호 링크 클릭 실패: {str(e)[:60]}")
        return False
    await page.wait_for_timeout(4000)
    log("[v] (홈택스) 접수번호 링크 클릭 — 접수증/신고서 창 열림")
    return True


async def set_disclosure(ctx, disclose: bool = True, log=print) -> bool:
    """'신고서 보기 개인정보 공개여부' 팝업: 공개/비공개 선택 + 적용 (자식 frame 순회)."""
    target = "개인정보 공개" if disclose else "개인정보 비공개"
    for p in list(ctx.pages):
        try:
            b = await p.locator("body").inner_text(timeout=2000)
        except Exception:
            continue
        if "공개여부" not in b and "개인정보가 공개된" not in b:
            continue
        for frame in p.frames:
            try:
                lab = frame.get_by_text(target, exact=True).first
                if await lab.count() and await lab.is_visible():
                    await lab.click(timeout=3000)
            except Exception:
                pass
            try:
                aply = frame.get_by_text("적용", exact=True).first
                if await aply.count() and await aply.is_visible():
                    await aply.click(timeout=3000)
                    log(f"[i] (홈택스) 개인정보 {('공개' if disclose else '비공개')} 적용")
                    return True
            except Exception:
                pass
    return False


async def _clipreport_scope(window):
    """window 또는 그 자식 frame 중 m_reportHashMap을 가진 scope 반환."""
    try:
        if await window.evaluate("() => !!window.m_reportHashMap"):
            return window
    except Exception:
        pass
    for frame in window.frames:
        try:
            if await frame.evaluate("() => !!window.m_reportHashMap"):
                return frame
        except Exception:
            continue
    return None


async def _clipreport_print(scope, target, log=print, save: bool = True) -> bool:
    """clipreport 인쇄 → (save=True) PDF 저장 / (save=False) 기본 프린터로 출력.

    데이터 로드 → printWindowView() → (인쇄방식 레이어가 뜨면 change 발화로 PDF DOM 초기화
    + mRe_printExportInfo) → save면 fill_and_save. 레이어 없으면(접수증) printWindowView가 곧 인쇄.
    """
    try:
        await scope.wait_for_function(_CLIPREPORT_LOADED, timeout=30000)
    except Exception:
        log("  [!] (홈택스) clipreport 데이터 로드 대기 시간초과(계속)")
    await scope.wait_for_timeout(500)
    key = await scope.evaluate("""() => {
        const m=window.m_reportHashMap; if(!m)return null;
        const k=Object.keys(m)[0]; if(!k)return null;
        try{m[k].printWindowView();}catch(e){return '__ERR__'+e.message;} return k;
    }""")
    if not key or (isinstance(key, str) and key.startswith("__ERR__")):
        log(f"  [!] (홈택스) printWindowView 실패: {key}")
        return False
    await scope.wait_for_timeout(1500)
    # 인쇄방식 레이어(신고서)면: change 발화 → mRe_selectPrintRange(1) → mRe_printExportInfo
    layer_key = await scope.evaluate("""() => {
        const sel = document.querySelector('[id^="re_printType1"]');
        if(!sel) return null;
        const k = sel.id.replace('re_printType1','');
        sel.value='pdf'; sel.dispatchEvent(new Event('change',{bubbles:true}));
        const r = window.m_reportHashMap[k];
        try{ if(r.mRe_selectPrintRange) r.mRe_selectPrintRange(1); }catch(e){}
        return k;
    }""")
    if layer_key:
        await scope.wait_for_timeout(1200)
        await scope.evaluate(f"""() => {{
            try{{ window.m_reportHashMap['{layer_key}'].mRe_printExportInfo(); }}catch(e){{}}
        }}""")
    if not save:
        # 출력 모드: 기본 프린터로 바로 출력됨(kiosk). 저장 다이얼로그 없음.
        await scope.wait_for_timeout(2500)
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    # 저장 다이얼로그 내부 진행 로그는 사용자에게 불필요 → log=None (실패 사유는 err로 받음)
    ok, err = await asyncio.to_thread(pdf_save.fill_and_save, target, 25.0, None)
    if not ok:
        log(f"  [!] (홈택스) PDF 저장 실패: {err}")
    return ok


async def print_documents(ctx, page, pdf_dir, label: str, disclose: bool = True,
                          output_mode: str = "pdf", include_name: bool = False, log=print) -> dict:
    """접수번호 링크로 열린 접수증 + 신고서 목록을 PDF저장/출력. 반환: {saved:[...], failed:[...]}.

    호출 전 open_receipt_docs로 창들이 열려 있어야 함. output_mode 'print'면 기본 프린터로 출력.
    LIVE-TODO: 원천세 신고서 목록 항목명('이행상황신고서' 등)에 맞게 필터 확인.
    """
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    await set_disclosure(ctx, disclose, log)
    await page.wait_for_timeout(1500)

    # 접수증 (clipreport.do 최상위 창)
    report = next((p for p in ctx.pages if "clipreport" in (p.url or "")), None)
    if report:
        await report.wait_for_timeout(1500)
        sc = await _clipreport_scope(report)
        tgt = pdf_dir / pdf_save.doc_name("접수증", [], include_name, label)
        if sc and await _clipreport_print(sc, tgt, log, save=save):
            result["saved"].append(tgt.name)
            log(f"[v] (홈택스) 접수증 {'저장' if save else '출력'}: {tgt.name}")
        else:
            result["failed"].append("[접수증]")
        try:
            await report.close()
        except Exception:
            pass
    await page.wait_for_timeout(1000)

    # 신고서 보기 뷰어 — 원천세(라이브 확인): 좌측 '신고서 목록'(체크박스) + 우측 뷰어에
    # 기본 신고서(원천징수이행상황신고서)가 이미 표시된 상태. 표시된 리포트를 바로 인쇄한다.
    viewer = None
    for p in ctx.pages:
        try:
            if "신고서 목록" in await p.locator("body").inner_text(timeout=2000):
                viewer = p
                break
        except Exception:
            continue
    if viewer is None:
        log("[!] (홈택스) 신고서 보기 뷰어 없음")
        return result

    items = []
    for frame in viewer.frames:
        try:
            els = frame.locator("a, li, label")
            for i in range(min(await els.count(), 100)):
                el = els.nth(i)
                if await el.is_visible():
                    t = " ".join((await el.inner_text()).split())
                    if ("신고서" in t or "명세서" in t or "계산서" in t) and len(t) < 60 \
                            and t not in items:
                        items.append(t)
        except Exception:
            continue
    log(f"[i] (홈택스) 신고서 목록: {items or '(탐지 실패 — 표시된 신고서만 저장)'}")

    await viewer.wait_for_timeout(1500)
    sc = await _clipreport_scope(viewer)
    if sc is None:
        log("[!] (홈택스) 신고서 뷰어 clipreport 미탐지")
        result["failed"].append("신고서")
        return result
    it = items[0] if items else "원천세"
    fname = pdf_save.doc_name("신고서", [it], include_name, label)
    tgt = pdf_dir / fname
    if await _clipreport_print(sc, tgt, log, save=save):
        result["saved"].append(fname)
        log(f"[v] (홈택스) 신고서 {'저장' if save else '출력'}: {fname}")
    else:
        result["failed"].append(it)
    if len(items) > 1:
        # LIVE-TODO: 원천세는 보통 1종 — 여러 종이면 체크박스 선택→일괄출력 흐름 확정 필요
        log(f"[!] (홈택스) 신고서 {len(items)}종 감지 — 첫 항목만 처리(나머지는 수동 확인)")
    # 저장 끝난 신고서 뷰어 창 닫기(접수증 창처럼 정리 — 창이 쌓이지 않게)
    try:
        await viewer.close()
    except Exception:
        pass
    return result


async def _click_text_in_frames(window, text: str) -> bool:
    for frame in window.frames:
        try:
            loc = frame.get_by_text(text, exact=True).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


def _norm_due_input(s: str) -> str:
    """사용자 입력 납부기한 정규화 → 'YYYY-MM-DD'. (2026-07-10 / 26.07.10 / 20260710 허용)"""
    d = "".join(c for c in (s or "") if c.isdigit())
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    if len(d) == 6:
        return f"20{d[:2]}-{d[2:4]}-{d[4:]}"
    return ""


async def print_napbu(ctx, page, pdf_dir, label: str = "", output_mode: str = "pdf",
                      include_name: bool = False, log=print, due_override: str = "") -> dict:
    """신고내역 모달의 납부서 [보기] → '납부서 목록' 모달 → 행별 [출력] → PDF저장/출력.

    원천세 라이브 확인: 납부서 목록은 신고서종류별 행 + [출력] 버튼 구조.
    [출력] 클릭 시 납부세액 0원이면 '납부세액이 없습니다.' 알림 → 확인 후 없음 처리,
    세액 있으면 clipreport 창 → 저장. 파일명: [납부서]{이름}_원천세_{납부기한}_{소득구분}.pdf.
    납부기한: ①사용자 입력(due_override) ②납부서 화면 추출 ③과세기간 다음달 10일 계산.
    """
    pdf_dir = Path(pdf_dir)
    save = (output_mode == "pdf")
    result = {"saved": [], "failed": []}

    await page.bring_to_front()
    # 신고내역 행엔 접수증 [보기] + 납부서 [보기]가 있고, 조회 결과가 여러 행(여러 달)일 수
    # 있다 → 페이지 전체가 아니라 '첫 데이터 행(최신 신고분)' 안에서 마지막 보기(=납부서)를
    # 클릭. 행에 보기가 1개뿐이면 납부서 없음(환급/무납부).
    _NAPBU_BOGI_JS = """() => {
        for (const row of document.querySelectorAll('tr')) {
            const btns = [...row.querySelectorAll(
                "a, button, input[type=button], input[type=submit]")]
                .filter(e => { const r = e.getBoundingClientRect();
                               return r.width > 1 && r.height > 1; })
                .filter(e => ((((e.innerText || e.value) || '') + '').trim()) === '보기');
            if (!btns.length) continue;
            if (btns.length >= 2) { btns[btns.length - 1].click(); return 'clicked'; }
            return 'no-napbu';
        }
        return 'no-rows';
    }"""
    outcome = "no-rows"
    for frame in page.frames:
        try:
            outcome = await frame.evaluate(_NAPBU_BOGI_JS)
            if outcome in ("clicked", "no-napbu"):
                break
        except Exception:
            continue
    if outcome == "no-napbu":
        log("[i] (홈택스) 납부서 보기 없음(환급/무납부) — 건너뜀")
        return result
    if outcome != "clicked":
        log("[!] (홈택스) 신고내역 행을 못 찾음")
        return result
    await page.wait_for_timeout(2500)

    # '납부서 목록' 모달(원천세 라이브 확인): 신고서종류별 행 + [출력] 버튼.
    # [출력] 클릭 → ⓐ '납부세액이 없습니다.' 알림 → 확인(없음 처리)
    #            → ⓑ clipreport 납부서 창 → PDF 저장.
    _FIND_PRINT_BTNS_JS = """() => {
        const out = [];
        const els = document.querySelectorAll(
            "a, button, input[type=button], input[type=submit]");
        for (let i = 0; i < els.length; i++) {
            const e = els[i];
            const r = e.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const t = (((e.innerText || e.value) || '') + '').trim();
            if (t !== '출력') continue;
            const row = e.closest('tr');
            const txt = row ? (row.innerText || '') : '';
            const m = txt.match(/[가-힣]*소득세/);          // 소득구분 (예: 사업소득세)
            const p = txt.match(/20\\d\\d년\\s*\\d{1,2}월/); // 과세기간 (예: 2026년1월)
            out.push({ i: i, label: m ? m[0] : '',
                       period: p ? p[0].replace(/\\s+/g, '') : '' });
        }
        return out;
    }"""
    btns = []
    scope = None
    for frame in page.frames:
        try:
            found = await frame.evaluate(_FIND_PRINT_BTNS_JS)
            if found:
                btns, scope = found, frame
                break
        except Exception:
            continue
    log(f"[i] (홈택스) 납부서 [출력] 버튼 {len(btns)}건: "
        f"{[b['label'] or '?' for b in btns]}")
    if not btns:
        log("[i] (홈택스) 납부서 출력 대상 없음 — 건너뜀")
        return result

    for k, b in enumerate(btns):
        tag = b["label"] or (f"{k + 1}" if len(btns) > 1 else "")
        win = None
        try:
            try:
                async with ctx.expect_page(timeout=5000) as info:
                    await scope.locator(_BTN_SELECTOR).nth(b["i"]).click(timeout=5000)
                win = await info.value
            except Exception:
                win = None
            if win is None:
                # 새 창 없음 → '납부세액이 없습니다.' 알림인지 확인
                if await _click_modal_confirm(page, must_contain="납부세액", log=log):
                    log(f"[i] (홈택스) 납부서({tag or k + 1}) 납부세액 없음 — 건너뜀")
                    continue
                log(f"[!] (홈택스) 납부서({tag or k + 1}) 출력 반응 없음")
                result["failed"].append(f"납부서{k + 1}")
                continue
            await win.wait_for_timeout(1500)
            sc = await _clipreport_scope(win)
            # 납부기한: ①사용자 입력 ②납부서 화면 텍스트 추출 ③과세기간 다음달 10일 계산
            # (기한후신고 등은 규칙과 달라 사용자 입력이 최우선 — 원천세 목록엔 기한 컬럼 없음)
            due_raw = _norm_due_input(due_override)
            if due_raw:
                log(f"  [i] 납부기한(입력값): {due_raw}")
            else:
                due_raw = await _win_due_date(win)
                if due_raw:
                    log(f"  [i] 납부기한(화면 추출): {due_raw}")
                else:
                    due_raw = _due_from_period(b.get("period", ""))
                    if due_raw:
                        log(f"  [i] 납부기한(규칙 계산: 과세기간 다음달 10일): {due_raw}")
            due = pdf_save.fmt_due(due_raw)
            # 파일명: [납부서]{이름}_원천세_{납부기한}.pdf
            # (소득구분은 납부서가 여러 종일 때만 붙임 — 파일명 충돌 방지)
            extras = ["원천세", due] + ([tag] if len(btns) > 1 else [])
            tgt = pdf_dir / pdf_save.doc_name("납부서", extras, include_name, label)
            if sc and await _clipreport_print(sc, tgt, log, save=save):
                result["saved"].append(tgt.name)
                log(f"[v] (홈택스) 납부서 {'저장' if save else '출력'}: {tgt.name}")
            else:
                result["failed"].append(f"납부서{k + 1}")
            try:
                await win.close()
            except Exception:
                pass
        except Exception as e:
            log(f"[!] (홈택스) 납부서{k + 1} 실패: {str(e)[:70]}")
            result["failed"].append(f"납부서{k + 1}")
    # 납부서 목록 팝업 닫기
    try:
        await page.get_by_text("닫기", exact=True).last.click(timeout=3000)
    except Exception:
        pass
    return result
