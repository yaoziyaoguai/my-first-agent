# Retry feature

Complete the bounded retry behavior for transient `RuntimeError` failures. The
new public name is `max_retries`; the command-line adapter must use the same
value. Negative limits are invalid, and an operation must never run more than
`1 + max_retries` times.

During the task the operator will add one correction: preserve the previous
`retry_count` keyword and CLI option as aliases. If both old and new names are
provided at once, reject the ambiguous request.
