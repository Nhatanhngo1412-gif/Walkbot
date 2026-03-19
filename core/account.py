import os
import json
import psutil
import subprocess
import time
from colorama import Fore, Style
from core.utils import get_data_path

class SteamAccount:
    def __init__(self, username, password="", name="", steam_id=""):
        self.username = username
        self.password = password
        self.name = name
        self.steam_id = steam_id

    def to_dict(self):
        return {
            "username": self.username,
            "password": self.password,
            "name": self.name,
            "steam_id": self.steam_id
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            username=data.get("username", ""),
            password=data.get("password", ""),
            name=data.get("name", ""),
            steam_id=data.get("steam_id", "")
        )

class SteamAccountManager:
    def __init__(self, config_folder=None):
        if config_folder is None:
            config_folder = get_data_path()
        self.config_folder = config_folder
        self.accounts_file = os.path.join(config_folder, "steam_accounts.json")
        self.current_account_index = 0
        self.accounts = []
        self.steam_path = self.find_steam_path()
        self.tcno_path = r"C:\Program Files\TcNo Account Switcher\TcNo-Acc-Switcher.exe"
        self.load_accounts()

    def find_steam_path(self):
        possible_paths = [
            "C:\\Program Files (x86)\\Steam\\steam.exe",
            "C:\\Program Files\\Steam\\steam.exe",
            os.path.expanduser("~\\AppData\\Local\\Programs\\Steam\\steam.exe"),
            os.path.expanduser("~\\Desktop\\Steam\\steam.exe")
        ]
        for path in possible_paths:
            if os.path.exists(path):
                print(Fore.GREEN + f"[Account] Found Steam at: {path}" + Style.RESET_ALL)
                return path
        print(Fore.RED + "[Account] Steam not found in common locations" + Style.RESET_ALL)
        return None

    def load_accounts(self):
        if os.path.exists(self.accounts_file):
            try:
                with open(self.accounts_file, 'r') as f:
                    accounts_data = json.load(f)
                    self.accounts = [SteamAccount.from_dict(acc) for acc in accounts_data]
                print(Fore.GREEN + f"[Account] Loaded {len(self.accounts)} accounts from {self.accounts_file}" + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + f"[Account] Failed to load accounts: {e}" + Style.RESET_ALL)
                self.accounts = []
        else:
            print(Fore.YELLOW + f"[Account] No accounts file found at {self.accounts_file}, starting empty." + Style.RESET_ALL)
            self.accounts = []

    def save_accounts(self):
        try:
            os.makedirs(self.config_folder, exist_ok=True)
            accounts_data = [acc.to_dict() for acc in self.accounts]
            with open(self.accounts_file, 'w') as f:
                json.dump(accounts_data, f, indent=4)
            return True
        except Exception as e:
            print(Fore.RED + f"[Account] Failed to save accounts: {e}" + Style.RESET_ALL)
            return False

    def add_account(self, username, password="", name="", steam_id=""):
        for acc in self.accounts:
            if acc.username == username:
                return False
        new_account = SteamAccount(username, password, name, steam_id)
        self.accounts.append(new_account)
        return self.save_accounts()

    def remove_account(self, index):
        if 0 <= index < len(self.accounts):
            self.accounts.pop(index)
            return self.save_accounts()
        return False

    def get_current_account(self):
        if 0 <= self.current_account_index < len(self.accounts):
            return self.accounts[self.current_account_index]
        return None

    def switch_account(self, index):
        if 0 <= index < len(self.accounts):
            self.current_account_index = index
            return True
        return False

    def kill_steam(self):
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'steam' in proc.info['name'].lower():
                    proc.kill()
                    print(Fore.YELLOW + f"[Account] Killed Steam process: {proc.info['name']}" + Style.RESET_ALL)
            time.sleep(2)
            return True
        except:
            return False

    def launch_steam_with_tcno(self, account_index=None):
        if not os.path.exists(self.tcno_path):
            print(Fore.RED + f"[Account] TcNo not found at: {self.tcno_path}" + Style.RESET_ALL)
            return False

        if account_index is None:
            account_index = self.current_account_index
        if account_index >= len(self.accounts):
            return False

        account = self.accounts[account_index]
        if not account.steam_id:
            print(Fore.RED + f"[Account] Account {account.name} has no steam_id!" + Style.RESET_ALL)
            return False

        self.kill_steam()
        time.sleep(2)

        cmd = f'"{self.tcno_path}" +s:{account.steam_id}'
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(cmd, startupinfo=startupinfo, shell=True)
            print(Fore.CYAN + f"[Account] TcNo command sent: {cmd}" + Style.RESET_ALL)
            time.sleep(5)

            if self.steam_path:
                steam_cmd = f'"{self.steam_path}"'
                subprocess.Popen(steam_cmd, startupinfo=startupinfo, shell=True)
                print(Fore.GREEN + f"[Account] Steam launched for account: {account.name or account.username}" + Style.RESET_ALL)
                time.sleep(15)
            return True
        except Exception as e:
            print(Fore.RED + f"[Account] TcNo launch failed: {e}" + Style.RESET_ALL)
            return False

    def launch_cs2(self):
        if not self.steam_path:
            return False
        steam_running = any(proc.info['name'] and 'steam' in proc.info['name'].lower() for proc in psutil.process_iter(['name']))
        if not steam_running:
            print(Fore.YELLOW + "[Account] Steam not running, launching with current account..." + Style.RESET_ALL)
            if not self.launch_steam_with_tcno():
                return False
        time.sleep(5)
        cmd = f'"{self.steam_path}" -applaunch 730'
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(cmd, startupinfo=startupinfo)
            print(Fore.GREEN + "[Account] CS2 launch command sent" + Style.RESET_ALL)
            return True
        except Exception as e:
            print(Fore.RED + f"[Account] Failed to launch CS2: {e}" + Style.RESET_ALL)
            return False