#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace cooling_tower::prusa_timing {

// Independent geometric policy: the junction vector includes the extruder,
// while its acceleration is bounded by each physical machine axis.
inline double junction_speed(
    const std::array<double, 4>& before,
    const std::array<double, 4>& after,
    const std::array<double, 4>& acceleration_caps,
    const std::array<double, 4>& jerks,
    double acceleration, const double deviation, const double distance,
    const double previous_speed, const double current_speed,
    const double previous_safe, const double current_safe
) {
    if (std::min(previous_speed, current_speed) <= 1e-9) return current_safe;
    if (deviation > 0) {
        double cosine = 0.0, magnitude_squared = 0.0;
        std::array<double, 4> change;
        for (std::size_t axis = 0; axis < 4; ++axis) {
            cosine -= before[axis] * after[axis];
            change[axis] = after[axis] - before[axis];
            magnitude_squared += change[axis] * change[axis];
        }
        if (cosine > .999999) return 0.0;
        cosine = std::max(-.999999, cosine);
        const double magnitude = std::sqrt(magnitude_squared);
        if (magnitude > 1e-9) {
            for (std::size_t axis = 0; axis < 4; ++axis) {
                const double cap = acceleration_caps[axis];
                if (std::isfinite(cap) && cap > 0 && std::abs(change[axis]) > 1e-9)
                    acceleration = std::min(acceleration, cap * magnitude / std::abs(change[axis]));
            }
        }
        const double half_sine = std::sqrt((1-cosine) / 2);
        double squared = acceleration * deviation * half_sine / (1-half_sine);
        if (distance < 1 && cosine < -std::sqrt(.5))
            squared = std::min(squared, distance * acceleration / std::max(.033, std::acos(-cosine)));
        return std::sqrt(std::max(0.0, std::min({squared, previous_speed*previous_speed, current_speed*current_speed})));
    }
    const double shared = std::min(previous_speed, current_speed);
    double factor = 1.0;
    for (std::size_t axis = 0; axis < 4; ++axis) {
        const double a = before[axis] * shared * factor;
        const double b = after[axis] * current_speed * factor;
        const double change = a*b > 0 ? std::abs(a-b) : std::max(std::abs(a), std::abs(b));
        if (std::isfinite(jerks[axis]) && change > jerks[axis]) factor *= jerks[axis] / change;
    }
    const double speed = shared * factor;
    return std::min(previous_safe, current_safe) > speed*.99 ? current_safe : speed;
}

} // namespace cooling_tower::prusa_timing
