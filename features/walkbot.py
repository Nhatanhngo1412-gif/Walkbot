import time
import math
import json
import os
import struct
import win32api
import win32con
import win32gui
import random
import threading
import psutil

# Thử import noise, nếu không có thì dùng phương án thay thế
try:
    import noise
    HAS_NOISE = True
except ImportError:
    HAS_NOISE = False
    print("[Walkbot] Noise library not installed, using fallback jitter.")

from core.memory import get_memory_reader
from core.utils import is_cs2_window_active, get_window_handle, get_game_window_rect, angle_to_direction, get_data_path
from core.raytracer import raytracer
from core.visibility_cache import vis_cache
from core.account import SteamAccountManager, SteamAccount
from offsets import (
    dwViewAngles, m_pGameSceneNode, m_vecOrigin, dwLocalPlayerPawn,
    dwEntityList, m_hPlayerPawn, m_iTeamNum, m_iHealth, m_lifeState,
    m_vecViewOffset, m_bGunGameImmunity, m_modelState, m_iShotsFired,
    m_aimPunchAngle, m_iIDEntIndex, m_AttributeManager, m_Item, m_iItemDefinitionIndex
)

WAYPOINT_DIR = os.path.join(get_data_path(), "waypoint")
os.makedirs(WAYPOINT_DIR, exist_ok=True)

# --- Hằng số jitter dạng sóng sin (chỉ dùng cho combat) ---
MOVE_JITTER = 1.2          # Biên độ rung (độ) - giảm để bớt giật
JITTER_FREQ = 2.5          # Tần số rung (Hz) – tăng nhẹ

def get_waypoint_filename(map_name):
    return os.path.join(WAYPOINT_DIR, f"waypoints_{map_name}.json")

def release_movement_keys(hwnd=None):
    if hwnd is None:
        hwnd = get_window_handle()
    keys = [0x57, 0x41, 0x53, 0x44]  # W, A, S, D
    for key in keys:
        win32api.SendMessage(hwnd, win32con.WM_KEYUP, key, 0)
        win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)

