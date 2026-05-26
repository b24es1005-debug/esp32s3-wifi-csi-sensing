# =============================================================================
# firmware/csi_receiver/CMakeLists.txt
# Top-level CMake file for the ESP-IDF project.
# ESP-IDF requires this exact structure at the project root.
# =============================================================================

cmake_minimum_required(VERSION 3.16)

# Include the ESP-IDF CMake build system.
# The IDF_PATH environment variable must point to your ESP-IDF installation.
# This is set automatically by running `. ~/esp/esp-idf/export.sh`
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Project name — used by idf.py as the build output name
project(csi_receiver)
