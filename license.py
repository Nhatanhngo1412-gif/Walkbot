import requests
import uuid
import time
import json
import os
from core.utils import get_data_path

CACHE_FILE = os.path.join(get_data_path(), "license_cache.json")
CACHE_EXPIRY = 24 * 3600  # 24 giờ

def get_hwid():
    """Lấy địa chỉ MAC làm HWID (có thể thay bằng cách khác nếu muốn)"""
    return str(uuid.getnode())

def check_license(key):
    # Nếu key là "123123" → luôn đúng
    if key == "123123":
        print("[License] Using custom key 123123.")
        return True

    # Phần còn lại giữ nguyên (kiểm tra cache và server)
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                if cache.get('key') == key and cache.get('hwid') == get_hwid():
                    if time.time() - cache.get('timestamp', 0) < CACHE_EXPIRY:
                        print("[License] Using cached valid license.")
                        return True
        except:
            pass

    url = "https://server-alaa.onrender.com/api/verify"
    hwid = get_hwid()
    try:
        response = requests.get(url, params={"key": key, "hwid": hwid}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                # Lưu cache
                try:
                    with open(CACHE_FILE, 'w') as f:
                        json.dump({
                            'key': key,
                            'hwid': hwid,
                            'timestamp': time.time()
                        }, f)
                except:
                    pass
                return True
            else:
                print("[License] Server returned error:", data.get("error", "Unknown"))
        elif response.status_code == 401:
            print("[License] Invalid or expired key.")
        else:
            print(f"[License] Server error: HTTP {response.status_code}")
    except requests.exceptions.Timeout:
        print("[License] Connection timeout. Check your internet.")
    except requests.exceptions.ConnectionError:
        print("[License] Cannot connect to license server.")
    except Exception as e:
        print(f"[License] Unexpected error: {e}")
    return False