"""Explicit technical vocabulary for support exports; unknown text never leaves local logs.

Changes to this vocabulary require privacy review. Do not populate it from user
profiles, runtime logs, exception messages or environment variables.
"""
from __future__ import annotations

import builtins
import math
import re
from collections.abc import Mapping
from itertools import islice
from datetime import datetime
from typing import Any


MAX_ITEMS = 100
OMITTED_TEXT = "<Freitext ausgelassen>"
_VERSION = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}(?:(?:a|b|rc|dev)[0-9]{1,4})?")
_NUMERIC_KEY = re.compile(r"(?:_count|_bytes|_s|_ms|_mm|_deg)$")
_ERROR_SUFFIXES = frozenset({
    "file_not_found", "access_denied", "timeout", "encoding_error", "io_error",
    "invalid_data", "runtime_error", "unexpected_error",
})
_ERROR_OPERATIONS = frozenset({
    "slicer_discovery", "profile_matching", "profile_catalog", "preview_generation",
    "source_preslice", "stl_validation", "main_thread_exception", "worker_thread_exception",
    "application_startup",
})
SAFE_ERROR_TYPES = frozenset(
    name for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)

# Keys are also data: never copy arbitrary mapping keys, including profile names.
CONTEXT_KEYS = frozenset({
    "workflow_stage", "source", "source_kind", "loaded", "suffix", "size_bytes",
    "analysis_gcode_available", "gcode_origin", "preslice_cache_hit", "analysis",
    "available", "failed", "slicer", "search_completed", "installations", "selected",
    "profile", "unfiltered_option_counts", "visible_option_counts", "preview", "export",
    "last_export_available", "settings", "active_background_jobs",
    "profile_name", "machine_profile_name", "process_profile_name", "filament_profile_name",
})
SETTING_KEYS = frozenset({
    "target_layer_time_s", "layer_time_tolerance_s", "minimum_outer_diameter_mm",
    "maximum_outer_diameter_mm", "minimum_object_tower_distance_mm",
    "simulate_full_tower_infill", "simulate_tower_without_supports", "simulate_source_supports",
    "minimum_base_radius_mm", "base_margin_mm", "base_height_factor", "automatic_base_width",
    "manual_base_width_mm", "minimum_radius_height_factor", "maximum_radius_change_per_mm_z",
    "maximum_expansion_angle_deg", "maximum_contraction_angle_deg", "local_reference_window",
})
_TEXT_KEYS = frozenset({
    "message", "error_message", "visible_error", "status_text", "diagnostics",
    "failure_reason", "error_scope",
})


def sanitize_technical(value: Any, *, allowed_keys: frozenset[str], key: str = "", depth: int = 0) -> Any:
    """Fail closed for fields and strings, including nested containers and keys."""
    if depth > 8:
        return "<Verschachtelung ausgelassen>"
    if key in _TEXT_KEYS:
        return OMITTED_TEXT
    if key.endswith("profile_name"):
        return "Profil 1"
    if isinstance(value, Mapping):
        return {
            child_key: sanitize_technical(child_value, allowed_keys=allowed_keys, key=child_key, depth=depth + 1)
            for child_key, child_value in islice(value.items(), MAX_ITEMS)
            if isinstance(child_key, str) and child_key in allowed_keys
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_technical(item, allowed_keys=allowed_keys, key=key, depth=depth + 1)
                for item in islice(value, MAX_ITEMS)]
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if key == "return_code":
            return value if isinstance(value, int) and -(2**31) <= value < 2**32 else None
        if (key in SETTING_KEYS or _NUMERIC_KEY.search(key)
                or key in {"event_sequence", "return_code", "timeout_ms", "diagnostic_event_schema_version",
                           "calibration_round", "layer_count", "unfiltered_option_counts", "visible_option_counts"}):
            try:
                return value if math.isfinite(value) and abs(value) <= 1_000_000_000 else None
            except OverflowError:
                return None
        return None
    if not isinstance(value, str) or len(value) > 128:
        return OMITTED_TEXT
    if key in {"utc_time", "started_utc", "finished_utc"}:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None
    if key in {"version", "program_version"}:
        return value if _VERSION.fullmatch(value) else "<Version ausgelassen>"
    if key in {"event", "source_event"}:
        return value if value in SAFE_EVENTS else "unknown_event"
    if key == "error_type":
        return value if value in SAFE_ERROR_TYPES else "Exception"
    if key == "suffix":
        return value if value in {".stl", ".gcode", ".bgcode"} else "<Dateityp ausgelassen>"
    if key in {"result_code", "error_code"}:
        valid_errors = {f"{op}_{suffix}" for op in _ERROR_OPERATIONS for suffix in _ERROR_SUFFIXES}
        valid_results = {f"slicer_{state}" for state in (
            "available", "available_and_recommended", "needs_manual_path", "unsupported", "not_found", "unknown")}
        valid_results.update(f"profile_{state}" for state in (
            "matched", "reconstructed", "compatible", "ambiguous", "unavailable", "unknown"))
        return value if value in valid_errors | valid_results | SAFE_TOKENS else "unknown_code"
    return value if value in SAFE_TOKENS else OMITTED_TEXT

