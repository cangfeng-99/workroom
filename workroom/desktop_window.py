"""A small native controller; all project work stays in the browser UI."""

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from desktop_runtime import clear_instance, open_workbench


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
        self.root.geometry("560x430")
        self.root.minsize(520, 410)
        self.root.configure(bg="#f4f7f4")
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        frame = tk.Frame(self.root, bg="#f4f7f4", padx=28, pady=24)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="WorkRoom",
            bg="#f4f7f4",
            fg="#16211b",
            font=("Microsoft YaHei UI", 21, "bold"),
        ).pack(anchor="w")
        self.status = tk.StringVar(value="正在准备本机工作台…")
        tk.Label(
            frame,
            textvariable=self.status,
            bg="#f4f7f4",
            fg="#0a5a42",
            pady=12,
            anchor="w",
            wraplength=490,
            justify="left",
        ).pack(fill="x")
        tk.Label(
            frame,
            text="项目页面在浏览器中使用。关闭网页后应用仍会运行；关闭这个窗口即可退出。",
            bg="#f4f7f4",
            fg="#4b5850",
            wraplength=490,
            justify="left",
        ).pack(fill="x", pady=(0, 20))
        self.open_button = tk.Button(
            frame,
            text="打开工作台",
            command=lambda: open_workbench(self.server.url),
            bg="#0f7a5a",
            fg="white",
            activebackground="#0a5a42",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=9,
            state="disabled",
            highlightthickness=2,
            highlightcolor="#0f7a5a",
        )
        self.open_button.pack(anchor="w")
        actions = tk.Frame(frame, bg="#f4f7f4")
        actions.pack(fill="x", pady=(14, 20))
        self.backups_button = ttk.Button(
            actions,
            text="备份与恢复",
            command=lambda: open_workbench(self.server.url + "backups/"),
            state="disabled",
        )
        self.backups_button.pack(side="left", padx=(0, 10))
        self.restart_button = ttk.Button(
            actions, text="重启应用", command=self.on_restart, state="disabled"
        )
        self.restart_button.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="退出应用", command=self.on_close).pack(side="left")
        tk.Label(frame, text="数据位置", bg="#f4f7f4", fg="#4b5850").pack(anchor="w")
        tk.Message(frame, text=str(data), bg="#f4f7f4", fg="#4b5850", width=490, anchor="w").pack(
            fill="x"
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

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
                self.status.set("启动未完成，请检查数据目录中的 logs/desktop.log，然后退出重开。")
                return
            self.status.set("已在本机运行 · " + self.server.url)
            for button in [self.open_button, self.backups_button, self.restart_button]:
                button.configure(state="normal")
            if not self.no_browser:
                open_workbench(self.server.url)
        from apps.projects.local_backups import restore_state

        self.restart_button.configure(
            text="重启并恢复" if restore_state().get("has_pending") else "重启应用"
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
