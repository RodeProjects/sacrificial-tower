#include "native_analysis.hpp"
#include "orca_timing.hpp"
#include "prusa_timing.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

namespace cooling_tower::native_analysis {
namespace {

constexpr double MOVEMENT_EPSILON = 1e-9;
constexpr double ARC_EPSILON = 1e-7;
constexpr double Z_EPSILON_MM = 1e-4;
constexpr double EXTRUSION_EPSILON_MM = 1e-9;
constexpr double PI = 3.141592653589793238462643383279502884;
constexpr std::size_t LOOKAHEAD_MOVEMENTS = 64;
constexpr std::size_t REFRESH_THRESHOLD_MOVEMENTS = 4096;
constexpr std::size_t ROW_WIDTH = 38;

double missing() noexcept {
    return std::numeric_limits<double>::quiet_NaN();
}

bool present(const double value) noexcept {
    return !std::isnan(value);
}

bool ascii_space(const char value) noexcept {
    return value == ' ' || value == '\t' || value == '\r'
        || value == '\n' || value == '\f' || value == '\v';
}

bool ascii_alpha(const char value) noexcept {
    return (value >= 'A' && value <= 'Z')
        || (value >= 'a' && value <= 'z');
}

bool ascii_digit(const char value) noexcept {
    return value >= '0' && value <= '9';
}

char ascii_upper(const char value) noexcept {
    return value >= 'a' && value <= 'z'
        ? static_cast<char>(value - ('a' - 'A'))
        : value;
}

char ascii_lower(const char value) noexcept {
    return value >= 'A' && value <= 'Z'
        ? static_cast<char>(value + ('a' - 'A'))
        : value;
}

std::string trim(std::string value) {
    std::size_t begin = 0;
    while (begin < value.size() && ascii_space(value[begin])) {
        ++begin;
    }
    std::size_t end = value.size();
    while (end > begin && ascii_space(value[end - 1])) {
        --end;
    }
    return value.substr(begin, end - begin);
}

std::string uppercase(std::string value) {
    for (char& character : value) {
        character = ascii_upper(character);
    }
    return value;
}

std::string lowercase(std::string value) {
    for (char& character : value) {
        character = ascii_lower(character);
    }
    return value;
}

bool starts_with(const std::string& value, const std::string& prefix) {
    return value.size() >= prefix.size()
        && value.compare(0, prefix.size(), prefix) == 0;
}

bool parse_number(
    const std::string& text,
    const std::size_t begin,
    std::size_t& end,
    double& value
) {
    std::size_t cursor = begin;
    if (cursor < text.size() && (text[cursor] == '+' || text[cursor] == '-')) {
        ++cursor;
    }
    const std::size_t integer_begin = cursor;
    while (cursor < text.size() && ascii_digit(text[cursor])) {
        ++cursor;
    }
    const bool has_integer = cursor > integer_begin;
    bool has_fraction = false;
    if (cursor < text.size() && text[cursor] == '.') {
        ++cursor;
        const std::size_t fraction_begin = cursor;
        while (cursor < text.size() && ascii_digit(text[cursor])) {
            ++cursor;
        }
        has_fraction = cursor > fraction_begin;
    }
    if (!has_integer && !has_fraction) {
        return false;
    }
    if (cursor < text.size() && (text[cursor] == 'e' || text[cursor] == 'E')) {
        std::size_t exponent = cursor + 1;
        if (exponent < text.size() && (text[exponent] == '+' || text[exponent] == '-')) {
            ++exponent;
        }
        const std::size_t exponent_begin = exponent;
        while (exponent < text.size() && ascii_digit(text[exponent])) {
            ++exponent;
        }
        if (exponent > exponent_begin) {
            cursor = exponent;
        }
    }
    const std::string number = text.substr(begin, cursor - begin);
    char* parsed_end = nullptr;
    value = std::strtod(number.c_str(), &parsed_end);
    if (
        parsed_end != number.c_str() + number.size()
        || !std::isfinite(value)
    ) {
        return false;
    }
    end = cursor;
    return true;
}

struct ParsedLine {
    std::int64_t number = 0;
    std::string code;
    std::string command;
    std::map<std::string, double> parameters;
    std::string comment;
    std::string unparsed;
    bool has_command = false;
    bool has_comment = false;
};

std::string normalize_command(std::string command) {
    command = uppercase(std::move(command));
    if (command.size() < 2 || (
        command[0] != 'G' && command[0] != 'M' && command[0] != 'T'
    )) {
        return command;
    }
    std::size_t end = 1;
    double numeric = 0.0;
    if (!parse_number(command, 1, end, numeric) || end != command.size()) {
        return command;
    }
    const double integral = std::trunc(numeric);
    if (numeric == integral) {
        return std::string(1, command[0])
            + std::to_string(static_cast<long long>(integral));
    }
    return command;
}

void split_comments(const std::string& raw, std::string& code, std::string& comment, bool& has_comment) {
    const std::size_t semicolon = raw.find(';');
    std::string code_part = semicolon == std::string::npos
        ? raw : raw.substr(0, semicolon);
    std::vector<std::string> comments;
    std::string without_parentheses;
    without_parentheses.reserve(code_part.size());
    std::size_t cursor = 0;
    while (cursor < code_part.size()) {
        const std::size_t open = code_part.find('(', cursor);
        if (open == std::string::npos) {
            without_parentheses.append(code_part, cursor, std::string::npos);
            break;
        }
        without_parentheses.append(code_part, cursor, open - cursor);
        const std::size_t close = code_part.find(')', open + 1);
        if (close == std::string::npos) {
            without_parentheses.append(code_part, open, std::string::npos);
            break;
        }
        has_comment = true;
        const std::string item = trim(code_part.substr(open + 1, close - open - 1));
        if (!item.empty()) {
            comments.push_back(item);
        }
        without_parentheses.push_back(' ');
        cursor = close + 1;
    }
    if (code_part.empty()) {
        without_parentheses.clear();
    }
    if (semicolon != std::string::npos) {
        has_comment = true;
        const std::string item = trim(raw.substr(semicolon + 1));
        if (!item.empty()) {
            comments.push_back(item);
        }
    }
    code = trim(std::move(without_parentheses));
    for (std::size_t index = 0; index < comments.size(); ++index) {
        if (index > 0) {
            comment += " | ";
        }
        comment += comments[index];
    }
}

ParsedLine parse_line(std::string raw, const std::int64_t number) {
    ParsedLine result;
    result.number = number;
    if (number == 1 && raw.size() >= 3
        && static_cast<unsigned char>(raw[0]) == 0xef
        && static_cast<unsigned char>(raw[1]) == 0xbb
        && static_cast<unsigned char>(raw[2]) == 0xbf) {
        raw.erase(0, 3);
    }
    if (raw.empty()) {
        return result;
    }
    if (raw.front() == ';') {
        result.has_comment = true;
        result.comment = trim(raw.substr(1));
        return result;
    }
    split_comments(raw, result.code, result.comment, result.has_comment);

    const std::size_t checksum = result.code.rfind('*');
    if (checksum != std::string::npos) {
        std::size_t cursor = checksum + 1;
        while (cursor < result.code.size() && ascii_space(result.code[cursor])) {
            ++cursor;
        }
        const std::size_t digits = cursor;
        while (cursor < result.code.size() && ascii_digit(result.code[cursor])) {
            ++cursor;
        }
        while (cursor < result.code.size() && ascii_space(result.code[cursor])) {
            ++cursor;
        }
        if (cursor == result.code.size() && cursor > digits) {
            result.code = trim(result.code.substr(0, checksum));
        }
    }
    if (result.code.size() >= 2
        && (result.code[0] == 'N' || result.code[0] == 'n')
        && ascii_digit(result.code[1])) {
        std::size_t cursor = 2;
        while (cursor < result.code.size() && ascii_digit(result.code[cursor])) {
            ++cursor;
        }
        while (cursor < result.code.size() && ascii_space(result.code[cursor])) {
            ++cursor;
        }
        result.code = result.code.substr(cursor);
    }
    result.code = trim(std::move(result.code));
    if (result.code.empty()) {
        return result;
    }

    std::size_t command_end = 0;
    if (ascii_alpha(result.code[0])) {
        std::size_t letters_end = 1;
        while (letters_end < result.code.size() && ascii_alpha(result.code[letters_end])) {
            ++letters_end;
        }
        if (letters_end < result.code.size() && result.code[letters_end] == '_') {
            std::size_t cursor = letters_end;
            bool valid = true;
            while (cursor < result.code.size() && result.code[cursor] == '_') {
                ++cursor;
                const std::size_t segment_begin = cursor;
                while (cursor < result.code.size()
                    && (ascii_alpha(result.code[cursor]) || ascii_digit(result.code[cursor]))) {
                    ++cursor;
                }
                if (cursor == segment_begin) {
                    valid = false;
                    break;
                }
            }
            if (valid) {
                command_end = cursor;
            }
        } else if (letters_end == 1) {
            double ignored = 0.0;
            std::size_t number_end = 1;
            if (parse_number(result.code, 1, number_end, ignored)) {
                command_end = number_end;
            }
        }
    }
    if (command_end == 0) {
        result.unparsed = result.code;
        return result;
    }
    result.has_command = true;
    result.command = normalize_command(result.code.substr(0, command_end));
    const std::string parameter_text = result.code.substr(command_end);
    const bool named = parameter_text.find('=') != std::string::npos;
    std::size_t cursor = 0;
    while (cursor < parameter_text.size()) {
        const std::size_t parameter_begin = cursor;
        while (cursor < parameter_text.size() && ascii_space(parameter_text[cursor])) {
            ++cursor;
        }
        std::string name;
        if (named) {
            if (cursor >= parameter_text.size()
                || (!ascii_alpha(parameter_text[cursor]) && parameter_text[cursor] != '_')) {
                cursor = parameter_begin;
                break;
            }
            const std::size_t name_begin = cursor++;
            while (cursor < parameter_text.size()
                && (ascii_alpha(parameter_text[cursor])
                    || ascii_digit(parameter_text[cursor])
                    || parameter_text[cursor] == '_')) {
                ++cursor;
            }
            name = uppercase(parameter_text.substr(name_begin, cursor - name_begin));
            while (cursor < parameter_text.size() && ascii_space(parameter_text[cursor])) {
                ++cursor;
            }
            if (cursor >= parameter_text.size() || parameter_text[cursor] != '=') {
                cursor = parameter_begin;
                break;
            }
            ++cursor;
            while (cursor < parameter_text.size() && ascii_space(parameter_text[cursor])) {
                ++cursor;
            }
        } else {
            if (cursor >= parameter_text.size() || !ascii_alpha(parameter_text[cursor])) {
                cursor = parameter_begin;
                break;
            }
            name.assign(1, ascii_upper(parameter_text[cursor++]));
            while (cursor < parameter_text.size() && ascii_space(parameter_text[cursor])) {
                ++cursor;
            }
        }
        std::size_t number_end = cursor;
        double value = 0.0;
        if (!parse_number(parameter_text, cursor, number_end, value)) {
            cursor = parameter_begin;
            break;
        }
        result.parameters[name] = value;
        cursor = number_end;
    }
    result.unparsed = trim(parameter_text.substr(cursor));
    return result;
}

double parameter(const ParsedLine& line, const std::string& name, const double fallback = missing()) {
    const auto found = line.parameters.find(name);
    return found == line.parameters.end() ? fallback : found->second;
}

bool has_parameter(const ParsedLine& line, const std::string& name) {
    return line.parameters.find(name) != line.parameters.end();
}

enum RowIndex : std::size_t {
    ENDPOINT_XY = 0, ENDPOINT_XYZ, DELTA_X, DELTA_Y, DELTA_Z, DELTA_E,
    PATH_LENGTH, EFFECTIVE_FEEDRATE, TIMING_DISTANCE, ACCELERATION,
    JERK_X, JERK_Y, JERK_Z, JERK_E, SQUARE_CORNER_VELOCITY,
    ENTRY_DIRECTION_X, ENTRY_DIRECTION_Y, ENTRY_DIRECTION_Z,
    EXIT_DIRECTION_X, EXIT_DIRECTION_Y, EXIT_DIRECTION_Z,
    ARC_PLANAR_LENGTH, ARC_START_RADIUS, ARC_SWEEP_DEGREES,
    MAXIMUM_FEEDRATE_X, MAXIMUM_FEEDRATE_Y, MAXIMUM_FEEDRATE_Z,
    MAXIMUM_FEEDRATE_E, MINIMUM_EXTRUDING_FEEDRATE,
    MINIMUM_TRAVEL_FEEDRATE, EXTRUSION_FACTOR,
    CENTRIPETAL_ACCELERATION, IS_ARC,
    JUNCTION_DEVIATION, MAXIMUM_ACCELERATION_X, MAXIMUM_ACCELERATION_Y,
    MAXIMUM_ACCELERATION_Z, MAXIMUM_ACCELERATION_E,
};

using Row = std::array<double, ROW_WIDTH>;

enum class Category {
    deposition,
    travel,
    travel_with_retraction,
    retraction,
    unretraction,
    feedrate_only,
    no_op,
};

struct Movement {
    std::int64_t line_number = 0;
    std::string command;
    double start_x = 0.0;
    double start_y = 0.0;
    double start_z = 0.0;
    double start_e = 0.0;
    double end_x = 0.0;
    double end_y = 0.0;
    double end_z = 0.0;
    double end_e = 0.0;
    double delta_x = 0.0;
    double delta_y = 0.0;
    double delta_z = 0.0;
    double delta_e = 0.0;
    double path_length = missing();
    double duration = missing();
    double entry_speed = missing();
    double exit_speed = missing();
    Category category = Category::no_op;
    Row row{};
};

struct Dwell {
    std::int64_t line_number = 0;
    double duration = missing();
};

using Event = std::variant<Movement, Dwell>;

struct MachineState {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double e = 0.0;
    double feedrate = missing();
    double speed_factor_percent = 100.0;
    double unit_scale_mm = 1.0;
    double print_acceleration = missing();
    double travel_acceleration = missing();
    double retract_acceleration = missing();
    double maximum_acceleration_x = missing();
    double maximum_acceleration_y = missing();
    double maximum_acceleration_z = missing();
    double maximum_acceleration_e = missing();
    double maximum_feedrate_x = missing();
    double maximum_feedrate_y = missing();
    double maximum_feedrate_z = missing();
    double maximum_feedrate_e = missing();
    double minimum_extruding_feedrate = missing();
    double minimum_travel_feedrate = missing();
    double extrusion_factor = 1.0;
    double jerk_x = missing();
    double jerk_y = missing();
    double jerk_z = missing();
    double jerk_e = missing();
    double junction_deviation = 0.0;
    double square_corner_velocity = missing();
    bool xyz_relative = false;
    bool extrusion_relative = false;
    bool arc_center_relative = true;
    std::string arc_plane = "XY";
    int active_tool = -1;
    bool movement_seen = false;
    std::uint64_t anycubic_startup_macro_count = 0;
};

void apply_orca_limits(MachineState& state, const Options& options, const double jd, const bool initialize) {
    auto limit = [&options](const std::string& key, const double fallback = missing()) {
        const auto found = options.orca_limits.find(key);
        return found == options.orca_limits.end() ? fallback : found->second;
    };
    const std::array<double*, 4> acceleration_caps = {&state.maximum_acceleration_x, &state.maximum_acceleration_y, &state.maximum_acceleration_z, &state.maximum_acceleration_e};
    const std::array<double*, 4> speed_caps = {&state.maximum_feedrate_x, &state.maximum_feedrate_y, &state.maximum_feedrate_z, &state.maximum_feedrate_e};
    const std::array<double*, 4> jerks = {&state.jerk_x, &state.jerk_y, &state.jerk_z, &state.jerk_e};
    const std::array<std::string, 4> axes = {"x", "y", "z", "e"};
    if (initialize) {
        state.print_acceleration = limit("machine_max_acceleration_extruding", 1500.0);
        state.travel_acceleration = limit("machine_max_acceleration_travel", 1250.0);
        state.retract_acceleration = limit("machine_max_acceleration_retracting", 1500.0);
        if (state.print_acceleration <= 0) state.print_acceleration = 1500.0;
        if (state.travel_acceleration <= 0) state.travel_acceleration = 1250.0;
        if (state.retract_acceleration <= 0) state.retract_acceleration = 1500.0;
        state.minimum_extruding_feedrate = limit("machine_min_extruding_rate");
        state.minimum_travel_feedrate = limit("machine_min_travel_rate");
        for (std::size_t axis = 0; axis < 4; ++axis) {
            *acceleration_caps[axis] = limit("machine_max_acceleration_" + axes[axis]);
            *speed_caps[axis] = limit(std::string(options.prusa_compatible ? "machine_max_feedrate_" : "machine_max_speed_") + axes[axis]);
            *jerks[axis] = limit("machine_max_jerk_" + axes[axis]);
        }
    }
    if (options.prusa_compatible) return;
    const std::array<double*, 3> categories = {&state.print_acceleration, &state.travel_acceleration, &state.retract_acceleration};
    const std::array<std::string, 3> category_keys = {"extruding", "travel", "retracting"};
    for (std::size_t category = 0; category < 3; ++category) {
        const double cap = limit("machine_max_acceleration_" + category_keys[category]);
        if (present(cap) && cap > 0) *categories[category] = std::min(*categories[category], cap);
    }
    if (options.orca_marlin2 && jd > 0) {
        for (std::size_t axis = 0; axis < 4; ++axis) {
            const double cap = *acceleration_caps[axis];
            const double acceleration = present(cap) && cap > 0 ? std::min(state.print_acceleration, cap) : state.print_acceleration;
            *jerks[axis] = std::sqrt(2.5 * jd * acceleration);
        }
    }
}

struct ArcGeometry {
    double path_length = missing();
    double radius = missing();
    double sweep_degrees = missing();
    double center_x = missing();
    double center_y = missing();
    double planar_length = missing();
    double start_radius = missing();
};

double positive_mod(const double value, const double modulus) {
    double result = std::fmod(value, modulus);
    if (result < 0.0) {
        result += modulus;
    }
    return result;
}

double directed_sweep(
    const double start_angle,
    const double end_angle,
    const bool clockwise,
    const bool full_circle
) {
    if (full_circle) {
        return 2.0 * PI;
    }
    const double sweep = clockwise
        ? positive_mod(start_angle - end_angle, 2.0 * PI)
        : positive_mod(end_angle - start_angle, 2.0 * PI);
    return sweep < ARC_EPSILON ? 0.0 : sweep;
}

ArcGeometry ij_arc(
    const Movement& movement,
    const ParsedLine& line,
    const bool clockwise,
    const bool center_relative,
    const double unit_scale
) {
    const double center_x = center_relative
        ? movement.start_x + parameter(line, "I", 0.0) * unit_scale
        : (
            has_parameter(line, "I")
            ? parameter(line, "I") * unit_scale
            : movement.start_x
        );
    const double center_y = center_relative
        ? movement.start_y + parameter(line, "J", 0.0) * unit_scale
        : (
            has_parameter(line, "J")
            ? parameter(line, "J") * unit_scale
            : movement.start_y
        );
    const double start_radius = std::hypot(
        movement.start_x - center_x, movement.start_y - center_y
    );
    const double end_radius = std::hypot(
        movement.end_x - center_x, movement.end_y - center_y
    );
    if (start_radius <= ARC_EPSILON) {
        return {};
    }
    const double radius = (start_radius + end_radius) / 2.0;
    const double start_angle = std::atan2(
        movement.start_y - center_y, movement.start_x - center_x
    );
    const double end_angle = std::atan2(
        movement.end_y - center_y, movement.end_x - center_x
    );
    const bool full_circle = std::hypot(
        movement.end_x - movement.start_x,
        movement.end_y - movement.start_y
    ) <= ARC_EPSILON;
    const double sweep = directed_sweep(start_angle, end_angle, clockwise, full_circle);
    const double planar = radius * sweep;
    ArcGeometry result;
    result.path_length = std::hypot(planar, movement.end_z - movement.start_z);
    result.radius = radius;
    result.sweep_degrees = sweep * 180.0 / PI;
    result.center_x = center_x;
    result.center_y = center_y;
    result.planar_length = planar;
    result.start_radius = start_radius;
    return result;
}

ArcGeometry radius_arc(
    const Movement& movement,
    const double radius_parameter,
    const bool clockwise
) {
    const double radius = std::abs(radius_parameter);
    const double delta_x = movement.end_x - movement.start_x;
    const double delta_y = movement.end_y - movement.start_y;
    const double chord = std::hypot(delta_x, delta_y);
    ArcGeometry invalid;
    invalid.radius = radius;
    if (radius <= ARC_EPSILON || chord <= ARC_EPSILON
        || chord > 2.0 * radius + ARC_EPSILON) {
        return invalid;
    }
    const double midpoint_x = (movement.start_x + movement.end_x) / 2.0;
    const double midpoint_y = (movement.start_y + movement.end_y) / 2.0;
    const double center_distance = std::sqrt(std::max(
        0.0, radius * radius - (chord / 2.0) * (chord / 2.0)
    ));
    const double perpendicular_x = -delta_y / chord;
    const double perpendicular_y = delta_x / chord;
    std::array<ArcGeometry, 2> candidates;
    for (std::size_t index = 0; index < 2; ++index) {
        const double sign = index == 0 ? 1.0 : -1.0;
        const double center_x = midpoint_x + sign * perpendicular_x * center_distance;
        const double center_y = midpoint_y + sign * perpendicular_y * center_distance;
        const double start_angle = std::atan2(
            movement.start_y - center_y, movement.start_x - center_x
        );
        const double end_angle = std::atan2(
            movement.end_y - center_y, movement.end_x - center_x
        );
        const double sweep = directed_sweep(start_angle, end_angle, clockwise, false);
        const double planar = radius * sweep;
        candidates[index].path_length = std::hypot(
            planar, movement.end_z - movement.start_z
        );
        candidates[index].radius = radius;
        candidates[index].sweep_degrees = sweep * 180.0 / PI;
        candidates[index].center_x = center_x;
        candidates[index].center_y = center_y;
        candidates[index].planar_length = planar;
        candidates[index].start_radius = radius;
    }
    const bool first = radius_parameter >= 0.0
        ? candidates[0].sweep_degrees <= candidates[1].sweep_degrees
        : candidates[0].sweep_degrees >= candidates[1].sweep_degrees;
    return candidates[first ? 0 : 1];
}

Category classify(const bool spatial, const double delta_e, const bool feedrate_changed) {
    if (spatial && delta_e > MOVEMENT_EPSILON) return Category::deposition;
    if (spatial && delta_e < -MOVEMENT_EPSILON) return Category::travel_with_retraction;
    if (spatial) return Category::travel;
    if (delta_e < -MOVEMENT_EPSILON) return Category::retraction;
    if (delta_e > MOVEMENT_EPSILON) return Category::unretraction;
    if (feedrate_changed) return Category::feedrate_only;
    return Category::no_op;
}

double selected_acceleration(const MachineState& state, const Category category) {
    if (category == Category::retraction || category == Category::unretraction) {
        return state.retract_acceleration;
    }
    if (category == Category::travel || category == Category::travel_with_retraction) {
        return state.travel_acceleration;
    }
    return state.print_acceleration;
}

double limited_acceleration(
    const MachineState& state,
    const double commanded,
    const bool spatial,
    const bool arc,
    const double distance,
    const double dx,
    const double dy,
    const double dz,
    const double de
) {
    if (!present(commanded) || commanded <= MOVEMENT_EPSILON) {
        return commanded;
    }
    double result = commanded;
    const auto apply = [&result, distance](const double delta, const double maximum) {
        if (present(maximum) && std::abs(delta) > MOVEMENT_EPSILON) {
            result = std::min(result, maximum * distance / std::abs(delta));
        }
    };
    if (spatial && arc) {
        if (state.arc_plane == "XY") {
            if (present(state.maximum_acceleration_x)) result = std::min(result, state.maximum_acceleration_x);
            if (present(state.maximum_acceleration_y)) result = std::min(result, state.maximum_acceleration_y);
            apply(dz, state.maximum_acceleration_z);
        } else if (state.arc_plane == "XZ") {
            if (present(state.maximum_acceleration_x)) result = std::min(result, state.maximum_acceleration_x);
            if (present(state.maximum_acceleration_z)) result = std::min(result, state.maximum_acceleration_z);
            apply(dy, state.maximum_acceleration_y);
        } else {
            if (present(state.maximum_acceleration_y)) result = std::min(result, state.maximum_acceleration_y);
            if (present(state.maximum_acceleration_z)) result = std::min(result, state.maximum_acceleration_z);
            apply(dx, state.maximum_acceleration_x);
        }
    } else if (spatial) {
        apply(dx, state.maximum_acceleration_x);
        apply(dy, state.maximum_acceleration_y);
        apply(dz, state.maximum_acceleration_z);
    }
    apply(de, state.maximum_acceleration_e);
    return result;
}

struct BasicTiming {
    double distance = missing();
    double effective_feedrate = missing();
    double duration = missing();
};

BasicTiming basic_timing(
    const bool spatial,
    const double path_length,
    const double delta_e,
    const double feedrate,
    const double speed_factor,
    const double acceleration
) {
    BasicTiming result;
    if (spatial) {
        if (!present(path_length)) return result;
        result.distance = path_length;
    } else if (std::abs(delta_e) > MOVEMENT_EPSILON) {
        result.distance = std::abs(delta_e);
    } else {
        result.distance = 0.0;
    }
    if (present(feedrate)) {
        result.effective_feedrate = feedrate * speed_factor / 100.0;
    }
    if (result.distance <= MOVEMENT_EPSILON) {
        result.duration = 0.0;
    } else if (!present(result.effective_feedrate)
        || result.effective_feedrate <= MOVEMENT_EPSILON) {
        result.duration = missing();
    } else if (!present(acceleration)) {
        result.duration = result.distance / (result.effective_feedrate / 60.0);
    } else if (acceleration > MOVEMENT_EPSILON) {
        const double target = result.effective_feedrate / 60.0;
        const double cruise = std::min(target, std::sqrt(std::max(0.0, acceleration * result.distance)));
        const double accel_distance = cruise * cruise / (2.0 * acceleration);
        result.duration = 2.0 * cruise / acceleration
            + std::max(0.0, result.distance - 2.0 * accel_distance) / cruise;
    }
    return result;
}

Movement create_movement(
    MachineState& state,
    const ParsedLine& line
) {
    state.movement_seen = true;
    Movement movement;
    movement.line_number = line.number;
    movement.command = line.command;
    movement.start_x = state.x;
    movement.start_y = state.y;
    movement.start_z = state.z;
    movement.start_e = state.e;
    const bool feedrate_changed = has_parameter(line, "F");
    if (feedrate_changed) {
        state.feedrate = parameter(line, "F") * state.unit_scale_mm;
    }
    const auto resolve = [
        &line,
        unit_scale = state.unit_scale_mm
    ](const std::string& name, const double current, const bool relative) {
        const double value = parameter(line, name);
        if (!present(value)) return current;
        const double scaled = value * unit_scale;
        return relative ? current + scaled : scaled;
    };
    movement.end_x = resolve("X", state.x, state.xyz_relative);
    movement.end_y = resolve("Y", state.y, state.xyz_relative);
    movement.end_z = resolve("Z", state.z, state.xyz_relative);
    movement.end_e = resolve("E", state.e, state.extrusion_relative);
    movement.delta_x = movement.end_x - movement.start_x;
    movement.delta_y = movement.end_y - movement.start_y;
    movement.delta_z = movement.end_z - movement.start_z;
    movement.delta_e = movement.end_e - movement.start_e;
    const double endpoint_xy = std::hypot(movement.delta_x, movement.delta_y);
    const double endpoint_xyz = std::sqrt(
        movement.delta_x * movement.delta_x
        + movement.delta_y * movement.delta_y
        + movement.delta_z * movement.delta_z
    );
    const bool arc = movement.command == "G2" || movement.command == "G3";
    double radius = missing();
    double sweep = missing();
    double planar = missing();
    double start_radius = missing();
    std::array<double, 3> entry = {missing(), missing(), missing()};
    std::array<double, 3> exit = {missing(), missing(), missing()};
    if (!arc) {
        movement.path_length = endpoint_xyz;
    } else {
        Movement planar_movement = movement;
        ParsedLine planar_line = line;
        planar_line.parameters.clear();
        std::string center_u;
        std::string center_v;
        if (state.arc_plane == "XY") {
            center_u = "I";
            center_v = "J";
        } else if (state.arc_plane == "XZ") {
            planar_movement.start_x = movement.start_z;
            planar_movement.start_y = movement.start_x;
            planar_movement.start_z = movement.start_y;
            planar_movement.end_x = movement.end_z;
            planar_movement.end_y = movement.end_x;
            planar_movement.end_z = movement.end_y;
            center_u = "K";
            center_v = "I";
        } else {
            planar_movement.start_x = movement.start_y;
            planar_movement.start_y = movement.start_z;
            planar_movement.start_z = movement.start_x;
            planar_movement.end_x = movement.end_y;
            planar_movement.end_y = movement.end_z;
            planar_movement.end_z = movement.end_x;
            center_u = "J";
            center_v = "K";
        }
        if (has_parameter(line, center_u)) {
            planar_line.parameters["I"] = parameter(line, center_u);
        }
        if (has_parameter(line, center_v)) {
            planar_line.parameters["J"] = parameter(line, center_v);
        }
        if (has_parameter(line, "R")) {
            planar_line.parameters["R"] = parameter(line, "R");
        }
        const ArcGeometry geometry = (
            has_parameter(planar_line, "I")
            || has_parameter(planar_line, "J")
        )
            ? ij_arc(
                planar_movement,
                planar_line,
                movement.command == "G2",
                state.arc_center_relative,
                state.unit_scale_mm
            )
            : has_parameter(planar_line, "R")
                ? radius_arc(
                    planar_movement,
                    parameter(planar_line, "R") * state.unit_scale_mm,
                    movement.command == "G2"
                )
                : ArcGeometry{};
        movement.path_length = geometry.path_length;
        radius = geometry.radius;
        sweep = geometry.sweep_degrees;
        planar = geometry.planar_length;
        start_radius = geometry.start_radius;
        if (present(geometry.center_x) && present(geometry.center_y)
            && present(geometry.radius) && geometry.radius > ARC_EPSILON) {
            const double sr = std::hypot(
                planar_movement.start_x - geometry.center_x,
                planar_movement.start_y - geometry.center_y
            );
            const double er = std::hypot(
                planar_movement.end_x - geometry.center_x,
                planar_movement.end_y - geometry.center_y
            );
            if (sr > ARC_EPSILON && er > ARC_EPSILON) {
                const double su = (planar_movement.start_x - geometry.center_x) / sr;
                const double sv = (planar_movement.start_y - geometry.center_y) / sr;
                const double eu = (planar_movement.end_x - geometry.center_x) / er;
                const double ev = (planar_movement.end_y - geometry.center_y) / er;
                const auto to_xyz = [&state](const double u, const double v) {
                    if (state.arc_plane == "XY") return std::array<double,3>{u,v,0.0};
                    if (state.arc_plane == "XZ") return std::array<double,3>{v,0.0,u};
                    return std::array<double,3>{0.0,u,v};
                };
                if (movement.command == "G2") {
                    entry = to_xyz(sv, -su);
                    exit = to_xyz(ev, -eu);
                } else {
                    entry = to_xyz(-sv, su);
                    exit = to_xyz(-ev, eu);
                }
            }
        }
    }
    const bool spatial = endpoint_xyz > MOVEMENT_EPSILON
        || (arc && present(movement.path_length) && movement.path_length > MOVEMENT_EPSILON);
    movement.category = classify(spatial, movement.delta_e, feedrate_changed);
    const double preliminary_distance = spatial
        ? (present(movement.path_length) ? movement.path_length : 0.0)
        : std::abs(movement.delta_e);
    const double acceleration = limited_acceleration(
        state,
        selected_acceleration(state, movement.category),
        spatial,
        arc,
        preliminary_distance,
        movement.delta_x,
        movement.delta_y,
        movement.delta_z,
        movement.delta_e
    );
    const BasicTiming timing = basic_timing(
        spatial,
        movement.path_length,
        movement.delta_e,
        state.feedrate,
        state.speed_factor_percent,
        acceleration
    );
    movement.duration = timing.duration;
    Row row;
    row.fill(missing());
    row[ENDPOINT_XY] = endpoint_xy;
    row[ENDPOINT_XYZ] = endpoint_xyz;
    row[DELTA_X] = movement.delta_x;
    row[DELTA_Y] = movement.delta_y;
    row[DELTA_Z] = movement.delta_z;
    row[DELTA_E] = movement.delta_e;
    row[PATH_LENGTH] = movement.path_length;
    row[EFFECTIVE_FEEDRATE] = timing.effective_feedrate;
    row[TIMING_DISTANCE] = timing.distance;
    row[ACCELERATION] = acceleration;
    row[JERK_X] = state.jerk_x;
    row[JERK_Y] = state.jerk_y;
    row[JERK_Z] = state.jerk_z;
    row[JERK_E] = state.jerk_e;
    row[JUNCTION_DEVIATION] = state.junction_deviation;
    row[MAXIMUM_ACCELERATION_X] = state.maximum_acceleration_x;
    row[MAXIMUM_ACCELERATION_Y] = state.maximum_acceleration_y;
    row[MAXIMUM_ACCELERATION_Z] = state.maximum_acceleration_z;
    row[MAXIMUM_ACCELERATION_E] = state.maximum_acceleration_e;
    row[SQUARE_CORNER_VELOCITY] = state.square_corner_velocity;
    row[ENTRY_DIRECTION_X] = entry[0];
    row[ENTRY_DIRECTION_Y] = entry[1];
    row[ENTRY_DIRECTION_Z] = entry[2];
    row[EXIT_DIRECTION_X] = exit[0];
    row[EXIT_DIRECTION_Y] = exit[1];
    row[EXIT_DIRECTION_Z] = exit[2];
    row[ARC_PLANAR_LENGTH] = planar;
    row[ARC_START_RADIUS] = start_radius;
    row[ARC_SWEEP_DEGREES] = sweep;
    row[MAXIMUM_FEEDRATE_X] = state.maximum_feedrate_x;
    row[MAXIMUM_FEEDRATE_Y] = state.maximum_feedrate_y;
    row[MAXIMUM_FEEDRATE_Z] = state.maximum_feedrate_z;
    row[MAXIMUM_FEEDRATE_E] = state.maximum_feedrate_e;
    row[MINIMUM_EXTRUDING_FEEDRATE] = state.minimum_extruding_feedrate;
    row[MINIMUM_TRAVEL_FEEDRATE] = state.minimum_travel_feedrate;
    row[EXTRUSION_FACTOR] = state.extrusion_factor;
    row[CENTRIPETAL_ACCELERATION] = state.print_acceleration;
    row[IS_ARC] = arc ? 1.0 : 0.0;
    movement.row = row;
    state.x = movement.end_x;
    state.y = movement.end_y;
    state.z = movement.end_z;
    state.e = movement.end_e;
    return movement;
}

bool safe_ignored_command(const std::string& command) {
    // Only commands known not to alter the modeled coordinate, extrusion,
    // feedrate, acceleration, junction, or layer state belong here. Commands
    // such as G29, M501, or SET_GCODE_OFFSET deliberately trigger fallback.
    static const std::set<std::string> commands = {
        "M17", "M18", "M73", "M75", "M76", "M77",
        "M84", "M104", "M105", "M106", "M107", "M109", "M117",
        "M140", "M190", "M300", "M400", "M486",
        "M620", "M621", "M900", "M960", "M971", "M972", "M975",
        "M976", "M977", "M991", "M1002", "M1403",
        "SET_PRESSURE_ADVANCE", "SET_PRINT_STATS_INFO",
        "SET_HEATER_TEMPERATURE", "TEMPERATURE_WAIT",
        "EXCLUDE_OBJECT_DEFINE", "EXCLUDE_OBJECT_START", "EXCLUDE_OBJECT_END",
    };
    return commands.find(command) != commands.end();
}

bool bambu_ignored_command(const std::string& command) {
    // These commands are emitted by Bambu Studio for printer preparation,
    // calibration, camera control, material handling, timelapse and shutdown.
    // The Python reference analyzer deliberately excludes their opaque
    // firmware-side work from printable-layer timing. Keep them scoped to a
    // positively identified Bambu file instead of weakening generic fallback.
    static const std::set<std::string> commands = {
        "G29", "G29.1", "G29.2", "G29.99", "G130", "G150",
        "G150.1", "G150.2", "G150.3", "G151", "G380", "G3811",
        "G383", "G383.3", "G383.4",
        "M1003", "M1004", "M1006", "M1012.1", "M1012.5",
        "M1015.3", "M1015.4", "M1028", "M141", "M142", "M145",
        "M191", "M201.2", "M211", "M500", "M562", "M620.6",
        "M620.10", "M620.11", "M620.17", "M620.22", "M622",
        "M622.1", "M623", "M624", "M625", "M628", "M629", "M630",
        "M73.2",
        "M970.2", "M970.3", "M974", "M981", "M982.2", "M983.1",
        "M983.3", "M983.4", "M993",
    };
    return commands.find(command) != commands.end();
}

std::optional<Event> process_machine_line(
    MachineState& state,
    const ParsedLine& line,
    const bool bambu,
    const bool anycubic_slicer_next,
    bool& unsupported,
    const bool bambu_firmware,
    const bool prusa
) {
    unsupported = false;
    if (!line.has_command) {
        if (!line.unparsed.empty()) unsupported = true;
        return std::nullopt;
    }
    const std::string& command = line.command;
    if (prusa) {
        // Prusa's viewer excludes these firmware preparation/check and
        // shutdown commands from the motion estimate. Keep this allowlist
        // independent from Bambu's device macros.
        static const std::set<std::string> commands = {
            "G29", "M74", "M115", "M142", "M302", "M555", "M569", "M572", "M593",
            "M862.1", "M862.2", "M862.3", "M862.4", "M862.5", "M862.6", "M862.7",
        };
        if (commands.find(command) != commands.end()) return std::nullopt;
    }
    if (!line.unparsed.empty()
        && !safe_ignored_command(command)
        && !(bambu_firmware && bambu_ignored_command(command))
        && !(bambu && command == "G28")
        && !(anycubic_slicer_next && command == "G9111")
        && command != "EXCLUDE_OBJECT_START"
        && command != "EXCLUDE_OBJECT_DEFINE"
        && command != "EXCLUDE_OBJECT_END") {
        unsupported = true;
        return std::nullopt;
    }
    if (command == "G0" || command == "G1" || command == "G2" || command == "G3") {
        return Event(create_movement(state, line));
    }
    if (command == "G4") {
        double duration = 0.0;
        const double milliseconds = parameter(line, "P");
        const double seconds = parameter(line, "S");
        if ((present(milliseconds) && milliseconds < 0.0)
            || (present(seconds) && seconds < 0.0)) {
            duration = missing();
        } else {
            if (present(milliseconds)) duration += milliseconds / 1000.0;
            if (present(seconds)) duration += seconds;
        }
        return Event(Dwell{line.number, duration});
    }
    if (command == "G20") {
        state.unit_scale_mm = 25.4;
    } else if (command == "G21") {
        state.unit_scale_mm = 1.0;
    } else if (command == "M201") {
        if (has_parameter(line, "X")) state.maximum_acceleration_x = parameter(line, "X") * state.unit_scale_mm;
        if (has_parameter(line, "Y")) state.maximum_acceleration_y = parameter(line, "Y") * state.unit_scale_mm;
        if (has_parameter(line, "Z")) state.maximum_acceleration_z = parameter(line, "Z") * state.unit_scale_mm;
        if (has_parameter(line, "E")) state.maximum_acceleration_e = parameter(line, "E") * state.unit_scale_mm;
    } else if (command == "M203") {
        if (bambu) {
            if (has_parameter(line, "X")) state.maximum_feedrate_x = parameter(line, "X") * state.unit_scale_mm;
            if (has_parameter(line, "Y")) state.maximum_feedrate_y = parameter(line, "Y") * state.unit_scale_mm;
            if (has_parameter(line, "Z")) state.maximum_feedrate_z = parameter(line, "Z") * state.unit_scale_mm;
            if (has_parameter(line, "E")) state.maximum_feedrate_e = parameter(line, "E") * state.unit_scale_mm;
        }
    } else if (command == "M204") {
        if (has_parameter(line, "S")) {
            const double shared = parameter(line, "S") * state.unit_scale_mm;
            state.print_acceleration = shared;
            state.travel_acceleration = shared;
            if (bambu && has_parameter(line, "T")) {
                state.retract_acceleration = parameter(line, "T") * state.unit_scale_mm;
            } else if (!bambu) {
                state.retract_acceleration = shared;
            }
        } else {
            if (has_parameter(line, "P")) state.print_acceleration = parameter(line, "P") * state.unit_scale_mm;
            if (has_parameter(line, "T")) state.travel_acceleration = parameter(line, "T") * state.unit_scale_mm;
            if (has_parameter(line, "R")) state.retract_acceleration = parameter(line, "R") * state.unit_scale_mm;
        }
    } else if (command == "M205") {
        if (has_parameter(line, "X")) {
            state.jerk_x = parameter(line, "X") * state.unit_scale_mm;
            if (bambu) state.jerk_y = state.jerk_x;
        }
        if (has_parameter(line, "Y")) state.jerk_y = parameter(line, "Y") * state.unit_scale_mm;
        if (has_parameter(line, "Z")) state.jerk_z = parameter(line, "Z") * state.unit_scale_mm;
        if (has_parameter(line, "E")) state.jerk_e = parameter(line, "E") * state.unit_scale_mm;
        if (bambu && has_parameter(line, "S")) state.minimum_extruding_feedrate = parameter(line, "S") * state.unit_scale_mm;
        if (bambu && has_parameter(line, "T")) state.minimum_travel_feedrate = parameter(line, "T") * state.unit_scale_mm;
    } else if (command == "SET_VELOCITY_LIMIT") {
        if (has_parameter(line, "ACCEL")) {
            const double acceleration = parameter(line, "ACCEL") * state.unit_scale_mm;
            state.print_acceleration = acceleration;
            state.travel_acceleration = acceleration;
            state.retract_acceleration = acceleration;
        }
        if (has_parameter(line, "SQUARE_CORNER_VELOCITY")) {
            state.square_corner_velocity = parameter(line, "SQUARE_CORNER_VELOCITY") * state.unit_scale_mm;
        }
    } else if (command == "M220") {
        if (has_parameter(line, "S")) state.speed_factor_percent = parameter(line, "S");
    } else if (command == "M221") {
        if (bambu && has_parameter(line, "S") && !has_parameter(line, "T")) {
            state.extrusion_factor = parameter(line, "S") / 100.0;
        }
    } else if (command == "G90") {
        state.xyz_relative = false;
    } else if (command == "G91") {
        state.xyz_relative = true;
    } else if (command == "M82") {
        state.extrusion_relative = false;
    } else if (command == "M83") {
        state.extrusion_relative = true;
    } else if (command == "G90.1") {
        state.arc_center_relative = false;
    } else if (command == "G91.1") {
        state.arc_center_relative = true;
    } else if (command == "G17") {
        state.arc_plane = "XY";
    } else if (command == "G18") {
        state.arc_plane = "XZ";
    } else if (command == "G19") {
        state.arc_plane = "YZ";
    } else if (command == "G92") {
        if (has_parameter(line, "X")) state.x = parameter(line, "X") * state.unit_scale_mm;
        if (has_parameter(line, "Y")) state.y = parameter(line, "Y") * state.unit_scale_mm;
        if (has_parameter(line, "Z")) state.z = parameter(line, "Z") * state.unit_scale_mm;
        if (has_parameter(line, "E")) state.e = parameter(line, "E") * state.unit_scale_mm;
    } else if (command == "G28") {
        const bool all = !has_parameter(line, "X")
            && !has_parameter(line, "Y")
            && !has_parameter(line, "Z");
        if (all || has_parameter(line, "X")) state.x = 0.0;
        if (all || has_parameter(line, "Y")) state.y = 0.0;
        if (all || has_parameter(line, "Z")) state.z = 0.0;
    } else if (command == "G9111") {
        static const std::set<std::string> allowed_parameters = {
            "BEDTEMP", "EXTRUDERTEMP",
        };
        bool parameters_supported = line.unparsed.empty();
        for (const auto& item : line.parameters) {
            parameters_supported = parameters_supported
                && allowed_parameters.find(item.first)
                    != allowed_parameters.end();
        }
        if (
            !anycubic_slicer_next
            || state.movement_seen
            || !parameters_supported
        ) {
            unsupported = true;
        } else {
            // AnycubicSlicerNext emits this firmware-defined startup macro
            // before it reasserts G90/G21/M83 and before the first movement.
            // Its heating, homing and purge work is outside slicer layer
            // timing, just as in the Python reference analyzer. Restricting
            // this recognition to the untouched preamble prevents an opaque
            // macro from invalidating an established motion state.
            ++state.anycubic_startup_macro_count;
        }
    } else if (command.size() > 1 && command[0] == 'T') {
        bool digits = true;
        for (std::size_t index = 1; index < command.size(); ++index) {
            digits = digits && ascii_digit(command[index]);
        }
        if (digits) state.active_tool = std::stoi(command.substr(1));
        else unsupported = true;
    } else if (
        !safe_ignored_command(command)
        && !(bambu_firmware && bambu_ignored_command(command))
    ) {
        unsupported = true;
    }
    return std::nullopt;
}

struct Direction4 { double x = 0.0, y = 0.0, z = 0.0, e = 0.0; bool valid = false; };
struct Direction2 { double x = 0.0, y = 0.0; bool valid = false; };
struct Kinematics { double target = 0.0, distance = 0.0, acceleration = 0.0, safe = 0.0; Direction4 direction; };
struct Planned { double feedrate = 0.0, distance = 0.0, duration = 0.0, entry = 0.0, cruise = 0.0, exit = 0.0; };

bool row_is_arc(const Row& row) { return row[IS_ARC] != 0.0; }
double optional_zero(const double value) { return present(value) ? value : 0.0; }

double planar_length(const Row& row) {
    if (row_is_arc(row) && present(row[ARC_START_RADIUS])
        && row[ARC_START_RADIUS] > ARC_EPSILON
        && present(row[ARC_SWEEP_DEGREES])) {
        return row[ARC_START_RADIUS] * row[ARC_SWEEP_DEGREES] * PI / 180.0;
    }
    return row[ARC_PLANAR_LENGTH];
}

double bambu_distance(const Row& row) {
    const double planar = planar_length(row);
    if (row_is_arc(row) && present(planar)) return std::hypot(planar, row[DELTA_Z]);
    return optional_zero(row[TIMING_DISTANCE]);
}

Direction4 movement_direction(const Row& row) {
    Direction4 result;
    if (row[ENDPOINT_XYZ] > MOVEMENT_EPSILON) {
        result.x = row[DELTA_X] / row[ENDPOINT_XYZ];
        result.y = row[DELTA_Y] / row[ENDPOINT_XYZ];
        result.z = row[DELTA_Z] / row[ENDPOINT_XYZ];
        result.valid = true;
    } else if (std::abs(row[DELTA_E]) > MOVEMENT_EPSILON) {
        result.e = std::copysign(1.0, row[DELTA_E]);
        result.valid = true;
    }
    return result;
}

Direction2 xy_direction(const Row& row, const bool at_exit) {
    double x = row[at_exit ? EXIT_DIRECTION_X : ENTRY_DIRECTION_X];
    double y = row[at_exit ? EXIT_DIRECTION_Y : ENTRY_DIRECTION_Y];
    if (!present(x) || !present(y)) { x = row[DELTA_X]; y = row[DELTA_Y]; }
    Direction2 result;
    const double length = std::hypot(x, y);
    if (length > MOVEMENT_EPSILON) { result.x = x / length; result.y = y / length; result.valid = true; }
    return result;
}

std::array<double, 4> axis_feedrates(const Row& row, const double speed) {
    const double distance = bambu_distance(row);
    if (distance <= MOVEMENT_EPSILON) return {0.0, 0.0, 0.0, 0.0};
    const double planar = planar_length(row);
    if (row_is_arc(row) && present(planar)) {
        const double planar_speed = speed * planar / distance;
        return {planar_speed, planar_speed, speed * row[DELTA_Z] / distance,
            speed * row[DELTA_E] / distance * row[EXTRUSION_FACTOR]};
    }
    return {speed * row[DELTA_X] / distance, speed * row[DELTA_Y] / distance,
        speed * row[DELTA_Z] / distance,
        speed * row[DELTA_E] / distance * row[EXTRUSION_FACTOR]};
}

double bambu_cruise(const Row& row, const Row* previous) {
    double speed = optional_zero(row[EFFECTIVE_FEEDRATE]) / 60.0;
    const double minimum = std::abs(row[DELTA_E]) <= MOVEMENT_EPSILON
        ? row[MINIMUM_TRAVEL_FEEDRATE] : row[MINIMUM_EXTRUDING_FEEDRATE];
    if (present(minimum)) speed = std::max(speed, minimum);
    const double centripetal = row[CENTRIPETAL_ACCELERATION];
    if (row_is_arc(row) && present(row[ARC_START_RADIUS])
        && row[ARC_START_RADIUS] > ARC_EPSILON
        && present(centripetal) && centripetal > MOVEMENT_EPSILON) {
        const double planar = planar_length(row);
        const double distance = bambu_distance(row);
        if (present(planar) && planar > ARC_EPSILON && distance > MOVEMENT_EPSILON) {
            speed = std::min(speed, std::sqrt(centripetal * row[ARC_START_RADIUS]) / (planar / distance));
        }
    } else if (previous != nullptr && !row_is_arc(row)
        && present(centripetal) && centripetal > MOVEMENT_EPSILON
        && row[ENDPOINT_XY] > MOVEMENT_EPSILON) {
        const Direction2 before = xy_direction(*previous, true);
        const Direction2 current = xy_direction(row, false);
        if (before.valid && current.valid) {
            const double difference = std::hypot(current.x - before.x, current.y - before.y);
            if (difference > 0.00001 && difference < 0.5) {
                speed = std::min(speed, std::sqrt(centripetal * row[ENDPOINT_XY] * 0.5 / (difference * 0.5)));
            }
        }
    }
    const auto projected = axis_feedrates(row, speed);
    const std::array<std::size_t, 4> maximums = {MAXIMUM_FEEDRATE_X, MAXIMUM_FEEDRATE_Y, MAXIMUM_FEEDRATE_Z, MAXIMUM_FEEDRATE_E};
    double factor = 1.0;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        if (std::abs(projected[axis]) > MOVEMENT_EPSILON
            && present(row[maximums[axis]]) && row[maximums[axis]] > MOVEMENT_EPSILON) {
            factor = std::min(factor, row[maximums[axis]] / std::abs(projected[axis]));
        }
    }
    return speed * factor;
}

double bambu_safe(const Row& row, const double cruise) {
    if (cruise <= MOVEMENT_EPSILON || bambu_distance(row) <= MOVEMENT_EPSILON) return 0.0;
    const auto speeds = axis_feedrates(row, cruise);
    const std::array<std::size_t, 4> jerks = {JERK_X, JERK_Y, JERK_Z, JERK_E};
    double safe = cruise;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        if (present(row[jerks[axis]]) && std::abs(speeds[axis]) > row[jerks[axis]]) {
            safe = std::min(safe, std::max(0.0, row[jerks[axis]]));
        }
    }
    return safe;
}

