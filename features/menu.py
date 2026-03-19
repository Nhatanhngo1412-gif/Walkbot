import os
import time
import sys
import tempfile
import glfw
import imgui
import OpenGL.GL as gl
from imgui.integrations.glfw import GlfwRenderer
import win32api
import win32con
import win32gui

from core.utils import (
    draw_rect_outline, draw_rect_filled, draw_line,
    draw_circle_filled, draw_text, code_to_name, glfw_key_map,
    win32_key_map, is_cs2_window_active, set_console_visibility,
    get_window_handle, get_game_window_rect
)
from offsets import verdana_bytes, font_awesome

# --- Color and style configuration ---
color_accent = (0.55, 0.00, 0.55, 1.00)
color_bg_dark = (0.08, 0.08, 0.08, 1.00)
color_item_bg = (0.15, 0.15, 0.15, 1.00)
color_text = (0.90, 0.90, 0.90, 1.00)
color_border = (0.25, 0.25, 0.25, 0.50)

def setup_imgui_style():
    style = imgui.get_style()
    style.window_rounding = 3
    style.frame_rounding = 3
    style.grab_rounding = 3
    style.scrollbar_rounding = 3
    style.window_padding = (8, 8)
    style.frame_padding = (6, 4)
    style.item_spacing = (8, 6)
    style.scrollbar_size = 10

    colors = style.colors
    colors[imgui.COLOR_WINDOW_BACKGROUND] = color_bg_dark
    colors[imgui.COLOR_BORDER] = color_border
    colors[imgui.COLOR_FRAME_BACKGROUND] = color_item_bg
    colors[imgui.COLOR_FRAME_BACKGROUND_HOVERED] = (0.20, 0.20, 0.20, 1.0)
    colors[imgui.COLOR_FRAME_BACKGROUND_ACTIVE] = (0.25, 0.25, 0.25, 1.0)
    colors[imgui.COLOR_CHECK_MARK] = color_accent
    colors[imgui.COLOR_SLIDER_GRAB] = color_accent
    colors[imgui.COLOR_SLIDER_GRAB_ACTIVE] = (0.70, 0.00, 0.55, 1.0)
    colors[imgui.COLOR_HEADER] = color_accent
    colors[imgui.COLOR_HEADER_HOVERED] = (0.65, 0.00, 0.55, 1.0)
    colors[imgui.COLOR_HEADER_ACTIVE] = (0.50, 0.00, 0.55, 1.0)
    colors[imgui.COLOR_SCROLLBAR_BACKGROUND] = (0.10, 0.10, 0.10, 1.0)
    colors[imgui.COLOR_SCROLLBAR_GRAB] = color_item_bg
    colors[imgui.COLOR_TEXT] = color_text
    colors[imgui.COLOR_TEXT_DISABLED] = (0.50, 0.50, 0.50, 1.0)
    colors[imgui.COLOR_BUTTON] = color_accent
    colors[imgui.COLOR_BUTTON_HOVERED] = (0.65, 0.00, 0.55, 1.0)
    colors[imgui.COLOR_BUTTON_ACTIVE] = (0.50, 0.00, 0.55, 1.0)

# --- Custom widget functions ---
def custom_tab_bar(tabs, current_tab, width, icon_font, main_font, tab_animations):
    imgui.begin_child("##tabbar", width, 0, border=False)
    for i, tab in enumerate(tabs):
        button_height = 90
        pos = imgui.get_cursor_pos()
        is_selected = (current_tab == i)
        anim = tab_animations[i]

        if imgui.invisible_button(f"##tab_{i}", width, button_height):
            current_tab = i

        draw_list = imgui.get_window_draw_list()
        if anim > 0.001:
            col = list(color_accent)
            col[3] *= anim
            draw_rect_filled(draw_list, *imgui.get_item_rect_min(), *imgui.get_item_rect_max(), col)
        if imgui.is_item_hovered() and not is_selected:
            draw_rect_filled(draw_list, *imgui.get_item_rect_min(), *imgui.get_item_rect_max(), (0.2,0.2,0.2,0.3))
        imgui.push_font(icon_font)
        icon_size = imgui.calc_text_size(tab["icon"])
        imgui.set_cursor_pos((pos[0] + (width - icon_size.x)*0.5, pos[1] + 20))
        imgui.text(tab["icon"])
        imgui.pop_font()
        imgui.push_font(main_font)
        text_width = imgui.calc_text_size(tab["name"]).x
        imgui.set_cursor_pos((pos[0] + (width - text_width)*0.5, pos[1] + button_height - imgui.get_text_line_height() - 20))
        imgui.text(tab["name"])
        imgui.pop_font()
        imgui.set_cursor_pos((pos[0], pos[1] + button_height))
    imgui.end_child()
    return current_tab

