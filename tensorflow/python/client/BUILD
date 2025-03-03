# Contains targets that expose client session APIs

load("//tensorflow:tensorflow.bzl", "tf_cuda_library")
load("//tensorflow:tensorflow.bzl", "tf_python_pybind_extension")

# buildifier: disable=same-origin-load
load("//tensorflow:tensorflow.bzl", "tf_py_test")

# buildifier: disable=same-origin-load
load("//tensorflow:tensorflow.bzl", "cuda_py_test")
load("//tensorflow/core/platform:build_config_root.bzl", "if_static")

package(
    default_visibility = [
        "//tensorflow:internal",
    ],
    licenses = ["notice"],
)

py_library(
    name = "pywrap_tf_session",
    srcs = ["pywrap_tf_session.py"],
    srcs_version = "PY3",
    visibility = ["//visibility:public"],
    deps = [
        ":_pywrap_tf_session",
        "//tensorflow/python:pywrap_tensorflow",
    ],
)

tf_python_pybind_extension(
    name = "_pywrap_tf_session",
    srcs = ["tf_session_wrapper.cc"],
    hdrs = [
        "tf_session_helper.h",
        "//tensorflow/c:headers",
        "//tensorflow/c/eager:headers",
        "//tensorflow/c/eager:pywrap_required_hdrs",
        "//tensorflow/c/experimental/ops:pywrap_required_hdrs",
        "//tensorflow/core/common_runtime/eager:pywrap_required_hdrs",
        "//tensorflow/core/distributed_runtime:pywrap_required_hdrs",
        "//tensorflow/core/distributed_runtime/coordination:pywrap_required_hdrs",
        "//tensorflow/core/distributed_runtime/eager:pywrap_required_hdrs",
        "//tensorflow/python/lib/core:numpy_hdr",
        "//tensorflow/python/lib/core:safe_ptr_hdr",
    ],
    module_name = "_pywrap_tf_session",
    deps = [
        "//third_party/eigen3",
        "//tensorflow/python/lib/core:pybind11_lib",
        "//tensorflow/python/lib/core:pybind11_status",
        "//tensorflow/python/lib/core:safe_pyobject_ptr",
        "//tensorflow/core/framework:pywrap_required_hdrs",
        "//third_party/py/numpy:headers",
        "//tensorflow/c:pywrap_required_hdrs",
        "@pybind11",
        "//third_party/python_runtime:headers",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/core:framework_headers_lib",
        "//tensorflow/core/common_runtime:core_cpu_headers_lib",
        "//tensorflow/core:lib_headers_for_pybind",
        "@com_google_absl//absl/types:optional",
        "//tensorflow/core/lib/llvm_rtti",
    ] + if_static(
        extra_deps = [
            "//tensorflow/core/protobuf:eager_service_proto_cc",
            "//tensorflow/core/protobuf:master_proto_cc",
            "//tensorflow/core/protobuf:worker_proto_cc",
            "//tensorflow/core:version_lib",
        ],
        otherwise = [
            "//tensorflow/core/protobuf:eager_service_proto_cc_headers_only",
            "//tensorflow/core/protobuf:master_proto_cc_headers_only",
            "//tensorflow/core/protobuf:worker_proto_cc_headers_only",
        ],
    ),
)

tf_python_pybind_extension(
    name = "_pywrap_debug_events_writer",
    srcs = ["debug_events_writer_wrapper.cc"],
    module_name = "_pywrap_debug_events_writer",
    deps = [
        "//tensorflow/core:framework_headers_lib",
        "//tensorflow/core:lib_headers_for_pybind",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/python/lib/core:pybind11_absl",
        "//tensorflow/python/lib/core:pybind11_proto",
        "//tensorflow/python/lib/core:pybind11_status",
        "//third_party/python_runtime:headers",
        "@com_google_absl//absl/strings",
        "@pybind11",
    ],
)

tf_python_pybind_extension(
    name = "_pywrap_events_writer",
    srcs = ["events_writer_wrapper.cc"],
    module_name = "_pywrap_events_writer",
    deps = [
        "//tensorflow/core:framework_headers_lib",
        "//tensorflow/core:lib_headers_for_pybind",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/python/lib/core:pybind11_absl",
        "//tensorflow/python/lib/core:pybind11_proto",
        "//tensorflow/python/lib/core:pybind11_status",
        "//third_party/python_runtime:headers",
        "@com_google_absl//absl/strings",
        "@pybind11",
    ],
)

