from __future__ import annotations

import math
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from weakref import ref

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    QTimer,
    Qt,
    Signal,
    Slot,
)
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
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayoutItem,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.diagnostics import (
    DiagnosticJournal,
    current_diagnostic_journal,
)
from cooling_tower.gui.about_dialog import AboutDialog, CURRENT_LICENSE_STATUS, LICENSE_STATUS_DEFINITIONS
from cooling_tower.gui.widgets.preparation_controls import (
    _SequentialPreparationTabs, _PreparationState, _PreparationStepSelector, _PreparationRequirementsPanel, _ConfirmationProgressBar
)
from cooling_tower.gui.background_jobs import (
    BackgroundJob,
    BackgroundJobManager,
    JobKind,
)
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.feasibility_worker import FeasibilityWorker
from cooling_tower.gui.generation_panel import GenerationPanel
from cooling_tower.gui.generation_session import GenerationMode, GenerationSession
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.manual_controller import ManualGenerationController
from cooling_tower.gui.widgets.generation_mode_card import GenerationModeCard, GenerationModeGrid
from cooling_tower.gui.widgets.stl_validation_feedback import StlValidationFeedback
from cooling_tower.gui.generation_progress_dialog import (
    JointSliceSettingsDialog,
    MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
)
from cooling_tower.gui.export_history import resolve_latest_export_directory
from cooling_tower.gui.export_worker import ExportWorker
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.layer_range_dialog import LayerRangeDialog
from cooling_tower.models.layer_ranges import excluded_layer_indices, normalize_layer_ranges
from cooling_tower.gui.preview_worker import PreviewWorker
from cooling_tower.gui.profile_worker import (
    ProfileCatalogWorker,
    ProfileMatchingWorker,
)
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.gui.slicer_worker import SlicerDiscoveryWorker
from cooling_tower.gui.stl_validation_worker import StlValidationWorker
from cooling_tower.gui.source_preslice_worker import SourcePreSliceWorker
from cooling_tower.gui.support_simulation_dialog import SupportSimulationDialog
from cooling_tower.gui.draft_shield_dialog import DraftShieldDialog
from cooling_tower.slicers.support_simulation import (
    tower_support_warning_angle, with_simulated_supports,
)
from cooling_tower.slicers.draft_shield import (
    draft_shield_source, with_simulated_draft_shield_disabled,
)
from cooling_tower.gui.support_report_dialog import SupportReportDialog
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
    SourceDropZone,
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
    SourceChangedError,
    BedBounds,
    CalibrationConfig,
    CalibrationMode,
    FeasibilityIssue,
    GCodeAnalysisSnapshot,
    PreparedAnalysisSource,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    TowerNeedAssessment,
    SourceArtifact,
    SourceKind,
)
from cooling_tower.distribution import (
    DistributionChannel,
    detect_distribution_channel,
)
from cooling_tower.persistence import migrate_legacy_configuration
from cooling_tower.persistence import PreSliceCache
from cooling_tower.preview import (
    OutputMode,
    PreviewExportResult,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewScene,
    PreviewService,
    PreviewState,
)
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.services import (
    DEFAULT_PRESLICE_TIMEOUT_S,
    GCodeAnalysisService,
    SourcePreSliceResult,
    SourcePreSliceService,
    StlValidationResult,
    StlValidationService,
    assess_tower_need,
)
from cooling_tower.services.stl_validation import StlIssueCode
from cooling_tower.slicers import (
    ProfileCatalog,
    ProfileCatalogConfirmation,
    ProfileInventoryService,
    ProfileConfirmation,
    ProfileMappingStore,
    ProfileMatchResult,
    ProfileMatchingService,
    ProfileMatchingContext,
    ProfileMatchState,
    ProfileSelectionReference,
    SlicerDiscoveryResult,
    SlicerDiscoveryService,
    SlicerGuiState,
    SlicerInstallation,
    SlicerPreferenceStore,
    SlicerProcessError,
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
from cooling_tower.support_report import SupportReportService
from cooling_tower.tower.solid_profile import (
    MAXIMUM_EXPANSION_ANGLE_DEG,
    validate_solid_settings,
)
from cooling_tower.tower.base_calculator import (
    BASE_WIDTH_PER_OBJECT_HEIGHT,
    MAXIMUM_BASE_WIDTH_MM,
    MINIMUM_AUTOMATIC_BASE_WIDTH_MM,
    MINIMUM_BASE_WIDTH_MM,
)


_LOCKED_SLICER_STEP_TOOLTIP = (
    "Zuerst Schritt 1 mit einer gültigen STL abschließen."
)

_PROFILE_SELECTION_ROLE = int(Qt.ItemDataRole.UserRole) + 1
DEFAULT_MAXIMUM_SEPARATE_SLICES = 6
GENERATION_PHASE_FADE_OUT_MS = 180
GENERATION_PHASE_FADE_IN_MS = 220
GENERATION_MINIMUM_JOINT_SLICES = MINIMUM_JOINT_SLICES_BEFORE_ACCEPT
MAIN_FOOTER_MAX_HEIGHT_PX = 350
MAIN_FOOTER_NARROW_MAX_HEIGHT_PX = 400
MAXIMUM_TARGET_LAYER_TIME_S = 30.0
PREVIEW_ACTION_COMPACT_WIDTH_PX = 176
EXPORT_ACTION_HORIZONTAL_PADDING_PX = 25
ABOUT_DIALOG_MINIMUM_WIDTH_PX = 450
ABOUT_DIALOG_PREFERRED_WIDTH_PX = 720
ABOUT_DIALOG_MAXIMUM_NATURAL_HEIGHT_PX = 720
OPTIONAL_DIALOG_PARENT_MARGIN_PX = 80
OUTPUT_DIALOG_MINIMUM_WIDTH_PX = 600
EXPORT_SUCCESS_DIALOG_PREFERRED_WIDTH_PX = 540
SUPPORT_DIALOG_PREFERRED_WIDTH_PX = 700
SUPPORT_DIALOG_PREFERRED_HEIGHT_PX = 670
INTERNAL_DIALOG_REVEAL_DELAY_MS = 40
_PREPARATION_CONTENT_GAP_PX = 8
PRESLICE_ACTIVITY_FRAME_INTERVAL_MS = 140
_PRESLICE_PROGRESS_FORMAT = (
    "Slicer und Profile bestätigt, Pre-Slice wird durchgeführt... (%p%)"
)
_PRESLICE_CANCEL_FORMAT = "Pre-Slice wird abgebrochen... (%p%)"
_PRESLICE_TIMEOUT_FORMAT = (
    "Zeitlimit von 8 Minuten erreicht, Pre-Slice wird abgebrochen... (%p%)"
)
_PRESLICE_ACTIVITY_FRAMES = ("◐", "◓", "◑", "◒")
SETTING_UNITS = {
    "target_layer_time_s": "Sek.",
    "layer_time_tolerance_s": "Sek.",
    "minimum_outer_diameter_mm": "mm",
    "maximum_outer_diameter_mm": "mm",
    "manual_base_width_mm": "mm",
    "maximum_expansion_angle_deg": "°",
    "maximum_contraction_angle_deg": "°",
    "local_reference_window": "Layer",
}
GUI_ASSET_ROOT = Path(__file__).with_name("assets")

FULL_INFILL_HINT_HTML = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was macht diese Funktion?</b></p>
<p style="margin-top:0; margin-bottom:10px;">
&#8226; <b>Aktiviert:</b> In der temporären Slicerprofilkopie wird für den Turm 100% Füllung eingestellt.<br>
&#8226; <b>Deaktiviert:</b> Für Berechnung und Slice gelten die Füllungswerte des gewählten Slicerprofils.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Sollte ich diese Einstellung aktivieren?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Das hängt teilweise davon ab, ob Ihr Drucker ein Bettschubser oder ein CoreXY-Drucker ist.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Welchen Druckertyp habe ich?</b></p>
<p style="margin-top:0; margin-bottom:8px;">
&#8226; <b>Bettschubser:</b> Das Druckbett bewegt das Modell horizontal vor und zurück.<br>
&#8226; <b>CoreXY:</b> Der Druckkopf übernimmt die horizontalen X/Y-Bewegungen; das Bett fährt dabei nicht hin und her.</p>
<p align="center" style="margin-top:0; margin-bottom:0px;"><b>Vor- und Nachteile dieser Funktion:</b></p>
<table width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:6px; margin-bottom:0px;">
  <tr>
    <th align="left" style="padding:4px 12px 4px 0;"><u>Druckertyp</u></th>
    <th align="left" style="padding:4px 12px;"><u>Aktiviert: Vorteil / Nachteil</u></th>
    <th align="left" style="padding:4px 12px;"><u>Deaktiviert: Vorteil / Nachteil</u></th>
  </tr>
  <tr>
    <td valign="top" style="padding:4px 12px 4px 0;"><b>Bettschubser</b></td>
    <td valign="top" style="padding:4px 12px;"><b>Aktivierung empfohlen.</b><br>+ Schmalerer Turm<br>+ Weniger Schwingungen<br>- Mehr Material</td>
    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br>- Breiterer Turm<br>- Kann stärker schwingen.</td>
  </tr>
  <tr>
    <td valign="top" style="padding:4px 12px 4px 0;"><b>CoreXY</b></td>
    <td valign="top" style="padding:4px 12px;">+ Schmalerer Turm<br/>- Mehr Material</td>
    <td valign="top" style="padding:4px 12px;">+ Weniger Material<br/>- Breiterer Turm</td>
  </tr>
</table>
<p>* Die 100%-Füllung gilt nur für den Kühlturm. Zur Generierung werden temporäre Profilkopien verwendet; im exportierten 3MF wird die Füllung objektspezifisch gesetzt. Die Originalprofile bleiben unverändert.</p>
""".strip()

FULL_INFILL_HINT_ACCESSIBLE = (
    "Sollte ich diese Einstellung aktivieren? Das hängt vom Druckertyp ab. "
    "Beim Bettschubser bewegt das Bett das Modell horizontal; die Aktivierung "
    "ist empfohlen, weil der Turm gleich breit bleibt oder schmaler und "
    "stabiler wird und weniger schwingt. "
    "Sie benötigt etwas mehr Material. Bei CoreXY bewegt der Druckkopf sich "
    "horizontal; die Aktivierung ist meist optional. Deaktiviert braucht der "
    "Turm meist weniger Material, kann aber breiter sein. Die volle Füllung "
    "betrifft nur den Kühlturm."
)

def _automatic_base_hint() -> tuple[str, str]:
    rate = f"{BASE_WIDTH_PER_OBJECT_HEIGHT:g}".replace(".", ",")
    html = (
        '<p align="left" style="margin-top:0; margin-bottom:0px;">'
        '<b>Automatische Standfußbreite</b></p>'
        '<p style="margin-top:0; margin-bottom:10px;">'
        f'&#8226; <b>Berechnungsgrundlage:</b> {rate} mm Breite je 1 mm '
        'Original-Objekthöhe.<br>'
        '&#8226; <b>Grenzbereich:</b> Das Ergebnis wird auf mindestens '
        '25 mm und höchstens 80 mm begrenzt.</p>'
        '<p align="left" style="margin-top:0; margin-bottom:0px;">'
        '<b>Manuelle Standfußbreite</b></p>'
        '<p style="margin-top:0; margin-bottom:10px;">'
        '&#8226; <b>Grenzbereich:</b> Manuell einstellbar zwischen 20 und 80mm.<br>'
        '&#8226; Ein breiterer Standfuß verbessert Druckbett-Haftung und '
        'Turmstabilität.</p>'
    )
    accessible = (
        f"Automatische Standfußbreite. Berechnungsgrundlage: {rate} "
        "Millimeter Breite je 1 Millimeter Original-Objekthöhe. "
        "Grenzbereich: Das Ergebnis wird auf mindestens 25 Millimeter "
        "und höchstens 80 Millimeter begrenzt. "
        "Manuelle Standfußbreite. Grenzbereich: Manuell einstellbar "
        "zwischen 20 und 80 Millimetern. Ein breiterer Standfuß verbessert "
        "Druckbett-Haftung und Turmstabilität."
    )
    return html, accessible

TOWER_SUPPORT_HINT_HTML = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was bewirkt die Einstellung?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Bei aktivierter Einstellung werden die Stützen für den Kühlturm objektspezifisch deaktiviert. Der Turm wird so ohne eigene Stützen berechnet; die Stützen des Druckobjekts bleiben erhalten.</p>
<p>* Die Stützen werden nur für den Kühlturm deaktiviert. Zur Generierung werden temporäre Profilkopien verwendet; im exportierten 3MF wird die Deaktivierung objektspezifisch gesetzt. Die Originalprofile bleiben unverändert.</p>
""".strip()

TOWER_SUPPORT_HINT_ACCESSIBLE = (
    "Bei aktivierter Einstellung werden die Stützen für den Kühlturm "
    "objektspezifisch deaktiviert. Der Turm wird ohne eigene Stützen "
    "berechnet; die Stützen des Druckobjekts bleiben erhalten. Hinweis: "
    "Für die Generierung werden temporäre Profilkopien verwendet. Im "
    "exportierten 3MF werden nur die Turmstützen deaktiviert. Die "
    "Originalprofile bleiben unverändert."
)


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


def _concise_operation_failure_reason(message: object) -> str:
    """Return a compact cause for the persistent footer status."""

    raw = " ".join(str(message).split())
    folded = raw.casefold()
    if "sparse_infill_pattern" in folded and "100" in folded:
        return (
            "Das gewählte Füllmuster ist mit 100 % Turmfüllung nicht "
            "kompatibel."
        )
    rendered = " ".join(german_user_message(raw).split())
    if not rendered:
        return "Die Verarbeitung konnte nicht abgeschlossen werden."
    first_sentence = rendered.split(". ", 1)[0].rstrip(".") + "."
    if len(first_sentence) <= 150:
        return first_sentence
    return "Die Verarbeitung konnte nicht abgeschlossen werden."


def _preview_failure_footer_reason(message: object) -> str:
    """Keep the complete cause, except for a known cryptic slicer diagnostic."""

    raw = " ".join(str(message).split())
    if "sparse_infill_pattern" in raw.casefold() and "100" in raw:
        return _concise_operation_failure_reason(raw)
    return german_user_message(raw)


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




class _InternalDialogRevealFilter(QObject):
    """Conceal every owned dialog until its first native frame is stable."""

    def __init__(self, owner: QMainWindow) -> None:
        super().__init__(owner)
        self._owner_ref = ref(owner)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QDialog)
            and watched.isWindow()
            and self._is_managed_dialog(watched)
        ):
            self.prepare(watched)
            self.schedule_reveal(watched)
        return super().eventFilter(watched, event)

    def _is_managed_dialog(self, dialog: QDialog) -> bool:
        owner = self._owner_ref()
        if owner is None:
            return False
        parent = dialog.parentWidget()
        while parent is not None:
            if parent is owner:
                return True
            parent = parent.parentWidget()
        return owner.isVisible() and dialog.parentWidget() is None

    @staticmethod
    def prepare(dialog: QDialog) -> None:
        dialog.setWindowOpacity(0.0)

    def schedule_reveal(
        self,
        dialog: QDialog,
        before_reveal: Callable[[], None] | None = None,
    ) -> None:
        dialog._initial_reveal_callback = before_reveal  # type: ignore[attr-defined]
        timer = getattr(dialog, "_initial_reveal_timer", None)
        if timer is None:
            timer = QTimer(dialog)
            timer.setSingleShot(True)
            timer.setInterval(INTERNAL_DIALOG_REVEAL_DELAY_MS)
            filter_ref = ref(self)
            dialog_ref = ref(dialog)

            def reveal_referenced_dialog() -> None:
                reveal_filter = filter_ref()
                referenced_dialog = dialog_ref()
                if reveal_filter is not None and referenced_dialog is not None:
                    reveal_filter._reveal(referenced_dialog)

            timer.timeout.connect(reveal_referenced_dialog)
            dialog._initial_reveal_timer = timer  # type: ignore[attr-defined]
        timer.start()

    @staticmethod
    def _reveal(dialog: QDialog) -> None:
        callback = getattr(dialog, "_initial_reveal_callback", None)
        dialog._initial_reveal_callback = None  # type: ignore[attr-defined]
        try:
            if dialog.isVisible() and callable(callback):
                callback()
        finally:
            dialog.setWindowOpacity(1.0)
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()












class MainWindow(QMainWindow):
    """Scrollable desktop front end for the shared generation service."""

    def __init__(
        self,
        *,
        user_settings_path: str | Path | None = None,
        default_settings_path: str | Path | None = None,
        analysis_service: GCodeAnalysisService | None = None,
        stl_validation_service: StlValidationService | None = None,
        preslice_service: SourcePreSliceService | None = None,
        slicer_service: SlicerDiscoveryService | None = None,
        profile_service: ProfileMatchingService | None = None,
        preview_service: PreviewService | None = None,
        export_service: PreviewExportService | None = None,
        update_service: UpdateService | None = None,
        enable_update_check: bool | None = None,
        enable_startup_slicer_discovery: bool | None = None,
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
        self.analysis_service = analysis_service or GCodeAnalysisService(
            persistent_cache_path=(
                user_config_root / "gcode_analysis_cache.json"
            )
        )
        self.stl_validation_service = (
            stl_validation_service or StlValidationService()
        )
        self.preslice_service = preslice_service or SourcePreSliceService(
            analysis_service=self.analysis_service,
            workspace_parent=self.user_data_root / "temporary",
            diagnostics_root=(
                self.user_data_root / "diagnostics" / "source_preslice"
            ),
            cache=PreSliceCache(
                self.user_data_root / "cache" / "source_preslice"
            ),
        )
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
        self.support_report_service = SupportReportService(
            self.user_data_root,
            diagnostic_journal=self.background_job_manager.diagnostic_journal,
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
        self._startup_slicer_discovery_enabled = bool(
            enable_startup_slicer_discovery
            if enable_startup_slicer_discovery is not None
            else (
                os.environ.get("COOLING_TOWER_DISABLE_SLICER_DISCOVERY") != "1"
                and os.environ.get("QT_QPA_PLATFORM", "").casefold()
                != "offscreen"
            )
        )
        self.available_update: UpdateInfo | None = None
        self._update_check_request_id = 0
        self._update_download_request_id = 0
        self._update_download_cancel_requested = False
        self._slicer_request_id = 0
        self._pending_slicer_discovery: tuple[bool, Path | None] | None = None
        self._slicer_step_auto_discovery_attempted = False
        self.slicer_discovery_result: SlicerDiscoveryResult | None = None
        self._slicer_header_installation: SlicerInstallation | None = None
        self._automatically_selected_slicer_key: str | None = None
        self._populating_slicer_combo = False
        self._profile_request_id = 0
        self._pending_profile_match: dict[str, object] | None = None
        self._profile_catalog_match_source_request_id: int | None = None
        self.profile_catalog: ProfileCatalog | None = None
        self.profile_catalog_confirmation: ProfileCatalogConfirmation | None = None
        self._force_profile_catalog_after_discovery = False
        self._profile_catalog_preserve_selection_requests: dict[int, bool] = {}
        self.profile_match_result: ProfileMatchResult | None = None
        self.confirmed_profile_context: ProfileConfirmation | None = None
        self._populating_profile_combos = False
        self.profile_preview_outdated = False
        self._stl_validation_request_id = 0
        self._preslice_request_id = 0
        self._support_simulation_offer_id = None
        self._support_simulation_dialog = None
        self._draft_shield_dialog = None
        self._draft_shield_simulation_requested = False
        self._pending_support_retry = None
        self._pending_support_profile_reload = None
        self._preslice_runtime_request_id: int | None = None
        self._preslice_timeout_request_id: int | None = None
        self._preslice_cancel_requested = False
        self._preslice_cancel_dispatch_pending = False
        self._preslice_progress_base_format = _PRESLICE_PROGRESS_FORMAT
        self._preslice_activity_frame_index = -1
        self._analysis_failed = False
        self._closing = False
        self.analysis_snapshot: GCodeAnalysisSnapshot | None = None
        self._excluded_layer_ranges: tuple[tuple[int, int], ...] = ()
        self._layer_range_silhouette = None
        self._layer_range_dialog: LayerRangeDialog | None = None
        self._range_color_thresholds = (0.0, 1.0)
        self.tower_assessment: TowerNeedAssessment | None = None
        self.profile_feasibility: ProfileFeasibilityAssessment | None = None
        self.current_gcode_path: Path | None = None
        self.current_source_path: Path | None = None
        self.current_source_kind: SourceKind | None = None
        self.source_artifact: SourceArtifact | None = None
        self.stl_validation_result: StlValidationResult | None = None
        self.source_preslice_result: SourcePreSliceResult | None = None
        self.prepared_analysis_source: PreparedAnalysisSource | None = None
        self._feasibility_request_id = 0
        self._preview_request_id = 0
        self._preview_cancel_requested = False
        self._active_preview_worker: PreviewWorker | None = None
        self._joint_generation_dialog: GenerationPanel | None = None
        self._joint_slice_settings_dialog: JointSliceSettingsDialog | None = None
        self._joint_phase_active = False
        self._joint_accept_requested = False
        self._joint_resume_active = False
        self._joint_resume_accept_seed_only = False
        self._joint_generation_paused = False
        self._joint_slice_offset = 0
        self._joint_slices_completed = 0
        self._generation_phase_effect: QGraphicsOpacityEffect | None = None
        self._generation_phase_fade_out: QPropertyAnimation | None = None
        self._generation_phase_fade_in: QPropertyAnimation | None = None
        self._generation_phase_transition_request_id: int | None = None
        self._generation_phase_transition_target: tuple[int, int] | None = None
        self._generation_phase_transition_stage: str | None = None
        self.generation_sessions = {
            mode: GenerationSession() for mode in GenerationMode
        }
        self.generation_mode: GenerationMode | None = None
        self.current_preview: PreviewResult | None = None
        self.preview_state = PreviewState.EMPTY
        self._slicer_prediction_request_id = 0
        self._slicer_prediction_estimate_s: float | None = None
        self._slicer_prediction_status = ""
        self._export_request_id = 0
        self._bambu_multinozzle_tower_only_export_active = False
        self.last_export_result: PreviewExportResult | None = None
        # Session-only state: exported generations must not create duplicate
        # timestamped folders, while their confirmation remains reopenable.
        self._last_exported_preview_identity: tuple[str, str | None] | None = None
        self._last_export_report_result: PreviewExportResult | None = None
        self._latest_export_directory: Path | None = None
        self._latest_export_root_text: str | None = None
        self._latest_export_unavailable_reason = "Kein Exportordner gefunden."
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
        self._export_success_dialog: QDialog | None = None
        self._support_report_dialog: SupportReportDialog | None = None

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
        self._manual_base_width_session_value = (
            self.default_settings.manual_base_width_mm
        )
        self._manual_base_width_user_override = False
        self._automatic_base_width_active = (
            self.default_settings.automatic_base_width
        )
        self.default_output_root = self.settings_store.load_default_output_root()
        self.default_maximum_joint_slices = (
            self.settings_store.load_default_maximum_joint_slices()
        )
        self.default_maximum_separate_slices = (
            self.settings_store.load_default_maximum_separate_slices()
        )
        initial_settings, ui_state = self.settings_store.load()
        self.show_setting_limits = ui_state.get("show_setting_limits", False) is True
        raw_joint_slices = ui_state.get(
            "maximum_joint_slices",
            self.default_maximum_joint_slices,
        )
        self.maximum_joint_slices = (
            int(raw_joint_slices)
            if isinstance(raw_joint_slices, int)
            and not isinstance(raw_joint_slices, bool)
            and 5 <= raw_joint_slices <= 20
            else self.default_maximum_joint_slices
        )
        raw_separate_slices = ui_state.get(
            "maximum_separate_slices",
            self.default_maximum_separate_slices,
        )
        self.maximum_separate_slices = (
            int(raw_separate_slices)
            if isinstance(raw_separate_slices, int)
            and not isinstance(raw_separate_slices, bool)
            and 1 <= raw_separate_slices <= 15
            else self.default_maximum_separate_slices
        )

        self._feasibility_timer = QTimer(self)
        self._feasibility_timer.setSingleShot(True)
        self._feasibility_timer.setInterval(180)
        self._feasibility_timer.timeout.connect(
            self._start_feasibility_validation
        )
        self._preslice_activity_timer = QTimer(self)
        self._preslice_activity_timer.setInterval(
            PRESLICE_ACTIVITY_FRAME_INTERVAL_MS
        )
        self._preslice_activity_timer.timeout.connect(
            self._advance_preslice_activity_frame
        )
        self._preslice_runtime_timer = QTimer(self)
        self._preslice_runtime_timer.setSingleShot(True)
        self._preslice_runtime_timer.timeout.connect(
            self._on_preslice_runtime_timeout
        )
        self._build_ui()
        for button in self.findChildren(QAbstractButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_target_geometry: QRect | None = None
        self._hint_controller = WindowHintController(self)
        self._internal_dialog_reveal_filter = _InternalDialogRevealFilter(self)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self._internal_dialog_reveal_filter)
        self._apply_style()
        cancel_metrics = QFontMetrics(self.preslice_cancel_button.font())
        self.preslice_cancel_button.setFixedWidth(
            max(
                cancel_metrics.horizontalAdvance(text)
                for text in (
                    "Pre-Slice abbrechen",
                    "Abbruch wird ausgeführt …",
                    "Zeitlimit erreicht …",
                )
            )
            + 36
        )
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
        self._update_preparation_requirements()
        self._show_settings_load_notice()
        QTimer.singleShot(0, self._update_slicer_combo_widths)
        if self._startup_slicer_discovery_enabled:
            QTimer.singleShot(0, self._start_initial_slicer_discovery)
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
        self.main_header = header
        header.setObjectName("mainHeader")
        header.setProperty("scrolled", False)
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
            "Turmeinstellungen außerhalb der allgemeinen Einstellungen zurücksetzen"
        )
        self.reset_button.setFixedHeight(METRICS.info_button_diameter_px)
        self.reset_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.reset_button.clicked.connect(self.request_reset_defaults)
        title_row.addWidget(title)
        title_row.addStretch(1)
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
        self.options_button.setAccessibleName("Menü öffnen")
        self.options_menu = QMenu(self.options_button)
        self.options_menu.setObjectName("mainOptionsMenu")
        self.joint_slice_settings_action = self.options_menu.addAction(
            QIcon(str(GUI_ASSET_ROOT / "settings_gear.svg")),
            "Allgemeine Einstellungen …",
        )
        self.joint_slice_settings_action.triggered.connect(
            self.show_joint_slice_settings
        )
        self.support_report_action = self.options_menu.addAction(
            QIcon(str(GUI_ASSET_ROOT / "document.svg")),
            "Support & Diagnose …",
        )
        self.support_report_action.triggered.connect(
            self.show_support_report_dialog
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
        self.update_cancel_button = QPushButton("Abbrechen")
        self.update_cancel_button.setObjectName("updateCancelButton")
        self.update_cancel_button.setFixedHeight(METRICS.info_button_diameter_px)
        self.update_cancel_button.clicked.connect(self.cancel_update_download)
        self.update_cancel_button.hide()
        subtitle_row.addWidget(self.update_cancel_button)
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
        # The gutter is needed only when the current viewport cannot display
        # the real content height.  Large windows therefore keep their full
        # width instead of showing an inactive scrollbar beside empty space.
        self.settings_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.settings_scroll.verticalScrollBar().rangeChanged.connect(
            self._on_settings_scroll_range_changed
        )
        self.settings_scroll.verticalScrollBar().valueChanged.connect(
            self._refresh_header_scroll_border
        )
        content = QWidget()
        content.setObjectName("settingsContent")
        self.settings_content = content
        self.content_layout = QVBoxLayout(content)
        self._settings_content_bottom_margin_px = 22
        self.content_layout.setContentsMargins(
            22,
            8,
            22,
            self._settings_content_bottom_margin_px,
        )
        self.content_layout.setSpacing(10)

        workflow_group = SectionCard(
            "Datei und Slicer vorbereiten",
            collapsible=False,
            expanded=True,
            state=SectionState.ACTIVE,
        )
        self.workflow_group = workflow_group
        # Alias with a domain-oriented name for callers and UI tests.
        self.preparation_group = workflow_group
        workflow_group.setProperty("role", "preparation")
        workflow_group.setProperty("outerDropdown", True)
        # Only the header is interactive.  A hover colour across the complete
        # expanded preparation surface makes the whole card look clickable and
        # causes distracting repaints while the user works inside a step.
        workflow_group.setProperty("bodyHover", False)
        workflow_group.status_icon.setProperty("headerLead", True)
        workflow_group.status_icon.setFixedWidth(45)
        workflow_group.status_icon.setFixedHeight(40)
        workflow_group.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        workflow_group.header_layout.setContentsMargins(
            METRICS.card_header_horizontal_padding_px,
            6,
            METRICS.card_header_horizontal_padding_px,
            6,
        )
        workflow_group.content_layout.setContentsMargins(0, 0, 0, 0)
        workflow_group.content_layout.setSpacing(0)

        source_group = SectionCard(
            "Dateiübergabe",
            collapsible=False,
            state=SectionState.ACTIVE,
        )
        self.source_group = source_group
        source_group.setProperty("role", "source")
        source_group.setProperty("subsection", "fileTransfer")
        source_layout = source_group.content_layout
        # The card itself is fitted to the exact sum of its visible blocks.
        # A global AlignTop constraint makes QVBoxLayout retain a cached,
        # smaller allocation for a drop-zone that grows after validation and
        # lets the fixed-height widget protrude into the following row.
        source_layout.setAlignment(Qt.Alignment())
        source_layout.setContentsMargins(20, 20, 20, 20)
        source_layout.setSpacing(_PREPARATION_CONTENT_GAP_PX)

        # Local progress is transient: the persistent state is represented by
        # the shared prerequisite overview above both columns.
        self.source_progress_bar = QProgressBar()
        self.source_progress_bar.setObjectName("sourceValidationProgressBar")
        self.source_progress_bar.setRange(0, 100)
        self.source_progress_bar.setValue(0)
        self.source_progress_bar.setFormat("%p %")
        self.source_progress_bar.setAccessibleName(
            "Fortschritt der STL-Prüfung"
        )
        source_layout.addWidget(self.source_progress_bar)
        self.source_progress_bar.hide()
        self.source_progress_status_widget = QWidget()
        self.source_progress_status_widget.setObjectName("sourceProgressStatus")
        source_progress_status = QHBoxLayout(
            self.source_progress_status_widget
        )
        source_progress_status.setContentsMargins(0, 0, 0, 0)
        self.source_progress_icon_label = QLabel("○")
        self.source_progress_icon_label.setObjectName("progressStatusIcon")
        self.source_progress_icon_label.setProperty("state", "pending")
        self.source_progress_status_label = QLabel("Datei auswählen")
        self.source_progress_status_label.setObjectName("sourceProgressStatusLabel")
        self.source_progress_status_label.setWordWrap(True)
        source_progress_status.addWidget(
            self.source_progress_icon_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.source_progress_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        source_progress_status.addWidget(self.source_progress_status_label, 1)
        source_layout.addWidget(self.source_progress_status_widget)
        # The drop zone already exposes the durable source state in its
        # dedicated "Status" fact row. Keep this compatibility widget for
        # existing status updates, but do not render the duplicate summary.
        self.source_progress_status_widget.hide()

        self.source_guide_row = QWidget()
        self.source_guide_row.setObjectName("sourceGuideRow")
        source_guide_layout = QHBoxLayout(self.source_guide_row)
        source_guide_layout.setContentsMargins(
            0,
            0,
            0,
            max(
                0,
                METRICS.card_body_vertical_padding_px
                - source_layout.spacing(),
            ),
        )
        source_guide_layout.setSpacing(8)
        self.source_guide_icon = QLabel("ℹ")
        self.source_guide_icon.setObjectName("sourceGuideIcon")
        self.source_guide_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_guide_icon.setFixedWidth(22)
        self.source_guide = QLabel(
            "Wähle das STL-Modell aus, für das ein Kühlturm erstellt werden "
            "soll."
        )
        self.source_guide.setObjectName("sourceGuide")
        self.source_guide.setWordWrap(True)
        source_guide_layout.addWidget(
            self.source_guide_icon,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        source_guide_layout.addWidget(self.source_guide, 1)
        source_layout.addWidget(self.source_guide_row)
        # This remains an informational hint only. The drop zone below is the
        # sole interactive entry point for the supported STL source.
        self.drop_zone = SourceDropZone()
        self.drop_zone.source_selected.connect(self._on_source_selected)
        self.drop_zone.file_rejected.connect(self._show_input_error)
        self.drop_zone.reload_requested.connect(self.reload_source)
        self.drop_zone.remove_requested.connect(self.remove_source)
        source_layout.addWidget(self.drop_zone)
        self.preslice_cancel_button = QPushButton("Pre-Slice abbrechen")
        self.preslice_cancel_button.setObjectName("presliceCancelButton")
        self.preslice_cancel_button.clicked.connect(self.cancel_source_preslice)
        self.preslice_cancel_button.hide()

        self.stl_validation_feedback = StlValidationFeedback()
        self.stl_validation_message = self.stl_validation_feedback.message
        self.stl_validation_warning_message = (
            self.stl_validation_feedback.warning_message
        )
        self.stl_validation_details_toggle = (
            self.stl_validation_feedback.details_toggle
        )
        self.stl_validation_details = self.stl_validation_feedback.details
        source_layout.addWidget(self.stl_validation_feedback)
        self.stl_validation_details_toggle.toggled.connect(
            self._toggle_stl_validation_details
        )
        self.accept_rejected_stl_button = QPushButton("STL trotzdem verwenden")
        self.accept_rejected_stl_button.setObjectName(
            "acceptRejectedStlButton"
        )
        self.accept_rejected_stl_button.setAccessibleName(
            "Abgelehnte STL nach Sicherheitsbestätigung trotzdem verwenden"
        )
        self.accept_rejected_stl_button.clicked.connect(
            self._confirm_rejected_stl
        )
        self.accept_rejected_stl_button.hide()
        source_layout.addWidget(
            self.accept_rejected_stl_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

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
        self.stl_mode_status = QLabel(
            "Ein bestätigter Slicer ist für die Verarbeitung erforderlich."
        )
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
            "Slicer-Einstellungen",
            collapsible=False,
        )
        self.slicer_group = slicer_group
        slicer_group.setProperty("role", "slicer")
        slicer_group.setProperty("subsection", "slicerSettings")
        slicer_layout = slicer_group.content_layout
        slicer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        slicer_layout.setContentsMargins(20, 20, 20, 20)
        slicer_layout.setSpacing(_PREPARATION_CONTENT_GAP_PX)

        # Search progress always forms the first block in the Slicer card, but
        # remains hidden whenever no background calculation is active.
        # Compatibility-only handles for existing integrations.  Transient
        # Slicer activity is rendered later in the stable confirmation slot,
        # so these widgets never take layout space or shift the selectors.
        self.slicer_progress_bar = QProgressBar(slicer_group.content_widget)
        self.slicer_progress_bar.setObjectName("slicerDiscoveryProgressBar")
        self.slicer_progress_bar.setRange(0, 100)
        self.slicer_progress_bar.setValue(0)
        self.slicer_progress_bar.setFormat("%p %")
        self.slicer_progress_bar.setAccessibleName(
            "Fortschritt der Slicer- und Profilprüfung"
        )
        self.slicer_progress_status_widget = QWidget(
            slicer_group.content_widget
        )
        slicer_progress_status = QHBoxLayout(
            self.slicer_progress_status_widget
        )
        slicer_progress_status.setContentsMargins(0, 0, 0, 0)
        self.slicer_progress_icon_label = QLabel("○")
        self.slicer_progress_icon_label.setObjectName("progressStatusIcon")
        self.slicer_progress_icon_label.setProperty("state", "pending")
        self.slicer_progress_status_label = QLabel(
            "Wartet auf die Dateianalyse"
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
        self.slicer_progress_bar.hide()
        self.slicer_progress_status_widget.hide()
        # Keep the primary controls in one predictable vertical sequence.
        # Supporting evidence is collected in a separate disclosure below.
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
        self.profile_filter_label = QLabel(
            "Profilfilter\nNoch keine Profile inventarisiert."
        )
        self.profile_filter_label.setObjectName("profileFilterLabel")
        self.profile_filter_label.setWordWrap(True)
        slicer_information_layout.addWidget(self.slicer_detail_label)
        slicer_information_layout.addWidget(self.profile_filter_label)

        slicer_selectors = QWidget()
        self.slicer_selector_column = slicer_selectors
        slicer_selectors.setObjectName("slicerSelectorColumn")
        slicer_selectors_layout = QVBoxLayout(slicer_selectors)
        self.slicer_selectors_layout = slicer_selectors_layout
        # The outer white card owns all edge spacing.  An additional local
        # bottom inset made confirmed/hidden-button states appear misaligned.
        slicer_selectors_layout.setContentsMargins(0, 0, 0, 0)
        slicer_selectors_layout.setSpacing(6)
        self.slicer_combo = WheelSafeComboBox()
        self.slicer_combo.setObjectName("slicerSelection")
        self.slicer_combo.setProperty("important", True)
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
        self.slicer_refresh_button = QPushButton(
            "Slicer und Profile erneut erkennen"
        )
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
        self.slicer_selection_label.setBuddy(self.slicer_combo)
        self.slicer_auto_detected_label = QLabel("(automatisch erkannt)")
        self.slicer_auto_detected_label.setObjectName(
            "slicerAutoDetectedLabel"
        )
        self.slicer_auto_detected_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.slicer_auto_detected_label.hide()
        slicer_label_row = QWidget()
        slicer_label_row.setObjectName("slicerLabelRow")
        slicer_label_row_layout = QHBoxLayout(slicer_label_row)
        slicer_label_row_layout.setContentsMargins(0, 0, 0, 0)
        slicer_label_row_layout.setSpacing(6)
        slicer_label_row_layout.addWidget(self.slicer_selection_label)
        slicer_label_row_layout.addWidget(self.slicer_auto_detected_label)
        slicer_label_row_layout.addStretch(1)
        slicer_selectors_layout.addWidget(slicer_label_row)
        slicer_selectors_layout.addWidget(self.slicer_combo)
        slicer_actions = QHBoxLayout()
        # Align the visible combo-to-action gap with the progress-to-cancel
        # gap at the bottom of this same control column.
        slicer_actions.setContentsMargins(0, 4, 0, 0)
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
            combo.setProperty("important", True)
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
            (self.filament_profile_label, self.filament_profile_combo),
            (self.process_profile_label, self.process_profile_combo),
        ):
            label.setObjectName("slicerFieldTitle")
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            label.setBuddy(combo)
            slicer_selectors_layout.addWidget(label)
            slicer_selectors_layout.addWidget(combo)
        self.show_all_profiles_checkbox = QCheckBox("Alle Profile anzeigen")
        self.show_all_profiles_checkbox.setObjectName(
            "showAllProfilesCheckBox"
        )
        self.show_all_profiles_checkbox.setToolTip(
            "Zeigt alle Maschinen-, Filament- und Prozessprofile des "
            "gewählten Slicers und setzt den Druckerfilter vorübergehend aus."
        )
        self.show_all_profiles_checkbox.setEnabled(False)
        self.show_all_profiles_row = QWidget()
        self.show_all_profiles_row.setObjectName("showAllProfilesRow")
        show_all_profiles_row_layout = QHBoxLayout(self.show_all_profiles_row)
        # The check box's own styled padding changes its visual top offset.
        # These asymmetric row insets produce the same effective 10 px gap
        # above and below as between every title and its dropdown.
        show_all_profiles_row_layout.setContentsMargins(0, 8, 0, 4)
        show_all_profiles_row_layout.setSpacing(0)
        show_all_profiles_row_layout.addWidget(
            self.show_all_profiles_checkbox,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        slicer_selectors_layout.addWidget(self.show_all_profiles_row)

        self.slicer_columns_divider = QFrame()
        self.slicer_columns_divider.setObjectName("slicerVerticalDivider")
        self.slicer_columns_divider.setFixedWidth(1)
        self.slicer_columns_divider.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        # Retained as a compatibility handle; the reduced Slicer hierarchy no
        # longer splits its already narrow outer column a second time.
        self.slicer_columns_divider.hide()
        self.slicer_columns.add_full_width(slicer_selectors)
        slicer_layout.addWidget(self.slicer_status_label)
        # Durable readiness is represented by the status checklist.  The old
        # prose lines duplicated that information and obscured the selectors.
        self.slicer_status_label.hide()
        slicer_layout.addWidget(self.slicer_columns)

        self.slicer_details_divider = QFrame()
        self.slicer_details_divider.setObjectName("slicerHorizontalDivider")
        self.slicer_details_divider.setFixedHeight(1)
        slicer_layout.addWidget(self.slicer_details_divider)
        self.slicer_details_divider.hide()
        self.profile_status_label = QLabel(
            "Profilzuordnung beginnt nach Quellen- und Slicerauswahl."
        )
        self.profile_status_label.setObjectName("profileStatusLabel")
        self.profile_status_label.setWordWrap(True)
        self.profile_status_label.setProperty("state", "pending")
        self.profile_status_label.hide()
        self.profile_effective_summary_label = QLabel()
        self.profile_effective_summary_label.setObjectName(
            "profileEffectiveSummaryLabel"
        )
        self.profile_effective_summary_label.setWordWrap(True)
        self.profile_effective_summary_label.hide()
        self.profile_confirm_button = QPushButton(
            "Slicer und Profile bestätigen 🔒"
        )
        self.profile_confirm_button.setObjectName("profileConfirmButton")
        self.profile_confirm_button.setProperty("ready", False)
        self.profile_confirm_button.setProperty("confirmed", False)
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.setToolTip(
            "Wähle einen validen Slicer sowie je ein vorhandenes Maschinen-, "
            "Filament- und Prozessprofil aus."
        )
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
        slicer_selectors_layout.addWidget(self.profile_effective_summary_label)
        self.profile_confirmation_stack = QStackedWidget()
        self.profile_confirmation_stack.setObjectName(
            "profileConfirmationStack"
        )
        self.profile_confirmation_stack.setFixedHeight(50)
        self.profile_confirmation_stack.addWidget(self.profile_confirm_button)
        self.profile_confirmation_progress = _ConfirmationProgressBar()
        self.profile_confirmation_progress.setObjectName(
            "profileConfirmationProgress"
        )
        self.profile_confirmation_progress.setRange(0, 100)
        self.profile_confirmation_progress.setValue(0)
        self.profile_confirmation_progress.setFormat(
            "Slicer-Einstellungen werden geprüft · %p %"
        )
        self.profile_confirmation_progress.setTextVisible(False)
        self.profile_confirmation_progress.setAccessibleName(
            "Fortschritt der Slicer- und Profilprüfung"
        )
        self.profile_confirmation_stack.addWidget(
            self.profile_confirmation_progress
        )
        self.profile_confirmation_stack.setCurrentWidget(
            self.profile_confirm_button
        )
        self._profile_confirmation_busy = False
        slicer_selectors_layout.addWidget(self.profile_confirmation_stack)
        slicer_selectors_layout.addWidget(
            self.preslice_cancel_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )

        self.slicer_message_divider_host = QWidget()
        self.slicer_message_divider_host.setObjectName(
            "slicerMessageDividerHost"
        )
        slicer_message_divider_layout = QVBoxLayout(
            self.slicer_message_divider_host
        )
        slicer_message_divider_layout.setContentsMargins(0, 0, 0, 0)
        slicer_message_divider_layout.setSpacing(0)
        self.slicer_message_divider = QFrame()
        self.slicer_message_divider.setObjectName("slicerMessageDivider")
        self.slicer_message_divider.setFixedHeight(1)
        slicer_message_divider_layout.addWidget(self.slicer_message_divider)
        self.slicer_message_divider_host.hide()
        slicer_layout.addWidget(self.slicer_message_divider_host)
        # Actionable messages belong below the primary action.  The divider
        # appears only together with such a message.
        slicer_layout.addWidget(self.profile_status_label)

        self.slicer_analysis_details_toggle = QPushButton(
            "Analyse- und Profildetails anzeigen ▸"
        )
        self.slicer_analysis_details_toggle.setObjectName(
            "slicerAnalysisDetailsToggle"
        )
        self.slicer_analysis_details_toggle.setProperty(
            "compactDisclosure", True
        )
        self.slicer_analysis_details_toggle.setCheckable(True)
        self.slicer_analysis_details_toggle.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )
        self.slicer_analysis_details_toggle.setMinimumHeight(24)
        self.slicer_analysis_details_toggle.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.slicer_analysis_details_toggle.setAccessibleName(
            "Analyse- und Profildetails einblenden"
        )
        self.slicer_analysis_details = QScrollArea()
        self.slicer_analysis_details.setObjectName("slicerAnalysisDetails")
        self.slicer_analysis_details.setWidgetResizable(True)
        self.slicer_analysis_details.setFrameShape(QFrame.Shape.NoFrame)
        self.slicer_analysis_details.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.slicer_analysis_details.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.slicer_analysis_details.setFixedHeight(190)
        self.slicer_analysis_details.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.slicer_analysis_details_content = QWidget()
        self.slicer_analysis_details_content.setObjectName(
            "slicerAnalysisDetailsContent"
        )
        slicer_analysis_details_layout = QVBoxLayout(
            self.slicer_analysis_details_content
        )
        slicer_analysis_details_layout.setContentsMargins(10, 8, 10, 8)
        slicer_analysis_details_layout.setSpacing(8)
        slicer_analysis_details_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )
        slicer_analysis_details_layout.addWidget(slicer_information)
        slicer_analysis_details_layout.addWidget(self.profile_origin_label)
        slicer_analysis_details_layout.addWidget(self.profile_diagnostics)
        # Embedded reconstruction remains independently expandable and starts
        # closed whenever a G-code is read.
        slicer_analysis_details_layout.addWidget(
            self.reconstructed_config_toggle
        )
        slicer_analysis_details_layout.addWidget(self.reconstructed_config_text)
        self.slicer_analysis_details.setWidget(
            self.slicer_analysis_details_content
        )
        self.slicer_analysis_details.hide()
        self.slicer_analysis_details_toggle.toggled.connect(
            self._toggle_slicer_analysis_details
        )
        # Supporting analysis data is available near the Slicer status, before
        # the primary selectors.  It no longer competes visually with the
        # confirmation button at the end of the form.
        slicer_details_index = slicer_layout.indexOf(self.slicer_columns)
        slicer_layout.insertWidget(
            slicer_details_index,
            self.slicer_analysis_details_toggle,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        slicer_layout.insertWidget(
            slicer_details_index + 1,
            self.slicer_analysis_details,
        )
        self.slicer_analysis_details_toggle.hide()
        self.slicer_analysis_details.hide()
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
        # Both preparation steps retain their established functional cards,
        # but receive an integrated step introduction instead of another
        # top-level card header.  The centred shell uses most of the available
        # width while remaining pleasantly bounded on very wide windows.
        self.preparation_tabs = _SequentialPreparationTabs(
            transition_duration_ms=400,
        )
        self.preparation_tabs.setObjectName("preparationSteps")
        self.preparation_tabs.set_step_guard(
            self._can_open_preparation_step
        )
        self.preparation_tabs.step_blocked.connect(
            self._on_preparation_step_blocked
        )
        # Document mode keeps the page pane flush with the custom navigation
        # that is inserted below the shared progress bar.
        self.preparation_tabs.setDocumentMode(True)
        self.preparation_tabs.setAccessibleName(
            "Schritte für Dateiübergabe und Slicer-Einstellungen"
        )
        preparation_tab_bar = self.preparation_tabs.tabBar()
        # The visible navigation is built below the global progress bar so it
        # can permanently contain each step's prerequisite list.  QTabWidget
        # remains the page controller, while its native one-line bar is hidden.
        preparation_tab_bar.hide()
        self.preparation_tabs.setProperty("stepTone", "source")
        self.preparation_tab_pages: list[QWidget] = []
        self.preparation_step_shells: list[QWidget] = []
        self.preparation_step_heading_labels: list[QLabel] = []
        self.preparation_step_state_labels: list[QLabel] = []
        self.preparation_step_left_pills: list[QLabel] = []
        self.preparation_step_right_pills: list[QLabel] = []
        self.preparation_step_intro_layouts: list[QGridLayout] = []
        for step_number, card, title, heading, description, step_tone in (
            (
                1,
                source_group,
                "1. Dateiübergabe",
                "Dateiübergabe",
                "",
                "source",
            ),
            (
                2,
                slicer_group,
                "2. Slicer-Einstellungen",
                "Slicer-Einstellungen",
                "",
                "slicer",
            ),
        ):
            page = QWidget()
            page.setObjectName("preparationStepPage")
            page.setProperty("stepTone", step_tone)
            page.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            page_layout = QHBoxLayout(page)
            # The navigation row directly above already contributes the
            # desired 10 px gap.  Match that value below the buttons as well.
            page_layout.setContentsMargins(24, 10, 24, 20)
            page_layout.setSpacing(0)

            step_shell = QWidget()
            step_shell.setObjectName("preparationStepShell")
            step_shell.setMaximumWidth(700)
            step_shell.setProperty("stepTone", step_tone)
            step_shell.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            step_layout = QVBoxLayout(step_shell)
            step_layout.setContentsMargins(0, 0, 0, 0)
            step_layout.setSpacing(12)
            step_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            step_intro = QFrame()
            step_intro.setObjectName("preparationStepIntro")
            step_intro_layout = QGridLayout(step_intro)
            step_intro_layout.setContentsMargins(2, 0, 2, 0)
            step_intro_layout.setHorizontalSpacing(12)
            step_intro_layout.setVerticalSpacing(0)
            step_intro_layout.setColumnMinimumWidth(0, 168)
            step_intro_layout.setColumnStretch(1, 1)
            step_intro_layout.setColumnMinimumWidth(2, 168)
            step_eyebrow = QLabel(f"SCHRITT {step_number}")
            step_eyebrow.setObjectName("preparationStepEyebrow")
            step_eyebrow.setFixedHeight(26)
            step_eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_copy = QWidget()
            step_copy.setObjectName("preparationStepCopy")
            step_copy.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            step_copy_layout = QVBoxLayout(step_copy)
            step_copy_layout.setContentsMargins(0, 0, 0, 0)
            step_copy_layout.setSpacing(2)
            step_heading = QLabel(heading)
            step_heading.setObjectName("preparationStepHeading")
            step_heading.setWordWrap(True)
            step_heading.setAlignment(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignVCenter
            )
            step_heading.setMinimumWidth(0)
            step_heading.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            step_description = QLabel(description)
            step_description.setObjectName("preparationStepDescription")
            step_description.setWordWrap(True)
            step_description.setAlignment(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignVCenter
            )
            step_description.setMinimumWidth(0)
            step_description.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            step_copy_layout.addWidget(step_heading)
            step_copy_layout.addWidget(step_description)
            step_state = QLabel(
                "Bereit für STL" if step_number == 1 else "Wird vorbereitet"
            )
            step_state.setObjectName("preparationStepState")
            step_state.setProperty("state", "pending")
            step_state.setFixedHeight(26)
            step_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_intro_layout.addWidget(
                step_eyebrow,
                0,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )
            step_intro_layout.addWidget(step_copy, 0, 1)
            step_intro_layout.addWidget(
                step_state,
                0,
                2,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            )
            # The common three-column navigation row owns the visible title.
            # Keep these handles only for API compatibility with older UI
            # integrations; the redundant "SCHRITT 1/2" block is not shown.
            step_layout.addWidget(step_intro)
            step_intro.hide()

            card.setProperty("embeddedStep", True)
            card.setProperty("stepTone", step_tone)
            card.header.hide()
            card.body_divider.hide()
            card.setMaximumWidth(16777215)
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            step_layout.addWidget(card)
            page_layout.addStretch(1)
            page_layout.addWidget(
                step_shell,
                16,
                Qt.AlignmentFlag.AlignTop,
            )
            page_layout.addStretch(1)
            self.preparation_tabs.addTab(page, title)
            self.preparation_tab_pages.append(page)
            self.preparation_step_shells.append(step_shell)
            self.preparation_step_heading_labels.append(step_heading)
            self.preparation_step_state_labels.append(step_state)
            self.preparation_step_left_pills.append(step_eyebrow)
            self.preparation_step_right_pills.append(step_state)
            self.preparation_step_intro_layouts.append(step_intro_layout)
        self.preparation_tabs.setCurrentIndex(0)
        self.preparation_tabs.set_transition_targets(
            tuple(self.preparation_step_shells),
            self._refresh_preparation_section_layout,
        )

        self.preparation_overview = QWidget()
        self.preparation_overview.setObjectName("preparationOverview")
        # Match the page's 24 px side insets plus the 700 px white content
        # card.  Navigation, connector, and progress therefore align exactly
        # with the active card at every responsive width.
        self.preparation_overview.setMaximumWidth(748)
        self.preparation_overview.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Maximum,
        )
        preparation_overview_layout = QVBoxLayout(self.preparation_overview)
        preparation_overview_layout.setContentsMargins(24, 14, 24, 0)
        preparation_overview_layout.setSpacing(10)
        preparation_overview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.preparation_progress_header = QWidget()
        self.preparation_progress_header.setObjectName(
            "preparationProgressHeader"
        )
        self.preparation_progress_header.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        preparation_progress_header_layout = QHBoxLayout(
            self.preparation_progress_header
        )
        preparation_progress_header_layout.setContentsMargins(0, 0, 0, 0)
        preparation_progress_header_layout.setSpacing(12)
        self.preparation_progress_title_label = QLabel(
            "Fortschritt der Vorbereitungen"
        )
        self.preparation_progress_title_label.setObjectName(
            "preparationProgressTitle"
        )
        self.preparation_progress_status_label = QLabel(
            "Schritt 1 von 2 · Dateiübergabe"
        )
        self.preparation_progress_status_label.setObjectName(
            "preparationProgressStatus"
        )
        self.preparation_progress_status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        preparation_progress_header_layout.addWidget(
            self.preparation_progress_title_label
        )
        preparation_progress_header_layout.addStretch(1)
        preparation_progress_header_layout.addWidget(
            self.preparation_progress_status_label
        )
        self.preparation_progress_bar = QProgressBar()
        self.preparation_progress_bar.setObjectName(
            "preparationProgressBar"
        )
        self.preparation_progress_bar.setRange(0, 100)
        self.preparation_progress_bar.setValue(0)
        self.preparation_progress_bar.setFormat("%p %")
        self.preparation_progress_bar.setTextVisible(True)
        self.preparation_progress_bar.setAccessibleName(
            "Gesamtfortschritt der Vorbereitung"
        )
        preparation_overview_layout.addWidget(
            self.preparation_progress_header
        )
        preparation_overview_layout.addWidget(
            self.preparation_progress_bar
        )
        self.preparation_requirements = ResponsiveCardGrid(
            # Wizard tabs always remain one equal-width row, including at the
            # narrowest supported main-window size.
            breakpoint_px=0,
            horizontal_spacing_px=0,
            vertical_spacing_px=0,
        )
        self.preparation_requirements.setObjectName("preparationRequirements")
        self.preparation_source_requirements = _PreparationRequirementsPanel()
        self.preparation_source_requirements.setObjectName(
            "preparationSourceRequirements"
        )
        self.preparation_source_requirements.setProperty("active", True)
        self.preparation_source_requirements.setAccessibleName(
            "Voraussetzungen für die STL-Datei"
        )
        source_requirements_layout = QGridLayout(
            self.preparation_source_requirements
        )
        self.preparation_slicer_requirements = _PreparationRequirementsPanel()
        self.preparation_slicer_requirements.setObjectName(
            "preparationSlicerRequirements"
        )
        self.preparation_slicer_requirements.setProperty("active", False)
        self.preparation_slicer_requirements.setAccessibleName(
            "Voraussetzungen für Slicer und Profile"
        )
        slicer_requirements_layout = QGridLayout(
            self.preparation_slicer_requirements
        )
        for requirements_layout in (
            source_requirements_layout,
            slicer_requirements_layout,
        ):
            requirements_layout.setContentsMargins(0, 0, 0, 0)
            requirements_layout.setHorizontalSpacing(8)
            requirements_layout.setVerticalSpacing(3)
            requirements_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.preparation_requirement_rows: dict[str, tuple[QLabel, QLabel]] = {}
        source_requirement_texts = (
            ("source_selected", "STL-Datei übergeben"),
            ("source_validated", "STL-Geometrie geprüft"),
        )
        slicer_requirement_texts = (
            ("slicer_detected", "Verwendbarer Slicer erkannt"),
            ("profiles_loaded", "Zugehörige Profile geladen"),
            ("profiles_confirmed", "Slicer- und Profilauswahl bestätigt"),
            ("preslice_completed", "Pre-Slice erfolgreich durchgeführt"),
            (
                "model_analyzed",
                "Modell mit bestätigten Profilen analysiert",
            ),
        )
        for requirements_layout, requirement_texts in (
            (source_requirements_layout, source_requirement_texts),
            (slicer_requirements_layout, slicer_requirement_texts),
        ):
            for row, (key, text_value) in enumerate(requirement_texts):
                icon_label = QLabel("○")
                icon_label.setObjectName("preparationRequirementIcon")
                icon_label.setProperty("state", "missing")
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_label.setFixedWidth(18)
                text_label = QLabel(text_value)
                text_label.setObjectName("preparationRequirementText")
                text_label.setWordWrap(True)
                text_label.setProperty("state", "missing")
                requirements_layout.addWidget(icon_label, row, 0)
                requirements_layout.addWidget(text_label, row, 1)
                self.preparation_requirement_rows[key] = (
                    icon_label,
                    text_label,
                )
            requirements_layout.setColumnStretch(1, 1)

        self.preparation_source_divider = QFrame()
        self.preparation_source_divider.setObjectName(
            "preparationContentDivider"
        )
        self.preparation_source_divider.setFixedHeight(1)
        self.preparation_slicer_divider = QFrame()
        self.preparation_slicer_divider.setObjectName(
            "preparationContentDivider"
        )
        self.preparation_slicer_divider.setFixedHeight(1)
        # Status belongs to the step it describes: compact checklist first,
        # separator second, established functional controls underneath.
        source_layout.insertWidget(0, self.preparation_source_requirements)
        source_layout.insertWidget(1, self.preparation_source_divider)
        slicer_layout.insertWidget(0, self.preparation_slicer_requirements)
        slicer_layout.insertWidget(1, self.preparation_slicer_divider)
        self.preparation_step_selectors: list[_PreparationStepSelector] = []
        self.preparation_step_selector_containers: list[QWidget] = []
        self.preparation_step_selector_icons: list[QLabel] = []
        self.preparation_step_selector_titles: list[QLabel] = []
        for index, title, tone, requirements_widget in (
            (
                0,
                "1. Dateiübergabe",
                "source",
                self.preparation_source_requirements,
            ),
            (
                1,
                "2. Slicer-Einstellungen",
                "slicer",
                self.preparation_slicer_requirements,
            ),
        ):
            selector_container = QWidget()
            selector_container.setObjectName(
                "preparationStepSelectorContainer"
            )
            selector_container.setProperty("stepTone", tone)
            selector_container.setProperty("active", index == 0)
            selector_container.setProperty("complete", False)
            selector_container.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            selector_container_layout = QVBoxLayout(selector_container)
            selector_container_layout.setContentsMargins(0, 0, 0, 0)
            selector_container_layout.setSpacing(0)
            selector = _PreparationStepSelector()
            selector.setObjectName("preparationStepSelector")
            selector.setProperty("stepTone", tone)
            selector.setProperty("complete", False)
            selector.setCheckable(True)
            selector.setAutoExclusive(True)
            selector.setAccessibleName(title)
            selector.setToolTip(f"{title} öffnen")
            selector.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            selector.setFixedHeight(48)
            selector_layout = QVBoxLayout(selector)
            selector_layout.setContentsMargins(0, 0, 0, 0)
            selector_layout.setSpacing(0)
            selector_title_row = QWidget()
            selector_title_row.setObjectName("preparationStepSelectorTitleRow")
            selector_title_layout = QHBoxLayout(selector_title_row)
            selector_title_layout.setContentsMargins(16, 7, 16, 7)
            selector_title_layout.setSpacing(6)
            selector_icon = QLabel("")
            selector_icon.setObjectName("preparationStepSelectorIcon")
            selector_icon.setProperty("state", "pending")
            selector_icon.setFixedWidth(18)
            selector_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            selector_title = QLabel(title)
            selector_title.setObjectName("preparationStepSelectorTitle")
            selector_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            selector_title.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
            selector_title_layout.addStretch(1)
            selector_title_layout.addWidget(selector_icon)
            selector_title_layout.addWidget(selector_title)
            selector_title_layout.addStretch(1)
            selector_layout.addWidget(selector_title_row)
            selector.progress_label.raise_()
            for passive_widget in (
                selector_title_row,
                *selector_title_row.findChildren(QWidget),
            ):
                passive_widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                    True,
                )
            selector.clicked.connect(
                lambda _checked=False, target=index: (
                    self.preparation_tabs.setCurrentIndex(target)
                )
            )
            selector.hover_changed.connect(
                lambda hovered, target=index: (
                    self._set_preparation_step_hovered(target, hovered)
                )
            )
            requirements_widget.setAccessibleDescription(
                f"Status und Voraussetzungen für {title}"
            )
            for passive_widget in requirements_widget.findChildren(QWidget):
                passive_widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                    True,
                )
            selector_container_layout.addWidget(selector)
            self.preparation_step_selectors.append(selector)
            self.preparation_step_selector_containers.append(
                selector_container
            )
            self.preparation_step_selector_icons.append(selector_icon)
            self.preparation_step_selector_titles.append(selector_title)
        self.preparation_step_selectors[0].setChecked(True)
        self.preparation_step_selectors[0].setProperty("active", True)
        self.preparation_step_selectors[1].setProperty("active", False)
        self.preparation_step_connector = QLabel("›››")
        self.preparation_step_connector.setObjectName(
            "preparationStepConnector"
        )
        self.preparation_step_connector.setProperty("state", "locked")
        self.preparation_step_connector.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preparation_step_connector.setFixedWidth(48)
        self.preparation_step_connector.setAccessibleName(
            "Schrittfolge von Dateiübergabe zu Slicer-Einstellungen"
        )
        # Compatibility handle for integrations that inspect the former
        # connector. The new tabs meet directly and need no middle glyph.
        self.preparation_step_connector.hide()
        self.preparation_requirements.add_pair(
            self.preparation_step_selector_containers[0],
            self.preparation_step_selector_containers[1],
            equal_height=True,
        )
        preparation_overview_layout.addWidget(self.preparation_requirements)

        self.preparation_navigation = QWidget()
        self.preparation_navigation.setObjectName("preparationNavigation")
        preparation_navigation_layout = QGridLayout(
            self.preparation_navigation
        )
        preparation_navigation_layout.setContentsMargins(0, 2, 0, 0)
        preparation_navigation_layout.setHorizontalSpacing(12)
        preparation_navigation_layout.setVerticalSpacing(0)
        for column in range(3):
            preparation_navigation_layout.setColumnStretch(column, 1)

        self.preparation_back_button = QPushButton("Zurück")
        self.preparation_back_button.setObjectName(
            "preparationBackButton"
        )
        self.preparation_back_button.setProperty("navigationTone", "back")
        self.preparation_back_button.setAccessibleName(
            "Zurück zur Dateiübergabe"
        )
        self.preparation_back_button.clicked.connect(
            lambda: self.preparation_tabs.setCurrentIndex(0)
        )
        preparation_navigation_layout.addWidget(
            self.preparation_back_button,
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        self.preparation_navigation_title_label = QLabel("Dateiübergabe")
        self.preparation_navigation_title_label.setObjectName(
            "preparationNavigationTitle"
        )
        self.preparation_navigation_title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        preparation_navigation_layout.addWidget(
            self.preparation_navigation_title_label,
            0,
            1,
        )

        preparation_next_host = QWidget()
        preparation_next_host.setObjectName("preparationNextHost")
        preparation_next_layout = QHBoxLayout(preparation_next_host)
        preparation_next_layout.setContentsMargins(0, 0, 0, 0)
        preparation_next_layout.setSpacing(0)
        preparation_next_layout.addStretch(1)
        self.preparation_next_button = QPushButton("Weiter 🔒")
        self.preparation_next_button.setObjectName("preparationNextButton")
        self.preparation_next_button.setProperty("ready", False)
        self.preparation_next_button.setEnabled(False)
        self.preparation_next_button.setToolTip(_LOCKED_SLICER_STEP_TOOLTIP)
        self.preparation_next_button.clicked.connect(
            lambda: self.preparation_tabs.setCurrentIndex(1)
        )
        preparation_next_layout.addWidget(self.preparation_next_button)
        self.preparation_finish_button = QPushButton("Fertig 🔒")
        self.preparation_finish_button.setObjectName(
            "preparationFinishButton"
        )
        self.preparation_finish_button.setProperty("ready", False)
        self.preparation_finish_button.setEnabled(False)
        self.preparation_finish_button.setToolTip(
            "Die Vorbereitung ist noch nicht vollständig abgeschlossen."
        )
        self.preparation_finish_button.clicked.connect(
            self._finish_preparation
        )
        self.preparation_finish_button.hide()
        preparation_next_layout.addWidget(self.preparation_finish_button)
        preparation_navigation_layout.addWidget(
            preparation_next_host,
            0,
            2,
        )
        # Domain-oriented aliases keep the intent obvious to callers.
        self.preparation_continue_button = self.preparation_next_button
        self.preparation_title_label = self.preparation_navigation_title_label
        preparation_overview_layout.addWidget(self.preparation_navigation)
        self.preparation_overview_host = QWidget()
        self.preparation_overview_host.setObjectName(
            "preparationOverviewHost"
        )
        self.preparation_overview_host.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Maximum,
        )
        preparation_overview_host_layout = QHBoxLayout(
            self.preparation_overview_host
        )
        preparation_overview_host_layout.setContentsMargins(0, 0, 0, 0)
        preparation_overview_host_layout.setSpacing(0)
        preparation_overview_host_layout.addStretch(1)
        preparation_overview_host_layout.addWidget(
            self.preparation_overview,
            16,
        )
        preparation_overview_host_layout.addStretch(1)
        workflow_group.content_layout.addWidget(self.preparation_overview_host)
        workflow_group.content_layout.addWidget(self.preparation_tabs)
        self.content_layout.addWidget(workflow_group)

        timing_group = SectionCard(
            "Layerzeit",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.timing_group = timing_group
        timing_group.setProperty("role", "timing")
        timing_group.setProperty("outerDropdown", True)
        timing_group.setProperty("bodyHover", False)
        timing_layout = timing_group.content_layout
        self.target_time_spin = self._double_spin(
            5.0,
            MAXIMUM_TARGET_LAYER_TIME_S,
            2,
            0.1,
            "targetLayerTime",
        )
        self.target_time_spin.set_display_decimals(1)
        self.target_time_spin.setProperty("rangeLabelShowMinimum", True)
        self.layer_time_tolerance_spin = self._double_spin(0.1, 3.0, 2, 0.01, "layerTimeTolerance")
        self.layer_time_tolerance_spin.setParent(self)
        self.layer_time_tolerance_spin.hide()
        self.layer_time_tolerance_spin.valueChanged.connect(self._on_value_changed)
        target_setting = self._add_numeric_setting(
            timing_layout,
            "target_layer_time_s",
            "Gewünschte Mindest-Layerzeit",
            self.target_time_spin,
        )
        self.full_infill_checkbox = QCheckBox(
            "100% Turmfüllung simulieren"
        )
        self.full_infill_checkbox.setObjectName("simulateFullTowerInfill")
        self.full_infill_checkbox.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.full_infill_checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        full_infill_row = QWidget()
        full_infill_layout = QHBoxLayout(full_infill_row)
        full_infill_layout.setContentsMargins(0, 2, 0, 2)
        full_infill_layout.setSpacing(METRICS.setting_info_text_gap_px)
        self.full_infill_info_button = InfoToolButton(
            FULL_INFILL_HINT_HTML,
            full_infill_row,
            accessible_name="Informationen zur 100-%-Turmfüllung",
            accessible_hint=FULL_INFILL_HINT_ACCESSIBLE,
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        full_infill_layout.addWidget(
            self.full_infill_info_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        full_infill_layout.addWidget(
            self.full_infill_checkbox,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        full_infill_layout.addStretch(1)
        timing_layout.addWidget(full_infill_row)
        self.simulate_tower_without_supports_checkbox = QCheckBox(
            "Deaktivierte Turmstützen simulieren"
        )
        self.simulate_tower_without_supports_checkbox.setObjectName(
            "simulateTowerWithoutSupports"
        )
        self.simulate_tower_without_supports_checkbox.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.simulate_tower_without_supports_checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        support_row = QWidget()
        support_layout = QHBoxLayout(support_row)
        support_layout.setContentsMargins(0, 2, 0, 2)
        support_layout.setSpacing(METRICS.setting_info_text_gap_px)
        self.simulate_tower_without_supports_info_button = InfoToolButton(
            TOWER_SUPPORT_HINT_HTML,
            support_row,
            accessible_name="Informationen zur Stützen-Simulation",
            accessible_hint=TOWER_SUPPORT_HINT_ACCESSIBLE,
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        support_layout.addWidget(self.simulate_tower_without_supports_info_button)
        support_layout.addWidget(self.simulate_tower_without_supports_checkbox)
        support_layout.addStretch(1)
        timing_layout.addWidget(support_row)
        self.tower_need_label = QLabel(
            "Bitte zuerst eine STL-Datei auswählen."
        )
        self.tower_need_label.setObjectName("towerNeedLabel")
        self.tower_need_label.setWordWrap(True)
        self.tower_need_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.tower_need_label.setProperty("state", "pending")
        target_setting.layout().addWidget(self.tower_need_label, 3, 0, 1, 4)
        self.tower_need_label.hide()
        self.content_layout.addWidget(timing_group)

        geometry_group = SectionCard(
            "Erweiterte Turmeinstellungen",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.geometry_group = geometry_group
        geometry_layout = geometry_group.content_layout
        self.geometry_fields_layout = geometry_layout
        self.minimum_outer_spin = self._double_spin(
            3.0, 40.0, 3, 1.0, "minimumOuterDiameter"
        )
        self.minimum_outer_spin.set_display_decimals(1)
        self.minimum_outer_spin.setProperty("rangeLabelShowMinimum", True)
        self.maximum_outer_spin = self._double_spin(
            5.0, 100.0, 3, 1.0, "maximumOuterDiameter"
        )
        self.maximum_outer_spin.set_display_decimals(1)
        self.maximum_outer_spin.setProperty("rangeLabelShowMinimum", True)
        self._add_numeric_setting(
            geometry_layout,
            "minimum_outer_diameter_mm",
            "Minimaler Turmdurchmesser",
            self.minimum_outer_spin,
        )
        self._add_numeric_setting(
            geometry_layout,
            "maximum_outer_diameter_mm",
            "Maximaler Turmdurchmesser",
            self.maximum_outer_spin,
        )
        self.layer_range_button = QPushButton("Bereichseditor öffnen")
        self.layer_range_button.setObjectName("layerRangeToolButton")
        self.layer_range_button.setFixedHeight(METRICS.info_button_diameter_px)
        self.layer_range_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.layer_range_button.clicked.connect(self.show_layer_range_tool)
        self.layer_range_button_row = QWidget()
        range_button_layout = QHBoxLayout(self.layer_range_button_row)
        range_button_layout.setContentsMargins(0, 0, 0, 0)
        range_button_layout.setSpacing(METRICS.setting_info_text_gap_px)
        self.layer_range_info_button = InfoToolButton(
            "<b>Was macht dieses Werkzeug?</b><p>"
            "&#8226; Mit diesem Werkzeug kannst du Bereiche bestimmen, in denen der Turm jegliche Layerzeit-Defizite ignoriert<br>"
            "&#8226; Der minimale Turmdurchmesser kann dadurch nicht unterschritten werden</p>",
            accessible_name="Informationen zum Bereichseditor",
            accessible_hint=("Was macht dieses Werkzeug?\n"
                "• Mit diesem Werkzeug kannst du Bereiche bestimmen, in denen der Turm jegliche Layerzeit-Defizite ignoriert\n"
                "• Der minimale Turmdurchmesser kann dadurch nicht unterschritten werden"),
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        range_button_layout.addWidget(self.layer_range_info_button, 0, Qt.AlignmentFlag.AlignVCenter)
        range_button_layout.addWidget(self.layer_range_button, 0)
        self.layer_range_summary = QLabel()
        self.layer_range_summary.setWordWrap(False)
        range_button_layout.addWidget(self.layer_range_summary, 0, Qt.AlignmentFlag.AlignVCenter)
        range_button_layout.addStretch(1)
        self._refresh_layer_range_tool()
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
        self.automatic_base_checkbox.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.automatic_base_checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.automatic_base_checkbox.setFixedHeight(
            METRICS.form_control_height_px
        )
        self.automatic_base_error_label = QLabel()
        self.automatic_base_error_label.setObjectName("settingMessage")
        self.automatic_base_error_label.setWordWrap(True)
        self.automatic_base_error_label.hide()
        self.manual_base_width_spin = self._double_spin(
            MINIMUM_BASE_WIDTH_MM,
            MAXIMUM_BASE_WIDTH_MM,
            2,
            1.0,
            "manualBaseWidth",
        )
        self.manual_base_width_spin.setProperty(
            "rangeLabelShowMinimum", True
        )
        self.manual_base_width_spin.setProperty(
            "rangeLabelIntegerBounds", True
        )
        self.manual_base_width_spin.setProperty(
            "resetCompareDisplayedValue", True
        )
        self.automatic_base_width_label = QLabel(
            "Automatische Breite: 25,00 bis höchstens 80,00 mm", self
        )
        self.automatic_base_width_label.setObjectName("calculatedHint")
        self.automatic_base_width_label.setWordWrap(True)
        self.minimum_base_spin = self._double_spin(
            0.0, 500.0, 3, 0.5, "minimumBaseRadius"
        )
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
        manual_base_setting = self._add_numeric_setting(
            stability_fields_layout,
            "manual_base_width_mm",
            "Standfußbreite",
            self.manual_base_width_spin,
            info_text=_automatic_base_hint()[0],
        )
        self.manual_base_width_setting = manual_base_setting
        manual_base_setting.default_provider = self._automatic_base_width_mm
        manual_base_setting.label.hide()
        manual_base_setting.layout().removeWidget(manual_base_setting.label)
        manual_base_setting.layout().addWidget(
            self.automatic_base_checkbox,
            0,
            1,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignAbsolute
            | Qt.AlignmentFlag.AlignVCenter,
        )
        self.automatic_base_checkbox.setAccessibleName(
            "Standfußbreite automatisch berechnen"
        )
        self.automatic_base_info_button = manual_base_setting.info_button
        self.automatic_base_info_button.setAccessibleName(
            "Informationen zur automatischen und manuellen Standfußbreite"
        )
        base_hint, accessible_base_hint = _automatic_base_hint()
        self.automatic_base_info_button.set_hint(
            base_hint, accessible_hint=accessible_base_hint
        )
        manual_base_setting.layout().addWidget(
            self.automatic_base_error_label,
            3,
            0,
            1,
            4,
        )
        # Compatibility alias: the reset now shares the single checkbox and
        # width row, as it does for all other numeric settings.
        self.automatic_base_reset_button = manual_base_setting.reset_button
        self.automatic_base_width_label.hide()
        base_height_hint = QLabel("Standfußhöhe: 1 Layer; anschließend mindestens 6 mm oder 22 Layer Verjüngung (der längere Wert gilt), soweit der Turm hoch genug ist.", self)
        base_height_hint.setObjectName("calculatedHint")
        base_height_hint.setWordWrap(True)
        base_height_hint.hide()
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
            "Maximaler Aufweitungswinkel",
            self.maximum_expansion_angle_spin,
        )
        self._add_numeric_setting(
            overhang_layout,
            "maximum_contraction_angle_deg",
            "Maximaler Verjüngungswinkel",
            self.maximum_contraction_angle_spin,
        )
        overhang_group.refresh_collapsed_state()
        self.content_layout.addWidget(overhang_group)

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
        options_title = QLabel("Exportordner ändern")
        options_title.setObjectName("dialogTitle")
        options_layout.addWidget(options_title)

        output_path_layout = QGridLayout()
        output_path_layout.setHorizontalSpacing(METRICS.setting_info_text_gap_px)
        self.output_root_info_button = InfoToolButton(
            "Basisordner für Zeitstempel-Unterordner, STL-Dateien, Berichte "
            "und Fehlerprotokolle. Vorhandene Ausgabedateien werden nicht "
            "überschrieben.",
            self.additional_options_content,
            accessible_name="Informationen zum aktuellen Exportordner",
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
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
            "Exportordner auf Standardwert zurücksetzen"
        )
        self.output_root_reset_button.setAccessibleName(
            "Exportordner auf Standardwert zurücksetzen"
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
        options_layout.addWidget(QLabel("Aktueller Exportordner:"))
        options_layout.addLayout(output_path_layout)
        self.prediction_frame = SectionCard(
            "Generierung und Vorschau",
            collapsible=True,
            expanded=True,
            state=SectionState.PREVIEW,
        )
        self.prediction_frame.setProperty("role", "prediction")
        self.prediction_frame.setProperty("cardTone", "preview")
        self.prediction_frame.setProperty("outerDropdown", True)
        self.prediction_frame.setProperty("bodyHover", False)
        prediction_layout = self.prediction_frame.content_layout
        self.prediction_method_label = QLabel("Noch nicht verfügbar")
        self.prediction_method_label.setObjectName("predictionMethodBadge")
        self.prediction_method_label.setProperty("mode", "pending")
        self.prediction_label = QLabel(
            "Die Schätzung ist nach der Quellen- und Geometrieanalyse verfügbar."
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

        prediction_grid.setColumnStretch(0, 3)
        prediction_grid.setColumnStretch(1, 2)
        self.prediction_grid = prediction_grid
        self.prediction_primary_widget = QWidget(self)
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

        self.prediction_primary_widget.hide()
        self.tower_need_label.hide()
        self.generation_intro_label = QLabel(
            "Noch kein Kühlturm generiert. Starten Sie die Generierung, "
            "um den Fortschritt und das Ergebnis hier zu sehen."
        )
        self.generation_intro_label.setObjectName("generationIntroLabel")
        self.generation_intro_label.setWordWrap(True)
        prediction_layout.addWidget(self.generation_intro_label)
        prediction_layout.addWidget(self.joint_generation_dialog)
        self.prediction_preview_divider = QFrame()
        self.prediction_preview_divider.setObjectName("predictionPreviewDivider")
        self.prediction_preview_divider.setFrameShape(QFrame.Shape.HLine)
        self.prediction_preview_divider.setFixedHeight(1)
        prediction_layout.addWidget(self.prediction_preview_divider)
        self.preview_hint_label = QLabel()
        self.preview_hint_label.setObjectName("previewHintLabel")
        self.preview_hint_label.setWordWrap(True)
        self.preview_hint_label.hide()
        prediction_layout.addWidget(self.preview_hint_label)
        self._preview_dialog = PreviewDialog(
            self.prediction_frame.content_widget,
            embedded=True,
        )
        self._preview_dialog.layout_changed.connect(
            self._refresh_ready_grid_layout
        )
        self._preview_dialog.canvas.apply_camera_state(
            self._pending_preview_camera_state
        )
        prediction_primary_layout.addWidget(
            self._preview_dialog.quality_widget
        )
        prediction_layout.addWidget(self._preview_dialog)
        self._preview_dialog.show()
        options_actions = QHBoxLayout()
        options_actions.addStretch(1)
        self.additional_options_close_button = QPushButton("Schließen")
        self.additional_options_close_button.clicked.connect(
            self._close_additional_options
        )
        options_actions.addWidget(self.additional_options_close_button)
        options_layout.addLayout(options_actions)
        # Timing and geometry share one collapsible card after preparation.
        # The advanced subsection collapses inside the outer settings card.
        self.geometry_settings_group = SectionCard(
            "Turmeinstellungen",
            collapsible=True,
            expanded=True,
            state=SectionState.NEUTRAL,
        )
        self.geometry_settings_group.setProperty("role", "geometrySettings")
        self.geometry_settings_group.setProperty("outerDropdown", True)
        self.geometry_settings_group.setProperty("bodyHover", False)
        self.geometry_settings_group.content_layout.setContentsMargins(
            0, 0, 0, 0
        )
        timing_group.setCheckable(False)
        timing_group.setProperty("headerless", True)
        timing_group.refresh_collapsed_state()
        timing_group.setProperty("outerDropdown", False)
        timing_group.setProperty("subsection", "single")
        stability_group.setCheckable(False)
        overhang_group.setCheckable(False)
        geometry_group.setProperty("subsection", "single")
        stability_group.setProperty("subsection", "single")
        overhang_group.setProperty("subsection", "single")
        self.geometry_split = QWidget()
        self.geometry_split.setObjectName("geometrySettingsSplit")
        self.geometry_split_layout = QVBoxLayout(self.geometry_split)
        self.geometry_split_layout.setContentsMargins(0, 0, 0, 0)
        self.geometry_split_layout.setSpacing(0)
        self.geometry_split_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Nach Dateiübergabe und Slicer folgt die eigentliche Arbeitsfläche: bei
        # genügend Platz zweispaltig, in schmalen Fenstern sauber gestapelt.
        for card in (
            timing_group,
            geometry_group,
            stability_group,
            overhang_group,
        ):
            self.content_layout.removeWidget(card)
        self.geometry_split_layout.addWidget(timing_group)
        self.geometry_split_layout.addWidget(geometry_group)
        for old_layout in (stability_fields_layout, overhang_layout, calculation_body_layout):
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget() is not None:
                    if item.widget() is self._setting_widgets["local_reference_window"]:
                        continue
                    geometry_layout.addWidget(item.widget())
        geometry_layout.addWidget(self.layer_range_button_row)
        stability_group.hide()
        overhang_group.hide()
        self.geometry_calculation_section.hide()
        self.geometry_settings_group.content_layout.addWidget(self.geometry_split)
        self.geometry_settings_group.toggled.connect(
            lambda expanded: self._sync_collapsible_content(
                "geometry_settings", expanded
            )
        )
        self.ready_grid = ResponsiveCardGrid()
        self.ready_grid.setObjectName("readySettingsGrid")
        self.ready_left_column = QWidget()
        self.ready_left_column.setObjectName("readyLeftColumn")
        ready_left_layout = QVBoxLayout(self.ready_left_column)
        ready_left_layout.setContentsMargins(0, 0, 0, 0)
        ready_left_layout.setSpacing(METRICS.card_spacing_px)
        ready_left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        ready_left_layout.addWidget(self.geometry_settings_group)
        self.ready_grid.add_pair(
            self.ready_left_column,
            self.prediction_frame,
            equal_height=False,
            stacked_right_first=True,
        )
        self.generation_workspace = QWidget()
        self.generation_workspace.setObjectName("generationWorkspace")
        self.generation_workspace.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        generation_layout = QVBoxLayout(self.generation_workspace)
        generation_layout.setContentsMargins(0, 0, 0, 0)
        generation_layout.setSpacing(METRICS.card_spacing_px)
        self.generation_method_navigation = QWidget()
        navigation_layout = QHBoxLayout(self.generation_method_navigation)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        self.generation_method_back_button = QPushButton("← Zur Methodenauswahl")
        self.generation_method_back_button.setObjectName("generationMethodBackButton")
        self.generation_method_back_button.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        self.generation_method_back_button.setToolTip(
            "Andere Methode wählen. Ihre Einstellungen und generierten Türme bleiben erhalten."
        )
        self.generation_method_back_button.clicked.connect(
            self.show_generation_method_selection
        )
        navigation_layout.addWidget(self.generation_method_back_button)
        self.generation_method_label = QLabel()
        self.generation_method_label.setObjectName("generationMethodLabel")
        self.generation_method_label.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
        navigation_layout.addWidget(self.generation_method_label)
        self.generation_method_recommendation = QLabel("(Zweispaltige Ansicht empfohlen - Fenster verbreitern)")
        self.generation_method_recommendation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generation_method_recommendation.setWordWrap(True)
        self.generation_method_recommendation.setStyleSheet("color: #b42318;")
        self.generation_method_recommendation.hide()
        navigation_layout.addWidget(self.generation_method_recommendation,1)
        navigation_layout.addStretch(1)
        generation_layout.addWidget(self.generation_method_navigation)
        self.generation_method_picker = QWidget()
        picker_layout = QVBoxLayout(self.generation_method_picker)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(16)
        self.generation_method_heading = QLabel("Wie soll der Kühlturm erstellt werden?")
        self.generation_method_heading.setObjectName("generationMethodHeading")
        self.generation_method_heading.setWordWrap(True)
        self.generation_method_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        picker_layout.addWidget(self.generation_method_heading)
        self.generation_method_grid = GenerationModeGrid()
        self.automatic_generation_card = GenerationModeCard(
            "Automatisch",
            "Der Kühlturm wird passend zum Kühlbedarf Ihres Modells berechnet "
            "und schrittweise an die gewünschte Layerzeit angepasst.",
            "Automatische Erstellung öffnen →",
        )
        self.manual_generation_card = GenerationModeCard(
            "Manuell",
            "Die Turmform selbst festlegen und anschließend prüfen, "
            "welche Layerzeiten das Modell mit diesem Kühlturm erreicht.",
            "Manuelle Erstellung öffnen →",
        )
        self.automatic_generation_card.setProperty("generationMode", "automatic")
        self.manual_generation_card.setProperty("generationMode", "manual")
        self.automatic_generation_card.clicked.connect(
            lambda: self.select_generation_mode(GenerationMode.AUTOMATIC)
        )
        self.manual_generation_card.clicked.connect(
            lambda: self.select_generation_mode(GenerationMode.MANUAL)
        )
        self.generation_method_grid.add_pair(
            self.automatic_generation_card, self.manual_generation_card
        )
        picker_layout.addWidget(
            self.generation_method_grid, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        generation_layout.addWidget(self.generation_method_picker)
        generation_layout.addWidget(self.ready_grid)
        self.manual_generation_panel = ManualGenerationPanel()
        self.manual_generation_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.manual_controller = ManualGenerationController(self, self.manual_generation_panel)
        generation_layout.addWidget(self.manual_generation_panel)
        self.content_layout.addWidget(self.generation_workspace)
        # Keep this workflow block pinned to the top when its final row is
        # expanded or collapsed.
        self.content_layout.setAlignment(
            self.generation_workspace,
            Qt.AlignmentFlag.AlignTop,
        )
        # The trailing stretch is enabled only after preparation. Before that,
        # the workflow card itself consumes the available viewport height.
        self.content_layout.addStretch(1)

        workflow_group.toggled.connect(
            self._refresh_preparation_section_layout
        )
        timing_group.toggled.connect(
            lambda _expanded: self._refresh_ready_grid_layout()
        )
        self.prediction_frame.toggled.connect(
            lambda _expanded: self._refresh_ready_grid_layout()
        )
        self.geometry_settings_group.toggled.connect(
            self._refresh_geometry_section_layout
        )
        geometry_group.toggled.connect(
            lambda _expanded: self._refresh_geometry_section_layout(
                self.geometry_settings_group.isChecked()
            )
        )

        workflow_widgets = (self.generation_workspace,)

        self.workflow = WorkflowController(
            source_card=source_group,
            slicer_card=slicer_group,
            workflow_card=workflow_group,
            downstream_widgets=workflow_widgets,
            parent=self,
            duration_ms=(
                0
                if os.environ.get("QT_QPA_PLATFORM", "").casefold()
                == "offscreen"
                else 500
            ),
            # The accepted card remains visible throughout the slide itself;
            # no additional pause is inserted before the 0.5 s transition.
            first_success_duration_ms=0,
            requires_explicit_completion=True,
        )
        self.preparation_tabs.currentChanged.connect(
            self._on_preparation_tab_changed
        )

        self.preview_button = QPushButton("Kühlturm generieren")
        self.preview_button.setObjectName("previewButton")
        self.preview_button.clicked.connect(
            self._on_generation_button_clicked
        )
        self.export_button = QPushButton("Kühlturm exportieren")
        self.export_button.setObjectName("exportButton")
        self.export_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._on_main_export_clicked)

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
        self.isolated_progress_widget = QWidget()
        self.isolated_progress_widget.setObjectName(
            "isolatedSliceProgress"
        )
        self.isolated_progress_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        isolated_progress_layout = QVBoxLayout(
            self.isolated_progress_widget
        )
        isolated_progress_layout.setContentsMargins(0, 0, 0, 0)
        isolated_progress_layout.setSpacing(6)
        self.isolated_progress_title_label = QLabel(
            "Turmgenerierung wird vorbereitet..."
        )
        self.isolated_progress_title_label.setObjectName(
            "preparationProgressTitle"
        )
        self.isolated_progress_bar = QProgressBar()
        self.isolated_progress_bar.setObjectName("preparationProgressBar")
        self.isolated_progress_bar.setRange(0, 100)
        self.isolated_progress_bar.setValue(0)
        self.isolated_progress_bar.setFormat("%p %")
        self.isolated_progress_bar.setAccessibleName(
            "Fortschritt der getrennten Kühlturm-Slices"
        )
        self.isolated_progress_detail_label = QLabel(
            "Die getrennte Turmoptimierung wird vorbereitet …"
        )
        self.isolated_progress_detail_label.setObjectName(
            "isolatedSliceProgressDetail"
        )
        self.isolated_progress_detail_label.setWordWrap(True)
        self.isolated_progress_detail_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        isolated_progress_layout.addWidget(self.isolated_progress_title_label)
        isolated_progress_layout.addWidget(self.isolated_progress_bar)
        isolated_progress_layout.addWidget(
            self.isolated_progress_detail_label
        )
        self.isolated_progress_widget.hide()
        self.status_label = QLabel("Bitte STL auswählen")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.status_icon_label = QLabel("⇧")
        self.status_icon_label.setObjectName("progressStatusIcon")
        self.status_icon_label.setProperty("prominent", True)
        self.result_label = QLabel("")
        self.result_label.setObjectName("resultLabel")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumWidth(0)
        self.result_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
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
            maximum_height=104,
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
            "Export/Vorschau nicht möglich: Bitte zuerst eine STL auswählen."
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
        self.open_output_button = QPushButton("Alle Exporte öffnen")
        self.open_output_button.setObjectName("openBaseOutputFolderButton")
        self.open_output_button.setToolTip(
            "Den Exportordner mit allen Exporten öffnen"
        )
        self.open_stl_button = QPushButton("Letzten Export öffnen")
        self.open_stl_button.setObjectName("openOutputFolderButton")
        self.open_stl_button.setAccessibleName(
            "Ordner des letzten Exports öffnen"
        )
        self.open_stl_button.setAttribute(
            Qt.WidgetAttribute.WA_AlwaysShowToolTips,
            True,
        )
        self.open_run_button = QPushButton("Letzten Exportbericht öffnen")
        self.open_run_button.setObjectName("openExportReportButton")
        self.open_run_button.setAccessibleName(
            "Letzten Exportbericht öffnen"
        )
        self.last_export_report_button = self.open_run_button
        self.open_output_button.setEnabled(False)
        self.open_stl_button.setEnabled(False)
        self._refresh_last_export_report_action()
        self.open_output_button.clicked.connect(self.open_output_directory)
        self.open_stl_button.clicked.connect(self.open_stl_directory)
        self.open_run_button.clicked.connect(self.show_last_export_report)
        self.open_run_button.hide()

        self.preview_action_control = QFrame()
        self.preview_action_control.setObjectName("previewActionControl")
        self.preview_action_control.setFixedWidth(
            PREVIEW_ACTION_COMPACT_WIDTH_PX
        )
        preview_action_layout = QVBoxLayout(self.preview_action_control)
        preview_action_layout.setContentsMargins(0, 0, 0, 0)
        preview_action_layout.setSpacing(0)
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
            self.open_run_button,
            0,
            2,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(
            self.preview_action_control,
            0,
            4,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.addWidget(
            self.export_button,
            0,
            5,
            Qt.AlignmentFlag.AlignBottom,
        )
        main_actions.setColumnStretch(3, 1)
        for column in (0, 1, 2, 4, 5):
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

        self.footer_message_area = QWidget()
        self.footer_message_area.setObjectName("footerMessageArea")
        self.footer_message_layout = QVBoxLayout(self.footer_message_area)
        self.footer_message_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_message_layout.setSpacing(8)
        self.footer_message_layout.addWidget(self.footer_messages_scroll)
        self.footer_message_layout.addStretch(1)
        self.footer_reset_host = QWidget()
        resets = QHBoxLayout(self.footer_reset_host)
        resets.setContentsMargins(0,0,0,0)
        resets.setSpacing(8)
        resets.addWidget(self.reset_button)
        self.tower_reset_button = QPushButton("Turmform zurücksetzen")
        self.tower_reset_button.setObjectName("towerResetButton")
        self.tower_reset_button.setToolTip("Manuelle Turmform mit den aktuellen Einstellungen zurücksetzen")
        self.tower_reset_button.setFixedHeight(METRICS.info_button_diameter_px)
        self.tower_reset_button.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        self.tower_reset_button.clicked.connect(lambda: self.manual_controller.panel.reset_tower())
        self.tower_reset_button.hide()
        resets.addWidget(self.tower_reset_button)
        resets.addStretch(1)
        self.footer_message_layout.addWidget(self.footer_reset_host)

        self.footer_action_area = QWidget()
        self.footer_action_area.setObjectName("footerActionArea")
        self.footer_action_layout = QVBoxLayout(self.footer_action_area)
        self.footer_action_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_action_layout.setSpacing(8)
        self.joint_generation_dialog.layout().insertWidget(1, self.isolated_progress_widget)
        self.footer_action_layout.addWidget(self.action_availability_widget)
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
        self.manual_controller.attach_footer()
        self.manual_generation_panel.layout_changed.connect(self._refresh_generation_method_label)

        self.automatic_base_checkbox.stateChanged.connect(
            self._on_base_mode_changed
        )
        self.full_infill_checkbox.toggled.connect(
            self._on_full_infill_changed
        )
        self.simulate_tower_without_supports_checkbox.toggled.connect(
            self._on_support_simulation_changed
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
        self.show_all_profiles_checkbox.toggled.connect(
            self._on_show_all_profiles_toggled
        )
        self.profile_confirm_button.clicked.connect(
            self.confirm_profile_selection
        )

    def _on_workflow_stage_changed(self, stage_value: str) -> None:
        """Show fixed footer actions only after both prerequisites succeeded."""

        preparation_ready = bool(
            stage_value == WorkflowStage.READY.value
            and getattr(self.workflow, "preparation_acknowledged", True)
        )
        if not preparation_ready:
            self.generation_mode = None
        self._refresh_generation_workspace(preparation_ready)
        actions_visible = preparation_ready and self.generation_mode in {GenerationMode.AUTOMATIC, GenerationMode.MANUAL}
        self._set_preparation_viewport_fill(not preparation_ready)
        if hasattr(self, "footer"):
            self.footer.setVisible(actions_visible)
        self._set_setting_feedback_enabled(actions_visible and self.generation_mode is GenerationMode.AUTOMATIC)
        for widget in (
            self.open_output_button,
            self.open_stl_button,
            self.reset_button,
            self.preview_action_control,
            self.preview_button,
            self.export_button,
        ):
            widget.setVisible(actions_visible)
        if not actions_visible and hasattr(self, "action_availability_widget"):
            self.export_availability_label.clear()
            self.action_availability_widget.hide()
        if actions_visible and self.generation_mode is GenerationMode.AUTOMATIC and hasattr(self, "geometry_settings_group"):
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
            if actions_visible and self.generation_mode is GenerationMode.AUTOMATIC:
                self.validate_form()
            else:
                self._apply_inline_errors({})
                self._refresh_collapsible_error_badges({})
                self.validation_label.clear()
                self._refresh_issue_panels()
        self._refresh_footer_auxiliary_visibility()
        self._schedule_footer_height_update()
        if self.generation_mode is GenerationMode.MANUAL:
            self.manual_controller.refresh()
            QTimer.singleShot(0,self.manual_controller.fit_editor_to_window)

    def _generation_method_change_available(self) -> bool:
        return not (
            self.background_job_manager.has_active(JobKind.PREVIEW)
            or self.background_job_manager.has_active(JobKind.EXPORT)
        )

    def select_generation_mode(self, mode: GenerationMode) -> None:
        mode = GenerationMode(mode)
        if not self._generation_method_change_available():
            return
        if (
            self.workflow.stage is not WorkflowStage.READY
            or not self.workflow.preparation_acknowledged
        ):
            return
        self.generation_mode = mode
        self._on_workflow_stage_changed(self.workflow.stage.value)
        if mode is GenerationMode.MANUAL:
            self.manual_controller.ensure_context()
            self.manual_controller.panel.select("")
        self._refresh_phase17_actions()

    def show_generation_method_selection(self) -> None:
        if not self._generation_method_change_available():
            return
        self.generation_mode = None
        self._on_workflow_stage_changed(self.workflow.stage.value)

    def _refresh_generation_workspace(self, preparation_ready: bool) -> None:
        selecting = self.generation_mode is None
        workspace_visible = preparation_ready
        source_ready = (self.workflow.stage is WorkflowStage.READY and self.workflow.preparation_acknowledged)
        self.generation_workspace.setVisible(workspace_visible)
        self.generation_method_picker.setVisible(workspace_visible and selecting)
        self.generation_method_navigation.setVisible(workspace_visible and not selecting)
        for card in (self.automatic_generation_card,self.manual_generation_card):
            card.setEnabled(source_ready)
            card.setToolTip("" if source_ready else "Zuerst Datei, Slicer und Druckprofile vorbereiten.")
        self.ready_grid.setVisible(source_ready and self.generation_mode is GenerationMode.AUTOMATIC)
        self.manual_generation_panel.setVisible(source_ready and self.generation_mode is GenerationMode.MANUAL)
        self._refresh_generation_method_label()
        self.generation_method_back_button.setEnabled(self._generation_method_change_available())

    def _refresh_generation_method_label(self,*_):
        manual = self.generation_mode is GenerationMode.MANUAL
        text = "Manuelle Turmerstellung" if manual else "Automatische Turmerstellung"
        self.generation_method_label.setText(text)
        narrow = manual and getattr(self.manual_controller.panel,"_narrow_layout",False)
        self.generation_method_recommendation.setVisible(narrow)
        self.generation_method_navigation.layout().setStretch(3,0 if narrow else 1)

    # The existing generator owns the automatic session even while its view
    # is hidden. Manual generation can use its own session and controls without
    # routing automatic callbacks into a different method's result.
    @property
    def current_preview(self) -> PreviewResult | None:
        return self.generation_sessions[GenerationMode.AUTOMATIC].preview

    @current_preview.setter
    def current_preview(self, value: PreviewResult | None) -> None:
        self.generation_sessions[GenerationMode.AUTOMATIC].preview = value

    @property
    def preview_state(self) -> PreviewState:
        return self.generation_sessions[GenerationMode.AUTOMATIC].preview_state

    @preview_state.setter
    def preview_state(self, value: PreviewState) -> None:
        self.generation_sessions[GenerationMode.AUTOMATIC].preview_state = value

    @property
    def last_export_result(self) -> PreviewExportResult | None:
        return self.generation_sessions[GenerationMode.AUTOMATIC].export_result

    @last_export_result.setter
    def last_export_result(self, value: PreviewExportResult | None) -> None:
        self.generation_sessions[GenerationMode.AUTOMATIC].export_result = value

    @property
    def _last_exported_preview_identity(self) -> tuple[str, str | None] | None:
        return self.generation_sessions[GenerationMode.AUTOMATIC].exported_preview_identity

    @_last_exported_preview_identity.setter
    def _last_exported_preview_identity(self, value: tuple[str, str | None] | None) -> None:
        self.generation_sessions[GenerationMode.AUTOMATIC].exported_preview_identity = value

    def _set_preparation_viewport_fill(self, enabled: bool) -> None:
        """Fill the usable scroll viewport while preparation is unfinished."""

        vertical_policy = (
            QSizePolicy.Policy.Expanding
            if enabled
            else QSizePolicy.Policy.Preferred
        )
        self.workflow_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            vertical_policy,
        )
        self.workflow_group.content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            vertical_policy,
        )
        workflow_index = self.content_layout.indexOf(self.workflow_group)
        if workflow_index >= 0:
            self.content_layout.setStretch(
                workflow_index,
                1 if enabled else 0,
            )
        # The final layout item is the deliberately retained trailing stretch.
        # It takes over only when the preparation card no longer owns the page.
        trailing_index = self.content_layout.count() - 1
        if trailing_index >= 0:
            self.content_layout.setStretch(
                trailing_index,
                0 if enabled else 1,
            )
        self.content_layout.invalidate()
        self.workflow_group.updateGeometry()
        self._refresh_settings_content_minimum_height()
        QTimer.singleShot(0, self._refresh_settings_content_minimum_height)

    def _on_preparation_tab_changed(self, index: int) -> None:
        """Reveal Slicer feedback only when its named step becomes relevant."""

        tones = ("source", "slicer")
        if 0 <= index < len(tones):
            self.preparation_tabs.setProperty("stepTone", tones[index])
            self._refresh_widget_style(self.preparation_tabs)
        for selector_index, selector in enumerate(
            getattr(self, "preparation_step_selectors", ())
        ):
            active = selector_index == index
            selector.setChecked(active)
            selector.setProperty("active", active)
            self._refresh_widget_style(selector)
            containers = getattr(
                self, "preparation_step_selector_containers", ()
            )
            if selector_index < len(containers):
                containers[selector_index].setProperty("active", active)
                self._refresh_widget_style(containers[selector_index])
            requirement_widgets = (
                self.preparation_source_requirements,
                self.preparation_slicer_requirements,
            )
            requirement_widget = requirement_widgets[selector_index]
            requirement_widget.setProperty("active", active)
            self._refresh_widget_style(requirement_widget)
        if not hasattr(self, "workflow"):
            self._refresh_preparation_section_layout()
            return
        self.workflow.set_slicer_step_visible(index == 1)
        if index == 1:
            self._ensure_slicer_profiles_on_first_step_entry()
        self._update_preparation_requirements()
        self._refresh_preparation_section_layout()

    def _ensure_slicer_profiles_on_first_step_entry(self) -> None:
        """Retry one missing automatic Slicer/profile load per session."""

        if (
            self._slicer_step_auto_discovery_attempted
            or not self._startup_slicer_discovery_enabled
        ):
            return
        selections = (
            self.slicer_combo.currentData(),
            self.machine_profile_combo.currentData(),
            self.filament_profile_combo.currentData(),
            self.process_profile_combo.currentData(),
        )
        if all(selection not in (None, "") for selection in selections):
            return
        self._slicer_step_auto_discovery_attempted = True
        # The discovery entry point serializes itself behind any startup
        # discovery/profile worker that is still finishing. This guarantees
        # one real retry even when the user reaches step 2 during startup.
        self.start_slicer_discovery(force=True)

    def _source_step_is_complete(self) -> bool:
        """Return whether the currently selected STL owns a valid result."""

        source_path = self.current_source_path
        artifact = self.source_artifact
        validation = self.stl_validation_result
        if (
            self.current_source_kind is not SourceKind.STL
            or source_path is None
            or artifact is None
            or validation is None
            or not getattr(validation, "accepted", validation.valid)
        ):
            return False
        artifact_path = getattr(artifact, "original_path", source_path)
        try:
            if Path(artifact_path).resolve() != source_path.resolve():
                return False
        except (OSError, TypeError, ValueError):
            return False
        matches_current_file = getattr(artifact, "matches_current_file", None)
        if callable(matches_current_file):
            try:
                if not matches_current_file():
                    return False
            except OSError:
                return False
        return True

    def _can_open_preparation_step(self, index: int) -> bool:
        """Allow every backward step, but gate all forward preparation."""

        return index == 0 or (index == 1 and self._source_step_is_complete())

    def _on_preparation_step_blocked(self, index: int) -> None:
        """Explain why an attempted forward navigation cannot continue."""

        if index != 1:
            return
        self._set_main_status(
            "Schritt 2 ist gesperrt · zuerst eine gültige STL übergeben",
            icon="⇧",
            state="idle",
        )
        selector = self.preparation_step_selectors[0]
        selector.setFocus(Qt.FocusReason.OtherFocusReason)

    def _finish_preparation(self) -> None:
        """Acknowledge a fully ready preparation and reveal method selection."""

        if not self._current_preparation_state().preparation_completed:
            self._update_preparation_requirements()
            return
        if not self.workflow.complete_preparation():
            return
        self.workflow_group.setChecked(False)
        self.generation_workspace.show()
        self._on_workflow_stage_changed(self.workflow.stage.value)
        self._refresh_preparation_section_layout()

    def _set_preparation_step_hovered(
        self,
        index: int,
        hovered: bool,
    ) -> None:
        """Apply hover feedback exclusively to the actual step selector."""

        selectors = getattr(self, "preparation_step_selectors", ())
        if not (0 <= index < len(selectors)):
            return
        self._set_boolean_style_property(
            selectors[index],
            "groupHovered",
            hovered,
        )
        selectors[index].update()

    def _schedule_slicer_step_open(self, request_id: int, source: Path) -> None:
        """Move from the accepted STL into the now-unlocked Slicer step."""

        delay_ms = max(0, self.workflow.first_success_duration_ms)

        def open_slicer_step() -> None:
            if (
                self._closing
                or request_id != self._stl_validation_request_id
                or self.current_source_path != source
                or not self._source_step_is_complete()
            ):
                return
            self.preparation_tabs.setCurrentIndex(1)

        QTimer.singleShot(delay_ms, open_slicer_step)

    def _set_setting_feedback_enabled(self, enabled: bool) -> None:
        """Gate setting hints until STL analysis and slicer are available."""

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
        setting_widget.set_limits_visible(self.show_setting_limits)
        self._setting_widgets[setting_name] = setting_widget
        editor.valueChanged.connect(self._on_value_changed)
        setting_widget.input_state_changed.connect(
            self._on_numeric_input_state_changed
        )
        setting_widget.reset_performed.connect(
            self._on_individual_reset
        )
        setting_widget.message_expand_button.toggled.connect(
            lambda _expanded: self._refresh_geometry_section_layout(
                self.geometry_settings_group.isChecked()
            )
            if hasattr(self, "geometry_settings_group")
            else None
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

    @Slot(int, object)
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

    @Slot(int, str, str)
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
        self._update_download_cancel_requested = False
        request_id = self._update_download_request_id
        self.update_button.setEnabled(False)
        self.update_button.setText("Lädt … 0 %")
        self.update_cancel_button.setEnabled(True)
        self.update_cancel_button.show()
        worker = UpdateDownloadWorker(
            request_id,
            self.available_update,
            self.update_service,
        )
        worker.progress.connect(self._on_update_download_progress)
        worker.succeeded.connect(self._on_update_download_succeeded)
        worker.failed.connect(self._on_update_download_failed)
        worker.finished.connect(self._on_update_download_finished)
        self.background_job_manager.start_job(
            kind=JobKind.UPDATE_DOWNLOAD,
            request_id=request_id,
            worker=worker,
        )

    @Slot(int, int)
    def _on_update_download_progress(self, request_id: int, percent: int) -> None:
        if (
            request_id != self._update_download_request_id
            or self._closing or self._update_download_cancel_requested
        ):
            return
        self.update_button.setText(f"Lädt … {max(0, min(100, percent))} %")

    def cancel_update_download(self) -> None:
        if not self.background_job_manager.has_active(JobKind.UPDATE_DOWNLOAD):
            return
        self._update_download_cancel_requested = True
        self.update_cancel_button.setEnabled(False)
        self.update_button.setText("Abbruch läuft …")
        self.background_job_manager.cancel_jobs(
            JobKind.UPDATE_DOWNLOAD, reason="user_request"
        )

    @Slot(int)
    def _on_update_download_finished(self, request_id: int) -> None:
        if request_id != self._update_download_request_id:
            return
        self.update_cancel_button.hide()
        if self._update_download_cancel_requested:
            self.update_button.setText("Aktualisieren")
            self.update_button.setEnabled(True)
            self._update_download_cancel_requested = False

    @Slot(int, object)
    def _on_update_download_succeeded(
        self,
        request_id: int,
        installer_path: Path,
    ) -> None:
        if request_id != self._update_download_request_id or self._closing:
            self.update_service.discard_installer(installer_path)
            return
        if self._update_download_cancel_requested:
            self.update_service.discard_installer(installer_path)
            return
        self.update_cancel_button.hide()
        self.update_button.setText("Update geprüft")
        result = UpdateRestartCountdownDialog(self, seconds=10).exec_countdown()
        if result == QMessageBox.DialogCode.Rejected:
            self.update_service.discard_installer(installer_path)
            self.update_button.setText("Aktualisieren")
            self.update_button.setEnabled(True)
            return
        if self._closing:
            self.update_service.discard_installer(installer_path)
            return
        self.update_button.setText("Installation startet …")
        try:
            self.update_service.launch_installer(installer_path)
        except Exception as error:
            self.update_service.discard_installer(installer_path)
            self._show_update_error(str(error))
            return
        application = QApplication.instance()
        if application is not None:
            application.quit()

    @Slot(int, str, str)
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
        self.update_cancel_button.hide()
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
            ).replace(
                "__CHECKBOX_CHECK_ICON__",
                (assets / "checkbox_check.svg").as_posix(),
            )
            self.setStyleSheet(style)
        except OSError:
            pass
        self.layer_range_button.ensurePolished()
        self.layer_range_button.setFixedWidth(
            self.layer_range_button.sizeHint().width()
        )

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
        """Return the preview panel embedded at the end of Prognose."""

        if self._preview_dialog is None:  # pragma: no cover - construction guard
            raise RuntimeError("Die eingebettete Vorschau wurde nicht aufgebaut.")
        return self._preview_dialog

    @property
    def additional_options_dialog(self) -> QDialog:
        """Create the output-folder dialog lazily."""

        if self._additional_options_dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("additionalOptionsDialog")
            dialog.setWindowTitle("Exportordner ändern")
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
    def export_success_dialog(self) -> QDialog:
        """Create the compact export confirmation dialog lazily."""

        if self._export_success_dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("exportSuccessDialog")
            dialog.setWindowTitle("Export erfolgreich")
            dialog.setModal(True)
            dialog.setSizeGripEnabled(False)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 11, 24, 20)
            layout.setSpacing(13)

            self.export_success_header_layout = QVBoxLayout()
            self.export_success_header_layout.setContentsMargins(0, 0, 0, 0)
            self.export_success_header_layout.setSpacing(7)

            self.export_success_title_label = QLabel(
                "✓ Kühlturm erfolgreich exportiert"
            )
            self.export_success_title_label.setObjectName(
                "exportSuccessTitle"
            )
            self.export_success_header_layout.addWidget(
                self.export_success_title_label
            )

            self.export_success_summary_label = QLabel()
            self.export_success_summary_label.setObjectName(
                "exportSuccessSummary"
            )
            self.export_success_summary_label.setWordWrap(True)
            self.export_success_summary_label.setTextFormat(Qt.TextFormat.RichText)
            self.export_success_header_layout.addWidget(
                self.export_success_summary_label
            )
            layout.addLayout(self.export_success_header_layout)

            metrics_frame = QFrame()
            metrics_frame.setObjectName("exportSuccessMetrics")
            metrics_layout = QVBoxLayout(metrics_frame)
            metrics_layout.setContentsMargins(14, 12, 14, 12)
            metrics_layout.setSpacing(0)
            self.export_success_target_label = QLabel()
            self.export_success_target_label.setObjectName(
                "exportSuccessMetric"
            )
            self.export_success_target_label.hide()
            self.export_success_achieved_label = QLabel()
            self.export_success_achieved_label.setObjectName(
                "exportSuccessMetric"
            )
            self.export_success_achieved_label.setWordWrap(True)
            self.export_success_deviation_label = QLabel()
            self.export_success_deviation_label.setObjectName(
                "exportSuccessTolerance"
            )
            self.export_success_deviation_label.setWordWrap(True)
            metrics_layout.addWidget(self.export_success_achieved_label)
            metrics_layout.addWidget(self.export_success_deviation_label)
            metrics_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            layout.addWidget(metrics_frame)

            self.export_success_simulation_frame = QFrame()
            self.export_success_simulation_frame.setObjectName("exportSuccessUsage")
            simulation_layout = QVBoxLayout(self.export_success_simulation_frame)
            simulation_layout.setContentsMargins(14, 12, 14, 12)
            simulation_layout.setSpacing(12)
            simulation_title = QLabel("Simulierte Einstellungen")
            simulation_title.setObjectName("exportSuccessUsageTitle")
            self.export_success_simulation_label = QLabel()
            self.export_success_simulation_label.setObjectName("exportSuccessUsageText")
            self.export_success_simulation_label.setTextFormat(Qt.TextFormat.RichText)
            self.export_success_simulation_label.setWordWrap(True)
            simulation_layout.addWidget(simulation_title)
            simulation_layout.addWidget(self.export_success_simulation_label)
            layout.addWidget(self.export_success_simulation_frame)
            self.export_success_simulation_frame.hide()

            usage_frame = QFrame()
            usage_frame.setObjectName("exportSuccessUsage")
            usage_layout = QVBoxLayout(usage_frame)
            usage_layout.setContentsMargins(14, 12, 14, 12)
            usage_layout.setSpacing(12)
            self.export_success_usage_title = QLabel(
                "So können Sie die exportierten Dateien verwenden"
            )
            self.export_success_usage_title.setObjectName(
                "exportSuccessUsageTitle"
            )
            self.export_success_usage_label = QLabel()
            self.export_success_usage_label.setObjectName(
                "exportSuccessUsageText"
            )
            self.export_success_usage_label.setTextFormat(
                Qt.TextFormat.RichText
            )
            self.export_success_usage_label.setWordWrap(True)
            usage_layout.addWidget(self.export_success_usage_title)
            usage_layout.addWidget(self.export_success_usage_label)
            layout.addWidget(usage_frame)

            self.export_success_check_hint = QLabel(
                "<b>Wichtig:</b> Prüfen Sie die Layerzeit vor dem Druck noch einmal "
                "im Slicer. Nachträgliche Änderungen im Slicer am Modell, "
                "Turm, Anordnung oder Druckprofilen können zu "
                "Abweichungen von der hier erreichten Layerzeit "
                "führen."
            )
            self.export_success_check_hint.setObjectName(
                "exportSuccessCheckHint"
            )
            self.export_success_check_hint.setTextFormat(
                Qt.TextFormat.RichText
            )
            self.export_success_check_hint.setWordWrap(True)
            self.export_success_check_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            layout.addWidget(self.export_success_check_hint)

            self.export_success_error_label = QLabel()
            self.export_success_error_label.setObjectName(
                "exportSuccessError"
            )
            self.export_success_error_label.setWordWrap(True)
            self.export_success_error_label.hide()
            layout.addWidget(self.export_success_error_label)

            actions = QHBoxLayout()
            actions.setContentsMargins(0, 2, 0, 0)
            actions.setSpacing(8)
            actions.addStretch(1)
            self.export_success_cancel_button = QPushButton("Schließen")
            self.export_success_cancel_button.clicked.connect(dialog.reject)
            actions.addWidget(self.export_success_cancel_button)
            self.export_success_open_button = QPushButton(
                "Exportordner öffnen"
            )
            self.export_success_open_button.setObjectName("primaryButton")
            self.export_success_open_button.setDefault(True)
            self.export_success_open_button.clicked.connect(
                self._open_export_directory_from_success_dialog
            )
            actions.addWidget(self.export_success_open_button)
            layout.addLayout(actions)

            self._export_success_dialog = dialog
        return self._export_success_dialog

    @property
    def about_dialog(self) -> AboutDialog:
        if self._about_dialog is None:
            self._about_dialog = AboutDialog(self)
            self._about_dialog.content_changed.connect(self._expand_about_downward_for_content)
        return self._about_dialog

    def _set_about_license_status(self, status: str) -> None:
        self.about_dialog._set_about_license_status(status)

    @property
    def about_close_button(self):
        return self.about_dialog.about_close_button

    @property
    def about_content(self):
        return self.about_dialog.about_content

    @property
    def about_content_layout(self):
        return self.about_dialog.about_content_layout

    @property
    def about_copyright_row(self):
        return self.about_dialog.about_copyright_row

    @property
    def about_copyright_symbol(self):
        return self.about_dialog.about_copyright_symbol

    @property
    def about_copyright_text(self):
        return self.about_dialog.about_copyright_text

    @property
    def about_developer_name(self):
        return self.about_dialog.about_developer_name

    @property
    def about_developer_row(self):
        return self.about_dialog.about_developer_row

    @property
    def about_legal_buttons(self):
        return self.about_dialog.about_legal_buttons

    @property
    def about_legal_grid(self):
        return self.about_dialog.about_legal_grid

    @property
    def about_license_status_description(self):
        return self.about_dialog.about_license_status_description

    @property
    def about_license_status_label(self):
        return self.about_dialog.about_license_status_label

    @property
    def about_license_status_row(self):
        return self.about_dialog.about_license_status_row

    @property
    def about_placeholder_label(self):
        return self.about_dialog.about_placeholder_label

    @property
    def about_product_description(self):
        return self.about_dialog.about_product_description

    @property
    def about_product_title(self):
        return self.about_dialog.about_product_title

    @property
    def about_program_icon(self):
        return self.about_dialog.about_program_icon

    @property
    def about_scroll(self):
        return self.about_dialog.about_scroll

    @property
    def about_support_link(self):
        return self.about_dialog.about_support_link



    @property
    def support_report_dialog(self) -> SupportReportDialog:
        """Create the local support-report dialog only when requested."""

        if self._support_report_dialog is None:
            self._support_report_dialog = SupportReportDialog(
                self.support_report_service,
                application_context_provider=self._support_diagnostic_context,
                open_directory=open_directory,
                asset_root=GUI_ASSET_ROOT,
                parent=self,
            )
        return self._support_report_dialog





    def _close_additional_options(self) -> None:
        if self._additional_options_dialog is not None:
            self._additional_options_dialog.close()

    def _restore_phase17_ui_state(self, ui_state: dict[str, object]) -> None:
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
        joint_slice_available = bool(
            self.source_artifact is not None
            and self.source_artifact.source_kind.value == "stl"
        )
        return CalibrationConfig(
            mode=CalibrationMode.STL,
            time_tolerance_s=self.layer_time_tolerance_spin.value(),
            maximum_iterations=(
                self.maximum_separate_slices + self.maximum_joint_slices
            ),
            object_clearance_mm=5.0,
            bed_edge_clearance_mm=5.0,
            perform_joint_final_slice=joint_slice_available,
            maximum_joint_slices=self.maximum_joint_slices,
            minimum_joint_slices=GENERATION_MINIMUM_JOINT_SLICES,
        )

    @property
    def preview_iterations(self) -> int:
        return self.maximum_separate_slices + self.maximum_joint_slices

    @property
    def preview_joint_slices(self) -> int:
        return self.maximum_joint_slices

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
            "Slicer-gestützte Verarbeitung ist verfügbar."
            if can_calibrate_stl
            else "Ein bestätigter, aufrufbarer Slicer ist erforderlich."
        )
        self._refresh_phase17_actions()

    def _show_confirmed_profiles_analysis_action(self) -> None:
        """Offer source-bound analysis after profiles were confirmed first."""

        if (
            not self._source_step_is_complete()
            or not self._catalog_selection_is_confirmed()
            or self.profile_match_result is not None
        ):
            return
        self.profile_confirm_button.setText(
            "Modell bestätigen und mit Profilen analysieren"
        )
        self.profile_confirm_button.setEnabled(True)
        self.profile_confirm_button.show()
        if self.workflow.can_transition_to(
            WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION
        ):
            self.workflow.wait_for_profile_confirmation()

    def _current_preview_request(
        self,
        *,
        calibration_config: CalibrationConfig | None = None,
    ) -> PreviewRequest:
        snapshot = self.analysis_snapshot
        if snapshot is None:
            raise ValueError("Die slicerbasierte Modellanalyse ist noch nicht abgeschlossen.")
        result = self.profile_match_result
        if (
            result is None
            or result.selected is None
            or not result.can_use_stl_mode
            or not result.user_confirmed
            or not result.execution_slicer.can_slice
        ):
            raise ValueError(
                "Vorschau und Export benötigen einen bestätigten, "
                "automatisch aufrufbaren Slicer mit vollständigen Profilen."
            )
        effective_profile = result.selected.effective_profile
        if self.source_preslice_result is not None and getattr(self.source_preslice_result, "supports_simulated", False):
            effective_profile = with_simulated_supports(effective_profile)
        if self.source_preslice_result is not None and getattr(
            self.source_preslice_result, "draft_shield_simulated", False
        ):
            effective_profile = with_simulated_draft_shield_disabled(effective_profile)
        adapter = self.slicer_service.adapter_for(result.execution_slicer)
        slicer_key = result.execution_slicer.identity_key
        profile_fingerprint = (
            f"{result.inventory_fingerprint}:{result.selected.bundle_id}:1"
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
            source_artifact=self.source_artifact,
            prepared_analysis_source=self.prepared_analysis_source,
            prepared_source_data=(
                self.source_preslice_result.preview_source_data
                if self.source_preslice_result is not None
                else None
            ),
            force_tower=False,
        )

    def _invalidate_preview(
        self,
        reason: str,
        *,
        preserve_slicer_prediction: bool = False,
    ) -> None:
        if self._loading_phase17_state:
            return
        self._cancel_generation_phase_transition()
        if not preserve_slicer_prediction:
            self._clear_slicer_prediction()
        self._preview_request_id += 1
        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="preview_invalidated",
        )
        if self._joint_generation_dialog is not None and self._joint_generation_dialog._running:
            self._joint_generation_dialog.mark_interrupted(
                "Einstellungen geändert. Bitte mit den aktuellen Werten neu generieren."
            )
            self._set_isolated_slice_progress_visible(False)
        if hasattr(self, "progress_bar"):
            self.progress_bar.setProperty("task", "default")
            self._refresh_widget_style(self.progress_bar)
        had_preview = self.current_preview is not None
        request_matches = self._retained_preview_matches_current_request()
        self.preview_state = (
            PreviewState.CURRENT
            if request_matches
            else PreviewState.STALE
            if had_preview
            else PreviewState.EMPTY
        )
        if self._preview_dialog is not None:
            if request_matches:
                self._preview_dialog.mark_current()
            else:
                self._preview_dialog.mark_stale()
        # Staleness is intentionally communicated once, directly above the
        # retained 3D scene. The prediction card and footer no longer repeat
        # the same warning; their disabled actions still enforce safety.
        self.preview_hint_label.hide()
        if request_matches:
            self._set_main_status(
                "Vorschau ist aktuell", icon="✓", state="success"
            )
        elif had_preview:
            self._set_main_status(
                "Einstellungen geändert", icon="↻", state="idle"
            )
        self._refresh_widget_style(self.preview_hint_label)
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def _retained_preview_matches_current_request(self) -> bool:
        """Compare all export-relevant inputs with the retained preview."""

        preview = self.current_preview
        signature = getattr(preview, "request_signature", None)
        if not isinstance(signature, str) or not signature:
            return False
        try:
            current_signature = self._current_preview_request().signature()
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        return signature == current_signature

    def _refresh_phase17_actions(self) -> None:
        if not hasattr(self, "preview_button"):
            return
        self.generation_method_back_button.setEnabled(
            self._generation_method_change_available()
        )
        if self.generation_mode is GenerationMode.MANUAL:
            self.manual_controller.refresh()
            return
        self._refresh_layer_range_tool()
        block_reason = self._export_block_reason()
        generation_active = self.background_job_manager.has_active(
            JobKind.PREVIEW
        )
        preview_enabled = (
            generation_active and not self._preview_cancel_requested
        ) or (
            not generation_active
            and self._generation_block_reason() is None
        )
        self.preview_button.setEnabled(preview_enabled)
        preview_is_current = bool(
            self.current_preview is not None
            and self.preview_state is PreviewState.CURRENT
        )
        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.continue_button.setEnabled(
                preview_is_current and not generation_active and block_reason is None
            )
        export_reason = block_reason
        if export_reason is None and not preview_is_current:
            export_reason = (
                "Bitte zuerst einen aktuellen Kühlturm generieren."
            )
        if (
            export_reason is None
            and preview_is_current
            and self._current_preview_was_exported()
        ):
            export_reason = (
                "Dieser Generierungsstand wurde bereits exportiert."
            )
        self._set_export_button_state(
            export_reason is None,
            export_reason,
        )
        if block_reason is None and not preview_is_current:
            self.export_availability_label.clear()
            self.action_availability_widget.hide()
            self._refresh_footer_auxiliary_visibility()
            self._schedule_footer_height_update()
        actions_available = bool(
            hasattr(self, "footer") and not self.footer.isHidden()
        )
        show_generation = (
            generation_active or self._joint_generation_paused
            or not preview_is_current
        )
        self.preview_action_control.setVisible(
            actions_available and show_generation
        )
        self.preview_button.setVisible(actions_available and show_generation)
        self.export_button.setVisible(
            actions_available and preview_is_current and not generation_active
        )
        if hasattr(self, "slicer_prediction_button"):
            self._refresh_prediction_advice(
                self.prediction_method_label.text()
            )
        self._update_responsive_action_labels()
        self._refresh_folder_action_states()

    def _current_preview_was_exported(self) -> bool:
        """Return whether the exact current generation was exported this session."""

        return (
            self._preview_export_identity(self.current_preview)
            == self._last_exported_preview_identity
            and self._last_exported_preview_identity is not None
        )

    @staticmethod
    def _preview_export_identity(preview: object) -> tuple[str, str | None] | None:
        """Identify the generated tower, not only the settings shared by its revisions."""

        signature = getattr(preview, "request_signature", None)
        if not isinstance(signature, str) or not signature:
            return None
        artifact_sha256 = getattr(preview, "artifact_sha256", None)
        return signature, artifact_sha256 if isinstance(artifact_sha256, str) else None

    def _export_block_reason(self) -> str | None:
        if self.background_job_manager.has_active(JobKind.EXPORT):
            return "Ein Export wird bereits ausgeführt."
        if self.background_job_manager.has_active(JobKind.SLICER_PREDICTION):
            return "Die einmalige Slicer-Schätzung wird gerade erstellt."
        if self.background_job_manager.has_active(JobKind.PREVIEW):
            return "Die Vorschau wird gerade erstellt."
        if self.current_source_path is None:
            return "Bitte zuerst eine STL auswählen."
        if self._analysis_failed:
            return self._workflow_error_message or "Die STL-Vorbereitung oder Analyse ist fehlgeschlagen. Bitte die Quellenprüfung erneut ausführen."
        if self.current_gcode_path is None:
            return "Die STL wird noch geprüft, geslict oder analysiert."
        if self.analysis_snapshot is None:
            return "Die Quelle wird noch analysiert."
        no_tower = (
            self.tower_assessment is not None
            and not self.tower_assessment.tower_required
        )
        if no_tower:
            return self._no_tower_required_reason(
                self.tower_assessment, self.analysis_snapshot
            )
        if not self._phase17_static_valid:
            causes = list(dict.fromkeys(message for messages in self._static_field_errors.values() for message in messages))
            return "Bitte Eingaben korrigieren: " + " ".join(causes[:3]) if causes else "Bitte ungültige oder unvollständige Eingaben korrigieren."
        if self.tower_assessment is None:
            return "Der Kühlturmbedarf wird noch geprüft."
        if self.profile_feasibility is None:
            return "Die Turmgeometrie wird noch geprüft."
        elif not self.profile_feasibility.feasible:
            reasons = " ".join(german_user_message(issue.message) for issue in self.profile_feasibility.issues[:3])
            return "Die Turmgeometrie ist mit den aktuellen Werten nicht möglich. " + reasons
        return None

    def _generation_block_reason(self) -> str | None:
        return self._export_block_reason()

    def _set_export_button_state(
        self,
        enabled: bool,
        reason: str | None = None,
    ) -> None:
        self.export_button.setEnabled(enabled)
        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.export_button.setEnabled(enabled)
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
        if message == "Dieser Generierungsstand wurde bereits exportiert.":
            self.export_availability_label.setText(
                "Erneuter Export nicht nötig: Dieser Generierungsstand wurde bereits exportiert."
            )
        elif message.startswith("Kein Kühlturm erforderlich:"):
            self.export_availability_label.setText(
                "Kein Kühlturm erforderlich. Alle berücksichtigten Layer des Originalobjekts "
                "erreichen bereits die gewünschte Mindest-Layerzeit; "
                "die Generierung ist deshalb deaktiviert."
            )
        else:
            self.export_availability_label.setText(
                f"Export/Vorschau nicht möglich: {message}"
            )
        no_tower = message.startswith("Kein Kühlturm erforderlich:")
        self.action_availability_icon.setText("✓" if no_tower else "⚠")
        state = "success" if no_tower else "warning"
        for widget in (self.action_availability_icon, self.export_availability_label):
            widget.setProperty("state", state)
            self._refresh_widget_style(widget)
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
        if (
            not force
            and manual_path is None
            and self.slicer_discovery_result is not None
        ):
            # Installation discovery is a session-level operation. Loading a
            # new G-code updates its profile assignment, but must not repeat
            # the visible Slicer detection workflow or briefly disable its
            # controls. The explicit refresh action remains the rescan path.
            if self._profile_matching_context() is not None:
                self.start_profile_matching()
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
            self._profile_catalog_match_source_request_id = None
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
        self._profile_catalog_match_source_request_id = None
        self._force_profile_catalog_after_discovery = bool(
            force or manual_path is not None
        )
        if force or manual_path is not None:
            self.profile_catalog = None
            self.profile_catalog_confirmation = None
            self._update_preparation_requirements()
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

    def _start_initial_slicer_discovery(self) -> None:
        """Start once, unless an explicit request already won the startup race."""

        if (
            self._closing
            or self.slicer_discovery_result is not None
            or self._pending_slicer_discovery is not None
            or self.background_job_manager.has_active(
                JobKind.SLICER_DISCOVERY
            )
        ):
            return
        if (
            self._slicer_service_was_injected
            or os.environ.get("QT_QPA_PLATFORM", "").casefold() != "offscreen"
        ):
            self.start_slicer_discovery()

    def select_manual_slicer(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Installierten oder portablen Slicer auswählen",
            "",
            "Windows-Programme (*.exe);;Alle Dateien (*)",
        )
        if selected:
            self.start_slicer_discovery(manual_path=Path(selected))

    @Slot(int, object)
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
                if installation.verified and installation.can_slice
            )
            preferred_key = (
                result.last_used_key
                or (
                    previous_key
                    if any(
                        installation.identity_key == previous_key
                        for installation in verified_installations
                    )
                    else None
                )
                or result.recommended_key
            )
            show_last_used_suffix = len(verified_installations) > 1
            for index, installation in enumerate(verified_installations):
                label = installation.display_name
                if (
                    show_last_used_suffix
                    and installation.identity_key == result.last_used_key
                ):
                    label += " – zuletzt verwendet"
                self.slicer_combo.addItem(
                    label,
                    installation.identity_key,
                )
                self.slicer_combo.setItemData(
                    index,
                    str(installation.executable_path),
                    Qt.ItemDataRole.ToolTipRole,
                )
                if installation.identity_key == preferred_key:
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
        retained_automatic_selection = bool(
            previous_key is not None
            and previous_key == self._automatically_selected_slicer_key
        )
        self._automatically_selected_slicer_key = (
            selected.identity_key
            if (
                selected is not None
                and selected.automatically_discovered
                and selected.identity_key == result.recommended_key
                and (
                    previous_key is None
                    or retained_automatic_selection
                    or selected.identity_key == result.last_used_key
                )
            )
            else None
        )
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
                    selected.identity_key == result.last_used_key,
                    "zuletzt verwendeter slicer",
                    "Zuletzt verwendeter Slicer wurde vorausgewählt.",
                ),
                (
                    result.last_used_key is None
                    and selected.identity_key == result.recommended_key,
                    "passender erkannter slicer",
                    "Passender erkannter Slicer wurde vorausgewählt.",
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
                55,
                "Slicer erkannt · Profile werden als Nächstes geprüft",
                icon="✓",
                state="success",
            )
            self._set_slicer_header_summary(selected)
            self._update_preparation_requirements()
            self.start_profile_catalog_loading(
                force_inventory=self._force_profile_catalog_after_discovery,
                prefer_active_presets=True,
                restore_remembered_profiles=(
                    not self._force_profile_catalog_after_discovery
                ),
            )
        else:
            self._slicer_header_installation = None
            self.profile_catalog = None
            self.profile_catalog_confirmation = None
            self._set_slicer_progress(
                100,
                "Kein verwendbarer Slicer erkannt",
                icon="!",
                state="warning",
            )
            self.workflow.required_slicer_unavailable(
                "Für STL ist ein automatisch aufrufbarer Slicer erforderlich"
            )
            self._update_preparation_requirements()
        self._refresh_prediction()

    @Slot(int, str, str)
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
        self.workflow.required_slicer_unavailable(
            "Für STL ist ein automatisch aufrufbarer Slicer erforderlich"
        )
        self.profile_catalog = None
        self.profile_catalog_confirmation = None
        self._update_preparation_requirements()

    def _on_slicer_selection_changed(self, _index: int) -> None:
        if self._populating_slicer_combo:
            return
        # A direct combo change is a manual choice, even when its installation
        # originally came from automatic discovery.
        self._automatically_selected_slicer_key = None
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
        if selected is not None:
            self.start_profile_catalog_loading(prefer_active_presets=True)

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
        self.slicer_group.set_summary_note(None)
        self.slicer_group.set_title_note(
            (
                "(automatisch erkannt)"
                if installation.automatically_discovered
                else None
            ),
            severity="success",
        )
        self._refresh_slicer_auto_detection_label()
        self._refresh_slicer_header_profiles(installation)

    def _refresh_slicer_auto_detection_label(self) -> None:
        installation = self.selected_slicer_installation
        visible = bool(
            installation is not None
            and installation.identity_key
            == self._automatically_selected_slicer_key
        )
        self.slicer_auto_detected_label.setVisible(visible)
        self.slicer_auto_detected_label.setAccessibleDescription(
            "Der aktuell ausgewählte Slicer wurde automatisch erkannt."
            if visible
            else ""
        )

    def _refresh_slicer_header_profiles(
        self,
        installation: SlicerInstallation | None = None,
    ) -> None:
        """Keep the compact header aligned and expose selections accessibly."""

        self._refresh_slicer_auto_detection_label()
        current = (
            installation
            or self.selected_slicer_installation
            or self._slicer_header_installation
        )
        if current is None:
            self.slicer_group.set_summary("")
            self.slicer_selector_column.setAccessibleDescription(
                "Noch kein Slicer und keine Profile ausgewählt"
            )
            return

        def selected_text(combo: QComboBox) -> str:
            text = combo.currentText().strip()
            return text if text else "Noch nicht ausgewählt"

        selections = (
            ("Slicer", current.display_name),
            ("Maschinenprofil", selected_text(self.machine_profile_combo)),
            ("Filamentprofil", selected_text(self.filament_profile_combo)),
            ("Prozessprofil", selected_text(self.process_profile_combo)),
        )
        self.slicer_group.set_summary(current.display_name)
        self.slicer_selector_column.setAccessibleDescription(
            "; ".join(f"{label}: {value}" for label, value in selections)
        )
        QTimer.singleShot(0, self._refresh_slicer_section_layout)

    def _clear_profile_assignment(
        self,
        message: str,
        state: str,
        *,
        preserve_catalog: bool = False,
    ) -> None:
        self._discard_source_preslice("profile_context_changed")
        self._pending_profile_match = None
        self._profile_catalog_match_source_request_id = None
        self.profile_match_result = None
        self.confirmed_profile_context = None
        self._reset_profile_filter_controls()
        if preserve_catalog and self.profile_catalog is not None:
            self._populate_profile_combos(self.profile_catalog)
            self.show_all_profiles_checkbox.setEnabled(
                bool(self.profile_catalog.machine_options)
            )
        else:
            self.profile_catalog = None
            self.profile_catalog_confirmation = None
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
        self._set_profile_notice(
            message if state == "error" else None,
            state=state,
        )
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.show()
        if preserve_catalog and self.profile_catalog is not None:
            catalog_confirmed = self._catalog_selection_is_confirmed()
            self._set_profile_notice()
            self.profile_confirm_button.setText(
                "Slicer und Profile bestätigen"
            )
            self.profile_confirm_button.show()
            self.profile_confirm_button.setEnabled(not catalog_confirmed)
        self.profile_effective_summary_label.clear()
        self.profile_effective_summary_label.hide()
        if hasattr(self, "profile_origin_label"):
            self.profile_origin_label.setText(
                "Profilherkunft wird nach einer belastbaren Zuordnung angezeigt."
            )
            self.profile_origin_label.hide()
            self.profile_diagnostics.clear()
            self.profile_diagnostics.hide()
        self._refresh_stl_availability()
        self._update_preparation_requirements()
        self.update_wall_path_preview()

    def _reset_profile_filter_controls(self) -> None:
        self.show_all_profiles_checkbox.setEnabled(False)
        previous_block_state = self.show_all_profiles_checkbox.blockSignals(True)
        self.show_all_profiles_checkbox.setChecked(False)
        self.show_all_profiles_checkbox.blockSignals(previous_block_state)
        self.profile_filter_label.setText(
            "Profilfilter\nProfile werden nach dem verwendeten Drucker "
            "gefiltert."
        )

    def _set_profile_notice(
        self,
        message: str | None = None,
        *,
        state: str = "pending",
    ) -> None:
        """Show only actionable or exceptional profile information."""

        text = (message or "").strip()
        self.profile_status_label.setText(text)
        self.profile_status_label.setProperty("state", state)
        self.profile_status_label.setVisible(bool(text))
        if hasattr(self, "slicer_message_divider_host"):
            self.slicer_message_divider_host.setVisible(bool(text))
        self._refresh_widget_style(self.profile_status_label)
        self._refresh_dynamic_preparation_layout()

    def _profile_confirmation_inputs_ready(self) -> bool:
        """Require one existing, catalog-backed file for every profile role."""

        installation = self.selected_slicer_installation
        catalog = self.profile_catalog
        if (
            installation is None
            or not getattr(installation, "verified", False)
            or not getattr(installation, "can_slice", True)
            or catalog is None
            or not catalog.complete
            or catalog.execution_slicer.identity_key
            != installation.identity_key
        ):
            return False
        if not all(
            hasattr(catalog, attribute)
            for attribute in (
                "machine_options",
                "filament_options",
                "process_options",
            )
        ):
            return False
        executable_path = getattr(installation, "executable_path", None)
        if executable_path is not None and not Path(executable_path).is_file():
            return False

        selections_and_options = (
            (
                self._profile_combo_reference(self.machine_profile_combo),
                catalog.machine_options,
            ),
            (
                self._profile_combo_reference(self.filament_profile_combo),
                catalog.filament_options,
            ),
            (
                self._profile_combo_reference(self.process_profile_combo),
                catalog.process_options,
            ),
        )
        for reference, records in selections_and_options:
            if reference is None or reference.path is None:
                return False
            if not reference.path.is_file():
                return False
            if not any(
                record.profile_id.casefold()
                == reference.profile_id.casefold()
                and record.path == reference.path
                and record.path.is_file()
                for record in records
            ):
                return False
        return True

    def _profile_confirmation_blocking_reason(self) -> str | None:
        """Explain an actionable catalog/profile lock without exposing paths."""

        installation = self.selected_slicer_installation
        catalog = self.profile_catalog
        if installation is None:
            return "Es ist kein verwendbarer Slicer ausgewählt."
        executable_path = getattr(installation, "executable_path", None)
        if executable_path is not None and not Path(executable_path).is_file():
            return "Die ausführbare Datei des ausgewählten Slicers fehlt."
        if catalog is None:
            return None
        if not all(
            hasattr(catalog, attribute)
            for attribute in (
                "machine_options",
                "filament_options",
                "process_options",
            )
        ):
            return "Der geladene Profilkatalog enthält nicht alle Profilarten."
        if not getattr(catalog, "complete", False):
            return getattr(catalog, "blocking_message", None) or (
                "Der Profilkatalog enthält nicht alle benötigten Profilarten."
            )
        selections_and_options = (
            (
                "Maschinenprofil",
                self._profile_combo_reference(self.machine_profile_combo),
                catalog.machine_options,
            ),
            (
                "Filamentprofil",
                self._profile_combo_reference(self.filament_profile_combo),
                catalog.filament_options,
            ),
            (
                "Prozessprofil",
                self._profile_combo_reference(self.process_profile_combo),
                catalog.process_options,
            ),
        )
        for label, reference, records in selections_and_options:
            if reference is None or reference.path is None:
                return f"Es ist kein gültiges {label} ausgewählt."
            if not reference.path.is_file():
                return f"Die Datei des ausgewählten {label}s ist nicht mehr vorhanden."
            if not any(
                record.profile_id.casefold()
                == reference.profile_id.casefold()
                and record.path == reference.path
                for record in records
            ):
                return (
                    f"Das ausgewählte {label} gehört nicht mehr zum aktuellen "
                    "Profilkatalog."
                )
        return None

    def _refresh_profile_confirmation_button(self) -> None:
        """Render one persistent action state without changing its geometry."""

        if not hasattr(self, "profile_confirmation_stack"):
            return
        self.profile_confirmation_stack.show()
        if self._profile_confirmation_busy:
            self.profile_confirmation_stack.setCurrentWidget(
                self.profile_confirmation_progress
            )
            return

        self.profile_confirmation_stack.setCurrentWidget(
            self.profile_confirm_button
        )
        self.profile_confirm_button.show()
        inputs_ready = self._profile_confirmation_inputs_ready()
        source_ready = self._source_step_is_complete()
        catalog_confirmed = self._catalog_selection_is_confirmed()
        result = self.profile_match_result
        result_requires_confirmation = bool(
            result is not None
            and getattr(result, "requires_confirmation", False)
        )
        source_analysis_can_start = bool(
            result is None
            and catalog_confirmed
            and self._profile_matching_context() is not None
        )
        confirmation_needed = bool(
            inputs_ready
            and source_ready
            and (
                result_requires_confirmation
                or not catalog_confirmed
                or source_analysis_can_start
            )
        )
        fully_confirmed = bool(
            inputs_ready
            and catalog_confirmed
            and result is not None
            and getattr(result, "user_confirmed", False)
            and not result_requires_confirmation
        )

        if source_analysis_can_start:
            text = "Modell bestätigen und mit Profilen analysieren"
        elif fully_confirmed:
            text = "Slicer und Profile bestätigt ✓"
        else:
            text = (
                "Slicer und Profile bestätigen"
                if confirmation_needed
                else "Slicer und Profile bestätigen 🔒"
            )
        self.profile_confirm_button.setText(text)
        self.profile_confirm_button.setEnabled(confirmation_needed)
        self.profile_confirm_button.setProperty("ready", confirmation_needed)
        self.profile_confirm_button.setProperty("confirmed", fully_confirmed)
        if confirmation_needed or fully_confirmed:
            tooltip = ""
        elif not source_ready:
            tooltip = _LOCKED_SLICER_STEP_TOOLTIP
        else:
            blocking_reason = self._profile_confirmation_blocking_reason()
            tooltip = (
                ((blocking_reason + " ") if blocking_reason else "")
                + "Wähle einen validen Slicer sowie je ein vorhandenes "
                "Maschinen-, Filament- und Prozessprofil aus."
            )
        self.profile_confirm_button.setToolTip(tooltip)
        blocking_reason = (
            self._profile_confirmation_blocking_reason()
            if source_ready and not inputs_ready
            else None
        )
        current_is_input_blocker = bool(
            self.profile_status_label.property("inputBlocker")
        )
        if blocking_reason and (
            current_is_input_blocker
            or not self.profile_status_label.text().strip()
        ):
            self._set_profile_notice(blocking_reason, state="error")
            self.profile_status_label.setProperty("inputBlocker", True)
        elif current_is_input_blocker and not blocking_reason:
            self.profile_status_label.setProperty("inputBlocker", False)
            self._set_profile_notice()
        self._refresh_widget_style(self.profile_confirm_button)

    def _set_profile_confirmation_busy(
        self,
        visible: bool,
        text: str | None = None,
        *,
        percent: int | None = None,
        progress_format: str | None = None,
    ) -> None:
        """Use the confirmation slot for progress at an unchanged 50 px."""

        self._profile_confirmation_busy = bool(visible)
        if visible:
            if percent is None:
                self.profile_confirmation_progress.setRange(0, 0)
                self.profile_confirmation_progress.setFormat(
                    text or "Slicer-Einstellungen werden geprüft …"
                )
            else:
                bounded = max(0, min(100, int(percent)))
                self.profile_confirmation_progress.setRange(0, 100)
                self.profile_confirmation_progress.setValue(bounded)
                self.profile_confirmation_progress.setFormat(
                    progress_format
                    or f"{(text or 'Slicer-Einstellungen werden geprüft').rstrip(' …')} · %p %"
                )
            self.profile_confirmation_progress.setAccessibleDescription(
                text or "Slicer-Einstellungen werden geprüft"
            )
        self._refresh_profile_confirmation_button()

    def start_profile_catalog_loading(
        self,
        *,
        force_inventory: bool = False,
        selected_machine: str | ProfileSelectionReference | None = None,
        selected_profile_ids: dict[
            str, str | ProfileSelectionReference
        ] | None = None,
        include_all_profiles: bool | None = None,
        prefer_active_presets: bool = False,
        restore_remembered_profiles: bool = True,
        match_source_after_loading: bool = False,
    ) -> None:
        """Load the selected slicer's profiles without requiring a source."""

        if self._closing:
            return
        installation = self.selected_slicer_installation
        if installation is None:
            self.profile_catalog = None
            self.profile_catalog_confirmation = None
            self._update_preparation_requirements()
            self._update_slicer_discovery_controls()
            return
        if self.background_job_manager.has_active(
            JobKind.SLICER_DISCOVERY
        ) or self.background_job_manager.has_active(JobKind.PROFILE_MATCH):
            self._profile_request_id += 1
            self._pending_profile_match = {
                "catalog_only": True,
                "force_inventory": bool(force_inventory),
                "selected_machine": selected_machine,
                "selected_profile_ids": dict(selected_profile_ids or {}),
                "include_all_profiles": include_all_profiles,
                "prefer_active_presets": bool(prefer_active_presets),
                "restore_remembered_profiles": bool(
                    restore_remembered_profiles
                ),
                "match_source_after_loading": bool(
                    match_source_after_loading
                ),
            }
            return
        restored_profile_ids = dict(selected_profile_ids or {})
        restored_confirmed_profiles = False
        if not restored_profile_ids and restore_remembered_profiles:
            remembered = getattr(
                self.slicer_service,
                "remembered_profile_selections",
                None,
            )
            if callable(remembered):
                try:
                    restored_profile_ids = dict(
                        remembered(installation.identity_key)
                    )
                    restored_confirmed_profiles = bool(restored_profile_ids)
                except (OSError, TypeError, ValueError, RuntimeError):
                    restored_profile_ids = {}
        if selected_machine is None:
            selected_machine = restored_profile_ids.get("machine")
        if selected_machine is None:
            selected_machine = self._profile_combo_reference(
                self.machine_profile_combo
            )
        show_all_profiles = (
            self.show_all_profiles_checkbox.isChecked()
            if include_all_profiles is None
            else bool(include_all_profiles)
        )
        try:
            adapter = self.slicer_service.adapter_for(installation)
        except (AttributeError, KeyError, ValueError):
            self.profile_catalog = None
            self.profile_catalog_confirmation = None
            self._set_profile_notice(
                "Für den ausgewählten Slicer ist kein Profiladapter verfügbar.",
                state="error",
            )
            self._set_slicer_progress(
                100,
                "Profiladapter nicht verfügbar",
                icon="✕",
                state="error",
            )
            self.workflow.required_slicer_unavailable(
                "Slicer-Profile konnten nicht geladen werden"
            )
            self._update_preparation_requirements()
            self._update_slicer_discovery_controls()
            return

        self._profile_request_id += 1
        request_id = self._profile_request_id
        self._profile_catalog_match_source_request_id = (
            request_id if match_source_after_loading else None
        )
        self._profile_catalog_preserve_selection_requests[request_id] = bool(
            restore_remembered_profiles
        )
        self.profile_match_result = None
        self.confirmed_profile_context = None
        self.workflow.begin_profile_matching()
        self._set_slicer_progress(
            60,
            "Zugehörige Slicer-Profile werden geladen …",
            icon="⌛",
            state="running",
        )
        self._set_profile_notice()
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.show()
        self._update_preparation_requirements()

        worker = ProfileCatalogWorker(
            request_id,
            self.profile_service,
            installation,
            adapter,
            force_inventory=force_inventory,
            selected_machine=selected_machine,
            selected_profile_ids=restored_profile_ids,
            include_all_profiles=show_all_profiles,
            prefer_active_presets=(
                prefer_active_presets and not restored_confirmed_profiles
            ),
        )
        self.slicer_refresh_button.setEnabled(False)
        self.slicer_manual_button.setEnabled(False)
        worker.succeeded.connect(self._on_profile_catalog_succeeded)
        worker.failed.connect(self._on_profile_catalog_failed)
        self.background_job_manager.start_job(
            kind=JobKind.PROFILE_MATCH,
            request_id=request_id,
            worker=worker,
        )

    @Slot(int, object)
    def _on_profile_catalog_succeeded(
        self,
        request_id: int,
        catalog: ProfileCatalog,
    ) -> None:
        if request_id != self._profile_request_id:
            self._profile_catalog_preserve_selection_requests.pop(
                request_id,
                None,
            )
            return
        match_source_after_loading = (
            request_id == self._profile_catalog_match_source_request_id
        )
        self._profile_catalog_match_source_request_id = None
        installation = self.selected_slicer_installation
        if (
            installation is None
            or catalog.execution_slicer.identity_key
            != installation.identity_key
        ):
            return
        previous_confirmation = self.profile_catalog_confirmation
        self.profile_catalog = catalog
        if (
            previous_confirmation is None
            or not previous_confirmation.matches_catalog(catalog)
        ):
            self.profile_catalog_confirmation = None
        preserve_previous_selection = (
            self._profile_catalog_preserve_selection_requests.pop(
                request_id,
                True,
            )
        )
        self._populate_profile_combos(
            catalog,
            preserve_previous_selection=preserve_previous_selection,
        )
        self.show_all_profiles_checkbox.setEnabled(bool(catalog.machine_options))
        self.profile_filter_label.setText(
            catalog.profile_filter_summary
            or (
                "Profilkatalog\n"
                f"{len(catalog.machine_options)} Maschinen-, "
                f"{len(catalog.filament_options)} Filament- und "
                f"{len(catalog.process_options)} Prozessprofile geladen."
            )
        )
        self.profile_filter_label.setProperty(
            "state", "available" if catalog.complete else "error"
        )
        self._refresh_widget_style(self.profile_filter_label)
        should_match_source = bool(
            catalog.complete
            and (
                match_source_after_loading
                or self._catalog_selection_is_confirmed()
            )
            and self._profile_matching_context() is not None
            and self._profile_confirmation_inputs_ready()
        )
        if not catalog.complete:
            self.profile_catalog_confirmation = None
            self._set_profile_notice(
                catalog.blocking_message
                or "Der Profilkatalog ist unvollständig.",
                state="error",
            )
            self.profile_confirm_button.setEnabled(False)
            self.profile_confirm_button.show()
            self.workflow.required_slicer_unavailable(
                "Slicer-Profile sind unvollständig"
            )
        elif should_match_source:
            # The catalogue worker still owns the shared profile job until its
            # native thread has ended. start_profile_matching() therefore
            # queues the source match. Keep the workflow continuously busy so
            # neither the UI nor tests can observe a false confirmation-ready
            # gap before that queued match starts.
            self._set_profile_notice()
            self.profile_confirm_button.setText(
                "Slicer und Profile bestätigen"
            )
            self.profile_confirm_button.setEnabled(False)
            self.profile_confirm_button.show()
            self.workflow.begin_profile_matching()
        elif self._catalog_selection_is_confirmed():
            self._set_profile_notice()
            self.profile_confirm_button.setEnabled(False)
            self.profile_confirm_button.show()
            self.workflow.slicer_succeeded(installation.display_name)
        else:
            self._set_profile_notice()
            self.profile_confirm_button.setText(
                "Slicer und Profile bestätigen"
            )
            self.profile_confirm_button.setEnabled(True)
            self.profile_confirm_button.show()
            self.workflow.wait_for_profile_confirmation()
        self._set_slicer_progress(
            70 if should_match_source else 100,
            (
                "Slicer und Profile geladen · Quelle wird geprüft …"
                if should_match_source
                else "Slicer und Profile geladen"
            ),
            icon="⌛" if should_match_source else "✓",
            state="running" if should_match_source else "success",
        )
        self._refresh_slicer_header_profiles()
        self._update_preparation_requirements()
        if should_match_source:
            # Matching may prepare a proposal, but cannot confirm it or start
            # a Pre-Slice.  Running it against the freshly installed catalogue
            # keeps the confirmation action immediate without ever mixing the
            # old and new profile scopes.
            self.start_profile_matching()

    @Slot(int, str, str)
    def _on_profile_catalog_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._profile_request_id:
            self._profile_catalog_preserve_selection_requests.pop(
                request_id,
                None,
            )
            return
        self._profile_catalog_preserve_selection_requests.pop(request_id, None)
        if request_id == self._profile_catalog_match_source_request_id:
            self._profile_catalog_match_source_request_id = None
        self.profile_catalog = None
        self.profile_catalog_confirmation = None
        self._set_profile_notice(
            "Slicer-Profile konnten nicht geladen werden: "
            f"{german_user_message(message)}",
            state="error",
        )
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.show()
        self._set_slicer_progress(
            100,
            "Slicer-Profile konnten nicht geladen werden",
            icon="✕",
            state="error",
        )
        self.workflow.required_slicer_unavailable(
            "Slicer-Profile konnten nicht geladen werden"
        )
        self._update_preparation_requirements()

    def _catalog_selection_is_confirmed(self) -> bool:
        catalog = self.profile_catalog
        confirmation = self.profile_catalog_confirmation
        if (
            catalog is None
            or confirmation is None
            or not confirmation.matches_catalog(catalog)
        ):
            return False
        current = {
            "machine": self._profile_combo_reference(
                self.machine_profile_combo
            ),
            "process": self._profile_combo_reference(
                self.process_profile_combo
            ),
            "filament": self._profile_combo_reference(
                self.filament_profile_combo
            ),
        }
        expected = confirmation.selected_profile_ids()
        return all(
            current[role] is not None
            and current[role].profile_id.casefold()
            == expected[role].profile_id.casefold()
            and current[role].path == expected[role].path
            for role in expected
        )

    def _confirm_catalog_selection(self) -> bool:
        if not self._source_step_is_complete():
            self._set_profile_notice(
                "Bitte zuerst Schritt 1 mit einer gültigen STL abschließen.",
                state="error",
            )
            self._on_preparation_step_blocked(1)
            return False
        catalog = self.profile_catalog
        if catalog is None or not catalog.complete:
            return False
        selections = {
            "machine": self._profile_combo_reference(
                self.machine_profile_combo
            ),
            "process": self._profile_combo_reference(
                self.process_profile_combo
            ),
            "filament": self._profile_combo_reference(
                self.filament_profile_combo
            ),
        }
        if not all(
            isinstance(value, ProfileSelectionReference)
            for value in selections.values()
        ):
            self._set_profile_notice(
                "Bitte je ein Maschinen-, Filament- und Prozessprofil auswählen.",
                state="error",
            )
            return False
        try:
            confirmation = ProfileCatalogConfirmation.from_catalog(
                catalog,
                machine_path=selections["machine"].path,
                process_path=selections["process"].path,
                filament_path=selections["filament"].path,
                machine_profile_id=selections["machine"].profile_id,
                process_profile_id=selections["process"].profile_id,
                filament_profile_id=selections["filament"].profile_id,
            )
        except (OSError, TypeError, ValueError) as error:
            self._set_profile_notice(
                german_user_message(str(error)), state="error"
            )
            return False
        self.profile_catalog_confirmation = confirmation
        for role, selected_identifier in selections.items():
            self._remember_profile_selection(role, selected_identifier)
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.show()
        self._set_profile_notice()
        installation = self.selected_slicer_installation
        if installation is not None and self.current_source_path is None:
            self.workflow.slicer_succeeded(installation.display_name)
        self._update_preparation_requirements()
        return True

    def _profile_matching_context(self) -> ProfileMatchingContext | None:
        if not self._source_step_is_complete():
            return None
        return ProfileMatchingContext.from_stl(self.source_artifact)

    def start_profile_matching(
        self,
        *,
        selected_profile_ids: dict[
            str, str | ProfileSelectionReference
        ] | None = None,
        force_inventory: bool = False,
        stale_check_only: bool = False,
        include_all_profiles: bool | None = None,
    ) -> None:
        if self._closing:
            return
        source_context = self._profile_matching_context()
        installation = self.selected_slicer_installation
        if source_context is None or installation is None:
            return
        if selected_profile_ids is None and not stale_check_only:
            catalog_confirmation = self.profile_catalog_confirmation
            catalog = self.profile_catalog
            if (
                catalog_confirmation is not None
                and catalog is not None
                and catalog_confirmation.matches_catalog(catalog)
                and catalog.execution_slicer.identity_key
                == installation.identity_key
            ):
                selected_profile_ids = (
                    catalog_confirmation.selected_profile_ids()
                )
        if selected_profile_ids is None and not stale_check_only:
            catalog = self.profile_catalog
            if (
                catalog is not None
                and catalog.complete
                and catalog.execution_slicer.identity_key
                == installation.identity_key
            ):
                current_selections = {
                    "machine": self._profile_combo_reference(
                        self.machine_profile_combo
                    ),
                    "process": self._profile_combo_reference(
                        self.process_profile_combo
                    ),
                    "filament": self._profile_combo_reference(
                        self.filament_profile_combo
                    ),
                }
                if all(
                    isinstance(value, ProfileSelectionReference)
                    for value in current_selections.values()
                ):
                    # The currently displayed catalogue reflects the latest
                    # active slicer state and therefore outranks an older
                    # convenience preference from this application.
                    selected_profile_ids = current_selections
        if selected_profile_ids is None and not stale_check_only:
            remembered = getattr(
                self.slicer_service,
                "remembered_profile_selections",
                None,
            )
            if callable(remembered):
                try:
                    restored = remembered(installation.identity_key)
                except (OSError, TypeError, ValueError, RuntimeError):
                    restored = {}
                if restored:
                    selected_profile_ids = dict(restored)
        show_all_profiles = (
            self.show_all_profiles_checkbox.isChecked()
            if include_all_profiles is None
            else bool(include_all_profiles)
        )
        if self.background_job_manager.has_active(JobKind.SLICER_DISCOVERY):
            # The discovery success signal can arrive just before its native
            # worker thread has fully ended. Queue profile access until the
            # manager confirms release so both jobs never touch one adapter at
            # the same time.
            self._profile_request_id += 1
            self._pending_profile_match = {
                "catalog_only": False,
                "selected_profile_ids": dict(selected_profile_ids or {}),
                "force_inventory": force_inventory,
                "stale_check_only": stale_check_only,
                "include_all_profiles": show_all_profiles,
            }
            return
        if self.background_job_manager.has_active(JobKind.PROFILE_MATCH):
            # Profile resolution, its disk cache and probe validator are one
            # shared unit.  Concurrent matches used to race on those objects.
            self._profile_request_id += 1
            self._pending_profile_match = {
                "catalog_only": False,
                "selected_profile_ids": dict(selected_profile_ids or {}),
                "force_inventory": force_inventory,
                "stale_check_only": stale_check_only,
                "include_all_profiles": show_all_profiles,
            }
            if not stale_check_only:
                self._set_profile_notice()
            return
        try:
            adapter = self.slicer_service.adapter_for(installation)
        except (AttributeError, KeyError, ValueError):
            self._clear_profile_assignment(
                "Für den ausgewählten Slicer ist kein Profiladapter verfügbar.",
                "error",
            )
            self._set_slicer_progress(
                100,
                "Profiladapter nicht verfügbar",
                icon="✕",
                state="error",
            )
            self.workflow.required_slicer_unavailable(
                "Slicer-Profile konnten nicht geprüft werden"
            )
            return

        self._profile_request_id += 1
        request_id = self._profile_request_id
        if not stale_check_only:
            self.confirmed_profile_context = None
            self.workflow.begin_profile_matching()
            self._update_preparation_requirements()
            self._set_slicer_progress(
                70,
                "Slicer-Profile werden geprüft …",
                icon="⌛",
                state="running",
            )
            self._set_profile_notice()
            self.profile_confirm_button.setEnabled(False)

        worker = ProfileMatchingWorker(
            request_id,
            self.profile_service,
            source_context,
            installation,
            adapter,
            selected_profile_ids=selected_profile_ids,
            force_inventory=force_inventory,
            include_all_profiles=show_all_profiles,
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

    @Slot(int, object)
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
        catalog_confirmed = bool(
            result.requires_confirmation
            and self._profile_result_matches_catalog_confirmation(result)
            and self.source_artifact is not None
        )
        draft_detected = (
            draft_shield_source(
                result.selected.effective_profile,
                result.selected.resolved_profiles,
            )
            if catalog_confirmed and result.selected is not None
            and not self._draft_shield_simulation_requested
            else None
        )
        if (
            catalog_confirmed and draft_detected is None
        ):
            try:
                source_confirmation = ProfileConfirmation.from_result(
                    result,
                    self.source_artifact,
                )
                result = self.profile_service.confirm(result)
            except (OSError, ValueError, SlicerProcessError):
                # A startup confirmation is carried forward only when the
                # exact inventory and selected paths can also be bound safely
                # to the immutable source. Otherwise the visible confirmation
                # step below remains mandatory.
                self.confirmed_profile_context = None
            else:
                self.confirmed_profile_context = source_confirmation
                if self.prepared_analysis_source is not None:
                    self.prepared_analysis_source = replace(
                        self.prepared_analysis_source,
                        slicer_version=result.execution_slicer.version,
                        effective_profile_fingerprint=(
                            result.effective_profile_fingerprint
                        ),
                    )
        self.profile_match_result = result
        self._populate_profile_combos(result)
        self.show_all_profiles_checkbox.setEnabled(True)
        self.profile_filter_label.setText(
            result.profile_filter_summary
            or "Profilfilter\nFür diese Profilprüfung liegen keine "
            "Filterangaben vor."
        )
        selected = result.selected
        if result.state is ProfileMatchState.UNAVAILABLE:
            profile_message = german_user_message(result.message)
            if (
                result.source_kind is SourceKind.STL
                and not result.can_use_stl_mode
                and "Pre-Slice" not in profile_message
            ):
                profile_message += (
                    " Für diese STL steht kein sicherer Pre-Slice zur Verfügung."
                )
            self._set_profile_notice(
                profile_message,
                state="error",
            )
        else:
            self._set_profile_notice()
        self.profile_confirm_button.setText(
            "Slicer und Profile bestätigen"
        )
        self.profile_confirm_button.show()
        self.profile_confirm_button.setEnabled(result.requires_confirmation)
        self.profile_origin_label.setText(self._profile_origin_text(result))
        self.profile_origin_label.show()
        self.profile_effective_summary_label.clear()
        self.profile_effective_summary_label.hide()
        if selected is not None:
            values = selected.effective_profile.effective_values

            def first_value(*keys: str) -> object | None:
                value = next(
                    (
                        values[key]
                        for key in keys
                        if values.get(key) not in (None, "")
                    ),
                    None,
                )
                if isinstance(value, (list, tuple)) and len(value) == 1:
                    return value[0]
                return value

            nozzle = first_value("nozzle_diameter", "machine_nozzle_size")
            layer_height = first_value("layer_height")
            validation_labels = {
                "invalid": "ungültig",
                "structurally_valid": "strukturell gültig",
                "probe_validated": "durch Probelauf validiert",
            }
            diagnostics = [
                "Bestätigungswerte · Düse: "
                f"{nozzle if nozzle is not None else 'nicht angegeben'} mm · "
                "Layerhöhe: "
                f"{layer_height if layer_height is not None else 'nicht angegeben'} mm",
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
        if result.requires_confirmation:
            self._set_slicer_progress(
                90,
                "Slicer und Profile geprüft · Bestätigung ausstehend",
                icon="○",
                state="warning",
            )
            self.workflow.wait_for_profile_confirmation()
        elif result.selected is not None and result.user_confirmed:
            self._set_slicer_progress(
                100,
                "Slicer und Profile bestätigt",
                icon="✓",
                state="success",
            )
            if result.source_kind is SourceKind.STL:
                self.start_source_preslice()
            else:
                self.workflow.slicer_succeeded(
                    result.execution_slicer.display_name
                )
        else:
            self._set_slicer_progress(
                100,
                "Keine bestätigbare Profilzuordnung gefunden",
                icon="✕",
                state="error",
            )
            self.workflow.required_slicer_unavailable(
                "Keine bestätigbare Profilzuordnung gefunden"
            )
        self._refresh_stl_availability()
        self._update_preparation_requirements()
        self.update_wall_path_preview()
        if draft_detected is not None and self.profile_match_result is result:
            self._show_draft_shield_dialog(result, draft_detected)

    def _profile_result_matches_catalog_confirmation(
        self,
        result: ProfileMatchResult,
    ) -> bool:
        confirmation = self.profile_catalog_confirmation
        selected = result.selected
        if confirmation is None or selected is None:
            return False
        if (
            result.execution_slicer.identity_key
            != confirmation.slicer_identity_key
            or result.inventory_fingerprint
            != confirmation.inventory_fingerprint
            or selected.machine is None
            or selected.process is None
            or selected.filament is None
        ):
            return False
        return (
            selected.machine.path.resolve() == confirmation.machine_path
            and selected.machine.profile_id.casefold()
            == confirmation.machine_profile_id.casefold()
            and selected.process.path.resolve() == confirmation.process_path
            and selected.process.profile_id.casefold()
            == confirmation.process_profile_id.casefold()
            and selected.filament.path.resolve() == confirmation.filament_path
            and selected.filament.profile_id.casefold()
            == confirmation.filament_profile_id.casefold()
        )

    def _populate_profile_combos(
        self,
        result: ProfileMatchResult | ProfileCatalog,
        *,
        preserve_previous_selection: bool = True,
    ) -> None:
        selected = (
            result.selected if isinstance(result, ProfileMatchResult) else None
        )
        def catalog_record(
            records,
            reference: ProfileSelectionReference | None,
        ):
            if reference is None:
                return None
            return next(
                (
                    record
                    for record in records
                    if record.profile_id.casefold()
                    == reference.profile_id.casefold()
                    and (
                        reference.path is None
                        or record.path == reference.path
                    )
                ),
                None,
            )

        catalog_machine = None
        catalog_process = None
        catalog_filament = None
        if isinstance(result, ProfileCatalog):
            catalog_machine = catalog_record(
                result.machine_options, result.selected_machine
            )
            catalog_process = catalog_record(
                result.process_options, result.selected_process
            )
            catalog_filament = catalog_record(
                result.filament_options, result.selected_filament
            )
        selected_records = (
            selected.machine if selected is not None else catalog_machine,
            selected.process if selected is not None else catalog_process,
            selected.filament if selected is not None else catalog_filament,
        )
        previous_selections = (
            (
                self.machine_profile_combo.currentData(),
                self.process_profile_combo.currentData(),
                self.filament_profile_combo.currentData(),
            )
            if preserve_previous_selection
            else (None, None, None)
        )
        previous_references = (
            (
                self._profile_combo_reference(self.machine_profile_combo),
                self._profile_combo_reference(self.process_profile_combo),
                self._profile_combo_reference(self.filament_profile_combo),
            )
            if preserve_previous_selection
            else (None, None, None)
        )
        self._populating_profile_combos = True
        try:
            for combo, records, current, previous, previous_reference in zip(
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
                previous_references,
            ):
                combo.clear()
                selected_index = -1
                selected_path = (
                    str(current.path)
                    if current is not None
                    else previous if isinstance(previous, str) else None
                )
                selected_profile_id = (
                    current.profile_id
                    if current is not None
                    else (
                        previous_reference.profile_id
                        if previous_reference is not None
                        else None
                    )
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
                        combo.setItemData(
                            index,
                            ProfileSelectionReference(
                                record.profile_id,
                                record.path,
                            ),
                            _PROFILE_SELECTION_ROLE,
                        )
                        if (
                            profile_path == selected_path
                            and (
                                selected_profile_id is None
                                or record.profile_id.casefold()
                                == selected_profile_id.casefold()
                            )
                        ):
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
    def _profile_combo_reference(
        combo: QComboBox,
    ) -> ProfileSelectionReference | None:
        reference = combo.currentData(_PROFILE_SELECTION_ROLE)
        return (
            reference
            if isinstance(reference, ProfileSelectionReference)
            else None
        )

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
        if self._populating_profile_combos or (
            self.profile_match_result is None and self.profile_catalog is None
        ):
            return
        self._discard_source_preslice("profile_selection_changed")
        self._refresh_slicer_header_profiles()
        self.confirmed_profile_context = None
        self.profile_catalog_confirmation = None
        selections = {
            "machine": self._profile_combo_reference(
                self.machine_profile_combo
            ),
            "process": self._profile_combo_reference(
                self.process_profile_combo
            ),
            "filament": self._profile_combo_reference(
                self.filament_profile_combo
            ),
        }
        selected_profile_ids = {
            role: value
            for role, value in selections.items()
            if isinstance(value, ProfileSelectionReference)
        }
        self.profile_confirm_button.setText("Slicer und Profile bestätigen")
        self.profile_confirm_button.show()
        self.profile_confirm_button.setEnabled(len(selected_profile_ids) == 3)
        self._set_profile_notice()
        self._update_preparation_requirements()
        if self._profile_matching_context() is None:
            self.workflow.wait_for_profile_confirmation()
            if _changed_role == "machine":
                machine = selected_profile_ids.get("machine")
                if machine is not None:
                    self.start_profile_catalog_loading(
                        selected_machine=machine,
                        include_all_profiles=(
                            self.show_all_profiles_checkbox.isChecked()
                        ),
                    )
            return
        if _changed_role == "machine":
            machine = selected_profile_ids.get("machine")
            if machine is None:
                return
            self.profile_preview_outdated = True
            self._invalidate_preview(
                "Das Maschinenprofil wurde geändert; Filament- und "
                "Prozessprofile werden neu gefiltert."
            )
            self.start_profile_matching(
                selected_profile_ids={"machine": machine},
            )
            return
        if len(selected_profile_ids) != 3:
            return
        self.profile_preview_outdated = True
        self._invalidate_preview("Die Profilkombination wird neu geprüft.")
        self.start_profile_matching(
            selected_profile_ids=selected_profile_ids,
        )

    def _remember_profile_selection(
        self,
        role: str,
        selected_identifier: str | ProfileSelectionReference | None,
    ) -> None:
        """Persist one validated member of a successfully confirmed bundle."""

        installation = self.selected_slicer_installation
        result = self.profile_match_result or self.profile_catalog
        remember = getattr(
            self.slicer_service,
            "remember_profile_selection",
            None,
        )
        if (
            installation is None
            or result is None
            or not callable(remember)
            or not isinstance(
                selected_identifier,
                (str, ProfileSelectionReference),
            )
        ):
            return
        option_name = {
            "machine": "machine_options",
            "process": "process_options",
            "filament": "filament_options",
        }.get(role)
        if option_name is None:
            return
        selected = next(
            (
                record
                for record in getattr(result, option_name, ())
                if (
                    str(record.path).casefold()
                    == str(
                        selected_identifier.path
                        if isinstance(
                            selected_identifier,
                            ProfileSelectionReference,
                        )
                        else selected_identifier
                    ).casefold()
                    and (
                        not isinstance(
                            selected_identifier,
                            ProfileSelectionReference,
                        )
                        or record.profile_id.casefold()
                        == selected_identifier.profile_id.casefold()
                    )
                )
            ),
            None,
        )
        if selected is None:
            return
        try:
            remember(installation.identity_key, role, selected)
        except (OSError, TypeError, ValueError, RuntimeError):
            # Preference persistence must never interrupt profile validation.
            return

    def _on_show_all_profiles_toggled(self, checked: bool) -> None:
        if self.selected_slicer_installation is None:
            return
        # Changing the visible profile scope is a user decision that can
        # replace the effective profile bundle. A confirmation belonging to
        # the previously completed preparation must never authorize the next
        # Pre-Slice implicitly.
        self._discard_source_preslice("profile_filter_changed")
        self.confirmed_profile_context = None
        self.profile_catalog_confirmation = None
        self.profile_filter_label.setText(
            "Profilfilter\nAlle Maschinenprofile werden geladen …"
            if checked
            else "Profilfilter\nDruckerkompatible Profile werden ermittelt …"
        )
        current_selections = {
            "machine": self._profile_combo_reference(
                self.machine_profile_combo
            ),
            "process": self._profile_combo_reference(
                self.process_profile_combo
            ),
            "filament": self._profile_combo_reference(
                self.filament_profile_combo
            ),
        }
        selected_profile_ids = {
            role: value
            for role, value in current_selections.items()
            if isinstance(value, ProfileSelectionReference)
        }
        # A scope toggle changes the catalogue itself.  Rebuild that catalogue
        # before any source matching, so combo references and confirmation
        # validation can never belong to different inventories.
        self.start_profile_catalog_loading(
            selected_machine=selected_profile_ids.get("machine"),
            selected_profile_ids=selected_profile_ids,
            include_all_profiles=checked,
            match_source_after_loading=(
                self._profile_matching_context() is not None
            ),
        )

    def confirm_profile_selection(self) -> None:
        if not self._source_step_is_complete():
            self._set_profile_notice(
                "Bitte zuerst Schritt 1 mit einer gültigen STL abschließen.",
                state="error",
            )
            self._on_preparation_step_blocked(1)
            return
        result = self.profile_match_result
        if (
            self.profile_catalog is not None
            and not self._catalog_selection_is_confirmed()
        ):
            if not self._confirm_catalog_selection():
                return
        if result is None:
            if self._profile_matching_context() is not None:
                self.profile_confirm_button.setText(
                    "Modellanalyse wird vorbereitet …"
                )
                self.profile_confirm_button.setEnabled(False)
                self.start_profile_matching()
            return
        if not result.requires_confirmation:
            return
        if self.source_artifact is not None and not self.source_artifact.matches_current_file(
            verify_content=True
        ):
            self._set_profile_notice(
                "Die Quelldatei wurde geändert. Bitte die Datei erneut prüfen.",
                state="error",
            )
            return
        selected = result.selected
        if selected is not None and not self._draft_shield_simulation_requested:
            detected = draft_shield_source(
                selected.effective_profile, selected.resolved_profiles
            )
            if detected is not None:
                self._show_draft_shield_dialog(result, detected)
                return
        try:
            confirmation = (
                ProfileConfirmation.from_result(result, self.source_artifact)
                if self.source_artifact is not None
                else None
            )
            confirmed = self.profile_service.confirm(result)
        except (OSError, ValueError, SlicerProcessError) as error:
            self._set_profile_notice(
                "Profilzuordnung konnte nicht gespeichert werden: "
                f"{german_user_message(error)}",
                state="error",
            )
            return
        self.profile_match_result = confirmed
        for role, combo in (
            ("machine", self.machine_profile_combo),
            ("process", self.process_profile_combo),
            ("filament", self.filament_profile_combo),
        ):
            self._remember_profile_selection(
                role,
                self._profile_combo_reference(combo),
            )
        self.confirmed_profile_context = confirmation
        if self.prepared_analysis_source is not None:
            self.prepared_analysis_source = replace(
                self.prepared_analysis_source,
                slicer_version=confirmed.execution_slicer.version,
                effective_profile_fingerprint=(
                    confirmed.effective_profile_fingerprint
                ),
            )
        self._refresh_slicer_header_profiles()
        self.profile_confirm_button.setEnabled(False)
        self.profile_confirm_button.show()
        self._set_profile_notice()
        self.profile_origin_label.setText(self._profile_origin_text(confirmed))
        self.profile_origin_label.show()
        self._invalidate_preview("Die Profilzuordnung wurde bestätigt.")
        self._set_slicer_progress(
            100,
            "Slicer und Profile bestätigt",
            icon="✓",
            state="success",
        )
        if confirmed.source_kind is SourceKind.STL:
            if confirmation is None:
                self._on_source_preslice_failed(
                    self._preslice_request_id,
                    "Die Profilbestätigung konnte nicht an die STL gebunden werden.",
                    "Fehlender ProfileConfirmation-Kontext.",
                )
                return
            self.start_source_preslice()
        else:
            self.workflow.slicer_succeeded(
                confirmed.execution_slicer.display_name
            )
        self._refresh_stl_availability()
        self._update_preparation_requirements()

    def _show_draft_shield_dialog(self, result, detected) -> None:
        if self._draft_shield_dialog is not None:
            self._draft_shield_dialog.reject()
            self._draft_shield_dialog.deleteLater()
        dialog = DraftShieldDialog(detected.role, detected.profile_name, self)
        self._draft_shield_dialog = dialog
        source = self.source_artifact

        def still_current() -> bool:
            return (
                not self._closing
                and self.profile_match_result is result
                and self.source_artifact == source
            )

        def accepted() -> None:
            if still_current():
                self._draft_shield_simulation_requested = True
                self.confirm_profile_selection()

        def reload_profiles() -> None:
            if not still_current() or result.selected is None:
                return
            selected = {
                role: ProfileSelectionReference(record.profile_id, record.path)
                for role in ("machine", "filament", "process")
                if (record := getattr(result.selected, role)) is not None
            }
            self._discard_source_preslice("Profile werden erneut eingelesen")
            self.profile_catalog_confirmation = None
            self.confirmed_profile_context = None
            self.profile_match_result = None
            self.start_profile_catalog_loading(
                force_inventory=True,
                selected_profile_ids=selected,
                restore_remembered_profiles=False,
                match_source_after_loading=True,
            )

        dialog.accepted.connect(accepted)
        dialog.reload_profiles_requested.connect(reload_profiles)
        self._show_internal_dialog_without_flash(
            dialog, self._resize_draft_shield_dialog
        )

    def _resize_draft_shield_dialog(self) -> None:
        dialog = self._draft_shield_dialog
        if dialog is None or not dialog.isVisible():
            return
        screen = dialog.screen() or self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            dialog.resize(min(640, available.width() - 40), min(571, available.height() - 40))
        self._place_dialog_centered(dialog)

    def start_source_preslice(self, *, simulate_supports: bool = False) -> None:
        validation = self.stl_validation_result
        profile_match = self.profile_match_result
        confirmation = self.confirmed_profile_context
        if (
            not self._source_step_is_complete()
            or validation is None
            or profile_match is None
            or not profile_match.user_confirmed
            or confirmation is None
        ):
            self._set_profile_notice(
                "Der Pre-Slice benötigt eine gültige STL und vollständig "
                "bestätigte Profile.",
                state="error",
            )
            return
        try:
            adapter = self.slicer_service.adapter_for(
                profile_match.execution_slicer
            )
        except Exception as error:
            self._preslice_request_id += 1
            self._on_source_preslice_failed(
                self._preslice_request_id,
                str(error),
                f"{type(error).__name__}: {error}",
            )
            return

        self._discard_source_preslice("preslice_replaced")
        self._preslice_request_id += 1
        request_id = self._preslice_request_id
        self.workflow.begin_preslice()
        self._start_preslice_runtime_watchdog(request_id)
        self.preslice_cancel_button.setEnabled(True)
        self.preslice_cancel_button.setText("Pre-Slice abbrechen")
        self.preslice_cancel_button.show()
        self._set_preslice_activity(
            True,
            "Preslice läuft · der Slicer wird im Hintergrund vorbereitet …",
            percent=0,
        )
        self._refresh_dynamic_preparation_layout()
        self._set_main_status(
            "Slicer wird vorbereitet …",
            icon="⏳",
            state="running",
        )
        worker = SourcePreSliceWorker(
            request_id,
            self.preslice_service,
            validation,
            profile_match,
            confirmation,
            adapter,
            simulate_supports=simulate_supports,
            simulate_draft_shield=self._draft_shield_simulation_requested,
        )
        worker.support_simulation_available.connect(self._on_support_simulation_available)
        worker.progress.connect(self._on_source_preslice_progress)
        worker.succeeded.connect(self._on_source_preslice_succeeded)
        worker.failed.connect(self._on_source_preslice_failed)
        worker.cancelled.connect(self._on_source_preslice_cancelled)
        self.background_job_manager.start_job(
            kind=JobKind.PRESLICE,
            request_id=request_id,
            worker=worker,
        )

    def cancel_source_preslice(self) -> None:
        if (
            self._preslice_cancel_requested
            or not self.background_job_manager.has_active(JobKind.PRESLICE)
        ):
            return
        request_id = self._preslice_request_id
        self._preslice_cancel_requested = True
        self._preslice_progress_base_format = _PRESLICE_CANCEL_FORMAT
        self.preslice_cancel_button.setText("Abbruch wird ausgeführt …")
        self.preslice_cancel_button.setEnabled(False)
        self._set_preslice_activity(
            True,
            "Preslice wird kontrolliert abgebrochen …",
            percent=self.profile_confirmation_progress.value(),
        )
        self.profile_confirmation_progress.update()
        self.preslice_cancel_button.update()
        self._queue_preslice_cancellation(
            request_id,
            reason="preslice_cancelled_by_user",
        )

    @Slot(int, int, str, bool)
    def _on_source_preslice_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
        _busy: bool,
    ) -> None:
        if request_id != self._preslice_request_id:
            return
        if self._preslice_cancel_requested:
            return
        if (
            percent >= 70
            and self.workflow.stage is WorkflowStage.PRESLICING_MODEL
        ):
            self.workflow.begin_preslice_analysis()
        rendered = german_user_message(status)
        self._set_preslice_activity(
            True,
            f"Preslice läuft · {rendered}",
            percent=percent,
        )
        self._set_main_status(rendered, icon="⏳", state="running")

    @Slot(int, object)
    def _on_source_preslice_succeeded(
        self,
        request_id: int,
        result: SourcePreSliceResult,
    ) -> None:
        if request_id != self._preslice_request_id or self._closing:
            result.cleanup()
            return
        artifact = self.source_artifact
        confirmation = self.confirmed_profile_context
        if (
            self.current_source_kind is not SourceKind.STL
            or artifact is None
            or confirmation is None
            or result.prepared_source.source_artifact != artifact
            or not confirmation.matches_source(artifact)
            or not artifact.matches_current_file(verify_content=True)
            or not result.prepared_source.matches_analysis_gcode()
        ):
            result.cleanup()
            self._on_source_preslice_failed(
                request_id,
                "Das Pre-Slice-Ergebnis ist nicht mehr der aktuellen Quelle "
                "und Profilauswahl zugeordnet.",
                "Veraltetes oder nachträglich verändertes Pre-Slice-Ergebnis.",
            )
            return
        self._cleanup_source_preslice_result()
        self.source_preslice_result = result
        self.prepared_analysis_source = result.prepared_source
        self.current_gcode_path = result.prepared_source.analysis_gcode_path
        self._analysis_failed = False
        self._workflow_error_message = None
        self._stop_preslice_runtime_watchdog()
        self._preslice_timeout_request_id = None
        self.preslice_cancel_button.hide()
        self._set_preslice_activity(False)
        self._set_slicer_progress(
            100,
            "Modellanalyse mit Slicer abgeschlossen",
            icon="✓",
            state="success",
        )
        self._clear_stl_validation_details()
        snapshot = result.analysis_snapshot
        self._adopt_common_analysis_snapshot(snapshot)
        self._show_reconstructed_configuration(snapshot)
        profile_match = self.profile_match_result
        slicer_summary = (
            profile_match.execution_slicer.display_name
            if profile_match is not None
            else "Pre-Slice abgeschlossen"
        )
        source_name = artifact.original_path.name
        self.slicer_group.set_state(SectionState.SUCCESS)
        self._update_preparation_requirements()
        self.workflow.preslice_succeeded(
            f"{source_name} · automatisch geslict · {snapshot.layer_count} Layer",
            slicer_summary,
        )
        self._set_main_status(
            f"{snapshot.layer_count} Layer aus der STL analysiert · "
            f"ermittelte Modellhöhe {snapshot.maximum_print_z_mm:.3f} mm",
            icon="✓",
            state="success",
        )
        self._refresh_stl_availability()
        self._finish_preparation()
        self._show_original_object_preview()
        self._update_expansion_angle_warning()

    @Slot(int, str, str)
    def _on_source_preslice_failed(
        self,
        request_id: int,
        message: str,
        details: str,
    ) -> None:
        if request_id != self._preslice_request_id or self._closing:
            return
        confirmation = self.confirmed_profile_context
        self.current_gcode_path = None
        self.analysis_snapshot = None
        self._refresh_target_time_hint()
        self.prepared_analysis_source = None
        self._analysis_failed = True
        rendered = german_user_message(message)
        self._workflow_error_message = rendered
        self._stop_preslice_runtime_watchdog()
        self._preslice_timeout_request_id = None
        self.preslice_cancel_button.hide()
        self._set_preslice_activity(False)
        self._set_slicer_progress(
            100,
            "Modellanalyse mit Slicer fehlgeschlagen",
            icon="✕",
            state="error",
        )
        self._set_profile_notice(
            "Das Modell konnte mit den bestätigten Einstellungen nicht "
            f"sicher analysiert werden. {rendered}",
            state="error",
        )
        self.profile_diagnostics.setPlainText(details)
        self.workflow.preslice_failed("Pre-Slice fehlgeschlagen")
        self._set_main_status(
            "Pre-Slice fehlgeschlagen",
            icon="✕",
            state="error",
        )
        self._reset_preslice_confirmation_for_retry(rendered)
        self._update_preparation_requirements()
        self.validate_form()
        if self._support_simulation_offer_id == request_id and confirmation is not None:
            self._show_support_simulation_dialog(request_id, confirmation)

    @Slot(int)
    def _on_support_simulation_available(self, request_id: int) -> None:
        if request_id == self._preslice_request_id and not self._closing:
            self._support_simulation_offer_id = request_id

    def _show_support_simulation_dialog(self, request_id, confirmation) -> None:
        if self._support_simulation_dialog is not None:
            self._support_simulation_dialog.reject()
            self._support_simulation_dialog.deleteLater()
        dialog = SupportSimulationDialog(self)
        self._support_simulation_dialog = dialog
        source = self.source_artifact
        match = self.profile_match_result

        def accepted():
            if (self._closing or request_id != self._preslice_request_id
                    or source != self.source_artifact or match is not self.profile_match_result):
                return
            self._pending_support_retry = (request_id, confirmation, match)
            self._start_pending_support_retry()

        def reload_profiles():
            if (self._closing or request_id != self._preslice_request_id
                    or source != self.source_artifact or match is not self.profile_match_result):
                return
            profile = match.selected
            selected = {
                role: ProfileSelectionReference(record.profile_id, record.path)
                for role in ("machine", "filament", "process")
                if (record := getattr(profile, role)) is not None
            }
            self._discard_source_preslice("Profile werden erneut eingelesen")
            self.profile_catalog_confirmation = None
            self.confirmed_profile_context = None
            self._workflow_error_message = None
            self._analysis_failed = False
            self.profile_match_result = None
            self.workflow.begin_profile_matching()
            self.profile_confirm_button.setEnabled(False)
            self._set_profile_notice()
            self.profile_diagnostics.clear()
            self._set_main_status("Profile werden erneut eingelesen", icon="⌛", state="running")
            self._set_slicer_progress(0, "Profile werden erneut eingelesen …", icon="⌛", state="running")
            self._pending_support_profile_reload = (self._preslice_request_id, source, selected)
            self._start_pending_support_retry()
            self.validate_form()

        dialog.accepted.connect(accepted)
        dialog.reload_profiles_requested.connect(reload_profiles)
        self._show_internal_dialog_without_flash(dialog, self._resize_support_simulation_dialog)

    def _resize_support_simulation_dialog(self) -> None:
        dialog = self._support_simulation_dialog
        if dialog is None or not dialog.isVisible():
            return
        screen = dialog.screen() or self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            dialog.resize(min(640, available.width() - 40), min(571, available.height() - 40))
        self._place_dialog_centered(dialog)

    def _start_pending_support_retry(self) -> None:
        reload_pending = self._pending_support_profile_reload
        if reload_pending is not None and not self.background_job_manager.has_active(JobKind.PRESLICE):
            self._pending_support_profile_reload = None
            request_id, source, selected = reload_pending
            if (not self._closing and request_id == self._preslice_request_id
                    and source == self.source_artifact):
                self.start_profile_catalog_loading(
                    force_inventory=True, selected_profile_ids=selected,
                    restore_remembered_profiles=False, match_source_after_loading=False,
                )
        pending = self._pending_support_retry
        if pending is None or self.background_job_manager.has_active(JobKind.PRESLICE):
            return
        self._pending_support_retry = None
        request_id, confirmation, match = pending
        if (self._closing or request_id != self._preslice_request_id
                or self.profile_match_result is not match or self.source_artifact is None
                or not confirmation.matches_source(self.source_artifact)):
            return
        self.profile_match_result = replace(match, user_confirmed=True, requires_confirmation=False)
        self.confirmed_profile_context = confirmation
        self._workflow_error_message = None
        self._analysis_failed = False
        self._set_profile_notice()
        self.profile_diagnostics.clear()
        self.start_source_preslice(simulate_supports=True)
        self.validate_form()

    @Slot(int)
    def _on_source_preslice_cancelled(self, request_id: int) -> None:
        if request_id != self._preslice_request_id or self._closing:
            return
        timed_out = self._preslice_timeout_request_id == request_id
        self._stop_preslice_runtime_watchdog()
        self._preslice_timeout_request_id = None
        self.current_gcode_path = None
        self.analysis_snapshot = None
        self._refresh_target_time_hint()
        self.prepared_analysis_source = None
        self.preslice_cancel_button.hide()
        self._set_preslice_activity(False)
        self._set_slicer_progress(
            0,
            (
                "Pre-Slice nach 8 Minuten automatisch abgebrochen"
                if timed_out
                else "Pre-Slice wurde abgebrochen"
            ),
            icon="✕" if timed_out else "○",
            state="error" if timed_out else "pending",
        )
        cancellation_message = (
            "Der Pre-Slice wurde automatisch abgebrochen, weil die maximale "
            "Laufzeit von 8 Minuten überschritten wurde."
            if timed_out
            else "Der Pre-Slice wurde abgebrochen."
        )
        self._workflow_error_message = cancellation_message if timed_out else None
        self.workflow.preslice_failed(
            "Zeitlimit des Pre-Slices überschritten"
            if timed_out
            else "Pre-Slice abgebrochen"
        )
        self._reset_preslice_confirmation_for_retry(cancellation_message)
        self._set_main_status(
            (
                "Pre-Slice wegen Zeitüberschreitung abgebrochen"
                if timed_out
                else "Pre-Slice abgebrochen"
            ),
            icon="✕" if timed_out else "○",
            state="error" if timed_out else "idle",
        )
        self._update_preparation_requirements()
        self.validate_form()

    def _reset_preslice_confirmation_for_retry(self, message: str) -> None:
        result = self.profile_match_result
        if result is not None and result.source_kind is SourceKind.STL:
            self.profile_match_result = replace(
                result,
                user_confirmed=False,
                requires_confirmation=True,
            )
            self.confirmed_profile_context = None
            self.profile_confirm_button.setText(
                "Slicer und Profile bestätigen"
            )
            self.profile_confirm_button.setEnabled(True)
            self.profile_confirm_button.show()
            self._set_profile_notice(message, state="error")
            self.workflow.begin_profile_matching()
            self.workflow.wait_for_profile_confirmation()

    def _cleanup_source_preslice_result(self) -> None:
        result = self.source_preslice_result
        self.source_preslice_result = None
        if result is not None:
            result.cleanup()

    def _discard_source_preslice(self, reason: str) -> None:
        self._excluded_layer_ranges = ()
        self._layer_range_silhouette = None
        if self._layer_range_dialog is not None:
            self._layer_range_dialog.close()
        if reason != "preslice_replaced":
            self._draft_shield_simulation_requested = False
        if self._draft_shield_dialog is not None and self._draft_shield_dialog.isVisible():
            self._draft_shield_dialog.reject()
        self._discard_generated_tower()
        self._pending_support_retry = None
        self._pending_support_profile_reload = None
        self._support_simulation_offer_id = None
        if self._support_simulation_dialog is not None:
            self._support_simulation_dialog.reject()
        if not hasattr(self, "background_job_manager"):
            return
        self._stop_preslice_runtime_watchdog()
        self._preslice_timeout_request_id = None
        had_preslice = bool(
            self.source_preslice_result is not None
            or self.background_job_manager.has_active(JobKind.PRESLICE)
        )
        self._preslice_request_id += 1
        self.background_job_manager.cancel_jobs(
            JobKind.PRESLICE,
            reason=reason,
        )
        self._cleanup_source_preslice_result()
        self.prepared_analysis_source = None
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.set_scene(None)
            self._preview_dialog.mark_stale()
        if hasattr(self, "generation_intro_label"):
            self.generation_intro_label.setText(
                "Noch kein Kühlturm generiert. Starten Sie die Generierung, "
                "um den Fortschritt und das Ergebnis hier zu sehen."
            )
            self.generation_intro_label.show()
        if hasattr(self, "maximum_expansion_angle_setting"):
            self._update_expansion_angle_warning()
        if had_preslice and self.current_source_kind is SourceKind.STL:
            self.current_gcode_path = None
            self.analysis_snapshot = None
            self.tower_assessment = None
            self.profile_feasibility = None
            self._clear_feasibility_issues()
            self._refresh_target_time_hint()
        if hasattr(self, "preslice_cancel_button"):
            self.preslice_cancel_button.hide()
        if hasattr(self, "profile_confirmation_stack"):
            self._set_preslice_activity(False)
        self._refresh_layer_range_tool()

    def _show_original_object_preview(self) -> None:
        self._refresh_layer_range_tool()
        preslice = self.source_preslice_result
        snapshot = self.analysis_snapshot
        profile_match = self.profile_match_result
        if (
            preslice is None or preslice.preview_source_data is None
            or snapshot is None or profile_match is None
            or profile_match.selected is None or self._preview_dialog is None
        ):
            return
        data = preslice.preview_source_data
        geometry = parse_bed_geometry(
            profile_match.selected.effective_profile.effective_values
        )
        occupied = data.occupied_bounds
        bed = geometry.bounds if geometry is not None else BedBounds(
            occupied.minimum_x_mm - 10.0,
            occupied.maximum_x_mm + 10.0,
            occupied.minimum_y_mm - 10.0,
            occupied.maximum_y_mm + 10.0,
        )
        scene = PreviewScene(
            object_segments=data.object_segments,
            tower_segments=(),
            bed_bounds=bed,
            tower_center_xy_mm=(0.0, 0.0),
            source_segment_count=data.source_segment_count,
            displayed_segment_count=len(data.object_segments),
            tower_height_mm=0.0,
            object_height_mm=float(snapshot.maximum_print_z_mm),
            object_layer_count=int(snapshot.layer_count),
            tower_layer_count=0,
        )
        self._preview_dialog.set_original_object(scene)
        self.generation_intro_label.setText(
            "Die Vorschau zeigt derzeit nur das übergebene Originalobjekt, "
            "da noch kein Kühlturm generiert wurde."
        )
        self.generation_intro_label.show()
        self._refresh_ready_grid_layout()

    def _discard_generated_tower(self) -> None:
        if not hasattr(self, "current_preview"):
            return
        self._preview_request_id += 1
        if hasattr(self, "background_job_manager"):
            self.background_job_manager.cancel_jobs(
                JobKind.PREVIEW, reason="preparation_changed"
            )
        self._cancel_generation_phase_transition()
        if self.current_preview is not None:
            dispose = getattr(self.current_preview, "dispose", None)
            if callable(dispose):
                dispose()
            self.current_preview = None
        self.preview_state = PreviewState.EMPTY
        self._preview_cancel_requested = False
        self._last_exported_preview_identity = None
        self.manual_controller.invalidate_context()
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.set_scene(None)
            self._preview_dialog.mark_stale()
            self._show_original_object_preview()
        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.hide()
        if hasattr(self, "generation_intro_label"):
            if self._preview_dialog is None or self._preview_dialog.canvas.scene is None:
                self.generation_intro_label.setText(
                    "Noch kein Kühlturm generiert. Starten Sie die Generierung, "
                    "um den Fortschritt und das Ergebnis hier zu sehen."
                )
            self.generation_intro_label.show()
        if hasattr(self, "preview_hint_label"):
            self.preview_hint_label.hide()
        if hasattr(self, "result_label"):
            self._clear_result_notices()

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

    @Slot(int)
    def _on_profile_inventory_unchanged(self, request_id: int) -> None:
        if request_id != self._profile_request_id:
            return

    @Slot(int, str, str)
    def _on_profile_matching_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._profile_request_id:
            return
        self._set_profile_notice(
            "Profilzuordnung konnte nicht geprüft werden: "
            f"{german_user_message(message)}",
            state="error",
        )
        self.profile_origin_label.hide()
        self.profile_diagnostics.hide()
        self._set_slicer_progress(
            100,
            "Slicer-Profile konnten nicht geprüft werden",
            icon="✕",
            state="error",
        )
        self.workflow.required_slicer_unavailable(
            "Slicer-Profile konnten nicht geprüft werden"
        )
        self._show_confirmed_profiles_analysis_action()

    @Slot(object)
    def _on_background_job_released(self, job: BackgroundJob) -> None:
        """React only after the manager has observed the native thread end."""

        finished_kind = job.kind
        if finished_kind == JobKind.PRESLICE:
            self._start_pending_support_retry()

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
        elif finished_kind in {"slicer", "profile"} and not (
            self.background_job_manager.has_active(JobKind.SLICER_DISCOVERY)
            or self.background_job_manager.has_active(JobKind.PROFILE_MATCH)
        ):
            pending = self._pending_profile_match
            self._pending_profile_match = None
            if pending is not None:
                pending_adapter_work_started = True
                if bool(pending.get("catalog_only", False)):
                    QTimer.singleShot(
                        0,
                        lambda: self.start_profile_catalog_loading(
                            force_inventory=bool(
                                pending.get("force_inventory", False)
                            ),
                            selected_machine=pending.get(
                                "selected_machine"
                            ),
                            selected_profile_ids=dict(
                                pending.get("selected_profile_ids", {}) or {}
                            ),
                            include_all_profiles=pending.get(
                                "include_all_profiles"
                            ),
                            prefer_active_presets=bool(
                                pending.get("prefer_active_presets", False)
                            ),
                            restore_remembered_profiles=bool(
                                pending.get("restore_remembered_profiles", True)
                            ),
                            match_source_after_loading=bool(
                                pending.get(
                                    "match_source_after_loading",
                                    False,
                                )
                            ),
                        ),
                    )
                else:
                    QTimer.singleShot(
                        0,
                        lambda: self.start_profile_matching(
                            selected_profile_ids=pending[
                                "selected_profile_ids"
                            ],
                            force_inventory=bool(pending["force_inventory"]),
                            stale_check_only=bool(
                                pending["stale_check_only"]
                            ),
                            include_all_profiles=bool(
                                pending["include_all_profiles"]
                            ),
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
            self.profile_confirm_button.show()
        elif section == "stability":
            self._setting_widgets["manual_base_width_mm"].show()
            self.automatic_base_width_label.hide()
            self.automatic_base_reset_button.setVisible(True)
            self.automatic_base_error_label.setVisible(
                bool(self.automatic_base_error_label.text().strip())
            )
        elif section == "geometry_settings":
            self._sync_collapsible_content("stability", True)

    def _refresh_geometry_section_layout(
        self,
        expanded: bool,
        *,
        _second_pass: bool = False,
    ) -> None:
        """Publish the complete single-column geometry-card size."""

        self.geometry_settings_group.setMinimumHeight(0)
        self.geometry_settings_group.setMaximumHeight(16777215)
        self.geometry_settings_group.content_widget.setMinimumHeight(0)
        self.geometry_settings_group.content_widget.setMaximumHeight(16777215)
        self.geometry_split.setMinimumHeight(0)
        self.geometry_split.setMaximumHeight(16777215)
        for subsection in (
            self.timing_group,
            self.geometry_group,
            self.stability_group,
            self.overhang_group,
            self.geometry_calculation_section,
        ):
            subsection.setMinimumHeight(0)
            subsection.setMaximumHeight(16777215)
            if isinstance(subsection, SectionCard):
                subsection.content_widget.setMinimumHeight(0)
                subsection.content_widget.setMaximumHeight(16777215)
        self.timing_group.content_layout.setContentsMargins(20, 10, 20, 10)
        self.geometry_fields_layout.setContentsMargins(20, 10, 20, 10)
        self.stability_fields_layout.setContentsMargins(20, 10, 20, 10)
        self.overhang_fields_layout.setContentsMargins(20, 10, 20, 10)
        self.geometry_calculation_body_layout.setContentsMargins(
            20, 4, 20, 10
        )
        for nested_layout in (
            self.timing_group.content_layout,
            self.geometry_fields_layout,
            self.stability_fields_layout,
            self.overhang_fields_layout,
            self.geometry_calculation_body_layout,
            self.geometry_split_layout,
        ):
            nested_layout.invalidate()
            nested_layout.activate()
        for subsection in (self.timing_group, self.geometry_group):
            body = subsection.content_widget
            body_layout = subsection.content_layout
            # This card already computes each row's height from its live width.
            # Qt's box layout can retain old positions after several rows gain
            # wrapped feedback at once, so place these rows from that same
            # measurement instead of letting stale geometry overlap controls.
            body_layout.setEnabled(False)
            required = self._visible_vbox_height(body_layout, body.width())
            body.setFixedHeight(max(0, required))
            self._position_visible_vbox_children(body_layout, body.width())
            body.updateGeometry()
            subsection.layout().invalidate()
            subsection.layout().activate()
            subsection.updateGeometry()
        # The split layout may still cache its previous fixed height while
        # range hints are being hidden. Measure the two visible cards directly.
        split_height = (
            self.timing_group.sizeHint().height()
            + self.geometry_group.sizeHint().height()
            + self.geometry_split_layout.spacing()
        )
        self.geometry_split.setFixedHeight(max(0, split_height))
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
        # Hiding a wrapped hint can change the available body width only after
        # the parent card has been laid out. Re-measure once at that final width
        # so the section shrinks immediately as well as growing immediately.
        if not _second_pass and any(
            subsection.content_widget.height()
            != self._visible_vbox_height(
                subsection.content_layout, subsection.content_widget.width()
            )
            for subsection in (self.timing_group, self.geometry_group)
        ):
            self._refresh_geometry_section_layout(expanded, _second_pass=True)

    @staticmethod
    def _visible_vbox_height(layout: QVBoxLayout, width: int) -> int:
        """Measure live child heights without Qt's stale height-for-width cache."""

        margins = layout.contentsMargins()
        child_width = max(1, width - margins.left() - margins.right())
        heights: list[int] = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None or item.isEmpty():
                continue
            heights.append(MainWindow._visible_vbox_item_height(item, child_width))
        return (
            margins.top()
            + margins.bottom()
            + sum(heights)
            + layout.spacing() * max(0, len(heights) - 1)
        )

    @staticmethod
    def _visible_vbox_item_height(item: QLayoutItem, width: int) -> int:
        widget = item.widget()
        if widget is not None:
            preferred = (
                widget.heightForWidth(width)
                if widget.hasHeightForWidth()
                else widget.sizeHint().height()
            )
            height = min(widget.maximumHeight(), max(widget.minimumHeight(), preferred))
        else:
            height = (
                item.heightForWidth(width)
                if item.hasHeightForWidth()
                else item.sizeHint().height()
            )
        return max(0, height)

    @staticmethod
    def _position_visible_vbox_children(layout: QVBoxLayout, width: int) -> None:
        """Place rows at the measured offsets, including wrapped feedback."""

        margins = layout.contentsMargins()
        child_width = max(1, width - margins.left() - margins.right())
        y = margins.top()
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None or item.isEmpty():
                continue
            height = MainWindow._visible_vbox_item_height(item, child_width)
            item.setGeometry(QRect(margins.left(), y, child_width, height))
            y += height + layout.spacing()

    def _refresh_slicer_section_layout(self, _expanded: bool | None = None) -> None:
        """Publish the current Slicer height without retaining stale minima."""

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
        self._update_slicer_combo_widths()
        if hasattr(self, "preparation_tabs"):
            self.preparation_tabs.updateGeometry()
        self._refresh_settings_content_minimum_height()

    def _refresh_preparation_section_layout(
        self,
        _expanded: bool | None = None,
    ) -> None:
        """Synchronise the shared prerequisite card after layout changes."""

        if not hasattr(self, "preparation_tabs"):
            return
        # QStackedWidget normally lays out only its visible page. Keep the
        # hidden target step at the same responsive page size as the current
        # one, so controls already own the correct width when a transition is
        # captured or the window is narrowed before step 2 is unlocked.
        current_page = self.preparation_tabs.currentWidget()
        if current_page is not None and current_page.width() > 0:
            current_page_size = current_page.size()
            for page_index in range(self.preparation_tabs.count()):
                step_page = self.preparation_tabs.widget(page_index)
                if step_page is not current_page:
                    step_page.resize(current_page_size)
                if step_page.layout() is not None:
                    step_page.layout().setGeometry(step_page.rect())
                if page_index < len(self.preparation_step_shells):
                    step_shell = self.preparation_step_shells[page_index]
                    if step_shell.layout() is not None:
                        step_shell.layout().setGeometry(step_shell.rect())
        for index in range(len(self.preparation_step_intro_layouts)):
            self._balance_preparation_step_intro(index)
        for card in (self.source_group, self.slicer_group):
            card.setMinimumHeight(0)
            card.setMaximumHeight(16777215)
            card.content_widget.setMinimumHeight(0)
            if card.layout() is not None:
                card.layout().setGeometry(card.rect())
            card.content_layout.setGeometry(card.content_widget.rect())
            card.content_layout.invalidate()
            card.content_layout.activate()
            card.updateGeometry()
        self.slicer_columns.refresh_layout()
        self.slicer_columns.grid.setGeometry(self.slicer_columns.rect())
        self.slicer_selectors_layout.setGeometry(
            self.slicer_selector_column.contentsRect()
        )
        self.preparation_requirements.setMinimumHeight(0)
        self.preparation_requirements.setMaximumHeight(16777215)
        self.preparation_requirements.refresh_layout()
        self.preparation_requirements.grid.invalidate()
        self.preparation_requirements.grid.activate()
        requirements_height = (
            self.preparation_requirements.content_height_hint()
        )
        # The navigation owns exactly the height of its visible cards.  A
        # minimum-only constraint allowed the expanding preparation body to
        # leave an empty band below the cards and pushed the following step
        # introduction down when switching back to the shorter STL page.
        self.preparation_requirements.setFixedHeight(
            max(0, requirements_height)
        )
        self.preparation_requirements.updateGeometry()
        self.preparation_overview.layout().invalidate()
        self.preparation_overview.layout().activate()
        overview_height = self.preparation_overview.layout().sizeHint().height()
        self.preparation_overview.setFixedHeight(max(0, overview_height))
        self.preparation_overview_host.setFixedHeight(max(0, overview_height))
        self.preparation_overview.updateGeometry()
        # Every view rendered inside either white preparation card uses one
        # stable inset.  State changes may alter the visible children, but
        # never the distance between those children and the card outline.
        self.source_group.content_layout.setContentsMargins(20, 20, 20, 20)
        self.slicer_group.content_layout.setContentsMargins(20, 20, 20, 20)
        for card in (self.source_group, self.slicer_group):
            card.content_layout.invalidate()
            card.content_layout.activate()
            margins = card.content_layout.contentsMargins()
            available_width = max(
                1,
                card.content_widget.width()
                - margins.left()
                - margins.right(),
            )
            visible_children = [
                card.content_layout.itemAt(index).widget()
                for index in range(card.content_layout.count())
                if (
                    card.content_layout.itemAt(index).widget() is not None
                    and not card.content_layout.itemAt(index)
                    .widget()
                    .isHidden()
                )
            ]
            child_heights = []
            for child in visible_children:
                preferred_height = (
                    child.heightForWidth(available_width)
                    if child.hasHeightForWidth()
                    else child.sizeHint().height()
                )
                child_heights.append(
                    max(
                        0,
                        child.minimumHeight(),
                        child.minimumSizeHint().height(),
                        preferred_height,
                    )
                )
            body_height = (
                margins.top()
                + margins.bottom()
                + sum(child_heights)
                + card.content_layout.spacing()
                * max(0, len(child_heights) - 1)
            )
            card.setFixedHeight(body_height + card.frameWidth() * 2)
            card_layout = card.layout()
            if card_layout is not None:
                card_layout.invalidate()
                card_layout.setGeometry(card.rect())
                card_layout.activate()
            # The root layout assigns the resized body geometry. Activate the
            # child layout only afterwards; otherwise a newly visible error
            # message can retain the smaller pre-validation body rectangle
            # and squeeze the drop-zone below its own minimum height.
            card.content_layout.invalidate()
            card.content_layout.setGeometry(card.content_widget.rect())
            card.content_layout.activate()
        # Card heights can change while the target step is still hidden.
        # Re-run every page layout after those heights are final so the
        # transition snapshot receives the same centred introduction as the
        # visible page instead of stale child geometry from the first pass.
        for step_page in self.preparation_tab_pages:
            page_layout = step_page.layout()
            if page_layout is not None:
                page_layout.invalidate()
                page_layout.activate()
                page_layout.setGeometry(step_page.rect())
        for shell_index, shell in enumerate(self.preparation_step_shells):
            if shell.layout() is not None:
                shell.layout().invalidate()
                shell.layout().activate()
                shell.layout().setGeometry(shell.rect())
            if shell_index < len(self.preparation_step_intro_layouts):
                intro_layout = self.preparation_step_intro_layouts[shell_index]
                intro_layout.invalidate()
                intro_layout.activate()
                if intro_layout.parentWidget() is not None:
                    intro_layout.setGeometry(intro_layout.parentWidget().rect())
            shell.updateGeometry()
        self.slicer_columns.grid.setGeometry(self.slicer_columns.rect())
        self.slicer_selectors_layout.setGeometry(
            self.slicer_selector_column.contentsRect()
        )
        page = self.preparation_tabs.currentWidget()
        if page is not None and page.layout() is not None:
            page.layout().invalidate()
            page.layout().activate()
            page.updateGeometry()
            # The native tab bar is intentionally hidden because the visible
            # step cards above replace it.  Reserving its size hint still
            # added an invisible row and made the main scrollbar appear
            # before any visible preparation content reached the viewport.
            tab_height = 0
            page_layout = page.layout()
            page_height = (
                page_layout.heightForWidth(max(1, page.width()))
                if page_layout.hasHeightForWidth()
                else page_layout.sizeHint().height()
            )
            self.preparation_tabs.setFixedHeight(
                max(0, tab_height + page_height + 4)
            )
        self.preparation_tabs.updateGeometry()
        self.workflow_group.content_layout.invalidate()
        self.workflow_group.content_layout.activate()
        self.workflow_group.content_widget.updateGeometry()
        self.workflow_group.updateGeometry()
        self._update_slicer_combo_widths()
        self._refresh_settings_content_minimum_height()

    def _refresh_dynamic_preparation_layout(self) -> None:
        """Publish dynamic preparation content before the next paint frame."""

        if not hasattr(self, "preparation_tabs"):
            return
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)

    def _on_settings_scroll_range_changed(
        self,
        _minimum: int,
        _maximum: int,
    ) -> None:
        self._refresh_header_scroll_border()
        self._update_slicer_combo_widths()
        QTimer.singleShot(0, self._update_slicer_combo_widths)

    def _refresh_header_scroll_border(self) -> None:
        scrollbar = self.settings_scroll.verticalScrollBar()
        scrolled = (
            scrollbar.maximum() > scrollbar.minimum()
            and scrollbar.value() > scrollbar.minimum()
        )
        if self._set_boolean_style_property(self.main_header, "scrolled", scrolled):
            self.main_header.update()

    def _refresh_ready_grid_layout(self) -> None:
        """Refresh the shared grid without changing any sibling card state."""

        self.ready_grid.setMinimumHeight(0)
        self.ready_grid.setMaximumHeight(16777215)
        self.ready_grid.refresh_layout()
        self.ready_grid.grid.invalidate()
        # A first height query can still contain a child's old geometry when
        # the first joint result reveals the preview and changes several labels
        # at once. Applying that height lays out the children; measure again so
        # the temporary surplus is not retained below the preview card.
        for _ in range(3):
            required_grid_height = self.ready_grid.content_height_hint()
            if required_grid_height <= 0:
                break
            self.ready_grid.setFixedHeight(required_grid_height)
            self.ready_grid.grid.activate()
            if self.ready_grid.content_height_hint() == required_grid_height:
                break
        self.ready_grid.grid.activate()
        self.ready_grid.updateGeometry()
        # The method navigation adds a parent layout with its own cached
        # height-for-width. Refresh it before measuring the scroll content,
        # then settle its minimum once the new column widths have been applied.
        self.generation_workspace.layout().invalidate()
        self.generation_workspace.layout().activate()
        self.generation_workspace.updateGeometry()
        self._refresh_settings_content_minimum_height()
        if self.ready_grid.isVisible():
            QTimer.singleShot(0, self._refresh_settings_content_minimum_height)

    def _refresh_settings_content_minimum_height(self) -> None:
        content = self.settings_scroll.widget()
        if content is None:
            return
        # Drop the former cached preferred height before asking the layout for
        # its true non-overlapping minimum. QScrollArea expands a resizable
        # child to its viewport on its own; only this minimum may create a
        # vertical range when a small window would otherwise clip controls.
        if content.minimumHeight() != 0:
            content.setMinimumHeight(0)
        content.updateGeometry()
        layout = content.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            # Keep the full 22 px lower page margin whenever there is room.
            # While preparation is unfinished that decorative margin may
            # shrink before a scrollbar is introduced: scrolling begins only
            # when a visible control/card would otherwise be clipped, not
            # merely because empty breathing space no longer fits.
            workflow = getattr(self, "workflow", None)
            preparation_incomplete = (
                workflow is None
                or workflow.stage is not WorkflowStage.READY
            )
            margins = layout.contentsMargins()
            standard_bottom = getattr(
                self,
                "_settings_content_bottom_margin_px",
                margins.bottom(),
            )
            target_bottom = standard_bottom
            if preparation_incomplete:
                required_without_bottom = max(
                    0,
                    layout.minimumSize().height() - margins.bottom(),
                )
                target_bottom = min(
                    standard_bottom,
                    max(
                        0,
                        self.settings_scroll.viewport().height()
                        - required_without_bottom,
                    ),
                )
            if margins.bottom() != target_bottom:
                layout.setContentsMargins(
                    margins.left(),
                    margins.top(),
                    margins.right(),
                    target_bottom,
                )
                layout.invalidate()
                layout.activate()
            required_height = max(0, layout.minimumSize().height())
            if content.minimumHeight() != required_height:
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
        prominent = text in {
            "Bitte STL auswählen",
        }
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
        self.footer_notice_host.setVisible(bool(active_panels) and self.generation_mode is not GenerationMode.MANUAL)
        if hasattr(self, "footer_status_layout"):
            self.footer_status_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_notice_layout.invalidate()
        self.footer_notice_layout.activate()

    def _refresh_footer_auxiliary_visibility(self) -> None:
        """Show the right footer column and separator only with real content."""

        if not hasattr(self, "footer_action_area"):
            return
        if hasattr(self,"manual_footer_status_widget"):
            manual = self.generation_mode is GenerationMode.MANUAL
            self.footer_message_layout.setSpacing(5 if manual else 8)
            self.footer_content_grid.setAlignment(self.footer_message_area,
                                                  Qt.AlignmentFlag.AlignBottom if manual else Qt.AlignmentFlag.AlignTop)
            self.tower_reset_button.setVisible(manual)
            self.manual_controller.update_scrollbar_policy(manual)
            self.manual_controller.sync_footer_content_visibility()
            saved = getattr(self,"_automatic_footer_status_hidden_before_manual",None)
            if manual:
                if saved is None:
                    self._automatic_footer_status_hidden_before_manual = self.footer_status_widget.isHidden()
                self.footer_status_widget.hide()
            elif saved is not None:
                self.footer_status_widget.setVisible(not saved)
                self._automatic_footer_status_hidden_before_manual = None
        action_widgets = (
            self.isolated_progress_widget,
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

    def _set_isolated_slice_progress_visible(self, visible: bool) -> None:
        """Show the preparatory phase inside the embedded generation panel."""

        self.isolated_progress_widget.setVisible(visible)
        self.joint_generation_dialog.layout_changed.emit()
        self.footer_status_widget.setVisible(not visible)
        self.footer_action_layout.invalidate()
        self.footer_action_layout.activate()
        self._refresh_footer_auxiliary_visibility()
        self._schedule_footer_height_update()

    def _refresh_footer_responsive_layout(self, *, force: bool = False) -> None:
        """Switch between two footer columns and the narrow vertical stack."""

        if not hasattr(self, "footer_content_grid"):
            return
        narrow = getattr(
            self, "_footer_layout_narrow_required",
            self.width() < METRICS.responsive_breakpoint_px,
        )
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
                self.footer_message_area,
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
                self.footer_message_area,
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
        status_text_width = max(
            1,
            left_width - self.status_icon_label.sizeHint().width() - 6,
        )
        for label, available_width in (
            (self.status_label, status_text_width),
            (self.result_label, left_width),
        ):
            label.setMinimumHeight(0)
            if label.text():
                label.setMinimumHeight(
                    max(
                        label.minimumSizeHint().height(),
                        label.heightForWidth(available_width),
                    )
                )
        self.footer_status_widget.setMinimumHeight(0)
        status_natural_height = max(
            0,
            self.footer_status_layout.heightForWidth(left_width)
            if self.footer_status_layout.hasHeightForWidth()
            else self.footer_status_layout.sizeHint().height(),
        )
        # A word-wrapped QLabel reports its height-for-width correctly, but a
        # nested QWidget/QVBoxLayout can still be compressed back to one line
        # by the surrounding scroll-area layout. Keep the calculated status
        # block height so neither the main status nor its explanation is cut.
        self.footer_status_widget.setMinimumHeight(status_natural_height)
        self.footer_messages_layout.invalidate()
        self.footer_messages_layout.activate()
        messages_natural_height = max(
            0,
            self.footer_messages_layout.heightForWidth(left_width)
            if self.footer_messages_layout.hasHeightForWidth()
            else self.footer_messages_layout.sizeHint().height(),
            self.footer_messages_layout.minimumSize().height(),
        )
        self.footer_messages_scroll.setVisible(messages_natural_height > 0)
        message_spacing = self.footer_message_layout.spacing() if messages_natural_height else 0
        reset_height = self.reset_button.sizeHint().height() if not self.reset_button.isHidden() else 0
        left_natural_height = messages_natural_height+message_spacing+reset_height
        action_height = self.main_actions_layout.sizeHint().height()
        notice_height = (
            max(
                0,
                self.action_availability_widget.layout().heightForWidth(
                    max(1, self.footer_action_area.width())
                ),
            )
            if not self.action_availability_widget.isHidden()
            else 0
        )
        right_natural_height = (
            action_height
            + notice_height
            + (self.footer_action_layout.spacing() if notice_height else 0)
            if not self.footer_action_area.isHidden()
            else 0
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
        self.footer_messages_content.setMinimumHeight(messages_natural_height)
        self.footer_messages_scroll.setFixedHeight(
            max(0, visible_left_height-message_spacing-reset_height)
        )
        self.footer_action_area.setMinimumHeight(right_natural_height)
        target_height = margins.top() + margins.bottom() + content_height
        bounded_height = min(maximum_height, target_height)
        self.footer.setFixedHeight(bounded_height)
        self.footer_layout.invalidate()
        self.footer_layout.activate()
        self.footer_content_grid.activate()
        if self._footer_narrow_layout and not self.footer_action_area.isHidden():
            action_bottom = self.footer_action_area.mapTo(
                self.footer, QPoint(0, self.footer_action_area.height())
            ).y()
            required_height = action_bottom + margins.bottom()
            if required_height > self.footer.height():
                self.footer.setFixedHeight(min(maximum_height, required_height))
        self.footer_messages_scroll.updateGeometry()
        self.footer.updateGeometry()

    def _set_source_progress_status(
        self,
        text: str,
        *,
        icon: str,
        state: str,
    ) -> None:
        self._set_status_indicator(
            self.source_progress_icon_label,
            self.source_progress_status_label,
            icon,
            text,
            state,
        )
        # The same state is already visible in the drop-zone fact table.
        # Asynchronous paths still update these labels for compatibility, so
        # enforce the presentation rule centrally.
        self.source_progress_status_widget.hide()

    def _finish_source_progress(self, *, completed: bool) -> None:
        self.source_progress_bar.setRange(0, 100)
        self.source_progress_bar.setFormat("%p %")
        self.source_progress_bar.setValue(100 if completed else 0)
        self.source_progress_bar.hide()
        self._refresh_dynamic_preparation_layout()

    def _set_preparation_step_state(
        self,
        index: int,
        text: str,
        state: str,
    ) -> None:
        """Update the quiet state badge in an embedded step introduction."""

        labels = getattr(self, "preparation_step_state_labels", ())
        if not 0 <= index < len(labels):
            return
        label = labels[index]
        label.setText(text)
        label.setProperty("state", state)
        # Completion is represented permanently in the visible tab selector
        # and its prerequisite rows.  Avoid adding a third green success badge
        # to the content introduction itself.
        label.setVisible(state != "success")
        self._refresh_widget_style(label)
        self._balance_preparation_step_intro(index)

    def _balance_preparation_step_intro(self, index: int) -> None:
        """Reserve equal side columns so the middle copy is truly centred."""

        layouts = getattr(self, "preparation_step_intro_layouts", ())
        left_pills = getattr(self, "preparation_step_left_pills", ())
        right_pills = getattr(self, "preparation_step_right_pills", ())
        if not (
            0 <= index < len(layouts)
            and index < len(left_pills)
            and index < len(right_pills)
        ):
            return
        side_width = max(
            168,
            left_pills[index].sizeHint().width(),
            right_pills[index].sizeHint().width(),
        )
        layouts[index].setColumnMinimumWidth(0, side_width)
        layouts[index].setColumnMinimumWidth(2, side_width)

    def _current_preparation_state(self) -> _PreparationState:
        """Derive all Wizard readiness from the current domain objects."""

        source_selected = self.current_source_path is not None
        source_accepted = self._source_step_is_complete()
        installation = self.selected_slicer_installation
        slicer_detected = bool(
            installation is not None and installation.verified
        )
        catalog = self.profile_catalog
        profiles_loaded = bool(
            catalog is not None
            and catalog.complete
            and installation is not None
            and catalog.execution_slicer.identity_key
            == installation.identity_key
        )
        profiles_confirmed = self._catalog_selection_is_confirmed()
        source_confirmation = self.confirmed_profile_context
        model_analyzed = bool(
            source_selected
            and profiles_confirmed
            and self.profile_match_result is not None
            and self.profile_match_result.user_confirmed
            and self.source_artifact is not None
            and source_confirmation is not None
            and source_confirmation.matches_source(self.source_artifact)
            and self.analysis_snapshot is not None
            and not self._analysis_failed
            and self.source_preslice_result is not None
            and self.prepared_analysis_source is not None
        )
        return _PreparationState(
            source_selected=source_selected,
            source_accepted=source_accepted,
            slicer_detected=slicer_detected,
            profiles_loaded=profiles_loaded,
            profiles_confirmed=profiles_confirmed,
            preslice_completed=bool(
                profiles_confirmed
                and self.source_preslice_result is not None
                and self.prepared_analysis_source is not None
                and source_confirmation is not None
                and self.source_artifact is not None
                and source_confirmation.matches_source(self.source_artifact)
            ),
            model_analyzed=model_analyzed,
        )

    def _update_preparation_requirements(self) -> None:
        if not hasattr(self, "preparation_step_selectors"):
            return
        preparation_state = self._current_preparation_state()
        source_selected = preparation_state.source_selected
        guide_visible = not source_selected
        if (not self.source_guide_row.isHidden()) != guide_visible:
            self.source_guide_row.setVisible(guide_visible)
            QTimer.singleShot(0, self._refresh_preparation_section_layout)
        source_validated = preparation_state.step1_completed
        slicer_detected = preparation_state.slicer_detected
        profiles_loaded = preparation_state.profiles_loaded
        catalog_confirmed = preparation_state.profiles_confirmed
        model_analyzed = preparation_state.model_analyzed
        requirements = preparation_state.requirements()
        progress_requirements = dict(requirements)
        if not preparation_state.step1_completed:
            for key in (
                "slicer_detected",
                "profiles_loaded",
                "profiles_confirmed",
                "preslice_completed",
                "model_analyzed",
            ):
                progress_requirements[key] = False
        fulfilled = sum(
            int(complete) for complete in progress_requirements.values()
        )
        for key, complete in requirements.items():
            icon_label, text_label = self.preparation_requirement_rows[key]
            icon_label.setText("✓" if complete else "○")
            state = "complete" if complete else "missing"
            icon_label.setProperty("state", state)
            text_label.setProperty("state", state)
            self._refresh_widget_style(icon_label)
            self._refresh_widget_style(text_label)
        preparation_complete = preparation_state.preparation_completed
        preparation_acknowledged = bool(
            getattr(self.workflow, "preparation_acknowledged", False)
        )
        self.workflow_group.setCheckable(
            preparation_complete and preparation_acknowledged
        )
        step_requirement_keys = (
            ("source_selected", "source_validated"),
            (
                "slicer_detected",
                "profiles_loaded",
                "profiles_confirmed",
                "preslice_completed",
                "model_analyzed",
            ),
        )
        for selector, requirement_keys in zip(
            self.preparation_step_selectors,
            step_requirement_keys,
            strict=True,
        ):
            step_fulfilled = sum(
                int(progress_requirements[key]) for key in requirement_keys
            )
            step_percent = round(
                100 * step_fulfilled / len(requirement_keys)
            )
            selector.set_progress_value(step_percent)
            selector.setAccessibleDescription(
                f"{step_percent} Prozent der Voraussetzungen erfüllt"
            )
        # Background slicer work remains visible in its status rows, but does
        # not advance progress for a step the user cannot enter yet.
        percent = round(100 * fulfilled / len(requirements))
        self.preparation_progress_bar.setValue(percent)
        self.preparation_progress_bar.setAccessibleDescription(
            f"{percent} Prozent der Vorbereitung abgeschlossen"
        )
        if self.preparation_tabs.currentIndex() == 1 and source_validated:
            progress_text = "Schritt 2 von 2 · Slicer-Einstellungen"
        else:
            progress_text = "Schritt 1 von 2 · Dateiübergabe"
        progress_state = "complete" if preparation_complete else "active"
        self.preparation_progress_status_label.setText(progress_text)
        self.preparation_progress_status_label.setProperty(
            "state", progress_state
        )
        self._refresh_widget_style(self.preparation_progress_status_label)
        self.preparation_requirements.setAccessibleDescription(
            f"{fulfilled} von {len(requirements)} Voraussetzungen erfüllt"
        )

        slicer_step_complete = bool(
            slicer_detected
            and profiles_loaded
            and catalog_confirmed
            and model_analyzed
        )
        self.preparation_tabs.setTabText(0, "1. Dateiübergabe")
        self.preparation_tabs.setTabText(1, "2. Slicer-Einstellungen")
        for selector_index, complete in enumerate(
            (source_validated, slicer_step_complete)
        ):
            locked = selector_index == 1 and not source_validated
            selector = self.preparation_step_selectors[selector_index]
            selector.setProperty("complete", complete)
            selector.setProperty("locked", locked)
            selector.setCursor(
                Qt.CursorShape.ForbiddenCursor
                if locked
                else Qt.CursorShape.PointingHandCursor
            )
            selector.setToolTip(
                _LOCKED_SLICER_STEP_TOOLTIP
                if locked
                else f"Schritt {selector_index + 1} öffnen"
            )
            self._refresh_widget_style(selector)
            container = self.preparation_step_selector_containers[
                selector_index
            ]
            container.setProperty("complete", complete)
            container.setProperty("locked", locked)
            self._refresh_widget_style(container)
            requirements_widget = (
                self.preparation_source_requirements,
                self.preparation_slicer_requirements,
            )[selector_index]
            requirements_widget.setProperty("locked", locked)
            requirements_widget.setCursor(Qt.CursorShape.ArrowCursor)
            requirements_widget.setAccessibleDescription(
                "Status: gesperrt, bis eine gültige STL übergeben wurde."
                if locked
                else f"Status und Voraussetzungen für Schritt {selector_index + 1}"
            )
            self._refresh_widget_style(requirements_widget)
            icon = self.preparation_step_selector_icons[selector_index]
            icon.setText("🔒" if locked else "")
            icon.setProperty(
                "state",
                "locked" if locked else ("complete" if complete else "pending"),
            )
            self._refresh_widget_style(icon)

        self.preparation_step_connector.setText("›››")
        self.preparation_step_connector.setProperty(
            "state", "open" if source_validated else "locked"
        )
        self._refresh_widget_style(self.preparation_step_connector)

        current_step = self.preparation_tabs.currentIndex()
        self.preparation_back_button.setVisible(current_step == 1)
        self.preparation_navigation_title_label.setText(
            "Slicer-Einstellungen" if current_step == 1 else "Dateiübergabe"
        )
        self.preparation_next_button.setVisible(current_step == 0)
        self.preparation_finish_button.setVisible(current_step == 1)
        self.preparation_next_button.setEnabled(source_validated)
        self.preparation_next_button.setText(
            "Weiter" if source_validated else "Weiter 🔒"
        )
        self.preparation_next_button.setToolTip(
            ""
            if source_validated
            else _LOCKED_SLICER_STEP_TOOLTIP
        )
        self.preparation_next_button.setProperty("ready", source_validated)
        self._refresh_widget_style(self.preparation_next_button)
        self.preparation_finish_button.setEnabled(preparation_complete)
        self.preparation_finish_button.setText(
            "Fertig" if preparation_complete else "Fertig 🔒"
        )
        self.preparation_finish_button.setToolTip(
            ""
            if preparation_complete
            else "Die Vorbereitung ist noch nicht vollständig abgeschlossen."
        )
        self.preparation_finish_button.setProperty(
            "ready", preparation_complete
        )
        self._refresh_widget_style(self.preparation_finish_button)

        self._refresh_profile_confirmation_button()

        if not source_validated and self.preparation_tabs.currentIndex() > 0:
            self.preparation_tabs.setCurrentIndex(0)

        if source_validated:
            source_step_text, source_step_state = "Abgeschlossen", "success"
        elif (
            source_selected
            and self.stl_validation_result is not None
            and not getattr(
                self.stl_validation_result,
                "accepted",
                self.stl_validation_result.valid,
            )
        ):
            source_step_text, source_step_state = "Prüfung fehlgeschlagen", "error"
        elif source_selected:
            source_step_text, source_step_state = "STL wird geprüft", "active"
        else:
            source_step_text, source_step_state = "Bereit für STL", "pending"
        self._set_preparation_step_state(
            0,
            source_step_text,
            source_step_state,
        )

        if not source_validated:
            slicer_step_text, slicer_step_state = (
                "Gesperrt bis STL gültig",
                "locked",
            )
        elif slicer_step_complete:
            slicer_step_text, slicer_step_state = "Abgeschlossen", "success"
        elif self._analysis_failed and catalog_confirmed:
            slicer_step_text, slicer_step_state = "Analyse prüfen", "error"
        elif catalog_confirmed and source_validated:
            slicer_step_text, slicer_step_state = "Modell wird analysiert", "active"
        elif catalog_confirmed:
            slicer_step_text, slicer_step_state = "Wartet auf STL", "pending"
        elif profiles_loaded:
            slicer_step_text, slicer_step_state = "Auswahl bestätigen", "active"
        elif slicer_detected:
            slicer_step_text, slicer_step_state = "Profile werden geladen", "active"
        else:
            slicer_step_text, slicer_step_state = "Wird vorbereitet", "pending"
        self._set_preparation_step_state(
            1,
            slicer_step_text,
            slicer_step_state,
        )

        self._refresh_preparation_header_summary(preparation_complete)

    def _refresh_preparation_header_summary(self, complete: bool) -> None:
        """Show the completed file and profile overview in one fact column."""

        if not complete:
            self.workflow_group.set_split_summary_columns((), ())
            return
        installation = self.selected_slicer_installation
        source_path = self.current_source_path
        if installation is None or source_path is None:
            self.workflow_group.set_split_summary_columns((), ())
            return

        def selected_text(combo: QComboBox) -> str:
            return combo.currentText().strip() or "Nicht ausgewählt"

        self.workflow_group.set_split_summary_columns(
            (),
            (
                ("Dateiname", source_path.name),
                ("Slicer", installation.display_name),
                ("Maschinenprofil", selected_text(self.machine_profile_combo)),
                ("Filamentprofil", selected_text(self.filament_profile_combo)),
                ("Prozessprofil", selected_text(self.process_profile_combo)),
            ),
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
        # Retain the former values for diagnostics and integrations, but never
        # insert the short-lived blocks into the selector layout.
        self.slicer_progress_bar.hide()
        self.slicer_progress_status_widget.hide()
        self._set_status_indicator(
            self.slicer_progress_icon_label,
            self.slicer_progress_status_label,
            icon,
            text,
            state,
        )
        if hasattr(self, "profile_confirmation_stack"):
            self._set_profile_confirmation_busy(
                state == "running" and 0 <= percent < 100,
                text,
                percent=percent,
            )

    def _set_preslice_activity(
        self,
        visible: bool,
        text: str | None = None,
        *,
        percent: int | None = None,
    ) -> None:
        """Show Preslice activity in the fixed-height confirmation slot."""

        was_busy = self._profile_confirmation_busy
        if visible and percent is None:
            percent = (
                self.profile_confirmation_progress.value()
                if self.profile_confirmation_progress.maximum() == 100
                else 0
            )
        if visible:
            if not self._preslice_activity_timer.isActive():
                self._preslice_activity_frame_index = -1
                self._advance_preslice_activity_frame()
                self._preslice_activity_timer.start()
            progress_format = self._preslice_progress_base_format
        else:
            self._preslice_activity_timer.stop()
            self._preslice_activity_frame_index = -1
            progress_format = None
        self._set_profile_confirmation_busy(
            visible,
            text,
            percent=percent,
            progress_format=progress_format,
        )
        self.profile_confirmation_progress.set_activity_frame(
            _PRESLICE_ACTIVITY_FRAMES[
                max(0, self._preslice_activity_frame_index)
                % len(_PRESLICE_ACTIVITY_FRAMES)
            ]
            if visible
            else ""
        )
        if was_busy != bool(visible):
            self._refresh_dynamic_preparation_layout()

    def _advance_preslice_activity_frame(self) -> None:
        self._preslice_activity_frame_index = (
            self._preslice_activity_frame_index + 1
        ) % len(_PRESLICE_ACTIVITY_FRAMES)
        if not getattr(self, "_profile_confirmation_busy", False):
            return
        self.profile_confirmation_progress.set_activity_frame(
            _PRESLICE_ACTIVITY_FRAMES[self._preslice_activity_frame_index]
        )

    def _start_preslice_runtime_watchdog(self, request_id: int) -> None:
        configured_timeout = float(
            getattr(
                self.preslice_service,
                "timeout_s",
                DEFAULT_PRESLICE_TIMEOUT_S,
            )
        )
        maximum_runtime_s = min(
            DEFAULT_PRESLICE_TIMEOUT_S,
            max(0.001, configured_timeout),
        )
        self._preslice_runtime_request_id = request_id
        self._preslice_timeout_request_id = None
        self._preslice_cancel_requested = False
        self._preslice_cancel_dispatch_pending = False
        self._preslice_progress_base_format = _PRESLICE_PROGRESS_FORMAT
        self._preslice_runtime_timer.setInterval(
            max(1, round(maximum_runtime_s * 1000))
        )
        self._preslice_runtime_timer.start()

    def _stop_preslice_runtime_watchdog(self) -> None:
        self._preslice_runtime_timer.stop()
        self._preslice_activity_timer.stop()
        self._preslice_runtime_request_id = None
        self._preslice_cancel_requested = False
        self._preslice_cancel_dispatch_pending = False
        self._preslice_progress_base_format = _PRESLICE_PROGRESS_FORMAT
        self._preslice_activity_frame_index = -1
        if hasattr(self, "profile_confirmation_progress"):
            self.profile_confirmation_progress.set_activity_frame("")
        if hasattr(self, "preslice_cancel_button"):
            self.preslice_cancel_button.setText("Pre-Slice abbrechen")

    def _queue_preslice_cancellation(
        self,
        request_id: int,
        *,
        reason: str,
    ) -> None:
        if self._preslice_cancel_dispatch_pending:
            return
        self._preslice_cancel_dispatch_pending = True

        def dispatch() -> None:
            self._preslice_cancel_dispatch_pending = False
            if request_id != self._preslice_request_id or self._closing:
                return
            self.background_job_manager.cancel_jobs(
                JobKind.PRESLICE,
                reason=reason,
            )

        # Returning from the click handler first lets Qt paint the immediate
        # visual acknowledgement before cancellation reaches the worker.
        QTimer.singleShot(0, dispatch)

    def _on_preslice_runtime_timeout(self) -> None:
        request_id = self._preslice_runtime_request_id
        if (
            request_id is None
            or request_id != self._preslice_request_id
            or not self.background_job_manager.has_active(JobKind.PRESLICE)
        ):
            return
        self._preslice_timeout_request_id = request_id
        self._preslice_cancel_requested = True
        self._preslice_progress_base_format = _PRESLICE_TIMEOUT_FORMAT
        self.preslice_cancel_button.setText("Zeitlimit erreicht …")
        self.preslice_cancel_button.setEnabled(False)
        self._set_preslice_activity(
            True,
            "Das Zeitlimit von 8 Minuten wurde erreicht.",
            percent=self.profile_confirmation_progress.value(),
        )
        self._set_main_status(
            "Zeitlimit erreicht – Pre-Slice wird abgebrochen",
            icon="⏳",
            state="running",
        )
        self.profile_confirmation_progress.update()
        self.preslice_cancel_button.update()
        self._queue_preslice_cancellation(
            request_id,
            reason="preslice_timeout",
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
        QTimer.singleShot(0, self._refresh_preparation_section_layout)

    def _toggle_stl_validation_details(self, expanded: bool) -> None:
        """Toggle the STL evidence while keeping its compact control stable."""

        self.stl_validation_feedback.set_expanded(expanded)
        self.stl_validation_details_toggle.setText(
            "Details ausblenden ▾"
            if expanded
            else "Details anzeigen ▸"
        )
        self.stl_validation_details_toggle.setAccessibleName(
            "Details ausblenden"
            if expanded
            else "Details einblenden"
        )
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)

    def _toggle_slicer_analysis_details(self, expanded: bool) -> None:
        """Reveal secondary Slicer evidence without crowding primary controls."""

        self.slicer_analysis_details.setVisible(expanded)
        self.slicer_analysis_details_toggle.setText(
            "Analyse- und Profildetails ausblenden ▾"
            if expanded
            else "Analyse- und Profildetails anzeigen ▸"
        )
        self.slicer_analysis_details_toggle.setAccessibleName(
            "Analyse- und Profildetails ausblenden"
            if expanded
            else "Analyse- und Profildetails einblenden"
        )
        # The QTabWidget publishes a fixed height for its current page.  Update
        # that complete height after both opening and closing so the compact
        # toggle can never be compressed into an almost invisible line.
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)

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
        QTimer.singleShot(0, self._refresh_preparation_section_layout)

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
            and getattr(result, "selected", None) is not None
            and bool(getattr(result, "can_use_stl_mode", False))
            and bool(
                getattr(
                    getattr(result, "execution_slicer", None),
                    "can_slice",
                    False,
                )
            )
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

    def _refresh_prediction_advice(self, _estimate_kind: str = "") -> None:
        # The former manually triggered Slicer estimate was intentionally
        # removed. Preview generation now owns all Slicer-backed feedback.
        return

    def _fit_prediction_advice_height(self) -> None:
        """Compatibility no-op after removing the prediction advice panel."""

        return

    def start_slicer_prediction(self) -> None:
        """Run a slicer estimate with the selected number of passes."""

        if not self._slicer_prediction_can_start():
            self._slicer_prediction_status = (
                "Die Profilzuordnung oder Geometrieprüfung ist noch nicht abgeschlossen."
            )
            self._refresh_prediction_advice()
            return
        try:
            request = self._current_preview_request(
                calibration_config=self._calibration_config(),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self._slicer_prediction_status = german_user_message(error)
            self._refresh_prediction_advice()
            return

        self._slicer_prediction_request_id += 1
        request_id = self._slicer_prediction_request_id
        self._slicer_prediction_estimate_s = None
        self._slicer_prediction_status = (
            "Slicer-gestützte Schätzung mit "
            f"{self.preview_iterations} Durchläufen wird erstellt …"
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

    @Slot(int, int, str)
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
        self._refresh_prediction_advice()

    @Slot(int, object)
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
                    "Es wird keine Ersatzschätzung verwendet."
                )
                self._slicer_prediction_estimate_s = None
            else:
                self._slicer_prediction_estimate_s = float(estimate)
                self._slicer_prediction_status = ""
        finally:
            result.dispose()
        self._refresh_prediction()

    @Slot(int, str, str)
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
            self.prediction_frame.set_summary(
                self.joint_generation_dialog.title_label.text()
                if not self.joint_generation_dialog.isHidden()
                else ""
            )
            self._refresh_prediction_advice("Schätzung ausstehend")
            self._refresh_widget_style(self.prediction_label)
            self._update_section_summaries()
            return

        estimate = None
        estimate_kind = "Slicer-Schätzung ausstehend"
        if (
            self.preview_state is PreviewState.CURRENT
            and self.current_preview is not None
            and self.current_preview.minimum_verified_layer_time_s is not None
        ):
            estimate = self.current_preview.minimum_verified_layer_time_s
            estimate_kind = "Slicer-gestützte Schätzung"
        elif self._slicer_prediction_estimate_s is not None:
            estimate = self._slicer_prediction_estimate_s
            estimate_kind = "Slicer-gestützte Schätzung"
        elif not assessment.tower_required:
            excluded = excluded_layer_indices(snapshot.layers, self._excluded_layer_ranges)
            estimate = min((layer.total_time_s for layer in snapshot.layers if layer.index not in excluded), default=None)
            estimate_kind = "Slicer-Analyse des Modells"

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
            "slicer"
            if estimate_kind in {
                "Slicer-gestützte Schätzung",
                "Slicer-Analyse des Modells",
            }
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
        self.prediction_frame.set_summary(
            self.joint_generation_dialog.title_label.text()
            if not self.joint_generation_dialog.isHidden()
            else ""
        )
        self._refresh_prediction_advice(estimate_kind)
        self._update_section_summaries()

    def _on_value_changed(self, value) -> None:
        if self._closing:
            return
        sender = self.sender()
        changed_setting_name = self._last_changed_setting_name
        if sender is self.layer_time_tolerance_spin:
            self._last_changed_setting_name = "layer_time_tolerance_s"
            changed_setting_name = "layer_time_tolerance_s"
        for name, setting in self._setting_widgets.items():
            if sender is setting.editor:
                self._last_changed_setting_name = name
                changed_setting_name = name
                if name == "manual_base_width_mm":
                    self._manual_base_width_session_value = float(
                        setting.editor.value()
                    )
                    self._manual_base_width_user_override = True
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
        if _setting_name == "manual_base_width_mm":
            self._manual_base_width_session_value = (
                self._automatic_base_width_mm()
            )
            self._manual_base_width_user_override = False
        self._last_changed_setting_name = _setting_name
        self._pending_reset_setting_name = _setting_name
        self._on_value_changed(None)

    def _on_output_root_changed(self, _text: str) -> None:
        if not self._loading_phase17_state:
            self._last_changed_setting_name = "output_root"
        self._update_section_summaries()
        self.validate_form()
        self._refresh_folder_action_states(rescan=True)

    def _reset_output_root(self) -> None:
        self.output_root_edit.setText(str(self.default_output_root))
        self.output_root_edit.selectAll()

    def remove_source(self) -> None:
        if self.background_job_manager.has_active(JobKind.EXPORT):
            self.result_label.setText(
                "Die STL kann erst nach Abschluss des laufenden Exports entfernt werden."
            )
            return
        self._stl_validation_request_id += 1
        self._discard_source_preslice("source_removed")
        self._workflow_error_message = None
        self._profile_request_id += 1
        self._feasibility_request_id += 1
        self._preview_request_id += 1
        self._clear_slicer_prediction()
        self.background_job_manager.cancel_jobs(
            JobKind.STL_VALIDATION,
            reason="source_removed",
        )
        self.background_job_manager.cancel_jobs(
            JobKind.PROFILE_MATCH,
            reason="source_removed",
        )
        self._cancel_feasibility_jobs()
        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="source_removed",
        )
        for session in self.generation_sessions.values():
            session.discard_preview()
        self.preview_state = PreviewState.EMPTY
        if self._preview_dialog is not None:
            self._preview_dialog.canvas.set_scene(None)
            self._preview_dialog.mark_stale()
        self.current_gcode_path = None
        self.current_source_path = None
        self.current_source_kind = None
        self.source_artifact = None
        self.stl_validation_result = None
        self.prepared_analysis_source = None
        self.analysis_snapshot = None
        self._refresh_target_time_hint()
        self.tower_assessment = None
        self.profile_feasibility = None
        self.profile_match_result = None
        self._reset_profile_filter_controls()
        self.profile_preview_outdated = False
        self._analysis_failed = False
        self._clear_feasibility_issues()
        self.last_export_result = None
        self.drop_zone.clear_file()
        self.source_progress_bar.setValue(0)
        self.source_progress_bar.hide()
        self.source_progress_status_widget.show()
        self._set_source_progress_status(
            "Datei auswählen",
            icon="○",
            state="pending",
        )
        self._clear_stl_validation_details()
        self._show_reconstructed_configuration(None)
        self._clear_profile_assignment(
            "Slicer- und Profilauswahl bleibt für die nächste Datei erhalten.",
            "pending",
            preserve_catalog=True,
        )
        self._set_tower_need_message(
            "Bitte zuerst eine STL-Datei auswählen.", "pending"
        )
        self.result_label.clear()
        self.warning_text.clear()
        self.warning_text.hide()
        self._refresh_issue_panels()
        self.validation_label.clear()
        self._refresh_folder_action_states()
        self._refresh_last_export_report_action()
        self.preview_hint_label.setProperty("state", "current")
        self.preview_hint_label.setText(
            "Beim Export wird der Kühlturm immer mit den aktuellen "
            "Einstellungen erzeugt."
        )
        self._refresh_widget_style(self.preview_hint_label)
        self._set_main_status(
            "Bitte STL auswählen",
            icon="⇧",
            state="idle",
        )
        self._refresh_prediction()
        self.workflow.reset()
        self.preparation_tabs.setCurrentIndex(0)
        if (
            self.selected_slicer_installation is not None
            and self._catalog_selection_is_confirmed()
        ):
            self._set_slicer_progress(
                100,
                "Slicer und Profile bestätigt · wartet auf Datei",
                icon="✓",
                state="success",
            )
            self.workflow.slicer_succeeded(
                self.selected_slicer_installation.display_name
            )
        elif self.selected_slicer_installation is not None:
            self._set_slicer_progress(
                100,
                "Slicer erkannt · Profilbestätigung ausstehend",
                icon="○",
                state="warning",
            )
        else:
            self._set_slicer_progress(
                0,
                "Wartet auf die Dateianalyse",
                icon="○",
                state="pending",
            )
        self._update_preparation_requirements()
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)
        self.validate_form()

    def reload_source(self) -> None:
        """Read and validate the selected source again from disk."""

        if self.background_job_manager.has_active(JobKind.EXPORT):
            self.result_label.setText(
                "Die STL kann erst nach Abschluss des laufenden Exports "
                "neu eingelesen werden."
            )
            return
        path = self.current_source_path or self.drop_zone.selected_path
        if path is None or not path.is_file():
            self._show_input_error(
                "Die ausgewählte Quelldatei ist nicht mehr verfügbar."
            )
            return
        self.drop_zone.set_file(path.resolve())

    def _on_base_mode_changed(self, state: int) -> None:
        if self._closing:
            return
        automatic = self.automatic_base_checkbox.isChecked()
        if self._automatic_base_width_active and not automatic:
            # Entering manual mode starts at the current automatic default
            # unless the user has already supplied a manual value this session.
            if not self._manual_base_width_user_override:
                self._manual_base_width_session_value = (
                    self._automatic_base_width_mm()
                )
        elif not self._automatic_base_width_active and automatic:
            self._manual_base_width_session_value = float(
                self.manual_base_width_spin.value()
            )
        self._automatic_base_width_active = automatic
        self._last_changed_setting_name = "automatic_base_width"
        self._pending_reset_setting_name = None
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self.automatic_base_width_label.hide()
        self.automatic_base_reset_button.setVisible(True)
        self.profile_feasibility = None
        self._invalidate_preview("Die Standfußberechnung wurde geändert.")
        self._update_automatic_base_width_preview()
        self._refresh_tower_assessment()
        self._update_section_summaries()
        self.validate_form()
        self._refresh_geometry_section_layout(self.geometry_settings_group.isChecked())
        self._schedule_feasibility_validation()

    def _on_full_infill_changed(self, _checked: bool) -> None:
        if self._closing:
            return
        self.maximum_contraction_angle_spin.setEnabled(not _checked)
        self._last_changed_setting_name = "simulate_full_tower_infill"
        self._pending_reset_setting_name = None
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self.profile_feasibility = None
        self._invalidate_preview(
            "Die simulierte Turmfüllung wurde geändert."
        )
        self.update_wall_path_preview()
        self._refresh_tower_assessment()
        self._update_section_summaries()
        self.validate_form()
        self._schedule_feasibility_validation()

    def _on_support_simulation_changed(self, _checked: bool) -> None:
        if self._closing:
            return
        self._last_changed_setting_name = "simulate_tower_without_supports"
        self._update_expansion_angle_warning()
        self._invalidate_preview("Die Stützen-Simulation wurde geändert.")
        self.validate_form()

    def _on_source_selected(self, path: str, source_kind: str) -> None:
        kind = SourceKind(source_kind)
        if kind is not SourceKind.STL:
            self._show_input_error(
                "Als Modelldatei wird derzeit ausschließlich STL unterstützt."
            )
            return
        resolved = Path(path).resolve()
        self.current_source_path = resolved
        self.current_source_kind = kind
        self.source_artifact = None
        self._update_preparation_requirements()
        self._prepare_for_replaced_source(
            "Eine andere STL-Datei wurde ausgewählt."
        )
        self.current_gcode_path = None
        self.workflow.set_slicer_step_visible(False)
        self.preparation_tabs.setCurrentIndex(0)
        self.workflow.begin_source_validation(is_stl=True)
        self.drop_zone.set_status(
            "STL-Modell erkannt – Geometrie wird geprüft"
        )
        self._set_main_status(
            "STL-Modell erkannt – Geometrie wird geprüft",
            icon="⏳",
            state="running",
        )
        self._start_stl_validation(resolved)
        # Installation and source validation touch independent read-only
        # resources and may therefore run in parallel. Visible Slicer feedback
        # remains deferred by the workflow controller until tab 2 opens.
        if (
            self._slicer_service_was_injected
            or self._startup_slicer_discovery_enabled
        ):
            self.start_slicer_discovery()
        self.validate_form()

    def _prepare_for_replaced_source(self, reason: str) -> None:
        self._last_changed_setting_name = None
        self._workflow_error_message = None
        self._discard_source_preslice("source_replaced")
        self._stl_validation_request_id += 1
        self.background_job_manager.cancel_jobs(
            JobKind.STL_VALIDATION,
            reason="source_replaced",
        )
        self.background_job_manager.cancel_jobs(
            JobKind.PROFILE_MATCH,
            reason="source_replaced",
        )
        self._invalidate_preview(reason)
        self.analysis_snapshot = None
        self.stl_validation_result = None
        self._clear_stl_validation_details()
        self.profile_preview_outdated = True
        self._profile_request_id += 1
        self._clear_profile_assignment(
            "Profilzuordnung wartet auf die neue Quellenanalyse.",
            "pending",
            preserve_catalog=True,
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
        self._refresh_last_export_report_action()
        self.validation_label.clear()
        self._show_reconstructed_configuration(None)
        self._refresh_prediction()

    def _start_stl_validation(self, path: Path) -> None:
        self.background_job_manager.cancel_jobs(
            JobKind.STL_VALIDATION,
            reason="stl_validation_replaced",
        )
        self._stl_validation_request_id += 1
        request_id = self._stl_validation_request_id
        self.workflow.begin_source_validation(is_stl=True)
        self.drop_zone.set_analysis_state("analyzing")
        self.source_progress_bar.setValue(0)
        self.source_progress_bar.show()
        self.source_progress_status_widget.show()
        self._set_source_progress_status(
            "STL-Geometrie wird geprüft …",
            icon="⏳",
            state="running",
        )
        self._refresh_dynamic_preparation_layout()
        worker = StlValidationWorker(
            request_id,
            path,
            self.stl_validation_service,
        )
        worker.progress.connect(self._on_stl_validation_progress)
        worker.succeeded.connect(self._on_stl_validation_succeeded)
        worker.failed.connect(self._on_stl_validation_failed)
        self.background_job_manager.start_job(
            kind=JobKind.STL_VALIDATION,
            request_id=request_id,
            worker=worker,
        )

    @Slot(int, int, str)
    def _on_stl_validation_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._stl_validation_request_id:
            return
        self.source_progress_bar.setValue(max(0, min(100, int(percent))))
        if percent >= 100:
            self.source_progress_bar.hide()
            self._refresh_dynamic_preparation_layout()
        self._set_source_progress_status(
            status,
            icon="⏳",
            state="running",
        )
        self.drop_zone.set_status("STL-Geometrie wird geprüft")

    @Slot(int, object)
    def _on_stl_validation_succeeded(
        self,
        request_id: int,
        result: StlValidationResult,
    ) -> None:
        if request_id != self._stl_validation_request_id:
            return
        if (
            self.current_source_kind is not SourceKind.STL
            or self.current_source_path is None
            or result.source_artifact.original_path
            != self.current_source_path.resolve()
        ):
            return
        self.stl_validation_result = result
        self.source_artifact = result.source_artifact
        self.stl_validation_feedback.clear_warning()
        self.source_progress_bar.setValue(100)
        accepted = bool(getattr(result, "accepted", result.valid))
        self._finish_source_progress(completed=accepted)
        self.source_progress_status_widget.show()
        if not accepted:
            self._analysis_failed = True
            self._workflow_error_message = (
                "Die STL ist non-manifold (nicht vollständig geschlossen) "
                "oder geometrisch nicht gültig."
            )
            self.drop_zone.set_status("STL-Prüfung fehlgeschlagen")
            self.drop_zone.set_analysis_state("rejected")
            self.source_progress_status_widget.show()
            self._set_source_progress_status(
                "STL-Prüfung fehlgeschlagen",
                icon="✕",
                state="error",
            )
            self.stl_validation_feedback.set_primary(
                "STL-Geometrie prüfen",
                "Die STL ist non-manifold (nicht vollständig geschlossen) "
                "oder geometrisch nicht gültig. Das Modell "
                "enthält offene, überlappende oder fehlerhaft verbundene "
                "Flächen. Das Modell muss manifold (vollständig "
                "geschlossen) sein, damit Layerzeiten zuverlässig ermittelt "
                "werden können. "
                "Bitte im Slicer, CAD- oder "
                "3D-Programm korrigieren und erneut exportieren.",
                severity="error",
                icon="×",
            )
            self.stl_validation_details.setPlainText(result.technical_summary)
            self.stl_validation_details_toggle.show()
            self.accept_rejected_stl_button.setVisible(
                self._rejected_stl_can_be_overridden(result)
            )
            self.workflow.source_invalid("STL-Geometrie ist ungültig")
            self._set_main_status(
                "Die STL ist non-manifold (nicht vollständig geschlossen)",
                icon="✕",
                state="error",
            )
            self._update_preparation_requirements()
            self._refresh_preparation_section_layout()
            QTimer.singleShot(0, self._refresh_preparation_section_layout)
            self.validate_form()
            return

        self._complete_accepted_stl(request_id, result)

    def _rejected_stl_can_be_overridden(
        self,
        result: StlValidationResult | None,
    ) -> bool:
        """Allow overrides only for parsed geometry that remains processable."""

        if (
            result is None
            or bool(
                getattr(
                    result,
                    "accepted",
                    getattr(result, "valid", False),
                )
            )
            or self.current_source_kind is not SourceKind.STL
            or self.current_source_path is None
            or getattr(result, "format", None) is None
            or getattr(result, "face_count", 0) <= 0
            or getattr(result, "vertex_count", 0) < 3
            or getattr(result, "component_count", 0) <= 0
        ):
            return False
        try:
            if (
                result.source_artifact.original_path
                != self.current_source_path.resolve()
            ):
                return False
        except (OSError, TypeError, ValueError):
            return False
        overridable_codes = {
            StlIssueCode.DEGENERATE_FACE,
            StlIssueCode.DUPLICATE_FACE,
            StlIssueCode.BOUNDARY_EDGE,
            StlIssueCode.NON_MANIFOLD_EDGE,
            StlIssueCode.INCONSISTENT_WINDING,
            StlIssueCode.NON_POSITIVE_VOLUME,
            StlIssueCode.SELF_INTERSECTION,
        }
        blocking_issues = tuple(
            getattr(
                result,
                "blocking_issues",
                tuple(
                    issue
                    for issue in getattr(result, "issues", ())
                    if getattr(issue, "blocking", True)
                ),
            )
        )
        return bool(blocking_issues) and all(
            issue.code in overridable_codes for issue in blocking_issues
        )

    def _confirm_rejected_stl(self) -> None:
        """Ask for an explicit risk acknowledgement before overriding rejection."""

        result = self.stl_validation_result
        source_path = self.current_source_path
        if (
            result is None
            or bool(
                getattr(
                    result,
                    "accepted",
                    getattr(result, "valid", False),
                )
            )
            or source_path is None
            or result.source_artifact.original_path != source_path.resolve()
            or not self._rejected_stl_can_be_overridden(result)
        ):
            self.accept_rejected_stl_button.hide()
            return
        if not self._ask_rejected_stl_confirmation():
            return
        matches_current_file = getattr(
            result.source_artifact,
            "matches_current_file",
            None,
        )
        try:
            source_unchanged = not callable(matches_current_file) or bool(
                matches_current_file(verify_content=True)
            )
        except (OSError, TypeError, ValueError):
            source_unchanged = False
        if not source_unchanged:
            self._show_input_error(
                "Die STL wurde seit der Prüfung verändert. Bitte die Datei "
                "neu einlesen und anschließend erneut bestätigen."
            )
            return
        confirmed = replace(result, user_confirmed=True)
        self.stl_validation_result = confirmed
        # Re-enter the documented source-validation path so the workflow
        # state machine records this as an explicit acceptance transition.
        self.workflow.begin_source_validation(is_stl=True)
        self._complete_accepted_stl(
            self._stl_validation_request_id,
            confirmed,
        )

    def _create_rejected_stl_message_box(self) -> QMessageBox:
        """Build a Qt-owned warning box that never falls back to a native dialog."""

        box = QMessageBox(self)
        box.setObjectName("rejectedStlConfirmationDialog")
        box.setWindowTitle("Abgelehnte STL trotzdem verwenden?")
        box.setWindowModality(Qt.WindowModality.WindowModal)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "Diese STL wurde von der Sicherheits- und Geometrieprüfung "
            "abgelehnt. Wenn du sie trotzdem verwendest, kann dies zu "
            "unerwarteten oder nicht zufriedenstellenden Ergebnissen, "
            "Fehlern oder Fehlverhalten führen.\n\n"
            "Bist du sicher, dass du die STL auf eigenes Risiko verwenden "
            "möchtest?"
        )
        accept_button = box.addButton(
            "Trotzdem verwenden",
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = box.addButton(
            "Abbrechen",
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)
        box._rejected_stl_accept_button = accept_button  # type: ignore[attr-defined]
        box._rejected_stl_cancel_button = cancel_button  # type: ignore[attr-defined]
        return box

    def _ask_rejected_stl_confirmation(self) -> bool:
        """Show the warning visibly on-screen and return the explicit decision."""

        box = self._create_rejected_stl_message_box()
        box.ensurePolished()
        box.adjustSize()
        # Use the same concealed first-frame lifecycle as the About dialog.
        # The nested event loop created by exec() still services the delayed
        # reveal, but Windows never receives a visible frame at its default
        # top-left position before final centring has settled.
        self._show_internal_dialog_without_flash(
            box,
            lambda: self._place_dialog_centered(box),
        )
        box._rejected_stl_cancel_button.setFocus(  # type: ignore[attr-defined]
            Qt.FocusReason.OtherFocusReason
        )
        box.exec()
        return (
            box.clickedButton()
            is box._rejected_stl_accept_button  # type: ignore[attr-defined]
        )

    def _complete_accepted_stl(
        self,
        request_id: int,
        result: StlValidationResult,
    ) -> None:
        """Continue with an automatically or explicitly accepted STL."""

        user_confirmed = bool(
            getattr(result, "user_confirmed", False) and not result.valid
        )
        self._analysis_failed = False
        self._workflow_error_message = None
        self.accept_rejected_stl_button.hide()
        self.drop_zone.set_status(
            "STL user-bestätigt"
            if user_confirmed
            else "STL-Prüfung abgeschlossen"
        )
        self.drop_zone.set_analysis_state("ready")
        # A safely accepted source is already complete from the file-input
        # perspective.  Later profile-bound analysis remains visible in the
        # shared workflow prerequisites without withholding this green cue.
        self.drop_zone.set_completed(True)
        self._set_source_progress_status(
            "STL auf ausdrücklichen Benutzerwunsch akzeptiert"
            if user_confirmed
            else "STL-Geometrie ist manifold (vollständig geschlossen)",
            icon="✓",
            state="warning" if user_confirmed else "success",
        )
        if user_confirmed:
            self.stl_validation_feedback.set_primary(
                "STL auf eigenes Risiko akzeptiert",
                "Die STL wurde trotz fehlgeschlagener Prüfung auf deinen "
                "ausdrücklichen Wunsch als „user-bestätigt“ akzeptiert. "
                "Unerwartete oder nicht zufriedenstellende Ergebnisse, "
                "Fehler oder Fehlverhalten sind weiterhin möglich.",
                severity="warning",
                icon="!",
            )
        elif result.warning_issues:
            self.stl_validation_feedback.set_primary(
                "STL-Datei akzeptiert",
                "<p style='margin:0;'>"
                "&#x2022; Das Mesh ist geschlossen und topologisch manifold.<br>"
                "&#x2022; Es wurden keine offenen Kanten erkannt.</p>",
                severity="success",
                icon="✓",
            )
            self.stl_validation_feedback.set_warning(
                "Kleine Geometrieabweichungen",
                "<p style='margin:0;'>"
                "&#x2022; Es wurden geringfügige lokale Flächenüberschneidungen "
                "erkannt.<br>"
                "&#x2022; Eine reguläre Weiterverarbeitung ist "
                "voraussichtlich möglich.</p>"
                "<p style='margin:13px 0 0 0;'>"
                "Ein Pre-Slice prüft im letzten Vorbereitungsschritt zusätzlich, "
                "ob der ausgewählte Slicer einen zuverlässig verarbeitbaren "
                "G‑Code erzeugen kann.</p>"
            )
        else:
            self.stl_validation_feedback.set_primary(
                "STL-Datei akzeptiert",
                "Die STL ist manifold (vollständig geschlossen), geometrisch "
                "konsistent und für die weitere Verarbeitung geeignet.",
                severity="success",
                icon="✓",
            )
        self.stl_validation_details.setPlainText(result.technical_summary)
        self.stl_validation_details_toggle.show()
        self.workflow.source_validation_succeeded(
            f"{self.current_source_path.name} · {result.face_count} Dreiecke"
            + (" · user-bestätigt" if user_confirmed else ""),
            analysis_complete=False,
        )
        self._show_confirmed_profiles_analysis_action()
        if user_confirmed:
            self.source_group.set_summary_note(
                "user-bestätigt · auf eigenes Risiko",
                severity="warning",
            )
        elif result.warning_issues:
            self.source_group.set_summary_note(
                "mit Geometriehinweis",
                severity="warning",
            )
        self._set_main_status(
            (
                "STL user-bestätigt · Verwendung auf eigenes Risiko"
                if user_confirmed
                else f"STL geprüft · {result.face_count} Dreiecke · "
                f"{result.component_count} Komponente(n)"
            ),
            icon="✓",
            state="warning" if user_confirmed else "success",
        )
        self._update_preparation_requirements()
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)
        self.validate_form()

    @Slot(int, str, str)
    def _on_stl_validation_failed(
        self,
        request_id: int,
        message: str,
        details: str,
    ) -> None:
        if request_id != self._stl_validation_request_id:
            return
        self.stl_validation_result = None
        self.source_artifact = None
        self.stl_validation_feedback.clear_warning()
        self._analysis_failed = True
        self._workflow_error_message = german_user_message(message)
        self.drop_zone.set_status("STL-Prüfung fehlgeschlagen")
        self.drop_zone.set_analysis_state("rejected")
        self.source_progress_bar.setValue(0)
        self._finish_source_progress(completed=False)
        self.source_progress_status_widget.show()
        self._set_source_progress_status(
            "STL-Prüfung fehlgeschlagen",
            icon="✕",
            state="error",
        )
        self.stl_validation_feedback.set_primary(
            "STL-Datei konnte nicht geprüft werden",
            "Die STL konnte nicht vollständig und sicher gelesen werden. "
            "Bitte die Datei erneut exportieren oder eine andere STL auswählen.",
            severity="error",
            icon="×",
        )
        self.stl_validation_details.setPlainText(details)
        self.stl_validation_details_toggle.show()
        self.workflow.source_invalid("STL-Prüfung fehlgeschlagen")
        self._set_main_status(
            "STL-Prüfung fehlgeschlagen",
            icon="✕",
            state="error",
        )
        self._update_preparation_requirements()
        self._refresh_preparation_section_layout()
        QTimer.singleShot(0, self._refresh_preparation_section_layout)
        self.validate_form()

    def _clear_stl_validation_details(self) -> None:
        if not hasattr(self, "stl_validation_details"):
            return
        self.stl_validation_feedback.clear()
        if hasattr(self, "accept_rejected_stl_button"):
            self.accept_rejected_stl_button.hide()
        if hasattr(self, "source_group"):
            self.source_group.set_summary_note(None)

    def _adopt_common_analysis_snapshot(
        self,
        snapshot: GCodeAnalysisSnapshot,
    ) -> None:
        """Enter the cooling-tower pipeline for the prepared STL analysis."""

        self.analysis_snapshot = snapshot
        self._refresh_target_time_hint()
        self._update_local_window_layer_limit(snapshot.layer_count)
        self._refresh_tower_assessment()
        self.validate_form()
        self._schedule_feasibility_validation()

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

    def _refresh_tower_assessment(self) -> None:
        snapshot = self.analysis_snapshot
        if snapshot is None:
            self.tower_assessment = None
            self.profile_feasibility = None
            self._set_tower_need_message(
                "Bitte zuerst eine STL-Datei auswählen.", "pending"
            )
            self._refresh_target_time_hint()
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
                self._no_tower_required_reason(assessment, snapshot),
                "notRequired",
            )
            self._refresh_prediction()
            return

        self._show_required_tower_message(assessment)
        self._refresh_prediction()

    @staticmethod
    def _no_tower_required_reason(
        assessment: TowerNeedAssessment,
        snapshot: GCodeAnalysisSnapshot,
    ) -> str:
        return (
            "Kein Kühlturm erforderlich:\n"
            f"• Gewünschte Mindest-Layerzeit: {_de_number(assessment.target_layer_time_s, 1)} s.\n"
            f"• Kürzeste Layerzeit des Originalobjekts: "
            f"{_de_number(snapshot.minimum_layer_time_s, 3)} s.\n"
            "• Kein berücksichtigter Layer benötigt zusätzliche Zeit; festgelegte "
            "Ausschlussbereiche werden dabei ignoriert."
        )

    def _show_required_tower_message(
        self,
        assessment: TowerNeedAssessment,
    ) -> None:
        snapshot = self.analysis_snapshot
        if snapshot is not None:
            difference = assessment.maximum_time_deficit_s
            if 0 < difference <= 0.5 + 1e-9:
                self._set_tower_need_message(
                    f"Nur {_de_number(difference, 3)} s zusätzliche Layerzeit: "
                    "Dieser geringe Zeitgewinn macht oft keinen zusätzlichen "
                    "Kühlturm erforderlich.",
                    "smallGain",
                )
                return
        verb = (
            "unterschreitet"
            if assessment.deficit_layer_count == 1
            else "unterschreiten"
        )
        self._set_tower_need_message(
            "Kühlturm erforderlich - "
            f"{assessment.deficit_layer_count} Layer {verb} die gewünschte "
            "Mindest-Layerzeit.",
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

    @Slot(int, object)
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
        # Geometric feasibility depends on several settings and the source.
        # Keep these diagnostics in the general result area, never under an
        # individual input where they look like a field validation error.
        self._feasibility_field_errors = {}
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

    @Slot(int, str, str)
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
        if setting_name == "target_layer_time_s":
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
        self._feasibility_field_errors = {}
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
                if trigger == "target_layer_time_s":
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
        if setting_name == "simulate_full_tower_infill":
            state = (
                "aktiviert"
                if self.full_infill_checkbox.isChecked()
                else "deaktiviert"
            )
            return f"100% Turmfüllung simulieren: {state}"
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
            return f"Exportordner: {self.output_root_edit.text().strip()}"
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
                "minimum_outer_diameter_mm": ("Minimaler Turmdurchmesser",),
                "maximum_outer_diameter_mm": ("Maximaler Turmdurchmesser",),
                "manual_base_width_mm": ("Manuelle Standfußbreite",),
                "maximum_expansion_angle_deg": ("Aufweitungswinkel",),
                "maximum_contraction_angle_deg": ("Verjüngungswinkel",),
                "local_reference_window": ("Lokales Zeitfenster",),
                "output_root": ("Exportordner",),
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
            "MAXIMUM_OUTER_DIAMETER_REACHED": (
                "Eingestellter größter Außendurchmesser von "
                f"{_de_number(self.maximum_outer_spin.value())} mm reicht "
                "nicht aus"
            ),
        }
        remedies = {
            "EXPANSION_ANGLE_TOO_SMALL": (
                "Den maximalen Aufweitungswinkel erhöhen.",
                "Die Ziel-Layerzeit verringern.",
                "Den größten Außendurchmesser erhöhen.",
            ),
            "BASE_WIDTH_TOO_SMALL": (
                "Die automatische Standfußbreite aktivieren.",
                "Die manuelle Standfußbreite vergrößern.",
                "Die Ziel-Layerzeit verringern.",
            ),
            "MAXIMUM_OUTER_DIAMETER_REACHED": (
                "Den größten Außendurchmesser erhöhen.",
                "Die Ziel-Layerzeit verringern.",
                "Optional 100% Turmfüllung simulieren.",
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
            # Angle and base issues carry directly actionable setting units.
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
        if trigger == "minimum_outer_diameter_mm":
            return "Den kleinsten Außendurchmesser auf den Standardwert zurücksetzen."
        if trigger == "maximum_outer_diameter_mm":
            return "Den zuletzt geänderten größten Außendurchmesser erhöhen."
        if trigger == "automatic_base_width":
            return "Die automatische Standfußbreite wieder aktivieren."
        if trigger == "manual_base_width_mm":
            return "Die zuletzt geänderte manuelle Standfußbreite erhöhen."
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
        visible = state in {"notRequired", "smallGain"}
        changed = (
            self.tower_need_label.text() != text
            or self.tower_need_label.property("state") != state
            or self.tower_need_label.isHidden() == visible
        )
        if not changed:
            return
        self.tower_need_label.setText(text)
        self.tower_need_label.setProperty("state", state)
        self.tower_need_label.setVisible(visible)
        self.tower_need_label.style().unpolish(self.tower_need_label)
        self.tower_need_label.style().polish(self.tower_need_label)
        self.tower_need_label.updateGeometry()
        self._setting_widgets["target_layer_time_s"].refresh_content_height()
        if hasattr(self, "geometry_settings_group"):
            self._refresh_geometry_section_layout(
                self.geometry_settings_group.isChecked()
            )

    def _show_input_error(self, message: str) -> None:
        self._workflow_error_message = german_user_message(message)
        self.validate_form()

    def select_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self.additional_options_dialog,
            "Exportordner auswählen",
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
        self.show_joint_slice_settings()

    def show_joint_slice_settings(self) -> None:
        dialog = JointSliceSettingsDialog(
            self.maximum_joint_slices,
            self,
            output_root=self.output_root_edit.text(),
            default_output_root=str(self.default_output_root),
            maximum_separate_slices=self.maximum_separate_slices,
            default_maximum_separate_slices=(
                self.default_maximum_separate_slices
            ),
            default_maximum_joint_slices=self.default_maximum_joint_slices,
            local_reference_window=self.local_window_spin.value(),
            default_local_reference_window=self.default_settings.local_reference_window,
            maximum_local_reference_window=self.local_window_spin.property("validationMaximum") or 999,
            layer_time_tolerance_s=self.layer_time_tolerance_spin.value(),
            default_layer_time_tolerance_s=self.default_settings.layer_time_tolerance_s,
        )
        dialog.output_root_applied.connect(self.output_root_edit.setText)
        dialog.show_limits_checkbox.setChecked(self.show_setting_limits)
        dialog.limits_applied.connect(self._apply_show_setting_limits)
        dialog.separate_value_applied.connect(
            self._apply_maximum_separate_slices
        )
        dialog.value_applied.connect(self._apply_maximum_joint_slices)
        dialog.local_window_applied.connect(self._apply_local_reference_window)
        dialog.layer_time_tolerance_applied.connect(self._apply_layer_time_tolerance)
        self._joint_slice_settings_dialog = dialog
        dialog.finished.connect(
            lambda _result: setattr(
                self,
                "_joint_slice_settings_dialog",
                None,
            )
        )
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        self._show_internal_dialog_without_flash(
            dialog,
            self._resize_joint_slice_settings_to_content,
        )

    def _apply_show_setting_limits(self, visible: bool) -> None:
        self.show_setting_limits = bool(visible)
        for setting in self._setting_widgets.values():
            setting.set_limits_visible(self.show_setting_limits)
            setting.layout().invalidate()
            setting.layout().activate()
            setting.updateGeometry()
        self._refresh_geometry_section_layout(self.geometry_settings_group.isChecked())
        self._save_user_settings()

    def _resize_joint_slice_settings_to_content(self) -> None:
        dialog = self._joint_slice_settings_dialog
        if dialog is None or not dialog.isVisible():
            return
        dialog.layout().activate()
        dialog.adjustSize()
        preferred = dialog.sizeHint()
        dialog.setFixedSize(
            max(dialog.minimumWidth(), preferred.width()),
            preferred.height(),
        )
        self._place_dialog_centered(dialog)

    @Slot(int)
    def _apply_maximum_separate_slices(self, value: int) -> None:
        normalized = max(1, min(15, int(value)))
        if normalized == self.maximum_separate_slices:
            return
        self.maximum_separate_slices = normalized
        self._save_user_settings()
        self._invalidate_preview(
            "Die maximale Anzahl getrennter Slices wurde geändert."
        )

    @Slot(int)
    def _apply_maximum_joint_slices(self, value: int) -> None:
        normalized = max(5, min(20, int(value)))
        if normalized == self.maximum_joint_slices:
            return
        self.maximum_joint_slices = normalized
        self._save_user_settings()
        self._invalidate_preview(
            "Die maximale Anzahl gemeinsamer Slices wurde geändert."
        )

    @Slot(int)
    def _apply_local_reference_window(self, value: int) -> None:
        if value != self.local_window_spin.value():
            self.local_window_spin.setValue(value)
            self._save_user_settings()

    @Slot(float)
    def _apply_layer_time_tolerance(self, value: float) -> None:
        if value != self.layer_time_tolerance_spin.value():
            self.layer_time_tolerance_spin.setValue(value)
            self._save_user_settings()

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
        dialog.reset_document()
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        self._show_internal_dialog_without_flash(
            dialog,
            self._resize_about_to_content,
        )
        self._about_initial_height = dialog.height()
        main_frame = self.frameGeometry()
        self._about_expansion_allowance = max(
            0,
            main_frame.bottom()
            - round(main_frame.height() * 0.1)
            - dialog.frameGeometry().bottom(),
        )

    def _show_export_success_dialog(
        self,
        result: PreviewExportResult,
    ) -> None:
        dialog = self.export_success_dialog
        target = getattr(result, "target_layer_time_s", None)
        achieved = getattr(result, "minimum_verified_layer_time_s", None)
        tolerance = float(
            getattr(result, "calibration_time_tolerance_s", 0.2) or 0.2
        )
        values_are_known = bool(
            target is not None
            and achieved is not None
            and math.isfinite(float(target))
            and math.isfinite(float(achieved))
        )

        saved_files = [result.output_path.name]
        project_path = getattr(result, "project_path", None)
        if project_path is not None:
            saved_files.append(Path(project_path).name)
        self.export_success_summary_label.setText(
            '<p style="margin:0">Gespeichert:</p>'
            '<ul style="margin-top:3px; margin-bottom:0; -qt-list-indent:0">'
            + "".join(f"<li><b>{escape(name)}</b></li>" for name in saved_files)
            + "</ul>"
        )
        if values_are_known:
            target_value = float(target)
            achieved_value = float(achieved)
            difference = achieved_value - target_value
            within_tolerance = abs(difference) <= tolerance + 1e-9
            self.export_success_target_label.clear()
            self.export_success_achieved_label.setText(
                "Erreichte Layerzeit: "
                f"{self._format_export_number(achieved_value)} von "
                f"{self._format_export_number(target_value)} Sekunden"
            )
            deviation_text = (
                "Abweichung: "
                f"{self._format_export_seconds(difference, signed=True)} "
                f"({'innerhalb' if within_tolerance else 'außerhalb'} der Toleranz "
                f"von ±{self._format_export_number(tolerance)} Sekunden)"
            )
            self.export_success_deviation_label.setText(deviation_text)
            self.export_success_deviation_label.setProperty(
                "status",
                "within" if within_tolerance else "outside",
            )
        else:
            self.export_success_target_label.clear()
            self.export_success_achieved_label.setText(
                "Erreichte Layerzeit: nicht verfügbar"
            )
            self.export_success_deviation_label.setText(
                "Die Abweichung konnte nicht bestimmt werden."
            )
            self.export_success_deviation_label.setProperty(
                "status", "unknown"
            )
        if getattr(result, "full_tower_infill_simulated", False):
            manual_infill = (
                "Stellen Sie für die Turm-STL objektspezifisch 100 % "
                "Fülldichte ein. Das Druckobjekt behält seine eigene Füllung."
            )
        else:
            manual_infill = (
                "Die Turm-STL verwendet wie vorgesehen die Füllung des "
                "ausgewählten Prozessprofils."
            )
        if project_path is not None:
            project_intro = (
                "Öffnen Sie alternativ die ebenfalls exportierte .3MF-Datei."
            )
        else:
            project_intro = (
                "Falls der Exportordner zusätzlich eine .3MF-Datei enthält, "
                "können Sie diese alternativ öffnen."
            )
        simulated_properties = getattr(result, "simulated_project_properties", ())
        simulation_hint = ""
        if simulated_properties:
            simulation_hint = (
                '<ul style="color:#23704c; -qt-list-indent:0; margin-left:20px; margin-top:0; margin-bottom:12px">'
                + ''.join(f'<li><b>{escape(label)}</b></li>' for label in simulated_properties)
                + '</ul><p style="margin:0">Diese Einstellungen sind <b>in der exportierten 3MF aktiviert</b>. '
                'In anderen Projekten oder beim STL-Import müssen sie ggf. selbst aktiviert werden. '
                'Originalprofile bleiben unverändert.</p>'
            )
        self.export_success_simulation_label.setText(simulation_hint)
        self.export_success_simulation_frame.setVisible(bool(simulated_properties))
        self.export_success_usage_label.setText(
            '<p style="margin:0 0 12px 0"><b>1. Turm-STL manuell zum Druckobjekt hinzufügen</b><br>'
            "Importieren Sie die exportierte Turm-STL zusammen mit Ihrem "
            "Druckobjekt auf dieselbe Druckplatte. "
            f"{escape(manual_infill)}</p>"
            '<p style="margin:0"><b>2. Optional die vorbereitete .3MF-Datei verwenden</b><br>'
            f"{project_intro} Sie enthält Druckobjekt und Kühlturm bereits "
            "gemeinsam angeordnet inklusive aller simulierten "
            "Einstellungen.</p>"
        )
        self.export_success_deviation_label.show()
        if getattr(result, "generation_method", None) == "manual":
            self.manual_controller.describe_export(result)
        self._refresh_widget_style(self.export_success_deviation_label)
        self.export_success_error_label.clear()
        self.export_success_error_label.hide()
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        # Give the native dialog its final size and approximate position before
        # the first Show event, so Windows never paints a frame at (0, 0).
        self._resize_export_success_dialog()
        self._show_internal_dialog_without_flash(
            dialog,
            self._resize_export_success_dialog,
        )

    @staticmethod
    def _format_export_number(value: float) -> str:
        return f"{float(value):.3f}".rstrip("0").rstrip(".").replace(".", ",")

    @classmethod
    def _format_export_seconds(
        cls,
        value: float,
        *,
        signed: bool = False,
    ) -> str:
        prefix = "+" if signed and value >= 0.0 else ""
        return f"{prefix}{cls._format_export_number(value)} Sekunden"

    def _resize_export_success_dialog(self) -> None:
        dialog = self.export_success_dialog
        screen = dialog.screen() or self.screen()
        target_width = EXPORT_SUCCESS_DIALOG_PREFERRED_WIDTH_PX
        if screen is not None:
            target_width = min(
                target_width,
                max(420, screen.availableGeometry().width() - 40),
            )
        dialog.setFixedWidth(target_width)
        dialog.layout().invalidate()
        dialog.layout().activate()
        dialog.setFixedHeight(max(dialog.minimumSizeHint().height(), dialog.layout().totalHeightForWidth(target_width)))
        self._place_dialog_centered(dialog, allow_hidden=True)

    def _open_export_directory_from_success_dialog(self) -> None:
        directory = self._latest_export_directory
        if directory is None:
            self.export_success_error_label.setText(
                "Der Exportordner ist nicht mehr verfügbar."
            )
            self.export_success_error_label.show()
            self._resize_export_success_dialog()
            return
        try:
            open_directory(directory)
        except OSError as error:
            self.export_success_error_label.setText(
                "Der Exportordner konnte nicht geöffnet werden: "
                f"{german_user_message(error)}"
            )
            self.export_success_error_label.show()
            self._resize_export_success_dialog()
            return
        self.export_success_dialog.accept()

    def show_support_report_dialog(self) -> None:
        """Show the local report composer without transmitting any data."""

        dialog = self.support_report_dialog
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        self._show_internal_dialog_without_flash(
            dialog,
            self._resize_support_report_dialog,
        )

    def _resize_support_report_dialog(self) -> None:
        dialog = self.support_report_dialog
        if not dialog.isVisible():
            return
        target_width = SUPPORT_DIALOG_PREFERRED_WIDTH_PX
        target_height = SUPPORT_DIALOG_PREFERRED_HEIGHT_PX
        screen = dialog.screen() or self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(target_width, max(620, available.width() - 40))
            target_height = min(target_height, max(590, available.height() - 40))
        dialog.resize(target_width, target_height)
        self._place_dialog_centered(dialog)

    def _show_internal_dialog_without_flash(
        self,
        dialog: QDialog,
        finalize_geometry: Callable[[], None],
    ) -> None:
        """Reveal a child dialog only after native sizing and placement settle."""

        if dialog.isVisible():
            finalize_geometry()
            dialog.raise_()
            dialog.activateWindow()
            return

        self._internal_dialog_reveal_filter.prepare(dialog)
        dialog.show()
        finalize_geometry()
        self._internal_dialog_reveal_filter.schedule_reveal(
            dialog,
            finalize_geometry,
        )

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
        initial_height = getattr(self, "_about_initial_height", dialog.height())
        expansion_allowance = getattr(self, "_about_expansion_allowance", 0)
        natural_height = (
            initial_height
            if dialog.about_placeholder_label.isHidden()
            else self._about_natural_content_height(dialog.width()) + 2
        )

        screen = dialog.screen() or self.screen()
        target_height = min(
            max(initial_height, natural_height),
            initial_height + expansion_allowance,
        )
        frame_geometry = dialog.frameGeometry()
        frame_top_left = frame_geometry.topLeft()
        if screen is not None:
            available = screen.availableGeometry()
            frame_overhead = max(
                0,
                frame_geometry.height() - dialog.height(),
            )
            maximum_client_height = max(
                280,
                available.bottom()
                - frame_geometry.top()
                + 1
                - frame_overhead,
            )
            target_height = min(target_height, maximum_client_height)

        if target_height != dialog.height():
            dialog.resize(dialog.width(), target_height)
            # Both opening and closing preserve the chosen upper edge.
            dialog.move(frame_top_left)
        if screen is not None:
            overflow = dialog.frameGeometry().bottom() - available.bottom()
            if overflow > 0:
                dialog.resize(dialog.width(), max(280, dialog.height() - overflow))
                dialog.move(frame_top_left)

    def _place_additional_options_dialog(self) -> None:
        dialog = self.additional_options_dialog
        if not dialog.isVisible():
            return
        self._place_dialog_centered(dialog)

    def _place_dialog_centered(self, dialog: QDialog, *, allow_hidden: bool = False) -> None:
        if not dialog.isVisible() and not allow_hidden:
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
        if self._layer_range_dialog is not None and self._layer_range_dialog.isVisible():
            self._place_dialog_centered(self._layer_range_dialog)
        self._resize_support_simulation_dialog()
        self._resize_draft_shield_dialog()
        if self._about_dialog is not None and self._about_dialog.isVisible():
            self._resize_about_to_content()
        if (
            self._additional_options_dialog is not None
            and self._additional_options_dialog.isVisible()
        ):
            self._resize_additional_options_to_content()
        if (
            self._support_report_dialog is not None
            and self._support_report_dialog.isVisible()
        ):
            self._resize_support_report_dialog()
        if (
            self._export_success_dialog is not None
            and self._export_success_dialog.isVisible()
        ):
            self._resize_export_success_dialog()

    def _support_diagnostic_context(self) -> dict[str, object]:
        """Return a bounded, non-file-content snapshot for local support."""

        source: dict[str, object] = {
            "loaded": self.current_source_path is not None,
            "source_kind": (
                self.current_source_kind.value
                if self.current_source_kind is not None
                else None
            ),
            "analysis_gcode_available": self.current_gcode_path is not None,
        }
        if self.source_artifact is not None:
            source["suffix"] = self.source_artifact.original_path.suffix.casefold()
            source["size_bytes"] = self.source_artifact.original_size
        elif self.current_gcode_path is not None:
            source["suffix"] = self.current_gcode_path.suffix.casefold()
            try:
                source["size_bytes"] = self.current_gcode_path.stat().st_size
            except OSError:
                source["size_bytes"] = None
        prepared = self.prepared_analysis_source
        if prepared is not None:
            source["gcode_origin"] = prepared.gcode_origin.value
            provenance = prepared.preslice_provenance
            source["preslice_cache_hit"] = bool(
                provenance is not None and provenance.cache_hit
            )

        discovery = self.slicer_discovery_result
        slicer_context: dict[str, object] = {
            "status_text": self.slicer_status_label.text(),
            "search_completed": discovery is not None,
        }
        if discovery is not None:
            slicer_context.update(
                {
                    "gui_state": discovery.gui_state.value,
                    "message": discovery.message,
                    "installation_count": len(discovery.installations),
                    "verified_installation_count": sum(
                        1 for item in discovery.installations if item.verified
                    ),
                    "diagnostics": list(discovery.diagnostics),
                    "installations": [
                        {
                            "adapter_id": item.adapter_id,
                            "product_name": item.product_name,
                            "version": item.version,
                            "verified": item.verified,
                            "can_slice": item.can_slice,
                            "support_level": item.support_level.value,
                        }
                        for item in discovery.installations
                    ],
                }
            )
        selected_slicer = self.selected_slicer_installation
        if selected_slicer is not None:
            slicer_context["selected"] = {
                "adapter_id": selected_slicer.adapter_id,
                "product_name": selected_slicer.product_name,
                "version": selected_slicer.version,
                "can_slice": selected_slicer.can_slice,
            }

        profile_context: dict[str, object] = {
            "status_text": self.profile_status_label.text(),
            "available": self.profile_match_result is not None,
        }
        if self.profile_match_result is not None:
            match = self.profile_match_result
            selected = match.selected
            profile_context.update(
                {
                    "state": match.state.value,
                    "message": match.message,
                    "candidate_count": len(match.candidates),
                    "selection_available": selected is not None,
                    "requires_confirmation": match.requires_confirmation,
                    "user_confirmed": match.user_confirmed,
                    "can_use_stl_mode": match.can_use_stl_mode,
                    "profiles_filtered": match.profiles_filtered,
                    "unfiltered_option_counts": list(
                        match.unfiltered_option_counts
                    ),
                    "visible_option_counts": list(
                        match.visible_option_counts
                    ),
                    "execution_slicer": {
                        "adapter_id": match.execution_slicer.adapter_id,
                        "product_name": match.execution_slicer.product_name,
                        "version": match.execution_slicer.version,
                        "can_slice": match.execution_slicer.can_slice,
                    },
                }
            )

        active_jobs = [
            {
                "job_kind": item.get("job_kind"),
                "state": item.get("state"),
                "worker_class": item.get("worker_class"),
                "cancel_requested": item.get("cancel_requested"),
                "duration_s": item.get("duration_s"),
            }
            for item in self.background_job_manager.diagnostic_snapshot()
        ]

        return {
            "workflow_stage": self.workflow.stage.value,
            "source": source,
            "analysis": {
                "available": self.analysis_snapshot is not None,
                "layer_count": (
                    self.analysis_snapshot.layer_count
                    if self.analysis_snapshot is not None
                    else None
                ),
                "failed": self._analysis_failed,
            },
            "slicer": slicer_context,
            "profile": profile_context,
            "preview": {
                "state": self.preview_state.value,
                "available": self.current_preview is not None,
            },
            "export": {
                "last_export_available": self.last_export_result is not None,
            },
            "settings": self.collect_settings().to_dict(),
            "active_background_jobs": active_jobs,
            "visible_error": self._workflow_error_message,
        }

    def _refresh_layer_range_tool(self) -> None:
        if not hasattr(self, "layer_range_button"):
            return
        data = getattr(self.source_preslice_result, "preview_source_data", None)
        manager = getattr(self, "background_job_manager", None)
        busy = manager is not None and any(manager.has_active(kind) for kind in (
            JobKind.PRESLICE, JobKind.PROFILE_MATCH, JobKind.PREVIEW, JobKind.EXPORT,
        ))
        available = bool(data is not None and self.analysis_snapshot is not None and not busy and not self._closing)
        self.layer_range_button.setEnabled(available)
        self.layer_range_button.setToolTip(
            "Layerzeit-Ausgleich für ausgewählte Original-Layer ausschließen"
            if available else "Nach abgeschlossenem Pre-Slice verfügbar; während Generierung und Export gesperrt"
        )
        spans = self._excluded_layer_ranges
        self.layer_range_summary.setText(
            f"{len(spans)} {'Ausschlussbereich' if len(spans) == 1 else 'Ausschlussbereiche'}"
            if spans else ""
        )
        self.layer_range_summary.setVisible(bool(spans))
        if self._layer_range_dialog is not None:
            self._layer_range_dialog.set_editing_enabled(available)

    def show_layer_range_tool(self) -> None:
        self._refresh_layer_range_tool()
        if not self.layer_range_button.isEnabled():
            return
        if self._layer_range_dialog is not None:
            self._layer_range_dialog.show()
            self._layer_range_dialog.raise_()
            self._layer_range_dialog.activateWindow()
            return
        silhouette = getattr(self, "_layer_range_silhouette", None)
        if silhouette is None and self.source_artifact is not None:
            from cooling_tower.preview.layer_silhouette import load_layer_silhouette
            try:
                silhouette = load_layer_silhouette(self.source_artifact, self.analysis_snapshot.layers)
            except (OSError, ValueError, SourceChangedError) as error:
                QMessageBox.warning(self, "Objektvorschau nicht verfügbar", str(error))
                return
            self._layer_range_silhouette = silhouette
        dialog = LayerRangeDialog(
            self.analysis_snapshot.layers,
            self.source_preslice_result.preview_source_data.object_segments,
            target_time_s=self.target_time_spin.value(),
            target_minimum=float(self.target_time_spin.property("validationMinimum")),
            target_maximum=float(self.target_time_spin.property("validationMaximum")),
            target_decimals=self.target_time_spin.decimals(),
            ranges=self._excluded_layer_ranges,
            gradient_start_deficit_s=self._range_color_thresholds[0],
            gradient_full_deficit_s=self._range_color_thresholds[1],
            silhouette=silhouette,
            target_time_hint=self._setting_widgets["target_layer_time_s"].info_button.toolTip(),
            target_default=self.settings_store.load_defaults().target_layer_time_s,
            parent=self,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._layer_range_dialog = dialog
        dialog.finished.connect(self._on_layer_range_tool_closed)
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            dialog.resize(dialog.initial_size(QSize(available.width() - 32, available.height() - 60)))
        dialog.show()
        self._place_dialog_centered(dialog)

    def _on_layer_range_tool_closed(self, result: int) -> None:
        dialog = self._layer_range_dialog
        self._layer_range_dialog = None
        if dialog is None or result != QDialog.DialogCode.Accepted or self.analysis_snapshot is None:
            return
        ranges = normalize_layer_ranges(dialog.ranges, layer_count=self.analysis_snapshot.layer_count)
        target_time = dialog.target_spin.value()
        target_changed = target_time != self.target_time_spin.value()
        ranges_changed = ranges != self._excluded_layer_ranges
        self._excluded_layer_ranges = ranges
        self._range_color_thresholds = (dialog.color_start_spin.value(), dialog.color_full_spin.value())
        # The normal target signal refreshes validation and modified-state UI.
        # All accepted values are already installed before that signal runs.
        self.target_time_spin.setValue(target_time)
        if ranges_changed and not target_changed:
            self._last_changed_setting_name = "target_layer_time_s"
            self._on_value_changed(None)
        self._refresh_layer_range_tool()

    def collect_settings(self) -> GenerationSettings:
        manual_base_width = (
            self.manual_base_width_spin.value()
            if not self.automatic_base_checkbox.isChecked()
            else self._manual_base_width_session_value
        )
        return GenerationSettings(
            excluded_layer_ranges=self._excluded_layer_ranges,
            target_layer_time_s=self.target_time_spin.value(),
            layer_time_tolerance_s=self.layer_time_tolerance_spin.value(),
            minimum_outer_diameter_mm=self.minimum_outer_spin.value(),
            maximum_outer_diameter_mm=self.maximum_outer_spin.value(),
            minimum_object_tower_distance_mm=5.0,
            simulate_full_tower_infill=(
                self.full_infill_checkbox.isChecked()
            ),
            simulate_tower_without_supports=self.simulate_tower_without_supports_checkbox.isChecked(),
            minimum_base_radius_mm=self.minimum_base_spin.value(),
            base_margin_mm=self.base_margin_spin.value(),
            base_height_factor=self.base_height_factor_spin.value(),
            automatic_base_width=self.automatic_base_checkbox.isChecked(),
            manual_base_width_mm=manual_base_width,
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
            local_reference_window=self.local_window_spin.value(),
        )

    def apply_settings(self, settings: GenerationSettings) -> None:
        self._excluded_layer_ranges = settings.excluded_layer_ranges
        if self._layer_range_dialog is not None:
            self._layer_range_dialog.set_target_time(settings.target_layer_time_s)
            self._layer_range_dialog.set_ranges(settings.excluded_layer_ranges)
        self._refresh_layer_range_tool()
        self._manual_base_width_session_value = float(
            settings.manual_base_width_mm
        )
        self._manual_base_width_user_override = (
            not settings.automatic_base_width
            or abs(
                settings.manual_base_width_mm
                - self.default_settings.manual_base_width_mm
            )
            > 1e-9
        )
        values = (
            (self.target_time_spin, settings.target_layer_time_s),
            (self.layer_time_tolerance_spin, settings.layer_time_tolerance_s),
            (self.minimum_outer_spin, settings.minimum_outer_diameter_mm),
            (self.maximum_outer_spin, settings.maximum_outer_diameter_mm),
            (self.minimum_base_spin, settings.minimum_base_radius_mm),
            (self.manual_base_width_spin, settings.manual_base_width_mm),
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
            (self.local_window_spin, settings.local_reference_window),
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
        self.full_infill_checkbox.blockSignals(True)
        self.full_infill_checkbox.setChecked(
            settings.simulate_full_tower_infill
        )
        self.full_infill_checkbox.blockSignals(False)
        self.simulate_tower_without_supports_checkbox.blockSignals(True)
        self.simulate_tower_without_supports_checkbox.setChecked(
            settings.simulate_tower_without_supports
        )
        self.simulate_tower_without_supports_checkbox.blockSignals(False)
        self.maximum_contraction_angle_spin.setEnabled(not settings.simulate_full_tower_infill)
        self.manual_base_width_spin.setEnabled(
            not settings.automatic_base_width
        )
        self._automatic_base_width_active = settings.automatic_base_width
        self.automatic_base_width_label.hide()
        self.automatic_base_reset_button.setVisible(True)
        self._update_expansion_angle_warning()
        self._update_automatic_base_width_preview()

    def _update_expansion_angle_warning(self) -> None:
        warning = (
            "Vorsicht: Aufweitungswinkel ab 51° erzeugen steilere "
            "Überhänge und setzen einen gut kalibrierten Drucker voraus."
            if self.maximum_expansion_angle_spin.value() >= 51.0
            else ""
        )
        profile_match = self.profile_match_result
        if (
            self.source_preslice_result is not None
            and profile_match is not None
            and profile_match.selected is not None
            and not self.simulate_tower_without_supports_checkbox.isChecked()
        ):
            profile = profile_match.selected.effective_profile
            if self.source_preslice_result.supports_simulated:
                profile = with_simulated_supports(profile)
            threshold = tower_support_warning_angle(profile)
            if threshold is not None and self.maximum_expansion_angle_spin.value() >= threshold:
                support_warning = (
                    f"Ab {threshold:g}° Aufweitungswinkel kann das aktive "
                    "Slicerprofil Stützen am Turm erzeugen. Diese verlängern "
                    "die Layerzeit und verfälschen die Turmkalibrierung. "
                    "Aktiviere die Einstellung <b>„Deaktivierte Turmstützen "
                    "simulieren“</b>, um dies zu verhindern."
                )
                warning = (
                    f"• {warning}<br>• {support_warning}"
                    if warning else support_warning
                )
        self.maximum_expansion_angle_setting.set_warning(warning)
        if hasattr(self, "geometry_settings_group"):
            self._refresh_geometry_section_layout(
                self.geometry_settings_group.isChecked()
            )

    def update_wall_path_preview(self) -> None:
        self._update_section_summaries()

    def _update_section_summaries(self) -> None:
        """Keep the most useful values readable before opening a card."""

        if not hasattr(self, "timing_group"):
            return
        for group in (
            self.timing_group,
            self.geometry_group,
            self.stability_group,
            self.overhang_group,
            self.geometry_settings_group,
        ):
            group.set_summary("")
        output_text = self.output_root_edit.text().strip()
        self.automatic_base_reset_button.setVisible(True)
        output_modified = output_text != str(self.default_output_root)
        self.output_root_reset_button.setProperty("modified", output_modified)
        self.output_root_reset_button.setEnabled(output_modified)
        self._refresh_widget_style(self.automatic_base_reset_button)
        self._refresh_widget_style(self.output_root_reset_button)
        if hasattr(self, "reset_button"):
            if self.generation_mode is GenerationMode.MANUAL:
                self.manual_controller.refresh_footer()
            else:
                self.reset_button.setEnabled(self._has_non_default_settings())
        self._update_automatic_base_width_preview()

    def _update_automatic_base_width_preview(self) -> None:
        width = self._automatic_base_width_mm()
        if (
            not self.automatic_base_checkbox.isChecked()
            and self._manual_base_width_user_override
        ):
            displayed_width = self._manual_base_width_session_value
        else:
            displayed_width = width
            if not self.automatic_base_checkbox.isChecked():
                self._manual_base_width_session_value = width

        self.manual_base_width_spin.blockSignals(True)
        self.manual_base_width_spin.setValue(displayed_width)
        self.manual_base_width_spin.blockSignals(False)
        if self.automatic_base_checkbox.isChecked():
            self.manual_base_width_spin.lineEdit().deselect()
        self.manual_base_width_spin.setEnabled(
            not self.automatic_base_checkbox.isChecked()
        )
        automatic_preview = self.automatic_base_checkbox.isChecked()
        if (
            self.manual_base_width_spin.property("automaticPreview")
            != automatic_preview
        ):
            self.manual_base_width_spin.setProperty(
                "automaticPreview", automatic_preview
            )
            self._refresh_widget_style(self.manual_base_width_spin)
        self.automatic_base_reset_button.setVisible(True)
        self.manual_base_width_setting.refresh_reset_state()

        if self.automatic_base_checkbox.isChecked():
            object_height = (
                self.analysis_snapshot.maximum_print_z_mm
                if self.analysis_snapshot is not None
                else None
            )
            if object_height is None:
                self.automatic_base_width_label.setText(
                    "Automatische Breite: 25,00 bis höchstens 80,00 mm; "
                    "der genaue "
                    "Wert folgt aus der ermittelten Modellhöhe."
                )
            else:
                rate = f"{BASE_WIDTH_PER_OBJECT_HEIGHT:g}".replace(".", ",")
                self.automatic_base_width_label.setText(
                    f"Automatische Breite bei {object_height:.2f} mm "
                    f"{self._source_height_description()}: {width:.2f} mm "
                    f"({rate} mm je 1 mm)"
                )
        else:
            self.automatic_base_width_label.setText(
                f"Manuelle Standfußbreite: "
                f"{displayed_width:.2f} mm"
            )

    def _automatic_base_width_mm(self) -> float:
        object_height = (
            self.analysis_snapshot.maximum_print_z_mm
            if self.analysis_snapshot is not None
            else None
        )
        if object_height is None or object_height <= 0.0:
            return MINIMUM_AUTOMATIC_BASE_WIDTH_MM
        return min(
            MAXIMUM_BASE_WIDTH_MM,
            max(
                MINIMUM_AUTOMATIC_BASE_WIDTH_MM,
                object_height * BASE_WIDTH_PER_OBJECT_HEIGHT,
            ),
        )
    def _source_height_description(self) -> str:
        if self.current_source_kind is SourceKind.STL:
            return "Höhe des automatisch geslicten Modells"
        return "ermittelte Modellhöhe"

    def _update_target_time_minimum(self) -> None:
        minimum = 5.0
        if self.target_time_spin.property("validationMinimum") != minimum:
            self.target_time_spin.setProperty("validationMinimum", minimum)
            self._setting_widgets["target_layer_time_s"].refresh_range_state()

    def _refresh_target_time_hint(self) -> None:
        if "target_layer_time_s" not in self._setting_widgets:
            return
        hint = SETTING_INFO_TEXTS["target_layer_time_s"]
        snapshot = self.analysis_snapshot
        observed = getattr(snapshot, "minimum_layer_time_s", None)
        if isinstance(observed, (int, float)) and not isinstance(observed, bool):
            observed = float(observed)
            if math.isfinite(observed) and observed > 0:
                hint += (
                    "\n\nPre-Slice des Originalobjekts:\n"
                    f"Kürzeste Layerzeit: {_de_number(observed, 3)} s."
                )
        self._setting_widgets["target_layer_time_s"].info_button.set_hint(hint)

    def _update_diameter_limits(self) -> None:
        boundaries = (
            (self.minimum_outer_spin, "validationMaximum",
             min(self.maximum_outer_spin.value(), 99.0),
             "minimum_outer_diameter_mm"),
            (self.maximum_outer_spin, "validationMinimum",
             max(self.minimum_outer_spin.value() + 1.0, 5.0),
             "maximum_outer_diameter_mm"),
        )
        for editor, property_name, value, setting_name in boundaries:
            if editor.property(property_name) != value:
                editor.setProperty(property_name, value)
                self._setting_widgets[setting_name].refresh_range_state()

    def validate_form(self) -> bool:
        self._update_target_time_minimum()
        self._update_diameter_limits()
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
        diameter_order_invalid = (
            settings.minimum_outer_diameter_mm
            >= settings.maximum_outer_diameter_mm
        )
        range_invalid_names: set[str] = set()
        for name, setting in self._setting_widgets.items():
            if not hasattr(settings, name):
                continue
            if name == "manual_base_width_mm" and settings.automatic_base_width:
                continue
            if name == "maximum_contraction_angle_deg" and settings.simulate_full_tower_infill:
                continue
            if diameter_order_invalid and name in {
                "minimum_outer_diameter_mm",
                "maximum_outer_diameter_mm",
            }:
                continue
            value = float(getattr(settings, name))
            minimum = setting.editor.property("validationMinimum")
            maximum = setting.editor.property("validationMaximum")
            unit = SETTING_UNITS.get(name, "")
            unit_suffix = f" {unit}" if unit else ""
            sentence_end = "" if unit.endswith(".") else "."
            formatter = setting.editor.textFromValue
            if minimum is not None and value < float(minimum):
                range_invalid_names.add(name)
                rendered_minimum = formatter(
                    float(minimum)
                    if isinstance(setting.editor, QDoubleSpinBox)
                    else int(minimum)
                )
                add_error(
                    (name,),
                    f"{self._setting_value_description(name)} liegt unter "
                    f"dem Mindestwert {rendered_minimum}"
                    f"{unit_suffix}{sentence_end}",
                )
            elif maximum is not None and value > float(maximum):
                range_invalid_names.add(name)
                rendered_maximum = formatter(
                    float(maximum)
                    if isinstance(setting.editor, QDoubleSpinBox)
                    else int(maximum)
                )
                add_error(
                    (name,),
                    f"{self._setting_value_description(name)} überschreitet "
                    f"den Maximalwert {rendered_maximum}"
                    f"{unit_suffix}{sentence_end}",
                )
        if diameter_order_invalid:
            add_error(
                ("minimum_outer_diameter_mm",),
                "Min. Turmdurchmesser muss kleiner als Max. Turmdurchmesser sein.",
            )
            add_error(
                ("maximum_outer_diameter_mm",),
                "Max. Turmdurchmesser muss größer als Min. Turmdurchmesser sein.",
            )
        for name in self._incomplete_setting_names:
            if name == "maximum_contraction_angle_deg" and settings.simulate_full_tower_infill:
                continue
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
            "minimum_outer_diameter_mm" not in range_invalid_names
            and settings.minimum_outer_diameter_mm <= 0.0
        ):
            add_error(
                ("minimum_outer_diameter_mm",),
                "Minimaler Turmdurchmesser muss größer als 0 sein.",
                (
                    "Einen kleinsten Außendurchmesser größer als 0 mm eingeben.",
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
            not settings.simulate_full_tower_infill
            and "maximum_contraction_angle_deg" not in range_invalid_names
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
                validate_solid_settings(settings)
            except ValueError as error:
                raw_text = str(error)
                translated = german_user_message(raw_text)
                if _validation_issue_key(translated) not in issue_keys:
                    add_general_error(translated)
        if not self.output_root_edit.text().strip():
            add_error(
                ("output_root",),
                "Bitte einen Exportordner angeben.",
                (
                    "Einen beschreibbaren Exportordner auswählen.",
                    "Den Standard-Exportordner wiederherstellen.",
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

        grouped_messages: dict[str, list[str]] = {
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
        input_messages = (
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
        standalone_messages = _deduplicate_validation_messages(
            (*workflow_messages, *input_messages)
        )
        footer_groups = [
            (
                self._footer_setting_heading(name),
                _deduplicate_validation_messages(messages),
            )
            for name, messages in grouped_messages.items()
            if messages
        ]
        if (
            feedback_available
            or self._workflow_error_message
        ):
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
        feasibility_errors: dict[str, list[str]] = {}
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
                {"target_layer_time_s", "layer_time_tolerance_s"},
            ),
            (
                self.geometry_settings_group,
                {
                    "target_layer_time_s",
                    "layer_time_tolerance_s",
                    "minimum_outer_diameter_mm",
                    "maximum_outer_diameter_mm",
                    "automatic_base_width",
                    "manual_base_width_mm",
                    "maximum_expansion_angle_deg",
                    "maximum_contraction_angle_deg",
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
        feasibility_errors: dict[str, list[str]] = {}
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
        self.prediction_frame.setChecked(True)
        self.preview_dialog.show()
        self.settings_scroll.ensureWidgetVisible(self.preview_dialog, 0, 18)

    @property
    def joint_generation_dialog(self) -> GenerationPanel:
        if self._joint_generation_dialog is None:
            dialog = GenerationPanel(
                GUI_ASSET_ROOT / "tower_gen_finished.webp",
                self,
            )
            dialog.accept_requested.connect(self._accept_joint_candidate)
            dialog.export_requested.connect(self._on_main_export_clicked)
            dialog.layout_changed.connect(self._refresh_ready_grid_layout)
            dialog.continue_requested.connect(self._continue_joint_generation)
            self._joint_generation_dialog = dialog
        return self._joint_generation_dialog

    def _connect_preview_worker(self, worker: PreviewWorker) -> None:
        self._active_preview_worker = worker
        worker.progress.connect(self._on_preview_progress)
        worker.joint_phase_started.connect(self._on_joint_phase_started)
        worker.joint_progress.connect(self._on_joint_progress)
        worker.joint_scene.connect(self._on_joint_scene)
        worker.succeeded.connect(self._on_preview_succeeded)
        worker.failed.connect(self._on_preview_failed)
        worker.finished.connect(self._on_preview_finished)

    def _place_preview_beside_main_window(self) -> None:
        return

    def _enforce_preview_window_geometry(self) -> None:
        return

    def _restore_main_after_preview(self) -> None:
        return

    def start_preview(self) -> None:
        self._cancel_generation_phase_transition()
        self.validate_form()
        self._refresh_stl_availability()
        if (
            self.tower_assessment is not None
            and not self.tower_assessment.tower_required
        ):
            return
        self._show_preview_dialog()
        if not self.preview_button.isEnabled():
            self.generation_intro_label.hide()
            reason = self._export_block_reason()
            message = reason or self.validation_label.text() or "Quellen- und Geometrieprüfung noch nicht abgeschlossen."
            self.joint_generation_dialog.show_error(message)
            self.preview_dialog.set_failed(message)
            self._set_main_status(
                f"Vorschau fehlgeschlagen: {_preview_failure_footer_reason(message)}",
                icon="✕", state="error",
            )
            return
        try:
            request = self._current_preview_request()
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self.generation_intro_label.hide()
            self.joint_generation_dialog.show_error(german_user_message(error))
            self.preview_dialog.set_failed(german_user_message(error))
            self._set_main_status(
                f"Vorschau fehlgeschlagen: {_preview_failure_footer_reason(error)}",
                icon="✕", state="error",
            )
            return

        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.allow_programmatic_close()
            self._joint_generation_dialog.close()
        simulations = []
        if request.settings.simulate_full_tower_infill:
            simulations.append("Turmfüllung: 100 %")
        if request.settings.simulate_tower_without_supports:
            simulations.append("Turmstützen: deaktiviert")
        if getattr(request.effective_profile, "supports_simulated", False):
            simulations.append("Stützen: aktiviert")
        if getattr(request.effective_profile, "draft_shield_simulated", False):
            simulations.append("Draft Shield: deaktiviert")
        self.joint_generation_dialog.set_context(simulations)
        self.generation_intro_label.hide()
        self.joint_generation_dialog.begin(
            request.settings.target_layer_time_s,
            request.settings.layer_time_tolerance_s,
            0,
            self.maximum_joint_slices,
            GENERATION_MINIMUM_JOINT_SLICES,
        )
        self._joint_phase_active = False
        self._joint_accept_requested = False
        self._joint_resume_active = False
        self._joint_resume_accept_seed_only = False
        self._joint_generation_paused = False
        self._joint_slice_offset = 0
        self._joint_slices_completed = 0

        self._clear_result_notices()
        self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="preview_replaced",
        )
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self._preview_cancel_requested = False
        self.preview_state = PreviewState.BUILDING
        self.preview_button.setEnabled(True)
        self._update_responsive_action_labels()
        self._set_export_button_state(
            False,
            "Die Vorschau wird gerade erstellt.",
        )
        self.preview_hint_label.setText(
            "Der Kühlturm wird vollständig generiert. Die bisherige Vorschau "
            "bleibt bis zum Abschluss sichtbar."
        )
        self.preview_hint_label.setProperty("state", "building")
        self.preview_hint_label.show()
        self._refresh_widget_style(self.preview_hint_label)
        self.progress_bar.setProperty("task", "preview")
        self._refresh_widget_style(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self.isolated_progress_bar.setValue(0)
        self.isolated_progress_detail_label.setText(
            "Die getrennte Turmoptimierung wird vorbereitet …"
        )
        self._set_isolated_slice_progress_visible(True)
        self._set_main_status(
            "Kühlturm wird vorbereitet …", icon="⏳", state="running"
        )
        self.preview_dialog.set_building("Kühlturm wird vorbereitet …")

        worker = PreviewWorker(request_id, request, self.preview_service)
        self._refresh_phase17_actions()
        self._connect_preview_worker(worker)
        self.background_job_manager.start_job(
            kind=JobKind.PREVIEW,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"preview-{request_id}",
        )

    @Slot(int, int, str)
    def _on_preview_progress(
        self,
        request_id: int,
        percent: int,
        status: str,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        status = german_user_message(status)
        if self._joint_resume_active and self._joint_slice_offset:
            status = re.sub(
                r"(Gemeinsamer Slice\s+)(\d+)\s*/\s*\d+",
                lambda match: (
                    f"{match.group(1)}"
                    f"{self._joint_slice_offset + int(match.group(2))}"
                    f"/{self.maximum_joint_slices}"
                ),
                status,
                count=1,
                flags=re.IGNORECASE,
            )
        self.preview_dialog.set_progress(percent, status)
        normalized = status.casefold()
        if self._joint_phase_active or "gemeinsamer slice" in normalized:
            self._set_main_status(status, icon="⏳", state="running")
            if not self._joint_phase_active:
                return
            if "ausgeführt" in normalized:
                self.joint_generation_dialog.set_slice_progress(0.58)
            elif "ausgewertet" in normalized or "slicer-ergebnis" in normalized:
                self.joint_generation_dialog.set_slice_progress(0.84)
            self.progress_bar.hide()
            return
        self.progress_bar.hide()
        self._update_isolated_slice_progress(status)

    def _isolated_slice_progress(self, status: str, fallback: int) -> int:
        match = re.search(
            r"getrennt(?:er|en)\w*\s+(?:Kühlturm-)?Slice\s+(\d+)\s*/\s*(\d+)",
            status,
            re.IGNORECASE,
        )
        if match is not None:
            current, maximum = map(int, match.groups())
            if "ausgewertet" in status.casefold():
                return round(max(0, current) / max(1, maximum) * 100)
            return round(max(0, current - 1) / max(1, maximum) * 100)
        match = re.search(r"Slicer-Ergebnis\s+(\d+)\s*/", status, re.IGNORECASE)
        if match is not None:
            current = min(self.maximum_separate_slices, int(match.group(1)))
            return round(current / self.maximum_separate_slices * 100)
        return max(0, min(99, int(fallback)))

    def _update_isolated_slice_progress(
        self,
        status: str,
    ) -> None:
        percent = self._isolated_slice_progress(
            status, self.isolated_progress_bar.value()
        )
        self.isolated_progress_bar.setValue(
            max(self.isolated_progress_bar.value(), percent)
        )
        self.isolated_progress_detail_label.setText(status)
        self._set_isolated_slice_progress_visible(True)

    def _ensure_generation_phase_animation(self) -> None:
        if self._generation_phase_effect is not None:
            return
        panel = self.joint_generation_dialog
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(1.0)
        effect.setEnabled(False)
        panel.setGraphicsEffect(effect)
        self._generation_phase_effect = effect
        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(GENERATION_PHASE_FADE_OUT_MS)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        fade_out.finished.connect(self._finish_generation_phase_fade_out)
        self._generation_phase_fade_out = fade_out
        fade_in = QPropertyAnimation(effect, b"opacity", self)
        fade_in.setDuration(GENERATION_PHASE_FADE_IN_MS)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutCubic)
        fade_in.finished.connect(self._finish_generation_phase_fade_in)
        self._generation_phase_fade_in = fade_in

    def _cancel_generation_phase_transition(self) -> None:
        self._generation_phase_transition_stage = None
        self._generation_phase_transition_request_id = None
        self._generation_phase_transition_target = None
        if self._generation_phase_fade_out is not None:
            self._generation_phase_fade_out.stop()
        if self._generation_phase_fade_in is not None:
            self._generation_phase_fade_in.stop()
        if self._generation_phase_effect is not None:
            self._generation_phase_effect.setOpacity(1.0)
            self._generation_phase_effect.setEnabled(False)

    def _finish_generation_phase_fade_out(self) -> None:
        if self._generation_phase_transition_stage != "out":
            return
        target = self._generation_phase_transition_target
        if (
            target is None
            or self._generation_phase_transition_request_id != self._preview_request_id
            or self._closing
        ):
            self._cancel_generation_phase_transition()
            return
        self._set_isolated_slice_progress_visible(False)
        self.joint_generation_dialog.start_slice(*target)
        self._generation_phase_transition_stage = "in"
        self._generation_phase_fade_in.start()

    def _finish_generation_phase_fade_in(self) -> None:
        if self._generation_phase_transition_stage == "in":
            self._cancel_generation_phase_transition()

    @Slot(int, int, int)
    def _on_joint_phase_started(
        self,
        request_id: int,
        completed: int,
        _maximum_for_run: int,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        total_completed = self._joint_slice_offset + completed
        first_joint_slice = not self._joint_phase_active
        self._joint_phase_active = True
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        dialog = self.joint_generation_dialog
        if dialog.isHidden():
            dialog.begin(
                self.target_time_spin.value(),
                self.layer_time_tolerance_spin.value(),
                total_completed,
                self.maximum_joint_slices,
            )
        if self._generation_phase_transition_stage == "out":
            self._generation_phase_transition_target = (
                total_completed, self.maximum_joint_slices
            )
            return
        if (
            first_joint_slice
            and self.isVisible()
            and self.isolated_progress_widget.isVisibleTo(dialog)
        ):
            self._ensure_generation_phase_animation()
            self._generation_phase_transition_request_id = request_id
            self._generation_phase_transition_target = (
                total_completed, self.maximum_joint_slices
            )
            self._generation_phase_transition_stage = "out"
            self._generation_phase_effect.setEnabled(True)
            self._generation_phase_fade_out.start()
            return
        self._set_isolated_slice_progress_visible(False)
        dialog.start_slice(total_completed, self.maximum_joint_slices)

    @Slot(int, object)
    def _on_joint_progress(self, request_id: int, progress: object) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        previous_completed = self._joint_slices_completed
        completed = self._joint_slice_offset + int(
            getattr(progress, "completed_count", 0)
        )
        self._joint_slices_completed = max(
            self._joint_slices_completed,
            completed,
        )
        if (
            previous_completed < GENERATION_MINIMUM_JOINT_SLICES
            <= self._joint_slices_completed
        ):
            self._update_responsive_action_labels()
        if self._generation_phase_transition_stage == "out":
            self._generation_phase_transition_target = (
                completed, self.maximum_joint_slices
            )
        self.joint_generation_dialog.complete_slice(
            completed,
            self.maximum_joint_slices,
            progress.best_iteration,
            self.target_time_spin.value(),
        )

    @Slot(int, object)
    def _on_joint_scene(self, request_id: int, scene: object) -> None:
        if (
            request_id == self._preview_request_id
            and not self._closing
            and self.preview_state is PreviewState.BUILDING
        ):
            self.preview_dialog.set_intermediate_scene(scene)

    @Slot(int, object)
    def _on_preview_succeeded(
        self,
        request_id: int,
        result: PreviewResult,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            result.dispose()
            return
        if self._joint_resume_active and self._preview_cancel_requested:
            result.dispose()
            return
        self._cancel_generation_phase_transition()
        try:
            current_signature = self._current_preview_request().signature()
        except (AttributeError, KeyError, TypeError, ValueError):
            current_signature = None
        if (
            self._joint_resume_active
            and current_signature is not None
            and result.refinement_seed_signature
            == self._current_preview_request().refinement_seed_signature()
        ):
            result.request_signature = current_signature
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
        if result.joint_sliced:
            result.completed_joint_slice_count = self._joint_slices_completed
            result.configured_joint_slice_count = self.maximum_joint_slices
        self.current_preview = result
        self.preview_state = PreviewState.CURRENT
        self._preview_cancel_requested = False
        self.last_export_result = None
        self.preview_dialog.set_preview(result)
        self.preview_hint_label.setProperty("state", "current")
        self.preview_hint_label.hide()
        self._refresh_widget_style(self.preview_hint_label)
        self.progress_bar.setProperty("task", "default")
        self._refresh_widget_style(self.progress_bar)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self._set_isolated_slice_progress_visible(False)
        self._set_main_status(
            "Vorschau ist aktuell", icon="✓", state="success"
        )
        self._clear_result_notices()
        if self._joint_generation_dialog is not None:
            paused = self._joint_accept_requested
            self._joint_generation_paused = paused
            self._joint_generation_dialog.set_achieved(result.minimum_verified_layer_time_s)
            self._joint_generation_dialog.mark_finished(
                paused=paused,
                can_continue=(
                    paused
                    and self._joint_slices_completed
                    < self.maximum_joint_slices
                ),
            )
        self._joint_resume_active = False
        self._joint_resume_accept_seed_only = False
        if previous is not None and previous is not result:
            previous.dispose()
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def _clear_result_notices(self) -> None:
        """Remove non-error notices left by an earlier generation or export."""

        self.result_label.clear()
        self.result_label.setToolTip("")
        self.warning_text.clear()
        self.warning_text.hide()
        self._refresh_issue_panels()

    @Slot(int, str, str)
    def _on_preview_failed(
        self,
        request_id: int,
        message: str,
        _details: str,
    ) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        self._cancel_generation_phase_transition()
        resume_failed_with_safe_candidate = bool(
            self._joint_resume_active and self.current_preview is not None
        )
        self.preview_state = (
            PreviewState.CURRENT
            if resume_failed_with_safe_candidate
            else PreviewState.STALE
            if self.current_preview is not None
            else PreviewState.FAILED
        )
        self._preview_cancel_requested = False
        if self._joint_generation_dialog is not None:
            if resume_failed_with_safe_candidate:
                self._joint_slices_completed = self._joint_slice_offset
                self._joint_generation_paused = True
                self._joint_generation_dialog.set_achieved(self.current_preview.minimum_verified_layer_time_s)
            self._joint_generation_dialog.show_error(
                german_user_message(message),
                retain_result=resume_failed_with_safe_candidate,
                can_continue=(
                    resume_failed_with_safe_candidate
                    and self._joint_slices_completed < self.maximum_joint_slices
                ),
            )
        self._joint_resume_active = False
        self._joint_resume_accept_seed_only = False
        self._joint_phase_active = False
        self._joint_accept_requested = False
        if resume_failed_with_safe_candidate:
            self.preview_dialog.set_preview(self.current_preview)
        else:
            self.preview_dialog.set_failed(german_user_message(message))
        self.preview_hint_label.hide()
        self.progress_bar.setProperty("task", "default")
        self._refresh_widget_style(self.progress_bar)
        self._set_main_status(
            f"Vorschau fehlgeschlagen: {_preview_failure_footer_reason(message)}",
            icon="✕",
            state="error",
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self._set_isolated_slice_progress_visible(False)
        self._refresh_prediction()
        self._refresh_phase17_actions()

    def _on_generation_button_clicked(self) -> None:
        if self.generation_mode is GenerationMode.MANUAL:
            self.manual_controller.primary_action()
            return
        if self.background_job_manager.has_active(JobKind.PREVIEW):
            self.cancel_generation()
            return
        if self._joint_generation_paused:
            self.cancel_generation()
            return
        self.start_preview()

    def cancel_generation(self) -> None:
        if self._preview_cancel_requested:
            return
        if (
            self._joint_generation_paused
            and not self.background_job_manager.has_active(JobKind.PREVIEW)
            and not self.background_job_manager.has_active(JobKind.EXPORT)
        ):
            self._finish_generation_cancelled()
            return
        cancelled = self.background_job_manager.cancel_jobs(
            JobKind.PREVIEW,
            reason="user_request",
        )
        if not cancelled:
            return
        if self._joint_resume_active:
            # An explicit abort takes precedence even if accepting the
            # retained seed was already requested in this resumed run.
            self._joint_resume_accept_seed_only = False
            self._joint_accept_requested = False
        self._cancel_generation_phase_transition()
        self._preview_cancel_requested = True
        self.preview_button.setText("Abbruch wird ausgeführt …")
        self.preview_button.setEnabled(False)
        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.accept_button.setEnabled(False)
        self._set_main_status(
            "Generierung wird sicher abgebrochen …",
            icon="⏳",
            state="running",
        )

    @Slot()
    def _accept_joint_candidate(self) -> None:
        if self._preview_cancel_requested:
            return
        if not self.background_job_manager.has_active(JobKind.PREVIEW):
            if self._joint_generation_dialog is not None:
                self._joint_generation_dialog.allow_programmatic_close()
                self._joint_generation_dialog.close()
            return
        if self._joint_slices_completed < GENERATION_MINIMUM_JOINT_SLICES:
            return
        worker = self._active_preview_worker
        if worker is None:
            return
        self._joint_accept_requested = True
        if (
            self._joint_resume_active
            and self._joint_slices_completed == self._joint_slice_offset
            and self.current_preview is not None
        ):
            # The resumed worker has no fully checked candidate yet. Keep the
            # already accepted seed and stop this worker without accepting its
            # incomplete slicer output.
            self._joint_resume_accept_seed_only = True
            self.background_job_manager.cancel_jobs(
                JobKind.PREVIEW, reason="retained_seed_accepted"
            )
        else:
            worker.accept_current()
        dialog = self.joint_generation_dialog
        dialog.accept_button.setEnabled(False)
        dialog.accept_button.setText("Bestes Ergebnis wird übernommen …")
        self._set_main_status(
            "Bester gemeinsamer Kandidat wird sicher übernommen …",
            icon="⏳",
            state="running",
        )

    @Slot()
    def _continue_joint_generation(self) -> None:
        if (
            self.background_job_manager.has_active(JobKind.PREVIEW)
            or self.current_preview is None
            or self.preview_state is not PreviewState.CURRENT
        ):
            return
        self.validate_form()
        if self.analysis_snapshot is not None and self.tower_assessment is not None:
            if not self.tower_assessment.tower_required:
                self._set_main_status(
                    self._no_tower_required_reason(
                        self.tower_assessment, self.analysis_snapshot
                    ),
                    icon="○",
                    state="idle",
                )
                return
        self._cancel_generation_phase_transition()
        remaining = self.maximum_joint_slices - self._joint_slices_completed
        if remaining <= 0:
            return
        config = replace(
            self._calibration_config(),
            maximum_iterations=remaining,
            maximum_joint_slices=remaining,
            completed_joint_slices_before_run=self._joint_slices_completed,
            perform_joint_final_slice=True,
        )
        try:
            request = self._current_preview_request(
                calibration_config=config,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self.joint_generation_dialog.show_error(
                german_user_message(error)
            )
            return
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self._joint_slice_offset = self._joint_slices_completed
        self._joint_resume_active = True
        self._joint_resume_accept_seed_only = False
        self._joint_accept_requested = False
        self._joint_generation_paused = False
        self._joint_phase_active = False
        self._preview_cancel_requested = False
        self.preview_state = PreviewState.BUILDING
        self.joint_generation_dialog.resume_waiting()
        self.preview_dialog.set_building("Gemeinsame Angleichung wird fortgesetzt …")
        worker = PreviewWorker(
            request_id,
            request,
            self.preview_service,
            seed_preview=self.current_preview,
        )
        self._connect_preview_worker(worker)
        self._refresh_phase17_actions()
        self.background_job_manager.start_job(
            kind=JobKind.PREVIEW,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"preview-resume-{request_id}",
        )

    @Slot(int)
    def _on_preview_finished(self, request_id: int) -> None:
        if request_id != self._preview_request_id or self._closing:
            return
        self._cancel_generation_phase_transition()
        self._active_preview_worker = None

        if self._joint_resume_accept_seed_only and self.current_preview is not None:
            self._joint_slices_completed = self._joint_slice_offset
            self._joint_phase_active = False
            self._joint_resume_active = False
            self._joint_resume_accept_seed_only = False
            self._joint_accept_requested = False
            self._joint_generation_paused = True
            self._preview_cancel_requested = False
            self.preview_state = PreviewState.CURRENT
            self.preview_dialog.set_preview(self.current_preview)
            self.joint_generation_dialog.set_achieved(
                self.current_preview.minimum_verified_layer_time_s
            )
            self.joint_generation_dialog.mark_finished(
                paused=True,
                can_continue=self._joint_slices_completed < self.maximum_joint_slices,
            )
            self._set_main_status("Bester gemeinsamer Kandidat übernommen", icon="✓", state="success")
            self._refresh_prediction()
            self._refresh_phase17_actions()
            return
        if self.preview_state is not PreviewState.BUILDING:
            return
        self._finish_generation_cancelled()

    def _finish_generation_cancelled(self) -> None:
        self._preview_cancel_requested = False
        previous = self.current_preview
        self.current_preview = None
        self.preview_state = PreviewState.EMPTY
        self.preview_dialog.set_cancelled()
        self._show_original_object_preview()
        if previous is not None:
            previous.dispose()
        self._joint_resume_active = False
        self._joint_resume_accept_seed_only = False
        self._joint_accept_requested = False
        self._joint_generation_paused = False
        self._joint_phase_active = False
        self._joint_slices_completed = 0
        self._joint_slice_offset = 0
        self.joint_generation_dialog.mark_interrupted("Generierung abgebrochen.")
        self.generation_intro_label.setText(
            "Die Generierung wurde manuell abgebrochen.\n"
            "Der bisherige Kühlturm wurde verworfen."
        )
        self.generation_intro_label.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self._set_isolated_slice_progress_visible(False)
        self.preview_hint_label.hide()
        self._set_main_status(
            "Generierung abgebrochen",
            icon="⚠",
            state="warning",
        )
        self._refresh_prediction()
        if not self.background_job_manager.has_active(JobKind.PREVIEW):
            self._refresh_phase17_actions()
        for delay_ms in (0, 50):
            QTimer.singleShot(delay_ms, self._refresh_phase17_actions)
        # The original scene is restored before the interruption panel and
        # status labels reach their final geometry. Recompute the card height
        # after those changes, as on the initial original-object display.
        self._refresh_ready_grid_layout()
        QTimer.singleShot(0, self._refresh_ready_grid_layout)

    def start_export(self) -> None:
        self._bambu_multinozzle_tower_only_export_active = False
        self.validate_form()
        self._refresh_stl_availability()
        if not self.export_button.isEnabled():
            return
        try:
            request = self._current_preview_request()
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self.result_label.setText(german_user_message(error))
            return
        preview = self.current_preview
        if not (
            preview is not None
            and self.preview_state is PreviewState.CURRENT
            and request.signature() == preview.request_signature
        ):
            self._invalidate_preview(
                "Die Einstellungen stimmen nicht mit der Generierung überein."
            )
            return
        if self._current_preview_was_exported():
            self._refresh_phase17_actions()
            return
        self._clear_result_notices()
        self._export_request_id += 1
        request_id = self._export_request_id
        self._set_export_button_state(
            False,
            "Ein Export wird bereits ausgeführt.",
        )
        self.preview_button.setEnabled(False)
        self.drop_zone.remove_button.setEnabled(False)
        self._refresh_folder_action_states()
        self.open_run_button.setEnabled(False)
        self._set_main_status(
            "Aktuelle Generierung wird ohne erneute Slicer-Läufe exportiert …",
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
            preview,
            request,
            Path(self.output_root_edit.text()).expanduser(),
            self.export_service,
        )
        worker.progress.connect(self._on_export_progress)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(self._on_export_failed)
        worker.finished.connect(self._on_export_finished)
        self.background_job_manager.start_job(
            kind=JobKind.EXPORT,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"export-{request_id}",
        )

    @Slot()
    def _on_main_export_clicked(self) -> None:
        if self.generation_mode is GenerationMode.MANUAL:
            self.manual_controller.export()
            return
        self.start_export()

    @Slot()
    def _export_from_generation_dialog(self) -> None:
        if self._joint_generation_dialog is not None:
            self._joint_generation_dialog.allow_programmatic_close()
            self._joint_generation_dialog.close()
        self._joint_generation_paused = False
        self._update_responsive_action_labels()
        self.start_export()

    @Slot(int, int, str)
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

    @Slot(int, object)
    def _on_export_succeeded(
        self,
        request_id: int,
        result: PreviewExportResult,
    ) -> None:
        if request_id != self._export_request_id or self._closing:
            return
        self.last_export_result = result
        self._last_export_report_result = result
        self._last_exported_preview_identity = self._preview_export_identity(
            self.current_preview
        )
        self._latest_export_directory = result.output_path.parent.resolve()
        self._latest_export_root_text = self.output_root_edit.text().strip()
        self._latest_export_unavailable_reason = ""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        kind = (
            "slicerbasiert kalibriert und Zielzeit erreicht"
            if result.calibrated
            else "sliceroptimierter bester Zwischenstand"
        )
        self._set_main_status(
            "STL erfolgreich exportiert", icon="✓", state="success"
        )
        self.result_label.setText(
            f"Datei: {result.output_path.name}\n"
            f"Erzeugungsart: {kind}\n"
            "Kurzbericht und technischer Bericht wurden im "
            "Exportordner gespeichert."
        )
        self.result_label.setToolTip(str(result.output_path))
        self._update_responsive_action_labels()
        self._refresh_folder_action_states()
        self._refresh_last_export_report_action()
        self._clear_result_notices()
        self._save_user_settings()
        self._bambu_multinozzle_tower_only_export_active = False
        self._refresh_phase17_actions()
        self._show_export_success_dialog(result)

    @Slot(int, str, str)
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
            "Export fehlgeschlagen: "
            f"{_concise_operation_failure_reason(message)}",
            icon="✕",
            state="error",
        )
        self.result_label.setText(german_user_message(message))
        self._bambu_multinozzle_tower_only_export_active = False
        self._refresh_phase17_actions()

    @Slot(int)
    def _on_export_finished(self, request_id: int) -> None:
        if request_id != self._export_request_id or self._closing:
            return
        self.drop_zone.remove_button.setEnabled(True)
        for delay_ms in (0, 50):
            QTimer.singleShot(delay_ms, self._refresh_phase17_actions)

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
        self._refresh_folder_action_states(rescan=True)
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
                "Der Exportordner konnte nicht geöffnet werden: "
                f"{german_user_message(error)}"
            )
            self._schedule_footer_height_update()

    def open_run_directory(self) -> None:
        if self.last_export_result is not None:
            open_path(self.last_export_result.user_report_path)

    def show_last_export_report(self) -> None:
        """Reopen the latest successful export confirmation without exporting."""

        result = self._last_export_report_result
        if result is None:
            return
        self._show_export_success_dialog(result)

    def _refresh_last_export_report_action(self) -> None:
        if not hasattr(self, "open_run_button"):
            return
        available = self._last_export_report_result is not None
        self.open_run_button.setVisible(available)
        self.open_run_button.setEnabled(
            available
            and not self.background_job_manager.has_active(JobKind.EXPORT)
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.generation_mode is GenerationMode.MANUAL:
            QTimer.singleShot(0,self.manual_controller.fit_editor_to_window)
        self._update_responsive_action_labels()
        self._update_slicer_combo_widths()
        if hasattr(self, "slicer_columns"):
            QTimer.singleShot(0, self._refresh_slicer_section_layout)
        if hasattr(self, "preparation_tabs"):
            QTimer.singleShot(0, self._refresh_preparation_section_layout)
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
        manual = self.generation_mode is GenerationMode.MANUAL
        self.reset_button.setText("Alles zurücksetzen" if manual else "Standardwerte wiederherstellen")
        controller = self.manual_controller
        if not manual:
            self.reset_button.setToolTip("Turmeinstellungen außerhalb der allgemeinen Einstellungen zurücksetzen")
        accepting = False
        cancelling = (
            controller.job_id is not None and controller.operation != "export"
            if manual else self.preview_state is PreviewState.BUILDING or self._joint_generation_paused
        )
        cancel_requested = controller.cancelled if manual else self._preview_cancel_requested
        for widget in (self.preview_action_control, self.preview_button):
            if widget.property("cancelAction") != cancelling:
                widget.setProperty("cancelAction", cancelling)
                self._refresh_widget_style(widget)
            if widget.property("acceptAction") != accepting:
                widget.setProperty("acceptAction", accepting)
                self._refresh_widget_style(widget)
        if manual:
            self.preview_button.setText(controller.panel.cancel_button.text() if cancelling else
                "Vorschau erneut vorbereiten" if controller.panel.draft is None and not controller.panel.retry_button.isHidden() else
                controller.panel.generate_button.text())
        elif cancelling:
            if cancel_requested:
                self.preview_button.setText("Abbruch wird ausgeführt …")
            else:
                self.preview_button.setText("Generierung abbrechen")
        elif self.current_preview is not None:
            self.preview_button.setText("Kühlturm aktualisieren")
        else:
            self.preview_button.setText("Kühlturm generieren")
        footer_inner_width = max(0, self.width() - 44)
        wide_action_width = max(0, (footer_inner_width - 13) // 2 - 12)
        folder_buttons = (
            self.open_output_button,
            self.open_stl_button,
            self.open_run_button,
        )
        report_visible = not self.open_run_button.isHidden()
        action_buttons = (self.preview_action_control, self.export_button)
        spacing = self.main_actions_layout.horizontalSpacing()

        def set_labels(
            shorten_folders: bool, report_label_level: int,
            shorten_actions: bool,
        ) -> None:
            self.open_output_button.setText(
                "Alle Exporte" if shorten_folders else "Alle Exporte öffnen"
            )
            self.open_stl_button.setText(
                "Letzter Export" if shorten_folders else "Letzten Export öffnen"
            )
            self.open_run_button.setText((
                "Letzten Exportbericht öffnen",
                "Exportbericht öffnen",
                "Exportbericht",
            )[report_label_level])
            self.export_button.setText(
                "Exportieren" if shorten_actions else "Kühlturm exportieren"
            )
            if cancelling and not cancel_requested:
                self.preview_button.setText(
                    "Abbrechen" if shorten_actions or manual else "Generierung abbrechen"
                )
            self.preview_action_control.setFixedWidth(max(
                0 if shorten_actions and cancelling
                else PREVIEW_ACTION_COMPACT_WIDTH_PX,
                QFontMetrics(self.preview_button.font()).horizontalAdvance(
                    self.preview_button.text()
                ) + 2 * EXPORT_ACTION_HORIZONTAL_PADDING_PX + 2,
            ))
            self._fit_export_button_width()

        def required_action_width() -> int:
            visible = [
                button for button in (*folder_buttons, *action_buttons)
                if not button.isHidden()
            ]
            return (
                sum(button.sizeHint().width() for button in visible)
                + spacing * max(0, len(visible) - 1)
                # Columns 2 and 3 may still reserve grid gaps between the
                # folder buttons and the right-aligned action group.
                + (2 * spacing if any(
                    not button.isHidden() for button in action_buttons
                ) and any(
                    not button.isHidden() for button in folder_buttons
                ) else 0)
                + (spacing + 2 if visible else 0)
            )

        for narrow, action_area_width in (
            (False, wide_action_width), (True, footer_inner_width)
        ):
            label_stages = [(False, 0, False)]
            if report_visible:
                label_stages.extend(((False, 1, False), (False, 2, False)))
            label_stages.append((True, 2 if report_visible else 0, False))
            label_stages.append((True, 2 if report_visible else 0, True))
            for shorten_folders, report_label_level, shorten_actions in label_stages:
                set_labels(shorten_folders, report_label_level, shorten_actions)
                if required_action_width() <= action_area_width:
                    break
            if required_action_width() <= action_area_width:
                break
        self._footer_layout_narrow_required = narrow
        self._refresh_footer_responsive_layout()

        required_width = required_action_width()
        primary_width = sum(
            button.sizeHint().width()
            for button in action_buttons if not button.isHidden()
        ) + spacing * max(0, sum(
            not button.isHidden() for button in action_buttons
        ) - 1)
        folder_pair_width = sum(
            button.sizeHint().width()
            for button in (self.open_output_button, self.open_stl_button)
            if not button.isHidden()
        )
        paired_width = (
            folder_pair_width + primary_width
            + spacing * 5 + 2
        )
        mode = (
            "single"
            if required_width <= action_area_width
            else "report_above"
            if report_visible and paired_width <= action_area_width
            else "report_and_action_above"
            if report_visible
            else "action_below"
        )
        if mode != getattr(self, "_footer_actions_layout_mode", None):
            self._footer_actions_layout_mode = mode
            self._footer_actions_wrapped = mode != "single"
            actions = self.main_actions_layout
            action_widgets = (
                self.open_output_button, self.open_stl_button,
                self.open_run_button, self.preview_action_control,
                self.export_button,
            )
            hidden_widgets = {
                widget: widget.isHidden() for widget in action_widgets
            }
            for widget in action_widgets:
                actions.removeWidget(widget)
            report_above = mode in {"report_above", "report_and_action_above"}
            folder_row = 1 if report_above else 0
            actions.setVerticalSpacing(8 if mode != "single" else 0)
            actions.addWidget(
                self.open_output_button, folder_row, 0,
                Qt.AlignmentFlag.AlignBottom,
            )
            actions.addWidget(
                self.open_stl_button, folder_row, 1,
                Qt.AlignmentFlag.AlignBottom,
            )
            if report_above:
                actions.addWidget(
                    self.open_run_button, 0, 0, 1, 2,
                    Qt.AlignmentFlag.AlignLeft,
                )
            else:
                actions.addWidget(
                    self.open_run_button, 0, 2,
                    Qt.AlignmentFlag.AlignBottom,
                )
            if mode in {"action_below", "report_and_action_above"}:
                action_row = folder_row + 1
                actions.addWidget(
                    self.preview_action_control, action_row, 0, 1, 5,
                    Qt.AlignmentFlag.AlignRight,
                )
                actions.addWidget(
                    self.export_button, action_row, 5,
                    Qt.AlignmentFlag.AlignRight,
                )
            else:
                actions.addWidget(
                    self.preview_action_control,
                    folder_row, 4, Qt.AlignmentFlag.AlignBottom,
                )
                actions.addWidget(
                    self.export_button,
                    folder_row, 5, Qt.AlignmentFlag.AlignBottom,
                )
            actions.invalidate()
            for widget, hidden in hidden_widgets.items():
                widget.setVisible(not hidden)

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

    def _refresh_folder_action_states(self, *, rescan: bool = False) -> None:
        if not hasattr(self, "open_output_button"):
            return
        output_root_text = self.output_root_edit.text().strip()
        self.open_output_button.setEnabled(bool(output_root_text))
        known_directory_missing = bool(
            self._latest_export_directory is not None
            and not self._latest_export_directory.is_dir()
        )
        if (
            rescan
            or output_root_text != self._latest_export_root_text
            or known_directory_missing
        ):
            resolution = resolve_latest_export_directory(
                output_root_text,
                preferred_directory=self._latest_export_directory,
            )
            self._latest_export_directory = resolution.directory
            self._latest_export_unavailable_reason = (
                resolution.unavailable_reason or ""
            )
            self._latest_export_root_text = output_root_text
        latest_export_available = self._latest_export_directory is not None
        self.open_stl_button.setEnabled(latest_export_available)
        self.open_stl_button.setToolTip(
            "Den Ordner des zuletzt erstellten Exports öffnen"
            if latest_export_available
            else self._latest_export_unavailable_reason
        )
        self._refresh_last_export_report_action()

    def _has_non_default_settings(self) -> bool:
        defaults = self.settings_store.load_defaults()
        return self.collect_settings() != replace(
            defaults,
            local_reference_window=self.local_window_spin.value(),
            layer_time_tolerance_s=self.layer_time_tolerance_spin.value(),
        )

    def request_reset_defaults(self) -> None:
        if self.generation_mode is GenerationMode.MANUAL:
            self.manual_controller.request_reset_defaults()
            return
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
            "Alle abweichenden Einstellungen außerhalb der allgemeinen "
            "Einstellungen werden auf ihre Standardwerte zurückgesetzt. "
            "Die bisherigen Änderungen gehen dadurch verloren."
        )
        yes_button = box.addButton("Ja", QMessageBox.ButtonRole.AcceptRole)
        no_button = box.addButton("Nein", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no_button)
        box.setEscapeButton(no_button)
        box._reset_yes_button = yes_button  # type: ignore[attr-defined]
        box._reset_no_button = no_button  # type: ignore[attr-defined]
        return box

    def reset_defaults(self) -> None:
        self._feasibility_timer.stop()
        self._feasibility_request_id += 1
        self._cancel_feasibility_jobs()
        self.profile_feasibility = None
        self._clear_feasibility_issues()
        self._last_changed_setting_name = None
        self.apply_settings(replace(
            self.settings_store.load_defaults(),
            local_reference_window=self.local_window_spin.value(),
            layer_time_tolerance_s=self.layer_time_tolerance_spin.value(),
        ))
        self._incomplete_setting_names.clear()
        if self.analysis_snapshot is not None:
            self._update_local_window_layer_limit(self.analysis_snapshot.layer_count)
            self._setting_widgets["local_reference_window"].refresh_reset_state()
        self._pending_preview_camera_state = None
        if self._preview_dialog is not None:
            canvas = self._preview_dialog.canvas
            canvas.three_quarter_view()
        self.timing_group.setChecked(True)
        self.prediction_frame.setChecked(True)
        self.geometry_settings_group.setChecked(True)
        self._invalidate_preview("Alle Einstellungen wurden zurückgesetzt.")
        self.update_wall_path_preview()
        self._refresh_tower_assessment()
        self.validate_form()
        self._schedule_feasibility_validation()

    def _save_user_settings(self) -> None:
        self.manual_controller.save_settings()
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
                preview_iterations=self.preview_iterations,
                maximum_separate_slices=self.maximum_separate_slices,
                maximum_joint_slices=self.maximum_joint_slices,
                show_setting_limits=self.show_setting_limits,
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
        self._pending_support_retry = None
        self._pending_support_profile_reload = None
        if self._support_simulation_dialog is not None:
            self._support_simulation_dialog.reject()
        if self._draft_shield_dialog is not None:
            self._draft_shield_dialog.reject()
        self._pending_slicer_discovery = None
        self._pending_profile_match = None
        self._feasibility_timer.stop()
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
        self._cleanup_source_preslice_result()
        for session in self.generation_sessions.values():
            session.discard_preview()
        if self._preview_dialog is not None:
            self._preview_dialog.close()
        if self._additional_options_dialog is not None:
            self._additional_options_dialog.close()
        if self._about_dialog is not None:
            self._about_dialog.close()
        if self._export_success_dialog is not None:
            self._export_success_dialog.close()
        if self._support_report_dialog is not None:
            self._support_report_dialog.close()
        self._hint_controller.dispose()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self._internal_dialog_reveal_filter)
        super().closeEvent(event)
