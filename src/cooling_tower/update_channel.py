"""Single official release/update channel; no legacy-channel migration."""

RELEASE_REPOSITORY = "RodeProjects/sacrificial-tower"
LATEST_RELEASE_URL = f"https://github.com/{RELEASE_REPOSITORY}/releases/latest"
DEFAULT_UPDATE_MANIFEST_URL = f"{LATEST_RELEASE_URL}/download/latest.json"
INSTALLER_PATH_PREFIX = f"/{RELEASE_REPOSITORY}/releases/download/"


def installer_url(version: str) -> str:
    return (
        f"https://github.com{INSTALLER_PATH_PREFIX}v{version}/"
        f"SacrificialTowerSetup-{version}.exe"
    )
