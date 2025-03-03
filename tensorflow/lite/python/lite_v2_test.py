# Lint as: python2, python3
# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for lite.py functionality related to TensorFlow 2.0."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ctypes
import os
import sys

from absl.testing import parameterized
import numpy as np
from six.moves import range
from six.moves import zip
import tensorflow as tf

# Force loaded shared object symbols to be globally visible. This is needed so
# that the interpreter_wrapper, in one .so file, can see the test_registerer,
# in a different .so file. Note that this may already be set by default.
# pylint: disable=g-import-not-at-top
if hasattr(sys, 'setdlopenflags') and hasattr(sys, 'getdlopenflags'):
  sys.setdlopenflags(sys.getdlopenflags() | ctypes.RTLD_GLOBAL)

from tensorflow.lite.python import convert
from tensorflow.lite.python import lite
from tensorflow.lite.python import lite_v2_test_util
from tensorflow.lite.python import schema_py_generated as schema_fb
from tensorflow.lite.python import test_util as tflite_test_util
from tensorflow.lite.python import util
from tensorflow.lite.python.convert import mlir_quantize
from tensorflow.lite.python.interpreter import Interpreter
from tensorflow.lite.python.interpreter import InterpreterWithCustomOps
from tensorflow.lite.python.interpreter import OpResolverType
from tensorflow.lite.python.testdata import _pywrap_test_registerer as test_registerer
from tensorflow.lite.python.testdata import double_op
from tensorflow.lite.toco import types_pb2 as _types_pb2
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import test_util
from tensorflow.python.lib.io import file_io
from tensorflow.python.ops import map_ops
from tensorflow.python.platform import resource_loader
from tensorflow.python.platform import test
from tensorflow.python.saved_model import save_options
from tensorflow.python.saved_model import saved_model
from tensorflow.python.saved_model.loader_impl import parse_saved_model
from tensorflow.python.saved_model.save import save
from tensorflow.python.training.tracking import tracking
# pylint: enable=g-import-not-at-top


