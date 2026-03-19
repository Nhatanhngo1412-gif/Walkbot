import ctypes
import os
from .utils import download_and_extract_zip, get_base_path

class RayTracer:
    def __init__(self, dll_name="raytracer.dll"):
        # Xác định đường dẫn DLL
        current_file = os.path.abspath(__file__)
        core_dir = os.path.dirname(current_file)
        project_dir = os.path.dirname(core_dir)

        self.dll_path = os.path.join(project_dir, dll_name)
        self.dll = None
        self.current_map_path = None

        # File ID của maps.zip trên Drive (thay bằng ID thật của bạn)
        self.Map_zip_id = "1YQccTQ3pttblV5RSICs4vIq37fStoN9"  # <--- Thay ID thật

        if not os.path.exists(self.dll_path):
            print(f"[RayTracer] Warning: {dll_name} not found at {self.dll_path}")
            return

        try:
            self.dll = ctypes.CDLL(self.dll_path)

            # --- CẤU HÌNH HÀM C++ ---
            try:
                self.func_load_map = self.dll.LoadMap
                self.func_load_map.argtypes = [ctypes.c_char_p]
                self.func_load_map.restype = ctypes.c_bool
            except AttributeError:
                print("[RayTracer] Error: Function 'LoadMap' not found in DLL.")

            try:
                self.func_is_visible = self.dll.IsVisible
                self.func_is_visible.argtypes = [
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,
                    ctypes.c_float, ctypes.c_float, ctypes.c_float
                ]
                self.func_is_visible.restype = ctypes.c_bool
            except AttributeError:
                print("[RayTracer] Error: Function 'IsVisible' not found in DLL.")

            print(f"[RayTracer] Loaded {dll_name} successfully.")

        except Exception as e:
            print(f"[RayTracer] Critical Error loading DLL: {e}")
            self.dll = None

    def ensure_map_files(self):
        """Đảm bảo thư mục map tồn tại và có các file .tri.
        Nếu chưa có, tải maps.zip từ Drive và giải nén."""
        base = get_base_path()
        map_dir = os.path.join(base, "map")

        # Nếu thư mục map chưa tồn tại hoặc rỗng, tải về
        if not os.path.exists(map_dir) or not os.listdir(map_dir):
            print("[RayTracer] Thư mục map chưa có, đang tải maps.zip từ Drive...")
            if download_and_extract_zip(self.maps_zip_id, base):
                print("[RayTracer] Tải và giải nén maps.zip thành công.")
                return True
            else:
                print("[RayTracer] Không thể tải maps.zip.")
                return False
        return True

    def load_map(self, map_name):
        if not self.dll:
            return False

        # Đảm bảo các file map đã có
        if not self.ensure_map_files():
            return False

        base = get_base_path()
        map_file_path = os.path.join(base, "map", f"{map_name}.tri")

        # Kiểm tra file map cụ thể có tồn tại không
        if not os.path.exists(map_file_path):
            print(f"[RayTracer] File {map_name}.tri không tồn tại trong thư mục map.")
            return False

        # Nếu đã load rồi thì thôi
        if self.current_map_path == map_file_path:
            return True

        print(f"[RayTracer] Loading mesh: {map_name}.tri ...")
        try:
            c_path = map_file_path.encode('utf-8')
            success = self.func_load_map(c_path)
            if success:
                self.current_map_path = map_file_path
                print(f"[RayTracer] Map loaded successfully.")
            else:
                print(f"[RayTracer] DLL failed to load map (returned False).")
            return success
        except Exception as e:
            print(f"[RayTracer] Exception in load_map: {e}")
            return False

    def is_visible(self, start_vec, end_vec):
        """
        start_vec: tuple (x, y, z) - Mắt mình
        end_vec: tuple (x, y, z) - Đầu địch
        """
        if not self.dll:
            return True

        if not self.current_map_path:
            return True

        return self.func_is_visible(
            start_vec[0], start_vec[1], start_vec[2],
            end_vec[0], end_vec[1], end_vec[2]
        )

# --- Biến toàn cục dùng chung ---
raytracer = RayTracer()