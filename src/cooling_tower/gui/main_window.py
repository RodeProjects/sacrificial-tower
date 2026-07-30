from __future__ import annotations

import os
import sys
from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, Qt, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QCursor,
    QFontMetrics,
    QIcon,
    QPixmap,
    QResizeEvent,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.diagnostics import (
    DiagnosticJournal,
    current_diagnostic_journal,
)
from cooling_tower.gui.analysis_worker import AnalysisWorker
from cooling_tower.gui.background_jobs import (
    BackgroundJob,
    BackgroundJobManager,
    JobKind,
)
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.feasibility_worker import FeasibilityWorker
from cooling_tower.gui.export_worker import ExportWorker
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.preview_worker import PreviewWorker
from cooling_tower.gui.profile_worker import ProfileMatchingWorker
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.gui.slicer_worker import SlicerDiscoveryWorker
from cooling_tower.gui.texts import (
    PREDICTION_ROWS,
    SETTING_INFO_TEXTS,
)
from cooling_tower.gui.update_restart_dialog import UpdateRestartCountdownDialog
from cooling_tower.gui.update_worker import UpdateCheckWorker, UpdateDownloadWorker
from cooling_tower.gui.user_messages import german_user_message
from cooling_tower.gui.workflow_controller import WorkflowController, WorkflowStage
from cooling_tower.gui.widgets import (
    AutoHeightTextEdit,
    FooterNoticeDropdown,
    GCodeDropZone,
    InfoToolButton,
    NumericSettingWidget,
    ResponsiveCardGrid,
    SectionCard,
    SectionState,
    WheelSafeComboBox,
    WheelSafeDoubleSpinBox,
    WheelSafeSpinBox,
    WindowHintController,
)
from cooling_tower.models import (
    CalibrationConfig,
    CalibrationMode,
    FeasibilityIssue,
    GCodeAnalysisSnapshot,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    TowerNeedAssessment,
)
from cooling_tower.distribution import (
    DistributionChannel,
    detect_distribution_channel,
)
from cooling_tower.persistence import migrate_legacy_configuration
from cooling_tower.preview import (
    OutputMode,
    PreviewExportResult,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewService,
    PreviewState,
)
from cooling_tower.services import GCodeAnalysisService, assess_tower_need
from cooling_tower.slicers import (
    ProfileInventoryService,
    ProfileMappingStore,
    ProfileMatchResult,
    ProfileMatchingService,
    ProfileMatchState,
    SlicerDiscoveryResult,
    SlicerDiscoveryService,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerPreferenceStore,
    SlicerProfileProbeValidator,
)
from cooling_tower.version import (
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    APP_VERSION_LABEL,
)
from cooling_tower.update import UpdateInfo, UpdateService
from cooling_tower.runtime_paths import (
    INSTALL_ROOT,
    IS_FROZEN,
    RESOURCE_ROOT,
    resolve_user_data_root,
)
from cooling_tower.tower.hollow_profile import (
    MAXIMUM_EXPANSION_ANGLE_DEG,
    validate_hollow_settings,
)
from cooling_tower.tower.base_calculator import (
    BASE_WIDTH_PER_OBJECT_HEIGHT,
    MINIMUM_BASE_WIDTH_MM,
)
from cooling_tower.tower.wall_calculator import calculate_wall_path_bounds


PREVIEW_QUALITY_ITERATIONS = {
    "fast": 1,
    "balanced": 3,
    "exact": 5,
}
DEFAULT_PREVIEW_QUALITY = "balanced"
EXPORT_SLICER_ITERATIONS = 5
MAIN_FOOTER_MAX_HEIGHT_PX = 350
MAIN_FOOTER_NARROW_MAX_HEIGHT_PX = 400
MAXIMUM_TARGET_LAYER_TIME_S = 120.0
PREVIEW_ACTION_COMPACT_WIDTH_PX = 176
EXPORT_ACTION_HORIZONTAL_PADDING_PX = 25
ABOUT_DIALOG_MINIMUM_WIDTH_PX = 450
ABOUT_DIALOG_PREFERRED_WIDTH_PX = 720
ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX = 720
OPTIONAL_DIALOG_PARENT_MARGIN_PX = 80
OUTPUT_DIALOG_MINIMUM_WIDTH_PX = 600
CURRENT_LICENSE_STATUS = "development"
LICENSE_STATUS_DEFINITIONS = {
    "development": {
        "label": "Entwicklungsversion",
        "description": (
            "Diese Version befindet sich noch in Entwicklung und ist nicht "
            "für den regulären Vertrieb bestimmt."
        ),
        "foreground": "#6b4b00",
        "background": "#fff3ce",
        "border": "#e3c365",
    },
    "evaluation": {
        "label": "Testversion",
        "description": (
            "Diese Version ist für einen begrenzten Test- und "
            "Evaluierungszeitraum vorgesehen."
        ),
        "foreground": "#174ea6",
        "background": "#eaf2ff",
        "border": "#9bbcf2",
    },
    "licensed": {
        "label": "Lizenzierte Version",
        "description": "Für diese Version liegt eine gültige Lizenz vor.",
        "foreground": "#17633a",
        "background": "#e7f6ed",
        "border": "#8fc9a5",
    },
    "unlicensed": {
        "label": "Nicht lizenzierte Version",
        "description": "Für diese Version liegt keine gültige Lizenz vor.",
        "foreground": "#9b1c1c",
        "background": "#fdecec",
        "border": "#e4a1a1",
    },
}
SETTING_UNITS = {
    "target_layer_time_s": "s",
    "safety_factor": "",
    "minimum_outer_radius_mm": "mm",
    "maximum_outer_radius_mm": "mm",
    "minimum_wall_thickness_mm": "mm",
    "maximum_wall_thickness_mm": "mm",
    "wall_path_width_mm": "mm",
    "minimum_inner_radius_mm": "mm",
    "manual_base_width_mm": "mm",
    "base_height_mm": "mm",
    "maximum_expansion_angle_deg": "°",
    "maximum_contraction_angle_deg": "°",
    "maximum_wall_change_per_mm_z": "mm/mm",
    "mesh_segments": "Segm.",
    "local_reference_window": "Layer",
}
GUI_ASSET_ROOT = Path(__file__).with_name("assets")


def open_path(path: str | Path) -> None:
    target = str(Path(path).resolve())
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(target))


def open_directory(path: str | Path) -> None:
    open_path(path)