class FromConcreteFunctionTest(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testTypeInvalid(self):
    root = self._getSimpleVariableModel()
    with self.assertRaises(ValueError) as error:
      _ = lite.TFLiteConverterV2.from_concrete_functions([root.f], root)
    self.assertIn('call get_concrete_function', str(error.exception))

  @parameterized.named_parameters(
      ('EnableMlirConverter', True),  # enable mlir
      ('DisableMlirConverter', False))  # disable mlir
  @test_util.run_v2_only
  def testFloat(self, enable_mlir_converter):
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.f.get_concrete_function(input_data)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    converter.experimental_new_converter = enable_mlir_converter
    tflite_model = converter.convert()

    # Check output value from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @parameterized.named_parameters(('_INT8InputOutput', dtypes.int8),
                                  ('_UINT8InputOutput', dtypes.uint8),
                                  ('_INT16InputOutput', dtypes.int16))
  @test_util.run_v2_only
  def testInvalidFloat(self, inference_input_output_type):
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.f.get_concrete_function(input_data)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    with self.assertRaises(ValueError) as error:
      converter.inference_input_type = inference_input_output_type
      converter.inference_output_type = inference_input_output_type
      converter.convert()
    self.assertEqual(
        'The inference_input_type and inference_output_type '
        'must be tf.float32.', str(error.exception))

  @test_util.run_v2_only
  def testScalarInput(self):
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[])
    concrete_func = root.f.get_concrete_function(input_data)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @test_util.run_v2_only
  def testMultiFunctionModel(self):
    """Convert a single model in a multi-functional model."""
    root = self._getMultiFunctionModel()
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.add.get_concrete_function(input_data)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.add(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @test_util.run_v2_only
  def testConvertMultipleFunctions(self):
    """Convert multiple functions in a multi-functional model."""
    root = self._getMultiFunctionModel()
    input_data = tf.constant(1., shape=[1])
    add_func = root.add.get_concrete_function(input_data)
    sub_func = root.sub.get_concrete_function(input_data)

    # Try converting multiple functions.
    converter = lite.TFLiteConverterV2.from_concrete_functions(
        [add_func, sub_func], root)
    tflite_model = converter.convert()

    # Check signatures are valid from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 2)
    self.assertEqual(list(signature_defs.keys()), ['add', 'sub'])
    self.assertEqual(len(signature_defs.values()), 2)
    self.assertEqual(list(signature_defs['add'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['add']['inputs'], ['x'])
    self.assertEqual(list(signature_defs['add']['outputs']), ['output_0'])
    self.assertEqual(list(signature_defs['sub'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['sub']['inputs'], ['x'])
    self.assertEqual(list(signature_defs['sub']['outputs']), ['output_0'])

    # Verify the Signature runner executions.
    add_signature_runner = interpreter.get_signature_runner('add')
    add_output = add_signature_runner(x=input_data)
    self.assertEqual(add_output['output_0'], 3)
    input_details = add_signature_runner.get_input_details()
    self.assertEqual(1, len(input_details))
    self.assertEqual('add_x:0', input_details['x']['name'])
    self.assertEqual(np.float32, input_details['x']['dtype'])
    self.assertTrue(([1] == input_details['x']['shape']).all())
    self.assertEqual((0.0, 0), input_details['x']['quantization'])

    sub_signature_runner = interpreter.get_signature_runner('sub')
    sub_output = sub_signature_runner(x=input_data)
    self.assertEqual(sub_output['output_0'], -2)
    output_details = sub_signature_runner.get_output_details()
    self.assertEqual(1, len(output_details))
    self.assertEqual('StatefulPartitionedCall:0',
                     output_details['output_0']['name'])
    self.assertEqual(np.float32, output_details['output_0']['dtype'])
    self.assertTrue(([1] == output_details['output_0']['shape']).all())
    self.assertEqual((0.0, 0), output_details['output_0']['quantization'])

  def _getIntegerQuantizeModel(self, num_filters=16):
    np.random.seed(0)

    root = tracking.AutoTrackable()

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[1, 5, 5, 3], dtype=tf.float32)])
    def func(inp):
      conv = tf.nn.conv2d(
          inp,
          tf.ones([3, 3, 3, num_filters]), strides=[1, 1, 1, 1], padding='SAME')
      output = tf.nn.relu(conv, name='output')
      return output

    def calibration_gen():
      for _ in range(5):
        yield [np.random.uniform(-1, 1, size=(1, 5, 5, 3)).astype(np.float32)]

    root.f = func
    to_save = root.f.get_concrete_function()
    return (root, to_save, calibration_gen)

  @parameterized.named_parameters(
      ('EnableMlirQuantizer', True),  # enable mlir quantizer
      ('DisableMlirQuantizer', False))  # disable mlir quantizer
  def testPostTrainingCalibrateAndQuantize(self, mlir_quantizer):
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    # Convert float model.
    float_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                     root)
    float_tflite_model = float_converter.convert()
    self.assertIsNotNone(float_tflite_model)

    # Convert quantized model.
    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calibration_gen
    quantized_converter.experimental_new_quantizer = mlir_quantizer
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    # The default input and output types should be float.
    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(np.float32, input_details[0]['dtype'])
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 1)
    self.assertEqual(np.float32, output_details[0]['dtype'])

    # Ensure that the quantized weights tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(float_tflite_model))

  @parameterized.named_parameters(('_INT8InputOutput', dtypes.int8),
                                  ('_UINT8InputOutput', dtypes.uint8),
                                  ('_INT16InputOutput', dtypes.int16))
  @test_util.run_v2_only
  def testInvalidPostTrainingDynamicRangeQuantization(
      self, inference_input_output_type):
    root, func, _ = self._getIntegerQuantizeModel()

    # Convert float model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([func], root)
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

    # Convert quantized model.
    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    with self.assertRaises(ValueError) as error:
      quantized_converter.inference_input_type = inference_input_output_type
      quantized_converter.inference_output_type = inference_input_output_type
      quantized_converter.convert()
    self.assertEqual(
        'The inference_input_type and inference_output_type '
        'must be tf.float32.', str(error.exception))

  @parameterized.named_parameters(
      ('_Default', False, False, dtypes.float32),
      ('_INT8InputOutput', False, False, dtypes.int8),
      ('_UINT8InputOutput', False, False, dtypes.uint8),
      ('_INT16Quantize', False, True, dtypes.float32),
      ('_INT16Quantize_INT16InputOutput', False, True, dtypes.int16),
      ('_IntOnly', True, False, dtypes.float32),
      ('_IntOnly_INT8InputOutput', True, False, dtypes.int8),
      ('_IntOnly_UINT8InputOutput', True, False, dtypes.uint8),
      ('_IntOnly_INT16Quantize', True, True, dtypes.float32),
      ('_IntOnly_INT16Quantize_INT16InputOutput', True, True, dtypes.int16))
  def testIntegerQuantization(self, is_int_only, is_int16_quantize,
                              inference_input_output_type):
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    # Convert float model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([func], root)
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

    # Convert quantized model.
    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calibration_gen
    if is_int_only:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8
        ]
      else:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.TFLITE_BUILTINS_INT8
        ]
    else:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
            lite.OpsSet.TFLITE_BUILTINS
        ]
    quantized_converter.inference_input_type = inference_input_output_type
    quantized_converter.inference_output_type = inference_input_output_type
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     input_details[0]['dtype'])
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     output_details[0]['dtype'])

    # Ensure that the quantized tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(tflite_model))

  @parameterized.named_parameters(
      ('_INT16Quantize_INT8InputOutput', True, dtypes.int8))
  def testInvalidIntegerQuantization(self, is_int16_quantize,
                                     inference_input_output_type):
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    # Convert quantized model.
    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calibration_gen
    if is_int16_quantize:
      quantized_converter.target_spec.supported_ops = [
          lite.OpsSet.
          EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
          lite.OpsSet.TFLITE_BUILTINS
      ]
    with self.assertRaises(ValueError) as error:
      quantized_converter.inference_input_type = dtypes.int8
      quantized_converter.inference_output_type = dtypes.int8
      quantized_converter.convert()
    self.assertEqual(
        'The inference_input_type and inference_output_type '
        "must be in ['tf.float32', 'tf.int16'].", str(error.exception))

  def testCalibrateAndQuantizeBuiltinInt16(self):
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    # Convert float model.
    float_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                     root)
    float_tflite_model = float_converter.convert()
    self.assertIsNotNone(float_tflite_model)

    converter = lite.TFLiteConverterV2.from_concrete_functions([func], root)
    # TODO(b/156309549): We should add INT16 to the builtin types.
    converter.optimizations = [lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops = [lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.representative_dataset = calibration_gen
    converter._experimental_calibrate_only = True
    calibrated_tflite = converter.convert()
    quantized_tflite_model = mlir_quantize(
        calibrated_tflite, inference_type=_types_pb2.QUANTIZED_INT16)

    self.assertIsNotNone(quantized_tflite_model)

    # The default input and output types should be float.
    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(np.float32, input_details[0]['dtype'])
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 1)
    self.assertEqual(np.float32, output_details[0]['dtype'])

    # Ensure that the quantized weights tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(float_tflite_model))

  @test_util.run_v2_only
  def testSignatureDefs(self):
    """Test converting SignatureDef is correct and uses SignatureDef API."""
    root = self._getMultiFunctionModel()
    input_data = tf.constant(1., shape=[1])
    add_func = root.add.get_concrete_function(input_data)

    converter = lite.TFLiteConverterV2([add_func], trackable_obj=root)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = add_func(input_data)
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    results = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model, 'serving_default', {'x': input_data})
    self.assertLen(list(results.keys()), 1)
    self.assertStartsWith(list(results.keys())[0], 'output')
    self.assertAllClose(
        expected_value.numpy(),
        results[signature_defs['serving_default']['outputs'][0]])

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 1)
    self.assertEqual(list(signature_defs.keys()), ['serving_default'])
    self.assertEqual(len(signature_defs.values()), 1)
    self.assertEqual(
        list(signature_defs['serving_default'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['serving_default']['inputs'], ['x'])
    self.assertLen(list(signature_defs['serving_default']['outputs']), 1)
    self.assertStartsWith(
        list(signature_defs['serving_default']['outputs'])[0], 'output')

  @test_util.run_v2_only
  def testNoSignatureDefsWhenTrackingObjIsNone(self):
    """Test converting SignatureDef is correct and uses SignatureDef API."""
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.f.get_concrete_function(input_data)

    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               None)
    tflite_model = converter.convert()

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    # Verify that there is no SignatureDef structure found.
    self.assertEqual(len(signature_defs), 0)

  @test_util.run_v2_only
  def testNoSignatureDefsWhenInvalidTrackingObjIsGiven(self):
    """Test converting SignatureDef is correct and uses SignatureDef API."""
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.f.get_concrete_function(input_data)

    converter = lite.TFLiteConverterV2.from_concrete_functions(
        [concrete_func], trackable_obj=tracking.AutoTrackable())
    tflite_model = converter.convert()

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    # Verify that there is no SignatureDef structure found.
    self.assertEqual(len(signature_defs), 0)

  @test_util.run_v2_only
  def testTrackbleObject(self):
    """Test converting with trackable objects."""
    root = self._getMultiFunctionModel()
    input_data = tf.constant(1., shape=[1])
    add_func = root.add.get_concrete_function(input_data)

    converter = lite.TFLiteConverterV2.from_concrete_functions(
        [add_func], trackable_obj=root)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = add_func(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  def _getTrainingTimeQuantizedModel(self):

    class QLinear(tf.keras.layers.Layer):

      def __init__(self, units=3, **kwargs):
        super(QLinear, self).__init__(**kwargs)
        self.units = units

      def build(self, input_shape):
        self.w = self.add_weight(
            'weight',
            shape=(input_shape[-1], self.units),
            initializer='random_normal',
            trainable=True)
        self.min_var = self.add_weight(
            'min',
            initializer=tf.keras.initializers.Constant(-6.0),
            trainable=False)
        self.max_var = self.add_weight(
            'max',
            initializer=tf.keras.initializers.Constant(6.0),
            trainable=False)

      def call(self, inputs):
        x = tf.quantization.fake_quant_with_min_max_vars(
            inputs, self.min_var, self.max_var)

        w_fq = tf.quantization.fake_quant_with_min_max_vars(
            self.w, self.min_var, self.max_var)
        x = tf.matmul(x, w_fq)

        x = tf.quantization.fake_quant_with_min_max_vars(
            x, self.min_var, self.max_var)

        return x

    return tf.keras.Sequential(QLinear(3, input_shape=(2,)))

  @parameterized.named_parameters(
      ('_DefaultFLOAT32InputOutput', dtypes.float32),
      ('_INT8InputOutput', dtypes.int8), ('_UINT8InputOutput', dtypes.uint8))
  @test_util.run_v2_only
  def testTrainingTimeQuantization(self, inference_input_output_type):
    model = self._getTrainingTimeQuantizedModel()

    float_converter = lite.TFLiteConverterV2.from_keras_model(model)
    float_tflite_model = float_converter.convert()
    self.assertIsNotNone(float_tflite_model)

    quantized_converter = lite.TFLiteConverterV2.from_keras_model(model)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.inference_input_type = inference_input_output_type
    quantized_converter.inference_output_type = inference_input_output_type
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     input_details[0]['dtype'])
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     output_details[0]['dtype'])

    # Ensure that the quantized tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(float_tflite_model))

  @test_util.run_v2_only
  def testNewQuantizer(self):
    """Test the model quantized by the new converter."""
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.target_spec.supported_ops = [
        lite.OpsSet.TFLITE_BUILTINS_INT8
    ]
    quantized_converter.representative_dataset = calibration_gen

    # default quantizer
    quantized_converter.experimental_new_quantizer = False
    old_tflite = quantized_converter.convert()

    # new quantizer
    quantized_converter.experimental_new_quantizer = True
    new_tflite = quantized_converter.convert()

    for _ in range(5):
      input_data = tf.constant(
          np.random.uniform(-1, 1, size=(1, 5, 5, 3)).astype(np.float32))
      old_value = self._evaluateTFLiteModel(old_tflite, [input_data])
      new_value = self._evaluateTFLiteModel(new_tflite, [input_data])
      self.assertAllClose(old_value, new_value, atol=1e-01)

  @parameterized.named_parameters(
      ('EnableMlirConverter', True),  # enable mlir
      ('DisableMlirConverter', False))  # disable mlir
  @test_util.run_v2_only
  def testEmbeddings(self, enable_mlir_converter):
    """Test model with embeddings."""
    input_data = tf.constant(
        np.array(np.random.random_sample((20)), dtype=np.int32))

    class EmbeddingModel(tf.keras.Model):

      def __init__(self):
        super(EmbeddingModel, self).__init__()
        self.shared_weights = self.add_weight(
            'weights',
            shape=(2000, 300),
            dtype=tf.float32,
            initializer=tf.random_normal_initializer(
                mean=0.0, stddev=300**(-0.5)))

      @tf.function(input_signature=[tf.TensorSpec(shape=(20), dtype=tf.int32)])
      def func(self, x):
        return tf.gather(self.shared_weights, x)

    # Building the model.
    root = EmbeddingModel()
    concrete_func = root.func.get_concrete_function()

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    converter.experimental_new_converter = enable_mlir_converter
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.func(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertAllClose(expected_value.numpy(), actual_value[0], atol=1e-05)

  @test_util.run_v2_only
  def testGraphDebugInfo(self):
    """Test a concrete function has debug info captured."""
    root = tracking.AutoTrackable()
    root.v1 = tf.Variable(3.)
    root.f = tf.function(lambda x: root.v1 * x)
    input_data = tf.constant(1., shape=[1])
    concrete_func = root.f.get_concrete_function(input_data)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    converter.convert()
    self._assertValidDebugInfo(converter._debug_info)

  def _getIntegerQuantizationModelWithFlexOp(self):
    np.random.seed(0)

    root = tracking.AutoTrackable()

    @tf.function(input_signature=[
        tf.TensorSpec(shape=[3, 3, 3, 3, 3], dtype=tf.float32)
    ])
    def func(inp):
      tanh = tf.math.tanh(inp)
      # Flex delegate will merge the consecutive conv3d and erf ops into one
      # Delegate node.
      conv3d = tf.nn.conv3d(
          tanh,
          tf.ones([3, 3, 3, 3, 3]),
          strides=[1, 1, 1, 1, 1],
          padding='SAME')
      erf = tf.math.erf(conv3d)
      output = tf.math.tanh(erf)
      return output

    def calibration_gen():
      for _ in range(5):
        yield [
            np.random.uniform(-1, 1, size=(3, 3, 3, 3, 3)).astype(np.float32)
        ]

    root.f = func
    return (root, root.f.get_concrete_function(), calibration_gen)

  @parameterized.named_parameters(
      ('_Default', False, False, dtypes.float32),
      ('_INT8InputOutput', False, False, dtypes.int8),
      ('_UINT8InputOutput', False, False, dtypes.uint8),
      ('_INT16Quantize', False, True, dtypes.float32),
      ('_INT16Quantize_INT16InputOutput', False, True, dtypes.int16),
      ('_IntOnly', True, False, dtypes.float32),
      ('_IntOnly_INT8InputOutput', True, False, dtypes.int8),
      ('_IntOnly_UINT8InputOutput', True, False, dtypes.uint8),
      ('_IntOnly_INT16Quantize', True, True, dtypes.float32),
      ('_IntOnly_INT16Quantize_INT16InputOutput', True, True, dtypes.int16))
  @test_util.run_v2_only
  def testIntegerQuantizationWithFlexOp(self, is_int_only, is_int16_quantize,
                                        inference_input_output_type):
    root, func, calibration_gen = self._getIntegerQuantizationModelWithFlexOp()

    quantized_converter = tf.lite.TFLiteConverter.from_concrete_functions(
        [func], root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calibration_gen
    if is_int_only:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
            lite.OpsSet.SELECT_TF_OPS
        ]
      else:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.TFLITE_BUILTINS_INT8, lite.OpsSet.SELECT_TF_OPS
        ]
    else:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
            lite.OpsSet.TFLITE_BUILTINS,
            lite.OpsSet.SELECT_TF_OPS
        ]
      else:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.TFLITE_BUILTINS, lite.OpsSet.SELECT_TF_OPS
        ]

    quantized_converter.inference_input_type = inference_input_output_type
    quantized_converter.inference_output_type = inference_input_output_type
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     input_details[0]['dtype'])
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 1)
    self.assertEqual(inference_input_output_type.as_numpy_dtype,
                     output_details[0]['dtype'])

  def _getIntegerQuantizationModelWithUnsupportedOps(self):
    np.random.seed(0)

    root = tracking.AutoTrackable()

    @tf.function(input_signature=[
        tf.TensorSpec(shape=[3], dtype=tf.float32),
        tf.TensorSpec(shape=[3], dtype=tf.float32)
    ])
    def func(a, b):
      # ceil kernel does not support int8 nor int16 types neither.
      left = tf.math.ceil(a)
      right = tf.nn.tanh(b)
      add = tf.math.add(left, right)
      # ceil kernel does not support int8 nor int16 types neither.
      output = tf.math.ceil(add)
      return (output, right)

    def calibration_gen():
      for _ in range(5):
        yield [
            np.random.uniform(-1, 1, size=(3)).astype(np.float32),
            np.random.uniform(-1, 1, size=(3)).astype(np.float32)
        ]

    root.f = func
    return (root, root.f.get_concrete_function(), calibration_gen)

  @parameterized.named_parameters(
      ('_INT8InputOutput', False, False, dtypes.int8),
      ('_UINT8InputOutput', False, False, dtypes.uint8),
      ('_INT16Quantize_INT16InputOutput', False, True, dtypes.int16),
      ('_IntOnly_INT8InputOutput', True, False, dtypes.int8),
      ('_IntOnly_UINT8InputOutput', True, False, dtypes.uint8),
      ('_IntOnly_INT16Quantize_INT16InputOutput', True, True, dtypes.int16),
      ('_IntOnly_INT8InputOutputMlirQuant', True, False, dtypes.int8, True),
      ('_IntOnly_UINT8InputOutputMlirQuant', True, False, dtypes.uint8, True))
  @test_util.run_v2_only
  def testIntegerQuantizationWithUnsupportedOps(self,
                                                is_int_only,
                                                is_int16_quantize,
                                                inference_input_output_type,
                                                enable_mlir_quantizer=False):
    root, func, calib_gen = self._getIntegerQuantizationModelWithUnsupportedOps(
    )

    quantized_converter = tf.lite.TFLiteConverter.from_concrete_functions(
        [func], root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calib_gen
    if is_int_only:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
            lite.OpsSet.TFLITE_BUILTINS
        ]
      else:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.TFLITE_BUILTINS_INT8, lite.OpsSet.TFLITE_BUILTINS
        ]
    else:
      if is_int16_quantize:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.
            EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8,
            lite.OpsSet.TFLITE_BUILTINS
        ]
      else:
        quantized_converter.target_spec.supported_ops = [
            lite.OpsSet.TFLITE_BUILTINS
        ]

    quantized_converter.inference_input_type = inference_input_output_type
    quantized_converter.inference_output_type = inference_input_output_type
    quantized_converter.experimental_new_quantizer = enable_mlir_quantizer
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    expected_dtype = inference_input_output_type.as_numpy_dtype
    # Allow float32 for fallback on non-quantizable op.
    expected_ceil_dtype = (
        expected_dtype if enable_mlir_quantizer else dtypes.float32)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 2)
    self.assertEqual(input_details[0]['dtype'], expected_dtype)
    self.assertEqual(input_details[1]['dtype'], expected_ceil_dtype)
    output_details = interpreter.get_output_details()
    self.assertLen(output_details, 2)
    self.assertEqual(output_details[0]['dtype'], expected_dtype)
    self.assertEqual(output_details[1]['dtype'], expected_ceil_dtype)

  @parameterized.named_parameters(
      ('_BlocklistedNoneWithLowering', None, None, True),
      ('_BlocklistedNoneWithoutLowering', None, None, False),
      ('_BlocklistedOpsWithLowering', {'CONV_2D'}, None, True),
      ('_BlocklistedOpsWithoutLowering', {'CONV_2D'}, None, False),
      ('_BlocklistedNodesWithLowering', None, {'PartitionedCall:0'}, True),
      ('_BlocklistedNodesWithoutLowering', None, {'Identity'}, False))
  @test_util.run_v2_only
  def testNewQuantizerBlocklistingArgs(self, denylisted_ops, denylisted_nodes,
                                       lower_to_saved_model):
    """Test the model quantized by the new converter and denylisted options."""
    root, func, calibration_gen = self._getIntegerQuantizeModel()
    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.target_spec.supported_ops = [
        lite.OpsSet.TFLITE_BUILTINS_INT8
    ]
    quantized_converter.representative_dataset = calibration_gen
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.experimental_new_quantizer = True
    quantized_converter._experimental_calibrate_only = True
    quantized_converter.experimental_lower_to_saved_model = lower_to_saved_model
    calibrated = quantized_converter.convert()
    quantized_tflite_model = mlir_quantize(
        calibrated,
        denylisted_ops=denylisted_ops,
        denylisted_nodes=denylisted_nodes)
    interpreter = Interpreter(model_content=quantized_tflite_model)
    details = interpreter.get_tensor_details()
    num_quantized_tensors = sum(
        [1 for detail in details
         if len(detail['quantization_parameters']['scales'])])
    if denylisted_nodes or denylisted_ops:
      self.assertEqual(num_quantized_tensors, 0)
      return
    self.assertEqual(num_quantized_tensors, 4)  # quant, filter, bias, dequant

  @parameterized.named_parameters(
      ('_SingleLayer', False),
      ('_WholeModel', True),
  )
  @test_util.run_v2_only
  def testNewQuantizerNumericVerificationDebugMode(self, whole_model_verify):
    """Test the model quantized by the new converter with numeric verify ops."""
    root, func, calibration_gen = self._getIntegerQuantizeModel()

    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions([func],
                                                                         root)
    quantized_converter.target_spec.supported_ops = [
        lite.OpsSet.TFLITE_BUILTINS_INT8
    ]
    quantized_converter.representative_dataset = calibration_gen

    # Create a TFLite model with new quantizer.
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.experimental_new_quantizer = True
    production_tflite = quantized_converter.convert()
    # Create a TFLite model with new quantizer and numeric verify ops.
    quantized_converter._experimental_calibrate_only = True
    calibrated = quantized_converter.convert()
    debug_mode_tflite = mlir_quantize(
        calibrated,
        enable_numeric_verify=True,
        enable_whole_model_verify=whole_model_verify)

    # Check if adding debug mode should output a different flatbuffer.
    self.assertNotEqual(production_tflite, debug_mode_tflite)

    # Check if newly added ops are numeric verify ops.
    input_data = tf.constant(
        np.random.uniform(-1, 1, size=(1, 5, 5, 3)).astype(np.float32))

    def examine_tflite_model(tflite_content, input_data):
      interpreter = Interpreter(
          model_content=tflite_content,
          experimental_op_resolver_type=OpResolverType
          .BUILTIN_WITHOUT_DEFAULT_DELEGATES)
      interpreter.allocate_tensors()
      input_details = interpreter.get_input_details()
      interpreter.set_tensor(input_details[0]['index'], input_data.numpy())
      interpreter.invoke()
      tensor_details = interpreter.get_tensor_details()
      return {
          details['name']: interpreter.get_tensor(details['index'])
          for details in interpreter.get_tensor_details()
      }, tensor_details

    tflite_result, _ = examine_tflite_model(production_tflite, input_data)
    debug_mode_tflite_result, debug_tensor_details = examine_tflite_model(
        debug_mode_tflite, input_data)

    # MLIR-based quantizer should output flatbuffer model with `tfl.quantize`.
    num_production_quantize_ops = len([
        None for output_tensor_name in tflite_result
        if 'tfl.quantize' in output_tensor_name
    ])
    self.assertEqual(num_production_quantize_ops, 1)
    # MLIR-based quantizer should output flatbuffer model with `tfl.quantize`.
    num_debug_quantize_ops = len([
        None for output_tensor_name in debug_mode_tflite_result
        if 'tfl.quantize' in output_tensor_name
    ])
    # Two numbers should be equal.
    self.assertEqual(num_production_quantize_ops, num_debug_quantize_ops)
    # DebugMode TFLite flatbuffer should have NumericVerifyOps more than zero.
    # The name has the prefix "NumericVerify/{name}:{id}
    # where {name} is the tensor name of the original quantized op's activation,
    # and {id} is its tensor id.
    num_debug_ops = 0
    for output_tensor_name in debug_mode_tflite_result:
      if 'NumericVerify' in output_tensor_name:
        pos_end_prefix = len('NumericVerify/')
        pos_colon = output_tensor_name.rfind(':')
        self.assertEqual('NumericVerify/', output_tensor_name[:pos_end_prefix])
        tensor_id = int(output_tensor_name[pos_colon + 1:])
        original_tensor_name = output_tensor_name[pos_end_prefix:pos_colon]
        self.assertEqual(original_tensor_name,
                         debug_tensor_details[tensor_id]['name'])
        num_debug_ops += 1
    self.assertEqual(num_debug_ops, 1)
    # The number of debug ops should be equal to that of quantized ops.
    self.assertEqual(num_debug_ops, num_debug_quantize_ops)

  @parameterized.named_parameters(
      ('_PerChannelQuant', False, False),
      ('_PerChannelMlirQuant', False, True),
      ('_PerTensorQuant', True, False),
      ('_PerTensorMlirQuant', True, True),
      ('_PerChannelDynamicRange', False, False, False),
      ('_PerTensorDynamicRange', True, False, False))
  @test_util.run_v2_only
  def testDisablePerChannelQuantization(self, disable_per_channel=False,
                                        enable_mlir_quantizer=False,
                                        representative_dataset=True):
    k_conv_name = 'Conv2D1'
    # Dynamic range quant requires total num elements of filters > 1024.
    k_num_filters = 38
    root, func, calib_gen = self._getIntegerQuantizeModel(k_num_filters)
    quantized_converter = tf.lite.TFLiteConverter.from_concrete_functions(
        [func], root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calib_gen
    quantized_converter.target_spec.supported_ops = [
        lite.OpsSet.TFLITE_BUILTINS
    ]
    quantized_converter.experimental_new_quantizer = enable_mlir_quantizer
    if disable_per_channel:
      quantized_converter._experimental_disable_per_channel = (
          disable_per_channel)
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    detail = next((d for d in interpreter.get_tensor_details()
                   if d['name'] == k_conv_name))
    quant_params = detail['quantization_parameters']
    expected_num_params = 1 if disable_per_channel else k_num_filters
    self.assertLen(quant_params['scales'], expected_num_params)
    self.assertLen(quant_params['zero_points'], expected_num_params)

  @parameterized.named_parameters(('MlirQuantize', True),
                                  ('TocoQuantize', False))
  @test_util.run_v2_only
  def testQuantizeBiasOverflow(self, enable_mlir_quantizer):
    """Tests if the quantizer handles bias overflow by adjusting scales."""
    input_data = np.array([[-1e-3, 1e-3]], dtype=np.float32)

    def calibration_gen():
      yield {'x': input_data}

    root = self._getMatMulModelWithSmallWeights()
    input_data = tf.constant([-1e-3, 1e-3], shape=(1, 2))
    concrete_func = root.matmul.get_concrete_function(input_data)
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    converter.optimizations = [lite.Optimize.DEFAULT]
    converter.representative_dataset = calibration_gen
    converter.experimental_new_quantizer = enable_mlir_quantizer
    quantized_model = converter.convert()

    interpreter = Interpreter(model_content=quantized_model)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    output_details = interpreter.get_output_details()
    output = interpreter.get_tensor(output_details[0]['index'])
    # the inputs and weights are far smaller than the biases, so the final
    # result should be equal to the biases.
    self.assertAllClose(root.bias, output.flatten())

  @test_util.run_v2_only
  def testOpVersion(self):
    @tf.function(
        input_signature=[tf.TensorSpec(shape=[5, 5], dtype=tf.float32)])
    def custom_resize(image):
      # Add "batch" and "channels" dimensions
      image = image[tf.newaxis, ..., tf.newaxis]
      # ResizeBilinear version 3.
      resize1 = tf.compat.v1.image.resize_bilinear(
          image, [2, 2], half_pixel_centers=True)
      # ResizeBilinear version 1.
      resize2 = tf.compat.v1.image.resize_bilinear(image, [2, 2])
      return resize1 + resize2

    concrete_func = custom_resize.get_concrete_function()
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               custom_resize)
    tflite_model = converter.convert()
    model_object = schema_fb.Model.GetRootAsModel(tflite_model, 0)
    model = schema_fb.ModelT.InitFromObj(model_object)

    for operator in model.operatorCodes:
      if operator.builtinCode == schema_fb.BuiltinOperator.RESIZE_BILINEAR:
        # half_pixel_centers is supported by ResizeBilinear version 3.
        self.assertEqual(operator.version, 3)
        break


