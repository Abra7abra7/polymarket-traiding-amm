"""
Tensor Core — Matrix of Matrices Data Architecture.

Aggregates individual TransitionMatrix objects into a multi-dimensional tensor
to perform cross-asset analysis, correlation detection, and trend strength estimation.

Structure: [Asset, Timeframe, From_State, To_State]
"""

import numpy as np
from typing import Dict, List, Optional
from .matrix import TransitionMatrix

class TensorCore:
    """
    Manages the 'Matrix of Matrices' for the trading system.
    """

    def __init__(self, assets: List[str], windows: List[str], n_states: int = 20):
        self.assets = assets
        self.windows = windows
        self.n_states = n_states
        
        # Mapping for tensor indexing
        self.asset_to_idx = {asset: i for i, asset in enumerate(assets)}
        self.window_to_idx = {window: i for i, window in enumerate(windows)}
        
        # The Core Tensor [Market, Timeframe, N, N]
        self.tensor = np.zeros((len(assets), len(windows), n_states, n_states))
        self.is_ready = False

    def sync(self, matrices: Dict[str, TransitionMatrix]):
        """
        Synchronize the tensor with the latest individual transition matrices.
        
        Args:
            matrices: Dict mapping "asset:window" -> TransitionMatrix
        """
        for key, matrix in matrices.items():
            if ":" not in key: continue
            asset, window = key.split(":")
            
            if asset in self.asset_to_idx and window in self.window_to_idx:
                a_idx = self.asset_to_idx[asset]
                w_idx = self.window_to_idx[window]
                
                P = matrix.get_matrix()
                if P is not None:
                    self.tensor[a_idx, w_idx] = P
        
        self.is_ready = True

    def get_correlations(self) -> np.ndarray:
        """
        Calculate asset-wise correlations based on transition matrix similarity.
        Uses Frobenius norm of the difference between matrices as a distance metric.
        
        Returns:
            Correlation matrix [Market x Market]
        """
        n = len(self.assets)
        corr = np.eye(n)
        
        if not self.is_ready:
            return corr

        for i in range(n):
            for j in range(i + 1, n):
                # Compare matrices across all timeframes (mean similarity)
                similarities = []
                for w in range(len(self.windows)):
                    m1 = self.tensor[i, w]
                    m2 = self.tensor[j, w]
                    
                    if np.any(m1) and np.any(m2):
                        # Similarity = 1 - (Normalized Frobenius Norm of diff)
                        diff = np.linalg.norm(m1 - m2)
                        norm_factor = np.linalg.norm(m1) + np.linalg.norm(m2)
                        sim = 1.0 - (diff / norm_factor) if norm_factor > 0 else 0.0
                        similarities.append(sim)
                
                avg_sim = np.mean(similarities) if similarities else 0.0
                corr[i, j] = avg_sim
                corr[j, i] = avg_sim
                
        return corr

    def get_trend_strength(self, asset: str) -> float:
        """
        Detect trend strength using the principal eigenvalue of the aggregate matrix.
        A larger gap between the first and second eigenvalues indicates a stronger, 
        more stable transition regime (Trend Strength).
        """
        if asset not in self.asset_to_idx:
            return 0.0
            
        a_idx = self.asset_to_idx[asset]
        # Average matrix across timeframes
        avg_matrix = np.mean(self.tensor[a_idx], axis=0)
        
        if not np.any(avg_matrix):
            return 0.0
            
        try:
            eigenvalues = np.linalg.eigvals(avg_matrix)
            # Sort by absolute value descending
            evals = sorted(np.abs(eigenvalues), reverse=True)
            if len(evals) >= 2:
                # Spectral gap
                return float(evals[0] - evals[1])
        except np.linalg.LinAlgError:
            pass
            
        return 0.0

    def get_aggregate_p_hat(self, asset: str, current_state: int) -> float:
        """
        Get an ensemble prediction by averaging across all timeframes.
        """
        if asset not in self.asset_to_idx:
            return 0.5
            
        a_idx = self.asset_to_idx[asset]
        predictions = []
        
        for w in range(len(self.windows)):
            P = self.tensor[a_idx, w]
            if np.any(P):
                next_state = np.argmax(P[current_state])
                prob = P[current_state, next_state]
                predictions.append(prob)
                
        return float(np.mean(predictions)) if predictions else 0.5
