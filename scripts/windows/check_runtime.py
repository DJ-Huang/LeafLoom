"""Fail installation early on broken/missing native DLLs; never load model weights."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import vault_rag  # register app-local MSVC DLL directories before native imports
import lancedb
import numpy
import pandas
import pystray
import torch
from sentence_transformers import SentenceTransformer

assert sys.version_info[:2]==(3,12) and sys.maxsize>2**32, 'Windows requires Python 3.12 x64'
assert torch.tensor([1.0,2.0],device='cpu').sum().item()==3.0
print(f'Native dependency check passed: Python x64, CPU PyTorch {torch.__version__}, LanceDB {lancedb.__version__}')
