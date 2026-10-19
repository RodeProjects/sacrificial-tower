#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace cooling_tower::native_analysis {

enum class Status {
    success,
    unsupported_syntax,
    cancelled,
    io_error,
    invalid_result,
};

struct LayerResult {
    std::int64_t index = 0;
    double z_mm = 0.0;
    double height_mm = 0.0;
    std::int64_t start_line = 0;
    std::int64_t first_deposition_line = 0;
    std::int64_t end_line = 0;
    std::int64_t event_count = 0;
    std::int64_t movement_count = 0;
    std::int64_t deposition_count = 0;
    double total_time_s = 0.0;
    double deposition_time_s = 0.0;
    double travel_time_s = 0.0;
    double retraction_time_s = 0.0;
    double unretraction_time_s = 0.0;
    double dwell_time_s = 0.0;
    double other_time_s = 0.0;
    double deposition_path_mm = 0.0;
    double deposition_e_mm = 0.0;
    std::int64_t untimed_event_count = 0;
    double untimed_distance_mm = 0.0;
};

struct PreviewSegment {
    double start_x = 0.0;
    double start_y = 0.0;
    double start_z = 0.0;
    double end_x = 0.0;
    double end_y = 0.0;
    double end_z = 0.0;
};

struct MetadataEvent {
    std::int64_t line_number = 0;
    std::string command;
    std::vector<std::pair<std::string, double>> parameters;
    std::string comment;
    bool has_command = false;
    bool has_comment = false;
};

struct InfillEvidence {
    std::int64_t tower_block_count = 0;
    bool sparse_tower_infill = false;
    std::map<std::int64_t, std::vector<double>> label_bounds;
    std::vector<std::int64_t> sparse_labels;
};

struct Diagnostics {
    std::uint64_t bytes_read = 0;
    std::uint64_t line_count = 0;
    std::uint64_t movement_count = 0;
    std::uint64_t dwell_count = 0;
    std::uint64_t metadata_event_count = 0;
    std::uint64_t planner_flush_count = 0;
    std::uint64_t peak_pending_movements = 0;
    std::uint64_t preview_candidate_count = 0;
    std::uint64_t anycubic_startup_macro_count = 0;
};

struct Options {
    bool bambu_compatible = false;
    bool orca_compatible = false;
    bool prusa_compatible = false;
    bool orca_marlin2 = false;
    std::map<std::string, double> orca_limits;
    bool anycubic_slicer_next_compatible = false;
    bool use_explicit_layer_markers = false;
    bool collect_preview = false;
    bool collect_infill_evidence = false;
    std::size_t maximum_preview_segments = 60000;
    std::size_t cancellation_interval_lines = 2048;
    std::function<bool(std::uint64_t, std::uint64_t)> should_cancel;
};

struct Result {
    Status status = Status::invalid_result;
    std::string message;
    std::int64_t fallback_line = 0;
    std::string fallback_command;
    std::vector<LayerResult> layers;
    std::int64_t confirmed_layer_changes = 0;
    std::int64_t rejected_z_candidates = 0;
    std::int64_t pre_layer_event_count = 0;
    double pre_layer_time_s = 0.0;
    std::int64_t pre_layer_untimed_event_count = 0;
    std::vector<MetadataEvent> metadata_events;
    std::vector<PreviewSegment> preview_segments;
    std::uint64_t preview_source_segment_count = 0;
    bool has_occupied_bounds = false;
    double minimum_x = 0.0;
    double maximum_x = 0.0;
    double minimum_y = 0.0;
    double maximum_y = 0.0;
    InfillEvidence infill;
    Diagnostics diagnostics;
};

Result analyze_file(const std::filesystem::path& path, const Options& options);
const char* status_name(Status status) noexcept;

}  // namespace cooling_tower::native_analysis
