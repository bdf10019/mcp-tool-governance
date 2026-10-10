from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


ENVIRONMENTS = {
    "local_product",
    "development",
    "automated_test",
    "restore_isolation",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    root: Path
    environment_kind: str
    db_path: Path
    mcp_timeout_seconds: float = 6.0
    session_seconds: int = 8 * 60 * 60
    auth_context_seconds: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        root = project_root()
        kind = os.environ.get("MCP_APP_ENV_KIND", "local_product")
        explicit = os.environ.get("MCP_APP_DB_PATH")
        db_path = Path(explicit) if explicit else root / "state" / kind / "app.db"
        return cls(root=root, environment_kind=kind, db_path=db_path).validated()

    @classmethod
    def automated_test(cls, db_path: Path) -> "Settings":
        return cls(
            root=project_root(),
            environment_kind="automated_test",
            db_path=db_path,
            mcp_timeout_seconds=4.0,
            session_seconds=900,
        ).validated()

    def validated(self) -> "Settings":
        root = self.root.resolve()
        db_path = self.db_path.resolve()
        if self.environment_kind not in ENVIRONMENTS:
            raise RuntimeError(f"Unsupported environment_kind: {self.environment_kind}")
        allowed = [root / "state" / self.environment_kind]
        if self.environment_kind == "automated_test":
            allowed.extend([root / "tmp" / "test", Path(tempfile.gettempdir())])
        if not any(_is_within(db_path, candidate.resolve()) for candidate in allowed):
            raise RuntimeError("Database path escapes the selected environment boundary")
        if db_path.exists() and db_path.is_symlink():
            raise RuntimeError("Database path must not be a symbolic link")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def environment_id(self) -> str:
        digest = hashlib.sha256(str(self.db_path.parent.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"{self.environment_kind}-{digest}"

