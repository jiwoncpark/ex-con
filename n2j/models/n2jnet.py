from typing import Optional, Tuple
from torch import Tensor
import torch
from torch.nn import (Module, ModuleList, ReLU, LayerNorm,
                      Sequential as Seq, Linear as Lin)
from torch_scatter import scatter_add
from torch_geometric.nn import MetaLayer
import torch
from torch import nn
from torch import optim

from nflows.flows.base import Flow
from nflows.distributions.normal import ConditionalDiagonalNormal
from nflows.transforms.base import CompositeTransform
from nflows.transforms.autoregressive import MaskedAffineAutoregressiveTransform
from nflows.transforms.permutations import ReversePermutation
from nflows.nn.nets import ResidualNet

__all__ = ['N2JNet']


class CustomMetaLayer(MetaLayer):
    def __init__(self, node_model=None, global_model=None):
        super(CustomMetaLayer, self).__init__(edge_model=None,
                                              node_model=node_model,
                                              global_model=global_model)
        pass

    def forward(self,
                x: Tensor,
                u: Optional[Tensor] = None,
                batch: Optional[Tensor] = None) -> Tuple[Tensor, Tensor]:
        if self.node_model is not None:
            x = self.node_model(x, u, batch)

        if self.global_model is not None:
            u = self.global_model(x, u, batch)
        return x, u


def get_flow(dim_in, dim_hidden, dim_out, n_layers):
    base_dist = ConditionalDiagonalNormal(shape=[dim_in],
                                          context_encoder=nn.Linear(dim_out, dim_hidden))
    transforms = []
    for _ in range(n_layers):
        transforms.append(ReversePermutation(features=dim_in))
        transforms.append(MaskedAffineAutoregressiveTransform(features=dim_in,
                                                              hidden_features=dim_hidden,
                                                              context_features=dim_out))
    transform = CompositeTransform(transforms)
    flow = Flow(transform, base_dist)
    return flow


class N2JNet(Module):
    def __init__(self, dim_in, dim_out_local, dim_out_global, dim_local, dim_global,
                 dim_hidden=20, dim_pre_aggr=20, n_iter=20, n_out_layers=5):
        super(N2JNet, self).__init__()
        self.dim_in = dim_in
        self.dim_out_local = dim_out_local
        self.dim_out_global = dim_out_global
        self.dim_hidden = dim_hidden
        self.dim_local = dim_local
        self.dim_global = dim_global
        self.dim_pre_aggr = dim_pre_aggr
        self.n_iter = n_iter
        self.n_out_layers = n_out_layers
        # MLP for initially encoding local
        self.mlp_node_init = Seq(Lin(self.dim_in, self.dim_hidden),
                                 ReLU(),
                                 Lin(self.dim_hidden, self.dim_hidden),
                                 ReLU(),
                                 Lin(self.dim_hidden, self.dim_local),
                                 LayerNorm(self.dim_local))
        # MLPs for encoding local and global
        meta_layers = ModuleList()
        for i in range(self.n_iter):
            node_model = NodeModel(self.dim_local, self.dim_global, self.dim_hidden)
            global_model = GlobalModel(self.dim_local, self.dim_global,
                                       self.dim_hidden, self.dim_pre_aggr)
            meta = CustomMetaLayer(node_model=node_model, global_model=global_model)
            meta_layers.append(meta)
        self.meta_layers = meta_layers
        # Networks for local and global output
        self.net_out_local = get_flow(self.dim_local, self.dim_hidden,
                                      self.dim_out_local, self.n_out_layers)
        self.net_out_global = get_flow(self.dim_global, self.dim_hidden,
                                       self.dim_out_global, self.n_out_layers)

    def forward(self, data):
        x = data.x  # [n_nodes, n_features]
        y_local = data.y_local  # [n_nodes, 2]
        y = data.y  # [batch_size, 1]
        batch = data.batch  # [batch_size,]
        batch_size = data.y.shape[0]
        # Init node and global encodings x, u
        x = self.mlp_node_init(x)  # [n_nodes, dim_local]
        u = torch.zeros(batch_size, self.dim_global).to(x.dtype).to(x.device)
        for i, meta in enumerate(self.meta_layers):
            x, u = meta(x=x, u=u, batch=batch)
        # x : [n_nodes, dim_local]
        # u : [batch_size, dim_global]
        logp_local = self.net_out_local.log_prob(x, context=y_local)  # [n_nodes, 2]
        logp_global = self.net_out_global.log_prob(u, context=y)  # [batch_size, 1]
        return logp_local, logp_global


