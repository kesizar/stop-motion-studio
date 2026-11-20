"""Chinese Tkinter interface for the stop-motion studio."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


FONT = "Microsoft YaHei UI"
PAPER = "#ffffff"
INK = "#192c36"
MUTED = "#526a76"
DARK = "#182a31"
TEAL = "#08675e"


def label(parent, text, size=10, bold=False, fg=INK, bg=PAPER):
    return tk.Label(parent, text=text, bg=bg, fg=fg, anchor="w", justify="left",
                    font=(FONT, size, "bold" if bold else "normal"))


def button(parent, text, command, primary=False):
    return tk.Button(parent, text=text, command=command,
                     bg=TEAL if primary else "#eaf1f2", fg="white" if primary else INK,
                     activebackground="#09574e" if primary else "#d9e6e8",
                     activeforeground="white" if primary else INK, disabledforeground="#758b93",
                     font=(FONT, 9), relief="flat", borderwidth=0, padx=7, pady=3, cursor="hand2")


class StudioUI:
    """Render capture and playback. All project and device decisions belong to the controller."""

    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        self.frames = []
        self._image = None
        self._photo = None
        self._resize_job = None
        self._strip_job = None
        self._thumbnail_images = []
        self._page_end = 0
        self._playing = False
        self._source = "待机"
        self._camera = tk.StringVar(root, value="0")
        self._fps = tk.StringVar(root, value="8")
        self._onion_skin = tk.BooleanVar(root, value=False)
        root.title("逐格 · 定格动画工作台")
        root.geometry("1040x720")
        root.minsize(740, 550)
        root.configure(bg="#f0f4f5")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = tk.Frame(root, bg=DARK, padx=18, pady=9)
        header.grid(row=0, column=0, sticky="ew")
        label(header, "逐格  /  定格动画工作台", 15, True, "white", DARK).pack(side="left")
        self.source_label = label(header, self._source, fg="#bbded7", bg=DARK)
        self.source_label.pack(side="right")
        self.project_label = label(header, "", fg="white", bg=DARK)
        self.project_label.pack(side="right", padx=(0, 14))

        body = tk.Frame(root, bg="#f0f4f5")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        card = tk.Frame(body, bg=PAPER)
        card.grid(row=0, column=0, sticky="nsew")
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)
        label(card, "取景与回放", 11, True).grid(row=0, column=0, padx=12, pady=5, sticky="w")
        self.preview = tk.Canvas(card, bg=DARK, highlightthickness=0, width=300, height=150)
        self.preview.grid(row=1, column=0, sticky="nsew", padx=7)
        self._preview_item = self.preview.create_image(0, 0)
        self._placeholder = self.preview.create_text(
            0, 0, text="打开摄像头，或在右侧试用演示", fill="#c4d6dc", font=(FONT, 11)
        )
        self.preview.bind("<Configure>", self._queue_preview)

        self._progress_value = None
        self._progress_captured = False
        self._progress_bar = tk.Canvas(card, height=5, bg="#eaf1f2", highlightthickness=0)
        self._progress_bar.grid(row=2, column=0, sticky="ew", padx=7)
        self._progress_fill = self._progress_bar.create_rectangle(0, 0, 0, 5, width=0, state="hidden")
        self._progress_bar.bind("<Configure>", self._draw_capture_progress)

        capture_controls = tk.Frame(card, bg=PAPER)
        capture_controls.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        tk.Checkbutton(
            capture_controls, text="上一帧叠影", variable=self._onion_skin,
            command=lambda: controller.set_onion_skin(self._onion_skin.get()),
            bg=PAPER, fg=INK, activebackground=PAPER, font=(FONT, 9), padx=0, pady=0,
        ).pack(side="left")
        self.capture_button = button(capture_controls, "手动拍一帧", controller.manual_capture)
        self.capture_button.pack(side="right")
        self.pause_button = button(capture_controls, "暂停自动快门", controller.toggle_auto_pause)
        self.pause_button.pack(side="right", padx=(6, 4))
        self.set_capture_controls(available=False, paused=False, can_capture=False)

        self.status_label = label(card, "把一个小物件放在镜头前。", fg=MUTED)
        self.status_label.grid(row=4, column=0, sticky="ew", padx=12, pady=5)

        panel = tk.Frame(body, bg=PAPER, padx=12, pady=7)
        panel.grid(row=0, column=1, sticky="ns", padx=(9, 0))
        panel.columnconfigure(0, weight=1)
        label(panel, "开始拍摄", 12, True).grid(row=0, column=0, sticky="w")
        label(panel, "固定镜头，移动物件，再把手移出画面。\n画面稳定后，工作台会自动拍下一帧。", 9, fg=MUTED).grid(
            row=1, column=0, sticky="w", pady=(2, 6)
        )
        selector = tk.Frame(panel, bg=PAPER)
        selector.grid(row=2, column=0, sticky="ew")
        label(selector, "摄像头编号", 9, fg=MUTED).pack(side="left")
        ttk.Combobox(selector, textvariable=self._camera, values=tuple(range(8)), width=4).pack(side="right")
        button(panel, "打开摄像头", self._start_camera, True).grid(row=3, column=0, sticky="ew", pady=(5, 3))
        sources = self._paired_row(panel, 4)
        button(sources, "试用演示", controller.start_demo).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        button(sources, "停止取景", controller.stop_source).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        ttk.Separator(panel).grid(row=5, column=0, sticky="ew", pady=7)
        label(panel, "播放与保存", 12, True).grid(row=6, column=0, sticky="w")
        speed_row = tk.Frame(panel, bg=PAPER)
        speed_row.grid(row=7, column=0, sticky="ew", pady=(3, 4))
        label(speed_row, "回放速度（帧/秒）", 9, fg=MUTED).pack(side="left")
        speed = ttk.Combobox(speed_row, textvariable=self._fps, values=tuple(range(2, 17)), width=4, state="readonly")
        speed.pack(side="right")
        speed.bind("<<ComboboxSelected>>", lambda _e: controller.set_fps(int(self._fps.get())))
        edits = self._paired_row(panel, 8)
        self.play_button = button(edits, "回放", controller.playback)
        self.play_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.undo_button = button(edits, "撤回一帧", controller.undo)
        self.undo_button.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        self.export_button = button(panel, "导出 GIF", controller.export_gif, True)
        self.export_button.grid(row=9, column=0, sticky="ew", pady=(5, 0))
        projects = self._paired_row(panel, 10)
        self.open_project_button = button(projects, "打开作品…", controller.open_project_dialog)
        self.open_project_button.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=(3, 0))
        button(projects, "新建项目", controller.new_project).grid(
            row=0, column=1, sticky="ew", padx=(2, 0), pady=(3, 0),
        )

        timeline = tk.Frame(root, bg=PAPER, padx=10, pady=4)
        timeline.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        timeline.columnconfigure(0, weight=1)
        strip_header = tk.Frame(timeline, bg=PAPER)
        strip_header.grid(row=0, column=0, sticky="ew")
        self.count_label = label(strip_header, "已拍 0 帧", 11, True)
        self.count_label.pack(side="left")
        self.next_button = button(strip_header, "后页 ›", lambda: self._turn_page(1))
        self.next_button.pack(side="right", padx=(3, 0))
        self.prev_button = button(strip_header, "‹ 前页", lambda: self._turn_page(-1))
        self.prev_button.pack(side="right")
        self.strip = tk.Canvas(timeline, height=71, width=200, bg=PAPER, highlightthickness=0)
        self.strip.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.strip.bind("<Configure>", self._queue_strip)
        self.strip.bind("<Button-1>", self._inspect_thumbnail)
        root.bind("<Control-z>", lambda e: self._shortcut(e, self.undo_button))
        root.bind("<Control-s>", lambda e: self._shortcut(e, self.export_button))
        root.bind("<space>", lambda e: self._shortcut(e, self.play_button))
        self.set_timeline([])

    @staticmethod
    def _paired_row(parent, row):
        group = tk.Frame(parent, bg=PAPER)
        group.grid(row=row, column=0, sticky="ew")
        for col in range(2):
            group.columnconfigure(col, weight=1, uniform="pair")
        return group

    @staticmethod
    def _shortcut(event, action):
        widget_class = event.widget.winfo_class()
        if widget_class in {"TCombobox", "Entry", "TEntry", "Text"}:
            return None
        if event.keysym == "space" and widget_class == "Button":
            return None
        action.invoke()
        return "break"

    def _start_camera(self):
        try:
            index = int(self._camera.get())
            if index < 0:
                raise ValueError()
        except ValueError:
            self.set_status("摄像头编号需要是非负整数，一般先试 0。")
            return
        self.controller.start_camera(index)

    @staticmethod
    def _project_title(name: str) -> str:
        return f"作品 {name.removeprefix('session-')}"

    def set_project(self, name: str) -> None:
        self.project_label.config(text=self._project_title(name) if name else "")

    def choose_project(self, names: list[str], current: str) -> str | None:
        """Return a chosen session name. Closing the dialog leaves the project unchanged."""
        if not names:
            return None

        window = tk.Toplevel(self.root)
        window.title("打开作品")
        window.transient(self.root)
        window.configure(bg=PAPER, padx=14, pady=12)
        window.resizable(False, False)
        label(window, "选择要继续编辑的作品", 11, True).pack(anchor="w", pady=(0, 8))

        project_list = tk.Frame(window, bg=PAPER)
        project_list.pack(fill="x")
        scrollbar = ttk.Scrollbar(project_list, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        options = tk.Listbox(
            project_list, width=30, height=min(8, len(names)), selectmode=tk.BROWSE,
            exportselection=False, font=(FONT, 10), yscrollcommand=scrollbar.set,
        )
        options.pack(side="left", fill="both")
        scrollbar.config(command=options.yview)
        for name in names:
            suffix = "（当前）" if name == current else ""
            options.insert(tk.END, self._project_title(name) + suffix)
        selected = names.index(current) if current in names else 0
        options.selection_set(selected)
        options.activate(selected)
        options.see(selected)

        result = None

        def accept(_event=None):
            nonlocal result
            selection = options.curselection()
            if selection:
                result = names[selection[0]]
                window.destroy()

        actions = tk.Frame(window, bg=PAPER)
        actions.pack(fill="x", pady=(10, 0))
        button(actions, "打开", accept, True).pack(side="right")
        button(actions, "取消", window.destroy).pack(side="right", padx=(0, 6))
        window.bind("<Return>", accept)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.wait_visibility()
        window.grab_set()
        options.focus_set()
        window.wait_window()
        return result

    def set_source(self, label):
        self._source = label
        self.source_label.config(text="动画回放" if self._playing else label)

    def set_playing(self, playing):
        self._playing = playing
        self.play_button.config(text="停止回放" if playing else "回放")
        self.source_label.config(text="动画回放" if playing else self._source)

    def set_status(self, text):
        self.status_label.config(text=text)

    def set_capture_controls(self, *, available, paused, can_capture):
        self.pause_button.config(
            text="恢复自动快门" if paused else "暂停自动快门",
            state="normal" if available else "disabled",
        )
        self.capture_button.config(state="normal" if available and can_capture else "disabled")

    def set_capture_progress(self, progress, *, captured=False):
        if (progress, captured) == (self._progress_value, self._progress_captured):
            return
        self._progress_value = progress
        self._progress_captured = captured
        self._progress_bar.itemconfigure(
            self._progress_fill, state="hidden" if progress is None else "normal",
            fill="#208052" if captured else "#cf8218",
        )
        self._draw_capture_progress()

    def _draw_capture_progress(self, _event=None):
        if self._progress_value is not None:
            width = round(self._progress_bar.winfo_width() * self._progress_value)
            self._progress_bar.coords(self._progress_fill, 0, 0, width, 5)

    def cancel_pending_draws(self):
        for job in (self._resize_job, self._strip_job):
            if job is not None:
                self.root.after_cancel(job)
        self._resize_job = None
        self._strip_job = None

    def show_frame(self, rgb):
        self._image = rgb
        self._queue_preview()

    def _queue_preview(self, _event=None):
        if self._resize_job is None:
            self._resize_job = self.root.after_idle(self._draw_preview)

    def _draw_preview(self):
        self._resize_job = None
        w, h = self.preview.winfo_width(), self.preview.winfo_height()
        self.preview.coords(self._placeholder, w // 2, h // 2)
        self.status_label.config(wraplength=max(180, w - 18))
        if self._image is None:
            self.preview.itemconfigure(self._placeholder, state="normal")
            self.preview.itemconfigure(self._preview_item, image="")
            self._photo = None
            return
        if w <= 1 or h <= 1:
            return
        scale = min(w / self._image.width, h / self._image.height)
        size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        self._photo = ImageTk.PhotoImage(self._image.resize(size, Image.Resampling.BILINEAR), master=self.root)
        self.preview.itemconfigure(self._placeholder, state="hidden")
        self.preview.coords(self._preview_item, w // 2, h // 2)
        self.preview.itemconfigure(self._preview_item, image=self._photo)

    def set_timeline(self, frames):
        self.frames = frames
        self._page_end = len(frames)
        self.count_label.config(text=f"已拍 {len(frames)} 帧")
        for action in (self.play_button, self.undo_button, self.export_button):
            action.config(state="normal" if frames else "disabled")
        self._queue_strip()

    def _capacity(self):
        return max(1, self.strip.winfo_width() // 96)

    def _turn_page(self, direction):
        self._page_end += direction * self._capacity()
        self._queue_strip()

    def _queue_strip(self, _event=None):
        if self._strip_job is None:
            self._strip_job = self.root.after_idle(self._draw_strip)

    def _draw_strip(self):
        self._strip_job = None
        self.strip.delete("all")
        self._thumbnail_images.clear()
        capacity = self._capacity()
        self._page_end = min(len(self.frames), max(capacity, self._page_end))
        start = max(0, self._page_end - capacity)
        self.prev_button.config(state="normal" if start else "disabled")
        self.next_button.config(state="normal" if self._page_end < len(self.frames) else "disabled")
        if not self.frames:
            self.strip.create_text(5, 31, text="拍下的画面会按顺序排在这里。", anchor="w", font=(FONT, 9), fill=MUTED)
            return
        for position, index in enumerate(range(start, self._page_end)):
            x = 4 + position * 96
            tags = (f"frame_{index}",)
            self.strip.create_rectangle(x, 2, x + 88, 53, fill="#eaf1f2", outline="", tags=tags)
            shot = self.frames[index].copy()
            shot.thumbnail((86, 49), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(shot, master=self.root)
            self._thumbnail_images.append(photo)
            self.strip.create_image(x + 44, 27, image=photo, tags=tags)
            self.strip.create_text(x + 44, 63, text=f"第 {index + 1} 帧", fill=MUTED, font=(FONT, 8), tags=tags)

    def _inspect_thumbnail(self, _event):
        tag = next((tag for tag in self.strip.gettags("current") if tag.startswith("frame_")), None)
        if tag is None:
            return
        index = int(tag[6:])
        if index >= len(self.frames):
            return
        window = tk.Toplevel(self.root)
        window.title(f"画面检查 · 第 {index + 1} 帧")
        window.transient(self.root)
        shot = self.frames[index].copy()
        shot.thumbnail((min(850, self.root.winfo_screenwidth() - 60), min(600, self.root.winfo_screenheight() - 120)),
                       Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(shot, master=window)
        view = tk.Label(window, image=photo, bg=DARK)
        view.image = photo
        view.pack()
        window.bind("<Escape>", lambda _e: window.destroy())