double generic_junction(const Row& previous, const Row& current) {
    const double maximum = std::min(optional_zero(previous[EFFECTIVE_FEEDRATE]), optional_zero(current[EFFECTIVE_FEEDRATE])) / 60.0;
    if (maximum <= MOVEMENT_EPSILON) return 0.0;
    const Direction4 before = movement_direction(previous);
    const Direction4 after = movement_direction(current);
    if (!before.valid || !after.valid || ((std::abs(before.e) > 0.0) != (std::abs(after.e) > 0.0))) return 0.0;
    const std::array<double, 4> changes = {after.x-before.x, after.y-before.y, after.z-before.z, after.e-before.e};
    double length2 = 0.0;
    for (double value : changes) length2 += value * value;
    const double length = std::sqrt(length2);
    if (length <= MOVEMENT_EPSILON) return maximum;
    if (present(current[SQUARE_CORNER_VELOCITY])) {
        if (current[SQUARE_CORNER_VELOCITY] <= 0.0) return 0.0;
        return std::min(maximum, std::sqrt(2.0) * current[SQUARE_CORNER_VELOCITY] / length);
    }
    const std::array<std::size_t, 4> jerks = {JERK_X, JERK_Y, JERK_Z, JERK_E};
    double result = maximum;
    bool found = false;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        if (std::abs(changes[axis]) <= MOVEMENT_EPSILON || !present(current[jerks[axis]])) continue;
        found = true;
        result = std::min(result, std::max(0.0, current[jerks[axis]]) / std::abs(changes[axis]));
    }
    return found ? result : 0.0;
}

