"""Sketch of the loop an AI agent would drive over the SAME scqo.Session API.

The agent only ever sees JSON: a catalog of measurements (with parameter schemas), the
structured result of each run, and the device snapshot it uses as memory. No Qblox or QM
object crosses the agent boundary — so the identical loop works on either backend.

    python scripts/ai_loop_demo.py
"""

from __future__ import annotations

import json

from scqo import Session
from scqo.testing import InMemoryDevice, SimulatedBackend

import lchqb.experiments  # noqa: F401  registers experiments


def agent_decide(catalog: list[dict], device_state: dict) -> tuple[str, dict]:
    """Stand-in for an LLM: pick an experiment + fill its parameters from the schema.

    A real agent would receive `catalog` as tool definitions and `device_state` as
    context, then emit a tool call. Here we hard-code one decision.
    """
    _ = catalog, device_state
    return "resonator_spectroscopy", {"qubits": list(device_state), "frequency_span_hz": 15e6}


def main() -> None:
    device = InMemoryDevice(
        {
            "q0": {"readout_freq": 5.95e9, "drive_freq": 3.87e9, "pi_amp": 0.20},
            "q1": {"readout_freq": 6.05e9, "drive_freq": 4.01e9, "pi_amp": 0.18},
        }
    )
    sess = Session(SimulatedBackend(device))

    # 1. perceive: what can I measure, and what is the device's current state?
    catalog = sess.catalog()
    print("catalog:", json.dumps([c["name"] for c in catalog], indent=2))

    # 2. decide -> 3. act -> 4. read result -> (loop)
    for _ in range(1):  # one iteration for the demo; a real loop continues until a goal is met
        experiment, params = agent_decide(catalog, sess.device_state())
        result = sess.run(experiment, params)
        print(f"ran {experiment} -> success={all(v == 'successful' for v in result['outcomes'].values())}")
        print("extracted:", json.dumps(result["fit"], indent=2))

    print("final device state:", json.dumps(sess.device_state(), indent=2))


if __name__ == "__main__":
    main()
