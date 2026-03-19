import time
import struct
import win32api
import win32con
import win32gui
import socket
import tempfile
import os
from multiprocessing import Process, Manager
from offsets import weapon_bytes

try:
    with open("weapon_font.ttf", "wb") as f:
        f.write(weapon_bytes)
    print("Saved to weapon_font.ttf")
except (PermissionError, OSError):
    pass
from core.memory import get_memory_reader
from core.utils import (
    w2s,
    get_weapon_name, get_weapon_icon, get_weapon_type,
    is_cs2_window_active, angle_to_direction, point_along_direction,
    get_game_window_rect
)
from core.raytracer import raytracer
from core.visibility_cache import vis_cache

from offsets import (
    verdana_bytes, weapon_bytes,
    dwEntityList, dwLocalPlayerPawn, dwViewMatrix,
    m_iTeamNum, m_hPlayerPawn, m_iHealth, m_lifeState,
    m_pGameSceneNode,
    m_vecOrigin, m_modelState, m_angEyeAngles, m_pClippingWeapon,
    m_AttributeManager, m_Item, m_iItemDefinitionIndex,
    m_bGunGameImmunity, m_ArmorValue,
    m_iszPlayerName, bone_ids, bone_connections,
    m_vecViewOffset
)

CMD_LINE = 0x01
CMD_RECT = 0x02
CMD_TEXT = 0x03
CMD_GAME_WIN = 0x04

_pack_line = struct.Struct('<BffffIf').pack
_pack_rect = struct.Struct('<BffffI').pack
_pack_gwin = struct.Struct('<Biiii').pack
_pack_text_hdr = struct.Struct('<BffBIBB').pack

def _rgba_to_argb(r, g, b, a):
    ri, gi, bi, ai = int(r * 255), int(g * 255), int(b * 255), int(a * 255)
    return (ai << 24) | (ri << 16) | (gi << 8) | bi

class OverlayClient:
    def __init__(self, host="127.0.0.1", port=7777):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
        self.commands = []

    def clear(self):
        self.commands.clear()

    def add_line(self, x1, y1, x2, y2, color, thickness=1.0):
        argb = _rgba_to_argb(*color)
        self.commands.append(
            _pack_line(CMD_LINE, float(x1), float(y1), float(x2), float(y2), argb, float(thickness))
        )

    def add_rect_filled(self, x1, y1, x2, y2, color):
        r, g, b, a = color
        ri, gi, bi = int(r * 255), int(g * 255), int(b * 255)
        if ri + gi + bi == 0 and int(a * 255) > 0:
            ri = gi = bi = 8
        ai = int(a * 255)
        argb = (ai << 24) | (ri << 16) | (gi << 8) | bi
        self.commands.append(
            _pack_rect(CMD_RECT, float(x1), float(y1), float(x2), float(y2), argb)
        )

    def add_circle_lines(self, cx, cy, radius, color, segments=40):
        if radius <= 0 or segments < 4:
            return
        import math
        argb = _rgba_to_argb(*color)
        step = 2 * math.pi / segments
        prev_x = cx + radius
        prev_y = cy
        angle = step
        for _ in range(1, segments + 1):
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            self.commands.append(
                _pack_line(CMD_LINE, float(prev_x), float(prev_y), float(x), float(y), argb, 1.0)
            )
            prev_x, prev_y = x, y
            angle += step

    def add_crosshair(self, cx, cy, size, color):
        half = max(1, int(size))
        argb = _rgba_to_argb(*color)
        self.commands.append(_pack_line(CMD_LINE, float(cx - half), float(cy), float(cx + half), float(cy), argb, 1.0))
        self.commands.append(_pack_line(CMD_LINE, float(cx), float(cy - half), float(cx), float(cy + half), argb, 1.0))

    def add_text(self, x, y, size, color, text, kind="T"):
        if not text:
            return
        argb = _rgba_to_argb(*color)
        icon_flag = 1 if kind == "W" else 0
        text_bytes = str(text).replace("\n", " ").encode('ascii', errors='ignore')[:255]
        self.commands.append(
            _pack_text_hdr(CMD_TEXT, float(x), float(y), int(size) & 0xFF, argb, icon_flag, len(text_bytes))
            + text_bytes
        )

    def send_game_window(self, x, y, w, h):
        self.commands.append(_pack_gwin(CMD_GAME_WIN, int(x), int(y), int(w), int(h)))

    def send(self):
        if not self.commands:
            return
        data = b''.join(self.commands)
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass
        self.clear()


