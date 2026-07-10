"""Phase: 위택스 지방세(특별징수) 납부서 PDF저장/출력 — 작업 대장 순회(일괄) + 단일 폴백.

⚠ 가상계좌는 신고 후 몇 분 뒤 생성 → 시작 전 inp.napbu_wait_sec 만큼 대기(중단 가능).
일괄 모드(기본): 대장에서 '위택스 신고됨 & 납부서 미출력' 업체 순회 — 납세자명+신고일자로
행을 특정해(공용 인증서라 다른 직원 신고와 구분) 납부서 출력, {저장폴더}\\{업체명}\\ 저장.
세액 0원 업체는 조회 없이 '없음' 처리. 재실행 시 미출력분만 재시도.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .. import browser as B
from .. import pdf_save
from .. import roster
from .. import wetax as W
from .base import Inputs, PhaseResult

KEY = "wetax_napbu"
LABEL = "위택스 납부서 출력"
SITE = "위택스"


async def _wait(sec: int, emit, stop_check) -> None:
    """가상계좌 생성 대기(1초 단위, 중단 가능). 10초마다 남은 시간 로그."""
    log = lambda m: emit("log", text=m)
    if sec <= 0:
        return
    log(f"[i] (위택스) 가상계좌 생성 대기 {sec}초…")
    for elapsed in range(sec):
        if stop_check and stop_check():
            log("[i] (위택스) 대기 중단됨")
            return
        if elapsed and elapsed % 10 == 0:
            log(f"    대기 {elapsed}/{sec}초")
        await asyncio.sleep(1)


def _company_dir(base: Path, name: str) -> Path:
    sub = pdf_save.sanitize_filename(name or "업체").replace(".pdf", "")
    d = base / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    out_base = Path(inp.output_dir) if inp.output_dir else (Path.home() / "Downloads")
    page = B.find_page(ctx, "wetax.go.kr")
    if page is None:
        res.reason = "위택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res

    entries = roster.load_ledger()
    pending = [(k, e) for k, e in entries.items()
               if e.get("wt", {}).get("filed_at") and not e["wt"].get("napbu")]

    if not pending:
        res.ok = True
        res.reason = "대장에 출력 대상 없음(모두 완료 또는 위택스 신고 기록 없음)"
        log(f"[i] {res.reason}")
        return res

    await _wait(int(inp.napbu_wait_sec or 0), emit, stop_check)
    if stop_check and stop_check():
        res.reason = "중단됨"
        return res
    await page.bring_to_front()

    log(f"[i] (위택스) 납부서 출력 대상 {len(pending)}곳 (대장 기준, 미출력분만)")
    due = (inp.napbu_due or "").strip()
    done = skipped = failed = 0
    for i, (key, e) in enumerate(pending, 1):
        if stop_check and stop_check():
            log("[i] 중단됨 — 지금까지 결과는 대장에 저장됨")
            break
        wt = e["wt"]
        name = e.get("name") or wt.get("wt_name", "")
        wt_name = wt.get("wt_name") or e.get("ceo") or name
        # 세액 0원은 납부서가 없다 — 조회 없이 바로 '없음' 처리
        if (wt.get("amount") or "") in ("", "0"):
            wt["napbu"] = "none"
            entries[key] = e
            roster.save_ledger(entries)
            skipped += 1
            log(f"[i] (위택스) [{i}/{len(pending)}] {name} — 세액 0원, 건너뜀")
            continue
        log(f"[i] (위택스) [{i}/{len(pending)}] {name} (납세자명 {wt_name})")
        fname = pdf_save.doc_name("납부서", ["지방세", due], inp.include_name, name)
        outcome = await W.print_napbu_for(
            ctx, page, _company_dir(out_base, name), wt_name,
            wt.get("filed_at", ""), fname, output_mode=inp.output_mode, log=log)
        if outcome:
            wt["napbu"] = outcome
            entries[key] = e
            roster.save_ledger(entries)   # 건별 저장 — 중단돼도 진행 보존
            done += outcome == "done"
            skipped += outcome == "none"
        else:
            failed += 1

    res.ok = failed == 0
    res.reason = f"저장 {done} / 없음 {skipped} / 실패 {failed} (총 {len(pending)})"
    if failed:
        res.reason += " — 실패분은 다시 실행하면 재시도됩니다(가상계좌 지연이면 잠시 후)"
    return res
