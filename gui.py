"""인건비(원천세·간이지급명세서) 홈택스+위택스 신고 자동화 — Tkinter GUI (모던 테마).

phase를 각각 켜고(선택 실행) 전부 켜서(연속 실행) 돌릴 수 있다. 기본 순서는 레지스트리 순.
순수 Tkinter Canvas로 그린 커스텀 테마(외부 의존성 없음): 다크 헤더 + 화이트 카드 +
인디고 액센트, iOS식 토글 스위치, 둥근 버튼, 상태 pill, 콘솔형 로그. (yangdo_auto와 동일)

실행:  python gui.py
"""
from __future__ import annotations

import os
import sys

# 배포(frozen exe)면 동봉된 Chromium을 Playwright가 쓰도록 — 어떤 playwright import보다 먼저.
if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          os.path.join(_base, "playwright-browsers"))

import asyncio
import base64
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import updater
from automation import ALL_PHASES, BrowserSession, Inputs, run_phases
from automation.browser import app_data_dir
from automation.hometax import JIGUP_TYPES

# 사용자 설정(파일 비밀번호 등) — 개발: 프로젝트 폴더 / 배포: %LOCALAPPDATA%\IngunbiAuto
SETTINGS_PATH = app_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────── 디자인 토큰 ───────────────────────────
FONT = "Malgun Gothic"        # 한글 선명
MONO = "Consolas"
BG = "#F1F5F9"                # slate-100  (앱 배경)
CARD = "#FFFFFF"              # 카드
HEAD = "#0F172A"              # slate-900  (헤더)
INK = "#0F172A"              # 본문 텍스트
MUTE = "#64748B"             # 보조 텍스트
BORDER = "#E2E8F0"           # 테두리
ACCENT = "#0EA5E9"           # sky-500 (양도세 앱과 색으로 구분)
ACCENT_DK = "#0284C7"        # hover
ACCENT_SOFT = "#E0F2FE"
TRACK = "#CBD5E1"            # 토글 off
CONSOLE_BG = "#0B1220"
CONSOLE_FG = "#E2E8F0"

SITE_BADGE = {
    "홈택스": ("#DBEAFE", "#1D4ED8"),
    "위택스": ("#DCFCE7", "#15803D"),
}


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Canvas에 둥근 사각형(smooth polygon)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


# ─────────────────────────── 커스텀 위젯 ───────────────────────────
class Toggle(tk.Canvas):
    """iOS식 토글 스위치 (BooleanVar 바인딩)."""

    def __init__(self, parent, variable: tk.BooleanVar, bg, command=None):
        super().__init__(parent, width=46, height=26, bg=bg, highlightthickness=0, bd=0)
        self.var = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        round_rect(self, 2, 3, 44, 23, 10, fill=ACCENT if on else TRACK, outline="")
        x = 26 if on else 4
        self.create_oval(x, 5, x + 16, 21, fill="#FFFFFF", outline="")

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class RButton(tk.Canvas):
    """둥근 버튼 (primary / ghost / mini) + hover."""

    def __init__(self, parent, text, command, *, kind="primary", bg,
                 width=128, height=44, font=None):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        self.text, self.command, self.kind = text, command, kind
        self.w, self.h = width, height
        self.font = font or (FONT, 11, "bold")
        self._hover = False
        self.enabled = True
        self.configure(cursor="hand2")
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _on_click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, b: bool):
        if b == self.enabled:
            return
        self.enabled = b
        self.configure(cursor="hand2" if b else "arrow")
        self._draw()

    def _set(self, h):
        if not self.enabled:
            return
        self._hover = h
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        if self.kind == "primary":
            if not self.enabled:
                fill = "#CBD5E1"
            else:
                fill = ACCENT_DK if self._hover else ACCENT
            round_rect(self, 1, 1, w - 1, h - 1, 13, fill=fill, outline="")
            fg = "#FFFFFF" if self.enabled else "#EEF2F8"
        elif self.kind == "ghost":
            round_rect(self, 1, 1, w - 1, h - 1, 13, fill="#F8FAFC" if self._hover else CARD,
                       outline=BORDER, width=1)
            fg = INK
        else:  # mini
            round_rect(self, 1, 1, w - 1, h - 1, 9, fill=ACCENT_SOFT if self._hover else "#F1F5F9", outline="")
            fg = ACCENT
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


