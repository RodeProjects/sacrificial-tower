#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "native_analysis.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <deque>
#include <filesystem>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

constexpr double MOVEMENT_EPSILON = 1e-9;
constexpr double ARC_EPSILON = 1e-7;
constexpr std::size_t ROW_WIDTH = 33;
constexpr std::uint64_t ENGINE_VERSION = 3;
constexpr std::size_t DEFAULT_CACHE_BYTES = 64ULL * 1024ULL * 1024ULL;

enum RowIndex : std::size_t {
    ENDPOINT_XY = 0,
    ENDPOINT_XYZ,
    DELTA_X,
    DELTA_Y,
    DELTA_Z,
    DELTA_E,
    PATH_LENGTH,
    EFFECTIVE_FEEDRATE,
    TIMING_DISTANCE,
    ACCELERATION,
    JERK_X,
    JERK_Y,
    JERK_Z,
    JERK_E,
    SQUARE_CORNER_VELOCITY,
    ENTRY_DIRECTION_X,
    ENTRY_DIRECTION_Y,
    ENTRY_DIRECTION_Z,
    EXIT_DIRECTION_X,
    EXIT_DIRECTION_Y,
    EXIT_DIRECTION_Z,
    ARC_PLANAR_LENGTH,
    ARC_START_RADIUS,
    ARC_SWEEP_DEGREES,
    MAXIMUM_FEEDRATE_X,
    MAXIMUM_FEEDRATE_Y,
    MAXIMUM_FEEDRATE_Z,
    MAXIMUM_FEEDRATE_E,
    MINIMUM_EXTRUDING_FEEDRATE,
    MINIMUM_TRAVEL_FEEDRATE,
    EXTRUSION_FACTOR,
    CENTRIPETAL_ACCELERATION,
    IS_ARC,
};

using Row = std::array<double, ROW_WIDTH>;

struct Direction4 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double e = 0.0;
    bool valid = false;
};

struct Direction2 {
    double x = 0.0;
    double y = 0.0;
    bool valid = false;
};

struct Kinematics {
    double target_speed = 0.0;
    double distance = 0.0;
    double acceleration = 0.0;
    double safe_speed = 0.0;
    Direction4 direction;
};

struct PlannedValue {
    double effective_feedrate = 0.0;
    double timing_distance = 0.0;
    double duration = 0.0;
    double entry_speed = 0.0;
    double cruise_speed = 0.0;
    double exit_speed = 0.0;
};

struct CommonLine {
    std::string code;
    std::string command;
    std::vector<std::pair<std::string, double>> parameters;
    std::string comment;
    std::string unparsed;
    bool has_command = false;
    bool has_comment = false;
    bool has_unparsed = false;
};

struct VectorHash {
    std::size_t operator()(const std::vector<std::uint64_t>& values) const noexcept {
        std::uint64_t hash = 1469598103934665603ULL;
        for (const std::uint64_t value : values) {
            hash ^= value;
            hash *= 1099511628211ULL;
            hash ^= value >> 32;
            hash *= 1099511628211ULL;
        }
        return static_cast<std::size_t>(hash);
    }
};

struct CacheEntry {
    std::vector<PlannedValue> values;
    std::size_t bytes = 0;
};

std::unordered_map<std::vector<std::uint64_t>, CacheEntry, VectorHash> block_cache;
std::deque<std::vector<std::uint64_t>> cache_order;
std::size_t cache_bytes = 0;
std::size_t maximum_cache_bytes = DEFAULT_CACHE_BYTES;
std::uint64_t cache_hits = 0;
std::uint64_t cache_misses = 0;
std::uint64_t cache_evictions = 0;
std::mutex cache_mutex;

inline bool ascii_space(const char character) {
    return character == ' ' || character == '\t' || character == '\r'
        || character == '\n' || character == '\f' || character == '\v';
}

inline bool ascii_alpha(const char character) {
    return (character >= 'A' && character <= 'Z')
        || (character >= 'a' && character <= 'z');
}

inline bool ascii_digit(const char character) {
    return character >= '0' && character <= '9';
}

inline char ascii_upper(const char character) {
    return character >= 'a' && character <= 'z'
        ? static_cast<char>(character - ('a' - 'A'))
        : character;
}

