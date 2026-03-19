import time
import ctypes
import ctypes.wintypes as wintypes
import psutil
from win32gui import FindWindow
from offsets import dwGameTypes, dwGlobalVars

PROCESS_ALL_ACCESS = 0x1F0FFF
TH32CS_SNAPMODULE = 0x00000008
MAX_MODULE_NAME32 = 255

class ProcessManager:
    def __init__(self):
        self.process_id = None
        self.process_handle = None
        self.client_module = None
        self.server_module = None
        self.hwnd = None

    @staticmethod
    def get_process_id(process_name):
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] == process_name:
                return proc.info['pid']
        return None

    def connect(self, process_name, window_title):
        self.process_id = self.get_process_id(process_name)
        if not self.process_id:
            return False
            
        self.hwnd = FindWindow("SDL_app", window_title)
        self.process_handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_ALL_ACCESS, 
            False, 
            self.process_id
        )
        self.client_module = self.get_module_address("client.dll")
        self.server_module = self.get_module_address("server.dll")
        
        return self.process_handle is not None

    def get_module_address(self, module_name):
        h_snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE, 
            self.process_id
        )
        
        class ModuleEntry32(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('th32ModuleID', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('GlblcntUsage', wintypes.DWORD),
                ('ProccntUsage', wintypes.DWORD),
                ('modBaseAddr', ctypes.POINTER(wintypes.BYTE)),
                ('modBaseSize', wintypes.DWORD),
                ('hModule', wintypes.HMODULE),
                ('szModule', ctypes.c_char * (MAX_MODULE_NAME32 + 1)),
                ('szExePath', ctypes.c_char * 260)
            ]
            
        entry = ModuleEntry32()
        entry.dwSize = ctypes.sizeof(ModuleEntry32)
        
        if ctypes.windll.kernel32.Module32First(h_snapshot, ctypes.byref(entry)):
            while True:
                if module_name.encode() == entry.szModule:
                    ctypes.windll.kernel32.CloseHandle(h_snapshot)
                    return entry.hModule
                if not ctypes.windll.kernel32.Module32Next(h_snapshot, ctypes.byref(entry)):
                    break
                    
        ctypes.windll.kernel32.CloseHandle(h_snapshot)
        return 0


class MemoryReader:
    def __init__(self, process_handle):
        self.process_handle = process_handle
        
    def read(self, address, c_type):
        buffer = c_type()
        bytes_read = ctypes.c_size_t()
        
        ctypes.windll.kernel32.ReadProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_read)
        )
        
        return buffer.value if bytes_read.value == ctypes.sizeof(buffer) else None

    def read_bytes(self, address, size):
        buffer = (ctypes.c_byte * size)()
        bytes_read = ctypes.c_size_t()
        
        ctypes.windll.kernel32.ReadProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        
        return bytes(buffer) if bytes_read.value == size else None
    
    def read_int(self, address): return self.read(address, ctypes.c_int)
    def read_float(self, address): return self.read(address, ctypes.c_float)
    def read_longlong(self, address): return self.read(address, ctypes.c_longlong)
    def read_bool(self, address): return self.read(address, ctypes.c_bool)
    def read_short(self, address): return self.read(address, ctypes.c_short)
        
    def read_string(self, address, max_length):
        buffer = ctypes.create_string_buffer(max_length)
        bytes_read = ctypes.c_size_t()
        ctypes.windll.kernel32.ReadProcessMemory(
            self.process_handle, ctypes.c_void_p(address), buffer, max_length, ctypes.byref(bytes_read)
        )
        return buffer.value.decode('utf-8', 'ignore') if bytes_read.value > 0 else ""

    # --- THÊM CÁC HÀM GHI ---
    def write(self, address, c_type, value):
        """Ghi giá trị vào bộ nhớ process"""
        buffer = c_type(value)
        bytes_written = ctypes.c_size_t()
        result = ctypes.windll.kernel32.WriteProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_written)
        )
        return result != 0 and bytes_written.value == ctypes.sizeof(buffer)

    def write_float(self, address, value):
        return self.write(address, ctypes.c_float, value)

    def write_int(self, address, value):
        return self.write(address, ctypes.c_int, value)

    def write_bool(self, address, value):
        return self.write(address, ctypes.c_bool, value)
    # --------------------------

    def get_map_name(self, client_base):
        try:
            if not dwGlobalVars: return None
            global_vars_ptr = self.read_longlong(client_base + dwGlobalVars)
            if not global_vars_ptr: return None
            
            map_name_ptr = self.read_longlong(global_vars_ptr + 0x180)
            if not map_name_ptr: return None
            
            map_str = self.read_string(map_name_ptr, 128)
            
            if map_str:
                if "<empty>" in map_str or len(map_str) < 3: return None
                
                map_str = map_str.replace("\\", "/")
                
                if "/" in map_str:
                    map_str = map_str.split("/")[-1]
                
                if "." in map_str:
                    map_str = map_str.split(".")[0]
                    
                return map_str
        except Exception:
            pass
        return None

def wait_cs2():
    while True:
        time.sleep(1)
        try:
            pid = ProcessManager.get_process_id("cs2.exe")
            if pid:
                temp = ProcessManager()
                temp.process_id = pid
                client = temp.get_module_address("client.dll")
                if client: return True
        except: pass

def get_memory_reader():
    pid = ProcessManager.get_process_id("cs2.exe")
    if not pid: return None, None
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not handle: return None, None
    pm = MemoryReader(handle)
    temp = ProcessManager()
    temp.process_id = pid
    client_base = temp.get_module_address("client.dll")
    if not client_base: return None, None
    return client_base, pm