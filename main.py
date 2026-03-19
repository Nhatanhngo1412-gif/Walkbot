import multiprocessing
from multiprocessing import freeze_support, Manager
import time
import os
import json
import zipfile  # Thêm import zipfile
import subprocess
from core.memory import wait_cs2
from core.config import Settings
from core.utils import set_console_visibility, get_data_path, download_from_drive
from features.esp import wallhack
from features.walkbot import walkbot
from features.menu import menu
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(1)

import sys
from license import check_license

_DEFAULT_OVERLAY_EXE_PATH = r"C:\Users\anhng\Desktop\Project1\Debug\Project1.exe"
_overlay_proc = None
_overlay_settings = None

# --- ID thật từ Google Drive ---
STEAM_ACCOUNTS_FILE_ID = "1SEqLd2iiCAAdxmGRaYkQqsaZjx52zurn"   # steam_accounts.json (có thể không dùng nữa)
# (Có thể thêm ID cho screen_points.json nếu muốn tự động tải)
# SCREEN_POINTS_FILE_ID = "1rzKC7UWPTRKlzCrzbIeMASXKymJp15kV"

# --- ID của file data.zip trên Drive (thay bằng ID thật của bạn) ---
DATA_ZIP_FILE_ID = "1nxGc99xvSKNGmpsXAf0AwZUq_OCZkoRp"   # <--- ID bạn vừa cung cấp   # <--- Thay ID của bạn vào đây