def section_header(label, font):
    imgui.push_font(font)
    imgui.push_style_color(imgui.COLOR_TEXT, *color_accent)
    imgui.text(label.upper())
    imgui.separator()
    imgui.pop_style_color()
    imgui.pop_font()

def custom_checkbox(label, state, font):
    imgui.push_font(font)
    imgui.push_style_var(imgui.STYLE_FRAME_ROUNDING, 3)
    changed, new_state = imgui.checkbox(f"##{label}", state)
    imgui.same_line()
    imgui.text(label)
    imgui.pop_style_var()
    imgui.pop_font()
    return changed, new_state

def custom_slider_float(label, value, v_min, v_max, fmt="%.2f", font=None):
    if font: imgui.push_font(font)
    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *color_item_bg)
    imgui.push_style_color(imgui.COLOR_SLIDER_GRAB, *color_accent)
    changed, new_val = imgui.slider_float(f"##{label}", value, v_min, v_max, format=fmt)
    imgui.pop_style_color(2)
    imgui.same_line()
    imgui.text(label)
    if font: imgui.pop_font()
    return changed, new_val

def custom_combo(label, current_item, items, font):
    imgui.push_font(font)
    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *color_item_bg)
    imgui.push_style_color(imgui.COLOR_HEADER, *color_accent)
    imgui.push_style_color(imgui.COLOR_BUTTON, *color_item_bg)
    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *color_item_bg)
    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *color_item_bg)
    new_item = None
    if imgui.begin_combo(f"##{label}", items[current_item] if items else ""):
        for i, item in enumerate(items):
            if imgui.selectable(item, i == current_item)[0]:
                new_item = i
            if i == current_item:
                imgui.set_item_default_focus()
        imgui.end_combo()
    imgui.same_line()
    imgui.text(label)
    imgui.pop_style_color(5)
    imgui.pop_font()
    return new_item

def color_cube(label, color, font):
    imgui.push_font(font)
    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *color_item_bg)
    flags = imgui.COLOR_EDIT_ALPHA_BAR | imgui.COLOR_EDIT_ALPHA_PREVIEW | imgui.COLOR_EDIT_NO_INPUTS
    changed, new_col = imgui.color_edit4(f"##{label}", *color, flags=flags)
    imgui.same_line()
    imgui.text(label)
    imgui.pop_style_color()
    imgui.pop_font()
    return changed, new_col

def draw_esp_preview(settings, font):
    draw_list = imgui.get_window_draw_list()
    pos = imgui.get_cursor_screen_pos()
    size = imgui.get_content_region_available()
    center_x = pos.x + size.x * 0.5
    center_y = pos.y + size.y * 0.5
    box_w = size.x * 0.6
    box_h = box_w * 2.0
    x1, y1 = center_x - box_w/2, center_y - box_h/2
    x2, y2 = center_x + box_w/2, center_y + box_h/2
    head = (center_x, y1 + box_h*0.1)
    neck = (center_x, y1 + box_h*0.2)
    l_shoulder = (center_x - box_w*0.3, y1 + box_h*0.25)
    r_shoulder = (center_x + box_w*0.3, y1 + box_h*0.25)
    l_elbow = (center_x - box_w*0.4, y1 + box_h*0.4)
    r_elbow = (center_x + box_w*0.4, y1 + box_h*0.4)
    spine = (center_x, y1 + box_h*0.45)
    l_hip = (center_x - box_w*0.2, y1 + box_h*0.5)
    r_hip = (center_x + box_w*0.2, y1 + box_h*0.5)
    l_knee = (center_x - box_w*0.22, y1 + box_h*0.75)
    r_knee = (center_x + box_w*0.22, y1 + box_h*0.75)
    l_foot = (center_x - box_w*0.2, y2)
    r_foot = (center_x + box_w*0.2, y2)
    connections = [
        (neck, l_shoulder), (neck, r_shoulder), (l_shoulder, l_elbow), (r_shoulder, r_elbow),
        (neck, spine), (spine, l_hip), (spine, r_hip), (l_hip, l_knee), (r_hip, r_knee),
        (l_knee, l_foot), (r_knee, r_foot)
    ]

    if settings.get("esp_filled_box"):
        draw_rect_filled(draw_list, x1, y1, x2, y2, settings.get("esp_box_fill_spotted_color"))
    if settings.get("esp_box"):
        draw_rect_outline(draw_list, x1, y1, x2, y2, settings.get("esp_box_border_color"), 1.0)
    if settings.get("esp_skeleton"):
        col = imgui.get_color_u32_rgba(*settings.get("esp_skeleton_color"))
        for p1,p2 in connections:
            draw_list.add_line(p1[0], p1[1], p2[0], p2[1], col, 1.0)
    if settings.get("esp_corners"):
        corner_len = box_w * 0.3
        col = imgui.get_color_u32_rgba(*settings.get("esp_enemy_color"))
        draw_list.add_line(x1, y1, x1+corner_len, y1, col, 1.0)
        draw_list.add_line(x1, y1, x1, y1+corner_len, col, 1.0)
        draw_list.add_line(x2, y1, x2-corner_len, y1, col, 1.0)
        draw_list.add_line(x2, y1, x2, y1+corner_len, col, 1.0)
        draw_list.add_line(x1, y2, x1+corner_len, y2, col, 1.0)
        draw_list.add_line(x1, y2, x1, y2-corner_len, col, 1.0)
        draw_list.add_line(x2, y2, x2-corner_len, y2, col, 1.0)
        draw_list.add_line(x2, y2, x2, y2-corner_len, col, 1.0)
    if settings.get("esp_health_bar"):
        hb_x = x1 - 6
        draw_line(draw_list, hb_x, y1, hb_x, y2, settings.get("esp_health_bar_bg_color"), 2.0)
        draw_line(draw_list, hb_x, y1, hb_x, y2, settings.get("esp_health_bar_color"), 2.0)
    if settings.get("esp_armor_bar"):
        ab_y = y2 + 4
        draw_line(draw_list, x1, ab_y, x2, ab_y, settings.get("esp_health_bar_bg_color"), 2.0)
        draw_line(draw_list, x1, ab_y, x2, ab_y, settings.get("esp_armor_bar_color"), 2.0)
    if settings.get("esp_head_dot"):
        draw_circle_filled(draw_list, head[0], head[1], 15, settings.get("esp_head_dot_color"))
    if settings.get("esp_names"):
        draw_text(draw_list, center_x - 30, y1 - 20, "Player", settings.get("esp_name_color"), font)
    if settings.get("esp_weapons"):
        draw_text(draw_list, center_x - 30, y2 + 8, "Weapon", settings.get("esp_weapon_color"), font)