# Biến toàn cục để theo dõi map hiện tại và các map đã thử load nhưng thất bại
current_map_name = ""
last_map_check = 0
failed_maps = set()

def update_map(pm, client):
    global current_map_name, last_map_check, failed_maps
    now = time.time()
    if now - last_map_check > 2.0:
        detected_map = pm.get_map_name(client)
        if detected_map and detected_map != current_map_name:
            if detected_map in failed_maps:
                pass
            elif raytracer.load_map(detected_map):
                current_map_name = detected_map
                print(f"[ESP] Loaded {detected_map}.tri")
            else:
                failed_maps.add(detected_map)
                print(f"[ESP] Could not load map/{detected_map}.tri")
        last_map_check = now

def get_entities_data(pm, client):
    view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
    local_player = pm.read_longlong(client + dwLocalPlayerPawn)
    local_team = pm.read_int(local_player + m_iTeamNum) if local_player else 0
    entity_list = pm.read_longlong(client + dwEntityList)
    entity_ptr = pm.read_longlong(entity_list + 0x10) if entity_list else 0
    return view_matrix, local_player, local_team, entity_list, entity_ptr

def get_local_eye_pos(pm, local_player):
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

def get_pawn_info(pm, i, entity_ptr, entity_list, local_player, local_eye_pos, visible_check, view_matrix, width, height):
    controller = pm.read_longlong(entity_ptr + 0x70 * (i & 0x1FF))
    if not controller:
        return None

    pawn_handle = pm.read_longlong(controller + m_hPlayerPawn)
    if not pawn_handle:
        return None

    list_entry = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
    if not list_entry:
        return None

    pawn = pm.read_longlong(list_entry + 0x70 * (pawn_handle & 0x1FF))
    if not pawn or pawn == local_player:
        return None

    hp = pm.read_int(pawn + m_iHealth)
    if hp <= 0 or pm.read_int(pawn + m_lifeState) != 256:
        return None

    game_scene = pm.read_longlong(pawn + m_pGameSceneNode)
    if not game_scene:
        return None

    bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
    if not bone_matrix:
        return None

    all_bone_data = pm.read_bytes(bone_matrix, 29 * 0x20)
    if not all_bone_data or len(all_bone_data) < 29 * 0x20:
        return None
    head_pos_3d = struct.unpack_from('fff', all_bone_data, 6 * 0x20)

    head_screen = w2s(view_matrix, head_pos_3d[0], head_pos_3d[1], head_pos_3d[2] + 8, width, height)
    if head_screen[0] == -999:
        return None

    is_visible = False
    if local_eye_pos and visible_check:
        is_visible = vis_cache.is_visible(local_eye_pos, head_pos_3d, pawn)
    elif not visible_check:
        is_visible = True

    return {
        "pawn": pawn,
        "controller": controller,
        "team": pm.read_int(pawn + m_iTeamNum),
        "hp": hp,
        "immune": pm.read_int(pawn + m_bGunGameImmunity) in (257, 1),
        "is_visible": is_visible,
        "head_pos_3d": head_pos_3d,
        "head_screen": head_screen,
        "bone_data": all_bone_data
    }

