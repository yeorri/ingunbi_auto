"""Phase: 위택스 지방소득세 특별징수 회계파일신고.

실행 단위 = 업체 1곳 → 보통 파일 1개. (';'/폴더로 여러 개 넣으면 순차 반복도 지원.)

건당 흐름(화면 라이브 확인): 회계파일신고(B070101M31) → 파일 주입 + 파일비밀번호
→ [파일변환하기] → JS 확인창 자동수락 → M32 '정상 신고 내역 N건' → [제출하기].
(기본 순서상 첫 번째 — 지방세 납부서 가상계좌가 늦게 떠서 먼저 돌리는 게 유리.)
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_filing"
LABEL = "위택스 특별징수 파일신고"
SITE = "위택스"


def expand_files(raw: str) -> list[str]:
    """';' 구분 파일 목록 또는 폴더 경로 → 파일 경로 리스트."""
    items = [s.strip() for s in (raw or "").split(";") if s.strip()]
    out: list[str] = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            out.extend(str(f) for f in sorted(p.iterdir()) if f.is_file())
        else:
            out.append(it)
    return out


async def _file_one(page, file_path: str, inp: Inputs, log) -> tuple[bool, str]:
    """특별징수 파일 1건 신고. (성공여부, 사유)."""
    if not await W.navigate_to_filing(page, log):
        return False, "화면 진입 실패"
    if not await W.inject_file(page, file_path, log):
        return False, "파일 주입 실패"
    if not await W.fill_file_password(page, inp.file_password, log):
        return False, "파일비밀번호 입력 실패"
    if not await W.convert_and_verify(page, log):
        return False, "서식검증 실패(오류/시간초과)"
    if not inp.auto_submit:
        log("[i] (위택스) 서식검증 완료. auto_submit=False → 제출은 사람이 직접.")
        return True, "검증완료(수동제출 모드)"
    ok = await W.submit_filing(page, log)
    return ok, ("제출 완료" if ok else "제출 실패")


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    files = expand_files(inp.wetax_convert_file)
    missing = [f for f in files if not Path(f).exists()]
    if not files or missing:
        res.reason = f"위택스 파일 없음: {missing or '(미입력)'}"
        log(f"[!] {res.reason}")
        return res
    if not inp.file_password:
        res.reason = "파일 비밀번호 미입력"
        log(f"[!] {res.reason}")
        return res

    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    reasons = []
    ok_count = 0
    for i, f in enumerate(files, 1):
        if stop_check and stop_check():
            reasons.append("중단됨")
            break
        log(f"[i] (위택스) 특별징수 {i}/{len(files)}: {Path(f).name}")
        ok, why = await _file_one(page, f, inp, log)
        reasons.append(f"{Path(f).name}: {why}")
        if ok:
            ok_count += 1

    res.ok = ok_count == len(files) and bool(files)
    res.reason = f"{ok_count}/{len(files)}건 — " + " / ".join(reasons[:5]) + \
                 (" …" if len(reasons) > 5 else "")
    return res
