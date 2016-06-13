# creating spectrograms from all the files, and saving split labelled versions to disk ready for machine learning
import matplotlib.pyplot as plt

import os
import sys
import cPickle as pickle
import numpy as np
import time
import random
import yaml

import nolearn
import nolearn.lasagne
import lasagne.layers

from lasagne.layers import InputLayer, DimshuffleLayer
from lasagne.layers import DenseLayer
from lasagne.layers import NonlinearityLayer
from lasagne.layers import DropoutLayer
from lasagne.layers import Pool2DLayer as PoolLayer
from lasagne.layers.dnn import Conv2DDNNLayer as ConvLayer
from lasagne.nonlinearities import softmax, elu as vlr
import theano
from lasagne.layers import batch_norm, ElemwiseSumLayer, ExpressionLayer, DimshuffleLayer
import theano.tensor as T

from train_helpers import SpecSampler, Log1Plus
import train_helpers
import data_io
from ml_helpers import ui
from ml_helpers.evaluation import plot_confusion_matrix

RUN_TYPE = 'standard_spec'
fold = 0

logging_dir = data_io.base + 'predictions/%s/' % RUN_TYPE
train_helpers.force_make_dir(logging_dir)
sys.stdout = ui.Logger(logging_dir + 'log.txt')

# parameters... these could probably be hyperopted
CLASSNAME = 'biotic'
HWW = 5
SPEC_HEIGHT = 330
LEARN_LOG = 0
DO_AUGMENTATION = True
DO_BATCH_NORM = True
NUM_FILTERS = 32
NUM_DENSE_UNITS = 64
CONV_FILTER_WIDTH = 4
WIGGLE_ROOM = 5
MAX_EPOCHS = 50
LEARNING_RATE = 0.0005

# loading data
train_files, test_files = data_io.load_splits()
train_data, test_data = data_io.load_data(train_files, test_files, SPEC_HEIGHT, LEARN_LOG, CLASSNAME)
print len(test_data[0]), len(train_data[0])

# # creaging samplers and batch iterators
train_sampler = SpecSampler(64, train_data[0], train_data[1], HWW, DO_AUGMENTATION, LEARN_LOG, randomise=True)
test_sampler = SpecSampler(64, test_data[0], test_data[1], HWW, False, LEARN_LOG)

class MyTrainSplit(nolearn.lasagne.TrainSplit):
    # custom data split
    def __call__(self, data, Yb, net):
        return None, None, None, None#train_sampler, test_sampler, None, None


if not DO_BATCH_NORM:
    batch_norm = lambda x: x

# main input layer, then logged
net = {}
net['input'] = InputLayer((None, 1, SPEC_HEIGHT, HWW*2), name='input')

if LEARN_LOG:
    off = lasagne.init.Constant(0.01)
    mult = lasagne.init.Constant(1.0)

    net['input_logged'] = Log1Plus(net['input'], off, mult)

    # logging the median and multiplying by -1
    net['input_med'] = InputLayer((None, 1, SPEC_HEIGHT, HWW*2), name='input_med')
    net['med_logged'] = Log1Plus(
        net['input_med'], off=net['input_logged'].off, mult=net['input_logged'].mult)
    net['med_logged'] = ExpressionLayer(net['med_logged'], lambda X: -X)

    # summing the logged input with the negative logged median
    net['input'] = ElemwiseSumLayer((net['input_logged'], net['med_logged']))

net['conv1_1'] = batch_norm(
    ConvLayer(net['input'], NUM_FILTERS, (SPEC_HEIGHT - WIGGLE_ROOM, CONV_FILTER_WIDTH), nonlinearity=vlr))
net['pool1'] = PoolLayer(net['conv1_1'], pool_size=(2, 2), stride=(2, 2), mode='max')
net['pool1'] = DropoutLayer(net['pool1'], p=0.5)
net['conv1_2'] = batch_norm(ConvLayer(net['pool1'], NUM_FILTERS, (1, 3), nonlinearity=vlr))
# net['pool2'] = PoolLayer(net['conv1_2'], pool_size=(1, 2), stride=(1, 1))
net['pool2'] = DropoutLayer(net['conv1_2'], p=0.5)

net['fc6'] = batch_norm(DenseLayer(net['pool2'], num_units=NUM_DENSE_UNITS, nonlinearity=vlr))
net['fc6'] = DropoutLayer(net['fc6'], p=0.5)
net['fc7'] = batch_norm(DenseLayer(net['fc6'], num_units=NUM_DENSE_UNITS, nonlinearity=vlr))
net['fc7'] = DropoutLayer(net['fc7'], p=0.5)
net['fc8'] = DenseLayer(net['fc7'], num_units=2, nonlinearity=None)
net['prob'] = NonlinearityLayer(net['fc8'], softmax)

save_history = train_helpers.SaveHistory(logging_dir)
# save_predictions = train_helpers.SavePredictions(logging_dir)
save_weights = train_helpers.SaveWeights(logging_dir, 2, 20)

net = nolearn.lasagne.NeuralNet(
    layers=net['prob'],
    max_epochs=MAX_EPOCHS,
    update=lasagne.updates.adam,
    update_learning_rate=LEARNING_RATE,
#     update_momentum=0.975,
    verbose=1,
    batch_iterator_train=train_sampler,
    batch_iterator_test=test_sampler,
    train_split=MyTrainSplit(None),
    custom_epoch_scores=[('fake', lambda x, y: 0.0)],
    on_epoch_finished=[save_weights, save_history],
    check_input=False
)
net.fit(None, None)

results_savedir = train_helpers.force_make_dir(logging_dir + 'results/')

# now test the algorithm and save:
num_to_sample = np.sum(test_sampler.labels == 1)
X, y_true = test_sampler.sample(num_to_sample)
y_pred_prob = net.predict_proba(X)
y_pred = np.argmax(y_pred_prob, axis=1)

# confusion matrix
plt.figure(figsize=(5, 5))
plot_confusion_matrix(y_true, y_pred, normalise=True, cls_labels=['None', CLASSNAME])
plt.savefig(results_savedir + 'conf_mat_%d.png' % fold)
plt.close()

# final predictions
# todo - actually save one per file? (no, let's do this balanced...)
with open(results_savedir + "predictions_%d.pkl" % fold, 'w') as f:
    pickle.dump([y_true, y_pred_prob], f, -1)

# save weights from network
net.save_params_to(results_savedir + "weights_%d.pkl" % fold)

# we could now do one per file... each spectrogram at a time... We could do the full plotting etc
# probably not worth it.
# let's do this another time