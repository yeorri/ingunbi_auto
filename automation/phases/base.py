"""Phase 공통 타입 — 입력 묶음과 결과.

각 phase는 독립 모듈(KEY/LABEL/run)로 개발하고, 동일한 Inputs/PhaseResult를 공유한다.
phase 내부 세부 단계는 단정짓지 않는다(라이브 화면 보며 단계별로 채움).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Inputs:
    """실행 전에 GUI에서 한 번에 받아두는 입력. phase가 필요한 것만 골라 쓴다."""
    name_label: str = "업체"            # 업체명(상호) — 파일명/위택스 행 찾기용
    biz_no: str = ""                    # 사업자등록번호 (홈택스 신고내역 조회용)
    hometax_convert_file: str = ""      # 홈택스 원천세 변환파일 (.01/.enc, 세무사랑 제작)
    # 간이지급명세서: (명세서 종류 라벨, 변환파일 경로) 목록 — 종류 하나당 제출 1회.
    # 종류 라벨은 hometax.JIGUP_TYPES(홈택스 드롭다운 표기 그대로) 중 하나.
    jigup_jobs: list = field(default_factory=list)
    jigup_report_type: str = "정기신고"  # 제출구분: 정기신고 | 수정신고 | 기한후신고
    jigup_pay_ym: str = ""              # 지급연월 YYYY-MM (수정·기한후신고만, 정기는 자동)
    wetax_convert_file: str = ""        # 위택스 특별징수 파일 — ';' 여러 개 또는 폴더 경로
    file_password: str = ""             # 세무사랑 암호화 파일 비밀번호 (홈택스·위택스 공용)
    napbu_due: str = ""                 # 납부기한(선택, 예 2026-07-10) — 홈택스 납부서 파일명용
    output_dir: str = ""                # PDF 저장 경로
    output_mode: str = "pdf"            # "pdf"(저장) | "print"(출력)
    auto_submit: bool = True            # 파일변환신고 제출까지 자동 여부
    disclose_personal_info: bool = True # 서류 출력 시 개인정보 공개 여부(디폴트 공개)
    include_name: bool = False          # 서류 파일명에 업체명 포함
    napbu_wait_sec: int = 180           # 위택스 납부서 출력 전 가상계좌 생성 대기(초)


@dataclass
class PhaseResult:
    key: str
    label: str
    ok: bool = False
    receipt_no: str = ""
    outputs: list[str] = field(default_factory=list)   # 저장된 PDF 경로 등
    reason: str = ""
