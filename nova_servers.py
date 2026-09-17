#!/usr/bin/env python3
"""
Nova Servers — Minecraft Server Manager
Supports: Vanilla, Paper, Fabric, NeoForge, Forge, Bukkit/CraftBukkit
Auto-install: Vanilla, Paper, Fabric, NeoForge
Tunnel: Playit.gg (auto-download + auto-start)
Cross-platform: Windows, Linux, macOS
"""

# ── Bootstrap: auto-install missing packages before anything else ─────────────────
import sys
import subprocess
import importlib
import os
import platform as _platform_mod

_SYSTEM = _platform_mod.system()  # "Windows", "Linux", "Darwin"

# Packages we optionally use: (import_name, pip_package_name)
_OPTIONAL_PACKAGES = [
    ("PIL", "Pillow"),
    # miniupnpc is NOT auto-installed — enable UPnP in Settings to install it
]

def _find_python():
    """Return the python executable that is running this script."""
    return sys.executable  # always correct, works on all platforms

def _pip_install(package_name):
    """Install a package using the current interpreter's pip."""
    python = _find_python()
    print(f"[Bootstrap] Installing {package_name}…")
    result = subprocess.run(
        [python, "-m", "pip", "install", "--quiet",
         "--break-system-packages", package_name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[Bootstrap] Warning: could not install {package_name}: {result.stderr.strip()}")
        return False
    print(f"[Bootstrap] {package_name} installed ✓")
    return True

def _ensure_packages():
    """Check optional packages and install any that are missing."""
    for import_name, pip_name in _OPTIONAL_PACKAGES:
        try:
            importlib.import_module(import_name)
        except ImportError:
            _pip_install(pip_name)

_ensure_packages()

# ── Standard library imports ─────────────────────────────────────────────────────
import threading
import json
import shutil
import urllib.request
import urllib.error
import time
import re
import zipfile
import tempfile
import socket
import hashlib
import struct
import io
import queue
from pathlib import Path
from datetime import datetime

# ── Tkinter — give a clear error if missing (Linux sometimes needs python3-tk) ───
try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, filedialog, messagebox
except ImportError:
    print("ERROR: tkinter is not installed.")
    if _SYSTEM == "Linux":
        print("Install it with:  sudo apt install python3-tk   (Debian/Ubuntu)")
        print("                  sudo dnf install python3-tkinter  (Fedora)")
    elif _SYSTEM == "Darwin":
        print("Install it with:  brew install python-tk")
    else:
        print("Reinstall Python from python.org and tick 'tcl/tk' during setup.")
    sys.exit(1)

# ── Pillow (optional — only needed for server icon resizing) ────────────────────
try:
    from PIL import Image
except ImportError:
    Image = None


def fix_icon(s_dir):
    p = Path(s_dir) / "server-icon.png"
    if p.exists() and Image is not None:
        try:
            with Image.open(p) as img:
                if img.size != (64, 64):
                    img.resize((64, 64)).save(p)
        except Exception:
            pass

# ── Constants ────────────────────────────────────────────────────────────────────

APP_NAME    = "Nova Servers"
CONFIG_FILE = "nova_servers_config.json"
SERVERS_DIR = Path("servers")
JAVA_MIN    = 17

SYSTEM = _SYSTEM  # "Windows", "Linux", "Darwin"  (set during bootstrap)

# Playit binaries per platform
PLAYIT_DOWNLOAD = {
    "Windows": {
        "url":      "https://github.com/playit-cloud/playit-agent/releases/download/v0.15.26/playit-windows-x86_64.exe",
        "filename": "playit.exe",
    },
    "Linux": {
        "url":      "https://github.com/playit-cloud/playit-agent/releases/download/v0.15.26/playit-linux-amd64",
        "filename": "playit",
    },
    "Darwin": {
        # macOS: arm64 for Apple Silicon, amd64 for Intel
        "url":      "https://github.com/playit-cloud/playit-agent/releases/download/v0.15.26/playit-macos-aarch64"
                    if _platform_mod.machine() in ("arm64", "aarch64")
                    else "https://github.com/playit-cloud/playit-agent/releases/download/v0.15.26/playit-macos-amd64",
        "filename": "playit",
    },
}

# cloudflared binaries — uses GitHub's /latest redirect so always up to date
CLOUDFLARED_BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download"
CLOUDFLARED_DOWNLOAD = {
    # (url_filename, local_filename, needs_chmod)
    ("Windows", "AMD64"):  (f"{CLOUDFLARED_BASE}/cloudflared-windows-amd64.exe", "cloudflared.exe", False),
    ("Windows", "x86"):    (f"{CLOUDFLARED_BASE}/cloudflared-windows-386.exe",   "cloudflared.exe", False),
    ("Linux",   "x86_64"): (f"{CLOUDFLARED_BASE}/cloudflared-linux-amd64",       "cloudflared",     True),
    ("Linux",   "aarch64"):(f"{CLOUDFLARED_BASE}/cloudflared-linux-arm64",        "cloudflared",     True),
    ("Linux",   "armv7l"): (f"{CLOUDFLARED_BASE}/cloudflared-linux-armhf",        "cloudflared",     True),
    ("Darwin",  "x86_64"): (f"{CLOUDFLARED_BASE}/cloudflared-darwin-amd64.tgz",  "cloudflared.tgz", True),
    ("Darwin",  "arm64"):  (f"{CLOUDFLARED_BASE}/cloudflared-darwin-arm64.tgz",   "cloudflared.tgz", True),
}

PAPER_API             = "https://fill.papermc.io/v3/projects/paper"
PAPER_USER_AGENT      = "NovaServers/2.0 (https://github.com/nova-servers)"
FABRIC_INSTALLER_META = "https://meta.fabricmc.net/v2/versions/installer"
NEOFORGE_MAVEN_META   = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
VANILLA_MANIFEST      = "https://launchermeta.mojang.com/mc/game/version_manifest.json"

LOADER_INFO = {
    "Vanilla": {
        "color": "#5BA85A",
        "description": "Official Mojang server — no mods, pure Minecraft. Auto-installs from Mojang.",
        "auto_install": True,
        "jar_name": "vanilla-server.jar",
    },
    "Paper": {
        "color": "#4C92D4",
        "description": "High-performance Bukkit fork with many optimisations. Best for survival/vanilla-style servers. Auto-installs.",
        "auto_install": True,
        "jar_name": "paper.jar",
    },
    "Fabric": {
        "color": "#C2B49E",
        "description": "Lightweight modding toolchain. Great for client+server mods. Auto-installs via the Fabric installer.",
        "auto_install": True,
        "jar_name": "fabric-server-launch.jar",
    },
    "NeoForge": {
        "color": "#E8734A",
        "description": "Modern community Forge fork with faster updates. Auto-installs the server installer.",
        "auto_install": True,
        "jar_name": "neoforge-server.jar",
    },
    "Forge": {
        "color": "#D4832A",
        "description": "Classic modding platform — largest mod ecosystem. Browse files.minecraftforge.net and provide the installer JAR.",
        "auto_install": False,
        "jar_name": "forge-server.jar",
        "note": "Download the installer from files.minecraftforge.net, run it to produce a server folder, then point here to that server's run.jar or forge-*.jar.",
    },
    "Bukkit": {
        "color": "#F4A636",
        "description": "Original server plugin API. BuildTools required — use the Auto Setup button or run BuildTools yourself.",
        "auto_install": "buildtools",
        "jar_name": "craftbukkit.jar",
        "note": "Auto Setup downloads BuildTools.jar and runs it. Requires Java 21+ and Git.",
    },
}

COLORS = {
    "bg":      "#111318",
    "panel":   "#181C24",
    "card":    "#1E2330",
    "accent":  "#7C6AF7",
    "accent2": "#3B82F6",
    "success": "#34D399",
    "danger":  "#F87171",
    "warning": "#FBBF24",
    "text":    "#E8EAF0",
    "subtext": "#6B7280",
    "border":  "#2A2F3E",
    "pill_bg": "#252B3B",
}

# ── Platform helpers ──────────────────────────────────────────────────────────────

def default_java_path():
    """Return a sane default Java executable for the current OS."""
    if SYSTEM == "Windows":
        # Try JAVA_HOME first, then fall back to PATH
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            candidate = Path(java_home) / "bin" / "java.exe"
            if candidate.exists():
                return str(candidate)
        return "java"   # rely on PATH on Windows
    else:
        # Linux / macOS — honour SDKMAN if present
        sdkman = Path.home() / ".sdkman" / "candidates" / "java" / "current" / "bin" / "java"
        if sdkman.exists():
            return str(sdkman)
        return "java"


# ── Config helpers ────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "servers": {},
        "java_path": default_java_path(),
        "playit_path": "",
        "playit_auto_start": False,
        "cloudflared_path": "",
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Download helpers ──────────────────────────────────────────────────────────────

def fetch_json(url, user_agent="NovaServers/1.0"):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NovaServers/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()

def download_file(url, dest_path, progress_cb=None):
    req = urllib.request.Request(url, headers={"User-Agent": "NovaServers/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length", 0))
        done  = 0
        chunk = 65536
        with open(dest_path, "wb") as f:
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if progress_cb:
                    progress_cb(done, total)


# ── Auto-install implementations ──────────────────────────────────────────────────

def get_paper_versions():
    """Return list of MC versions available on Paper, newest first."""
    data = fetch_json(PAPER_API, PAPER_USER_AGENT)
    # v3 shape: {"versions": {"1.21": ["1.21.1", "1.21"], ...}}
    groups = data.get("versions", {})
    all_versions = []
    for group_versions in groups.values():
        all_versions.extend(group_versions)
    # Sort semantically newest-first
    def ver_key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0,)
    return sorted(all_versions, key=ver_key, reverse=True)

def get_paper_build(mc_version):
    """
    Uses the PaperMC Fill v3 API (fill.papermc.io/v3).
    The v2 api.papermc.io endpoint stopped receiving builds on Dec 31 2025.
    
    v3 builds endpoint returns a list of build objects; each has:
      .channel ("STABLE"|"EXPERIMENTAL")
      .downloads."server:default".url  — direct download link
    """
    builds_url = f"{PAPER_API}/versions/{mc_version}/builds"
    try:
        builds = fetch_json(builds_url, PAPER_USER_AGENT)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            suggestion = _find_latest_paper_version()
            hint = f"\n\nLatest supported version: {suggestion}" if suggestion else \
                   "\n\nCheck https://fill.papermc.io for supported versions."
            raise RuntimeError(
                f"Paper has no builds for Minecraft {mc_version} "
                f"(HTTP {e.code} — version may be unsupported or builds removed).{hint}"
            )
        raise RuntimeError(f"Paper API error fetching builds: {e}")

    # v3 returns a list directly (newest build first)
    if not isinstance(builds, list) or not builds:
        raise RuntimeError(
            f"No Paper builds found for Minecraft {mc_version}.\n"
            "Check https://fill.papermc.io for supported versions."
        )

    # Prefer the newest STABLE build
    stable = [b for b in builds if b.get("channel", "").upper() == "STABLE"]
    build  = stable[0] if stable else builds[0]

    dl = build.get("downloads", {}).get("server:default", {})
    url = dl.get("url")
    name = dl.get("name", f"paper-{mc_version}.jar")

    if not url:
        raise RuntimeError(
            f"Paper build object for {mc_version} has no download URL.\n"
            f"Build data: {build}"
        )
    return url, name


def _find_latest_paper_version():
    """Walk Paper versions newest-first and return the first one with a stable build."""
    try:
        versions = get_paper_versions()
        for v in versions:
            try:
                builds = fetch_json(f"{PAPER_API}/versions/{v}/builds", PAPER_USER_AGENT)
                if isinstance(builds, list) and any(
                    b.get("channel", "").upper() == "STABLE" for b in builds
                ):
                    return v
            except Exception:
                continue
    except Exception:
        pass
    return ""

def install_paper(mc_version, server_dir, progress_cb=None, log_cb=None):
    _log(log_cb, f"Fetching latest Paper build for {mc_version}…")
    url, jar_name = get_paper_build(mc_version)
    dest = Path(server_dir) / "paper.jar"
    _log(log_cb, f"Downloading {jar_name}…")
    download_file(url, dest, progress_cb)
    _log(log_cb, "Paper downloaded ✓")
    return str(dest)

def get_vanilla_url(mc_version, log_cb=None):
    _log(log_cb, "Fetching Mojang version manifest…")
    manifest = fetch_json(VANILLA_MANIFEST)
    versions = manifest.get("versions", [])
    entry = next((v for v in versions if v["id"] == mc_version), None)
    if entry is None:
        release = manifest.get("latest", {}).get("release", "")
        raise RuntimeError(
            f"Minecraft version '{mc_version}' not found.\n"
            f"Latest release is '{release}'."
        )
    version_meta = fetch_json(entry["url"])
    server_url = version_meta.get("downloads", {}).get("server", {}).get("url")
    if not server_url:
        raise RuntimeError(f"No server download available for {mc_version}")
    return server_url

def install_vanilla(mc_version, server_dir, progress_cb=None, log_cb=None):
    url  = get_vanilla_url(mc_version, log_cb)
    dest = Path(server_dir) / "vanilla-server.jar"
    _log(log_cb, f"Downloading vanilla server {mc_version}…")
    download_file(url, dest, progress_cb)
    _log(log_cb, "Vanilla server downloaded ✓")
    return str(dest)

def get_fabric_installer_url(log_cb=None):
    _log(log_cb, "Fetching Fabric installer versions…")
    versions = fetch_json(FABRIC_INSTALLER_META)
    stable   = [v for v in versions if not v.get("unstable", False)]
    if not stable:
        stable = versions
    latest = stable[0]
    ver    = latest["version"]
    url    = (f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/"
              f"{ver}/fabric-installer-{ver}.jar")
    return url, ver

def install_fabric(mc_version, server_dir, java_path="java",
                   progress_cb=None, log_cb=None):
    installer_url, inst_ver = get_fabric_installer_url(log_cb)
    installer_path = Path(server_dir) / f"fabric-installer-{inst_ver}.jar"
    _log(log_cb, f"Downloading Fabric installer {inst_ver}…")
    download_file(installer_url, installer_path, progress_cb)

    _log(log_cb, "Running Fabric installer (server mode)…")
    # On Windows, resolve java_path in case it's just "java"
    java_exe = _resolve_java(java_path)
    # Resolve to absolute path — spaces in server_dir would break if path is relative
    installer_abs = str(Path(installer_path).resolve())
    server_dir_abs = str(Path(server_dir).resolve())
    result = subprocess.run(
        [java_exe, "-jar", installer_abs,
         "server", "-mcversion", mc_version, "-downloadMinecraft"],
        cwd=server_dir_abs,
        capture_output=True, text=True
    )
    if result.stdout:
        _log(log_cb, result.stdout)
    if result.returncode != 0:
        _log(log_cb, result.stderr)
        raise RuntimeError(
            f"Fabric installer failed (exit {result.returncode}).\n"
            f"Make sure Java {JAVA_MIN}+ is installed and set in Settings.\n"
            f"{result.stderr[-800:]}"
        )

    # Fabric creates fabric-server-launch.jar in the server dir
    launch_jar = Path(server_dir) / "fabric-server-launch.jar"
    if not launch_jar.exists():
        raise RuntimeError(
            "Fabric installer ran successfully but fabric-server-launch.jar was not found.\n"
            "The MC version may not have a Fabric loader release yet."
        )
    _log(log_cb, "Fabric installed ✓")
    return str(launch_jar)

def get_neoforge_latest(mc_version, log_cb=None):
    _log(log_cb, "Fetching NeoForge version list…")
    xml = fetch_text(NEOFORGE_MAVEN_META)

    # NeoForge versions use the MC minor+patch, e.g. MC 1.21.1 → prefix "21.1"
    parts = mc_version.split(".")
    if len(parts) >= 3:
        # e.g. "1.21.1" → "21.1"
        prefix = ".".join(parts[1:])
    elif len(parts) == 2:
        # e.g. "1.21" → "21"
        prefix = parts[1]
    else:
        prefix = mc_version.lstrip("1.")

    versions = re.findall(r"<version>([^<]+)</version>", xml)
    matching = [v for v in versions if v.startswith(prefix)]
    if not matching:
        raise RuntimeError(
            f"No NeoForge versions found for Minecraft {mc_version}.\n"
            f"NeoForge only supports MC 1.20.1+. Use Forge for older versions.\n"
            f"Available prefixes in NeoForge: check https://maven.neoforged.net"
        )
    latest = matching[-1]
    url = (
        f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{latest}/"
        f"neoforge-{latest}-installer.jar"
    )
    return latest, url

def install_neoforge(mc_version, server_dir, java_path="java",
                     progress_cb=None, log_cb=None):
    nf_ver, installer_url = get_neoforge_latest(mc_version, log_cb)
    installer_path = Path(server_dir) / f"neoforge-{nf_ver}-installer.jar"
    _log(log_cb, f"Downloading NeoForge {nf_ver} installer…")
    download_file(installer_url, installer_path, progress_cb)

    _log(log_cb, "Running NeoForge installer (--installServer)…")
    java_exe = _resolve_java(java_path)
    installer_abs  = str(Path(installer_path).resolve())
    server_dir_abs = str(Path(server_dir).resolve())
    result = subprocess.run(
        [java_exe, "-jar", installer_abs, "--installServer"],
        cwd=server_dir_abs,
        capture_output=True, text=True
    )
    out = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
    _log(log_cb, out)
    if result.returncode != 0:
        err = result.stderr[-2000:]
        _log(log_cb, err)
        raise RuntimeError(
            f"NeoForge installer failed (exit {result.returncode}).\n"
            f"Make sure Java {JAVA_MIN}+ is installed and set in Settings.\n"
            f"{err[-600:]}"
        )

    jar = _find_neoforge_jar(server_dir)
    _log(log_cb, "NeoForge installed ✓")
    return str(jar)

def _find_neoforge_jar(server_dir):
    """
    NeoForge ≥ 1.20.4 produces run.sh / run.bat + a libraries tree.
    Older builds drop a neoforge-*-server.jar directly.
    We try several patterns in preference order.
    """
    p = Path(server_dir)

    # Prefer the launcher scripts (they set the correct classpath)
    if SYSTEM == "Windows":
        script = p / "run.bat"
    else:
        script = p / "run.sh"
    if script.exists():
        if SYSTEM != "Windows":
            os.chmod(script, 0o755)
        return script

    # Try the other script as a fallback
    for s in ["run.sh", "run.bat"]:
        candidate = p / s
        if candidate.exists():
            return candidate

    # Standalone fat-jar (older versions)
    for pattern in ["neoforge-*-server.jar", "neoforge-*.jar"]:
        matches = sorted(p.glob(pattern))
        if matches:
            return matches[-1]

    # Any jar that isn't the installer
    jars = [j for j in p.glob("*.jar") if "installer" not in j.name.lower()]
    if jars:
        return jars[0]

    raise RuntimeError(
        "NeoForge installer ran but could not locate a server jar or run script.\n"
        "Check the server directory manually."
    )

def install_bukkit_buildtools(mc_version, server_dir, java_path="java",
                               progress_cb=None, log_cb=None):
    bt_url  = "https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar"
    bt_path = Path(server_dir) / "BuildTools.jar"
    _log(log_cb, "Downloading BuildTools.jar…")
    download_file(bt_url, bt_path, progress_cb)
    _log(log_cb, f"Running BuildTools for {mc_version}… (this can take 10–30 minutes)")
    java_exe = _resolve_java(java_path)
    bt_abs         = str(Path(bt_path).resolve())
    server_dir_abs = str(Path(server_dir).resolve())
    result = subprocess.run(
        [java_exe, "-jar", bt_abs,
         "--rev", mc_version, "--compile", "craftbukkit"],
        cwd=server_dir_abs,
        capture_output=True, text=True
    )
    out = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
    _log(log_cb, out)
    if result.returncode != 0:
        _log(log_cb, result.stderr[-2000:])
        raise RuntimeError(f"BuildTools failed (exit {result.returncode})\nSee log for details.")
    matches = list(Path(server_dir).glob(f"craftbukkit-{mc_version}*.jar"))
    if not matches:
        matches = list(Path(server_dir).glob("craftbukkit*.jar"))
    if not matches:
        raise RuntimeError("BuildTools ran but craftbukkit jar not found.")
    dest = Path(server_dir) / "craftbukkit.jar"
    shutil.copy2(matches[0], dest)
    _log(log_cb, "Bukkit/CraftBukkit built ✓")
    return str(dest)


def download_playit(dest_dir, progress_cb=None, log_cb=None):
    """Download the correct Playit binary for the current OS."""
    info     = PLAYIT_DOWNLOAD.get(SYSTEM, PLAYIT_DOWNLOAD["Linux"])
    url      = info["url"]
    filename = info["filename"]
    # Always resolve to an absolute path so subprocess can find it
    dest     = Path(dest_dir).resolve() / filename

    _log(log_cb, f"Downloading Playit agent for {SYSTEM} from:\n  {url}")
    download_file(url, dest, progress_cb)

    # Make executable on Unix
    if SYSTEM != "Windows":
        os.chmod(dest, 0o755)

    abs_path = str(dest.resolve())
    _log(log_cb, f"Playit downloaded → {abs_path} ✓")
    return abs_path


def _resolve_java(java_path):
    """
    Return the java executable to use.
    On Windows, if the user just typed 'java' and it resolves via PATH that's fine.
    If it's a full path, normalise with quotes isn't needed — subprocess handles it.
    """
    if java_path and java_path != "java":
        p = Path(java_path)
        if p.exists():
            return str(p)
    # Fall back to whatever is on PATH
    return java_path or "java"


def _log(cb, msg):
    if cb and msg:
        cb(str(msg) + "\n")


# ── UPnP / No-port-forwarding helpers ────────────────────────────────────────────

def upnp_open_port(port: int, proto: str = "TCP",
                   desc: str = "NovaServers", log_cb=None) -> tuple[bool, str]:
    """
    Try to open a port via UPnP (works on ~70% of home routers automatically).
    Returns (success, external_ip_or_error_message).
    """
    try:
        import miniupnpc
        upnp = miniupnpc.UPnP()
        upnp.discoverdelay = 200
        n = upnp.discover()
        if n == 0:
            return False, "No UPnP-capable router found on the network."
        upnp.selectigd()
        ext_ip = upnp.externalipaddress()
        # Remove any existing mapping first (ignore errors)
        try:
            upnp.deleteportmapping(port, proto)
        except Exception:
            pass
        result = upnp.addportmapping(
            port, proto, upnp.lanaddr, port, desc, ""
        )
        if result:
            _log(log_cb, f"UPnP: opened {proto} port {port} → {ext_ip}:{port} ✓")
            return True, ext_ip
        else:
            return False, f"UPnP: router refused to open port {port}."
    except ImportError:
        return False, "miniupnpc not installed (run: pip install miniupnpc)."
    except Exception as e:
        return False, f"UPnP error: {e}"


def upnp_close_port(port: int, proto: str = "TCP", log_cb=None):
    """Remove a UPnP port mapping."""
    try:
        import miniupnpc
        upnp = miniupnpc.UPnP()
        upnp.discoverdelay = 200
        upnp.discover()
        upnp.selectigd()
        upnp.deleteportmapping(port, proto)
        _log(log_cb, f"UPnP: closed {proto} port {port}")
    except Exception:
        pass


def get_local_ip() -> str:
    """Return the LAN IP of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Set by NovaServers on init/save. Controls whether UPnP is attempted.
_UPNP_ENABLED: bool = False

def try_upnp_then_fallback(port: int, desc: str = "NovaServers Admin",
                            log_cb=None) -> tuple[str, str]:
    """
    Try UPnP to get a public address for `port`.
    Returns (method, address_or_error):
      method = "upnp"  → UPnP succeeded; address is "public_ip:port"
      method = "local" → UPnP disabled/failed; address is LAN IP
    UPnP is only attempted when enabled in Settings.
    """
    if _UPNP_ENABLED:
        ok, result = upnp_open_port(port, "TCP", desc, log_cb)
        if ok:
            return "upnp", f"{result}:{port}"
        _log(log_cb, f"UPnP not available ({result}). Falling back to LAN IP.")
    lan = get_local_ip()
    return "local", f"{lan}:{port}"


# ── Cloudflare Tunnel (TryCloudflare) helpers ────────────────────────────────────

def _get_cloudflared_download_info() -> tuple[str, str, bool]:
    """Return (url, local_filename, needs_chmod) for the current platform/arch."""
    machine = _platform_mod.machine().lower()
    # Normalise arch names
    if machine in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine.startswith("armv7") or machine == "armhf":
        arch = "armv7l"
    elif machine in ("i386", "i686", "x86"):
        arch = "x86"
    else:
        arch = "x86_64"  # best guess fallback

    key = (SYSTEM, arch)
    if key not in CLOUDFLARED_DOWNLOAD:
        # Fallback: try x86_64 for same OS
        key = (SYSTEM, "x86_64")
    return CLOUDFLARED_DOWNLOAD.get(key,
        (f"{CLOUDFLARED_BASE}/cloudflared-linux-amd64", "cloudflared", True))


def download_cloudflared(dest_dir: str, progress_cb=None, log_cb=None) -> str:
    """Download cloudflared binary and return the path to the executable."""
    import tarfile
    url, filename, needs_chmod = _get_cloudflared_download_info()
    dest_dir = Path(dest_dir).resolve()
    raw_dest = dest_dir / filename
    _log(log_cb, f"Downloading cloudflared for {SYSTEM}/{_platform_mod.machine()}…\n  {url}")
    download_file(url, raw_dest, progress_cb)

    # macOS ships as a .tgz — extract the binary
    if filename.endswith(".tgz"):
        _log(log_cb, "Extracting cloudflared from archive…")
        import tarfile
        with tarfile.open(raw_dest, "r:gz") as tf:
            # The binary inside is just called "cloudflared"
            tf.extract("cloudflared", path=str(dest_dir))
        raw_dest.unlink()  # remove .tgz
        exe_dest = dest_dir / "cloudflared"
    else:
        exe_dest = raw_dest

    if needs_chmod:
        os.chmod(exe_dest, 0o755)

    abs_path = str(exe_dest.resolve())
    _log(log_cb, f"cloudflared downloaded → {abs_path} ✓")
    return abs_path


class CloudflaredTunnel:
    """
    Wraps a cloudflared quick-tunnel subprocess.
    Parses stdout/stderr for the trycloudflare.com URL and
    exposes it via self.tunnel_url once the tunnel is ready.
    Usage:
        tunnel = CloudflaredTunnel(cloudflared_path, local_port, log_cb)
        tunnel.start()
        # tunnel.tunnel_url is set once ready
        tunnel.stop()
    """
    URL_RE = re.compile(r"https://[\w-]+\.trycloudflare\.com")

    def __init__(self, binary_path: str, local_port: int,
                 log_cb=None, url_cb=None):
        self.binary_path = binary_path
        self.local_port  = local_port
        self.log_cb      = log_cb
        self.url_cb      = url_cb   # called with the URL string when ready
        self.tunnel_url: str | None = None
        self.process = None
        self._running = False

    def start(self) -> bool:
        if not os.path.exists(self.binary_path):
            _log(self.log_cb, f"[Cloudflared] Binary not found: {self.binary_path}\n")
            return False
        try:
            if SYSTEM != "Windows":
                os.chmod(self.binary_path, 0o755)

            creation_flags = 0
            if SYSTEM == "Windows":
                creation_flags = subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                [self.binary_path, "tunnel", "--url",
                 f"http://localhost:{self.local_port}",
                 "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=creation_flags,
            )
            self._running = True
            threading.Thread(target=self._read_stream,
                             args=(self.process.stdout,), daemon=True).start()
            threading.Thread(target=self._read_stream,
                             args=(self.process.stderr,), daemon=True).start()
            return True
        except Exception as e:
            _log(self.log_cb, f"[Cloudflared ERROR] {e}\n")
            return False

    def _read_stream(self, stream):
        try:
            for line in stream:
                stripped = line.rstrip("\n")
                if stripped:
                    _log(self.log_cb, f"[Cloudflared] {stripped}\n")
                    # Extract tunnel URL from output
                    m = self.URL_RE.search(stripped)
                    if m and self.tunnel_url is None:
                        self.tunnel_url = m.group(0)
                        _log(self.log_cb, f"\n✓ Tunnel ready: {self.tunnel_url}\n")
                        if self.url_cb:
                            self.url_cb(self.tunnel_url)
        except Exception:
            pass
        if self.process and self.process.poll() is not None:
            self._running = False

    def stop(self):
        self._running = False
        self.tunnel_url = None
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None

    @property
    def running(self):
        return self._running


def safe_name(name: str) -> str:
    """
    Convert a user-facing server name into a safe directory name.
    Replaces spaces and any characters that are problematic on Windows or Linux
    with underscores, and strips leading/trailing whitespace.
    """
    import re as _re
    # Replace anything that isn't alphanumeric, dash, dot, or underscore
    safe = _re.sub(r"[^\w\-.]", "_", name.strip())
    # Collapse multiple underscores
    safe = _re.sub(r"_+", "_", safe)
    # Strip leading/trailing underscores/dots (Windows edge cases)
    safe = safe.strip("_.")
    return safe or "server"


# ── ServerProperties Helper ───────────────────────────────────────────────────────

def read_server_property(server_dir, key, default=""):
    props_path = Path(server_dir) / "server.properties"
    if not props_path.exists():
        return default
    try:
        with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1]
    except Exception:
        pass
    return default

def write_server_property(server_dir, key, value):
    props_path = Path(server_dir) / "server.properties"
    lines = []
    found = False
    if props_path.exists():
        try:
            with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            pass
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    try:
        with open(props_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass


# ── ServerProcess ─────────────────────────────────────────────────────────────────

class ServerProcess:
    def __init__(self, name, directory, jar, java, ram_mb, log_callback, stop_callback):
        self.name          = name
        self.directory     = directory
        self.jar           = jar
        self.java          = java
        self.ram_mb        = ram_mb
        self.log_callback  = log_callback
        self.stop_callback = stop_callback
        self.process       = None
        self._running      = False

    def start(self):
        if self._running:
            return False

        jar_path = Path(self.jar)
        suffix   = jar_path.suffix.lower()

        if suffix == ".sh":
            # Linux/macOS shell script (NeoForge run.sh, etc.)
            os.chmod(jar_path, 0o755)
            cmd = [str(jar_path.resolve())]
        elif suffix == ".bat":
            # Windows batch file
            cmd = [str(jar_path.resolve())]
        else:
            # Standard JAR
            java_exe = _resolve_java(self.java)
            cmd = [
                java_exe,
                f"-Xmx{self.ram_mb}M",
                f"-Xms{self.ram_mb // 2}M",
                "-jar", str(jar_path.resolve()),
                "--nogui",
            ]

        # On Windows, batch files need to be run via cmd.exe
        if suffix == ".bat" and SYSTEM == "Windows":
            cmd = ["cmd.exe", "/c"] + cmd

        try:
            creation_flags = 0
            if SYSTEM == "Windows":
                # Prevent a new console window popping up
                creation_flags = subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(
                cmd,
                cwd=self.directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,          # line-buffered stdout (fast log output)
                creationflags=creation_flags,
            )
            # Force stdin to be unbuffered so commands reach MC immediately
            import io as _io
            self.process.stdin = _io.TextIOWrapper(
                self.process.stdin.buffer, line_buffering=True)
        except FileNotFoundError as e:
            self.log_callback(
                f"[ERROR] Could not start server: {e}\n"
                f"Make sure Java is installed and the path in Settings is correct.\n"
            )
            return False
        except Exception as e:
            self.log_callback(f"[ERROR] {e}\n")
            return False

        self._running = True
        threading.Thread(target=self._read_output, daemon=True).start()
        return True

    def _read_output(self):
        try:
            for line in self.process.stdout:
                self.log_callback(line)
        except Exception:
            pass
        self._running = False
        self.stop_callback()

    def send_command(self, cmd):
        if self.process and self._running:
            try:
                self.process.stdin.write(cmd + "\n")
                self.process.stdin.flush()
            except Exception:
                pass

    def stop(self, force=False):
        if not self.process:
            self._running = False
            return
        if force:
            self.process.kill()
            self._running = False
            return
        # Send the Minecraft 'stop' command gracefully
        try:
            self.send_command("stop")
        except Exception:
            pass
        # Wait up to 10 s for it to exit, then force-kill
        def _wait_and_kill():
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
            self._running = False
        threading.Thread(target=_wait_and_kill, daemon=True).start()

    @property
    def running(self):
        return self._running


# ── PlayitProcess ─────────────────────────────────────────────────────────────────

class PlayitProcess:
    # Playit prints lines like:
    #   "server address: auto.playit.gg:30000"
    #   "address: sg1.playit.gg:10987"
    # We capture the first match as the public tunnel address.
    _ADDR_RE = re.compile(
        r'(?:server address|address)\s*:\s*([\w.\-]+:\d+)', re.IGNORECASE)

    def __init__(self, path, log_callback):
        self.path         = path
        self.log_callback = log_callback
        self.process      = None
        self._running     = False
        self.tunnel_url: str | None = None   # set once Playit prints its address

    def start(self):
        if not self.path or not os.path.exists(self.path):
            self.log_callback(
                f"[Playit] Binary not found at: {self.path}\n"
                "Use 'Auto-Download' or browse to the correct path.\n"
            )
            return False
        try:
            if SYSTEM != "Windows":
                os.chmod(self.path, 0o755)

            creation_flags = 0
            if SYSTEM == "Windows":
                creation_flags = subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                [self.path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=creation_flags,
            )
            self._running = True
            threading.Thread(target=self._read_stream,
                             args=(self.process.stdout,), daemon=True).start()
            threading.Thread(target=self._read_stream,
                             args=(self.process.stderr,), daemon=True).start()
            return True
        except Exception as e:
            self.log_callback(f"[Playit ERROR] {e}\n")
            return False

    def _read_stream(self, stream):
        """Read a stream (stdout or stderr) and forward to log_callback."""
        try:
            for line in stream:
                stripped = line.rstrip("\n")
                if stripped:
                    self.log_callback(f"[Playit] {stripped}\n")
                    # Extract tunnel address on first match
                    if self.tunnel_url is None:
                        m = self._ADDR_RE.search(stripped)
                        if m:
                            self.tunnel_url = m.group(1)
        except Exception:
            pass
        if self.process and self.process.poll() is not None:
            self._running = False

    def stop(self):
        if self.process:
            self.process.kill()
            self.process = None
        self._running = False
        self.tunnel_url = None

    @property
    def running(self):
        return self._running


# ── Progress dialog ───────────────────────────────────────────────────────────────

class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, title="Installing…"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.geometry("500x280")
        self.grab_set()

        tk.Label(self, text=title, font=("Helvetica", 13, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(pady=(20, 4))

        self.log = scrolledtext.ScrolledText(
            self, bg=COLORS["panel"], fg=COLORS["text"],
            font=("Courier", 9), height=8, bd=0, state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=8)

        self.bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=16, pady=(0, 6))

        self.status_var = tk.StringVar(value="Starting…")
        tk.Label(self, textvariable=self.status_var, bg=COLORS["bg"],
                 fg=COLORS["subtext"], font=("Helvetica", 9)).pack(pady=(0, 12))

    def append_log(self, text):
        if self.winfo_exists():
            self.log.config(state="normal")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.config(state="disabled")

    def set_progress(self, done, total):
        if not self.winfo_exists():
            return
        if total > 0:
            self.bar.config(mode="determinate")
            self.bar["value"] = done / total * 100
            self.status_var.set(f"{done // 1024:,} / {total // 1024:,} KB")
        else:
            self.bar.config(mode="indeterminate")
            self.bar.start(10)

    def finish(self, msg="Done"):
        if not self.winfo_exists():
            return
        self.bar.stop()
        self.bar.config(mode="determinate")
        self.bar["value"] = 100
        self.status_var.set(msg)

    def close_after(self, ms=1500):
        self.after(ms, lambda: self.destroy() if self.winfo_exists() else None)


# ── Admin Tools — HTTP-based protocol ────────────────────────────────────────────
#
# The host runs a minimal HTTP server (stdlib http.server).
# Cloudflare Tunnel exposes it as https://xyz.trycloudflare.com
# — or accessed directly over LAN/UPnP.
#
# All requests require:  Authorization: Bearer <sha256(password)>
#
# Endpoints:
#   GET  /state   → immediate JSON state snapshot
#   POST /cmd     → JSON body {"cmd": "...", "args": [...]}
#   GET  /poll    → newline-delimited JSON stream (~2s interval)
#
import base64
import http.server
import urllib.parse

ADMIN_PORT_DEFAULT = 25575
ADMIN_PROTOCOL_VER = 2


def _pw_hash(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _auth_header(password: str) -> str:
    return f"Bearer {_pw_hash(password)}"


def _admin_request_headers(auth: str) -> dict:
    """
    Headers sent with every AdminClient request.
    The 'CF-Access-Client-Id' / non-browser User-Agent tells Cloudflare's
    TryCloudflare interstitial to skip the browser challenge so our JSON
    API calls go straight through.
    """
    return {
        'Authorization':      auth,
        'User-Agent':         'NovaServers-Admin/2.0',
        # Prevents Cloudflare's "browser check" page for non-browser clients
        'CF-Access-Client-Id': 'nova-servers-admin',
        'Accept':              'application/json',
    }


class AdminServer:
    """
    HTTP server on the host.  Serves two distinct interfaces on the same port:

    Browser (web UI):
      GET  /              → login page (HTML)
      POST /login         → check web_password, set session cookie, redirect /dashboard
      GET  /dashboard     → full server dashboard HTML (mirrors the desktop View panel)
      GET  /events        → Server-Sent Events stream: state + console log lines
      POST /web-cmd       → form/fetch action for server commands from the browser
      GET  /logout        → clears session

    Python AdminClient (existing API, unchanged):
      GET  /ping          → unauthenticated health check
      GET  /state         → JSON state snapshot  (Authorization: Bearer <sha256pw>)
      GET  /poll          → chunked JSON stream   (Authorization: Bearer <sha256pw>)
      POST /cmd           → JSON command          (Authorization: Bearer <sha256pw>)
    """
    _SESSION_BYTES = 32   # random session token length

    def __init__(self, password: str, port: int = ADMIN_PORT_DEFAULT,
                 web_password: str = "", server_dir: str = ""):
        self.pw_hash        = _pw_hash(password)
        # Web UI uses its own plain-text password (stored hashed); falls back
        # to the same password as the API if not set separately.
        self.web_pw_hash    = _pw_hash(web_password if web_password else password)
        self.port           = port
        self._httpd         = None
        self._running       = False
        # Pre-seed directory so file browser works before first state broadcast
        self._state: dict   = {'directory': server_dir} if server_dir else {}
        self._state_lock    = threading.Lock()
        self._cmd_callback  = None
        # Session store: token → expiry timestamp
        self._sessions: dict[str, float] = {}
        self._session_lock  = threading.Lock()
        # Console log ring buffer (last 300 lines)
        self._console_log: list[str] = []
        self._log_lock      = threading.Lock()
        self._log_max       = 300
        # SSE subscriber queues: one per open /events connection
        self._sse_queues: list[queue.Queue] = []
        self._sse_lock      = threading.Lock()

    # ── public helpers ──────────────────────────────────────────────────────

    def push_log_line(self, line: str):
        """Called by the app whenever the server emits a console line."""
        with self._log_lock:
            self._console_log.append(line)
            if len(self._console_log) > self._log_max:
                self._console_log.pop(0)
        # Forward to all open SSE connections
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait(('log', line))
                except queue.Full:
                    pass

    def update_state(self, state: dict):
        with self._state_lock:
            self._state = state
        # Push state to SSE subscribers too
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait(('state', json.dumps(state)))
                except queue.Full:
                    pass

    # ── session helpers ─────────────────────────────────────────────────────

    def _new_session(self) -> str:
        token = base64.urlsafe_b64encode(os.urandom(self._SESSION_BYTES)).decode()
        with self._session_lock:
            self._sessions[token] = time.time() + 8 * 3600   # 8-hour expiry
        return token

    def _valid_session(self, token: str) -> bool:
        with self._session_lock:
            exp = self._sessions.get(token, 0)
            if time.time() < exp:
                return True
            self._sessions.pop(token, None)
            return False

    def _get_cookie(self, cookie_header: str, name: str) -> str:
        for part in cookie_header.split(';'):
            part = part.strip()
            if '=' in part:
                k, v = part.split('=', 1)
                if k.strip() == name:
                    return v.strip()
        return ''

    # ── HTML helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _html_page(title: str, body: str, extra_head: str = '') -> bytes:
        """Wrap body in the Nova Servers dark-theme shell."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Nova Servers</title>
{extra_head}
<style>
:root{{
  --bg:#111318;--panel:#181C24;--card:#1E2330;
  --accent:#7C6AF7;--accent2:#3B82F6;
  --success:#34D399;--danger:#F87171;--warning:#FBBF24;
  --text:#E8EAF0;--sub:#6B7280;--border:#2A2F3E;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
a{{color:var(--accent);text-decoration:none}}
button,input,select{{font-family:inherit}}
.btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600;transition:.15s}}
.btn-primary{{background:var(--accent);color:#fff}}
.btn-success{{background:var(--success);color:#111}}
.btn-danger{{background:var(--danger);color:#fff}}
.btn-warn{{background:var(--warning);color:#111}}
.btn-ghost{{background:var(--card);color:var(--text);border:1px solid var(--border)}}
.btn:hover{{opacity:.88}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden}}
.card-hdr{{padding:10px 16px;font-weight:700;font-size:14px;border-bottom:1px solid var(--border)}}
.card-body{{padding:14px 16px}}
.stat-row{{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}}
.stat-label{{color:var(--sub)}}
.stat-val{{font-weight:600}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}}
.online{{color:var(--success)}}.offline{{color:var(--danger)}}
header{{background:var(--panel);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;gap:16px}}
header h1{{font-size:18px;color:var(--accent)}}
header .sub{{color:var(--sub);font-size:13px}}
.layout{{display:grid;grid-template-columns:320px 1fr;gap:16px;padding:20px 24px;max-width:1200px}}
@media(max-width:750px){{.layout{{grid-template-columns:1fr}}}}
.left>*+*{{margin-top:12px}}
#console{{background:#0D0D14;color:#A0F0B0;font-family:"Courier New",monospace;font-size:12px;height:380px;overflow-y:auto;padding:10px;white-space:pre-wrap;word-break:break-all}}
#console-wrap{{position:relative}}
.cmd-row{{display:flex;gap:8px;margin-top:8px}}
.cmd-row input{{flex:1;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:13px}}
.tag{{background:var(--accent);color:#fff;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700}}
.playit-box{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px 14px;display:flex;align-items:center;gap:10px}}
.playit-addr{{font-size:16px;font-weight:700;color:var(--success);letter-spacing:.5px}}
.ctrl-row{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}}
input[type=text],input[type=password]{{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:9px 13px;font-size:14px;width:100%}}
label{{display:block;font-size:13px;color:var(--sub);margin-bottom:6px}}
.login-wrap{{display:flex;justify-content:center;align-items:center;min-height:100vh}}
.login-card{{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:40px 36px;width:340px}}
.login-card h2{{font-size:22px;margin-bottom:6px}}
.login-card p{{color:var(--sub);font-size:13px;margin-bottom:24px}}
.login-card .field{{margin-bottom:16px}}
.err{{color:var(--danger);font-size:13px;margin-top:10px}}
</style>
</head>
<body>
{body}
</body>
</html>"""
        return html.encode('utf-8')

    def _login_page(self, error: str = '') -> bytes:
        err_html = f'<p class="err">{error}</p>' if error else ''
        body = f"""
<div class="login-wrap">
  <div class="login-card">
    <h2>◈ Nova Servers</h2>
    <p>Sign in to manage your Minecraft server remotely.</p>
    <form method="POST" action="/login">
      <div class="field">
        <label>Username</label>
        <input type="text" name="username" placeholder="admin" autocomplete="username" required>
      </div>
      <div class="field">
        <label>Password</label>
        <input type="password" name="password" placeholder="••••••••" autocomplete="current-password" required>
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center" type="submit">Sign In →</button>
      {err_html}
    </form>
  </div>
</div>"""
        return self._html_page('Sign In', body)

    def _dashboard_page(self, state: dict) -> bytes:
        running     = state.get('running', False)
        name        = state.get('name', 'Server')
        loader      = state.get('loader', '?')
        mc_ver      = state.get('mc_version', '?')
        ram         = state.get('ram', 0)
        players     = state.get('players', [])
        total_joins = state.get('total_joins', 0)
        playit_url  = state.get('playit_url', '')

        status_cls = 'online' if running else 'offline'
        status_txt = '● Online'  if running else '○ Offline'

        player_rows = ''.join(
            f'<div class="player-row"><span class="dot-green">●</span>{p}</div>'
            for p in players
        ) or '<div style="color:var(--sub);font-size:13px;padding:6px 0">No players online</div>'

        playit_block = ''
        if playit_url:
            playit_block = f"""
<div class="card">
  <div class="card-hdr">🎮 Player Connection (Playit.gg)</div>
  <div class="card-body">
    <div class="playit-box">
      <div>
        <div style="color:var(--sub);font-size:11px;margin-bottom:4px">Give this address to players:</div>
        <div class="playit-addr" id="playit-addr">{playit_url}</div>
      </div>
      <button class="btn btn-ghost" style="margin-left:auto;white-space:nowrap"
        onclick="navigator.clipboard.writeText(document.getElementById('playit-addr').textContent);this.textContent='Copied ✓'">Copy</button>
    </div>
  </div>
</div>"""
        else:
            playit_block = """
<div class="card">
  <div class="card-hdr">🎮 Player Connection (Playit.gg)</div>
  <div class="card-body" style="color:var(--sub);font-size:13px">
    Playit.gg not running — start it in the desktop app to get a player address.
  </div>
</div>"""

        extra_head = """
<script>
/* ── live updates via fetch (cookies forwarded correctly) ── */
const con = document.getElementById('console');
let autoscroll = true;
con.addEventListener('scroll', () => {
  autoscroll = con.scrollTop + con.clientHeight >= con.scrollHeight - 10;
});

function applyState(s) {
  const el = id => document.getElementById(id);
  if (el('srv-status')) {
    el('srv-status').textContent  = s.running ? '\u25cf Online' : '\u25cb Offline';
    el('srv-status').className    = 'stat-val ' + (s.running ? 'online' : 'offline');
  }
  if (el('player-count')) el('player-count').textContent = s.player_count ?? 0;
  if (el('player-list'))  el('player-list').innerHTML =
    (s.players||[]).map(p => '<div class=\"player-row\"><span class=\"dot-green\">\u25cf</span>'+p+'</div>').join('') ||
    '<div style=\"color:var(--sub);font-size:13px;padding:6px 0\">No players online</div>';
  if (el('playit-addr') && s.playit_url) el('playit-addr').textContent = s.playit_url;
}

async function connectSSE() {
  try {
    const resp = await fetch('/events', {credentials: 'include'});
    if (resp.status === 401) { window.location = '/'; return; }
    if (!resp.ok) { setTimeout(connectSSE, 3000); return; }
    const reader = resp.body.getReader();
    const dec    = new TextDecoder();
    let buf = '';
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      const msgs = buf.split('\\n\\n');
      buf = msgs.pop();
      for (const msg of msgs) {
        let evtName = 'message', data = '';
        for (const ln of msg.split('\\n')) {
          if (ln.startsWith('event:')) evtName = ln.slice(6).trim();
          else if (ln.startsWith('data:')) data = ln.slice(5).trim();
        }
        if (!data) continue;
        if (evtName === 'log') {
          const line = data.replace(/\\\\n/g, '\\n');
          con.textContent += line;
          if (autoscroll) con.scrollTop = con.scrollHeight;
        } else if (evtName === 'state') {
          try { applyState(JSON.parse(data)); } catch(e) {}
        }
      }
    }
  } catch(e) { /* network error — retry */ }
  setTimeout(connectSSE, 3000);
}
connectSSE();

/* ── general helpers ──────────────────────────────── */
function api(path, body) {
  return fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
}
function sendCmd(cmd) { if(cmd) api('/web-cmd',{cmd}); }
function handleKey(e) { if(e.key==='Enter'){ sendCmd(e.target.value); e.target.value=''; } }

/* ── tab switching ─────────────────────────────────── */
function showTab(id) {
  document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).style.display = 'block';
  document.querySelector('[data-tab="' + id + '"]').classList.add('active');
  if (id === 'files') loadFiles('/');
  if (id === 'plugins') loadPlugins();
}

/* ── file browser ──────────────────────────────────── */
let currentPath = '/';
function loadFiles(path) {
  currentPath = path;
  document.getElementById('file-path').textContent = path;
  document.getElementById('file-list').innerHTML = '<div style="color:var(--sub);padding:12px">Loading…</div>';
  fetch('/files?path=' + encodeURIComponent(path))
    .then(r => r.json())
    .then(d => {
      if (d.root) document.getElementById('file-path').textContent = d.root + (path === '/' ? '' : path);
      renderFiles(d);
    })
    .catch(e => {
      document.getElementById('file-list').innerHTML =
        '<div style="color:var(--danger);padding:12px">⚠ ' + e + '</div>';
    });
}
function renderFiles(data) {
  const ul = document.getElementById('file-list');
  if (data.error) { ul.innerHTML = '<div style="color:var(--danger);padding:12px">' + data.error + '</div>'; return; }
  let html = '';
  if (data.parent !== null) {
    html += `<div class="file-row dir" onclick="loadFiles('${data.parent}')">
      <span class="file-icon">📁</span><span class="file-name">.. (up)</span></div>`;
  }
  (data.dirs||[]).forEach(d => {
    html += `<div class="file-row dir" onclick="loadFiles('${d.path}')">
      <span class="file-icon">📁</span><span class="file-name">${d.name}</span>
      <span class="file-size">${d.items} items</span></div>`;
  });
  (data.files||[]).forEach(f => {
    const acts = `<span class="file-actions">
      <a href="/download?path=${encodeURIComponent(f.path)}" class="act-link">⬇ Download</a>
      ${f.editable ? `<button class="act-btn" onclick="editFile('${f.path}')">✎ Edit</button>` : ''}
      <button class="act-btn danger" onclick="deleteFile('${f.path}','${f.name}')">🗑</button>
    </span>`;
    html += `<div class="file-row">
      <span class="file-icon">${f.icon}</span>
      <span class="file-name">${f.name}</span>
      <span class="file-size">${f.size}</span>
      ${acts}</div>`;
  });
  if (!html) html = '<div style="color:var(--sub);padding:12px">Empty folder</div>';
  ul.innerHTML = html;
}
function deleteFile(path, name) {
  if (!confirm('Delete ' + name + '?')) return;
  api('/delete-file', {path}).then(() => loadFiles(currentPath));
}
function editFile(path) {
  fetch('/file-content?path=' + encodeURIComponent(path)).then(r => r.json()).then(d => {
    if (d.error) { alert(d.error); return; }
    document.getElementById('editor-path').textContent = path;
    document.getElementById('editor-area').value = d.content;
    document.getElementById('editor-modal').style.display = 'flex';
    document.getElementById('editor-area').dataset.path = path;
  });
}
function saveEdit() {
  const path = document.getElementById('editor-area').dataset.path;
  const content = document.getElementById('editor-area').value;
  api('/save-file', {path, content}).then(r => r.json()).then(d => {
    if (d.ok) { closeEditor(); loadFiles(currentPath); }
    else alert('Save failed: ' + d.error);
  });
}
function closeEditor() { document.getElementById('editor-modal').style.display = 'none'; }
function uploadFile() {
  const inp = document.getElementById('upload-input');
  if (!inp.files.length) return;
  const fd = new FormData();
  fd.append('file', inp.files[0]);
  fd.append('path', currentPath);
  fetch('/upload-file', {method:'POST', body:fd})
    .then(r => r.json()).then(d => { if (d.ok) loadFiles(currentPath); else alert('Upload failed: ' + d.error); });
}

/* ── plugins ───────────────────────────────────────── */
function loadPlugins() {
  document.getElementById('plugin-list').innerHTML = '<div style="color:var(--sub);padding:12px">Loading…</div>';
  fetch('/plugins').then(r => r.json()).then(d => {
    if (d.error) { document.getElementById('plugin-list').innerHTML = '<div style="color:var(--danger);padding:12px">'+d.error+'</div>'; return; }
    let html = '';
    (d.plugins||[]).forEach(p => {
      html += `<div class="file-row">
        <span class="file-icon">🔌</span>
        <span class="file-name">${p.name}</span>
        <span class="file-size">${p.size}</span>
        <span class="file-actions">
          <button class="act-btn danger" onclick="removePlugin('${p.name}')">Remove</button>
        </span></div>`;
    });
    const note = d.note ? `<div style="color:var(--sub);font-size:11px;padding:6px 10px">${d.note}</div>` : '';
    if (!html) html = '<div style="color:var(--sub);padding:12px">No plugins installed</div>';
    document.getElementById('plugin-list').innerHTML = html + note;
  });
}
function removePlugin(name) {
  if (!confirm('Remove plugin ' + name + '?')) return;
  api('/remove-plugin', {name}).then(() => loadPlugins());
}
function uploadPlugin() {
  const inp = document.getElementById('plugin-upload-input');
  if (!inp.files.length) return;
  const fd = new FormData();
  fd.append('file', inp.files[0]);
  fetch('/upload-plugin', {method:'POST', body:fd})
    .then(r => r.json()).then(d => {
      if (d.ok) { loadPlugins(); inp.value=''; document.getElementById('plugin-status').textContent = '✓ Installed — restart server to activate'; }
      else alert('Upload failed: ' + d.error);
    });
}

/* ── world transfer ────────────────────────────────── */
function downloadWorld() {
  const wname = document.getElementById('world-name').value.trim() || 'world';
  document.getElementById('world-status').textContent = '⏳ Zipping world, download will start…';
  window.location = '/download-world?name=' + encodeURIComponent(wname);
  setTimeout(() => document.getElementById('world-status').textContent = '', 3000);
}
function uploadWorld() {
  const inp = document.getElementById('world-upload-input');
  if (!inp.files.length) { alert('Select a world zip first.'); return; }
  const wname = document.getElementById('world-name').value.trim() || 'world';
  document.getElementById('world-status').textContent = '⏳ Uploading…';
  const fd = new FormData();
  fd.append('file', inp.files[0]);
  fd.append('name', wname);
  fetch('/upload-world', {method:'POST', body:fd}).then(r => r.json()).then(d => {
    document.getElementById('world-status').textContent = d.ok ? '✓ World uploaded — restart server to use it' : '✗ ' + d.error;
  });
}
</script>
<style>
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:16px}
.tab-btn{padding:8px 18px;background:transparent;border:none;color:var(--sub);cursor:pointer;font-size:13px;font-weight:600;border-bottom:2px solid transparent;transition:.15s}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}
.file-row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid var(--border);font-size:13px}
.file-row:last-child{border-bottom:none}
.file-row.dir{cursor:pointer}.file-row.dir:hover{background:var(--panel)}
.file-icon{font-size:16px;flex-shrink:0}
.file-name{flex:1;word-break:break-all}
.file-size{color:var(--sub);font-size:11px;white-space:nowrap}
.file-actions{display:flex;gap:6px;flex-shrink:0}
.act-link{font-size:11px;color:var(--accent2);text-decoration:none}
.act-btn{font-size:11px;padding:2px 8px;border:1px solid var(--border);border-radius:4px;background:var(--panel);color:var(--text);cursor:pointer}
.act-btn.danger{color:var(--danger);border-color:var(--danger)}
.file-path-bar{display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--panel);border-radius:6px;margin-bottom:10px;font-size:12px;color:var(--sub)}
.upload-row{display:flex;gap:8px;align-items:center;padding:10px 0;flex-wrap:wrap}
.upload-row input[type=file]{font-size:12px;color:var(--sub)}
.player-row{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:13px;border-bottom:1px solid var(--border)}
.player-row:last-child{border-bottom:none}
.dot-green{color:var(--success)}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.modal-box{background:var(--panel);border:1px solid var(--border);border-radius:12px;width:min(860px,95vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden}
.modal-hdr{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;border-bottom:1px solid var(--border)}
.modal-hdr h3{font-size:14px;color:var(--text)}
textarea#editor-area{flex:1;background:#0D0D14;color:#A0F0B0;font-family:monospace;font-size:13px;border:none;padding:14px;resize:none;min-height:420px}
.modal-footer{display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--border)}
</style>"""

        body = f"""
<!-- editor modal -->
<div class="modal-overlay" id="editor-modal">
  <div class="modal-box">
    <div class="modal-hdr">
      <h3>✎ Edit: <span id="editor-path"></span></h3>
      <button class="btn btn-ghost" onclick="closeEditor()">✕ Close</button>
    </div>
    <textarea id="editor-area"></textarea>
    <div class="modal-footer">
      <button class="btn btn-primary" onclick="saveEdit()">💾 Save</button>
      <button class="btn btn-ghost"   onclick="closeEditor()">Cancel</button>
    </div>
  </div>
</div>

<header>
  <div>
    <h1>◈ {name}</h1>
    <span class="sub">{loader} · MC {mc_ver} · {ram} MB RAM</span>
  </div>
  <span class="tag" style="margin-left:auto">{loader}</span>
  <a href="/logout" class="btn btn-ghost" style="font-size:12px">Sign out</a>
</header>

<div class="layout">
  <!-- LEFT column -->
  <div class="left">

    {playit_block}

    <div class="card">
      <div class="card-hdr">Server Stats</div>
      <div class="card-body">
        <div class="ctrl-row">
          <button class="btn btn-success" onclick="sendCmd('__start__')">▶ Start</button>
          <button class="btn btn-warn"    onclick="sendCmd('__restart__')">↺ Restart</button>
          <button class="btn btn-danger"  onclick="sendCmd('__stop__')">■ Stop</button>
        </div>
        <div class="stat-row"><span class="stat-label">Status</span>
          <span class="stat-val {status_cls}" id="srv-status">{status_txt}</span></div>
        <div class="stat-row"><span class="stat-label">Online Now</span>
          <span class="stat-val" id="player-count">{len(players)}</span></div>
        <div class="stat-row"><span class="stat-label">All-Time Joins</span>
          <span class="stat-val">{total_joins}</span></div>
        <div class="stat-row"><span class="stat-label">MC Version</span>
          <span class="stat-val">{mc_ver}</span></div>
        <div class="stat-row"><span class="stat-label">Type</span>
          <span class="stat-val">{loader}</span></div>
        <div class="stat-row"><span class="stat-label">RAM</span>
          <span class="stat-val">{ram} MB</span></div>
      </div>
    </div>

    <div class="card">
      <div class="card-hdr">Online Players</div>
      <div class="card-body" id="player-list">
        {player_rows}
      </div>
    </div>

  </div>

  <!-- RIGHT column -->
  <div>
    <div class="tabs">
      <button class="tab-btn active" data-tab="console" onclick="showTab('console')">Console</button>
      <button class="tab-btn" data-tab="plugins"  onclick="showTab('plugins')">Plugins</button>
      <button class="tab-btn" data-tab="world"    onclick="showTab('world')">World</button>
      <button class="tab-btn" data-tab="files"    onclick="showTab('files')">Files</button>
    </div>

    <!-- Console tab -->
    <div class="tab-content" id="tab-console" style="display:block">
      <div class="card">
        <div class="card-body" style="padding:0">
          <div id="console" style="background:#0D0D14;color:#A0F0B0;font-family:'Courier New',monospace;font-size:12px;height:420px;overflow-y:auto;padding:10px;white-space:pre-wrap;word-break:break-all"></div>
          <div class="cmd-row" style="padding:10px">
            <input type="text" id="cmd-input" placeholder="Type a command and press Enter…" onkeydown="handleKey(event)">
            <button class="btn btn-primary"
              onclick="sendCmd(document.getElementById('cmd-input').value);document.getElementById('cmd-input').value=''">Send</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Plugins tab -->
    <div class="tab-content" id="tab-plugins">
      <div class="card">
        <div class="card-hdr">Installed Plugins</div>
        <div class="card-body" style="padding:0">
          <div id="plugin-list"></div>
          <div style="padding:12px;border-top:1px solid var(--border)">
            <div class="upload-row">
              <input type="file" id="plugin-upload-input" accept=".jar">
              <button class="btn btn-primary" onclick="uploadPlugin()">⬆ Install Plugin</button>
            </div>
            <div id="plugin-status" style="font-size:12px;color:var(--success);margin-top:4px"></div>
            <div style="font-size:11px;color:var(--sub);margin-top:4px">Restart the server after installing/removing plugins.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- World tab -->
    <div class="tab-content" id="tab-world">
      <div class="card">
        <div class="card-hdr">World Transfer</div>
        <div class="card-body">
          <div style="margin-bottom:14px">
            <label>World folder name</label>
            <input type="text" id="world-name" value="world" style="max-width:220px">
          </div>
          <div class="ctrl-row">
            <button class="btn btn-success" onclick="downloadWorld()">⬇ Download World (ZIP)</button>
            <span style="color:var(--sub);font-size:12px;align-self:center">or</span>
          </div>
          <div class="upload-row">
            <input type="file" id="world-upload-input" accept=".zip">
            <button class="btn btn-primary" onclick="uploadWorld()">⬆ Upload &amp; Replace World</button>
          </div>
          <div id="world-status" style="font-size:12px;color:var(--success);margin-top:8px"></div>
          <div style="font-size:11px;color:var(--sub);margin-top:8px">
            Upload replaces the world folder. The existing world is backed up automatically.<br>
            Stop the server before uploading to avoid corruption.
          </div>
        </div>
      </div>
    </div>

    <!-- Files tab -->
    <div class="tab-content" id="tab-files">
      <div class="card">
        <div class="card-hdr">File Browser</div>
        <div class="card-body" style="padding:10px">
          <div class="file-path-bar">
            📂 Server folder: <span id="file-path">/</span>
            <span style="margin-left:auto;display:flex;gap:8px">
              <label class="act-btn" style="cursor:pointer">
                ⬆ Upload
                <input type="file" id="upload-input" style="display:none" onchange="uploadFile()">
              </label>
            </span>
          </div>
          <div id="file-list"></div>
        </div>
      </div>
    </div>

  </div>
</div>
<script>
// Show console tab on load (default)
document.querySelector('[data-tab="console"]').classList.add('active');
</script>"""
        return self._html_page(f'Dashboard — {name}', body, extra_head)


    # ── file / plugin / world helpers ──────────────────────────────────────

    def _safe_path(self, rel: str):
        """Resolve rel path inside server dir; returns None on traversal attempt."""
        sdir = self._state.get('directory', '')
        if not sdir:
            return None
        root = Path(sdir).resolve()
        try:
            target = (root / rel.lstrip('/')).resolve()
            target.relative_to(root)
            return target
        except Exception:
            return None

    def _list_files(self, rel: str) -> dict:
        sdir = self._state.get('directory', '')
        if not sdir:
            return {'error': 'Server directory not set — start the server at least once so Nova Servers knows its folder, then try again.'}
        p = self._safe_path(rel)
        if p is None:
            return {'error': f'Path outside server directory (traversal blocked)'}
        if not p.exists():
            return {'error': f'Path does not exist: {rel}'}
        if not p.is_dir():
            return {'error': f'Not a folder: {rel}'}
        root = Path(sdir).resolve()
        parent = None
        if p != root:
            par = p.parent.relative_to(root)
            parent = '/' + str(par).replace('\\', '/')
            if parent == '/.':
                parent = '/'
        EDITABLE = {'.txt','.properties','.json','.yml','.yaml','.toml',
                    '.cfg','.conf','.log','.sh','.bat','.md','.ini','.xml'}
        ICONS = {'.jar':'📦','.zip':'🗜','.log':'📋','.json':'{}',
                 '.properties':'⚙','.yml':'⚙','.yaml':'⚙','.png':'🖼',
                 '.sh':'⚡','.bat':'⚡','.txt':'📄','.xml':'📄'}
        try:
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return {'error': 'Permission denied reading this folder'}
        dirs, files = [], []
        for entry in entries:
            rel_e = '/' + str(entry.relative_to(root)).replace('\\', '/')
            if entry.is_dir():
                # Don't count items — scanning thousands of library folders is slow
                dirs.append({'name': entry.name, 'path': rel_e, 'items': '—'})
            else:
                try:
                    sz  = entry.stat().st_size
                except OSError:
                    sz = 0
                sfx = entry.suffix.lower()
                sz_s = (f'{sz} B' if sz < 1024 else
                        f'{sz//1024:,} KB' if sz < 1048576 else
                        f'{sz/1048576:.1f} MB')
                files.append({'name': entry.name, 'path': rel_e, 'size': sz_s,
                              'icon': ICONS.get(sfx, '📄'),
                              'editable': sfx in EDITABLE and sz < 512*1024})
        return {'dirs': dirs, 'files': files, 'parent': parent,
                'root': str(root)}

    def _read_file(self, rel: str) -> dict:
        p = self._safe_path(rel)
        if p is None or not p.is_file():
            return {'error': 'File not found'}
        if p.stat().st_size > 512*1024:
            return {'error': 'File too large to edit (>512 KB)'}
        try:
            return {'content': p.read_text(encoding='utf-8', errors='replace')}
        except Exception as e:
            return {'error': str(e)}

    def _save_file(self, rel: str, content: str) -> dict:
        p = self._safe_path(rel)
        if p is None or not p.exists():
            return {'error': 'File not found or invalid path'}
        try:
            p.write_text(content, encoding='utf-8')
            return {'ok': True}
        except Exception as e:
            return {'error': str(e)}

    def _delete_file(self, rel: str) -> dict:
        p = self._safe_path(rel)
        if p is None or not p.exists():
            return {'error': 'File not found'}
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return {'ok': True}
        except Exception as e:
            return {'error': str(e)}

    def _download_file(self, rel: str):
        """Returns (bytes, filename, error)."""
        p = self._safe_path(rel)
        if p is None or not p.is_file():
            return None, None, 'File not found'
        try:
            return p.read_bytes(), p.name, None
        except Exception as e:
            return None, None, str(e)

    def _list_plugins(self) -> dict:
        sdir = self._state.get('directory', '')
        if not sdir:
            # State not populated yet — return empty list, not an error
            return {'plugins': [], 'note': 'Server not started yet'}
        pd = Path(sdir) / 'plugins'
        if not pd.exists():
            return {'plugins': [],
                    'note': 'No plugins folder (Vanilla/Fabric servers do not use plugins)'}
        out = []
        for f in sorted(pd.glob('*.jar')):
            sz = f.stat().st_size
            out.append({'name': f.name,
                        'size': f'{sz//1024:,} KB' if sz >= 1024 else f'{sz} B'})
        return {'plugins': out}

    def _remove_plugin(self, name: str) -> dict:
        sdir = self._state.get('directory', '')
        if not sdir:
            return {'error': 'Server directory unknown'}
        if '/' in name or '\\' in name or '..' in name:
            return {'error': 'Invalid plugin name'}
        p = Path(sdir) / 'plugins' / name
        if not p.exists() or p.suffix.lower() != '.jar':
            return {'error': 'Plugin not found'}
        try:
            p.unlink()
            return {'ok': True}
        except Exception as e:
            return {'error': str(e)}

    def _zip_world(self, world_name: str):
        """Returns (zip_bytes, error)."""
        sdir = self._state.get('directory', '')
        if not sdir:
            return None, 'Server directory unknown'
        world_dir = Path(sdir) / world_name
        if not world_dir.exists():
            return None, f'World folder "{world_name}" not found'
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in world_dir.rglob('*'):
                    if f.is_file():
                        zf.write(f, f.relative_to(world_dir.parent))
            return buf.getvalue(), None
        except Exception as e:
            return None, str(e)

    def _handle_upload(self, path: str, content_type: str, raw: bytes) -> dict:
        """Parse multipart/form-data and handle plugin/file/world upload."""
        import email as _email
        bm = re.search(r'boundary=([^\s;]+)', content_type)
        if not bm:
            return {'error': 'No multipart boundary'}
        msg = _email.message_from_bytes(
            f'Content-Type: {content_type}\r\n\r\n'.encode() + raw)
        file_data, file_name, extra_val = None, '', ''
        for part in msg.walk():
            disp = part.get('Content-Disposition', '')
            if not disp:
                continue
            params = {}
            for chunk in disp.split(';'):
                chunk = chunk.strip()
                if '=' in chunk:
                    k, v = chunk.split('=', 1)
                    params[k.strip()] = v.strip().strip('"')
            fn = params.get('name', '')
            if fn == 'file':
                file_data = part.get_payload(decode=True)
                file_name = params.get('filename', 'upload')
            elif fn in ('path', 'name'):
                extra_val = (part.get_payload(decode=True) or b'').decode('utf-8', errors='replace').strip()
        if file_data is None:
            return {'error': 'No file in request'}
        sdir = self._state.get('directory', '')
        if not sdir:
            return {'error': 'Server directory unknown'}

        if path == '/upload-plugin':
            if not file_name.lower().endswith('.jar'):
                return {'error': 'Only .jar files allowed'}
            safe = re.sub(r'[^\w.\-]', '_', file_name)
            pd   = Path(sdir) / 'plugins'
            pd.mkdir(exist_ok=True)
            (pd / safe).write_bytes(file_data)
            return {'ok': True, 'name': safe}

        if path == '/upload-file':
            tdir = self._safe_path(extra_val or '/')
            if tdir is None or not tdir.is_dir():
                return {'error': 'Invalid target directory'}
            safe = re.sub(r'[^\w.\-]', '_', file_name)
            (tdir / safe).write_bytes(file_data)
            return {'ok': True}

        if path == '/upload-world':
            wname = re.sub(r'[^\w.\-]', '_', extra_val or 'world')
            if not file_name.lower().endswith('.zip'):
                return {'error': 'World must be a .zip file'}
            wdir = Path(sdir) / wname
            if wdir.exists():
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                shutil.copytree(wdir, Path(sdir) / f'{wname}_backup_{ts}')
                shutil.rmtree(wdir)
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                zf.extractall(Path(sdir))
            return {'ok': True}

        return {'error': 'Unknown upload path'}

    def start(self) -> bool:
        try:
            server = self

            class _Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, fmt, *args):
                    pass  # suppress per-request access log

                def handle_error(self, request, client_address):
                    # Silence BrokenPipeError — Cloudflare and browsers close
                    # connections early; these are harmless and very noisy.
                    import sys as _sys
                    exc = _sys.exc_info()[1]
                    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
                        return
                    super().handle_error(request, client_address)

                # ── auth helpers ────────────────────────────────────────────

                def _check_api_auth(self) -> bool:
                    auth = self.headers.get('Authorization', '')
                    return auth == f"Bearer {server.pw_hash}"

                def _check_session(self) -> bool:
                    cookie = self.headers.get('Cookie', '')
                    token  = server._get_cookie(cookie, 'ns_session')
                    return server._valid_session(token)

                # ── response helpers ────────────────────────────────────────

                def _send_html(self, html_bytes: bytes, status: int = 200,
                               extra_headers: list = None):
                    self.send_response(status)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(html_bytes)))
                    self.send_header('Cache-Control', 'no-store')
                    for k, v in (extra_headers or []):
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(html_bytes)

                def _send_json(self, obj: dict, status: int = 200):
                    body = json.dumps(obj).encode('utf-8')
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)

                def _redirect(self, location: str, extra_headers: list = None):
                    self.send_response(303)
                    self.send_header('Location', location)
                    self.send_header('Cache-Control', 'no-store')
                    for k, v in (extra_headers or []):
                        self.send_header(k, v)
                    self.end_headers()

                # ── OPTIONS (CORS pre-flight) ───────────────────────────────

                def do_OPTIONS(self):
                    self.send_response(204)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Headers',
                                     'Authorization, Content-Type')
                    self.send_header('Access-Control-Allow-Methods',
                                     'GET, POST, OPTIONS')
                    self.end_headers()

                # ── GET ─────────────────────────────────────────────────────

                def do_GET(self):
                    path = urllib.parse.urlparse(self.path).path

                    # ── unauthenticated ─────────────────────────────────────

                    if path == '/ping':
                        self._send_json({'nova': True,
                                         'protocol': ADMIN_PROTOCOL_VER})
                        return

                    if path in ('/', '/login'):
                        self._send_html(server._login_page())
                        return

                    if path == '/logout':
                        cookie = self.headers.get('Cookie', '')
                        token  = server._get_cookie(cookie, 'ns_session')
                        with server._session_lock:
                            server._sessions.pop(token, None)
                        self._redirect('/', extra_headers=[
                            ('Set-Cookie', 'ns_session=; Max-Age=0; Path=/')])
                        return

                    # ── web browser UI (session cookie) ─────────────────────

                    if path == '/dashboard':
                        if not self._check_session():
                            self._redirect('/')
                            return
                        with server._state_lock:
                            state = server._state.copy()
                        self._send_html(server._dashboard_page(state))
                        return

                    if path == '/events':
                        # Server-Sent Events — browser dashboard live updates
                        if not self._check_session():
                            self.send_response(401)
                            self.send_header('Content-Type', 'text/plain')
                            self.send_header('Content-Length', '12')
                            self.end_headers()
                            try: self.wfile.write(b'Unauthorized')
                            except Exception: pass
                            return
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('X-Accel-Buffering', 'no')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()

                        q: queue.Queue = queue.Queue(maxsize=200)
                        with server._sse_lock:
                            server._sse_queues.append(q)

                        # Send buffered console history first
                        with server._log_lock:
                            history = list(server._console_log)
                        def _sse(kind, data):
                            # SSE data fields must not contain raw newlines.
                            # Escape them so the browser can unescape them.
                            safe = data.replace('\n', '\\n').replace('\r', '')
                            return f'event: {kind}\ndata: {safe}\n\n'.encode('utf-8')

                        try:
                            for line in history:
                                self.wfile.write(_sse('log', line))
                            self.wfile.flush()

                            while True:
                                try:
                                    kind, data = q.get(timeout=20)
                                    self.wfile.write(_sse(kind, data))
                                    self.wfile.flush()
                                except queue.Empty:
                                    self.wfile.write(b': keepalive\n\n')
                                    self.wfile.flush()
                        except Exception:
                            pass
                        finally:
                            with server._sse_lock:
                                try:
                                    server._sse_queues.remove(q)
                                except ValueError:
                                    pass
                        return

                    # ── web browser file/plugin/world routes (session) ──────

                    if path in ('/files', '/file-content', '/download',
                                '/plugins', '/download-world'):
                        if not self._check_session():
                            self._redirect('/')
                            return

                        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

                        if path == '/files':
                            self._send_json(server._list_files(
                                qs.get('path', ['/'])[0]))

                        elif path == '/file-content':
                            self._send_json(server._read_file(
                                qs.get('path', [''])[0]))

                        elif path == '/download':
                            data, fname, err = server._download_file(
                                qs.get('path', [''])[0])
                            if err:
                                self._send_json({'error': err}, 404)
                            else:
                                self.send_response(200)
                                self.send_header('Content-Type', 'application/octet-stream')
                                self.send_header('Content-Disposition',
                                                 f'attachment; filename="{fname}"')
                                self.send_header('Content-Length', str(len(data)))
                                self.send_header('Cache-Control', 'no-store')
                                self.end_headers()
                                self.wfile.write(data)

                        elif path == '/plugins':
                            self._send_json(server._list_plugins())

                        elif path == '/download-world':
                            wname = qs.get('name', ['world'])[0]
                            data, err = server._zip_world(wname)
                            if err:
                                self._send_json({'error': err}, 400)
                            else:
                                self.send_response(200)
                                self.send_header('Content-Type', 'application/zip')
                                self.send_header('Content-Disposition',
                                                 f'attachment; filename="{wname}.zip"')
                                self.send_header('Content-Length', str(len(data)))
                                self.send_header('Cache-Control', 'no-store')
                                self.end_headers()
                                self.wfile.write(data)
                        return

                    # ── Python AdminClient API (Bearer token) ───────────────

                    if not self._check_api_auth():
                        self._send_json({'error': 'Unauthorized'}, 401)
                        return

                    if path == '/state':
                        with server._state_lock:
                            self._send_json({'type': 'state',
                                             'data': server._state.copy()})

                    elif path == '/poll':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain')
                        self.send_header('Transfer-Encoding', 'chunked')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        try:
                            while server._running:
                                with server._state_lock:
                                    state = server._state.copy()
                                payload = (json.dumps(
                                    {'type': 'state', 'data': state}
                                ) + '\n').encode('utf-8')
                                chunk_header = f'{len(payload):X}\r\n'.encode()
                                self.wfile.write(
                                    chunk_header + payload + b'\r\n')
                                self.wfile.flush()
                                time.sleep(2)
                            self.wfile.write(b'0\r\n\r\n')
                        except Exception:
                            pass

                    else:
                        self._send_json({'error': 'Not found'}, 404)

                # ── POST ────────────────────────────────────────────────────

                def do_POST(self):
                    path = urllib.parse.urlparse(self.path).path

                    # ── web login ───────────────────────────────────────────

                    if path == '/login':
                        length = int(self.headers.get('Content-Length', 0))
                        raw    = self.rfile.read(length).decode('utf-8', errors='replace')
                        params = urllib.parse.parse_qs(raw)
                        pw     = params.get('password', [''])[0]
                        if _pw_hash(pw) == server.web_pw_hash:
                            token = server._new_session()
                            self._redirect('/dashboard', extra_headers=[
                                ('Set-Cookie',
                                 f'ns_session={token}; Max-Age=28800; Path=/; HttpOnly')])
                        else:
                            self._send_html(
                                server._login_page('Wrong password — try again.'),
                                status=401)
                        return

                    # ── web command (from dashboard fetch/form) ─────────────

                    if path == '/web-cmd':
                        if not self._check_session():
                            self._send_json({'error': 'Unauthorized'}, 401)
                            return
                        length = int(self.headers.get('Content-Length', 0))
                        body   = self.rfile.read(length)
                        try:
                            msg = json.loads(body.decode('utf-8'))
                            cmd = msg.get('cmd', '').strip()
                            if cmd and server._cmd_callback:
                                # Map the special UI button commands
                                if cmd == '__start__':
                                    server._cmd_callback('start', [])
                                elif cmd == '__stop__':
                                    server._cmd_callback('stop', [])
                                elif cmd == '__restart__':
                                    server._cmd_callback('restart', [])
                                else:
                                    server._cmd_callback('console', [cmd])
                            self._send_json({'ok': True})
                        except Exception as e:
                            self._send_json({'error': str(e)}, 400)
                        return

                    # ── file save ──────────────────────────────────────────

                    if path == '/save-file':
                        if not self._check_session():
                            self._send_json({'error': 'Unauthorized'}, 401)
                            return
                        length = int(self.headers.get('Content-Length', 0))
                        body   = self.rfile.read(length)
                        try:
                            msg     = json.loads(body.decode('utf-8'))
                            result  = server._save_file(msg.get('path',''), msg.get('content',''))
                            self._send_json(result)
                        except Exception as e:
                            self._send_json({'error': str(e)}, 400)
                        return

                    # ── file delete ─────────────────────────────────────────

                    if path == '/delete-file':
                        if not self._check_session():
                            self._send_json({'error': 'Unauthorized'}, 401)
                            return
                        length = int(self.headers.get('Content-Length', 0))
                        body   = self.rfile.read(length)
                        try:
                            msg    = json.loads(body.decode('utf-8'))
                            result = server._delete_file(msg.get('path',''))
                            self._send_json(result)
                        except Exception as e:
                            self._send_json({'error': str(e)}, 400)
                        return

                    # ── plugin remove ───────────────────────────────────────

                    if path == '/remove-plugin':
                        if not self._check_session():
                            self._send_json({'error': 'Unauthorized'}, 401)
                            return
                        length = int(self.headers.get('Content-Length', 0))
                        body   = self.rfile.read(length)
                        try:
                            msg    = json.loads(body.decode('utf-8'))
                            result = server._remove_plugin(msg.get('name',''))
                            self._send_json(result)
                        except Exception as e:
                            self._send_json({'error': str(e)}, 400)
                        return

                    # ── multipart uploads (plugin / file / world) ────────────

                    if path in ('/upload-file', '/upload-plugin', '/upload-world'):
                        if not self._check_session():
                            self._send_json({'error': 'Unauthorized'}, 401)
                            return
                        ct     = self.headers.get('Content-Type', '')
                        length = int(self.headers.get('Content-Length', 0))
                        raw    = self.rfile.read(length)
                        try:
                            result = server._handle_upload(path, ct, raw)
                            self._send_json(result)
                        except Exception as e:
                            self._send_json({'error': str(e)}, 500)
                        return

                    # ── Python AdminClient API ──────────────────────────────

                    if not self._check_api_auth():
                        self._send_json({'error': 'Unauthorized'}, 401)
                        return
                    if path == '/cmd':
                        length = int(self.headers.get('Content-Length', 0))
                        body   = self.rfile.read(length)
                        try:
                            msg  = json.loads(body.decode('utf-8'))
                            cmd  = msg.get('cmd', '')
                            args = msg.get('args', [])
                            if server._cmd_callback and cmd:
                                server._cmd_callback(cmd, args)
                            self._send_json({'ok': True})
                        except Exception as e:
                            self._send_json({'error': str(e)}, 400)
                    else:
                        self._send_json({'error': 'Not found'}, 404)

            import socketserver as _ss
            class _ThreadingHTTPServer(_ss.ThreadingMixIn,
                                       http.server.HTTPServer):
                daemon_threads = True  # die when main thread dies
            self._httpd = _ThreadingHTTPServer(
                ('0.0.0.0', self.port), _Handler)
            self._running = True
            threading.Thread(target=self._httpd.serve_forever,
                             daemon=True).start()
            return True
        except Exception as e:
            print(f'[AdminServer] Could not start: {e}')
            return False

    def stop(self):
        self._running = False
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass


class AdminClient:
    """
    HTTP client. Polls /poll for live state, POSTs /cmd for commands.
    Works over HTTP (LAN/UPnP) or HTTPS (Cloudflare Tunnel URL).

    Cloudflare TryCloudflare tunnels buffer chunked-transfer responses,
    so when a CF URL is used we fall back to polling /state every 3 s
    instead of streaming /poll.  Direct LAN/UPnP connections still use
    the efficient streaming /poll endpoint.
    """
    def __init__(self, host: str, port: int, password: str,
                 on_state, on_disconnect, on_error,
                 base_url: str = ''):
        if base_url:
            self.base_url   = base_url.rstrip('/')
            # Cloudflare tunnel URLs always use HTTPS (trycloudflare.com)
            self._use_cf    = 'trycloudflare.com' in self.base_url or \
                              self.base_url.startswith('https://')
        else:
            self.base_url   = f'http://{host}:{port}'
            self._use_cf    = False
        self._auth         = _auth_header(password)
        self.on_state      = on_state
        self.on_disconnect = on_disconnect
        self.on_error      = on_error
        self._running      = False

    def _make_request(self, path: str, data: bytes = None,
                      extra_headers: dict = None, timeout: int = 10):
        """Build and return a urllib Request with the correct headers."""
        headers = _admin_request_headers(self._auth)
        if extra_headers:
            headers.update(extra_headers)
        return urllib.request.Request(
            f'{self.base_url}{path}',
            data=data,
            headers=headers,
        )

    def _check_cf_interstitial(self, response_bytes: bytes) -> bool:
        """
        Return True if the response looks like a Cloudflare challenge/
        interstitial page rather than our JSON API.  This happens when
        the tunnel URL is opened in a way that triggers CF's browser check.
        """
        snippet = response_bytes[:512].lower()
        return b'<html' in snippet or b'cloudflare' in snippet

    def connect(self) -> bool:
        try:
            # First hit /ping (unauthenticated) to confirm this is a Nova
            # Servers endpoint and not a Cloudflare interstitial page.
            if self._use_cf:
                try:
                    ping_req = self._make_request('/ping', timeout=12)
                    with urllib.request.urlopen(ping_req, timeout=12) as r:
                        raw = r.read()
                    if self._check_cf_interstitial(raw):
                        self.on_error(
                            'Cloudflare returned a challenge page instead of '
                            'the admin server.\n\n'
                            'Make sure the host has started the Admin Server '
                            '(▶ Start Hosting) before starting the tunnel, '
                            'and that cloudflared is tunnelling the correct port.')
                        return False
                    ping_data = json.loads(raw)
                    if not ping_data.get('nova'):
                        self.on_error(
                            'The URL does not point to a Nova Servers admin endpoint.')
                        return False
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        # Older server — skip ping check, continue to /state
                        pass
                    else:
                        raise

            req = self._make_request('/state')
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()

            if self._check_cf_interstitial(raw):
                self.on_error(
                    'Received a Cloudflare challenge page — the tunnel URL '
                    'may have expired or the Admin Server is not running.')
                return False

            data = json.loads(raw)
            if 'error' in data:
                self.on_error(f"Auth failed: {data['error']}")
                return False

            self._running = True
            # Use short-poll for CF tunnels (streaming is buffered by CF);
            # use the efficient /poll stream for direct LAN connections.
            target = self._cf_poll_loop if self._use_cf else self._poll_loop
            threading.Thread(target=target, daemon=True).start()
            return True

        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.on_error('Wrong password.')
            else:
                self.on_error(f'HTTP {e.code}: {e.reason}')
            return False
        except Exception as e:
            self.on_error(str(e))
            return False

    def send_cmd(self, cmd: str, args: list = None):
        def _send():
            try:
                body = json.dumps({'cmd': cmd, 'args': args or []}).encode()
                req  = self._make_request(
                    '/cmd', data=body,
                    extra_headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=8)
            except Exception:
                pass
        threading.Thread(target=_send, daemon=True).start()

    def disconnect(self):
        self._running = False

    def _cf_poll_loop(self):
        """
        Polling fallback for Cloudflare tunnel connections.
        Cloudflare buffers chunked-transfer responses, so /poll never
        delivers lines in real-time over a CF URL.  Instead we hit /state
        every 3 seconds which works fine over HTTPS.
        """
        while self._running:
            try:
                req = self._make_request('/state')
                with urllib.request.urlopen(req, timeout=15) as r:
                    raw = r.read()
                if self._check_cf_interstitial(raw):
                    # Tunnel expired / CF re-challenged
                    if self._running:
                        self.on_error('Cloudflare challenge appeared — tunnel may have expired.')
                    break
                data = json.loads(raw)
                if data.get('type') == 'state' and 'data' in data:
                    self.on_state(data['data'])
            except Exception:
                pass
            time.sleep(3)
        self.on_disconnect()

    def _poll_loop(self):
        """Efficient streaming poll for direct LAN/UPnP connections."""
        while self._running:
            try:
                req = self._make_request('/poll')
                with urllib.request.urlopen(req, timeout=60) as r:
                    for raw_line in r:
                        if not self._running:
                            break
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                            if msg.get('type') == 'state':
                                self.on_state(msg['data'])
                        except Exception:
                            pass
            except Exception:
                if self._running:
                    time.sleep(3)
                    continue
        self.on_disconnect()


# ── World transfer helpers (P2P over TCP) ─────────────────────────────────────────

class WorldSender:
    """Zips a world folder and sends it over a TCP socket to WorldReceiver."""
    def __init__(self, world_dir: str, port: int = 25576,
                 progress_cb=None, log_cb=None, done_cb=None):
        self.world_dir   = world_dir
        self.port        = port
        self.progress_cb = progress_cb
        self.log_cb      = log_cb
        self.done_cb     = done_cb
        self._sock       = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            _log(self.log_cb, "Zipping world…")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                base = Path(self.world_dir)
                files = list(base.rglob("*"))
                for i, f in enumerate(files):
                    if f.is_file():
                        zf.write(f, f.relative_to(base.parent))
                    if self.progress_cb:
                        self.progress_cb(i + 1, len(files))
            data = buf.getvalue()
            _log(self.log_cb, f"World zipped ({len(data)//1024:,} KB). Waiting for receiver…")

            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(1)
            srv.settimeout(120)
            conn, addr = srv.accept()
            srv.close()
            _log(self.log_cb, f"Receiver connected from {addr[0]}, sending…")

            # Send size then data
            conn.sendall(struct.pack(">Q", len(data)))
            sent = 0
            chunk = 65536
            while sent < len(data):
                end = min(sent + chunk, len(data))
                conn.sendall(data[sent:end])
                sent = end
                if self.progress_cb:
                    self.progress_cb(sent, len(data))
            conn.close()
            _log(self.log_cb, "World sent ✓")
            if self.done_cb:
                self.done_cb(True, "")
        except Exception as e:
            _log(self.log_cb, f"[ERROR] {e}")
            if self.done_cb:
                self.done_cb(False, str(e))


class WorldReceiver:
    """Connects to WorldSender and saves the received zip as the world."""
    def __init__(self, host: str, world_dir: str, port: int = 25576,
                 progress_cb=None, log_cb=None, done_cb=None):
        self.host        = host
        self.world_dir   = world_dir
        self.port        = port
        self.progress_cb = progress_cb
        self.log_cb      = log_cb
        self.done_cb     = done_cb

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            _log(self.log_cb, f"Connecting to {self.host}:{self.port}…")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((self.host, self.port))
            sock.settimeout(None)
            _log(self.log_cb, "Connected. Receiving world data…")

            raw = _recv_exactly(sock, 8)
            total = struct.unpack(">Q", raw)[0]
            _log(self.log_cb, f"World size: {total//1024:,} KB")

            received = b""
            while len(received) < total:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received += chunk
                if self.progress_cb:
                    self.progress_cb(len(received), total)
            sock.close()

            _log(self.log_cb, "Extracting world…")
            dest = Path(self.world_dir)
            # Backup existing world first
            backup = dest.parent / (dest.name + "_backup_" +
                                    datetime.now().strftime("%Y%m%d_%H%M%S"))
            if dest.exists():
                shutil.copytree(dest, backup)
                _log(self.log_cb, f"Existing world backed up → {backup.name}")

            with zipfile.ZipFile(io.BytesIO(received)) as zf:
                zf.extractall(dest.parent)
            _log(self.log_cb, "World received and extracted ✓")
            if self.done_cb:
                self.done_cb(True, "")
        except Exception as e:
            _log(self.log_cb, f"[ERROR] {e}")
            if self.done_cb:
                self.done_cb(False, str(e))


# ── Main GUI ──────────────────────────────────────────────────────────────────────

class NovaServers(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1150x720")
        self.minsize(960, 620)
        self.configure(bg=COLORS["bg"])

        SERVERS_DIR.mkdir(exist_ok=True)
        self.config      = load_config()
        global _UPNP_ENABLED
        _UPNP_ENABLED = self.config.get("upnp_enabled", False)
        self.server_procs: dict[str, ServerProcess] = {}
        self.playit: PlayitProcess | None = None

        # Admin Tools — one AdminServer per hosted server (keyed by server name)
        self.admin_servers: dict[str, AdminServer] = {}
        # Cloudflare tunnels keyed by server name
        self.cf_tunnels: dict[str, CloudflaredTunnel] = {}
        # Per-server player tracking (parsed from console output)
        self._player_lists: dict[str, list[str]] = {}
        self._total_joins:  dict[str, int]  = {}

        self._style_ttk()
        self._build_ui()
        self._refresh_server_list()

        # Broadcast state to any connected admin clients every 2 seconds
        self._broadcast_admin_state()

        if self.config.get("playit_auto_start") and self.config.get("playit_path"):
            self.after(1000, self._auto_start_playit)

    # ── TTK styling ─────────────────────────────────────────────────────────────

    def _style_ttk(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            selectbackground=COLORS["accent"],
            selectforeground="white",
            borderwidth=0)
        style.configure("TScrollbar",
            background=COLORS["panel"],
            troughcolor=COLORS["bg"],
            borderwidth=0)
        style.configure("TProgressbar",
            troughcolor=COLORS["panel"],
            background=COLORS["accent"],
            borderwidth=0)
        style.configure("TSeparator", background=COLORS["border"])

    # ── Layout ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.sidebar = tk.Frame(self, bg=COLORS["panel"], width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_frame = tk.Frame(self.sidebar, bg=COLORS["panel"])
        logo_frame.pack(fill="x", pady=(16, 12))
        tk.Label(logo_frame, text="◈", font=("Helvetica", 22),
                 bg=COLORS["panel"], fg=COLORS["accent"]).pack(side="left", padx=(18, 6))
        tk.Label(logo_frame, text=APP_NAME, font=("Helvetica", 14, "bold"),
                 bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")

        tk.Frame(self.sidebar, bg=COLORS["border"], height=1).pack(fill="x", padx=14)

        # Nav items — simple frame, no canvas needed for 5 items
        self.nav_frame = tk.Frame(self.sidebar, bg=COLORS["panel"])
        self.nav_frame.pack(fill="x", pady=8)

        self._nav_buttons = {}
        self._active_nav  = None
        for label, icon, cmd in [
            ("Servers",    "▣", self._show_servers),
            ("New Server", "＋", self._show_new_server),
            ("Playit.gg",  "⬡", self._show_playit),
            ("Admin Join", "⇌", self._show_admin_join),
            ("Settings",   "⚙", self._show_settings),
        ]:
            btn = tk.Button(
                self.nav_frame,
                text=f"  {icon}  {label}",
                anchor="w", padx=10,
                font=("Helvetica", 10), bd=0, relief="flat",
                bg=COLORS["panel"], fg=COLORS["subtext"],
                activebackground=COLORS["card"],
                activeforeground=COLORS["text"],
                cursor="hand2",
                command=lambda c=cmd, l=label: self._nav(c, l),
            )
            btn.pack(fill="x", ipady=9)
            self._nav_buttons[label] = btn

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.sidebar, textvariable=self.status_var,
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8), wraplength=190, pady=6
                 ).pack(side="bottom", fill="x")

        self.playit_indicator = tk.Label(
            self.sidebar, text="● Playit off",
            bg=COLORS["panel"], fg=COLORS["subtext"], font=("Helvetica", 8))
        self.playit_indicator.pack(side="bottom", fill="x", padx=14, pady=(0, 4))

        self.content = tk.Frame(self, bg=COLORS["bg"])
        self.content.pack(side="right", fill="both", expand=True)

        self.pages: dict[str, tk.Frame] = {}
        for name in ("servers", "new_server", "playit", "admin_join", "settings"):
            f = tk.Frame(self.content, bg=COLORS["bg"])
            self.pages[name] = f
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_servers_page()
        self._build_new_server_page()
        self._build_playit_page()
        self._build_admin_join_page()
        self._build_settings_page()
        self._nav(self._show_servers, "Servers")

    # ── Navigation ───────────────────────────────────────────────────────────────

    def _nav(self, cmd, label):
        for l, b in self._nav_buttons.items():
            if l == label:
                b.config(bg=COLORS["card"], fg=COLORS["accent"])
            else:
                b.config(bg=COLORS["panel"], fg=COLORS["subtext"])
        cmd()

    def _show_page(self, name):   self.pages[name].lift()
    def _show_servers(self):      self._show_page("servers")
    def _show_new_server(self):   self._show_page("new_server")
    def _show_playit(self):       self._show_page("playit")
    def _show_admin_join(self):   self._show_page("admin_join")
    def _show_settings(self):     self._show_page("settings")

    def _btn(self, parent, text, cmd, color=None, fg="white", **kwargs):
        color = color or COLORS["accent"]
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg=fg, bd=0, cursor="hand2",
                         activebackground=color, activeforeground=fg,
                         relief="flat", **kwargs)

    # ── Servers page ─────────────────────────────────────────────────────────────

    def _build_servers_page(self):
        page = self.pages["servers"]

        # ── Header ───────────────────────────────────────────────────────────
        header = tk.Frame(page, bg=COLORS["bg"])
        header.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(header, text="Your Servers", font=("Helvetica", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
        self._btn(header, "⟳  Refresh", self._refresh_server_list,
                  color=COLORS["card"], fg=COLORS["text"],
                  padx=12, pady=4).pack(side="right")

        tk.Frame(page, bg=COLORS["border"], height=1).pack(fill="x", padx=24)

        # ── Bottom bar — MUST be packed before the expanding canvas ──────────
        # tkinter packs side="bottom" widgets in reverse order of declaration,
        # so anything that should sit below an expand=True canvas must be
        # packed first (before the canvas), then the canvas fills the rest.
        tk.Frame(page, bg=COLORS["border"], height=1).pack(
            side="bottom", fill="x")
        bottom = tk.Frame(page, bg=COLORS["panel"], padx=16, pady=10)
        bottom.pack(side="bottom", fill="x")

        tk.Label(bottom, text="⇌  Connect to Admin Tools",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 9)).pack(side="left", padx=(0, 12))

        tk.Label(bottom, text="Host:", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 9)).pack(side="left")
        self._quick_host = tk.StringVar()
        tk.Entry(bottom, textvariable=self._quick_host, width=16,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", ipady=4, padx=(4, 8))

        tk.Label(bottom, text="Port:", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 9)).pack(side="left")
        self._quick_port = tk.StringVar(value=str(ADMIN_PORT_DEFAULT))
        tk.Entry(bottom, textvariable=self._quick_port, width=6,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", ipady=4, padx=(4, 8))

        tk.Label(bottom, text="Password:", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 9)).pack(side="left")
        self._quick_pw = tk.StringVar()
        tk.Entry(bottom, textvariable=self._quick_pw, show="●", width=12,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", ipady=4, padx=(4, 8))

        # Optional Cloudflare URL — overrides host:port when filled
        tk.Label(bottom, text="or CF URL:", bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(side="left")
        self._quick_cfurl = tk.StringVar()
        tk.Entry(bottom, textvariable=self._quick_cfurl, width=22,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 8),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", ipady=4, padx=(4, 8))

        self._btn(bottom, "Connect →", self._quick_admin_connect,
                  color=COLORS["accent"], padx=12, pady=4,
                  font=("Helvetica", 9, "bold")).pack(side="left", padx=(0, 10))

        self._quick_status = tk.StringVar(value="")
        tk.Label(bottom, textvariable=self._quick_status,
                 bg=COLORS["panel"], fg=COLORS["warning"],
                 font=("Helvetica", 8)).pack(side="left")

        # ── Scrollable server list canvas (packed last so it fills remaining space)
        canvas = tk.Canvas(page, bg=COLORS["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        self.server_list_frame = tk.Frame(canvas, bg=COLORS["bg"])
        self.server_list_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.server_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(24, 0), pady=(10, 4))

        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _scroll)

    def _refresh_server_list(self):
        for w in self.server_list_frame.winfo_children():
            w.destroy()
        servers = self.config.get("servers", {})
        if not servers:
            tk.Label(self.server_list_frame,
                     text="No servers yet — click  ＋ New Server  to add one.",
                     bg=COLORS["bg"], fg=COLORS["subtext"],
                     font=("Helvetica", 12), pady=50).pack()
            return
        for name, info in servers.items():
            self._server_card(name, info)

    def _server_card(self, name, info):
        loader     = info.get("loader", "Paper")
        linfo      = LOADER_INFO.get(loader, {})
        color      = linfo.get("color", COLORS["accent"])
        is_running = name in self.server_procs and self.server_procs[name].running

        outer = tk.Frame(self.server_list_frame, bg=COLORS["bg"])
        outer.pack(fill="x", pady=5, padx=4)

        card = tk.Frame(outer, bg=COLORS["card"],
                        highlightbackground=color if is_running else COLORS["border"],
                        highlightthickness=1)
        card.pack(fill="x")

        tk.Frame(card, bg=color, width=5).pack(side="left", fill="y")

        inner = tk.Frame(card, bg=COLORS["card"], padx=14, pady=10)
        inner.pack(side="left", fill="both", expand=True)

        tr = tk.Frame(inner, bg=COLORS["card"])
        tr.pack(fill="x")

        dot_color = COLORS["success"] if is_running else COLORS["danger"]
        tk.Label(tr, text="●", fg=dot_color, bg=COLORS["card"],
                 font=("Helvetica", 10)).pack(side="left", padx=(0, 6))
        tk.Label(tr, text=name, font=("Helvetica", 12, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"]).pack(side="left")

        tk.Label(tr, text=loader, font=("Helvetica", 8, "bold"),
                 bg=color, fg="white", padx=8, pady=2).pack(side="left", padx=10)

        mc_ver = info.get("mc_version", "?")
        ram    = info.get("ram", 2048)
        tk.Label(inner, text=f"MC {mc_ver}  ·  {ram} MB RAM",
                 font=("Helvetica", 9), bg=COLORS["card"],
                 fg=COLORS["subtext"]).pack(anchor="w", pady=(3, 6))

        br = tk.Frame(inner, bg=COLORS["card"])
        br.pack(fill="x")
        if is_running:
            self._btn(br, "■  Stop",
                      lambda n=name: self._stop_server(n),
                      color=COLORS["danger"], padx=12, pady=4).pack(side="left", padx=(0, 6))
            self._btn(br, "⊞  View",
                      lambda n=name, i=info: self._open_dashboard(n, i),
                      color=COLORS["accent"], padx=12, pady=4).pack(side="left", padx=(0, 6))
            self._btn(br, "▶  Console",
                      lambda n=name, i=info: self._open_console(n, i),
                      color=COLORS["card"], fg=COLORS["text"], padx=12, pady=4,
                      highlightbackground=COLORS["border"], highlightthickness=1).pack(side="left")
        else:
            self._btn(br, "▶  Start",
                      lambda n=name, i=info: self._start_server(n, i),
                      color=COLORS["success"], fg=COLORS["bg"], padx=12, pady=4).pack(side="left", padx=(0, 6))
            self._btn(br, "⊞  View",
                      lambda n=name, i=info: self._open_dashboard(n, i),
                      color=COLORS["accent"], padx=10, pady=4).pack(side="left", padx=(0, 6))
            self._btn(br, "✎  Edit",
                      lambda n=name, i=info: self._open_edit_server(n, i),
                      color=COLORS["card"], fg=COLORS["text"], padx=10, pady=4,
                      highlightbackground=COLORS["border"], highlightthickness=1).pack(side="left", padx=(0, 6))
            self._btn(br, "Delete",
                      lambda n=name: self._delete_server(n),
                      color=COLORS["card"], fg=COLORS["danger"], padx=10, pady=4).pack(side="left")

    # ── Edit Server Dialog ──────────────────────────────────────────────────────

    def _open_edit_server(self, name, info):
        win = tk.Toplevel(self)
        win.title(f"Edit Server — {name}")
        win.geometry("500x480")
        win.resizable(False, False)
        win.configure(bg=COLORS["bg"])
        win.grab_set()

        tk.Label(win, text=f"Edit Server: {name}", font=("Helvetica", 14, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill="x", padx=20)

        form = tk.Frame(win, bg=COLORS["panel"], padx=20, pady=16)
        form.pack(fill="both", expand=True, padx=20, pady=12)

        def add_field(label, val):
            r = tk.Frame(form, bg=COLORS["panel"])
            r.pack(fill="x", pady=6)
            tk.Label(r, text=label, width=16, anchor="w", bg=COLORS["panel"],
                     fg=COLORS["text"], font=("Helvetica", 10)).pack(side="left")
            var = tk.StringVar(value=str(val))
            tk.Entry(r, textvariable=var, bg=COLORS["card"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
            return var

        server_dir      = info.get("directory", "")
        current_motd    = read_server_property(server_dir, "motd", "A Nova Server")
        current_players = read_server_property(server_dir, "max-players", "20")

        var_version = add_field("MC Version",   info.get("mc_version", "1.21.1"))
        var_ram     = add_field("RAM (MB)",      info.get("ram", 2048))
        var_motd    = add_field("MOTD Text",     current_motd)
        var_players = add_field("Max Players",   current_players)

        # Server icon row
        ir = tk.Frame(form, bg=COLORS["panel"])
        ir.pack(fill="x", pady=8)
        tk.Label(ir, text="Server Icon", width=16, anchor="w", bg=COLORS["panel"],
                 fg=COLORS["text"], font=("Helvetica", 10)).pack(side="left")
        icon_path_var = tk.StringVar()
        tk.Entry(ir, textvariable=icon_path_var, bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))

        def choose_icon():
            path = filedialog.askopenfilename(
                title="Select Server Image (64×64 PNG recommended)",
                filetypes=[("PNG Image", "*.png"), ("All files", "*.*")])
            if path:
                icon_path_var.set(path)

        self._btn(ir, "Browse", choose_icon, color=COLORS["accent2"], padx=8).pack(side="left")
        tk.Label(form, text="Tip: server-icon.png should be a 64×64 PNG.",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(anchor="w", pady=(2, 10))

        def save_changes():
            try:
                ram_val = int(var_ram.get().strip())
            except ValueError:
                messagebox.showerror("Error", "RAM must be a valid integer.", parent=win)
                return
            info["mc_version"] = var_version.get().strip()
            info["ram"]        = ram_val
            write_server_property(server_dir, "motd",        var_motd.get())
            write_server_property(server_dir, "max-players", var_players.get())

            icon_src = icon_path_var.get().strip()
            if icon_src and os.path.exists(icon_src):
                dest_icon = Path(server_dir) / "server-icon.png"
                try:
                    shutil.copy2(icon_src, dest_icon)
                    fix_icon(server_dir)
                except Exception as ex:
                    messagebox.showwarning("Warning",
                        f"Could not copy server icon: {ex}", parent=win)

            save_config(self.config)
            self._refresh_server_list()
            win.destroy()
            messagebox.showinfo("Success", f"Server '{name}' updated successfully!")

        btn_row = tk.Frame(win, bg=COLORS["bg"])
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        self._btn(btn_row, "Save Changes", save_changes,
                  padx=16, pady=6, font=("Helvetica", 10, "bold")).pack(side="right")
        self._btn(btn_row, "Cancel", win.destroy,
                  color=COLORS["card"], fg=COLORS["text"], padx=14, pady=6
                  ).pack(side="right", padx=(0, 8))

    # ── New Server page ───────────────────────────────────────────────────────────

    def _build_new_server_page(self):
        page = self.pages["new_server"]

        tk.Label(page, text="New Server", font=("Helvetica", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(page,
                 text="Auto-installs server software for Vanilla, Paper, Fabric, and NeoForge.",
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 10)).pack(anchor="w", padx=24, pady=(0, 12))
        tk.Frame(page, bg=COLORS["border"], height=1).pack(fill="x", padx=24)

        canvas = tk.Canvas(page, bg=COLORS["bg"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        form_outer = tk.Frame(canvas, bg=COLORS["bg"])
        canvas.create_window((0, 0), window=form_outer, anchor="nw")
        form_outer.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        form = tk.Frame(form_outer, bg=COLORS["panel"], padx=28, pady=20)
        form.pack(fill="x", padx=24, pady=16)

        def field(label, default="", hint=""):
            r = tk.Frame(form, bg=COLORS["panel"])
            r.pack(fill="x", pady=7)
            tk.Label(r, text=label, width=20, anchor="w",
                     bg=COLORS["panel"], fg=COLORS["text"],
                     font=("Helvetica", 10)).pack(side="left")
            var = tk.StringVar(value=default)
            e = tk.Entry(r, textvariable=var, bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                         highlightthickness=1, highlightbackground=COLORS["border"])
            e.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
            if hint:
                tk.Label(r, text=hint, bg=COLORS["panel"], fg=COLORS["subtext"],
                         font=("Helvetica", 8)).pack(side="left")
            return var

        self.new_name    = field("Server Name",        "My Server")
        self.new_version = field("Minecraft Version",  "1.21.1", "(e.g. 1.21.1)")
        self.new_ram     = field("RAM (MB)",            "2048",   "e.g. 2048")

        lr = tk.Frame(form, bg=COLORS["panel"])
        lr.pack(fill="x", pady=7)
        tk.Label(lr, text="Server Type", width=20, anchor="w",
                 bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 10)).pack(side="left")
        self.new_loader = tk.StringVar(value="Paper")
        loader_menu = ttk.Combobox(lr, textvariable=self.new_loader,
                                   values=list(LOADER_INFO.keys()),
                                   state="readonly", width=22,
                                   font=("Helvetica", 10))
        loader_menu.pack(side="left")
        loader_menu.bind("<<ComboboxSelected>>", self._on_loader_change)

        self.install_badge = tk.Label(lr, text="⚡ Auto-install",
                 bg=COLORS["success"], fg=COLORS["bg"],
                 font=("Helvetica", 8, "bold"), padx=8, pady=2)
        self.install_badge.pack(side="left", padx=10)

        self.loader_desc = tk.Label(form, text=LOADER_INFO["Paper"]["description"],
                                    bg=COLORS["panel"], fg=COLORS["warning"],
                                    font=("Helvetica", 9), wraplength=640, justify="left")
        self.loader_desc.pack(anchor="w", pady=(0, 4))

        # JAR section (shown for manual / Forge / Bukkit)
        self.jar_section = tk.Frame(form, bg=COLORS["panel"])
        self.jar_section.pack(fill="x")

        jr = tk.Frame(self.jar_section, bg=COLORS["panel"])
        jr.pack(fill="x", pady=6)
        tk.Label(jr, text="Server JAR", width=20, anchor="w",
                 bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 10)).pack(side="left")
        self.new_jar = tk.StringVar()
        tk.Entry(jr, textvariable=self.new_jar, bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self._btn(jr, "Browse", self._browse_jar,
                  color=COLORS["accent2"], padx=10).pack(side="left")

        self.jar_note = tk.Label(self.jar_section, text="", bg=COLORS["panel"],
                                 fg=COLORS["subtext"], font=("Helvetica", 8),
                                 wraplength=640, justify="left")
        self.jar_note.pack(anchor="w")

        # Bukkit BuildTools section
        self.bukkit_section = tk.Frame(form, bg=COLORS["panel"])
        self.bukkit_section.pack(fill="x")
        self._btn(self.bukkit_section, "⚡  Auto Setup (BuildTools)", self._auto_bukkit,
                  color=COLORS["warning"], fg=COLORS["bg"], padx=14, pady=6,
                  font=("Helvetica", 10)).pack(anchor="w", pady=(4, 0))
        tk.Label(self.bukkit_section,
                 text="Runs BuildTools to compile CraftBukkit — requires Java & Git.",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(anchor="w")

        tk.Label(form,
                 text="✓  eula.txt accepted automatically (Mojang EULA required to run a server).",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(anchor="w", pady=(12, 0))

        self._on_loader_change()

        self._btn(form_outer, "  Create Server  ", self._create_server,
                  padx=24, pady=10,
                  font=("Helvetica", 11, "bold")).pack(anchor="w", padx=24, pady=(0, 24))

    def _on_loader_change(self, *_):
        loader = self.new_loader.get()
        info   = LOADER_INFO.get(loader, {})
        self.loader_desc.config(text=info.get("description", ""))
        auto = info.get("auto_install", False)

        if auto is True:
            self.install_badge.config(text="⚡ Auto-install", bg=COLORS["success"])
            self.jar_section.pack_forget()
            self.bukkit_section.pack_forget()
        elif auto == "buildtools":
            self.install_badge.config(text="⚙ BuildTools", bg=COLORS["warning"])
            self.jar_section.pack(fill="x")
            self.jar_note.config(text=info.get("note", ""))
            self.bukkit_section.pack(fill="x")
        else:
            self.install_badge.config(text="✋ Manual", bg=COLORS["subtext"])
            self.jar_section.pack(fill="x")
            self.jar_note.config(text=f"Expected: {info.get('jar_name','server.jar')}\n{info.get('note','')}")
            self.bukkit_section.pack_forget()

    def _browse_jar(self):
        path = filedialog.askopenfilename(
            filetypes=[("JAR / Scripts", "*.jar *.sh *.bat"), ("All files", "*.*")])
        if path:
            self.new_jar.set(path)

    def _auto_bukkit(self):
        name    = self.new_name.get().strip()
        version = self.new_version.get().strip()
        if not name:
            messagebox.showerror("Error", "Enter a server name first."); return
        if name in self.config["servers"]:
            messagebox.showerror("Error", f"A server named '{name}' already exists."); return
        try:
            ram_mb = int(self.new_ram.get().strip())
        except ValueError:
            messagebox.showerror("Error", "RAM must be a number."); return

        dir_name   = safe_name(name)
        server_dir = SERVERS_DIR / dir_name
        server_dir.mkdir(parents=True, exist_ok=True)
        java = self.config.get("java_path", default_java_path())

        dlg = ProgressDialog(self, f"Building Bukkit — {name}")

        def _run():
            try:
                jar = install_bukkit_buildtools(
                    version, server_dir, java,
                    progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                    log_cb=lambda m: self.after(0, lambda: dlg.append_log(m))
                )
                self.after(0, lambda: self._finish_create(name, version, "Bukkit", str(jar), ram_mb, dlg))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._install_error(dlg, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _create_server(self):
        name    = self.new_name.get().strip()
        version = self.new_version.get().strip()
        loader  = self.new_loader.get()
        ram_str = self.new_ram.get().strip()
        info    = LOADER_INFO.get(loader, {})
        auto    = info.get("auto_install", False)

        if not name:
            messagebox.showerror("Error", "Server name is required."); return
        if name in self.config["servers"]:
            messagebox.showerror("Error", f"A server named '{name}' already exists."); return
        if not version:
            messagebox.showerror("Error", "Minecraft version is required."); return
        try:
            ram_mb = int(ram_str)
        except ValueError:
            messagebox.showerror("Error", "RAM must be a number (MB)."); return

        dir_name   = safe_name(name)
        server_dir = SERVERS_DIR / dir_name
        server_dir.mkdir(parents=True, exist_ok=True)
        java = self.config.get("java_path", default_java_path())

        if auto is True:
            dlg = ProgressDialog(self, f"Installing {loader} {version}")

            def _run():
                try:
                    if loader == "Vanilla":
                        jar = install_vanilla(version, server_dir,
                            progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                            log_cb=lambda m: self.after(0, lambda: dlg.append_log(m)))
                    elif loader == "Paper":
                        jar = install_paper(version, server_dir,
                            progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                            log_cb=lambda m: self.after(0, lambda: dlg.append_log(m)))
                    elif loader == "Fabric":
                        jar = install_fabric(version, server_dir, java,
                            progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                            log_cb=lambda m: self.after(0, lambda: dlg.append_log(m)))
                    elif loader == "NeoForge":
                        jar = install_neoforge(version, server_dir, java,
                            progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                            log_cb=lambda m: self.after(0, lambda: dlg.append_log(m)))
                    else:
                        raise RuntimeError(f"Unknown auto-install loader: {loader}")
                    self.after(0, lambda: self._finish_create(name, version, loader, jar, ram_mb, dlg))
                except Exception as e:
                    err_msg = str(e) if str(e).strip() else f"Unexpected error: {type(e).__name__}"
                    self.after(0, lambda msg=err_msg: self._install_error(dlg, msg))

            threading.Thread(target=_run, daemon=True).start()

        elif auto == "buildtools":
            jar = self.new_jar.get().strip()
            if jar and os.path.exists(jar):
                self._finish_create_sync(name, version, loader, jar, ram_mb)
            else:
                if messagebox.askyesno("BuildTools",
                        "No JAR selected. Run BuildTools auto-setup now?"):
                    self._auto_bukkit()
        else:
            jar = self.new_jar.get().strip()
            if not jar or not os.path.exists(jar):
                messagebox.showerror("Error",
                    "Select a valid server JAR.\n\n" + info.get("note", "")); return
            self._finish_create_sync(name, version, loader, jar, ram_mb)

    def _finish_create(self, name, version, loader, jar_src, ram_mb, dlg):
        try:
            dlg.finish("Install complete!")
            self._persist_server(name, version, loader, jar_src, ram_mb)
            dlg.close_after(1200)
            self.after(1500, self._refresh_server_list)
            self.after(1600, self._show_servers)
            self.status_var.set(f"Created: {name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _finish_create_sync(self, name, version, loader, jar_src, ram_mb):
        try:
            self._persist_server(name, version, loader, jar_src, ram_mb)
            messagebox.showinfo("Created",
                f"Server '{name}' created!\n\nGo to Servers to start it.")
            self._refresh_server_list()
            self._show_servers()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _persist_server(self, name, version, loader, jar_src, ram_mb):
        server_dir = SERVERS_DIR / safe_name(name)
        server_dir.mkdir(parents=True, exist_ok=True)

        jar_path = Path(jar_src)
        jar_dest = server_dir / jar_path.name

        # Only copy if the source is outside the server directory
        if jar_path.resolve() != jar_dest.resolve() and jar_path.exists():
            shutil.copy2(jar_src, jar_dest)
            # Make scripts executable on Unix
            if jar_dest.suffix in (".sh",) and SYSTEM != "Windows":
                os.chmod(jar_dest, 0o755)

        (server_dir / "eula.txt").write_text("eula=true\n")
        props = server_dir / "server.properties"
        if not props.exists():
            props.write_text(
                "server-port=25565\nmotd=A Nova Server\n"
                "max-players=20\nlevel-name=world\nonline-mode=true\n")

        self.config["servers"][name] = {
            "loader":     loader,
            "mc_version": version,
            "directory":  str(server_dir.resolve()),
            "jar":        str(jar_dest.resolve()),
            "ram":        ram_mb,
        }
        save_config(self.config)

    def _install_error(self, dlg, msg):
        dlg.append_log(f"\n[ERROR] {msg}\n")
        dlg.finish("Failed — see log above")
        messagebox.showerror("Install Failed", msg, parent=dlg)

    # ── Server control ────────────────────────────────────────────────────────────

    def _start_server(self, name, info):
        # Guard: don't start a second instance if one is already running
        existing = self.server_procs.get(name)
        if existing and existing.running:
            return
        java = self.config.get("java_path", default_java_path())
        proc = ServerProcess(
            name=name,
            directory=info["directory"],
            jar=info["jar"],
            java=java,
            ram_mb=info.get("ram", 2048),
            log_callback=lambda line: self._global_log(name, line),
            stop_callback=lambda: self.after(0, self._refresh_server_list),
        )
        if proc.start():
            self.server_procs[name] = proc
            self.status_var.set(f"Started: {name}")
            self.after(500, self._refresh_server_list)
        else:
            messagebox.showerror("Error",
                f"Could not start '{name}'.\n"
                "Check the Java path in Settings and that the server JAR exists.")

    def _stop_server(self, name):
        proc = self.server_procs.get(name)
        if proc:
            proc.stop()
            self.status_var.set(f"Stopping: {name}…")
            self.after(3500, self._refresh_server_list)

    def _delete_server(self, name):
        if not messagebox.askyesno("Delete Server",
                f"Remove '{name}' from the list?\n(Server files are kept on disk.)"):
            return
        self.config["servers"].pop(name, None)
        save_config(self.config)
        self._refresh_server_list()

    def _open_console(self, name, info):
        win = tk.Toplevel(self)
        win.title(f"Console — {name}")
        win.geometry("820x540")
        win.configure(bg=COLORS["bg"])

        header = tk.Frame(win, bg=COLORS["bg"])
        header.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(header, text=f"◈ {name}", font=("Helvetica", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(side="left")

        log_widget = scrolledtext.ScrolledText(
            win, bg="#0D0D14", fg="#A0F0B0", font=("Courier New", 10),
            insertbackground="#A0F0B0", bd=0, state="disabled")
        log_widget.pack(fill="both", expand=True, padx=10, pady=8)

        cmd_frame = tk.Frame(win, bg=COLORS["panel"])
        cmd_frame.pack(fill="x", padx=10, pady=(0, 10))
        cmd_var   = tk.StringVar()
        cmd_entry = tk.Entry(cmd_frame, textvariable=cmd_var,
                             bg=COLORS["card"], fg=COLORS["text"],
                             insertbackground=COLORS["text"],
                             font=("Courier New", 10), bd=0,
                             highlightthickness=1, highlightbackground=COLORS["border"])
        cmd_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        cmd_entry.focus()

        def send(*_):
            cmd = cmd_var.get().strip()
            if cmd:
                proc = self.server_procs.get(name)
                if proc:
                    proc.send_command(cmd)
                cmd_var.set("")

        cmd_entry.bind("<Return>", send)
        self._btn(cmd_frame, "Send", send, padx=14, pady=6).pack(side="left")

        proc = self.server_procs.get(name)
        if proc:
            # Unwrap existing wrappers to avoid callback chain buildup
            base_cb = proc.log_callback
            while hasattr(base_cb, '_is_dash_wrapper'):
                base_cb = base_cb._wrapped_orig

            def new_cb(line, _base=base_cb):
                _base(line)
                try:
                    if win.winfo_exists():
                        win.after(0, lambda l=line: (
                            log_widget.config(state="normal"),
                            log_widget.insert("end", l),
                            log_widget.see("end"),
                            log_widget.config(state="disabled"),
                        ))
                except Exception:
                    pass
            new_cb._is_dash_wrapper = True
            new_cb._wrapped_orig    = base_cb
            proc.log_callback = new_cb

            def _on_close():
                current = self.server_procs.get(name)
                if current and current.log_callback is new_cb:
                    current.log_callback = base_cb
            win.protocol("WM_DELETE_WINDOW", lambda: (_on_close(), win.destroy()))
            win.bind("<Destroy>", lambda e: _on_close() if e.widget is win else None)

    def _global_log(self, name, line):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}][{name}] {line}", end="")
        self._parse_player_event(name, line)

    def _parse_player_event(self, server_name, line):
        """Parse Minecraft server log lines to track online players."""
        if server_name not in self._player_lists:
            self._player_lists[server_name] = []
        if server_name not in self._total_joins:
            self._total_joins[server_name] = 0
        pl = self._player_lists[server_name]

        # Join: "UUID joined the game" or "player logged in"
        m = re.search(r": (\w+) joined the game", line)
        if not m:
            m = re.search(r"(\w+)\[.*\] logged in", line)
        if m:
            player = m.group(1)
            if player not in pl:
                pl.append(player)
            self._total_joins[server_name] += 1
            return

        # Leave: "UUID left the game"
        m = re.search(r": (\w+) left the game", line)
        if m:
            player = m.group(1)
            if player in pl:
                pl.remove(player)
            return

        # Response to /list command: "There are X of a max of Y players online: a, b, c"
        m = re.search(r"players online: (.*)", line)
        if m:
            names_str = m.group(1).strip()
            if names_str:
                self._player_lists[server_name] = [
                    n.strip() for n in names_str.split(",") if n.strip()
                ]
            else:
                self._player_lists[server_name] = []

    def _get_server_state(self, name: str) -> dict:
        """Build the state dict broadcast to admin clients and shown in dashboard."""
        info       = self.config.get("servers", {}).get(name, {})
        is_running = name in self.server_procs and self.server_procs[name].running
        players    = self._player_lists.get(name, [])
        total      = self._total_joins.get(name, 0)
        playit_url = (self.playit.tunnel_url or "")  if self.playit else ""
        return {
            "name":        name,
            "loader":      info.get("loader", "?"),
            "mc_version":  info.get("mc_version", "?"),
            "ram":         info.get("ram", 0),
            "running":     is_running,
            "players":     players,
            "player_count":len(players),
            "total_joins": total,
            "directory":   info.get("directory", ""),
            "playit_url":  playit_url,
        }

    def _broadcast_admin_state(self):
        """Periodically push state to any connected admin clients."""
        for name, adm in list(self.admin_servers.items()):
            state = self._get_server_state(name)
            adm.update_state(state)
            proc = self.server_procs.get(name)
            if proc:
                # Use the proc object as the key so we never double-wrap.
                # _adm_hooked_procs is a set of id()s of already-wrapped procs.
                if not hasattr(adm, '_hooked_proc_ids'):
                    adm._hooked_proc_ids = set()
                pid = id(proc)
                if pid not in adm._hooked_proc_ids:
                    orig_log = proc.log_callback
                    def _web_log(line, _adm=adm, _orig=orig_log):
                        _orig(line)
                        _adm.push_log_line(line)
                    proc.log_callback = _web_log
                    adm._hooked_proc_ids.add(pid)
        self.after(2000, self._broadcast_admin_state)

    # ── Playit page ───────────────────────────────────────────────────────────────

    def _build_playit_page(self):
        page = self.pages["playit"]

        tk.Label(page, text="Playit.gg Tunnel", font=("Helvetica", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(page,
            text="Expose your server to the internet without port-forwarding. Auto-download included.",
            bg=COLORS["bg"], fg=COLORS["subtext"],
            font=("Helvetica", 10)).pack(anchor="w", padx=24, pady=(0, 10))
        tk.Frame(page, bg=COLORS["border"], height=1).pack(fill="x", padx=24)

        card = tk.Frame(page, bg=COLORS["panel"], padx=24, pady=18)
        card.pack(fill="x", padx=24, pady=14)

        pr = tk.Frame(card, bg=COLORS["panel"])
        pr.pack(fill="x", pady=6)
        tk.Label(pr, text="Playit binary:", width=18, anchor="w",
                 bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Helvetica", 10)).pack(side="left")
        self.playit_path_var = tk.StringVar(value=self.config.get("playit_path", ""))
        tk.Entry(pr, textvariable=self.playit_path_var, bg=COLORS["card"],
                 fg=COLORS["text"], insertbackground=COLORS["text"], bd=0,
                 highlightthickness=1, highlightbackground=COLORS["border"],
                 font=("Helvetica", 10)
                 ).pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self._btn(pr, "Browse", self._browse_playit,
                  color=COLORS["accent2"], padx=10).pack(side="left", padx=(0, 6))
        self._btn(pr, "⚡  Auto-Download", self._auto_download_playit,
                  color=COLORS["accent"], padx=10).pack(side="left")

        as_row = tk.Frame(card, bg=COLORS["panel"])
        as_row.pack(fill="x", pady=6)
        self.playit_auto_var = tk.BooleanVar(value=self.config.get("playit_auto_start", False))
        tk.Checkbutton(as_row, text="Auto-start Playit when Nova Servers opens",
                       variable=self.playit_auto_var,
                       bg=COLORS["panel"], fg=COLORS["text"],
                       selectcolor=COLORS["card"],
                       activebackground=COLORS["panel"],
                       command=self._save_playit_settings,
                       font=("Helvetica", 10)).pack(side="left")

        br = tk.Frame(card, bg=COLORS["panel"])
        br.pack(fill="x", pady=10)
        self._btn(br, "▶  Start Playit", self._start_playit,
                  color=COLORS["success"], fg=COLORS["bg"],
                  padx=16, pady=7,
                  font=("Helvetica", 10, "bold")).pack(side="left", padx=(0, 8))
        self._btn(br, "■  Stop Playit", self._stop_playit,
                  color=COLORS["danger"],
                  padx=16, pady=7,
                  font=("Helvetica", 10)).pack(side="left")

        self.playit_log = scrolledtext.ScrolledText(
            page, bg="#0D0D14", fg="#00FFAA", font=("Courier New", 10),
            insertbackground=COLORS["text"], bd=0, height=14, state="disabled")
        self.playit_log.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        # Show the correct download URL for this OS
        pinfo = PLAYIT_DOWNLOAD.get(SYSTEM, PLAYIT_DOWNLOAD["Linux"])
        tk.Label(page, text=f"Download: {pinfo['url']}",
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(pady=(0, 8))

    def _browse_playit(self):
        path = filedialog.askopenfilename(title="Select Playit binary")
        if path:
            self.playit_path_var.set(path)
            self._save_playit_settings()

    def _auto_download_playit(self):
        # Save next to the script so the absolute path is always findable
        dest_dir = Path(sys.argv[0]).resolve().parent
        dlg = ProgressDialog(self, f"Downloading Playit Agent ({SYSTEM})")

        def _run():
            try:
                path = download_playit(
                    dest_dir,
                    progress_cb=lambda d, t: self.after(0, lambda: dlg.set_progress(d, t)),
                    log_cb=lambda m: self.after(0, lambda: dlg.append_log(m))
                )
                self.after(0, lambda: self._on_playit_downloaded(path, dlg))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._install_error(dlg, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _on_playit_downloaded(self, path, dlg):
        dlg.finish("Downloaded!")
        dlg.close_after(1200)
        self.playit_path_var.set(path)
        self._save_playit_settings()
        messagebox.showinfo("Playit Downloaded",
            f"Playit saved to:\n{path}\n\nClick 'Start Playit' to launch it.")

    def _save_playit_settings(self):
        self.config["playit_path"]       = self.playit_path_var.get().strip()
        self.config["playit_auto_start"] = self.playit_auto_var.get()
        save_config(self.config)

    def _start_playit(self):
        self._save_playit_settings()
        path = self.config.get("playit_path", "")
        if not path:
            messagebox.showerror("Error",
                "Set the Playit binary path or use Auto-Download first.")
            return
        if self.playit and self.playit.running:
            messagebox.showinfo("Info", "Playit is already running.")
            return
        self.playit = PlayitProcess(path, self._append_playit_log)
        if self.playit.start():
            self.status_var.set("Playit running")
            self.playit_indicator.config(text="● Playit on", fg=COLORS["success"])

    def _stop_playit(self):
        if self.playit:
            self.playit.stop()
            self.playit = None
            self.status_var.set("Playit stopped")
            self.playit_indicator.config(text="● Playit off", fg=COLORS["subtext"])

    def _auto_start_playit(self):
        self._start_playit()

    def _append_playit_log(self, line):
        if hasattr(self, "playit_log") and self.playit_log.winfo_exists():
            self.playit_log.config(state="normal")
            self.playit_log.insert("end", line)
            self.playit_log.see("end")
            self.playit_log.config(state="disabled")

    # ── Dashboard (View) Window ──────────────────────────────────────────────────────

    def _open_dashboard(self, name, info, remote_client: "AdminClient | None" = None):
        """
        Full-featured server dashboard.
        - local=True:  reads from self (host)
        - remote_client: an already-connected AdminClient (remote admin view)
        """
        is_remote = remote_client is not None

        win = tk.Toplevel(self)
        win.title(f"{'🌐 Remote' if is_remote else '⊞'} Dashboard — {name}")
        win.geometry("900x660")
        win.configure(bg=COLORS["bg"])
        win.minsize(760, 560)

        # ── Header ──────────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=COLORS["panel"], padx=18, pady=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text=f"⊞  {name}", font=("Helvetica", 14, "bold"),
                 bg=COLORS["panel"], fg=COLORS["accent"]).pack(side="left")

        self.dash_status_var = tk.StringVar(value="●  Loading…")
        tk.Label(hdr, textvariable=self.dash_status_var,
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 9)).pack(side="left", padx=16)

        # Control buttons (right side of header)
        ctrl = tk.Frame(hdr, bg=COLORS["panel"])
        ctrl.pack(side="right")

        def do_start():
            if is_remote:
                remote_client.send_cmd("start")
            else:
                self._start_server(name, info)
                self._refresh_server_list()

        def do_stop():
            if is_remote:
                remote_client.send_cmd("stop")
            else:
                self._stop_server(name)

        def do_restart():
            if is_remote:
                remote_client.send_cmd("restart")
            else:
                proc = self.server_procs.get(name)
                if proc:
                    proc.stop()
                self.after(4000, lambda: self._start_server(name, info))

        self._btn(ctrl, "▶ Start",   do_start,
                  color=COLORS["success"], fg=COLORS["bg"],
                  padx=10, pady=4, font=("Helvetica", 9)).pack(side="left", padx=3)
        self._btn(ctrl, "↺ Restart", do_restart,
                  color=COLORS["warning"], fg=COLORS["bg"],
                  padx=10, pady=4, font=("Helvetica", 9)).pack(side="left", padx=3)
        self._btn(ctrl, "■ Stop",    do_stop,
                  color=COLORS["danger"],
                  padx=10, pady=4, font=("Helvetica", 9)).pack(side="left", padx=3)

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill="x")

        # ── Two-column body ───────────────────────────────────────────────────
        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)

        # ── LEFT: stats + player list + plugin upload + world transfer ────────
        # Left panel — scrollable canvas so all cards are reachable regardless
        # of window height (UPnP / Cloudflare cards can push below the fold)
        left_outer = tk.Frame(body, bg=COLORS["bg"], width=310)
        left_outer.pack(side="left", fill="y", padx=(16, 8), pady=12)
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, bg=COLORS["bg"],
                                highlightthickness=0, width=294)
        left_sb = ttk.Scrollbar(left_outer, orient="vertical",
                                command=left_canvas.yview)
        left = tk.Frame(left_canvas, bg=COLORS["bg"])
        left.bind("<Configure>",
            lambda e: left_canvas.configure(
                scrollregion=left_canvas.bbox("all")))
        left_canvas.create_window((0, 0), window=left, anchor="nw")
        left_canvas.configure(yscrollcommand=left_sb.set)
        left_sb.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        def _left_scroll(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind("<MouseWheel>", _left_scroll)
        left.bind("<MouseWheel>", _left_scroll)

        # Stats card
        stats_card = tk.Frame(left, bg=COLORS["card"],
                              highlightbackground=COLORS["border"], highlightthickness=1)
        stats_card.pack(fill="x", pady=(0, 10))
        tk.Label(stats_card, text="Server Stats", font=("Helvetica", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"],
                 padx=12, pady=6).pack(anchor="w")
        tk.Frame(stats_card, bg=COLORS["border"], height=1).pack(fill="x")

        self.dash_stat_vars = {}
        for key, label in [
            ("running",      "Status"),
            ("player_count", "Online Now"),
            ("total_joins",  "All-Time Joins"),
            ("mc_version",   "MC Version"),
            ("loader",       "Type"),
            ("ram",          "RAM"),
        ]:
            row = tk.Frame(stats_card, bg=COLORS["card"])
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label + ":", width=14, anchor="w",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 9)).pack(side="left")
            var = tk.StringVar(value="—")
            tk.Label(row, textvariable=var, anchor="w",
                     bg=COLORS["card"], fg=COLORS["text"],
                     font=("Helvetica", 9, "bold")).pack(side="left")
            self.dash_stat_vars[key] = var
        tk.Frame(stats_card, bg=COLORS["card"], height=6).pack()  # bottom padding

        # Player list
        pl_card = tk.Frame(left, bg=COLORS["card"],
                           highlightbackground=COLORS["border"], highlightthickness=1)
        pl_card.pack(fill="x", pady=(0, 10))
        pl_hdr = tk.Frame(pl_card, bg=COLORS["card"])
        pl_hdr.pack(fill="x", padx=12, pady=6)
        tk.Label(pl_hdr, text="Online Players", font=("Helvetica", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"]).pack(side="left")

        def refresh_list():
            if not is_remote:
                proc = self.server_procs.get(name)
                if proc and proc.running:
                    proc.send_command("list")

        self._btn(pl_hdr, "⟳", refresh_list,
                  color=COLORS["panel"], fg=COLORS["subtext"],
                  padx=6, pady=2, font=("Helvetica", 8)).pack(side="right")
        tk.Frame(pl_card, bg=COLORS["border"], height=1).pack(fill="x")
        self.dash_player_list = tk.Listbox(
            pl_card, bg=COLORS["card"], fg=COLORS["text"],
            font=("Helvetica", 10), bd=0, selectbackground=COLORS["accent"],
            height=7, activestyle="none")
        self.dash_player_list.pack(fill="x", padx=8, pady=6)
        tk.Frame(pl_card, bg=COLORS["card"], height=2).pack()

        # Plugin upload (host-only for now, remote sends cmd)
        plug_card = tk.Frame(left, bg=COLORS["card"],
                             highlightbackground=COLORS["border"], highlightthickness=1)
        plug_card.pack(fill="x", pady=(0, 10))
        tk.Label(plug_card, text="Add Plugin", font=("Helvetica", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"],
                 padx=12, pady=6).pack(anchor="w")
        tk.Frame(plug_card, bg=COLORS["border"], height=1).pack(fill="x")
        plug_body = tk.Frame(plug_card, bg=COLORS["card"], padx=12, pady=8)
        plug_body.pack(fill="x")
        plug_var = tk.StringVar()
        tk.Entry(plug_body, textvariable=plug_var,
                 bg=COLORS["panel"], fg=COLORS["text"],
                 insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(fill="x", ipady=5, pady=(0, 6))

        def browse_plugin():
            path = filedialog.askopenfilename(
                title="Select Plugin JAR",
                filetypes=[("Plugin JAR", "*.jar"), ("All files", "*.*")])
            if path:
                plug_var.set(path)

        def install_plugin():
            src_path = plug_var.get().strip()
            if not src_path or not os.path.exists(src_path):
                messagebox.showerror("Error", "Select a valid plugin JAR.", parent=win)
                return
            server_dir = info.get("directory", "")
            if not server_dir:
                messagebox.showerror("Error", "Server directory unknown.", parent=win)
                return
            plugins_dir = Path(server_dir) / "plugins"
            plugins_dir.mkdir(exist_ok=True)
            dest = plugins_dir / Path(src_path).name
            shutil.copy2(src_path, dest)
            messagebox.showinfo("Plugin Added",
                f"{Path(src_path).name} copied to plugins/\n"
                "Restart the server or run /reload confirm to activate.",
                parent=win)

        pb = tk.Frame(plug_body, bg=COLORS["card"])
        pb.pack(fill="x")
        self._btn(pb, "Browse…", browse_plugin,
                  color=COLORS["accent2"], padx=8, pady=4,
                  font=("Helvetica", 9)).pack(side="left", padx=(0, 6))
        self._btn(pb, "Install Plugin", install_plugin,
                  color=COLORS["accent"], padx=8, pady=4,
                  font=("Helvetica", 9)).pack(side="left")

        # World transfer card
        world_card = tk.Frame(left, bg=COLORS["card"],
                              highlightbackground=COLORS["border"], highlightthickness=1)
        world_card.pack(fill="x")
        tk.Label(world_card, text="World Transfer (P2P)", font=("Helvetica", 10, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"],
                 padx=12, pady=6).pack(anchor="w")
        tk.Frame(world_card, bg=COLORS["border"], height=1).pack(fill="x")
        wb = tk.Frame(world_card, bg=COLORS["card"], padx=12, pady=8)
        wb.pack(fill="x")
        tk.Label(wb, text="World folder name:", bg=COLORS["card"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(anchor="w")
        world_name_var = tk.StringVar(value="world")
        tk.Entry(wb, textvariable=world_name_var, bg=COLORS["panel"],
                 fg=COLORS["text"], insertbackground=COLORS["text"],
                 bd=0, font=("Helvetica", 9),
                 highlightthickness=1, highlightbackground=COLORS["border"]
                 ).pack(fill="x", ipady=4, pady=(2, 6))

        host_ip = tk.StringVar(value="")
        if is_remote:
            tk.Label(wb, text="Host IP (for download):", bg=COLORS["card"],
                     fg=COLORS["subtext"], font=("Helvetica", 8)).pack(anchor="w")
            tk.Entry(wb, textvariable=host_ip, bg=COLORS["panel"],
                     fg=COLORS["text"], insertbackground=COLORS["text"],
                     bd=0, font=("Helvetica", 9),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(fill="x", ipady=4, pady=(2, 6))

        def upload_world():
            """Host: zip + serve world to a waiting receiver."""
            server_dir  = info.get("directory", "")
            world_dir   = str(Path(server_dir) / world_name_var.get())
            dlg         = ProgressDialog(win, "Sending World…")
            sender      = WorldSender(
                world_dir,
                log_cb=lambda m: win.after(0, lambda: dlg.append_log(m)),
                progress_cb=lambda d, t: win.after(0, lambda: dlg.set_progress(d, t)),
                done_cb=lambda ok, err: win.after(0,
                    lambda: dlg.finish("Sent ✓" if ok else f"Failed: {err}"))
            )
            sender.start()

        def download_world():
            """Admin client or local: receive world from host."""
            if is_remote:
                h = host_ip.get().strip()
            else:
                try:
                    h = socket.gethostbyname(socket.gethostname())
                except Exception:
                    h = "127.0.0.1"
            server_dir = info.get("directory", "")
            world_dir  = str(Path(server_dir) / world_name_var.get())
            dlg        = ProgressDialog(win, "Receiving World…")
            receiver   = WorldReceiver(
                h, world_dir,
                log_cb=lambda m: win.after(0, lambda: dlg.append_log(m)),
                progress_cb=lambda d, t: win.after(0, lambda: dlg.set_progress(d, t)),
                done_cb=lambda ok, err: win.after(0,
                    lambda: dlg.finish("Received ✓" if ok else f"Failed: {err}"))
            )
            receiver.start()

        wbtns = tk.Frame(wb, bg=COLORS["card"])
        wbtns.pack(fill="x")
        self._btn(wbtns, "⬆ Upload (Send)",   upload_world,
                  color=COLORS["accent2"], padx=8, pady=4,
                  font=("Helvetica", 9)).pack(side="left", padx=(0, 6))
        self._btn(wbtns, "⬇ Download (Get)", download_world,
                  color=COLORS["panel"], fg=COLORS["text"], padx=8, pady=4,
                  font=("Helvetica", 9),
                  highlightbackground=COLORS["border"], highlightthickness=1).pack(side="left")

        # Admin Tools card (host mode)
        if not is_remote:
            adm_card = tk.Frame(left, bg=COLORS["card"],
                                highlightbackground=COLORS["border"], highlightthickness=1)
            adm_card.pack(fill="x", pady=(10, 0))
            tk.Label(adm_card, text="Admin Tools (Host)", font=("Helvetica", 10, "bold"),
                     bg=COLORS["card"], fg=COLORS["text"],
                     padx=12, pady=6).pack(anchor="w")
            tk.Frame(adm_card, bg=COLORS["border"], height=1).pack(fill="x")
            ab = tk.Frame(adm_card, bg=COLORS["card"], padx=12, pady=8)
            ab.pack(fill="x")

            tk.Label(ab, text="API Password:", bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 8)).pack(anchor="w")
            adm_pw_var = tk.StringVar(
                value=self.config.get("servers", {}).get(name, {}).get("admin_pw", ""))
            tk.Entry(ab, textvariable=adm_pw_var, show="●",
                     bg=COLORS["panel"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(fill="x", ipady=4, pady=(2, 6))

            tk.Label(ab, text="Web UI Password (browser login):",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 8)).pack(anchor="w")
            adm_web_pw_var = tk.StringVar(
                value=self.config.get("servers", {}).get(name, {}).get("admin_web_pw", ""))
            tk.Entry(ab, textvariable=adm_web_pw_var, show="●",
                     bg=COLORS["panel"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(fill="x", ipady=4, pady=(2, 6))
            tk.Label(ab, text="Leave blank to use API Password for both.",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 7)).pack(anchor="w", pady=(0, 6))

            tk.Label(ab, text="Port:", bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 8)).pack(anchor="w")
            adm_port_var = tk.StringVar(
                value=str(self.config.get("servers", {}).get(name, {}).get(
                    "admin_port", ADMIN_PORT_DEFAULT)))
            tk.Entry(ab, textvariable=adm_port_var,
                     bg=COLORS["panel"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(fill="x", ipady=4, pady=(2, 6))

            adm_status_var = tk.StringVar(
                value="● Running" if name in self.admin_servers else "○ Stopped")
            adm_status_label = tk.Label(ab, textvariable=adm_status_var,
                     bg=COLORS["card"],
                     fg=COLORS["success"] if name in self.admin_servers else COLORS["subtext"],
                     font=("Helvetica", 8))
            adm_status_label.pack(anchor="w", pady=(0, 6))

            def _set_adm_status(text, running):
                adm_status_var.set(text)
                adm_status_label.config(
                    fg=COLORS["success"] if running else COLORS["subtext"])

            def start_admin_srv():
                pw   = adm_pw_var.get().strip()
                port_s = adm_port_var.get().strip()
                if not pw:
                    messagebox.showerror("Error", "Set a password first.", parent=win)
                    return
                try:
                    port = int(port_s)
                except ValueError:
                    messagebox.showerror("Error", "Port must be a number.", parent=win)
                    return
                if name in self.admin_servers:
                    messagebox.showinfo("Info", "Admin server already running.", parent=win)
                    return
                web_pw  = adm_web_pw_var.get().strip()
                srv_dir = self.config.get("servers", {}).get(name, {}).get("directory", "")
                adm = AdminServer(pw, port, web_password=web_pw, server_dir=srv_dir)
                adm._cmd_callback = lambda cmd, args: self._handle_remote_cmd(name, cmd, args)
                if adm.start():
                    self.admin_servers[name] = adm
                    # Save pw + port to config
                    self.config["servers"][name]["admin_pw"]     = pw
                    self.config["servers"][name]["admin_web_pw"] = web_pw
                    self.config["servers"][name]["admin_port"]   = port
                    save_config(self.config)
                    _set_adm_status("● Running · visit /dashboard in browser", True)
                    # Push initial state immediately so file browser has the
                    # server directory before the first 2-second broadcast tick
                    adm.update_state(self._get_server_state(name))

                    # Show connection info (UPnP only if enabled in Settings)
                    def _try_upnp():
                        method, addr = try_upnp_then_fallback(port, "NovaServers Admin")
                        if method == "upnp":
                            note = (f"✓ UPnP opened port automatically!\n"
                                    f"Co-admins can connect to:\n\n"
                                    f"  Host: {addr.split(':')[0]}\n"
                                    f"  Port: {port}\n\n"
                                    f"Or use the Cloudflare Tunnel below for internet access.")
                        else:
                            note = (f"Admin Server running on port {port}.\n\n"
                                    f"Local network: {addr.split(':')[0]}:{port}\n\n"
                                    f"For internet access:\n"
                                    f"  • Use the ☁ Cloudflare Tunnel below  (easiest)\n"
                                    f"  • Or enable UPnP in Settings\n"
                                    f"  • Or forward port {port} on your router")
                        win.after(0, lambda: messagebox.showinfo(
                            "Admin Server Started", note, parent=win))

                    threading.Thread(target=_try_upnp, daemon=True).start()
                else:
                    messagebox.showerror("Error", "Could not start admin server.", parent=win)

            def stop_admin_srv():
                adm = self.admin_servers.pop(name, None)
                if adm:
                    adm.stop()
                _set_adm_status("○ Stopped", False)

            abtns = tk.Frame(ab, bg=COLORS["card"])
            abtns.pack(fill="x")
            self._btn(abtns, "▶ Start Hosting", start_admin_srv,
                      color=COLORS["success"], fg=COLORS["bg"],
                      padx=8, pady=4, font=("Helvetica", 9)).pack(side="left", padx=(0, 6))
            self._btn(abtns, "■ Stop Hosting",  stop_admin_srv,
                      color=COLORS["danger"], padx=8, pady=4,
                      font=("Helvetica", 9)).pack(side="left")

        # ── Cloudflare Tunnel card (host-only) ─────────────────────────────────
        if not is_remote:
            cf_card = tk.Frame(left, bg=COLORS["card"],
                               highlightbackground=COLORS["border"], highlightthickness=1)
            cf_card.pack(fill="x", pady=(10, 0))

            cf_hdr = tk.Frame(cf_card, bg=COLORS["card"])
            cf_hdr.pack(fill="x", padx=12, pady=6)
            tk.Label(cf_hdr, text="☁  Cloudflare Tunnel",
                     font=("Helvetica", 10, "bold"),
                     bg=COLORS["card"], fg=COLORS["text"]).pack(side="left")
            tk.Label(cf_hdr, text="No port forwarding · Free · Instant",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 7)).pack(side="left", padx=8)

            tk.Frame(cf_card, bg=COLORS["border"], height=1).pack(fill="x")
            cf_body = tk.Frame(cf_card, bg=COLORS["card"], padx=12, pady=8)
            cf_body.pack(fill="x")

            tk.Label(cf_body,
                     text="Tunnel port (Admin server port shown above):",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 8)).pack(anchor="w")
            cf_port_var = tk.StringVar(value=str(
                self.config.get("servers", {}).get(name, {}).get(
                    "admin_port", ADMIN_PORT_DEFAULT)))
            tk.Entry(cf_body, textvariable=cf_port_var, width=8,
                     bg=COLORS["panel"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 9),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(anchor="w", ipady=4, pady=(2, 6))

            cf_url_var    = tk.StringVar(value="")
            cf_status_var = tk.StringVar(value="○ Not running")

            cf_url_label = tk.Label(cf_body, textvariable=cf_url_var,
                                    bg=COLORS["card"], fg=COLORS["success"],
                                    font=("Helvetica", 8, "bold"),
                                    wraplength=240, justify="left", cursor="hand2")
            cf_url_label.pack(anchor="w")

            tk.Label(cf_body, textvariable=cf_status_var,
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 8)).pack(anchor="w", pady=(2, 6))

            # Click URL to copy
            def _copy_cf_url(e=None):
                url = cf_url_var.get()
                if url:
                    win.clipboard_clear()
                    win.clipboard_append(url)
                    cf_status_var.set("✓ URL copied to clipboard!")
            cf_url_label.bind("<Button-1>", _copy_cf_url)

            cf_binary_var = tk.StringVar(
                value=self.config.get("cloudflared_path", ""))

            # Binary path row
            cf_bin_row = tk.Frame(cf_body, bg=COLORS["card"])
            cf_bin_row.pack(fill="x", pady=(0, 6))
            tk.Entry(cf_bin_row, textvariable=cf_binary_var,
                     bg=COLORS["panel"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], bd=0, font=("Helvetica", 8),
                     highlightthickness=1, highlightbackground=COLORS["border"]
                     ).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

            def browse_cloudflared():
                p = filedialog.askopenfilename(title="Select cloudflared binary")
                if p:
                    cf_binary_var.set(p)
                    self.config["cloudflared_path"] = p
                    save_config(self.config)
            self._btn(cf_bin_row, "Browse", browse_cloudflared,
                      color=COLORS["accent2"], padx=6, pady=3,
                      font=("Helvetica", 8)).pack(side="left")

            cf_btns = tk.Frame(cf_body, bg=COLORS["card"])
            cf_btns.pack(fill="x")

            def auto_download_cf():
                binary = cf_binary_var.get().strip()
                if binary and os.path.exists(binary):
                    messagebox.showinfo("cloudflared",
                        "cloudflared is already downloaded.", parent=win)
                    return
                dest_dir = Path(sys.argv[0]).resolve().parent
                dlg = ProgressDialog(win, "Downloading cloudflared…")

                def _run():
                    try:
                        path = download_cloudflared(
                            str(dest_dir),
                            progress_cb=lambda d, t: win.after(
                                0, lambda: dlg.set_progress(d, t)),
                            log_cb=lambda m: win.after(
                                0, lambda: dlg.append_log(m))
                        )
                        self.config["cloudflared_path"] = path
                        save_config(self.config)
                        win.after(0, lambda: cf_binary_var.set(path))
                        win.after(0, lambda: dlg.finish("Downloaded ✓"))
                        win.after(0, lambda: dlg.close_after(1200))
                    except Exception as e:
                        win.after(0, lambda: dlg.finish(f"Failed: {e}"))

                threading.Thread(target=_run, daemon=True).start()

            def start_cf_tunnel():
                # Guard: Admin Server MUST be running first.
                # Cloudflare returns 502 if nothing is listening on the port.
                adm = self.admin_servers.get(name)
                if not adm or not adm._running:
                    messagebox.showerror(
                        "Start Hosting First",
                        "The Web Server is not running yet.\n\n"
                        "① Scroll UP in this left panel\n"
                        "② Set a password in Admin Tools (Host)\n"
                        "③ Click  ▶ Start Hosting\n"
                        "④ Then come back here and click  ☁ Start Tunnel\n\n"
                        "Cloudflare returns 502 if nothing is listening.",
                        parent=win)
                    return
                binary = cf_binary_var.get().strip()
                if not binary or not os.path.exists(binary):
                    messagebox.showerror("Error",
                        "Download cloudflared first.", parent=win)
                    return
                if name in self.cf_tunnels and self.cf_tunnels[name].running:
                    messagebox.showinfo("Info", "Tunnel already running.", parent=win)
                    return

                # Use the ACTUAL port the AdminServer is bound to —
                # the port field may have been edited since hosting started
                actual_port = adm.port
                cf_status_var.set(f"⏳ Starting tunnel on port {actual_port}…")
                cf_url_var.set("")

                def on_url(url):
                    win.after(0, lambda: cf_url_var.set(url))
                    win.after(0, lambda: cf_status_var.set(
                        "● Active — open URL in browser, add /dashboard"))

                tunnel = CloudflaredTunnel(
                    binary, actual_port,
                    log_cb=lambda m: None,
                    url_cb=on_url
                )
                if tunnel.start():
                    self.cf_tunnels[name] = tunnel
                    cf_status_var.set("⏳ Waiting for tunnel URL…")
                else:
                    cf_status_var.set("✗ Failed to start — check cloudflared binary")

            def stop_cf_tunnel():
                t = self.cf_tunnels.pop(name, None)
                if t:
                    t.stop()
                cf_url_var.set("")
                cf_status_var.set("○ Stopped")

            self._btn(cf_btns, "⬇ Auto-Download", auto_download_cf,
                      color=COLORS["panel"], fg=COLORS["text"], padx=8, pady=4,
                      font=("Helvetica", 9),
                      highlightbackground=COLORS["border"], highlightthickness=1
                      ).pack(side="left", padx=(0, 4))
            self._btn(cf_btns, "☁ Start Tunnel", start_cf_tunnel,
                      color=COLORS["accent2"], padx=8, pady=4,
                      font=("Helvetica", 9)).pack(side="left", padx=(0, 4))
            self._btn(cf_btns, "■ Stop", stop_cf_tunnel,
                      color=COLORS["danger"], padx=8, pady=4,
                      font=("Helvetica", 9)).pack(side="left")

            # Restore existing tunnel status if one is running
            existing = self.cf_tunnels.get(name)
            if existing and existing.running and existing.tunnel_url:
                cf_url_var.set(existing.tunnel_url)
                cf_status_var.set("● Active — click URL to copy · paste into Connect bar")
            elif existing and existing.running:
                cf_status_var.set("⏳ Waiting for tunnel URL…")

            tk.Label(cf_body,
                     text="① Set password above + click  ▶ Start Hosting\n"
                          "② Scroll down, then click  ☁ Start Tunnel\n"
                          "③ Open the URL in any browser, add  /dashboard\n"
                          "   e.g.  https://xxx.trycloudflare.com/dashboard\n"
                          "Note: URL changes each tunnel restart.",
                     bg=COLORS["card"], fg=COLORS["subtext"],
                     font=("Helvetica", 7),
                     justify="left").pack(anchor="w", pady=(4, 0))

        # ── RIGHT: Console log ─────────────────────────────────────────────────
        right = tk.Frame(body, bg=COLORS["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

        tk.Label(right, text="Console", font=("Helvetica", 10, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")

        log_widget = scrolledtext.ScrolledText(
            right, bg="#0D0D14", fg="#A0F0B0", font=("Courier New", 9),
            insertbackground="#A0F0B0", bd=0, state="disabled")
        log_widget.pack(fill="both", expand=True, pady=(4, 6))

        cmd_row = tk.Frame(right, bg=COLORS["bg"])
        cmd_row.pack(fill="x")
        cmd_var   = tk.StringVar()
        cmd_entry = tk.Entry(cmd_row, textvariable=cmd_var,
                             bg=COLORS["card"], fg=COLORS["text"],
                             insertbackground=COLORS["text"],
                             font=("Courier New", 9), bd=0,
                             highlightthickness=1, highlightbackground=COLORS["border"])
        cmd_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        def send_console_cmd(*_):
            cmd = cmd_var.get().strip()
            if not cmd:
                return
            if is_remote:
                remote_client.send_cmd("console", [cmd])
            else:
                proc = self.server_procs.get(name)
                if proc:
                    proc.send_command(cmd)
            cmd_var.set("")

        cmd_entry.bind("<Return>", send_console_cmd)
        self._btn(cmd_row, "Send", send_console_cmd,
                  padx=12, pady=5, font=("Helvetica", 9)).pack(side="left")

        def append_log(line):
            # Must run on main thread — callers must use win.after(0, ...)
            try:
                if not win.winfo_exists():
                    return
                log_widget.config(state="normal")
                log_widget.insert("end", line)
                log_widget.see("end")
                log_widget.config(state="disabled")
            except tk.TclError:
                pass   # window was destroyed between check and update

        # Hook into live server log — restore original callback when window closes.
        # Walk past any existing wrappers to reach the true original, so we
        # never end up with a chain of wrappers from repeated window opens.
        if not is_remote:
            proc = self.server_procs.get(name)
            if proc:
                # Unwrap any previous dashboard wrappers to get the real callback
                base_cb = proc.log_callback
                while hasattr(base_cb, '_is_dash_wrapper'):
                    base_cb = base_cb._wrapped_orig

                def new_cb(line, _base=base_cb):
                    _base(line)
                    try:
                        if win.winfo_exists():
                            win.after(0, lambda l=line: append_log(l))
                    except Exception:
                        pass
                new_cb._is_dash_wrapper = True
                new_cb._wrapped_orig    = base_cb

                proc.log_callback = new_cb

                def _on_dash_close():
                    current_proc = self.server_procs.get(name)
                    if current_proc and current_proc.log_callback is new_cb:
                        current_proc.log_callback = base_cb

                win.protocol("WM_DELETE_WINDOW", lambda: (_on_dash_close(), win.destroy()))
                win.bind("<Destroy>", lambda e: _on_dash_close() if e.widget is win else None)

        # ── Live state refresh ─────────────────────────────────────────────────
        def refresh_dashboard(state: dict | None = None):
            if not win.winfo_exists():
                return
            if state is None:
                state = self._get_server_state(name)
            running = state.get("running", False)
            self.dash_status_var.set(
                f"● Online  {state.get('player_count', 0)} player(s)"
                if running else "○ Offline")
            for key, var in self.dash_stat_vars.items():
                val = state.get(key, "—")
                if key == "running":
                    val = "Online ✓" if val else "Offline"
                elif key == "ram":
                    val = f"{val} MB"
                var.set(str(val))
            players = state.get("players", [])
            self.dash_player_list.delete(0, "end")
            for p in players:
                self.dash_player_list.insert("end", f"  {p}")
            if not is_remote:
                win.after(3000, refresh_dashboard)

        if is_remote:
            # Wire remote state updates → refresh_dashboard
            orig_on_state = remote_client.on_state
            def on_state_update(state):
                orig_on_state(state)
                win.after(0, lambda s=state: refresh_dashboard(s))
            remote_client.on_state = on_state_update

            def on_remote_log(line):
                win.after(0, lambda l=line: append_log(l))
            remote_client._log_cb = on_remote_log
        else:
            refresh_dashboard()

    def _quick_admin_connect(self):
        """Quick-connect from the bottom bar of the Servers page."""
        pw     = self._quick_pw.get().strip()
        cfurl  = self._quick_cfurl.get().strip()
        host   = self._quick_host.get().strip()
        if not pw:
            self._quick_status.set("Enter password.")
            return

        # Determine base_url: Cloudflare URL takes priority over host:port
        if cfurl:
            base_url    = cfurl
            display_name = cfurl.replace("https://", "").split(".")[0]
            port_int     = 443
        else:
            if not host:
                self._quick_status.set("Enter host IP or Cloudflare URL.")
                return
            try:
                port_int = int(self._quick_port.get().strip())
            except ValueError:
                self._quick_status.set("Port must be a number.")
                return
            base_url     = ""
            display_name = host

        self._quick_status.set("Connecting…")
        self.update()

        fake_info = {"directory": "", "loader": "?", "mc_version": "?", "ram": 0}
        client = AdminClient(
            host, port_int, pw,
            on_state=lambda s: None,
            on_disconnect=lambda: self.after(0, lambda: messagebox.showinfo(
                "Disconnected", f"Connection to {display_name} closed.")),
            on_error=lambda e: self.after(
                0, lambda: self._quick_status.set(f"Error: {e}")),
            base_url=base_url,
        )
        if client.connect():
            self._quick_status.set("Connected ✓")
            self._quick_pw.set("")
            self._quick_cfurl.set("")
            self.after(300, lambda: self._open_dashboard(
                f"Remote ({display_name})", fake_info, remote_client=client))
        else:
            self._quick_status.set("Failed — check credentials.")

    def _handle_remote_cmd(self, server_name: str, cmd: str, args: list):
        """Execute a command sent by a remote admin client."""
        proc = self.server_procs.get(server_name)
        info = self.config.get("servers", {}).get(server_name, {})
        if cmd == "start":
            self.after(0, lambda: self._start_server(server_name, info))
        elif cmd == "stop":
            # Re-look-up proc at execution time in case it started after wiring
            def _do_stop():
                p = self.server_procs.get(server_name)
                if p:
                    p.stop()
            self.after(0, _do_stop)
        elif cmd == "restart":
            def _do_restart():
                p = self.server_procs.get(server_name)
                if p:
                    p.stop()
            self.after(0, _do_restart)
            self.after(5000, lambda: self._start_server(server_name, info))
        elif cmd == "console" and args:
            if proc and proc.running:
                proc.send_command(args[0])

    # ── Admin Join page (remote admin client) ────────────────────────────────────

    def _build_admin_join_page(self):
        page = self.pages["admin_join"]

        tk.Label(page, text="Admin Join", font=("Helvetica", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(page,
            text="Connect to another Nova Servers host to manage their server remotely.",
            bg=COLORS["bg"], fg=COLORS["subtext"],
            font=("Helvetica", 10)).pack(anchor="w", padx=24, pady=(0, 12))
        tk.Frame(page, bg=COLORS["border"], height=1).pack(fill="x", padx=24)

        card = tk.Frame(page, bg=COLORS["panel"], padx=24, pady=20)
        card.pack(fill="x", padx=24, pady=16)

        def field(label, default="", show=None):
            r = tk.Frame(card, bg=COLORS["panel"])
            r.pack(fill="x", pady=6)
            tk.Label(r, text=label, width=16, anchor="w",
                     bg=COLORS["panel"], fg=COLORS["text"],
                     font=("Helvetica", 10)).pack(side="left")
            var = tk.StringVar(value=default)
            kwargs = dict(textvariable=var, bg=COLORS["card"], fg=COLORS["text"],
                          insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                          highlightthickness=1, highlightbackground=COLORS["border"])
            if show:
                kwargs["show"] = show
            tk.Entry(r, **kwargs).pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
            return var

        host_var  = field("Host IP / Domain", "")
        port_var  = field("Port", str(ADMIN_PORT_DEFAULT))
        pw_var    = field("Password", show="●")
        name_var  = field("Server Name", "Remote Server")

        tk.Frame(card, bg=COLORS["border"], height=1).pack(
            fill="x", pady=(10, 6))
        tk.Label(card,
            text="OR connect via Cloudflare Tunnel URL (overrides Host/Port above):",
            bg=COLORS["panel"], fg=COLORS["subtext"],
            font=("Helvetica", 8)).pack(anchor="w")
        cfurl_var = field("Cloudflare URL",
            "https://xyz.trycloudflare.com")

        status_var = tk.StringVar(value="")
        tk.Label(card, textvariable=status_var, bg=COLORS["panel"],
                 fg=COLORS["warning"], font=("Helvetica", 9),
                 wraplength=460).pack(anchor="w", pady=(4, 0))

        def connect():
            host = host_var.get().strip()
            pw   = pw_var.get().strip()
            name = name_var.get().strip() or "Remote Server"
            try:
                port = int(port_var.get().strip())
            except ValueError:
                status_var.set("Port must be a number.")
                return
            if not host:
                status_var.set("Enter the host IP or domain name.")
                return
            if not pw:
                status_var.set("Enter the admin password.")
                return

            status_var.set("Connecting…")
            page.update()

            # Fake info dict for remote server (dashboard uses it for world paths etc.)
            fake_info = {"directory": "", "loader": "?", "mc_version": "?", "ram": 0}

            cfurl = cfurl_var.get().strip()
            # Cloudflare URL overrides host:port
            if cfurl and cfurl != "https://xyz.trycloudflare.com":
                base_url     = cfurl
                display_addr = cfurl
            else:
                base_url     = ""
                display_addr = f"{host}:{port}"

            client = AdminClient(
                host, port, pw,
                on_state=lambda s: None,
                on_disconnect=lambda: messagebox.showinfo(
                    "Disconnected", f"Connection to {display_addr} closed."),
                on_error=lambda e: status_var.set(f"Error: {e}"),
                base_url=base_url,
            )
            if client.connect():
                status_var.set(f"Connected to {display_addr} ✓")
                self.after(300, lambda: self._open_dashboard(name, fake_info,
                                                              remote_client=client))
            else:
                status_var.set("Connection failed — check credentials.")

        self._btn(card, "Connect →", connect,
                  padx=20, pady=8,
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(16, 0))

        tk.Label(page, text=(
            "How to host:  Open a server's View dashboard → Admin Tools (Host) → "
            "set a password and click Start Hosting.  Share your public IP, port, and password."),
            bg=COLORS["bg"], fg=COLORS["subtext"],
            font=("Helvetica", 8), wraplength=700, justify="left",
            padx=24).pack(anchor="w", pady=(8, 0))


    # ── Settings page ─────────────────────────────────────────────────────────────

    def _build_settings_page(self):
        page = self.pages["settings"]

        tk.Label(page, text="Settings", font=("Helvetica", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w", padx=24, pady=(20, 12))
        tk.Frame(page, bg=COLORS["border"], height=1).pack(fill="x", padx=24)

        card = tk.Frame(page, bg=COLORS["panel"], padx=24, pady=20)
        card.pack(fill="x", padx=24, pady=16)

        def row(label, var, browse_cmd=None):
            r = tk.Frame(card, bg=COLORS["panel"])
            r.pack(fill="x", pady=8)
            tk.Label(r, text=label, width=22, anchor="w", bg=COLORS["panel"],
                     fg=COLORS["text"], font=("Helvetica", 10)).pack(side="left")
            e = tk.Entry(r, textvariable=var, bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], bd=0, font=("Helvetica", 10),
                         highlightthickness=1, highlightbackground=COLORS["border"])
            e.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
            if browse_cmd:
                self._btn(r, "Browse", browse_cmd,
                          color=COLORS["accent2"], padx=10).pack(side="left")

        self.java_path_var = tk.StringVar(
            value=self.config.get("java_path", default_java_path()))
        row("Java executable", self.java_path_var, self._browse_java)

        tk.Label(card,
                 text=f"Detected OS: {SYSTEM} ({_platform_mod.machine()})  |  Default Java: {default_java_path()}",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8)).pack(anchor="w", pady=(0, 10))

        # ── UPnP toggle ──────────────────────────────────────────────────────
        upnp_frame = tk.Frame(card, bg=COLORS["panel"])
        upnp_frame.pack(fill="x", pady=(10, 4))

        self.upnp_var = tk.BooleanVar(
            value=self.config.get("upnp_enabled", False))
        tk.Checkbutton(
            upnp_frame,
            text="Enable UPnP  (auto-open ports on router — works on most home networks)",
            variable=self.upnp_var,
            bg=COLORS["panel"], fg=COLORS["text"],
            selectcolor=COLORS["card"],
            activebackground=COLORS["panel"],
            activeforeground=COLORS["text"],
            font=("Helvetica", 10),
            bd=0, cursor="hand2",
        ).pack(side="left")

        tk.Label(card,
                 text="UPnP is disabled by default. Enabling it installs miniupnpc "                      "automatically and lets Nova Servers open firewall ports without "                      "manual port forwarding. Requires a UPnP-compatible router.",
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 font=("Helvetica", 8), wraplength=560, justify="left",
                 ).pack(anchor="w", pady=(0, 10))

        self._btn(card, "Save Settings", self._save_settings,
                  padx=16, pady=7, font=("Helvetica", 10)).pack(anchor="w", pady=(4, 0))

        ref = tk.Frame(page, bg=COLORS["panel"], padx=24, pady=16)
        ref.pack(fill="x", padx=24)
        tk.Label(ref, text="Server Types", font=("Helvetica", 11, "bold"),
                 bg=COLORS["panel"], fg=COLORS["text"]).pack(anchor="w", pady=(0, 10))

        for lname, ldata in LOADER_INFO.items():
            rr = tk.Frame(ref, bg=COLORS["panel"])
            rr.pack(fill="x", pady=3)
            tk.Label(rr, text="●", fg=ldata["color"], bg=COLORS["panel"],
                     font=("Helvetica", 11)).pack(side="left", padx=(0, 8))
            auto  = ldata.get("auto_install", False)
            badge = "Auto" if auto is True else ("BuildTools" if auto == "buildtools" else "Manual")
            tk.Label(rr, text=lname, font=("Helvetica", 10, "bold"),
                     bg=COLORS["panel"], fg=COLORS["text"],
                     width=10, anchor="w").pack(side="left")
            tk.Label(rr, text=f"[{badge}]  ", bg=COLORS["panel"],
                     fg=COLORS["subtext"], font=("Helvetica", 8),
                     width=10, anchor="w").pack(side="left")
            tk.Label(rr, text=ldata["description"], bg=COLORS["panel"],
                     fg=COLORS["subtext"], font=("Helvetica", 9),
                     wraplength=500, justify="left").pack(side="left", anchor="w")

    def _browse_java(self):
        filetypes = [("Java executable", "java.exe java"), ("All files", "*.*")] \
            if SYSTEM == "Windows" else [("All files", "*")]
        path = filedialog.askopenfilename(
            title="Select Java executable", filetypes=filetypes)
        if path:
            self.java_path_var.set(path)

    def _save_settings(self):
        self.config["java_path"]     = self.java_path_var.get().strip()
        prev_upnp = self.config.get("upnp_enabled", False)
        self.config["upnp_enabled"] = self.upnp_var.get()
        save_config(self.config)
        self.status_var.set("Settings saved")
        # If UPnP was just enabled, install miniupnpc now
        if self.config["upnp_enabled"] and not prev_upnp:
            def _install():
                ok = _pip_install("miniupnpc")
                msg = ("miniupnpc installed ✓  UPnP is now active."
                       if ok else
                       "Could not install miniupnpc.\n"                       "Try: pip install miniupnpc --break-system-packages")
                self.after(0, lambda: messagebox.showinfo("UPnP", msg))
            threading.Thread(target=_install, daemon=True).start()
            messagebox.showinfo("Saved", "Settings saved.\nInstalling miniupnpc for UPnP…")
        else:
            messagebox.showinfo("Saved", "Settings saved.")


# ── Entry point ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = NovaServers()
    app.mainloop()
