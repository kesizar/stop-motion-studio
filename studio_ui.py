"""Tkinter application views for the stop-motion workbench."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


FONT = "Microsoft YaHei UI"
BG = "#111722"
PANEL = "#1b2432"
SURFACE = "#273345"
BORDER = "#34445a"
INK = "#f1f4f8"
MUTED = "#a4b2c6"
DISABLED = "#738199"
VIEWPORT = "#0b101a"
AMBER = "#f3b867"
DARK_INK = "#241a0f"
GREEN = "#63d6a4"

TILE_WIDTH = 92
TILE_STEP = 100
STRIP_PADDING = 2


def label(parent, text, size=10, bold=False, fg=INK, bg=PANEL):
    return tk.Label(parent, text=text, bg=bg, fg=fg, anchor="w", justify="left",
                    font=(FONT, size, "bold" if bold else "normal"))


def button(parent, text, command, primary=False, compact=False):
    return tk.Button(
        parent, text=text, command=command,
        bg=AMBER if primary else SURFACE, fg=DARK_INK if primary else INK,
        activebackground="#ffce8c" if primary else BORDER,
        activeforeground=DARK_INK if primary else INK, disabledforeground=DISABLED,
        font=(FONT, 9, "bold" if primary else "normal"), relief="flat", borderwidth=0,
        highlightthickness=1, highlightbackground=AMBER if primary else BORDER,
        highlightcolor=AMBER, padx=8, pady=2 if compact else 4, cursor="hand2",
    )


class StudioUI:
    """Render capture, frame inspection and playback through the same preview."""

    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        self.frames = []
        self._image = None
        self._photo = None
        self._resize_job = None
        self._strip_job = None
        self._thumbnail_images = {}
        self._visible_tiles = {}
        self._page_start = 0
        self._timeline_edits = ()
        self._edit_controls = None
        self._hold = tk.StringVar(root, value="1")
        self._region = None
        self._region_available = False
        self._region_selecting = False
        self._drag_start = None
        self._drag_end = None
        self._position = None
        self._playing = False
        self._reviewing = False
        self._source = "待机"
        self._camera = tk.StringVar(root, value="0")
        self._fps = tk.StringVar(root, value="8")
        self._onion_skin = tk.BooleanVar(root, value=False)
        self._progress_value = None
        self._progress_captured = False

        root.title("逐格 · 定格动画工作台")
        root.geometry("1100x748")
        root.minsize(740, 550)
        root.configure(bg=BG)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self._configure_styles()
        self._build_header()

        body = tk.Frame(root, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self._build_preview(body)
        self._build_sidebar(body)
        self._build_timeline()

        for key, action in (
            ("<Control-z>", self.edit_undo_button),
            ("<Control-y>", self.edit_redo_button),
            ("<Control-s>", self.export_button),
            ("<space>", self.play_button),
            ("<Left>", self.previous_frame_button),
            ("<Right>", self.next_frame_button),
        ):
            root.bind(key, lambda event, target=action: self._shortcut(event, target))
        root.bind("<Escape>", self._escape)
        self.set_edit_controls(available=False, hold=1, hidden=False, can_undo=False, can_redo=False)
        self.set_capture_controls(available=False, paused=False, can_capture=False)
        self.set_reviewing(False)
        self.set_timeline([])

    def _configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Studio.TCombobox", fieldbackground=SURFACE, background=SURFACE,
            foreground=INK, arrowcolor=INK, selectforeground=INK, selectbackground=SURFACE,
            bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
            insertcolor=INK, padding=2,
        )
        style.map(
            "Studio.TCombobox",
            fieldbackground=[("readonly", SURFACE)],
            background=[("active", BORDER), ("pressed", BORDER)],
        )
        style.configure(
            "Studio.Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
            arrowcolor=INK, bordercolor=PANEL, lightcolor=BORDER, darkcolor=BORDER,
        )
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", AMBER)
        self.root.option_add("*TCombobox*Listbox.selectForeground", DARK_INK)

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG, padx=15, pady=10)
        header.grid(row=0, column=0, sticky="ew")
        label(header, "逐格", 17, True, AMBER, BG).pack(side="left")
        label(header, "定格动画工作台", 10, fg=MUTED, bg=BG).pack(side="left", padx=(12, 0))
        self.source_label = label(header, self._source, 9, True, AMBER, SURFACE)
        self.source_label.config(padx=9, pady=3)
        self.source_label.pack(side="right")
        self.project_label = label(header, "", 9, fg=MUTED, bg=BG)
        self.project_label.pack(side="right", padx=(0, 12))

    def _build_preview(self, body):
        card = tk.Frame(body, bg=PANEL, padx=10, pady=8)
        card.grid(row=0, column=0, sticky="nsew")
        card.rowconfigure(1, weight=1)
        card.columnconfigure(0, weight=1)

        viewer_header = tk.Frame(card, bg=PANEL)
        viewer_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.viewer_label = label(viewer_header, "取景预览", 11, True)
        self.viewer_label.pack(side="left")
        self.resume_button = button(
            viewer_header, "返回取景", self.controller.resume_preview, compact=True,
        )
        self.resume_button.pack(side="right")
        self.region_clear_button = button(viewer_header, "清除区域", self._clear_region, compact=True)
        self.region_clear_button.pack(side="right", padx=(4, 6))
        self.region_select_button = button(viewer_header, "框选区域", self._toggle_region_selection, compact=True)
        self.region_select_button.pack(side="right")
        self.region_clear_button.config(state="disabled")
        self.region_select_button.config(state="disabled")

        self.preview = tk.Canvas(card, bg=VIEWPORT, highlightthickness=0, width=250, height=130)
        self.preview.grid(row=1, column=0, sticky="nsew")
        self._preview_item = self.preview.create_image(0, 0)
        self._placeholder = self.preview.create_text(
            0, 0, text="打开摄像头，或先试用演示", fill=MUTED, font=(FONT, 11),
        )
        self._region_outline = self.preview.create_rectangle(
            0, 0, 0, 0, outline=GREEN, width=2, dash=(5, 3), state="hidden",
        )
        self.preview.bind("<Configure>", self._queue_preview)
        self.preview.bind("<ButtonPress-1>", self._start_region_drag)
        self.preview.bind("<B1-Motion>", self._move_region_drag)
        self.preview.bind("<ButtonRelease-1>", self._finish_region_drag)

        self._progress_bar = tk.Canvas(card, height=4, bg=SURFACE, highlightthickness=0)
        self._progress_bar.grid(row=2, column=0, sticky="ew")
        self._progress_fill = self._progress_bar.create_rectangle(0, 0, 0, 4, width=0, state="hidden")
        self._progress_bar.bind("<Configure>", self._draw_capture_progress)

        capture_controls = tk.Frame(card, bg=PANEL)
        capture_controls.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.onion_button = tk.Checkbutton(
            capture_controls, text="上一帧叠影", variable=self._onion_skin,
            command=lambda: self.controller.set_onion_skin(self._onion_skin.get()),
            bg=PANEL, fg=INK, activebackground=PANEL, activeforeground=INK,
            disabledforeground=DISABLED, selectcolor=SURFACE, highlightcolor=AMBER,
            font=(FONT, 9), highlightbackground=PANEL, padx=0, pady=0,
        )
        self.onion_button.pack(side="left")
        self.capture_button = button(
            capture_controls, "手动拍一帧", self.controller.manual_capture, compact=True,
        )
        self.capture_button.pack(side="right")
        self.pause_button = button(
            capture_controls, "暂停自动快门", self.controller.toggle_auto_pause, compact=True,
        )
        self.pause_button.pack(side="right", padx=(5, 4))

        self.status_label = label(card, "把一个小物件放在镜头前。", 9, fg=MUTED)
        self.status_label.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.alignment_label = label(card, "", 9, fg=AMBER)
        self.alignment_label.grid(row=5, column=0, sticky="ew", pady=(2, 0))
        self.alignment_label.grid_remove()

    def _build_sidebar(self, body):
        controller = self.controller
        sidebar = tk.Frame(body, bg=PANEL)
        sidebar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        sidebar.rowconfigure(0, weight=1)
        canvas = tk.Canvas(sidebar, bg=PANEL, width=1, height=1, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            sidebar, orient="vertical", style="Studio.Vertical.TScrollbar", command=canvas.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        scrollbar.grid_remove()
        canvas.configure(yscrollcommand=scrollbar.set)

        panel = tk.Frame(canvas, bg=PANEL, padx=11, pady=9)
        panel.columnconfigure(0, weight=1)
        canvas.create_window(0, 0, window=panel, anchor="nw")

        label(panel, "拍摄", 11, True).grid(row=0, column=0, sticky="w")
        selector = tk.Frame(panel, bg=PANEL)
        selector.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        label(selector, "摄像头编号", 9, fg=MUTED).pack(side="left")
        ttk.Combobox(
            selector, textvariable=self._camera, values=tuple(range(8)), width=4,
            style="Studio.TCombobox",
        ).pack(side="right")
        button(panel, "打开摄像头", self._start_camera, True).grid(
            row=2, column=0, sticky="ew", pady=(4, 4),
        )
        sources = self._paired_row(panel, 3)
        button(sources, "试用演示", controller.start_demo).grid(
            row=0, column=0, sticky="ew", padx=(0, 2),
        )
        button(sources, "停止取景", controller.stop_source).grid(
            row=0, column=1, sticky="ew", padx=(2, 0),
        )

        tk.Frame(panel, bg=BORDER, height=1).grid(row=4, column=0, sticky="ew", pady=7)
        label(panel, "回放与导出", 11, True).grid(row=5, column=0, sticky="w")
        speed_row = tk.Frame(panel, bg=PANEL)
        speed_row.grid(row=6, column=0, sticky="ew", pady=(4, 4))
        label(speed_row, "速度（帧 / 秒）", 9, fg=MUTED).pack(side="left", padx=(0, 12))
        speed = ttk.Combobox(
            speed_row, textvariable=self._fps, values=tuple(range(2, 17)), width=4,
            state="readonly", style="Studio.TCombobox",
        )
        speed.pack(side="right")
        speed.bind("<<ComboboxSelected>>", lambda _event: controller.set_fps(int(self._fps.get())))
        edits = self._paired_row(panel, 7)
        self.play_button = button(edits, "回放", controller.playback)
        self.play_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.undo_button = button(edits, "撤回末帧", controller.undo)
        self.undo_button.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        exports = self._paired_row(panel, 8)
        self.export_button = button(exports, "导出 GIF", controller.export_gif)
        self.export_button.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=(4, 0))
        self.export_mp4_button = button(exports, "导出 MP4", controller.export_mp4)
        self.export_mp4_button.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=(4, 0))

        tk.Frame(panel, bg=BORDER, height=1).grid(row=9, column=0, sticky="ew", pady=7)
        projects = self._paired_row(panel, 10)
        self.open_project_button = button(projects, "打开作品…", controller.open_project_dialog)
        self.open_project_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        button(projects, "新建项目", controller.new_project).grid(
            row=0, column=1, sticky="ew", padx=(2, 0),
        )

        self.import_button = button(panel, "导入照片序列", controller.import_images)
        self.import_button.grid(row=11, column=0, sticky="ew", pady=(4, 0))

        self._build_editor(panel)
        self._fit_sidebar(canvas, panel, scrollbar)

    def _build_editor(self, panel):
        tk.Frame(panel, bg=BORDER, height=1).grid(row=12, column=0, sticky="ew", pady=7)
        label(panel, "画格剪辑", 11, True).grid(row=13, column=0, sticky="w")
        hold_row = tk.Frame(panel, bg=PANEL)
        hold_row.grid(row=14, column=0, sticky="ew", pady=(4, 4))
        label(hold_row, "停留格数", 9, fg=MUTED).pack(side="left")
        self.apply_hold_button = button(hold_row, "应用", self._apply_hold, compact=True)
        self.apply_hold_button.pack(side="right", padx=(4, 0))
        self.hold_spinbox = tk.Spinbox(
            hold_row, from_=1, to=120, textvariable=self._hold, width=4, justify="center",
            bg=SURFACE, fg=INK, disabledbackground=PANEL, disabledforeground=DISABLED,
            insertbackground=INK, buttonbackground=SURFACE, relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=AMBER, font=(FONT, 9),
        )
        self.hold_spinbox.pack(side="right")
        self.hold_spinbox.bind("<Return>", self._apply_hold)
        self.hide_frame_button = button(panel, "隐藏画格", self.controller.toggle_selected_hidden)
        self.hide_frame_button.grid(row=15, column=0, sticky="ew")
        history = self._paired_row(panel, 16)
        self.edit_undo_button = button(history, "撤销剪辑", self.controller.undo_edit)
        self.edit_undo_button.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=(4, 0))
        self.edit_redo_button = button(history, "重做剪辑", self.controller.redo_edit)
        self.edit_redo_button.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=(4, 0))

    def _apply_hold(self, _event=None):
        if str(self.hold_spinbox.cget("state")) != "disabled":
            try:
                count = int(self._hold.get())
            except ValueError:
                count = 0
            if 1 <= count <= 120:
                self.controller.set_selected_hold(count)
            else:
                self.set_status("停留格数请输入 1 到 120 的整数。")
        return "break"

    def set_edit_controls(self, *, available, hold, hidden, can_undo, can_redo):
        controls = (available, hold, hidden, can_undo, can_redo)
        if controls == self._edit_controls:
            return
        if self._edit_controls is None or (available, hold) != self._edit_controls[:2]:
            self._hold.set(str(hold))
        self._edit_controls = controls
        enabled = "normal" if available else "disabled"
        self.hold_spinbox.config(state=enabled)
        self.apply_hold_button.config(state=enabled)
        self.hide_frame_button.config(
            state=enabled, text="恢复显示" if hidden else "隐藏画格",
        )
        self.edit_undo_button.config(state="normal" if can_undo else "disabled")
        self.edit_redo_button.config(state="normal" if can_redo else "disabled")

    @staticmethod
    def _fit_sidebar(canvas, panel, scrollbar):
        def resize(_event=None):
            width, height = panel.winfo_reqwidth(), panel.winfo_reqheight()
            canvas.configure(width=width, scrollregion=(0, 0, width, height))
            if height > canvas.winfo_height():
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
                canvas.yview_moveto(0)

        def wheel(event):
            if scrollbar.winfo_ismapped() and event.delta:
                steps = max(1, abs(event.delta) // 120)
                canvas.yview_scroll(-steps if event.delta > 0 else steps, "units")
                return "break"
            return None

        def reveal_focus(event):
            if not scrollbar.winfo_ismapped():
                return
            widget = event.widget
            top = widget.winfo_rooty() - panel.winfo_rooty()
            bottom = top + widget.winfo_height()
            first = canvas.canvasy(0)
            last = first + canvas.winfo_height()
            if top < first or bottom > last:
                y = top if top < first else bottom - canvas.winfo_height()
                canvas.yview_moveto(max(0, y) / panel.winfo_reqheight())

        canvas.bind("<Configure>", resize)
        panel.bind("<Configure>", resize)
        canvas.bind("<MouseWheel>", wheel)
        widgets = [panel]
        while widgets:
            widget = widgets.pop()
            widgets.extend(widget.winfo_children())
            widget.bind("<MouseWheel>", wheel, add="+")
            widget.bind("<FocusIn>", reveal_focus, add="+")

    def _build_timeline(self):
        timeline = tk.Frame(self.root, bg=PANEL, padx=10, pady=7)
        timeline.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 11))
        timeline.columnconfigure(0, weight=1)

        strip_header = tk.Frame(timeline, bg=PANEL)
        strip_header.grid(row=0, column=0, sticky="ew")
        label(strip_header, "时间轴", 11, True).pack(side="left")
        self.count_label = label(strip_header, "0 帧", 9, fg=MUTED)
        self.count_label.pack(side="left", padx=(7, 0))
        self.next_button = button(strip_header, "后页 ›", lambda: self._turn_page(1), compact=True)
        self.next_button.pack(side="right", padx=(4, 0))
        self.prev_button = button(strip_header, "‹ 前页", lambda: self._turn_page(-1), compact=True)
        self.prev_button.pack(side="right", padx=(12, 0))
        self.next_frame_button = button(
            strip_header, "下一帧", lambda: self.controller.step_frame(1), compact=True,
        )
        self.next_frame_button.pack(side="right", padx=(4, 0))
        self.previous_frame_button = button(
            strip_header, "上一帧", lambda: self.controller.step_frame(-1), compact=True,
        )
        self.previous_frame_button.pack(side="right")
        self.frame_label = label(strip_header, "— / —", 9, fg=MUTED)
        self.frame_label.config(anchor="e")
        self.frame_label.pack(side="right", padx=(8, 10))

        self.strip = tk.Canvas(timeline, height=71, width=200, bg=PANEL, highlightthickness=0)
        self.strip.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.strip.bind("<Configure>", self._resize_strip)
        self.strip.bind("<Button-1>", self._select_thumbnail)
        self.strip.bind("<Double-Button-1>", self._inspect_thumbnail)

    @staticmethod
    def _paired_row(parent, row):
        group = tk.Frame(parent, bg=PANEL)
        group.grid(row=row, column=0, sticky="ew")
        for col in range(2):
            group.columnconfigure(col, weight=1, uniform="pair")
        return group

    @staticmethod
    def _shortcut(event, action):
        widget_class = event.widget.winfo_class()
        if widget_class in {"TCombobox", "Entry", "TEntry", "Text", "Listbox", "Spinbox"}:
            return None
        if event.keysym == "space" and widget_class in {"Button", "Checkbutton"}:
            return None
        if str(action.cget("state")) != "disabled":
            action.invoke()
            return "break"
        return None

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
    def _project_title(name):
        return f"作品 {name.removeprefix('session-')}"

    def set_project(self, name):
        self.project_label.config(text=self._project_title(name) if name else "")

    def choose_project(self, names, current):
        """Return a chosen session name. Closing the dialog leaves it unchanged."""
        if not names:
            return None

        window = tk.Toplevel(self.root, bg=PANEL, padx=14, pady=12)
        window.title("打开作品")
        window.transient(self.root)
        window.resizable(False, False)
        label(window, "选择作品", 11, True).pack(anchor="w", pady=(0, 8))

        project_list = tk.Frame(window, bg=PANEL)
        project_list.pack(fill="x")
        scrollbar = ttk.Scrollbar(project_list, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        options = tk.Listbox(
            project_list, width=30, height=min(8, len(names)), selectmode=tk.BROWSE,
            exportselection=False, font=(FONT, 10), yscrollcommand=scrollbar.set,
            bg=SURFACE, fg=INK, relief="flat", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=AMBER,
            selectbackground=AMBER, selectforeground=DARK_INK,
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

        actions = tk.Frame(window, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        button(actions, "打开", accept, True).pack(side="right")
        button(actions, "取消", window.destroy).pack(side="right", padx=(0, 6))
        options.bind("<Double-Button-1>", accept)
        window.bind("<Return>", accept)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.wait_visibility()
        window.grab_set()
        options.focus_set()
        window.wait_window()
        return result

    def _sync_viewer_mode(self):
        if self._playing:
            mode = "动画回放"
        elif self._reviewing:
            mode = "逐帧检查"
        elif self._region_selecting:
            mode = "拖动画面框选 · Esc 取消"
        else:
            mode = "取景预览"
        self.viewer_label.config(text=mode)
        self.source_label.config(text=self._source)
        self.resume_button.config(state="normal" if self._reviewing else "disabled")
        self.onion_button.config(state="disabled" if self._playing or self._reviewing else "normal")

    def _escape(self, event):
        if self._region_selecting:
            self._set_region_selecting(False)
            return "break"
        return self._shortcut(event, self.resume_button)

    def set_region_controls(self, *, available, region):
        if (available, region) == (self._region_available, self._region):
            return
        self._region_available, self._region = available, region
        if not available and self._region_selecting:
            self._set_region_selecting(False)
        self.region_select_button.config(state="normal" if available else "disabled")
        self.region_clear_button.config(state="normal" if available and region else "disabled")
        self._draw_region()

    def _set_region_selecting(self, active):
        if self._region_selecting == active:
            return
        self._region_selecting = active
        self._drag_start = self._drag_end = None
        self.preview.config(cursor="crosshair" if active else "")
        self.region_select_button.config(text="取消框选" if active else "框选区域")
        self._sync_viewer_mode()
        self._draw_region()
        self.controller.set_region_selecting(active)

    def _toggle_region_selection(self):
        if self._region_available:
            self._set_region_selecting(not self._region_selecting)
            if self._region_selecting:
                self.preview.focus_set()

    def _clear_region(self):
        self._set_region_selecting(False)
        self.controller.set_capture_region(None)

    def _region_point(self, event, *, clamp):
        bounds = self.preview.bbox(self._preview_item)
        if not bounds or self._photo is None:
            return None
        left, top, right, bottom = bounds
        x = (event.x - left) / (right - left)
        y = (event.y - top) / (bottom - top)
        if clamp:
            return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        if 0 <= x <= 1 and 0 <= y <= 1:
            return x, y
        return None

    def _start_region_drag(self, event):
        if self._region_selecting:
            self._drag_start = self._drag_end = self._region_point(event, clamp=False)
            self._draw_region()
            return "break"
        return None

    def _move_region_drag(self, event):
        if self._drag_start is not None:
            self._drag_end = self._region_point(event, clamp=True)
            self._draw_region()
            return "break"
        return None

    def _drag_region(self):
        if self._drag_start is None or self._drag_end is None:
            return None
        x0, y0 = self._drag_start
        x1, y1 = self._drag_end
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def _finish_region_drag(self, event):
        if self._drag_start is None:
            return None
        self._drag_end = self._region_point(event, clamp=True)
        region = self._drag_region()
        if region is not None and region[2] - region[0] >= 0.01 and region[3] - region[1] >= 0.01:
            self.controller.set_capture_region(region)
            self._set_region_selecting(False)
        else:
            self._drag_start = self._drag_end = None
            self._draw_region()
        return "break"

    def _draw_region(self):
        region = self._drag_region() or self._region
        bounds = self.preview.bbox(self._preview_item)
        if not self._region_available or self._photo is None or region is None or not bounds:
            self.preview.itemconfigure(self._region_outline, state="hidden")
            return
        left, top, right, bottom = bounds
        x0, y0, x1, y1 = region
        width, height = right - left, bottom - top
        self.preview.coords(
            self._region_outline, left + x0 * width, top + y0 * height,
            left + x1 * width, top + y1 * height,
        )
        self.preview.itemconfigure(
            self._region_outline, state="normal", outline=AMBER if self._region_selecting else GREEN,
        )

    def set_alignment_status(self, text):
        if self.alignment_label.cget("text") == text:
            return
        self.alignment_label.config(text=text)
        if text:
            self.alignment_label.grid()
        else:
            self.alignment_label.grid_remove()

    def set_source(self, label):
        self._source = label
        self._sync_viewer_mode()

    def set_playing(self, playing):
        self._playing = playing
        self.play_button.config(text="停止回放" if playing else "回放")
        self._sync_viewer_mode()

    def set_reviewing(self, reviewing):
        self._reviewing = reviewing
        self._sync_viewer_mode()

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
            fill=GREEN if captured else AMBER,
        )
        self._draw_capture_progress()

    def _draw_capture_progress(self, _event=None):
        if self._progress_value is not None:
            width = round(self._progress_bar.winfo_width() * self._progress_value)
            self._progress_bar.coords(self._progress_fill, 0, 0, width, 4)

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
        self.status_label.config(wraplength=max(180, w - 12))
        self.alignment_label.config(wraplength=max(180, w - 12))
        if self._image is None:
            self.preview.itemconfigure(self._placeholder, state="normal")
            self.preview.itemconfigure(self._preview_item, image="")
            self._photo = None
            self._draw_region()
            return
        if w <= 1 or h <= 1:
            return
        scale = min(w / self._image.width, h / self._image.height)
        size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        self._photo = ImageTk.PhotoImage(self._image.resize(size, Image.Resampling.BILINEAR), master=self.root)
        self.preview.itemconfigure(self._placeholder, state="hidden")
        self.preview.coords(self._preview_item, w // 2, h // 2)
        self.preview.itemconfigure(self._preview_item, image=self._photo)
        self._draw_region()

    def set_timeline(self, frames):
        self.frames = frames
        if self._position is not None and self._position >= len(frames):
            self._position = None
        if self._position is None:
            self._page_start = self._last_page_start()
        else:
            self._show_position_page()
        if len(frames) != len(self._timeline_edits):
            self._timeline_edits = ()
        self._sync_render_buttons()
        self._sync_timeline_controls()
        self._queue_strip()

    def set_timeline_edits(self, settings):
        edits = tuple(settings)
        if edits == self._timeline_edits:
            return
        self._timeline_edits = edits
        self._sync_render_buttons()
        self._queue_strip()

    def _sync_render_buttons(self):
        total = len(self.frames)
        slots = sum(hold for hold, hidden in self._timeline_edits if not hidden) if self._timeline_edits else total
        self.count_label.config(text=f"{total} 帧" if slots == total else f"{total} 帧 · 成片 {slots} 格")
        self.undo_button.config(state="normal" if total else "disabled")
        for action in (self.play_button, self.export_button, self.export_mp4_button):
            action.config(state="normal" if slots else "disabled")

    def set_frame_position(self, index):
        if index is not None and not 0 <= index < len(self.frames):
            index = None
        previous = self._position
        if previous == index:
            return
        self._position = index
        # A value typed but not applied belongs to the previous selection.
        hold = self._timeline_edits[index][0] if index is not None and index < len(self._timeline_edits) else 1
        self._hold.set(str(hold))
        self._sync_timeline_controls()
        if index is None:
            self._page_start = self._last_page_start()
            self._queue_strip()
        elif self._show_position_page():
            self._queue_strip()
        else:
            self._paint_tile(previous)
            self._paint_tile(index)

    def _sync_timeline_controls(self):
        current = self._position
        total = len(self.frames)
        self.frame_label.config(text=f"{current + 1 if current is not None else '—'} / {total or '—'}")
        self.previous_frame_button.config(
            state="normal" if total and (current is None or current > 0) else "disabled",
        )
        self.next_frame_button.config(
            state="normal" if total and (current is None or current < total - 1) else "disabled",
        )

    def _capacity(self):
        return max(1, (self.strip.winfo_width() - STRIP_PADDING * 2) // TILE_STEP)

    def _last_page_start(self):
        return max(0, len(self.frames) - self._capacity())

    def _show_position_page(self):
        if self._position is None:
            return False
        old_start = self._page_start
        capacity = self._capacity()
        if self._position < old_start:
            self._page_start = self._position
        elif self._position >= old_start + capacity:
            self._page_start = min(self._position, self._last_page_start())
        return old_start != self._page_start

    def _turn_page(self, direction):
        self._page_start = max(0, min(self._last_page_start(), self._page_start + direction * self._capacity()))
        self._queue_strip()

    def _resize_strip(self, _event=None):
        self._show_position_page()
        self._queue_strip()

    def _queue_strip(self):
        if self._strip_job is None:
            self._strip_job = self.root.after_idle(self._draw_strip)

    def _draw_strip(self):
        self._strip_job = None
        self.strip.delete("all")
        self._visible_tiles.clear()
        cached = self._thumbnail_images
        self._thumbnail_images = {}
        self._page_start = min(self._page_start, self._last_page_start())
        end = min(len(self.frames), self._page_start + self._capacity())
        self.prev_button.config(state="normal" if self._page_start > 0 else "disabled")
        self.next_button.config(state="normal" if end < len(self.frames) else "disabled")
        if not self.frames:
            self.strip.create_text(
                4, 31, text="拍下的画面会按顺序排在这里。", anchor="w",
                font=(FONT, 9), fill=MUTED,
            )
            return

        for slot, index in enumerate(range(self._page_start, end)):
            frame = self.frames[index]
            entry = cached.get(index)
            if entry is not None and entry[0] is frame:
                _, photo = entry
            else:
                shot = frame.copy()
                shot.thumbnail((TILE_WIDTH - 8, 45), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(shot, master=self.root)
            self._thumbnail_images[index] = (frame, photo)

            x = STRIP_PADDING + slot * TILE_STEP
            middle = x + TILE_WIDTH // 2
            tags = (f"frame_{index}",)
            tile = self.strip.create_rectangle(
                x, 2, x + TILE_WIDTH, 69, fill=VIEWPORT, outline=BORDER, tags=tags,
            )
            self.strip.create_image(middle, 27, image=photo, tags=tags)
            hold, hidden = self._timeline_edits[index] if index < len(self._timeline_edits) else (1, False)
            caption = f"{index + 1:02d}"
            if hidden:
                self.strip.create_rectangle(
                    x + 2, 4, x + TILE_WIDTH - 2, 51, fill=PANEL, stipple="gray50", width=0, tags=tags,
                )
                caption += " · 隐藏"
            elif hold > 1:
                caption += f" · ×{hold}"
            number = self.strip.create_text(
                middle, 59, text=caption, fill=MUTED, font=(FONT, 8), tags=tags,
            )
            self._visible_tiles[index] = (tile, number)
            self._paint_tile(index)

    def _paint_tile(self, index):
        items = self._visible_tiles.get(index)
        if items is None:
            return
        tile, number = items
        selected = index == self._position
        self.strip.itemconfigure(tile, outline=AMBER if selected else BORDER, width=2 if selected else 1)
        self.strip.itemconfigure(number, fill=AMBER if selected else MUTED)

    def _frame_at(self, event):
        for item in self.strip.find_overlapping(event.x, event.y, event.x, event.y):
            for tag in self.strip.gettags(item):
                if tag.startswith("frame_"):
                    index = int(tag[6:])
                    if index < len(self.frames):
                        return index
        return None

    def _select_thumbnail(self, event):
        index = self._frame_at(event)
        if index is not None:
            self.strip.focus_set()
            self.controller.seek_frame(index)

    def _inspect_thumbnail(self, event):
        index = self._frame_at(event)
        if index is None:
            return
        window = tk.Toplevel(self.root, bg=VIEWPORT)
        window.title(f"原始画面 · 第 {index + 1} 帧")
        window.transient(self.root)
        shot = self.frames[index].copy()
        shot.thumbnail(
            (min(850, self.root.winfo_screenwidth() - 60), min(600, self.root.winfo_screenheight() - 120)),
            Image.Resampling.LANCZOS,
        )
        photo = ImageTk.PhotoImage(shot, master=window)
        view = tk.Label(window, image=photo, bg=VIEWPORT)
        view.image = photo
        view.pack()
        window.bind("<Escape>", lambda _event: window.destroy())