SAFE_EVENTS = frozenset({
    'application_startup_failed',
    'calibration_joint_stagnated',
    'calibration_round_finished',
    'calibration_round_started',
    'calibration_slicer_retry',
    'gcode_analysis_memory_cache_hit',
    'gcode_native_full_analysis',
    'gcode_native_full_analysis_fallback',
    'gcode_native_planning_cache_analysis',
    'gcode_python_block_cache_analysis',
    'geometry_created',
    'invalid_job_transition',
    'job_cancel_callback_failed',
    'job_cancel_repeated',
    'job_cancel_requested',
    'job_released',
    'job_shutdown_finished',
    'job_shutdown_timeout',
    'job_started',
    'job_state_changed',
    'job_thread_started',
    'job_worker_failed',
    'job_worker_finished',
    'job_worker_succeeded',
    'persistent_analysis_cache_hit',
    'persistent_analysis_cache_load_failed',
    'persistent_analysis_cache_miss',
    'persistent_analysis_cache_stored',
    'persistent_analysis_cache_write_failed',
    'preview_build_state_changed',
    'preview_generation_cancelled',
    'preview_generation_failed',
    'preview_generation_finished',
    'preview_generation_started',
    'preview_progress',
    'preview_request_accepted',
    'preview_result_accepted',
    'preview_result_discarded',
    'preview_source_cache_hit',
    'preview_source_cache_miss',
    'preview_source_cache_stored',
    'preview_source_combined_analysis_used',
    'previous_crash_report_discarded',
    'profile_catalog_failed',
    'profile_catalog_finished',
    'profile_catalog_started',
    'profile_matching_cancelled',
    'profile_matching_failed',
    'profile_matching_finished',
    'profile_matching_started',
    'qt_message',
    'session_finished',
    'session_started',
    'slice_job_failed',
    'slice_job_prepared',
    'slice_output_files_checked',
    'slicer_candidate_rejected',
    'slicer_candidate_verified',
    'slicer_discovery_cancelled',
    'slicer_discovery_completed',
    'slicer_discovery_failed',
    'slicer_discovery_finished',
    'slicer_discovery_started',
    'slicer_native_layer_times',
    'slicer_process_error',
    'slicer_process_finished',
    'slicer_process_force_stopped',
    'slicer_process_started',
    'slicer_process_state',
    'slicer_process_state_callback_failed',
    'slicer_process_stop_requested',
    'source_preslice_cancelled',
    'source_preslice_failed',
    'source_preslice_finished',
    'source_preslice_started',
    'stl_validation_cancelled',
    'stl_validation_failed',
    'stl_validation_finished',
    'stl_validation_started',
    'stress_finalizer_timeout',
    'support_report_bundle_created',
    'support_report_bundle_failed',
    'support_report_bundle_started',
    'temporary_data_cleaned',
    'unhandled_python_exception',
    'windows_process_policy',
})

