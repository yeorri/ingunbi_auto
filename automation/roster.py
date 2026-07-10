"""거래처 명부 + 월별 작업 대장.

- 명부(clients.json): 담당 거래처 [{name, bizno, ceo}] — 엑셀/CSV 가져오기로 등록.
  대표자명(ceo)은 위택스 납세자명(개인사업자=대표자)과 업체를 잇는 열쇠.
- 대장(ledger-YYYY-MM.json): 이번 달 신고·출력 기록. 신고 phase가 자동 기입하고
  납부서 phase는 '미출력' 항목만 순회 → 재실행해도 이미 뽑은 건 건너뛴다.

대장 entry (key = 사업자번호 10자리, 위택스만 잡힌 경우 "wt:{이름}"):
  { name, bizno, ceo,
    ht: {filed_at, taxym, receipt, napbu},   # napbu: "" | "done" | "none"
    wt: {filed_at, taxym, amount, napbu} }
저장 위치는 %LOCALAPPDATA%\\IngunbiAuto (개발 시 프로젝트 폴더) — 버전 교체와 무관하게 유지.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from .browser import app_data_dir

CLIENTS_PATH = app_data_dir() / "clients.json"


def _norm_bizno(s: str) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    return d if len(d) == 10 else ""


# ─────────────────────────── 명부 ───────────────────────────

def load_clients() -> list[dict]:
    try:
        rows = json.loads(CLIENTS_PATH.read_text(encoding="utf-8"))
        return [r for r in rows if r.get("name")]
    except Exception:
        return []


def save_clients(rows: list[dict]) -> None:
    CLIENTS_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def import_table(path: str) -> list[dict]:
    """엑셀(.xlsx)/CSV에서 (업체명, 사업자등록번호, 대표자명) 추출.

    열 제목 행(업체명·사업자등록번호·대표자 등 키워드)을 찾아 해당 열만 읽는다 —
    아이디/비밀번호 등 다른 열이 섞여 있어도 무시. 제목 행이 없으면 앞 3열로 간주.
    """
    p = Path(path)
    if p.suffix.lower() == ".csv":
        grid = _read_csv(p)
    else:
        grid = _read_xlsx(p)

    name_i = biz_i = ceo_i = None
    header_row = -1
    for ri, row in enumerate(grid[:10]):   # 제목은 앞쪽 몇 행 안에 있다고 가정
        for ci, cell in enumerate(row):
            c = str(cell or "")
            if name_i is None and any(k in c for k in ("업체명", "거래처", "상호", "회사명")):
                name_i, header_row = ci, ri
            if biz_i is None and "사업자" in c:
                biz_i, header_row = ci, ri
            if ceo_i is None and "대표" in c:
                ceo_i = ci
        if name_i is not None and biz_i is not None:
            break
    if name_i is None or biz_i is None:    # 제목 행 없음 → 앞 3열 (업체명|사업자번호|대표자)
        name_i, biz_i, ceo_i, header_row = 0, 1, 2, -1

    out, seen = [], set()
    for row in grid[header_row + 1:]:
        def cell(i):
            return str(row[i]).strip() if (i is not None and i < len(row)
                                           and row[i] is not None) else ""
        name, bizno, ceo = cell(name_i), _norm_bizno(cell(biz_i)), cell(ceo_i)
        if not name or not bizno or bizno in seen:
            continue
        seen.add(bizno)
        out.append({"name": name, "bizno": bizno, "ceo": ceo})
    return out


def _read_csv(p: Path) -> list[list]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, newline="", encoding=enc) as f:
                return [row for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    return []


def _read_xlsx(p: Path) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb.active
    grid = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return grid


# ─────────────────────────── 대장 ───────────────────────────

def current_ym() -> str:
    return date.today().strftime("%Y-%m")


def prev_ym() -> str:
    d = date.today().replace(day=1)
    d = d.replace(year=d.year - 1, month=12) if d.month == 1 \
        else d.replace(month=d.month - 1)
    return d.strftime("%Y-%m")


def ledger_path(ym: str | None = None) -> Path:
    return app_data_dir() / f"ledger-{ym or current_ym()}.json"


def load_ledger(ym: str | None = None) -> dict:
    try:
        data = json.loads(ledger_path(ym).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_ledger(entries: dict, ym: str | None = None) -> None:
    ledger_path(ym).write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def _blank_entry(name="", bizno="", ceo="") -> dict:
    return {"name": name, "bizno": bizno, "ceo": ceo,
            "ht": {}, "wt": {}}


def _find_client(clients: list[dict], *, bizno="", wt_name="") -> dict | None:
    for c in clients:
        if bizno and c.get("bizno") == bizno:
            return c
        if wt_name and wt_name in (c.get("ceo"), c.get("name")):
            return c
    return None


def record_ht_rows(rows: list[dict], ym: str | None = None) -> int:
    """홈택스 신고내역 수집 결과를 대장에 기입. rows: {name,bizno,at,taxym,receipt}."""
    entries = load_ledger(ym)
    clients = load_clients()
    n = 0
    for r in rows:
        bizno = _norm_bizno(r.get("bizno", ""))
        if not bizno:
            continue
        e = entries.get(bizno)
        if e is None:
            c = _find_client(clients, bizno=bizno) or {}
            e = _blank_entry(r.get("name") or c.get("name", ""), bizno, c.get("ceo", ""))
            entries[bizno] = e
        e["ht"].setdefault("napbu", "")
        e["ht"].update({"filed_at": r.get("at", ""), "taxym": r.get("taxym", ""),
                        "receipt": r.get("receipt", "")})
        n += 1
    save_ledger(entries, ym)
    return n


def add_manual(clients_sel: list[dict], *, ht: bool, wt: bool,
               filed_at: str, ym: str | None = None) -> int:
    """수기(프로그램 밖) 신고분을 대장에 '미출력' 상태로 등록 — 납부서 출력 대기열에 추가.

    이미 대장에 있는 업체는 신고 표시만 보강한다(출력 기록은 건드리지 않음).
    """
    entries = load_ledger(ym)
    n = 0
    for c in clients_sel:
        bizno = _norm_bizno(c.get("bizno", ""))
        key = bizno or f"wt:{c.get('ceo') or c.get('name', '')}"
        e = entries.get(key) or _blank_entry(c.get("name", ""), bizno, c.get("ceo", ""))
        if ht and not e["ht"].get("filed_at"):
            e["ht"].update({"filed_at": filed_at + " (수기)", "napbu": e["ht"].get("napbu", "")})
        if wt and not e["wt"].get("filed_at"):
            e["wt"].update({"filed_at": filed_at, "napbu": e["wt"].get("napbu", ""),
                            "wt_name": c.get("ceo") or c.get("name", ""),
                            "amount": "?"})   # 수기분은 세액 미상 → 0원 스킵 안 함
        entries[key] = e
        n += 1
    save_ledger(entries, ym)
    return n


def record_wt_rows(rows: list[dict], filed_at: str, ym: str | None = None) -> int:
    """위택스 '정상 신고 내역' 수집 결과를 대장에 기입. rows: {name,taxym,amount}."""
    entries = load_ledger(ym)
    clients = load_clients()
    n = 0
    for r in rows:
        wt_name = (r.get("name") or "").strip()
        if not wt_name:
            continue
        c = _find_client(clients, wt_name=wt_name)
        key = (c or {}).get("bizno") or f"wt:{wt_name}"
        e = entries.get(key)
        if e is None:
            e = _blank_entry((c or {}).get("name", wt_name), (c or {}).get("bizno", ""),
                             (c or {}).get("ceo", wt_name))
            entries[key] = e
        e["wt"].setdefault("napbu", "")
        e["wt"].update({"filed_at": filed_at, "taxym": r.get("taxym", ""),
                        "amount": r.get("amount", ""), "wt_name": wt_name})
        n += 1
    save_ledger(entries, ym)
    return n
