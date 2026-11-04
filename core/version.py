"""
Version and repository metadata for Audio Visualizer.
"""

import re
from typing import Tuple

__version__ = "2.2.1"
GITHUB_REPO = "Helvior-dev/Audio-Visualizer"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
LATEST_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Parse a semver string like 'v2.0.0', '2.1.3', 'v3.0-rc1' into a comparable tuple of ints.
    """
    if not version_str:
        return (0, 0, 0)
    cleaned = version_str.strip().lstrip("vV")
    # Match digit sequences
    parts = re.findall(r"\d+", cleaned)
    num_parts = [int(p) for p in parts]
    while len(num_parts) < 3:
        num_parts.append(0)
    return tuple(num_parts[:3])


def is_newer_version(remote_version_str: str, current_version_str: str = __version__) -> bool:
    """
    Compare remote version with current version. Returns True if remote is strictly greater.
    """
    return parse_version(remote_version_str) > parse_version(current_version_str)