std::pair<std::size_t, std::size_t> trim_bounds(
    const std::string& value,
    std::size_t begin,
    std::size_t end
) {
    while (begin < end && ascii_space(value[begin])) {
        ++begin;
    }
    while (end > begin && ascii_space(value[end - 1])) {
        --end;
    }
    return {begin, end};
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
        std::size_t exponent_cursor = cursor + 1;
        if (
            exponent_cursor < text.size()
            && (text[exponent_cursor] == '+' || text[exponent_cursor] == '-')
        ) {
            ++exponent_cursor;
        }
        const std::size_t exponent_begin = exponent_cursor;
        while (exponent_cursor < text.size() && ascii_digit(text[exponent_cursor])) {
            ++exponent_cursor;
        }
        if (exponent_cursor > exponent_begin) {
            cursor = exponent_cursor;
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

bool parse_common_line(const std::string& raw, CommonLine& result) {
    for (const unsigned char character : raw) {
        if (
            character >= 0x80
            || (character < 0x20 && !ascii_space(static_cast<char>(character)))
        ) {
            return false;
        }
    }
    if (raw.find('(') != std::string::npos || raw.find('=') != std::string::npos) {
        return false;
    }
    if (raw.empty()) {
        return true;
    }
    if (raw.front() == ';') {
        const auto comment_bounds = trim_bounds(raw, 1, raw.size());
        result.comment = raw.substr(
            comment_bounds.first,
            comment_bounds.second - comment_bounds.first
        );
        result.has_comment = true;
        return true;
    }

    const std::size_t semicolon = raw.find(';');
    const std::size_t code_end = (
        semicolon == std::string::npos ? raw.size() : semicolon
    );
    const auto code_bounds = trim_bounds(raw, 0, code_end);
    result.code = raw.substr(
        code_bounds.first,
        code_bounds.second - code_bounds.first
    );
    if (semicolon != std::string::npos) {
        const auto comment_bounds = trim_bounds(raw, semicolon + 1, raw.size());
        result.comment = raw.substr(
            comment_bounds.first,
            comment_bounds.second - comment_bounds.first
        );
        result.has_comment = true;
    }
    if (result.code.empty()) {
        return true;
    }
    // Communication checksums and line-number prefixes are uncommon in
    // slicer output and stay on the reference parser's exact fallback path.
    if (
        result.code.find('*') != std::string::npos
        || (
            result.code.size() >= 2
            && (result.code[0] == 'N' || result.code[0] == 'n')
            && ascii_digit(result.code[1])
        )
    ) {
        return false;
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
                while (
                    cursor < result.code.size()
                    && (ascii_alpha(result.code[cursor]) || ascii_digit(result.code[cursor]))
                ) {
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
        result.has_unparsed = true;
        return true;
    }
    result.command.reserve(command_end);
    for (std::size_t index = 0; index < command_end; ++index) {
        result.command.push_back(ascii_upper(result.code[index]));
    }
    result.has_command = true;

    std::size_t cursor = command_end;
    while (cursor < result.code.size()) {
        const std::size_t parameter_begin = cursor;
        while (cursor < result.code.size() && ascii_space(result.code[cursor])) {
            ++cursor;
        }
        if (cursor >= result.code.size() || !ascii_alpha(result.code[cursor])) {
            break;
        }
        std::string name(1, ascii_upper(result.code[cursor]));
        ++cursor;
        while (cursor < result.code.size() && ascii_space(result.code[cursor])) {
            ++cursor;
        }
        std::size_t number_end = cursor;
        double value = 0.0;
        if (!parse_number(result.code, cursor, number_end, value)) {
            cursor = parameter_begin;
            break;
        }
        result.parameters.emplace_back(std::move(name), value);
        cursor = number_end;
    }
    const auto remaining_bounds = trim_bounds(result.code, cursor, result.code.size());
    if (remaining_bounds.first < remaining_bounds.second) {
        result.unparsed = result.code.substr(
            remaining_bounds.first,
            remaining_bounds.second - remaining_bounds.first
        );
        result.has_unparsed = true;
    }
    return true;
}

inline bool present(const double value) {
    return !std::isnan(value);
}

inline bool is_arc(const Row& movement) {
    return movement[IS_ARC] != 0.0;
}

inline double optional_or_zero(const double value) {
    return present(value) ? value : 0.0;
}

inline std::uint64_t double_bits(const double value) {
    std::uint64_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value), "Unexpected double width");
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

double planar_length(const Row& movement) {
    if (
        is_arc(movement)
        && present(movement[ARC_START_RADIUS])
        && movement[ARC_START_RADIUS] > ARC_EPSILON
        && present(movement[ARC_SWEEP_DEGREES])
    ) {
        constexpr double PI = 3.141592653589793238462643383279502884;
        return movement[ARC_START_RADIUS] * movement[ARC_SWEEP_DEGREES] * PI / 180.0;
    }
    return movement[ARC_PLANAR_LENGTH];
}

double bambu_timing_distance(const Row& movement) {
    const double planar = planar_length(movement);
    if (is_arc(movement) && present(planar)) {
        return std::hypot(planar, movement[DELTA_Z]);
    }
    return optional_or_zero(movement[TIMING_DISTANCE]);
}

Direction4 movement_direction(const Row& movement) {
    Direction4 result;
    if (movement[ENDPOINT_XYZ] > MOVEMENT_EPSILON) {
        const double distance = movement[ENDPOINT_XYZ];
        result.x = movement[DELTA_X] / distance;
        result.y = movement[DELTA_Y] / distance;
        result.z = movement[DELTA_Z] / distance;
        result.e = 0.0;
        result.valid = true;
    } else if (std::abs(movement[DELTA_E]) > MOVEMENT_EPSILON) {
        result.e = std::copysign(1.0, movement[DELTA_E]);
        result.valid = true;
    }
    return result;
}

Direction2 bambu_xy_direction(const Row& movement, const bool at_exit) {
    Direction2 result;
    const std::size_t x_index = at_exit ? EXIT_DIRECTION_X : ENTRY_DIRECTION_X;
    const std::size_t y_index = at_exit ? EXIT_DIRECTION_Y : ENTRY_DIRECTION_Y;
    double x = movement[x_index];
    double y = movement[y_index];
    if (!present(x) || !present(y)) {
        x = movement[DELTA_X];
        y = movement[DELTA_Y];
    }
    const double length = std::hypot(x, y);
    if (length > MOVEMENT_EPSILON) {
        result.x = x / length;
        result.y = y / length;
        result.valid = true;
    }
    return result;
}

std::array<double, 4> bambu_axis_feedrates(
    const Row& movement,
    const double speed
) {
    const double distance = bambu_timing_distance(movement);
    if (distance <= MOVEMENT_EPSILON) {
        return {0.0, 0.0, 0.0, 0.0};
    }
    const double planar = planar_length(movement);
    if (is_arc(movement) && present(planar)) {
        const double planar_speed = speed * planar / distance;
        return {
            planar_speed,
            planar_speed,
            speed * movement[DELTA_Z] / distance,
            speed * movement[DELTA_E] / distance * movement[EXTRUSION_FACTOR],
        };
    }
    return {
        speed * movement[DELTA_X] / distance,
        speed * movement[DELTA_Y] / distance,
        speed * movement[DELTA_Z] / distance,
        speed * movement[DELTA_E] / distance * movement[EXTRUSION_FACTOR],
    };
}

double bambu_cruise_feedrate(const Row& movement, const Row* previous) {
    double speed = optional_or_zero(movement[EFFECTIVE_FEEDRATE]) / 60.0;
    const double minimum = (
        std::abs(movement[DELTA_E]) <= MOVEMENT_EPSILON
        ? movement[MINIMUM_TRAVEL_FEEDRATE]
        : movement[MINIMUM_EXTRUDING_FEEDRATE]
    );
    if (present(minimum)) {
        speed = std::max(speed, minimum);
    }

    const double centripetal = movement[CENTRIPETAL_ACCELERATION];
    if (
        is_arc(movement)
        && present(movement[ARC_START_RADIUS])
        && movement[ARC_START_RADIUS] > ARC_EPSILON
        && present(centripetal)
        && centripetal > MOVEMENT_EPSILON
    ) {
        const double planar = planar_length(movement);
        const double distance = bambu_timing_distance(movement);
        if (
            present(planar)
            && planar > ARC_EPSILON
            && distance > MOVEMENT_EPSILON
        ) {
            const double planar_fraction = planar / distance;
            const double limit = std::sqrt(
                centripetal * movement[ARC_START_RADIUS]
            ) / planar_fraction;
            speed = std::min(speed, limit);
        }
    } else if (
        previous != nullptr
        && !is_arc(movement)
        && present(centripetal)
        && centripetal > MOVEMENT_EPSILON
        && movement[ENDPOINT_XY] > MOVEMENT_EPSILON
    ) {
        const Direction2 previous_direction = bambu_xy_direction(*previous, true);
        const Direction2 current_direction = bambu_xy_direction(movement, false);
        if (previous_direction.valid && current_direction.valid) {
            const double difference = std::hypot(
                current_direction.x - previous_direction.x,
                current_direction.y - previous_direction.y
            );
            if (difference > 0.00001 && difference < 0.5) {
                const double sin_half_angle = difference * 0.5;
                const double radius = movement[ENDPOINT_XY] * 0.5 / sin_half_angle;
                speed = std::min(speed, std::sqrt(centripetal * radius));
            }
        }
    }

    const std::array<double, 4> axis_feedrates = bambu_axis_feedrates(movement, speed);
    const std::array<std::size_t, 4> maximum_indices = {
        MAXIMUM_FEEDRATE_X,
        MAXIMUM_FEEDRATE_Y,
        MAXIMUM_FEEDRATE_Z,
        MAXIMUM_FEEDRATE_E,
    };
    double factor = 1.0;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        const double maximum = movement[maximum_indices[axis]];
        if (
            std::abs(axis_feedrates[axis]) > MOVEMENT_EPSILON
            && present(maximum)
            && maximum > MOVEMENT_EPSILON
        ) {
            factor = std::min(factor, maximum / std::abs(axis_feedrates[axis]));
        }
    }
    return speed * factor;
}

double bambu_safe_feedrate(const Row& movement, const double cruise_speed) {
    if (cruise_speed <= MOVEMENT_EPSILON) {
        return 0.0;
    }
    if (bambu_timing_distance(movement) <= MOVEMENT_EPSILON) {
        return 0.0;
    }
    const std::array<double, 4> axis_speeds = bambu_axis_feedrates(
        movement, cruise_speed
    );
    const std::array<std::size_t, 4> jerk_indices = {
        JERK_X, JERK_Y, JERK_Z, JERK_E,
    };
    double safe = cruise_speed;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        const double jerk = movement[jerk_indices[axis]];
        if (!present(jerk)) {
            continue;
        }
        if (std::abs(axis_speeds[axis]) > jerk) {
            safe = std::min(safe, std::max(0.0, jerk));
        }
    }
    return safe;
}

