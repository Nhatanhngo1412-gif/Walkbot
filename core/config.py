import os
import json
from multiprocessing import Lock, Manager

class Settings:
    def __init__(self, manager):
        self._lock = Lock()
        self.config_dir = "configs"
        self._data = manager.dict({
            # --- Cài đặt ESP ---
            "esp_enable": True,
            "esp_visible_check": True,
            "esp_box": True,
            "esp_filled_box": True,
            "esp_corners": True,
            "esp_skeleton": True,
            "esp_names": True,
            "esp_teammates": False,
            "esp_weapons": True,
            "esp_health_bar": True,
            "esp_armor_bar": True,
            "esp_head_dot": True,
            "esp_snap_lines": False,
            "esp_eye_lines": True,
            "esp_dropped_weapons": False,

            # --- Màu sắc ESP ---
            "esp_ally_color": (0.0, 1.0, 0.0, 0.8),
            "esp_enemy_color": (1.0, 0.0, 0.0, 0.8),
            "esp_ally_snapline_color": (0.0, 1.0, 0.0, 0.5),
            "esp_enemy_snapline_color": (1.0, 0.0, 0.0, 0.5),
            "esp_box_border_color": (0.1, 0.1, 0.1, 0.8),
            "esp_box_fill_normal_color": (0.23, 0.2, 0.19, 0.4),
            "esp_box_fill_spotted_color": (0.23, 0.3, 0.19, 0.4),
            "esp_box_fill_immune_color": (0.83, 0.3, 0.19, 0.4),
            "esp_health_bar_color": (1.0, 0.0, 0.0, 0.9),
            "esp_health_bar_bg_color": (0.0, 0.0, 0.0, 0.7),
            "esp_armor_bar_color": (0.05, 0.27, 0.56, 0.9),
            "esp_head_dot_color": (1.0, 0.0, 0.0, 0.7),
            "esp_skeleton_color": (1.0, 1.0, 1.0, 1.0),
            "esp_name_color": (1.0, 1.0, 1.0, 1.0),
            "esp_weapon_color": (1.0, 1.0, 1.0, 1.0),
            "esp_eye_line_color": (1.0, 1.0, 1.0, 0.7),
            "esp_dropped_weapon_color": (1.0, 1.0, 1.0, 1.0),
            "esp_fov_color": (1.0, 1.0, 1.0, 0.7),
            "esp_crosshair_color": (0.0, 1.0, 0.0, 1.0),

            # --- Walkbot ---
            "walkbot_enable": False,
            "show_waypoints": False,
            "friendly_fire": False,
            "dm_mode": True,
            "walkbot_shot_delay": 0.1,
            "walkbot_aim_speed": 15.0,
            "headshot_rate": 100.0,
            "dm_burst_count": 3,
            "dm_burst_cooldown_min": 0.3,
            "dm_burst_cooldown_max": 0.5,

            # --- Account Switcher ---
            "account_switch_enable": False,
            "account_switch_after_maps": 1,
            "account_list": [],               # danh sách dict
            "account_current_index": 0,
            "account_switch_request": -1,      # -1 = không có request, >=0 là index cần chuyển
            "auto_join_match": False,          # Tự động tìm trận sau khi đổi acc
            "temp_auto_join": False,           # Cờ tạm thời cho nút test
            "auto_join_points": [],             # Danh sách điểm auto join [{"x": float, "y": float} hoặc {"x_rel": float, "y_rel": float}]
            "point_add_hotkey": "F9",           # Phím tắt thêm điểm
            "bulk_accounts_text": "",           # Text để nhập hàng loạt account

            # --- Team selection (mới) ---
            "auto_select_team": False,          # Tự động chọn team khi map thay đổi
            "team_preference": 1,                # 1 = T, 2 = CT
            "execute_team_t_request": False,     # Cờ yêu cầu chọn T thủ công
            "execute_team_ct_request": False,    # Cờ yêu cầu chọn CT thủ công

            # --- System ---
            "config_profile": 0,
            "hide_console": False,
            "auto_load_config": "1.json",
            "overlay_exe_path": r"C:\Users\anhng\Desktop\Project1\Debug\Project1.exe",
            
            # --- Reset signal ---
            "reset_requested": False,
        })

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._data[key] = value

    def save(self, filename):
        if not filename.endswith(".json"):
            filename += ".json"
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        filepath = os.path.join(self.config_dir, filename)

        with self._lock:
            config_data = dict(self._data)

        with open(filepath, 'w') as f:
            json.dump(config_data, f, indent=4)
        return True

    def load(self, filename):
        if not filename.endswith(".json"):
            filename += ".json"
        filepath = os.path.join(self.config_dir, filename)
        if not os.path.exists(filepath):
            return False

        with open(filepath, 'r') as f:
            config_data = json.load(f)

        with self._lock:
            for key, value in config_data.items():
                self._data[key] = value
        return True

    def list_configs(self):
        if not os.path.exists(self.config_dir):
            return ["Không tìm thấy config"]
        files = [f for f in os.listdir(self.config_dir) if f.endswith(".json")]
        return files if files else ["Không tìm thấy config"]