class FromSavedModelTest(lite_v2_test_util.ModelTest):

  def _createV1SavedModel(self, shape):
    """Create a simple SavedModel."""
    saved_model_dir = os.path.join(self.get_temp_dir(), 'simple_savedmodel')
    with tf.Graph().as_default():
      with tf.compat.v1.Session() as sess:
        in_tensor_1 = tf.compat.v1.placeholder(
            shape=shape, dtype=tf.float32, name='inputB')
        in_tensor_2 = tf.compat.v1.placeholder(
            shape=shape, dtype=tf.float32, name='inputA')
        variable_node = tf.Variable(1.0, name='variable_node')
        out_tensor = in_tensor_1 + in_tensor_2 * variable_node
        inputs = {'x': in_tensor_1, 'y': in_tensor_2}
        outputs = {'z': out_tensor}
        sess.run(tf.compat.v1.variables_initializer([variable_node]))
        saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
    return saved_model_dir

  def _createV2QATSavedModel(self, shape):
    """Create a simple QAT SavedModel in TF 2."""
    saved_model_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    input_name = 'input'
    output_name = 'scores'

    input_tensor = tf.keras.layers.Input((32, 32, 128), name=input_name)
    x = tf.quantization.fake_quant_with_min_max_args(input_tensor, -3.0, 3.0)
    x = tf.keras.layers.Conv2D(1, (3, 3))(x)
    x = tf.quantization.fake_quant_with_min_max_args(x, -3.0, 3.0)
    scores = tf.keras.layers.Reshape((-1,), name=output_name)(x)
    model = tf.keras.Model(input_tensor, scores)
    model.save(saved_model_dir)
    return saved_model_dir, input_name, output_name

  @test_util.run_v2_only
  def testV1SimpleModel(self):
    """Test a SavedModel."""
    with tf.Graph().as_default():
      saved_model_dir = self._createV1SavedModel(shape=[1, 16, 16, 3])

      # Convert model and ensure model is not None.
      converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
      tflite_model = converter.convert()
      self.assertTrue(tflite_model)

      interpreter = Interpreter(model_content=tflite_model)
      interpreter.allocate_tensors()

      input_details = interpreter.get_input_details()
      self.assertLen(input_details, 2)
      self.assertStartsWith(input_details[0]['name'], 'inputA')
      self.assertEqual(np.float32, input_details[0]['dtype'])
      self.assertAllEqual([1, 16, 16, 3], input_details[0]['shape'])
      self.assertEqual((0., 0.), input_details[0]['quantization'])

      self.assertStartsWith(
          input_details[1]['name'],
          'inputB',
      )
      self.assertEqual(np.float32, input_details[1]['dtype'])
      self.assertTrue([1, 16, 16, 3], input_details[1]['shape'])
      self.assertEqual((0., 0.), input_details[1]['quantization'])

      output_details = interpreter.get_output_details()
      self.assertLen(output_details, 1)
      self.assertStartsWith(output_details[0]['name'], 'add')
      self.assertEqual(np.float32, output_details[0]['dtype'])
      self.assertTrue([1, 16, 16, 3], output_details[0]['shape'])
      self.assertEqual((0., 0.), output_details[0]['quantization'])

  @parameterized.named_parameters(
      ('Default', False),
      ('UnfoldLargeConstant', True),
  )
  @test_util.run_v2_only
  def testUnfoldLargeConstant(self, unfold_large_constant):
    """Test unfolding large splat constant in a TF Lite model."""
    saved_model_dir = os.path.join(self.get_temp_dir(), 'simple_savedmodel')
    with tf.Graph().as_default():
      with tf.compat.v1.Session() as sess:
        in_tensor = tf.compat.v1.placeholder(
            shape=[1000, 1000], dtype=tf.float32, name='input')
        constant = tf.constant(value=1, dtype=tf.float32, shape=[1000, 1000])
        out_tensor = in_tensor + constant
        inputs = {'x': in_tensor}
        outputs = {'y': out_tensor}
        saved_model.simple_save(sess, saved_model_dir, inputs, outputs)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter._experimental_unfold_large_splat_constant = unfold_large_constant
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

    model = util._convert_model_from_bytearray_to_object(tflite_model)
    if unfold_large_constant:
      self.assertEqual(model.operatorCodes[0].builtinCode,
                       schema_fb.BuiltinOperator.FILL)
      self.assertEqual(model.operatorCodes[1].builtinCode,
                       schema_fb.BuiltinOperator.ADD)
    else:
      self.assertEqual(model.operatorCodes[0].builtinCode,
                       schema_fb.BuiltinOperator.ADD)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual('input:0', input_details[0]['name'])
    self.assertEqual(np.float32, input_details[0]['dtype'])
    self.assertAllEqual([1000, 1000], input_details[0]['shape'])
    self.assertEqual((0., 0.), input_details[0]['quantization'])

    output_details = interpreter.get_output_details()
    self.assertEqual('add:0', output_details[0]['name'])
    self.assertEqual(np.float32, output_details[0]['dtype'])
    self.assertAllEqual([1000, 1000], output_details[0]['shape'])
    self.assertEqual((0., 0.), output_details[0]['quantization'])

    interpreter.set_tensor(input_details[0]['index'],
                           np.ones(shape=[1000, 1000], dtype=np.float32))
    interpreter.invoke()
    self.assertAllEqual(
        np.full(shape=[1000, 1000], fill_value=2.0, dtype=np.float32),
        interpreter.get_tensor(output_details[0]['index']))

  @test_util.run_v2_only
  def testTF1HubFormattedModel(self):
    """Test a TF1 hub formatted model."""
    saved_model_dir = self._createV1SavedModel(shape=[1, 16, 16, 3])

    # TF1 hub model is based on V1 saved model and they omit the saved model
    # schema version setting.
    saved_model_proto = parse_saved_model(saved_model_dir)
    saved_model_proto.saved_model_schema_version = 0

    saved_model_pb_file_path = os.path.join(saved_model_dir, 'saved_model.pb')
    with file_io.FileIO(saved_model_pb_file_path, 'wb') as writer:
      writer.write(saved_model_proto.SerializeToString())

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

  def _createV1ModelWithHashTableInitializer(self):
    # Create a v1 saved model with hash table initializers.
    tf.compat.v1.disable_eager_execution()
    saved_model_dir = os.path.join(self.get_temp_dir(),
                                   'savedmodel_with_hashtable')

    table_initializer = tf.lookup.KeyValueTensorInitializer(
        keys=['a', 'b', 'c', 'd'],
        values=[1, 2, 3, 4],
        key_dtype=tf.string,
        value_dtype=tf.int64)
    table = tf.lookup.StaticHashTable(
        table_initializer, default_value=tf.constant(-1, dtype=tf.int64))

    x = tf.compat.v1.placeholder(tf.string, shape=(), name='input')
    y = table.lookup(x)

    tensor_info_x = tf.compat.v1.saved_model.utils.build_tensor_info(x)
    tensor_info_y = tf.compat.v1.saved_model.utils.build_tensor_info(y)

    signature_def_map, init_op, assets_collection = {
        'serving_default':
            (tf.compat.v1.saved_model.signature_def_utils.build_signature_def(
                inputs={'x': tensor_info_x},
                outputs={'y': tensor_info_y},
                method_name='some_function'))
    }, tf.compat.v1.tables_initializer(), None

    sess = tf.compat.v1.Session()
    sess.run(tf.compat.v1.initializers.global_variables())

    builder = tf.compat.v1.saved_model.builder.SavedModelBuilder(
        saved_model_dir)
    builder.add_meta_graph_and_variables(
        sess, [tf.compat.v1.saved_model.tag_constants.SERVING],
        signature_def_map,
        main_op=init_op,
        assets_collection=assets_collection,
        strip_default_attrs=True)
    builder.save()

    # Restore TF v2 behavior.
    tf.compat.v1.reset_default_graph()
    tf.compat.v1.enable_eager_execution()
    return saved_model_dir

  @test_util.run_v2_only
  def testModelWithHashTableInitializer(self):
    """Test a model with saved_model's session initializer for hash tables."""
    saved_model_dir = self._createV1ModelWithHashTableInitializer()

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    tflite_model = converter.convert()

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_data = np.array(['a', 'b', 'c', 'z'], dtype=np.string_)
    interpreter.resize_tensor_input(
        input_details[0]['index'], [4], strict=False)
    interpreter.allocate_tensors()

    interpreter.set_tensor(input_details[0]['index'], input_data)

    # Invoke multiple times to ensure the initializer graph runs only once.
    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual([1, 2, 3, -1], list(actual_value))

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual([1, 2, 3, -1], list(actual_value))

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual([1, 2, 3, -1], list(actual_value))

  def _createV1ModelWithMutableHashTable(self):
    # Create a v1 saved model with mutable hash table.
    tf.compat.v1.disable_eager_execution()
    saved_model_dir = os.path.join(self.get_temp_dir(),
                                   'savedmodel_with_mutable_hashtable')

    table = tf.raw_ops.MutableHashTableV2(
        key_dtype=tf.string, value_dtype=tf.int64)
    x = tf.compat.v1.placeholder(tf.string, shape=(), name='input')
    keys = tf.constant(['a', 'b'], tf.string)
    values = tf.constant([1, 5], tf.int64)
    default_value = tf.constant(-1, tf.int64)
    insert_call = tf.raw_ops.LookupTableInsertV2(
        table_handle=table, keys=keys, values=values)
    with tf.control_dependencies([insert_call]):
      y = tf.raw_ops.LookupTableFindV2(
          table_handle=table, keys=x, default_value=default_value)

    tensor_info_x = tf.compat.v1.saved_model.utils.build_tensor_info(x)
    tensor_info_y = tf.compat.v1.saved_model.utils.build_tensor_info(y)

    signature_def_map, init_op, assets_collection = {
        'serving_default':
            (tf.compat.v1.saved_model.signature_def_utils.build_signature_def(
                inputs={'x': tensor_info_x},
                outputs={'y': tensor_info_y},
                method_name='some_function'))
    }, tf.compat.v1.tables_initializer(), None

    sess = tf.compat.v1.Session()

    builder = tf.compat.v1.saved_model.builder.SavedModelBuilder(
        saved_model_dir)
    builder.add_meta_graph_and_variables(
        sess, [tf.compat.v1.saved_model.tag_constants.SERVING],
        signature_def_map,
        main_op=init_op,
        assets_collection=assets_collection,
        strip_default_attrs=True)
    builder.save()

    # Restore TF v2 behavior.
    tf.compat.v1.reset_default_graph()
    tf.compat.v1.enable_eager_execution()
    return saved_model_dir

  @test_util.run_v2_only
  def testModelWithMutableHashTable(self):
    """Test a model with saved_model's session initializer for hash tables."""
    saved_model_dir = self._createV1ModelWithMutableHashTable()

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_data = np.array(['a', 'b', 'c'], dtype=np.string_)
    interpreter.resize_tensor_input(
        input_details[0]['index'], [3], strict=False)
    interpreter.allocate_tensors()

    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual([1, 5, -1], list(actual_value))

  @test_util.run_v2_only
  def testConstModel(self):
    """Test a basic model with functions to make sure functions are inlined."""
    input_data = tf.constant(1., shape=[1])
    root = tracking.AutoTrackable()
    root.f = tf.function(lambda x: 2. * x)
    to_save = root.f.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, to_save)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @test_util.run_v2_only
  def testVariableModel(self):
    """Test a basic model with Variables with saving/loading the SavedModel."""
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    to_save = root.f.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, to_save)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @parameterized.named_parameters(('EnableResourceVariables', True),
                                  ('DisableResourceVariables', False))
  @test_util.run_v2_only
  def testNativeVariablesModel(self, enable_resource_variables):
    """Test a basic model with Variables with saving/loading the SavedModel."""
    root = self._getSimpleModelWithVariables()
    input_data = tf.constant(1., shape=[1, 10])
    to_save = root.assign_add.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, to_save)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    converter.experimental_enable_resource_variables = enable_resource_variables

    if not enable_resource_variables:
      with self.assertRaises(convert.ConverterError) as error:
        tflite_model = converter.convert()
      self.assertIn(
          'Variable constant folding is failed. Please consider using enabling '
          '`experimental_enable_resource_variables` flag in the TFLite '
          'converter object.',
          str(error.exception))
      return

    # Enable resource variables.
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.assign_add(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    for tf_result, tflite_result in zip(expected_value, actual_value[0]):
      self.assertAllClose(tf_result, tflite_result, atol=1e-05)

  @test_util.run_v2_only
  def testSignatures(self):
    """Test values for `signature_keys` argument."""
    root = self._getSimpleVariableModel()
    input_data = tf.constant(1., shape=[1])
    to_save = root.f.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, to_save)

    # Convert model with invalid `signature_keys`.
    with self.assertRaises(ValueError) as error:
      _ = lite.TFLiteConverterV2.from_saved_model(
          save_dir, signature_keys=['INVALID'])
    self.assertIn("Invalid signature key 'INVALID'", str(error.exception))

    # Convert model with empty `signature_keys`.
    converter = lite.TFLiteConverterV2.from_saved_model(
        save_dir, signature_keys=[])
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value.numpy(), actual_value)

  @test_util.run_v2_only
  def testSignatureDefsWithFullIntegerQuantization(self):
    # SETUP
    # 1. Define input shapes
    tf_input_shape = (32, 32, 128)
    tflite_input_shape = (1,) + tf_input_shape
    # 2. Define model
    tf_saved_model_dir, input_name, output_name = (
        self._createV2QATSavedModel(tf_input_shape))

    # MODEL 1: TFLite (float) model
    # 1. Create TFLite model
    converter = tf.lite.TFLiteConverter.from_saved_model(tf_saved_model_dir)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_model = converter.convert()
    # 2. Initialize the Intepreter
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    interpreter.resize_tensor_input(input_details['index'], tflite_input_shape)
    interpreter.allocate_tensors()
    signature_list = interpreter._get_full_signature_list()['serving_default']
    # 3. (Skip) Verify that signature def input/output tensors are in the model.
    # 4. Evaluate the model
    input_data = np.random.random(tflite_input_shape).astype(np.float32)
    result = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model, 'serving_default', {input_name: input_data})[output_name]

    # MODEL 2: TFLite (full integer quantized) model
    # 1. Create TFLite model
    converter = tf.lite.TFLiteConverter.from_saved_model(tf_saved_model_dir)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    tflite_model_quant = converter.convert()
    # 2. Initialize the Intepreter
    interpreter = Interpreter(model_content=tflite_model_quant)
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    interpreter.resize_tensor_input(input_details['index'], tflite_input_shape)
    interpreter.allocate_tensors()
    # 3. Verify that signature def input/output tensors are in the model.
    all_indices = {item['index'] for item in interpreter.get_tensor_details()}
    signature_list = interpreter._get_full_signature_list()['serving_default']
    input_tensor_indices = set(signature_list['inputs'].values())
    assert input_tensor_indices.issubset(all_indices)
    output_tensor_indices = set(signature_list['outputs'].values())
    assert output_tensor_indices.issubset(all_indices)

    # 4. Evaluate the model
    input_data = np.random.random(tflite_input_shape)
    input_scale, input_zero_point = input_details['quantization']
    if (input_scale, input_zero_point) != (0.0, 0):
      input_data = input_data / input_scale + input_zero_point
      input_data = input_data.astype(input_details['dtype'])
    result_quant = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model_quant, 'serving_default',
        {input_name: input_data})[output_name]
    output_scale, output_zero_point = output_details['quantization']
    if (output_scale, output_zero_point) != (0.0, 0):
      result_quant = result_quant.astype(np.float32)
      result_quant = (result_quant - output_zero_point) * output_scale

    # COMPARE: Validate that results from both models are approx. the same.
    root_mean_squared = np.sqrt(np.mean((result-result_quant)**2))
    assert root_mean_squared < 1.0

  @test_util.run_v2_only
  def testSignatureDefs(self):
    """Test converting SignatureDef is correct and uses SignatureDef API."""
    root = self._getMultiFunctionModel()
    input_data_0 = tf.constant(1., shape=[1])
    input_data_1 = tf.constant(3., shape=[1])
    mul_add_func = root.mul_add.get_concrete_function(input_data_1,
                                                      input_data_0)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, {'mul_add': mul_add_func})

    converter = lite.TFLiteConverterV2.from_saved_model(
        save_dir, signature_keys=['mul_add'])
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.mul_add(input_data_1, input_data_0)
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    results = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model, 'mul_add', {
            'y': input_data_0,
            'x': input_data_1
        })
    self.assertEqual(list(results.keys()), ['output_0'])
    self.assertEqual(expected_value.numpy(), results['output_0'])

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 1)
    self.assertEqual(list(signature_defs.keys()), ['mul_add'])
    self.assertEqual(len(signature_defs.values()), 1)
    self.assertEqual(
        list(signature_defs['mul_add'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['mul_add']['inputs'], ['x', 'y'])
    self.assertEqual(list(signature_defs['mul_add']['outputs']), ['output_0'])

  @test_util.run_v2_only
  def testSignatureDefsWithDefaultValue(self):
    """Test converting SignatureDef is correct and uses SignatureDef API.

    This test uses None as signature_key to test default behavior.
    """
    root = self._getMultiFunctionModel()
    input_data_0 = tf.constant(1., shape=[1])
    input_data_1 = tf.constant(3., shape=[1])
    mul_add_func = root.mul_add.get_concrete_function(input_data_1,
                                                      input_data_0)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, {'mul_add': mul_add_func})

    converter = lite.TFLiteConverterV2.from_saved_model(
        save_dir, signature_keys=['mul_add'])
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.mul_add(input_data_1, input_data_0)
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    results = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model, None, {
            'y': input_data_0,
            'x': input_data_1
        })
    self.assertEqual(list(results.keys()), ['output_0'])
    self.assertEqual(expected_value.numpy(), results['output_0'])

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 1)
    self.assertEqual(list(signature_defs.keys()), ['mul_add'])
    self.assertEqual(len(signature_defs.values()), 1)
    self.assertEqual(
        list(signature_defs['mul_add'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['mul_add']['inputs'], ['x', 'y'])
    self.assertEqual(list(signature_defs['mul_add']['outputs']), ['output_0'])

  @test_util.run_v2_only
  def testSignatureDefsQuantizedModel(self):
    """Test converting SignatureDef on quantized model."""
    root = self._getMultiFunctionModel()
    input_data_0 = tf.constant(1., shape=[1])
    input_data_1 = tf.constant(3., shape=[1])
    mul_add_func = root.mul_add.get_concrete_function(input_data_1,
                                                      input_data_0)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, {'mul_add': mul_add_func})

    converter = lite.TFLiteConverterV2.from_saved_model(
        save_dir, signature_keys=['mul_add'])

    def representative_dataset_gen():
      for _ in range(2):
        yield {
            'x':
                np.random.uniform(low=0, high=1,
                                  size=(1, 1)).astype(np.float32),
            'y':
                np.random.uniform(low=0, high=1, size=(1, 1)).astype(np.float32)
        }

    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    tflite_model = converter.convert()

    # Check signatures are valid from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 1)
    self.assertEqual(list(signature_defs.keys()), ['mul_add'])
    self.assertEqual(len(signature_defs.values()), 1)
    self.assertEqual(
        list(signature_defs['mul_add'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['mul_add']['inputs'], ['x', 'y'])
    self.assertEqual(list(signature_defs['mul_add']['outputs']), ['output_0'])

  @test_util.run_v2_only
  def testMultipleFunctionModel(self):
    """Convert multiple functions in a multi-functional model."""
    root = self._getMultiFunctionModel()
    input_data = tf.constant(1., shape=[1])
    add_func = root.add.get_concrete_function(input_data)
    sub_func = root.sub.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, {'add': add_func, 'sub': sub_func})

    # Try converting multiple functions.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    interpreter = tf.lite.Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 2)
    self.assertEqual(list(signature_defs.keys()), ['add', 'sub'])
    self.assertEqual(len(signature_defs.values()), 2)
    self.assertEqual(list(signature_defs['add'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['add']['inputs'], ['x'])
    self.assertEqual(list(signature_defs['add']['outputs']), ['output_0'])
    self.assertEqual(list(signature_defs['sub'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['sub']['inputs'], ['x'])
    self.assertEqual(list(signature_defs['sub']['outputs']), ['output_0'])

    # Verify the Signature runner executions.
    add_signature_runner = interpreter.get_signature_runner('add')
    add_output = add_signature_runner(x=input_data)
    self.assertEqual(add_output['output_0'], 3)

    sub_signature_runner = interpreter.get_signature_runner('sub')
    sub_output = sub_signature_runner(x=input_data)
    self.assertEqual(sub_output['output_0'], -2)

  @test_util.run_v2_only
  def testMultipleFunctionModelWithSharedWeight(self):
    """Convert multiple functions with the shared weight."""
    root = self._getMultiFunctionModelWithSharedWeight()
    input_data = tf.constant(1., shape=[1])
    add_func = root.add.get_concrete_function(input_data)
    sub_func = root.sub.get_concrete_function(input_data)
    mul_func = root.mul.get_concrete_function(input_data)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, {'add': add_func, 'sub': sub_func, 'mul': mul_func})

    # Try converting multiple functions.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Make sure that the weight tensors are shared.
    self.assertLess(len(tflite_model), 1100000)

    # TODO(b/184696047): Write down the test codes for multiple signature
    #                    runners once the Python API is ready to use.
    interpreter = tf.lite.Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    self.assertLen(signature_defs, 3)
    add_signature_runner = interpreter.get_signature_runner('add')
    sub_signature_runner = interpreter.get_signature_runner('sub')
    mul_signature_runner = interpreter.get_signature_runner('mul')
    self.assertIsNotNone(add_signature_runner)
    self.assertIsNotNone(sub_signature_runner)
    self.assertIsNotNone(mul_signature_runner)

  @test_util.run_v2_only
  def testNoConcreteFunctionModel(self):
    root = self._getMultiFunctionModel()

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir)

    with self.assertRaises(ValueError) as error:
      _ = lite.TFLiteConverterV2.from_saved_model(save_dir)
    self.assertIn('Only support at least one signature key.',
                  str(error.exception))

  @test_util.run_v2_only
  def testKerasSequentialModel(self):
    """Test a simple sequential tf.Keras model."""
    input_data = tf.constant(1., shape=[1, 1])

    x = np.array([[1.], [2.]])
    y = np.array([[2.], [4.]])

    model = tf.keras.models.Sequential([
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(1),
    ])
    model.compile(optimizer='sgd', loss='mean_squared_error')
    model.fit(x, y, epochs=1)

    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(model, save_dir)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = model.predict(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value, actual_value)

  @test_util.run_v2_only
  def testGraphDebugInfo(self):
    """Test a SavedModel has debug info captured."""
    input_data = tf.constant(1., shape=[1])
    root = tracking.AutoTrackable()
    root.f = tf.function(lambda x: 2. * x)
    to_save = root.f.get_concrete_function(input_data)
    options = save_options.SaveOptions(save_debug_info=True)
    save_dir = os.path.join(self.get_temp_dir(), 'saved_model')
    save(root, save_dir, to_save, options)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(save_dir)
    converter.convert()
    self._assertValidDebugInfo(converter._debug_info)

  @test_util.run_v2_only
  def testFallbackPath(self):
    """Test a SavedModel fallback path using old converter."""
    saved_model_dir = self._createV1SavedModel(shape=[1, 16, 16, 3])

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.experimental_new_converter = False
    tflite_model = converter.convert()

    self.assertTrue(tflite_model)

  @test_util.run_v2_only
  def testNonStatefulConvLSTM2D(self):
    """Test saved model with non stateful ConvLSTM2D keras layer."""
    # Create keras model
    model = tf.keras.Sequential([
        tf.keras.layers.ConvLSTM2D(
            32, (3, 3),
            padding='same',
            return_sequences=True,
            stateful=False,
            batch_input_shape=(1, 1, 10, 10, 1))
    ])
    model.compile()

    # Export the keras model to saved model.
    saved_model_dir = os.path.join(self.get_temp_dir(), 'conv_lstm_2d')
    model.save(saved_model_dir, save_format='tf', include_optimizer=False)

    converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

  @test_util.run_v2_only
  def testKerasConvLSTM2DWithMoreThanOneDilationRate(self):
    input_tensor = tf.keras.layers.Input(
        batch_size=8,
        shape=[9, 10, 11, 12],
        name='input_tensor',
        dtype=tf.float32)

    output = tf.keras.layers.ConvLSTM2D(
        filters=3,
        kernel_size=3,
        strides=1,
        padding='VALID',
        dilation_rate=2,
        use_bias=False,
        bias_initializer='ones',
        data_format='channels_last')(
            input_tensor)

    model = tf.keras.Model(inputs=[input_tensor], outputs=output)
    model.compile(
        optimizer='adam',
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy'])

    # Export the keras model to saved model.
    saved_model_dir = os.path.join(self.get_temp_dir(),
                                   'conv_lstm_2d_with_dilation_rate')
    model.save(saved_model_dir, save_format='tf', include_optimizer=False)

    converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

  def _createUnknownInputShapeModel(self):
    """Create a simple SavedModel with unknown input."""
    saved_model_dir = os.path.join(self.get_temp_dir(), 'unknown_input_shape')
    with tf.Graph().as_default():
      with tf.compat.v1.Session() as sess:
        unknown_shape = tf.TensorShape(None)
        in_tensor = tf.compat.v1.placeholder(
            shape=unknown_shape, dtype=tf.float32, name='input')
        out_tensor = in_tensor + in_tensor
        inputs = {'input': in_tensor}
        outputs = {'output': out_tensor}
        saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
    return saved_model_dir

  @test_util.run_v2_only
  def testUnknownInputShapeModel(self):
    """Test a SavedModel with an unknown input shape."""
    saved_model_dir = self._createUnknownInputShapeModel()

    converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_data = np.array([1., 2., 3.], dtype=np.float32)
    interpreter.resize_tensor_input(
        input_details[0]['index'], [3], strict=False)
    interpreter.allocate_tensors()

    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual([2., 4., 6.], list(actual_value))

  @parameterized.named_parameters(
      ('_PerChannelQuant', False, False),
      ('_PerChannelMlirQuant', False, True),
      ('_PerTensorQuant', True, False),
      ('_PerTensorMlirQuant', True, True),
      ('_PerChannelDynamicRange', False, False, True),
      ('_PerTensorDynamicRange', True, False, True))
  @test_util.run_v2_only
  def testDisablePerChannelQuantization(self, disable_per_channel=False,
                                        enable_mlir_quantizer=False,
                                        representative_dataset=True):
    # Dynamic range quant requires total num elements of filters > 1024.
    k_num_filters = 38
    model = tf.keras.models.Sequential([
        tf.keras.layers.Conv2D(k_num_filters, (3, 3), activation='relu')
    ])
    model.build(input_shape=(1, 5, 5, 3))
    saved_model_dir = os.path.join(self.get_temp_dir(), 'conv_saved_model')
    save(model, saved_model_dir)
    k_conv_name = 'sequential/conv2d/Conv2D1'
    quantized_converter = tf.lite.TFLiteConverter.from_saved_model(
        saved_model_dir)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    if representative_dataset:
      def calib_gen():
        for _ in range(5):
          yield [np.random.uniform(-1, 1, size=(1, 5, 5, 3)).astype(np.float32)]
      quantized_converter.representative_dataset = calib_gen
    quantized_converter.target_spec.supported_ops = [
        lite.OpsSet.TFLITE_BUILTINS
    ]
    quantized_converter.experimental_new_quantizer = enable_mlir_quantizer
    if disable_per_channel:
      quantized_converter._experimental_disable_per_channel = (
          disable_per_channel)
    quantized_tflite_model = quantized_converter.convert()
    self.assertIsNotNone(quantized_tflite_model)

    interpreter = Interpreter(model_content=quantized_tflite_model)
    interpreter.allocate_tensors()
    detail = next((d for d in interpreter.get_tensor_details()
                   if d['name'] == k_conv_name))
    quant_params = detail['quantization_parameters']
    expected_num_params = k_num_filters
    if disable_per_channel:
      expected_num_params = 1
    self.assertLen(quant_params['scales'], expected_num_params)
    self.assertLen(quant_params['zero_points'], expected_num_params)


class FromKerasModelTest(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testSequentialModel(self):
    """Test a simple sequential tf.Keras model."""
    input_data = tf.constant(1., shape=[1, 1])

    # Create a simple Keras model.
    x = np.array([[1.], [2.]])
    y = np.array([[2.], [4.]])

    model = tf.keras.models.Sequential([
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(units=1, input_shape=[1])
    ])
    model.compile(optimizer='sgd', loss='mean_squared_error')
    model.fit(x, y, epochs=1)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = model.predict(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    self.assertEqual(expected_value, actual_value)

  @test_util.run_v2_only
  def testSequentialMultiInputOutputModel(self):
    """Test a tf.Keras model with multiple inputs and outputs."""
    left_input_data = tf.constant(1., shape=[1, 3])
    right_input_data = tf.constant(1., shape=[1, 3])

    # Create a simple Keras model.
    input_a_np = np.random.random((10, 3))
    input_b_np = np.random.random((10, 3))
    output_c_np = np.random.random((10, 3))
    output_d_np = np.random.random((10, 2))

    input_a = tf.keras.layers.Input(shape=(3,), name='input_a')
    input_b = tf.keras.layers.Input(shape=(3,), name='input_b')

    dense = tf.keras.layers.Dense(8, name='dense_1')
    interm_a = dense(input_a)
    interm_b = dense(input_b)
    merged = tf.keras.layers.concatenate([interm_a, interm_b], name='merge')

    output_c = tf.keras.layers.Dense(
        3, activation='softmax', name='dense_2')(
            merged)
    output_d = tf.keras.layers.Dense(
        2, activation='softmax', name='dense_3')(
            merged)

    model = tf.keras.models.Model(
        inputs=[input_a, input_b], outputs=[output_c, output_d])
    model.compile(optimizer='sgd', loss='mean_squared_error')
    model.fit([input_a_np, input_b_np], [output_c_np, output_d_np], epochs=1)

    # Convert model and ensure model is not None.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    tflite_model = converter.convert()

    # Check values from converted model.
    input_data = [left_input_data, right_input_data]
    expected_value = model.predict(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, input_data)
    for tf_result, tflite_result in zip(expected_value, actual_value):
      self.assertAllClose(tf_result, tflite_result, atol=1e-05)

  @test_util.run_v2_only
  def testGraphDebugInfo(self):
    """Test a tf.Keras model has debug info captured."""
    # Create a simple Keras model.
    x = [-1, 0, 1, 2, 3, 4]
    y = [-3, -1, 1, 3, 5, 7]
    model = tf.keras.models.Sequential(
        [tf.keras.layers.Dense(units=1, input_shape=[1])])
    model.compile(optimizer='sgd', loss='mean_squared_error')
    model.fit(x, y, epochs=1)
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    converter.convert()
    self._assertValidDebugInfo(converter._debug_info)

  @test_util.run_v2_only
  def testKerasFallbackPath(self):
    """Test keras model which failed when exporting to the saved model."""
    input_data = tf.constant(
        np.array(np.random.random_sample((20)), dtype=np.float32))

    class Model(tf.keras.Model):

      def __init__(self):
        super(Model, self).__init__()
        # A None name will cause a failure in exporting to a saved model.
        self.shared_weights = self.add_weight(
            name=None,
            shape=(20, 1),
            dtype=tf.float32,
            initializer=tf.random_normal_initializer(
                mean=0.0, stddev=300**(-0.5)))

      def call(self, x):
        return tf.add(self.shared_weights, x)

    # Building the model.
    model = Model()
    model.compile(optimizer='sgd', loss='mean_squared_error')
    model.fit(input_data, input_data, epochs=1)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)

  @test_util.run_v2_only
  def testSignatureDefs(self):
    """Test converting SignatureDef is correct and uses SignatureDef API."""
    keras_model = tf.keras.Sequential([
        tf.keras.layers.Conv2D(
            32,
            kernel_size=3,
            padding='same',
            activation='relu',
            input_shape=(32, 32, 3),
            name='tensor'),
        tf.keras.layers.Dense(10, name='output_tensor')
    ])

    converter = lite.TFLiteConverterV2.from_keras_model(keras_model)
    tflite_model = converter.convert()

    # Check values from converted model.
    input_data = tf.constant(
        np.random.uniform(-1, 1, size=(1, 32, 32, 3)).astype(np.float32))
    expected_value = keras_model(input_data)
    interpreter = Interpreter(model_content=tflite_model)
    signature_defs = interpreter.get_signature_list()
    results = self._evaluateTFLiteModelUsingSignatureDef(
        tflite_model, 'serving_default', {'tensor_input': input_data})
    self.assertEqual(list(results.keys()), ['output_tensor'])
    self.assertAllClose(expected_value.numpy(), results['output_tensor'])

    # Verify the SignatureDef structure returned is as expected.
    self.assertEqual(len(signature_defs), 1)
    self.assertEqual(list(signature_defs.keys()), ['serving_default'])
    self.assertEqual(len(signature_defs.values()), 1)
    self.assertEqual(
        list(signature_defs['serving_default'].keys()), ['inputs', 'outputs'])
    self.assertCountEqual(signature_defs['serving_default']['inputs'],
                          ['tensor_input'])
    self.assertEqual(
        list(signature_defs['serving_default']['outputs']), ['output_tensor'])


class ControlFlowTest(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testCond(self):
    input_data = {
        'x': tf.constant([1., 2.], shape=[1, 2]),
        'b': tf.constant(True)
    }

    weights = tf.Variable([[0.1, 0.2], [0.3, 0.4]], dtype=tf.float32)

    def true_fn(x):
      return tf.matmul(x, weights)

    def false_fn(x):
      return tf.add(x, weights)

    @tf.function(input_signature=[
        tf.TensorSpec(shape=[1, 2], dtype=tf.float32),
        tf.TensorSpec(shape=(), dtype=tf.bool)
    ])
    def model(x, b):
      return tf.cond(
          b, true_fn=lambda: true_fn(x), false_fn=lambda: false_fn(x))

    concrete_func = model.get_concrete_function()

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(**input_data)
    actual_value = self._evaluateTFLiteModel(
        tflite_model, [input_data['x'], input_data['b']])[0]
    self.assertAllClose(expected_value, actual_value)

  @test_util.run_v2_only
  def testConverterErrorOnControlFlowV1Ops(self):
    filename = resource_loader.get_path_to_datafile(
        'testdata/control_flow_v1_saved_model')
    converter = lite.TFLiteConverterV2.from_saved_model(filename)
    with self.assertRaises(convert.ConverterError) as error:
      converter.convert()
    self.assertIn(
        'Failed to functionalize Control Flow V1 ops. Consider using Control '
        'Flow V2 ops instead. See https://www.tensorflow.org/api_docs/python/'
        'tf/compat/v1/enable_control_flow_v2.', str(error.exception))

  @test_util.run_v2_only
  def testStaticRnn(self):
    input_data = tf.constant(
        np.array(np.random.random_sample((3, 10)), dtype=np.float32))

    cell = tf.compat.v1.nn.rnn_cell.LSTMCell(10)

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[3, 10], dtype=tf.float32)])
    def model(x):
      seq = tf.split(x, 3, 0)
      return tf.compat.v1.nn.static_rnn(
          cell, seq, dtype=tf.float32, sequence_length=[1])

    concrete_func = model.get_concrete_function()

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(input_data)[0]
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    for expected, actual in zip(expected_value, actual_value):
      self.assertAllClose(expected, actual)

  @test_util.run_v2_only
  def testWhileLoop(self):
    input_data = tf.constant([1., 2., 3., 4.], shape=[2, 2])

    weights = tf.Variable([[0.1, 0.2], [0.3, 0.4]], dtype=tf.float32)

    def condition(x):
      return tf.reduce_sum(x) < 100

    def body(x):
      return tf.add(x, weights)

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[2, 2], dtype=tf.float32)])
    def model(x):
      return tf.while_loop(condition, body, [x])

    concrete_func = model.get_concrete_function()

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(input_data)[0]
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]
    self.assertAllClose(expected_value, actual_value)

  @test_util.run_v2_only
  def testDynamicRnn(self):
    input_data = tf.constant(
        np.array(np.random.random_sample((3, 10, 10)), dtype=np.float32))

    cell = tf.compat.v1.nn.rnn_cell.LSTMCell(10)

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[3, 10, 10], dtype=tf.float32)])
    def model(x):
      return tf.compat.v1.nn.dynamic_rnn(cell, x, dtype=tf.float32)

    concrete_func = model.get_concrete_function()

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])
    for expected, actual in zip(expected_value, actual_value):
      if not isinstance(expected, ops.EagerTensor):
        expected = expected.c
      self.assertAllClose(expected, actual)

  @parameterized.named_parameters(
      ('LSTMBatchSizeOne', tf.keras.layers.LSTM, True),
      ('LSTM', tf.keras.layers.LSTM, False),
      ('SimpleRNNBatchSizeOne', tf.keras.layers.SimpleRNN, True),
      ('SimpleRNN', tf.keras.layers.SimpleRNN, False),
      ('GRUBatchSizeOne', tf.keras.layers.GRU, True),
      ('GRU', tf.keras.layers.GRU, False))
  @test_util.run_v2_only
  def testKerasRNN(self, rnn_layer, default_to_single_batch):
    input_data = tf.constant(
        np.array(np.random.random_sample((1, 10, 10)), dtype=np.float32))
    rnn_obj = rnn_layer(units=10, input_shape=(10, 10))
    model = tf.keras.models.Sequential([
        tf.keras.layers.Input(shape=(10, 10), name='input'),
        rnn_obj,
    ])

    # Convert model.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    converter._experimental_default_to_single_batch_in_tensor_list_ops = default_to_single_batch
    if not default_to_single_batch:
      converter.target_spec.supported_ops = [
          tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
      ]
    tflite_model = converter.convert()
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]

    # Check values from converted model.
    expected_value = model.predict(input_data)
    self.assertAllClose(expected_value, actual_value, atol=1e-05)

  @parameterized.named_parameters(('LSTM', tf.keras.layers.LSTM),
                                  ('SimpleRNN', tf.keras.layers.SimpleRNN),
                                  ('GRU', tf.keras.layers.GRU))
  @test_util.run_v2_only
  def testKerasRNNMultiBatches(self, rnn_layer):
    input_data = tf.constant(
        np.array(np.random.random_sample((4, 10, 10)), dtype=np.float32))
    # Specify a fixed batch size(4) for the test model.
    x = tf.keras.layers.Input(batch_shape=(4, 10, 10))
    y = rnn_layer(units=10, input_shape=(10, 10))(x)
    model = tf.keras.Model(inputs=[x], outputs=[y])

    # Convert model.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    tflite_model = converter.convert()
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]

    # Check values from converted model.
    expected_value = model.predict(input_data)
    self.assertAllClose(expected_value, actual_value, atol=1e-05)

  @parameterized.named_parameters(('ForceToUseBatchSizeOne', True),
                                  ('DontForceToUseBatchSizeOne', False))
  @test_util.run_v2_only
  def testKerasBidirectionalRNNReturnSequence(self, default_to_single_batch):
    input_data = tf.constant(
        np.array(np.random.random_sample((1, 10, 10)), dtype=np.float32))
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Input(shape=(10, 10), name='input'))
    model.add(
        tf.keras.layers.Bidirectional(
            tf.keras.layers.LSTM(units=10, return_sequences=True),
            input_shape=(10, 10)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(5))
    model.add(tf.keras.layers.Activation('softmax'))

    # Convert model.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    converter._experimental_default_to_single_batch_in_tensor_list_ops = default_to_single_batch
    if not default_to_single_batch:
      converter.target_spec.supported_ops = [
          tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
      ]
    tflite_model = converter.convert()
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]

    # Check values from converted model.
    expected_value = model.predict(input_data)
    self.assertAllClose(expected_value, actual_value, atol=1e-05)

  @parameterized.named_parameters(('ForceToUseBatchSizeOne', True),
                                  ('DontForceToUseBatchSizeOne', False))
  @test_util.run_v2_only
  def testKerasBidirectionalRNN(self, default_to_single_batch):
    input_data = tf.constant(
        np.array(np.random.random_sample((1, 10, 10)), dtype=np.float32))
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Input(shape=(10, 10), name='input'))
    model.add(tf.keras.layers.Bidirectional(tf.keras.layers.LSTM(units=10)))
    model.add(tf.keras.layers.Dense(5))
    model.add(tf.keras.layers.Activation('softmax'))

    # Convert model.
    converter = lite.TFLiteConverterV2.from_keras_model(model)
    converter._experimental_default_to_single_batch_in_tensor_list_ops = default_to_single_batch
    if not default_to_single_batch:
      converter.target_spec.supported_ops = [
          tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
      ]
    tflite_model = converter.convert()
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]

    # Check values from converted model.
    expected_value = model.predict(input_data)
    self.assertAllClose(expected_value, actual_value, atol=1e-05)


