"""A small native controller; all project work stays in the browser UI.

The window is deliberately launcher-like: one dark surface, the mark in the
corner, a single bright primary action and quiet secondary ones. It is the only
part of WorkRoom that is not HTML, so it cannot inherit the web theme — the
palette below mirrors the web greys by hand.
"""

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from desktop_runtime import clear_instance, open_workbench

BG = "#12161b"
CARD = "#1a2027"
EDGE = "#2b333c"
INK = "#eef2f6"
MUTED = "#8b96a3"
DIM = "#5c6672"
PRIMARY = "#e6ebf1"
PRIMARY_HOVER = "#ffffff"
GHOST = "#1f262e"
GHOST_HOVER = "#28313b"

FONT = "Microsoft YaHei UI"


def _round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class FlatButton(tk.Canvas):
    """Canvas button so the primary action can keep a rounded, flat look."""

    def __init__(self, parent, text, command, *, primary=False, height=44):
        self.primary = primary
        self.command = command
        self.enabled = False
        self.hovered = False
        self._text = text
        super().__init__(
            parent,
            height=height,
            # Canvas 默认请求宽 378px，三个并排会把窗口撑破。
            # 给小请求宽度，让 pack(fill=x, expand=True) 自己平分。
            width=40,
            highlightthickness=0,
            bg=CARD,
            cursor="hand2",
        )
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self._draw()

    def set_text(self, text):
        self._text = text
        self._draw()

    def _colors(self):
        if not self.enabled:
            return ("#20262d", "#2b333c", DIM, EDGE)
        if self.primary:
            return (
                PRIMARY_HOVER if self.hovered else PRIMARY,
                PRIMARY_HOVER if self.hovered else PRIMARY,
                BG,
                PRIMARY,
            )
        return (
            GHOST_HOVER if self.hovered else GHOST,
            "#3b4550" if self.hovered else EDGE,
            INK if self.hovered else MUTED,
            "#3b4550" if self.hovered else EDGE,
        )

    def _draw(self, _event=None):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            return
        fill, border, fg, _ = self._colors()
        _round_rect(self, 1, 1, width - 1, height - 1, 9, fill=fill, outline=border)
        self.create_text(
            width / 2,
            height / 2,
            text=self._text,
            fill=fg,
            font=(FONT, 10, "bold" if self.primary else "normal"),
        )

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self._draw()

    def _on_click(self, _event):
        if self.enabled:
            self._draw()

    def _on_release(self, _event):
        if self.enabled and self.command:
            self.command()


