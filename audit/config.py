"""Load + validate a client audit config."""
import json
import os


REQUIRED = ["client", "live_url", "sf_internal_all_csv"]

DEFAULTS = {
    "mockup_url": None,
    "sf_images_csv": None,
    "exclude_url_patterns": [],
    "pagespeed_strategy": "mobile",
    "drive_folder_id": None,
}


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    for key in REQUIRED:
        if not cfg.get(key):
            raise ValueError(f"Config missing required field: {key}")
    merged = {**DEFAULTS, **cfg}

    # Resolve CSV paths relative to project root (dir containing this package's parent).
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for key in ("sf_internal_all_csv", "sf_images_csv"):
        if merged.get(key) and not os.path.isabs(merged[key]):
            merged[key] = os.path.join(root, merged[key])
    if merged.get(key) and not os.path.exists(merged["sf_internal_all_csv"]):
        raise FileNotFoundError(merged["sf_internal_all_csv"])
    return merged
