
import numpy as np
import scipy.optimize as optimize
import random


_floatX = np.float32
_intX = np.int8


class MaxDiverseDensity(object):
    """
    bags is a list of bag
    each bag is a dict required following <key, value>
    key: inst_prob, value: a vector indicating each instance's probability
    key: label, value: a scalar indicating this bag's label
    key: prob, value: a scalar indicating this bag's probability
    key: instances, value: a numpy array indicating instances in this bag, each row is a instance, each column is a
    feature
    """

    def __init__(self):
        pass

    def diverse_density_nll(self, params, bags):

        fun = 0
        n_bag = len(bags)
        n_dim = bags[0]['instances'].shape[1]
        # parameter length equal to feature length, only learn target vector
        if params.shape[0] == n_dim:
            target = params
            scale = np.ones(n_dim, )
        # parameter length equal to 2*feature length, learn target vector and scaling vector both
        else:
            target = params[0:n_dim]
            scale = params[n_dim:]

        # compute negative log likelihood
        for bag_idx in range(n_bag):
            instances = bags[bag_idx]['instances']
            dist = np.mean(((instances - target) ** 2) * (scale ** 2), axis=1)
            bags[bag_idx]['inst_prob'] = np.exp(-dist)
            bags[bag_idx]['prob'] = 1 - np.prod(1 - np.asarray(bags[bag_idx]['inst_prob']))

            if bags[bag_idx]['label'] == 1:
                if bags[bag_idx]['prob'] == 0:
                    bags[bag_idx]['prob'] = 1e-10
                fun = fun - np.log(bags[bag_idx]['prob'])
            else:
                if bags[bag_idx]['prob'] == 1:
                    bags[bag_idx]['prob'] = 1 - 1e-10
                fun = fun - np.log(1 - bags[bag_idx]['prob'])
        return fun

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
            bag_idx = random.randint(0, n_bag - 1)
            while bags[bag_idx]['label'] == 0 or np.all(np.asarray(bags[bag_idx]['starting_point']) == 1):
                bag_idx = random.randint(0, n_bag - 1)
                # bag_idx = (bag_idx + 1) % n_bag

            [_, n_dim] = bags[bag_idx]['instances'].shape
            starting_point_bag = np.asarray(bags[bag_idx]['starting_point'])
            valuable_idx = np.asarray(np.nonzero(starting_point_bag == 0))
            if valuable_idx.shape[1] == 1:
                instance_idx = valuable_idx[0, 0]
            else:
                rand_idx = random.randint(0, valuable_idx.shape[1]-1)
                instance_idx = valuable_idx[0, rand_idx]
            bags[bag_idx]['starting_point'][instance_idx] = 1

            if scale_indicator == 1:
                init_params = np.hstack((bags[bag_idx]['instances'][instance_idx, :], np.ones([n_dim, ])))
                r_params = optimize.minimize(self.diverse_density_nll, init_params, args=(bags,), method='L-BFGS-B')
                print('epoch %d, selected instance is from <bag %d, bag label %d, instance %d>. '
                      'nll before optimization is %f, nll after optimization is %f' %
                      (epoch_idx, bag_idx, bags[bag_idx]['label'], instance_idx,
                       self.diverse_density_nll(init_params, bags),
                       self.diverse_density_nll(r_params.x, bags)))
                targets.append(r_params.x[:n_dim])
                scales.append(r_params.x[n_dim:])
                func_values.append(r_params.fun)

            else:
                init_params = bags[bag_idx]['instances'][instance_idx, :]
                r_params = optimize.minimize(self.diverse_density_nll, init_params, args=(bags,), method='L-BFGS-B')
                print('epoch %d, selected instance is from <bag %d, bag label %d, instance %d>. '
                      'nll before optimization is %f, nll after optimization is %f' %
                      (epoch_idx, bag_idx, bags[bag_idx]['label'], instance_idx,
                       self.diverse_density_nll(init_params, bags),
                       self.diverse_density_nll(r_params.x, bags)))
                targets.append(r_params.x)
                scales.append(np.ones(n_dim,))
                func_values.append(r_params.fun)
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
        # with maximal negative log likelihood
        if aggregate == 'max':
            target_idx = np.argmax(func_values)
            target = targets[target_idx]
            scale = scales[target_idx]
        # with minimal negative log likelihood
        elif aggregate == 'min':
            target_idx = np.argmin(func_values)
            target = targets[target_idx]
            scale = scales[target_idx]
        # with average negative log likelihood
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

