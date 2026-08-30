import os


def run(arguments, inputs):
    return {
        "kind": "observation",
        "payload": {
            "ambient_canary_present": "FIRST_AGENT_E2M_CANARY" in os.environ,
            "entrypoint": arguments["entrypoint"],
            "input_digests": sorted(inputs),
        },
        "artifact": None,
    }