SAFE_TOKENS = frozenset({
    'AMD64',
    'ARM64',
    'Darwin',
    'ExportWorker',
    'False',
    'FeasibilityWorker',
    'Linux',
    'ManualViewWorker',
    'ManualWorker',
    'OrcaSlicer',
    'PreviewWorker',
    'ProfileCatalogWorker',
    'ProfileMatchingWorker',
    'PrusaSlicer',
    'RasterObjectPicture',
    'Simplify3D',
    'SlicerDiscoveryWorker',
    'SourcePreSliceWorker',
    'SpatialFrame',
    'StlValidationWorker',
    'True',
    'UltiMaker Cura',
    'Unknown slicer',
    'UpdateCheckWorker',
    'UpdateDownloadWorker',
    'Windows',
    'aarch64',
    'absent',
    'active',
    'ambiguous',
    'analyzing_preslice',
    'anycubic_profile_compatibility',
    'anycubic_slicer_next',
    'app_paths',
    'application_startup',
    'ascii',
    'auto',
    'auto_arrange',
    'automatic',
    'available',
    'available_and_recommended',
    'bambu_studio',
    'base',
    'behavioral_signature',
    'binary',
    'boundary_edge',
    'build_volume_too_small',
    'building',
    'bypassed',
    'calibration_preparing',
    'cancel_requested',
    'cancelled',
    'cli_slice',
    'compatible',
    'converged',
    'created',
    'critical',
    'cura',
    'current',
    'custom_profiles',
    'definition',
    'degenerate_face',
    'degraded',
    'detailed',
    'detection_only',
    'discovering_slicer',
    'duplicate_face',
    'empty',
    'enabled',
    'error',
    'evaluating',
    'explicit',
    'export',
    'extruder_count_mismatch',
    'failed',
    'feasibility',
    'filament',
    'filename_hint',
    'final_timing_deficit',
    'finalizing',
    'finished',
    'footer_config',
    'full',
    'gcode',
    'gcode_dialect_mismatch',
    'gcode_integration_failure',
    'gcode_metadata',
    'gcode_reconstruction',
    'generated_preslice',
    'geometry_invalid',
    'header_comment',
    'ideaMaker',
    'ideamaker',
    'idle',
    'incompatible_profile_combination',
    'incompatible_profile_version',
    'inconsistent_winding',
    'invalid',
    'invalid_format',
    'invalid_geometry',
    'invalid_value',
    'iteration_limit',
    'known_path',
    'layer_mismatch',
    'legacy',
    'limit_reached',
    'machine',
    'machine_command',
    'machine_model',
    'machine_variant',
    'manual',
    'manual-view',
    'manual_slicer_candidate_verified',
    'matched',
    'matching_profiles',
    'maximum_radius',
    'maximum_wall_thickness',
    'microsoft-store',
    'motion_aware',
    'needs_manual_path',
    'neutral',
    'no_bed_space',
    'nominal_only',
    'non_manifold_edge',
    'non_positive_volume',
    'none',
    'normal',
    'not_found',
    'not_selected',
    'not_started',
    'nozzle_mismatch',
    'object_override_rejected',
    'orca_bambu_anycubic',
    'orca_slicer',
    'other',
    'output_directory',
    'partial',
    'prediction',
    'preparing',
    'preslice',
    'preslicing_model',
    'preview',
    'preview_directory',
    'preview_generation_cancelled',
    'preview_generation_succeeded',
    'probe_validated',
    'process',
    'process_cancellation',
    'profile',
    'profile_incomplete',
    'profile_inventory',
    'profile_inventory_unchanged',
    'profile_matching_cancelled',
    'project',
    'prusa_slic3r',
    'prusa_slicer',
    'qprocess',
    'quality',
    'ready',
    'reconstructed',
    'registry_system',
    'registry_user',
    'rejected',
    'released',
    'resource_limit',
    'running',
    'runtime_limit',
    'saved_path',
    'selected',
    'self_intersection',
    'session',
    'simplify3d',
    'slicer',
    'slicer_adapter_not_found',
    'slicer_calibrated',
    'slicer_candidate_verified',
    'slicer_discovery_cancelled',
    'slicer_executable_missing',
    'slicer_failed',
    'slicer_failure',
    'slicer_running',
    'slicer_timing_mismatch',
    'slicer_working_directory',
    'source_invalid',
    'source_version_mismatch',
    'stale',
    'stalled',
    'standalone',
    'start_menu',
    'starting',
    'stl',
    'stl-validation',
    'strong_signature',
    'structurally_valid',
    'subprocess',
    'succeeded',
    'success',
    'system',
    'temporary',
    'temporary_effective_profile',
    'thread_finished',
    'transition_angle',
    'unavailable',
    'unknown',
    'unresolved_inheritance',
    'unsupported',
    'unsupported_gcode',
    'unsupported_tool_change',
    'unverified',
    'update-check',
    'update-download',
    'user',
    'user_confirmation',
    'user_override',
    'valid',
    'validating_source',
    'validating_stl',
    'verified',
    'waiting_for_profile_confirmation',
    'waiting_for_source',
    'warning',
    'weak_signature',
    'worker_finished',
    'wrong_technology',
    'x86_64',
})
