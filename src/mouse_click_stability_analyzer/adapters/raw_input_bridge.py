from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes

# Compatibility aliases for Python builds where ctypes.wintypes lacks some Win32 handle types.
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HMENU = getattr(wintypes, "HMENU", wintypes.HANDLE)
HINSTANCE = getattr(wintypes, "HINSTANCE", wintypes.HANDLE)


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
RIM_TYPEMOUSE = 0
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWMOUSE_BUTTONS_STRUCT(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]

class RAWMOUSE_BUTTONS_UNION(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("buttons", RAWMOUSE_BUTTONS_STRUCT),
    ]

class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("button_union", RAWMOUSE_BUTTONS_UNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]

class RAWINPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mouse", RAWMOUSE),
    ]

class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", RAWINPUT_UNION),
    ]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    HMENU,
    HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.RegisterRawInputDevices.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICE),
    wintypes.UINT,
    wintypes.UINT,
]
user32.RegisterRawInputDevices.restype = wintypes.BOOL

user32.GetRawInputData.argtypes = [
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
]
user32.GetRawInputData.restype = wintypes.UINT

user32.GetRawInputDeviceInfoW.argtypes = [
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
]
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT

user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

device_name_cache = {}

def emit(obj):
    # ASCII-only wire format: non-ASCII text travels as \uXXXX escapes, so the
    # line never depends on the helper's console code page.
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()

def emit_error(message):
    emit({
        "type": "error",
        "message": str(message),
        "capture_source": "windows_raw_input_bridge",
    })

def button_events_from_flags(flags: int):
    mapping = [
        (RI_MOUSE_LEFT_BUTTON_DOWN, "Left", "down"),
        (RI_MOUSE_LEFT_BUTTON_UP, "Left", "up"),
        (RI_MOUSE_RIGHT_BUTTON_DOWN, "Right", "down"),
        (RI_MOUSE_RIGHT_BUTTON_UP, "Right", "up"),
        (RI_MOUSE_MIDDLE_BUTTON_DOWN, "Middle", "down"),
        (RI_MOUSE_MIDDLE_BUTTON_UP, "Middle", "up"),
        (RI_MOUSE_BUTTON_4_DOWN, "X1", "down"),
        (RI_MOUSE_BUTTON_4_UP, "X1", "up"),
        (RI_MOUSE_BUTTON_5_DOWN, "X2", "down"),
        (RI_MOUSE_BUTTON_5_UP, "X2", "up"),
    ]
    for bit, button, event_type in mapping:
        if flags & bit:
            yield button, event_type

def get_device_name(hDevice):
    key = int(hDevice) if hDevice else 0
    if key in device_name_cache:
        return device_name_cache[key]

    if not hDevice:
        device_name_cache[key] = "rawinput_unknown_device"
        return device_name_cache[key]

    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, None, ctypes.byref(size))

    if size.value <= 0:
        name = f"rawinput_device_{key}"
        device_name_cache[key] = name
        return name

    buf = ctypes.create_unicode_buffer(size.value + 1)
    result = user32.GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, buf, ctypes.byref(size))

    if result == ctypes.c_uint(-1).value:
        name = f"rawinput_device_{key}"
    else:
        name = buf.value or f"rawinput_device_{key}"

    device_name_cache[key] = name
    return name

def handle_raw_input(lParam):
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(RAWINPUTHEADER)

    user32.GetRawInputData(lParam, RID_INPUT, None, ctypes.byref(size), header_size)

    if size.value <= 0:
        return

    buffer = ctypes.create_string_buffer(size.value)
    result = user32.GetRawInputData(lParam, RID_INPUT, buffer, ctypes.byref(size), header_size)

    if result == ctypes.c_uint(-1).value:
        return

    raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents

    if raw.header.dwType != RIM_TYPEMOUSE:
        return

    mouse = raw.data.mouse
    flags = int(mouse.button_union.buttons.usButtonFlags)

    if not flags:
        return

    device_name = get_device_name(raw.header.hDevice)

    for button, event_type in button_events_from_flags(flags):
        emit({
            "type": "mouse_button",
            "button": button,
            "event_type": event_type,
            "x": int(mouse.lLastX),
            "y": int(mouse.lLastY),
            "time_perf": time.perf_counter(),
            "capture_source": "windows_raw_input",
            "device_source": device_name,
            "raw_hdevice": str(int(raw.header.hDevice) if raw.header.hDevice else 0),
            "raw_dx": int(mouse.lLastX),
            "raw_dy": int(mouse.lLastY),
        })

@WNDPROC
def wndproc(hwnd, msg, wParam, lParam):
    if msg == WM_INPUT:
        try:
            handle_raw_input(lParam)
        except Exception as e:
            emit_error(f"WM_INPUT handle error: {e}")
        return 0

    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0

    return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

def main():
    h_instance = kernel32.GetModuleHandleW(None)
    class_name = "MCSARawInputBridgeWindow"

    wc = WNDCLASS()
    wc.lpfnWndProc = wndproc
    wc.hInstance = h_instance
    wc.lpszClassName = class_name

    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        # Class may already exist in rare repeated starts inside same process.
        pass

    hwnd = user32.CreateWindowExW(
        0,
        class_name,
        "MCSA Raw Input Bridge",
        0,
        0,
        0,
        0,
        0,
        None,
        None,
        h_instance,
        None,
    )

    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())

    rid = RAWINPUTDEVICE()
    rid.usUsagePage = 0x01
    rid.usUsage = 0x02
    rid.dwFlags = RIDEV_INPUTSINK
    rid.hwndTarget = hwnd

    ok = user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

    emit({
        "type": "ready",
        "capture_source": "windows_raw_input_bridge",
    })

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        emit_error(e)
        raise
