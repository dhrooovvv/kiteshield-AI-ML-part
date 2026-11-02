# Local model and added dependency notices

## Invoice extraction / offline attack generation

The inspected local artifact is **unsloth/gemma-4-12B-it-qat-GGUF**,
`gemma-4-12B-it-qat-UD-Q4_K_XL.gguf`, imported into Ollama as
`kiteshield-gemma4:12b`. It is a quantized derivative of Google's Gemma 4 12B
instruction model, not an independently trained KiteShield model.

The publisher model card declares **Apache License 2.0**:
https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/blob/main/README.md

Google's license reference: https://ai.google.dev/gemma/docs/gemma_4_license

Retain the upstream license and attribution with any redistributed model files.
Model weights are local dependencies; they are not included in this repository.
The extraction interface does not provide tools, registry choices, wallet keys,
credentials, or an RPC client to the model. This is logical separation, not an
operating-system sandbox or hardware signing boundary.

## Runtime dependencies

- Ollama: MIT license, https://github.com/ollama/ollama/blob/main/LICENSE
- pypdf: BSD-3-Clause, https://github.com/py-pdf/pypdf/blob/main/LICENSE

Other dependencies retain their upstream licenses and notices.

## Gemma 4 26B-A4B local integration (2026-10-25)

Current intended local model: **unsloth/gemma-4-26B-A4B-it-GGUF**, quantization
`gemma-4-26B-A4B-it-UD-IQ4_NL.gguf`, Ollama alias
`kiteshield-gemma4:26b-a4b-iq4nl`.

- Upstream revision: `c099eb48e663fd284577b04978a94ffccb261841`.
- File size: 13,613,037,280 bytes.
- SHA-256: `eeb867f279ea5a3d52a0dc15fe8ada677b3328a328530957f3f9a5da93cb10b8`.
- Publisher-declared license: **Apache License 2.0**.
- Model card: https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF

This is a quantized Google/Unsloth model, not a KiteShield-trained model. Model
weights remain local, outside Git. Only text inference is used; companion vision
and MTP files are not imported into this text-only Ollama alias. Existing 12B
benchmark/evaluation artifacts remain historical and do not establish this model's
accuracy. Deterministic authorization and the Horizon/Bastion screeners are unchanged.

## Active model: Gemma 4 12B Q4_K_M (2026-10-25)

The operator selected **unsloth/gemma-4-12b-it-GGUF**, exact variant
`gemma-4-12b-it-Q4_K_M.gguf`, imported as **`kiteshield-gemma4:12b-q4km`**.
This supersedes the intended 26B integration above. The 26B file remains on disk
but is not the active configured model. The older `kiteshield-gemma4:12b` alias is
a different QAT variant; historical evaluation results using it remain historical.

- Publisher-declared license: **Apache License 2.0**.
- Source: https://huggingface.co/unsloth/gemma-4-12b-it-GGUF
- Revision: `fc034cfff751157913579611efad8462ac1be606`.
- Exact GGUF size: 7,121,861,440 bytes.
- Verified SHA-256: `0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42`.
- Text-only import. No remote model code, vision projector or MTP component is used.

Retain upstream license/attribution when redistributing weights. Weights are not
committed to this source repository. A small development smoke check does not
replace the earlier frozen evaluation or establish this variant's general accuracy.


## Optional local voice and guarded vault (2026-11-02)

- whisper.cpp v1.9.5, commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`: MIT.
  [Pinned source and license](https://github.com/ggml-org/whisper.cpp/tree/v1.9.5).
  Built locally from the official archive; no installation script or wallet SDK.
- Whisper base.en model, Hugging Face revision `5359861c739e955e79d9a303bcbc70fb988958b1`:
  MIT, model SHA-256 `a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002`.
- CMake 4.1.2 macOS universal official archive: BSD-3-Clause (bundled LICENSE.rst).
  SHA-256 `3be85f5b999e327b1ac7d804cbc9acd767059e9f603c42ec2765f6ab68fbd367`.
- solc-js 0.8.30: MIT JavaScript wrapper, underlying Solidity compiler GPL-3.0.
  Official npm archive verified with SHA-512 integrity recorded in the committed contract artifact.
  No npm installation or package lifecycle scripts were run. Existing Node executes soljson directly.
- Foundry v1.3.1: MIT OR Apache-2.0. Official darwin_arm64 archive SHA-256
  `e3c880d28eae2a150f3f01a674b3cd6a130d6d3f16685740cd1e16538b58a4a5`.
  Used for local Solidity tests, never wallet signing or deployment.
- GuardedVault Solidity source: MIT, no external Solidity dependencies.
  Compiled with 0.8.30, Cancun bytecode, optimizer 200 runs. Live RPC estimates
  determine Sepolia fees; Foundry's older local gas schedule is not a live fee prediction.

Tools, model weights and private keys stay outside Git. No secrets were supplied to
compiler downloads, source repositories, Gemma or the local transcription process.
The vault uses KiteShield's existing signer; no third-party wallet/signing path is adopted.
