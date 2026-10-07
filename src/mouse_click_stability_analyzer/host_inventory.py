"""Frozen host reproducibility inventory.

Collected off the timing-capture path. Failures become "Not available".
Does not require administrator rights or network access.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from typing import Any, Callable

from .schema import CAPTURE_WINDOWS_RAW_INPUT, TOOL_VERSION

NOT_AVAILABLE = "Not available"
HOST_INFORMATION_SCHEMA = "MCSA_HOST_INFORMATION_V1"
_CIM_TIMEOUT_SEC = 5
_CREATE_NO_WINDOW = 0x08000000

# Privacy: never request or emit these CIM/WMI properties.
_EXCLUDED_PROPERTY_NAMES = frozenset({
    "SerialNumber", "IdentifyingNumber", "UUID", "UserName", "RegisteredUser",
    "MACAddress", "IPAddress", "ProductKey", "OA3xOriginalProductKey",
})

_CIM_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cs = Get-CimInstance -ClassName Win32_ComputerSystem | Select-Object Manufacturer, Model
$os = Get-CimInstance -ClassName Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber
$cpu = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1 Name
$bios = Get-CimInstance -ClassName Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate
$usb = @(Get-CimInstance -ClassName Win32_USBController | Select-Object Name)
[pscustomobject]@{
    ComputerSystem = $cs
    OperatingSystem = $os
    Processor = $cpu
    BIOS = $bios
    USBControllers = $usb
} | ConvertTo-Json -Compress -Depth 5
"""

_CIM_CACHE: dict[str, Any] | None = None
PRIVACY_EXCLUDED_FIELD_NAMES = frozenset({
    "serial_number", "username", "user_name", "password", "token",
    "ip_address", "mac_address", "product_key", "windows_product_key",
    "motherboard_serial_number", "device_serial_number", "machine_serial_number",
})


def _clean(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "unknown"}:
        return None
    return text


def _value_or_na(value: Any) -> str:
    text = _clean(value)
    return text if text else NOT_AVAILABLE


