"""Small real physics checks, not LLM self-voting. Each verifier has a narrow scope."""
from __future__ import annotations
from sympy import symbols, log, diff, simplify

TESTS = {
    "csk_delta_rg": "Show difference of two CS kernels has zero common-scale derivative under a shared anomalous dimension",
    "csk_experimental_overclaim": "Audit whether kernel RG invariance alone guarantees model-independent EEC extraction"
}

def check(test_id: str) -> dict:
    if test_id == "csk_delta_rg":
        mu, mu0, gamma, k1, k2 = symbols("mu mu0 gamma K_1 K_2", positive=True)
        K1 = k1 - gamma * log(mu / mu0)
        K2 = k2 - gamma * log(mu / mu0)
        result = simplify(diff(K1 - K2, mu))
        return {"test": test_id, "verdict": "passed_under_assumptions" if result == 0 else "failed",
                "formal_check": f"d/dmu [K1(mu)-K2(mu)] = {result}",
                "assumptions": ["Common anomalous dimension", "Same representation", "Compatible evolution convention"],
                "limits": ["No inference about experimental extraction", "Not a check of factorization accuracy"]}
    if test_id == "csk_experimental_overclaim":
        return {"test": test_id, "verdict": "not_established",
                "formal_check": "RG invariance imposes no algebraic cancellation of process-dependent initial TMD inputs.",
                "assumptions": ["Cross-process factorization needs separate derivation"],
                "limits": ["This is a logical-sufficiency audit, not a disproof of every possible construction",
                           "A complete factorization calculation and mock-data closure test are required"]}
    raise KeyError("unknown verification test")
