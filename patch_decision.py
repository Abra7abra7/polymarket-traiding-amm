
import sys, os
# Monkey-patch DecisionEngine.should_enter to log every call
original_should_enter = None

def patched_should_enter(self, P, state, price):
    result, meta = original_should_enter(self, P, state, price)
    with open("/tmp/decision_log.txt", "a") as f:
        f.write(f"{meta.get('persist',0):.4f} {meta.get('p_hat',0):.4f} {meta.get('gap',0):.4f} tau={self.tau} eps={self.eps} -> {result}\n")
    return result, meta

from polymarket_bot.core.decision import DecisionEngine
original_should_enter = DecisionEngine.should_enter
DecisionEngine.should_enter = patched_should_enter