py_library(
    name = "client",
    srcs = [
        "client_lib.py",
        "device_lib.py",
        "timeline.py",
    ],
    srcs_version = "PY3",
    deps = [
        ":_pywrap_device_lib",
        "//tensorflow/python:platform",
        "//tensorflow/python:session",
        "//tensorflow/python:session_ops",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:errors",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//tensorflow/python/util",
        "//third_party/py/numpy",
        "@six_archive//:six",
    ],
)

tf_py_test(
    name = "events_writer_test",
    size = "small",
    srcs = ["events_writer_test.py"],
    python_version = "PY3",
    deps = [
        "//tensorflow/python:lib",
        "//tensorflow/python:platform_test",
        "//tensorflow/python:pywrap_tensorflow",
        "//tensorflow/python/framework:errors",
        "//tensorflow/python/framework:test_lib",
        "//tensorflow/python/util",
    ],
)

py_library(
    name = "device_lib",
    srcs = ["device_lib.py"],
    srcs_version = "PY3",
    deps = [
        ":_pywrap_device_lib",
        "//tensorflow/core:protos_all_py",
        "//tensorflow/python:pywrap_tensorflow",
    ],
)

tf_python_pybind_extension(
    name = "_pywrap_device_lib",
    srcs = ["device_lib_wrapper.cc"],
    module_name = "_pywrap_device_lib",
    deps = [
        "//tensorflow/core:framework_internal_headers_lib",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/core/common_runtime:core_cpu_headers_lib",
        "//tensorflow/python/lib/core:pybind11_proto",
        "//tensorflow/python/lib/core:pybind11_status",
        "//third_party/python_runtime:headers",
        "@pybind11",
    ],
)

cuda_py_test(
    name = "device_lib_test",
    size = "small",
    srcs = [
        "device_lib_test.py",
    ],
    python_version = "PY3",
    deps = [
        ":client",
        "//tensorflow/core:protos_all_py",
        "//tensorflow/python:client_testlib",
        "//tensorflow/python:platform_test",
        "//tensorflow/python/framework:test_lib",
    ],
)

cc_library(
    name = "session_ref",
    srcs = ["session_ref.cc"],
    hdrs = ["session_ref.h"],
    deps = [
        "//tensorflow/core:core_cpu",
        "//tensorflow/core:lib",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/core/protobuf:master_proto_cc",
        "//tensorflow/core/protobuf:replay_log_proto_cc",
    ],
)

tf_cuda_library(
    name = "tf_session_helper",
    srcs = ["tf_session_helper.cc"],
    hdrs = ["tf_session_helper.h"],
    compatible_with = [],
    deps = [
        ":construction_fails_op",
        ":session_ref",
        "//tensorflow/c:c_api",
        "//tensorflow/c:c_api_internal",
        "//tensorflow/c:tf_status_helper",
        "//tensorflow/core",
        "//tensorflow/core:all_kernels",
        "//tensorflow/core:direct_session",
        "//tensorflow/core:framework",
        "//tensorflow/core:framework_internal",
        "//tensorflow/core:graph",
        "//tensorflow/core:lib",
        "//tensorflow/core:protos_all_cc",
        "//tensorflow/python:ndarray_tensor",
        "//tensorflow/python:ndarray_tensor_bridge",
        "//tensorflow/python:numpy_lib",
        "//tensorflow/python:safe_ptr",
        "//tensorflow/python/framework:test_ops_kernels",
        "//third_party/py/numpy:headers",
        "//third_party/python_runtime:headers",
    ],
    alwayslink = 1,
)

py_library(
    name = "session",
    srcs = ["session.py"],
    srcs_version = "PY3",
    visibility = ["//tensorflow:internal"],
    deps = [
        "//tensorflow/python:mixed_precision_global_state",
        "//tensorflow/python:platform",
        "//tensorflow/python:pywrap_tensorflow",
        "//tensorflow/python:session_ops",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:c_api_util",
        "//tensorflow/python/framework:error_interpolation",
        "//tensorflow/python/framework:errors",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//tensorflow/python/util",
        "//third_party/py/numpy",
        "@wrapt",
    ],
)

py_library(
    name = "timeline",
    srcs = ["timeline.py"],
    srcs_version = "PY3",
    visibility = ["//visibility:public"],
    deps = [
        "//tensorflow/python:platform",
    ],
)

# Just used by tests.
tf_cuda_library(
    name = "construction_fails_op",
    srcs = ["test_construction_fails_op.cc"],
    deps = [
        "//tensorflow/core",
        "//tensorflow/core:framework",
        "//tensorflow/core:lib",
        "//tensorflow/core:protos_all_cc",
    ],
    alwayslink = 1,
)

