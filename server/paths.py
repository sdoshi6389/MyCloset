"""Central resolution of on-disk output directories.

In production (Railway) these point at the mounted persistent volume via env
vars so generated files survive restarts / sleep / redeploys. With no env vars
set (local dev) they fall back to the original cwd-relative folders — unchanged
behavior.
"""
import os


def _resolve(env_key: str, default_name: str) -> str:
    path = os.environ.get(env_key) or os.path.join(os.getcwd(), default_name)
    os.makedirs(path, exist_ok=True)
    return path


ICON_OUTPUTS_DIR      = _resolve("ICON_OUTPUTS_DIR",      "icon_outputs")
MANNEQUIN_OUTPUTS_DIR = _resolve("MANNEQUIN_OUTPUTS_DIR", "mannequin_outputs")
EMOJI_OUTPUTS_DIR     = _resolve("EMOJI_OUTPUTS_DIR",     "emoji_outputs")
GENERATED_OUTFITS_DIR = _resolve("GENERATED_OUTFITS_DIR", "generated_outfits")
