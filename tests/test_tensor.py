import pytest
import numpy as np
from polymarket_bot.core.tensor import TensorCore
from polymarket_bot.core.matrix import TransitionMatrix

def test_tensor_sync():
    assets = ["BTC", "ETH"]
    windows = ["1H", "4H"]
    core = TensorCore(assets, windows, n_states=20)
    
    # Create mock matrices
    m1 = TransitionMatrix(n_states=20)
    m1.P = np.eye(20) # Identity matrix
    m1.is_valid = True
    
    m2 = TransitionMatrix(n_states=20)
    # Drift matrix
    m2.P = np.zeros((20, 20))
    for i in range(19): m2.P[i, i+1] = 1.0
    m2.P[19, 19] = 1.0
    m2.is_valid = True
    
    matrices = {
        "BTC:1H": m1,
        "ETH:4H": m2
    }
    
    core.sync(matrices)
    assert core.is_ready
    assert np.array_equal(core.tensor[0, 0], m1.P)
    assert np.array_equal(core.tensor[1, 1], m2.P)
    assert np.all(core.tensor[0, 1] == 0)

def test_tensor_correlations():
    assets = ["BTC", "ETH"]
    windows = ["1H"]
    core = TensorCore(assets, windows, n_states=20)
    
    m1 = TransitionMatrix(n_states=20)
    m1.P = np.eye(20)
    m1.is_valid = True
    
    # Identical matrices should have high correlation
    matrices = {
        "BTC:1H": m1,
        "ETH:1H": m1
    }
    
    core.sync(matrices)
    corr = core.get_correlations()
    assert corr[0, 1] == pytest.approx(1.0)
    assert corr[1, 0] == pytest.approx(1.0)

def test_trend_strength():
    assets = ["BTC"]
    windows = ["1H"]
    core = TensorCore(assets, windows, n_states=20)
    
    # Matrix that always transitions to state 0 (strong trend/sink)
    m = TransitionMatrix(n_states=20)
    m.P = np.zeros((20, 20))
    m.P[:, 0] = 1.0 
    m.is_valid = True
    
    core.sync({"BTC:1H": m})
    strength = core.get_trend_strength("BTC")
    assert strength > 0.5