class Segmented(tk.Canvas):
    """2지 세그먼트 컨트롤 (StringVar)."""

    def __init__(self, parent, variable: tk.StringVar, options, bg, width=190, height=36):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        self.var = variable
        self.options = options  # [(value,label),(value,label)]
        self.w, self.h = width, height
        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.w, self.h
        round_rect(self, 1, 1, w - 1, h - 1, 11, fill="#F1F5F9", outline=BORDER, width=1)
        half = w / 2
        for i, (val, label) in enumerate(self.options):
            sel = self.var.get() == val
            cx = half * i + half / 2
            if sel:
                x1 = half * i + 3
                round_rect(self, x1, 3, x1 + half - 6, h - 3, 9, fill=ACCENT, outline="")
            self.create_text(cx, h / 2, text=label, fill="#FFFFFF" if sel else MUTE,
                             font=(FONT, 9, "bold"))

    def _click(self, e):
        self.var.set(self.options[0][0] if e.x < self.w / 2 else self.options[1][0])


class Pill(tk.Canvas):
    """상태 pill (대기/진행/완료/실패)."""

    STYLES = {
        "idle": ("대기", "#F1F5F9", "#64748B"),
        "run": ("진행 중", "#FEF3C7", "#B45309"),
        "ok": ("완료", "#DCFCE7", "#15803D"),
        "fail": ("실패", "#FEE2E2", "#B91C1C"),
    }

    def __init__(self, parent, bg):
        super().__init__(parent, width=64, height=24, bg=bg, highlightthickness=0, bd=0)
        self.set("idle")

    def set(self, status):
        t, fill, fg = self.STYLES.get(status, self.STYLES["idle"])
        self.delete("all")
        round_rect(self, 1, 1, 63, 23, 11, fill=fill, outline="")
        self.create_text(32, 12, text=t, fill=fg, font=(FONT, 8, "bold"))


