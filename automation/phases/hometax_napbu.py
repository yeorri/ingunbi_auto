"""Phase: 홈택스 원천세 납부서 PDF저장/출력 — 작업 대장 순회(일괄) + 단일 폴백.

일괄 모드(기본): 이번 달 작업 대장에서 '홈택스 신고됨 & 납부서 미출력' 업체를 순회 —
업체별로 신고내역 조회(사업자번호) → 납부서 출력 → {저장폴더}\\{업체명}\\ 에 저장 →
대장에 출력 기록. 재실행하면 미출력분만 다시 시도한다(중단 안전).
대장이 비어 있으면(신고를 이 프로그램으로 안 한 경우) 입력된 사업자번호 1건만 처리.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .. import pdf_save
from .. import roster
from .base import Inputs, PhaseResult

KEY = "hometax_napbu"
LABEL = "홈택스 납부서 출력"
SITE = "홈택스"


def _company_dir(base: Path, name: str) -> Path:
    sub = pdf_save.sanitize_filename(name or "업체").replace(".pdf", "")
    d = base / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _print_one(ctx, page, inp: Inputs, out_base: Path, name: str, bizno: str,
                     log) -> str:
    """업체 1곳 납부서 출력. 반환 "done" | "none" | ""(실패)."""
    if not await H.navigate_to_inquiry(page, log):
        return ""
    if not await H.query_inquiry(page, bizno, log):
        return ""
    summary = await H.print_napbu(
        ctx, page, _company_dir(out_base, name), label=name,
        output_mode=inp.output_mode, include_name=inp.include_name, log=log,
        due_override=inp.napbu_due,
    )
    if summary.get("failed"):
        return ""
    return "done" if summary.get("saved") else "none"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    out_base = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    # 이번 달 대장에서 미출력분 검색 — 없으면 지난달 대장도 확인
    # (월말 신고 → 다음 달 초 출력하는 경우 대비)
    ym = roster.current_ym()
    entries = roster.load_ledger(ym)

    def _pending(ent):
        return [(k, e) for k, e in ent.items()
                if e.get("bizno") and e.get("ht", {}).get("filed_at")
                and not e["ht"].get("napbu")]

    pending = _pending(entries)
    if not pending:
        ym = roster.prev_ym()
        entries = roster.load_ledger(ym)
        pending = _pending(entries)
        if pending:
            log(f"[i] (홈택스) 지난달({ym}) 대장의 미출력분 {len(pending)}건 발견")

    if not pending:
        # 폴백: 대장이 없으면 입력된 사업자번호 1건 (기존 단일 모드)
        digits = "".join(c for c in (inp.biz_no or "") if c.isdigit())
        if len(digits) != 10:
            res.ok = True
            res.reason = "대장에 출력 대상 없음(모두 완료 또는 신고 기록 없음)"
            log(f"[i] {res.reason}")
            return res
        outcome = await _print_one(ctx, page, inp, out_base,
                                   inp.name_label, digits, log)
        res.ok = outcome in ("done", "none")
        res.reason = {"done": "납부서 저장 완료", "none": "납부서 없음(환급/무납부)",
                      "": "납부서 출력 실패"}[outcome]
        return res

    log(f"[i] (홈택스) 납부서 출력 대상 {len(pending)}곳 (대장 기준, 미출력분만)")
    done = skipped = failed = 0
    for i, (key, e) in enumerate(pending, 1):
        if stop_check and stop_check():
            log("[i] 중단됨 — 지금까지 결과는 대장에 저장됨")
            break
        name = e.get("name") or e.get("bizno")
        log(f"[i] (홈택스) [{i}/{len(pending)}] {name}")
        outcome = await _print_one(ctx, page, inp, out_base, name, e["bizno"], log)
        if outcome:
            e["ht"]["napbu"] = outcome
            entries[key] = e
            roster.save_ledger(entries, ym)   # 건별 저장 — 중단돼도 진행 보존
            done += outcome == "done"
            skipped += outcome == "none"
        else:
            failed += 1

    res.ok = failed == 0
    res.reason = f"저장 {done} / 없음 {skipped} / 실패 {failed} (총 {len(pending)})"
    if failed:
        res.reason += " — 실패분은 다시 실행하면 재시도됩니다"
    return res