double bambu_junction(const Row& previous, const Row& current, const Kinematics& before, const Kinematics& after) {
    if (before.target <= MOVEMENT_EPSILON) return after.safe;
    const double maximum = std::min(before.target, after.target);
    if (!before.direction.valid || !after.direction.valid) return after.safe;
    if (std::abs(before.direction.e) > 0.0 || std::abs(after.direction.e) > 0.0) return maximum;
    std::array<double, 3> previous_direction = {before.direction.x, before.direction.y, before.direction.z};
    std::array<double, 3> current_direction = {after.direction.x, after.direction.y, after.direction.z};
    if (present(previous[EXIT_DIRECTION_X])) previous_direction = {previous[EXIT_DIRECTION_X], previous[EXIT_DIRECTION_Y], previous[EXIT_DIRECTION_Z]};
    if (present(current[ENTRY_DIRECTION_X])) current_direction = {current[ENTRY_DIRECTION_X], current[ENTRY_DIRECTION_Y], current[ENTRY_DIRECTION_Z]};
    const std::array<std::size_t, 3> jerks = {JERK_X, JERK_Y, JERK_Z};
    double result = std::numeric_limits<double>::infinity();
    bool found = false;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double change = current_direction[axis] - previous_direction[axis];
        if (std::abs(change) <= MOVEMENT_EPSILON || !present(current[jerks[axis]])) continue;
        found = true;
        result = std::min(result, std::max(0.0, current[jerks[axis]]) / std::abs(change));
    }
    if (!found) return maximum;
    if (before.safe > result * 0.99 && after.safe > result * 0.99) result = after.safe;
    return result;
}