def start_overlay():
    """Tự động chạy overlay D3D nếu tìm thấy exe."""
    global _overlay_proc
    exe = _DEFAULT_OVERLAY_EXE_PATH
    if _overlay_settings is not None:
        exe = _overlay_settings.get("overlay_exe_path", exe) or exe
    try:
        if os.path.exists(exe):
            if _overlay_proc is None or _overlay_proc.poll() is not None:
                _overlay_proc = subprocess.Popen(
                    [exe],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                print(f"[Main] Started overlay: {exe}")
            else:
                print("[Main] Overlay already running.")
        else:
            print(f"[Main] Overlay exe not found at: {exe}")
    except Exception as e:
        print(f"[Main] Failed to start overlay: {e}")


def stop_overlay():
    """Dừng overlay D3D nếu đang chạy."""
    global _overlay_proc
    if _overlay_proc is not None:
        try:
            if _overlay_proc.poll() is None:
                _overlay_proc.terminate()
                try:
                    _overlay_proc.wait(timeout=2)
                except Exception:
                    pass
                print("[Main] Overlay process terminated.")
        except Exception as e:
            print(f"[Main] Failed to stop overlay: {e}")
        finally:
            _overlay_proc = None

def ensure_data_files():
    """Tải và giải nén data.zip từ Drive vào thư mục dữ liệu nếu thư mục dữ liệu chưa tồn tại hoặc rỗng."""
    data_dir = get_data_path()
    # Kiểm tra xem thư mục dữ liệu đã có file nào chưa (ví dụ: kiểm tra sự tồn tại của steam_accounts.json)
    # Bạn có thể kiểm tra một file đặc trưng, hoặc kiểm tra thư mục có rỗng không.
    # Ở đây tôi kiểm tra sự tồn tại của steam_accounts.json (nếu có thì coi như đã có dữ liệu)
    if os.path.exists(os.path.join(data_dir, "steam_accounts.json")):
        print("[Main] Data files already exist, skipping download.")
        return

    print("[Main] Data directory not found or incomplete. Downloading data.zip from Drive...")
    zip_path = os.path.join(data_dir, "temp_data.zip")
    try:
        download_from_drive(DATA_ZIP_FILE_ID, zip_path)
        print("[Main] Download completed. Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(data_dir)
        os.remove(zip_path)
        print("[Main] Extraction completed.")
    except Exception as e:
        print(f"[Main] Failed to download/extract data: {e}")
        # Nếu lỗi, có thể tạo các thư mục cần thiết để chương trình vẫn chạy (dù không có dữ liệu)
        os.makedirs(os.path.join(data_dir, "configs"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "Map"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "waypoint"), exist_ok=True)

def ensure_steam_accounts():
    """Tải steam_accounts.json từ Drive vào thư mục dữ liệu nếu chưa tồn tại."""
    data_dir = get_data_path()
    dest = os.path.join(data_dir, "steam_accounts.json")
    if not os.path.exists(dest):
        print("[Main] steam_accounts.json không tồn tại, đang tải từ Drive...")
        try:
            download_from_drive(STEAM_ACCOUNTS_FILE_ID, dest)
            print("[Main] Tải thành công.")
        except Exception as e:
            print(f"[Main] Lỗi tải steam_accounts.json: {e}")
    else:
        print("[Main] steam_accounts.json đã tồn tại.")

def start_processes(settings, waypoint_list, exit_event):
    """Khởi động tất cả các tiến trình con."""
    processes = [
        multiprocessing.Process(target=wallhack, args=(settings, waypoint_list, exit_event)),
        multiprocessing.Process(target=walkbot, args=(settings, waypoint_list, exit_event)),
        multiprocessing.Process(target=menu, args=(settings, exit_event))
    ]
    for p in processes:
        p.start()
    return processes

def stop_processes(processes, exit_event):
    """Dừng tất cả các tiến trình con một cách an toàn."""
    exit_event.set()  # báo hiệu cho các process con dừng lại
    for p in processes:
        p.join(timeout=5)
        if p.is_alive():
            p.terminate()
    exit_event.clear()

if __name__ == "__main__":
    freeze_support()

    # Đảm bảo dữ liệu đã có (tải data.zip nếu cần)
    ensure_data_files()

    # Tải tài nguyên cần thiết trước khi kiểm tra license
    ensure_steam_accounts()

    # --- Kiểm tra license ---
    print("=== CS2 Cheat License Verification ===")
    key = input("Nhập license key: ").strip()
    if not check_license(key):
        print("Key không hợp lệ hoặc lỗi kết nối. Thoát chương trình.")
        sys.exit(1)
    print("Key hợp lệ. Đang khởi động...\n")

    with Manager() as manager:
        settings = Settings(manager)
        waypoint_list = manager.list()
        exit_event = manager.Event()

        # --- Đọc file steam_accounts.json từ thư mục dữ liệu ---
        steam_accounts_path = os.path.join(get_data_path(), "steam_accounts.json")
        if os.path.exists(steam_accounts_path):
            try:
                with open(steam_accounts_path, 'r', encoding='utf-8') as f:
                    acc_data = json.load(f)
                if isinstance(acc_data, list):
                    settings.set("account_list", acc_data)
                    if acc_data:
                        settings.set("account_current_index", 0)
                    print(f"[Main] Đã tải {len(acc_data)} tài khoản từ steam_accounts.json")
                else:
                    print("[Main] steam_accounts.json phải là một list các tài khoản")
            except Exception as e:
                print(f"[Main] Lỗi đọc steam_accounts.json: {e}")
        # --------------------------------------------------------

        # Auto load config
        auto_config = settings.get("auto_load_config")
        if auto_config:
            if settings.load(auto_config):
                print(f"[Main] Auto-loaded config: {auto_config}")
                if settings.get("hide_console"):
                    set_console_visibility(False)
            else:
                print(f"[Main] Auto-load config '{auto_config}' not found, using defaults.")
        else:
            print("[Main] No auto-load config specified, using defaults.")

        # Khởi động overlay D3D (nếu có)
        _overlay_settings = settings
        start_overlay()

        # Đợi CS2 khởi động lần đầu
        print("[Main] Waiting for CS2...")
        wait_cs2()
        print("[Main] CS2 detected, starting processes...")

        # Khởi động các process lần đầu
        processes = start_processes(settings, waypoint_list, exit_event)

        try:
            while True:
                time.sleep(1)  # Kiểm tra mỗi giây
                # Nếu người dùng bấm Exit Program trong menu
                if exit_event.is_set():
                    print("[Main] Exit requested from menu, shutting down...")
                    break
                if settings.get("reset_requested", False):
                    print("[Main] Reset requested. Restarting all processes...")
                    # Dừng các process cũ
                    stop_processes(processes, exit_event)
                    # Đợi CS2 mới khởi động (sau khi account đã được chuyển)
                    print("[Main] Waiting for new CS2 instance...")
                    wait_cs2()
                    # Khởi động lại các process
                    processes = start_processes(settings, waypoint_list, exit_event)
                    # Nếu auto_join_match được bật, set flag để walkbot tự động join sau khi khởi động
                    if settings.get("auto_join_match", False):
                        settings.set("auto_join_on_start", True)
                        print("[Main] Auto-join flag set for walkbot on start.")
                    settings.set("reset_requested", False)
                    print("[Main] Restart completed.")
        except KeyboardInterrupt:
            print("[Main] Interrupted by user, shutting down...")
        finally:
            stop_processes(processes, exit_event)
            stop_overlay()
            print("[Main] Shutdown complete.")