cmake_minimum_required(VERSION 3.16)

# Wrapper CMakeLists for convenience: delegate to the existing
# ESP-IDF project in `csi_receiver/` so `idf.py` commands work
# when invoked from `firmware/`.

add_subdirectory(csi_receiver)
