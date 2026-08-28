#include "native_analysis.hpp"

#include <filesystem>
#include <fstream>

int main() {
    const std::filesystem::path source =
        std::filesystem::temp_directory_path() / "cooling_tower_native_smoke.gcode";
    {
        std::ofstream output(source, std::ios::binary);
        output << "M83\nG90\nM204 S1000\n;LAYER:0\n"
               << "G1 Z0.2 F900\nG1 X10 E0.2 F1200\n";
    }
    cooling_tower::native_analysis::Options options;
    const auto result = cooling_tower::native_analysis::analyze_file(source, options);
    std::error_code ignored;
    std::filesystem::remove(source, ignored);
    if (result.status != cooling_tower::native_analysis::Status::success) {
        return 1;
    }
    if (result.layers.size() != 1 || result.layers.front().deposition_count != 1) {
        return 2;
    }
    return 0;
}
