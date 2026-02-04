"""
pdoc generator for osysHome.

This module lives inside the Docs plugin so the generation logic can be updated
independently from the core application.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional, Tuple, List, Dict


def _discover_plugin_names(project_root: str) -> List[str]:
    plugins_dir = os.path.join(project_root, "plugins")
    if not os.path.isdir(plugins_dir):
        return []
    names: List[str] = []
    for name in os.listdir(plugins_dir):
        if name.startswith(".") or name.startswith("__"):
            continue
        if name in {"venv", "env"}:
            continue
        plugin_path = os.path.join(plugins_dir, name)
        if not os.path.isdir(plugin_path):
            continue
        if not os.path.isfile(os.path.join(plugin_path, "__init__.py")):
            continue
        names.append(name)
    names.sort(key=lambda s: s.lower())
    return names


def _get_active_plugins_from_runtime() -> Optional[List[str]]:
    """
    Get active plugins from runtime registry (PluginsHelper.plugins).

    Returns:
        list(plugin_names) or None if not available.
    """
    try:
        from app.core.main.PluginsHelper import plugins as runtime_plugins  # type: ignore

        names = list(runtime_plugins.keys())
        names.sort(key=lambda s: s.lower())
        return names
    except Exception:
        return None


def generate_docs_dev(
    *,
    project_root: str,
    output_dir: Optional[str] = None,
    echo: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Generate developer documentation (HTML) into docs_dev/ using pdoc.

    Returns:
        (success, message)
    """
    if echo is None:
        echo = lambda s: None  # noqa: E731

    project_root = os.path.abspath(project_root)
    docs_dev_dir = os.path.abspath(output_dir or os.path.join(project_root, "docs_dev"))

    if not os.path.exists(docs_dev_dir):
        os.makedirs(docs_dev_dir, exist_ok=True)
        echo(f"Created docs_dev directory: {docs_dev_dir}")

    # Build modules list: always document core `app` and only ACTIVE plugins.
    # Prefer runtime registry (only active plugins are loaded there).
    all_plugins = _discover_plugin_names(project_root)
    active_from_runtime = _get_active_plugins_from_runtime()
    if active_from_runtime is None:
        active_plugins = all_plugins
        echo("Active plugins: runtime registry not available, documenting all plugins.")
    else:
        active_plugins = [p for p in all_plugins if p in set(active_from_runtime)]
        echo(f"Active plugins (runtime): {len(active_plugins)}/{len(all_plugins)}")

    modules: List[str] = ["app"] + [f"plugins.{p}" for p in active_plugins]

    cmd: List[str] = [
        sys.executable,  # Используем текущий интерпретатор Python
        "-m",
        "pdoc",
        "--docformat",
        "google",
        "--no-show-source",
        "--output-dir",
        docs_dev_dir,
        *modules,
    ]

    # Make sure pdoc can import app/ and plugins/ without installation.
    env: Dict[str, str] = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = project_root + (os.pathsep + existing_pp if existing_pp else "")

    echo("Generating documentation with pdoc...")
    echo(f"Command: {' '.join(cmd)}")
    echo(f"CWD: {project_root}")
    echo(f"PYTHONPATH: {env.get('PYTHONPATH', '')}")
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return False, "pdoc not found. Please install it: pip install pdoc"
    except Exception as e:
        return False, f"Error: {e}"

    if result.returncode == 0:
        msg = "Documentation generated successfully in docs_dev/."
        if result.stdout:
            msg += "\n" + result.stdout.strip()
        return True, msg

    msg = "Error generating documentation with pdoc."
    msg += f"\nReturn code: {result.returncode}"
    if result.stdout:
        msg += "\n--- STDOUT ---\n" + result.stdout.strip()
    if result.stderr:
        msg += "\n--- STDERR ---\n" + result.stderr.strip()
    return False, msg

