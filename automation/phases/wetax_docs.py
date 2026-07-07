"""Phase: 위택스 지방세(특별징수) 신고서 PDF저장/출력 (납부서 제외).

특별징수 신고내역 → 상세검색(사업자등록번호로 1건 필터) → 행 체크
→ [신고결과서출력] → OZ 뷰어 [인쇄]→[확인] → PDF저장/출력.
납부서(가상계좌)는 별도 phase(wetax_napbu)에서.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_docs"
LABEL = "위택스 신고서 출력"
SITE = "위택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    digits = "".join(c for c in (inp.biz_no or "") if c.isdigit())
    if len(digits) != 10:
        res.reason = "사업자등록번호(10자리) 필요"
        log(f"[!] {res.reason}")
        return res
    out_dir = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    summary = await W.print_singo(
        ctx, page, out_dir, digits, inp.name_label, output_mode=inp.output_mode,
        include_name=inp.include_name, log=log,
    )
    res.outputs = summary.get("saved", [])
    failed = summary.get("failed", [])
    verb = "저장" if inp.output_mode == "pdf" else "출력"
    if res.outputs and not failed:
        res.ok = True
        res.reason = f"{len(res.outputs)}건 {verb} 완료"
    elif res.outputs:
        res.ok = True
        res.reason = f"{len(res.outputs)}건 {verb}, {len(failed)}건 실패: {failed}"
    else:
        res.reason = f"위택스 신고서 {verb} 실패: {failed}"
    return res