double generic_junction_speed(const Row& previous, const Row& current) {
    const double previous_speed = optional_or_zero(previous[EFFECTIVE_FEEDRATE]) / 60.0;
    const double current_speed = optional_or_zero(current[EFFECTIVE_FEEDRATE]) / 60.0;
    const double maximum_speed = std::min(previous_speed, current_speed);
    if (maximum_speed <= MOVEMENT_EPSILON) {
        return 0.0;
    }
    const Direction4 previous_direction = movement_direction(previous);
    const Direction4 current_direction = movement_direction(current);
    if (!previous_direction.valid || !current_direction.valid) {
        return 0.0;
    }
    const bool previous_extruder_only = std::abs(previous_direction.e) > 0.0;
    const bool current_extruder_only = std::abs(current_direction.e) > 0.0;
    if (previous_extruder_only != current_extruder_only) {
        return 0.0;
    }
    const std::array<double, 4> changes = {
        current_direction.x - previous_direction.x,
        current_direction.y - previous_direction.y,
        current_direction.z - previous_direction.z,
        current_direction.e - previous_direction.e,
    };
    double change_squared = 0.0;
    for (const double component : changes) {
        change_squared += component * component;
    }
    const double change_length = std::sqrt(change_squared);
    if (change_length <= MOVEMENT_EPSILON) {
        return maximum_speed;
    }
    const double square_corner = current[SQUARE_CORNER_VELOCITY];
    if (present(square_corner)) {
        if (square_corner <= 0.0) {
            return 0.0;
        }
        return std::min(
            maximum_speed,
            std::sqrt(2.0) * square_corner / change_length
        );
    }
    const std::array<std::size_t, 4> jerk_indices = {
        JERK_X, JERK_Y, JERK_Z, JERK_E,
    };
    double junction_speed = maximum_speed;
    bool found_limit = false;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        if (std::abs(changes[axis]) <= MOVEMENT_EPSILON) {
            continue;
        }
        const double jerk = current[jerk_indices[axis]];
        if (!present(jerk)) {
            continue;
        }
        found_limit = true;
        junction_speed = std::min(
            junction_speed,
            std::max(0.0, jerk) / std::abs(changes[axis])
        );
    }
    return found_limit ? junction_speed : 0.0;
}

double bambu_junction_speed(
    const Row& previous,
    const Row& current,
    const Kinematics& previous_kinematics,
    const Kinematics& current_kinematics
) {
    if (previous_kinematics.target_speed <= MOVEMENT_EPSILON) {
        return current_kinematics.safe_speed;
    }
    const double maximum_speed = std::min(
        previous_kinematics.target_speed,
        current_kinematics.target_speed
    );
    if (!previous_kinematics.direction.valid || !current_kinematics.direction.valid) {
        return current_kinematics.safe_speed;
    }
    if (
        std::abs(previous_kinematics.direction.e) > 0.0
        || std::abs(current_kinematics.direction.e) > 0.0
    ) {
        return maximum_speed;
    }

    const std::array<double, 3> previous_direction = {
        present(previous[EXIT_DIRECTION_X])
            ? previous[EXIT_DIRECTION_X] : previous_kinematics.direction.x,
        present(previous[EXIT_DIRECTION_Y])
            ? previous[EXIT_DIRECTION_Y] : previous_kinematics.direction.y,
        present(previous[EXIT_DIRECTION_Z])
            ? previous[EXIT_DIRECTION_Z] : previous_kinematics.direction.z,
    };
    const std::array<double, 3> current_direction = {
        present(current[ENTRY_DIRECTION_X])
            ? current[ENTRY_DIRECTION_X] : current_kinematics.direction.x,
        present(current[ENTRY_DIRECTION_Y])
            ? current[ENTRY_DIRECTION_Y] : current_kinematics.direction.y,
        present(current[ENTRY_DIRECTION_Z])
            ? current[ENTRY_DIRECTION_Z] : current_kinematics.direction.z,
    };
    const std::array<std::size_t, 3> jerk_indices = {
        JERK_X, JERK_Y, JERK_Z,
    };
    double junction_speed = std::numeric_limits<double>::infinity();
    bool found_limit = false;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double component = current_direction[axis] - previous_direction[axis];
        const double jerk = current[jerk_indices[axis]];
        if (std::abs(component) <= MOVEMENT_EPSILON || !present(jerk)) {
            continue;
        }
        found_limit = true;
        junction_speed = std::min(
            junction_speed,
            std::max(0.0, jerk) / std::abs(component)
        );
    }
    if (!found_limit) {
        return maximum_speed;
    }
    const double threshold = junction_speed * 0.99;
    if (
        previous_kinematics.safe_speed > threshold
        && current_kinematics.safe_speed > threshold
    ) {
        junction_speed = current_kinematics.safe_speed;
    }
    return junction_speed;
}

PlannedValue calculate_timing(
    const Row& movement,
    const double distance,
    const double target_speed,
    double entry_speed,
    double exit_speed,
    const bool bambu
) {
    const bool has_spatial_motion = (
        movement[ENDPOINT_XYZ] > MOVEMENT_EPSILON
        || (
            is_arc(movement)
            && present(movement[PATH_LENGTH])
            && movement[PATH_LENGTH] > MOVEMENT_EPSILON
        )
    );
    const double path_length = (
        bambu && is_arc(movement)
        ? distance
        : movement[PATH_LENGTH]
    );
    const double timing_distance = (
        has_spatial_motion ? path_length : std::abs(movement[DELTA_E])
    );
    const double feedrate = (
        bambu ? target_speed * 60.0 : movement[EFFECTIVE_FEEDRATE]
    );
    const double acceleration = movement[ACCELERATION];
    const double requested_speed = feedrate / 60.0;

    if (bambu) {
        entry_speed = std::max(0.0, entry_speed);
        exit_speed = std::max(0.0, exit_speed);
    } else {
        entry_speed = std::min(std::max(0.0, entry_speed), requested_speed);
        exit_speed = std::min(std::max(0.0, exit_speed), requested_speed);
    }
    const double peak_speed_squared = (
        acceleration * timing_distance
        + (entry_speed * entry_speed + exit_speed * exit_speed) / 2.0
    );
    const double cruise_speed = std::min(
        requested_speed,
        std::sqrt(std::max(0.0, peak_speed_squared))
    );
    const double acceleration_distance = std::max(
        0.0,
        (cruise_speed * cruise_speed - entry_speed * entry_speed)
            / (2.0 * acceleration)
    );
    const double deceleration_distance = std::max(
        0.0,
        (cruise_speed * cruise_speed - exit_speed * exit_speed)
            / (2.0 * acceleration)
    );
    const double constant_distance = std::max(
        0.0,
        timing_distance - acceleration_distance - deceleration_distance
    );
    const double duration = (
        std::max(0.0, cruise_speed - entry_speed) / acceleration
        + std::max(0.0, cruise_speed - exit_speed) / acceleration
        + constant_distance / cruise_speed
    );
    return PlannedValue{
        feedrate,
        timing_distance,
        duration,
        entry_speed,
        cruise_speed,
        exit_speed,
    };
}