tf_py_test(
    name = "session_test",
    size = "medium",
    srcs = ["session_test.py"],
    grpc_enabled = True,
    python_version = "PY3",
    tags = [
        "no_gpu",  # b/127001953
        "no_pip_gpu",  # testInteractivePlacePrunedGraph fails on invalid assumption about GPU ops.
        "no_windows",
    ],
    deps = [
        ":client",
        "//tensorflow/python:array_ops",
        "//tensorflow/python:control_flow_ops",
        "//tensorflow/python:data_flow_ops",
        "//tensorflow/python:math_ops",
        "//tensorflow/python:platform_test",
        "//tensorflow/python:state_ops",
        "//tensorflow/python:training",
        "//tensorflow/python:variables",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:config",
        "//tensorflow/python/framework:errors",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//tensorflow/python/framework:test_lib",
        "//tensorflow/python/util",
        "//third_party/py/numpy",
        "@six_archive//:six",
    ],
)

tf_py_test(
    name = "session_clusterspec_prop_test",
    size = "small",
    srcs = ["session_clusterspec_prop_test.py"],
    grpc_enabled = True,
    python_version = "PY3",
    tags = [
        "no_gpu",
        "no_oss",
        "no_pip",
        "no_pip_gpu",
        "notap",
    ],
    deps = [
        ":client",
        "//tensorflow/python:array_ops",
        "//tensorflow/python:client_testlib",
        "//tensorflow/python:math_ops",
        "//tensorflow/python:platform_test",
        "//tensorflow/python:state_ops",
        "//tensorflow/python:training",
        "//tensorflow/python:variables",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//tensorflow/python/framework:test_lib",
        "//tensorflow/python/util",
        "//third_party/py/numpy",
    ],
)

tf_py_test(
    name = "session_list_devices_test",
    size = "small",
    srcs = ["session_list_devices_test.py"],
    grpc_enabled = True,
    python_version = "PY3",
    tags = [
        "no_gpu",
        "no_pip_gpu",
        "notsan",  # data race due to b/62910646
    ],
    deps = [
        ":client",
        "//tensorflow/python:platform_test",
        "//tensorflow/python:training",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:test_lib",
    ],
)

tf_py_test(
    name = "session_partial_run_test",
    size = "small",
    srcs = ["session_partial_run_test.py"],
    grpc_enabled = True,
    python_version = "PY3",
    tags = [
        "no_gpu",
        "no_windows",
    ],
    deps = [
        ":client",
        "//tensorflow/python:array_ops",
        "//tensorflow/python:math_ops",
        "//tensorflow/python:platform_test",
        "//tensorflow/python:training",
        "//tensorflow/python/framework",
        "//tensorflow/python/framework:errors",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//tensorflow/python/framework:test_lib",
        "//tensorflow/python/util",
        "@six_archive//:six",
    ],
)

cuda_py_test(
    name = "timeline_test",
    size = "small",
    srcs = ["timeline_test.py"],
    python_version = "PY3",
    tags = [
        "gpu_cupti",
        "no_gpu",  # b/154742661
    ],
    xla_enable_strict_auto_jit = False,  # Graph structure is different with autojit
    deps = [
        ":client",
        "//tensorflow/core:protos_all_py",
        "//tensorflow/python:client_testlib",
        "//tensorflow/python:math_ops",
        "//tensorflow/python/framework:for_generated_wrappers",
    ],
)

cuda_py_test(
    name = "virtual_gpu_test",
    size = "small",
    srcs = ["virtual_gpu_test.py"],
    python_version = "PY3",
    tags = [
        "no_gpu",  # b/127386241
        "no_windows_gpu",
    ],
    deps = [
        ":client",
        "//tensorflow/core:protos_all_py",
        "//tensorflow/python:client_testlib",
        "//tensorflow/python:math_ops",
        "//tensorflow/python/framework:for_generated_wrappers",
    ],
)

cuda_py_test(
    name = "session_benchmark",
    srcs = ["session_benchmark.py"],
    grpc_enabled = True,
    main = "session_benchmark.py",
    python_version = "PY3",
    deps = [
        ":client",
        "//tensorflow/python:array_ops",
        "//tensorflow/python:client_testlib",
        "//tensorflow/python:random_ops",
        "//tensorflow/python:training",
        "//tensorflow/python:variables",
        "//tensorflow/python/framework:for_generated_wrappers",
        "//third_party/py/numpy",
    ],
)
