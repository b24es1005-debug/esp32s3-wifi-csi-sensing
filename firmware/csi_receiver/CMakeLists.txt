## This CMakeLists originally acted as the ESP-IDF project root.
## The canonical ESP-IDF top-level CMake is now `firmware/CMakeLists.txt`.
## Keep this file as a harmless marker so the directory remains a normal
## subdirectory when building from the new top-level project.

cmake_minimum_required(VERSION 3.16)

# No `project()` or `include($ENV{IDF_PATH}/tools/cmake/project.cmake)` here;
# the top-level `firmware/CMakeLists.txt` provides the project() call.