class GrapplerTest(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testConstantFolding(self):
    # Constant folding handles the tf.broadcast_to operation which was not
    # supported by the TFLite at the time this test was added.
    input_data = tf.constant([1., 2., 3., 4., 5., 6., 7., 8., 9.], shape=[3, 3])

    @tf.function
    def func(x):
      y_const = tf.constant([1., 2., 3.])
      y_broadcast = tf.broadcast_to(y_const, [3, 3])
      return tf.matmul(x, y_broadcast)

    root = tracking.AutoTrackable()
    root.f = func
    concrete_func = root.f.get_concrete_function(input_data)

    # Convert model.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               root)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = root.f(input_data)
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]
    self.assertAllClose(expected_value, actual_value)

    # Enable hybrid quantization, same result
    converter.optimizations = [lite.Optimize.DEFAULT]
    tflite_model = converter.convert()
    actual_value = self._evaluateTFLiteModel(tflite_model, [input_data])[0]
    self.assertAllClose(expected_value, actual_value)


class UnknownShapes(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testMatMul(self):
    input_data = tf.constant(
        np.array(np.random.random_sample((10, 4)), dtype=np.float32))

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[None, 4], dtype=tf.float32)])
    def model(in_tensor):
      shape = tf.shape(in_tensor)
      fill = tf.transpose(tf.fill(shape, 1.))
      return tf.matmul(fill, in_tensor)

    concrete_func = model.get_concrete_function()

    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(input_data)
    actual_value = self._evaluateTFLiteModel(
        tflite_model, [input_data], input_shapes=[([-1, 4], [10, 4])])[0]
    self.assertAllClose(expected_value, actual_value, atol=1e-06)

  def _getIntegerQuantizeModelWithUnknownShapes(self):
    np.random.seed(0)

    @tf.function(
        input_signature=[tf.TensorSpec(shape=[None, 33], dtype=tf.float32)])
    def model(input_tensor):
      """Define a model with tf.MatMul and unknown shapes."""
      # We need the tensor to have more than 1024 elements for quantize_weights
      # to kick in. Thus, the [33, 33] shape.
      const_tensor = tf.constant(
          np.random.uniform(low=-10., high=10., size=[33, 33]),
          shape=[33, 33],
          dtype=tf.float32,
          name='inputB')

      shape = tf.shape(input_tensor)
      fill = tf.transpose(tf.fill(shape, 1.))
      mult = tf.matmul(fill, input_tensor)
      return tf.matmul(mult, const_tensor)

    root = tracking.AutoTrackable()
    root.f = model
    concrete_func = root.f.get_concrete_function()

    def calibration_gen():
      for batch in range(5, 20, 5):
        for _ in range(5):
          yield [np.random.uniform(-1, 1, size=(batch, 33)).astype(np.float32)]

    return root, concrete_func, calibration_gen

  @test_util.run_v2_only
  def testMatMulQuantize(self):
    root, concrete_func, _ = self._getIntegerQuantizeModelWithUnknownShapes()
    float_converter = lite.TFLiteConverterV2.from_concrete_functions(
        [concrete_func], root)
    float_tflite_model = float_converter.convert()

    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions(
        [concrete_func], root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_tflite_model = quantized_converter.convert()

    # The default input and output types should be float.
    quantized_interpreter = Interpreter(model_content=quantized_tflite_model)
    quantized_interpreter.allocate_tensors()
    input_details = quantized_interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(np.float32, input_details[0]['dtype'])
    self.assertAllEqual([-1, 33], input_details[0]['shape_signature'])

    # Ensure that the quantized weights tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(float_tflite_model))

  @test_util.run_v2_only
  def testMatMulCalibrateAndQuantize(self):
    root, concrete_func, calibration_gen = (
        self._getIntegerQuantizeModelWithUnknownShapes())
    float_converter = lite.TFLiteConverterV2.from_concrete_functions(
        [concrete_func], root)
    float_tflite_model = float_converter.convert()

    quantized_converter = lite.TFLiteConverterV2.from_concrete_functions(
        [concrete_func], root)
    quantized_converter.optimizations = [lite.Optimize.DEFAULT]
    quantized_converter.representative_dataset = calibration_gen
    quantized_tflite_model = quantized_converter.convert()

    # The default input and output types should be float.
    quantized_interpreter = Interpreter(model_content=quantized_tflite_model)
    quantized_interpreter.allocate_tensors()
    input_details = quantized_interpreter.get_input_details()
    self.assertLen(input_details, 1)
    self.assertEqual(np.float32, input_details[0]['dtype'])
    self.assertAllEqual([-1, 33], input_details[0]['shape_signature'])

    # Ensure that the quantized weights tflite model is smaller.
    self.assertLess(len(quantized_tflite_model), len(float_tflite_model))

  def testBatchMatMul(self):
    input_data_1 = tf.constant(
        np.array(np.random.random_sample((1, 256, 256)), dtype=np.float32))
    input_data_2 = tf.constant(
        np.array(np.random.random_sample((1, 256, 256)), dtype=np.float32))

    @tf.function(input_signature=[
        tf.TensorSpec(shape=[None, 256, 256], dtype=tf.float32),
        tf.TensorSpec(shape=[None, 256, 256], dtype=tf.float32)
    ])
    def model(in_tensor_1, in_tensor_2):
      return tf.matmul(in_tensor_1, in_tensor_2)

    concrete_func = model.get_concrete_function()

    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    tflite_model = converter.convert()

    # Check values from converted model.
    expected_value = concrete_func(input_data_1, input_data_2)
    actual_value = self._evaluateTFLiteModel(
        tflite_model, [input_data_1, input_data_2],
        input_shapes=[([-1, 256, 256], [1, 256, 256])])[0]
    self.assertAllClose(expected_value, actual_value, atol=4)

  def testSizeInvalid(self):

    @tf.function(input_signature=[
        tf.TensorSpec(shape=[1, None, 16, 3], dtype=tf.float32)
    ])
    def model(in_tensor):
      return in_tensor + in_tensor

    concrete_func = model.get_concrete_function()

    # Test invalid shape. None after 1st dimension. Run with TOCO in order to
    # invoke shape checking code.
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    converter.experimental_new_converter = False
    with self.assertRaises(ValueError) as error:
      converter.convert()
    self.assertEqual(
        'None is only supported in the 1st dimension. Tensor '
        '\'in_tensor\' has invalid shape \'[1, None, 16, 3]\'.',
        str(error.exception))


class ResourceAndVariantTypes(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testVariants(self):

    @tf.function(input_signature=[tf.TensorSpec(shape=[1], dtype=tf.float32)])
    def model(v):
      m = map_ops.empty_tensor_map()
      k = tf.constant(1.0)
      p = tf.add(k, v)
      with ops.control_dependencies([m]):
        m2 = map_ops.tensor_map_insert(m, p, v)
        with ops.control_dependencies([m2]):
          return map_ops.tensor_map_size(m2)

    concrete_func = model.get_concrete_function()

    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(1, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(1, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(1, actual_value)

  @test_util.run_v2_only
  def testVariantsWithCond(self):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(), 'variants_with_cond')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          m = map_ops.empty_tensor_map()

          def body(i, m):
            m = map_ops.tensor_map_insert(m, i, i)
            return i + 1, m

          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.int32, name='input')
          _, result_m = tf.cond(in_tensor < 10, lambda: body(in_tensor, m),
                                lambda: body(in_tensor + 1, m))
          out_tensor = in_tensor + map_ops.tensor_map_size(result_m)

          inputs = {'x': in_tensor}
          outputs = {'z': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([0], dtype=np.int32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    expected_value = np.array([1], dtype=np.int32)
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(expected_value, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(expected_value, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(expected_value, actual_value)

  @test_util.run_v2_only
  def testVariantsWithWhile(self):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(), 'variants_with_while')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          m = map_ops.empty_tensor_map()

          def cond(i, m):
            del m
            return i < 10

          def body(i, m):
            m = map_ops.tensor_map_insert(m, i, i)
            return i + 1, m

          _, result_m = tf.while_loop(cond, body, [0, m])
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.int32, name='input')
          out_tensor = in_tensor + map_ops.tensor_map_size(result_m)

          inputs = {'x': in_tensor}
          outputs = {'z': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([0], dtype=np.int32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(10, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(10, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(10, actual_value)

  @test_util.run_v2_only
  def testResources(self):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(), 'simple_resources')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.float32, name='input')

          stack = tf.raw_ops.StackV2(max_size=10, elem_type=tf.float32)
          w = tf.raw_ops.StackPushV2(handle=stack, elem=in_tensor)
          with ops.control_dependencies([w]):
            a = in_tensor + in_tensor
            with ops.control_dependencies([a]):
              out_tensor = a + tf.raw_ops.StackPopV2(
                  handle=stack, elem_type=tf.float32)

          inputs = {'x': in_tensor}
          outputs = {'z': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(3.0, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(3.0, actual_value)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(3.0, actual_value)

  @test_util.run_v2_only
  def testResourcesWithCond(self):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(), 'resources_with_cond')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.float32, name='input')

          def body(i, arr):
            n = tf.raw_ops.StackPushV2(
                handle=arr, elem=tf.cast(i, dtype=tf.float32))
            return n, arr

          arr = tf.raw_ops.StackV2(max_size=10, elem_type=tf.float32)
          n, result_arr = tf.cond(in_tensor < 10, lambda: body(0, arr),
                                  lambda: body(1, arr))

          with ops.control_dependencies([result_arr, n]):
            out_tensor = tf.raw_ops.StackPopV2(
                handle=result_arr, elem_type=tf.float32)

          inputs = {'x': in_tensor}
          outputs = {'a': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(0.0, actual_value)

  @test_util.run_v2_only
  def testResourcesWithWhile(self):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(),
                                     'resources_with_while')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.float32, name='input')

          def cond(i, arr, m):
            del arr
            del m
            return i < 10

          def body(i, arr, m):
            del m
            n = tf.raw_ops.StackPushV2(
                handle=arr, elem=tf.cast(i, dtype=tf.float32))
            return i + 1, arr, n

          arr = tf.raw_ops.StackV2(max_size=10, elem_type=tf.float32)
          _, result_arr, n = tf.while_loop(cond, body, [0, arr, 0.0])

          with ops.control_dependencies([result_arr, n]):
            out_tensor = tf.raw_ops.StackPopV2(
                handle=result_arr, elem_type=tf.float32)

          inputs = {'x': in_tensor}
          outputs = {'a': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(9.0, actual_value)

  @parameterized.named_parameters(('EnableLoweringTensorListOps', True),
                                  ('DisableLoweringTensorListOps', False))
  @test_util.run_v2_only
  def testTensorListWithStaticSize(self, lower_tensor_list_ops):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(),
                                     'simple_mutable_variable')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.float32, name='input')

          ta = tf.TensorArray(
              tf.float32, size=3, dynamic_size=False, clear_after_read=False)
          ta = ta.write(0, 10.0)
          ta = ta.write(1, 20.0)
          ta = ta.write(2, 30.0)

          out_tensor = ta.read(0) + ta.read(2)

          inputs = {'x': in_tensor}
          outputs = {'z': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    if not lower_tensor_list_ops:
      converter.target_spec.supported_ops = [
          tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
      ]
    converter._experimental_lower_tensor_list_ops = lower_tensor_list_ops
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(40.0, actual_value)

  @parameterized.named_parameters(('EnableLoweringTensorListOps', True),
                                  ('DisableLoweringTensorListOps', False))
  @test_util.run_v2_only
  def testTensorListWithDynamicSize(self, lower_tensor_list_ops):

    def create_v1_saved_model():
      saved_model_dir = os.path.join(self.get_temp_dir(),
                                     'simple_mutable_variable')
      with tf.Graph().as_default():
        with tf.compat.v1.Session() as sess:
          in_tensor = tf.compat.v1.placeholder(
              shape=[1], dtype=tf.float32, name='input')

          ta = tf.TensorArray(
              tf.float32, size=0, dynamic_size=True, clear_after_read=False)
          ta = ta.write(0, 10.0)
          ta = ta.write(1, 20.0)
          ta = ta.write(2, 30.0)

          out_tensor = ta.read(0) + ta.read(2)

          inputs = {'x': in_tensor}
          outputs = {'z': out_tensor}
          saved_model.simple_save(sess, saved_model_dir, inputs, outputs)
      return saved_model_dir

    saved_model_dir = create_v1_saved_model()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    if lower_tensor_list_ops:
      with self.assertRaises(convert.ConverterError) as error:
        converter.convert()
      self.assertIn(
          'Lowering tensor list ops is failed. Please consider using Select '
          'TF ops and disabling `_experimental_lower_tensor_list_ops` flag in '
          'the TFLite converter object.', str(error.exception))

    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    input_data = np.array([1.0], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(40.0, actual_value)


class CalibrateAndQuantizeWithCustomOpTest(lite_v2_test_util.ModelTest):

  def _createGraphWithCustomOp(self):
    # Create a graph that has one double op.
    np.random.seed(0)

    saved_model_dir = os.path.join(self.get_temp_dir(), 'double_model')
    with ops.Graph().as_default():
      with tf.compat.v1.Session() as sess:
        in_tensor = tf.compat.v1.placeholder(
            shape=[1, 4], dtype=dtypes.float32, name='input')
        out_tensor = double_op.double(in_tensor)
        inputs = {'x': in_tensor}
        outputs = {'z': out_tensor}
        saved_model.simple_save(sess, saved_model_dir, inputs, outputs)

    def calibration_gen():
      for _ in range(100):
        yield [np.random.uniform(-1, 1, size=(1, 4)).astype(np.float32)]

    return (saved_model_dir, calibration_gen)

  def testCustomOpRegistererByName(self):
    """Test a calibration with custom op registered by name."""
    saved_model_dir, calibration_gen = self._createGraphWithCustomOp()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.optimizations = [lite.Optimize.DEFAULT]
    converter.representative_dataset = calibration_gen
    converter.allow_custom_ops = True
    converter.target_spec._experimental_custom_op_registerers = [
        'TF_TestRegisterer'
    ]
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)
    self.assertGreater(test_registerer.get_num_test_registerer_calls(), 0)
    self.assertIn('Double', tflite_test_util.get_ops_list(tflite_model))

    # Check the model works with custom ops.
    interpreter = InterpreterWithCustomOps(
        model_content=tflite_model, custom_op_registerers=['TF_TestRegisterer'])
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    test_input = np.array([[0.0, 0.1, 0.2, 0.3]], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], test_input)
    interpreter.invoke()

    output_details = interpreter.get_output_details()
    expected_output = np.array([[0.0, 0.2, 0.4, 0.6]], dtype=np.float32)
    output_data = interpreter.get_tensor(output_details[0]['index'])
    self.assertArrayNear(expected_output[0], output_data[0], err=1e-2)

  def testCustomOpRegistererByFunc(self):
    """Test a calibration with custom op registered by function."""
    saved_model_dir, calibration_gen = self._createGraphWithCustomOp()

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.optimizations = [lite.Optimize.DEFAULT]
    converter.representative_dataset = calibration_gen
    converter.allow_custom_ops = True
    converter.target_spec._experimental_custom_op_registerers = [
        test_registerer.TF_TestRegisterer
    ]
    tflite_model = converter.convert()
    self.assertTrue(tflite_model)
    self.assertGreater(test_registerer.get_num_test_registerer_calls(), 0)
    self.assertIn('Double', tflite_test_util.get_ops_list(tflite_model))

    # Check the model works with custom ops.
    interpreter = InterpreterWithCustomOps(
        model_content=tflite_model,
        custom_op_registerers=[test_registerer.TF_TestRegisterer])
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    test_input = np.array([[0.0, 0.1, 0.2, 0.3]], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], test_input)
    interpreter.invoke()

    output_details = interpreter.get_output_details()
    expected_output = np.array([[0.0, 0.2, 0.4, 0.6]], dtype=np.float32)
    output_data = interpreter.get_tensor(output_details[0]['index'])
    self.assertArrayNear(expected_output[0], output_data[0], err=1e-2)

  def testCustomOpRegistererFailure(self):
    """Test a calibration with wrong custom op registerer."""
    saved_model_dir, calibration_gen = self._createGraphWithCustomOp()

    bogus_name = 'CompletelyBogusRegistererName'

    converter = lite.TFLiteConverterV2.from_saved_model(saved_model_dir)
    converter.optimizations = [lite.Optimize.DEFAULT]
    converter.representative_dataset = calibration_gen
    converter.allow_custom_ops = True
    converter.target_spec._experimental_custom_op_registerers = [bogus_name]

    with self.assertRaisesRegex(
        ValueError, 'Looking up symbol \'' + bogus_name + '\' failed'):
      converter.convert()


class IntermediatesTest(lite_v2_test_util.ModelTest):

  def _run(self, experimental_preserve_all_tensors):

    @tf.function
    def f(x):
      y = tf.add(x, x, name='y')
      z = tf.add(y, y, name='z')
      w = tf.add(z, z, name='w')
      return w

    # NOTE this is exactly representable as a float as are the intermeidates of
    # f. So direct comparison is ok below.

    input_data = np.array(2.0, np.float32)
    concrete_func = f.get_concrete_function(input_data)
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               f)
    tflite_model = converter.convert()
    interpreter = Interpreter(
        model_content=tflite_model,
        experimental_preserve_all_tensors=experimental_preserve_all_tensors)
    interpreter.allocate_tensors()
    interpreter.set_tensor(interpreter.get_input_details()[0]['index'],
                           input_data)
    interpreter.invoke()
    out = interpreter.get_tensor(interpreter.get_output_details()[0]['index'])
    tensors = {}
    for t in interpreter.get_tensor_details():
      # With Tensorflow Lite default delegate applied to the model graph, the
      # access to original tensors of a delegated op could cause a ValueError
      # (i.e. 'Tensor data is null. Run allocate_tensors() first') to be thrown
      # out because the tensor memory isn't allocated at all.
      val = None
      try:
        val = interpreter.get_tensor(t['index'])
      except ValueError:
        pass
      tensors.update({t['name']: val})
    return (tensors, out)

  def testPreserve(self):
    tensors, result = self._run(experimental_preserve_all_tensors=True)
    # All intermediates should be true and result be true.
    self.assertAllClose(tensors['x'], 2.0)
    self.assertAllClose(tensors['y'], 4.0)
    self.assertAllClose(tensors['z'], 8.0)
    self.assertAllClose(result, 16.0)

  def testNoPreserve(self):
    tensors, result = self._run(experimental_preserve_all_tensors=False)
    # One of them should be wrong if preserve is not true, but result should be
    # ok. Input should still be ok for repeated invocation.
    self.assertAllClose(tensors['x'], 2.0)
    self.assertTrue(tensors['y'] != 4.0 or tensors['z'] != 8.0)
    self.assertAllClose(result, 16.0)


class DatasetOpsTest(lite_v2_test_util.ModelTest):

  @test_util.run_v2_only
  def testReduceDataset(self):

    @tf.function
    def model():
      dataset = tf.data.Dataset.from_tensor_slices([1, 2, 3, 4])
      output = dataset.reduce(np.int32(0), lambda x, y: x + y)
      return output

    concrete_func = model.get_concrete_function()
    converter = lite.TFLiteConverterV2.from_concrete_functions([concrete_func],
                                                               model)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS, tf.lite.OpsSet.SELECT_TF_OPS
    ]
    tflite_model = converter.convert()
    self.assertIsNotNone(tflite_model)

    # Check values from converted model.
    interpreter = Interpreter(model_content=tflite_model)
    output_details = interpreter.get_output_details()

    interpreter.allocate_tensors()

    interpreter.invoke()
    actual_value = interpreter.get_tensor(output_details[0]['index'])
    self.assertEqual(10, actual_value)


if __name__ == '__main__':
  test.main()