Planned planned_timing(const Row& row, const double distance, const double target, double entry, double exit, const bool bambu) {
    const double feedrate = target * 60.0;
    if (distance <= MOVEMENT_EPSILON) return {feedrate, distance, 0.0, 0.0, 0.0, 0.0};
    const double acceleration = optional_zero(row[ACCELERATION]);
    if (feedrate <= MOVEMENT_EPSILON || acceleration <= MOVEMENT_EPSILON) return {feedrate, distance, missing(), 0.0, 0.0, 0.0};
    if (bambu) { entry = std::max(0.0, entry); exit = std::max(0.0, exit); }
    else { entry = std::min(std::max(0.0, entry), target); exit = std::min(std::max(0.0, exit), target); }
    const double peak2 = acceleration * distance + (entry * entry + exit * exit) / 2.0;
    const double cruise = std::min(target, std::sqrt(std::max(0.0, peak2)));
    const double accel_distance = std::max(0.0, (cruise * cruise - entry * entry) / (2.0 * acceleration));
    const double decel_distance = std::max(0.0, (cruise * cruise - exit * exit) / (2.0 * acceleration));
    const double constant = std::max(0.0, distance - accel_distance - decel_distance);
    const double duration = std::max(0.0, cruise-entry)/acceleration + std::max(0.0, cruise-exit)/acceleration + constant/cruise;
    return {feedrate, distance, duration, entry, cruise, exit};
}