def draw_esp_for_player(overlay, pm, info, vm, s, win_x, win_y, win_w, win_h):
    is_ally = (info['team'] == s['local_team'])
    if is_ally and not s.get('esp_teammates', False):
        return

    pawn = info['pawn']
    head_screen = info['head_screen']
    head_pos_3d = info['head_pos_3d']
    bone_data = info.get('bone_data')
    if not bone_data:
        return

    leg_z = struct.unpack_from('f', bone_data, 28 * 0x20 + 0x8)[0]
    leg_pos = w2s(vm, head_pos_3d[0], head_pos_3d[1], leg_z, win_w, win_h)
    if leg_pos[0] == -999:
        return

    head_abs = (head_screen[0] + win_x, head_screen[1] + win_y)
    leg_abs = (leg_pos[0] + win_x, leg_pos[1] + win_y)

    delta_z = abs(head_abs[1] - leg_abs[1])
    left_x, right_x = head_abs[0] - delta_z // 4, head_abs[0] + delta_z // 4

    box_fill = None
    if info['immune']:
        box_fill = s.get('esp_box_fill_immune_color', (0.83, 0.3, 0.19, 0.4))
    elif info['is_visible']:
        box_fill = s.get('esp_box_fill_spotted_color', (0.23, 0.3, 0.19, 0.4))
    else:
        box_fill = s.get('esp_box_fill_normal_color', (0.23, 0.2, 0.19, 0.4))

    if s.get('esp_snap_lines'):
        line_col = s.get('esp_ally_snapline_color') if is_ally else s.get('esp_enemy_snapline_color')
        overlay.add_line(head_abs[0], head_abs[1], win_x + win_w / 2, win_y + win_h / 2, line_col or (1.0, 1.0, 1.0, 1.0))

    if s.get('esp_filled_box') and box_fill:
        overlay.add_rect_filled(left_x, head_abs[1], right_x, leg_abs[1], box_fill)

    if s.get('esp_box'):
        col = s.get('esp_box_border_color', (1.0, 1.0, 1.0, 1.0))
        overlay.add_line(left_x, leg_abs[1], right_x, leg_abs[1], col)
        overlay.add_line(left_x, head_abs[1], right_x, head_abs[1], col)
        overlay.add_line(left_x, head_abs[1], left_x, leg_abs[1], col)
        overlay.add_line(right_x, head_abs[1], right_x, leg_abs[1], col)

    if s.get('esp_corners'):
        c_len = (right_x - left_x) * 0.3
        col = s.get('esp_enemy_color', (1.0, 0.0, 0.0, 1.0))
        # 4 góc, mỗi góc là 2 đoạn nhỏ
        corners = [
            (left_x, head_abs[1],  c_len,  0,      0,       c_len),
            (right_x, head_abs[1], -c_len, 0,      0,       c_len),
            (left_x, leg_abs[1],   c_len,  0,      0,      -c_len),
            (right_x, leg_abs[1], -c_len,  0,      0,      -c_len),
        ]
        for x, y, dx1, dy1, dx2, dy2 in corners:
            overlay.add_line(x, y, x + dx1, y + dy1, col)
            overlay.add_line(x, y, x + dx2, y + dy2, col)

    if s.get('esp_health_bar'):
        pct = max(0.0, min(1.0, info['hp'] / 100.0))
        bg_col = s.get('esp_health_bar_bg_color', (0.0, 0.0, 0.0, 0.7))
        hp_col = s.get('esp_health_bar_color', (0.0, 1.0, 0.0, 1.0))
        bar_w = 4
        bar_x = left_x - bar_w - 3
        overlay.add_rect_filled(bar_x, head_abs[1], bar_x + bar_w, leg_abs[1], bg_col)
        bar_h = delta_z * pct
        overlay.add_rect_filled(bar_x, leg_abs[1] - bar_h, bar_x + bar_w, leg_abs[1], hp_col)

    if s.get('esp_armor_bar'):
        armor = pm.read_int(pawn + m_ArmorValue)
        pct = max(0.0, min(1.0, armor / 100.0))
        bg_col = s.get('esp_health_bar_bg_color', (0.0, 0.0, 0.0, 0.7))
        ar_col = s.get('esp_armor_bar_color', (0.0, 0.5, 1.0, 1.0))
        bar_h = 4
        bar_y = leg_abs[1] + 3
        bar_w = right_x - left_x
        overlay.add_rect_filled(left_x, bar_y, right_x, bar_y + bar_h, bg_col)
        fill_w = bar_w * pct
        overlay.add_rect_filled(left_x, bar_y, left_x + fill_w, bar_y + bar_h, ar_col)

    if s.get('esp_skeleton'):
        if info['immune']:
            skel_color = (1.0, 0.0, 0.0, 1.0)
        elif info['is_visible']:
            skel_color = (0.0, 1.0, 0.0, 1.0)
        else:
            skel_color = s.get('esp_skeleton_color', (1.0, 1.0, 1.0, 1.0))

        bones = {}
        if bone_data:
            for name, idx in bone_ids.items():
                bp = struct.unpack_from('fff', bone_data, idx * 0x20)
                screen_bp = w2s(vm, *bp, win_w, win_h)
                if screen_bp[0] != -999:
                    bones[name] = (screen_bp[0] + win_x, screen_bp[1] + win_y)
            for a, b in bone_connections:
                if a in bones and b in bones:
                    overlay.add_line(bones[a][0], bones[a][1], bones[b][0], bones[b][1], skel_color)

    # Tên
    if s.get('esp_names'):
        name = pm.read_string(info['controller'] + m_iszPlayerName, 32)
        if name:
            name_col = s.get('esp_name_color', (1.0, 1.0, 1.0, 1.0))
            # canh giữa trên đầu
            overlay.add_text(head_abs[0], head_abs[1] - 20, 14, name_col, name)

    # Vũ khí (dùng icon súng nếu có, ưu tiên icon thay vì text tên)
    if s.get('esp_weapons'):
        w_ptr = pm.read_longlong(pawn + m_pClippingWeapon)
        if w_ptr:
            w_idx = pm.read_int(w_ptr + m_AttributeManager + m_Item + m_iItemDefinitionIndex)
            weap_name = get_weapon_name(w_idx)
            icon = get_weapon_icon(weap_name) if weap_name else ""
            text_to_draw = icon or weap_name
            if text_to_draw:
                weap_col = s.get('esp_weapon_color', (1.0, 1.0, 1.0, 1.0))
                # kind="W" để phía overlay chọn font icon
                overlay.add_text(head_abs[0], leg_abs[1] + 10, 24, weap_col, text_to_draw, kind="W")

    if s.get('esp_eye_lines'):
        p, y = pm.read_float(pawn + m_angEyeAngles), pm.read_float(pawn + m_angEyeAngles + 4)
        end = point_along_direction(head_pos_3d, angle_to_direction(p, y), 100)
        end_s = w2s(vm, *end, win_w, win_h)
        if end_s[0] != -999:
            end_abs = (end_s[0] + win_x, end_s[1] + win_y)
            overlay.add_line(head_abs[0], head_abs[1] - 5, end_abs[0], end_abs[1], s.get('esp_eye_line_color', (1.0, 1.0, 1.0, 1.0)))

