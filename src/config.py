import yaml
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(path=None):
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    # Explicit encoding, not the locale default. On Windows that default is
    # cp1252, so a single non-ASCII character anywhere in the file -- including
    # in a comment -- raises UnicodeDecodeError and takes down every command
    # that loads config. YAML is UTF-8 by specification; this says so.
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _validate(config)
    return config


def _validate(config):
    required_keys = ["subreddits", "keywords", "scoring"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")

    if not isinstance(config["subreddits"], list) or len(config["subreddits"]) == 0:
        raise ValueError("subreddits must be a non-empty list")

    keywords = config["keywords"]
    if "high_intent" not in keywords and "medium_intent" not in keywords:
        raise ValueError("At least one of high_intent or medium_intent keywords required")
