include(FetchContent)
FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG v2.13.6
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(pybind11)

pybind11_add_module(manifold_engine
    bindings.cpp
    byte_stream_manifold.cpp
    structural_entropy.cpp
    manifold_builder.cpp
    io_utils.cpp
)

target_link_libraries(manifold_engine PRIVATE sep_core_deps sep_fetchcontent_deps)