def weapon_worker(shared_list, settings, exit_event):
    client, pm = get_memory_reader()
    if not client or not pm:
        return
    while not exit_event.is_set():
        try:
            if settings.get("esp_dropped_weapons"):
                _, _, _, ent_list, _ = get_entities_data(pm, client)
                temp = []
                for i in range(64, 1024):
                    entry = pm.read_longlong(ent_list + 8 * ((i & 0x7FFF) >> 9) + 16)
                    if not entry:
                        continue
                    item = pm.read_longlong(entry + 120 * (i & 0x1FF))
                    if not item or pm.read_longlong(item + 0x440):
                        continue

                    node = pm.read_longlong(item + m_pGameSceneNode)
                    origin = (pm.read_float(node + m_vecOrigin),
                              pm.read_float(node + m_vecOrigin + 4),
                              pm.read_float(node + m_vecOrigin + 8))

                    typestr = pm.read_string(pm.read_longlong(pm.read_longlong(item + 0x10) + 0x20), 128)
                    name = get_weapon_type(typestr)
                    if name != 'unknown':
                        temp.append({'world': origin, 'name': name})
                shared_list[:] = temp
        except:
            pass
        time.sleep(0.2)

def wallhack(settings, waypoint_list, exit_event):
    weapon_list = Manager().list()
    p = Process(target=weapon_worker, args=(weapon_list, settings, exit_event), daemon=True)
    p.start()

    last_frame_time = time.time()
    overlay = OverlayClient()
    s_map = {}
    last_settings_refresh = 0.0

    while not exit_event.is_set():
        start_time = time.time()
        try:
            if not (is_cs2_window_active() and settings.get("esp_enable", True)):
                overlay.clear()
                time.sleep(0.01)
                continue

            game_rect = get_game_window_rect()
            if not game_rect:
                time.sleep(0.01)
                continue

            win_x, win_y, win_w, win_h = game_rect
            client, pm = get_memory_reader()
            if not (client and pm):
                time.sleep(0.01)
                continue

            update_map(pm, client)

            vm, local_player, local_team, ent_list, ent_ptr = get_entities_data(pm, client)
            if not local_player:
                time.sleep(0.01)
                continue

            local_eye_pos = get_local_eye_pos(pm, local_player)
            visible_check = settings.get('esp_visible_check', True)

            if start_time - last_settings_refresh > 0.5:
                s_map = {k: settings.get(k) for k in settings._data.keys()}
                last_settings_refresh = start_time
            s_map['local_team'] = local_team

            overlay.clear()
            overlay.send_game_window(win_x, win_y, win_w, win_h)

            # Vẽ waypoint: chấm + line nối
            if settings.get('show_waypoints', False) and waypoint_list:
                points_2d = []
                for wp in waypoint_list:
                    screen = w2s(vm, wp[0], wp[1], wp[2], win_w, win_h)
                    if screen[0] != -999:
                        abs_pos = (screen[0] + win_x, screen[1] + win_y)
                        points_2d.append(abs_pos)
                # chấm (nhỏ) tại từng waypoint
                for px, py in points_2d:
                    overlay.add_crosshair(px, py, 3, (0.0, 1.0, 0.0, 1.0))
                for i in range(len(points_2d) - 1):
                    overlay.add_line(
                        points_2d[i][0], points_2d[i][1],
                        points_2d[i + 1][0], points_2d[i + 1][1],
                        (0.0, 1.0, 0.0, 0.5)
                    )

            # Vẽ FOV + crosshair
            cx, cy = win_x + win_w / 2, win_y + win_h / 2
            fov_val = settings.get('aimbot_fov', 0)
            if settings.get('draw_fov') and fov_val > 0:
                radius = (fov_val / 100.0) * win_w / 2
                overlay.add_circle_lines(
                    cx, cy, radius,
                    settings.get('esp_fov_color', (1.0, 1.0, 1.0, 0.3)),
                    segments=48
                )
            if settings.get('draw_crosshair'):
                overlay.add_crosshair(
                    cx, cy, 4,
                    settings.get('esp_crosshair_color', (1.0, 1.0, 1.0, 1.0))
                )

            # Vẽ từng người chơi
            for i in range(1, 65):
                try:
                    info = get_pawn_info(pm, i, ent_ptr, ent_list,
                                         local_player, local_eye_pos,
                                         visible_check, vm, win_w, win_h)
                    if info:
                        draw_esp_for_player(
                            overlay, pm, info, vm, s_map,
                            win_x, win_y, win_w, win_h
                        )
                except Exception:
                    continue

            # Vũ khí rơi (text)
            if settings.get('esp_dropped_weapons'):
                for w in weapon_list:
                    world = w['world']
                    screen = w2s(vm, world[0], world[1], world[2], win_w, win_h)
                    if screen[0] != -999:
                        x = screen[0] + win_x
                        y = screen[1] + win_y
                        overlay.add_text(
                            x, y, 14,
                            settings.get('esp_dropped_weapon_color', (1.0, 1.0, 1.0, 1.0)),
                            w['name']
                        )

            overlay.send()

        except Exception:
            # Tránh crash loop ESP
            pass

        # Giới hạn FPS overlay (45 = cân bằng mượt / ít lag)
        target_fps = 45
        frame_time = 1.0 / target_fps
        elapsed = time.time() - start_time
        if elapsed < frame_time:
            time.sleep(frame_time - elapsed)

    p.join(timeout=1)