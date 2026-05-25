cmake_minimum_required(VERSION 3.16)

# Top-level ESP-IDF project for this firmware folder.
# This file must contain a literal `project()` call and include the
# ESP-IDF CMake project helper so the toolchain and idf build system
# are configured correctly when running `idf.py` from `firmware/`.

if(NOT DEFINED ENV{IDF_PATH})
	message(FATAL_ERROR "IDF_PATH environment variable is not set. Source ESP-IDF export script before building.")
endif()

# Ensure this firmware is configured for ESP32-S3 by default. This can be
# overridden by the environment or by running `idf.py set-target` if needed.
set(IDF_TARGET "esp32s3" CACHE STRING "ESP-IDF target (chip family) for this project")

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/csi_receiver/main")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(csi_receiver)
