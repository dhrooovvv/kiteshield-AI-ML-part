# Frozen workflow smoke set

Synthetic development set, committed before evaluation. It is not a broad model
benchmark: Gemma sees only a canonical goal and proposes step names; deterministic
code interprets the original text. Each case is checked with its declared expected
initial outcome. Approval and rejection decisions are sent separately by the test
harness using the human approver role, never by the model or task worker.

Report the dataset SHA-256, source commit, exact model/runtime pins, successful
cases/total with a two-sided Wilson 95% interval, failure reasons and elapsed time.
No independent-distribution or production-security inference is justified by this
small, intentionally selected set. Keep model failures in the denominator.