std::vector<Planned> calculate_plan(const std::vector<Row>& rows, const double start, const bool bambu, const Row* previous, const bool orca = false, const bool prusa = false) {
    const std::size_t count = rows.size();
    std::vector<Kinematics> values(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Row* before = index > 0 ? &rows[index-1] : previous;
        values[index].target = bambu ? bambu_cruise(rows[index], before) : optional_zero(rows[index][EFFECTIVE_FEEDRATE]) / 60.0;
        values[index].distance = bambu ? bambu_distance(rows[index]) : optional_zero(rows[index][TIMING_DISTANCE]);
        values[index].acceleration = optional_zero(rows[index][ACCELERATION]);
        values[index].direction = movement_direction(rows[index]);
        if (bambu) values[index].safe = bambu_safe(rows[index], values[index].target);
        if (prusa && rows[index][JUNCTION_DEVIATION] > 0) values[index].safe = 0;
    }
    std::vector<double> boundaries(count + 1, 0.0);
    if (bambu) {
        std::vector<double> maximum_entries(count, 0.0);
        std::vector<bool> nominal(count, false);
        for (std::size_t index = 0; index < count; ++index) {
            double maximum = index == 0
                ? (start > MOVEMENT_EPSILON ? start : values[index].safe)
                : bambu_junction(rows[index-1], rows[index], values[index-1], values[index]);
            if (orca && index > 0) {
                const auto& before = values[index-1]; const auto& after = values[index];
                maximum = std::min(before.target, after.target) <= MOVEMENT_EPSILON ? after.safe
                    : cooling_tower::orca_timing::junction_speed(
                        axis_feedrates(rows[index-1], std::min(before.target, after.target)),
                        axis_feedrates(rows[index], after.target),
                        {rows[index][JERK_X], rows[index][JERK_Y], rows[index][JERK_Z], rows[index][JERK_E]},
                        std::min(before.target, after.target), before.safe, after.safe);
            }
            if (prusa && index > 0) {
                const auto& row = rows[index];
                // Unit vectors here include E without flow scaling.
                auto before = axis_feedrates(rows[index-1], 1.0);
                auto after = axis_feedrates(row, 1.0);
                const double previous_flow = rows[index-1][EXTRUSION_FACTOR];
                const double current_flow = row[EXTRUSION_FACTOR];
                if (row[JUNCTION_DEVIATION] > 0) {
                    for (std::size_t axis = 0; axis < 4; ++axis) {
                        before[axis] = rows[index-1][DELTA_X + axis] / values[index-1].distance;
                        after[axis] = row[DELTA_X + axis] / values[index].distance;
                    }
                } else {
                    before[3] = rows[index-1][DELTA_E] / values[index-1].distance;
                    after[3] = row[DELTA_E] / values[index].distance;
                }
                auto classic_before = before, classic_after = after;
                if (!(row[JUNCTION_DEVIATION] > 0)) {
                    classic_before[3] *= previous_flow;
                    classic_after[3] *= current_flow;
                }
                maximum = cooling_tower::prusa_timing::junction_speed(
                    classic_before, classic_after,
                    {row[MAXIMUM_ACCELERATION_X], row[MAXIMUM_ACCELERATION_Y], row[MAXIMUM_ACCELERATION_Z], row[MAXIMUM_ACCELERATION_E]},
                    {row[JERK_X], row[JERK_Y], row[JERK_Z], row[JERK_E]},
                    values[index].acceleration, row[JUNCTION_DEVIATION], values[index].distance,
                    values[index-1].target, values[index].target, values[index-1].safe, values[index].safe);
            }
            const double allowable = std::sqrt(std::max(0.0, values[index].safe*values[index].safe + 2.0*values[index].acceleration*values[index].distance));
            maximum_entries[index] = maximum;
            boundaries[index] = std::min(maximum, allowable);
            nominal[index] = values[index].target <= allowable;
        }
        boundaries[count] = values.back().safe;
        auto forward_pass = [&]() { for (std::size_t index = 0; index + 1 < count; ++index) {
            if (!nominal[index] && boundaries[index] < boundaries[index+1]) {
                boundaries[index+1] = std::min(boundaries[index+1], std::sqrt(std::max(0.0, boundaries[index]*boundaries[index] + 2.0*values[index].acceleration*values[index].distance)));
            }
        }};
        auto reverse_pass = [&]() { for (std::size_t reverse = (orca || prusa) ? count-1 : count; reverse-- > 0;) {
            const std::size_t index = reverse;
            if (boundaries[index] == maximum_entries[index]) continue;
            if (!nominal[index] && maximum_entries[index] > boundaries[index+1]) {
                boundaries[index] = std::min(maximum_entries[index], std::sqrt(std::max(0.0, boundaries[index+1]*boundaries[index+1] + 2.0*values[index].acceleration*values[index].distance)));
            } else boundaries[index] = maximum_entries[index];
        }};
        if (orca || prusa) { reverse_pass(); forward_pass(); }
        else { forward_pass(); reverse_pass(); }
    } else {
        boundaries[0] = std::min(std::max(0.0, start), values[0].target);
        boundaries[count] = 0.0;
        for (std::size_t index = 1; index < count; ++index) boundaries[index] = generic_junction(rows[index-1], rows[index]);
        for (std::size_t reverse = count; reverse-- > 0;) {
            const std::size_t index = reverse;
            const double maximum = std::sqrt(std::max(0.0, boundaries[index+1]*boundaries[index+1] + 2.0*values[index].acceleration*values[index].distance));
            boundaries[index] = std::min({boundaries[index], values[index].target, maximum});
        }
        for (std::size_t index = 0; index < count; ++index) {
            const double maximum = std::sqrt(std::max(0.0, boundaries[index]*boundaries[index] + 2.0*values[index].acceleration*values[index].distance));
            boundaries[index+1] = std::min({boundaries[index+1], values[index].target, maximum});
        }
    }
    std::vector<Planned> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) result.push_back(planned_timing(rows[index], values[index].distance, values[index].target, boundaries[index], boundaries[index+1], bambu));
    return result;
}

