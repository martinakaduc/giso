import time
import torch
import torch.nn as nn
import torch.nn.functional as F
from utils import *
from layers import GAT_gate
from multiprocessing import Pool

class gnn(torch.nn.Module):
    def __init__(self, args):
        super(gnn, self).__init__()
        n_graph_layer = args.n_graph_layer
        d_graph_layer = args.d_graph_layer
        n_FC_layer = args.n_FC_layer
        d_FC_layer = args.d_FC_layer
        self.dropout_rate = args.dropout_rate 


        self.layers1 = [d_graph_layer for i in range(n_graph_layer+1)]
        self.gconv1 = nn.ModuleList([GAT_gate(self.layers1[i], self.layers1[i+1], 2 * i + 1, args.ngpu>0) 
                                    for i in range(len(self.layers1)-1)]) 
        
        self.FC = nn.ModuleList([nn.Linear(self.layers1[-1], d_FC_layer) if i==0 else
                                 nn.Linear(d_FC_layer, 1) if i==n_FC_layer-1 else
                                 nn.Linear(d_FC_layer, d_FC_layer) for i in range(n_FC_layer)])
        
        self.embede = nn.Linear(2*args.embedding_dim, d_graph_layer, bias = False)
        self.theta = torch.tensor(args.al_scale)
        self.zeros = torch.zeros(1)
        if args.ngpu > 0:
            self.theta = self.theta.cuda()
            self.zeros = self.zeros.cuda()

    def embede_graph(self, data):
        c_hs, c_adjs1, c_adjs2, c_valid = data
        c_hs = self.embede(c_hs)
        attention = None

        for k in range(len(self.gconv1)):
            c_hs1 = self.gconv1[k](c_hs, c_adjs1)
            if k==len(self.gconv1)-1:
                c_hs2, attention = self.gconv1[k](c_hs, c_adjs2, True)
            else:
                c_hs2 = self.gconv1[k](c_hs, c_adjs2)
            c_hs = c_hs2-c_hs1
            c_hs = F.dropout(c_hs, p=self.dropout_rate, training=self.training)
        c_hs = c_hs*c_valid.unsqueeze(-1).repeat(1, 1, c_hs.size(-1))
        c_hs = c_hs.sum(1)

        return c_hs, F.normalize(attention)

    def fully_connected(self, c_hs):
        # regularization = torch.empty(len(self.FC)*1-1, device=c_hs.device)

        for k in range(len(self.FC)):
            #c_hs = self.FC[k](c_hs)
            if k<len(self.FC)-1:
                c_hs = self.FC[k](c_hs)
                c_hs = F.dropout(c_hs, p=self.dropout_rate, training=self.training)
                c_hs = F.relu(c_hs)
            else:
                c_hs = self.FC[k](c_hs)

        c_hs = torch.sigmoid(c_hs)

        return c_hs

    def train_model(self, data, attn_masking):
        #embede a graph to a vector
        c_hs, attention = self.embede_graph(data)

        #fully connected NN
        c_hs = self.fully_connected(c_hs)
        c_hs = c_hs.view(-1) 

        #note that if you don't use concrete dropout, regularization 1-2 is zero
        return c_hs, self.cal_attn_loss(attention, attn_masking)

    def cal_attn_loss(self, attention, attn_masking):
        mapping, samelb = attn_masking

        top = torch.exp(-(attention * mapping))
        top = torch.where(mapping == 1.0, top, self.zeros)
        top = top.sum((1,2))

        topabot = torch.exp(-(attention * samelb))
        topabot = torch.where(samelb == 1.0, topabot, self.zeros)
        topabot = topabot.sum((1,2))
        
        return (top / (topabot - top + 1)).sum(0) * self.theta / attention.shape[0]

    def get_refined_adjs2(self, data):
        c_hs, c_adjs1, c_adjs2, c_valid = data
        c_hs = self.embede(c_hs)
        c_adjs2 = torch.exp(-torch.pow(c_adjs2-self.mu.expand_as(c_adjs2), 2)/self.dev) + c_adjs1

        for k in range(len(self.gconv1)):
            c_hs1 = self.gconv1[k](c_hs, c_adjs1)
            if k==len(self.gconv1)-1:
                c_hs2, attention = self.gconv1[k](c_hs, c_adjs2, True)
                return F.normalize(attention)
            else:
                c_hs2 = self.gconv1[k](c_hs, c_adjs2)
            c_hs = c_hs2-c_hs1
            c_hs = F.dropout(c_hs, p=self.dropout_rate, training=self.training)

        return c_adjs2
