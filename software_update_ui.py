"""Startup update prompt and in-place updater.

One dialog per new version at startup; choosing "稍后" remembers that tag so the
same release is not offered again. Applying downloads, verifies SHA256, replaces
the installation and restarts the app (see auto_update for the mechanics).
"""
import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import auto_update
from app_version import VERSION
from software_update import DEFAULT_REPOSITORY, check_release, repository

BG = '#171b23'
PANEL = '#202630'
TEXT = '#edf3fb'
MUTED = '#93a4bb'


def load_config(app):
    return auto_update.read_config(app)


def save_config(app, config):
    auto_update.write_config(app, config)


class _UpdateBase(tk.Toplevel):
    """Shared download / replace / restart flow."""

    def __init__(self, app, release):
        super().__init__(app)
        self.app = app
        self.release = release
        self.config = load_config(app)
        self.queue = queue.Queue()
        self.busy = False
        self.plan = auto_update.plan(release)
        self.configure(bg=BG)
        self.transient(app)
        self.protocol('WM_DELETE_WINDOW', self.later)

    def build_notes(self, parent):
        note = tk.Text(parent, height=12, wrap='word', bg=PANEL, fg=TEXT, relief='flat',
                       font=('Microsoft YaHei UI', 10), padx=10, pady=8)
        note.insert('1.0', (self.release.get('notes') or '作者未填写更新说明').strip())
        note.configure(state='disabled')
        return note

    def update_now(self):
        if self.busy:
            return
        if not self.plan.get('supported'):
            self.status.set(self.plan.get('reason') or '当前安装方式不支持自动更新')
            return
        self.busy = True
        self.update_button.configure(state='disabled')
        self.later_button.configure(state='disabled')
        self.progress.configure(value=0)
        self.status.set('正在下载新版…')

        def worker():
            try:
                staged = auto_update.stage(
                    self.release, self.app.user_dir / 'updates',
                    lambda done, total: self.queue.put(('progress', (done, total))))
                self.queue.put(('status', '正在替换程序文件…'))
                auto_update.apply(staged, self.plan)
                self.queue.put(('done', True))
            except Exception as error:  # noqa: BLE001 - shown to the user
                self.queue.put(('error', str(error)[:400]))

        threading.Thread(target=worker, daemon=True).start()
        self.after(150, self.poll)

    def poll(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == 'progress':
                    done, total = value
                    self.progress.configure(value=done / max(1, total) * 100)
                    self.status.set(f'正在下载新版… {done / 1048576:.0f} / {total / 1048576:.0f} MB')
                    continue
                if kind == 'status':
                    self.status.set(value)
                    continue
                if kind == 'error':
                    self.busy = False
                    self.update_button.configure(state='normal')
                    self.later_button.configure(state='normal')
                    self.status.set('更新未完成：' + value)
                    continue
                if kind == 'done':
                    self.status.set('更新完成，正在重启…')
                    self.after(300, self.quit_and_restart)
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.after(150, self.poll)

    def quit_and_restart(self):
        # The detached helper waits for this process to exit before swapping files.
        try:
            self.app.destroy()
        finally:
            os._exit(0)

    def later(self):
        if self.busy:
            return
        self.config = auto_update.remember(self.config, skipped_version=self.release.get('tag'))
        save_config(self.app, self.config)
        self.destroy()

    def page(self):
        if self.release.get('page'):
            webbrowser.open(self.release['page'])


class UpdatePrompt(_UpdateBase):
    """The one popup shown at startup when a newer release exists."""

    def __init__(self, app, release):
        super().__init__(app, release)
        self.title('发现新版本')
        self.geometry('620x520')
        self.minsize(540, 440)
        self.resizable(True, True)
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill='both', expand=True)
        tag = str(release.get('tag') or '')
        ttk.Label(frame, text=f'发现新版本 {tag}', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=f'当前版本 {VERSION} · 更新会直接覆盖现有程序，保留你的设置与数据',
                  foreground=MUTED).pack(anchor='w', pady=(4, 10))
        self.build_notes(frame).pack(fill='both', expand=True)
        self.status = tk.StringVar(value='' if self.plan.get('supported') else self.plan.get('reason', ''))
        ttk.Label(frame, textvariable=self.status, wraplength=560).pack(fill='x', pady=(10, 6))
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill='x')
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(12, 0))
        self.update_button = ttk.Button(actions, text='立即更新并重启', command=self.update_now,
                                        state='normal' if self.plan.get('supported') else 'disabled')
        self.update_button.pack(side='left')
        self.later_button = ttk.Button(actions, text='稍后', command=self.later)
        self.later_button.pack(side='left', padx=8)
        ttk.Button(actions, text='发布页面', command=self.page).pack(side='right')
        self.grab_set()