bool is_physical(const Movement& movement) { return optional_zero(movement.row[TIMING_DISTANCE]) > MOVEMENT_EPSILON; }
bool is_plannable(const Movement& movement) {
    return is_physical(movement) && present(movement.duration)
        && optional_zero(movement.row[EFFECTIVE_FEEDRATE]) > MOVEMENT_EPSILON
        && optional_zero(movement.row[ACCELERATION]) > MOVEMENT_EPSILON;
}

class MotionPlanner {
public:
    MotionPlanner(const bool bambu, Diagnostics& diagnostics, const bool orca = false, const bool prusa = false)
        : bambu_(bambu || orca || prusa), orca_(orca), prusa_(prusa), diagnostics_(diagnostics) {}

    template <typename Emit>
    void process(Event event, Emit emit) {
        if (std::holds_alternative<Dwell>(event)) {
            flush_all(emit);
            emit(std::move(event));
            return;
        }
        const Movement& movement = std::get<Movement>(event);
        if (!is_physical(movement)) {
            pending_.push_back(std::move(event));
            return;
        }
        if (!is_plannable(movement)) {
            flush_all(emit);
            start_speed_ = 0.0;
            emit(std::move(event));
            return;
        }
        pending_.push_back(std::move(event));
        ++pending_physical_;
        diagnostics_.peak_pending_movements = std::max<std::uint64_t>(diagnostics_.peak_pending_movements, pending_physical_);
        if (pending_physical_ > ((orca_ || prusa_) ? 256 : REFRESH_THRESHOLD_MOVEMENTS)) {
            flush_prefix(pending_physical_ - LOOKAHEAD_MOVEMENTS, emit);
        }
    }

    template <typename Emit>
    void finish(Emit emit) { flush_all(emit); }

private:
    std::vector<Event> planned_pending() {
        std::vector<Row> rows;
        for (const Event& event : pending_) {
            if (std::holds_alternative<Movement>(event) && is_plannable(std::get<Movement>(event))) rows.push_back(std::get<Movement>(event).row);
        }
        if (rows.empty()) return pending_;
        const Row* previous = previous_.has_value() ? &previous_->row : nullptr;
        const std::vector<Planned> planned = calculate_plan(rows, start_speed_, bambu_, previous, orca_, prusa_);
        std::vector<Event> result = pending_;
        std::size_t planned_index = 0;
        for (Event& event : result) {
            if (!std::holds_alternative<Movement>(event) || !is_plannable(std::get<Movement>(event))) continue;
            Movement& movement = std::get<Movement>(event);
            const Planned& value = planned[planned_index++];
            movement.row[EFFECTIVE_FEEDRATE] = value.feedrate;
            if (bambu_) movement.row[TIMING_DISTANCE] = value.distance;
            movement.duration = value.duration;
            movement.entry_speed = value.entry;
            movement.exit_speed = value.exit;
        }
        return result;
    }

    template <typename Emit>
    void flush_prefix(const std::size_t physical_count, Emit emit) {
        std::vector<Event> planned = planned_pending();
        std::size_t seen = 0;
        std::size_t cutoff = 0;
        for (; cutoff < planned.size(); ++cutoff) {
            if (std::holds_alternative<Movement>(planned[cutoff]) && is_plannable(std::get<Movement>(planned[cutoff]))) ++seen;
            if (seen == physical_count) break;
        }
        Movement cutoff_movement = std::get<Movement>(planned[cutoff]);
        start_speed_ = optional_zero(cutoff_movement.exit_speed);
        previous_ = cutoff_movement;
        for (std::size_t index = 0; index <= cutoff; ++index) emit(std::move(planned[index]));
        pending_.erase(pending_.begin(), pending_.begin() + static_cast<std::ptrdiff_t>(cutoff + 1));
        pending_physical_ -= physical_count;
        ++diagnostics_.planner_flush_count;
    }

    template <typename Emit>
    void flush_all(Emit emit) {
        if (pending_.empty()) {
            start_speed_ = 0.0;
            previous_.reset();
            return;
        }
        std::vector<Event> planned = planned_pending();
        for (Event& event : planned) emit(std::move(event));
        pending_.clear();
        pending_physical_ = 0;
        start_speed_ = 0.0;
        previous_.reset();
        ++diagnostics_.planner_flush_count;
    }

    bool bambu_ = false;
    bool orca_ = false;
    bool prusa_ = false;
    Diagnostics& diagnostics_;
    std::vector<Event> pending_;
    std::size_t pending_physical_ = 0;
    double start_speed_ = 0.0;
    std::optional<Movement> previous_;
};

struct LayerAccumulator : LayerResult {
    LayerResult record() const { return static_cast<const LayerResult&>(*this); }
};

struct ExplicitMarker { std::int64_t start_line; double z; double height; };

class LayerCollector {
public:
    explicit LayerCollector(const bool explicit_markers) : explicit_(explicit_markers) {}

    void mark(const std::int64_t line, const double z, const double height) {
        if (explicit_) markers_.push_back({line, z, height});
    }

    void consume(const Event& event) {
        if (explicit_) { consume_explicit(event); return; }
        if (!current_.has_value()) { before_first(event); return; }
        if (!candidates_.empty()) { candidates_.push_back(event); evaluate(event); return; }
        if (std::holds_alternative<Movement>(event)
            && std::get<Movement>(event).end_z > current_->z_mm + Z_EPSILON_MM) {
            candidates_.push_back(event); evaluate(event); return;
        }
        add(*current_, event);
    }

    void finish(Result& result) {
        if (!candidates_.empty()) reject();
        if (current_.has_value()) { completed_.push_back(current_->record()); current_.reset(); }
        result.layers = std::move(completed_);
        result.confirmed_layer_changes = confirmed_;
        result.rejected_z_candidates = rejected_;
        result.pre_layer_event_count = pre_events_;
        result.pre_layer_time_s = pre_time_;
        result.pre_layer_untimed_event_count = pre_untimed_;
    }

private:
    static std::int64_t line_number(const Event& event) {
        return std::holds_alternative<Movement>(event)
            ? std::get<Movement>(event).line_number : std::get<Dwell>(event).line_number;
    }
    static double duration(const Event& event) {
        return std::holds_alternative<Movement>(event)
            ? std::get<Movement>(event).duration : std::get<Dwell>(event).duration;
    }
    static bool positive_deposition(const Movement& movement) {
        return movement.category == Category::deposition && movement.delta_e > EXTRUSION_EPSILON_MM;
    }
    static void add(LayerAccumulator& layer, const Event& event) {
        ++layer.event_count;
        layer.end_line = std::max(layer.end_line, line_number(event));
        if (std::holds_alternative<Dwell>(event)) {
            const double value = std::get<Dwell>(event).duration;
            if (!present(value)) ++layer.untimed_event_count;
            else { layer.total_time_s += value; layer.dwell_time_s += value; }
            return;
        }
        const Movement& movement = std::get<Movement>(event);
        ++layer.movement_count;
        if (movement.category == Category::deposition) {
            ++layer.deposition_count;
            if (layer.first_deposition_line <= 0) layer.first_deposition_line = movement.line_number;
            if (present(movement.path_length)) layer.deposition_path_mm += movement.path_length;
            if (movement.delta_e > 0.0) layer.deposition_e_mm += movement.delta_e;
        }
        if (!present(movement.duration)) {
            ++layer.untimed_event_count;
            if (present(movement.row[TIMING_DISTANCE])) layer.untimed_distance_mm += movement.row[TIMING_DISTANCE];
            return;
        }
        layer.total_time_s += movement.duration;
        if (movement.category == Category::deposition) layer.deposition_time_s += movement.duration;
        else if (movement.category == Category::travel || movement.category == Category::travel_with_retraction) layer.travel_time_s += movement.duration;
        else if (movement.category == Category::retraction) layer.retraction_time_s += movement.duration;
        else if (movement.category == Category::unretraction) layer.unretraction_time_s += movement.duration;
        else layer.other_time_s += movement.duration;
    }
    void before_first(const Event& event) {
        if (std::holds_alternative<Movement>(event) && positive_deposition(std::get<Movement>(event))) {
            const Movement& movement = std::get<Movement>(event);
            LayerAccumulator layer;
            layer.index = 1;
            layer.z_mm = movement.end_z;
            layer.height_mm = std::max(0.0, movement.end_z);
            layer.start_line = movement.line_number;
            layer.first_deposition_line = movement.line_number;
            layer.end_line = movement.line_number;
            current_ = layer;
            add(*current_, event);
        } else {
            ++pre_events_;
            const double value = duration(event);
            if (present(value)) pre_time_ += value; else ++pre_untimed_;
        }
    }
    void evaluate(const Event& event) {
        if (!std::holds_alternative<Movement>(event) || !current_.has_value()) return;
        const Movement& movement = std::get<Movement>(event);
        if (positive_deposition(movement) && movement.end_z > current_->z_mm + Z_EPSILON_MM) {
            completed_.push_back(current_->record());
            LayerAccumulator next;
            next.index = current_->index + 1;
            next.z_mm = movement.end_z;
            next.height_mm = movement.end_z - current_->z_mm;
            next.start_line = line_number(candidates_.front());
            next.first_deposition_line = movement.line_number;
            next.end_line = movement.line_number;
            for (const Event& candidate : candidates_) add(next, candidate);
            candidates_.clear(); current_ = next; ++confirmed_;
        } else if (movement.end_z <= current_->z_mm + Z_EPSILON_MM) reject();
    }
    void reject() {
        if (current_.has_value()) for (const Event& event : candidates_) add(*current_, event);
        candidates_.clear(); ++rejected_;
    }
    void consume_explicit(const Event& event) {
        while (marker_index_ < markers_.size() && line_number(event) >= markers_[marker_index_].start_line) {
            const ExplicitMarker& marker = markers_[marker_index_++];
            if (current_.has_value()) { completed_.push_back(current_->record()); ++confirmed_; }
            LayerAccumulator next;
            next.index = static_cast<std::int64_t>(completed_.size() + 1);
            next.z_mm = marker.z; next.height_mm = marker.height;
            next.start_line = marker.start_line; next.end_line = marker.start_line;
            current_ = next;
        }
        const bool startup_untimed = current_.has_value() && current_->index == 1
            && current_->first_deposition_line == 0 && std::holds_alternative<Movement>(event)
            && std::get<Movement>(event).category != Category::deposition
            && !present(duration(event));
        if (!current_.has_value() || startup_untimed) {
            ++pre_events_;
            const double value = duration(event);
            if (present(value)) pre_time_ += value; else ++pre_untimed_;
        } else add(*current_, event);
    }
    bool explicit_ = false;
    std::vector<ExplicitMarker> markers_;
    std::size_t marker_index_ = 0;
    std::vector<LayerResult> completed_;
    std::optional<LayerAccumulator> current_;
    std::vector<Event> candidates_;
    std::int64_t confirmed_ = 0, rejected_ = 0, pre_events_ = 0, pre_untimed_ = 0;
    double pre_time_ = 0.0;
};

