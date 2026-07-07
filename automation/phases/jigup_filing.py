"""Phase: 홈택스 간이지급명세서 제출 (변환파일) — 사용자 확인 흐름 반영(2026-07-03).

건당 흐름:
  신청/제출 → (일용·간이·용역) 변환파일 제출 → 명세서 종류 선택
  → (검증내역 팝업 확인) → [파일선택] → (진행중 파일 팝업 확인)
  → '변환할 지급명세서 파일 선택' 창에서 파일 주입 + [파일 업로드]
  → 제출구분 라디오(정기 기본, 수정·기한후는 지급연월 입력) → [파일검증 시작하기]
  → 암호입력 모달(파일 암호) → 검증 완료([제출하기] 등장) / 오류 팝업이면 실패
  → '위 내용을 확인하고 제출합니다' 체크 → [제출하기] → 확인 팝업들 → 제출 완료.

GUI에서 (명세서 종류, 변환파일) 행을 자유롭게 추가 — 종류 하나당 제출 1회 반복.
"""
from __future__ import annotations

from pathlib import Path

from .. import browser as B
from .. import hometax as H
from .base import Inputs, PhaseResult

KEY = "jigup_filing"
LABEL = "홈택스 간이지급명세서 제출"
SITE = "홈택스"


async def _submit_one(ctx, page, file_path: str, type_label: str,
                      inp: Inputs, log) -> tuple[bool, str]:
    """간이지급명세서 파일 1개 제출. (성공여부, 사유)."""
    if not await H.navigate_to_jigup(page, log):
        return False, "메뉴 내비게이션 실패"
    if not await H.jigup_select_type(page, type_label, log):
        return False, f"명세서 종류 선택 실패({type_label})"
    if not await H.jigup_upload_file(ctx, page, file_path, log):
        return False, "파일 업로드 실패"
    if not await H.jigup_set_report_type(page, inp.jigup_report_type, inp.jigup_pay_ym, log):
        return False, "제출구분 설정 실패"
    if not await H.jigup_verify(ctx, page, inp.file_password, log):
        return False, "파일검증 실패(오류/시간초과)"
    if not inp.auto_submit:
        log("[i] (홈택스) 검증 완료. auto_submit=False → 체크박스+제출하기는 사람이 직접.")
        return True, "검증완료(수동제출 모드)"
    receipt = await H.jigup_submit(page, log)
    if receipt:
        return True, f"제출 완료(접수 {receipt})"
    return False, "제출 확인 실패 — 화면 확인 필요"


async def run(ctx, inp: Inputs, emit, stop_check=None) -> PhaseResult:
    log = lambda m: emit("log", text=m)
    res = PhaseResult(KEY, LABEL)

    jobs: list[tuple[str, str]] = []   # (파일, 종류 라벨)
    for label, f in (inp.jigup_jobs or []):
        if label not in H.JIGUP_TYPES:
            res.reason = f"알 수 없는 명세서 종류: {label}"
            log(f"[!] {res.reason}")
            return res
        if not f or not Path(f).exists():
            res.reason = f"파일 없음: {f or '(미입력)'} ({label})"
            log(f"[!] {res.reason}")
            return res
        jobs.append((f, label))
    if not jobs:
        res.reason = "간이지급명세서 (종류, 파일) 미입력"
        log(f"[!] {res.reason}")
        return res
    if inp.jigup_report_type != "정기신고" and not inp.jigup_pay_ym:
        res.reason = f"{inp.jigup_report_type}는 지급연월(YYYY-MM) 입력 필요"
        log(f"[!] {res.reason}")
        return res

    page = B.find_page(ctx, "hometax.go.kr")
    if page is None:
        res.reason = "홈택스 페이지를 찾을 수 없음"
        log(f"[!] {res.reason}")
        return res
    await page.bring_to_front()

    reasons = []
    ok_count = 0
    for i, (f, label) in enumerate(jobs, 1):
        if stop_check and stop_check():
            reasons.append("중단됨")
            break
        log(f"[i] (홈택스) 간이지급명세서 {i}/{len(jobs)} [{label}]: {Path(f).name}")
        ok, why = await _submit_one(ctx, page, f, label, inp, log)
        reasons.append(f"{Path(f).name}: {why}")
        if ok:
            ok_count += 1

    res.ok = ok_count == len(jobs)
    res.reason = f"{ok_count}/{len(jobs)}건 — " + " / ".join(reasons)
    return res