# --- Icon definitions ---
icons = {
    "ESP": "\uF06E",
    "VISUALS": "\uF042",
    "WALK": "\uF007",
    "CONFIGS": "\uF07C",
    "ACCOUNT": "\uF007"
}

# --- Cấu hình các tab ---
config_tabs = [
    {
        "name": "ESP",
        "icon": icons["ESP"],
        "elements": [
            {"type": "checkbox", "label": "Enable ESP", "name": "esp_enable", "default": True},
            {"type": "checkbox", "label": "Visible Check", "name": "esp_visible_check", "default": True},
            {"type": "checkbox", "label": "ESP Box", "name": "esp_box", "default": True},
            {"type": "checkbox", "label": "Filled Box", "name": "esp_filled_box", "default": True, "dependencies": [("esp_box", True)]},
            {"type": "checkbox", "label": "Corners", "name": "esp_corners", "default": True},
            {"type": "checkbox", "label": "Skeleton", "name": "esp_skeleton", "default": True},
            {"type": "checkbox", "label": "Names", "name": "esp_names", "default": True},
            {"type": "checkbox", "label": "Show Teammates", "name": "esp_teammates", "default": False},
            {"type": "checkbox", "label": "Weapons", "name": "esp_weapons", "default": True},
            {"type": "checkbox", "label": "Health Bar", "name": "esp_health_bar", "default": True},
            {"type": "checkbox", "label": "Armor Bar", "name": "esp_armor_bar", "default": True},
            {"type": "checkbox", "label": "Head Dot", "name": "esp_head_dot", "default": True},
            {"type": "checkbox", "label": "Snap Lines", "name": "esp_snap_lines", "default": False},
            {"type": "checkbox", "label": "Eye Lines", "name": "esp_eye_lines", "default": True},
            {"type": "checkbox", "label": "Dropped Weapons", "name": "esp_dropped_weapons", "default": False},
        ]
    },
    {
        "name": "VISUALS",
        "icon": icons["VISUALS"],
        "elements": [
            {"type": "color", "label": "Ally Color", "name": "esp_ally_color"},
            {"type": "color", "label": "Enemy Color", "name": "esp_enemy_color"},
            {"type": "color", "label": "Ally Snapline", "name": "esp_ally_snapline_color"},
            {"type": "color", "label": "Enemy Snapline", "name": "esp_enemy_snapline_color"},
            {"type": "color", "label": "Box Border", "name": "esp_box_border_color"},
            {"type": "color", "label": "Fill Normal", "name": "esp_box_fill_normal_color"},
            {"type": "color", "label": "Fill Spotted", "name": "esp_box_fill_spotted_color"},
            {"type": "color", "label": "Fill Immune", "name": "esp_box_fill_immune_color"},
            {"type": "color", "label": "Health Bar", "name": "esp_health_bar_color"},
            {"type": "color", "label": "Health Bar BG", "name": "esp_health_bar_bg_color"},
            {"type": "color", "label": "Armor Bar", "name": "esp_armor_bar_color"},
            {"type": "color", "label": "Head Dot", "name": "esp_head_dot_color"},
            {"type": "color", "label": "Skeleton", "name": "esp_skeleton_color"},
            {"type": "color", "label": "Name", "name": "esp_name_color"},
            {"type": "color", "label": "Weapon", "name": "esp_weapon_color"},
            {"type": "color", "label": "Eye Line", "name": "esp_eye_line_color"},
            {"type": "color", "label": "Dropped Weapon", "name": "esp_dropped_weapon_color"},
            {"type": "color", "label": "FOV Circle", "name": "esp_fov_color"},
            {"type": "color", "label": "Crosshair", "name": "esp_crosshair_color"},
        ]
    },
    {
        "name": "WALK",
        "icon": icons["WALK"],
        "elements": [
            {"type": "checkbox", "label": "Enable Walkbot", "name": "walkbot_enable", "default": False},
            {"type": "checkbox", "label": "Show Waypoints", "name": "show_waypoints", "default": False},
            {"type": "checkbox", "label": "Shoot All", "name": "friendly_fire", "default": False},
            {"type": "checkbox", "label": "Deathmatch (no strafe, fast aim)", "name": "dm_mode", "default": True},
            {"type": "slider", "label": "Shot Delay (s)", "name": "walkbot_shot_delay", "default": 0.1, "min": 0.1, "max": 1.0, "format": "%.2f"},
            {"type": "slider", "label": "Aim Speed", "name": "walkbot_aim_speed", "default": 15.0, "min": 0.5, "max": 20.0, "format": "%.1f"},
            {"type": "slider", "label": "Headshot Rate (%)", "name": "headshot_rate", "default": 100, "min": 0, "max": 100, "format": "%.0f"},
            {"type": "slider", "label": "Burst Count", "name": "dm_burst_count", "default": 3, "min": 1, "max": 6, "format": "%.0f"},
            {"type": "slider", "label": "Burst Cooldown Min (s)", "name": "dm_burst_cooldown_min", "default": 0.3, "min": 0.1, "max": 1.0, "format": "%.2f"},
            {"type": "slider", "label": "Burst Cooldown Max (s)", "name": "dm_burst_cooldown_max", "default": 0.5, "min": 0.2, "max": 2.0, "format": "%.2f"},
            {"type": "text", "label": "F5: Toggle Walkbot"},
            {"type": "text", "label": "F6: Save waypoint"},
            {"type": "text", "label": "F7: Clear waypoints"},
        ]
    },
    {
        "name": "CONFIGS",
        "icon": icons["CONFIGS"],
        "elements": [
            {"type": "text_input", "label": "Config Name", "name": "config_filename"},
            {"type": "button", "label": "Save Config", "name": "config_save"},
            {"type": "combo", "label": "Load Config", "name": "config_profile", "items": ["Loading..."]},
            {"type": "button", "label": "Load Selected", "name": "config_load"},
            {"type": "combo", "label": "Auto-load Config", "name": "auto_load_config", "items": ["Loading..."]},
            {"type": "button", "label": "Refresh Lists", "name": "config_refresh"},
            {"type": "checkbox", "label": "Hide Console", "name": "hide_console", "default": False},
            {"type": "button", "label": "Exit Program", "name": "exit_program"},
        ]
    },
    {
        "name": "ACCOUNT",
        "icon": icons["ACCOUNT"],
        "elements": [
            {"type": "checkbox", "label": "Enable Auto Switch", "name": "account_switch_enable", "default": False},
            {"type": "slider", "label": "Switch after X maps", "name": "account_switch_after_maps", "default": 1, "min": 1, "max": 10, "format": "%.0f"},
            {"type": "checkbox", "label": "Auto Join Match", "name": "auto_join_match", "default": False},
            {"type": "text", "label": "Account List:"},
            {"type": "combo", "label": "Current Account", "name": "account_current_index", "items": []},
            {"type": "text_input", "label": "Username", "name": "account_username_input"},
            {"type": "text_input", "label": "Password", "name": "account_password_input"},
            {"type": "text_input", "label": "Name", "name": "account_name_input"},
            {"type": "text_input", "label": "Steam ID", "name": "account_steam_id_input"},
            {"type": "button", "label": "Add Account", "name": "account_add_single"},
            {"type": "button", "label": "Remove Selected", "name": "account_remove"},
            {"type": "button", "label": "Switch to Selected", "name": "account_switch_now"},
            {"type": "button", "label": "Switch & Auto Join", "name": "account_switch_and_join"},
            {"type": "separator"},
            {"type": "text", "label": "Team Selection"},
            {"type": "checkbox", "label": "Auto Select Team on Map Change", "name": "auto_select_team", "default": False},
            {"type": "combo", "label": "Preferred Team", "name": "team_preference", "items": ["T", "CT"]},
            {"type": "button", "label": "Select Team T Now", "name": "execute_team_t"},
            {"type": "button", "label": "Select Team CT Now", "name": "execute_team_ct"},
            {"type": "separator"},
            {"type": "text", "label": "Auto Join Points (click positions)"},
            {"type": "button", "label": "Add Current Point", "name": "point_add"},
            {"type": "hotkey", "label": "Add Point Hotkey", "name": "point_add_hotkey"},
            {"type": "button", "label": "Save Points", "name": "point_save"},
            {"type": "button", "label": "Clear All Points", "name": "point_clear"},
            {"type": "table", "label": "Points", "name": "points_table", "headers": ["#", "X", "Y", "Actions"]},
        ]
    }
]