struct SegmentRecord { double layer; PreviewSegment segment; std::int64_t line; };

bool segment_equal(const PreviewSegment& left, const PreviewSegment& right) {
    return left.start_x==right.start_x && left.start_y==right.start_y && left.start_z==right.start_z
        && left.end_x==right.end_x && left.end_y==right.end_y && left.end_z==right.end_z;
}

bool collinear(const PreviewSegment& first, const PreviewSegment& second) {
    const double join = std::sqrt(
        (first.end_x-second.start_x)*(first.end_x-second.start_x)
        + (first.end_y-second.start_y)*(first.end_y-second.start_y)
        + (first.end_z-second.start_z)*(first.end_z-second.start_z)
    );
    if (join > 1e-5) return false;
    const std::array<double,3> a = {first.end_x-first.start_x, first.end_y-first.start_y, first.end_z-first.start_z};
    const std::array<double,3> b = {second.end_x-second.start_x, second.end_y-second.start_y, second.end_z-second.start_z};
    const double al = std::sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);
    const double bl = std::sqrt(b[0]*b[0]+b[1]*b[1]+b[2]*b[2]);
    if (al <= 1e-9 || bl <= 1e-9) return false;
    return (a[0]*b[0]+a[1]*b[1]+a[2]*b[2])/(al*bl) >= 0.99995;
}

std::FILE* open_temporary_file() {
#ifdef _MSC_VER
    std::FILE* result = nullptr;
    return ::tmpfile_s(&result) == 0 ? result : nullptr;
#else
    return std::tmpfile();
#endif
}

class PreviewCollector {
public:
    PreviewCollector(const bool enabled, const std::size_t maximum, Diagnostics& diagnostics)
        : enabled_(enabled), maximum_(maximum), diagnostics_(diagnostics),
          spool_(enabled ? open_temporary_file() : nullptr) {}
    ~PreviewCollector() {
        if (spool_ != nullptr) std::fclose(spool_);
    }
    bool valid() const { return !enabled_ || spool_ != nullptr; }
    void observe(const ParsedLine& line) {
        if (!enabled_ || !line.has_comment) return;
        const std::string comment = trim(line.comment);
        if (starts_with(lowercase(comment), "generated by prusaslicer ")) prusa_startup_ = true;
        if (prusa_startup_ && comment == "LAYER_CHANGE") prusa_layer_started_ = true;
        const std::string feature = lowercase(comment);
        if (starts_with(feature, "type:") || starts_with(feature, "feature:")) {
            const std::string name = trim(feature.substr(feature.find(':')+1));
            const bool wall = name=="outer wall" || name=="external perimeter";
            if (wall != wall_) printing_wall_ = false;
            wall_ = wall;
        } else if (feature=="layer_change" || feature=="change_layer") {
            printing_wall_=false; seam_layer_z_=missing();
        } else if (starts_with(feature,"z:") || starts_with(feature,"z_height:")) {
            try { seam_layer_z_=std::stod(trim(feature.substr(feature.find(':')+1))); }
            catch (...) {}
        }
    }
    void consume(const Movement& movement) {
        if (!enabled_) return;
        if (prusa_startup_ && !prusa_layer_started_) return;
        if (movement.category != Category::deposition) {
            if (std::hypot(std::hypot(movement.end_x-movement.start_x,movement.end_y-movement.start_y),
                    movement.end_z-movement.start_z)>1e-6
                    || movement.category==Category::retraction || movement.category==Category::unretraction)
                printing_wall_=false;
            return;
        }
        if (wall_ && !printing_wall_) {
            ++seams_seen_;
            if ((seams_seen_-1)%seam_stride_==0) {
                seams_.push_back({movement.start_x,movement.start_y,
                    present(seam_layer_z_) ? seam_layer_z_ : movement.end_z});
                if (seams_.size()>20000) {
                    std::vector<std::array<double,3>> reduced;
                    for (std::size_t i=0;i<seams_.size();i+=2) reduced.push_back(seams_[i]);
                    seams_=std::move(reduced); seam_stride_*=2;
                }
            }
        }
        printing_wall_=true;
        minimum_x_ = std::min({minimum_x_, movement.start_x, movement.end_x});
        maximum_x_ = std::max({maximum_x_, movement.start_x, movement.end_x});
        minimum_y_ = std::min({minimum_y_, movement.start_y, movement.end_y});
        maximum_y_ = std::max({maximum_y_, movement.start_y, movement.end_y});
        const std::array<double,6> values = {movement.start_x,movement.start_y,movement.start_z,movement.end_x,movement.end_y,movement.end_z};
        for (double value : values) if (!std::isfinite(value)) return;
        ++source_count_;
        ++diagnostics_.preview_candidate_count;
        PreviewSegment segment{movement.start_x,movement.start_y,movement.start_z,movement.end_x,movement.end_y,movement.end_z};
        const double layer = std::nearbyint(movement.end_z * 10000.0) / 10000.0;
        if (pending_.has_value() && pending_layer_ == layer && collinear(*pending_, segment)) {
            pending_->end_x=segment.end_x; pending_->end_y=segment.end_y; pending_->end_z=segment.end_z;
            return;
        }
        flush(); pending_=segment; pending_layer_=layer; pending_line_=movement.line_number;
    }
    void finish(Result& result, const std::size_t layer_count) {
        if (!enabled_) return;
        flush();
        const std::size_t per_layer = std::max<std::size_t>(8, std::min<std::size_t>(256, maximum_/std::max<std::size_t>(1, layer_count)));
        struct LayerSample {
            std::array<std::optional<PreviewSegment>,4> extremes;
            std::array<double,4> extreme_values{};
            std::vector<PreviewSegment> samples;
            std::size_t seen = 0;
        };
        std::map<double, LayerSample> grouped;
        std::rewind(spool_);
        SegmentRecord record;
        while (std::fread(&record, sizeof(record), 1, spool_) == 1) {
            LayerSample& sample = grouped[record.layer];
            ++sample.seen;
            const PreviewSegment& segment = record.segment;
            const std::array<double,4> values = {
                std::min(segment.start_x,segment.end_x), std::max(segment.start_x,segment.end_x),
                std::min(segment.start_y,segment.end_y), std::max(segment.start_y,segment.end_y)};
            for (std::size_t key=0; key<4; ++key) {
                if (!sample.extremes[key].has_value() || ((key==0||key==2) ? values[key]<sample.extreme_values[key] : values[key]>sample.extreme_values[key])) {
                    sample.extremes[key]=segment;
                    sample.extreme_values[key]=values[key];
                }
            }
            if (sample.samples.size()<per_layer) sample.samples.push_back(segment);
            else {
                const std::size_t slot = (static_cast<std::uint64_t>(record.line)*2654435761ULL)%sample.seen;
                if (slot<per_layer) sample.samples[slot]=segment;
            }
        }
        if (std::ferror(spool_)) {
            throw std::runtime_error("Unable to read native preview spool.");
        }
        std::vector<PreviewSegment> output;
        for (const auto& entry : grouped) {
            std::vector<PreviewSegment> layer_values;
            for (const auto& value : entry.second.extremes) if (value.has_value()) layer_values.push_back(*value);
            layer_values.insert(layer_values.end(),entry.second.samples.begin(),entry.second.samples.end());
            std::vector<PreviewSegment> unique_layer_values;
            for (const PreviewSegment& segment : layer_values) {
                bool duplicate=false; for (const PreviewSegment& seen_segment : unique_layer_values) {
                    if (segment_equal(segment,seen_segment)) { duplicate=true; break; }
                }
                if (!duplicate) unique_layer_values.push_back(segment);
            }
            output.insert(
                output.end(),
                unique_layer_values.begin(),
                unique_layer_values.end()
            );
        }
        if (output.size()>maximum_) {
            const double step=static_cast<double>(output.size())/static_cast<double>(maximum_);
            std::vector<PreviewSegment> reduced; reduced.reserve(maximum_);
            for (std::size_t index=0; index<maximum_; ++index) reduced.push_back(output[static_cast<std::size_t>(index*step)]);
            output=std::move(reduced);
        }
        result.preview_segments=std::move(output); result.preview_source_segment_count=source_count_;
        result.seam_points=std::move(seams_);
        if (std::isfinite(minimum_x_)&&std::isfinite(maximum_x_)&&std::isfinite(minimum_y_)&&std::isfinite(maximum_y_)) {
            result.has_occupied_bounds=true; result.minimum_x=minimum_x_; result.maximum_x=maximum_x_; result.minimum_y=minimum_y_; result.maximum_y=maximum_y_;
        }
    }
private:
    void flush() {
        if (pending_.has_value()) {
            const SegmentRecord record{pending_layer_,*pending_,pending_line_};
            if (std::fwrite(&record, sizeof(record), 1, spool_) != 1) {
                throw std::runtime_error("Unable to spool native preview data.");
            }
        }
        pending_.reset();
    }
    bool prusa_startup_ = false, prusa_layer_started_ = false;
    bool wall_=false, printing_wall_=false;
    double seam_layer_z_=missing();
    std::vector<std::array<double,3>> seams_;
    std::uint64_t seams_seen_=0, seam_stride_=1;
    bool enabled_; std::size_t maximum_; Diagnostics& diagnostics_;
    std::FILE* spool_; std::optional<PreviewSegment> pending_; double pending_layer_=0.0; std::int64_t pending_line_=0;
    std::uint64_t source_count_=0; double minimum_x_=std::numeric_limits<double>::infinity(),maximum_x_=-std::numeric_limits<double>::infinity(),minimum_y_=std::numeric_limits<double>::infinity(),maximum_y_=-std::numeric_limits<double>::infinity();
};

