from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
import unittest
from unittest import skip
import sys
import os
import numpy as np
from deeplift.conversion import keras_conversion as kc
import deeplift.blobs as blobs
from deeplift.blobs import NonlinearMxtsMode
from deeplift.backend import function as compile_func
import theano
import keras
from keras import models


class TestConcatModel(unittest.TestCase):


    def setUp(self):
        if (hasattr(keras, '__version__')==False):
            self.keras_version = 0.2 #didn't have the __version__ tag
        else:
            self.keras_version = float(keras.__version__[0:3])
        self.inp1 = (np.random.randn(10*10*51)
                    .reshape(10,10,51).transpose(0,2,1))
        self.inp2 = (np.random.randn(10*10*51)
                    .reshape(10,10,51).transpose(0,2,1))
        self.run_graph_tests = True
        if (self.keras_version < 1.0):
            self.keras_model = keras.models.Graph()
        else:
            self.run_graph_tests = False
            return #skip setup
        self.keras_model.add_input(name="inp1", input_shape=(51,10))
        self.keras_model.add_node(
            keras.layers.convolutional.Convolution1D(
                nb_filter=2, filter_length=4, subsample_length=2,
                activation="relu"), name="conv1", input="inp1")
        self.keras_model.add_node(
            keras.layers.convolutional.MaxPooling1D(
                pool_length=4, stride=2), name="mp1", input="conv1")

        self.keras_model.add_input(name="inp2", input_shape=(51,10))
        self.keras_model.add_node(
            keras.layers.convolutional.Convolution1D(
                nb_filter=2, filter_length=4, subsample_length=2,
                activation="relu"), name="conv2", input="inp2")
        self.keras_model.add_node(
            keras.layers.convolutional.MaxPooling1D(
                pool_length=4, stride=2), name="mp2", input="conv2")

        self.keras_model.add_node(keras.layers.core.Flatten(),
                                  name='flatten',
                                  inputs=['mp1','mp2'], merge_mode='concat',
                                  concat_axis=2)
        self.keras_model.add_node(keras.layers.core.Dense(output_dim=5),
                                  name="dense1", input="flatten")
        self.keras_model.add_node(keras.layers.core.Activation("relu"),
                                  name="denserelu1", input="dense1")
        self.keras_model.add_node(keras.layers.core.Dense(output_dim=1),
                                  name='output_preact', input='denserelu1')
        self.keras_model.add_node(keras.layers.core.Activation("sigmoid"),
                                  name='output_postact', input='output_preact')
        self.keras_model.add_output(name='output', input='output_postact')
        self.keras_model.compile(loss={"output": "binary_crossentropy"},
                                 optimizer="sgd")
        
        if (self.keras_version <= 0.3): 
            self.keras_output_fprop_func = compile_func(
                        [self.keras_model.inputs['inp1'].input,
                         self.keras_model.inputs['inp2'].input],
                        self.keras_model.outputs['output'].get_output(False))
            grad = theano.grad(theano.tensor.sum(
                       (self.keras_model.nodes['output_preact']
                            .get_output(False)[:,0])),
                       [self.keras_model.inputs['inp1'].input,
                        self.keras_model.inputs['inp2'].input])
            self.grad_func = theano.function(
                         [self.keras_model.inputs['inp1'].input,
                        self.keras_model.inputs['inp2'].input],
                         grad, allow_input_downcast=True)
        else:
            inp1 = self.keras_model.inputs['inp1'].input
            inp2 = self.keras_model.inputs['inp2'].input
            keras_output_fprop_func = compile_func(
                [inp1, inp2, keras.backend.learning_phase()],
                self.keras_model.layers[-1].output)
            self.keras_output_fprop_func =\
                lambda x,y: keras_output_fprop_func(x,y,False)
            grad = theano.grad(theano.tensor.sum(
                       self.keras_model.nodes['output_preact'].output[:,0]),
                       [inp1, inp2])
            grad_func = theano.function(
                         [inp1, inp2, keras.backend.learning_phase()],
                         grad, allow_input_downcast=True,
                         on_unused_input='ignore')
            self.grad_func = lambda x,y: grad_func(x,y,False)
 

    def test_convert_conv1d_model_forward_prop(self): 
        if (self.run_graph_tests==False):
            return
        deeplift_model = kc.convert_graph_model(
                          model=self.keras_model,
                          nonlinear_mxts_mode=NonlinearMxtsMode.Rescale)
        deeplift_fprop_func = compile_func(
 [deeplift_model.get_name_to_blob()['inp1'].get_activation_vars(),
  deeplift_model.get_name_to_blob()['inp2'].get_activation_vars()],
  deeplift_model.get_name_to_blob()['output_postact'].get_activation_vars())
        np.testing.assert_almost_equal(
            deeplift_fprop_func(self.inp1, self.inp2),
            self.keras_output_fprop_func(self.inp1, self.inp2),
            decimal=6)
         

    def test_convert_conv1d_model_compute_scores(self): 
        if (self.run_graph_tests==False):
            return
        deeplift_model = kc.convert_graph_model(
                            model=self.keras_model,
                            nonlinear_mxts_mode=NonlinearMxtsMode.Rescale)
        deeplift_contribs_func = deeplift_model.\
                                     get_target_contribs_func(
                              find_scores_layer_name=["inp1", "inp2"],
                              pre_activation_target_layer_name="output_preact")

        grads_inp1, grads_inp2 = self.grad_func(self.inp1, self.inp2)
        np.testing.assert_almost_equal(
            np.array(deeplift_contribs_func(task_idx=0,
                                      input_data_list={
                                       'inp1': self.inp1,
                                       'inp2': self.inp2},
                                      input_references_list={
                                       'inp1': np.zeros_like(self.inp1),
                                       'inp2': np.zeros_like(self.inp2)},
                                      batch_size=10,
                                      progress_update=None)),
            #when biases are 0 and ref is 0, deeplift is the same as grad*inp 
            np.array([grads_inp1*self.inp1,
                      grads_inp2*self.inp2]), decimal=6)
