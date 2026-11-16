"""Create this project's own .venv and install/check dependencies. MIT adaptation.

Never borrow the sibling repository's environment. Preserve an existing unusable
environment for manual inspection instead of deleting or silently replacing it.
"""

from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def setup(root=ROOT):
    if sys.version_info < (3, 11):
        raise RuntimeError("Install Python 3.11 or later.")
    root = root.resolve()
    folder = root / ".venv"
    if folder.is_symlink() or folder.resolve().parent != root:
        raise RuntimeError("Use a real .venv directory inside this project.")
    python = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not folder.exists():
        venv.EnvBuilder(with_pip=True).create(folder)
    if not python.is_file():
        raise RuntimeError("Existing .venv is unusable. Preserve/rename it manually, then rerun setup.")
    probe = subprocess.run([str(python), "-I", "-c", "import sys; raise SystemExit(sys.version_info < (3,11))"],
                           capture_output=True, timeout=30)
    if probe.returncode:
        raise RuntimeError("Existing .venv interpreter is unusable; preserve it and recreate locally.")
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements-lock.txt")], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    print("Environment ready. Run the README's offline preview next.")


if __name__ == "__main__":
    try:
        setup()
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print("Setup failed. Check Python, the local .venv, package download access and file permissions.", file=sys.stderr)
        sys.exit(1)