class InfillCollector {
public:
    explicit InfillCollector(const bool enabled) : enabled_(enabled) {}
    void consume(const ParsedLine& line) {
        if (!enabled_) return;
        if (line.command == "M486") {
            if (has_parameter(line, "S")) {
                const double index = parameter(line, "S");
                marlin_index_ = std::isfinite(index) && index >= 0
                    && index <= std::numeric_limits<int>::max() && index == std::floor(index)
                    ? static_cast<int>(index) : -1;
            }
            bambu_object_ = marlin_index_ >= 0;
            const auto name_position = line.code.find(" A");
            if (name_position != std::string::npos && marlin_index_ >= 0)
                marlin_names_[marlin_index_] = lowercase(trim(line.code.substr(name_position + 2)));
            const auto name = marlin_names_.find(marlin_index_);
            inside_ = marlin_index_ >= 0 && name != marlin_names_.end()
                && (name->second.find("cooling_tower") != std::string::npos || name->second.find("cooling tower") != std::string::npos);
            if (inside_ && has_parameter(line, "S")) ++result_.tower_block_count;
            return;
        }
        if (line.command=="EXCLUDE_OBJECT_START") { bambu_object_=false; const auto label=lowercase(line.code); inside_=label.find("cooling_tower")!=std::string::npos || label.find("cooling tower")!=std::string::npos; if (inside_) ++result_.tower_block_count; return; }
        if (line.command=="EXCLUDE_OBJECT_END") { inside_=false; return; }
        if (!line.has_comment) { coordinates(line); return; }
        const std::string folded=lowercase(line.comment);
        if (starts_with(folded,"printing object ")) { bambu_object_=true; inside_=folded.find("cooling_tower")!=std::string::npos || folded.find("cooling tower")!=std::string::npos; if (inside_) ++result_.tower_block_count; return; }
        if (starts_with(folded,"start printing object, unique label id:")) { const std::string id=trim(folded.substr(folded.find(':')+1)); bool digits=!id.empty(); for(char c:id) digits=digits&&ascii_digit(c); if(digits){active_label_=std::stoll(id);bambu_object_=true;} return; }
        if (starts_with(folded,"stop printing object")) {inside_=false;bambu_object_=false;active_label_.reset();return;}
        if (folded=="type:sparse infill") {if(active_label_.has_value()) sparse_labels_.insert(*active_label_);if(inside_)result_.sparse_tower_infill=true;}
        else if(inside_&&!bambu_object_&&folded=="feature: sparse infill") result_.sparse_tower_infill=true;
        coordinates(line);
    }
    InfillEvidence finish() { result_.sparse_labels.assign(sparse_labels_.begin(),sparse_labels_.end()); return std::move(result_); }
private:
    void coordinates(const ParsedLine& line){if(!active_label_.has_value()||!has_parameter(line,"X")||!has_parameter(line,"Y"))return;const double x=parameter(line,"X"),y=parameter(line,"Y");auto& b=result_.label_bounds[*active_label_];if(b.empty())b={x,x,y,y};else{b[0]=std::min(b[0],x);b[1]=std::max(b[1],x);b[2]=std::min(b[2],y);b[3]=std::max(b[3],y);}}
    int marlin_index_ = -1; std::map<int, std::string> marlin_names_;
    bool enabled_=false,inside_=false,bambu_object_=false;std::optional<std::int64_t>active_label_;std::set<std::int64_t>sparse_labels_;InfillEvidence result_;
};

bool metadata_relevant(const ParsedLine& line) {
    if (line.command=="M201"||line.command=="M204"||line.command=="M205"||line.command=="SET_VELOCITY_LIMIT") return true;
    if (!line.has_comment) return false;
    const std::string folded=lowercase(line.comment);
    return folded.find('=')!=std::string::npos||folded.find(':')!=std::string::npos
        ||folded.find("slicer")!=std::string::npos||folded.find("bambu")!=std::string::npos
        ||folded.find("anycubic")!=std::string::npos||folded.find("cura")!=std::string::npos
        ||folded.find("ideamaker")!=std::string::npos||folded.find("simplify3d")!=std::string::npos;
}

void append_metadata(Result& result,const ParsedLine& line){if(!metadata_relevant(line))return;MetadataEvent event;event.line_number=line.number;event.command=line.command;event.has_command=line.has_command;event.comment=line.comment;event.has_comment=line.has_comment;for(const auto& item:line.parameters)event.parameters.push_back(item);result.metadata_events.push_back(std::move(event));++result.diagnostics.metadata_event_count;}

}  // namespace

const char* status_name(const Status status) noexcept {
    switch(status){case Status::success:return "success";case Status::unsupported_syntax:return "unsupported_syntax";case Status::cancelled:return "cancelled";case Status::io_error:return "io_error";case Status::invalid_result:return "invalid_result";}return "invalid_result";
}

Result analyze_file(const std::filesystem::path& path,const Options& options){
    Result result;
    if(options.collect_preview&&options.maximum_preview_segments<100){result.message="maximum_preview_segments must be at least 100";return result;}
    std::ifstream input(path,std::ios::binary);
    if(!input){result.status=Status::io_error;result.message="Unable to open G-code file.";return result;}
    MachineState machine;
    double orca_jd = 0.0;
    if (options.orca_compatible || options.prusa_compatible) {
        const auto found = options.orca_limits.find("machine_max_junction_deviation");
        if (found != options.orca_limits.end()) orca_jd = found->second;
        apply_orca_limits(machine, options, orca_jd, true);
        if (options.prusa_compatible && options.orca_marlin2) machine.junction_deviation = orca_jd;
    }
    std::array<double, 4> orca_classic_jerks;
    const std::array<double*, 4> orca_jerk_fields = {&machine.jerk_x, &machine.jerk_y, &machine.jerk_z, &machine.jerk_e};
    for (std::size_t axis = 0; axis < 4; ++axis) {
        const std::string key = "machine_max_jerk_" + std::string(1, "xyze"[axis]);
        const auto found = options.orca_limits.find(key);
        orca_classic_jerks[axis] = found == options.orca_limits.end() ? missing() : found->second;
    }
    LayerCollector layers(options.use_explicit_layer_markers);
    MotionPlanner planner(options.bambu_compatible,result.diagnostics, options.orca_compatible, options.prusa_compatible);
    PreviewCollector preview(options.collect_preview,options.maximum_preview_segments,result.diagnostics);
    if (!preview.valid()) {
        result.status=Status::invalid_result;
        result.message="Unable to create the bounded native preview spool.";
        return result;
    }
    InfillCollector infill(options.collect_infill_evidence);
    std::string raw;
    std::int64_t line_number=0;
    std::optional<std::int64_t> pending_marker_line;
    std::optional<double> pending_marker_z;
    bool pending_marker_prusa_style = false;
    while(std::getline(input,raw)){
        ++line_number;
        result.diagnostics.bytes_read+=raw.size()+1;
        result.diagnostics.line_count=static_cast<std::uint64_t>(line_number);
        if(!raw.empty()&&raw.back()=='\r')raw.pop_back();
        if(options.should_cancel&&options.cancellation_interval_lines>0
            &&static_cast<std::size_t>(line_number)%options.cancellation_interval_lines==0
            &&options.should_cancel(static_cast<std::uint64_t>(line_number),result.diagnostics.bytes_read)){
            result.status=Status::cancelled;result.message="G-Code analysis was cancelled.";return result;
        }
        ParsedLine line=parse_line(raw,line_number);
        preview.observe(line);
        append_metadata(result,line);
        infill.consume(line);
        if (options.orca_compatible && line.command == "M4899" && has_parameter(line, "T") && parameter(line, "T") == 3.0) continue;
        if (options.orca_compatible && line.command == "M205" && has_parameter(line, "J")) orca_jd = parameter(line, "J") * machine.unit_scale_mm;
        if (options.prusa_compatible && options.orca_marlin2 && line.command == "M205" && has_parameter(line, "J"))
            machine.junction_deviation = std::max(0.0, parameter(line, "J") * machine.unit_scale_mm);
        if (options.orca_compatible && line.command == "M205")
            for (std::size_t axis = 0; axis < 4; ++axis) *orca_jerk_fields[axis] = orca_classic_jerks[axis];
        if(options.use_explicit_layer_markers&&line.has_comment){
            const std::string comment=trim(line.comment);
            if(comment=="LAYER_CHANGE" || comment=="CHANGE_LAYER") {
                pending_marker_prusa_style = comment=="LAYER_CHANGE";
                pending_marker_line=line.number;pending_marker_z.reset();
            }
            const std::string z_prefix = pending_marker_prusa_style ? "Z:" : "Z_HEIGHT:";
            const std::string height_prefix = pending_marker_prusa_style ? "HEIGHT:" : "LAYER_HEIGHT:";
            if(pending_marker_line.has_value()&&starts_with(comment,z_prefix)){
                try{pending_marker_z=std::stod(trim(comment.substr(z_prefix.size())));}catch(...){pending_marker_line.reset();pending_marker_z.reset();}
            }else if(pending_marker_line.has_value()&&pending_marker_z.has_value()&&starts_with(comment,height_prefix)){
                try{layers.mark(*pending_marker_line,*pending_marker_z,std::stod(trim(comment.substr(height_prefix.size()))));}catch(...){}
                pending_marker_line.reset();pending_marker_z.reset();
            }
        }
        bool unsupported=false;
        const double previous_retract_acceleration = machine.retract_acceleration;
        std::optional<Event> event=process_machine_line(
            machine,
            line,
            options.bambu_compatible || options.orca_compatible || options.prusa_compatible,
            options.anycubic_slicer_next_compatible,
            unsupported,
            options.bambu_compatible,
            options.prusa_compatible
        );
        if (options.orca_compatible && line.command == "SET_VELOCITY_LIMIT") {
            machine.retract_acceleration = previous_retract_acceleration;
            if (has_parameter(line, "SQUARE_CORNER_VELOCITY")) {
                const double jerk = parameter(line, "SQUARE_CORNER_VELOCITY") * machine.unit_scale_mm;
                machine.jerk_x = machine.jerk_y = jerk;
                orca_classic_jerks[0] = orca_classic_jerks[1] = jerk;
            }
            if (has_parameter(line, "VELOCITY"))
                machine.maximum_feedrate_x = machine.maximum_feedrate_y = parameter(line, "VELOCITY") * machine.unit_scale_mm;
        }
        if (options.orca_compatible && line.command == "M205")
            for (std::size_t axis = 0; axis < 4; ++axis) orca_classic_jerks[axis] = *orca_jerk_fields[axis];
        if (options.orca_compatible && (line.command == "M201" || line.command == "M204" || line.command == "M205" || line.command == "SET_VELOCITY_LIMIT"))
            apply_orca_limits(machine, options, orca_jd, false);
        if(unsupported){result.status=Status::unsupported_syntax;result.message="Potentially state-changing G-code is not supported by the native analyzer.";result.fallback_line=line.number;result.fallback_command=line.has_command?line.command:line.unparsed;return result;}
        if(!event.has_value())continue;
        if(std::holds_alternative<Movement>(*event)){++result.diagnostics.movement_count;preview.consume(std::get<Movement>(*event));}
        else ++result.diagnostics.dwell_count;
        planner.process(std::move(*event),[&layers](Event emitted){layers.consume(emitted);});
    }
    if(input.bad()){result.status=Status::io_error;result.message="Unable to read G-code file.";return result;}
    if(options.should_cancel&&options.should_cancel(static_cast<std::uint64_t>(line_number),result.diagnostics.bytes_read)){result.status=Status::cancelled;result.message="G-Code analysis was cancelled.";return result;}
    planner.finish([&layers](Event emitted){layers.consume(emitted);});
    layers.finish(result);
    if(result.layers.empty()){result.status=Status::invalid_result;result.message="No printable layers were detected in the G-code.";return result;}
    preview.finish(result,result.layers.size());
    result.infill=infill.finish();
    result.diagnostics.anycubic_startup_macro_count =
        machine.anycubic_startup_macro_count;
    result.status=Status::success;
    return result;
}

}  // namespace cooling_tower::native_analysis
