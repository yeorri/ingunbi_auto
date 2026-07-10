"""Phase: 홈택스 원천세 파일변환신고.

흐름(양도세 파일변환신고에서 검증된 기계장치 재사용):
  메뉴 내비게이션 → 파일 주입(KUpload, set_input_files) → 파일검증하기
  → 종전내역 모달 처리 → 검증 완료 대기 → [제출하러 가기]→[전자파일 제출하기] → 접수증.
LIVE-TODO: 원천세 메뉴 경로 확정 (automation/hometax.py 참조).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .. import roster
from .base import Inputs, PhaseResult

KEY = "hometax_filing"
LABEL = "홈택스 원천세 파일변환신고"
SITE = "홈택스"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    if not inp.hometax_convert_file or not Path(inp.hometax_convert_file).exists():
        res.reason = "홈택스 변환파일 경로가 없거나 파일이 없음"
        log(f"[!] {res.reason}: {inp.hometax_convert_file}")
        return res

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    # 1) 메뉴 → 파일변환신고 화면
    if not await H.navigate_to_file_convert(page, log):
        res.reason = "메뉴 내비게이션 실패"
        return res
    await H.handle_prev_record_modal(page, log)  # 진입 시 모달이 떠 있으면 처리

    # 2) 파일 주입 (KUpload) — 주입 직후에도 종전내역 모달이 뜰 수 있음(라이브 확인)
    if not await H.inject_convert_file(page, inp.hometax_convert_file, log):
        res.reason = "파일 주입 실패"
        return res
    await H.handle_prev_record_modal(page, log)

    # 3) 파일검증하기 → 모달 처리 → (.enc 비밀번호 입력) → 검증 완료 대기
    status = await H.verify_and_wait(page, log, file_password=inp.file_password)
    if status != "완료":
        res.reason = f"검증 미완료({status})"
        return res

    if not inp.auto_submit:
        log("[i] (홈택스) 검증 완료. auto_submit=False → 제출은 사람이 직접.")
        res.ok = True
        res.reason = "검증완료(수동제출 모드)"
        return res

    # 4) 제출하러 가기 → 전자파일 제출하기 → 제출확인 → 접수증 (실제·비가역)
    run_start = datetime.now()
    ok = await H.submit_filing(page, log)
    res.ok = ok
    res.reason = "제출 완료" if ok else "제출 실패"

    if ok:
        # 방금 신고분(상호·사업자번호·접수번호)을 신고내역 조회에서 수집 → 작업 대장 기록.
        # 접수일시가 제출 시각 이후인 행만 취해 같은 날 다른 작업과 섞이지 않게 한다.
        since = (run_start - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")
        try:
            rows = await H.collect_filed_rows(page, since=since, log=log)
            if rows:
                n = roster.record_ht_rows(rows)
                log(f"[i] (홈택스) 작업 대장에 {n}건 기록")
                res.reason += f" (대장 {n}건)"
        except Exception as e:  # noqa: BLE001 — 수집 실패해도 신고 성공엔 영향 없음
            log(f"[!] (홈택스) 대장 수집 실패(신고는 완료됨): {str(e)[:60]}")
    return res
