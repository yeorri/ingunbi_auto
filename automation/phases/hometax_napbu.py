"""Phase: 홈택스 원천세 납부서 PDF저장/출력.

홈 리셋 → 신고/납부 → 원천세 → '신고내역 조회' → 사업자번호 조회
→ 납부서 [보기] → 납부서 목록 → 각 납부서 PDF. 환급/무납부면 0건(성공 처리).
접수증·신고서 출력(hometax_docs)과 분리 — 위택스 가상계좌 대기 동안 막히지 않게.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "hometax_napbu"
LABEL = "홈택스 납부서 출력"
SITE = "홈택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    digits = "".join(c for c in (inp.biz_no or "") if c.isdigit())
    if len(digits) != 10:
        res.reason = "사업자등록번호(10자리) 필요"
        log(f"[!] {res.reason}")
        return res
    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    if not await H.navigate_to_inquiry(page, log):
        res.reason = "신고내역 조회 화면 진입 실패"
        return res
    if not await H.query_inquiry(page, digits, log):
        res.reason = "사업자번호 조회 실패"
        return res

    summary = await H.print_napbu(
        ctx, page, out_dir, label=inp.name_label, output_mode=inp.output_mode,
        include_name=inp.include_name, log=log, due_override=inp.napbu_due,
    )
    res.outputs = summary.get("saved", [])
    failed = summary.get("failed", [])
    verb = "저장" if inp.output_mode == "pdf" else "출력"
    if failed:
        res.ok = bool(res.outputs)
        res.reason = f"{len(res.outputs)}건 {verb}, {len(failed)}건 실패: {failed}"
    elif res.outputs:
        res.ok = True
        res.reason = f"납부서 {len(res.outputs)}건 {verb} 완료"
    else:
        res.ok = True  # 환급/무납부 — 정상(없음)
        res.reason = "납부서 없음(환급/무납부) — 건너뜀"
    return res