class DesktopWindow:
    def __init__(self, data, *, no_browser=False):
        self.data = data
        self.no_browser = no_browser
        self.server = None
        self.restart = False
        self.closing = False
        self.initialized = False
        self.result = queue.Queue()
        self.root = tk.Tk(className="WorkRoom")
        self.root.title("WorkRoom · 本机工作台")
        self.root.geometry("580x452")
        self.root.minsize(540, 440)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", (FONT, 10))
        self._set_icon()

        shell = tk.Frame(self.root, bg=BG, padx=26, pady=22)
        shell.pack(fill="both", expand=True)

        head = tk.Frame(shell, bg=BG)
        head.pack(fill="x")
        self._logo = None
        self._place_logo(head)
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles, text="WorkRoom", bg=BG, fg=INK, font=(FONT, 19, "bold")
        ).pack(anchor="w")
        tk.Label(
            titles, text="本机工作台", bg=BG, fg=MUTED, font=(FONT, 9)
        ).pack(anchor="w")

        tk.Frame(shell, bg=EDGE, height=1).pack(fill="x", pady=(18, 0))

        card = tk.Frame(shell, bg=CARD, padx=20, pady=18)
        card.pack(fill="x", pady=(16, 0))

        line = tk.Frame(card, bg=CARD)
        line.pack(fill="x")
        self.dot = tk.Canvas(
            line, width=10, height=10, bg=CARD, highlightthickness=0
        )
        self.dot.create_oval(1, 1, 9, 9, fill=DIM, outline="")
        self.dot.pack(side="left", pady=(5, 0))
        self.status = tk.StringVar(value="正在准备本机工作台…")
        tk.Label(
            line, textvariable=self.status, bg=CARD, fg=INK, font=(FONT, 10)
        ).pack(side="left", padx=(8, 0))

        self.address = tk.Label(
            card,
            text="",
            bg=CARD,
            fg=MUTED,
            font=("Consolas", 9),
            anchor="w",
            cursor="hand2",
        )
        self.address.pack(fill="x", pady=(6, 0))
        self.address.bind("<Button-1>", lambda _e: self._open())

        tk.Label(
            card,
            text="项目页面在浏览器中使用。关闭网页后应用仍会运行；关闭这个窗口即可退出。",
            bg=CARD,
            fg=DIM,
            font=(FONT, 9),
            wraplength=470,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(12, 0))

        self.open_button = FlatButton(
            card, "打开工作台", self._open, primary=True, height=46
        )
        self.open_button.pack(fill="x", pady=(18, 0))

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", pady=(10, 0))
        self.backups_button = FlatButton(
            actions, "备份与恢复", lambda: open_workbench(self.server_url("backups/")),
            height=36,
        )
        self.backups_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.restart_button = FlatButton(
            actions, "重启应用", self.on_restart, height=36
        )
        self.restart_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.quit_button = FlatButton(actions, "退出应用", self.on_close, height=36)
        self.quit_button.pack(side="left", fill="x", expand=True)

        foot = tk.Frame(shell, bg=BG)
        foot.pack(fill="x", pady=(14, 0))
        tk.Label(foot, text="数据位置", bg=BG, fg=DIM, font=(FONT, 8)).pack(anchor="w")
        tk.Label(
            foot,
            text=str(data),
            bg=BG,
            fg=MUTED,
            font=("Consolas", 8),
            wraplength=520,
            justify="left",
            anchor="w",
        ).pack(fill="x")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _set_icon(self):
        """窗口和任务栏图标：用和网页 favicon 同一片羽毛。"""
        path = Path(__file__).with_name("static") / "workroom" / "logo.png"
        try:
            self._icon = tk.PhotoImage(file=str(path))
            self.root.iconphoto(True, self._icon)
        except Exception:  # 图标缺失不该挡住启动
            logging.getLogger(__name__).debug("window icon not loaded", exc_info=True)

    def _place_logo(self, parent):
        path = Path(__file__).with_name("static") / "workroom" / "logo-48.png"
        try:
            self._logo = tk.PhotoImage(file=str(path))
            tk.Label(parent, image=self._logo, bg=BG).pack(side="left", padx=(0, 12))
        except Exception:
            logging.getLogger(__name__).debug("logo not loaded", exc_info=True)

    def server_url(self, suffix=""):
        if not self.server:
            return ""
        return self.server.url + suffix

    def _open(self):
        if self.server:
            open_workbench(self.server.url)

    def run(self, startup):
        def boot():
            try:
                self.result.put((startup(), None))
            except Exception as exc:
                logging.getLogger(__name__).exception("Desktop initialization failed")
                self.result.put((None, exc))

        threading.Thread(target=boot, name="WorkRoom-startup", daemon=True).start()
        self.root.after(100, self.poll)
        try:
            self.root.mainloop()
        finally:
            if self.server:
                self.server.stop()
                clear_instance(self.data, self.server)
        return self.restart

    def _paint_dot(self, color):
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 9, 9, fill=color, outline="")

    def poll(self):
        if not self.initialized:
            try:
                self.server, error = self.result.get_nowait()
            except queue.Empty:
                self.root.after(100, self.poll)
                return
            self.initialized = True
            if self.closing:
                self.root.destroy()
                return
            if error:
                self.status.set("启动未完成")
                self.address.configure(
                    text="请检查数据目录中的 logs/desktop.log，然后退出重开。",
                    fg="#d98a8a",
                )
                self._paint_dot("#d98a8a")
                return
            self.status.set("已在本机运行")
            self.address.configure(text=self.server.url, fg=MUTED)
            self._paint_dot("#e0a34a")
            for button in [
                self.open_button,
                self.backups_button,
                self.restart_button,
                self.quit_button,
            ]:
                button.set_enabled(True)
            if not self.no_browser:
                open_workbench(self.server.url)
        from apps.projects.local_backups import restore_state

        self.restart_button.set_text(
            "重启并恢复" if restore_state().get("has_pending") else "重启应用"
        )
        self.root.after(1500, self.poll)

    def on_restart(self):
        from apps.projects.local_backups import BackupError, _ensure_idle

        try:
            _ensure_idle()
        except BackupError as exc:
            messagebox.showinfo("请先完成当前任务", str(exc), parent=self.root)
            return
        self.restart = True
        self.root.destroy()

    def on_close(self):
        if not self.initialized:
            self.closing = True
            self.status.set("正在完成初始化，完成后退出…")
            return
        if self.server:
            from apps.projects.local_backups import BackupError, _ensure_idle

            try:
                _ensure_idle()
            except BackupError:
                if not messagebox.askyesno(
                    "退出 WorkRoom",
                    "仍有任务正在执行，退出可能中断它们。确定退出？",
                    parent=self.root,
                ):
                    return
        self.root.destroy()