class Walkbot:
    def __init__(self, settings, waypoint_list):
        self.settings = settings
        self.waypoint_list = waypoint_list
        self.waypoints = []
        self.current_idx = 0
        self.current_map = ""
        self.last_map_check = 0
        self.enabled = False
        self.prev_enabled = False
        self.hwnd = None
        self.pm = None
        self.client = None

        self.waypoint_threshold = 100.0

        # Combat parameters
        self.max_engage_distance = 10000.0
        self.max_shoot_distance = 3000.0
        self.last_shot_time = 0
        self.tgb_next_action_time = 0

        self.recording = False
        self.last_recorded_pos = None
        self.record_threshold = 30.0

        self.was_dead = False

        self.last_buy_time = 0
        self.buy_cooldown = 5.0

        # Target locking (simplified)
        self.current_target_pawn = 0
        self.current_target_pos = None
        self.last_target_time = 0
        self.target_lock_duration = 2.0

        # Account switching
        self.account_manager = SteamAccountManager()
        self.auto_switch_accounts = False
        self.switch_map_count = 5
        self.map_play_count = 0
        self.is_switching_account = False

        # Load accounts from settings into manager
        acc_list = self.settings.get("account_list", [])
        if acc_list:
            self.account_manager.accounts = [SteamAccount.from_dict(acc) for acc in acc_list]
        self.account_manager.current_account_index = self.settings.get("account_current_index", 0)

        # Key state tracking
        self._key_states = {'W': False, 'A': False, 'S': False, 'D': False}

        # --- Các cờ để giới hạn in ấn theo map ---
        self.buy_printed_this_map = False
        self.respawn_message_printed = False
        self.spawn_snap_message_printed = False

        # --- Biến cho jitter dạng sóng (chỉ dùng trong combat) ---
        self.noise_offset = random.uniform(0, 1000)  # offset cho noise

        # --- Các biến liên quan đến hành vi phụ khi di chuyển đã bị xóa ---

        # --- Smooth movement look ---
        self._last_move_look_time = 0.0
        self._last_wp_dist = None
        self._wp_dist_increase_count = 0
        self._had_target_prev_frame = False

        # Burst fire state
        self.burst_active = False
        self.burst_start_shots = 0
        self.burst_start_time = 0.0
        self.burst_cooldown_until = 0.0

    # ---------- Helper functions ----------
    def normalize_angle(self, angle):
        while angle > 180:
            angle -= 360
        while angle < -180:
            angle += 360
        return angle

    def get_aim_angles(self, from_pos, to_pos):
        dx = to_pos[0] - from_pos[0]
        dy = to_pos[1] - from_pos[1]
        dz = to_pos[2] - from_pos[2]
        dist_2d = math.hypot(dx, dy)
        pitch = math.degrees(math.atan2(-dz, dist_2d))
        yaw = math.degrees(math.atan2(dy, dx))
        return pitch, yaw

    def get_local_pos(self, pm, client, local_player=None):
        if local_player is None:
            local_player = pm.read_longlong(client + dwLocalPlayerPawn)
            if not local_player:
                return None
        game_scene = pm.read_longlong(local_player + m_pGameSceneNode)
        if not game_scene:
            return None
        x = pm.read_float(game_scene + m_vecOrigin)
        if x is None:
            return None
        y = pm.read_float(game_scene + m_vecOrigin + 4)
        if y is None:
            return None
        z = pm.read_float(game_scene + m_vecOrigin + 8)
        if z is None:
            return None
        return (x, y, z)

    def _get_local_eye_pos(self, pm, client, local_player=None):
        if local_player is None:
            local_player = pm.read_longlong(client + dwLocalPlayerPawn)
            if not local_player:
                return None
        game_scene = pm.read_longlong(local_player + m_pGameSceneNode)
        if not game_scene:
            return None
        ox = pm.read_float(game_scene + m_vecOrigin)
        if ox is None:
            return None
        oy = pm.read_float(game_scene + m_vecOrigin + 4)
        if oy is None:
            return None
        oz = pm.read_float(game_scene + m_vecOrigin + 8)
        if oz is None:
            return None
        vz = pm.read_float(local_player + m_vecViewOffset + 8)
        if vz is None:
            return None
        return (ox, oy, oz + vz)

    def _get_bone_pos(self, pm, pawn, bone_id):
        game_scene = pm.read_longlong(pawn + m_pGameSceneNode)
        if not game_scene:
            return None
        bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
        if not bone_matrix:
            return None
        data = pm.read_bytes(bone_matrix + bone_id * 0x20, 12)
        if data:
            return struct.unpack('fff', data)
        return None

    # ---------- Account switching logic ----------
    def check_account_switch(self, new_map):
        if self.auto_switch_accounts:
            self.map_play_count += 1
            if self.map_play_count >= self.switch_map_count:
                self.switch_to_next_account()
                self.map_play_count = 0

    # ---------- Team selection (mới) ----------
    def _bring_window_to_foreground(self, hwnd):
        for _ in range(5):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            if win32gui.GetForegroundWindow() == hwnd:
                return True
        return False

    def _send_team_select(self, team):
        """Gửi tổ hợp phím chọn team: M + (1 cho T, 2 cho CT)"""
        hwnd = get_window_handle()
        if not hwnd:
            print("[Walkbot] No game window found")
            return False

        if not self._bring_window_to_foreground(hwnd):
            print("[Walkbot] Could not bring game window to foreground")
            return False

        time.sleep(0.3)

        win32api.SendMessage(hwnd, win32con.WM_KEYDOWN, ord('M'), 0)
        time.sleep(0.1)
        win32api.SendMessage(hwnd, win32con.WM_KEYUP, ord('M'), 0)
        time.sleep(0.3)

        key = ord('1') if team == 1 else ord('2')
        win32api.SendMessage(hwnd, win32con.WM_KEYDOWN, key, 0)
        time.sleep(0.1)
        win32api.SendMessage(hwnd, win32con.WM_KEYUP, key, 0)

        print(f"[Walkbot] Sent team selection: {'T' if team==1 else 'CT'}")
        return True

    # ---------- Combat functions ----------
    def find_aimlock_target(self, pm, client, local_player, local_eye, local_yaw, local_pitch, entities):
        is_auto_walking = self.enabled
        base_fov = self.settings.get('fovvalue', 50.0)
        current_fov = 360.0 if is_auto_walking else base_fov
        target_info = None
        min_metric = float('inf')
        local_team = pm.read_int(local_player + m_iTeamNum)
        if local_team is None:
            return None
        friendly_fire = self.settings.get('friendly_fire', False)
        headshot_rate = self.settings.get('headshot_rate', 100.0)

        for ent in entities:
            if ent['team'] == local_team and not friendly_fire:
                continue
            if ent['immune']:
                continue
            try:
                aim_bone = 6
                pseudo_random = (ent.get('index', 1) * 123456789) % 100
                # Dùng < để khi headshot_rate = 0% thì không bao giờ head (pseudo_random 0..99)
                should_hit_head = pseudo_random < headshot_rate
                secondary_bone = 4 if (ent.get('index', 1) % 2 == 0) else 2

                visible = ent.get('is_visible', True)
                if self.settings.get('esp_visible_check', True):
                    visible = ent.get('is_visible', False)
                if not visible:
                    continue

                if should_hit_head:
                    aim_bone = 6
                else:
                    aim_bone = secondary_bone

                target_pos = self._get_bone_pos(pm, ent['pawn'], aim_bone)
                if not target_pos:
                    continue

                if aim_bone == 6:
                    target_pos = (target_pos[0], target_pos[1], target_pos[2] + 1)

                t_pitch, t_yaw = self.get_aim_angles(local_eye, target_pos)

                if is_auto_walking:
                    dx = target_pos[0] - local_eye[0]
                    dy = target_pos[1] - local_eye[1]
                    dz = target_pos[2] - local_eye[2]
                    dist_sq = dx*dx + dy*dy + dz*dz
                    if dist_sq < min_metric and dist_sq < self.max_engage_distance**2:
                        min_metric = dist_sq
                        target_info = {
                            'aim_pitch': t_pitch,
                            'aim_yaw': t_yaw,
                            'bone': aim_bone,
                            'pawn': ent['pawn'],
                            'pos': target_pos
                        }
                else:
                    pitch_diff = abs(self.normalize_angle(t_pitch - local_pitch))
                    yaw_diff = abs(self.normalize_angle(t_yaw - local_yaw))
                    diff = math.hypot(pitch_diff, yaw_diff)
                    if diff < current_fov and diff < min_metric:
                        min_metric = diff
                        target_info = {
                            'aim_pitch': t_pitch,
                            'aim_yaw': t_yaw,
                            'bone': aim_bone,
                            'pawn': ent['pawn'],
                            'pos': target_pos
                        }
            except Exception:
                continue
        return target_info

    def perform_aimlock(self, pm, client, target_info, local_player, local_pitch, local_yaw, local_shots_fired):
        is_auto_walking = self.enabled
        smoothness = self.settings.get('walkbot_aim_speed', 15.0)
        dm_mode = self.settings.get('dm_mode', False)

        pitch_diff = self.normalize_angle(target_info['aim_pitch'] - local_pitch)
        yaw_diff = self.normalize_angle(target_info['aim_yaw'] - local_yaw)
        dist_angle = math.hypot(pitch_diff, yaw_diff)

        # Đang di chuyển mà địch lộ: góc lệch lớn -> aim nhanh (snap). Góc nhỏ -> mượt.
        need_fast_snap = (is_auto_walking and dist_angle > 28.0) or (not is_auto_walking)

        if is_auto_walking and not need_fast_snap:
            # Đã gần hướng, aim mượt
            target_pitch = target_info['aim_pitch']
            target_yaw = target_info['aim_yaw']
            if local_shots_fired > 1:
                try:
                    aim_punch_x = pm.read_float(local_player + m_aimPunchAngle)
                    aim_punch_y = pm.read_float(local_player + m_aimPunchAngle + 4)
                    if aim_punch_x is not None and aim_punch_y is not None:
                        target_pitch -= (aim_punch_x * 2.0)
                        target_yaw -= (aim_punch_y * 2.0)
                except:
                    pass
            max_speed = smoothness * 2.2
            base_pitch = self._smooth_angle_easing(local_pitch, target_pitch, max_speed * 0.7, 0.25)
            base_yaw = self._smooth_angle_easing(local_yaw, target_yaw, max_speed, 0.25)
            tiny_jitter = max(0.0, min(0.4, smoothness / 60.0))
            if tiny_jitter > 0:
                t = time.time()
                base_yaw = self._natural_jitter(base_yaw, tiny_jitter, 1.5, t)
                base_pitch = self._natural_jitter(base_pitch, tiny_jitter * 0.5, 1.8, t)
            final_pitch = base_pitch
            final_yaw = base_yaw
        elif need_fast_snap:
            # Aim nhanh: DM hoặc địch vừa lộ khi đang chạy (góc > 28°) -> dùng divisor nhỏ
            if dm_mode or (is_auto_walking and dist_angle > 28.0):
                if dist_angle > 60.0:
                    divisor = max(1.0, 10.0 / smoothness)
                else:
                    divisor = max(1.0, 14.0 / smoothness)
                final_pitch = local_pitch + (pitch_diff / divisor)
                final_yaw = local_yaw + (yaw_diff / divisor)
            else:
                base_divisor = max(1.0, 25.0 / smoothness)
                dynamic_smooth = base_divisor + (3.0 / (dist_angle + 0.1))
                if local_shots_fired > 1:
                    dynamic_smooth = 1.0
                final_pitch = local_pitch + (pitch_diff / dynamic_smooth)
                final_yaw = local_yaw + (yaw_diff / dynamic_smooth)

        # Norecoil: khi đang bắn (đặc biệt sấy người), trừ aim punch + kéo xuống thêm để spray không quá lên trên
        aim_bone = target_info.get('bone', 6)
        if local_shots_fired > 0:
            try:
                aim_punch_x = pm.read_float(local_player + m_aimPunchAngle)
                aim_punch_y = pm.read_float(local_player + m_aimPunchAngle + 4)
                if aim_punch_x is not None and aim_punch_y is not None:
                    # Sấy người: bù rất mạnh (AK/M4 recoil dọc cao) + kéo xuống theo số viên
                    if aim_bone != 6:
                        scale = 3.5
                        extra_pull = min(15, local_shots_fired) * 0.28
                        final_pitch -= (aim_punch_x * scale) + extra_pull
                        final_yaw -= (aim_punch_y * scale)
                    else:
                        scale = 1.5
                        final_pitch -= (aim_punch_x * scale)
                        final_yaw -= (aim_punch_y * scale)
            except Exception:
                pass

        if final_pitch > 89:
            final_pitch = 89
        if final_pitch < -89:
            final_pitch = -89

        pm.write_float(client + dwViewAngles, final_pitch)
        pm.write_float(client + dwViewAngles + 4, final_yaw)

    def shoot_worker(self, should_spray, delay_ms):
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        if should_spray:
            time.sleep(random.uniform(0.30, 0.45))
        else:
            time.sleep(random.uniform(0.05, 0.08))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def perform_triggerbot(self, pm, client, local_player, local_team, target_bone=None):
        now = time.time()
        if now < self.tgb_next_action_time:
            return

        try:
            target_id = pm.read_int(local_player + m_iIDEntIndex)
            if target_id is None or target_id <= 0:
                return

            ent_list = pm.read_longlong(client + dwEntityList)
            if not ent_list:
                return
            entry = pm.read_longlong(ent_list + 0x8 * (target_id >> 9) + 0x10)
            if not entry:
                return
            pawn = pm.read_longlong(entry + 112 * (target_id & 0x1FF))
            if not pawn:
                return

            hp = pm.read_int(pawn + m_iHealth)
            if hp is None or hp <= 0:
                return
            team = pm.read_int(pawn + m_iTeamNum)
            if team is None:
                return
            friendly_fire = self.settings.get('friendly_fire', False)
            if team == local_team and not friendly_fire:
                return

            should_spray = False
            # Nếu đang aim vào đầu -> tap, nếu aim vào thân -> spray
            if target_bone is not None:
                should_spray = (target_bone != 6)

            hold_time = 0.40 if should_spray else 0.08
            cooldown = random.uniform(0.15, 0.25)
            delay = self.settings.get('walkbot_shot_delay', 0.1) * 1000

            self.tgb_next_action_time = now + delay/1000.0 + hold_time + cooldown

            t = threading.Thread(target=self.shoot_worker, args=(should_spray, delay))
            t.daemon = True
            t.start()
        except Exception:
            pass

    # ---------- Smooth angle easing ----------
    def _smooth_angle_easing(self, current, target, max_speed, ease_factor=0.2):
        diff = self.normalize_angle(target - current)
        abs_diff = abs(diff)
        if abs_diff < 0.1:
            return target
        t = min(abs_diff / 180.0, 1.0)
        speed_factor = 3*t*t - 2*t*t*t
        speed = max_speed * (ease_factor + (1 - ease_factor) * speed_factor)
        speed = min(speed, abs_diff)
        return current + math.copysign(speed, diff)

    # ---------- Natural jitter using sin + noise ----------
    def _natural_jitter(self, base_angle, magnitude, freq, t):
        """Kết hợp sin và noise (nếu có) để tạo dao động tự nhiên"""
        sin_part = magnitude * math.sin(2 * math.pi * freq * t)
        if HAS_NOISE:
            noise_part = magnitude * 0.5 * noise.pnoise1(t + self.noise_offset, octaves=3)
        else:
            # Fallback: thêm sin với tần số khác
            noise_part = magnitude * 0.3 * math.sin(2 * math.pi * (freq * 1.7) * t + 1.2)
        return base_angle + sin_part + noise_part

    # ---------- Movement key handling ----------
    def _apply_movement_keys(self, forward, strafe):
        """forward: -1 (S), 0, 1 (W); strafe: -1 (A), 0, 1 (D)"""
        hwnd = get_window_handle()
        if not hwnd:
            return

        if hwnd != self.hwnd:
            self.hwnd = hwnd
            self._key_states = {'W': False, 'A': False, 'S': False, 'D': False}

        key_map = {
            'W': forward == 1,
            'S': forward == -1,
            'A': strafe == -1,
            'D': strafe == 1
        }
        for key, should_press in key_map.items():
            vk = {'W': 0x57, 'A': 0x41, 'S': 0x53, 'D': 0x44}[key]
            if should_press and not self._key_states[key]:
                win32api.SendMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
                self._key_states[key] = True
            elif not should_press and self._key_states[key]:
                win32api.SendMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
                self._key_states[key] = False

    # ---------- Waypoint management ----------
    def find_closest_waypoint(self, pos):
        if not self.waypoints:
            return 0
        min_dist_sq = float('inf')
        closest = 0
        for i, wp in enumerate(self.waypoints):
            dx = wp[0] - pos[0]
            dy = wp[1] - pos[1]
            dz = wp[2] - pos[2]
            dist_sq = dx*dx + dy*dy + dz*dz
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest = i
        return closest

    def get_next_waypoint_index(self):
        if not self.waypoints:
            return self.current_idx
        return (self.current_idx + 1) % len(self.waypoints)

    def load_waypoints(self, map_name):
        filename = get_waypoint_filename(map_name)
        self.waypoints = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                    self.waypoints = [(p['x'], p['y'], p['z']) for p in data]
                print(f"[Walkbot] Loaded {len(self.waypoints)} waypoints for {map_name}")
                self.current_idx = 0
            except Exception as e:
                print(f"[Walkbot] Failed to load waypoints: {e}")
        self._update_shared_list()

    def save_waypoints(self):
        if not self.current_map or self.current_map == "unknown":
            return
        filename = get_waypoint_filename(self.current_map)
        try:
            data = [{'x': p[0], 'y': p[1], 'z': p[2]} for p in self.waypoints]
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"[Walkbot] Saved {len(self.waypoints)} waypoints to {filename}")
        except Exception as e:
            print(f"[Walkbot] Failed to save waypoints: {e}")
        self._update_shared_list()

    def _update_shared_list(self):
        try:
            while len(self.waypoint_list) > 0:
                self.waypoint_list.pop()
            for wp in self.waypoints:
                self.waypoint_list.append(wp)
        except Exception:
            pass

    def clean_waypoints(self, min_distance=30.0):
        if len(self.waypoints) < 2:
            return
        new_waypoints = [self.waypoints[0]]
        for i in range(1, len(self.waypoints)):
            last = new_waypoints[-1]
            current = self.waypoints[i]
            dx = current[0] - last[0]
            dy = current[1] - last[1]
            dz = current[2] - last[2]
            dist = math.hypot(dx, dy, dz)
            if dist >= min_distance:
                new_waypoints.append(current)
        if new_waypoints[-1] != self.waypoints[-1]:
            new_waypoints.append(self.waypoints[-1])
        if len(new_waypoints) < len(self.waypoints):
            self.waypoints = new_waypoints
            self.save_waypoints()
            print(f"[Walkbot] Cleaned waypoints: now {len(self.waypoints)} points")

    # ---------- Buy / Utility ----------
    def buy_weapons(self, pm, client):
        now = time.time()
        if now - self.last_buy_time < self.buy_cooldown:
            return

        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player:
            return
        immunity = pm.read_int(local_player + m_bGunGameImmunity)
        if immunity is None or immunity not in (1, 257):
            return

        if not self.hwnd:
            return
        win32api.SendMessage(self.hwnd, win32con.WM_KEYDOWN, 0x42, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYUP, 0x42, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYDOWN, 0x34, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYUP, 0x34, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYDOWN, 0x32, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYUP, 0x32, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        time.sleep(0.05)
        win32api.SendMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)

        self.last_buy_time = now
        if not self.buy_printed_this_map:
            print("[Walkbot] Auto-buy executed (B 4 2 ESC) while immune")
            self.buy_printed_this_map = True

    # ---------- Account switching ----------
    def close_game_and_steam(self):
        print("[Account] Closing CS2 and Steam...")
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'cs2.exe' in proc.info['name'].lower():
                    proc.kill()
        except:
            pass
        time.sleep(2)
        self.account_manager.kill_steam()

    def reconnect_to_game(self):
        retries = 0
        while retries < 60:
            client, pm = get_memory_reader()
            if client and pm:
                self.client = client
                self.pm = pm
                self.hwnd = get_window_handle()
                print("[Account] Reconnected to CS2")
                return True
            time.sleep(2)
            retries += 1
        print("[Account] Failed to reconnect")
        self.client = None
        self.pm = None
        return False

    def switch_to_next_account(self):
        if len(self.account_manager.accounts) <= 1:
            return
        next_index = (self.account_manager.current_account_index + 1) % len(self.account_manager.accounts)
        print(f"[Account] Switching to account {next_index + 1}...")
        self.settings.set("account_switch_request", next_index)
        self.settings.set("force_auto_join_after_switch", self.settings.get("auto_join_match", False))

    # ---------- Main loop ----------
    def run(self, exit_event):
        client, pm = get_memory_reader()
        if not client or not pm:
            print("[Walkbot] Failed to get memory reader")
            return

        self.pm = pm
        self.client = client
        self.hwnd = get_window_handle()
        print("[Walkbot] Started.")

        # Biến để giới hạn in lỗi
        last_error_time = 0
        error_cooldown = 10

        # Kiểm tra auto_join_on_start
        if self.settings.get("auto_join_on_start", False):
            print("[Walkbot] Auto-join on start triggered.")
            self.auto_join_match(force=True)
            self.settings.set("auto_join_on_start", False)

        last_wasd_state = False

        while not exit_event.is_set():
            try:
                now = time.time()

                # Xử lý yêu cầu test auto join (cũ)
                if self.settings.get("test_auto_join_request", False):
                    old_auto_join = self.settings.get("auto_join_match", False)
                    self.settings.set("auto_join_match", True)
                    self.auto_join_match(force=True)
                    self.settings.set("auto_join_match", old_auto_join)
                    self.settings.set("test_auto_join_request", False)

                # Update settings
                aim_speed = self.settings.get('walkbot_aim_speed', 15.0)
                shot_delay = self.settings.get('walkbot_shot_delay', 0.1)
                friendly_fire = self.settings.get('friendly_fire', False)
                visible_check = self.settings.get('esp_visible_check', True)
                dm_mode = self.settings.get('dm_mode', False)
                triggerbot_enabled = self.settings.get('triggerbot_enabled', False)

                # Update account list from settings
                acc_list = self.settings.get("account_list", [])
                if acc_list != [a.to_dict() for a in self.account_manager.accounts]:
                    self.account_manager.accounts = [SteamAccount.from_dict(acc) for acc in acc_list]
                self.account_manager.current_account_index = self.settings.get("account_current_index", 0)

                self.auto_switch_accounts = self.settings.get("account_switch_enable", False)
                self.switch_map_count = self.settings.get("account_switch_after_maps", 1)

                # Handle manual switch request (từ nút Switch to Selected hoặc Switch & Auto Join)
                req = self.settings.get("account_switch_request", -1)
                if req >= 0:
                    force_join = self.settings.get("force_auto_join_after_switch", False)
                    if 0 <= req < len(self.account_manager.accounts):
                        print(f"[Walkbot] Processing switch request to index {req} (force_join={force_join})")
                        self.is_switching_account = True
                        self.close_game_and_steam()
                        if self.account_manager.switch_account(req):
                            if self.account_manager.launch_steam_with_tcno():
                                time.sleep(5)
                                if self.account_manager.launch_cs2():
                                    print("[Walkbot] CS2 launched. Waiting for game window...")
                                    time.sleep(10)
                                    # Thực hiện auto join nếu cần
                                    self.auto_join_match(force=force_join)
                                    # Yêu cầu main reset toàn bộ cheat
                                    print("[Walkbot] Requesting cheat reset...")
                                    self.settings.set("reset_requested", True)
                                    # Xoá request và flag force
                                    self.settings.set("account_switch_request", -1)
                                    self.settings.set("force_auto_join_after_switch", False)
                                    # Nhả phím di chuyển
                                    self._apply_movement_keys(0, 0)
                                    self.is_switching_account = False
                                    return  # Thoát khỏi run, process sẽ kết thúc
                                else:
                                    print("[Walkbot] Failed to launch CS2")
                            else:
                                print("[Walkbot] Failed to launch Steam with TcNo")
                        else:
                            print("[Walkbot] Failed to switch account")
                        # Nếu có lỗi, vẫn xoá request nhưng không reset
                        self.settings.set("account_switch_request", -1)
                        self.settings.set("force_auto_join_after_switch", False)
                        self.is_switching_account = False

                # Xử lý yêu cầu chọn team thủ công
                if self.settings.get("execute_team_t_request", False):
                    self._send_team_select(1)
                    self.settings.set("execute_team_t_request", False)

                if self.settings.get("execute_team_ct_request", False):
                    self._send_team_select(2)
                    self.settings.set("execute_team_ct_request", False)

                # Map detection
                if now - self.last_map_check > 2.0:
                    detected = pm.get_map_name(client)
                    if detected and detected != self.current_map:
                        if self.current_map != "":
                            self.check_account_switch(detected)
                        self.current_map = detected
                        print(f"[Walkbot] Map changed to {detected}")
                        # Reset các cờ in ấn theo map
                        self.buy_printed_this_map = False
                        self.respawn_message_printed = False
                        self.spawn_snap_message_printed = False
                        self.load_waypoints(detected)
                        if raytracer.load_map(detected):
                            print(f"[Walkbot] Loaded map {detected} for visibility checks")
                        else:
                            print(f"[Walkbot] Failed to load map {detected}")

                        # Auto select team nếu được bật
                        if self.settings.get("auto_select_team", False):
                            team = self.settings.get("team_preference", 1)
                            if team in (1, 2):
                                time.sleep(2)
                                self._send_team_select(team)

                    self.last_map_check = now

                # Hotkeys
                if win32api.GetAsyncKeyState(win32con.VK_F5) & 1:
                    current = self.settings.get('walkbot_enable', False)
                    self.settings.set('walkbot_enable', not current)

                if win32api.GetAsyncKeyState(win32con.VK_F6) & 1:
                    self.recording = not self.recording
                    if self.recording:
                        pos = self.get_local_pos(pm, client)
                        if pos:
                            self.waypoints = [pos]
                            self.last_recorded_pos = pos
                            self.save_waypoints()
                            print(f"[Walkbot] Recording started at waypoint #{len(self.waypoints)}")
                        else:
                            self.recording = False
                            print("[Walkbot] Failed to start recording")
                    else:
                        print("[Walkbot] Recording stopped")

                if win32api.GetAsyncKeyState(win32con.VK_F7) & 1:
                    self.waypoints = []
                    if self.current_map:
                        fname = get_waypoint_filename(self.current_map)
                        if os.path.exists(fname):
                            os.remove(fname)
                    self._update_shared_list()
                    print("[Walkbot] Cleared all waypoints")
                    self._apply_movement_keys(0, 0)

                if win32api.GetAsyncKeyState(win32con.VK_F8) & 1:
                    self.clean_waypoints(min_distance=30.0)

                if self.recording:
                    pos = self.get_local_pos(pm, client)
                    if pos and self.last_recorded_pos:
                        dx = pos[0] - self.last_recorded_pos[0]
                        dy = pos[1] - self.last_recorded_pos[1]
                        dz = pos[2] - self.last_recorded_pos[2]
                        dist = math.hypot(dx, dy, dz)
                        if dist >= self.record_threshold:
                            self.waypoints.append(pos)
                            self.last_recorded_pos = pos
                            self.save_waypoints()
                            print(f"[Walkbot] Recorded waypoint #{len(self.waypoints)} at distance {dist:.1f}")

                self.enabled = self.settings.get('walkbot_enable', False)

                if self.enabled and not self.prev_enabled:
                    if self.waypoints:
                        pos = self.get_local_pos(pm, client)
                        if pos:
                            self.current_idx = self.find_closest_waypoint(pos)
                            print(f"[Walkbot] Started at waypoint #{self.current_idx}")
                    self.prev_enabled = True
                    self.buy_weapons(pm, client)
                elif not self.enabled and self.prev_enabled:
                    self._apply_movement_keys(0, 0)
                    last_wasd_state = False
                    self.prev_enabled = False

                if not self.enabled or not is_cs2_window_active():
                    if last_wasd_state:
                        self._apply_movement_keys(0, 0)
                        last_wasd_state = False
                    time.sleep(0.1)
                    continue

                if not self.waypoints:
                    if last_wasd_state:
                        self._apply_movement_keys(0, 0)
                        last_wasd_state = False
                    time.sleep(0.1)
                    continue

                local_player = pm.read_longlong(client + dwLocalPlayerPawn)
                if not local_player:
                    continue

                local_hp = pm.read_int(local_player + m_iHealth)
                if local_hp is None:
                    continue

                local_pos = self.get_local_pos(pm, client, local_player)
                if not local_pos:
                    continue

                if local_hp <= 0:
                    self.was_dead = True
                    if self.burst_active:
                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.burst_active = False
                    if last_wasd_state:
                        self._apply_movement_keys(0, 0)
                        last_wasd_state = False
                    time.sleep(0.1)
                    continue
                else:
                    if self.was_dead and local_pos:
                        self.was_dead = False
                        self.current_idx = self.find_closest_waypoint(local_pos)
                        if not self.respawn_message_printed:
                            print(f"[Walkbot] Respawned. Snapping to waypoint #{self.current_idx}")
                            self.respawn_message_printed = True
                        self.buy_weapons(pm, client)
                    elif local_pos and len(self.waypoints) > 0:
                        target = self.waypoints[self.current_idx]
                        dist_to_wp = math.hypot(target[0] - local_pos[0], target[1] - local_pos[1], target[2] - local_pos[2])
                        if dist_to_wp > 1000.0:
                            self.current_idx = self.find_closest_waypoint(local_pos)
                            if not self.spawn_snap_message_printed:
                                print(f"[Walkbot] Spawn location changed. Snapping to waypoint #{self.current_idx}")
                                self.spawn_snap_message_printed = True

                # Combat data
                local_team = pm.read_int(local_player + m_iTeamNum)
                if local_team is None:
                    continue

                local_pitch = pm.read_float(client + dwViewAngles)
                local_yaw = pm.read_float(client + dwViewAngles + 4)
                if local_pitch is None or local_yaw is None:
                    continue

                local_shots_fired = pm.read_int(local_player + m_iShotsFired)
                if local_shots_fired is None:
                    local_shots_fired = 0

                local_eye = self._get_local_eye_pos(pm, client, local_player)
                if not local_eye:
                    continue

                # Get entities
                entities = []
                entity_list = pm.read_longlong(client + dwEntityList)
                if entity_list:
                    entity_ptr = pm.read_longlong(entity_list + 0x10)
                    if entity_ptr:
                        for i in range(1, 65):
                            try:
                                controller = pm.read_longlong(entity_ptr + 0x70 * (i & 0x1FF))
                                if not controller:
                                    continue
                                pawn_handle = pm.read_longlong(controller + m_hPlayerPawn)
                                if not pawn_handle:
                                    continue
                                list_entry = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
                                if not list_entry:
                                    continue
                                pawn = pm.read_longlong(list_entry + 0x70 * (pawn_handle & 0x1FF))
                                if not pawn or pawn == local_player:
                                    continue
                                hp = pm.read_int(pawn + m_iHealth)
                                if hp is None or hp <= 0:
                                    continue
                                life_state = pm.read_int(pawn + m_lifeState)
                                if life_state is None or life_state != 256:
                                    continue
                                team = pm.read_int(pawn + m_iTeamNum)
                                if team is None:
                                    continue
                                immune_val = pm.read_int(pawn + m_bGunGameImmunity)
                                immune = immune_val in (257, 1) if immune_val is not None else False
                                is_visible = True
                                if visible_check:
                                    head_pos = self._get_bone_pos(pm, pawn, 6)
                                    if head_pos and local_eye:
                                        is_visible = vis_cache.is_visible(local_eye, head_pos, pawn)
                                entities.append({
                                    'pawn': pawn,
                                    'controller': controller,
                                    'team': team,
                                    'hp': hp,
                                    'immune': immune,
                                    'is_visible': is_visible,
                                    'index': i
                                })
                            except Exception:
                                continue

                # Find target
                target_info = self.find_aimlock_target(pm, client, local_player, local_eye, local_yaw, local_pitch, entities)

                if target_info:
                    # Địch lộ: dừng di chuyển trước, frame đầu chỉ aim không bắn
                    self._apply_movement_keys(0, 0)
                    last_wasd_state = False

                    self.perform_aimlock(pm, client, target_info, local_player, local_pitch, local_yaw, local_shots_fired)

                    burst_count = int(self.settings.get('dm_burst_count', 3))
                    burst_cd_min = self.settings.get('dm_burst_cooldown_min', 0.3)
                    burst_cd_max = self.settings.get('dm_burst_cooldown_max', 0.5)

                    is_headshot = (target_info.get('bone', 6) == 6)

                    if self._had_target_prev_frame:
                        if now < self.burst_cooldown_until:
                            pass
                        elif self.burst_active:
                            current_shots = pm.read_int(local_player + m_iShotsFired) or 0
                            shots_in_burst = current_shots - self.burst_start_shots
                            if shots_in_burst >= burst_count or (now - self.burst_start_time > 0.5):
                                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                                self.burst_active = False
                                self.burst_cooldown_until = now + random.uniform(burst_cd_min, burst_cd_max)
                        else:
                            pitch_diff = abs(self.normalize_angle(target_info['aim_pitch'] - local_pitch))
                            yaw_diff = abs(self.normalize_angle(target_info['aim_yaw'] - local_yaw))
                            if pitch_diff < 2.0 and yaw_diff < 2.0:
                                dist_to_target = math.hypot(target_info['pos'][0] - local_eye[0],
                                                            target_info['pos'][1] - local_eye[1],
                                                            target_info['pos'][2] - local_eye[2])
                                if dist_to_target <= self.max_shoot_distance:
                                    if is_headshot:
                                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                                        time.sleep(random.uniform(0.04, 0.07))
                                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                                        self.burst_cooldown_until = now + random.uniform(burst_cd_min, burst_cd_max)
                                    else:
                                        self.burst_start_shots = local_shots_fired
                                        self.burst_start_time = now
                                        self.burst_active = True
                                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    self._had_target_prev_frame = True
                    time.sleep(0.01)
                    continue

                if self.burst_active:
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                    self.burst_active = False
                self._had_target_prev_frame = False
                # --- Không có mục tiêu: di chuyển thẳng đến waypoint, góc nhìn đặt trực tiếp ---
                if self.current_idx >= len(self.waypoints):
                    self.current_idx = 0

                target = self.waypoints[self.current_idx]

                dx = target[0] - local_pos[0]
                dy = target[1] - local_pos[1]
                dz = target[2] - local_pos[2]
                dist_3d = math.hypot(dx, dy, dz)

                # Nếu đã "đi qua" waypoint, dist sẽ tăng lại -> cho phép chuyển waypoint sớm để bám đường tốt hơn
                if self._last_wp_dist is None:
                    self._last_wp_dist = dist_3d
                    self._wp_dist_increase_count = 0
                else:
                    if dist_3d > self._last_wp_dist + 3.0:
                        self._wp_dist_increase_count += 1
                    else:
                        self._wp_dist_increase_count = max(0, self._wp_dist_increase_count - 1)
                    self._last_wp_dist = dist_3d

                passed_waypoint = (self._wp_dist_increase_count >= 6 and dist_3d < self.waypoint_threshold * 2.2)

                if dist_3d < self.waypoint_threshold or passed_waypoint:
                    # Đã đến waypoint, chuyển sang tiếp theo
                    self.current_idx = self.get_next_waypoint_index()
                    self._last_wp_dist = None
                    self._wp_dist_increase_count = 0
                    self._apply_movement_keys(0, 0)
                    last_wasd_state = False
                    time.sleep(0.01)
                    continue

                # --- Di chuyển tới waypoint: xoay mượt thay vì snap ---
                # Settings (có default an toàn nếu UI chưa có)
                turn_speed_dps = float(self.settings.get("walkbot_move_turn_speed", 350.0))   # deg/second
                turn_ease = float(self.settings.get("walkbot_move_turn_ease", 0.25))          # 0..1
                strafe_enabled = bool(self.settings.get("walkbot_move_strafe_enable", True))
                strafe_yaw_deg = float(self.settings.get("walkbot_move_strafe_yaw", 42.0))
                align_yaw_deg = float(self.settings.get("walkbot_move_align_yaw", 55.0))
                slow_dist = float(self.settings.get("walkbot_move_slow_dist", 120.0))          # giảm từ 260 -> 120: ít giảm tốc hơn
                pulse_period = float(self.settings.get("walkbot_move_pulse_period", 0.10))
                min_duty = float(self.settings.get("walkbot_move_min_duty", 0.35))             # giữ W nhiều hơn khi gần waypoint

                corner_angle_deg = float(self.settings.get("walkbot_corner_angle", 45.0))
                straight_angle_deg = float(self.settings.get("walkbot_straight_angle", 18.0))
                corner_slow_mult = float(self.settings.get("walkbot_corner_slow_mult", 1.3))   # giảm từ 1.8 -> 1.3: ít giảm tốc ở góc cua
                straight_speed_mult = float(self.settings.get("walkbot_straight_speed_mult", 1.4))  # tăng tốc mạnh hơn trên đường thẳng

                upcoming_turn_angle = None
                if len(self.waypoints) >= 3:
                    prev_idx = (self.current_idx - 1) % len(self.waypoints)
                    next_idx = self.get_next_waypoint_index()
                    if prev_idx != self.current_idx and next_idx != self.current_idx:
                        prev_wp = self.waypoints[prev_idx]
                        next_wp = self.waypoints[next_idx]
                        vin_x = target[0] - prev_wp[0]
                        vin_y = target[1] - prev_wp[1]
                        vout_x = next_wp[0] - target[0]
                        vout_y = next_wp[1] - target[1]
                        len_in = math.hypot(vin_x, vin_y)
                        len_out = math.hypot(vout_x, vout_y)
                        if len_in > 1.0 and len_out > 1.0:
                            dot = (vin_x * vout_x + vin_y * vout_y) / (len_in * len_out)
                            dot = max(-1.0, min(1.0, dot))
                            upcoming_turn_angle = math.degrees(math.acos(dot))  # 0 = thẳng, 90 = vuông góc, 180 = quay đầu

                # Áp dụng multiplier cho tốc độ quay và vùng giảm tốc tuỳ theo loại đoạn đường
                turn_speed_eff = turn_speed_dps
                slow_dist_eff = slow_dist
                if upcoming_turn_angle is not None:
                    if upcoming_turn_angle < straight_angle_deg:
                        # Đường gần như thẳng: quay nhanh hơn, giảm bớt vùng "giảm tốc"
                        turn_speed_eff = turn_speed_dps * straight_speed_mult
                        slow_dist_eff = slow_dist * 0.55
                    elif upcoming_turn_angle > corner_angle_deg:
                        # Cua gắt: giữ quay tương đối chậm + mở rộng vùng giảm tốc
                        slow_dist_eff = slow_dist * corner_slow_mult

                # Tính dt để giới hạn tốc độ quay theo thời gian thực
                if self._last_move_look_time <= 0:
                    dt = 0.02
                else:
                    dt = max(0.005, min(0.060, now - self._last_move_look_time))
                self._last_move_look_time = now

                # Góc mong muốn tới waypoint
                target_pitch, target_yaw = self.get_aim_angles(local_pos, target)
                target_pitch = max(-89, min(89, target_pitch))

                # Đọc lại góc hiện tại để smooth (giảm drift khi combat vừa kết thúc)
                cur_pitch = pm.read_float(client + dwViewAngles)
                cur_yaw = pm.read_float(client + dwViewAngles + 4)
                if cur_pitch is None or cur_yaw is None:
                    cur_pitch, cur_yaw = local_pitch, local_yaw

                max_step = max(1.0, turn_speed_eff * dt)
                smooth_pitch = self._smooth_angle_easing(cur_pitch, target_pitch, max_step * 0.75, turn_ease)
                smooth_yaw = self._smooth_angle_easing(cur_yaw, target_yaw, max_step, turn_ease)

                pm.write_float(client + dwViewAngles, smooth_pitch)
                pm.write_float(client + dwViewAngles + 4, smooth_yaw)

                # Strafe khi góc lệch lớn. DM: tắt strafe để không A/D điên, chỉ W + quay
                yaw_err = self.normalize_angle(target_yaw - cur_yaw)
                strafe = 0
                if not self.settings.get('dm_mode', False) and strafe_enabled and abs(yaw_err) > strafe_yaw_deg:
                    strafe = -1 if yaw_err < 0 else 1

                # Điều khiển forward để tránh đi lố waypoint:
                # - Nếu lệch yaw lớn: nhả W (chỉ quay + strafe) để bắt hướng
                # - Nếu gần waypoint: nhấp W theo duty cycle để giảm tốc (giúp vào waypoint chính xác hơn)
                forward = 1
                if abs(yaw_err) > align_yaw_deg:
                    forward = 0
                else:
                    if slow_dist_eff > 1.0 and dist_3d < slow_dist_eff:
                        # duty giảm dần khi gần waypoint, thêm giảm nếu đang còn lệch hướng
                        dist_ratio = max(0.0, min(1.0, dist_3d / slow_dist_eff))
                        yaw_ratio = max(0.0, min(1.0, 1.0 - (abs(yaw_err) / max(align_yaw_deg, 1.0))))
                        duty = max(min_duty, min(1.0, dist_ratio)) * (0.55 + 0.45 * yaw_ratio)
                        if pulse_period <= 0.02:
                            pulse_period = 0.02
                        phase = (now % pulse_period) / pulse_period
                        forward = 1 if phase < duty else 0

                self._apply_movement_keys(forward, strafe)
                last_wasd_state = True

                time.sleep(0.01)

            except Exception as e:
                now = time.time()
                if now - last_error_time > error_cooldown:
                    print(f"[Walkbot] Error: {e}")
                    last_error_time = now
                self._apply_movement_keys(0, 0)
                last_wasd_state = False
                time.sleep(1)

def walkbot(settings, waypoint_list, exit_event):
    wb = Walkbot(settings, waypoint_list)
    wb.run(exit_event)