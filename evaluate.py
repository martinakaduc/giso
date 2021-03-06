import pickle
from gnn import gnn
import time
import numpy as np
import utils
import torch.nn as nn
import torch
import time
import os
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, average_precision_score,f1_score
import argparse
import time
from tqdm import tqdm
from torch.utils.data import DataLoader                                     
from dataset import BaseDataset, collate_fn, UnderSampler

parser = argparse.ArgumentParser()
parser.add_argument("--ngpu", help="number of gpu", type=int, default = 1)
parser.add_argument("--dataset", help="dataset", type=str, default = "tiny")
parser.add_argument("--batch_size", help="batch_size", type=int, default = 32)
parser.add_argument("--num_workers", help="number of workers", type=int, default = os.cpu_count())
parser.add_argument("--embedding_dim", help="node embedding dim aka number of distinct node label", type=int, default = 20)
parser.add_argument("--tatic", help="tactic of defining number of hops", type=str, default = "static", choices=["static", "cont", "jump"])
parser.add_argument("--nhop", help="number of hops", type=int, default = 1)
parser.add_argument("--n_graph_layer", help="number of GNN layer", type=int, default = 4)
parser.add_argument("--d_graph_layer", help="dimension of GNN layer", type=int, default = 140)
parser.add_argument("--n_FC_layer", help="number of FC layer", type=int, default = 4)
parser.add_argument("--d_FC_layer", help="dimension of FC layer", type=int, default = 128)
parser.add_argument("--data_path", help="path to the data", type=str, default='data_processed')
parser.add_argument("--result_dir", help="save directory of model parameter", type=str, default = 'results/')
parser.add_argument("--dropout_rate", help="dropout_rate", type=float, default = 0.0)
parser.add_argument("--al_scale", help="attn_loss scale", type=float, default = 1.0)
parser.add_argument("--ckpt", help="Load ckpt file", type=str, default = "")
parser.add_argument("--train_keys", help="train keys", type=str, default='train_keys.pkl')
parser.add_argument("--test_keys", help="test keys", type=str, default='test_keys.pkl')

def main(args):
    #hyper parameters
    ngpu = args.ngpu
    batch_size = args.batch_size
    data_path = os.path.join(args.data_path, args.dataset)
    args.train_keys = os.path.join(data_path, args.train_keys)
    args.test_keys = os.path.join(data_path, args.test_keys)
    result_dir = os.path.join(args.result_dir, "%s_%s_%d" % (args.dataset, args.tatic, args.nhop))

    if not os.path.isdir(result_dir):
        os.system('mkdir ' + result_dir)

    with open (args.test_keys, 'rb') as fp:
        test_keys = pickle.load(fp)

    print (f'Number of test data: {len(test_keys)}')

    # Initialize model
    # if args.ngpu > 0:
    #     cmd = utils.set_cuda_visible_device(args.ngpu)
    #     os.environ['CUDA_VISIBLE_DEVICES']=cmd[:-1]

    model = gnn(args)
    print ('Number of parameters: ', sum(p.numel() for p in model.parameters() if p.requires_grad))
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = utils.initialize_model(model, device, load_save_file=args.ckpt)

    test_dataset = BaseDataset(test_keys, data_path, embedding_dim=args.embedding_dim)
    test_dataloader = DataLoader(test_dataset, args.batch_size, \
        shuffle=False, num_workers = args.num_workers, collate_fn=collate_fn)

    # Starting evaluation
    test_true = []
    test_pred = []

    model.eval()
    st_eval = time.time()

    for sample in tqdm(test_dataloader):
        model.zero_grad()
        H, A1, A2, M, S, Y, V, _ = sample 
        H, A1, A2, M, S, Y, V = H.to(device), A1.to(device), A2.to(device),\
                            M.to(device), S.to(device), Y.to(device), V.to(device)
        
        # Test neural network
        pred = model.test_model((H, A1, A2, V))
        
        # Collect true label and predicted label
        test_true.append(Y.data.cpu().numpy())
        test_pred.append(pred.data.cpu().numpy())
            
    end = time.time()

    test_pred = np.concatenate(np.array(test_pred), 0)
    test_true = np.concatenate(np.array(test_true), 0)
    result_rows = []

    for conf_step in [0.5, 0.6, 0.7, 0.8, 0.9, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1]:
        test_pred_by_conf = test_pred.copy()
        test_pred_by_conf[test_pred_by_conf < conf_step] = 0
        test_pred_by_conf[test_pred_by_conf > 0] = 1

        test_roc = roc_auc_score(test_true, test_pred_by_conf)
        test_acc = accuracy_score(test_true, test_pred_by_conf)
        test_pre = precision_score(test_true, test_pred_by_conf)
        test_rec = recall_score(test_true, test_pred_by_conf)
        test_f1s = f1_score(test_true, test_pred_by_conf)
        test_prc = average_precision_score(test_true, test_pred_by_conf)
        test_time = (end - st_eval) / len(test_dataset)

        result_rows.append([conf_step, test_time, test_roc, test_prc, test_pre, test_rec, test_f1s, test_acc])
    
    with open(os.path.join(result_dir, "%s_result.csv"%args.dataset), "w", encoding="utf-8") as f:
        f.write("Confident,Execution Time,ROC AUC,PR AUC,Precision,Recall,F1-Score,Accuracy\n")
        for row in result_rows:
            f.write(','.join([str(x) for x in row]))
            f.write('\n')

if __name__ == "__main__":
    args = parser.parse_args()
    print(args)

    main(args)