std::vector<PlannedValue> calculate_plan(
    const std::vector<Row>& movements,
    const double start_speed,
    const double end_speed,
    const bool bambu,
    const Row* previous_movement
) {
    const std::size_t count = movements.size();
    std::vector<Kinematics> kinematics(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Row* previous = index > 0 ? &movements[index - 1] : previous_movement;
        Kinematics item;
        item.target_speed = (
            bambu
            ? bambu_cruise_feedrate(movements[index], previous)
            : optional_or_zero(movements[index][EFFECTIVE_FEEDRATE]) / 60.0
        );
        item.distance = (
            bambu
            ? bambu_timing_distance(movements[index])
            : optional_or_zero(movements[index][TIMING_DISTANCE])
        );
        item.acceleration = optional_or_zero(movements[index][ACCELERATION]);
        item.direction = movement_direction(movements[index]);
        if (bambu) {
            item.safe_speed = bambu_safe_feedrate(
                movements[index], item.target_speed
            );
        }
        kinematics[index] = item;
    }

    std::vector<double> boundaries(count + 1, 0.0);
    if (bambu) {
        std::vector<double> maximum_entries(count, 0.0);
        std::vector<bool> nominal_length(count, false);
        for (std::size_t index = 0; index < count; ++index) {
            const double maximum_entry = (
                index == 0
                ? (
                    start_speed > MOVEMENT_EPSILON
                    ? start_speed : kinematics[index].safe_speed
                )
                : bambu_junction_speed(
                    movements[index - 1],
                    movements[index],
                    kinematics[index - 1],
                    kinematics[index]
                )
            );
            const double allowable_entry = std::sqrt(std::max(
                0.0,
                kinematics[index].safe_speed * kinematics[index].safe_speed
                    + 2.0 * kinematics[index].acceleration * kinematics[index].distance
            ));
            maximum_entries[index] = maximum_entry;
            boundaries[index] = std::min(maximum_entry, allowable_entry);
            nominal_length[index] = kinematics[index].target_speed <= allowable_entry;
        }
        boundaries[count] = kinematics.back().safe_speed;

        for (std::size_t index = 0; index + 1 < count; ++index) {
            if (!nominal_length[index] && boundaries[index] < boundaries[index + 1]) {
                boundaries[index + 1] = std::min(
                    boundaries[index + 1],
                    std::sqrt(std::max(
                        0.0,
                        boundaries[index] * boundaries[index]
                            + 2.0 * kinematics[index].acceleration
                            * kinematics[index].distance
                    ))
                );
            }
        }
        for (std::size_t reverse = count; reverse-- > 0;) {
            const std::size_t index = reverse;
            const double maximum_entry = maximum_entries[index];
            if (boundaries[index] == maximum_entry) {
                continue;
            }
            if (
                !nominal_length[index]
                && maximum_entry > boundaries[index + 1]
            ) {
                boundaries[index] = std::min(
                    maximum_entry,
                    std::sqrt(std::max(
                        0.0,
                        boundaries[index + 1] * boundaries[index + 1]
                            + 2.0 * kinematics[index].acceleration
                            * kinematics[index].distance
                    ))
                );
            } else {
                boundaries[index] = maximum_entry;
            }
        }
    } else {
        boundaries[0] = std::min(
            std::max(0.0, start_speed), kinematics[0].target_speed
        );
        boundaries[count] = std::min(
            std::max(0.0, end_speed), kinematics[count - 1].target_speed
        );
        for (std::size_t index = 1; index < count; ++index) {
            boundaries[index] = generic_junction_speed(
                movements[index - 1], movements[index]
            );
        }
        for (std::size_t reverse = count; reverse-- > 0;) {
            const std::size_t index = reverse;
            const double maximum_entry = std::sqrt(std::max(
                0.0,
                boundaries[index + 1] * boundaries[index + 1]
                    + 2.0 * kinematics[index].acceleration
                    * kinematics[index].distance
            ));
            boundaries[index] = std::min({
                boundaries[index],
                kinematics[index].target_speed,
                maximum_entry,
            });
        }
        for (std::size_t index = 0; index < count; ++index) {
            const double maximum_exit = std::sqrt(std::max(
                0.0,
                boundaries[index] * boundaries[index]
                    + 2.0 * kinematics[index].acceleration
                    * kinematics[index].distance
            ));
            boundaries[index + 1] = std::min({
                boundaries[index + 1],
                kinematics[index].target_speed,
                maximum_exit,
            });
        }
    }

    std::vector<PlannedValue> planned;
    planned.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        planned.push_back(calculate_timing(
            movements[index],
            kinematics[index].distance,
            kinematics[index].target_speed,
            boundaries[index],
            boundaries[index + 1],
            bambu
        ));
    }
    return planned;
}

bool parse_row(PyObject* source, Row& destination) {
    PyObject* fast = PySequence_Fast(source, "Each native movement row must be a sequence.");
    if (fast == nullptr) {
        return false;
    }
    if (PySequence_Fast_GET_SIZE(fast) != static_cast<Py_ssize_t>(ROW_WIDTH)) {
        Py_DECREF(fast);
        PyErr_Format(
            PyExc_ValueError,
            "Native movement rows require exactly %zu values.",
            ROW_WIDTH
        );
        return false;
    }
    PyObject** items = PySequence_Fast_ITEMS(fast);
    for (std::size_t index = 0; index < ROW_WIDTH; ++index) {
        destination[index] = PyFloat_AsDouble(items[index]);
        if (PyErr_Occurred()) {
            Py_DECREF(fast);
            return false;
        }
    }
    Py_DECREF(fast);
    return true;
}

std::vector<std::uint64_t> make_cache_key(
    const std::vector<Row>& rows,
    const double start_speed,
    const double end_speed,
    const bool bambu,
    const Row* previous
) {
    std::vector<std::uint64_t> key;
    key.reserve(6 + rows.size() * ROW_WIDTH + (previous ? ROW_WIDTH : 0));
    key.push_back(ENGINE_VERSION);
    key.push_back(bambu ? 1ULL : 0ULL);
    key.push_back(double_bits(start_speed));
    key.push_back(double_bits(end_speed));
    key.push_back(previous ? 1ULL : 0ULL);
    if (previous != nullptr) {
        for (const double value : *previous) {
            key.push_back(double_bits(value));
        }
    }
    key.push_back(static_cast<std::uint64_t>(rows.size()));
    for (const Row& row : rows) {
        for (const double value : row) {
            key.push_back(double_bits(value));
        }
    }
    return key;
}

