import math
import ctypes
import win32con
import win32gui
import win32api
import imgui
import struct
import requests
import os
import sys
from .memory import get_memory_reader
from offsets import verdana_bytes, weapon_bytes, font_awesome

import zipfile

def download_and_extract_zip(file_id, extract_to='.'):
    """
    Tải file ZIP từ Google Drive và giải nén vào thư mục extract_to.
    Trả về True nếu thành công.
    """
    zip_path = os.path.join(get_data_path(), 'temp.zip')
    try:
        if download_from_drive(file_id, zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            os.remove(zip_path)
            return True
    except Exception as e:
        print(f"[Utils] Lỗi giải nén ZIP: {e}")
    return False

# --- DPI Awareness ---
def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

# --- Hằng số key mapping ---
win32_key_map = {
    "NONE": 0,
    "MOUSE1": win32con.VK_LBUTTON,
    "MOUSE2": win32con.VK_RBUTTON,
    "MOUSE3": win32con.VK_MBUTTON,
    "MOUSE4": win32con.VK_XBUTTON1,
    "MOUSE5": win32con.VK_XBUTTON2,
    "LSHIFT": win32con.VK_LSHIFT,
    "RSHIFT": win32con.VK_RSHIFT,
    "LCTRL": win32con.VK_LCONTROL,
    "RCTRL": win32con.VK_RCONTROL,
    "LALT": win32con.VK_LMENU,
    "RALT": win32con.VK_RMENU,
    "SPACE": win32con.VK_SPACE,
    "ENTER": win32con.VK_RETURN,
    "ESCAPE": win32con.VK_ESCAPE,
    "TAB": win32con.VK_TAB,
    "UP": win32con.VK_UP,
    "DOWN": win32con.VK_DOWN,
    "LEFT": win32con.VK_LEFT,
    "RIGHT": win32con.VK_RIGHT,
    "F1": win32con.VK_F1, "F2": win32con.VK_F2, "F3": win32con.VK_F3,
    "F4": win32con.VK_F4, "F5": win32con.VK_F5, "F6": win32con.VK_F6,
    "F7": win32con.VK_F7, "F8": win32con.VK_F8, "F9": win32con.VK_F9,
    "F10": win32con.VK_F10, "F11": win32con.VK_F11, "F12": win32con.VK_F12,
    "A": ord('A'), "B": ord('B'), "C": ord('C'), "D": ord('D'), "E": ord('E'),
    "F": ord('F'), "G": ord('G'), "H": ord('H'), "I": ord('I'), "J": ord('J'),
    "K": ord('K'), "L": ord('L'), "M": ord('M'), "N": ord('N'), "O": ord('O'),
    "P": ord('P'), "Q": ord('Q'), "R": ord('R'), "S": ord('S'), "T": ord('T'),
    "U": ord('U'), "V": ord('V'), "W": ord('W'), "X": ord('X'), "Y": ord('Y'),
    "Z": ord('Z'),
    "0": ord('0'), "1": ord('1'), "2": ord('2'), "3": ord('3'), "4": ord('4'),
    "5": ord('5'), "6": ord('6'), "7": ord('7'), "8": ord('8'), "9": ord('9'),
}

glfw_key_map = {
    "NONE": 0, "MOUSE1": 0, "MOUSE2": 1, "MOUSE3": 2, "MOUSE4": 3, "MOUSE5": 4,
    "MOUSEWHEEL_UP": -1, "MOUSEWHEEL_DOWN": -2,
    "LSHIFT": 340, "RSHIFT": 344, "LCTRL": 341, "RCTRL": 345,
    "LALT": 342, "RALT": 346,
    "SPACE": 32, "ENTER": 257, "ESCAPE": 256, "TAB": 258,
    "UP": 265, "DOWN": 264, "LEFT": 263, "RIGHT": 262,
    "F1": 290, "F2": 291, "F3": 292, "F4": 293, "F5": 294, "F6": 295,
    "F7": 296, "F8": 297, "F9": 298, "F10": 299, "F11": 300, "F12": 301,
    "A": 65, "B": 66, "C": 67, "D": 68, "E": 69, "F": 70, "G": 71, "H": 72, "I": 73,
    "J": 74, "K": 75, "L": 76, "M": 77, "N": 78, "O": 79, "P": 80, "Q": 81, "R": 82,
    "S": 83, "T": 84, "U": 85, "V": 86, "W": 87, "X": 88, "Y": 89, "Z": 90,
    "0": 48, "1": 49, "2": 50, "3": 51, "4": 52, "5": 53, "6": 54, "7": 55, "8": 56, "9": 57,
}

code_to_name = {v: k for k, v in glfw_key_map.items() if v > 0}

# --- Hàm đường dẫn cơ sở (cho file nhúng) ---
def get_base_path():
    """Trả về đường dẫn gốc của chương trình (hỗ trợ cả khi đóng gói với PyInstaller)"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Hàm đường dẫn dữ liệu (có quyền ghi) ---
def get_data_path():
    """Trả về đường dẫn lưu dữ liệu (có quyền ghi)"""
    if getattr(sys, 'frozen', False):
        # Khi chạy file exe, lưu trong AppData/Local/CS2Cheat
        return os.path.join(os.environ['LOCALAPPDATA'], 'CS2Cheat')
    else:
        # Khi chạy script, lưu trong thư mục dự án
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Hàm tải từ Google Drive (có kiểm tra HTTP status) ---
def download_from_drive(file_id, dest_path):
    """
    Tải file từ Google Drive bằng file ID.
    Xử lý cookie xác nhận để tải file lớn.
    """
    def get_confirm_token(response):
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                return value
        return None

    # Tạo thư mục đích nếu chưa có
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    URL = "https://docs.google.com/uc?export=download"
    session = requests.Session()
    response = session.get(URL, params={'id': file_id}, stream=True)

    if response.status_code != 200:
        raise Exception(f"Failed to download: HTTP {response.status_code}")

    token = get_confirm_token(response)

    if token:
        params = {'id': file_id, 'confirm': token}
        response = session.get(URL, params=params, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download after confirmation: HTTP {response.status_code}")

    with open(dest_path, 'wb') as f:
        for chunk in response.iter_content(32768):
            if chunk:
                f.write(chunk)
    return True

# --- Các hàm liên quan đến cửa sổ ---
def get_window_handle():
    return win32gui.FindWindow(None, 'Counter-Strike 2')

def get_game_window_rect():
    """Trả về (left, top, width, height) của vùng client game."""
    hwnd = get_window_handle()
    if not hwnd:
        return None
    try:
        client_rect = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        return (left, top, client_rect[2], client_rect[3])
    except Exception as e:
        print(f"[Utils] Error getting game window rect: {e}")
        return None

def is_cs2_window_active():
    hwnd = get_window_handle()
    foreground = win32gui.GetForegroundWindow()
    return hwnd == foreground

def forcejump():
    hwnd = get_window_handle()
    win32api.SendMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_SPACE, 0)
    import time
    time.sleep(0.05)
    win32api.SendMessage(hwnd, win32con.WM_KEYUP, win32con.VK_SPACE, 0)

def set_console_visibility(visible):
    """Ẩn hoặc hiện cửa sổ console."""
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, win32con.SW_SHOW if visible else win32con.SW_HIDE)
    except Exception as e:
        print(f"[Utils] Error toggling console: {e}")

# --- Hàm toán học ---
def angle_to_direction(pitch, yaw):
    pitch_rad = math.radians(pitch)
    yaw_rad = math.radians(yaw)
    cos_pitch = math.cos(pitch_rad)
    return (
        math.cos(yaw_rad) * cos_pitch,
        math.sin(yaw_rad) * cos_pitch,
        -math.sin(pitch_rad)
    )

def point_along_direction(start, direction, distance):
    return (
        start[0] + direction[0] * distance,
        start[1] + direction[1] * distance,
        start[2] + direction[2] * distance
    )

def w2s(matrix, x, y, z, width, height):
    screenW = matrix[12]*x + matrix[13]*y + matrix[14]*z + matrix[15]
    if screenW > 0.001:
        screenX = matrix[0]*x + matrix[1]*y + matrix[2]*z + matrix[3]
        screenY = matrix[4]*x + matrix[5]*y + matrix[6]*z + matrix[7]
        camX = width / 2
        camY = height / 2
        x = camX + (camX * screenX / screenW)
        y = camY - (camY * screenY / screenW)
        return [int(x), int(y)]
    return [-999, -999]

# --- Đọc vector từ memory ---
def read_vec2(pm, address):
    data = pm.read_bytes(address, 8)
    return struct.unpack('2f', data) if data else (0,0)

def read_vec3(pm, address):
    data = pm.read_bytes(address, 12)
    return struct.unpack('3f', data) if data else (0,0,0)

# --- Weapon name/icon utilities ---
weapons_type = {
    "weapon_ak47": "AK-47",
    "weapon_m4a1": "M4A1",
    "weapon_awp": "AWP",
    "weapon_elite": "Elite",
    "weapon_famas": "Famas",
    "weapon_flashbang": "Flashbang",
    "weapon_g3sg1": "G3SG1",
    "weapon_galilar": "Galil AR",
    "weapon_healthshot": "Health Shot",
    "weapon_hegrenade": "HE Grenade",
    "weapon_incgrenade": "Incendiary Grenade",
    "weapon_m249": "M249",
    "weapon_m4a1_silencer": "M4A1-S",
    "weapon_mac10": "MAC-10",
    "weapon_mag7": "MAG-7",
    "weapon_molotov": "Molotov",
    "weapon_mp5sd": "MP5-SD",
    "weapon_mp7": "MP7",
    "weapon_mp9": "MP9",
    "weapon_negev": "Negev",
    "weapon_nova": "Nova",
    "weapon_p90": "P90",
    "weapon_sawedoff": "Sawed-Off",
    "weapon_scar20": "SCAR-20",
    "weapon_sg556": "SG 553",
    "weapon_smokegrenade": "Smoke Grenade",
    "weapon_ssg08": "SSG 08",
    "weapon_tagrenade": "TA Grenade",
    "weapon_taser": "Taser",
    "weapon_ump45": "UMP-45",
    "weapon_xm1014": "XM1014",
    "weapon_aug": "AUG",
    "weapon_bizon": "PP-Bizon",
    "weapon_decoy": "Decoy Grenade",
    "weapon_fiveseven": "Five-Seven",
    "weapon_hkp2000": "P2000",
    "weapon_usp_silencer": "USP-S",
    "weapon_p250": "P250",
    "weapon_tec9": "Tec-9",
    "weapon_cz75a": "CZ75-Auto",
    "weapon_deagle": "Desert Eagle",
    "weapon_revolver": "R8 Revolver",
    "weapon_glock": "Glock-18"
}

def get_weapon_type(item_identifier):
    return weapons_type.get(item_identifier, "unknown")

def get_weapon_name(weapon_id):
    if weapon_id > 262100:
        weapon_id = weapon_id - 262144
    weapon_name = {
        1: 'deagle', 2: 'elite', 3: 'fiveseven', 4: 'glock', 7: 'ak47', 8: 'aug', 9: 'awp',
        10: 'famas', 11: 'g3sg1', 13: 'galil', 14: 'm249', 16: 'm4a1', 17: 'mac10', 19: 'p90',
        23: 'ump45', 24: 'ump45', 25: 'xm1014', 26: 'bizon', 27: 'mag7', 28: 'negev', 29: 'sawedoff', 30: 'tec9',
        31: 'taser', 32: 'hkp2000', 33: 'mp7', 34: 'mp9', 35: 'nova', 36: 'p250', 38: 'scar20',
        39: 'sg556', 40: 'ssg08', 42: 'knife_ct', 43: 'flashbang', 44: 'hegrenade', 45: 'smokegrenade',
        46: 'molotov', 47: 'decoy', 48: 'incgrenade', 49: 'c4', 57: 'deagle', 59: 'knife_t', 60: 'm4a1_silencer',
        61: 'usp_silencer', 63: 'cz75a', 64: 'revolver', 500: 'bayonet', 505: 'knife_flip',
        506: 'knife_gut', 507: 'knife_karambit', 508: 'knife_m9_bayonet', 509: 'knife_tactical',
        512: 'knife_falchion', 514: 'knife_survival_bowie', 515: 'knife_butterfly', 516: 'knife_push',
        526: 'knife_kukri'
    }
    return weapon_name.get(weapon_id, None)

def get_weapon_icon(weapon_name):
    if weapon_name:
        weapon_icons_dict = {
            'knife_ct': ']', 'knife_t': '[', 'deagle': 'A', 'elite': 'B', 'fiveseven': 'C',
            'glock': 'D', 'revolver': 'J', 'hkp2000': 'E', 'p250': 'F', 'usp_silencer': 'G',
            'tec9': 'H', 'cz75a': 'I', 'mac10': 'K', 'ump45': 'L', 'bizon': 'M', 'mp7': 'N',
            'mp9': 'P', 'p90': 'O', 'galil': 'Q', 'famas': 'R', 'm4a1_silencer': 'T', 'm4a1': 'S',
            'aug': 'U', 'sg556': 'V', 'ak47': 'W', 'g3sg1': 'X', 'scar20': 'Y', 'awp': 'Z',
            'ssg08': 'a', 'xm1014': 'b', 'sawedoff': 'c', 'mag7': 'd', 'nova': 'e', 'negev': 'f',
            'm249': 'g', 'taser': 'h', 'flashbang': 'i', 'hegrenade': 'j', 'smokegrenade': 'k',
            'molotov': 'l', 'decoy': 'm', 'incgrenade': 'n', 'c4': 'o', 'mp5': 'z',
        }
        return weapon_icons_dict.get(weapon_name, None)
    return None

# --- Drawing utilities ---
def draw_line(draw_list, x1, y1, x2, y2, color, thickness=1.0):
    col = imgui.get_color_u32_rgba(*color)
    draw_list.add_line(x1, y1, x2, y2, col, thickness)

def draw_circle_outline(draw_list, x, y, radius, color, thickness=1.0):
    col = imgui.get_color_u32_rgba(*color)
    draw_list.add_circle(x, y, radius, col, 0, thickness)

def draw_circle_filled(draw_list, x, y, radius, color):
    col = imgui.get_color_u32_rgba(*color)
    draw_list.add_circle_filled(x, y, radius, col)

def draw_rect_outline(draw_list, x1, y1, x2, y2, color, thickness=1.0):
    col = imgui.get_color_u32_rgba(*color)
    draw_list.add_rect(x1, y1, x2, y2, col, 0, thickness)

def draw_rect_filled(draw_list, x1, y1, x2, y2, color):
    col = imgui.get_color_u32_rgba(*color)
    draw_list.add_rect_filled(x1, y1, x2, y2, col)

def draw_text(draw_list, x, y, text, color, font=None, shadow=True):
    if font:
        imgui.push_font(font)
    if shadow:
        shadow_col = imgui.get_color_u32_rgba(0,0,0,1)
        draw_list.add_text(x+1, y+1, shadow_col, text)
    text_col = imgui.get_color_u32_rgba(*color)
    draw_list.add_text(x, y, text_col, text)
    if font:
        imgui.pop_font()