# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import random


def _fix_frozen_qt_paths() -> None:
    """PyInstaller：在导入 PySide6 之前把 Qt/shiboken 的 DLL 目录加入搜索路径。"""
    if not getattr(sys, "frozen", False):
        return
    root = getattr(sys, "_MEIPASS", None)
    if not root:
        root = os.path.dirname(sys.executable)
    root = os.path.normpath(root)

    extra: list[str] = [root]
    pside = os.path.join(root, "PySide6")
    if os.path.isdir(pside):
        extra.append(pside)
        for rel in (
            ("Qt6", "bin"),
            ("Qt", "bin"),
            ("lib", "bin"),
        ):
            d = os.path.join(pside, *rel)
            if os.path.isdir(d):
                extra.append(d)
    sh = os.path.join(root, "shiboken6")
    if os.path.isdir(sh):
        extra.append(sh)

    seen: set[str] = set()
    if hasattr(os, "add_dll_directory"):
        for d in extra:
            d = os.path.normpath(d)
            if d in seen or not os.path.isdir(d):
                continue
            seen.add(d)
            try:
                os.add_dll_directory(d)
            except OSError:
                pass

    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")

    for rel in (("PySide6", "plugins"), ("PySide6", "Qt6", "plugins")):
        qtp = os.path.join(root, *rel)
        if os.path.isdir(qtp):
            os.environ["QT_PLUGIN_PATH"] = qtp
            plat = os.path.join(qtp, "platforms")
            if os.path.isdir(plat):
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plat
            break


_fix_frozen_qt_paths()

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDoubleValidator,
    QIntValidator,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QMenu,
    QWidgetAction,
    QSlider,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QStackedWidget,
    QWidget,
    QFrame,
    QScrollArea,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from image_processing import (
    ALGORITHM_FORMULAS,
    ALGORITHM_LABELS,
    ALGORITHMS,
    GrayParams,
    apply_gray_transform,
    default_suffix,
    histogram_256,
)
from qt_image_bridge import pil_to_qimage, qimage_to_pil

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma"}
PLAY_MODES = ("seq", "shuffle", "loop", "pause")  # 顺序 / 随机 / 循环 / 播完暂停