# ─────────────────────────── 앱 ───────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("인건비 신고 자동화 (원천세·간이지급명세서)")
        root.geometry("1140x940")
        root.minsize(1000, 760)
        root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar", background=TRACK, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTE, relief="flat")

        self.events: queue.Queue = queue.Queue()
        # 브라우저 세션: GUI 수명 동안 유지되는 전용 이벤트 루프 스레드에서 관리 —
        # 실행이 끝나도 브라우저를 닫지 않아 다음 업체를 재로그인 없이 처리.
        self.session: BrowserSession | None = None
        self.session_loop: asyncio.AbstractEventLoop | None = None
        self._busy = False
        self._stop = False
        self._run_fut = None   # 실행 중인 asyncio task — 중단 시 즉시 취소용
        self._phase_vars: dict[str, tk.BooleanVar] = {}
        self._phase_pills: dict[str, Pill] = {}

        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)
        updater.check_async(self._on_update_available)

    def _on_update_available(self, info: dict):
        """새 버전 알림 — background thread에서 호출되므로 Tk 조작은 after로 디스패치."""
        def ask():
            msg = (f"새 버전 v{info['latest']}이 있습니다. (현재 v{info['current']})\n\n"
                   + (f"{info['notes']}\n\n" if info.get("notes") else "")
                   + "다운로드 페이지를 열까요?")
            if messagebox.askyesno("업데이트 알림", msg):
                import webbrowser
                webbrowser.open(info["download_url"])
        try:
            self.root.after(0, ask)
        except Exception:
            pass

    def _ensure_session(self):
        """세션 루프 스레드 + BrowserSession 준비(최초 1회)."""
        if self.session_loop is not None:
            return
        self.session_loop = asyncio.new_event_loop()
        threading.Thread(target=self.session_loop.run_forever, daemon=True).start()
        self.session = BrowserSession()

    def _on_close(self):
        """창 닫기 — 세션 브라우저 정리 후 종료."""
        try:
            if self.session_loop is not None and self.session is not None:
                fut = asyncio.run_coroutine_threadsafe(self.session.close(), self.session_loop)
                fut.result(timeout=5)
        except Exception:
            pass
        self.root.destroy()

    # ── UI ──
    def _build_ui(self):
        # 헤더
        head = tk.Frame(self.root, bg=HEAD)
        head.pack(fill="x", side="top")
        hin = tk.Frame(head, bg=HEAD)
        hin.pack(fill="x", padx=24, pady=(18, 16))
        tk.Label(hin, text="인건비 신고 자동화", bg=HEAD, fg="#FFFFFF",
                 font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(hin, text="홈택스 · 위택스   |   원천세 파일변환 신고 → 간이지급명세서 제출 → 납부서·서류 PDF·출력",
                 bg=HEAD, fg="#94A3B8", font=(FONT, 9)).pack(anchor="w", pady=(3, 0))
        tk.Frame(self.root, bg=ACCENT, height=3).pack(fill="x", side="top")

        # 푸터(버튼) — 하단 고정
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", side="bottom", padx=20, pady=(8, 14))
        self.start_btn = RButton(footer, "▶  시작", self._start, kind="primary", bg=BG, width=130)
        self.start_btn.pack(side="left")
        RButton(footer, "■  중단", self._stop_clicked, kind="ghost", bg=BG, width=110).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="대기 중")
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTE,
                 font=(FONT, 9)).pack(side="right", pady=4)
        self.hint_var = tk.StringVar()
        tk.Label(footer, textvariable=self.hint_var, bg=BG, fg="#B45309",
                 font=(FONT, 9), wraplength=420, justify="left").pack(side="left", padx=14)

        # 로그 — 푸터 위 고정
        logwrap = tk.Frame(self.root, bg=BG)
        logwrap.pack(fill="x", side="bottom", padx=20, pady=(0, 0))
        tk.Label(logwrap, text="실행 로그", bg=BG, fg=MUTE, font=(FONT, 9, "bold")).pack(anchor="w", pady=(0, 4))
        lt = tk.Frame(logwrap, bg=CONSOLE_BG, highlightbackground=BORDER, highlightthickness=1)
        lt.pack(fill="both")
        self.log_text = tk.Text(lt, height=6, wrap="word", bg=CONSOLE_BG, fg=CONSOLE_FG,
                                relief="flat", font=(MONO, 9), insertbackground=CONSOLE_FG,
                                padx=12, pady=8, borderwidth=0)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(lt, orient="vertical", command=self.log_text.yview)
        lsb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.tag_config("ok", foreground="#4ADE80")
        self.log_text.tag_config("fail", foreground="#F87171")
        self.log_text.tag_config("info", foreground="#7DD3FC")
        self.log_text.tag_config("accent", foreground="#A5B4FC")

        # 중앙 — 스크롤 영역
        scroll = tk.Frame(self.root, bg=BG)
        scroll.pack(fill="both", expand=True, side="top")
        canvas = tk.Canvas(scroll, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        # 위: [실행 단계 | 옵션] 같은 높이로 나란히. 아래: [입력 정보] 전체 폭(긴 경로 잘 보이게).
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1, uniform="t")
        top.columnconfigure(1, weight=1, uniform="t")
        top.rowconfigure(0, weight=1)
        tl = tk.Frame(top, bg=BG)
        tl.grid(row=0, column=0, sticky="nsew", padx=(20, 8))
        tr = tk.Frame(top, bg=BG)
        tr.grid(row=0, column=1, sticky="nsew", padx=(8, 20))
        self._build_phase_card(tl, expand=True)
        self._build_option_card(tr, expand=True)

        bottom = tk.Frame(body, bg=BG)
        bottom.pack(fill="x", padx=20)
        self._build_input_card(bottom)
        self._setup_validation()

    def _card(self, parent, title, subtitle=None, expand=False):
        fill = "both" if expand else "x"
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill=fill, expand=expand, padx=0, pady=(12, 0))
        c = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        c.pack(fill=fill, expand=expand)
        head = tk.Frame(c, bg=CARD)
        head.pack(fill="x", padx=16, pady=(11, 4))
        tk.Label(head, text=title, bg=CARD, fg=INK, font=(FONT, 11, "bold")).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(side="left", padx=(8, 0))
        return c

    def _build_phase_card(self, parent, expand=False):
        c = self._card(parent, "실행 단계", "전부 체크 = 연속 실행 · 일부만 체크 = 선택 실행", expand=expand)
        for i, mod in enumerate(ALL_PHASES, 1):
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=16, pady=2)
            # 기본 선택: 신고 3종 + 납부서 2종. 접수증·신고서 출력(4·5)은 실무상 드물어 OFF.
            var = tk.BooleanVar(value=mod.KEY not in ("hometax_docs", "wetax_docs"))
            self._phase_vars[mod.KEY] = var
            Toggle(row, var, CARD).pack(side="left")
            site = getattr(mod, "SITE", "")
            if site in SITE_BADGE:
                bgc, fgc = SITE_BADGE[site]
                tk.Label(row, text=site, bg=bgc, fg=fgc, font=(FONT, 8, "bold"),
                         padx=7, pady=1).pack(side="left", padx=(12, 8))
            tk.Label(row, text=f"{i}.  {mod.LABEL}", bg=CARD, fg=INK,
                     font=(FONT, 10)).pack(side="left")
            pill = Pill(row, CARD)
            pill.pack(side="right")
            self._phase_pills[mod.KEY] = pill
        tk.Frame(c, bg=CARD, height=6).pack()

    def _build_input_card(self, parent):
        c = self._card(parent, "입력 정보")
        form = tk.Frame(c, bg=CARD)
        form.pack(fill="x", padx=16, pady=(2, 12))
        form.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar()
        self.var_bizno = tk.StringVar()
        self.var_ht_file = tk.StringVar()
        self.var_wt_file = tk.StringVar()
        self.var_filepw = tk.StringVar()
        self.var_outdir = tk.StringVar()  # 기본값 비움 — PDF 모드에서 필수 검증 대상

        # 짧은 입력 4개(업체명·사업자번호·납부기한·비밀번호)를 한 줄에 — 세로 압축
        self.var_napbu_due = tk.StringVar()
        pair = tk.Frame(form, bg=CARD)
        pair.grid(row=form.grid_size()[1], column=0, columnspan=3, sticky="ew", pady=3)
        for col in (1, 3, 5, 7):
            pair.columnconfigure(col, weight=1)

        def _pair_label(col, title, hint):
            lab = tk.Frame(pair, bg=CARD)
            lab.grid(row=0, column=col, sticky="w", padx=(2 if col == 0 else 12, 8))
            tk.Label(lab, text=title, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
            tk.Label(lab, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(anchor="w")

        def _pair_entry(col, var, secret=False):
            e = tk.Entry(pair, textvariable=var, font=(FONT, 10), bg="#FFFFFF", fg=INK,
                         relief="flat", highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT, insertbackground=INK,
                         show=("●" if secret else ""))
            e.grid(row=0, column=col, sticky="ew", ipady=5)

        _pair_label(0, "업체명(상호)", "파일명 포함 시 필수")
        _pair_entry(1, self.var_name)
        _pair_label(2, "사업자등록번호", "조회용 10자리 (- 없이)")
        _pair_entry(3, self.var_bizno)
        _pair_label(4, "납부기한 (선택)", "납부서 파일명용")
        _pair_entry(5, self.var_napbu_due)
        _pair_label(6, "파일 비밀번호", "세무사랑 공용")
        _pair_entry(7, self.var_filepw, secret=True)

        # 저장된 설정 복원 — 납부기한(입력 형식 그대로)·파일 비밀번호는 실행 간 기억
        s = load_settings()
        try:
            self.var_filepw.set(
                base64.b64decode(s.get("file_password_b64", "")).decode("utf-8"))
        except Exception:
            pass
        self.var_napbu_due.set(s.get("napbu_due", ""))
        self._field(form, "홈택스 원천세 변환파일", self.var_ht_file, pick="file")
        self._field(form, "위택스 특별징수 파일", self.var_wt_file, pick="file")
        self._field(form, "PDF 저장 폴더", self.var_outdir, pick="dir")

        # 간이지급명세서 — 제목·종류 드롭다운·파일을 한 줄에 (동적 행, 종류 하나당 제출 1회)
        sec = tk.Frame(c, bg=CARD)
        sec.pack(fill="x", padx=16, pady=(4, 12))
        self._jigup_wrap = tk.Frame(sec, bg=CARD)
        self._jigup_wrap.pack(fill="x")
        self._jigup_wrap.columnconfigure(1, weight=1)
        jt = tk.Frame(self._jigup_wrap, bg=CARD)
        jt.grid(row=0, column=0, sticky="nw", padx=(2, 12), pady=3)
        tk.Label(jt, text="간이지급명세서", bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(jt, text="종류마다 개별 제출", bg=CARD, fg=MUTE, font=(FONT, 8)).pack(anchor="w")
        self._jigup_rows: list[dict] = []
        self._jigup_row_seq = 0
        self._add_jigup_row()
        # 가로로 긴 '추가' 버튼 — 행들 아래 전체 폭
        addbtn = tk.Label(sec, text="＋  간이지급명세서 추가", bg="#F1F5F9", fg=ACCENT,
                          font=(FONT, 9, "bold"), pady=6, cursor="hand2")
        addbtn.pack(fill="x", pady=(6, 0))
        addbtn.bind("<Button-1>", lambda e: self._add_jigup_row())
        addbtn.bind("<Enter>", lambda e: addbtn.configure(bg=ACCENT_SOFT))
        addbtn.bind("<Leave>", lambda e: addbtn.configure(bg="#F1F5F9"))

    def _add_jigup_row(self):
        row = tk.Frame(self._jigup_wrap, bg=CARD)
        row.grid(row=self._jigup_row_seq, column=1, sticky="ew", pady=2)
        self._jigup_row_seq += 1
        tvar = tk.StringVar()
        fvar = tk.StringVar()
        cb = ttk.Combobox(row, textvariable=tvar, values=JIGUP_TYPES, state="readonly",
                          width=28, font=(FONT, 9))
        cb.pack(side="left")
        e = tk.Entry(row, textvariable=fvar, font=(FONT, 9), bg="#FFFFFF", fg=INK,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, insertbackground=INK)
        e.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=4)
        e.bind("<FocusOut>", lambda ev, ent=e: ent.xview_moveto(1.0))

        def pick(v=fvar, ent=e):
            self._pick_file(v)
            ent.xview_moveto(1.0)
        RButton(row, "파일", pick, kind="mini", bg=CARD, width=50, height=28,
                font=(FONT, 9, "bold")).pack(side="left", padx=(6, 0))

        entry = {"type": tvar, "file": fvar, "frame": row}

        def remove():
            if len(self._jigup_rows) <= 1:   # 마지막 행은 지우는 대신 비움
                tvar.set("")
                fvar.set("")
                return
            self._jigup_rows.remove(entry)
            row.destroy()
            self._refresh_validation()
        RButton(row, "✕", remove, kind="mini", bg=CARD, width=30, height=28,
                font=(FONT, 9, "bold")).pack(side="left", padx=(4, 0))

        self._jigup_rows.append(entry)
        tvar.trace_add("write", lambda *a: self._refresh_validation())
        fvar.trace_add("write", lambda *a: self._refresh_validation())
        self._refresh_validation()

    def _jigup_jobs(self) -> list[tuple[str, str]]:
        """완성된 (종류, 파일) 행 목록."""
        return [(r["type"].get().strip(), r["file"].get().strip())
                for r in self._jigup_rows
                if r["type"].get().strip() and r["file"].get().strip()]

    def _field(self, parent, label, var, pick=None, hint=None, secret=False):
        r = parent.grid_size()[1]
        lab = tk.Frame(parent, bg=CARD)
        lab.grid(row=r, column=0, sticky="w", padx=(2, 12), pady=3)
        tk.Label(lab, text=label, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        if hint:
            tk.Label(lab, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8)).pack(anchor="w")
        e = tk.Entry(parent, textvariable=var, font=(FONT, 10), bg="#FFFFFF", fg=INK,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, insertbackground=INK,
                     show=("●" if secret else ""))
        e.grid(row=r, column=1, sticky="ew", ipady=5, pady=3)
        # 긴 경로는 끝부분(파일명/마지막 폴더)이 보이도록 — 입력칸 떠날 때 끝으로 스크롤.
        e.bind("<FocusOut>", lambda ev, ent=e: ent.xview_moveto(1.0))
        if pick:
            btns = tk.Frame(parent, bg=CARD)
            btns.grid(row=r, column=2, padx=(8, 2))
            def mk(kind_label, fn, v=var, ent=e):
                def cmd():
                    fn(v)
                    ent.xview_moveto(1.0)
                RButton(btns, kind_label, cmd, kind="mini", bg=CARD, width=54, height=32,
                        font=(FONT, 9, "bold")).pack(side="left", padx=1)
            if pick == "file":
                mk("파일", self._pick_file)
            elif pick in ("files", "both"):
                mk("파일", self._pick_files)   # 다중 선택 → ';' 연결
            if pick in ("dir", "both"):
                mk("폴더", self._pick_dir)

    def _build_option_card(self, parent, expand=False):
        c = self._card(parent, "옵션", expand=expand)
        opt = tk.Frame(c, bg=CARD)
        opt.pack(fill="x", padx=16, pady=(2, 12))

        self.var_mode = tk.StringVar(value="pdf")
        self.var_incname = tk.BooleanVar(value=True)
        self.var_disclose = tk.BooleanVar(value=True)
        self.var_napbu_wait = tk.StringVar(value="0")

        seg = tk.Frame(opt, bg=CARD)
        seg.pack(fill="x", pady=(0, 4))
        tk.Label(seg, text="서류 처리", bg=CARD, fg=INK, font=(FONT, 10)).pack(side="left")
        Segmented(seg, self.var_mode, [("pdf", "PDF 저장"), ("print", "출력(인쇄)")], CARD).pack(side="right")

        # 간이지급명세서 제출구분 (정기신고 기본, 수정·기한후는 지급연월 필요)
        self.var_jigup_type = tk.StringVar(value="정기신고")
        self.var_jigup_ym = tk.StringVar()
        jrow = tk.Frame(opt, bg=CARD)
        jrow.pack(fill="x", pady=3)
        jtxt = tk.Frame(jrow, bg=CARD)
        jtxt.pack(side="left")
        tk.Label(jtxt, text="간이지급명세서 제출구분", bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(jtxt, text="수정·기한후는 지급연월(YYYY-MM)도 입력", bg=CARD, fg=MUTE,
                 font=(FONT, 8)).pack(anchor="w")
        # 라벨은 짧게(정기/수정/기한후), 내부 값은 홈택스 화면 표기 그대로(정기신고 등)
        jsel = tk.Frame(jrow, bg=CARD)
        jsel.pack(side="right")
        for short, val in (("정기", "정기신고"), ("수정", "수정신고"), ("기한후", "기한후신고")):
            tk.Radiobutton(jsel, text=short, variable=self.var_jigup_type, value=val,
                           bg=CARD, fg=INK, font=(FONT, 9), selectcolor="#FFFFFF",
                           activebackground=CARD).pack(side="left", padx=1)
        tk.Entry(jsel, textvariable=self.var_jigup_ym, font=(FONT, 10), width=10,
                 justify="center", bg="#FFFFFF", fg=INK, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="left", padx=(8, 0), ipady=4)
        self._switch(opt, "파일명에 업체명 포함", "여러 업체 서류 구분이 필요할 때", self.var_incname)
        self._switch(opt, "서류 개인정보 공개", "출력 서류에 주민번호 등 공개 표시", self.var_disclose)

        wrow = tk.Frame(opt, bg=CARD)
        wrow.pack(fill="x", pady=3)
        wtxt = tk.Frame(wrow, bg=CARD)
        wtxt.pack(side="left")
        tk.Label(wtxt, text="위택스 납부서 대기", bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(wtxt, text="지방세 가상계좌 생성 대기 시간 (납부서 출력 전)", bg=CARD, fg=MUTE,
                 font=(FONT, 8)).pack(anchor="w")
        wbox = tk.Frame(wrow, bg=CARD)
        wbox.pack(side="right")
        tk.Label(wbox, text="분", bg=CARD, fg=MUTE, font=(FONT, 9)).pack(side="right", padx=(4, 0))
        tk.Entry(wbox, textvariable=self.var_napbu_wait, font=(FONT, 10), width=4, justify="center",
                 bg="#FFFFFF", fg=INK, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="right", ipady=3)

    def _switch(self, parent, label, hint, var):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        Toggle(row, var, CARD).pack(side="right")
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=label, bg=CARD, fg=INK, font=(FONT, 10)).pack(anchor="w")
        tk.Label(txt, text=hint, bg=CARD, fg=MUTE, font=(FONT, 8),
                 wraplength=380, justify="left").pack(anchor="w")

    def _napbu_wait_seconds(self) -> int:
        """'위택스 납부서 대기' 분 입력 → 초. 파싱 실패 시 기본 3분."""
        raw = (self.var_napbu_wait.get() or "").strip().replace(",", ".")
        try:
            return max(0, int(round(float(raw) * 60)))
        except ValueError:
            return 180

    # ── 필수 입력 검증 ──
    def _setup_validation(self):
        watch = [self.var_name, self.var_bizno, self.var_ht_file,
                 self.var_wt_file, self.var_filepw, self.var_outdir,
                 self.var_mode, self.var_incname]
        for v in watch:
            v.trace_add("write", lambda *a: self._refresh_validation())
        for v in self._phase_vars.values():
            v.trace_add("write", lambda *a: self._refresh_validation())
        self._refresh_validation()

    def _missing(self) -> list[str]:
        """현재 선택/입력 기준 부족한 필수 항목 라벨 목록(없으면 빈 리스트)."""
        sel = {k for k, v in self._phase_vars.items() if v.get()}
        if not sel:
            return ["실행 단계 선택"]
        miss: list[str] = []

        def need(var, label):
            if not var.get().strip():
                miss.append(label)

        # 조회는 홈택스·위택스 모두 사업자등록번호 기준(이름 매칭 안 함).
        # 업체명은 '파일명에 업체명 포함' 옵션을 켰을 때만 필요.
        wetax_out = sel & {"wetax_docs", "wetax_napbu"}
        hometax_out = sel & {"hometax_docs", "hometax_napbu"}
        if self.var_incname.get() and (wetax_out or hometax_out):
            need(self.var_name, "업체명(상호)")
        if "wetax_filing" in sel:
            need(self.var_wt_file, "위택스 특별징수 파일")
        if "hometax_filing" in sel:
            need(self.var_ht_file, "원천세 변환파일")
        if "jigup_filing" in sel:
            rows = [(r["type"].get().strip(), r["file"].get().strip())
                    for r in self._jigup_rows]
            if not any(t and f for t, f in rows):
                miss.append("간이지급명세서(종류+파일) 1행 이상")
            if any(bool(t) != bool(f) for t, f in rows):
                miss.append("간이지급명세서 행 완성(종류·파일 짝 맞추기)")
        if sel & {"wetax_filing", "hometax_filing", "jigup_filing"}:
            need(self.var_filepw, "파일 비밀번호")
        if hometax_out or wetax_out:
            digits = "".join(c for c in self.var_bizno.get() if c.isdigit())
            if len(digits) != 10:
                miss.append("사업자등록번호(10자리)")
        if (sel & {"hometax_docs", "wetax_docs", "hometax_napbu", "wetax_napbu"}) \
                and self.var_mode.get() == "pdf":
            need(self.var_outdir, "PDF 저장 폴더")

        seen, out = set(), []
        for m in miss:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _refresh_validation(self):
        miss = self._missing()
        self.start_btn.set_enabled(not miss)
        self.hint_var.set(("필요: " + ", ".join(miss)) if miss else "")

    # ── 파일 선택 ──
    def _pick_file(self, var):
        p = filedialog.askopenfilename(title="파일 선택")
        if p:
            var.set(p)

    def _pick_files(self, var):
        ps = filedialog.askopenfilenames(title="파일 선택 (여러 개 가능)")
        if ps:
            var.set(";".join(ps))

    def _pick_dir(self, var):
        p = filedialog.askdirectory(title="폴더 선택")
        if p:
            var.set(p)

    # ── 실행 ──
    def _start(self):
        if self._busy:
            messagebox.showinfo("실행 중", "이미 진행 중입니다. 끝난 뒤 다시 시작하세요.")
            return

        selected = [k for k, v in self._phase_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("단계 없음", "실행할 단계를 하나 이상 켜세요.")
            return

        inp = Inputs(
            name_label=self.var_name.get().strip() or "업체",
            biz_no="".join(c for c in self.var_bizno.get() if c.isdigit()),
            hometax_convert_file=self.var_ht_file.get().strip(),
            jigup_jobs=self._jigup_jobs(),
            jigup_report_type=self.var_jigup_type.get(),
            jigup_pay_ym=self.var_jigup_ym.get().strip(),
            wetax_convert_file=self.var_wt_file.get().strip(),
            file_password=self.var_filepw.get(),
            napbu_due=self.var_napbu_due.get().strip(),
            output_dir=self.var_outdir.get().strip(),
            output_mode=self.var_mode.get(),
            auto_submit=True,  # 제출까지 자동(토글 제거 — 전 phase 실전 검증 완료)
            disclose_personal_info=self.var_disclose.get(),
            include_name=self.var_incname.get(),
            napbu_wait_sec=self._napbu_wait_seconds(),
        )

        self._stop = False
        for k in self._phase_vars:
            self._set_phase(k, "idle")
        self.log_text.delete("1.0", "end")
        self.status_var.set("실행 중…")

        # 실행 로그 파일 (실행마다 새로)
        logdir = Path(__file__).resolve().parent / "logs"
        logdir.mkdir(exist_ok=True)
        self._logfile = str(logdir / "run.log")
        try:
            open(self._logfile, "w", encoding="utf-8").close()
        except Exception:
            self._logfile = None

        def emit(kind, **kw):
            self.events.put({"kind": kind, **kw})

        async def main():
            try:
                await run_phases(self.session, selected, inp, emit,
                                 stop_check=lambda: self._stop)
            except asyncio.CancelledError:
                # 중단 버튼 = 즉시 취소. 화면이 어중간해도 phase는 시작 시 하드 리셋(goto)
                # 하므로 다음 실행은 깨끗하게 시작된다. 브라우저는 유지.
                emit("log", text="[i] 중단됨 — 즉시 종료 (브라우저 유지, 다음 실행 시 화면 자동 리셋)")
                emit("done")
            except Exception as e:  # noqa: BLE001
                emit("log", text=f"[!] 예외: {e}")
                emit("done")

        # 다음 실행을 위해 기억: 파일 비밀번호(살짝 가림) + 납부기한(입력 형식 그대로)
        save_settings({
            "file_password_b64": base64.b64encode(
                self.var_filepw.get().encode("utf-8")).decode("ascii"),
            "napbu_due": self.var_napbu_due.get().strip(),
        })

        self._ensure_session()
        self._busy = True
        self._run_fut = asyncio.run_coroutine_threadsafe(main(), self.session_loop)

    def _stop_clicked(self):
        self._stop = True
        if self._run_fut is not None and not self._run_fut.done():
            self._run_fut.cancel()   # 실행 중인 태스크 즉시 취소 (await 지점에서 끊김)
        self.status_var.set("중단됨")

    # ── 큐 폴링 ──
    def _poll(self):
        try:
            while True:
                evt = self.events.get_nowait()
                kind = evt["kind"]
                if kind == "log":
                    self._append_log(evt["text"])
                elif kind == "phase":
                    self._set_phase(evt["key"], evt["status"])
                elif kind == "status":
                    self.status_var.set(evt.get("text", ""))
                elif kind == "done":
                    self._busy = False
                    self.status_var.set("완료 — 다음 업체 입력 후 바로 시작 가능")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _append_log(self, text: str):
        tag = ""
        t = text.lstrip()
        if t.startswith("[v]") or "✓" in t or t.startswith("[결과]"):
            tag = "ok"
        elif t.startswith("[!]"):
            tag = "fail"
        elif t.startswith("[i]"):
            tag = "info"
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        # 파일에도 기록 — 실행 후 문제 분석용 (logs/run.log, 실행마다 초기화)
        if getattr(self, "_logfile", None):
            try:
                with open(self._logfile, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception:
                pass

    def _set_phase(self, key: str, status: str):
        pill = self._phase_pills.get(key)
        if pill:
            pill.set(status)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
