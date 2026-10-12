# Configuration module instructions

Keep `resolve_config(defaults, environment, project, cli)` as the public interface.
The intended precedence from weakest to strongest is defaults, environment,
project, then explicit CLI values.
