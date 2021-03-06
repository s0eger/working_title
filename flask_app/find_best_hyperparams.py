from words_to_vals import NMF_Time, _tokenize
from work_with_counts import Count_Worker
import pickle
from scipy.optimize import minimize, differential_evolution
import numpy as np
import pandas as pd
import datetime as dt
import matplotlib.pyplot as plt

def minimize_error(weights, *args):
    """ Minimization function, the y values are stored in the main block

    Parameters
    ----------
    weights: a tuple of current alpha, beta, gamma values

    Returns
    -------
    error: Sum of squared errors value looking to be minimized
    """
    Y = args[0]
    periods_ahead = 6
    m = 7
    alpha = weights[0]
    beta = weights[1]
    gamma = weights[2]
    s = Y.copy()
    b = np.zeros_like(s)
    c = np.zeros_like(s)
    L = 42 # weekly, sampling rate is 4 hours -> 7 days/week * 24 hours/day / 4 hours/sample = 42 samples/week
    n_cycles = s.shape[1] // L
    c_0 = np.zeros((s.shape[0],L))
    avgs = [np.sum(s[:,i*L:(i+1)*L],axis=1)/L for i in range(n_cycles)]
    for i in range(L):
        b[:,0] += (s[:,i+L]-s[:,i])/(L*L)
        c_0[:,i] = sum([s[:,L*j + i]-avgs[j] for j in range(n_cycles)])/n_cycles
    c[:,0]=c_0[:,0]
    for i in range(1, s.shape[0]):
        if i < L:
            s[:,i]=alpha*(Y[:,i]-c_0[:,i])+(1-alpha)*(s[:,i-1] + b[:,i-1])
            b[:,i]=beta*(s[:,i]-s[:,i-1])+(1-beta)*b[:,i-1]
            c[:,i]=gamma*(Y[:,i]-s[:,i])+(1-gamma)*c_0[:,i]
        else:
            s[:,i]=alpha*(Y[:,i]-c[:,i-L])+(1-alpha)*(s[:,i-1] + b[:,i-1])
            b[:,i]=beta*(s[:,i]-s[:,i-1])+(1-beta)*b[:,i-1]
            c[:,i]=gamma*(Y[:,i]-s[:,i])+(1-gamma)*c[:,i-L]
    error = 0
    # for i in range(s.shape[0]): # For each topic
    for j in range(s.shape[1]-periods_ahead): #for all times that can be predicted ahead
        error += np.sum(Y[:,j+m-1]-(s[:,j]+m*b[:,j]+c[:,(j+m)%L]))**2
    return error

def minimize_start():
    """ Utilizes scipy optimization to mimimize the Holt-Winter hyper-parameters

    Parameters
    ----------
    None

    Returns
    -------
    The response object of the scipy optimization
    """

    with open('app_model/output_data.pkl','rb') as f:
        cw = pickle.load(f)
    w0 = np.array([0.2,0.2,0.2])
    tsum = np.sum(cw.topic_counts, axis=1)
    sum_sort = np.argsort(tsum)
    Y = cw.smooth_data[sum_sort[:50],:]
    r = (0.0,1.0)
    # return minimize(minimize_error, w0, args = (Y), bounds=[r,r,r])
    return differential_evolution(minimize_error, args = (Y,), bounds=[r,r,r])

def generate_model(data_location, save_model=True):
    """ Generates a model for the flask app to utilize as data source

    Parameters
    ----------
    data_location: the relative location of the data to generate the model
    save_model: if you want to save this generated model for the flask app to use

    Returns
    -------
    nmf_model: the generated model
    """

    nmf_model = NMF_Time(top_n_words=25, verbose=True)
    df = pd.read_csv(data_location, index_col=0)
    df = df[df['news_source'] == 'NYT'] # Currently due to not enough from other sources
    nmf_model.generate_topics(df['content'].values, tok=_tokenize, min_df = 0.005, max_features = 10000, n_components=500)
    nmf_model.perform_time_counting_self(df, delta=dt.timedelta(hours=4), threshold=0.05)
    if save_model:
        nmf_model.save_model()
    return nmf_model

def load_prior_model():
    ''' Loads and returns the currently saved pickled model found under '/app_model' '''
    return NMF_Time(load_model=True)

def valid_error(new_df):
    model = NMF_Time(load_model=True)
    new_df['pub_date'] = pd.to_datetime(new_df['pub_date'])
    new_df = new_df[new_df['pub_date'] > model.times[-1]]
    model.perform_time_counting_new(new_df,threshold=0.05, prior_times=True)
    cw = Count_Worker(model)
    with open('app_model/output_data.pkl','rb') as f:
        pcw = pickle.load(f)
    mask = np.sum(pcw.all_counts,axis=1) >= 3
    cw.topic_counts = cw.all_counts[mask,:]
    cw.W_a = cw.W[:,mask]
    # cw.topics = cw.all_topics[mask,:]
    # cw.topics = {i : cw.topics[i,:] for i in range(pcw.topics.shape[0])}
    cw.dc = cw.all_dc[mask]
    cw.data_smoothing()
    top_topics = pcw.trending_order[:25]
    # top_topics = np.argsort(np.sum(pcw.topic_counts,axis=1))[:-26:-1]
    test_counts = cw.topic_counts[top_topics,:]
    pcw.predict_all(periods_ahead=cw.times.shape[0])
    test_predicted = pcw.predicted_values[top_topics,:]
    error = (np.sum((test_counts - test_predicted[:,1:])**2,axis=0)/cw.topic_counts.shape[0])**0.5
    base_counts = np.zeros_like(cw.topic_counts)
    for i in range(base_counts.shape[1]):
        base_counts[:,i]= pcw.topic_counts[:,-1]
    base_counts = base_counts[top_topics,:]
    base_error = (np.sum((test_counts - base_counts)**2,axis=0)/cw.topic_counts.shape[0])**0.5
    return error, base_error, pcw.predicted_times[1:]



def show_example_trend(topic_index = 1):
    with open('app_model/output_data.pkl','rb') as f:
        cw = pickle.load(f)
    p_vals = np.zeros(cw.times.shape[0])
    test_vals = cw.smooth_data[topic_index,:]
    L = 6
    # starting points are i*6
    # for i in range (1, p_vals.shape[0]):
    #     p_vals[i] = cw.triple_exp_predict(topic_index,periods_ahead= 1 + ((i-1) % L), at_time=6*((i-1) // L))[0]
    for i in range (1, p_vals.shape[0]):
        p_vals[i] = cw.triple_exp_predict(topic_index,periods_ahead = 1, at_time= i - 1)[0]
    p_vals = np.clip(p_vals,a_min=0,a_max=None)
    plt.plot(cw.times,test_vals,'b',linewidth=5,alpha=0.5, label='Actual')
    plt.plot(cw.times, p_vals,c='k',linewidth=2,ls='--',label='Predicted')
    # plt.ylabel('Article Counts', fontsize=18)
    # plt.xlabel('Date (Year-Month)',fontsize=18)
    plt.xticks(fontsize=14)
    plt.yticks(fontsize=14)
    plt.legend()
    plt.show()
    print(cw.all_dc[topic_index])

if __name__ == '__main__':
    # obj = generate_model('../article_data.csv',save_model=True)
    # result = minimize_start()
    df = pd.read_csv('../temp_data2.csv',index_col=0)
    err, b_err, times = valid_error(df)
    # show_example_trend()
