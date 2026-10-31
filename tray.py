"""Native Windows notification-area icon; no additional dependencies."""
import ctypes as C
from ctypes import wintypes as W
TRAY_MESSAGE=0x8000+31
RESTORE_MESSAGE=0x8000+32

class GUID(C.Structure):
    _fields_=[('Data1',W.DWORD),('Data2',W.WORD),('Data3',W.WORD),('Data4',W.BYTE*8)]

class NOTIFYICONDATAW(C.Structure):
    _fields_=[('cbSize',W.DWORD),('hWnd',W.HWND),('uID',W.UINT),('uFlags',W.UINT),
              ('uCallbackMessage',W.UINT),('hIcon',W.HANDLE),('szTip',W.WCHAR*128),
              ('dwState',W.DWORD),('dwStateMask',W.DWORD),('szInfo',W.WCHAR*256),
              ('uVersion',W.UINT),('szInfoTitle',W.WCHAR*64),('dwInfoFlags',W.DWORD),
              ('guidItem',GUID),('hBalloonIcon',W.HANDLE)]

shell32=C.WinDLL('shell32',use_last_error=True)
user32=C.WinDLL('user32',use_last_error=True)
shell32.Shell_NotifyIconW.argtypes=[W.DWORD,C.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype=W.BOOL
user32.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,C.c_int,C.c_int,W.UINT]
user32.LoadImageW.restype=W.HANDLE
user32.DestroyIcon.argtypes=[W.HANDLE];user32.DestroyIcon.restype=W.BOOL

class TrayIcon:
    def __init__(self,hwnd,icon_path):
        self.icon=user32.LoadImageW(None,str(icon_path),1,32,32,0x10)
        self.data=NOTIFYICONDATAW()
        self.data.cbSize=C.sizeof(self.data);self.data.hWnd=hwnd;self.data.uID=1
        self.data.uFlags=1|2|4|0x80
        self.data.uCallbackMessage=TRAY_MESSAGE;self.data.hIcon=self.icon
        self.active=False;self.version4=False
        self.data.szTip='莲儿桌宠 · 单击叫回来，右键打开菜单'
        self.add()

    def add(self):
        if not self.icon:return False
        self.active=bool(shell32.Shell_NotifyIconW(0,C.byref(self.data)))
        if self.active:
            self.data.uVersion=4
            self.version4=bool(shell32.Shell_NotifyIconW(4,C.byref(self.data)))
        return self.active

    def set_hidden(self,hidden):
        self.data.szTip='莲儿桌宠 · 已收纳，单击叫回来' if hidden else '莲儿桌宠 · 单击叫回来，右键打开菜单'
        if self.active:shell32.Shell_NotifyIconW(1,C.byref(self.data))

    def event(self,lparam):
        event=lparam&0xffff
        if self.version4:
            if event in (0x400,0x401):return 'show'
            if event==0x7b:return 'menu'
        else:
            if event in (0x202,0x203):return 'show'
            if event==0x205:return 'menu'
        return None

    def close(self):
        if self.active:
            shell32.Shell_NotifyIconW(2,C.byref(self.data));self.active=False
        if self.icon:
            user32.DestroyIcon(self.icon);self.icon=None
