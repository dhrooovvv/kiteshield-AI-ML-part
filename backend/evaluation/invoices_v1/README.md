# Held-out invoice evaluation v1

Synthetic text invoices only, denominated in Sepolia test ETH. This is not a
representative business-invoice dataset or evidence of universal injection safety.
The evaluation clock is fixed at 2026-10-24 UTC. The registry fixture contains
Northstar Services, a public fixture payout address and a 0.00005 ETH maximum.

Freeze and commit this directory before its first inference/evaluation run. Do not
change prompts, checks or thresholds using results from this set. Development
fixtures and a separately generated red-team demonstration are not this set.
The one-shot runner refuses a second run and records source fingerprints, model
identity, dataset hash, outcomes and raw structured extractions, but no credentials.
If the runtime is unavailable, record that limitation; do not invent measurements.

Counterfactuals remove one checking layer in an offline decision replay only. They
never disable a deployed gate, sign a real transaction or broadcast to any RPC.
If a preceding extraction failure makes a layer unevaluable, say unknown rather
than pretending the invoice would pass.
