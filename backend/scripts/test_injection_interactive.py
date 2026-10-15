"""Interactive terminal tester for the KiteShield injection screen."""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai_ml.injection_screen import InjectionScreen  # noqa: E402
from app.ai_ml.schemas import InjectionScreenResult  # noqa: E402


def _print_result(result: InjectionScreenResult, latency_ms: float) -> None:
    """Print only safe screening metadata, never the submitted text."""
    print("\nScreening result")
    print(f"  Predicted label: {result.label}")
    print(f"  Heuristic confidence: {result.confidence:.2f}")
    signals = ", ".join(result.matched_signals) or "none"
    print(f"  Matched rule identifiers: {signals}")
    print(f"  Model version: {result.model_version}")
    print(f"  Screening latency: {latency_ms:.3f} ms")


def main() -> None:
    """Read text until the user requests exit or the input stream ends."""
    screen = InjectionScreen()
    print("KiteShield prompt-injection tester")
    print('Enter text to screen. Type "exit" or "quit" to stop.')

    while True:
        try:
            text = input("\nText> ")
        except (EOFError, KeyboardInterrupt):
            print("\nTester stopped.")
            return

        if text.strip().casefold() in {"exit", "quit"}:
            print("Tester stopped.")
            return

        started_ns = time.perf_counter_ns()
        result = screen.screen(text)
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        _print_result(result, latency_ms)


if __name__ == "__main__":
    main()
