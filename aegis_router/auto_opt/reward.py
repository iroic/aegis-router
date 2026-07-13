import numpy as np

def cvar(values: np.ndarray, alpha: float = 0.95) -> float:
    sorted_vals = np.sort(values)
    k = int(np.ceil((1.0 - alpha) * len(sorted_vals)))
    tail = sorted_vals[:max(k, 1)]
    return float(tail.mean())

def compute_reward(pkt,
                   delivered: bool,
                   drop_reason: str | None,
                   lambda_cvar: float = 0.7,
                   recent_risks: list[float] | None = None) -> float:
    reward = 12.0 if delivered else 0.0
    reward -= 6.0 * pkt.loss_risk
    reward -= 1.5 * pkt.latency
    if recent_risks:
        reward -= lambda_cvar * cvar(np.array(recent_risks), alpha=0.95)
    if drop_reason == "ttl_expired":
        reward -= 2.0
    elif drop_reason == "link_loss":
        reward -= 2.5
    return reward