def check_dependencies(element, settings):
    for key, expected in element.get("dependencies", []):
        if settings.get(key) != expected:
            return False
    return True

def begin_disabled(disabled):
    if disabled:
        imgui.push_style_var(imgui.STYLE_ALPHA, imgui.get_style().alpha * 0.5)
    return disabled

def end_disabled(disabled):
    if disabled:
        imgui.pop_style_var()

def menu(settings, exit_event):
    if not glfw.init():
        return

    window_width, window_height = 800, 600
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    window = glfw.create_window(window_width, window_height, "Cheat Menu", None, None)
    if not window:
        glfw.terminate()
        return
    glfw.hide_window(window)
    glfw.make_context_current(window)
    glfw.set_window_pos(window, 100, 100)

    imgui.create_context()
    impl = GlfwRenderer(window)
    io = imgui.get_io()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as f:
        f.write(verdana_bytes)
        verdana_path = f.name
    main_font = io.fonts.add_font_from_file_ttf(verdana_path, 16)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as f:
        f.write(font_awesome)
        fa_path = f.name
    icon_ranges = imgui.core.GlyphRanges([0xf000, 0xf8ff, 0])
    icon_font = io.fonts.add_font_from_file_ttf(fa_path, 30, glyph_ranges=icon_ranges)

    impl.refresh_font_texture()
    setup_imgui_style()

    current_tab = 0
    prev_tab = -1
    tab_animations = [0.0] * len(config_tabs)
    content_alpha = 0.0
    last_tab_change = 0
    last_press = 0
    dragging = False
    visible = False
    config_filename = [""]
    # Biến cho các ô nhập tài khoản
    account_username = [""]
    account_password = [""]
    account_name = [""]
    account_steam_id = [""]
    # Biến quản lý điểm và hotkey
    points_edit = list(settings.get("auto_join_points", []))
    listening_for_hotkey = False
    last_hotkey_time = 0

    # Tìm tab CONFIGS và các phần tử combo
    config_tab_idx = next((i for i, t in enumerate(config_tabs) if t["name"] == "CONFIGS"), None)
    config_combo = None
    auto_config_combo = None
    if config_tab_idx is not None:
        config_combo = next((e for e in config_tabs[config_tab_idx]["elements"] if e.get("name") == "config_profile"), None)
        auto_config_combo = next((e for e in config_tabs[config_tab_idx]["elements"] if e.get("name") == "auto_load_config"), None)

    # Cập nhật danh sách config
    config_list = settings.list_configs()
    if config_combo:
        config_combo["items"] = config_list
    if auto_config_combo:
        auto_config_combo["items"] = config_list

    # Map tên text input tới biến tương ứng
    text_input_vars = {
        "account_username_input": account_username,
        "account_password_input": account_password,
        "account_name_input": account_name,
        "account_steam_id_input": account_steam_id,
        "config_filename": config_filename,
    }

    while not glfw.window_should_close(window):
        if exit_event.is_set():
            break

        current_time = time.time()

        # Xử lý phím tắt toàn cục (kể cả khi menu ẩn)
        hotkey_name = settings.get("point_add_hotkey", "")
        if hotkey_name and hotkey_name in win32_key_map:
            vk = win32_key_map[hotkey_name]
            if vk != 0 and win32api.GetAsyncKeyState(vk) & 1:
                if current_time - last_hotkey_time > 0.3:
                    # Ghi điểm tương đối
                    hwnd = get_window_handle()
                    if hwnd:
                        rect = get_game_window_rect()
                        if rect:
                            cursor = win32api.GetCursorPos()
                            rel_x = cursor[0] - rect[0]
                            rel_y = cursor[1] - rect[1]
                            points_edit.append({"x_rel": float(rel_x), "y_rel": float(rel_y)})
                            print(f"[Menu] Hotkey recorded relative point: ({rel_x}, {rel_y}) | Window rect: {rect}")
                        else:
                            x, y = win32api.GetCursorPos()
                            points_edit.append({"x": float(x), "y": float(y)})
                            print(f"[Menu] Hotkey recorded absolute point: ({x}, {y}) - no window rect")
                    else:
                        x, y = win32api.GetCursorPos()
                        points_edit.append({"x": float(x), "y": float(y)})
                        print(f"[Menu] Hotkey recorded absolute point: ({x}, {y}) - no game window")
                    last_hotkey_time = current_time

        # Xử lý hiện/ẩn menu (phím Insert)
        if win32api.GetAsyncKeyState(win32con.VK_INSERT) < 0:
            if current_time - last_press > 0.3:
                visible = not visible
                last_press = current_time
                if visible:
                    glfw.show_window(window)
                else:
                    glfw.hide_window(window)

        if visible:
            glfw.poll_events()
            impl.process_inputs()
            imgui.new_frame()

            if imgui.is_mouse_clicked(0) and not imgui.is_any_item_hovered() and not imgui.is_any_item_active():
                dragging = True
                win_x, win_y = glfw.get_window_pos(window)
                cursor_x, cursor_y = glfw.get_cursor_pos(window)
                initial_screen = (win_x + cursor_x, win_y + cursor_y)
                initial_win = (win_x, win_y)
            if dragging:
                cur_win_x, cur_win_y = glfw.get_window_pos(window)
                cursor_x, cursor_y = glfw.get_cursor_pos(window)
                cur_screen = (cur_win_x + cursor_x, cur_win_y + cursor_y)
                delta = (cur_screen[0] - initial_screen[0], cur_screen[1] - initial_screen[1])
                glfw.set_window_pos(window, int(initial_win[0] + delta[0]), int(initial_win[1] + delta[1]))
            if imgui.is_mouse_released(0):
                dragging = False

            if prev_tab != current_tab:
                last_tab_change = current_time
                content_alpha = 0.0
                prev_tab = current_tab
            for i in range(len(tab_animations)):
                if i == current_tab:
                    tab_animations[i] = min(tab_animations[i] + io.delta_time * 2, 1.0)
                else:
                    tab_animations[i] = 0.0
            time_since = current_time - last_tab_change
            fade_duration = 0.5
            content_alpha = min(time_since / fade_duration, 1.0)

            imgui.set_next_window_size(window_width, window_height)
            imgui.set_next_window_position(0, 0)
            imgui.begin("MainWindow", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_MOVE)
            imgui.begin_child("MainContent", 0, 0, border=False)

            imgui.begin_group()
            current_tab = custom_tab_bar(config_tabs, current_tab, 120, icon_font, main_font, tab_animations)
            imgui.end_group()
            imgui.same_line()

            # Cập nhật danh sách tài khoản cho combo
            if config_tabs[current_tab]["name"] == "ACCOUNT":
                acc_list = settings.get("account_list", [])
                display_names = []
                for acc in acc_list:
                    if isinstance(acc, dict):
                        name = acc.get("name", acc.get("username", "Unknown"))
                    else:
                        name = str(acc)
                    display_names.append(name)
                for e in config_tabs[current_tab]["elements"]:
                    if isinstance(e, dict) and e.get("name") == "account_current_index":
                        e["items"] = display_names if display_names else ["(empty)"]
                        break

            is_visuals = (config_tabs[current_tab]["name"] == "VISUALS")
            content_width = 450 if is_visuals else 0
            imgui.begin_child("TabContent", content_width, 0, border=False)
            if content_alpha > 0:
                imgui.push_style_var(imgui.STYLE_ALPHA, content_alpha)
                current_elements = config_tabs[current_tab]["elements"]
                section_header(config_tabs[current_tab]["name"], main_font)

                if is_visuals:
                    imgui.columns(2, "visuals_settings", border=False)

                for el in current_elements:
                    disabled = not check_dependencies(el, settings)
                    ds = begin_disabled(disabled)

                    if el["type"] == "checkbox":
                        val = settings.get(el["name"], el.get("default", False))
                        changed, new = custom_checkbox(el["label"], val, main_font)
                        if changed and not disabled:
                            settings.set(el["name"], new)
                            if el["name"] == "hide_console":
                                set_console_visibility(not new)

                    elif el["type"] == "slider":
                        val = settings.get(el["name"], el.get("default", 0.1))
                        changed, new = custom_slider_float(el["label"], val, el["min"], el["max"], el.get("format", "%.2f"), main_font)
                        if changed and not disabled:
                            settings.set(el["name"], new)

                    elif el["type"] == "combo":
                        items = el["items"]
                        if el["name"] == "auto_load_config":
                            current_filename = settings.get(el["name"], "default.json")
                            try:
                                current_idx = items.index(current_filename) if current_filename in items else 0
                            except:
                                current_idx = 0
                            new_idx = custom_combo(el["label"], current_idx, items, main_font)
                            if new_idx is not None and new_idx != current_idx and not disabled:
                                settings.set(el["name"], items[new_idx])
                        elif el["name"] == "account_current_index":
                            val = settings.get(el["name"], 0)
                            new = custom_combo(el["label"], val, items, main_font)
                            if new is not None and new != val and not disabled:
                                settings.set(el["name"], new)
                        elif el["name"] == "team_preference":
                            # 1 = T, 2 = CT
                            val = settings.get("team_preference", 1)
                            current_idx = 0 if val == 1 else 1
                            new_idx = custom_combo(el["label"], current_idx, ["T", "CT"], main_font)
                            if new_idx is not None and new_idx != current_idx:
                                new_val = 1 if new_idx == 0 else 2
                                settings.set("team_preference", new_val)
                        else:
                            val = settings.get(el["name"], 0)
                            new = custom_combo(el["label"], val, items, main_font)
                            if new is not None and new != val and not disabled:
                                settings.set(el["name"], new)

                    elif el["type"] == "color":
                        val = settings.get(el["name"])
                        changed, new = color_cube(el["label"], val, main_font)
                        if changed and not disabled:
                            settings.set(el["name"], new)
                        if is_visuals:
                            imgui.next_column()

                    elif el["type"] == "button":
                        if imgui.button(el["label"]) and not disabled:
                            if el["name"] == "config_save":
                                if config_filename[0]:
                                    settings.save(config_filename[0])
                            elif el["name"] == "config_load":
                                if config_combo:
                                    idx = settings.get("config_profile", 0)
                                    if idx < len(config_combo["items"]):
                                        fname = config_combo["items"][idx]
                                        if fname != "Không tìm thấy config":
                                            settings.load(fname)
                            elif el["name"] == "config_refresh":
                                new_list = settings.list_configs()
                                if config_combo:
                                    config_combo["items"] = new_list
                                if auto_config_combo:
                                    auto_config_combo["items"] = new_list
                            elif el["name"] == "exit_program":
                                exit_event.set()
                            elif el["name"] == "account_add_single":
                                username = account_username[0].strip()
                                if username:
                                    password = account_password[0].strip()
                                    name = account_name[0].strip() or username
                                    steam_id = account_steam_id[0].strip()
                                    acc_list = list(settings.get("account_list", []))
                                    new_acc = {
                                        "username": username,
                                        "password": password,
                                        "name": name,
                                        "steam_id": steam_id
                                    }
                                    acc_list.append(new_acc)
                                    settings.set("account_list", acc_list)
                                    if len(acc_list) == 1:
                                        settings.set("account_current_index", 0)
                                    # Xóa các ô nhập
                                    account_username[0] = ""
                                    account_password[0] = ""
                                    account_name[0] = ""
                                    account_steam_id[0] = ""
                            elif el["name"] == "account_remove":
                                idx = settings.get("account_current_index", 0)
                                acc_list = list(settings.get("account_list", []))
                                if 0 <= idx < len(acc_list):
                                    del acc_list[idx]
                                    settings.set("account_list", acc_list)
                                    if idx >= len(acc_list):
                                        settings.set("account_current_index", max(0, len(acc_list)-1))
                            elif el["name"] == "account_switch_now":
                                idx = settings.get("account_current_index", 0)
                                acc_list = settings.get("account_list", [])
                                if 0 <= idx < len(acc_list):
                                    settings.set("account_switch_request", idx)
                                    print(f"[Menu] Requested switch to account index {idx}")
                                else:
                                    print("[Menu] No account selected")
                            elif el["name"] == "account_switch_and_join":
                                idx = settings.get("account_current_index", 0)
                                acc_list = settings.get("account_list", [])
                                if 0 <= idx < len(acc_list):
                                    settings.set("account_switch_request", idx)
                                    settings.set("force_auto_join_after_switch", True)
                                    print(f"[Menu] Switch & Auto Join requested for account index {idx}")
                                else:
                                    print("[Menu] No account selected")
                            # --- Xử lý nút team selection ---
                            elif el["name"] == "execute_team_t":
                                settings.set("execute_team_t_request", True)
                                print("[Menu] Requested manual Team T selection")
                            elif el["name"] == "execute_team_ct":
                                settings.set("execute_team_ct_request", True)
                                print("[Menu] Requested manual Team CT selection")
                            # ---------------------------------
                            elif el["name"] == "point_add":
                                # Ghi điểm tương đối
                                hwnd = get_window_handle()
                                if hwnd:
                                    rect = get_game_window_rect()
                                    if rect:
                                        cursor = win32api.GetCursorPos()
                                        rel_x = cursor[0] - rect[0]
                                        rel_y = cursor[1] - rect[1]
                                        points_edit.append({"x_rel": float(rel_x), "y_rel": float(rel_y)})
                                        print(f"[Menu] Recorded relative point: ({rel_x}, {rel_y}) | Window rect: {rect}")
                                    else:
                                        x, y = win32api.GetCursorPos()
                                        points_edit.append({"x": float(x), "y": float(y)})
                                        print(f"[Menu] Recorded absolute point: ({x}, {y}) - no window rect")
                                else:
                                    x, y = win32api.GetCursorPos()
                                    points_edit.append({"x": float(x), "y": float(y)})
                                    print(f"[Menu] Recorded absolute point: ({x}, {y}) - no game window")
                            elif el["name"] == "point_save":
                                settings.set("auto_join_points", points_edit)
                                try:
                                    with open("screen_points.json", "w") as f:
                                        json.dump(points_edit, f, indent=4)
                                    print("[Menu] Points saved to screen_points.json")
                                except Exception as e:
                                    print(f"[Menu] Error saving points: {e}")
                            elif el["name"] == "point_clear":
                                points_edit = []

                    elif el["type"] == "text_input":
                        var_list = text_input_vars.get(el["name"])
                        if var_list is not None:
                            changed, new = imgui.input_text(f"##{el['label']}", var_list[0], 64)
                            if changed:
                                var_list[0] = new
                            imgui.same_line()
                            imgui.text(el["label"])

                    elif el["type"] == "hotkey":
                        current_hotkey = settings.get("point_add_hotkey", "None")
                        if imgui.button(f"{el['label']}: {current_hotkey}"):
                            listening_for_hotkey = True
                        if listening_for_hotkey:
                            imgui.text("Press any key...")
                            for key_code, key_name in code_to_name.items():
                                if imgui.is_key_pressed(key_code):
                                    settings.set("point_add_hotkey", key_name)
                                    listening_for_hotkey = False
                                    break

                    elif el["type"] == "table" and el["name"] == "points_table":
                        imgui.columns(4, "points_table", border=True)
                        imgui.text("#"); imgui.next_column()
                        imgui.text("X"); imgui.next_column()
                        imgui.text("Y"); imgui.next_column()
                        imgui.text("Actions"); imgui.next_column()
                        to_delete = None
                        for i, point in enumerate(points_edit):
                            imgui.text(str(i+1)); imgui.next_column()
                            if "x_rel" in point:
                                changed_x, new_x = imgui.input_float(f"##x_{i}", point["x_rel"], format="%.0f")
                                if changed_x:
                                    point["x_rel"] = new_x
                                imgui.next_column()
                                changed_y, new_y = imgui.input_float(f"##y_{i}", point["y_rel"], format="%.0f")
                                if changed_y:
                                    point["y_rel"] = new_y
                            else:
                                changed_x, new_x = imgui.input_float(f"##x_{i}", point["x"], format="%.0f")
                                if changed_x:
                                    point["x"] = new_x
                                imgui.next_column()
                                changed_y, new_y = imgui.input_float(f"##y_{i}", point["y"], format="%.0f")
                                if changed_y:
                                    point["y"] = new_y
                            imgui.next_column()
                            if imgui.button(f"Delete##{i}"):
                                to_delete = i
                            imgui.next_column()
                        if to_delete is not None:
                            points_edit.pop(to_delete)
                        imgui.columns(1)

                    elif el["type"] == "text":
                        imgui.text(el["label"])

                    elif el["type"] == "separator":
                        imgui.separator()

                    end_disabled(ds)

                if is_visuals:
                    imgui.columns(1)
                imgui.pop_style_var()

            imgui.end_child()

            if is_visuals:
                imgui.same_line()
                imgui.begin_child("PreviewPanel", 0, 0, border=True)
                draw_esp_preview(settings, main_font)
                imgui.end_child()

            imgui.end_child()
            imgui.end()

            gl.glClearColor(*color_bg_dark)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            imgui.render()
            impl.render(imgui.get_draw_data())
            glfw.swap_buffers(window)
            time.sleep(0.001)
        else:
            time.sleep(0.05)

    impl.shutdown()
    glfw.terminate()
    try:
        os.remove(verdana_path)
        os.remove(fa_path)
    except:
        pass