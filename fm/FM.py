# -*- coding: UTF-8 -*-
import os
import sys
import tensorflow as tf
import logging
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s',level=logging.INFO)
import numpy as np
import argparse
from util import *
from sklearn.metrics import *
class FM(object):
    # num_classes:2分类或者多分类，k：特征
    def __init__(self, num_classes, k, lr, batch_size, feature_length, reg_l1, reg_l2):
        self.num_classes = num_classes
        self.k = k
        self.lr = lr
        self.batch_size = batch_size
        self.p = feature_length
        self.reg_l1 = reg_l1
        self.reg_l2 = reg_l2

    # 数据集占位符，样本数据X(样本数量，特征个数），标签数据y(样本数量，分类个数)
    def add_input(self):
        self.X = tf.placeholder('float32', [None, self.p])
        self.y = tf.placeholder('float32', [None, self.num_classes])
        self.keep_prob = tf.placeholder('float32')

    # 搭模型，激活函数
    # y_out:(样本数量，分类个数）， y_out_prob激活函数输出后 (样本数量，分类个数） 元素值在0-1之间
    def inference(self):
        # 纯线性部分。初始化权重w(特征个数，分类个数)。初始化w0(分类个数,)。
        # w初始化为截断的正态分布随机数，w0初始化为0。
        # X*w + w0 。  X(样本数量，特征个数）*  w(特征个数，分类个数) + w0(分类个数,) =>  （样本数量，分类个数）
        with tf.variable_scope('linear_layer'):
            w0 = tf.get_variable('w0', shape=[self.num_classes],
                                initializer=tf.zeros_initializer())
            self.w = tf.get_variable('w', shape=[self.p, num_classes],
                                 initializer=tf.truncated_normal_initializer(mean=0,stddev=0.01))
            self.linear_terms = tf.add(tf.matmul(self.X, self.w), w0)
        # 特征交叉部分。初始化v(特征个数，隐向量长度)
        #  0.5 * mean_axis_1_keep_dims( (X*v)^2 - (X * v^2) ) 。
        ##  0.5 * mean_axis_1_keep_dims( ( X(样本数量，特征个数） * v(特征个数，隐向量长度) )^2 - (X(样本数量，特征个数） * v(特征个数，隐向量长度)^2) ) 。
        ##  0.5 * mean_axis_1_keep_dims( ( 样本数量，隐向量长度 )^2 - (X(样本数量，特征个数） * (特征个数，隐向量长度)) )
        ##  0.5 * mean_axis_1_keep_dims( ( 样本数量，隐向量长度) )  => （样本数量，1）
        with tf.variable_scope('interaction_layer'):
            self.v = tf.get_variable('v', shape=[self.p, self.k],
                                initializer=tf.truncated_normal_initializer(mean=0, stddev=0.01))
            self.interaction_terms = tf.multiply(0.5,
                                                 tf.reduce_mean(
                                                     tf.subtract(
                                                         tf.pow(tf.matmul(self.X, self.v), 2),
                                                         tf.matmul(self.X, tf.pow(self.v, 2))),
                                                     1, keep_dims=True))
        # X*w + w0 + 0.5 * mean_axis_1_keep_dims( (X*v)^2 - (X * v^2) )
        # (样本数量，分类个数）+ （样本数量，1） => (样本数量，分类个数）
        self.y_out = tf.add(self.linear_terms, self.interaction_terms)
        if self.num_classes == 2:
            self.y_out_prob = tf.nn.sigmoid(self.y_out)
        elif self.num_classes > 2:
            self.y_out_prob = tf.nn.softmax(self.y_out)
    # 在模型输出和和真实值之间构建交叉熵函数，构建损失函数，损失函数是交叉熵函数输出的均值
    def add_loss(self):
        # 交叉熵函数
        if self.num_classes == 2:
            cross_entropy = tf.nn.sigmoid_cross_entropy_with_logits(labels=self.y, logits=self.y_out)
        elif self.num_classes > 2:
            cross_entropy = tf.nn.softmax_cross_entropy_with_logits(labels=self.y, logits=self.y_out)
        mean_loss = tf.reduce_mean(cross_entropy)
        self.loss = mean_loss
        tf.summary.scalar('loss', self.loss)
    # 计算预测精度:分别找到预测值y_out和实际值y每一行的最大值小标，比较是否相等[True, 。。。,False]，把比较结果转换成float[1.,...,0.]，然后计算均值
    def add_accuracy(self):
        # accuracy
        self.correct_prediction = tf.equal(tf.cast(tf.argmax(self.y_out,1), tf.float32), tf.cast(tf.argmax(self.y,1), tf.float32))
        self.accuracy = tf.reduce_mean(tf.cast(self.correct_prediction, tf.float32))
        # add summary to accuracy
        tf.summary.scalar('accuracy', self.accuracy)
    # 训练：初始化步数、优化器、控制依赖、得到训练OP
    # 注意，tensorlow中训练本身也是一个Operation
    def train(self):
        # Variable变量更新以后加一
        self.global_step = tf.Variable(0, trainable=False)
        optimizer = tf.train.FtrlOptimizer(self.lr, l1_regularization_strength=self.reg_l1,
                                           l2_regularization_strength=self.reg_l2)
        extra_update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(extra_update_ops):
            # 更新Variable变量，分为两步计算梯度,应用梯度。每sess.run一次，会进行梯度下降的一个周期
            self.train_op = optimizer.minimize(self.loss, global_step=self.global_step)

    # 初始化样本占位符，搭模型，设置损失函数OP，设置精度OP，训练OP
    def build_graph(self):
        self.add_input()
        self.inference()
        self.add_loss()
        self.add_accuracy()
        self.train()

