from pathlib import Path

import yaml

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
MANIFEST_PATH = DATA_ROOT / "manifest.yaml"


def load_manifest() -> list[dict]:
    with open(MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f)
    return manifest["datasets"]