void evict_if_needed() {
    while (cache_bytes > maximum_cache_bytes && !cache_order.empty()) {
        std::vector<std::uint64_t> oldest = std::move(cache_order.front());
        cache_order.pop_front();
        const auto found = block_cache.find(oldest);
        if (found == block_cache.end()) {
            continue;
        }
        cache_bytes -= found->second.bytes;
        block_cache.erase(found);
        ++cache_evictions;
    }
}

std::pair<std::vector<PlannedValue>, bool> cached_plan(
    const std::vector<Row>& rows,
    const double start_speed,
    const double end_speed,
    const bool bambu,
    const Row* previous
) {
    std::vector<std::uint64_t> key = make_cache_key(
        rows, start_speed, end_speed, bambu, previous
    );
    std::lock_guard<std::mutex> lock(cache_mutex);
    const auto found = block_cache.find(key);
    if (found != block_cache.end()) {
        ++cache_hits;
        return {found->second.values, true};
    }
    ++cache_misses;
    std::vector<PlannedValue> values = calculate_plan(
        rows, start_speed, end_speed, bambu, previous
    );
    const std::size_t bytes = (
        key.size() * sizeof(std::uint64_t)
        + values.size() * sizeof(PlannedValue)
    );
    if (bytes <= maximum_cache_bytes) {
        cache_order.push_back(key);
        block_cache.emplace(
            std::move(key),
            CacheEntry{values, bytes}
        );
        cache_bytes += bytes;
        evict_if_needed();
    }
    return {std::move(values), false};
}

PyObject* py_plan_block(PyObject*, PyObject* arguments) {
    PyObject* rows_object = nullptr;
    PyObject* previous_object = Py_None;
    double start_speed = 0.0;
    double end_speed = 0.0;
    int bambu = 0;
    if (!PyArg_ParseTuple(
        arguments,
        "Oddp|O:plan_block",
        &rows_object,
        &start_speed,
        &end_speed,
        &bambu,
        &previous_object
    )) {
        return nullptr;
    }

    PyObject* fast_rows = PySequence_Fast(
        rows_object, "Native movement input must be a sequence."
    );
    if (fast_rows == nullptr) {
        return nullptr;
    }
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(fast_rows);
    if (count <= 0) {
        Py_DECREF(fast_rows);
        return Py_BuildValue("(NN)", PyTuple_New(0), PyBool_FromLong(0));
    }
    std::vector<Row> rows(static_cast<std::size_t>(count));
    PyObject** items = PySequence_Fast_ITEMS(fast_rows);
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (!parse_row(items[index], rows[static_cast<std::size_t>(index)])) {
            Py_DECREF(fast_rows);
            return nullptr;
        }
    }
    Py_DECREF(fast_rows);

    Row previous{};
    Row* previous_pointer = nullptr;
    if (previous_object != Py_None) {
        if (!parse_row(previous_object, previous)) {
            return nullptr;
        }
        previous_pointer = &previous;
    }

    std::pair<std::vector<PlannedValue>, bool> result;
    PyThreadState* saved_thread = PyEval_SaveThread();
    try {
        result = cached_plan(
            rows,
            start_speed,
            end_speed,
            bambu != 0,
            previous_pointer
        );
    } catch (const std::exception& error) {
        PyEval_RestoreThread(saved_thread);
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    } catch (...) {
        PyEval_RestoreThread(saved_thread);
        PyErr_SetString(PyExc_RuntimeError, "Unknown native timing failure.");
        return nullptr;
    }
    PyEval_RestoreThread(saved_thread);

    PyObject* values = PyTuple_New(static_cast<Py_ssize_t>(result.first.size()));
    if (values == nullptr) {
        return nullptr;
    }
    for (std::size_t index = 0; index < result.first.size(); ++index) {
        const PlannedValue& item = result.first[index];
        PyObject* row = Py_BuildValue(
            "(dddddd)",
            item.effective_feedrate,
            item.timing_distance,
            item.duration,
            item.entry_speed,
            item.cruise_speed,
            item.exit_speed
        );
        if (row == nullptr) {
            Py_DECREF(values);
            return nullptr;
        }
        PyTuple_SET_ITEM(values, static_cast<Py_ssize_t>(index), row);
    }
    PyObject* response = PyTuple_New(2);
    if (response == nullptr) {
        Py_DECREF(values);
        return nullptr;
    }
    PyTuple_SET_ITEM(response, 0, values);
    PyObject* hit = result.second ? Py_True : Py_False;
    Py_INCREF(hit);
    PyTuple_SET_ITEM(response, 1, hit);
    return response;
}

PyObject* py_parse_common_lines(PyObject*, PyObject* arguments) {
    PyObject* lines_object = nullptr;
    if (!PyArg_ParseTuple(arguments, "O:parse_common_lines", &lines_object)) {
        return nullptr;
    }
    PyObject* fast_lines = PySequence_Fast(
        lines_object, "Native line input must be a sequence."
    );
    if (fast_lines == nullptr) {
        return nullptr;
    }
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(fast_lines);
    PyObject* output = PyTuple_New(count);
    if (output == nullptr) {
        Py_DECREF(fast_lines);
        return nullptr;
    }
    PyObject** items = PySequence_Fast_ITEMS(fast_lines);
    for (Py_ssize_t index = 0; index < count; ++index) {
        Py_ssize_t text_size = 0;
        const char* text = PyUnicode_AsUTF8AndSize(items[index], &text_size);
        if (text == nullptr) {
            Py_DECREF(output);
            Py_DECREF(fast_lines);
            return nullptr;
        }
        CommonLine parsed;
        if (!parse_common_line(
            std::string(text, static_cast<std::size_t>(text_size)), parsed
        )) {
            Py_INCREF(Py_None);
            PyTuple_SET_ITEM(output, index, Py_None);
            continue;
        }
        PyObject* parameters = PyDict_New();
        if (parameters == nullptr) {
            Py_DECREF(output);
            Py_DECREF(fast_lines);
            return nullptr;
        }
        bool parameter_error = false;
        for (const auto& parameter : parsed.parameters) {
            PyObject* value = PyFloat_FromDouble(parameter.second);
            if (
                value == nullptr
                || PyDict_SetItemString(parameters, parameter.first.c_str(), value) < 0
            ) {
                Py_XDECREF(value);
                parameter_error = true;
                break;
            }
            Py_DECREF(value);
        }
        if (parameter_error) {
            Py_DECREF(parameters);
            Py_DECREF(output);
            Py_DECREF(fast_lines);
            return nullptr;
        }
        PyObject* code = PyUnicode_FromStringAndSize(
            parsed.code.data(), static_cast<Py_ssize_t>(parsed.code.size())
        );
        PyObject* command = parsed.has_command
            ? PyUnicode_FromStringAndSize(
                parsed.command.data(),
                static_cast<Py_ssize_t>(parsed.command.size())
            )
            : Py_NewRef(Py_None);
        PyObject* comment = parsed.has_comment
            ? PyUnicode_FromStringAndSize(
                parsed.comment.data(),
                static_cast<Py_ssize_t>(parsed.comment.size())
            )
            : Py_NewRef(Py_None);
        PyObject* unparsed = parsed.has_unparsed
            ? PyUnicode_FromStringAndSize(
                parsed.unparsed.data(),
                static_cast<Py_ssize_t>(parsed.unparsed.size())
            )
            : Py_NewRef(Py_None);
        if (
            code == nullptr || command == nullptr
            || comment == nullptr || unparsed == nullptr
        ) {
            Py_XDECREF(code);
            Py_XDECREF(command);
            Py_DECREF(parameters);
            Py_XDECREF(comment);
            Py_XDECREF(unparsed);
            Py_DECREF(output);
            Py_DECREF(fast_lines);
            return nullptr;
        }
        PyObject* row = PyTuple_New(5);
        if (row == nullptr) {
            Py_DECREF(code);
            Py_DECREF(command);
            Py_DECREF(parameters);
            Py_DECREF(comment);
            Py_DECREF(unparsed);
            Py_DECREF(output);
            Py_DECREF(fast_lines);
            return nullptr;
        }
        PyTuple_SET_ITEM(row, 0, code);
        PyTuple_SET_ITEM(row, 1, command);
        PyTuple_SET_ITEM(row, 2, parameters);
        PyTuple_SET_ITEM(row, 3, comment);
        PyTuple_SET_ITEM(row, 4, unparsed);
        PyTuple_SET_ITEM(output, index, row);
    }
    Py_DECREF(fast_lines);
    return output;
}

