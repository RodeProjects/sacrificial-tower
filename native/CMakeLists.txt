cmake_minimum_required(VERSION 3.16)
project(cooling_tower_native_analysis LANGUAGES CXX)

add_library(cooling_tower_native_analysis STATIC native_analysis.cpp)
target_include_directories(cooling_tower_native_analysis PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(cooling_tower_native_analysis PUBLIC cxx_std_17)

if(MSVC)
    target_compile_options(cooling_tower_native_analysis PRIVATE /O2 /EHsc /fp:strict)
else()
    target_compile_options(cooling_tower_native_analysis PRIVATE -O2 -fno-fast-math)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(native_analysis_smoke tests/native_analysis_smoke.cpp)
    target_link_libraries(native_analysis_smoke PRIVATE cooling_tower_native_analysis)
    add_test(NAME native_analysis_smoke COMMAND native_analysis_smoke)
endif()