# 训练数据的时候跑epochs个周期，一个周期分小批喂入模型进行训练（求导更新参数），每训练print_every次打印一次结果保存一次模型
# 注意epochs在此处并不等于训练次数，还跟分批有关系
def train_model(sess, model, epochs=100, print_every=50):
    """training model"""
    # Merge all the summaries and write them out to train_logs
    merged = tf.summary.merge_all()
    train_writer = tf.summary.FileWriter('train_logs', sess.graph)
    
    # get number of batches
    num_batches = len(x_train) // batch_size + 1

    # 跑epochs次
    for e in range(epochs):
        # 样本总数
        num_samples = 0
        # 每一批的误差
        losses = []
        # 分num_batches批跑所有数据
        for ibatch in range(num_batches):
            # batch_size data
            batch_x, batch_y = next(batch_gen)
            batch_y = np.array(batch_y).astype(np.float32)
            actual_batch_size = len(batch_y)
            # create a feed dictionary for this batch
            # 喂入该批次的数据
            feed_dict = {model.X: batch_x,
                         model.y: batch_y,
                         model.keep_prob:1.0}

            # 运行operations并计算tensor
            loss, accuracy,  summary, global_step, _ = sess.run([model.loss, model.accuracy,
                                                                 merged,model.global_step,
                                                                 model.train_op], feed_dict=feed_dict)
            # aggregate performance stats
            losses.append(loss*actual_batch_size)
            num_samples += actual_batch_size
            # Record summaries and train.csv-set accuracy
            train_writer.add_summary(summary, global_step=global_step)
            # print training loss and accuracy
            # 总的迭代次数每print_every输出一次误差和精度
            # 并保存训练检查点
            if global_step % print_every == 0:
                logging.info("Iteration {0}: with minibatch training loss = {1} and accuracy of {2}"
                             .format(global_step, loss, accuracy))
                saver.save(sess, "checkpoints/model", global_step=global_step)
        # print loss of one epoch
        total_loss = np.sum(losses)/num_samples
        print("Epoch {1}, Overall loss = {0:.3g}".format(total_loss, e+1))

# 测试模型
def test_model(sess, model, print_every = 50):
    """training model"""
    # get testing data, iterable
    all_ids = []
    all_clicks = []
    # get number of batches
    num_batches = len(y_test) // batch_size + 1
    # 分批预测
    for ibatch in range(num_batches):
        # batch_size data
        batch_x, batch_y = next(test_batch_gen) 
        actual_batch_size = len(batch_y)
        # create a feed dictionary for this15162 batch
        feed_dict = {model.X: batch_x,
                     model.keep_prob:1}
        # shape of [None,2]
        # 测试数据输出训练后模型计算y_out_prob
        # 会覆盖train_model的y_out_prob
        y_out_prob = sess.run([model.y_out_prob], feed_dict=feed_dict)
        y_out_prob = np.array(y_out_prob[0])
        # 预测结果，用最大概率的索引表示
        batch_clicks = np.argmax(y_out_prob, axis=1)
        # 实际结果，同样用最大索引表示
        batch_y = np.argmax(batch_y, axis=1)
        #
        print(confusion_matrix(batch_y, batch_clicks))
        ibatch += 1
        if ibatch % print_every == 0:
            logging.info("Iteration {0} has finished".format(ibatch))


def shuffle_list(data):
    num = data[0].shape[0]
    p = np.random.permutation(num)
    return [d[p] for d in data]

def batch_generator(data, batch_size, shuffle=True):
    if shuffle:
        data = shuffle_list(data)

    batch_count = 0
    while True:
        if batch_count * batch_size + batch_size > len(data[0]):
            batch_count = 0

            if shuffle:
                data = shuffle_list(data)

        start = batch_count * batch_size
        end = start + batch_size
        batch_count += 1
        yield [d[start:end] for d in data]

def check_restore_parameters(sess, saver):
    """ Restore the previously trained parameters if there are any. """
    ckpt = tf.train.get_checkpoint_state("checkpoints")
    if ckpt and ckpt.model_checkpoint_path:
        logging.info("Loading parameters for the my Factorization Machine")
        saver.restore(sess, ckpt.model_checkpoint_path)
    else:
        logging.info("Initializing fresh parameters for the my Factorization Machine")

#
if __name__ == '__main__':
    '''launching TensorBoard: tensorboard --logdir=path/to/log-directory'''
    # get mode (train or test)
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', help='train or test', type=str)
    args = parser.parse_args()
    mode = args.mode
    # length of representation
    x_train, y_train, x_test, y_test = load_dataset()
    # initialize the model
    num_classes = 2
    lr = 0.01
    batch_size = 128
    k = 40
    reg_l1 = 2e-2
    reg_l2 = 0
    feature_length = x_train.shape[1]
    # initialize FM model
    batch_gen = batch_generator([x_train,y_train],batch_size)
    test_batch_gen = batch_generator([x_test,y_test],batch_size)
    model = FM(num_classes, k, lr, batch_size, feature_length, reg_l1, reg_l2)
    # build graph for model
    model.build_graph()

    saver = tf.train.Saver(max_to_keep=5)

    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())
        check_restore_parameters(sess, saver)
        if mode == 'train':
            print('start training...')
            train_model(sess, model, epochs=1000, print_every=500)
        if mode == 'test':
            print('start testing...')
            test_model(sess, model)