PyObject* py_cache_info(PyObject*, PyObject*) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    return Py_BuildValue(
        "{sKsKsKsKsK}",
        "hits", cache_hits,
        "misses", cache_misses,
        "entries", static_cast<unsigned long long>(block_cache.size()),
        "bytes", static_cast<unsigned long long>(cache_bytes),
        "evictions", cache_evictions
    );
}

PyObject* py_clear_cache(PyObject*, PyObject*) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    block_cache.clear();
    cache_order.clear();
    cache_bytes = 0;
    cache_hits = 0;
    cache_misses = 0;
    cache_evictions = 0;
    Py_RETURN_NONE;
}

PyObject* py_set_cache_limit(PyObject*, PyObject* arguments) {
    unsigned long long requested = 0;
    if (!PyArg_ParseTuple(arguments, "K:set_cache_limit", &requested)) {
        return nullptr;
    }
    if (requested < 1024ULL * 1024ULL) {
        PyErr_SetString(PyExc_ValueError, "Native block cache limit must be at least 1 MiB.");
        return nullptr;
    }
    std::lock_guard<std::mutex> lock(cache_mutex);
    maximum_cache_bytes = static_cast<std::size_t>(requested);
    evict_if_needed();
    Py_RETURN_NONE;
}

bool dict_set_owned(PyObject* dictionary, const char* key, PyObject* value) {
    if (value == nullptr) {
        return false;
    }
    const int status = PyDict_SetItemString(dictionary, key, value);
    Py_DECREF(value);
    return status == 0;
}

PyObject* unicode_from_utf8(const std::string& value) {
    return PyUnicode_DecodeUTF8(
        value.data(),
        static_cast<Py_ssize_t>(value.size()),
        "replace"
    );
}

PyObject* native_layer_to_dict(
    const cooling_tower::native_analysis::LayerResult& layer
) {
    PyObject* result = PyDict_New();
    if (result == nullptr) {
        return nullptr;
    }
    const std::array<std::pair<const char*, long long>, 8> integers = {{
        {"index", layer.index},
        {"start_line", layer.start_line},
        {"first_deposition_line", layer.first_deposition_line},
        {"end_line", layer.end_line},
        {"event_count", layer.event_count},
        {"movement_count", layer.movement_count},
        {"deposition_count", layer.deposition_count},
        {"untimed_event_count", layer.untimed_event_count},
    }};
    for (const auto& item : integers) {
        if (!dict_set_owned(result, item.first, PyLong_FromLongLong(item.second))) {
            Py_DECREF(result);
            return nullptr;
        }
    }
    const std::array<std::pair<const char*, double>, 12> doubles = {{
        {"z_mm", layer.z_mm},
        {"height_mm", layer.height_mm},
        {"total_time_s", layer.total_time_s},
        {"deposition_time_s", layer.deposition_time_s},
        {"travel_time_s", layer.travel_time_s},
        {"retraction_time_s", layer.retraction_time_s},
        {"unretraction_time_s", layer.unretraction_time_s},
        {"dwell_time_s", layer.dwell_time_s},
        {"other_time_s", layer.other_time_s},
        {"deposition_path_mm", layer.deposition_path_mm},
        {"deposition_e_mm", layer.deposition_e_mm},
        {"untimed_distance_mm", layer.untimed_distance_mm},
    }};
    for (const auto& item : doubles) {
        if (!dict_set_owned(result, item.first, PyFloat_FromDouble(item.second))) {
            Py_DECREF(result);
            return nullptr;
        }
    }
    return result;
}

PyObject* native_metadata_to_tuple(
    const std::vector<cooling_tower::native_analysis::MetadataEvent>& events
) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(events.size()));
    if (result == nullptr) {
        return nullptr;
    }
    for (std::size_t index = 0; index < events.size(); ++index) {
        const auto& event = events[index];
        PyObject* parameters = PyDict_New();
        if (parameters == nullptr) {
            Py_DECREF(result);
            return nullptr;
        }
        for (const auto& item : event.parameters) {
            PyObject* value = PyFloat_FromDouble(item.second);
            if (
                value == nullptr
                || PyDict_SetItemString(parameters, item.first.c_str(), value) < 0
            ) {
                Py_XDECREF(value);
                Py_DECREF(parameters);
                Py_DECREF(result);
                return nullptr;
            }
            Py_DECREF(value);
        }
        PyObject* row = PyTuple_New(4);
        PyObject* command = event.has_command
            ? unicode_from_utf8(event.command) : Py_NewRef(Py_None);
        PyObject* comment = event.has_comment
            ? unicode_from_utf8(event.comment) : Py_NewRef(Py_None);
        if (row == nullptr || command == nullptr || comment == nullptr) {
            Py_XDECREF(row);
            Py_XDECREF(command);
            Py_DECREF(parameters);
            Py_XDECREF(comment);
            Py_DECREF(result);
            return nullptr;
        }
        PyTuple_SET_ITEM(row, 0, PyLong_FromLongLong(event.line_number));
        PyTuple_SET_ITEM(row, 1, command);
        PyTuple_SET_ITEM(row, 2, parameters);
        PyTuple_SET_ITEM(row, 3, comment);
        PyTuple_SET_ITEM(result, static_cast<Py_ssize_t>(index), row);
    }
    return result;
}

PyObject* native_preview_to_tuple(
    const std::vector<cooling_tower::native_analysis::PreviewSegment>& segments
) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(segments.size()));
    if (result == nullptr) {
        return nullptr;
    }
    for (std::size_t index = 0; index < segments.size(); ++index) {
        const auto& item = segments[index];
        PyObject* row = Py_BuildValue(
            "(dddddd)",
            item.start_x, item.start_y, item.start_z,
            item.end_x, item.end_y, item.end_z
        );
        if (row == nullptr) {
            Py_DECREF(result);
            return nullptr;
        }
        PyTuple_SET_ITEM(result, static_cast<Py_ssize_t>(index), row);
    }
    return result;
}

