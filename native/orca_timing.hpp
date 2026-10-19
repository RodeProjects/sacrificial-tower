#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace cooling_tower::orca_timing {

inline double junction_speed(
    const std::array<double, 4>& exiting, const std::array<double, 4>& entering,
    const std::array<double, 4>& limits, const double shared,
    const double previous_safe, const double current_safe
) {
    std::array<double, 3> changes{};
    for (std::size_t axis = 0; axis < 3; ++axis) changes[axis] = std::abs(exiting[axis] - entering[axis]);
    double factor = 1.0;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (std::isfinite(limits[axis]) && changes[axis] > limits[axis]) {
            factor *= limits[axis] / changes[axis];
            for (double& change : changes) change *= factor;
        }
    }
    const double before = exiting[3] * factor, after = entering[3] * factor;
    const double e_change = before * after > 0.0 ? std::abs(before-after) : std::max(std::abs(before), std::abs(after));
    if (std::isfinite(limits[3]) && e_change > limits[3]) factor *= limits[3] / e_change;
    const double speed = shared * factor;
    return std::min(previous_safe, current_safe) > 0.99 * speed ? current_safe : speed;
}

}  // namespace cooling_tower::orca_timing