class UpdateWindow(_UpdateBase):
    """Manual check window from 设置 / 数据."""

    def __init__(self, app, release=None):
        super().__init__(app, release or {'tag': '', 'notes': '', 'newer': False, 'asset': None, 'page': ''})
        self.title('软件更新')
        self.geometry('640x600')
        self.minsize(560, 500)
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='软件更新', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=f'当前版本 {VERSION} · 从 GitHub 公开 Release 检查').pack(anchor='w', pady=6)
        self.repo = tk.StringVar(value=self.config.get('repository') or DEFAULT_REPOSITORY)
        self.auto = tk.BooleanVar(value=bool(self.config.get('startup_check', True)))
        ttk.Label(frame, text='GitHub 仓库：owner/repo 或仓库链接').pack(anchor='w')
        ttk.Entry(frame, textvariable=self.repo).pack(fill='x', pady=4)
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=4)
        ttk.Checkbutton(row, text='启动时检查，有新版弹窗一次', variable=self.auto).pack(side='left')
        ttk.Button(row, text='保存并检查', command=self.check).pack(side='right')
        self.status = tk.StringVar(value='点击“检查更新”读取最新 Release。')
        ttk.Label(frame, textvariable=self.status, wraplength=590).pack(fill='x', pady=8)
        self.notes_box = self.build_notes(frame)
        self.notes_box.pack(fill='both', expand=True)
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill='x', pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        self.update_button = ttk.Button(actions, text='立即更新并重启', command=self.update_now, state='disabled')
        self.update_button.pack(side='left')
        self.later_button = ttk.Button(actions, text='关闭', command=self.destroy)
        self.later_button.pack(side='left', padx=8)
        ttk.Button(actions, text='发布页面', command=self.page).pack(side='right')
        ttk.Label(frame, text='下载经过 SHA256 校验；覆盖安装不会删除 userdata 里的设置与记录。',
                  foreground=MUTED, wraplength=590).pack(anchor='w', pady=(10, 0))
        if release and release.get('tag'):
            self.show_release(release)

    def check(self):
        if self.busy:
            return
        try:
            repo = repository(self.repo.get()) if self.repo.get().strip() else ''
            if self.auto.get() and not repo:
                raise ValueError('开启启动检查前请填写仓库')
        except ValueError as error:
            self.status.set(str(error))
            return
        self.config = auto_update.remember(self.config, repository=repo,
                                           startup_check=self.auto.get(), skipped_version='')
        save_config(self.app, self.config)
        self.repo.set(repo)
        self.busy = True
        self.status.set('正在检查 GitHub Release…')
        result = queue.Queue()

        def worker():
            try:
                result.put(('ok', check_release(repo)))
            except Exception as error:  # noqa: BLE001
                result.put(('error', str(error)[:300]))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                kind, value = result.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            self.busy = False
            if kind == 'error':
                self.status.set(value)
                return
            self.show_release(value)

        self.after(150, poll)

    def show_release(self, release):
        self.release = release
        self.plan = auto_update.plan(release)
        self.notes_box.configure(state='normal')
        self.notes_box.delete('1.0', 'end')
        self.notes_box.insert('1.0', (release.get('notes') or '').strip())
        self.notes_box.configure(state='disabled')
        if not release.get('newer'):
            self.status.set('当前已是最新版本。')
            self.update_button.configure(state='disabled')
            return
        if not self.plan.get('supported'):
            self.status.set(self.plan.get('reason') or 'Release 未提供适用的 Windows 文件。')
            self.update_button.configure(state='disabled')
            return
        self.status.set(f"发现新版本 {release.get('tag')}，可直接更新。")
        self.update_button.configure(state='normal')


def open_update(app, release=None):
    existing = getattr(app, 'software_update_window', None)
    if existing is not None and existing.winfo_exists():
        if release:
            existing.show_release(release)
        existing.lift()
        return existing
    app.software_update_window = UpdateWindow(app, release)
    return app.software_update_window


def startup_check(app):
    """Silent check; one dialog per new version, remembered when declined."""
    config = load_config(app)
    if not config.get('startup_check', True):
        return
    repo = config.get('repository') or DEFAULT_REPOSITORY
    results = queue.Queue()

    def worker():
        try:
            results.put(check_release(repo))
        except Exception:  # noqa: BLE001 - offline / rate limited / 404
            results.put(None)

    def poll():
        try:
            release = results.get_nowait()
        except queue.Empty:
            app.after(250, poll)
            return
        if release and auto_update.should_prompt(release, load_config(app)):
            UpdatePrompt(app, release)

    threading.Thread(target=worker, daemon=True).start()
    app.after(250, poll)