PyObject* native_infill_to_dict(
    const cooling_tower::native_analysis::InfillEvidence& infill
) {
    PyObject* result = PyDict_New();
    PyObject* label_bounds = PyDict_New();
    PyObject* sparse_labels = PyTuple_New(
        static_cast<Py_ssize_t>(infill.sparse_labels.size())
    );
    if (result == nullptr || label_bounds == nullptr || sparse_labels == nullptr) {
        Py_XDECREF(result);
        Py_XDECREF(label_bounds);
        Py_XDECREF(sparse_labels);
        return nullptr;
    }
    for (const auto& item : infill.label_bounds) {
        PyObject* key = PyLong_FromLongLong(item.first);
        PyObject* bounds = PyTuple_New(static_cast<Py_ssize_t>(item.second.size()));
        if (key == nullptr || bounds == nullptr) {
            Py_XDECREF(key);
            Py_XDECREF(bounds);
            Py_DECREF(result);
            Py_DECREF(label_bounds);
            Py_DECREF(sparse_labels);
            return nullptr;
        }
        for (std::size_t index = 0; index < item.second.size(); ++index) {
            PyTuple_SET_ITEM(
                bounds,
                static_cast<Py_ssize_t>(index),
                PyFloat_FromDouble(item.second[index])
            );
        }
        if (PyDict_SetItem(label_bounds, key, bounds) < 0) {
            Py_DECREF(key);
            Py_DECREF(bounds);
            Py_DECREF(result);
            Py_DECREF(label_bounds);
            Py_DECREF(sparse_labels);
            return nullptr;
        }
        Py_DECREF(key);
        Py_DECREF(bounds);
    }
    for (std::size_t index = 0; index < infill.sparse_labels.size(); ++index) {
        PyTuple_SET_ITEM(
            sparse_labels,
            static_cast<Py_ssize_t>(index),
            PyLong_FromLongLong(infill.sparse_labels[index])
        );
    }
    if (
        !dict_set_owned(
            result,
            "tower_block_count",
            PyLong_FromLongLong(infill.tower_block_count)
        )
        || !dict_set_owned(
            result,
            "sparse_tower_infill",
            PyBool_FromLong(infill.sparse_tower_infill ? 1 : 0)
        )
        || PyDict_SetItemString(result, "label_bounds", label_bounds) < 0
        || PyDict_SetItemString(result, "sparse_labels", sparse_labels) < 0
    ) {
        Py_DECREF(result);
        Py_DECREF(label_bounds);
        Py_DECREF(sparse_labels);
        return nullptr;
    }
    Py_DECREF(label_bounds);
    Py_DECREF(sparse_labels);
    return result;
}

PyObject* native_diagnostics_to_dict(
    const cooling_tower::native_analysis::Diagnostics& diagnostics
) {
    return Py_BuildValue(
        "{sKsKsKsKsKsKsKsKsK}",
        "bytes_read", diagnostics.bytes_read,
        "line_count", diagnostics.line_count,
        "movement_count", diagnostics.movement_count,
        "dwell_count", diagnostics.dwell_count,
        "metadata_event_count", diagnostics.metadata_event_count,
        "planner_flush_count", diagnostics.planner_flush_count,
        "peak_pending_movements", diagnostics.peak_pending_movements,
        "preview_candidate_count", diagnostics.preview_candidate_count,
        "anycubic_startup_macro_count",
        diagnostics.anycubic_startup_macro_count
    );
}

