import numpy as np
from scipy import optimize
import random
from sklearn import cross_validation
import time

from data_utils import load_musk1_data


_floatX = np.float32
_intX = np.int8


class EMDiverseDensity(object):
    """
        bags is a list of bag
        each bag is a dict required following <key, value>
        key: inst_prob, value: a vector indicating each instance's probability
        key: label, value: a scalar indicating this bag's label
        key: prob, value: a scalar indicating this bag's probability
        key: instances, value: a numpy array indicating instances in this bag, each row is a instance, each column is a
        feature
        this version select given number of different positive instances in different bags as starting points for em
        in predict process, simply use 'min', 'max' or 'avg' mode to select a concept from these learned concepts using
        the negative log likelihood, then use the concept for testing data.
    """

    def __init__(self):
        pass

    def diverse_density_nll(self, params, instances, labels):
        [n_instances, n_dim] = instances.shape
        if params.shape[0] == n_dim:
            target = params
            scale = np.ones(n_dim, )
        else:
            target = params[0:n_dim]
            scale = params[n_dim:]

        fun = 0

        dist = np.mean(((instances - target) ** 2) * (scale ** 2), axis=1)
        inst_prob = np.exp(-dist)
        for inst_idx in range(n_instances):
            if labels[inst_idx] == 1:
                if inst_prob[inst_idx] == 0:
                    inst_prob[inst_idx] = 1e-10
                fun -= np.log(inst_prob[inst_idx])
            else:
                if inst_prob[inst_idx] == 1:
                    inst_prob[inst_idx] = 1 - 1e-10
                fun -= np.log(1 - inst_prob[inst_idx])
        return fun

    def em(self, bags, scale_indicator, init_target, init_scale, func_val_tol=1e-5):
        target = init_target
        scale = init_scale

        # select an optimal instance from each bag according to current target and scale
        func_val_diff = np.inf
        prev_func_val = np.inf
        final_func_val = 0

        init_func_val = 0
        init_func_indicator = 1

        debug_count = 0
        while func_val_diff > func_val_tol:

            debug_count += 1
            if debug_count > 100:
                print(prev_func_val, final_func_val, func_val_diff, func_val_tol)
                raise NotImplementedError('loop error, em loop number is %d.' % debug_count)

            selected_instances = list()
            selected_labels = list()
            # select an instance with highest probability from each bag
            for bag in bags:
                instances = np.asarray(bag['instances'])
                [_, n_dim] = instances.shape
                dist = np.mean(((instances - target) ** 2) * (scale ** 2), axis=1)
                bag['inst_prob'] = np.exp(-dist)
                max_idx = np.argmax(bag['inst_prob'])
                selected_instances.append(instances[max_idx, :])
                selected_labels.append(bag['label'])

            selected_instances = np.asarray(selected_instances)

            if scale_indicator == 1:
                init_params = np.hstack((target, scale))
                if init_func_indicator == 1:
                    init_func_val = self.diverse_density_nll(init_params, selected_instances, selected_labels)
                    init_func_indicator = 0
                r_params = optimize.minimize(self.diverse_density_nll, init_params,
                                             args=(selected_instances, selected_labels,), method='L-BFGS-B')
                target = r_params.x[0:n_dim]
                scale = r_params.x[n_dim:]
            else:
                init_params = target
                if init_func_indicator == 1:
                    init_func_val = self.diverse_density_nll(init_params, selected_instances, selected_labels)
                    init_func_indicator = 0
                r_params = optimize.minimize(self.diverse_density_nll, init_params,
                                             args=(selected_instances, selected_labels,), method='L-BFGS-B')
                target = r_params.x
                scale = np.ones(n_dim,)

            final_func_val = r_params.fun
            func_val_diff = prev_func_val - final_func_val
            prev_func_val = final_func_val
        print('em loop number is %d. ' % debug_count, end='')

        return target, scale, final_func_val, init_func_val

    def train(self, bags, scale_indicator, epochs):
        n_bag = len(bags)
        n_pos_bag = 0

        max_iter = 0
        for bag in bags:
            if bag['label'] == 1:
                n_pos_bag += 1
                max_iter += bag['instances'].shape[0]

        epochs = min(max_iter, epochs)
        print('total epochs number is %d' % epochs)
        print('number of training positive bags is %d, number of positive instances is: %d' % (n_pos_bag, max_iter))

        targets = list()
        scales = list()
        func_values = list()

        for epoch_idx in range(epochs):
            # randomly select a positive bag
            bag_idx = random.randint(0, n_bag - 1)
            while bags[bag_idx]['label'] == 0 or np.all(np.asarray(bags[bag_idx]['starting_point']) == 1):
                bag_idx = random.randint(0, n_bag - 1)
            # randomly select a positive instance that not used before
            [_, n_dim] = bags[bag_idx]['instances'].shape
            starting_point_bag = np.asarray(bags[bag_idx]['starting_point'])
            valuable_idx = np.asarray(np.nonzero(starting_point_bag == 0))
            if valuable_idx.shape[1] == 1:
                instance_idx = valuable_idx[0, 0]
            else:
                rand_idx = random.randint(0, valuable_idx.shape[1] - 1)
                instance_idx = valuable_idx[0, rand_idx]
            bags[bag_idx]['starting_point'][instance_idx] = 1

            # scale is initialized to one
            print('epoch %d, selected instance is from <bag %d, bag label %d, instance %d>. ' %
                  (epoch_idx, bag_idx, bags[bag_idx]['label'], instance_idx), end='')
            [target, scale, func_val, init_func_val] = self.em(bags,
                                                               scale_indicator,
                                                               bags[bag_idx]['instances'][instance_idx, :],
                                                               np.ones(n_dim, ))
            print('nll before optimization is %f, nll after optimization is %f' % (init_func_val, func_val))

            targets.append(target)
            scales.append(scale)
            func_values.append(func_val)

        return targets, scales, func_values

    def predict(self, targets, scales, func_values, bags, aggregate, threshold):

        n_bag = len(bags)

        bags_label = np.zeros(n_bag, )
        bags_prob = np.zeros(n_bag, )
        instances_prob = list()
        instances_label = list()

        func_values = np.asarray(func_values)
        targets = np.asarray(targets)
        scales = np.asarray(scales)
        # with minimum diverse density
        if aggregate == 'max':
            target_idx = np.argmax(func_values)
            target = targets[target_idx]
            scale = scales[target_idx]
        # with maximum diverse density
        elif aggregate == 'min':
            target_idx = np.argmin(func_values)
            target = targets[target_idx]
            scale = scales[target_idx]
        # with average diverse density
        elif aggregate == 'avg':
            target = np.mean(targets, axis=0)
            scale = np.mean(scales, axis=0)
        else:
            raise NotImplementedError('must be max, min or avg')

        for bag_idx in range(n_bag):
            instances = bags[bag_idx]['instances']
            dist = np.mean(((instances - target) ** 2) * (scale ** 2), axis=1)
            inst_prob = np.exp(-dist)
            inst_label = np.int8(inst_prob > threshold)
            bags_prob[bag_idx] = np.max(inst_prob)
            bags_label[bag_idx] = np.any(inst_label)
            instances_prob.append(inst_prob)
            instances_label.append(inst_label)

        return bags_label, bags_prob, instances_label, instances_prob


