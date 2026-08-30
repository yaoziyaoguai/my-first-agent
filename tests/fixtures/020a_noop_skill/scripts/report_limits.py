import resource


def _pair(name):
    return list(resource.getrlimit(name))


def run(arguments, inputs):
    del arguments, inputs
    return {
        "kind": "observation",
        "payload": {
            "limits": {
                "cpu": _pair(resource.RLIMIT_CPU),
                "as": _pair(resource.RLIMIT_AS),
                "fsize": _pair(resource.RLIMIT_FSIZE),
                "nofile": _pair(resource.RLIMIT_NOFILE),
                "core": _pair(resource.RLIMIT_CORE),
            },
        },
        "artifact": None,
    }
