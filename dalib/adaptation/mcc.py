from typing import Optional
import torch
import torch.nn as nn
import torch.nn.functional as F
from dalib.modules.classifier import Classifier as ClassifierBase
from ._util import entropy


__all__ = ['MinimumClassConfusionLoss', 'ImageClassifier']


class MinimumClassConfusionLoss(nn.Module):
    r"""The `Minimum Class Confusion Loss <https://arxiv.org/abs/1912.03699>`_

    Minimum Class Confusion loss minimizes the class confusion in the target predictions.
    Given classifier predictions (logits before softmax) :math:`Z`, the definition of MCC loss is

    .. math::
           {\widehat Y_{ij}} = \frac{{\exp \left( {{Z_{ij}}/T} \right)}}{{\sum\nolimits_{j' = 1}^{|{\mathcal{C}}|}
           {\exp \left( {{Z_{ij'}}/T} \right)} }},
           where :math:`T` is the temperature for rescaling,
           {{\mathbf{C}}_{jj'}} = {\widehat{\mathbf{y}}}_{ \cdot j}^{\sf T}{{\widehat{\mathbf{y}}}_{ \cdot j'}},
           H(\widehat{\bf y}_{i\cdot})= - { \sum _{j=1 }^{ |{\cal {C}}| }{ { \widehat { Y }  }_{ ij }\
           log{ \widehat { Y }  }_{ ij } }  },
           {W_{ii}} = \frac{{B\left( {1 + \exp ( { - H( {{{{\widehat{\bf y}}}_{i \cdot }}} )} )} \right)}}
           {{\sum\limits_{i' = 1}^B {\left( {1 + \exp ( { - H( {{{{\widehat{\bf y}}}_{i' \cdot }}} )} )} \right)} }},
           {{\mathbf{C}}_{jj'}} = {\widehat{\mathbf{y}}}_{ \cdot j}^{\sf T}{\mathbf{W}}{{\widehat{\mathbf{y}}}_{ \cdot j'}}.
           {{{\widetilde{\mathbf C}}}_{jj'}} = \frac{{{{\mathbf{C}}_{jj'}}}}{{\sum\nolimits_{{j''} = 1}^
           {|{\mathcal{C}}|} {{{\mathbf{C}}_{j{j''}}}} }},
           {L_{{\rm{MCC}}}} ( {{{\widehat {\mathbf{Y}}}_t}} ) = \frac{1}{|{\cal {C}}|}\sum\limits_{j = 1}^
           {|{\mathcal{C}}|} {\sum\limits_{j' \ne j}^{|{\mathcal{C}}|} {\left| {{{{\widetilde{\mathbf C}}}_{jj'}}} \right|} }.

    You can see more details in `Minimum Class Confusion for Versatile Domain Adaptation <https://arxiv.org/abs/1912.03699>`

    Parameters:
        - **temperature** (float) : The temperature for rescaling, the prediction will shrink to vanilla softmax if
          temperature is 1.0.

    .. note::
        Make sure that temperature is larger than 0.

    Inputs: g_t
        - **g_t** (tensor): unnormalized classifier predictions on target domain, :math:`g^t`

    Shape:
        - g_t: :math:`(minibatch, C)` where C means the number of classes.
        - Output: scalar.

    Examples::
        >>> temperature = 2.0
        >>> loss = MinimumClassConfusionLoss(temperature)
        >>> # logits output from target domain
        >>> g_t = torch.randn(batch_size, num_classes)
        >>> output = loss(g_t)

    MCC can also serve as a regularizer for existing methods.
    Examples::
        >>> from dalib.modules.domain_discriminator import DomainDiscriminator
        >>> num_classes = 2
        >>> feature_dim = 1024
        >>> batch_size = 10
        >>> temperature = 2.0
        >>> discriminator = DomainDiscriminator(in_feature=feature_dim, hidden_size=1024)
        >>> cdan_loss = ConditionalDomainAdversarialLoss(discriminator, reduction='mean')
        >>> mcc_loss = MinimumClassConfusionLoss(temperature)
        >>> # features from source domain and target domain
        >>> f_s, f_t = torch.randn(batch_size, feature_dim), torch.randn(batch_size, feature_dim)
        >>> # logits output from source domain adn target domain
        >>> g_s, g_t = torch.randn(batch_size, num_classes), torch.randn(batch_size, num_classes)
        >>> total_loss = cdan_loss(g_s, f_s, g_t, f_t) + mcc_loss(g_t)
    """

    def __init__(self, temperature: float):
        super(MinimumClassConfusionLoss, self).__init__()
        self.temperature = temperature

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        batch_size, num_classes = logits.shape
        predictions = F.softmax(logits / self.temperature, dim=1)  # batch_size x num_classes
        entropy_weight = entropy(predictions).detach()
        entropy_weight = 1 + torch.exp(-entropy_weight)
        entropy_weight = (batch_size * entropy_weight / torch.sum(entropy_weight)).unsqueeze(dim=1)  # batch_size x 1
        class_confusion_matrix = torch.mm((predictions * entropy_weight).transpose(1, 0), predictions) # num_classes x num_classes
        class_confusion_matrix = class_confusion_matrix / torch.sum(class_confusion_matrix, dim=1)
        mcc_loss = (torch.sum(class_confusion_matrix) - torch.trace(class_confusion_matrix)) / num_classes
        return mcc_loss


def entropy(predictions: torch.Tensor) -> torch.Tensor:
    r"""Entropy of N predictions :math:`(p_1, p_2, ..., p_N)`.
    The definition is:

    .. math::
        d(p_1, p_2, ..., p_N) = -\dfrac{1}{K} \sum_{k=1}^K \log \left( \dfrac{1}{N} \sum_{i=1}^N p_{ik} \right)

    where K is number of classes.

    Parameters:
        - **predictions** (tensor): Classifier predictions. Expected to contain raw, normalized scores for each class
    """
    epsilon = 1e-5
    H = -predictions * torch.log(predictions + epsilon)
    return H.sum(dim=1)

class ImageClassifier(ClassifierBase):
    def __init__(self, backbone: nn.Module, num_classes: int, bottleneck_dim: Optional[int] = 256, **kwargs):
        bottleneck = nn.Sequential(
            nn.Linear(backbone.out_features, bottleneck_dim),
            nn.BatchNorm1d(bottleneck_dim),
            nn.ReLU()
        )
        super(ImageClassifier, self).__init__(backbone, num_classes, bottleneck, bottleneck_dim, **kwargs)
