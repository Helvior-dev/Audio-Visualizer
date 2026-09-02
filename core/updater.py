"""
GitHub Release Update Checker for Audio Visualizer.
Queries GitHub Releases API asynchronously in a worker thread.
"""

import json
import urllib.request
import urllib.error
from PyQt6.QtCore import QThread, pyqtSignal
from .version import __version__, LATEST_API_URL, RELEASES_URL, is_newer_version


class UpdateCheckWorker(QThread):
    """
    Background worker that queries GitHub API for the latest release.
    """
    # Emitted when a strictly newer release is found: payload is dict with release info
    update_available = pyqtSignal(dict)
    # Emitted when application is already on latest version: payload is dict with latest release info
    no_update = pyqtSignal(dict)
    # Emitted when an error occurs during fetching or parsing
    error_occurred = pyqtSignal(str)

    def __init__(self, current_version: str = __version__, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        req = urllib.request.Request(
            LATEST_API_URL,
            headers={
                "User-Agent": f"AudioVisualizer-Client/{self.current_version}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as response:
                if response.status == 200:
                    raw_data = response.read().decode("utf-8")
                    data = json.loads(raw_data)

                    tag_name = data.get("tag_name", "")
                    release_info = {
                        "tag_name": tag_name,
                        "name": data.get("name", tag_name),
                        "html_url": data.get("html_url", RELEASES_URL),
                        "body": data.get("body", ""),
                        "published_at": data.get("published_at", ""),
                        "current_version": self.current_version,
                    }

                    if is_newer_version(tag_name, self.current_version):
                        self.update_available.emit(release_info)
                    else:
                        self.no_update.emit(release_info)
                else:
                    self.error_occurred.emit(f"HTTP Server returned status {response.status}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # No releases published yet
                self.no_update.emit({"tag_name": self.current_version, "current_version": self.current_version})
            else:
                self.error_occurred.emit(f"HTTP Error: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            self.error_occurred.emit(f"Connection failed: {e.reason}")
        except Exception as e:
            self.error_occurred.emit(str(e))