def EMDD_musk1(split_ratio=None, cv_fold=None, aggregate='avg', threshold=0.5, scale_indicator=1, epochs=10):
    start_time = time.clock()
    dd_classifier = EMDiverseDensity()
    file_path = 'musk1.txt'
    bags, bag_labels = load_musk1_data(file_path)
    if split_ratio is None and cv_fold is None:
        print('parameters setting: split_ratio = None, cv_fold = None, aggregate = %s, threshold = %f, '
              'scale_indicator = %d, epochs = %d' % (aggregate, threshold, scale_indicator, epochs))
        targets, scales, func_values = dd_classifier.train(bags, scale_indicator, epochs)
        p_bags_label, p_bags_prob, p_instances_label, p_instances_prob = dd_classifier.predict(targets, scales,
                                                                                               func_values, bags,
                                                                                               aggregate, threshold)
        accuracy = sum(bag_labels == p_bags_label) / len(bags)
        print('training accuracy is: %f' % accuracy)

        train_result = (targets, scales, func_values)
        predict_result = (p_bags_label, p_bags_prob, p_instances_label, p_instances_prob)
        data = (bags, bag_labels)
        end_time = time.clock()
        print('time elapsed in EMDD is %f seconds' % (end_time - start_time))
        return data, train_result, predict_result

    elif split_ratio:
        print('parameters setting: split ratio = %f, cv_fold = None, aggregate = %s, '
              'threshold = %f, scale_indicator = %d, epochs = %d' %
              (split_ratio, aggregate, threshold, scale_indicator, epochs))
        train_bag, test_bag, train_label, test_label = cross_validation.train_test_split(bags,
                                                                                         bag_labels,
                                                                                         test_size=split_ratio,
                                                                                         random_state=0)

        targets, scales, func_values = dd_classifier.train(train_bag, scale_indicator, epochs)
        p_bags_label, p_bags_prob, p_instances_label, p_instances_prob = dd_classifier.predict(targets, scales,
                                                                                               func_values, test_bag,
                                                                                               aggregate, threshold)
        accuracy = sum(test_label == p_bags_label) / len(test_bag)
        print('split ratio is %f, testing accuracy is %f' % (split_ratio, accuracy))

        train_result = (targets, scales, func_values)
        predict_result = (p_bags_label, p_bags_prob, p_instances_label, p_instances_prob)
        data = (bags, bag_labels)
        end_time = time.clock()
        print('time elapsed in EMDD is %f seconds' % (end_time - start_time))
        return data, train_result, predict_result
    elif cv_fold:
        print('parameters setting: split_ratio = None, cv_fold = %d, aggregate = %s, '
              'threshold = %f, scale_indicator = %d, epochs = %d'
              % (cv_fold, aggregate, threshold, scale_indicator, epochs))
        accuracy_list = list()
        n_bags = len(bags)
        kf = cross_validation.KFold(n_bags, cv_fold, shuffle=True, random_state=0)
        cf = 1
        for train_idx, test_idx in kf:
            train_bag = list()
            train_label = list()
            for idx in train_idx:
                train_bag.append(bags[idx])
                train_label.append(bag_labels[idx])
            test_bag = list()
            test_label = list()
            for idx in test_idx:
                test_bag.append(bags[idx])
                test_label.append(bag_labels[idx])

            targets, scales, func_values = dd_classifier.train(train_bag, scale_indicator, epochs)
            p_bags_label, p_bags_prob, p_instances_label, p_instances_prob = dd_classifier.predict(targets, scales,
                                                                                                   func_values,
                                                                                                   test_bag,
                                                                                                   aggregate,
                                                                                                   threshold)
            accuracy = sum(test_label == p_bags_label) / len(test_bag)
            accuracy_list.append(accuracy)
            print('completed fold %d, accuracy is %f' % (cf, accuracy))
            cf += 1

        mean_accuracy = float(np.mean(np.asarray(accuracy_list)))
        print('mean accuracy with %d-fold cross validation is %f' % (cv_fold, mean_accuracy))
        end_time = time.clock()
        print('time elapsed in EMDD is %f seconds' % (end_time - start_time))

        return accuracy_list
    else:
        pass


if __name__ == '__main__':
    EMDD_musk1(split_ratio=None, cv_fold=10, aggregate='avg', threshold=0.5, scale_indicator=1, epochs=3)
