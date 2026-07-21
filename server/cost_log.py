"""
API cost logger — prints a cost line for every OpenAI call and appends to
server/api_cost_log.jsonl so you can review them any time.

Usage (inside any function that calls OpenAI):

    from cost_log import log_chat_cost, log_image_cost

    # after a chat.completions call:
    log_chat_cost("gpt-4o", response.usage, context="my_file.jpg")

    # after an images.edit / images.generate call (flat per-image pricing):
    log_image_cost("gpt-image-1", size="1024x1024", fidelity="high", context="my_file.jpg")
"""
import json
import os
from datetime import datetime, timezone

_LOG_PATH = os.path.join(os.path.dirname(__file__), "api_cost_log.jsonl")

# ── Pricing tables (USD) ──────────────────────────────────────────────────────
# GPT-4o  (as of 2025): $2.50 / 1M input tokens, $10.00 / 1M output tokens
# gpt-image-1 1024×1024: ~$0.04 standard edit/generate
#   with input_fidelity="high" the model processes more image tiles → ~$0.07
# dall-e-3 1024×1024 standard: $0.04 / image
# dall-e-2 1024×1024: $0.02 / image

_CHAT_PRICE: dict[str, dict] = {
    "gpt-4o":          {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":     {"input": 0.15,  "output": 0.60},
    "gpt-4-turbo":     {"input": 10.00, "output": 30.00},
}

_IMAGE_PRICE: dict[str, dict] = {
    # (model, size, fidelity) → cost per image
    ("gpt-image-1",  "1024x1024", "high"):     0.07,
    ("gpt-image-1",  "1024x1024", "medium"):   0.05,
    ("gpt-image-1",  "1024x1024", "low"):      0.04,
    ("gpt-image-1",  "1024x1024", None):       0.04,
    ("gpt-image-1",  "512x512",   None):       0.02,
    ("dall-e-3",     "1024x1024", None):       0.04,
    ("dall-e-3",     "1024x1792", None):       0.08,
    ("dall-e-2",     "1024x1024", None):       0.02,
    ("dall-e-2",     "512x512",   None):       0.018,
    ("dall-e-2",     "256x256",   None):       0.016,
    ("rembg",            "native",    None):  0.00,
    ("gemini-2.5-flash-image", "1024x1024", None):  0.01,   # image-gen ~1¢/call
    ("gemini-2.5-flash-image", "vision",    None):  0.0005, # bounding-box vision call only
}

_session_total: float = 0.0


def _append(record: dict):
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def log_chat_cost(model: str, usage, context: str = "") -> float:
    """
    Log cost for a chat.completions call.
    usage = response.usage  (has .prompt_tokens and .completion_tokens)
    Returns estimated cost in USD.
    """
    global _session_total
    prices = _CHAT_PRICE.get(model, {"input": 0.0, "output": 0.0})
    input_tok  = getattr(usage, "prompt_tokens",     0) or 0
    output_tok = getattr(usage, "completion_tokens", 0) or 0
    cost = (input_tok * prices["input"] + output_tok * prices["output"]) / 1_000_000
    _session_total += cost

    record = {
        "ts":            datetime.now(timezone.utc).isoformat(),
        "call_type":     "chat",
        "model":         model,
        "input_tokens":  input_tok,
        "output_tokens": output_tok,
        "cost_usd":      round(cost, 5),
        "session_total": round(_session_total, 5),
        "context":       context,
    }
    _append(record)
    print(
        f"💸 [{model}] chat  in={input_tok} out={output_tok}  "
        f"cost=${cost:.4f}  session=${_session_total:.4f}  | {context}",
        flush=True,
    )
    return cost


def log_image_cost(model: str, size: str = "1024x1024", fidelity: str | None = None,
                   call_type: str = "image_edit", context: str = "") -> float:
    """
    Log cost for an images.edit or images.generate call.
    Returns estimated cost in USD.
    """
    global _session_total
    key = (model, size, fidelity)
    cost = _IMAGE_PRICE.get(key) or _IMAGE_PRICE.get((model, size, None)) or 0.04
    _session_total += cost

    record = {
        "ts":            datetime.now(timezone.utc).isoformat(),
        "call_type":     call_type,
        "model":         model,
        "size":          size,
        "fidelity":      fidelity,
        "cost_usd":      round(cost, 5),
        "session_total": round(_session_total, 5),
        "context":       context,
    }
    _append(record)
    print(
        f"💸 [{model}] {call_type}  size={size} fidelity={fidelity}  "
        f"cost=${cost:.4f}  session=${_session_total:.4f}  | {context}",
        flush=True,
    )
    return cost


def print_session_summary():
    """Print a summary of costs logged this process session."""
    print(f"\n{'='*55}")
    print(f"  OpenAI spend this session:  ${_session_total:.4f}")
    print(f"  Full log: {_LOG_PATH}")
    print(f"{'='*55}\n", flush=True)


def read_log_summary(last_n: int = 20):
    """Read and print the last N entries from the log file."""
    if not os.path.exists(_LOG_PATH):
        print("No cost log found yet.")
        return
    with open(_LOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    entries = [json.loads(l) for l in lines if l.strip()]
    total = sum(e.get("cost_usd", 0) for e in entries)
    print(f"\n=== API Cost Log (last {min(last_n, len(entries))} of {len(entries)} calls) ===")
    for e in entries[-last_n:]:
        ts = e["ts"][11:19]  # HH:MM:SS
        if e["call_type"] == "chat":
            print(f"  {ts}  {e['model']:20s}  chat      in={e['input_tokens']:5d} out={e['output_tokens']:5d}  ${e['cost_usd']:.4f}  {e.get('context','')}")
        else:
            print(f"  {ts}  {e['model']:20s}  {e['call_type']:12s}  size={e.get('size','')}  ${e['cost_usd']:.4f}  {e.get('context','')}")
    print(f"\n  TOTAL all-time: ${total:.4f}\n", flush=True)