def _de_number(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _validation_issue_key(message: str) -> str:
    """Return a stable semantic key for equivalent validation wording."""

    normalized = " ".join(
        str(message)
        .casefold()
        .replace("-", " ")
        .replace(".", " ")
        .replace(":", " ")
        .split()
    )
    if (
        "mindest außenradius" in normalized
        and (
            "maximalradius" in normalized
            or "maximale außenradius" in normalized
        )
        and (
            "überschreiten" in normalized
            or "mindestens" in normalized
        )
    ):
        return "outer-radius-order"
    if (
        "mindestwandstärke" in normalized
        and "maximalwandstärke" in normalized
        and (
            "unterschreiten" in normalized
            or "mindestens" in normalized
        )
    ):
        return "wall-thickness-order"
    return normalized


def _deduplicate_validation_messages(messages) -> list[str]:
    """Preserve order while removing textually or semantically equal issues."""

    result: list[str] = []
    seen: set[str] = set()
    for raw_message in messages:
        message = str(raw_message).strip()
        if not message:
            continue
        key = _validation_issue_key(message)
        if key in seen:
            continue
        seen.add(key)
        result.append(message)
    return result


def _format_footer_notice(messages: list[str]) -> str:
    """Format every standalone footer notice as its own bullet point."""

    compact = [" ".join(message.split()) for message in messages if message]
    return "\n".join(
        f"• {message.lstrip('• ').strip()}" for message in compact
    )


def _format_grouped_footer_notice(
    general_messages: list[str],
    field_groups: list[tuple[str, list[str]]],
) -> str:
    """Render general bullets and field-specific heading/bullet groups."""

    lines: list[str] = []
    general_text = _format_footer_notice(general_messages)
    if general_text:
        lines.extend(general_text.splitlines())
    for heading, messages in field_groups:
        compact = _deduplicate_validation_messages(messages)
        if not heading or not compact:
            continue
        lines.append(" ".join(heading.split()))
        lines.extend(
            f"• {' '.join(message.split()).lstrip('• ').strip()}"
            for message in compact
        )
    return "\n".join(lines)


class _FooterIssueLabel(QLabel):
    """Rich footer rendering with a stable plain-text compatibility API."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plain_text = ""
        self._rendered_html = ""

    def setText(self, text: str) -> None:  # noqa: N802 - Qt compatibility
        self._plain_text = str(text)
        self._rendered_html = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        super().setText(self._plain_text)

    def text(self) -> str:
        return self._plain_text

    def clear(self) -> None:
        self._plain_text = ""
        self._rendered_html = ""
        super().clear()

    def set_grouped_notice(
        self,
        general_messages: list[str],
        field_groups: list[tuple[str, list[str]]],
    ) -> None:
        """Bold field headings and indent their associated bullet rows."""

        self._plain_text = _format_grouped_footer_notice(
            general_messages,
            field_groups,
        )
        if not self._plain_text:
            self.clear()
            return

        rows: list[str] = []
        for message in _deduplicate_validation_messages(general_messages):
            compact = " ".join(message.split()).lstrip("• ").strip()
            rows.append(
                '<tr><td colspan="2">'
                f"• {escape(compact)}"
                "</td></tr>"
            )
        for heading, messages in field_groups:
            compact_messages = _deduplicate_validation_messages(messages)
            if not heading or not compact_messages:
                continue
            rows.append(
                '<tr><td colspan="2"><b>'
                f"{escape(' '.join(heading.split()))}"
                "</b></td></tr>"
            )
            for message in compact_messages:
                compact = " ".join(message.split()).lstrip("• ").strip()
                rows.append(
                    '<tr><td width="18"></td><td>'
                    f"• {escape(compact)}"
                    "</td></tr>"
                )
        self._rendered_html = (
            '<table cellspacing="0" cellpadding="0" width="100%">'
            + "".join(rows)
            + "</table>"
        )
        self.setTextFormat(Qt.TextFormat.RichText)
        super().setText(self._rendered_html)
        self.setAccessibleDescription(self._plain_text)


class _ResponsiveLegalButtonGrid(QWidget):
    """Flow three legal-document actions across as many columns as fit."""

    def __init__(
        self,
        buttons: list[QPushButton],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.buttons = buttons
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.column_count = 0
        for button in self.buttons:
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        # Start with the preferred one-row arrangement so the parent dialog's
        # natural width can account for all three actions. A real resize then
        # reduces the column count when the available viewport is narrower.
        self._relayout(10_000)

    def _columns_for_width(self, width: int) -> int:
        widths = [
            QFontMetrics(button.font()).horizontalAdvance(button.text())
            + button.iconSize().width()
            + 30
            for button in self.buttons
        ]
        spacing = max(0, self.grid.horizontalSpacing())
        if width >= sum(widths) + spacing * (len(widths) - 1):
            return 3
        if width >= sum(sorted(widths, reverse=True)[:2]) + spacing:
            return 2
        return 1

    def _relayout(self, width: int) -> None:
        columns = self._columns_for_width(width)
        if columns == self.column_count:
            return
        for button in self.buttons:
            self.grid.removeWidget(button)
        for index, button in enumerate(self.buttons):
            row, column = divmod(index, columns)
            is_last_unpaired = (
                columns == 2
                and index == len(self.buttons) - 1
                and len(self.buttons) % columns
            )
            self.grid.addWidget(
                button,
                row,
                column,
                1,
                columns if is_last_unpaired else 1,
            )
        for column in range(3):
            self.grid.setColumnStretch(column, 0)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self.column_count = columns
        self.grid.invalidate()
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        self._relayout(event.size().width())
        super().resizeEvent(event)


class MainWindow(QMainWindow):
    """Scrollable desktop front end for the shared generation service."""

    def __init__(
        self,
        *,
        user_settings_path: str | Path | None = None,
        default_settings_path: str | Path | None = None,
        analysis_service: GCodeAnalysisService | None = None,
        slicer_service: SlicerDiscoveryService | None = None,
        profile_service: ProfileMatchingService | None = None,
        preview_service: PreviewService | None = None,
        export_service: PreviewExportService | None = None,
        update_service: UpdateService | None = None,
        enable_update_check: bool | None = None,
        user_data_root: str | Path | None = None,
        distribution_channel: DistributionChannel | str | None = None,
        diagnostic_journal: DiagnosticJournal | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(720, 640)
        if distribution_channel is None:
            self.distribution_channel = detect_distribution_channel()
        else:
            self.distribution_channel = DistributionChannel(distribution_channel)
        explicit_user_settings = (
            str(user_settings_path)
            if user_settings_path is not None
            else os.environ.get("COOLING_TOWER_USER_SETTINGS_PATH", "").strip()
            or None
        )
        if user_data_root is not None:
            self.user_data_root = Path(user_data_root).expanduser().resolve()
            user_config_root = self.user_data_root / "config"
        elif explicit_user_settings is not None:
            user_config_root = Path(explicit_user_settings).expanduser().resolve().parent
            self.user_data_root = user_config_root.parent
        else:
            default_instance = (
                self.distribution_channel.value
                if IS_FROZEN
                else "development"
            )
            self.user_data_root = resolve_user_data_root(
                instance_id=default_instance
            )
            user_config_root = self.user_data_root / "config"
        self.location_migration_results = ()
        if explicit_user_settings is None and user_data_root is None:
            self.location_migration_results = migrate_legacy_configuration(
                INSTALL_ROOT / "config",
                user_config_root,
                (
                    "user_settings.json",
                    "slicer_settings.json",
                    "profile_inventory_cache.json",
                    "profile_mappings.json",
                ),
            )
        self.analysis_service = analysis_service or GCodeAnalysisService()
        self._slicer_service_was_injected = slicer_service is not None
        self.slicer_service = slicer_service or SlicerDiscoveryService(
            preference_store=SlicerPreferenceStore(
                os.environ.get("COOLING_TOWER_SLICER_SETTINGS_PATH")
                or user_config_root / "slicer_settings.json"
            )
        )
        self.profile_service = profile_service or ProfileMatchingService(
            inventory_service=ProfileInventoryService(
                user_config_root / "profile_inventory_cache.json"
            ),
            mapping_store=ProfileMappingStore(
                user_config_root / "profile_mappings.json"
            ),
            validator=SlicerProfileProbeValidator(),
        )
        self.preview_service = preview_service or PreviewService()
        self.export_service = export_service or PreviewExportService()
        update_service_was_injected = update_service is not None
        self.update_service = update_service or UpdateService()
        self.background_job_manager = BackgroundJobManager(
            self,
            diagnostic_journal=(
                diagnostic_journal or current_diagnostic_journal()
            ),
        )
        self.background_job_manager.job_released.connect(
            self._on_background_job_released
        )
        requested_update_check = (
            enable_update_check
            if enable_update_check is not None
            else update_service_was_injected
            or (
                bool(getattr(sys, "frozen", False))
                and os.environ.get("COOLING_TOWER_DISABLE_UPDATE_CHECK") != "1"
            )
        )
        self._update_check_enabled = bool(
            requested_update_check
            and self.distribution_channel.uses_sacrificial_tower_updates
        )
        self.available_update: UpdateInfo | None = None
        self._update_check_request_id = 0
        self._update_download_request_id = 0
        self._slicer_request_id = 0
        self._pending_slicer_discovery: tuple[bool, Path | None] | None = None
        self.slicer_discovery_result: SlicerDiscoveryResult | None = None
        self._slicer_header_installation: SlicerInstallation | None = None
        self._populating_slicer_combo = False
        self._profile_request_id = 0
        self._pending_profile_match: dict[str, object] | None = None
        self.profile_match_result: ProfileMatchResult | None = None
        self._populating_profile_combos = False
        self.profile_preview_outdated = False
        self._analysis_request_id = 0
        self._analysis_failed = False
        self._closing = False
        self.analysis_snapshot: GCodeAnalysisSnapshot | None = None
        self.tower_assessment: TowerNeedAssessment | None = None
        self.profile_feasibility: ProfileFeasibilityAssessment | None = None
        self.current_gcode_path: Path | None = None
        self._feasibility_request_id = 0
        self._preview_request_id = 0
        self.current_preview: PreviewResult | None = None
        self.preview_state = PreviewState.EMPTY
        self._slicer_prediction_request_id = 0
        self._slicer_prediction_estimate_s: float | None = None
        self._slicer_prediction_status = ""
        self._export_request_id = 0
        self.last_export_result: PreviewExportResult | None = None
        # This session-scoped path intentionally survives a changed or removed
        # G-Code.  The footer action must always target the most recent
        # successful tower export since the application was started.
        self._latest_export_directory: Path | None = None
        self._phase17_static_valid = False
        self._loading_phase17_state = True
        self._setting_widgets: dict[str, NumericSettingWidget] = {}
        self._incomplete_setting_names: set[str] = set()
        self._static_field_errors: dict[str, list[str]] = {}
        self._static_error_causes: list[str] = []
        self._feasibility_field_errors: dict[str, list[str]] = {}
        self._feasibility_issues: tuple[FeasibilityIssue, ...] = ()
        self._feasibility_issue_summaries: list[str] = []
        self._feasibility_solution_items: list[str] = []
        self._feasibility_issue_targets: dict[
            tuple[str, tuple[str, ...]], str
        ] = {}
        self._feasibility_request_source: (
            tuple[int, str | None, str | None] | None
        ) = None
        self._pending_reset_setting_name: str | None = None
        self._workflow_error_message: str | None = None
        self._last_changed_setting_name: str | None = None
        # Keep optional native dialogs out of the Windows startup animation.
        # They are created only when the user opens them for the first time.
        self._preview_dialog: PreviewDialog | None = None
        self._pending_preview_camera_state: object = None
        self._additional_options_dialog: QDialog | None = None
        self._about_dialog: QDialog | None = None

        self.settings_store = UserSettingsStore(
            explicit_user_settings
            or user_config_root / "user_settings.json",
            default_settings_path
            or RESOURCE_ROOT / "config" / "default_settings.json",
            default_output_base=(
                self.user_data_root
                if explicit_user_settings is None
                else None
            ),
        )
        self.default_settings = self.settings_store.load_defaults()
        self.default_output_root = self.settings_store.load_default_output_root()
        initial_settings, ui_state = self.settings_store.load()

        self._feasibility_timer = QTimer(self)
        self._feasibility_timer.setSingleShot(True)
        self._feasibility_timer.setInterval(180)
        self._feasibility_timer.timeout.connect(
            self._start_feasibility_validation
        )
        self._profile_watch_timer = QTimer(self)
        # Runtime profile invalidation is intentionally infrequent.  The scan
        # itself stays off the GUI thread because real slicer installations can
        # contain many thousands of profile files.
        self._profile_watch_timer.setInterval(30000)
        self._profile_watch_timer.timeout.connect(
            self._check_profile_inventory_changes
        )

        self._build_ui()
        self._main_geometry_before_preview: QRect | None = None
        self._main_was_maximized_before_preview = False
        self._preview_layout_adjusted = False
        self._preview_target_geometry: QRect | None = None
        self._hint_controller = WindowHintController(self)
        self._apply_style()
        self.apply_settings(initial_settings)
        self.output_root_edit.setText(
            str(ui_state.get("output_root", self.default_output_root))
        )
        self._restore_phase17_ui_state(ui_state)
        window = ui_state.get("window", {})
        self.resize(
            int(window.get("width", 900)),
            int(window.get("height", 900)),
        )
        self._restore_initial_window_position(window)
        self.update_wall_path_preview()
        self._update_section_summaries()
        self._loading_phase17_state = False
        self._refresh_stl_availability()
        self.validate_form()
        self.workflow.reset()
        self._show_settings_load_notice()
        QTimer.singleShot(0, self._update_slicer_combo_widths)
        if self._update_check_enabled:
            QTimer.singleShot(750, self.start_update_check)

    def _restore_initial_window_position(
        self,
        window_state: object,
    ) -> None:
        """Place the complete main window before its first visible frame."""

        screens = QApplication.screens()
        if not screens:
            return

        saved_x: int | None = None
        saved_y: int | None = None
        if isinstance(window_state, dict):
            raw_x = window_state.get("x")
            raw_y = window_state.get("y")
            if (
                isinstance(raw_x, int)
                and not isinstance(raw_x, bool)
                and isinstance(raw_y, int)
                and not isinstance(raw_y, bool)
            ):
                saved_x = raw_x
                saved_y = raw_y

        target = QRect(QPoint(0, 0), self.size())
        screen = None
        if saved_x is not None and saved_y is not None:
            target.moveTopLeft(QPoint(saved_x, saved_y))
            largest_visible_area = 0
            for candidate in screens:
                intersection = target.intersected(candidate.availableGeometry())
                visible_area = max(0, intersection.width()) * max(
                    0,
                    intersection.height(),
                )
                if visible_area > largest_visible_area:
                    screen = candidate
                    largest_visible_area = visible_area

        if screen is None:
            screen = (
                QApplication.screenAt(QCursor.pos())
                or QApplication.primaryScreen()
                or screens[0]
            )
            target.moveCenter(screen.availableGeometry().center())

        available = screen.availableGeometry()
        maximum_x = max(
            available.left(),
            available.right() - target.width() + 1,
        )
        maximum_y = max(
            available.top(),
            available.bottom() - target.height() + 1,
        )
        target.moveLeft(
            min(max(target.left(), available.left()), maximum_x)
        )
        target.moveTop(
            min(max(target.top(), available.top()), maximum_y)
        )
        self.move(target.topLeft())

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("mainHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 8)
        header_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title = QLabel(APP_NAME)
        self.title_label = title
        title.setObjectName("titleLabel")
        self.reset_button = QPushButton("Standardwerte wiederherstellen")
        self.reset_button.setObjectName("headerResetButton")
        self.reset_button.setToolTip(
            "Alle Eingaben auf die Standardwerte zurücksetzen"
        )
        self.reset_button.setFixedHeight(METRICS.info_button_diameter_px)
        self.reset_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.reset_button.clicked.connect(self.request_reset_defaults)
        self.stl_info_button = InfoToolButton(
            "STL-Dateien bleiben allgemein anpassbar. Die endgültige "
            "Layerzeit sollte nach dem gemeinsamen Slicen von Objekt und "
            "Kühlturm kontrolliert werden."
        )
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.reset_button)
        title_row.addWidget(self.stl_info_button)
        self.options_button = QToolButton()
        self.options_button.setObjectName("optionsButton")
        self.options_button.setText("")
        self.options_button.setIcon(
            QIcon(str(GUI_ASSET_ROOT / "menu.svg"))
        )
        self.options_button.setIconSize(QSize(18, 18))
        self.options_button.setFixedSize(
            METRICS.info_button_diameter_px,
            METRICS.info_button_diameter_px,
        )
        self.options_button.setToolTip("Menü öffnen")
        self.options_button.setAccessibleName("Menü öffnen")
        self.options_menu = QMenu(self.options_button)
        self.options_menu.setObjectName("mainOptionsMenu")
        self.change_output_action = self.options_menu.addAction(
            QIcon(str(GUI_ASSET_ROOT / "folder.svg")),
            "Ausgabeordner ändern",
        )
        self.change_output_action.triggered.connect(
            self.show_additional_options
        )
        self.about_action = self.options_menu.addAction(
            QIcon(str(GUI_ASSET_ROOT / "info_circle.svg")),
            f"Über {APP_NAME}",
        )
        self.about_action.triggered.connect(self.show_about_dialog)
        self.options_button.clicked.connect(self.show_options_menu)
        title_row.addWidget(self.options_button)
        subtitle = QLabel(APP_SUBTITLE)
        self.subtitle_label = subtitle
        subtitle.setObjectName("subtitleLabel")
        self.version_label = QLabel(APP_VERSION_LABEL)
        self.version_label.setObjectName("versionLabel")
        self.version_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.version_label.setToolTip(
            f"Aktuelle Programmversion: {APP_VERSION}"
        )
        self.version_label.setAccessibleName(
            f"Programmversion {APP_VERSION}"
        )
        subtitle_row = QHBoxLayout()
        subtitle_row.setContentsMargins(0, 0, 0, 0)
        subtitle_row.setSpacing(8)
        subtitle_row.addWidget(subtitle)
        subtitle_row.addStretch(1)
        subtitle_row.addWidget(self.version_label)
        self.update_button = QPushButton("Aktualisieren")
        self.update_button.setObjectName("updateButton")
        self.update_button.setAccessibleName("Programm aktualisieren")
        self.update_button.setToolTip(
            "Die neueste Programmversion herunterladen und installieren"
        )
        self.update_button.clicked.connect(self.start_update_download)
        self.update_button.hide()
        subtitle_row.addWidget(self.update_button)
        header_layout.addLayout(title_row)
        header_layout.addLayout(subtitle_row)
        root_layout.addWidget(header)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("settingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Reserve the vertical gutter permanently so expanding or collapsing a
        # section never changes the width of the two-column cards.
        self.settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.settings_scroll.verticalScrollBar().rangeChanged.connect(
            self._on_settings_scroll_range_changed
        )
        content = QWidget()
        content.setObjectName("settingsContent")
        self.settings_content = content
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(22, 8, 22, 8)
        self.content_layout.setSpacing(10)

        source_group = SectionCard(
            "Referenz-G-Code",
            collapsible=True,
            expanded=True,
            state=SectionState.ACTIVE,
        )
        self.source_group = source_group
        source_group.setProperty("role", "gcodeSource")
        source_group.setProperty("outerDropdown", True)
        source_layout = source_group.content_layout
        self.gcode_import_guide_row = QWidget()
        self.gcode_import_guide_row.setObjectName("gcodeImportGuideRow")
        gcode_guide_layout = QHBoxLayout(self.gcode_import_guide_row)
        gcode_guide_layout.setContentsMargins(
            0,
            0,
            0,
            max(
                0,
                METRICS.card_body_vertical_padding_px
                - source_layout.spacing(),
            ),
        )
        gcode_guide_layout.setSpacing(8)
        self.gcode_import_guide_icon = QLabel("ℹ")
        self.gcode_import_guide_icon.setObjectName("gcodeImportGuideIcon")
        self.gcode_import_guide_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gcode_import_guide_icon.setFixedWidth(22)
        self.gcode_import_guide = QLabel(
            "Noch kein fertiger G-Code?\n"
            "Objekt im Slicer mit den gewünschten Einstellungen slicen → "
            "G-Code exportieren → G-Code anschließend hier im "
            f"{APP_NAME} importieren."
        )
        self.gcode_import_guide.setObjectName("gcodeImportGuide")
        self.gcode_import_guide.setWordWrap(True)
        gcode_guide_layout.addWidget(
            self.gcode_import_guide_icon,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        gcode_guide_layout.addWidget(self.gcode_import_guide, 1)
        source_layout.addWidget(self.gcode_import_guide_row)
        self.drop_zone = GCodeDropZone()
        self.drop_zone.file_selected.connect(self._on_file_selected)
        self.drop_zone.file_rejected.connect(self._show_input_error)
        self.drop_zone.reload_requested.connect(self.reload_gcode)
        self.drop_zone.remove_requested.connect(self.remove_gcode)
        source_layout.addWidget(self.drop_zone)
        self.gcode_progress_bar = QProgressBar()
        self.gcode_progress_bar.setObjectName("gcodeAnalysisProgressBar")
        self.gcode_progress_bar.setRange(0, 100)
        self.gcode_progress_bar.setValue(0)
        self.gcode_progress_bar.setFormat("%p %")
        self.gcode_progress_bar.hide()
        source_layout.addWidget(self.gcode_progress_bar)
        gcode_progress_status = QHBoxLayout()
        self.gcode_progress_icon_label = QLabel("○")
        self.gcode_progress_icon_label.setObjectName("progressStatusIcon")
        self.gcode_progress_status_label = QLabel("Noch keine Analyse gestartet")
        self.gcode_progress_status_label.setObjectName("gcodeProgressStatusLabel")
        self.gcode_progress_status_label.setWordWrap(True)
        gcode_progress_status.addWidget(
            self.gcode_progress_icon_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.gcode_progress_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        gcode_progress_status.addWidget(self.gcode_progress_status_label, 1)
        self.gcode_progress_status_widget = QWidget()
        self.gcode_progress_status_widget.setLayout(gcode_progress_status)
        self.gcode_progress_status_widget.hide()
        source_layout.addWidget(self.gcode_progress_status_widget)

        self.reconstructed_config_toggle = QPushButton(
            "Rekonstruierte Konfiguration anzeigen ▸"
        )
        self.reconstructed_config_toggle.setObjectName(
            "reconstructedConfigToggle"
        )
        self.reconstructed_config_toggle.setCheckable(True)
        self.reconstructed_config_toggle.setChecked(False)
        self.reconstructed_config_toggle.setVisible(False)
        self.reconstructed_config_text = QTextEdit()
        self.reconstructed_config_text.setObjectName(
            "reconstructedConfigText"
        )
        self.reconstructed_config_text.setReadOnly(True)
        self.reconstructed_config_text.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )
        self.reconstructed_config_text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.reconstructed_config_text.hide()
        self.reconstructed_config_toggle.toggled.connect(
            self._toggle_reconstructed_config
        )
        self.content_layout.addWidget(source_group)

        self.stl_notice_frame = QFrame()
        self.stl_notice_frame.setObjectName("stlNoticeFrame")
        stl_layout = QHBoxLayout(self.stl_notice_frame)
        stl_layout.setContentsMargins(10, 7, 10, 7)
        stl_icon = QLabel("ℹ")
        stl_icon.setObjectName("stlNoticeIcon")
        self.stl_mode_description = QLabel(
            "STL-Dateien bleiben allgemein anpassbar."
        )
        self.stl_mode_description.setObjectName("helpText")
        self.stl_mode_description.setWordWrap(True)
        self.stl_mode_status = QLabel("Analytischer STL-Fallback ist verfügbar.")
        self.stl_mode_status.setObjectName("outputModeStatus")
        self.stl_mode_status.setWordWrap(True)
        stl_text = QVBoxLayout()
        stl_text.setSpacing(2)
        stl_text.addWidget(self.stl_mode_description)
        stl_text.addWidget(self.stl_mode_status)
        stl_layout.addWidget(stl_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        stl_layout.addLayout(stl_text, 1)
        # Der dauerhafte Hinweis belegte viel Platz. Die gleiche Information
        # ist nun unaufdringlich und jederzeit über das Info-Symbol im Kopf
        # erreichbar; das alte Widget bleibt nur für API-Kompatibilität erhalten.
        self.stl_notice_frame.hide()

        slicer_group = SectionCard(
            "Slicer",
            collapsible=True,
            expanded=True,
        )
        self.slicer_group = slicer_group
        slicer_group.set_compact_summary_column()
        slicer_group.setProperty("role", "slicer")
        slicer_group.setProperty("outerDropdown", True)
        slicer_layout = slicer_group.content_layout

        # Search progress always forms the first block in the Slicer card.
        self.slicer_progress_bar = QProgressBar()
        self.slicer_progress_bar.setObjectName("slicerDiscoveryProgressBar")
        self.slicer_progress_bar.setRange(0, 100)
        self.slicer_progress_bar.setValue(0)
        self.slicer_progress_bar.setFormat("%p %")
        self.slicer_progress_bar.hide()
        self.slicer_progress_status_widget = QWidget()
        slicer_progress_status = QHBoxLayout(
            self.slicer_progress_status_widget
        )
        slicer_progress_status.setContentsMargins(0, 0, 0, 0)
        self.slicer_progress_icon_label = QLabel("○")
        self.slicer_progress_icon_label.setObjectName("progressStatusIcon")
        self.slicer_progress_status_label = QLabel(
            "Noch keine Slicer-Suche gestartet"
        )
        self.slicer_progress_status_label.setObjectName(
            "slicerProgressStatusLabel"
        )
        self.slicer_progress_status_label.setWordWrap(True)
        slicer_progress_status.addWidget(
            self.slicer_progress_icon_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.slicer_progress_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        slicer_progress_status.addWidget(
            self.slicer_progress_status_label,
            1,
        )
        self.slicer_progress_status_widget.hide()
        slicer_layout.addWidget(self.slicer_progress_bar)
        slicer_layout.addWidget(self.slicer_progress_status_widget)

        # Main Slicer content: general information on the left, all selectors
        # aligned in one dedicated column on the right.
        self.slicer_columns = ResponsiveCardGrid()
        self.slicer_columns.setObjectName("slicerColumns")
        slicer_information = QWidget()
        self.slicer_information_column = slicer_information
        slicer_information.setObjectName("slicerInformationColumn")
        slicer_information_layout = QVBoxLayout(slicer_information)
        slicer_information_layout.setContentsMargins(0, 0, 0, 0)
        slicer_information_layout.setSpacing(8)
        self.slicer_status_label = QLabel(
            "Installierte Slicer wurden noch nicht geprüft."
        )
        self.slicer_status_label.setObjectName("slicerStatusLabel")
        self.slicer_status_label.setWordWrap(True)
        self.slicer_status_label.setProperty("state", "pending")
        self.slicer_detail_label = QLabel(
            "Die Auswahl kann später jederzeit geändert werden. Nicht "
            "verifizierte Produkt- oder Profilangaben werden nicht behauptet."
        )
        self.slicer_detail_label.setObjectName("slicerDetailLabel")
        self.slicer_detail_label.setWordWrap(True)
        slicer_information_layout.addWidget(self.slicer_status_label)
        slicer_information_layout.addWidget(self.slicer_detail_label)
        slicer_information_layout.addStretch(1)

        slicer_selectors = QWidget()
        self.slicer_selector_column = slicer_selectors
        slicer_selectors.setObjectName("slicerSelectorColumn")
        slicer_selectors_layout = QVBoxLayout(slicer_selectors)
        self.slicer_selectors_layout = slicer_selectors_layout
        # A small bottom inset keeps the last combo box clear of the column
        # edge even with platform styles that paint one pixel beyond its hint.
        slicer_selectors_layout.setContentsMargins(0, 0, 0, 6)
        slicer_selectors_layout.setSpacing(6)
        self.slicer_combo = WheelSafeComboBox()
        self.slicer_combo.setObjectName("slicerSelection")
        self.slicer_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.slicer_combo.setMinimumContentsLength(18)
        self.slicer_combo.setFixedHeight(METRICS.form_control_height_px)
        self.slicer_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.slicer_combo.setEnabled(False)
        self.slicer_refresh_button = QPushButton("Erneut erkennen")
        self.slicer_refresh_button.setObjectName("slicerRefreshButton")
        self.slicer_manual_button = QPushButton(
            "Anderen Slicer auswählen …"
        )
        self.slicer_manual_button.setObjectName("slicerManualButton")
        self.slicer_selection_label = QLabel("Slicer")
        self.slicer_selection_label.setObjectName("slicerFieldTitle")
        self.slicer_selection_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        slicer_selectors_layout.addWidget(self.slicer_selection_label)
        slicer_selectors_layout.addWidget(self.slicer_combo)
        slicer_actions = QHBoxLayout()
        slicer_actions.addStretch(1)
        slicer_actions.addWidget(self.slicer_refresh_button)
        slicer_actions.addWidget(self.slicer_manual_button)
        slicer_selectors_layout.addLayout(slicer_actions)

        self.machine_profile_combo = WheelSafeComboBox()
        self.machine_profile_combo.setObjectName("machineProfileSelection")
        self.process_profile_combo = WheelSafeComboBox()
        self.process_profile_combo.setObjectName("processProfileSelection")
        self.filament_profile_combo = WheelSafeComboBox()
        self.filament_profile_combo.setObjectName("filamentProfileSelection")
        for combo in (
            self.machine_profile_combo,
            self.process_profile_combo,
            self.filament_profile_combo,
        ):
            combo.setEnabled(False)
            combo.setFixedHeight(METRICS.form_control_height_px)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(18)
        self.machine_profile_label = QLabel("Maschinenprofil")
        self.process_profile_label = QLabel("Prozessprofil")
        self.filament_profile_label = QLabel("Filamentprofil")
        for label, combo in (
            (self.machine_profile_label, self.machine_profile_combo),
            (self.process_profile_label, self.process_profile_combo),
            (self.filament_profile_label, self.filament_profile_combo),
        ):
            label.setObjectName("slicerFieldTitle")
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            slicer_selectors_layout.addWidget(label)
            slicer_selectors_layout.addWidget(combo)

        self.slicer_columns_divider = QFrame()
        self.slicer_columns_divider.setObjectName("slicerVerticalDivider")
        self.slicer_columns_divider.setFixedWidth(1)
        self.slicer_columns_divider.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        self.slicer_columns.set_vertical_separator(self.slicer_columns_divider)
        self.slicer_columns.add_pair(slicer_information, slicer_selectors)
        slicer_layout.addWidget(self.slicer_columns)

        self.slicer_details_divider = QFrame()
        self.slicer_details_divider.setObjectName("slicerHorizontalDivider")
        self.slicer_details_divider.setFixedHeight(1)
        slicer_layout.addWidget(self.slicer_details_divider)
        self.profile_status_label = QLabel(
            "Profilzuordnung beginnt nach G-Code- und Slicerauswahl."
        )
        self.profile_status_label.setObjectName("profileStatusLabel")
        self.profile_status_label.setWordWrap(True)
        self.profile_status_label.setProperty("state", "pending")
        self.profile_confirm_button = QPushButton("Profilzuordnung bestätigen")
        self.profile_confirm_button.setObjectName("profileConfirmButton")
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.hide()
        self.profile_origin_label = QLabel(
            "Herkunft der Zuordnung wird nach der Profilprüfung angezeigt."
        )
        self.profile_origin_label.setObjectName("profileOriginLabel")
        self.profile_origin_label.setWordWrap(True)
        self.profile_origin_label.hide()
        self.profile_diagnostics = QTextEdit()
        self.profile_diagnostics.setObjectName("profileDiagnostics")
        self.profile_diagnostics.setReadOnly(True)
        self.profile_diagnostics.setMaximumHeight(110)
        self.profile_diagnostics.hide()
        slicer_layout.addWidget(self.profile_status_label)
        slicer_layout.addWidget(self.profile_confirm_button)
        slicer_layout.addWidget(self.profile_origin_label)
        slicer_layout.addWidget(self.profile_diagnostics)
        # Embedded reconstruction remains independently expandable and starts
        # closed whenever a G-code is read.
        slicer_layout.addWidget(self.reconstructed_config_toggle)
        slicer_layout.addWidget(self.reconstructed_config_text)
        self._slicer_width_combos = (
            self.slicer_combo,
            self.machine_profile_combo,
            self.process_profile_combo,
            self.filament_profile_combo,
        )
        self._slicer_width_labels = (
            self.slicer_selection_label,
            self.machine_profile_label,
            self.process_profile_label,
            self.filament_profile_label,
        )
        self.content_layout.addWidget(slicer_group)

        timing_group = SectionCard(
            "Kühlzeit und Qualität",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.timing_group = timing_group
        timing_group.setProperty("role", "timing")
        timing_group.setProperty("outerDropdown", True)
        timing_layout = timing_group.content_layout
        self.target_time_spin = self._double_spin(
            0.01,
            MAXIMUM_TARGET_LAYER_TIME_S,
            2,
            1.0,
            "targetLayerTime",
        )
        self.safety_factor_spin = self._double_spin(1.0, 10.0, 3, 0.05, "safetyFactor")
        self._add_numeric_setting(
            timing_layout,
            "target_layer_time_s",
            "Gewünschte Mindest-Layerzeit",
            self.target_time_spin,
        )
        self._add_numeric_setting(
            timing_layout,
            "safety_factor",
            "Zeit-Sicherheitsfaktor",
            self.safety_factor_spin,
        )
        self.tower_need_label = QLabel("Bitte zuerst einen G-Code auswählen.")
        self.tower_need_label.setObjectName("towerNeedLabel")
        self.tower_need_label.setWordWrap(True)
        self.tower_need_label.setProperty("state", "pending")
        self.content_layout.addWidget(timing_group)

        geometry_group = SectionCard(
            "Abmessungen",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.geometry_group = geometry_group
        geometry_layout = geometry_group.content_layout
        self.geometry_fields_layout = geometry_layout
        self.minimum_outer_spin = self._double_spin(0.001, 500.0, 3, 0.5, "minimumOuterRadius")
        self.maximum_outer_spin = self._double_spin(0.001, 500.0, 3, 0.5, "maximumOuterRadius")
        self.minimum_wall_spin = self._double_spin(0.001, 100.0, 3, 0.1, "minimumWall")
        self.maximum_wall_spin = self._double_spin(0.001, 100.0, 3, 0.1, "maximumWall")
        self.path_width_spin = self._double_spin(0.001, 10.0, 3, 0.01, "wallPathWidth")
        self.minimum_inner_spin = self._double_spin(0.001, 500.0, 3, 0.5, "minimumInnerRadius")
        self.maximum_diameter_label = QLabel()
        self.maximum_diameter_label.setObjectName("helpText")
        self.maximum_diameter_label.setWordWrap(True)
        self.wall_paths_label = QLabel()
        self.wall_paths_label.setObjectName("calculatedHint")
        self.wall_paths_label.setWordWrap(True)
        self._add_numeric_setting(
            geometry_layout,
            "minimum_outer_radius_mm",
            "Kleinster Außenradius",
            self.minimum_outer_spin,
        )
        self._add_numeric_setting(
            geometry_layout,
            "maximum_outer_radius_mm",
            "Größter Außenradius",
            self.maximum_outer_spin,
        )
        geometry_layout.addWidget(self.maximum_diameter_label)
        self._add_numeric_setting(
            geometry_layout,
            "minimum_wall_thickness_mm",
            "Minimale Wandstärke",
            self.minimum_wall_spin,
        )
        self._add_numeric_setting(
            geometry_layout,
            "maximum_wall_thickness_mm",
            "Maximale Wandstärke",
            self.maximum_wall_spin,
        )
        self._add_numeric_setting(
            geometry_layout,
            "wall_path_width_mm",
            "Linienbreite der Wand",
            self.path_width_spin,
        )
        self._add_numeric_setting(
            geometry_layout,
            "minimum_inner_radius_mm",
            "Minimaler Hohlraumradius",
            self.minimum_inner_spin,
        )
        geometry_layout.addWidget(self.wall_paths_label)
        geometry_hint = QLabel(
            "Für eine 0,4-mm-Düse hier die tatsächlich im Slicer verwendete "
            "Linienbreite eintragen."
        )
        geometry_hint.setWordWrap(True)
        geometry_hint.setObjectName("helpText")
        geometry_layout.addWidget(geometry_hint)
        geometry_group.refresh_collapsed_state()
        self.content_layout.addWidget(geometry_group)

        stability_group = SectionCard(
            "Standfuß",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.stability_group = stability_group
        stability_layout = stability_group.content_layout
        # Let the nested calculation header span the same width as the other
        # geometry headers while the regular controls keep their body padding.
        stability_layout.setContentsMargins(0, 0, 0, 10)
        stability_layout.setSpacing(0)
        stability_fields = QWidget()
        stability_fields.setObjectName("stabilityFields")
        stability_fields_layout = QVBoxLayout(stability_fields)
        self.stability_fields_layout = stability_fields_layout
        stability_fields_layout.setContentsMargins(10, 10, 10, 0)
        stability_fields_layout.setSpacing(6)
        stability_fields_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        stability_layout.addWidget(stability_fields)
        self.automatic_base_checkbox = QCheckBox(
            "Standfußbreite automatisch berechnen"
        )
        self.automatic_base_checkbox.setObjectName("automaticBaseWidth")
        self.automatic_base_checkbox.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.automatic_base_checkbox.setMinimumWidth(220)
        self.automatic_base_checkbox.setFixedHeight(
            METRICS.form_control_height_px
        )
        self.automatic_base_checkbox.setToolTip(
            "Die Standfußbreite wird aus der vollständigen "
            "G-Code-Objekthöhe abgeleitet."
        )
        automatic_row = QWidget()
        automatic_layout = QGridLayout(automatic_row)
        automatic_layout.setContentsMargins(0, 2, 0, 2)
        self.automatic_base_info_button = InfoToolButton(
            "Ist die Automatik aktiv, wird die Standfußbreite aus der "
            "vollständigen Höhe des analysierten G-Codes berechnet. Nach dem "
            "Ausschalten kann der Außendurchmesser manuell eingegeben werden.",
            automatic_row,
            accessible_name=(
                "Informationen zur automatischen Standfußbreite"
            ),
            object_name="settingInfoButton",
            diameter_px=24,
        )
        self.automatic_base_error_label = QLabel()
        self.automatic_base_error_label.setObjectName("settingMessage")
        self.automatic_base_error_label.setWordWrap(True)
        self.automatic_base_error_label.hide()
        automatic_layout.addWidget(self.automatic_base_checkbox, 0, 0)
        automatic_layout.addWidget(
            self.automatic_base_info_button,
            0,
            1,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        automatic_layout.addWidget(
            self.automatic_base_error_label, 1, 0, 1, 2
        )
        automatic_layout.setColumnStretch(0, 0)
        automatic_layout.setColumnStretch(1, 1)
        self.manual_base_width_spin = self._double_spin(
            20.0, 1000.0, 2, 1.0, "manualBaseWidth"
        )
        self.automatic_base_width_label = QLabel(
            "Automatische Breite: mindestens 20,00 mm"
        )
        self.automatic_base_width_label.setObjectName("calculatedHint")
        self.automatic_base_width_label.setWordWrap(True)
        self.minimum_base_spin = self._double_spin(
            0.0, 500.0, 3, 0.5, "minimumBaseRadius"
        )
        self.base_height_spin = self._double_spin(0.0, 500.0, 3, 0.5, "baseHeight")
        self.base_margin_spin = self._double_spin(0.0, 500.0, 3, 0.5, "baseMargin")
        self.base_height_factor_spin = self._double_spin(
            0.0, 10.0, 4, 0.01, "baseHeightFactor"
        )
        self.maximum_radius_change_spin = self._double_spin(
            0.0, 100.0, 4, 0.05, "maximumRadiusChange"
        )
        self.maximum_expansion_angle_spin = self._double_spin(
            1.0,
            MAXIMUM_EXPANSION_ANGLE_DEG,
            1,
            1.0,
            "maximumExpansionAngle",
        )
        self.maximum_contraction_angle_spin = self._double_spin(
            1.0, 85.0, 1, 1.0, "maximumContractionAngle"
        )
        self.maximum_wall_change_spin = self._double_spin(0.0, 100.0, 4, 0.05, "maximumWallChange")
        stability_fields_layout.addWidget(automatic_row)
        manual_base_setting = self._add_numeric_setting(
            stability_fields_layout,
            "manual_base_width_mm",
            "Manuelle Standfußbreite",
            self.manual_base_width_spin,
        )
        # Compatibility alias for existing integrations. The reset now belongs
        # to the manual value row and can no longer overlap or sit above it.
        self.automatic_base_reset_button = manual_base_setting.reset_button
        stability_fields_layout.addWidget(self.automatic_base_width_label)
        self.base_height_setting = self._add_numeric_setting(
            stability_fields_layout,
            "base_height_mm",
            "Standfußhöhe",
            self.base_height_spin,
        )
        stability_group.refresh_collapsed_state()
        self.content_layout.addWidget(stability_group)

        overhang_group = SectionCard(
            "Überhänge",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.overhang_group = overhang_group
        overhang_layout = overhang_group.content_layout
        self.overhang_fields_layout = overhang_layout
        self.maximum_expansion_angle_setting = self._add_numeric_setting(
            overhang_layout,
            "maximum_expansion_angle_deg",
            "Maximaler Aufweitungswinkel zur Vertikalen",
            self.maximum_expansion_angle_spin,
        )
        self._add_numeric_setting(
            overhang_layout,
            "maximum_contraction_angle_deg",
            "Maximaler Verjüngungswinkel zur Vertikalen",
            self.maximum_contraction_angle_spin,
        )
        self._add_numeric_setting(
            overhang_layout,
            "maximum_wall_change_per_mm_z",
            "Max. Wandstärkenänderung",
            self.maximum_wall_change_spin,
        )
        overhang_group.refresh_collapsed_state()
        self.content_layout.addWidget(overhang_group)

        self.mesh_segments_spin = WheelSafeSpinBox()
        self.mesh_segments_spin.setObjectName("meshSegments")
        self.mesh_segments_spin.setProperty("validationMinimum", 3)
        self.mesh_segments_spin.setProperty("validationMaximum", 512)
        self.mesh_segments_spin.setRange(-1_000_000_000, 1_000_000_000)
        self.local_window_spin = WheelSafeSpinBox()
        self.local_window_spin.setObjectName("localReferenceWindow")
        self.local_window_spin.setProperty("validationMinimum", 1)
        self.local_window_spin.setProperty("validationMaximum", 999)
        self.local_window_spin.setRange(-1_000_000_000, 1_000_000_000)
        self.local_window_spin.setSingleStep(2)
        self.minimum_radius_height_factor_spin = self._double_spin(
            0.0, 10.0, 4, 0.01, "minimumRadiusHeightFactor"
        )

        # Calculation controls remain a separate, clearly named subsection in
        # the right geometry column instead of being assigned to Standfuß or
        # Überhänge.
        self.geometry_calculation_section = QFrame()
        self.geometry_calculation_section.setObjectName(
            "geometryCalculationSection"
        )
        calculation_layout = QVBoxLayout(
            self.geometry_calculation_section
        )
        calculation_layout.setContentsMargins(0, 10, 0, 0)
        calculation_layout.setSpacing(0)
        self.geometry_calculation_header = QFrame()
        self.geometry_calculation_header.setObjectName(
            "geometryCalculationHeader"
        )
        calculation_header_layout = QVBoxLayout(
            self.geometry_calculation_header
        )
        calculation_header_layout.setContentsMargins(0, 0, 0, 0)
        calculation_header_layout.setSpacing(0)
        self.geometry_calculation_title = QLabel(
            "Auflösung und Zeitfenster"
        )
        self.geometry_calculation_title.setObjectName(
            "sectionCardTitle"
        )
        self.geometry_calculation_title.setProperty(
            "subsectionHeader",
            True,
        )
        calculation_header_layout.addWidget(
            self.geometry_calculation_title
        )
        self.geometry_calculation_header_divider = QFrame()
        self.geometry_calculation_header_divider.setObjectName(
            "geometrySubsectionDivider"
        )
        self.geometry_calculation_header_divider.setFixedHeight(1)
        calculation_header_layout.addWidget(
            self.geometry_calculation_header_divider
        )
        calculation_layout.addWidget(self.geometry_calculation_header)
        self.geometry_calculation_body = QWidget()
        self.geometry_calculation_body.setObjectName(
            "geometryCalculationBody"
        )
        calculation_body_layout = QVBoxLayout(
            self.geometry_calculation_body
        )
        self.geometry_calculation_body_layout = calculation_body_layout
        calculation_body_layout.setContentsMargins(10, 4, 10, 0)
        calculation_body_layout.setSpacing(4)
        self._add_numeric_setting(
            calculation_body_layout,
            "mesh_segments",
            "Kreissegmente",
            self.mesh_segments_spin,
        )
        self._add_numeric_setting(
            calculation_body_layout,
            "local_reference_window",
            "Layer im lokalen Zeitfenster",
            self.local_window_spin,
        )
        calculation_layout.addWidget(self.geometry_calculation_body)

        self.additional_options_content = QWidget(self)
        self.additional_options_content.setObjectName(
            "additionalOptionsContent"
        )
        self.additional_options_content.hide()
        options_layout = QVBoxLayout(self.additional_options_content)
        options_layout.setContentsMargins(18, 18, 18, 18)
        options_layout.setSpacing(10)
        options_title = QLabel("Ausgabeordner ändern")
        options_title.setObjectName("dialogTitle")
        options_layout.addWidget(options_title)
        options_description = QLabel(
            "Hier legen Sie programmweite Ausgabeoptionen fest."
        )
        options_description.setObjectName("helpText")
        options_description.setWordWrap(True)
        options_layout.addWidget(options_description)

        output_path_layout = QGridLayout()
        self.output_root_info_button = InfoToolButton(
            "Basisordner für Zeitstempel-Unterordner, STL-Dateien, Berichte "
            "und Fehlerprotokolle. Vorhandene Ausgabedateien werden nicht "
            "überschrieben.",
            self.additional_options_content,
            accessible_name="Informationen zum Basis-Ausgabeordner",
            object_name="settingInfoButton",
            diameter_px=24,
        )
        self.output_root_edit = QLineEdit()
        self.output_root_edit.setObjectName("outputRoot")
        self.output_root_edit.setMinimumHeight(32)
        self.output_browse_button = QPushButton("Auswählen …")
        self.output_browse_button.setIcon(
            QIcon(str(GUI_ASSET_ROOT / "folder.svg"))
        )
        self.output_browse_button.setIconSize(QSize(18, 18))
        self.output_browse_button.clicked.connect(self.select_output_root)
        self.output_root_reset_button = QPushButton("")
        self.output_root_reset_button.setObjectName("settingResetButton")
        self.output_root_reset_button.setIcon(
            QIcon(str(GUI_ASSET_ROOT / "reset.svg"))
        )
        self.output_root_reset_button.setIconSize(QSize(18, 18))
        self.output_root_reset_button.setFixedSize(
            METRICS.reset_button_size_px,
            METRICS.reset_button_size_px,
        )
        self.output_root_reset_button.setToolTip(
            "Ausgabeordner auf Standardwert zurücksetzen"
        )
        self.output_root_reset_button.setAccessibleName(
            "Ausgabeordner auf Standardwert zurücksetzen"
        )
        self.output_root_error_label = QLabel()
        self.output_root_error_label.setObjectName("settingMessage")
        self.output_root_error_label.setWordWrap(True)
        self.output_root_error_label.hide()
        output_path_layout.addWidget(
            self.output_root_info_button,
            0,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        output_path_layout.addWidget(self.output_root_edit, 0, 1)
        output_path_layout.addWidget(self.output_browse_button, 0, 2)
        output_path_layout.addWidget(self.output_root_reset_button, 0, 3)
        output_path_layout.addWidget(
            self.output_root_error_label, 1, 0, 1, 4
        )
        output_path_layout.setColumnStretch(1, 1)
        options_layout.addWidget(QLabel("Basis-Ausgabeordner"))
        options_layout.addLayout(output_path_layout)
        self.prediction_frame = SectionCard(
            "Prognose",
            collapsible=True,
            expanded=True,
            state=SectionState.PREVIEW,
        )
        self.prediction_frame.setProperty("role", "prediction")
        self.prediction_frame.setProperty("cardTone", "preview")
        self.prediction_frame.setProperty("outerDropdown", True)
        prediction_layout = self.prediction_frame.content_layout
        self.prediction_method_label = QLabel("Noch nicht verfügbar")
        self.prediction_method_label.setObjectName("predictionMethodBadge")
        self.prediction_method_label.setProperty("mode", "pending")
        self.prediction_label = QLabel(
            "Die Schätzung ist nach der G-Code- und Geometrieanalyse verfügbar."
        )
        self.prediction_label.setObjectName("predictionLabel")
        self.prediction_label.setWordWrap(True)
        self.prediction_label.setProperty("state", "pending")
        prediction_grid = QGridLayout()
        prediction_grid.setHorizontalSpacing(10)
        prediction_grid.setVerticalSpacing(5)
        self.prediction_value_labels: dict[str, QLabel] = {}
        self.prediction_value_icons: dict[str, QLabel] = {}
        for row, (key, icon, caption) in enumerate(PREDICTION_ROWS):
            caption_widget = QWidget()
            caption_layout = QHBoxLayout(caption_widget)
            caption_layout.setContentsMargins(0, 0, 0, 0)
            caption_layout.setSpacing(5)
            icon_label = QLabel(icon)
            icon_label.setObjectName("predictionValueIcon")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setAccessibleName(f"Symbol für {caption}")
            caption_label = QLabel(caption)
            caption_label.setObjectName("predictionCaption")
            caption_label.setWordWrap(True)
            caption_label.setMinimumWidth(120)
            caption_layout.addWidget(
                icon_label,
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
            caption_layout.addWidget(caption_label, 1)
            value_label = QLabel("–")
            value_label.setObjectName("predictionValue")
            value_label.setWordWrap(True)
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setMinimumWidth(105)
            self.prediction_value_icons[key] = icon_label
            self.prediction_value_labels[key] = value_label
            prediction_grid.addWidget(caption_widget, row, 0)
            prediction_grid.addWidget(value_label, row, 1)

        self.prediction_advice_frame = QFrame()
        self.prediction_advice_frame.setObjectName("predictionAdviceFrame")
        self.prediction_advice_frame.setMinimumWidth(190)
        self.prediction_advice_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        advice_layout = QVBoxLayout(self.prediction_advice_frame)
        advice_layout.setContentsMargins(0, 0, 0, 0)
        advice_layout.setSpacing(0)
        self.prediction_advice_content = QWidget(
            self.prediction_advice_frame
        )
        self.prediction_advice_content.setObjectName(
            "predictionAdviceContent"
        )
        advice_content_layout = QVBoxLayout(
            self.prediction_advice_content
        )
        advice_content_layout.setContentsMargins(8, 8, 8, 8)
        advice_content_layout.setSpacing(5)
        self.prediction_advice_label = QLabel()
        self.prediction_advice_label.setObjectName("predictionAdviceText")
        self.prediction_advice_label.setWordWrap(True)
        self.prediction_advice_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.prediction_advice_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.slicer_prediction_button = QPushButton(
            "Slicer-Schätzung\ndurchführen"
        )
        self.slicer_prediction_button.setObjectName("slicerPredictionButton")
        self.slicer_prediction_button.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.slicer_prediction_button.setVisible(False)
        self.slicer_prediction_button.clicked.connect(
            self.start_slicer_prediction
        )
        self.slicer_prediction_status_label = QLabel()
        self.slicer_prediction_status_label.setObjectName(
            "slicerPredictionStatus"
        )
        self.slicer_prediction_status_label.setWordWrap(True)
        self.slicer_prediction_status_label.hide()
        advice_content_layout.addWidget(self.prediction_advice_label)
        advice_content_layout.addWidget(
            self.slicer_prediction_status_label
        )
        advice_layout.addWidget(self.prediction_advice_content)
        advice_layout.addWidget(self.slicer_prediction_button)

        prediction_grid.setColumnStretch(0, 3)
        prediction_grid.setColumnStretch(1, 2)
        self.prediction_grid = prediction_grid
        self.prediction_primary_widget = QWidget()
        self.prediction_primary_widget.setObjectName(
            "predictionPrimaryColumn"
        )
        prediction_primary_layout = QVBoxLayout(
            self.prediction_primary_widget
        )
        prediction_primary_layout.setContentsMargins(0, 0, 0, 0)
        prediction_primary_layout.setSpacing(6)
        prediction_primary_layout.addWidget(
            self.prediction_method_label,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        prediction_primary_layout.addWidget(self.prediction_label)
        prediction_primary_layout.addLayout(prediction_grid)

        self.prediction_content_grid = QGridLayout()
        self.prediction_content_grid.setContentsMargins(0, 0, 0, 0)
        self.prediction_content_grid.setHorizontalSpacing(10)
        self.prediction_content_grid.setVerticalSpacing(0)
        self.prediction_content_grid.addWidget(
            self.prediction_primary_widget,
            0,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self.prediction_content_grid.addWidget(
            self.prediction_advice_frame,
            0,
            1,
            Qt.AlignmentFlag.AlignTop,
        )
        self.prediction_content_grid.setColumnStretch(0, 5)
        self.prediction_content_grid.setColumnStretch(1, 4)
        prediction_layout.addLayout(self.prediction_content_grid)
        self.layer_time_check_hint = QLabel(
            "Bitte überprüfen Sie die endgültige Layerzeit nach dem gemeinsamen "
            "Slicen von Objekt und Kühlturm."
        )
        self.layer_time_check_hint.setObjectName("predictionFootnote")
        self.layer_time_check_hint.setWordWrap(True)
        prediction_layout.addWidget(self.tower_need_label)
        prediction_layout.addWidget(self.layer_time_check_hint)
        self.preview_hint_label = QLabel(
            "Beim Export wird der Kühlturm immer mit den aktuellen "
            "Einstellungen erzeugt."
        )
        self.preview_hint_label.setObjectName("previewHintLabel")
        self.preview_hint_label.setWordWrap(True)
        options_layout.addWidget(self.preview_hint_label)
        options_actions = QHBoxLayout()
        options_actions.addStretch(1)
        self.additional_options_close_button = QPushButton("Schließen")
        self.additional_options_close_button.clicked.connect(
            self._close_additional_options
        )
        options_actions.addWidget(self.additional_options_close_button)
        options_layout.addLayout(options_actions)
        # Abmessungen remain in the left geometry column. Standfuß,
        # Überhänge and the calculation controls form independent subsections
        # in the right column.
        self.geometry_settings_group = SectionCard(
            "Turmgeometrie",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.geometry_settings_group.setProperty("role", "geometrySettings")
        self.geometry_settings_group.setProperty("outerDropdown", True)
        self.geometry_settings_group.content_layout.setContentsMargins(
            0, 0, 0, 0
        )
        geometry_group.setCheckable(False)
        stability_group.setCheckable(False)
        overhang_group.setCheckable(False)
        geometry_group.setProperty("subsection", "left")
        stability_group.setProperty("subsection", "right")
        overhang_group.setProperty("subsection", "right")
        self.geometry_right_column = QWidget()
        self.geometry_right_column.setObjectName("geometryRightColumn")
        self.geometry_right_column.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.geometry_right_layout = QVBoxLayout(
            self.geometry_right_column
        )
        self.geometry_right_layout.setContentsMargins(0, 0, 0, 0)
        self.geometry_right_layout.setSpacing(0)
        self.geometry_right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.geometry_right_layout.addWidget(stability_group)
        self.geometry_right_layout.addWidget(overhang_group)
        self.geometry_right_layout.addWidget(
            self.geometry_calculation_section
        )
        self.geometry_split = ResponsiveCardGrid()
        self.geometry_split.setObjectName("geometrySettingsSplit")
        self.geometry_vertical_divider = QFrame()
        self.geometry_vertical_divider.setObjectName(
            "geometryVerticalDivider"
        )
        self.geometry_vertical_divider.setFixedWidth(1)
        self.geometry_vertical_divider.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        self.geometry_split.set_vertical_separator(
            self.geometry_vertical_divider
        )

        # Nach G-Code und Slicer folgt die eigentliche Arbeitsfläche: bei
        # genügend Platz zweispaltig, in schmalen Fenstern sauber gestapelt.
        for card in (
            timing_group,
            geometry_group,
            stability_group,
            overhang_group,
        ):
            self.content_layout.removeWidget(card)
        self.geometry_split.add_pair(
            geometry_group,
            self.geometry_right_column,
        )
        self.geometry_settings_group.content_layout.addWidget(self.geometry_split)
        self.geometry_settings_group.toggled.connect(
            lambda expanded: self._sync_collapsible_content(
                "geometry_settings", expanded
            )
        )
        self.ready_grid = ResponsiveCardGrid()
        self.ready_grid.setObjectName("readySettingsGrid")
        self.ready_grid.add_pair(
            timing_group,
            self.prediction_frame,
            equal_height=False,
            stacked_right_first=True,
        )
        self.ready_grid.add_full_width(self.geometry_settings_group)
        self.content_layout.addWidget(self.ready_grid)
        # Keep this workflow block pinned to the top when its final row is
        # expanded or collapsed.
        self.content_layout.setAlignment(
            self.ready_grid,
            Qt.AlignmentFlag.AlignTop,
        )
        # A trailing stretch keeps the initial G-Code card at its natural
        # height instead of letting it consume the entire scroll viewport.
        self.content_layout.addStretch(1)

        source_group.toggled.connect(
            lambda _expanded: self._refresh_settings_content_minimum_height()
        )
        slicer_group.toggled.connect(self._refresh_slicer_section_layout)
        timing_group.toggled.connect(
            lambda _expanded: self._refresh_ready_grid_layout()
        )
        self.prediction_frame.toggled.connect(
            lambda _expanded: self._refresh_ready_grid_layout()
        )
        self.geometry_settings_group.toggled.connect(
            self._refresh_geometry_section_layout
        )

        workflow_widgets = (self.ready_grid,)

        self.workflow = WorkflowController(
            source_card=source_group,
            slicer_card=slicer_group,
            downstream_widgets=workflow_widgets,
            parent=self,
        )

        self.preview_button = QPushButton("Vorschau erstellen")
        self.preview_button.setObjectName("previewButton")
        self.preview_button.clicked.connect(self.start_preview)
        self.export_button = QPushButton("Kühlturm exportieren")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.start_export)

        self.settings_scroll.setWidget(content)
        root_layout.addWidget(self.settings_scroll, 1)

        footer = QWidget()
        self.footer = footer
        footer.setObjectName("mainFooter")
        footer.setMaximumHeight(MAIN_FOOTER_MAX_HEIGHT_PX)
        footer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        footer_layout = QVBoxLayout(footer)
        self.footer_layout = footer_layout
        footer_layout.setContentsMargins(22, 8, 22, 18)
        footer_layout.setSpacing(8)

        self.validation_label = _FooterIssueLabel()
        self.validation_label.setObjectName("errorLabel")
        self.validation_label.setWordWrap(True)
        self.error_panel = FooterNoticeDropdown(
            "✕  Eingaben prüfen",
            severity="error",
        )
        error_layout = self.error_panel.content_layout
        self.error_title = self.error_panel.header_button
        error_layout.addWidget(self.validation_label)
        self.error_panel.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("mainProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p %")
        self.progress_bar.hide()
        self.status_label = QLabel("Bitte G-Code auswählen")
        self.status_label.setObjectName("statusLabel")
        self.status_icon_label = QLabel("⇧")
        self.status_icon_label.setObjectName("progressStatusIcon")
        self.status_icon_label.setProperty("prominent", True)
        self.result_label = QLabel("")
        self.result_label.setObjectName("resultLabel")
        self.result_label.setWordWrap(True)
        self.settings_load_notice_label = QLabel("")
        self.settings_load_notice_label.setObjectName(
            "settingsLoadNoticeLabel"
        )
        self.settings_load_notice_label.setWordWrap(True)
        self.settings_load_notice_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.settings_load_notice_panel = FooterNoticeDropdown(
            "⚠  Gespeicherte Einstellungen geschützt",
            severity="warning",
        )
        self.settings_load_notice_panel.content_layout.addWidget(
            self.settings_load_notice_label
        )
        self.settings_load_notice_panel.hide()
        self.warning_text = AutoHeightTextEdit(
            minimum_height=24,
            maximum_height=112,
        )
        self.warning_text.setObjectName("warningText")
        self.warning_text.hide()
        self.notice_panel = FooterNoticeDropdown(
            "⚠  Hinweise",
            severity="warning",
        )
        notice_layout = self.notice_panel.content_layout
        self.notice_title = self.notice_panel.header_button
        notice_layout.addWidget(self.warning_text)
        self.notice_panel.hide()
        self.export_availability_label = QLabel(
            "Export/Vorschau nicht möglich: Bitte zuerst einen G-Code auswählen."
        )
        self.export_availability_label.setObjectName(
            "exportAvailabilityLabel"
        )
        self.export_availability_label.setWordWrap(True)
        self.action_availability_widget = QFrame()
        self.action_availability_widget.setObjectName(
            "actionAvailabilityNotice"
        )
        action_notice_layout = QHBoxLayout(
            self.action_availability_widget
        )
        action_notice_layout.setContentsMargins(0, 2, 0, 2)
        action_notice_layout.setSpacing(7)
        self.action_availability_icon = QLabel("⚠")
        self.action_availability_icon.setObjectName(
            "actionAvailabilityIcon"
        )
        self.action_availability_icon.setAlignment(
            Qt.AlignmentFlag.AlignVCenter
        )
        action_notice_layout.addWidget(self.action_availability_icon)
        action_notice_layout.addWidget(self.export_availability_label, 1)
        self.open_output_button = QPushButton("Outputordner öffnen")
        self.open_output_button.setObjectName("openBaseOutputFolderButton")
        self.open_output_button.setToolTip(
            "Den in den Optionen festgelegten Output-Basisordner öffnen"
        )
        self.open_stl_button = QPushButton("Exportordner öffnen")
        self.open_stl_button.setObjectName("openOutputFolderButton")
        self.open_stl_button.setToolTip(
            "Den Ordner des zuletzt exportierten Kühlturms öffnen"
        )
        self.open_run_button = QPushButton("Letzten Kurzbericht öffnen")
        self.open_output_button.setEnabled(False)
        self.open_stl_button.setEnabled(False)
        self.open_run_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_directory)
        self.open_stl_button.clicked.connect(self.open_stl_directory)
        self.open_run_button.clicked.connect(self.open_run_directory)
        self.open_run_button.hide()

        self.preview_quality_panel = QWidget()
        self.preview_quality_panel.setObjectName("previewQualityPanel")
        self.preview_quality_panel.setAccessibleName(
            "Vorschauqualität auswählen"
        )
        preview_quality_layout = QHBoxLayout(self.preview_quality_panel)
        preview_quality_layout.setContentsMargins(0, 0, 0, 0)
        preview_quality_layout.setSpacing(0)
        self.preview_quality_selector = QFrame()
        self.preview_quality_selector.setObjectName("previewQualitySelector")
        quality_buttons_layout = QHBoxLayout(self.preview_quality_selector)
        quality_buttons_layout.setContentsMargins(0, 0, 0, 0)
        quality_buttons_layout.setSpacing(0)
        self.preview_quality_group = QButtonGroup(self)
        self.preview_quality_group.setExclusive(True)
        self.preview_quality_buttons: dict[str, QToolButton] = {}
        quality_options = (
            (
                "fast",
                "Schnell",
                "1 Slicer-Durchlauf – kürzeste Wartezeit, "
                "geringste Genauigkeit.",
            ),
            (
                "balanced",
                "Mittel",
                "3 Slicer-Durchläufe – guter Kompromiss aus "
                "Geschwindigkeit und Genauigkeit.",
            ),
            (
                "exact",
                "Exakt",
                "5 Slicer-Durchläufe – höchste Genauigkeit, "
                "längste Wartezeit.",
            ),
        )
        for index, (quality, label, description) in enumerate(quality_options):
            button = QToolButton()
            button.setObjectName("previewQualityButton")
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(f"{label}: {description}")
            button.setAccessibleName(
                f"Vorschauqualität {label}: {description}"
            )
            button.setProperty("quality", quality)
            button.setProperty(
                "segment",
                "first"
                if index == 0
                else "last"
                if index == len(quality_options) - 1
                else "middle",
            )
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
            button.setFixedHeight(24)
            self.preview_quality_group.addButton(button)
            self.preview_quality_buttons[quality] = button
            quality_buttons_layout.addWidget(button, 1)
        self.preview_quality_buttons[DEFAULT_PREVIEW_QUALITY].setChecked(True)
        self.preview_quality_group.buttonToggled.connect(
            self._on_preview_quality_toggled
        )
        preview_quality_layout.addWidget(self.preview_quality_selector, 1)
        self.preview_quality_panel.setFixedHeight(24)

        self.preview_action_control = QFrame()
        self.preview_action_control.setObjectName("previewActionControl")
        self.preview_action_control.setFixedWidth(
            PREVIEW_ACTION_COMPACT_WIDTH_PX
        )
        preview_action_layout = QVBoxLayout(self.preview_action_control)
        preview_action_layout.setContentsMargins(0, 0, 0, 0)
        preview_action_layout.setSpacing(0)
        preview_action_layout.addWidget(self.preview_quality_panel)
        preview_action_layout.addWidget(self.preview_button)

        main_actions = QGridLayout()
        self.main_actions_layout = main_actions
        main_actions.setContentsMargins(0, 4, 0, 0)
        main_actions.setHorizontalSpacing(8)
        main_actions.setVerticalSpacing(0)
        main_actions.addWidget(
            self.open_output_button,
            0,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(
            self.open_stl_button,
            0,
            1,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(
            self.preview_action_control,
            0,
            3,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(
            self.export_button,
            0,
            4,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(self.open_run_button, 0, 5)
        main_actions.setColumnStretch(2, 1)
        for column in (0, 1, 3, 4, 5):
            main_actions.setColumnStretch(column, 0)

        self.workflow.stage_changed.connect(self._on_workflow_stage_changed)
        self._on_workflow_stage_changed(self.workflow.stage.value)

        main_status_layout = QHBoxLayout()
        main_status_layout.setContentsMargins(0, 0, 0, 0)
        main_status_layout.setSpacing(6)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        main_status_layout.addWidget(
            self.status_icon_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        main_status_layout.addWidget(self.status_label, 1)

        self.footer_status_widget = QWidget()
        self.footer_status_widget.setObjectName("footerStatusContent")
        self.footer_status_layout = QVBoxLayout(
            self.footer_status_widget
        )
        self.footer_status_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_status_layout.setSpacing(6)
        self.footer_status_layout.addWidget(self.progress_bar)
        self.footer_status_layout.addLayout(main_status_layout)
        self.footer_status_layout.addWidget(self.result_label)

        self._footer_notice_panels = {
            "error": [self.error_panel],
            "warning": [
                self.settings_load_notice_panel,
                self.notice_panel,
            ],
            "info": [],
        }
        self.footer_notice_host = QWidget()
        self.footer_notice_host.setObjectName("footerNoticeHost")
        self.footer_notice_layout = QVBoxLayout(self.footer_notice_host)
        self.footer_notice_layout.setContentsMargins(0, 0, 4, 0)
        self.footer_notice_layout.setSpacing(6)
        self.footer_notice_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for severity in ("error", "warning", "info"):
            for panel in self._footer_notice_panels[severity]:
                self.footer_notice_layout.addWidget(panel)
                panel.toggled.connect(
                    lambda _expanded: self._schedule_footer_height_update()
                )
        self._last_footer_notice_signature: tuple[int, ...] = ()

        self.footer_messages_scroll = QScrollArea()
        self.footer_messages_scroll.setObjectName(
            "footerMessagesScroll"
        )
        self.footer_messages_scroll.setWidgetResizable(True)
        self.footer_messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.footer_messages_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.footer_messages_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.footer_messages_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.footer_messages_content = QWidget()
        self.footer_messages_content.setObjectName(
            "footerMessagesContent"
        )
        self.footer_messages_layout = QVBoxLayout(
            self.footer_messages_content
        )
        self.footer_messages_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_messages_layout.setSpacing(8)
        self.footer_messages_layout.addWidget(self.footer_notice_host)
        self.footer_messages_layout.addWidget(self.footer_status_widget)
        self.footer_messages_scroll.setWidget(
            self.footer_messages_content
        )
        self._refresh_footer_notice_layout()

        self.footer_action_area = QWidget()
        self.footer_action_area.setObjectName("footerActionArea")
        self.footer_action_layout = QVBoxLayout(self.footer_action_area)
        self.footer_action_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_action_layout.setSpacing(8)
        self.footer_action_layout.addWidget(self.action_availability_widget)
        self.footer_action_layout.addStretch(1)
        self.footer_action_layout.addLayout(main_actions)

        # Responsive layout code toggles these dividers before inserting them
        # into the current grid position.  Owning them from the hidden footer
        # prevents that initial toggle from creating a native top-level window.
        self.footer_vertical_divider = QFrame(footer)
        self.footer_vertical_divider.setObjectName("footerVerticalDivider")
        self.footer_vertical_divider.setFixedWidth(1)
        self.footer_horizontal_divider = QFrame(footer)
        self.footer_horizontal_divider.setObjectName("footerHorizontalDivider")
        self.footer_horizontal_divider.setFixedHeight(1)

        self.footer_content_widget = QWidget()
        self.footer_content_widget.setObjectName("footerContent")
        self.footer_content_grid = QGridLayout(self.footer_content_widget)
        self.footer_content_grid.setContentsMargins(0, 0, 0, 0)
        self.footer_content_grid.setHorizontalSpacing(12)
        self.footer_content_grid.setVerticalSpacing(8)
        footer_layout.addWidget(self.footer_content_widget)
        self._footer_narrow_layout: bool | None = None
        self._refresh_footer_responsive_layout(force=True)
        root_layout.addWidget(footer)
        self.setCentralWidget(central)
        self._footer_height_timer = QTimer(self)
        self._footer_height_timer.setSingleShot(True)
        self._footer_height_timer.timeout.connect(
            self._fit_footer_height
        )
        self._footer_height_timer.start(0)

        self.automatic_base_checkbox.stateChanged.connect(
            self._on_base_mode_changed
        )
        self.output_root_reset_button.clicked.connect(
            self._reset_output_root
        )
        self.output_root_edit.textChanged.connect(
            self._on_output_root_changed
        )
        self.slicer_refresh_button.clicked.connect(
            lambda: self.start_slicer_discovery(force=True)
        )
        self.slicer_manual_button.clicked.connect(
            self.select_manual_slicer
        )
        self.slicer_combo.currentIndexChanged.connect(
            self._on_slicer_selection_changed
        )
        self.machine_profile_combo.currentIndexChanged.connect(
            lambda _index: self._on_profile_selection_changed("machine")
        )
        self.process_profile_combo.currentIndexChanged.connect(
            lambda _index: self._on_profile_selection_changed("process")
        )
        self.filament_profile_combo.currentIndexChanged.connect(
            lambda _index: self._on_profile_selection_changed("filament")
        )
        self.profile_confirm_button.clicked.connect(
            self.confirm_profile_selection
        )

    def _on_workflow_stage_changed(self, stage_value: str) -> None:
        """Show fixed footer actions only after both prerequisites succeeded."""

        actions_visible = stage_value == WorkflowStage.READY.value
        self._set_setting_feedback_enabled(actions_visible)
        for widget in (
            self.open_output_button,
            self.open_stl_button,
            self.reset_button,
            self.preview_action_control,
            self.preview_button,
            *self.preview_quality_buttons.values(),
            self.export_button,
        ):
            widget.setVisible(actions_visible)
        if not actions_visible and hasattr(self, "action_availability_widget"):
            self.export_availability_label.clear()
            self.action_availability_widget.hide()
        if actions_visible and hasattr(self, "geometry_settings_group"):
            # The workflow area receives its real width only after becoming
            # visible. Re-measure after layout activation so a construction-
            # time height from the hidden 100 px geometry cannot survive.
            for delay_ms in (0, 40):
                QTimer.singleShot(
                    delay_ms,
                    lambda: self._refresh_geometry_section_layout(
                        self.geometry_settings_group.isChecked()
                    ),
                )
        self._refresh_folder_action_states()
        if hasattr(self, "validation_label"):
            if actions_visible:
                self.validate_form()
            else:
                self._apply_inline_errors({})
                self._refresh_collapsible_error_badges({})
                self.validation_label.clear()
                self._refresh_issue_panels()
        self._refresh_footer_auxiliary_visibility()
        self._schedule_footer_height_update()

    def _set_setting_feedback_enabled(self, enabled: bool) -> None:
        """Gate setting hints until G-code and slicer are both available."""

        for setting in self._setting_widgets.values():
            setting.set_feedback_enabled(enabled)

    def _setting_feedback_is_available(self) -> bool:
        workflow = getattr(self, "workflow", None)
        return workflow is not None and workflow.stage == WorkflowStage.READY

    @staticmethod
    def _double_spin(
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
        object_name: str,
    ) -> QDoubleSpinBox:
        widget = WheelSafeDoubleSpinBox()
        widget.setObjectName(object_name)
        widget.setProperty("validationMinimum", minimum)
        widget.setProperty("validationMaximum", maximum)
        # Preserve deliberately entered out-of-range values. The intended
        # domain above is validated live instead of silently clamping edits.
        widget.setRange(-1_000_000_000.0, 1_000_000_000.0)
        widget.setDecimals(decimals)
        widget.setSingleStep(step)
        widget.setKeyboardTracking(True)
        return widget

    def _add_numeric_setting(
        self,
        layout: QVBoxLayout,
        setting_name: str,
        label: str,
        editor: QDoubleSpinBox | QSpinBox,
        helper_text: str = "",
        info_text: str | None = None,
        default_value: int | float | None = None,
    ) -> NumericSettingWidget:
        if setting_name == "maximum_wall_change_per_mm_z":
            editor.setProperty("rangeLabelDecimals", 2)
            editor.setProperty("rangeLabelHideUnit", True)
        default_provider = (
            (lambda value=default_value: value)
            if default_value is not None
            else lambda name=setting_name: getattr(
                self.settings_store.load_defaults(), name
            )
        )
        setting_widget = NumericSettingWidget(
            setting_name=setting_name,
            label=label,
            editor=editor,
            default_provider=default_provider,
            unit=SETTING_UNITS.get(setting_name, ""),
            helper_text=helper_text,
            info_text=(
                SETTING_INFO_TEXTS.get(setting_name, "")
                if info_text is None
                else info_text
            ),
        )
        self._setting_widgets[setting_name] = setting_widget
        editor.valueChanged.connect(self._on_value_changed)
        setting_widget.input_state_changed.connect(
            self._on_numeric_input_state_changed
        )
        setting_widget.reset_performed.connect(
            self._on_individual_reset
        )
        layout.addWidget(setting_widget)
        return setting_widget

    def start_update_check(self) -> None:
        if (
            self._closing
            or not self._update_check_enabled
            or self.background_job_manager.has_active(JobKind.UPDATE_CHECK)
        ):
            return
        self._update_check_request_id += 1
        request_id = self._update_check_request_id
        worker = UpdateCheckWorker(
            request_id,
            APP_VERSION,
            self.update_service,
        )
        worker.succeeded.connect(self._on_update_check_succeeded)
        worker.failed.connect(self._on_update_check_failed)
        self.background_job_manager.start_job(
            kind=JobKind.UPDATE_CHECK,
            request_id=request_id,
            worker=worker,
        )

    def _on_update_check_succeeded(
        self,
        request_id: int,
        update_info: UpdateInfo | None,
    ) -> None:
        if request_id != self._update_check_request_id or self._closing:
            return
        self.available_update = update_info
        if update_info is None:
            self.update_button.hide()
            return
        self.update_button.setText("Aktualisieren")
        self.update_button.setToolTip(
            f"Version {update_info.version} herunterladen und installieren"
        )
        self.update_button.setEnabled(True)
        self.update_button.show()

    def _on_update_check_failed(
        self,
        request_id: int,
        _message: str,
        _details: str,
    ) -> None:
        if request_id != self._update_check_request_id or self._closing:
            return
        # Update checks must never disturb offline use of the application.
        self.available_update = None
        self.update_button.hide()

    def start_update_download(self) -> None:
        if (
            self._closing
            or self.available_update is None
            or self.background_job_manager.has_active(JobKind.UPDATE_DOWNLOAD)
        ):
            return
        self._update_download_request_id += 1
        request_id = self._update_download_request_id
        self.update_button.setEnabled(False)
        self.update_button.setText("Lädt … 0 %")
        worker = UpdateDownloadWorker(
            request_id,
            self.available_update,
            self.update_service,
        )
        worker.progress.connect(self._on_update_download_progress)
        worker.succeeded.connect(self._on_update_download_succeeded)
        worker.failed.connect(self._on_update_download_failed)
        self.background_job_manager.start_job(
            kind=JobKind.UPDATE_DOWNLOAD,
            request_id=request_id,
            worker=worker,
        )

    def _on_update_download_progress(self, request_id: int, percent: int) -> None:
        if request_id != self._update_download_request_id or self._closing:
            return
        self.update_button.setText(f"Lädt … {max(0, min(100, percent))} %")

    def _on_update_download_succeeded(
        self,
        request_id: int,
        installer_path: Path,
    ) -> None:
        if request_id != self._update_download_request_id or self._closing:
            return
        self.update_button.setText("Update geprüft")
        UpdateRestartCountdownDialog(self, seconds=5).exec_countdown()
        if self._closing:
            return
        self.update_button.setText("Installation startet …")
        try:
            self.update_service.launch_installer(installer_path)
        except Exception as error:
            self._show_update_error(str(error))
            return
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def _on_update_download_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._update_download_request_id or self._closing:
            return
        self._show_update_error(message)

    def _show_update_error(self, message: str) -> None:
        self.update_button.setText("Aktualisieren")
        self.update_button.setEnabled(True)
        QMessageBox.warning(
            self,
            "Aktualisierung fehlgeschlagen",
            "Das Programm konnte nicht automatisch aktualisiert werden.\n\n"
            f"{message}",
        )

    def _apply_style(self) -> None:
        style_path = Path(__file__).with_name("styles.qss")
        try:
            style = style_path.read_text(encoding="utf-8")
            assets = style_path.with_name("assets")
            style = style.replace(
                "__SPIN_UP_ICON__",
                (assets / "spin_up.svg").as_posix(),
            ).replace(
                "__SPIN_DOWN_ICON__",
                (assets / "spin_down.svg").as_posix(),
            ).replace(
                "__COMBO_DOWN_ICON__",
                (assets / "spin_down.svg").as_posix(),
            )
            self.setStyleSheet(style)
        except OSError:
            pass

    @property
    def selected_slicer_installation(self) -> SlicerInstallation | None:
        result = self.slicer_discovery_result
        identity_key = self.slicer_combo.currentData()
        if result is None or not isinstance(identity_key, str):
            return None
        return next(
            (
                installation
                for installation in result.installations
                if installation.identity_key == identity_key
            ),
            None,
        )

    @property
    def output_mode(self) -> OutputMode:
        return OutputMode.STL

    @property
    def preview_dialog(self) -> PreviewDialog:
        """Create the optional preview window only when it is first needed."""

        if self._preview_dialog is None:
            dialog = PreviewDialog(self)
            self._preview_dialog = dialog
            dialog.update_requested.connect(self.start_preview)
            dialog.export_requested.connect(self.start_export)
            dialog.closed.connect(self._restore_main_after_preview)
            dialog.canvas.apply_camera_state(
                self._pending_preview_camera_state
            )
            dialog.set_export_enabled(
                self.export_button.isEnabled(),
                self._export_block_reason(),
            )
        return self._preview_dialog

    @property
    def additional_options_dialog(self) -> QDialog:
        """Create the output-folder dialog lazily."""

        if self._additional_options_dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("additionalOptionsDialog")
            dialog.setWindowTitle("Ausgabeordner ändern")
            dialog.setModal(False)
            dialog.setMinimumWidth(OUTPUT_DIALOG_MINIMUM_WIDTH_PX)
            dialog.setSizeGripEnabled(False)
            dialog_layout = QVBoxLayout(dialog)
            dialog_layout.setContentsMargins(0, 0, 0, 0)
            dialog_layout.setSpacing(0)
            self.additional_options_content.setParent(dialog)
            dialog_layout.addWidget(self.additional_options_content)
            self.additional_options_content.show()
            self._additional_options_dialog = dialog
        return self._additional_options_dialog

    @property
    def about_dialog(self) -> QDialog:
        """Create the compact, scrollable program information dialog lazily."""

        if self._about_dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("aboutDialog")
            dialog.setWindowTitle(f"Über {APP_NAME}")
            dialog.setModal(False)
            dialog.setMinimumWidth(ABOUT_DIALOG_MINIMUM_WIDTH_PX)
            dialog.setSizeGripEnabled(True)

            dialog_layout = QVBoxLayout(dialog)
            dialog_layout.setContentsMargins(0, 0, 0, 0)
            dialog_layout.setSpacing(0)

            scroll = QScrollArea(dialog)
            scroll.setObjectName("aboutScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )

            content = QWidget()
            content.setObjectName("aboutContent")
            content.setMinimumWidth(320)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(24, 22, 24, 20)
            content_layout.setSpacing(14)
            self.about_content_layout = content_layout

            hero = QFrame()
            hero.setObjectName("aboutHero")
            hero_layout = QHBoxLayout(hero)
            hero_layout.setContentsMargins(18, 16, 18, 16)
            hero_layout.setSpacing(20)

            program_icon = QLabel()
            program_icon.setObjectName("aboutProgramIcon")
            program_icon.setAccessibleName(f"Programmsymbol {APP_NAME}")
            program_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_pixmap = QPixmap(
                str(GUI_ASSET_ROOT / "icon_tower_render.png")
            )
            program_icon.setPixmap(
                icon_pixmap.scaled(
                    104,
                    140,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            program_icon.setFixedSize(108, 144)
            hero_layout.addWidget(program_icon)

            hero_text = QVBoxLayout()
            hero_text.setSpacing(6)
            product_title = QLabel(APP_NAME)
            product_title.setObjectName("aboutProductTitle")
            self.about_product_title = product_title
            product_description = QLabel(APP_SUBTITLE)
            product_description.setObjectName("aboutProductDescription")
            product_description.setWordWrap(True)
            self.about_product_description = product_description
            version = QLabel(APP_VERSION_LABEL)
            version.setObjectName("aboutVersion")
            hero_text.addStretch(1)
            hero_text.addWidget(product_title)
            hero_text.addWidget(product_description)
            hero_text.addWidget(version)
            hero_text.addStretch(1)
            hero_layout.addLayout(hero_text, 1)
            content_layout.addWidget(hero)

            developer_section = QFrame()
            developer_section.setObjectName("aboutSection")
            developer_layout = QVBoxLayout(developer_section)
            developer_layout.setContentsMargins(18, 16, 18, 16)
            developer_layout.setSpacing(10)
            developer_name = QLabel("Florian Rode")
            developer_name.setObjectName("aboutEmphasis")
            self.about_developer_name = developer_name
            self.about_developer_row = self._about_icon_text_row(
                "user.svg",
                "Entwickelt von:",
                heading=True,
                value_widget=developer_name,
            )
            developer_layout.addLayout(self.about_developer_row)
            self.about_copyright_row = self._about_symbol_text_row(
                "©",
                "2026 Florian Rode · Alle Rechte vorbehalten.",
            )
            developer_layout.addLayout(self.about_copyright_row)
            proprietary_notice = QLabel(
                "Proprietäre Software. Die Nutzung, Vervielfältigung, "
                "Weitergabe oder Veränderung ist nur im Rahmen der "
                "geltenden Lizenzbedingungen gestattet."
            )
            proprietary_notice.setWordWrap(True)
            proprietary_notice.setObjectName("aboutBodyText")
            developer_layout.addWidget(proprietary_notice)
            content_layout.addWidget(developer_section)

            license_section = QFrame()
            license_section.setObjectName("aboutSection")
            license_layout = QVBoxLayout(license_section)
            license_layout.setContentsMargins(18, 16, 18, 16)
            license_layout.setSpacing(9)
            development_status = QLabel()
            development_status.setObjectName("aboutStatusBadge")
            development_status.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            self.about_license_status_label = development_status
            self.about_license_status_row = self._about_icon_text_row(
                "shield.svg",
                "Lizenzstatus:",
                heading=True,
                value_widget=development_status,
            )
            license_layout.addLayout(self.about_license_status_row)
            development_notice = QLabel()
            development_notice.setWordWrap(True)
            development_notice.setObjectName("aboutBodyText")
            self.about_license_status_description = development_notice
            self._set_about_license_status(CURRENT_LICENSE_STATUS)
            license_layout.addWidget(development_notice)
            content_layout.addWidget(license_section)

            legal_specs = (
                ("document.svg", "Lizenzbedingungen"),
                ("privacy.svg", "Datenschutzerklärung"),
                ("packages.svg", "Drittanbieter-Lizenzen"),
            )
            self.about_legal_buttons: list[QPushButton] = []
            for icon_name, caption in legal_specs:
                button = QPushButton(caption)
                button.setObjectName("aboutLegalButton")
                button.setIcon(QIcon(str(GUI_ASSET_ROOT / icon_name)))
                button.setIconSize(QSize(18, 18))
                button.setToolTip(f"{caption} – Inhalt folgt später")
                button.clicked.connect(
                    lambda _checked=False, name=caption: (
                        self._show_legal_placeholder(name)
                    )
                )
                self.about_legal_buttons.append(button)
            self.about_legal_grid = _ResponsiveLegalButtonGrid(
                self.about_legal_buttons
            )
            self.about_legal_grid.setObjectName("aboutLegalGrid")
            content_layout.addWidget(self.about_legal_grid)

            self.about_placeholder_label = QLabel()
            self.about_placeholder_label.setObjectName("aboutPlaceholder")
            self.about_placeholder_label.setWordWrap(True)
            self.about_placeholder_label.hide()
            content_layout.addWidget(self.about_placeholder_label)

            support_frame = QFrame()
            support_frame.setObjectName("aboutSupport")
            support_layout = QHBoxLayout(support_frame)
            support_layout.setContentsMargins(14, 10, 14, 10)
            support_layout.setSpacing(9)
            support_icon = QLabel()
            support_icon.setPixmap(
                QIcon(str(GUI_ASSET_ROOT / "mail.svg")).pixmap(20, 20)
            )
            support_icon.setAccessibleName("E-Mail")
            support_layout.addWidget(support_icon)
            support_link = QLabel(
                'Support: <a href="mailto:florian.rode@outlook.com">'
                '<span style="color:#123c63;">'
                "florian.rode@outlook.com</span></a>"
            )
            support_link.setObjectName("aboutSupportLink")
            support_link.setOpenExternalLinks(True)
            support_layout.addWidget(support_link, 1)
            content_layout.addWidget(support_frame)

            close_row = QHBoxLayout()
            close_row.addStretch(1)
            close_button = QPushButton("Schließen")
            close_button.setObjectName("aboutCloseButton")
            close_button.setIcon(
                QIcon(str(GUI_ASSET_ROOT / "close.svg"))
            )
            close_button.setIconSize(QSize(18, 18))
            close_button.clicked.connect(dialog.close)
            close_row.addWidget(close_button)
            content_layout.addLayout(close_row)

            scroll.setWidget(content)
            dialog_layout.addWidget(scroll)
            self.about_scroll = scroll
            self.about_content = content
            self.about_program_icon = program_icon
            self.about_support_link = support_link
            self.about_close_button = close_button
            self._about_dialog = dialog
        return self._about_dialog

    def _about_icon_text_row(
        self,
        icon_name: str,
        text: str,
        *,
        heading: bool = False,
        value_widget: QWidget | None = None,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(QIcon(str(GUI_ASSET_ROOT / icon_name)).pixmap(20, 20))
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(text)
        label.setObjectName("aboutSectionTitle" if heading else "aboutMetaText")
        label.setWordWrap(value_widget is None)
        icon_alignment = (
            Qt.AlignmentFlag.AlignVCenter
            if value_widget is not None
            else Qt.AlignmentFlag.AlignTop
        )
        row.addWidget(icon, 0, icon_alignment)
        row.addWidget(label, 0 if value_widget is not None else 1)
        if value_widget is not None:
            row.addWidget(value_widget)
            row.addStretch(1)
        return row

    def _about_symbol_text_row(
        self,
        symbol: str,
        text: str,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        symbol_label = QLabel(symbol)
        symbol_label.setObjectName("aboutCopyrightSymbol")
        symbol_label.setAccessibleName("Copyright")
        symbol_label.setFixedWidth(22)
        symbol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label = QLabel(text)
        text_label.setObjectName("aboutMetaText")
        text_label.setWordWrap(True)
        row.addWidget(symbol_label, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(text_label, 1)
        self.about_copyright_symbol = symbol_label
        self.about_copyright_text = text_label
        return row

    def _set_about_license_status(self, status: str) -> None:
        try:
            definition = LICENSE_STATUS_DEFINITIONS[status]
        except KeyError as error:
            raise ValueError(f"Unbekannter Lizenzstatus: {status}") from error
        self.about_license_status_label.setText(definition["label"])
        self.about_license_status_label.setProperty("licenseStatus", status)
        self.about_license_status_description.setText(
            definition["description"]
        )
        self.about_license_status_label.style().unpolish(
            self.about_license_status_label
        )
        self.about_license_status_label.style().polish(
            self.about_license_status_label
        )

    def _show_legal_placeholder(self, document_name: str) -> None:
        self.about_placeholder_label.setText(
            f"„{document_name}“ wird in einer späteren Version ergänzt."
        )
        self.about_placeholder_label.show()
        self.about_content_layout.invalidate()
        QTimer.singleShot(0, self._expand_about_downward_for_content)

    def _close_additional_options(self) -> None:
        if self._additional_options_dialog is not None:
            self._additional_options_dialog.close()

    def _restore_phase17_ui_state(self, ui_state: dict[str, object]) -> None:
        quality = str(ui_state.get("preview_quality", "")).casefold()
        if quality not in PREVIEW_QUALITY_ITERATIONS:
            try:
                legacy_iterations = int(ui_state.get("slicer_iterations", 2))
            except (TypeError, ValueError):
                legacy_iterations = 2
            quality = (
                "fast"
                if legacy_iterations <= 1
                else "balanced"
                if legacy_iterations < 5
                else "exact"
            )
        self._set_preview_quality(quality, invalidate=False)
        self._pending_preview_camera_state = ui_state.get("preview_camera")
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.apply_camera_state(
                self._pending_preview_camera_state
            )
        expanded = ui_state.get("expanded_sections", {})
        if isinstance(expanded, dict):
            sections = {
                "timing": self.timing_group,
                "prediction": self.prediction_frame,
                "geometry": self.geometry_settings_group,
            }
            for name, section in sections.items():
                if name in expanded:
                    section.setChecked(bool(expanded[name]))

    def _calibration_config(self) -> CalibrationConfig:
        return CalibrationConfig(
            mode=CalibrationMode.STL,
            maximum_iterations=PREVIEW_QUALITY_ITERATIONS[
                self.preview_quality
            ],
        )

    @property
    def preview_quality(self) -> str:
        checked = self.preview_quality_group.checkedButton()
        if checked is None:
            return DEFAULT_PREVIEW_QUALITY
        quality = str(checked.property("quality")).casefold()
        return (
            quality
            if quality in PREVIEW_QUALITY_ITERATIONS
            else DEFAULT_PREVIEW_QUALITY
        )

    def _set_preview_quality(
        self,
        quality: str,
        *,
        invalidate: bool,
    ) -> None:
        normalized = quality.casefold()
        if normalized not in PREVIEW_QUALITY_ITERATIONS:
            normalized = DEFAULT_PREVIEW_QUALITY
        changed = normalized != self.preview_quality
        self.preview_quality_group.blockSignals(True)
        try:
            self.preview_quality_buttons[normalized].setChecked(True)
        finally:
            self.preview_quality_group.blockSignals(False)
        if changed and invalidate:
            self._on_preview_quality_changed()

    def _on_preview_quality_toggled(
        self,
        _button: QToolButton,
        checked: bool,
    ) -> None:
        if checked and not self._loading_phase17_state:
            self._on_preview_quality_changed()

    def _on_preview_quality_changed(self) -> None:
        self._invalidate_preview(
            "Die Vorschauqualität wurde geändert.",
            preserve_slicer_prediction=True,
        )
        self._update_section_summaries()

    @staticmethod
    def _export_calibration_config() -> CalibrationConfig:
        return CalibrationConfig(
            mode=CalibrationMode.STL,
            maximum_iterations=EXPORT_SLICER_ITERATIONS,
        )

    def _profile_origin_text(self, result: ProfileMatchResult) -> str:
        if result.state is ProfileMatchState.RECONSTRUCTED:
            return "Aus eingebetteter Konfiguration rekonstruiert."
        if result.state is ProfileMatchState.MATCHED:
            return "Mit einem installierten Profil abgeglichen."
        if result.state in {
            ProfileMatchState.COMPATIBLE,
            ProfileMatchState.AMBIGUOUS,
        }:
            return "Kompatibler Vorschlag – Bestätigung erforderlich."
        return "Keine belastbare Profilzuordnung verfügbar."

    def _refresh_stl_availability(self) -> None:
        result = self.profile_match_result
        selected = result.selected if result is not None else None
        can_calibrate_stl = bool(
            result is not None
            and result.can_use_stl_mode
            and selected is not None
            and result.execution_slicer.can_slice
        )
        self.stl_mode_status.setText(
            "Slicer-gestützte Annäherung ist verfügbar."
            if can_calibrate_stl
            else "Analytischer STL-Fallback ist verfügbar."
        )
        self._refresh_phase17_actions()

    def _current_preview_request(
        self,
        *,
        calibration_config: CalibrationConfig | None = None,
    ) -> PreviewRequest:
        snapshot = self.analysis_snapshot
        if snapshot is None:
            raise ValueError("G-Code-Analyse ist noch nicht abgeschlossen.")
        result = self.profile_match_result
        effective_profile = None
        adapter = None
        slicer_key = None
        profile_fingerprint = None
        may_use_profile = bool(
            result is not None
            and result.selected is not None
            and result.can_use_stl_mode
        )
        if may_use_profile and result is not None and result.selected is not None:
            effective_profile = result.selected.effective_profile
            adapter = self.slicer_service.adapter_for(result.execution_slicer)
            slicer_key = result.execution_slicer.identity_key
            profile_fingerprint = (
                f"{result.inventory_fingerprint}:{result.selected.bundle_id}:"
                f"{int(result.user_confirmed)}"
            )
        return PreviewRequest(
            snapshot=snapshot,
            settings=self.collect_settings(),
            output_mode=self.output_mode,
            calibration_config=calibration_config or self._calibration_config(),
            slicer_identity_key=slicer_key,
            profile_fingerprint=profile_fingerprint,
            effective_profile=effective_profile,
            adapter=adapter,
        )

    def _invalidate_preview(
        self,
        reason: str,
        *,
        preserve_slicer_prediction: bool = False,
    ) -> None:
        if self._loading_phase17_state:
            return
        if not preserve_slicer_prediction:
            self._clear_slicer_prediction()
        self._preview_request_id += 1
        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="preview_invalidated",
        )
        if hasattr(self, "progress_bar"):
            self.progress_bar.setProperty("task", "default")
            self._refresh_widget_style(self.progress_bar)
        had_preview = self.current_preview is not None
        self.preview_state = (
            PreviewState.STALE
            if had_preview
            else PreviewState.EMPTY
        )
        if self._preview_dialog is not None:
            self._preview_dialog.mark_stale()
        self.preview_button.setText(
            "Vorschau aktualisieren"
            if had_preview
            else "Vorschau erstellen"
        )
        if had_preview:
            self.preview_hint_label.setProperty("state", "stale")
            self.preview_hint_label.setText(
                f"Vorschau nicht mehr aktuell: {reason} Der Export ist weiterhin "
                "möglich; vorher erscheint eine Sicherheitsabfrage."
            )
            self._set_main_status(
                "Vorschau ist nicht mehr aktuell", icon="⚠", state="warning"
            )
        else:
            self.preview_hint_label.setProperty("state", "current")
            self.preview_hint_label.setText(
                "Beim Export wird der Kühlturm immer mit den aktuellen "
                "Einstellungen erzeugt."
            )
        self._refresh_widget_style(self.preview_hint_label)
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def _refresh_phase17_actions(self) -> None:
        if not hasattr(self, "preview_button"):
            return
        block_reason = self._export_block_reason()
        enabled = block_reason is None
        self.preview_button.setEnabled(enabled)
        if self._preview_dialog is not None:
            self._preview_dialog.update_button.setEnabled(enabled)
        self.preview_quality_panel.setEnabled(
            not self.background_job_manager.has_active(JobKind.PREVIEW)
            and not self.background_job_manager.has_active(JobKind.EXPORT)
        )
        self._set_export_button_state(enabled, block_reason)
        if hasattr(self, "slicer_prediction_button"):
            self._refresh_prediction_advice(
                self.prediction_method_label.text()
            )
        self._update_responsive_action_labels()
        self._refresh_folder_action_states()

    def _export_block_reason(self) -> str | None:
        if self.background_job_manager.has_active(JobKind.EXPORT):
            return "Ein Export wird bereits ausgeführt."
        if self.background_job_manager.has_active(JobKind.SLICER_PREDICTION):
            return "Die einmalige Slicer-Schätzung wird gerade erstellt."
        if self.background_job_manager.has_active(JobKind.PREVIEW):
            return "Die Vorschau wird gerade erstellt."
        if self.current_gcode_path is None:
            return "Bitte zuerst einen G-Code auswählen."
        if self._analysis_failed:
            return "Die G-Code-Analyse ist fehlgeschlagen."
        if self.analysis_snapshot is None:
            return "Der G-Code wird noch analysiert."
        if not self._phase17_static_valid:
            return "Bitte ungültige oder unvollständige Eingaben korrigieren."
        if self.tower_assessment is None:
            return "Der Kühlturmbedarf wird noch geprüft."
        if not self.tower_assessment.tower_required:
            return "Für die aktuellen Werte ist kein Kühlturm erforderlich."
        if self.profile_feasibility is None:
            return "Die Turmgeometrie wird noch geprüft."
        if not self.profile_feasibility.feasible:
            return "Die Turmgeometrie ist mit den aktuellen Werten nicht möglich."
        return None

    def _set_export_button_state(
        self,
        enabled: bool,
        reason: str | None = None,
    ) -> None:
        self.export_button.setEnabled(enabled)
        if self._preview_dialog is not None:
            self._preview_dialog.set_export_enabled(enabled, reason)
        if not self._setting_feedback_is_available():
            self.export_availability_label.clear()
            self.action_availability_widget.hide()
            self._refresh_footer_auxiliary_visibility()
            self._schedule_footer_height_update()
            return
        if enabled:
            self.export_availability_label.clear()
            self.action_availability_widget.hide()
            self._refresh_footer_auxiliary_visibility()
            self._schedule_footer_height_update()
            return
        message = german_user_message(
            reason or "Die aktuellen Voraussetzungen sind noch nicht erfüllt."
        )
        self.export_availability_label.setText(
            f"Export/Vorschau nicht möglich: {message}"
        )
        self.export_availability_label.show()
        self.action_availability_widget.show()
        self._refresh_footer_auxiliary_visibility()
        self._schedule_footer_height_update()

    def start_slicer_discovery(
        self,
        *,
        force: bool = False,
        manual_path: Path | None = None,
    ) -> None:
        if self._closing:
            return
        if self.background_job_manager.has_active(
            JobKind.SLICER_DISCOVERY
        ) or self.background_job_manager.has_active(JobKind.PROFILE_MATCH):
            # Discovery and profile resolution share the selected adapter and
            # its process runner. Keep only the newest discovery request and
            # start it after both native worker threads have actually stopped.
            # Running either operation concurrently can deadlock an external
            # slicer and previously made repeated detection appear frozen.
            self._slicer_request_id += 1
            self._pending_slicer_discovery = (force, manual_path)
            self._pending_profile_match = None
            self._profile_watch_timer.stop()
            self.slicer_refresh_button.setEnabled(False)
            self.slicer_manual_button.setEnabled(False)
            if self.background_job_manager.has_active(
                JobKind.PROFILE_MATCH
            ) and not self.background_job_manager.has_active(
                JobKind.SLICER_DISCOVERY
            ):
                self._set_slicer_progress(
                    0,
                    "Laufende Profilprüfung wird abgeschlossen …",
                    icon="⌛",
                    state="running",
                )
            return
        self._slicer_request_id += 1
        request_id = self._slicer_request_id
        self.workflow.begin_slicer_search()
        self._set_slicer_progress(
            10,
            "Installierte Slicer werden gesucht und geprüft …",
            icon="⌛",
            state="running",
        )
        source_slicer = (
            self.analysis_snapshot.metadata.slicer
            if self.analysis_snapshot is not None
            else None
        )
        self.slicer_status_label.setText(
            "Ausgewählte Slicer-Datei wird verifiziert …"
            if manual_path is not None
            else "Installierte Slicer werden sicher erkannt und verifiziert …"
        )
        self.slicer_status_label.setProperty("state", "analyzing")
        self._refresh_widget_style(self.slicer_status_label)
        self.slicer_refresh_button.setEnabled(False)
        self.slicer_manual_button.setEnabled(False)

        worker = SlicerDiscoveryWorker(
            request_id,
            self.slicer_service,
            source_slicer,
            force=force,
            manual_path=manual_path,
        )
        worker.succeeded.connect(self._on_slicer_discovery_succeeded)
        worker.failed.connect(self._on_slicer_discovery_failed)
        self.background_job_manager.start_job(
            kind=JobKind.SLICER_DISCOVERY,
            request_id=request_id,
            worker=worker,
        )

    def select_manual_slicer(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Installierten oder portablen Slicer auswählen",
            "",
            "Windows-Programme (*.exe);;Alle Dateien (*)",
        )
        if selected:
            self.start_slicer_discovery(manual_path=Path(selected))

    def _on_slicer_discovery_succeeded(
        self,
        request_id: int,
        result: SlicerDiscoveryResult,
    ) -> None:
        if request_id != self._slicer_request_id:
            return
        previous_key = self.slicer_combo.currentData()
        self.slicer_discovery_result = result
        self._populating_slicer_combo = True
        try:
            self.slicer_combo.clear()
            selected_index = -1
            verified_installations = tuple(
                installation
                for installation in result.installations
                if installation.verified
            )
            for index, installation in enumerate(verified_installations):
                label = installation.display_name
                if installation.identity_key == result.recommended_key:
                    label += " – empfohlen"
                self.slicer_combo.addItem(
                    label,
                    installation.identity_key,
                )
                self.slicer_combo.setItemData(
                    index,
                    str(installation.executable_path),
                    Qt.ItemDataRole.ToolTipRole,
                )
                if installation.identity_key == previous_key:
                    selected_index = index
                elif (
                    selected_index < 0
                    and installation.identity_key == result.recommended_key
                ):
                    selected_index = index
            if selected_index >= 0:
                self.slicer_combo.setCurrentIndex(selected_index)
            self.slicer_combo.setEnabled(bool(verified_installations))
        finally:
            self._populating_slicer_combo = False

        state_names = {
            SlicerGuiState.AVAILABLE_AND_RECOMMENDED: "availableRecommended",
            SlicerGuiState.AVAILABLE: "available",
            SlicerGuiState.NEEDS_MANUAL_PATH: "manual",
            SlicerGuiState.UNSUPPORTED: "unsupported",
            SlicerGuiState.NOT_FOUND: "notFound",
        }
        selected = self.selected_slicer_installation
        status_messages = [result.message]
        combined_status = result.message.casefold()
        if selected is not None:
            supplemental_facts = (
                (
                    selected.can_slice,
                    "automatische slicer-verarbeitung",
                    "Automatische Slicer-Verarbeitung verfügbar.",
                ),
                (
                    selected.identity_key == result.recommended_key,
                    "passendster erkannter slicer",
                    "Passendster erkannter Slicer wurde vorausgewählt.",
                ),
            )
            for applies, marker, text in supplemental_facts:
                if applies and marker not in combined_status:
                    status_messages.append(text)
                    combined_status = f"{combined_status} {text.casefold()}"
        self.slicer_status_label.setText(
            " ".join(dict.fromkeys(message for message in status_messages if message))
        )
        self.slicer_status_label.setProperty(
            "state",
            state_names[result.gui_state],
        )
        self._refresh_widget_style(self.slicer_status_label)
        self._update_slicer_detail()
        if verified_installations and selected is not None:
            self._set_slicer_progress(
                100,
                "Slicer-Suche abgeschlossen",
                icon="✓",
                state="success",
            )
            self.workflow.slicer_succeeded(selected.display_name)
            self._set_slicer_header_summary(selected)
        else:
            self._slicer_header_installation = None
            self._set_slicer_progress(
                100,
                "Kein verwendbarer Slicer erkannt",
                icon="!",
                state="warning",
            )
            self.workflow.slicer_unavailable(
                "Kein verwendbarer Slicer erkannt"
            )
        self._refresh_prediction()
        if self.analysis_snapshot is not None:
            self.start_profile_matching()

    def _on_slicer_discovery_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._slicer_request_id:
            return
        self.slicer_status_label.setText(
            "Slicer konnte nicht bestätigt werden: "
            f"{german_user_message(message)}"
        )
        self.slicer_status_label.setProperty("state", "error")
        self._refresh_widget_style(self.slicer_status_label)
        self._set_slicer_progress(
            100,
            "Slicer-Suche ohne Ergebnis beendet",
            icon="!",
            state="warning",
        )
        self.workflow.slicer_unavailable("Analytischer Betrieb verfügbar")

    def _on_slicer_selection_changed(self, _index: int) -> None:
        if self._populating_slicer_combo:
            return
        identity_key = self.slicer_combo.currentData()
        self.slicer_service.remember_selection(
            identity_key if isinstance(identity_key, str) else None
        )
        self._update_slicer_detail()
        selected = self.selected_slicer_installation
        if selected is not None:
            self._set_slicer_header_summary(selected)
        self.profile_preview_outdated = True
        self._invalidate_preview("Der ausgewählte Slicer wurde geändert.")
        self._clear_profile_assignment(
            "Profilzuordnung wird für den gewählten Slicer neu bestimmt.",
            "pending",
        )
        if self.analysis_snapshot is not None:
            self.start_profile_matching()

    def _update_slicer_detail(self) -> None:
        installation = self.selected_slicer_installation
        result = self.slicer_discovery_result
        if installation is None:
            failed_count = len(result.diagnostics) if result else 0
            suffix = (
                f" {failed_count} Kandidat(en) konnten nicht verifiziert werden."
                if failed_count
                else ""
            )
            self.slicer_detail_label.setText(
                "Es werden keine nicht belegten Produkt-, Drucker- oder "
                f"Profilangaben angezeigt.{suffix}"
            )
            return
        support = (
            "Automatisches Hintergrund-Slicing verfügbar."
            if installation.can_slice
            else "Nur Installationserkennung; keine automatische Verarbeitung."
        )
        version = f" {installation.version}" if installation.version else ""
        self.slicer_detail_label.setText(
            f"Verifiziert: {installation.product_name}{version}. {support} "
            "Die genaue Profilzuordnung wird separat geprüft."
        )

    def _set_slicer_header_summary(
        self,
        installation: SlicerInstallation,
    ) -> None:
        self._slicer_header_installation = installation
        summary = installation.display_name
        self.workflow.update_slicer_summary(summary)
        self.slicer_group.set_summary(summary)
        automatically_detected = (
            installation.discovery_source is not SlicerDiscoverySource.MANUAL
        )
        self.slicer_group.set_summary_note(None)
        self.slicer_group.set_title_note(
            "(automatisch erkannt)" if automatically_detected else None,
            severity="success",
        )
        self._refresh_slicer_header_profiles(installation)

    def _refresh_slicer_header_profiles(
        self,
        installation: SlicerInstallation | None = None,
    ) -> None:
        """Keep the selected Slicer and all three profiles in its header."""

        current = (
            installation
            or self.selected_slicer_installation
            or self._slicer_header_installation
        )
        if current is None:
            self.slicer_group.set_compact_summary_rows(())
            return

        def selected_text(combo: QComboBox) -> str:
            text = combo.currentText().strip()
            return text if text else "Noch nicht ausgewählt"

        lines = (
            ("Slicer", current.display_name),
            ("Maschinenprofil", selected_text(self.machine_profile_combo)),
            ("Prozessprofil", selected_text(self.process_profile_combo)),
            ("Filamentprofil", selected_text(self.filament_profile_combo)),
        )
        self.slicer_group.set_compact_summary_rows(lines)
        QTimer.singleShot(0, self._refresh_slicer_section_layout)

    def _clear_profile_assignment(self, message: str, state: str) -> None:
        self._profile_watch_timer.stop()
        self._pending_profile_match = None
        self.profile_match_result = None
        self._populating_profile_combos = True
        try:
            for combo in (
                self.machine_profile_combo,
                self.process_profile_combo,
                self.filament_profile_combo,
            ):
                combo.clear()
                combo.setEnabled(False)
        finally:
            self._populating_profile_combos = False
        self._refresh_slicer_header_profiles()
        self.profile_status_label.setText(message)
        self.profile_status_label.setProperty("state", state)
        self._refresh_widget_style(self.profile_status_label)
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.hide()
        if hasattr(self, "profile_origin_label"):
            self.profile_origin_label.setText(
                "Profilherkunft wird nach einer belastbaren Zuordnung angezeigt."
            )
            self.profile_origin_label.hide()
            self.profile_diagnostics.clear()
            self.profile_diagnostics.hide()
        self._refresh_stl_availability()

    def start_profile_matching(
        self,
        *,
        selected_profile_ids: dict[str, str] | None = None,
        force_inventory: bool = False,
        stale_check_only: bool = False,
    ) -> None:
        if self._closing:
            return
        snapshot = self.analysis_snapshot
        installation = self.selected_slicer_installation
        if snapshot is None or installation is None:
            return
        if self.background_job_manager.has_active(JobKind.PROFILE_MATCH):
            # Profile resolution, its disk cache and probe validator are one
            # shared unit.  Concurrent matches used to race on those objects.
            self._profile_request_id += 1
            self._pending_profile_match = {
                "selected_profile_ids": dict(selected_profile_ids or {}),
                "force_inventory": force_inventory,
                "stale_check_only": stale_check_only,
            }
            if not stale_check_only:
                self.profile_status_label.setText(
                    "Die aktuelle Profilprüfung wird beendet; die neueste "
                    "Auswahl folgt anschließend …"
                )
                self.profile_status_label.setProperty("state", "analyzing")
                self._refresh_widget_style(self.profile_status_label)
            return
        try:
            adapter = self.slicer_service.adapter_for(installation)
        except (AttributeError, KeyError, ValueError):
            self._clear_profile_assignment(
                "Für den ausgewählten Slicer ist kein Profiladapter verfügbar.",
                "error",
            )
            return

        self._profile_request_id += 1
        request_id = self._profile_request_id
        if not stale_check_only:
            self._profile_watch_timer.stop()
            self.profile_status_label.setText(
                "Profile werden inventarisiert, aufgelöst und geprüft …"
            )
            self.profile_status_label.setProperty("state", "analyzing")
            self._refresh_widget_style(self.profile_status_label)
            self.profile_confirm_button.setEnabled(False)

        worker = ProfileMatchingWorker(
            request_id,
            self.profile_service,
            snapshot,
            installation,
            adapter,
            selected_profile_ids=selected_profile_ids,
            force_inventory=force_inventory,
            stale_check_result=(
                self.profile_match_result if stale_check_only else None
            ),
        )
        # A discovery run would use the same adapter concurrently. Keep both
        # discovery actions locked until this native profile thread has ended.
        self.slicer_refresh_button.setEnabled(False)
        self.slicer_manual_button.setEnabled(False)
        worker.succeeded.connect(self._on_profile_matching_succeeded)
        worker.unchanged.connect(self._on_profile_inventory_unchanged)
        worker.failed.connect(self._on_profile_matching_failed)
        self.background_job_manager.start_job(
            kind=JobKind.PROFILE_MATCH,
            request_id=request_id,
            worker=worker,
        )

    def _on_profile_matching_succeeded(
        self,
        request_id: int,
        result: ProfileMatchResult,
    ) -> None:
        if request_id != self._profile_request_id:
            return
        installation = self.selected_slicer_installation
        if (
            installation is None
            or result.execution_slicer.identity_key != installation.identity_key
        ):
            return
        self.profile_match_result = result
        self._populate_profile_combos(result)
        state_names = {
            ProfileMatchState.RECONSTRUCTED: "availableRecommended",
            ProfileMatchState.MATCHED: "available",
            ProfileMatchState.COMPATIBLE: "manual",
            ProfileMatchState.AMBIGUOUS: "manual",
            ProfileMatchState.UNAVAILABLE: "error",
        }
        mode_text = (
            " Slicerbasierte STL-Optimierung verfügbar."
            if result.can_use_stl_mode
            else " Analytischer STL-Fallback wird verwendet."
        )
        profile_message = (
            "Effektive G-Code-Konfiguration wurde rekonstruiert und validiert."
            if result.state is ProfileMatchState.RECONSTRUCTED
            else german_user_message(result.message)
        )
        self.profile_status_label.setText(profile_message + mode_text)
        self.profile_status_label.setProperty(
            "state", state_names[result.state]
        )
        self._refresh_widget_style(self.profile_status_label)
        self.profile_confirm_button.setVisible(result.requires_confirmation)
        self.profile_confirm_button.setEnabled(result.requires_confirmation)
        self.profile_origin_label.setText(self._profile_origin_text(result))
        self.profile_origin_label.show()
        selected = result.selected
        if selected is not None:
            validation_labels = {
                "invalid": "ungültig",
                "structurally_valid": "strukturell gültig",
                "probe_validated": "durch Probelauf validiert",
            }
            diagnostics = [
                "Validierung: "
                + validation_labels.get(
                    selected.validation_state.value,
                    selected.validation_state.value,
                ),
                f"Profilpaket: {selected.bundle_id}",
                *(german_user_message(item) for item in selected.evidence),
                *(
                    german_user_message(item.message)
                    for item in selected.exclusions
                ),
            ]
            self.profile_diagnostics.setPlainText(
                "\n".join(dict.fromkeys(item for item in diagnostics if item))
            )
            self.profile_diagnostics.setVisible(bool(diagnostics))
        else:
            self.profile_diagnostics.clear()
            self.profile_diagnostics.hide()
        self._invalidate_preview("Die wirksame Profilzuordnung wurde geändert.")
        self._refresh_stl_availability()
        self._profile_watch_timer.start()

    def _populate_profile_combos(self, result: ProfileMatchResult) -> None:
        selected = result.selected
        selected_records = (
            selected.machine if selected is not None else None,
            selected.process if selected is not None else None,
            selected.filament if selected is not None else None,
        )
        previous_selections = (
            self.machine_profile_combo.currentData(),
            self.process_profile_combo.currentData(),
            self.filament_profile_combo.currentData(),
        )
        self._populating_profile_combos = True
        try:
            for combo, records, current, previous in zip(
                (
                    self.machine_profile_combo,
                    self.process_profile_combo,
                    self.filament_profile_combo,
                ),
                (
                    result.machine_options,
                    result.process_options,
                    result.filament_options,
                ),
                selected_records,
                previous_selections,
            ):
                combo.clear()
                selected_index = -1
                selected_path = (
                    str(current.path)
                    if current is not None
                    else previous if isinstance(previous, str) else None
                )
                for heading, grouped_records in self._profile_option_groups(records):
                    combo.addItem(heading)
                    heading_index = combo.count() - 1
                    model = combo.model()
                    if isinstance(model, QStandardItemModel):
                        item = model.item(heading_index)
                        if item is not None:
                            font = item.font()
                            font.setBold(True)
                            item.setFont(font)
                            item.setFlags(Qt.ItemFlag.NoItemFlags)
                    for record in grouped_records:
                        profile_path = str(record.path)
                        combo.addItem(
                            self._profile_record_label(record),
                            profile_path,
                        )
                        index = combo.count() - 1
                        combo.setItemData(
                            index,
                            profile_path,
                            Qt.ItemDataRole.ToolTipRole,
                        )
                        if profile_path == selected_path:
                            selected_index = index
                if selected_index < 0:
                    selected_index = next(
                        (
                            index
                            for index in range(combo.count())
                            if isinstance(combo.itemData(index), str)
                        ),
                        -1,
                    )
                if selected_index >= 0:
                    combo.setCurrentIndex(selected_index)
                combo.setEnabled(bool(records))
        finally:
            self._populating_profile_combos = False
        self._refresh_slicer_header_profiles()

    @staticmethod
    def _profile_option_groups(records):
        grouped = {
            "user": [],
            "system": [],
            "other": [],
        }
        for record in records:
            source = str(record.source).casefold()
            category = (
                "system"
                if source == "system"
                else "user"
                if source == "user"
                else "other"
            )
            grouped[category].append(record)

        result = []
        for category, heading in (
            ("user", "- User presets -"),
            ("system", "- System presets -"),
            ("other", "- Other presets -"),
        ):
            category_records = tuple(
                sorted(
                    grouped[category],
                    key=lambda record: (
                        record.name.casefold(),
                        record.profile_id.casefold(),
                        str(record.path).casefold(),
                    ),
                )
            )
            if category_records:
                result.append((heading, category_records))
        return tuple(result)

    @staticmethod
    def _profile_record_label(record) -> str:
        identifier = (
            f" — {record.profile_id}"
            if record.profile_id != record.name
            else ""
        )
        return f"{record.name}{identifier}"

    def _on_profile_selection_changed(self, _changed_role: str) -> None:
        if self._populating_profile_combos or self.profile_match_result is None:
            return
        self._refresh_slicer_header_profiles()
        selections = {
            "machine": self.machine_profile_combo.currentData(),
            "process": self.process_profile_combo.currentData(),
            "filament": self.filament_profile_combo.currentData(),
        }
        selected_profile_ids = {
            role: value
            for role, value in selections.items()
            if isinstance(value, str)
        }
        if len(selected_profile_ids) != 3:
            return
        self.profile_preview_outdated = True
        self._invalidate_preview("Die Profilkombination wird neu geprüft.")
        self.start_profile_matching(
            selected_profile_ids=selected_profile_ids,
        )

    def confirm_profile_selection(self) -> None:
        result = self.profile_match_result
        if result is None or not result.requires_confirmation:
            return
        try:
            confirmed = self.profile_service.confirm(result)
        except (OSError, ValueError) as error:
            self.profile_status_label.setText(
                "Profilzuordnung konnte nicht gespeichert werden: "
                f"{german_user_message(error)}"
            )
            self.profile_status_label.setProperty("state", "error")
            self._refresh_widget_style(self.profile_status_label)
            return
        self.profile_match_result = confirmed
        self._refresh_slicer_header_profiles()
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.hide()
        self.profile_status_label.setText(
            german_user_message(confirmed.message)
        )
        self.profile_status_label.setProperty("state", "available")
        self._refresh_widget_style(self.profile_status_label)
        self.profile_origin_label.setText(self._profile_origin_text(confirmed))
        self.profile_origin_label.show()
        self._invalidate_preview("Die Profilzuordnung wurde bestätigt.")
        self._refresh_stl_availability()

    def _check_profile_inventory_changes(self) -> None:
        if (
            self._closing
            or self.profile_match_result is None
            or self.background_job_manager.has_active(JobKind.PROFILE_MATCH)
        ):
            return
        # The worker is retained until QThread.finished and profile jobs are
        # serialized, so a periodic check cannot race with another match or
        # leave a still-running native thread without a Python owner.
        self.start_profile_matching(stale_check_only=True)

    def _on_profile_inventory_unchanged(self, request_id: int) -> None:
        if request_id != self._profile_request_id:
            return

    def _on_profile_matching_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._profile_request_id:
            return
        self.profile_status_label.setText(
            "Profilzuordnung konnte nicht geprüft werden: "
            f"{german_user_message(message)}"
        )
        self.profile_status_label.setProperty("state", "error")
        self._refresh_widget_style(self.profile_status_label)
        self.profile_origin_label.hide()
        self.profile_diagnostics.hide()

    @Slot(object)
    def _on_background_job_released(self, job: BackgroundJob) -> None:
        """React only after the manager has observed the native thread end."""

        finished_kind = job.kind

        if self._closing:
            return
        pending_adapter_work_started = False
        if (
            finished_kind in {"slicer", "profile"}
            and not self.background_job_manager.has_active(
                JobKind.SLICER_DISCOVERY
            )
            and not self.background_job_manager.has_active(
                JobKind.PROFILE_MATCH
            )
            and self._pending_slicer_discovery is not None
        ):
            pending = self._pending_slicer_discovery
            self._pending_slicer_discovery = None
            force, manual_path = pending
            pending_adapter_work_started = True
            QTimer.singleShot(
                0,
                lambda: self.start_slicer_discovery(
                    force=force,
                    manual_path=manual_path,
                ),
            )
        elif finished_kind == "profile" and not (
            self.background_job_manager.has_active(JobKind.PROFILE_MATCH)
        ):
            pending = self._pending_profile_match
            self._pending_profile_match = None
            if pending is not None:
                pending_adapter_work_started = True
                QTimer.singleShot(
                    0,
                    lambda: self.start_profile_matching(
                        selected_profile_ids=pending["selected_profile_ids"],
                        force_inventory=bool(pending["force_inventory"]),
                        stale_check_only=bool(pending["stale_check_only"]),
                    ),
                )
        elif finished_kind in {"preview", "prediction", "export"}:
            if finished_kind in {"preview", "export"}:
                self.progress_bar.setRange(0, 100)
            if finished_kind == "export":
                self.drop_zone.remove_button.setEnabled(
                    self.current_gcode_path is not None
                )
            if finished_kind == "prediction":
                self._refresh_prediction()
            self._refresh_phase17_actions()
        if not pending_adapter_work_started:
            self._update_slicer_discovery_controls()

    def _update_slicer_discovery_controls(self) -> None:
        """Enable discovery actions only when shared adapter work is idle."""

        enabled = bool(
            not self._closing
            and not self.background_job_manager.has_active(
                JobKind.SLICER_DISCOVERY
            )
            and not self.background_job_manager.has_active(
                JobKind.PROFILE_MATCH
            )
            and self._pending_slicer_discovery is None
        )
        self.slicer_refresh_button.setEnabled(enabled)
        self.slicer_manual_button.setEnabled(enabled)

    @staticmethod
    def _refresh_widget_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    @staticmethod
    def _set_boolean_style_property(
        widget: QWidget,
        property_name: str,
        enabled: bool,
    ) -> bool:
        current = widget.property(property_name)
        enabled = bool(enabled)
        if current is not None and bool(current) == enabled:
            return False
        widget.setProperty(property_name, enabled)
        MainWindow._refresh_widget_style(widget)
        return True

    def _sync_collapsible_content(self, section: str, expanded: bool) -> None:
        if not expanded:
            return
        if section == "profile":
            self.profile_diagnostics.setVisible(
                bool(self.profile_diagnostics.toPlainText().strip())
            )
            requires_confirmation = bool(
                self.profile_match_result is not None
                and self.profile_match_result.requires_confirmation
            )
            self.profile_confirm_button.setVisible(requires_confirmation)
        elif section == "stability":
            automatic = self.automatic_base_checkbox.isChecked()
            self._setting_widgets["manual_base_width_mm"].setVisible(not automatic)
            self.automatic_base_width_label.setVisible(automatic)
            self.automatic_base_reset_button.setVisible(not automatic)
            self.automatic_base_error_label.setVisible(
                bool(self.automatic_base_error_label.text().strip())
            )
        elif section == "geometry_settings":
            self._sync_collapsible_content("stability", True)

    def _refresh_geometry_section_layout(
        self,
        expanded: bool,
    ) -> None:
        """Publish the complete immediate geometry-card size to the scroll area."""

        # Recalculate from both responsive columns instead of retaining a
        # stretched geometry from a former arrangement.
        self.geometry_settings_group.setMinimumHeight(0)
        self.geometry_settings_group.setMaximumHeight(16777215)
        self.geometry_settings_group.content_widget.setMinimumHeight(0)
        self.geometry_settings_group.content_widget.setMaximumHeight(16777215)
        self.geometry_split.setMinimumHeight(0)
        self.geometry_split.setMaximumHeight(16777215)
        self.geometry_right_column.setMinimumHeight(0)
        self.geometry_right_column.setMaximumHeight(16777215)
        for subsection in (
            self.geometry_group,
            self.stability_group,
            self.overhang_group,
            self.geometry_calculation_section,
        ):
            subsection.setMinimumHeight(0)
            subsection.setMaximumHeight(16777215)
        self.geometry_split.refresh_layout()
        if self.geometry_split.is_two_column():
            self.geometry_fields_layout.setContentsMargins(20, 10, 15, 10)
            self.stability_fields_layout.setContentsMargins(15, 10, 20, 10)
            self.overhang_fields_layout.setContentsMargins(15, 10, 20, 10)
            self.geometry_calculation_body_layout.setContentsMargins(
                15, 4, 20, 10
            )
        else:
            self.geometry_fields_layout.setContentsMargins(20, 10, 20, 10)
            self.stability_fields_layout.setContentsMargins(20, 10, 20, 10)
            self.overhang_fields_layout.setContentsMargins(20, 10, 20, 10)
            self.geometry_calculation_body_layout.setContentsMargins(
                20, 4, 20, 10
            )
        # Apply responsive inset changes before returning to the event loop.
        # Otherwise the next unrelated hover/input event becomes the trigger
        # for a visible two-pixel control shift.
        for nested_layout in (
            self.geometry_fields_layout,
            self.stability_fields_layout,
            self.overhang_fields_layout,
            self.geometry_calculation_body_layout,
            self.geometry_right_layout,
        ):
            nested_layout.invalidate()
            nested_layout.activate()
        self.geometry_split.grid.invalidate()
        split_height = self.geometry_split.content_height_hint()
        self.geometry_split.setFixedHeight(max(0, split_height))
        self.geometry_split.grid.activate()
        self.geometry_split.updateGeometry()
        self.geometry_settings_group.content_layout.invalidate()
        self.geometry_settings_group.content_layout.activate()
        self.geometry_settings_group.content_widget.updateGeometry()
        self.geometry_settings_group.updateGeometry()
        if expanded:
            self.geometry_settings_group.content_widget.setFixedHeight(
                self.geometry_settings_group.content_widget.sizeHint().height()
            )
            self.geometry_settings_group.setFixedHeight(
                self.geometry_settings_group.sizeHint().height()
            )
        else:
            # Include the card's outer top and bottom border.  Restricting the
            # card to the 52 px header clipped the lower blue frame line.
            self.geometry_settings_group.setFixedHeight(
                max(
                    self.geometry_settings_group.header.height(),
                    self.geometry_settings_group.sizeHint().height(),
                )
            )
        self.ready_grid.refresh_layout()
        self._refresh_ready_grid_layout()
        # All subsection heights are calculated from their current responsive
        # widths above; a deferred duplicate pass would only expose a transient
        # first geometry to hover and input events.

    def _refresh_slicer_section_layout(self, _expanded: bool | None = None) -> None:
        """Publish the full responsive Slicer height without clipping controls."""

        self.slicer_group.setMinimumHeight(0)
        self.slicer_group.content_widget.setMinimumHeight(0)
        self.slicer_columns.refresh_layout()
        self.slicer_selectors_layout.invalidate()
        self.slicer_selectors_layout.activate()
        self.slicer_selector_column.updateGeometry()
        self.slicer_columns.grid.invalidate()
        self.slicer_columns.grid.activate()
        self.slicer_columns.updateGeometry()
        self.slicer_group.content_layout.invalidate()
        self.slicer_group.content_layout.activate()
        self.slicer_group.content_widget.updateGeometry()
        self.slicer_group.updateGeometry()
        if self.slicer_group.isChecked():
            self.slicer_group.content_widget.setMinimumHeight(
                self.slicer_group.content_widget.sizeHint().height()
            )
            self.slicer_group.setMinimumHeight(
                self.slicer_group.sizeHint().height()
            )
        self._update_slicer_combo_widths()
        self._refresh_settings_content_minimum_height()

    def _on_settings_scroll_range_changed(
        self,
        _minimum: int,
        _maximum: int,
    ) -> None:
        self._update_slicer_combo_widths()
        QTimer.singleShot(0, self._update_slicer_combo_widths)

    def _refresh_ready_grid_layout(self) -> None:
        """Refresh the shared grid without changing any sibling card state."""

        self.ready_grid.setMinimumHeight(0)
        self.ready_grid.setMaximumHeight(16777215)
        self.ready_grid.refresh_layout()
        self.ready_grid.grid.invalidate()
        required_grid_height = self.ready_grid.content_height_hint()
        if required_grid_height > 0:
            # Compute from each card's height-for-width result, not its current
            # geometry.  Current geometry still contains the collapsed height
            # during the toggle signal and caused sibling cards to stay shut.
            self.ready_grid.setFixedHeight(required_grid_height)
        self.ready_grid.grid.activate()
        self.ready_grid.updateGeometry()
        self._refresh_settings_content_minimum_height()
        # ``content_height_hint`` already evaluates every child at its target
        # width, so a deferred second sizing pass is no longer necessary.

    def _refresh_settings_content_minimum_height(self) -> None:
        content = self.settings_scroll.widget()
        if content is None:
            return
        content.updateGeometry()
        layout = content.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            required_height = max(0, layout.sizeHint().height())
            if content.minimumHeight() != required_height:
                # QScrollArea can cache the resizable child's previous size
                # hint after a deeply nested grid row changes. Synchronising
                # only the vertical minimum makes the new scroll range explicit
                # without imposing a horizontal minimum at narrow widths.
                content.setMinimumHeight(required_height)
                content.updateGeometry()
                layout.invalidate()
                layout.activate()

    @staticmethod
    def _set_status_indicator(
        icon_label: QLabel,
        text_label: QLabel,
        icon: str,
        text: str,
        state: str,
    ) -> None:
        icon_label.setText(icon)
        icon_label.setProperty("state", state)
        text_label.setText(text)
        text_label.setProperty("state", state)
        MainWindow._refresh_widget_style(icon_label)
        MainWindow._refresh_widget_style(text_label)

    def _set_main_status(
        self,
        text: str,
        *,
        icon: str = "○",
        state: str = "idle",
    ) -> None:
        prominent = text == "Bitte G-Code auswählen"
        self.status_icon_label.setProperty("prominent", prominent)
        self.status_icon_label.setMinimumWidth(24 if prominent else 18)
        self._refresh_widget_style(self.status_icon_label)
        self._set_status_indicator(
            self.status_icon_label,
            self.status_label,
            icon,
            text,
            state,
        )
        self._schedule_footer_height_update()

    def _schedule_footer_height_update(self) -> None:
        """Recalculate the bounded footer after text or visibility changes."""

        if hasattr(self, "_footer_height_timer"):
            self._footer_height_timer.start(0)

    def _register_footer_notice(
        self,
        severity: str,
        panel: FooterNoticeDropdown,
    ) -> None:
        """Register a priority-sorted notice in the left footer column."""

        if severity not in self._footer_notice_panels:
            raise ValueError(f"Unbekannte Hinweisart: {severity}")
        self._footer_notice_panels[severity].append(panel)
        panel.setParent(self.footer_notice_host)
        panel.toggled.connect(
            lambda _expanded: self._schedule_footer_height_update()
        )
        self._refresh_footer_notice_layout()
        self._schedule_footer_height_update()

    def _show_settings_load_notice(self) -> None:
        warning = self.settings_store.last_load_warning
        self.settings_load_notice_label.setText(warning or "")
        self.settings_load_notice_panel.setVisible(bool(warning))
        if warning:
            self.settings_load_notice_panel.reset_collapsed()
        self._refresh_footer_notice_layout()
        self._schedule_footer_height_update()

    def _refresh_footer_notice_layout(self) -> None:
        """Order left-column dropdowns from critical to informational."""

        if not hasattr(self, "footer_notice_layout"):
            return
        active_panels = tuple(
            panel
            for severity in ("error", "warning", "info")
            for panel in self._footer_notice_panels[severity]
            if not panel.isHidden()
        )
        self._active_footer_notice_severities = tuple(
            severity
            for severity in ("error", "warning", "info")
            if any(
                not panel.isHidden()
                for panel in self._footer_notice_panels[severity]
            )
        )
        while self.footer_notice_layout.count():
            self.footer_notice_layout.takeAt(0)
        for panel in active_panels:
            self.footer_notice_layout.addWidget(panel)

        signature = tuple(id(panel) for panel in active_panels)
        if signature != self._last_footer_notice_signature:
            if len(active_panels) == 1:
                active_panels[0].set_expanded(True)
            elif len(active_panels) > 1:
                for panel in active_panels:
                    panel.set_expanded(False)
            self._last_footer_notice_signature = signature
        self.footer_notice_host.setVisible(bool(active_panels))
        if hasattr(self, "footer_status_layout"):
            self.footer_status_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_notice_layout.invalidate()
        self.footer_notice_layout.activate()

    def _refresh_footer_auxiliary_visibility(self) -> None:
        """Show the right footer column and separator only with real content."""

        if not hasattr(self, "footer_action_area"):
            return
        action_widgets = (
            self.open_output_button,
            self.open_stl_button,
            self.preview_action_control,
            self.export_button,
            self.open_run_button,
        )
        has_right_content = (
            not self.action_availability_widget.isHidden()
            or any(not widget.isHidden() for widget in action_widgets)
        )
        self.footer_action_area.setVisible(has_right_content)
        if self._footer_narrow_layout:
            self.footer_horizontal_divider.setVisible(has_right_content)
            self.footer_vertical_divider.hide()
        else:
            self.footer_vertical_divider.setVisible(has_right_content)
            self.footer_horizontal_divider.hide()

    def _refresh_footer_responsive_layout(self, *, force: bool = False) -> None:
        """Switch between two footer columns and the narrow vertical stack."""

        if not hasattr(self, "footer_content_grid"):
            return
        narrow = self.width() < METRICS.responsive_breakpoint_px
        if not force and narrow == self._footer_narrow_layout:
            return
        self._footer_narrow_layout = narrow
        while self.footer_content_grid.count():
            self.footer_content_grid.takeAt(0)
        for column in range(3):
            self.footer_content_grid.setColumnStretch(column, 0)
        for row in range(3):
            self.footer_content_grid.setRowStretch(row, 0)
        if narrow:
            self.footer_vertical_divider.hide()
            self.footer_horizontal_divider.show()
            self.footer_content_grid.addWidget(
                self.footer_messages_scroll,
                0,
                0,
                1,
                3,
                Qt.AlignmentFlag.AlignTop,
            )
            self.footer_content_grid.addWidget(
                self.footer_horizontal_divider, 1, 0, 1, 3
            )
            self.footer_content_grid.addWidget(
                self.footer_action_area, 2, 0, 1, 3
            )
            self.footer_content_grid.setColumnStretch(0, 1)
            self.footer.setMaximumHeight(MAIN_FOOTER_NARROW_MAX_HEIGHT_PX)
        else:
            self.footer_horizontal_divider.hide()
            self.footer_vertical_divider.show()
            self.footer_content_grid.addWidget(
                self.footer_messages_scroll,
                0,
                0,
                1,
                1,
                Qt.AlignmentFlag.AlignTop,
            )
            self.footer_content_grid.addWidget(
                self.footer_vertical_divider, 0, 1
            )
            self.footer_content_grid.addWidget(
                self.footer_action_area, 0, 2
            )
            self.footer_content_grid.setColumnStretch(0, 1)
            self.footer_content_grid.setColumnStretch(2, 1)
            self.footer.setMaximumHeight(MAIN_FOOTER_MAX_HEIGHT_PX)
        self.footer_content_grid.invalidate()
        self.footer_content_grid.activate()
        self._refresh_footer_auxiliary_visibility()

    def _fit_footer_height(self) -> None:
        """Use only the required height while keeping the action row visible."""

        if not hasattr(self, "footer_messages_scroll"):
            return
        self._refresh_footer_responsive_layout()
        self._refresh_footer_notice_layout()
        self.footer_messages_content.setMinimumHeight(0)
        self.footer_messages_layout.invalidate()
        self.footer_messages_layout.activate()
        self.footer_status_layout.invalidate()
        self.footer_status_layout.activate()
        self.footer_notice_layout.invalidate()
        self.footer_notice_layout.activate()
        self.main_actions_layout.invalidate()
        self.main_actions_layout.activate()
        self.footer_action_layout.invalidate()
        self.footer_action_layout.activate()

        margins = self.footer_layout.contentsMargins()
        maximum_height = (
            MAIN_FOOTER_NARROW_MAX_HEIGHT_PX
            if self._footer_narrow_layout
            else MAIN_FOOTER_MAX_HEIGHT_PX
        )
        left_width = max(120, self.footer_messages_scroll.viewport().width())
        left_natural_height = max(
            0,
            self.footer_messages_layout.heightForWidth(left_width)
            if self.footer_messages_layout.hasHeightForWidth()
            else self.footer_messages_layout.sizeHint().height(),
        )
        right_natural_height = max(
            0, self.footer_action_layout.sizeHint().height()
        )
        inner_maximum = max(
            0, maximum_height - margins.top() - margins.bottom()
        )
        if self._footer_narrow_layout:
            separators = self.footer_content_grid.verticalSpacing() * 2 + 1
            left_available = max(
                36,
                inner_maximum - right_natural_height - separators,
            )
            visible_left_height = min(left_natural_height, left_available)
            content_height = (
                visible_left_height + separators + right_natural_height
            )
        else:
            visible_left_height = min(left_natural_height, inner_maximum)
            content_height = max(visible_left_height, right_natural_height)
        self.footer_messages_content.setMinimumHeight(left_natural_height)
        self.footer_messages_scroll.setFixedHeight(visible_left_height)
        self.footer_action_area.setMinimumHeight(right_natural_height)
        target_height = margins.top() + margins.bottom() + content_height
        bounded_height = min(maximum_height, target_height)
        self.footer.setMinimumHeight(bounded_height)
        self.footer.setMaximumHeight(maximum_height)
        self.footer_messages_scroll.updateGeometry()
        self.footer.updateGeometry()

    def _set_gcode_progress_status(
        self,
        text: str,
        *,
        icon: str,
        state: str,
    ) -> None:
        self._set_status_indicator(
            self.gcode_progress_icon_label,
            self.gcode_progress_status_label,
            icon,
            text,
            state,
        )

    def _set_slicer_progress(
        self,
        percent: int,
        text: str,
        *,
        icon: str,
        state: str,
    ) -> None:
        self.slicer_progress_bar.setValue(max(0, min(100, percent)))
        self.slicer_progress_bar.show()
        self.slicer_progress_status_widget.show()
        self._set_status_indicator(
            self.slicer_progress_icon_label,
            self.slicer_progress_status_label,
            icon,
            text,
            state,
        )

    def _toggle_reconstructed_config(self, expanded: bool) -> None:
        self.reconstructed_config_text.setVisible(expanded)
        self.reconstructed_config_toggle.setText(
            "Rekonstruierte Konfiguration ausblenden ▾"
            if expanded
            else "Rekonstruierte Konfiguration anzeigen ▸"
        )
        if expanded:
            QTimer.singleShot(0, self._fit_reconstructed_config_height)

    def _fit_reconstructed_config_height(self) -> None:
        if not self.reconstructed_config_text.isVisible():
            return
        document = self.reconstructed_config_text.document()
        document.setTextWidth(
            max(120, self.reconstructed_config_text.viewport().width())
        )
        height = int(document.size().height())
        frame = self.reconstructed_config_text.frameWidth() * 2
        self.reconstructed_config_text.setFixedHeight(max(70, height + frame + 12))

    def _show_reconstructed_configuration(
        self,
        snapshot: GCodeAnalysisSnapshot | None,
    ) -> None:
        values = (
            tuple(snapshot.metadata.typed_config)
            if snapshot is not None
            else ()
        )
        self.reconstructed_config_toggle.blockSignals(True)
        self.reconstructed_config_toggle.setChecked(False)
        self.reconstructed_config_toggle.blockSignals(False)
        self.reconstructed_config_text.hide()
        self.reconstructed_config_text.setPlainText(
            "\n".join(f"{item.key} = {item.raw_value}" for item in values)
        )
        self.reconstructed_config_toggle.setText(
            "Rekonstruierte Konfiguration anzeigen ▸"
        )
        self.reconstructed_config_toggle.setVisible(bool(values))

    def _clear_slicer_prediction(self) -> None:
        self._slicer_prediction_request_id += 1
        self.background_job_manager.cancel_jobs(
            JobKind.SLICER_PREDICTION,
            reason="prediction_invalidated",
        )
        self._slicer_prediction_estimate_s = None
        self._slicer_prediction_status = ""

    def _slicer_prediction_is_offered(self) -> bool:
        installation = self.selected_slicer_installation
        return bool(installation is not None and installation.can_slice)

    def _slicer_prediction_can_start(self) -> bool:
        result = self.profile_match_result
        return bool(
            self._slicer_prediction_is_offered()
            and result is not None
            and result.selected is not None
            and result.can_use_stl_mode
            and result.execution_slicer.can_slice
            and self.analysis_snapshot is not None
            and self.tower_assessment is not None
            and self.tower_assessment.tower_required
            and self.profile_feasibility is not None
            and self.profile_feasibility.feasible
            and self.preview_state is not PreviewState.BUILDING
            and not self.background_job_manager.has_active(
                JobKind.SLICER_PREDICTION
            )
            and not self.background_job_manager.has_active(JobKind.PREVIEW)
            and not self.background_job_manager.has_active(JobKind.EXPORT)
        )

    def _refresh_prediction_advice(self, estimate_kind: str) -> None:
        analytical = estimate_kind == "Analytische Schätzung"
        offered = analytical and self._slicer_prediction_is_offered()
        running = self.background_job_manager.has_active(
            JobKind.SLICER_PREDICTION
        )
        preview_running = bool(
            self.preview_state is PreviewState.BUILDING
            or self.background_job_manager.has_active(JobKind.PREVIEW)
        )
        self.prediction_advice_frame.setProperty("active", analytical)
        self.prediction_advice_label.setVisible(analytical)
        self.prediction_advice_label.setText(
            "Die analytische Schätzung ist relativ ungenau.\n"
            "Eine Slicer-gestützte Schätzung wird empfohlen."
            if analytical
            else ""
        )
        self.slicer_prediction_button.setVisible(offered)
        self.slicer_prediction_button.setEnabled(
            offered and self._slicer_prediction_can_start()
        )
        self.slicer_prediction_button.setText(
            "Slicer-Schätzung läuft …"
            if running
            else "Schätzung wird durchgeführt..."
            if preview_running
            else "Slicer-Schätzung\ndurchführen"
        )
        if offered and not running and not self._slicer_prediction_can_start():
            if (
                self.preview_state is PreviewState.BUILDING
                or self.background_job_manager.has_active(JobKind.PREVIEW)
            ):
                tooltip = (
                    "Während die Vorschau erstellt wird, kann keine separate "
                    "Slicer-Schätzung gestartet werden."
                )
            else:
                tooltip = (
                    "Die Schätzung ist verfügbar, sobald G-Code, "
                    "Profilzuordnung und Geometrieprüfung abgeschlossen sind."
                )
            self.slicer_prediction_button.setToolTip(tooltip)
        else:
            self.slicer_prediction_button.setToolTip("")
        status = self._slicer_prediction_status if analytical else ""
        self.slicer_prediction_status_label.setText(status)
        self.slicer_prediction_status_label.setVisible(bool(status))
        self._refresh_widget_style(self.prediction_advice_frame)
        advice_layout = self.prediction_advice_frame.layout()
        if advice_layout is not None:
            advice_layout.invalidate()
            advice_layout.activate()
        self.prediction_advice_frame.updateGeometry()
        self.prediction_content_grid.invalidate()
        self.prediction_content_grid.activate()
        QTimer.singleShot(0, self._fit_prediction_advice_height)

    def _fit_prediction_advice_height(self) -> None:
        """Keep the advice panel at its current content's natural height."""

        if not hasattr(self, "prediction_advice_frame"):
            return
        layout = self.prediction_advice_frame.layout()
        if layout is None:
            return
        layout.invalidate()
        layout.activate()
        natural_height = max(0, layout.sizeHint().height())
        if self.prediction_advice_frame.height() != natural_height:
            self.prediction_advice_frame.setFixedHeight(natural_height)
        self.prediction_advice_frame.updateGeometry()
        self.prediction_content_grid.invalidate()
        self.prediction_content_grid.activate()
        self._refresh_ready_grid_layout()

    def start_slicer_prediction(self) -> None:
        """Run a one-off slicer estimate with exactly five iterations."""

        if not self._slicer_prediction_can_start():
            self._slicer_prediction_status = (
                "Die Profilzuordnung oder Geometrieprüfung ist noch nicht abgeschlossen."
            )
            self._refresh_prediction_advice("Analytische Schätzung")
            return
        fixed_config = replace(
            self._calibration_config(),
            maximum_iterations=5,
        )
        try:
            request = self._current_preview_request(
                calibration_config=fixed_config,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self._slicer_prediction_status = german_user_message(error)
            self._refresh_prediction_advice("Analytische Schätzung")
            return

        self._slicer_prediction_request_id += 1
        request_id = self._slicer_prediction_request_id
        self._slicer_prediction_estimate_s = None
        self._slicer_prediction_status = (
            "Slicer-gestützte Schätzung mit fest fünf Durchläufen wird erstellt …"
        )
        worker = PreviewWorker(request_id, request, self.preview_service)
        worker.progress.connect(self._on_slicer_prediction_progress)
        worker.succeeded.connect(self._on_slicer_prediction_succeeded)
        worker.failed.connect(self._on_slicer_prediction_failed)
        self._refresh_prediction()
        self._refresh_phase17_actions()
        self.background_job_manager.start_job(
            kind=JobKind.SLICER_PREDICTION,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"prediction-{request_id}",
        )

    def _on_slicer_prediction_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._slicer_prediction_request_id or self._closing:
            return
        self._slicer_prediction_status = (
            f"{max(0, min(100, percent))} % · "
            f"{german_user_message(status)}"
        )
        self._refresh_prediction_advice("Analytische Schätzung")

    def _on_slicer_prediction_succeeded(
        self,
        request_id: int,
        result: PreviewResult,
    ) -> None:
        try:
            if request_id != self._slicer_prediction_request_id or self._closing:
                return
            estimate = result.minimum_verified_layer_time_s
            if estimate is None:
                self._slicer_prediction_status = (
                    "Der Slicer lieferte noch keine belastbare Layerzeit. "
                    "Die analytische Schätzung bleibt aktiv."
                )
                self._slicer_prediction_estimate_s = None
            else:
                self._slicer_prediction_estimate_s = float(estimate)
                self._slicer_prediction_status = ""
        finally:
            result.dispose()
        self._refresh_prediction()

    def _on_slicer_prediction_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._slicer_prediction_request_id or self._closing:
            return
        self._slicer_prediction_estimate_s = None
        self._slicer_prediction_status = (
            "Slicer-gestützte Schätzung fehlgeschlagen: "
            f"{german_user_message(message)}"
        )
        self._refresh_prediction()

    def _refresh_prediction(self) -> None:
        if not hasattr(self, "prediction_label"):
            return
        snapshot = self.analysis_snapshot
        assessment = self.tower_assessment
        if snapshot is None or assessment is None:
            self.prediction_label.setText(
                "Noch nicht verfügbar"
            )
            self.prediction_label.setProperty("state", "pending")
            self.prediction_method_label.setText("Schätzung ausstehend")
            self.prediction_method_label.setProperty("mode", "pending")
            self._refresh_widget_style(self.prediction_method_label)
            for label in self.prediction_value_labels.values():
                label.setText("–")
                label.setProperty("state", "pending")
                self._refresh_widget_style(label)
            self.prediction_frame.set_state(SectionState.NEUTRAL)
            self.prediction_frame.set_summary("Schätzung ausstehend")
            self._refresh_prediction_advice("Schätzung ausstehend")
            self._refresh_widget_style(self.prediction_label)
            self._update_section_summaries()
            return

        estimate = None
        estimate_kind = "Analytische Schätzung"
        if (
            self.preview_state is PreviewState.CURRENT
            and self.current_preview is not None
            and self.current_preview.minimum_verified_layer_time_s is not None
        ):
            estimate = self.current_preview.minimum_verified_layer_time_s
            estimate_kind = "Slicer-gestützte Annäherung"
        elif self._slicer_prediction_estimate_s is not None:
            estimate = self._slicer_prediction_estimate_s
            estimate_kind = "Slicer-gestützte Annäherung"
        elif self.profile_feasibility is not None:
            estimate = (
                self.profile_feasibility
                .estimated_minimum_combined_layer_time_s
            )
        elif not assessment.tower_required:
            estimate = snapshot.minimum_layer_time_s

        target = assessment.target_layer_time_s
        self.prediction_method_label.setText(estimate_kind)
        self.prediction_value_labels["target"].setText(
            f"{_de_number(target)} s"
        )
        self.prediction_value_labels["critical"].setText(
            f"{assessment.deficit_layer_count}"
        )
        tower_height = assessment.tower_end_z_mm
        self.prediction_value_labels["height"].setText(
            f"{_de_number(tower_height)} mm" if tower_height is not None else "–"
        )
        geometry_invalid = bool(self._feasibility_issue_summaries) or (
            self.profile_feasibility is not None
            and not self.profile_feasibility.feasible
        )
        if geometry_invalid:
            self.prediction_label.setText(
                "Ziel mit den aktuellen Geometriegrenzen nicht erreichbar"
            )
            self.prediction_method_label.setText("Schätzung nicht belastbar")
            estimate_kind = "Schätzung nicht belastbar"
            self.prediction_value_labels["minimum"].setText("–")
            self.prediction_value_labels["shortfall"].setText("–")
            state = "error"
        elif estimate is None:
            self.prediction_label.setText(
                "Mit den aktuellen Daten noch nicht vollständig berechenbar."
            )
            self.prediction_value_labels["minimum"].setText("Noch nicht berechenbar")
            self.prediction_value_labels["shortfall"].setText("–")
            state = "pending"
        else:
            shortfall = max(0.0, target - estimate)
            reached = shortfall <= 1e-6
            self.prediction_label.setText(
                "Ziel voraussichtlich erreicht"
                if reached
                else "Ziel voraussichtlich nicht erreicht"
            )
            self.prediction_value_labels["minimum"].setText(
                f"{_de_number(estimate)} s"
            )
            self.prediction_value_labels["shortfall"].setText(
                "Keine erwartet" if reached else f"{_de_number(shortfall)} s"
            )
            state = "available" if reached else "warning"
        self.prediction_label.setProperty("state", state)
        method_mode = (
            "analytical"
            if estimate_kind == "Analytische Schätzung"
            else "slicer"
            if estimate_kind == "Slicer-gestützte Annäherung"
            else "neutral"
        )
        self.prediction_method_label.setProperty("mode", method_mode)
        self._refresh_widget_style(self.prediction_method_label)
        for key, label in self.prediction_value_labels.items():
            row_state = (
                "warning"
                if state == "warning" and key in {"minimum", "shortfall"}
                else "error"
                if state == "error" and key in {"minimum", "shortfall"}
                else "normal"
            )
            label.setProperty("state", row_state)
            self._refresh_widget_style(label)
        self._refresh_widget_style(self.prediction_label)
        card_state = {
            "available": SectionState.SUCCESS,
            "warning": SectionState.WARNING,
            "error": SectionState.ERROR,
            "pending": SectionState.NEUTRAL,
        }[state]
        self.prediction_frame.set_state(card_state)
        self.prediction_frame.set_summary(self.prediction_label.text())
        self._refresh_prediction_advice(estimate_kind)
        self._update_section_summaries()

    def _on_value_changed(self, value) -> None:
        if self._closing:
            return
        sender = self.sender()
        changed_setting_name = self._last_changed_setting_name
        for name, setting in self._setting_widgets.items():
            if sender is setting.editor:
                self._last_changed_setting_name = name
                changed_setting_name = name
                # A later ordinary edit supersedes a previously queued reset.
                self._pending_reset_setting_name = None
                break
        if sender is self.maximum_expansion_angle_spin:
            self._update_expansion_angle_warning()
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self.profile_feasibility = None
        self._invalidate_preview(
            "Kühlturmeinstellungen wurden geändert.",
        )
        self.update_wall_path_preview()
        self._refresh_tower_assessment()
        self._discard_feasibility_issues_for_setting(changed_setting_name)
        self.validate_form()
        self._schedule_feasibility_validation()
        self._refresh_stl_availability()
        self._update_section_summaries()

    def _on_numeric_input_state_changed(
        self,
        setting_name: str,
        acceptable: bool,
    ) -> None:
        self._last_changed_setting_name = setting_name
        if acceptable:
            self._incomplete_setting_names.discard(setting_name)
        else:
            self._incomplete_setting_names.add(setting_name)
            self.profile_feasibility = None
            self._feasibility_timer.stop()
            self._cancel_feasibility_jobs()
        self._invalidate_preview(
            "Eine Kühlturmeingabe wurde geändert.",
        )
        self._discard_feasibility_issues_for_setting(setting_name)
        self.validate_form()

    def _on_individual_reset(self, _setting_name: str) -> None:
        self._last_changed_setting_name = _setting_name
        self._pending_reset_setting_name = _setting_name
        self._on_value_changed(None)

    def _on_output_root_changed(self, _text: str) -> None:
        if not self._loading_phase17_state:
            self._last_changed_setting_name = "output_root"
        self._update_section_summaries()
        self.validate_form()
        self._refresh_folder_action_states()

    def _reset_output_root(self) -> None:
        self.output_root_edit.setText(str(self.default_output_root))
        self.output_root_edit.selectAll()

    def remove_gcode(self) -> None:
        if self.background_job_manager.has_active(JobKind.EXPORT):
            self.result_label.setText(
                "Der G-Code kann erst nach Abschluss des laufenden Exports entfernt werden."
            )
            return
        self._analysis_request_id += 1
        self._workflow_error_message = None
        self._profile_request_id += 1
        self._feasibility_request_id += 1
        self._preview_request_id += 1
        self._clear_slicer_prediction()
        self.background_job_manager.cancel_jobs(
            JobKind.ANALYSIS,
            reason="gcode_removed",
        )
        self.background_job_manager.cancel_jobs(
            JobKind.PROFILE_MATCH,
            reason="gcode_removed",
        )
        self._cancel_feasibility_jobs()
        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="gcode_removed",
        )
        if self.current_preview is not None:
            self.current_preview.dispose()
        self.current_preview = None
        self.preview_state = PreviewState.EMPTY
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.set_scene(None)
            self._preview_dialog.mark_stale()
        self.current_gcode_path = None
        self.analysis_snapshot = None
        self.tower_assessment = None
        self.profile_feasibility = None
        self.profile_match_result = None
        self.profile_preview_outdated = False
        self._analysis_failed = False
        self._clear_feasibility_issues()
        self.last_export_result = None
        self.drop_zone.clear_file()
        self.gcode_progress_bar.setValue(0)
        self.gcode_progress_bar.hide()
        self.gcode_progress_status_widget.hide()
        self._show_reconstructed_configuration(None)
        self._clear_profile_assignment(
            "Profilzuordnung beginnt nach G-Code- und Slicerauswahl.",
            "pending",
        )
        self._set_tower_need_message(
            "Bitte zuerst einen G-Code auswählen.", "pending"
        )
        self.result_label.clear()
        self.warning_text.clear()
        self.warning_text.hide()
        self._refresh_issue_panels()
        self.validation_label.clear()
        self._refresh_folder_action_states()
        self.open_run_button.setEnabled(False)
        self.preview_hint_label.setProperty("state", "current")
        self.preview_hint_label.setText(
            "Beim Export wird der Kühlturm immer mit den aktuellen "
            "Einstellungen erzeugt."
        )
        self._refresh_widget_style(self.preview_hint_label)
        self._set_main_status(
            "Bitte G-Code auswählen",
            icon="⇧",
            state="idle",
        )
        self._refresh_prediction()
        self.workflow.reset()
        self.validate_form()

    def reload_gcode(self) -> None:
        """Read and analyse the selected G-code again from disk."""

        if self.background_job_manager.has_active(JobKind.EXPORT):
            self.result_label.setText(
                "Der G-Code kann erst nach Abschluss des laufenden Exports "
                "neu eingelesen werden."
            )
            return
        path = self.current_gcode_path or self.drop_zone.selected_path
        if path is None or not path.is_file():
            self._show_input_error(
                "Die ausgewählte G-Code-Datei ist nicht mehr verfügbar."
            )
            return
        self._on_file_selected(str(path.resolve()))

    def _on_base_mode_changed(self, state: int) -> None:
        if self._closing:
            return
        automatic = self.automatic_base_checkbox.isChecked()
        self._last_changed_setting_name = "automatic_base_width"
        self._pending_reset_setting_name = None
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self.manual_base_width_spin.setEnabled(not automatic)
        self._setting_widgets["manual_base_width_mm"].setVisible(not automatic)
        self.automatic_base_width_label.setVisible(automatic)
        self.automatic_base_reset_button.setVisible(not automatic)
        self.profile_feasibility = None
        self._invalidate_preview("Die Standfußberechnung wurde geändert.")
        self._update_automatic_base_width_preview()
        self._refresh_tower_assessment()
        self._update_section_summaries()
        self.validate_form()
        self._schedule_feasibility_validation()

    def _on_file_selected(self, path: str) -> None:
        self._last_changed_setting_name = None
        self._workflow_error_message = None
        self.workflow.begin_analysis()
        self._invalidate_preview("Eine andere G-Code-Datei wurde ausgewählt.")
        self.current_gcode_path = Path(path)
        self.analysis_snapshot = None
        self.profile_preview_outdated = True
        self._profile_request_id += 1
        self._clear_profile_assignment(
            "Profilzuordnung wartet auf die neue G-Code-Analyse.",
            "pending",
        )
        self.tower_assessment = None
        self.profile_feasibility = None
        self._clear_feasibility_issues()
        self._feasibility_timer.stop()
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self._analysis_failed = False
        self.last_export_result = None
        self.result_label.clear()
        self.warning_text.clear()
        self.warning_text.hide()
        self._refresh_issue_panels()
        self._refresh_folder_action_states()
        self.open_run_button.setEnabled(False)
        self.validation_label.clear()
        self.drop_zone.set_status("Analyse läuft")
        self._show_reconstructed_configuration(None)
        self._refresh_prediction()
        self._start_gcode_analysis(self.current_gcode_path)
        self.validate_form()

    def _start_gcode_analysis(self, path: Path) -> None:
        self.background_job_manager.cancel_jobs(
            JobKind.ANALYSIS,
            reason="analysis_replaced",
        )

        self._analysis_request_id += 1
        request_id = self._analysis_request_id
        self.workflow.begin_analysis()
        self.drop_zone.set_analysis_state("analyzing")
        self._set_tower_need_message(
            "G-Code wird analysiert …",
            "analyzing",
        )
        self.gcode_progress_bar.setValue(0)
        self.gcode_progress_bar.show()
        self.gcode_progress_status_widget.show()
        self._set_gcode_progress_status(
            "G-Code wird analysiert …", icon="⏳", state="running"
        )
        self._set_main_status(
            "G-Code wird analysiert …", icon="⏳", state="running"
        )

        worker = AnalysisWorker(
            request_id,
            path,
            self.analysis_service,
        )
        worker.progress.connect(self._on_analysis_progress)
        worker.succeeded.connect(self._on_analysis_succeeded)
        worker.failed.connect(self._on_analysis_failed)
        self.background_job_manager.start_job(
            kind=JobKind.ANALYSIS,
            request_id=request_id,
            worker=worker,
        )

    def _on_analysis_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._analysis_request_id:
            return
        value = max(0, min(100, percent))
        status = german_user_message(status)
        self.gcode_progress_bar.setValue(value)
        self._set_gcode_progress_status(
            status, icon="⏳", state="running"
        )
        self.drop_zone.set_status("Analyse läuft")
        if not self.result_label.text():
            self._set_main_status(status, icon="⏳", state="running")

    def _on_analysis_succeeded(
        self,
        request_id: int,
        snapshot: GCodeAnalysisSnapshot,
    ) -> None:
        if request_id != self._analysis_request_id:
            return
        if self.current_gcode_path is None:
            return
        if snapshot.gcode_path != self.current_gcode_path.resolve():
            return
        self.analysis_snapshot = snapshot
        self._workflow_error_message = None
        self._update_local_window_layer_limit(snapshot.layer_count)
        self._analysis_failed = False
        self.drop_zone.set_status("Analyse abgeschlossen")
        self.drop_zone.set_analysis_state("ready")
        self.gcode_progress_bar.setValue(100)
        self.gcode_progress_bar.show()
        self.gcode_progress_status_widget.show()
        self._set_gcode_progress_status(
            "G-Code-Analyse abgeschlossen", icon="✓", state="success"
        )
        self._show_reconstructed_configuration(snapshot)
        self.workflow.analysis_succeeded(
            f"{self.current_gcode_path.name} · {snapshot.layer_count} Layer"
        )
        if not self.result_label.text():
            self._set_main_status(
                f"{snapshot.layer_count} Layer analysiert · "
                f"kleinste Layerzeit "
                f"{snapshot.minimum_layer_time_s:.3f} s · "
                f"maximale Druckhöhe "
                f"{snapshot.maximum_print_z_mm:.3f} mm",
                icon="✓",
                state="success",
            )
        self._refresh_tower_assessment()
        self.validate_form()
        self._schedule_feasibility_validation()
        if (
            self._slicer_service_was_injected
            or os.environ.get("QT_QPA_PLATFORM", "").casefold() != "offscreen"
        ):
            self.start_slicer_discovery()
        else:
            self.workflow.slicer_unavailable(
                "Slicer-Suche in dieser Sitzung deaktiviert"
            )

    def _update_local_window_layer_limit(self, layer_count: int) -> None:
        """Use the analyzed G-code's layer count as the visible upper bound."""

        maximum = max(1, int(layer_count))
        self.local_window_spin.setProperty("validationMaximum", maximum)
        if self.local_window_spin.value() > maximum:
            # The centered local window must stay odd.  Keep the displayed
            # maximum equal to the actual layer count, but select the largest
            # usable window when a newly loaded, shorter G-code requires it.
            adjusted = maximum if maximum % 2 else max(1, maximum - 1)
            self.local_window_spin.blockSignals(True)
            self.local_window_spin.setValue(adjusted)
            self.local_window_spin.blockSignals(False)
        self._setting_widgets[
            "local_reference_window"
        ].refresh_range_state()

    def _on_analysis_failed(
        self,
        request_id: int,
        message: str,
        details: str,
    ) -> None:
        if request_id != self._analysis_request_id:
            return
        self.analysis_snapshot = None
        self.tower_assessment = None
        self.profile_feasibility = None
        self._clear_feasibility_issues()
        self._analysis_failed = True
        self._workflow_error_message = german_user_message(message)
        self._set_tower_need_message(
            "Die G-Code-Datei konnte nicht analysiert werden.",
            "error",
        )
        self.drop_zone.set_status("Analyse fehlgeschlagen")
        self.drop_zone.set_analysis_state("failed")
        self.gcode_progress_bar.setValue(0)
        self.gcode_progress_bar.show()
        self.gcode_progress_status_widget.show()
        self._set_gcode_progress_status(
            "G-Code-Analyse fehlgeschlagen", icon="✕", state="error"
        )
        self.workflow.analysis_failed()
        self._set_main_status(
            "G-Code-Analyse fehlgeschlagen", icon="✕", state="error"
        )
        self._show_reconstructed_configuration(None)
        self._refresh_prediction()
        self._refresh_stl_availability()
        self.validate_form()

    def _refresh_tower_assessment(self) -> None:
        snapshot = self.analysis_snapshot
        if snapshot is None:
            self.tower_assessment = None
            self.profile_feasibility = None
            self._refresh_prediction()
            return
        try:
            assessment = assess_tower_need(
                snapshot,
                self.collect_settings(),
            )
        except ValueError as error:
            self.tower_assessment = None
            self._set_tower_need_message(
                german_user_message(error), "error"
            )
            self._refresh_prediction()
            return

        self.tower_assessment = assessment
        self.profile_feasibility = None
        self._update_automatic_base_width_preview()
        if not assessment.tower_required:
            self._clear_feasibility_issues()
            self._set_tower_need_message(
                "Kein Kühlturm erforderlich. Alle analysierten Schichten "
                f"erreichen die Zielzeit von {assessment.target_layer_time_s:.2f} s. "
                "Die kürzeste erkannte Zeit beträgt "
                f"{snapshot.minimum_layer_time_s:.3f} s. "
                "Es wird keine STL erzeugt.",
                "notRequired",
            )
            self._refresh_prediction()
            return

        self._show_required_tower_message(assessment)
        self._refresh_prediction()

    def _show_required_tower_message(
        self,
        assessment: TowerNeedAssessment,
    ) -> None:
        synthetic_text = (
            " Für den Abschluss wird eine synthetische Schichthöhe verwendet."
            if assessment.synthetic_final_layer_used
            else ""
        )
        tower_height = (
            f"{assessment.tower_end_z_mm:.3f}"
            if assessment.tower_end_z_mm is not None
            else "-"
        )
        self._set_tower_need_message(
            "Kühlturm erforderlich. Die eingestellte Zielzeit erfordert "
            "zusätzliche Kühlzeit; berechnete "
            f"Turmhöhe: {tower_height} mm."
            f"{synthetic_text}",
            "required",
        )

    def _schedule_feasibility_validation(self) -> None:
        if self._closing:
            return
        if (
            self.analysis_snapshot is None
            or self.tower_assessment is None
            or not self.tower_assessment.tower_required
            or self._incomplete_setting_names
            or self._static_field_errors
        ):
            self._feasibility_timer.stop()
            return
        self.profile_feasibility = None
        self._feasibility_timer.start()
        self.validate_form()

    def _start_feasibility_validation(self) -> None:
        snapshot = self.analysis_snapshot
        assessment = self.tower_assessment
        if (
            self._closing
            or snapshot is None
            or assessment is None
            or not assessment.tower_required
            or not self.validate_form()
        ):
            return

        self._cancel_feasibility_jobs()
        self._feasibility_request_id += 1
        request_id = self._feasibility_request_id
        self._feasibility_request_source = (
            request_id,
            self._last_changed_setting_name,
            self._pending_reset_setting_name,
        )
        self._pending_reset_setting_name = None
        worker = FeasibilityWorker(
            request_id,
            snapshot,
            self.collect_settings(),
            assessment,
        )
        worker.succeeded.connect(self._on_feasibility_succeeded)
        worker.failed.connect(self._on_feasibility_failed)
        self.background_job_manager.start_job(
            kind=JobKind.FEASIBILITY,
            request_id=request_id,
            worker=worker,
        )

    def _on_feasibility_succeeded(
        self,
        request_id: int,
        result: ProfileFeasibilityAssessment,
    ) -> None:
        if request_id != self._feasibility_request_id or self._closing:
            return
        request_source = (
            self._feasibility_request_source[1]
            if self._feasibility_request_source is not None
            and self._feasibility_request_source[0] == request_id
            else self._last_changed_setting_name
        )
        reset_setting_name = (
            self._feasibility_request_source[2]
            if self._feasibility_request_source is not None
            and self._feasibility_request_source[0] == request_id
            else None
        )
        self._feasibility_request_source = None
        self.profile_feasibility = result
        self._feasibility_issues = tuple(result.issues)
        grouped_issues = self._group_feasibility_issues(result.issues)
        self._feasibility_solution_items = list(
            dict.fromkeys(
                str(solution)
                for group in grouped_issues
                for solution in group.get("solutions", ())
            )
        )
        self._feasibility_field_errors = self._field_errors_for_issues(
            result.issues,
            source_setting_name=request_source,
            reset_setting_name=reset_setting_name,
        )
        self._feasibility_issue_summaries = [
            str(group["notice"]) for group in grouped_issues
        ]
        if not result.feasible and not self._feasibility_issue_summaries:
            self._feasibility_issue_summaries = [
                "Die Turmgeometrie ist mit den aktuellen Einstellungen "
                "nicht möglich."
            ]
        if result.feasible and not self._feasibility_issue_summaries:
            if self.tower_assessment is not None:
                self._show_required_tower_message(self.tower_assessment)
        else:
            self._set_tower_need_message(
                "Die Zielzeit kann mit den aktuellen Geometriegrenzen "
                "nicht erreicht werden. "
                f"{len(self._feasibility_issue_summaries)} Problemart(en) "
                "wurden erkannt. Die betroffenen Werte sind markiert.",
                "error",
            )
        self._refresh_prediction()
        self.validate_form()

    def _on_feasibility_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._feasibility_request_id or self._closing:
            return
        self._feasibility_request_source = None
        self.profile_feasibility = None
        self._feasibility_issues = ()
        self._feasibility_field_errors.clear()
        self._feasibility_issue_targets.clear()
        self._feasibility_issue_summaries = [
            "Die Turmgeometrie konnte nicht vollständig geprüft werden."
        ]
        self._feasibility_solution_items.clear()
        self._set_tower_need_message(
            "Die Profil-Erfüllbarkeit konnte nicht geprüft werden: "
            f"{german_user_message(message)}",
            "error",
        )
        self._refresh_prediction()
        self.validate_form()

    def _cancel_feasibility_jobs(self) -> None:
        self.background_job_manager.cancel_jobs(
            JobKind.FEASIBILITY,
            reason="feasibility_replaced",
        )

    def _discard_feasibility_issues_for_setting(
        self,
        setting_name: str | None,
    ) -> None:
        """Drop only calculated issues invalidated by a changed setting."""

        if setting_name is None or not self._feasibility_issues:
            return
        if setting_name in {"target_layer_time_s", "safety_factor"}:
            remaining: tuple[FeasibilityIssue, ...] = ()
        else:
            remaining = tuple(
                issue
                for issue in self._feasibility_issues
                if setting_name not in issue.related_setting_names
            )
        if remaining == self._feasibility_issues:
            return

        self._feasibility_issues = remaining
        grouped_issues = self._group_feasibility_issues(remaining)
        self._feasibility_solution_items = list(
            dict.fromkeys(
                str(solution)
                for group in grouped_issues
                for solution in group.get("solutions", ())
            )
        )
        self._feasibility_field_errors = self._field_errors_for_issues(
            remaining
        )
        self._feasibility_issue_summaries = [
            str(group["notice"]) for group in grouped_issues
        ]

    def _field_errors_for_issues(
        self,
        issues: tuple,
        *,
        source_setting_name: str | None = None,
        reset_setting_name: str | None = None,
    ) -> dict[str, list[str]]:
        """Map the latest authoritative issues to stable causal settings."""

        trigger = source_setting_name or self._last_changed_setting_name
        previous_targets = dict(self._feasibility_issue_targets)
        target_frequency: dict[str, int] = {}
        for target in previous_targets.values():
            if target == reset_setting_name:
                continue
            target_frequency[target] = target_frequency.get(target, 0) + 1
        dominant_target = (
            max(target_frequency, key=target_frequency.get)
            if target_frequency
            else None
        )
        grouped_errors: dict[str, list[str]] = {}
        active_targets: dict[tuple[str, tuple[str, ...]], str] = {}
        for group in self._group_feasibility_issues(issues):
            related_names = tuple(group["related_setting_names"])
            issue_key = (str(group["code"]), related_names)
            target = previous_targets.get(issue_key)
            if target == reset_setting_name:
                target = None
            if target not in self._setting_widgets:
                if trigger in {"target_layer_time_s", "safety_factor"}:
                    target = trigger
                elif dominant_target in self._setting_widgets:
                    target = dominant_target
                elif (
                    trigger != reset_setting_name
                    and trigger in related_names
                    and trigger in self._setting_widgets
                ):
                    target = trigger
                elif "target_layer_time_s" in self._setting_widgets:
                    target = "target_layer_time_s"
                else:
                    target = next(
                        (name for name in related_names if name in self._setting_widgets),
                        None,
                    )
            if target is None:
                continue
            notice = str(group["notice"])
            active_targets[issue_key] = target
            grouped_errors.setdefault(target, []).append(notice)
        self._feasibility_issue_targets = active_targets
        return {
            name: list(dict.fromkeys(messages))
            for name, messages in grouped_errors.items()
        }

    def _setting_value_description(self, setting_name: str) -> str:
        """Return a concise user-facing field name, value and unit."""

        if setting_name == "automatic_base_width":
            state = (
                "aktiviert"
                if self.automatic_base_checkbox.isChecked()
                else "deaktiviert"
            )
            return f"Automatische Standfußbreite: {state}"
        setting = self._setting_widgets.get(setting_name)
        if setting is None:
            return setting_name.replace("_", " ")
        label = " ".join(setting.label.text().split())
        editor = setting.editor
        if isinstance(editor, QDoubleSpinBox):
            value = editor.textFromValue(float(editor.value()))
        else:
            value = str(int(editor.value()))
        unit = SETTING_UNITS.get(setting_name, "").strip()
        return f"{label}: {value}{f' {unit}' if unit else ''}"

    def _footer_setting_heading(self, setting_name: str) -> str:
        """Return the black heading used for one field-related issue group."""

        if setting_name == "output_root":
            return f"Ausgabeordner: {self.output_root_edit.text().strip()}"
        return self._setting_value_description(setting_name)

    def _concise_field_message(self, setting_name: str, message: str) -> str:
        """Remove a field name/value already supplied by the group heading."""

        text = " ".join(german_user_message(message).split())
        setting = self._setting_widgets.get(setting_name)
        prefixes = [self._footer_setting_heading(setting_name)]
        if setting is not None:
            prefixes.append(" ".join(setting.label.text().split()))
        prefixes.extend(
            {
                "target_layer_time_s": ("Ziel-Layerzeit",),
                "safety_factor": ("Sicherheitsfaktor",),
                "minimum_outer_radius_mm": ("Mindest-Außenradius",),
                "maximum_outer_radius_mm": ("Maximaler Außenradius",),
                "minimum_wall_thickness_mm": ("Mindestwandstärke",),
                "maximum_wall_thickness_mm": ("Maximalwandstärke",),
                "wall_path_width_mm": ("Bahnbreite",),
                "minimum_inner_radius_mm": ("Mindest-Innenradius",),
                "manual_base_width_mm": ("Manuelle Standfußbreite",),
                "maximum_expansion_angle_deg": ("Aufweitungswinkel",),
                "maximum_contraction_angle_deg": ("Verjüngungswinkel",),
                "maximum_wall_change_per_mm_z": (
                    "Maximale Wandstärkenänderung",
                ),
                "local_reference_window": ("Lokales Zeitfenster",),
                "output_root": ("Ausgabeordner",),
            }.get(setting_name, ())
        )
        for prefix in sorted(set(prefixes), key=len, reverse=True):
            if not prefix or not text.casefold().startswith(prefix.casefold()):
                continue
            remainder = text[len(prefix):].lstrip(" :–—-")
            if remainder:
                text = remainder[0].upper() + remainder[1:]
            break
        return text

    def _group_feasibility_issues(self, issues: tuple) -> list[dict[str, object]]:
        grouped: dict[tuple[str, tuple[str, ...]], list] = {}
        for issue in issues:
            key = (issue.code, tuple(sorted(issue.related_setting_names)))
            grouped.setdefault(key, []).append(issue)

        titles = {
            "EXPANSION_ANGLE_TOO_SMALL": (
                "Maximaler Aufweitungswinkel reicht nicht aus"
            ),
            "BASE_WIDTH_TOO_SMALL": "Standfußbreite reicht nicht aus",
            "MAXIMUM_OUTER_RADIUS_REACHED": (
                "Eingestellter größter Außenradius von "
                f"{_de_number(self.maximum_outer_spin.value())} mm reicht "
                "nicht aus"
            ),
            "MAXIMUM_WALL_THICKNESS_REACHED": (
                "Eingestellte größte Wandstärke von "
                f"{_de_number(self.maximum_wall_spin.value())} mm reicht "
                "nicht aus"
            ),
            "MINIMUM_INNER_RADIUS_REACHED": "Mindest-Hohlraumradius erreicht",
        }
        remedies = {
            "EXPANSION_ANGLE_TOO_SMALL": (
                "Den maximalen Aufweitungswinkel erhöhen.",
                "Die Ziel-Layerzeit verringern.",
                "Den maximalen Außenradius oder die zulässige Wandstärke erhöhen.",
            ),
            "BASE_WIDTH_TOO_SMALL": (
                "Die automatische Standfußbreite aktivieren.",
                "Die manuelle Standfußbreite vergrößern.",
                "Die Ziel-Layerzeit verringern.",
            ),
            "MAXIMUM_OUTER_RADIUS_REACHED": (
                "Den maximalen Außenradius erhöhen.",
                "Die Ziel-Layerzeit verringern.",
                "Eine größere maximal zulässige Wandstärke verwenden.",
            ),
            "MAXIMUM_WALL_THICKNESS_REACHED": (
                "Die Maximalwandstärke erhöhen.",
                "Die Ziel-Layerzeit verringern.",
                "Den maximalen Außenradius erhöhen.",
            ),
            "MINIMUM_INNER_RADIUS_REACHED": (
                "Den Mindest-Hohlraumradius verkleinern.",
                "Die Ziel-Layerzeit verringern.",
                "Den maximalen Außenradius oder die Maximalwandstärke erhöhen.",
            ),
        }
        result: list[dict[str, object]] = []
        for (code, related_names), members in grouped.items():
            title = titles.get(
                code,
                german_user_message(members[0].message),
            )
            layers = sorted(
                {
                    int(item.affected_layer_index)
                    for item in members
                    if item.affected_layer_index is not None
                }
            )
            required = [
                float(item.required_value)
                for item in members
                if item.required_value is not None
            ]
            # Capacity issues expose a required extrusion-path length, not a
            # required radius, wall thickness, or inner radius.  Only these
            # two issue types carry a value in the same unit and meaning as
            # the setting for which we can give an exact recommendation.
            exact_setting_requirements = (
                required
                if code in {
                    "EXPANSION_ANGLE_TOO_SMALL",
                    "BASE_WIDTH_TOO_SMALL",
                }
                else []
            )
            values = "; ".join(
                self._setting_value_description(name)
                for name in related_names
            )
            summary = f"{values}: {title}." if values else f"{title}."
            if layers:
                if len(layers) == 1:
                    summary += " Betroffen ist 1 Layer."
                else:
                    summary += f" Betroffen sind {len(layers)} Layer."
            if exact_setting_requirements:
                unit = "°" if code == "EXPANSION_ANGLE_TOO_SMALL" else " mm"
                summary += (
                    f" Erforderlich sind bis zu "
                    f"{_de_number(max(exact_setting_requirements))}{unit}."
                )
                if code == "EXPANSION_ANGLE_TOO_SMALL":
                    summary += (
                        " Zulässig sind höchstens "
                        f"{_de_number(MAXIMUM_EXPANSION_ANGLE_DEG)}°."
                    )
            solutions = list(remedies.get(code, ()))
            if solutions and exact_setting_requirements:
                required_maximum = _de_number(max(exact_setting_requirements))
                if code == "EXPANSION_ANGLE_TOO_SMALL":
                    if (
                        max(exact_setting_requirements)
                        <= MAXIMUM_EXPANSION_ANGLE_DEG
                    ):
                        solutions[0] = (
                            "Den maximalen Aufweitungswinkel auf mindestens "
                            f"{required_maximum}° erhöhen."
                        )
                    else:
                        solutions[0] = (
                            "Den maximalen Aufweitungswinkel bis höchstens "
                            f"{MAXIMUM_EXPANSION_ANGLE_DEG:g}° erhöhen."
                        )
                elif code == "BASE_WIDTH_TOO_SMALL":
                    solutions[1] = (
                        "Die manuelle Standfußbreite auf mindestens "
                        f"{required_maximum} mm erhöhen."
                    )
            direct_solution = self._direct_feasibility_solution(
                self._last_changed_setting_name,
                code=code,
                required_values=required,
            )
            if direct_solution:
                solutions.insert(0, direct_solution)
            solutions = list(dict.fromkeys(solutions))
            result.append(
                {
                    "code": code,
                    "related_setting_names": related_names,
                    "members": tuple(members),
                    "summary": summary,
                    "notice": f"{title.rstrip('.')}.",
                    "inline": f"{title.rstrip('.')}.",
                    "title": title,
                    "solutions": tuple(solutions),
                }
            )
        return result

    def _direct_feasibility_solution(
        self,
        trigger: str | None,
        *,
        code: str,
        required_values: list[float],
    ) -> str | None:
        if trigger == "target_layer_time_s":
            return "Die zuletzt geänderte Ziel-Layerzeit verringern."
        if trigger == "safety_factor":
            return "Den Sicherheitsfaktor verringern, jedoch nicht unter 1,0."
        if trigger == "minimum_outer_radius_mm":
            return "Den Mindest-Außenradius auf den Standardwert zurücksetzen."
        if trigger == "maximum_outer_radius_mm":
            return "Den zuletzt geänderten maximalen Außenradius erhöhen."
        if trigger == "minimum_wall_thickness_mm":
            return "Die zuletzt geänderte Mindestwandstärke verringern."
        if trigger == "maximum_wall_thickness_mm":
            return "Die zuletzt geänderte Maximalwandstärke erhöhen."
        if trigger == "wall_path_width_mm":
            return "Die zuletzt geänderte Bahnbreite verringern."
        if trigger == "minimum_inner_radius_mm":
            return "Den zuletzt geänderten Mindest-Hohlraumradius verkleinern."
        if trigger == "automatic_base_width":
            return "Die automatische Standfußbreite wieder aktivieren."
        if trigger == "manual_base_width_mm":
            return "Die zuletzt geänderte manuelle Standfußbreite erhöhen."
        if trigger == "base_height_mm":
            return "Die zuletzt geänderte Standfußhöhe erhöhen."
        if trigger == "maximum_expansion_angle_deg":
            if (
                required_values
                and max(required_values) <= MAXIMUM_EXPANSION_ANGLE_DEG
            ):
                target = _de_number(max(required_values))
                return (
                    "Den zuletzt geänderten Aufweitungswinkel auf mindestens "
                    f"{target}° erhöhen."
                )
            return (
                "Den zuletzt geänderten Aufweitungswinkel bis höchstens "
                f"{MAXIMUM_EXPANSION_ANGLE_DEG:g}° erhöhen."
            )
        if trigger == "maximum_contraction_angle_deg":
            return "Den zuletzt geänderten Verjüngungswinkel erhöhen."
        if trigger == "maximum_wall_change_per_mm_z":
            return "Die zuletzt geänderte Wandstärkenänderung erhöhen."
        return None

    def _clear_feasibility_issues(self) -> None:
        self._feasibility_issues = ()
        self._feasibility_field_errors.clear()
        self._feasibility_issue_summaries.clear()
        self._feasibility_solution_items.clear()
        self._feasibility_issue_targets.clear()
        self._feasibility_request_source = None
        self._pending_reset_setting_name = None
        if hasattr(self, "geometry_group"):
            self.geometry_group.set_summary_badge(None)
            self.stability_group.set_summary_badge(None)
            self.overhang_group.set_summary_badge(None)
            self.geometry_settings_group.set_summary_badge(None)

    def _set_tower_need_message(self, text: str, state: str) -> None:
        self.tower_need_label.setText(text)
        self.tower_need_label.setProperty("state", state)
        self.tower_need_label.setVisible(state != "error")
        self.tower_need_label.style().unpolish(self.tower_need_label)
        self.tower_need_label.style().polish(self.tower_need_label)

    def _show_input_error(self, message: str) -> None:
        self._workflow_error_message = german_user_message(message)
        self.validate_form()

    def select_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self.additional_options_dialog,
            "Basis-Ausgabeordner auswählen",
            self.output_root_edit.text()
            or str(self.default_output_root),
        )
        if selected:
            self.output_root_edit.setText(selected)

    def show_options_menu(self) -> None:
        """Open the header menu below the button and inside the main window."""

        self.options_menu.ensurePolished()
        self.options_menu.adjustSize()
        popup_position = self._options_menu_popup_position(
            self.options_menu.sizeHint()
        )
        self.options_menu.popup(popup_position)

    def _options_menu_popup_position(self, menu_size: QSize) -> QPoint:
        button_top_left = self.options_button.mapToGlobal(QPoint(0, 0))
        window_top_left = self.mapToGlobal(QPoint(0, 0))
        window_right = window_top_left.x() + self.width()
        window_bottom = window_top_left.y() + self.height()

        desired_x = (
            button_top_left.x()
            + self.options_button.width()
            - menu_size.width()
        )
        maximum_x = max(window_top_left.x(), window_right - menu_size.width())
        x = max(window_top_left.x(), min(desired_x, maximum_x))

        below_y = button_top_left.y() + self.options_button.height()
        if below_y + menu_size.height() <= window_bottom:
            y = below_y
        else:
            above_y = button_top_left.y() - menu_size.height()
            if above_y >= window_top_left.y():
                y = above_y
            else:
                y = max(
                    window_top_left.y(),
                    min(below_y, window_bottom - menu_size.height()),
                )
        return QPoint(x, y)

    def show_additional_options(self) -> None:
        """Open the compact output-folder dialog over the main window."""

        dialog = self.additional_options_dialog
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        dialog.show()
        self._resize_additional_options_to_content()
        QTimer.singleShot(0, self._resize_additional_options_to_content)
        dialog.raise_()
        dialog.activateWindow()

    def _resize_additional_options_to_content(self) -> None:
        dialog = self.additional_options_dialog
        if not dialog.isVisible():
            return
        content_layout = self.additional_options_content.layout()
        if content_layout is not None:
            content_layout.invalidate()
            content_layout.activate()
        natural_height = self.additional_options_content.sizeHint().height()
        natural_width = self.additional_options_content.minimumSizeHint().width()
        target_width = max(OUTPUT_DIALOG_MINIMUM_WIDTH_PX, natural_width)
        screen = self.screen()
        if screen is not None:
            natural_height = min(
                natural_height,
                screen.availableGeometry().height() - 40,
            )
        dialog.setFixedSize(target_width, max(1, natural_height))
        self._place_dialog_centered(dialog)

    def show_about_dialog(self) -> None:
        """Show program information at its natural size with safe scrolling."""

        dialog = self.about_dialog
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        dialog.show()
        self._resize_about_to_content()
        QTimer.singleShot(0, self._resize_about_to_content)
        dialog.raise_()
        dialog.activateWindow()

    def _resize_about_to_content(self) -> None:
        dialog = self.about_dialog
        if not dialog.isVisible():
            return
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            width_limit = min(
                available.width() - 40,
                max(
                    ABOUT_DIALOG_MINIMUM_WIDTH_PX,
                    self.width() - OPTIONAL_DIALOG_PARENT_MARGIN_PX,
                ),
            )
            target_width = max(
                ABOUT_DIALOG_MINIMUM_WIDTH_PX,
                min(
                    ABOUT_DIALOG_PREFERRED_WIDTH_PX,
                    width_limit,
                ),
            )
        else:
            target_width = ABOUT_DIALOG_PREFERRED_WIDTH_PX

        natural_height = self._about_natural_content_height(target_width)
        if available is not None:
            height_limit = min(
                available.height() - 40,
                max(280, self.height() - OPTIONAL_DIALOG_PARENT_MARGIN_PX),
            )
            target_height = min(
                natural_height + 2,
                ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX,
                height_limit,
            )
        else:
            target_height = min(
                natural_height + 2,
                ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX,
            )
        dialog.resize(target_width, max(280, target_height))
        self._place_dialog_centered(dialog)

    def _about_natural_content_height(self, target_width: int) -> int:
        content_margins = self.about_content_layout.contentsMargins()
        inner_width = max(
            1,
            target_width
            - content_margins.left()
            - content_margins.right(),
        )
        self.about_legal_grid._relayout(inner_width)
        self.about_content.resize(target_width, self.about_content.height())
        self.about_content_layout.invalidate()
        self.about_content_layout.activate()
        natural_height = (
            self.about_content_layout.heightForWidth(target_width)
            if self.about_content_layout.hasHeightForWidth()
            else self.about_content_layout.sizeHint().height()
        )
        return max(
            natural_height,
            self.about_content_layout.minimumSize().height(),
        )

    def _expand_about_downward_for_content(self) -> None:
        dialog = self._about_dialog
        if dialog is None or not dialog.isVisible():
            return
        natural_height = self._about_natural_content_height(dialog.width()) + 2
        if natural_height <= dialog.height():
            return

        screen = dialog.screen() or self.screen()
        target_height = natural_height
        frame_geometry = dialog.frameGeometry()
        frame_top_left = frame_geometry.topLeft()
        if screen is not None:
            available = screen.availableGeometry()
            frame_overhead = max(
                0,
                frame_geometry.height() - dialog.height(),
            )
            maximum_client_height = max(
                dialog.height(),
                available.bottom()
                - frame_geometry.top()
                + 1
                - frame_overhead,
            )
            target_height = min(target_height, maximum_client_height)

        if target_height > dialog.height():
            dialog.resize(dialog.width(), target_height)
            # Preserve the current upper edge: newly revealed content grows
            # only downwards until the Windows work area is exhausted.
            dialog.move(frame_top_left)

    def _place_additional_options_dialog(self) -> None:
        dialog = self.additional_options_dialog
        if not dialog.isVisible():
            return
        self._place_dialog_centered(dialog)

    def _place_dialog_centered(self, dialog: QDialog) -> None:
        if not dialog.isVisible():
            return
        target_frame = dialog.frameGeometry()
        target_frame.moveCenter(self.frameGeometry().center())
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            x = max(
                available.left(),
                min(target_frame.left(), available.right() - target_frame.width() + 1),
            )
            y = max(
                available.top(),
                min(target_frame.top(), available.bottom() - target_frame.height() + 1),
            )
            target_frame.moveTopLeft(QPoint(x, y))
        dialog.move(target_frame.topLeft())

    def _resize_visible_optional_dialogs(self) -> None:
        if self._about_dialog is not None and self._about_dialog.isVisible():
            self._resize_about_to_content()
        if (
            self._additional_options_dialog is not None
            and self._additional_options_dialog.isVisible()
        ):
            self._resize_additional_options_to_content()

    def collect_settings(self) -> GenerationSettings:
        return GenerationSettings(
            target_layer_time_s=self.target_time_spin.value(),
            safety_factor=self.safety_factor_spin.value(),
            minimum_outer_radius_mm=self.minimum_outer_spin.value(),
            maximum_outer_radius_mm=self.maximum_outer_spin.value(),
            minimum_wall_thickness_mm=self.minimum_wall_spin.value(),
            maximum_wall_thickness_mm=self.maximum_wall_spin.value(),
            wall_path_width_mm=self.path_width_spin.value(),
            minimum_inner_radius_mm=self.minimum_inner_spin.value(),
            minimum_base_radius_mm=self.minimum_base_spin.value(),
            base_height_mm=self.base_height_spin.value(),
            base_margin_mm=self.base_margin_spin.value(),
            base_height_factor=self.base_height_factor_spin.value(),
            automatic_base_width=self.automatic_base_checkbox.isChecked(),
            manual_base_width_mm=self.manual_base_width_spin.value(),
            minimum_radius_height_factor=(
                self.minimum_radius_height_factor_spin.value()
            ),
            maximum_radius_change_per_mm_z=(
                self.maximum_radius_change_spin.value()
            ),
            maximum_expansion_angle_deg=(
                self.maximum_expansion_angle_spin.value()
            ),
            maximum_contraction_angle_deg=(
                self.maximum_contraction_angle_spin.value()
            ),
            maximum_wall_change_per_mm_z=(
                self.maximum_wall_change_spin.value()
            ),
            local_reference_window=self.local_window_spin.value(),
            mesh_segments=self.mesh_segments_spin.value(),
        )

    def apply_settings(self, settings: GenerationSettings) -> None:
        values = (
            (self.target_time_spin, settings.target_layer_time_s),
            (self.safety_factor_spin, settings.safety_factor),
            (self.minimum_outer_spin, settings.minimum_outer_radius_mm),
            (self.maximum_outer_spin, settings.maximum_outer_radius_mm),
            (self.minimum_wall_spin, settings.minimum_wall_thickness_mm),
            (self.maximum_wall_spin, settings.maximum_wall_thickness_mm),
            (self.path_width_spin, settings.wall_path_width_mm),
            (self.minimum_inner_spin, settings.minimum_inner_radius_mm),
            (self.minimum_base_spin, settings.minimum_base_radius_mm),
            (self.manual_base_width_spin, settings.manual_base_width_mm),
            (self.base_height_spin, settings.base_height_mm),
            (self.base_margin_spin, settings.base_margin_mm),
            (self.base_height_factor_spin, settings.base_height_factor),
            (
                self.minimum_radius_height_factor_spin,
                settings.minimum_radius_height_factor,
            ),
            (
                self.maximum_radius_change_spin,
                settings.maximum_radius_change_per_mm_z,
            ),
            (
                self.maximum_expansion_angle_spin,
                settings.maximum_expansion_angle_deg,
            ),
            (
                self.maximum_contraction_angle_spin,
                settings.maximum_contraction_angle_deg,
            ),
            (
                self.maximum_wall_change_spin,
                settings.maximum_wall_change_per_mm_z,
            ),
            (self.local_window_spin, settings.local_reference_window),
            (self.mesh_segments_spin, settings.mesh_segments),
        )
        for widget, value in values:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        for setting in self._setting_widgets.values():
            setting.refresh_reset_state()
        self.automatic_base_checkbox.blockSignals(True)
        self.automatic_base_checkbox.setChecked(
            settings.automatic_base_width
        )
        self.automatic_base_checkbox.blockSignals(False)
        self.manual_base_width_spin.setEnabled(
            not settings.automatic_base_width
        )
        self._setting_widgets["manual_base_width_mm"].setVisible(
            not settings.automatic_base_width
        )
        self.automatic_base_width_label.setVisible(
            settings.automatic_base_width
        )
        self.automatic_base_reset_button.setVisible(
            not settings.automatic_base_width
        )
        self._update_expansion_angle_warning()
        self._update_automatic_base_width_preview()

    def _update_expansion_angle_warning(self) -> None:
        warning = (
            "Vorsicht: Aufweitungswinkel ab 51° erzeugen steilere "
            "Überhänge und setzen einen gut kalibrierten Drucker voraus."
            if self.maximum_expansion_angle_spin.value() >= 51.0
            else ""
        )
        self.maximum_expansion_angle_setting.set_warning(warning)

    def update_wall_path_preview(self) -> None:
        width = self.path_width_spin.value()
        diameter = f"{2 * self.maximum_outer_spin.value():.2f}".replace(
            ".", ","
        )
        self.maximum_diameter_label.setText(
            f"Maximaler Außendurchmesser: {diameter} mm. "
            "Erst ab diesem Durchmesser wird zusätzlicher Zeitbedarf durch "
            "größere Wandstärke ausgeglichen"
        )
        try:
            bounds = calculate_wall_path_bounds(
                self.minimum_wall_spin.value(),
                self.maximum_wall_spin.value(),
                width,
            )
        except ValueError:
            self.wall_paths_label.setText("Wandbahnanzahl derzeit nicht berechenbar")
            return
        self.wall_paths_label.setText(
            f"Minimum: {bounds.minimum_path_count} Bahnen = "
            f"{bounds.effective_minimum_thickness_mm:.2f} mm  ·  "
            f"Maximum: {bounds.maximum_path_count} Bahnen = "
            f"{bounds.effective_maximum_thickness_mm:.2f} mm"
        )
        self._update_section_summaries()

    def _update_section_summaries(self) -> None:
        """Keep the most useful values readable before opening a card."""

        if not hasattr(self, "timing_group"):
            return
        self.timing_group.set_summary(
            f"Ziel {_de_number(self.target_time_spin.value())} s · "
            f"Sicherheitsfaktor {_de_number(self.safety_factor_spin.value())}"
        )
        self.geometry_group.set_summary(
            f"Außenradius {_de_number(self.minimum_outer_spin.value())}–"
            f"{_de_number(self.maximum_outer_spin.value())} mm · "
            f"Wand {_de_number(self.minimum_wall_spin.value())}–"
            f"{_de_number(self.maximum_wall_spin.value())} mm"
        )
        base_mode = (
            "Standfuß automatisch"
            if self.automatic_base_checkbox.isChecked()
            else f"Standfuß {_de_number(self.manual_base_width_spin.value())} mm"
        )
        self.stability_group.set_summary(
            f"{base_mode} · Höhe "
            f"{_de_number(self.base_height_spin.value())} mm"
        )
        self.overhang_group.set_summary(
            "Winkel "
            f"{_de_number(self.maximum_expansion_angle_spin.value(), 1)}/"
            f"{_de_number(self.maximum_contraction_angle_spin.value(), 1)}°"
        )
        self.geometry_settings_group.set_summary(
            f"Radius {_de_number(self.minimum_outer_spin.value())}–"
            f"{_de_number(self.maximum_outer_spin.value())} mm · {base_mode} · "
            f"{self.mesh_segments_spin.value()} Segmente"
        )
        output_text = self.output_root_edit.text().strip()
        manual_base_modified = (
            abs(
                self.manual_base_width_spin.value()
                - self.default_settings.manual_base_width_mm
            )
            > 1e-9
        )
        self.automatic_base_reset_button.setProperty(
            "modified", manual_base_modified
        )
        self.automatic_base_reset_button.setVisible(
            not self.automatic_base_checkbox.isChecked()
        )
        self.automatic_base_reset_button.setEnabled(manual_base_modified)
        output_modified = output_text != str(self.default_output_root)
        self.output_root_reset_button.setProperty("modified", output_modified)
        self.output_root_reset_button.setEnabled(output_modified)
        self._refresh_widget_style(self.automatic_base_reset_button)
        self._refresh_widget_style(self.output_root_reset_button)
        if hasattr(self, "reset_button"):
            self.reset_button.setEnabled(self._has_non_default_settings())
        self._update_automatic_base_width_preview()

    def _update_automatic_base_width_preview(self) -> None:
        if self.automatic_base_checkbox.isChecked():
            object_height = (
                self.analysis_snapshot.maximum_print_z_mm
                if self.analysis_snapshot is not None
                else None
            )
            if object_height is None:
                self.automatic_base_width_label.setText(
                    "Automatische Breite: mindestens 20,00 mm; der genaue "
                    "Wert folgt aus der vollständigen G-Code-Objekthöhe."
                )
            else:
                width = max(
                    MINIMUM_BASE_WIDTH_MM,
                    object_height * BASE_WIDTH_PER_OBJECT_HEIGHT,
                )
                self.automatic_base_width_label.setText(
                    f"Automatische Breite bei {object_height:.2f} mm "
                    f"G-Code-Objekthöhe: {width:.2f} mm "
                    "(0,2 mm je 1 mm)"
                )
        else:
            self.automatic_base_width_label.setText(
                f"Manuelle Standfußbreite: "
                f"{self.manual_base_width_spin.value():.2f} mm"
            )

    def validate_form(self) -> bool:
        field_records: dict[str, list[str]] = {}
        static_causes: list[str] = []
        general_errors: list[str] = []
        issue_keys: set[str] = set()
        previous_targets: dict[str, str] = {}
        for field_name, messages in self._static_field_errors.items():
            for previous_message in messages:
                previous_targets.setdefault(
                    _validation_issue_key(previous_message),
                    field_name,
                )

        def add_error(
            names: tuple[str, ...],
            message: str,
            _solutions: tuple[str, ...] = (),
        ) -> None:
            cause = german_user_message(message)
            issue_key = _validation_issue_key(cause)
            if issue_key in issue_keys:
                return
            issue_keys.add(issue_key)
            static_causes.append(cause)
            trigger = self._last_changed_setting_name
            # Keep the most recently responsible field marked until the
            # relationship is valid again—even during focus or unrelated
            # edits. A new edit of another participating field transfers the
            # marker to that field.
            target = trigger if trigger in names else previous_targets.get(issue_key)
            if target not in names:
                target = names[0] if names else None
            if target is not None:
                field_records.setdefault(target, []).append(cause)

        def add_general_error(message: str) -> None:
            cause = german_user_message(message)
            issue_key = _validation_issue_key(cause)
            if issue_key in issue_keys:
                return
            issue_keys.add(issue_key)
            general_errors.append(cause)

        settings = self.collect_settings()
        range_invalid_names: set[str] = set()
        for name, setting in self._setting_widgets.items():
            if not hasattr(settings, name):
                continue
            value = float(getattr(settings, name))
            minimum = setting.editor.property("validationMinimum")
            maximum = setting.editor.property("validationMaximum")
            if minimum is not None and value < float(minimum):
                range_invalid_names.add(name)
                rendered_minimum = setting.editor.textFromValue(
                    float(minimum)
                    if isinstance(setting.editor, QDoubleSpinBox)
                    else int(minimum)
                )
                add_error(
                    (name,),
                    f"{self._setting_value_description(name)} liegt unter "
                    f"dem Mindestwert {rendered_minimum}"
                    f"{f' {SETTING_UNITS.get(name)}' if SETTING_UNITS.get(name) else ''}.",
                )
            elif maximum is not None and value > float(maximum):
                range_invalid_names.add(name)
                rendered_maximum = setting.editor.textFromValue(
                    float(maximum)
                    if isinstance(setting.editor, QDoubleSpinBox)
                    else int(maximum)
                )
                add_error(
                    (name,),
                    f"{self._setting_value_description(name)} überschreitet "
                    f"den Maximalwert {rendered_maximum}"
                    f"{f' {SETTING_UNITS.get(name)}' if SETTING_UNITS.get(name) else ''}.",
                )
        for name in self._incomplete_setting_names:
            setting = self._setting_widgets.get(name)
            message = (
                setting.invalid_input_message()
                if setting is not None
                else "Bitte einen gültigen vollständigen Zahlenwert eingeben."
            )
            if setting is not None:
                entered = setting.editor.lineEdit().text().strip()
                unit = SETTING_UNITS.get(name, "")
                label = " ".join(setting.label.text().split())
                message = (
                    f"{label}: Eingabe „{entered or 'leer'}“"
                    f"{f' {unit}' if unit else ''} ist unvollständig oder "
                    "ungültig."
                )
            add_error(
                (name,),
                message,
                ("Den Zahlenwert vollständig neu eingeben.",),
            )
        if (
            "target_layer_time_s" not in range_invalid_names
            and settings.target_layer_time_s <= 0
        ):
            add_error(
                ("target_layer_time_s",),
                "Ziel-Layerzeit muss größer als 0 sein.",
                (
                    "Eine Ziel-Layerzeit größer als 0 Sekunden eingeben.",
                    "Den Standardwert der Ziel-Layerzeit wiederherstellen.",
                ),
            )
        if (
            "safety_factor" not in range_invalid_names
            and settings.safety_factor < 1.0
        ):
            add_error(
                ("safety_factor",),
                "Sicherheitsfaktor muss mindestens 1,0 betragen.",
                (
                    "Den Sicherheitsfaktor auf mindestens 1,0 erhöhen.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "minimum_outer_radius_mm" not in range_invalid_names
            and settings.minimum_outer_radius_mm <= 0.0
        ):
            add_error(
                ("minimum_outer_radius_mm",),
                "Mindest-Außenradius muss größer als 0 sein.",
                (
                    "Einen Mindest-Außenradius größer als 0 mm eingeben.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if settings.minimum_outer_radius_mm > settings.maximum_outer_radius_mm:
            add_error(
                ("minimum_outer_radius_mm", "maximum_outer_radius_mm"),
                f"{self._setting_value_description('maximum_outer_radius_mm')} "
                "muss mindestens so groß sein wie "
                f"{self._setting_value_description('minimum_outer_radius_mm')}.",
                (
                    "Den Mindest-Außenradius verkleinern.",
                    "Den maximalen Außenradius vergrößern.",
                    "Den zuletzt geänderten Wert zurücksetzen.",
                ),
            )
        if (
            "minimum_wall_thickness_mm" not in range_invalid_names
            and settings.minimum_wall_thickness_mm <= 0.0
        ):
            add_error(
                ("minimum_wall_thickness_mm",),
                "Mindestwandstärke muss größer als 0 sein.",
                (
                    "Eine Mindestwandstärke größer als 0 mm eingeben.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if settings.maximum_wall_thickness_mm < settings.minimum_wall_thickness_mm:
            add_error(
                (
                    "minimum_wall_thickness_mm",
                    "maximum_wall_thickness_mm",
                ),
                f"{self._setting_value_description('maximum_wall_thickness_mm')} "
                "muss mindestens so groß sein wie "
                f"{self._setting_value_description('minimum_wall_thickness_mm')}.",
                (
                    "Die Maximalwandstärke erhöhen.",
                    "Die Mindestwandstärke verringern.",
                    "Den zuletzt geänderten Wert zurücksetzen.",
                ),
            )
        if (
            "wall_path_width_mm" not in range_invalid_names
            and settings.wall_path_width_mm <= 0
        ):
            add_error(
                ("wall_path_width_mm",),
                "Bahnbreite muss größer als 0 sein.",
                (
                    "Die im Slicer verwendete positive Linienbreite eintragen.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "minimum_inner_radius_mm" not in range_invalid_names
            and settings.minimum_inner_radius_mm <= 0
        ):
            add_error(
                ("minimum_inner_radius_mm",),
                "Mindest-Innenradius muss größer als 0 sein.",
                (
                    "Einen Mindest-Hohlraumradius größer als 0 mm eingeben.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "manual_base_width_mm" not in range_invalid_names
            and
            not settings.automatic_base_width
            and settings.manual_base_width_mm < 20.0
        ):
            add_error(
                ("manual_base_width_mm",),
                "Manuelle Standfußbreite muss mindestens 20 mm betragen.",
                (
                    "Die manuelle Standfußbreite auf mindestens 20 mm erhöhen.",
                    "Die automatische Standfußbreite aktivieren.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "maximum_expansion_angle_deg" not in range_invalid_names
            and not (
            0.0
            < settings.maximum_expansion_angle_deg
            <= MAXIMUM_EXPANSION_ANGLE_DEG
            )
        ):
            add_error(
                ("maximum_expansion_angle_deg",),
                "Aufweitungswinkel muss größer als 0° und höchstens "
                f"{MAXIMUM_EXPANSION_ANGLE_DEG:g}° sein.",
                (
                    "Den Aufweitungswinkel auf höchstens "
                    f"{MAXIMUM_EXPANSION_ANGLE_DEG:g}° verringern.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "maximum_contraction_angle_deg" not in range_invalid_names
            and not 0.0 < settings.maximum_contraction_angle_deg < 90.0
        ):
            add_error(
                ("maximum_contraction_angle_deg",),
                "Verjüngungswinkel muss zwischen 0° und 90° liegen.",
                (
                    "Einen Verjüngungswinkel zwischen 0° und 90° eingeben.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "maximum_wall_change_per_mm_z" not in range_invalid_names
            and settings.maximum_wall_change_per_mm_z <= 0.0
        ):
            add_error(
                ("maximum_wall_change_per_mm_z",),
                "Maximale Wandstärkenänderung muss größer als 0 sein.",
                (
                    "Eine Wandstärkenänderung größer als 0 eingeben.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        if (
            "local_reference_window" not in range_invalid_names
            and settings.local_reference_window % 2 == 0
        ):
            add_error(
                ("local_reference_window",),
                f"{self._setting_value_description('local_reference_window')} "
                "muss ungerade sein.",
                (
                    "Die nächstkleinere ungerade Zahl verwenden.",
                    "Die nächstgrößere ungerade Zahl verwenden.",
                    "Den Standardwert wiederherstellen.",
                ),
            )
        # Run compound geometry validation only after direct range and
        # relationship causes are clean. This prevents one invalid value from
        # producing a second, derivative description of the same root cause.
        if (
            not range_invalid_names
            and not self._incomplete_setting_names
            and not static_causes
        ):
            try:
                validate_hollow_settings(settings)
            except ValueError as error:
                raw_text = str(error)
                translated = german_user_message(raw_text)
                if _validation_issue_key(translated) not in issue_keys:
                    if "Maximum outer radius cannot contain" in raw_text:
                        text = (
                            f"{self._setting_value_description('maximum_outer_radius_mm')} "
                            "ist für "
                            f"{self._setting_value_description('minimum_wall_thickness_mm')} "
                            "und "
                            f"{self._setting_value_description('minimum_inner_radius_mm')} "
                            "zu klein."
                        )
                        add_error(
                            (
                                "maximum_outer_radius_mm",
                                "minimum_inner_radius_mm",
                                "minimum_wall_thickness_mm",
                            ),
                            text,
                        )
                    elif "wall thickness" in raw_text.lower():
                        text = (
                            f"{self._setting_value_description('maximum_wall_thickness_mm')} "
                            "kann mit "
                            f"{self._setting_value_description('wall_path_width_mm')} "
                            "nicht alle erforderlichen Wandbahnen aufnehmen."
                        )
                        add_error(
                            (
                                "minimum_wall_thickness_mm",
                                "maximum_wall_thickness_mm",
                                "wall_path_width_mm",
                            ),
                            text,
                        )
                    else:
                        add_general_error(translated)
        if not self.output_root_edit.text().strip():
            add_error(
                ("output_root",),
                "Bitte einen Ausgabeordner angeben.",
                (
                    "Einen beschreibbaren Ausgabeordner auswählen.",
                    "Den Standard-Ausgabeordner wiederherstellen.",
                ),
            )

        raw_field_errors = {
            name: list(records) for name, records in field_records.items()
        }
        field_errors = {
            # The setting name and current value are already visible in the
            # row itself and, in the footer, in the group's heading.
            name: _deduplicate_validation_messages(
                self._concise_field_message(name, record)
                for record in records
            )
            for name, records in raw_field_errors.items()
        }
        # Preserve the original causes internally so a relationship error
        # remains attached to the same field until it is actually resolved.
        self._static_field_errors = raw_field_errors
        self._static_error_causes = _deduplicate_validation_messages(static_causes)
        feedback_available = self._setting_feedback_is_available()
        visible_field_errors = field_errors if feedback_available else {}
        self._apply_inline_errors(visible_field_errors)
        self._refresh_collapsible_error_badges(visible_field_errors)

        grouped_messages = {
            name: list(messages) for name, messages in field_errors.items()
        }
        for name, messages in self._feasibility_field_errors.items():
            grouped_messages.setdefault(name, []).extend(messages)

        assigned_static = {
            message
            for messages in raw_field_errors.values()
            for message in messages
        }
        assigned_feasibility = {
            message
            for messages in self._feasibility_field_errors.values()
            for message in messages
        }
        workflow_messages = (
            (self._workflow_error_message,)
            if self._workflow_error_message
            else ()
        )
        standalone_messages = _deduplicate_validation_messages(
            (
                *workflow_messages,
                *general_errors,
                *(
                    message
                    for message in static_causes
                    if message not in assigned_static
                ),
                *(
                    message
                    for message in self._feasibility_issue_summaries
                    if message not in assigned_feasibility
                ),
            )
        )
        footer_groups = [
            (
                self._footer_setting_heading(name),
                _deduplicate_validation_messages(messages),
            )
            for name, messages in grouped_messages.items()
            if messages
        ]
        if feedback_available or self._workflow_error_message:
            self.validation_label.set_grouped_notice(
                standalone_messages,
                footer_groups,
            )
        else:
            self.validation_label.clear()
        self._refresh_issue_panels()
        static_valid = (
            not static_causes
            and not general_errors
            and not self._workflow_error_message
        )
        analysis_complete = self.analysis_snapshot is not None
        tower_required = (
            self.tower_assessment is not None
            and self.tower_assessment.tower_required
        )
        geometry_feasible = (
            self.profile_feasibility is not None
            and self.profile_feasibility.feasible
            and not self._feasibility_issue_summaries
        )
        self.preview_button.setEnabled(
            static_valid
            and self.current_gcode_path is not None
            and not self._analysis_failed
            and analysis_complete
            and tower_required
            and geometry_feasible
        )
        self._phase17_static_valid = static_valid
        self._refresh_phase17_actions()
        return static_valid

    def _refresh_issue_panels(self) -> None:
        if hasattr(self, "error_panel"):
            has_errors = bool(self.validation_label.text().strip())
            newly_visible = has_errors and self.error_panel.isHidden()
            if newly_visible:
                self.error_panel.reset_collapsed()
            self.error_panel.setVisible(has_errors)
            if has_errors:
                problem_count = len(self._static_error_causes) + len(
                    self._feasibility_issue_summaries
                ) + bool(self._workflow_error_message)
                suffix = (
                    f" · {problem_count} Problem"
                    f"{'e' if problem_count != 1 else ''}"
                    if problem_count
                    else ""
                )
                self.error_panel.set_title(
                    f"✕  Eingaben prüfen{suffix}"
                )
        if hasattr(self, "notice_panel"):
            visible = bool(self.warning_text.toPlainText().strip())
            self.warning_text.setVisible(visible)
            if visible and self.notice_panel.isHidden():
                self.notice_panel.reset_collapsed()
            self.notice_panel.setVisible(visible)
        self._refresh_footer_notice_layout()
        self._schedule_footer_height_update()

    def _refresh_collapsible_error_badges(
        self,
        static_errors: dict[str, list[str]],
    ) -> None:
        feedback_available = self._setting_feedback_is_available()
        feasibility_errors = (
            self._feasibility_field_errors if feedback_available else {}
        )
        combined: dict[str, tuple[str, ...]] = {}
        for name in set(static_errors) | set(feasibility_errors):
            combined[name] = tuple(
                _deduplicate_validation_messages(
                    (
                        *static_errors.get(name, ()),
                        *feasibility_errors.get(name, ()),
                    )
                )
            )
        sections = (
            (
                self.timing_group,
                {"target_layer_time_s", "safety_factor"},
            ),
            (
                self.geometry_settings_group,
                {
                    "minimum_outer_radius_mm",
                    "maximum_outer_radius_mm",
                    "minimum_wall_thickness_mm",
                    "maximum_wall_thickness_mm",
                    "wall_path_width_mm",
                    "minimum_inner_radius_mm",
                    "automatic_base_width",
                    "manual_base_width_mm",
                    "base_height_mm",
                    "maximum_expansion_angle_deg",
                    "maximum_contraction_angle_deg",
                    "maximum_wall_change_per_mm_z",
                    "mesh_segments",
                    "local_reference_window",
                },
            ),
        )
        for group, names in sections:
            messages = {
                message
                for name in names
                for message in combined.get(name, ())
            }
            count = len(messages)
            badge = None if count == 0 else (
                "1 Fehler" if count == 1 else f"{count} Fehler"
            )
            group.set_summary_badge(badge)
            if count:
                group.set_state(SectionState.ERROR)
                group.setChecked(True)
            else:
                group.set_state(SectionState.NEUTRAL)
        self.geometry_group.set_summary_badge(None)
        self.stability_group.set_summary_badge(None)
        self.overhang_group.set_summary_badge(None)

    def _apply_inline_errors(
        self,
        static_errors: dict[str, list[str]],
    ) -> None:
        feedback_available = self._setting_feedback_is_available()
        feasibility_errors = (
            self._feasibility_field_errors if feedback_available else {}
        )
        layout_changed = False
        for name, widget in self._setting_widgets.items():
            messages = _deduplicate_validation_messages((
                *static_errors.get(name, ()),
                *feasibility_errors.get(name, ()),
            ))
            layout_changed = (
                widget.set_error("\n".join(messages) or None)
                or layout_changed
            )

        automatic_messages = [
            *static_errors.get("automatic_base_width", ()),
            *feasibility_errors.get(
                "automatic_base_width", ()
            ),
        ]
        automatic_error = "\n".join(
            dict.fromkeys(automatic_messages)
        )
        automatic_invalid = bool(automatic_error)
        layout_changed = (
            self._set_boolean_style_property(
                self.automatic_base_checkbox,
                "invalid",
                automatic_invalid,
            )
            or layout_changed
        )
        layout_changed = (
            self._set_boolean_style_property(
                self.automatic_base_error_label,
                "error",
                automatic_invalid,
            )
            or layout_changed
        )
        if self.automatic_base_error_label.text() != automatic_error:
            self.automatic_base_error_label.setText(automatic_error)
            layout_changed = True
        if (
            not self.automatic_base_error_label.isHidden()
        ) != automatic_invalid:
            self.automatic_base_error_label.setVisible(automatic_invalid)
            layout_changed = True

        output_messages = static_errors.get("output_root", ())
        output_error = "\n".join(dict.fromkeys(output_messages))
        output_invalid = bool(output_error)
        layout_changed = (
            self._set_boolean_style_property(
                self.output_root_edit,
                "invalid",
                output_invalid,
            )
            or layout_changed
        )
        layout_changed = (
            self._set_boolean_style_property(
                self.output_root_error_label,
                "error",
                output_invalid,
            )
            or layout_changed
        )
        if self.output_root_error_label.text() != output_error:
            self.output_root_error_label.setText(output_error)
            layout_changed = True
        if (not self.output_root_error_label.isHidden()) != output_invalid:
            self.output_root_error_label.setVisible(output_invalid)
            layout_changed = True
        layout_changed = (
            self._set_boolean_style_property(
                self.options_button,
                "invalid",
                output_invalid,
            )
            or layout_changed
        )
        # Inline messages participate in the normal layout. Refresh the two
        # fixed-height responsive hosts immediately so newly visible errors
        # enlarge their cards instead of painting over the following field.
        if layout_changed and hasattr(self, "geometry_settings_group"):
            self._refresh_geometry_section_layout(
                self.geometry_settings_group.isChecked()
            )
        elif layout_changed and hasattr(self, "ready_grid"):
            self._refresh_ready_grid_layout()

    def _show_preview_dialog(self) -> None:
        if not self.preview_dialog.isVisible():
            self.preview_dialog.setWindowState(Qt.WindowState.WindowNoState)
            self._place_preview_beside_main_window()
            self.preview_dialog.show()
            self._enforce_preview_window_geometry()
            QTimer.singleShot(0, self._enforce_preview_window_geometry)
            QTimer.singleShot(80, self._enforce_preview_window_geometry)
        else:
            self._enforce_preview_window_geometry()
        self.preview_dialog.raise_()
        self.preview_dialog.activateWindow()

    def _place_preview_beside_main_window(self) -> None:
        screen = self.screen()
        if screen is None:
            self._preview_target_geometry = None
            return
        available = screen.availableGeometry()
        margin = 8
        gap = 12
        preview_minimum_width = max(
            520,
            self.preview_dialog.minimumWidth(),
            self.preview_dialog.minimumSizeHint().width(),
        )
        preview_width = min(
            920,
            max(620, preview_minimum_width, available.width() // 2),
        )
        preview_height = min(720, max(520, available.height() - 2 * margin))
        main_frame = self.frameGeometry()
        direct_x = main_frame.right() + gap + 1
        if direct_x + preview_width <= available.right() + 1:
            # Align the top-level window frames. A post-show correction in
            # _enforce_preview_window_geometry() compensates for platform-
            # specific title-bar and frame margins.
            y = main_frame.top()
            target = QRect(
                direct_x,
                y,
                preview_width,
                preview_height,
            )
            self._preview_target_geometry = target
            self.preview_dialog.setGeometry(target)
            return

        self._main_geometry_before_preview = self.geometry()
        self._main_was_maximized_before_preview = self.isMaximized()
        if self.isMaximized():
            self.showNormal()

        usable_width = available.width() - 2 * margin - gap
        minimum_main = self.minimumWidth()
        preview_width = min(
            preview_width,
            max(preview_minimum_width, usable_width - minimum_main),
        )
        main_width = max(minimum_main, usable_width - preview_width)
        preview_width = max(preview_minimum_width, usable_width - main_width)
        x = available.left() + margin
        main_height = min(
            max(self.minimumHeight(), self.height()),
            available.height() - 2 * margin,
        )
        main_y = available.top() + margin
        self.setGeometry(x, main_y, main_width, main_height)
        target = QRect(
            x + main_width + gap,
            available.top() + margin,
            preview_width,
            preview_height,
        )
        self._preview_target_geometry = target
        self.preview_dialog.setGeometry(target)
        self._preview_layout_adjusted = True

    def _enforce_preview_window_geometry(self) -> None:
        """Keep the first preview opening normal-sized and beside the main window."""

        if self._closing or not self.preview_dialog.isVisible():
            return
        if self.preview_dialog.isMaximized() or self.preview_dialog.isFullScreen():
            self.preview_dialog.setWindowState(Qt.WindowState.WindowNoState)
        if self._preview_target_geometry is not None:
            self.preview_dialog.setGeometry(self._preview_target_geometry)
            frame_delta_y = (
                self.frameGeometry().top()
                - self.preview_dialog.frameGeometry().top()
            )
            if frame_delta_y:
                corrected = self.preview_dialog.geometry().translated(
                    0, frame_delta_y
                )
                self.preview_dialog.setGeometry(corrected)
            # Qt may enlarge the requested rectangle by a pixel to satisfy a
            # platform-specific minimum size. Preserve that actual normal
            # geometry instead of repeatedly forcing an impossible rectangle.
            self._preview_target_geometry = self.preview_dialog.geometry()

    def _restore_main_after_preview(self) -> None:
        self._preview_target_geometry = None
        if self._closing or not self._preview_layout_adjusted:
            return
        geometry = self._main_geometry_before_preview
        was_maximized = self._main_was_maximized_before_preview
        self._preview_layout_adjusted = False
        self._main_geometry_before_preview = None
        self._main_was_maximized_before_preview = False
        if geometry is not None:
            self.setGeometry(geometry)
        if was_maximized:
            self.showMaximized()

    def start_preview(self) -> None:
        self.validate_form()
        self._refresh_stl_availability()
        self._show_preview_dialog()
        if not self.preview_button.isEnabled():
            self.preview_dialog.set_failed(
                "Die Analyse, Geometrie oder Modusauswahl ist noch nicht exportfähig."
            )
            return
        try:
            request = self._current_preview_request()
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self.preview_dialog.set_failed(german_user_message(error))
            return

        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="preview_replaced",
        )
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self.preview_state = PreviewState.BUILDING
        self.preview_button.setEnabled(False)
        self.preview_quality_panel.setEnabled(False)
        self._update_responsive_action_labels()
        self._set_export_button_state(
            False,
            "Die Vorschau wird gerade erstellt.",
        )
        self.preview_hint_label.setText(
            "Vorschau wird im Hintergrund erstellt. Die Oberfläche bleibt bedienbar."
        )
        self.preview_hint_label.setProperty("state", "building")
        self._refresh_widget_style(self.preview_hint_label)
        self.progress_bar.setProperty("task", "preview")
        self._refresh_widget_style(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._set_main_status(
            "Vorschau wird vorbereitet …", icon="⏳", state="running"
        )
        self.preview_dialog.set_building("Vorschau wird vorbereitet …")

        worker = PreviewWorker(request_id, request, self.preview_service)
        self._refresh_phase17_actions()
        worker.progress.connect(self._on_preview_progress)
        worker.succeeded.connect(self._on_preview_succeeded)
        worker.failed.connect(self._on_preview_failed)
        self.background_job_manager.start_job(
            kind=JobKind.PREVIEW,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"preview-{request_id}",
        )

    def _on_preview_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        status = german_user_message(status)
        self.preview_dialog.set_progress(percent, status)
        self._set_main_status(status, icon="⏳", state="running")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_bar.show()

    def _on_preview_succeeded(
        self,
        request_id: int,
        result: PreviewResult,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            result.dispose()
            return
        try:
            current_signature = self._current_preview_request().signature()
        except (AttributeError, KeyError, TypeError, ValueError):
            current_signature = None
        if result.request_signature != current_signature:
            result.dispose()
            self.preview_state = (
                PreviewState.STALE
                if self.current_preview is not None
                else PreviewState.EMPTY
            )
            self.preview_dialog.mark_stale()
            return
        previous = self.current_preview
        self.current_preview = result
        self.preview_state = PreviewState.CURRENT
        self.last_export_result = None
        self.preview_dialog.set_preview(result)
        self.preview_button.setText("Vorschau aktualisieren")
        self.preview_hint_label.setProperty("state", "current")
        self.preview_hint_label.setText(
            "Vorschau ist aktuell. Der Export kann diesen Stand verwenden."
        )
        self._refresh_widget_style(self.preview_hint_label)
        self.progress_bar.setProperty("task", "default")
        self._refresh_widget_style(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self._set_main_status(
            "Vorschau ist aktuell", icon="✓", state="success"
        )
        if previous is not None and previous is not result:
            previous.dispose()
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def _on_preview_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        self.preview_state = (
            PreviewState.STALE
            if self.current_preview is not None
            else PreviewState.FAILED
        )
        self.preview_dialog.set_failed(german_user_message(message))
        self.preview_hint_label.setProperty("state", "warning")
        self.preview_hint_label.setText(
            "Vorschau konnte nicht aktualisiert werden. Der Export kann trotzdem "
            "mit den aktuellen Einstellungen gestartet werden."
        )
        self._refresh_widget_style(self.preview_hint_label)
        self.progress_bar.setProperty("task", "default")
        self._refresh_widget_style(self.progress_bar)
        self._set_main_status(
            "Vorschau fehlgeschlagen", icon="✕", state="error"
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def start_export(self) -> None:
        self.validate_form()
        self._refresh_stl_availability()
        if not self.export_button.isEnabled():
            return
        try:
            preview_request = self._current_preview_request()
            request = self._current_preview_request(
                calibration_config=self._export_calibration_config(),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self.result_label.setText(german_user_message(error))
            return
        preview = self.current_preview
        preview_matches_current_settings = bool(
            preview is not None
            and self.preview_state is PreviewState.CURRENT
            and preview_request.signature() == preview.request_signature
        )
        if preview is not None and not preview_matches_current_settings:
            action = self._ask_stale_preview_action()
            if action == "preview":
                self.start_preview()
                return
            if action != "yes":
                return
        preview_is_current = bool(
            preview_matches_current_settings
            and preview is not None
            and request.signature() == preview.request_signature
        )
        export_preview = preview if preview_is_current else None
        self._export_request_id += 1
        request_id = self._export_request_id
        self._set_export_button_state(
            False,
            "Ein Export wird bereits ausgeführt.",
        )
        self.preview_button.setEnabled(False)
        self.preview_quality_panel.setEnabled(False)
        self.drop_zone.remove_button.setEnabled(False)
        self._refresh_folder_action_states()
        self.open_run_button.setEnabled(False)
        self._set_main_status(
            "Exakter Kühlturm wird mit fünf Slicer-Durchläufen erzeugt und exportiert …"
            if export_preview is None
            else "Aktuelle Vorschau wird exportiert …",
            icon="⏳",
            state="running",
        )
        self.progress_bar.setProperty("task", "default")
        self._refresh_widget_style(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        worker = ExportWorker(
            request_id,
            export_preview,
            request,
            Path(self.output_root_edit.text()).expanduser(),
            self.export_service,
            self.preview_service,
        )
        worker.progress.connect(self._on_export_progress)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(self._on_export_failed)
        self.background_job_manager.start_job(
            kind=JobKind.EXPORT,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"export-{request_id}",
        )

    def _create_stale_preview_message_box(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setWindowTitle("Vorschau ist nicht aktuell")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "Die zuletzt erstellte Vorschau entspricht nicht mehr den "
            "aktuellen Einstellungen. Beim Export wird der Kühlturm mit "
            "den aktuellen Werten neu erzeugt.\n\nMöchten Sie den "
            "Kühlturm trotzdem generieren und exportieren?"
        )
        yes_button = box.addButton("Ja", QMessageBox.ButtonRole.AcceptRole)
        preview_button = box.addButton(
            "Vorschau aktualisieren", QMessageBox.ButtonRole.ActionRole
        )
        no_button = box.addButton("Nein", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no_button)
        box.setEscapeButton(no_button)
        box._stale_yes_button = yes_button  # type: ignore[attr-defined]
        box._stale_preview_button = preview_button  # type: ignore[attr-defined]
        box._stale_no_button = no_button  # type: ignore[attr-defined]
        return box

    def _ask_stale_preview_action(self) -> str:
        box = self._create_stale_preview_message_box()
        box.exec()
        clicked = box.clickedButton()
        if clicked is box._stale_yes_button:  # type: ignore[attr-defined]
            return "yes"
        if clicked is box._stale_preview_button:  # type: ignore[attr-defined]
            return "preview"
        return "no"

    def _on_export_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._export_request_id or self._closing:
            return
        status = german_user_message(status)
        self._set_main_status(status, icon="⏳", state="running")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_bar.show()

    def _on_export_succeeded(
        self,
        request_id: int,
        result: PreviewExportResult,
    ) -> None:
        if request_id != self._export_request_id or self._closing:
            return
        self.last_export_result = result
        self._latest_export_directory = result.output_path.parent.resolve()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        if result.output_mode is OutputMode.STL:
            kind = (
                "slicerbasiert kalibriert und Zielzeit erreicht"
                if result.calibrated
                else "sliceroptimierter bester Zwischenstand"
                if result.slicer_optimized
                else "analytisch erzeugt"
            )
            self._set_main_status(
                "STL erfolgreich exportiert", icon="✓", state="success"
            )
            self.result_label.setText(
                f"Datei: {result.output_path.name}\n"
                f"Erzeugungsart: {kind}\n"
                "Kurzbericht und technischer Bericht wurden im "
                "Ausgabeordner gespeichert."
            )
            self.result_label.setToolTip(str(result.output_path))
        else:
            minimum = (
                f"{result.minimum_verified_layer_time_s:.3f} s"
                if result.minimum_verified_layer_time_s is not None
                else "nicht separat verfügbar"
            )
            self._set_main_status(
                "G-Code erfolgreich exportiert und endanalysiert",
                icon="✓",
                state="success",
            )
            self.result_label.setText(
                f"G-Code gespeichert: {result.output_path}\n"
                f"Kleinste geprüfte relevante Layerzeit: {minimum}. "
                "Nachträgliche Objekt- oder Sliceränderungen erfordern einen neuen "
                "Slicevorgang und eine neue Kühlturmerzeugung."
            )
        self._update_responsive_action_labels()
        self._refresh_folder_action_states()
        self.open_run_button.setEnabled(True)
        if result.slicer_optimized and not result.calibrated:
            self.warning_text.setPlainText(
                _format_footer_notice([
                    "Die Sliceroptimierung hat die Zielzeit nicht vollständig "
                    "erreicht.",
                    "Der beste gültige Zwischenstand wurde exportiert.",
                ])
            )
            self.warning_text.show()
        elif not result.calibrated:
            self.warning_text.setPlainText(
                _format_footer_notice([
                    "Der Export wurde analytisch erstellt.",
                    "Die Layerzeit konnte nicht durch einen erfolgreichen "
                    "Slicerlauf bestätigt werden.",
                ])
            )
            self.warning_text.show()
        self._refresh_issue_panels()
        self._save_user_settings()

    def _on_export_failed(
        self,
        request_id: int,
        message: str,
        details: str,
    ) -> None:
        self._write_gui_error_log("gui_export_error.log", details)
        if request_id != self._export_request_id or self._closing:
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self._set_main_status(
            "Export fehlgeschlagen", icon="✕", state="error"
        )
        self.result_label.setText(german_user_message(message))
        self._refresh_phase17_actions()

    def _write_gui_error_log(
        self,
        file_name: str,
        details: str,
    ) -> Path | None:
        output_root = Path(
            self.output_root_edit.text() or self.default_output_root
        ).expanduser()
        try:
            log_directory = output_root / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            log_path = log_directory / file_name
            log_path.write_text(details, encoding="utf-8")
            return log_path.resolve()
        except OSError:
            return None

    def open_stl_directory(self) -> None:
        if self._latest_export_directory is not None:
            open_directory(self._latest_export_directory)

    def open_output_directory(self) -> None:
        """Open the configured base output folder, creating it if necessary."""

        output_text = self.output_root_edit.text().strip()
        if not output_text:
            return
        directory = Path(output_text).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            open_directory(directory.resolve())
        except OSError as error:
            self.result_label.setText(
                "Der Outputordner konnte nicht geöffnet werden: "
                f"{german_user_message(error)}"
            )
            self._schedule_footer_height_update()

    def open_run_directory(self) -> None:
        if self.last_export_result is not None:
            open_path(self.last_export_result.user_report_path)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_responsive_action_labels()
        self._update_slicer_combo_widths()
        if hasattr(self, "slicer_columns"):
            QTimer.singleShot(0, self._refresh_slicer_section_layout)
        if hasattr(self, "warning_text"):
            self.warning_text.schedule_height_update()
        if hasattr(self, "prediction_advice_frame"):
            QTimer.singleShot(0, self._fit_prediction_advice_height)
        if hasattr(self, "geometry_settings_group"):
            QTimer.singleShot(
                0,
                lambda: self._refresh_geometry_section_layout(
                    self.geometry_settings_group.isChecked()
                ),
            )
        if hasattr(self, "footer_content_grid"):
            self._refresh_footer_responsive_layout()
        self._schedule_footer_height_update()
        if (
            hasattr(self, "reconstructed_config_text")
            and self.reconstructed_config_text.isVisible()
        ):
            QTimer.singleShot(0, self._fit_reconstructed_config_height)
        if (
            (
                self._about_dialog is not None
                and self._about_dialog.isVisible()
            )
            or (
                self._additional_options_dialog is not None
                and self._additional_options_dialog.isVisible()
            )
        ):
            QTimer.singleShot(0, self._resize_visible_optional_dialogs)

    def _update_slicer_combo_widths(self) -> None:
        if not hasattr(self, "_slicer_width_combos"):
            return
        for combo in self._slicer_width_combos:
            # The selector column owns the width. Removing item alignment and
            # fixed limits lets every combo fill it in both responsive modes.
            combo.setMinimumWidth(0)
            combo.setMaximumWidth(16777215)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        for label in self._slicer_width_labels:
            label.setMinimumWidth(0)
            label.setMaximumWidth(16777215)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

    def _update_responsive_action_labels(self) -> None:
        if not hasattr(self, "open_stl_button"):
            return
        compact = self.width() < 900
        self.open_output_button.setText(
            "Outputordner" if compact else "Outputordner öffnen"
        )
        self.open_stl_button.setText(
            "Exportordner" if compact else "Exportordner öffnen"
        )
        self.reset_button.setText("Standardwerte wiederherstellen")
        preview_is_repeat = self.preview_state in {
            PreviewState.CURRENT,
            PreviewState.STALE,
        } or (
            self.preview_state is PreviewState.BUILDING
            and self.current_preview is not None
        )
        if self.preview_state is PreviewState.BUILDING:
            self.preview_button.setText("Vorschau wird erstellt...")
            if self._preview_dialog is not None:
                self._preview_dialog.update_button.setText(
                    "Vorschau wird erstellt..."
                )
        else:
            self.preview_button.setText(
                ("Aktualisieren" if preview_is_repeat else "Vorschau")
                if compact
                else (
                    "Vorschau aktualisieren"
                    if preview_is_repeat
                    else "Vorschau erstellen"
                )
            )
        self.export_button.setText(
            "Exportieren" if compact else "Kühlturm exportieren"
        )
        self._fit_export_button_width()

    def _fit_export_button_width(self) -> None:
        """Keep exactly 25 px of horizontal text padding on each side."""

        metrics = QFontMetrics(self.export_button.font())
        text_width = metrics.horizontalAdvance(self.export_button.text())
        border_width = 2
        self.export_button.setFixedWidth(
            text_width
            + 2 * EXPORT_ACTION_HORIZONTAL_PADDING_PX
            + border_width
        )

    def _refresh_folder_action_states(self) -> None:
        if not hasattr(self, "open_output_button"):
            return
        self.open_output_button.setEnabled(
            bool(self.output_root_edit.text().strip())
        )
        self.open_stl_button.setEnabled(
            self._latest_export_directory is not None
        )

    def _has_non_default_settings(self) -> bool:
        if self.collect_settings() != self.settings_store.load_defaults():
            return True
        if self.preview_quality != DEFAULT_PREVIEW_QUALITY:
            return True
        try:
            selected_output = Path(
                self.output_root_edit.text()
            ).expanduser().resolve()
            default_output = self.settings_store.load_default_output_root()
            return selected_output != default_output
        except OSError:
            return True

    def request_reset_defaults(self) -> None:
        if not self._has_non_default_settings():
            return
        box = self._create_reset_defaults_message_box()
        box.exec()
        if box.clickedButton() is box._reset_yes_button:  # type: ignore[attr-defined]
            self.reset_defaults()

    def _create_reset_defaults_message_box(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setWindowTitle("Standardwerte wiederherstellen?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "Alle abweichenden Einstellungen werden auf ihre Standardwerte "
            "zurückgesetzt. Die bisherigen Änderungen gehen dadurch verloren."
        )
        yes_button = box.addButton("Ja", QMessageBox.ButtonRole.AcceptRole)
        no_button = box.addButton("Nein", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no_button)
        box.setEscapeButton(no_button)
        box._reset_yes_button = yes_button  # type: ignore[attr-defined]
        box._reset_no_button = no_button  # type: ignore[attr-defined]
        return box

    def reset_defaults(self) -> None:
        self.apply_settings(self.settings_store.load_defaults())
        self._set_preview_quality(
            DEFAULT_PREVIEW_QUALITY,
            invalidate=False,
        )
        self.output_root_edit.setText(
            str(self.settings_store.load_default_output_root())
        )
        self._pending_preview_camera_state = None
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.reset_camera()
        self.timing_group.setChecked(True)
        self.prediction_frame.setChecked(True)
        self.geometry_settings_group.setChecked(True)
        self._invalidate_preview("Alle Einstellungen wurden zurückgesetzt.")
        self.update_wall_path_preview()
        self._refresh_tower_assessment()
        self.validate_form()

    def _save_user_settings(self) -> None:
        try:
            window_geometry = self.normalGeometry()
            window_position = self.pos()
            self.settings_store.save(
                self.collect_settings(),
                output_root=self.output_root_edit.text(),
                window_width=window_geometry.width(),
                window_height=window_geometry.height(),
                window_x=window_position.x(),
                window_y=window_position.y(),
                preview_quality=self.preview_quality,
                preview_camera=(
                    self._preview_dialog.canvas.camera_state()
                    if self._preview_dialog is not None
                    else self._pending_preview_camera_state
                ),
                expanded_sections={
                    "timing": self.timing_group.isChecked(),
                    "prediction": self.prediction_frame.isChecked(),
                    "geometry": self.geometry_settings_group.isChecked(),
                },
            )
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closing = True
        self._pending_slicer_discovery = None
        self._pending_profile_match = None
        self._feasibility_timer.stop()
        self._profile_watch_timer.stop()
        shutdown_result = self.background_job_manager.shutdown(5000)
        if not shutdown_result.clean:
            self._closing = False
            event.ignore()
            QMessageBox.warning(
                self,
                "Beenden noch nicht möglich",
                "Mindestens eine Hintergrundaufgabe konnte noch nicht "
                "kontrolliert beendet werden. Ihre Thread-Referenzen bleiben "
                "sicher erhalten. Bitte versuchen Sie es erneut.",
            )
            return

        self._save_user_settings()
        if self.current_preview is not None:
            self.current_preview.dispose()
            self.current_preview = None
        if self._preview_dialog is not None:
            self._preview_dialog.close()
        if self._additional_options_dialog is not None:
            self._additional_options_dialog.close()
        if self._about_dialog is not None:
            self._about_dialog.close()
        self._hint_controller.dispose()
        super().closeEvent(event)