PyObject* native_result_to_dict(
    const cooling_tower::native_analysis::Result& source
) {
    PyObject* result = PyDict_New();
    PyObject* layers = PyTuple_New(static_cast<Py_ssize_t>(source.layers.size()));
    if (result == nullptr || layers == nullptr) {
        Py_XDECREF(result);
        Py_XDECREF(layers);
        return nullptr;
    }
    for (std::size_t index = 0; index < source.layers.size(); ++index) {
        PyObject* layer = native_layer_to_dict(source.layers[index]);
        if (layer == nullptr) {
            Py_DECREF(result);
            Py_DECREF(layers);
            return nullptr;
        }
        PyTuple_SET_ITEM(layers, static_cast<Py_ssize_t>(index), layer);
    }
    PyObject* bounds = source.has_occupied_bounds
        ? Py_BuildValue(
            "(dddd)",
            source.minimum_x,
            source.maximum_x,
            source.minimum_y,
            source.maximum_y
        )
        : Py_NewRef(Py_None);
    PyObject* metadata = native_metadata_to_tuple(source.metadata_events);
    PyObject* preview = native_preview_to_tuple(source.preview_segments);
    PyObject* infill = native_infill_to_dict(source.infill);
    PyObject* diagnostics = native_diagnostics_to_dict(source.diagnostics);
    if (
        bounds == nullptr || metadata == nullptr || preview == nullptr
        || infill == nullptr || diagnostics == nullptr
    ) {
        Py_DECREF(result);
        Py_DECREF(layers);
        Py_XDECREF(bounds);
        Py_XDECREF(metadata);
        Py_XDECREF(preview);
        Py_XDECREF(infill);
        Py_XDECREF(diagnostics);
        return nullptr;
    }
    const bool ok =
        dict_set_owned(
            result,
            "status",
            PyUnicode_FromString(
                cooling_tower::native_analysis::status_name(source.status)
            )
        )
        && dict_set_owned(result, "message", unicode_from_utf8(source.message))
        && dict_set_owned(
            result, "fallback_line", PyLong_FromLongLong(source.fallback_line)
        )
        && dict_set_owned(
            result,
            "fallback_command",
            unicode_from_utf8(source.fallback_command)
        )
        && PyDict_SetItemString(result, "layers", layers) == 0
        && dict_set_owned(
            result,
            "confirmed_layer_changes",
            PyLong_FromLongLong(source.confirmed_layer_changes)
        )
        && dict_set_owned(
            result,
            "rejected_z_candidates",
            PyLong_FromLongLong(source.rejected_z_candidates)
        )
        && dict_set_owned(
            result,
            "pre_layer_event_count",
            PyLong_FromLongLong(source.pre_layer_event_count)
        )
        && dict_set_owned(
            result,
            "pre_layer_time_s",
            PyFloat_FromDouble(source.pre_layer_time_s)
        )
        && dict_set_owned(
            result,
            "pre_layer_untimed_event_count",
            PyLong_FromLongLong(source.pre_layer_untimed_event_count)
        )
        && PyDict_SetItemString(result, "metadata_events", metadata) == 0
        && PyDict_SetItemString(result, "preview_segments", preview) == 0
        && dict_set_owned(
            result,
            "preview_source_segment_count",
            PyLong_FromUnsignedLongLong(source.preview_source_segment_count)
        )
        && PyDict_SetItemString(result, "occupied_bounds", bounds) == 0
        && PyDict_SetItemString(result, "infill", infill) == 0
        && PyDict_SetItemString(result, "diagnostics", diagnostics) == 0;
    Py_DECREF(layers);
    Py_DECREF(bounds);
    Py_DECREF(metadata);
    Py_DECREF(preview);
    Py_DECREF(infill);
    Py_DECREF(diagnostics);
    if (!ok) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* py_analyze_file(PyObject*, PyObject* arguments) {
    PyObject* path_object = nullptr;
    PyObject* cancellation = Py_None;
    PyObject* orca_policy = Py_None;
    int bambu = 0;
    int anycubic_slicer_next = 0;
    int explicit_layers = 0;
    int collect_preview = 0;
    int collect_infill = 0;
    Py_ssize_t maximum_preview_segments = 60000;
    if (!PyArg_ParseTuple(
        arguments,
        "Opppppn|OO:analyze_file",
        &path_object,
        &bambu,
        &anycubic_slicer_next,
        &explicit_layers,
        &collect_preview,
        &collect_infill,
        &maximum_preview_segments,
        &cancellation,
        &orca_policy
    )) {
        return nullptr;
    }
    if (!PyUnicode_Check(path_object)) {
        PyErr_SetString(PyExc_TypeError, "Native analysis path must be text.");
        return nullptr;
    }
    if (cancellation != Py_None && !PyCallable_Check(cancellation)) {
        PyErr_SetString(PyExc_TypeError, "Cancellation callback must be callable.");
        return nullptr;
    }
    if (maximum_preview_segments < 100) {
        PyErr_SetString(PyExc_ValueError, "maximum_preview_segments must be at least 100.");
        return nullptr;
    }

    std::filesystem::path path;
#ifdef _WIN32
    Py_ssize_t wide_size = 0;
    wchar_t* wide_path = PyUnicode_AsWideCharString(path_object, &wide_size);
    if (wide_path == nullptr) {
        return nullptr;
    }
    path = std::filesystem::path(wide_path, wide_path + wide_size);
    PyMem_Free(wide_path);
#else
    PyObject* encoded_path = PyUnicode_EncodeFSDefault(path_object);
    if (encoded_path == nullptr) {
        return nullptr;
    }
    path = std::filesystem::path(
        PyBytes_AS_STRING(encoded_path),
        PyBytes_AS_STRING(encoded_path) + PyBytes_GET_SIZE(encoded_path)
    );
    Py_DECREF(encoded_path);
#endif

    cooling_tower::native_analysis::Options options;
    if (orca_policy != Py_None) {
        if (!PyDict_Check(orca_policy)) {
            PyErr_SetString(PyExc_TypeError, "Orca timing policy must be a dictionary.");
            return nullptr;
        }
        options.orca_compatible = true;
        PyObject* producer = PyDict_GetItemString(orca_policy, "producer");
        if (producer && PyUnicode_Check(producer) && PyUnicode_CompareWithASCIIString(producer, "prusa") == 0) {
            options.orca_compatible = false;
            options.prusa_compatible = true;
        }
        PyObject* flavor = PyDict_GetItemString(orca_policy, "marlin2");
        options.orca_marlin2 = flavor == Py_True;
        PyObject* limits = PyDict_GetItemString(orca_policy, "limits");
        if (!limits || !PyDict_Check(limits)) {
            PyErr_SetString(PyExc_TypeError, "Orca machine limits must be a dictionary.");
            return nullptr;
        }
        PyObject *key, *value; Py_ssize_t position = 0;
        while (PyDict_Next(limits, &position, &key, &value)) {
            if (!PyUnicode_Check(key)) { PyErr_SetString(PyExc_TypeError, "Machine limit names must be text."); return nullptr; }
            const char* name = PyUnicode_AsUTF8(key);
            const double number = PyFloat_AsDouble(value);
            if (!name || PyErr_Occurred()) return nullptr;
            if (!std::isfinite(number) || number < 0.0) { PyErr_SetString(PyExc_ValueError, "Invalid Orca machine limit."); return nullptr; }
            options.orca_limits[name] = number;
        }
    }
    options.bambu_compatible = bambu != 0;
    options.anycubic_slicer_next_compatible = anycubic_slicer_next != 0;
    options.use_explicit_layer_markers = explicit_layers != 0;
    options.collect_preview = collect_preview != 0;
    options.collect_infill_evidence = collect_infill != 0;
    options.maximum_preview_segments = static_cast<std::size_t>(
        maximum_preview_segments
    );
    bool callback_failed = false;
    PyObject* callback_type = nullptr;
    PyObject* callback_value = nullptr;
    PyObject* callback_traceback = nullptr;
    if (cancellation != Py_None) {
        options.should_cancel = [
            cancellation,
            &callback_failed,
            &callback_type,
            &callback_value,
            &callback_traceback
        ](std::uint64_t, std::uint64_t) {
            const PyGILState_STATE state = PyGILState_Ensure();
            PyObject* value = PyObject_CallNoArgs(cancellation);
            bool cancelled = false;
            if (value == nullptr) {
                callback_failed = true;
                PyErr_Fetch(
                    &callback_type,
                    &callback_value,
                    &callback_traceback
                );
                cancelled = true;
            } else {
                const int truth = PyObject_IsTrue(value);
                Py_DECREF(value);
                if (truth < 0) {
                    callback_failed = true;
                    PyErr_Fetch(
                        &callback_type,
                        &callback_value,
                        &callback_traceback
                    );
                    cancelled = true;
                } else {
                    cancelled = truth != 0;
                }
            }
            PyGILState_Release(state);
            return cancelled;
        };
    }

    cooling_tower::native_analysis::Result result;
    PyThreadState* saved_thread = PyEval_SaveThread();
    try {
        result = cooling_tower::native_analysis::analyze_file(path, options);
    } catch (const std::exception& error) {
        PyEval_RestoreThread(saved_thread);
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    } catch (...) {
        PyEval_RestoreThread(saved_thread);
        PyErr_SetString(PyExc_RuntimeError, "Unknown native analysis failure.");
        return nullptr;
    }
    PyEval_RestoreThread(saved_thread);
    if (callback_failed) {
        PyErr_Restore(callback_type, callback_value, callback_traceback);
        return nullptr;
    }
    return native_result_to_dict(result);
}

PyMethodDef module_methods[] = {
    {"analyze_file", py_analyze_file, METH_VARARGS, "Stream and aggregate one complete G-code file."},
    {"plan_block", py_plan_block, METH_VARARGS, "Plan one exact movement block."},
    {"parse_common_lines", py_parse_common_lines, METH_VARARGS, "Parse common slicer G-code lines."},
    {"cache_info", py_cache_info, METH_NOARGS, "Return native block-cache statistics."},
    {"clear_cache", py_clear_cache, METH_NOARGS, "Clear the native block cache."},
    {"set_cache_limit", py_set_cache_limit, METH_VARARGS, "Set the native cache memory bound."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module_definition = {
    PyModuleDef_HEAD_INIT,
    "_native_timing",
    "Exact native motion-timing planner for Sacrificial Tower.",
    -1,
    module_methods,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_timing() {
    PyObject* module = PyModule_Create(&module_definition);
    if (module == nullptr) {
        return nullptr;
    }
    if (PyModule_AddIntConstant(
        module,
        "ENGINE_VERSION",
        static_cast<long>(ENGINE_VERSION)
    ) < 0) {
        Py_DECREF(module);
        return nullptr;
    }
    return module;
}