def ms_to_hhmmss(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_sec = ms // 1000
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def ms_to_file_timestamp(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_ms = int(ms)
    total_sec = total_ms // 1000
    milli = total_ms % 1000
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}-{m:02d}-{s:02d}_{milli:03d}"


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def parse_mmss(text: str) -> int | None:
    """
    Parse 'hh:mm:ss' / 'mm:ss' / 'ss' to milliseconds.
    Returns None if invalid.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    if ":" in raw:
        parts = raw.split(":")
        if len(parts) not in (2, 3):
            return None
        parts = [p.strip() for p in parts]
        if any((not p.isdigit()) for p in parts):
            return None
        if len(parts) == 2:
            h = 0
            m = int(parts[0])
            s = int(parts[1])
        else:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2])
    else:
        if not raw.isdigit():
            return None
        h, m, s = 0, 0, int(raw)

    if h < 0 or m < 0 or s < 0 or s >= 60 or m >= 60:
        return None
    return (h * 3600 + m * 60 + s) * 1000


@dataclass(frozen=True)
class PlayerConfig:
    seek_step_ms: int = 5_000


class GotoTimeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("跳转到时间")
        self.setModal(True)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("输入 hh:mm:ss（如 1:02:03）/ mm:ss（如 01:23）/ ss（如 45）")
        self._input.returnPressed.connect(self.accept)

        hint = QLabel("提示：分钟/秒范围 0–59", self)
        hint.setStyleSheet("color: #666;")

        ok_btn = QPushButton("跳转", self)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("时间（hh:mm:ss / mm:ss）：", self))
        layout.addWidget(self._input)
        layout.addWidget(hint)
        layout.addLayout(btn_row)
        self.setLayout(layout)

        self.resize(380, 140)

    def value_ms(self) -> int | None:
        return parse_mmss(self._input.text())


class SliderScrubFilter(QObject):
    """
    Prevent accidental wheel changes on slider while hovering.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            return True
        return super().eventFilter(obj, event)


class ClickBlurFilter(QObject):
    """
    When user clicks on blank/non-input area, clear focus from inputs.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            w = QApplication.focusWidget()
            if w is not None and w is not obj:
                # If click target isn't an input-ish widget, blur current focus.
                name = obj.metaObject().className() if hasattr(obj, "metaObject") else ""
                if name not in {"QLineEdit", "QComboBox", "QAbstractSpinBox", "QTextEdit", "QPlainTextEdit"}:
                    w.clearFocus()
        return super().eventFilter(obj, event)


class HistogramWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original_hist: list[int] = [0] * 256
        self._processed_hist: list[int] = [0] * 256
        self._threshold: int | None = None
        self.setMinimumHeight(220)

    def set_histograms(
        self,
        original_hist: list[int],
        processed_hist: list[int],
        threshold: int | None = None,
    ) -> None:
        self._original_hist = list(original_hist[:256]) if original_hist else [0] * 256
        self._processed_hist = list(processed_hist[:256]) if processed_hist else [0] * 256
        self._threshold = threshold
        self.update()

    def clear(self) -> None:
        self.set_histograms([0] * 256, [0] * 256, None)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#111114"))

        margin = 12
        gap = 22
        label_h = 18
        available_h = max(20, self.height() - margin * 2 - gap - label_h * 2)
        graph_h = max(20, available_h // 2)
        graph_w = max(40, self.width() - margin * 2)
        top1 = margin + label_h
        top2 = top1 + graph_h + gap + label_h

        self._draw_one_histogram(
            painter,
            QRect(margin, top1, graph_w, graph_h),
            "原图灰度直方图",
            self._original_hist,
        )
        self._draw_one_histogram(
            painter,
            QRect(margin, top2, graph_w, graph_h),
            "处理后直方图",
            self._processed_hist,
        )
        painter.end()

    def _draw_one_histogram(
        self,
        painter: QPainter,
        rect: QRect,
        title: str,
        hist: list[int],
    ) -> None:
        title_rect = QRect(rect.left(), rect.top() - 18, rect.width(), 16)
        painter.setPen(QColor("#d8d8d8"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        painter.setPen(QColor("#303036"))
        painter.drawRect(rect)
        max_value = max(hist) if hist else 0
        if max_value <= 0:
            painter.setPen(QColor("#777"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "暂无直方图")
            return

        painter.setPen(QColor("#64b5f6"))
        for x in range(rect.width()):
            bin_index = min(255, int(x * 256 / max(1, rect.width())))
            value = hist[bin_index]
            bar_h = int(value / max_value * max(1, rect.height() - 2))
            painter.drawLine(
                rect.left() + x,
                rect.bottom() - 1,
                rect.left() + x,
                rect.bottom() - 1 - bar_h,
            )

        if self._threshold is not None:
            tx = rect.left() + int(clamp(self._threshold, 0, 255) / 255 * rect.width())
            painter.setPen(QPen(QColor("#ffb74d"), 2))
            painter.drawLine(tx, rect.top(), tx, rect.bottom())


class PlayerWindow(QMainWindow):
    def __init__(self, config: PlayerConfig | None = None) -> None:
        super().__init__()
        self._cfg = config or PlayerConfig()

        self.setWindowTitle("播放器")
        self.setMinimumSize(980, 620)
        self.setAcceptDrops(True)
        # Initialize mode early because event filters may fire during widget setup.
        self._mode: str = "media"  # "media" | "image"

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        # Bind to a concrete output device to avoid WASAPI edge cases.
        self._audio.setDevice(QMediaDevices.defaultAudioOutput())
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)
        self._audio.setMuted(False)

        self._video = QVideoWidget(self)
        self._player.setVideoOutput(self._video)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._last_video_frame: QImage | None = None
        try:
            self._video.videoSink().videoFrameChanged.connect(self._on_video_frame_changed)
        except AttributeError:
            self._last_video_frame = None

        self._image = QLabel(self)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setText("拖拽文件到窗口，或按 O 打开")
        self._image.setStyleSheet("color: #9a9a9a;")
        self._image.setMinimumSize(320, 180)
        self._image_original_preview = QLabel(self)
        self._image_original_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_original_preview.setText("原图")
        self._image_original_preview.setStyleSheet("color: #9a9a9a;")
        self._image_original_preview.setMinimumSize(260, 180)
        self._image_pixmap: QPixmap | None = None
        self._image_path: str | None = None
        self._current_path: str | None = None  # current opened file path (image/audio/video)
        self._image_original: QPixmap | None = None
        self._image_original_img: QImage | None = None
        self._image_edit_img: QImage | None = None
        self._gray_algorithm: str = "original"
        self._gray_params = GrayParams()
        self._image_dirty: bool = False
        self._img_edited_ever: bool = False
        self._img_saved_once: bool = False
        self._image_status_banner: str = ""
        self._undo_stack: list[QImage] = []
        self._undo_index: int = -1
        self._image.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._image.customContextMenuRequested.connect(self._on_image_context_menu)
        self._image.installEventFilter(self)

        # Draw tools (image mode)
        self._draw_enabled = True
        self._draw_tool = "brush"  # "brush" | "eraser"
        self._draw_color = QColor("#ffffff")
        self._draw_size_mm = 1.0
        self._drawing = False
        self._last_draw_pt: QPoint | None = None
        self._img_zoom: float = 1.0
        self._crop_mode: bool = False
        self._crop_dragging: bool = False
        self._crop_start: QPoint | None = None
        self._crop_end: QPoint | None = None
        self._img_pan_active: bool = False
        self._img_pan_last: QPoint | None = None
        self._img_pan_button: Qt.MouseButton | None = None

        self._draw_panel = QFrame(self)
        self._draw_panel.setObjectName("DrawPanel")
        self._draw_panel.setVisible(False)
        dp = QHBoxLayout(self._draw_panel)
        dp.setContentsMargins(10, 8, 10, 8)
        dp.setSpacing(8)

        self._tool_brush = QToolButton(self)
        self._tool_brush.setObjectName("ImageToolButton")
        self._tool_brush.setText("笔刷")
        self._tool_brush.setCheckable(True)
        self._tool_brush.setAutoExclusive(False)
        self._tool_brush.setChecked(True)
        self._tool_brush.clicked.connect(lambda: self._set_draw_tool("brush"))

        self._tool_eraser = QToolButton(self)
        self._tool_eraser.setObjectName("ImageToolButton")
        self._tool_eraser.setText("橡皮")
        self._tool_eraser.setCheckable(True)
        self._tool_eraser.setAutoExclusive(False)
        self._tool_eraser.clicked.connect(lambda: self._set_draw_tool("eraser"))

        self._color_btn = QToolButton(self)
        self._color_btn.setText("调色盘")
        self._color_btn.clicked.connect(self._pick_color)

        self._color_hex = QLineEdit(self)
        self._color_hex.setFixedWidth(86)
        self._color_hex.setText("ffffff")
        self._color_hex.setPlaceholderText("ffffff")
        self._color_hex.setToolTip("颜色：输入 RRGGBB（例如 ffffff），回车生效")
        self._color_hex.returnPressed.connect(self._apply_hex_color)
        self._color_hex.editingFinished.connect(self._apply_hex_color)

        self._size_mm = QDoubleSpinBox(self)
        self._size_mm.setRange(0.1, 50.0)
        self._size_mm.setSingleStep(0.1)
        self._size_mm.setDecimals(1)
        self._size_mm.setValue(1.0)
        self._size_mm.setFixedWidth(84)
        self._size_mm.setSuffix(" mm")
        self._size_mm.setToolTip("笔刷大小（单位 mm，步进 0.1mm）")
        self._size_mm.valueChanged.connect(self._on_size_mm_changed)

        dp.addWidget(self._tool_brush)
        dp.addWidget(self._tool_eraser)
        dp.addSpacing(10)
        dp.addWidget(self._color_btn)
        dp.addWidget(self._color_hex)
        dp.addSpacing(10)
        dp.addWidget(QLabel("大小：", self))
        dp.addWidget(self._size_mm)
        dp.addSpacing(14)

        self._zoom_out = QToolButton(self)
        self._zoom_out.setText("缩小")
        self._zoom_out.clicked.connect(lambda: self._set_zoom(self._img_zoom / 1.25))

        self._zoom_in = QToolButton(self)
        self._zoom_in.setText("放大")
        self._zoom_in.clicked.connect(lambda: self._set_zoom(self._img_zoom * 1.25))

        self._zoom_reset = QToolButton(self)
        self._zoom_reset.setText("还原")
        self._zoom_reset.clicked.connect(lambda: self._set_zoom(1.0))

        self._zoom_edit = QLineEdit(self)
        self._zoom_edit.setObjectName("ZoomEdit")
        self._zoom_edit.setFixedWidth(58)
        self._zoom_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_edit.setPlaceholderText("%")
        self._zoom_edit.setValidator(QIntValidator(10, 1000, self))
        self._zoom_edit.setToolTip("缩放百分比（10–1000），直接输入数字后回车，例如 150 表示 150%")
        self._zoom_edit.setText("100")
        self._zoom_edit.returnPressed.connect(self._apply_zoom_from_edit)
        self._zoom_edit.editingFinished.connect(self._apply_zoom_from_edit)

        self._crop_btn = QToolButton(self)
        self._crop_btn.setObjectName("ImageToolButton")
        self._crop_btn.setText("剪切")
        self._crop_btn.setCheckable(True)
        self._crop_btn.setAutoExclusive(False)
        self._crop_btn.toggled.connect(self._set_crop_mode)

        dp.addWidget(self._zoom_out)
        dp.addWidget(self._zoom_in)
        dp.addWidget(self._zoom_reset)
        dp.addWidget(self._zoom_edit)
        dp.addWidget(self._crop_btn)
        dp.addStretch(1)

        self._image_scroll = QScrollArea(self)
        self._image_scroll.setObjectName("ImageScrollArea")
        self._image_scroll.setWidgetResizable(False)
        self._image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._image_scroll.setWidget(self._image)
        self._image_scroll.setToolTip("放大后：用滚动条、鼠标中键拖动或 Alt+左键拖动平移画面")

        self._original_scroll = QScrollArea(self)
        self._original_scroll.setObjectName("ImageScrollArea")
        self._original_scroll.setWidgetResizable(False)
        self._original_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._original_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._original_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._original_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._original_scroll.setWidget(self._image_original_preview)

        original_pane = QFrame(self)
        original_pane.setObjectName("ImagePane")
        original_layout = QVBoxLayout(original_pane)
        original_layout.setContentsMargins(0, 0, 0, 0)
        original_layout.setSpacing(6)
        original_title = QLabel("原图", self)
        original_title.setObjectName("PaneTitle")
        original_layout.addWidget(original_title)
        original_layout.addWidget(self._original_scroll, 1)

        processed_pane = QFrame(self)
        processed_pane.setObjectName("ImagePane")
        processed_layout = QVBoxLayout(processed_pane)
        processed_layout.setContentsMargins(0, 0, 0, 0)
        processed_layout.setSpacing(6)
        processed_title = QLabel("处理图", self)
        processed_title.setObjectName("PaneTitle")
        processed_layout.addWidget(processed_title)
        processed_layout.addWidget(self._image_scroll, 1)

        self._experiment_panel = self._build_experiment_panel()
        self._image_compare_widget = QWidget(self)
        image_compare_layout = QHBoxLayout(self._image_compare_widget)
        image_compare_layout.setContentsMargins(0, 0, 0, 0)
        image_compare_layout.setSpacing(10)
        image_compare_layout.addWidget(original_pane, 1)
        image_compare_layout.addWidget(processed_pane, 1)
        image_compare_layout.addWidget(self._experiment_panel)

        self._viewer = QStackedWidget(self)
        self._viewer.addWidget(self._video)   # index 0
        self._viewer.addWidget(self._image_compare_widget)   # index 1

        self._focus_mode = False
        self._focus_btn = QToolButton(self)
        self._focus_btn.setObjectName("FocusModeButton")
        self._focus_btn.setText("认真观影模式")
        self._focus_btn.setCheckable(True)
        self._focus_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._focus_btn.toggled.connect(self.set_focus_mode)

        self._fullscreen_btn = QToolButton(self)
        self._fullscreen_btn.setObjectName("FullscreenButton")
        self._fullscreen_btn.setText("全屏")
        self._fullscreen_btn.setCheckable(True)
        self._fullscreen_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._fullscreen_btn.toggled.connect(self.set_fullscreen_mode)

        self._file_label = QLabel("未打开文件", self)
        self._file_label.setObjectName("FileLabel")
        self._file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._open_btn = QToolButton(self)
        self._open_btn.setText("打开")
        self._open_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._open_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self._open_btn.clicked.connect(self.open_file)

        self._capture_frame_btn = QToolButton(self)
        self._capture_frame_btn.setText("视频截图")
        self._capture_frame_btn.setToolTip("截取当前视频帧并进入灰度实验")
        self._capture_frame_btn.setEnabled(False)
        self._capture_frame_btn.clicked.connect(self.capture_video_frame)

        self._play_btn = QToolButton(self)
        self._play_btn.setObjectName("RoundPlayButton")
        self._play_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._play_btn.setIcon(self._make_round_icon(is_play=True))
        self._play_btn.setIconSize(QSize(28, 28))
        self._play_btn.setToolTip("播放/暂停（Space）")
        self._play_btn.clicked.connect(self.toggle_play)
        self._play_btn.setEnabled(False)

        self._prev_btn = QToolButton(self)
        self._prev_btn.setObjectName("NavButton")
        self._prev_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self._prev_btn.setIconSize(QSize(18, 18))
        self._prev_btn.setToolTip("上一个（同类型）")
        self._prev_btn.clicked.connect(lambda: self._step_same_type_in_folder(-1))
        self._prev_btn.setEnabled(False)

        self._next_btn = QToolButton(self)
        self._next_btn.setObjectName("NavButton")
        self._next_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self._next_btn.setIconSize(QSize(18, 18))
        self._next_btn.setToolTip("下一个（同类型）")
        self._next_btn.clicked.connect(lambda: self._step_same_type_in_folder(+1))
        self._next_btn.setEnabled(False)

        self._play_mode_btn = QToolButton(self)
        self._play_mode_btn.setObjectName("PlayModeButton")
        self._play_mode_btn.setText("顺序")
        self._play_mode_btn.setToolTip("播放模式：顺序 / 随机 / 循环 / 播完暂停（仅视频/音频）")
        self._play_mode_btn.clicked.connect(self._cycle_play_mode)
        self._play_mode_btn.setEnabled(False)

        nav_wrap = QWidget(self)
        nav_layout = QHBoxLayout(nav_wrap)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)
        nav_layout.addWidget(self._prev_btn)
        nav_layout.addWidget(self._play_btn)
        nav_layout.addWidget(self._next_btn)
        nav_layout.addWidget(self._play_mode_btn)
        self._nav_wrap = nav_wrap

        self._jump_input = QLineEdit(self)
        self._jump_input.setPlaceholderText("跳转 hh:mm:ss")
        self._jump_input.setFixedWidth(110)
        self._jump_input.returnPressed.connect(self.goto_time_inline)
        self._jump_btn = QToolButton(self)
        self._jump_btn.setText("跳转")
        self._jump_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self._jump_btn.clicked.connect(self.goto_time_inline)

        # Playback rate (compact editable + up/down buttons)
        self._rate_edit = QLineEdit(self)
        self._rate_edit.setFixedWidth(52)
        self._rate_edit.setText("1.0")
        self._rate_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rate_edit.setToolTip("倍速（0.25～8）。可直接输入，例如 1.25，回车生效。")
        self._rate_edit.setValidator(QDoubleValidator(0.25, 8.0, 2, self))
        self._rate_edit.returnPressed.connect(self._apply_rate_from_edit)
        self._rate_edit.editingFinished.connect(self._apply_rate_from_edit)

        self._rate_up = QToolButton(self)
        self._rate_up.setObjectName("RateStepButton")
        self._rate_up.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self._rate_up.setToolTip("+0.1x")
        self._rate_up.clicked.connect(lambda: self._step_rate(+0.1))

        self._rate_down = QToolButton(self)
        self._rate_down.setObjectName("RateStepButton")
        self._rate_down.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self._rate_down.setToolTip("-0.1x")
        self._rate_down.clicked.connect(lambda: self._step_rate(-0.1))

        self._rate_step_col = QWidget(self)
        rate_step_layout = QVBoxLayout(self._rate_step_col)
        rate_step_layout.setContentsMargins(0, 0, 0, 0)
        rate_step_layout.setSpacing(0)
        rate_step_layout.addWidget(self._rate_up)
        rate_step_layout.addWidget(self._rate_down)

        self._pos_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._pos_slider.setRange(0, 0)
        self._pos_slider.setSingleStep(1000)
        self._pos_slider.setPageStep(10_000)
        self._pos_slider.sliderPressed.connect(self._on_slider_pressed)
        self._pos_slider.sliderReleased.connect(self._on_slider_released)
        self._pos_slider.sliderMoved.connect(self._on_slider_moved)
        self._pos_slider.installEventFilter(SliderScrubFilter(self))

        self._click_blur = ClickBlurFilter(self)
        # Apply to the whole window so blank clicks blur inputs.
        self.installEventFilter(self._click_blur)

        self._time_label = QLabel("00:00 / 00:00", self)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._time_label.setMinimumWidth(140)

        self._vol_btn = QToolButton(self)
        self._vol_btn.setObjectName("VolumeButton")
        self._vol_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._vol_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self._vol_btn.setIconSize(QSize(18, 18))
        self._vol_btn.setToolTip("音量")

        self._vol_slider = QSlider(Qt.Orientation.Vertical, self)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(int(self._audio.volume() * 100))
        self._vol_slider.valueChanged.connect(lambda v: self._audio.setVolume(v / 100.0))
        self._vol_slider.setFixedHeight(120)

        self._vol_menu = QMenu(self)
        self._vol_menu.setObjectName("VolumeMenu")
        act = QWidgetAction(self._vol_menu)
        vol_wrap = QWidget(self._vol_menu)
        vol_layout = QVBoxLayout(vol_wrap)
        vol_layout.setContentsMargins(10, 10, 10, 10)
        vol_layout.addWidget(self._vol_slider, 1, Qt.AlignmentFlag.AlignHCenter)
        act.setDefaultWidget(vol_wrap)
        self._vol_menu.addAction(act)
        self._vol_btn.setMenu(self._vol_menu)
        self._vol_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self._audio_device = QComboBox(self)
        self._audio_device.setFixedWidth(220)
        self._audio_device.currentIndexChanged.connect(self._on_audio_device_changed)
        self._refresh_audio_devices()

        topbar_widget = QWidget(self)
        topbar = QHBoxLayout(topbar_widget)
        topbar.setContentsMargins(12, 10, 12, 0)
        topbar.setSpacing(10)
        topbar.addWidget(self._focus_btn)
        topbar.addWidget(self._fullscreen_btn)
        topbar.addSpacing(10)
        topbar.addWidget(self._file_label, 1)
        self._image_status_label = QLabel("", self)
        self._image_status_label.setObjectName("ImageStatusLabel")
        self._image_status_label.setMinimumWidth(160)
        self._image_status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._image_status_label.setVisible(False)
        topbar.addWidget(self._image_status_label)
        topbar.addWidget(QLabel("输出：", self))
        topbar.addWidget(self._audio_device)
        topbar.addWidget(self._capture_frame_btn)
        topbar.addWidget(self._open_btn)

        # Row 1: progress (separate line)
        progress_widget = QWidget(self)
        progress_row = QHBoxLayout(progress_widget)
        progress_row.setContentsMargins(12, 6, 12, 0)
        progress_row.setSpacing(10)
        progress_row.addWidget(self._pos_slider, 1)
        progress_row.addWidget(self._time_label)

        # Row 2: controls (left group / centered play / right group)
        left_group = QWidget(self)
        left_layout = QHBoxLayout(left_group)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(QLabel("跳转：", self))
        left_layout.addWidget(self._jump_input)
        left_layout.addWidget(self._jump_btn)
        left_layout.addSpacing(12)
        left_layout.addWidget(QLabel("倍速：", self))
        left_layout.addWidget(self._rate_edit)
        left_layout.addWidget(self._rate_step_col)

        controls_widget = QWidget(self)
        # Use a 3-column grid so play button is always centered
        controls = QGridLayout(controls_widget)
        controls.setContentsMargins(12, 8, 12, 12)
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(0)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(1, 0)
        controls.setColumnStretch(2, 1)
        controls.addWidget(left_group, 0, 0, Qt.AlignmentFlag.AlignLeft)
        controls.addWidget(self._nav_wrap, 0, 1, Qt.AlignmentFlag.AlignHCenter)
        controls.addWidget(self._vol_btn, 0, 2, Qt.AlignmentFlag.AlignRight)

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(topbar_widget)

        card = QFrame(self)
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(10)
        card_layout.addWidget(self._draw_panel)
        card_layout.addWidget(self._viewer, 1)
        layout.addWidget(card, 1)

        layout.addWidget(progress_widget)
        layout.addWidget(controls_widget)
        self.setCentralWidget(root)

        self._topbar_widget = topbar_widget
        self._progress_widget = progress_widget
        self._controls_widget = controls_widget
        self._card = card

        self._is_scrubbing = False
        self._last_user_seek_ms: int | None = None
        self._duration_ms = 0
        self._play_mode: str = "seq"
        # (already initialized at the top of __init__)

        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._sync_play_icon)
        self._player.errorOccurred.connect(self._on_error)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(200)
        self._ui_timer.timeout.connect(self._refresh_time_label)
        self._ui_timer.start()

        self._init_actions()
        self._apply_style()

        # QMediaDevices signals are emitted from an instance (PySide6 binding detail).
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._refresh_audio_devices)

    def _build_experiment_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("ExperimentPanel")
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("灰度变换实验", self)
        title.setObjectName("ExperimentTitle")
        layout.addWidget(title)

        self._algorithm_combo = QComboBox(self)
        for algorithm in ALGORITHMS:
            self._algorithm_combo.addItem(ALGORITHM_LABELS.get(algorithm, algorithm), algorithm)
        self._algorithm_combo.currentIndexChanged.connect(self._on_gray_algorithm_changed)
        layout.addWidget(self._algorithm_combo)

        self._experiment_scroll = QScrollArea(self)
        self._experiment_scroll.setObjectName("ExperimentScrollArea")
        self._experiment_scroll.setWidgetResizable(True)
        self._experiment_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._experiment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._experiment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_content = QWidget(self._experiment_scroll)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        self._brightness_slider, self._brightness_value = self._add_slider_row(
            scroll_layout, "亮度 b", -100, 100, 0
        )
        self._contrast_a_slider, self._contrast_a_value = self._add_slider_row(
            scroll_layout, "对比度 a", 10, 300, 100, scale=100.0
        )
        self._contrast_b_slider, self._contrast_b_value = self._add_slider_row(
            scroll_layout, "偏移 b", -100, 100, 0
        )
        self._threshold_slider, self._threshold_value = self._add_slider_row(
            scroll_layout, "阈值 T", 0, 255, 128
        )
        self._gamma_slider, self._gamma_value = self._add_slider_row(
            scroll_layout, "Gamma", 10, 500, 100, scale=100.0
        )

        self._formula_label = QLabel("", self)
        self._formula_label.setObjectName("ExperimentInfo")
        self._formula_label.setWordWrap(True)
        scroll_layout.addWidget(self._formula_label)

        self._result_info_label = QLabel("", self)
        self._result_info_label.setObjectName("ExperimentInfo")
        self._result_info_label.setWordWrap(True)
        scroll_layout.addWidget(self._result_info_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self._restore_original_btn = QToolButton(self)
        self._restore_original_btn.setText("还原原图")
        self._restore_original_btn.clicked.connect(self.restore_original_image)
        self._save_processed_btn = QToolButton(self)
        self._save_processed_btn.setText("保存处理结果")
        self._save_processed_btn.clicked.connect(self._save_processed_image)
        button_row.addWidget(self._restore_original_btn)
        button_row.addWidget(self._save_processed_btn)
        scroll_layout.addLayout(button_row)

        self._histogram = HistogramWidget(scroll_content)
        scroll_layout.addWidget(self._histogram)
        scroll_layout.addStretch(1)
        self._experiment_scroll.setWidget(scroll_content)
        layout.addWidget(self._experiment_scroll, 1)
        self._update_gray_control_labels()
        self._update_gray_panel_text()
        self._update_gray_control_enabled()
        return panel

    def _add_slider_row(
        self,
        parent_layout: QVBoxLayout,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        scale: float = 1.0,
    ) -> tuple[QSlider, QLabel]:
        row = QWidget(self)
        row.setObjectName("ParamRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        name = QLabel(title, self)
        name.setMinimumWidth(70)
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setProperty("value_scale", scale)
        value_label = QLabel("", self)
        value_label.setMinimumWidth(42)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(self._on_gray_control_changed)
        row_layout.addWidget(name)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        parent_layout.addWidget(row)
        return slider, value_label

    def _gray_params_from_controls(self) -> GrayParams:
        return GrayParams(
            brightness=int(self._brightness_slider.value()),
            contrast_a=float(self._contrast_a_slider.value()) / 100.0,
            contrast_b=int(self._contrast_b_slider.value()),
            threshold=int(self._threshold_slider.value()),
            gamma=float(self._gamma_slider.value()) / 100.0,
        )

    def _on_gray_algorithm_changed(self, _index: int | None = None) -> None:
        self._gray_algorithm = self._algorithm_combo.currentData() or "original"
        self._update_gray_control_enabled()
        self._apply_gray_settings()
        if hasattr(self, "_experiment_scroll"):
            self._experiment_scroll.verticalScrollBar().setValue(0)

    def _on_gray_control_changed(self, _value: int | None = None) -> None:
        self._gray_params = self._gray_params_from_controls()
        self._update_gray_control_labels()
        self._apply_gray_settings()

    def _update_gray_control_labels(self) -> None:
        if not hasattr(self, "_brightness_slider"):
            return
        self._brightness_value.setText(str(self._brightness_slider.value()))
        self._contrast_a_value.setText(f"{self._contrast_a_slider.value() / 100.0:.2f}")
        self._contrast_b_value.setText(str(self._contrast_b_slider.value()))
        self._threshold_value.setText(str(self._threshold_slider.value()))
        self._gamma_value.setText(f"{self._gamma_slider.value() / 100.0:.2f}")

    def _update_gray_control_enabled(self) -> None:
        if not hasattr(self, "_brightness_slider"):
            return
        algorithm = self._gray_algorithm
        self._brightness_slider.setEnabled(algorithm == "brightness")
        self._contrast_a_slider.setEnabled(algorithm == "contrast")
        self._contrast_b_slider.setEnabled(algorithm == "contrast")
        self._threshold_slider.setEnabled(algorithm == "threshold")
        self._gamma_slider.setEnabled(algorithm == "gamma")

    def _update_gray_panel_text(self) -> None:
        if not hasattr(self, "_formula_label"):
            return
        algorithm = self._gray_algorithm
        params = self._gray_params
        label = ALGORITHM_LABELS.get(algorithm, algorithm)
        formula = ALGORITHM_FORMULAS.get(algorithm, "")
        self._formula_label.setText(f"{label}\n{formula}")
        if self._image_edit_img and not self._image_edit_img.isNull():
            size_text = f"{self._image_edit_img.width()} x {self._image_edit_img.height()}"
        else:
            size_text = "未打开图片"
        param_text = (
            f"亮度 b={params.brightness}, 对比度 a={params.contrast_a:.2f}, "
            f"偏移 b={params.contrast_b}, 阈值 T={params.threshold}, Gamma={params.gamma:.2f}"
        )
        self._result_info_label.setText(f"尺寸：{size_text}\n参数：{param_text}")

    def _reset_gray_controls(self) -> None:
        self._gray_algorithm = "original"
        self._gray_params = GrayParams()
        widgets = (
            self._algorithm_combo,
            self._brightness_slider,
            self._contrast_a_slider,
            self._contrast_b_slider,
            self._threshold_slider,
            self._gamma_slider,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self._algorithm_combo.setCurrentIndex(0)
        self._brightness_slider.setValue(self._gray_params.brightness)
        self._contrast_a_slider.setValue(int(self._gray_params.contrast_a * 100))
        self._contrast_b_slider.setValue(self._gray_params.contrast_b)
        self._threshold_slider.setValue(self._gray_params.threshold)
        self._gamma_slider.setValue(int(self._gray_params.gamma * 100))
        for widget in widgets:
            widget.blockSignals(False)
        self._update_gray_control_labels()
        self._update_gray_control_enabled()
        self._update_gray_panel_text()

    def _apply_gray_settings(self) -> None:
        if not self._image_original_img or self._image_original_img.isNull():
            self._update_gray_panel_text()
            return
        try:
            source = qimage_to_pil(self._image_original_img)
            if self._gray_algorithm == "original":
                processed = source.copy()
            else:
                processed = apply_gray_transform(source, self._gray_algorithm, self._gray_params)
            self._image_edit_img = pil_to_qimage(processed).convertToFormat(QImage.Format.Format_ARGB32)
        except Exception as exc:
            QMessageBox.warning(self, "图像处理失败", str(exc))
            return

        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._image_dirty = self._gray_algorithm != "original"
        self._img_edited_ever = self._gray_algorithm != "original"
        self._img_saved_once = False
        self._reset_undo_stack()
        self._render_image()
        self._refresh_image_status_ui()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()

    def _refresh_histogram_ui(self) -> None:
        if not hasattr(self, "_histogram"):
            return
        if (
            not self._image_original_img
            or self._image_original_img.isNull()
            or not self._image_edit_img
            or self._image_edit_img.isNull()
        ):
            self._histogram.clear()
            return
        try:
            original_hist = histogram_256(qimage_to_pil(self._image_original_img))
            processed_hist = histogram_256(qimage_to_pil(self._image_edit_img))
        except Exception:
            self._histogram.clear()
            return
        threshold = self._gray_params.threshold if self._gray_algorithm == "threshold" else None
        self._histogram.set_histograms(original_hist, processed_hist, threshold)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #0f0f10; }
            QLabel { color: #eaeaea; }
            QToolButton#FocusModeButton {
              padding: 6px 10px;
              border-radius: 10px;
              background: #151516;
              border: 1px solid #2a2a2a;
              color: #eaeaea;
              font-size: 14px;
              font-weight: 700;
            }
            QToolButton#FocusModeButton:checked {
              background: #23324a;
              border: 1px solid #2a3b55;
            }
            QToolButton#FullscreenButton {
              padding: 6px 10px;
              border-radius: 10px;
              background: #151516;
              border: 1px solid #2a2a2a;
              color: #eaeaea;
              font-size: 14px;
              font-weight: 700;
            }
            QToolButton#FullscreenButton:checked {
              background: #23324a;
              border: 1px solid #2a3b55;
            }
            QLabel#FileLabel { color: #bdbdbd; }
            QFrame#Card { background: #111114; border: 1px solid #222; border-radius: 14px; }
            QFrame#DrawPanel { background: #141416; border: 1px solid #222; border-radius: 12px; }
            QFrame#ImagePane { background: transparent; border: none; }
            QLabel#PaneTitle {
              color: #d8d8d8;
              font-weight: 700;
              padding: 0 2px;
            }
            QFrame#ExperimentPanel {
              background: #141416;
              border: 1px solid #24242a;
              border-radius: 12px;
            }
            QLabel#ExperimentTitle {
              color: #f0f0f0;
              font-size: 15px;
              font-weight: 800;
            }
            QLabel#ExperimentInfo {
              color: #cfcfcf;
              line-height: 140%;
              padding: 6px 0;
            }
            QScrollArea#ImageScrollArea { background: transparent; border: none; }
            QScrollArea#ExperimentScrollArea {
              background: transparent;
              border: none;
            }
            QScrollArea#ExperimentScrollArea > QWidget > QWidget {
              background: transparent;
            }
            QScrollArea#ExperimentScrollArea QScrollBar:vertical {
              width: 8px;
              background: transparent;
              margin: 0;
            }
            QScrollArea#ExperimentScrollArea QScrollBar::handle:vertical {
              background: #33343a;
              border-radius: 4px;
              min-height: 28px;
            }
            QScrollArea#ExperimentScrollArea QScrollBar::handle:vertical:hover {
              background: #454750;
            }
            QScrollArea#ExperimentScrollArea QScrollBar::add-line:vertical,
            QScrollArea#ExperimentScrollArea QScrollBar::sub-line:vertical {
              height: 0;
              border: none;
              background: transparent;
            }
            QScrollArea#ExperimentScrollArea QScrollBar::add-page:vertical,
            QScrollArea#ExperimentScrollArea QScrollBar::sub-page:vertical {
              background: transparent;
            }
            QToolButton#ImageToolButton:checked {
              background: #23324a;
              border: 1px solid #4b9cff;
              color: #eaeaea;
            }
            QLineEdit#ZoomEdit {
              padding: 6px 8px;
              border-radius: 8px;
              border: 1px solid #333;
              background: #141414;
              color: #eaeaea;
            }
            QToolButton {
              padding: 6px 10px;
              border-radius: 8px;
              background: #1c1c1c;
              color: #eaeaea;
            }
            QToolButton:hover { background: #242424; }
            QToolButton:disabled { color: #777; background: #161616; }
            QToolButton#RoundPlayButton {
              padding: 6px;
              border-radius: 20px;
              background: #1f2a3a;
              border: 1px solid #2a3b55;
              min-width: 40px;
              min-height: 40px;
            }
            QToolButton#RoundPlayButton:hover { background: #24344a; }
            QToolButton#NavButton {
              padding: 6px;
              border-radius: 12px;
              background: #1c1c1c;
              border: 1px solid #2a2a2a;
              min-width: 34px;
              min-height: 34px;
            }
            QToolButton#NavButton:hover { background: #242424; }
            QToolButton#PlayModeButton {
              padding: 6px 10px;
              border-radius: 12px;
              background: #1c1c1c;
              border: 1px solid #2a2a2a;
              min-height: 34px;
              color: #eaeaea;
              font-weight: 700;
            }
            QToolButton#PlayModeButton:hover { background: #242424; }
            QToolButton#VolumeButton {
              padding: 6px;
              border-radius: 10px;
              background: #1c1c1c;
              border: 1px solid #2a2a2a;
              min-width: 34px;
              min-height: 34px;
            }
            QToolButton#VolumeButton:hover { background: #242424; }
            QToolButton#RateStepButton {
              padding: 0px;
              border-radius: 6px;
              background: #1c1c1c;
              border: 1px solid #2a2a2a;
              min-width: 22px;
              min-height: 16px;
            }
            QToolButton#RateStepButton:hover { background: #242424; }
            QMenu#VolumeMenu { background: #141414; border: 1px solid #333; border-radius: 10px; }
            QSlider::groove:horizontal { height: 6px; background: #2a2a2a; border-radius: 3px; }
            QSlider::handle:horizontal {
              width: 14px; height: 14px;
              margin: -5px 0;
              border-radius: 7px;
              background: #eaeaea;
            }
            QSlider::sub-page:horizontal { background: #4b9cff; border-radius: 3px; }
            QSlider::groove:vertical { width: 6px; background: #2a2a2a; border-radius: 3px; }
            QSlider::handle:vertical {
              width: 14px; height: 14px;
              margin: 0 -5px;
              border-radius: 7px;
              background: #eaeaea;
            }
            QSlider::sub-page:vertical { background: #4b9cff; border-radius: 3px; }
            QLineEdit {
              padding: 8px 10px;
              border-radius: 8px;
              border: 1px solid #333;
              background: #141414;
              color: #eaeaea;
            }
            QComboBox {
              padding: 7px 10px;
              border-radius: 8px;
              border: 1px solid #333;
              background: #141414;
              color: #eaeaea;
            }
            QComboBox::drop-down { border: none; width: 22px; }
            QDoubleSpinBox {
              padding: 7px 10px;
              border-radius: 8px;
              border: 1px solid #333;
              background: #141414;
              color: #eaeaea;
            }
            QPushButton {
              padding: 7px 12px;
              border-radius: 8px;
              background: #1f1f1f;
              color: #eaeaea;
              border: 1px solid #333;
            }
            QPushButton:hover { background: #272727; }
            """
        )

    def _make_round_icon(self, is_play: bool) -> QIcon:
        size = 40
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # circle outline (subtle)
        pen = QPen(QColor(235, 235, 235, 30))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(1, 1, size - 2, size - 2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(234, 234, 234))

        if is_play:
            # triangle (PySide6 requires QPoint / QPolygon, not list of tuples)
            x0 = int(size * 0.42)
            y0 = int(size * 0.30)
            x1 = int(size * 0.42)
            y1 = int(size * 0.70)
            x2 = int(size * 0.72)
            y2 = int(size * 0.50)
            painter.drawPolygon(
                [QPoint(x0, y0), QPoint(x1, y1), QPoint(x2, y2)]
            )
        else:
            # pause bars
            w = int(size * 0.12)
            h = int(size * 0.40)
            y = int(size * 0.30)
            x_left = int(size * 0.40)
            x_right = int(size * 0.55)
            painter.drawRoundedRect(x_left, y, w, h, 2, 2)
            painter.drawRoundedRect(x_right, y, w, h, 2, 2)

        painter.end()
        return QIcon(pm)

    def _init_actions(self) -> None:
        open_action = QAction("打开文件", self)
        open_action.setShortcut(QKeySequence("O"))
        open_action.triggered.connect(self.open_file)
        self.addAction(open_action)

        toggle_action = QAction("播放/暂停", self)
        toggle_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        toggle_action.triggered.connect(self.toggle_play)
        self.addAction(toggle_action)

        seek_back = QAction("后退", self)
        seek_back.setShortcut(QKeySequence(Qt.Key.Key_Left))
        seek_back.triggered.connect(lambda: self.seek_relative(-self._cfg.seek_step_ms))
        self.addAction(seek_back)

        seek_fwd = QAction("前进", self)
        seek_fwd.setShortcut(QKeySequence(Qt.Key.Key_Right))
        seek_fwd.triggered.connect(lambda: self.seek_relative(self._cfg.seek_step_ms))
        self.addAction(seek_fwd)

        goto_action = QAction("跳转到时间", self)
        goto_action.setShortcut(QKeySequence("Ctrl+G"))
        goto_action.triggered.connect(self.goto_time)
        self.addAction(goto_action)

        exit_focus = QAction("退出认真观影", self)
        exit_focus.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        exit_focus.triggered.connect(self.exit_immersive_modes)
        self.addAction(exit_focus)

        fullscreen_action = QAction("全屏", self)
        fullscreen_action.setShortcut(QKeySequence("F"))
        fullscreen_action.triggered.connect(lambda: self._fullscreen_btn.setChecked(not self._fullscreen_btn.isChecked()))
        self.addAction(fullscreen_action)

        undo_action = QAction("撤回", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self.image_undo)
        self.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        redo_action.triggered.connect(self.image_redo)
        self.addAction(redo_action)

        zoom_in = QAction("放大(图片)", self)
        zoom_in.setShortcut(QKeySequence("Ctrl++"))
        zoom_in.triggered.connect(lambda: self._set_zoom(self._img_zoom * 1.25))
        self.addAction(zoom_in)

        zoom_out = QAction("缩小(图片)", self)
        zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out.triggered.connect(lambda: self._set_zoom(self._img_zoom / 1.25))
        self.addAction(zoom_out)

        zoom_reset = QAction("还原缩放(图片)", self)
        zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset.triggered.connect(lambda: self._set_zoom(1.0))
        self.addAction(zoom_reset)

        crop_toggle = QAction("剪切(图片)", self)
        crop_toggle.setShortcut(QKeySequence("C"))
        crop_toggle.triggered.connect(lambda: self._crop_btn.setChecked(not self._crop_btn.isChecked()))
        self.addAction(crop_toggle)

    def set_focus_mode(self, enabled: bool) -> None:
        self._focus_mode = bool(enabled)
        self._topbar_widget.setVisible(not enabled)
        self._progress_widget.setVisible(not enabled)
        self._controls_widget.setVisible(not enabled)
        # keep video only; remove card chrome for immersion
        if enabled:
            self._card.setStyleSheet("background: transparent; border: none;")
        else:
            self._card.setStyleSheet("")

    def set_fullscreen_mode(self, enabled: bool) -> None:
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def exit_immersive_modes(self) -> None:
        if self._fullscreen_btn.isChecked():
            self._fullscreen_btn.setChecked(False)
        if self._focus_btn.isChecked():
            self._focus_btn.setChecked(False)
        if getattr(self, "_crop_mode", False):
            self._set_crop_mode(False)
            self._crop_btn.setChecked(False)

    def _refresh_audio_devices(self) -> None:
        current = self._audio.device()
        self._audio_device.blockSignals(True)
        self._audio_device.clear()
        devices = QMediaDevices.audioOutputs()
        selected_index = 0
        for idx, d in enumerate(devices):
            self._audio_device.addItem(d.description(), d)
            if d == current:
                selected_index = idx
        self._audio_device.setCurrentIndex(selected_index if devices else -1)
        self._audio_device.blockSignals(False)

    def _on_audio_device_changed(self, index: int) -> None:
        if index < 0:
            return
        d = self._audio_device.itemData(index)
        if d is None:
            return
        self._audio.setDevice(d)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        urls = event.mimeData().urls()
        if not urls:
            return
        local = urls[0].toLocalFile()
        if local:
            self.open_path(local)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        if self._mode == "image":
            self._render_original_preview()
            self._render_image()

    def _on_error(self, error, error_string: str) -> None:
        # error is QMediaPlayer.Error
        if error_string:
            QMessageBox.warning(self, "播放错误", error_string)

    def _sync_play_icon(self) -> None:
        st = self._player.playbackState()
        if st == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setIcon(self._make_round_icon(is_play=False))
        else:
            self._play_btn.setIcon(self._make_round_icon(is_play=True))

    def open_file(self) -> None:
        if not self._maybe_prompt_save_image("打开新文件"):
            return
        start_dir = os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择媒体文件",
            start_dir,
            "常见媒体/图片 (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mp3 *.wav *.flac *.aac *.m4a *.ogg *.opus *.wma *.jpg *.jpeg *.png *.webp *.bmp *.gif);;视频 (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv);;音频 (*.mp3 *.wav *.flac *.aac *.m4a *.ogg *.opus *.wma);;图片 (*.jpg *.jpeg *.png *.webp *.bmp *.gif);;所有文件 (*.*)",
        )
        if not file_path:
            return
        self.open_path(file_path)

    def open_path(self, file_path: str) -> None:
        if not file_path:
            return
        if not self._maybe_prompt_save_image("切换文件"):
            return

        self._current_path = file_path
        ext = os.path.splitext(file_path)[1].lower()
        is_image = ext in IMAGE_EXTS
        if is_image:
            self._open_image(file_path)
            return

        # audio / video
        self._open_media(file_path)

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "image":
            self._viewer.setCurrentIndex(1)
            self._play_btn.setEnabled(False)
            self._pos_slider.setEnabled(False)
            self._pos_slider.setRange(0, 0)
            self._time_label.setText("图片")
        else:
            self._viewer.setCurrentIndex(0)
            self._play_btn.setEnabled(True)
            self._pos_slider.setEnabled(True)
        is_video = bool(
            self._current_path
            and os.path.splitext(self._current_path)[1].lower() in VIDEO_EXTS
            and mode == "media"
        )
        self._capture_frame_btn.setEnabled(is_video)
        self._refresh_nav_enabled()
        self._refresh_image_status_ui()

    def _open_image(self, file_path: str) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        pm = QPixmap(file_path)
        if pm.isNull():
            QMessageBox.information(self, "无法打开图片", "图片格式不受支持或文件已损坏。")
            return
        self._image_path = file_path
        self._current_path = file_path
        self._image_original = QPixmap(pm)
        self._image_original_img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self._image_edit_img = QImage(self._image_original_img)
        self._reset_gray_controls()
        self._image_dirty = False
        self._img_edited_ever = False
        self._img_saved_once = False
        self._image_status_banner = ""
        self._reset_undo_stack()
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._set_mode("image")
        self._draw_panel.setVisible(True)
        self._set_zoom(1.0)
        self._set_crop_mode(False)
        self._crop_btn.setChecked(False)
        self._render_original_preview()
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        base = os.path.basename(file_path)
        self._file_label.setText(base)
        self.setWindowTitle(f"播放器 - {base}")

    def _render_image(self) -> None:
        if not self._image_pixmap or self._image_pixmap.isNull():
            return
        # Fit inside viewer area; avoid upscaling too much for tiny images.
        target = self._image_scroll.viewport().size()
        if target.width() <= 0 or target.height() <= 0:
            return
        img = self._image_pixmap
        img_w = img.width()
        img_h = img.height()
        if img_w <= 0 or img_h <= 0:
            return
        base_scale = min(target.width() / img_w, target.height() / img_h)
        scale = max(0.05, min(20.0, base_scale * float(self._img_zoom)))
        disp_w = max(1, int(img_w * scale))
        disp_h = max(1, int(img_h * scale))
        scaled = img.scaled(disp_w, disp_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # draw crop overlay if needed (display coords = image coords * pixel scale)
        sx = scaled.width() / float(img_w)
        sy = scaled.height() / float(img_h)
        if self._crop_mode and self._crop_start and self._crop_end:
            overlay = QPixmap(scaled)
            p = QPainter(overlay)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(75, 156, 255, 220))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(QColor(75, 156, 255, 40))
            a = self._crop_start
            b = self._crop_end
            x1, y1 = min(a.x(), b.x()), min(a.y(), b.y())
            x2, y2 = max(a.x(), b.x()), max(a.y(), b.y())
            rr = QRect(
                int(x1 * sx),
                int(y1 * sy),
                max(1, int((x2 - x1) * sx)),
                max(1, int((y2 - y1) * sy)),
            )
            p.drawRect(rr)
            p.end()
            scaled = overlay

        self._image.setPixmap(scaled)
        self._image.setFixedSize(scaled.size())

    def _render_original_preview(self) -> None:
        if not self._image_original or self._image_original.isNull():
            return
        target = self._original_scroll.viewport().size()
        if target.width() <= 0 or target.height() <= 0:
            return
        img = self._image_original
        img_w = img.width()
        img_h = img.height()
        if img_w <= 0 or img_h <= 0:
            return
        scale = min(target.width() / img_w, target.height() / img_h)
        scale = max(0.05, min(1.0, scale))
        disp_w = max(1, int(img_w * scale))
        disp_h = max(1, int(img_h * scale))
        scaled = img.scaled(disp_w, disp_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._image_original_preview.setPixmap(scaled)
        self._image_original_preview.setFixedSize(scaled.size())

    def _open_media(self, file_path: str) -> None:
        self._last_video_frame = None
        self._image_pixmap = None
        self._image.clear()
        self._image_original_preview.clear()
        self._image_original_preview.setText("原图")
        self._image_path = None
        self._current_path = file_path
        self._image_original = None
        self._image_original_img = None
        self._image_edit_img = None
        self._image_dirty = False
        self._img_edited_ever = False
        self._img_saved_once = False
        self._image_status_banner = ""
        self._undo_stack = []
        self._undo_index = -1
        if hasattr(self, "_histogram"):
            self._histogram.clear()
        self._update_gray_panel_text()
        self._set_mode("media")
        self._draw_panel.setVisible(False)
        self._set_crop_mode(False)

        url = QUrl.fromLocalFile(file_path)
        self._player.setSource(url)
        self._player.setPlaybackRate(self._effective_playback_rate())
        self._player.play()
        base = os.path.basename(file_path)
        self._file_label.setText(base)
        self.setWindowTitle(f"播放器 - {base}")

    def _refresh_nav_enabled(self) -> None:
        ok = bool(self._current_path and os.path.isfile(self._current_path))
        self._prev_btn.setEnabled(ok)
        self._next_btn.setEnabled(ok)
        self._play_mode_btn.setEnabled(ok and self._mode == "media")
        self._sync_play_mode_ui()

    def _sync_play_mode_ui(self) -> None:
        label = {
            "seq": "顺序",
            "shuffle": "随机",
            "loop": "循环",
            "pause": "播完暂停",
        }.get(self._play_mode, "顺序")
        self._play_mode_btn.setText(label)

    def _cycle_play_mode(self) -> None:
        if self._mode != "media":
            return
        try:
            i = PLAY_MODES.index(self._play_mode)
        except ValueError:
            i = 0
        self._play_mode = PLAY_MODES[(i + 1) % len(PLAY_MODES)]
        self._sync_play_mode_ui()

    def _on_media_status(self, status) -> None:
        if self._mode != "media":
            return
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._play_mode == "pause":
            self._player.pause()
            return
        if self._play_mode == "loop":
            self._player.setPosition(0)
            self._player.play()
            return
        if self._play_mode == "shuffle":
            self._step_same_type_in_folder(+1, shuffle=True)
            return
        self._step_same_type_in_folder(+1)

    def _on_video_frame_changed(self, frame) -> None:
        if frame is None or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._last_video_frame = image.copy()

    def capture_video_frame(self) -> None:
        if not self._current_path or os.path.splitext(self._current_path)[1].lower() not in VIDEO_EXTS:
            QMessageBox.information(self, "无法截图", "请先打开视频文件。")
            return
        frame_image = self._last_video_frame
        if frame_image is None or frame_image.isNull():
            try:
                current_frame = self._video.videoSink().videoFrame()
                frame_image = current_frame.toImage()
            except Exception:
                frame_image = None
        if frame_image is None or frame_image.isNull():
            QMessageBox.information(self, "暂无视频帧", "请先播放视频或暂停到目标画面后再截图。")
            return

        folder = os.path.dirname(self._current_path)
        root = os.path.splitext(os.path.basename(self._current_path))[0]
        timestamp = ms_to_file_timestamp(self._player.position())
        out_path = os.path.join(folder, f"{root}_frame_{timestamp}.png")
        if os.path.exists(out_path):
            base = os.path.join(folder, f"{root}_frame_{timestamp}")
            index = 1
            while os.path.exists(f"{base}_{index}.png"):
                index += 1
            out_path = f"{base}_{index}.png"

        if not frame_image.save(out_path):
            QMessageBox.warning(self, "截图失败", "无法保存当前视频帧。")
            return
        self.open_path(out_path)

    def _classify_path_kind(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            return "image"
        if ext in AUDIO_EXTS:
            return "audio"
        return "video"

    def _step_same_type_in_folder(self, delta: int, shuffle: bool = False) -> None:
        """
        delta: -1 prev, +1 next
        Only cycles within same folder and same kind (video/audio/image).
        """
        cur = self._current_path or self._image_path
        if not cur:
            return
        folder = os.path.dirname(cur)
        if not folder or not os.path.isdir(folder):
            return
        kind = self._classify_path_kind(cur)
        if kind == "image":
            exts = IMAGE_EXTS
        elif kind == "audio":
            exts = AUDIO_EXTS
        else:
            exts = VIDEO_EXTS

        try:
            names = os.listdir(folder)
        except OSError:
            return

        candidates: list[str] = []
        for n in names:
            p = os.path.join(folder, n)
            if not os.path.isfile(p):
                continue
            if os.path.splitext(n)[1].lower() in exts:
                candidates.append(p)
        if not candidates:
            return

        candidates.sort(key=lambda p: os.path.basename(p).lower())
        cur_norm = os.path.normcase(os.path.abspath(cur))
        idx = -1
        for i, p in enumerate(candidates):
            if os.path.normcase(os.path.abspath(p)) == cur_norm:
                idx = i
                break
        if shuffle:
            if len(candidates) == 1:
                idx = 0
            else:
                choices = [j for j in range(len(candidates)) if j != (idx if idx >= 0 else -1)]
                idx = random.choice(choices) if choices else 0
        else:
            if idx < 0:
                idx = 0
            else:
                idx = (idx + (1 if delta >= 0 else -1)) % len(candidates)

        self.open_path(candidates[idx])

    def toggle_play(self) -> None:
        if self._mode == "image":
            return
        if self._player.source().isEmpty():
            self.open_file()
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def seek_relative(self, delta_ms: int) -> None:
        if self._mode == "image":
            return
        if self._duration_ms <= 0:
            return
        new_pos = clamp(self._player.position() + int(delta_ms), 0, self._duration_ms)
        self._player.setPosition(new_pos)
        self._last_user_seek_ms = new_pos

    def goto_time(self) -> None:
        if self._mode == "image":
            return
        if self._duration_ms <= 0:
            return
        dlg = GotoTimeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value_ms = dlg.value_ms()
        if value_ms is None:
            QMessageBox.information(self, "无效时间", "请输入有效的 hh:mm:ss / mm:ss（分钟/秒 0–59）。")
            return
        self._player.setPosition(clamp(value_ms, 0, self._duration_ms))
        self._last_user_seek_ms = self._player.position()

    def goto_time_inline(self) -> None:
        if self._mode == "image":
            return
        if self._duration_ms <= 0:
            return
        value_ms = parse_mmss(self._jump_input.text())
        if value_ms is None:
            QMessageBox.information(self, "无效时间", "请输入有效的 hh:mm:ss / mm:ss（分钟/秒 0–59）。")
            return
        self._player.setPosition(clamp(value_ms, 0, self._duration_ms))
        self._last_user_seek_ms = self._player.position()

    def _effective_playback_rate(self) -> float:
        text = (self._rate_edit.text() or "").strip()
        if not text:
            return 1.0
        try:
            v = float(text.replace(",", "."))
        except ValueError:
            return 1.0
        return max(0.25, min(8.0, v))

    def _apply_rate_from_edit(self) -> None:
        if self._mode == "image":
            return
        rate = self._effective_playback_rate()
        self._rate_edit.setText(f"{rate:.2f}".rstrip("0").rstrip("."))
        self._player.setPlaybackRate(rate)
        # Exit editing mode so global hotkeys work immediately.
        self._rate_edit.clearFocus()
        self._play_btn.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self._maybe_prompt_save_image("关闭窗口", discard_reverts=False):
            event.ignore()
            return
        super().closeEvent(event)

    def _on_image_context_menu(self, pos) -> None:
        if self._mode != "image" or not self._image_pixmap or self._image_pixmap.isNull():
            return

        menu = QMenu(self)
        act_rotate_l = menu.addAction("向左旋转 90°")
        act_rotate_r = menu.addAction("向右旋转 90°")
        menu.addSeparator()
        act_flip_h = menu.addAction("水平翻转")
        act_flip_v = menu.addAction("垂直翻转")
        menu.addSeparator()
        act_gray = menu.addAction("转为灰度")
        menu.addSeparator()
        act_reset = menu.addAction("还原原图")
        menu.addSeparator()
        act_save_as = menu.addAction("另存为…")

        chosen = menu.exec(self._image.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_rotate_l:
            self._apply_image_transform("rotate_l")
        elif chosen == act_rotate_r:
            self._apply_image_transform("rotate_r")
        elif chosen == act_flip_h:
            self._apply_image_transform("flip_h")
        elif chosen == act_flip_v:
            self._apply_image_transform("flip_v")
        elif chosen == act_gray:
            self._apply_image_transform("gray")
        elif chosen == act_reset:
            self.restore_original_image()
        elif chosen == act_save_as:
            self._save_image_as()

    def restore_original_image(self) -> None:
        if not self._image_original_img or self._image_original_img.isNull():
            return
        self._image_edit_img = QImage(self._image_original_img)
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._reset_gray_controls()
        self._image_dirty = False
        self._img_edited_ever = False
        self._img_saved_once = False
        self._reset_undo_stack()
        self._render_original_preview()
        self._render_image()
        self._refresh_histogram_ui()
        self._refresh_image_status_ui()

    def _apply_image_transform(self, kind: str) -> None:
        if not self._image_edit_img or self._image_edit_img.isNull():
            return
        self._push_undo()
        if kind == "reset":
            self.restore_original_image()
            return

        pm = QPixmap.fromImage(self._image_edit_img)
        if kind == "rotate_l":
            pm = pm.transformed(QTransform().rotate(-90))
        elif kind == "rotate_r":
            pm = pm.transformed(QTransform().rotate(90))
        elif kind == "flip_h":
            pm = pm.transformed(QTransform().scale(-1, 1))
        elif kind == "flip_v":
            pm = pm.transformed(QTransform().scale(1, -1))
        elif kind == "gray":
            img = apply_gray_transform(qimage_to_pil(self._image_edit_img), "grayscale", self._gray_params)
            pm = QPixmap.fromImage(pil_to_qimage(img))
        else:
            return

        self._image_edit_img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._image_dirty = True
        self._img_edited_ever = True
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        self._refresh_image_status_ui()

    def _default_image_save_path(self) -> str:
        if self._image_path:
            base = os.path.basename(self._image_path)
            root, _ext = os.path.splitext(base)
            folder = os.path.dirname(self._image_path)
            suffix = default_suffix(self._gray_algorithm) if self._gray_algorithm != "original" else "_edited"
            return os.path.join(folder, f"{root}{suffix}.png")
        return os.path.join(os.path.expanduser("~"), "image_edited.png")

    def _save_processed_image(self) -> bool:
        return self._save_image_as()

    def _save_image_as(self) -> bool:
        if self._mode != "image" or not self._image_pixmap or self._image_pixmap.isNull():
            return True
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            self._default_image_save_path(),
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;WEBP (*.webp);;BMP (*.bmp);;所有文件 (*.*)",
        )
        if not out_path:
            return False
        ok = self._image_pixmap.toImage().save(out_path)
        if not ok:
            QMessageBox.warning(self, "保存失败", "无法保存该图片，请尝试更换格式或路径。")
            return False
        self._image_dirty = False
        self._img_saved_once = True
        self._refresh_image_status_ui()
        return True

    def _revert_image_to_original(self) -> None:
        if self._image_original_img and not self._image_original_img.isNull():
            self._image_edit_img = QImage(self._image_original_img)
            self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
            self._reset_undo_stack()
            self._reset_gray_controls()
        self._image_dirty = False
        self._img_edited_ever = False
        self._img_saved_once = False
        self._render_original_preview()
        self._render_image()
        self._refresh_histogram_ui()
        self._refresh_image_status_ui()

    def _refresh_image_status_ui(self) -> None:
        if self._mode != "image":
            self._image_status_label.setVisible(False)
            return
        self._image_status_label.setVisible(True)
        if self._image_status_banner:
            text = self._image_status_banner
            color = "#64b5f6"
        elif self._image_dirty:
            text = "已修改未保存"
            color = "#ffb74d"
        elif self._img_edited_ever and self._img_saved_once:
            text = "已修改已保存"
            color = "#81c784"
        else:
            text = "未修改"
            color = "#9e9e9e"
        self._image_status_label.setText(text)
        self._image_status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _show_image_status_banner(self, message: str, ms: int = 4500) -> None:
        self._image_status_banner = message
        self._refresh_image_status_ui()
        QTimer.singleShot(ms, lambda: self._clear_image_status_banner())

    def _clear_image_status_banner(self) -> None:
        self._image_status_banner = ""
        self._refresh_image_status_ui()

    def _maybe_prompt_save_image(self, reason: str, discard_reverts: bool = True) -> bool:
        """
        reason: short phrase for user context, e.g. "关闭窗口" / "打开新文件" / "切换文件"
        Returns True to proceed; False to cancel the close/open action.
        """
        if self._mode != "image" or not self._image_dirty:
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle("保存图片")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("当前图片已修改，是否保存？")
        msg.setInformativeText(
            f"即将：{reason}。若选择「保存」，将弹出对话框供您选择保存位置与文件名。"
        )
        save_btn = msg.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == save_btn:
            ok = self._save_image_as()
            return ok
        if clicked == discard_btn:
            if discard_reverts:
                self._revert_image_to_original()
                self._show_image_status_banner("已修改放弃保存")
            else:
                self._image_dirty = False
            return True
        return False

    # ---- Image drawing tools ----
    def _set_draw_tool(self, tool: str) -> None:
        self._draw_tool = tool
        self._crop_btn.blockSignals(True)
        self._crop_btn.setChecked(False)
        self._crop_btn.blockSignals(False)
        self._set_crop_mode(False)
        self._tool_brush.blockSignals(True)
        self._tool_eraser.blockSignals(True)
        self._tool_brush.setChecked(tool == "brush")
        self._tool_eraser.setChecked(tool == "eraser")
        self._tool_brush.blockSignals(False)
        self._tool_eraser.blockSignals(False)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self._draw_color, self, "选择颜色")
        if c.isValid():
            self._draw_color = c
            self._color_hex.setText(c.name()[1:])  # RRGGBB

    def _apply_hex_color(self) -> None:
        txt = (self._color_hex.text() or "").strip().lstrip("#")
        if len(txt) != 6:
            return
        try:
            int(txt, 16)
        except ValueError:
            return
        self._draw_color = QColor("#" + txt)

    def _on_size_mm_changed(self, v: float) -> None:
        self._draw_size_mm = float(v)

    def _px_from_mm(self, mm: float) -> float:
        screen = QApplication.primaryScreen()
        dpi = float(screen.logicalDotsPerInch() if screen else 96.0)
        return max(1.0, mm * dpi / 25.4)

    def _image_point_from_widget(self, p: QPoint) -> QPoint | None:
        """Map coordinates inside the image QLabel (same size as displayed pixmap) to image pixels."""
        if not self._image_edit_img or self._image_edit_img.isNull():
            return None
        img_w = self._image_edit_img.width()
        img_h = self._image_edit_img.height()
        if img_w <= 0 or img_h <= 0:
            return None
        pm = self._image.pixmap()
        if pm is None or pm.isNull():
            return None
        dw, dh = pm.width(), pm.height()
        if dw <= 0 or dh <= 0:
            return None
        x, y = float(p.x()), float(p.y())
        if x < 0 or y < 0 or x >= dw or y >= dh:
            return None
        ix = int(x * img_w / dw)
        iy = int(y * img_h / dh)
        ix = max(0, min(img_w - 1, ix))
        iy = max(0, min(img_h - 1, iy))
        return QPoint(ix, iy)

    def _end_image_pan(self) -> None:
        if not self._img_pan_active:
            return
        self._img_pan_active = False
        self._img_pan_button = None
        self._img_pan_last = None
        try:
            self._image.releaseMouse()
        except Exception:
            pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # During startup, Qt may deliver events before all fields are initialized.
        if not hasattr(self, "_mode"):
            return super().eventFilter(obj, event)
        if obj is self._image and self._mode == "image" and self._draw_panel.isVisible():
            et = event.type()
            if et == QEvent.Type.Wheel:
                return super().eventFilter(obj, event)
            if et not in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseMove,
            ):
                return super().eventFilter(obj, event)
            me = event
            gp = (
                me.globalPosition().toPoint()
                if hasattr(me, "globalPosition")
                else me.globalPos()
            )

            if et == QEvent.Type.MouseButtonPress:
                if me.button() == Qt.MouseButton.MiddleButton:
                    self._img_pan_active = True
                    self._img_pan_last = QPoint(gp)
                    self._img_pan_button = Qt.MouseButton.MiddleButton
                    self._image.grabMouse()
                    return True
                if me.button() == Qt.MouseButton.LeftButton and (
                    me.modifiers() & Qt.KeyboardModifier.AltModifier
                ):
                    self._img_pan_active = True
                    self._img_pan_last = QPoint(gp)
                    self._img_pan_button = Qt.MouseButton.LeftButton
                    self._image.grabMouse()
                    return True
                if me.button() == Qt.MouseButton.LeftButton and not (
                    me.modifiers() & Qt.KeyboardModifier.AltModifier
                ):
                    ip = self._image_point_from_widget(
                        me.position().toPoint() if hasattr(me, "position") else me.pos()
                    )
                    if ip is not None:
                        if self._crop_mode:
                            self._crop_dragging = True
                            self._crop_start = ip
                            self._crop_end = ip
                            self._render_image()
                        else:
                            self._push_undo()
                            self._drawing = True
                            self._last_draw_pt = ip
                        return True

            elif et == QEvent.Type.MouseMove:
                if self._img_pan_active and self._img_pan_last is not None:
                    if me.buttons() == Qt.MouseButton.NoButton:
                        self._end_image_pan()
                    else:
                        d = QPoint(gp) - self._img_pan_last
                        self._img_pan_last = QPoint(gp)
                        hsb = self._image_scroll.horizontalScrollBar()
                        vsb = self._image_scroll.verticalScrollBar()
                        hsb.setValue(hsb.value() - d.x())
                        vsb.setValue(vsb.value() - d.y())
                        return True
                if self._crop_mode and self._crop_dragging:
                    ip = self._image_point_from_widget(
                        me.position().toPoint() if hasattr(me, "position") else me.pos()
                    )
                    if ip is not None:
                        self._crop_end = ip
                        self._render_image()
                    return True
                if (
                    (not self._crop_mode)
                    and self._drawing
                    and (self._image_edit_img is not None)
                    and (self._last_draw_pt is not None)
                ):
                    ip = self._image_point_from_widget(
                        me.position().toPoint() if hasattr(me, "position") else me.pos()
                    )
                    if ip is None:
                        return True
                    self._draw_segment(self._last_draw_pt, ip)
                    self._last_draw_pt = ip
                    return True

            elif et == QEvent.Type.MouseButtonRelease:
                if self._img_pan_active and self._img_pan_button is not None:
                    if me.button() == self._img_pan_button:
                        self._end_image_pan()
                        return True
                if self._crop_mode and me.button() == Qt.MouseButton.LeftButton and self._crop_dragging:
                    self._crop_dragging = False
                    self._apply_crop_if_valid()
                    return True
                if me.button() == Qt.MouseButton.LeftButton and self._drawing:
                    self._drawing = False
                    return True
        return super().eventFilter(obj, event)

    def _apply_zoom_from_edit(self) -> None:
        if self._mode != "image":
            return
        raw = (self._zoom_edit.text() or "").strip().rstrip("%")
        if not raw:
            self._sync_zoom_edit_text()
            return
        try:
            pct = int(raw)
        except ValueError:
            self._sync_zoom_edit_text()
            return
        self._set_zoom(pct / 100.0)

    def _sync_zoom_edit_text(self) -> None:
        self._zoom_edit.blockSignals(True)
        self._zoom_edit.setText(str(int(round(self._img_zoom * 100))))
        self._zoom_edit.blockSignals(False)

    def _set_zoom(self, z: float) -> None:
        self._img_zoom = max(0.1, min(10.0, float(z)))
        self._sync_zoom_edit_text()
        if self._mode == "image":
            self._render_image()

    def _set_crop_mode(self, enabled: bool) -> None:
        self._crop_mode = bool(enabled)
        if self._crop_mode:
            self._tool_brush.blockSignals(True)
            self._tool_eraser.blockSignals(True)
            self._tool_brush.setChecked(False)
            self._tool_eraser.setChecked(False)
            self._tool_brush.blockSignals(False)
            self._tool_eraser.blockSignals(False)
        self._crop_dragging = False
        self._crop_start = None
        self._crop_end = None
        if self._mode == "image":
            self._render_image()

    def _apply_crop_if_valid(self) -> None:
        if not self._crop_mode or not self._crop_start or not self._crop_end:
            return
        if not self._image_edit_img or self._image_edit_img.isNull():
            return
        a, b = self._crop_start, self._crop_end
        x1, y1 = min(a.x(), b.x()), min(a.y(), b.y())
        x2, y2 = max(a.x(), b.x()), max(a.y(), b.y())
        if (x2 - x1) < 2 or (y2 - y1) < 2:
            self._crop_start = None
            self._crop_end = None
            self._render_image()
            return
        self._push_undo()
        rect = QRect(x1, y1, x2 - x1, y2 - y1)
        rect = rect.intersected(QRect(0, 0, self._image_edit_img.width(), self._image_edit_img.height()))
        if rect.width() <= 1 or rect.height() <= 1:
            return
        self._image_edit_img = self._image_edit_img.copy(rect)
        # cropping changes the meaning of "original" for eraser; keep original_img as-is,
        # but update pixmap and dirty flags.
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._image_dirty = True
        self._img_edited_ever = True
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        self._refresh_image_status_ui()
        # keep crop mode on, but clear rectangle
        self._crop_start = None
        self._crop_end = None


    def _reset_undo_stack(self) -> None:
        self._undo_stack = []
        self._undo_index = -1
        if self._image_edit_img and not self._image_edit_img.isNull():
            self._undo_stack.append(QImage(self._image_edit_img))
            self._undo_index = 0

    def _push_undo(self) -> None:
        if not self._image_edit_img or self._image_edit_img.isNull():
            return
        # truncate redo
        if 0 <= self._undo_index < len(self._undo_stack) - 1:
            self._undo_stack = self._undo_stack[: self._undo_index + 1]
        self._undo_stack.append(QImage(self._image_edit_img))
        self._undo_index = len(self._undo_stack) - 1
        # cap history
        if len(self._undo_stack) > 50:
            drop = len(self._undo_stack) - 50
            self._undo_stack = self._undo_stack[drop:]
            self._undo_index = max(0, self._undo_index - drop)

    def image_undo(self) -> None:
        if self._mode != "image" or not self._undo_stack:
            return
        if self._undo_index <= 0:
            return
        self._undo_index -= 1
        self._image_edit_img = QImage(self._undo_stack[self._undo_index])
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        if self._undo_index == 0:
            self._image_dirty = False
            self._img_edited_ever = False
            self._img_saved_once = False
        else:
            self._image_dirty = True
            self._img_edited_ever = True
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        self._refresh_image_status_ui()

    def image_redo(self) -> None:
        if self._mode != "image" or not self._undo_stack:
            return
        if self._undo_index >= len(self._undo_stack) - 1:
            return
        self._undo_index += 1
        self._image_edit_img = QImage(self._undo_stack[self._undo_index])
        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        if self._undo_index == 0:
            self._image_dirty = False
            self._img_edited_ever = False
            self._img_saved_once = False
        else:
            self._image_dirty = True
            self._img_edited_ever = True
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        self._refresh_image_status_ui()

    def _draw_segment(self, a: QPoint, b: QPoint) -> None:
        if not self._image_edit_img or self._image_edit_img.isNull():
            return
        width_px = self._px_from_mm(self._draw_size_mm)

        if self._draw_tool == "brush":
            painter = QPainter(self._image_edit_img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(self._draw_color)
            pen.setWidthF(width_px)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(a, b)
            painter.end()
        else:
            # eraser: restore pixels from original image under the stroke
            if not self._image_original_img or self._image_original_img.isNull():
                return
            path = QPainterPath()
            path.moveTo(a)
            path.lineTo(b)
            stroker = QPainterPathStroker()
            stroker.setWidth(width_px)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            clip = stroker.createStroke(path)

            painter = QPainter(self._image_edit_img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setClipPath(clip)
            painter.drawImage(0, 0, self._image_original_img)
            painter.end()

        self._image_pixmap = QPixmap.fromImage(self._image_edit_img)
        self._image_dirty = True
        self._img_edited_ever = True
        self._render_image()
        self._refresh_histogram_ui()
        self._update_gray_panel_text()
        self._refresh_image_status_ui()

    def _step_rate(self, delta: float) -> None:
        if self._mode == "image":
            return
        cur = self._effective_playback_rate()
        nxt = max(0.25, min(8.0, cur + float(delta)))
        nxt = round(nxt * 10) / 10.0
        self._rate_edit.setText(f"{nxt:.2f}".rstrip("0").rstrip("."))
        self._player.setPlaybackRate(nxt)

    def _on_duration(self, duration_ms: int) -> None:
        self._duration_ms = int(duration_ms or 0)
        if self._mode == "media":
            self._pos_slider.setRange(0, max(0, self._duration_ms))
            self._refresh_time_label()

    def _on_position(self, pos_ms: int) -> None:
        if self._mode != "media":
            return
        if self._is_scrubbing:
            return
        self._pos_slider.blockSignals(True)
        self._pos_slider.setValue(int(pos_ms or 0))
        self._pos_slider.blockSignals(False)
        self._refresh_time_label()

    def _on_slider_pressed(self) -> None:
        self._is_scrubbing = True

    def _on_slider_moved(self, value: int) -> None:
        # Show preview time while dragging.
        self._last_user_seek_ms = int(value)
        self._refresh_time_label(preview=value)

    def _on_slider_released(self) -> None:
        self._is_scrubbing = False
        value = int(self._pos_slider.value())
        self._player.setPosition(value)
        self._last_user_seek_ms = value
        self._refresh_time_label()

    def _refresh_time_label(self, preview: int | None = None) -> None:
        if self._mode == "image":
            return
        if self._duration_ms <= 0:
            self._time_label.setText("00:00 / 00:00")
            return
        cur = int(preview if preview is not None else self._player.position())
        self._time_label.setText(f"{ms_to_hhmmss(cur)} / {ms_to_hhmmss(self._duration_ms)}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("播放器")
    w = PlayerWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
