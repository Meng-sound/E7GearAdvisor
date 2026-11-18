"""Vectorized versions of the existing cosine scores; no new thresholds."""
import math
from collections import OrderedDict
_cache=OrderedDict()
def ranked(shape,templates,ratio=None):
    try:import numpy as np
    except ImportError:return None
    key=(id(templates),ratio is not None);entry=_cache.get(key)
    if entry is None or entry[0] is not templates:
        labels=[];samples=[];ratios=[]
        for label,values in templates.items():
            for value in values:
                labels.append(label);samples.append(value['shape'] if ratio is not None else value)
                if ratio is not None:ratios.append(value['ratio'])
        matrix=np.asarray(samples,dtype=np.float64)
        norms=np.sqrt(np.einsum('ij,ij->i',matrix,matrix))
        matrix=matrix/np.maximum(norms[:,None],1e-30)
        entry=(templates,labels,matrix,np.asarray(ratios));_cache[key]=entry
        if len(_cache)>8:_cache.popitem(last=False)
    _,labels,matrix,ratios=entry;vector=np.asarray(shape,dtype=np.float64)
    scores=np.einsum('ij,j->i',matrix,vector)/max(float(np.sqrt(np.einsum('i,i->',vector,vector))),1e-30)
    if ratio is not None:scores-=.10*np.abs(np.log(ratio/ratios))
    return sorted(((float(score),label) for score,label in zip(scores,labels)),reverse=True)