_DMTF_DATETIME = re.compile(
    r"^(\d{4})(\d{2})(\d{2})\d{6}\.\d{6}[+-]\d{3}$"
)
_MS_AJAX_DATE = re.compile(
    r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _calendar_ymd(year: Any, month: Any, day: Any) -> str | None:
    try:
        constructed = date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None
    return f"{constructed.year:04d}-{constructed.month:02d}-{constructed.day:02d}"


def normalize_bios_date(raw: Any) -> str | None:
    """Strict BIOS/UEFI date → YYYY-MM-DD, else None.

    Supported collector forms:
    - Windows PowerShell 5.1 ConvertTo-Json of System.DateTime: /Date(ms)/
    - CIM/DMTF datetime: YYYYMMDDHHMMSS.mmmmmm±UUU
    - Already-normalized YYYY-MM-DD (frozen snapshot identity)

    Never repairs impossible dates or slices arbitrary digit groups.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raw = raw.astimezone(timezone.utc)
        return _calendar_ymd(raw.year, raw.month, raw.day)
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return _calendar_ymd(raw.year, raw.month, raw.day)
    text = _clean(raw)
    if not text:
        return None
    text = text.replace("\\/", "/")
    if "*" in text:
        return None
    ajax = _MS_AJAX_DATE.fullmatch(text)
    if ajax:
        try:
            instant = datetime.fromtimestamp(int(ajax.group(1)) / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return _calendar_ymd(instant.year, instant.month, instant.day)
    dmtf = _DMTF_DATETIME.fullmatch(text)
    if dmtf:
        return _calendar_ymd(dmtf.group(1), dmtf.group(2), dmtf.group(3))
    iso_date = _ISO_DATE.fullmatch(text)
    if iso_date:
        return _calendar_ymd(iso_date.group(1), iso_date.group(2), iso_date.group(3))
    return None


def _bios_date(raw: Any) -> str | None:
    return normalize_bios_date(raw)


def _as_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def _query_windows_cim_cached() -> dict[str, Any]:
    global _CIM_CACHE
    if _CIM_CACHE is not None:
        return dict(_CIM_CACHE)
    payload = _query_windows_cim()
    _CIM_CACHE = dict(payload)
    return dict(payload)


def _cim_allowed() -> bool:
    """Skip live CIM under unittest. Production collection is unchanged."""
    if os.environ.get("MCSA_SKIP_HOST_CIM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if "unittest" in sys.modules:
        return False
    return True


def _query_windows_cim() -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {}
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        creationflags = _CREATE_NO_WINDOW
    result: dict[str, Any] = {"completed": None, "error": None}

    def _run() -> None:
        try:
            result["completed"] = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", _CIM_SCRIPT,
                ],
                capture_output=True,
                text=True,
                timeout=_CIM_TIMEOUT_SEC,
                startupinfo=startupinfo,
                creationflags=creationflags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["error"] = exc

    worker = threading.Thread(target=_run, name="mcsa-host-cim", daemon=True)
    worker.start()
    worker.join(_CIM_TIMEOUT_SEC + 0.5)
    if worker.is_alive() or result["error"] is not None or result["completed"] is None:
        return {}
    completed = result["completed"]
    payload = (completed.stdout or "").strip()
    if not payload or completed.returncode not in (0, None):
        if not payload:
            return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    for key in list(parsed.keys()):
        if str(key) in _EXCLUDED_PROPERTY_NAMES:
            parsed.pop(key, None)
    return parsed


def _runtime_versions() -> tuple[str | None, str | None]:
    pyside = None
    qt = None
    try:
        import PySide6
        pyside = getattr(PySide6, "__version__", None)
    except Exception:
        pyside = None
    try:
        from PySide6.QtCore import qVersion
        qt = qVersion()
    except Exception:
        qt = None
    return _clean(pyside), _clean(qt)


def collect_host_information(
    settings: dict[str, Any] | None = None,
    *,
    cim_probe: Callable[[], dict[str, Any] | None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect host reproducibility fields. Safe to call at profile-lock / complete.

    Never raises. Never queries the network. CIM work is optional and timed out.
    """
    settings = dict(settings or {})
    stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    pyside, qt = _runtime_versions()
    cim: dict[str, Any] = {}
    try:
        if cim_probe is not None:
            cim = dict(cim_probe() or {})
        elif sys.platform.startswith("win") and _cim_allowed():
            cim = _query_windows_cim_cached()
    except Exception:
        cim = {}

    cs = cim.get("ComputerSystem") if isinstance(cim.get("ComputerSystem"), dict) else {}
    os_info = cim.get("OperatingSystem") if isinstance(cim.get("OperatingSystem"), dict) else {}
    cpu = cim.get("Processor") if isinstance(cim.get("Processor"), dict) else {}
    bios = cim.get("BIOS") if isinstance(cim.get("BIOS"), dict) else {}
    controllers = []
    for item in _as_list(cim.get("USBControllers")):
        if isinstance(item, dict) and _clean(item.get("Name")):
            controllers.append(_clean(item.get("Name")))
    drivers = []
    for item in _as_list(cim.get("USBDrivers")):
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("DeviceName"))
        provider = _clean(item.get("DriverProviderName"))
        version = _clean(item.get("DriverVersion"))
        if name or provider or version:
            parts = [p for p in (name, provider, version) if p]
            drivers.append(" / ".join(parts))

    os_caption = _clean(os_info.get("Caption"))
    os_version = _clean(os_info.get("Version"))
    os_build = _clean(os_info.get("BuildNumber"))
    win_version = None
    if os_version and os_build and os_build not in os_version:
        win_version = f"{os_version} (build {os_build})"
    elif os_version:
        win_version = os_version
    elif os_build:
        win_version = f"build {os_build}"

    snapshot = {
        "schema": HOST_INFORMATION_SCHEMA,
        "collected_at": stamp,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "pyside6_version": pyside,
        "qt_version": qt,
        "capture_backend": settings.get("capture_mode") or CAPTURE_WINDOWS_RAW_INPUT,
        "tool_version": TOOL_VERSION,
        "host_manufacturer": _clean(cs.get("Manufacturer")) if isinstance(cs, dict) else None,
        "host_model": _clean(cs.get("Model")) if isinstance(cs, dict) else None,
        "os_name": os_caption or platform.platform(),
        "os_version": win_version,
        "cpu_model": _clean(cpu.get("Name")) if isinstance(cpu, dict) else None,
        "bios_vendor": _clean(bios.get("Manufacturer")) if isinstance(bios, dict) else None,
        "bios_version": _clean(bios.get("SMBIOSBIOSVersion")) if isinstance(bios, dict) else None,
        "bios_date": _bios_date(bios.get("ReleaseDate")) if isinstance(bios, dict) else None,
        "usb_host_controllers": controllers,
        "usb_controller_drivers": [],
        "dut_usb_controller_attributed": False,
        "python_runtime": platform.python_version(),
        "fields_na": NOT_AVAILABLE,
    }
    for key in PRIVACY_EXCLUDED_FIELD_NAMES:
        snapshot.pop(key, None)
    return snapshot


def empty_host_information(*, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Minimal snapshot used when collection fails. Never raises."""
    return collect_host_information(settings, cim_probe=lambda: {})


def field_display(snapshot: dict[str, Any] | None, key: str) -> str:
    env = snapshot or {}
    if key == "usb_host_controllers":
        names = [n for n in (env.get("usb_host_controllers") or []) if n]
        return "; ".join(names) if names else NOT_AVAILABLE
    if key == "usb_controller_drivers":
        names = [n for n in (env.get("usb_controller_drivers") or []) if n]
        return "; ".join(names) if names else NOT_AVAILABLE
    return _value_or_na(env.get(key))