class NodeModel(Module):

    def __init__(self, dim_local, dim_global, dim_hidden):
        super(NodeModel, self).__init__()
        self.dim_local = dim_local
        self.dim_global = dim_global
        self.dim_hidden = dim_hidden
        self.dim_concat = self.dim_local + self.dim_global
        self.mlp = Seq(Lin(self.dim_concat, self.dim_hidden),
                       ReLU(),
                       Lin(self.dim_hidden, self.dim_hidden),
                       ReLU(),
                       Lin(self.dim_hidden, self.dim_local),
                       LayerNorm(self.dim_local))

    def forward(self, x, u, batch):
        # x ~ [n_nodes, dim_local]
        # u ~ [batch, dim_global] but u[batch] ~ [n_nodes, dim_global]
        out = torch.cat([x, u[batch]], dim=-1)  # [n_nodes, dim_local + dim_global]
        out = self.mlp(out) + x  # [n_nodes, dim_local]
        return out


class GlobalModel(Module):
    def __init__(self, dim_local, dim_global, dim_hidden, dim_pre_aggr):
        super(GlobalModel, self).__init__()
        self.dim_local = dim_local
        self.dim_global = dim_global
        self.dim_hidden = dim_hidden
        self.dim_concat = self.dim_local + self.dim_global
        self.dim_pre_aggr = dim_pre_aggr

        # MLP prior to aggregating node encodings
        self.mlp_pre_aggr = Seq(Lin(self.dim_concat, self.dim_hidden),
                                ReLU(),
                                Lin(self.dim_hidden, self.dim_hidden),
                                ReLU(),
                                Lin(self.dim_hidden, self.dim_pre_aggr),
                                LayerNorm(self.dim_pre_aggr))
        # MLP after aggregating node encodings
        self.mlp_post_aggr = Seq(Lin(self.dim_pre_aggr+self.dim_global, self.dim_hidden),
                                 ReLU(),
                                 Lin(self.dim_hidden, self.dim_hidden),
                                 ReLU(),
                                 Lin(self.dim_hidden, self.dim_global),
                                 LayerNorm(self.dim_global))

    def forward(self, x, u, batch):
        out = torch.cat([x, u[batch]], dim=-1)  # [n_nodes, dim_local + dim_global]
        out = self.mlp_pre_aggr(out)  # [n_nodes, self.dim_pre_aggr]
        out = scatter_add(out, batch, dim=0)  # [batch_size, dim_pre_aggr]
        out = torch.cat([out, u], dim=-1)  # [batch_size, dim_pre_aggr + dim_global]
        out = self.mlp_post_aggr(out)  # [batch_size, dim_global]
        out += u  # [batch_size, dim_global]
        return out


if __name__ == '__main__':
    net = N2JNet(dim_in=4, dim_out_local=2, dim_out_global=1,
                 dim_local=11, dim_global=7,
                 dim_hidden=20, dim_pre_aggr=20, n_iter=3)

    class Batch:
        def __init__(self, x, y_local, y, batch):
            self.x = x
            self.y_local = y_local
            self.y = y
            self.batch = batch

    batch = Batch(x=torch.randn(5, 4),
                  y_local=torch.randn(5, 2),
                  y=torch.randn(3, 1),
                  batch=torch.LongTensor([0, 0, 1, 1, 2]))

    out = net(batch)

