from __future__ import annotations

import base64
import ctypes
import locale
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
APP_TITLE = "FixPrint"
APP_ID = "FixPrint.PrinterRepair.20260612"
APP_BUILD = "2026-06-12 16:35"
ICON_FILE = "fixprint.ico"
SPOOL_DIR = Path(r"C:\Windows\System32\spool\PRINTERS")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BG = "#0F1923"
PANEL = "#162030"
FIELD = "#101926"
TEXT = "#E8EFF7"
MUTED = "#8EA4BA"
BLUE = "#2E9CFF"
GREEN = "#00D4A0"
YELLOW = "#F5A623"
RED = "#FF5252"
GRAY = "#4B5563"
SCROLL_THUMB = "#3B4A5F"
SCROLL_TROUGH = "#101926"
LOADING_STATUS = "__loading__"
VIRTUAL_PRINTER_KEYWORDS = ("fax", "onenote", "xps", "pdf", "microsoft print to pdf", "anydesk")


@dataclass
class LocalPrinter:
    name: str
    driver: str = ""
    port: str = ""
    status: str = ""


@dataclass
class RemotePrinterShare:
    server: str
    share_name: str
    share_path: str
    printer_name: str = ""
    driver_name: str = ""


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        args = subprocess.list2cmdline([str(Path(__file__).resolve()), *sys.argv[1:]])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)


def preferred_encoding() -> str:
    return locale.getpreferredencoding(False) or "utf-8"


def decode_bytes(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "cp866", "cp1251", preferred_encoding()):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def run(command: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return done.returncode, decode_bytes(done.stdout), decode_bytes(done.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as exc:
        return -1, "", str(exc)


def ps(script: str, timeout: int = 90) -> tuple[int, str, str]:
    prefix = (
        "$ProgressPreference='SilentlyContinue';"
        "$FixPrintUtf8 = New-Object System.Text.UTF8Encoding $false;"
        "[Console]::OutputEncoding=$FixPrintUtf8;"
        "$OutputEncoding=$FixPrintUtf8;"
        "function Test-FixPrintCommand([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) };"
        "function Get-FixPrintPrinterObjects { "
        "if (Test-FixPrintCommand 'Get-Printer') { return @(Get-Printer -ErrorAction SilentlyContinue | Sort-Object Name) }; "
        "if (Test-FixPrintCommand 'Get-CimInstance') { return @(Get-CimInstance Win32_Printer -ErrorAction SilentlyContinue | Sort-Object Name) }; "
        "return @(Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue | Sort-Object Name) "
        "};"
    )
    encoded = base64.b64encode((prefix + script).encode("utf-16le")).decode("ascii")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
        )
        return done.returncode, done.stdout.strip(), done.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as exc:
        return -1, "", str(exc)


def quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def escape_reg_data(value: str) -> str:
    return value.replace("^", "^^").replace("&", "^&").replace("|", "^|").replace("<", "^<").replace(">", "^>").replace('"', '\\"')


def is_virtual_printer(printer: LocalPrinter) -> bool:
    text = f"{printer.name} {printer.driver}".lower()
    return any(keyword in text for keyword in VIRTUAL_PRINTER_KEYWORDS)


def make_share_name(name: str) -> str:
    share_name = "".join(ch for ch in name if ch not in '\\/:*?"<>|')
    return (share_name or "Printer")[:31]


def get_local_printers() -> tuple[list[LocalPrinter], str]:
    script = r"""
    try {
        Get-FixPrintPrinterObjects | ForEach-Object {
            $name = [string]$_.Name
            $driver = if ($_.PSObject.Properties['DriverName']) { [string]$_.DriverName } else { '' }
            $port = if ($_.PSObject.Properties['PortName']) { [string]$_.PortName } else { '' }
            $status = if ($_.PSObject.Properties['PrinterStatus']) { [string]$_.PrinterStatus } else { '' }
            $name + "`t" + $driver + "`t" + $port + "`t" + $status
        }
        exit 0
    } catch {
        Write-Output $_.Exception.Message
        exit 1
    }
    """
    code, out, err = ps(script, 45)
    if code != 0:
        return [], out or err or "Printerlar ro'yxatini o'qib bo'lmadi."

    printers: list[LocalPrinter] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[0].strip():
            printers.append(
                LocalPrinter(
                    name=parts[0].strip(),
                    driver=parts[1].strip(),
                    port=parts[2].strip(),
                    status=parts[3].strip(),
                )
            )
    return printers, ""


def parse_script_output(output: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    messages: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("LOG:"):
            messages.append(line[4:].strip())
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
            continue
        messages.append(line)
    return values, messages


def extract_server_from_unc(value: str) -> str:
    text = value.strip()
    if text.startswith("\\\\"):
        rest = text[2:]
        return rest.split("\\", 1)[0].strip()
    if text.startswith(",,"):
        rest = text[2:]
        return rest.split(",", 1)[0].strip()
    return ""


def extract_share_path_from_unc(value: str) -> str:
    text = value.strip()
    if text.startswith("\\\\"):
        parts = [part for part in text[2:].split("\\") if part]
        if len(parts) >= 2:
            return f"\\\\{parts[0]}\\{parts[1]}"
    if text.startswith(",,"):
        parts = [part.strip() for part in text[2:].split(",") if part.strip()]
        if len(parts) >= 2:
            return f"\\\\{parts[0]}\\{parts[1]}"
    return ""


def parse_share_path(share_path: str) -> RemotePrinterShare | None:
    text = share_path.strip()
    if not text.startswith("\\\\"):
        return None
    parts = [part for part in text[2:].split("\\") if part]
    if len(parts) < 2:
        return None
    return RemotePrinterShare(server=parts[0], share_name=parts[1], share_path=f"\\\\{parts[0]}\\{parts[1]}")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.set_app_id()
        self.title(APP_TITLE)
        self.set_icon()
        self.geometry("960x680")
        self.minsize(850, 610)
        self.configure(bg=BG)
        self.printers: list[LocalPrinter] = []
        self.candidate_servers: set[str] = set()
        self.candidate_share_paths: set[str] = set()
        self.busy = False
        self.pending_reboot_prompt = False
        self.reboot_dialog = None
        self.ui: queue.Queue[tuple[str, tuple]] = queue.Queue()
        self.configure_styles()
        self.build_ui()
        self.after(100, self.pump)
        self.after(300, self.startup)

    def set_app_id(self) -> None:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    def set_icon(self) -> None:
        paths = []
        if getattr(sys, "frozen", False):
            paths.append(Path(sys.executable))
            paths.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / ICON_FILE)
        paths.append(Path(__file__).resolve().parent / ICON_FILE)
        for path in paths:
            if path.exists():
                try:
                    self.iconbitmap(str(path))
                    return
                except tk.TclError:
                    pass

    def build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(header, text=APP_TITLE, font=("Segoe UI", 24, "bold"), fg=BLUE, bg=BG).pack(side="left")
        tk.Label(
            header,
            text="Administrator" if is_admin() else "Admin kerak",
            font=("Segoe UI", 9),
            fg=GREEN if is_admin() else YELLOW,
            bg=BG,
        ).pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        left = tk.Frame(body, bg=BG, width=370)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=PANEL)
        right.pack(side="left", fill="both", expand=True)
        self.build_left(left)
        self.build_right(right)

    def label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(parent, text=text, font=("Segoe UI", 8, "bold"), fg=MUTED, bg=BG).pack(anchor="w", pady=(10, 5))

    def configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Dark.Vertical.TScrollbar",
            background="#050A10",
            darkcolor="#050A10",
            lightcolor="#050A10",
            troughcolor="#050A10",
            bordercolor="#050A10",
            arrowcolor=TEXT,
            relief="flat",
            width=14,
            arrowsize=12,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#121C28"), ("pressed", "#000000")],
            arrowcolor=[("active", TEXT), ("pressed", BLUE)],
            troughcolor=[("active", "#050A10")],
        )

    def button(self, parent: tk.Widget, text: str, command, bg: str, fg: str = "#00150B") -> None:
        tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 10, "bold"),
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=11,
            cursor="hand2",
        ).pack(fill="x", pady=5)

    def make_textbox(
        self,
        parent: tk.Widget,
        *,
        height: int,
        font: tuple,
        bg: str,
        fg: str,
        padx: int,
        pady: int,
        wrap: str,
    ) -> tuple[tk.Frame, tk.Text]:
        box = tk.Frame(parent, bg=bg)
        text = tk.Text(
            box,
            height=height,
            font=font,
            bg=bg,
            fg=fg,
            insertbackground=fg,
            relief="flat",
            bd=0,
            padx=padx,
            pady=pady,
            wrap=wrap,
            state="disabled",
        )
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=text.yview, style="Dark.Vertical.TScrollbar")
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return box, text

    def build_left(self, parent: tk.Widget) -> None:
        self.label(parent, "1. USHBU KOMPYUTER")

        summary_box = tk.Frame(parent, bg=PANEL)
        summary_box.pack(fill="x", pady=(4, 12))
        self.summary_label = tk.Label(
            summary_box,
            text="Holat tekshirilmoqda...",
            font=("Segoe UI", 10),
            bg=PANEL,
            fg=TEXT,
            wraplength=330,
            justify="left",
            padx=14,
            pady=10,
        )
        self.summary_label.pack(fill="x")
        printer_box, self.printer_summary = self.make_textbox(
            summary_box,
            height=6,
            font=("Segoe UI", 8),
            bg=PANEL,
            fg=TEXT,
            padx=14,
            pady=4,
            wrap="word",
        )
        printer_box.pack(fill="x", padx=0, pady=(0, 10))

        self.label(parent, "2. AMALNI BAJARING")
        
        self.use_persistence = tk.BooleanVar(value=True)
        tk.Checkbutton(
            parent,
            text="Doimiy himoyani yoqish (Tavsiya etiladi)",
            variable=self.use_persistence,
            font=("Segoe UI", 9),
            bg=BG,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=BG,
            activeforeground=TEXT,
            cursor="hand2"
        ).pack(anchor="w", padx=0, pady=(0, 5))
        
        self.button(parent, "Scriptni o'rnatish", lambda: self.start(self.full_fix), GREEN)
        self.button(parent, "Holatni tekshirish", lambda: self.start(self.refresh_printers), YELLOW)
        self.button(parent, "Logni tozalash", self.clear_log, GRAY, TEXT)

        status_box = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground="#223245")
        status_box.pack(fill="x", pady=(18, 0))
        self.status = tk.Label(status_box, text="Tayyor", font=("Segoe UI", 12, "bold"), fg=GREEN, bg=PANEL)
        self.status.pack(pady=(18, 4))
        self.status_hint = tk.Label(status_box, text="Jarayon holati", font=("Segoe UI", 9), fg=MUTED, bg=PANEL)
        self.status_hint.pack(pady=(0, 18))
        tk.Label(
            parent,
            text="Created by Javohir Hojibayev",
            font=("Segoe UI", 8),
            fg=MUTED,
            bg=BG,
        ).pack(side="bottom", anchor="w", pady=(0, 10))

    def build_right(self, parent: tk.Widget) -> None:
        tk.Label(parent, text="LOG VA NATIJA", font=("Segoe UI", 8, "bold"), fg=MUTED, bg=PANEL).pack(anchor="w", padx=16, pady=(14, 6))
        log_box, self.log = self.make_textbox(
            parent,
            height=18,
            font=("Consolas", 9),
            bg=FIELD,
            fg=TEXT,
            padx=12,
            pady=10,
            wrap="word",
        )
        log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        for tag, color in [("ok", GREEN), ("warn", YELLOW), ("err", RED), ("info", BLUE), ("dim", MUTED), ("head", TEXT)]:
            self.log.tag_config(tag, foreground=color)
        self.log.tag_config("head", font=("Consolas", 9, "bold"))

    def pump(self) -> None:
        while True:
            try:
                action, payload = self.ui.get_nowait()
            except queue.Empty:
                break
            if action == "log":
                text, tag = payload
                self.log.config(state="normal")
                self.log.insert("end", text, tag)
                self.log.see("end")
                self.log.config(state="disabled")
            elif action == "set_persistence_checkbox":
                self.use_persistence.set(payload)
            elif action == "status":
                text, color = payload
                if text == LOADING_STATUS:
                    self.status.config(text="Kuting", fg=color)
                else:
                    self.status.config(text=text, fg=color)
            elif action == "progress":
                status_text, hint_text, color = payload
                self.status.config(text=status_text, fg=color)
                self.status_hint.config(text=hint_text, fg=TEXT if hint_text else MUTED)
            elif action == "summary":
                if len(payload) == 3:
                    text, color, printer_text = payload
                else:
                    text, color = payload
                    printer_text = None
                self.summary_label.config(text=text, fg=color)
                if printer_text is not None:
                    self.set_printer_summary(printer_text)
            elif action == "reboot_prompt":
                self.show_reboot_prompt()
            elif action == "done":
                self.busy = False
        self.after(100, self.pump)

    def log_line(self, text: str, tag: str = "") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.ui.put(("log", (f"[{stamp}]  {text}\n", tag)))

    def log_section(self, text: str) -> None:
        self.log_line("-" * 62, "dim")
        self.log_line(text, "head")

    def set_status(self, text: str, color: str = GREEN) -> None:
        self.ui.put(("status", (text, color)))

    def set_progress(self, status_text: str, hint_text: str = "", color: str = BLUE) -> None:
        self.ui.put(("progress", (status_text, hint_text, color)))

    def clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def show_reboot_prompt(self) -> None:
        if self.reboot_dialog and self.reboot_dialog.winfo_exists():
            self.reboot_dialog.lift()
            return
        dialog = tk.Toplevel(self)
        self.reboot_dialog = dialog
        dialog.title(APP_TITLE)
        dialog.geometry("460x260")
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.update_idletasks()
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_w = self.winfo_width()
        parent_h = self.winfo_height()
        dialog_w = dialog.winfo_width()
        dialog_h = dialog.winfo_height()
        x = parent_x + max((parent_w - dialog_w) // 2, 0)
        y = parent_y + max((parent_h - dialog_h) // 2, 0)
        dialog.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")

        panel = tk.Frame(dialog, bg=PANEL, highlightthickness=1, highlightbackground="#223245")
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(panel, text="Qurilmani qayta yuklang", font=("Segoe UI", 18, "bold"), fg=TEXT, bg=PANEL).pack(pady=(28, 10))
        tk.Label(
            panel,
            text="O'zgarishlar to'liq qo'llanishi uchun kompyuterni hozir qayta yuklash tavsiya etiladi.",
            font=("Segoe UI", 10),
            fg=MUTED,
            bg=PANEL,
            wraplength=360,
            justify="center",
        ).pack(padx=24)
        buttons = tk.Frame(panel, bg=PANEL)
        buttons.pack(pady=(28, 0))
        tk.Button(
            buttons,
            text="Ha",
            command=self.reboot_now,
            font=("Segoe UI", 10, "bold"),
            bg=RED,
            fg=TEXT,
            activebackground=RED,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            width=14,
            padx=10,
            pady=10,
            cursor="hand2",
        ).pack(side="left", padx=(0, 10))
        tk.Button(
            buttons,
            text="Keyinroq",
            command=self.close_after_reboot_prompt,
            font=("Segoe UI", 10, "bold"),
            bg=YELLOW,
            fg="#1F1400",
            activebackground=YELLOW,
            activeforeground="#1F1400",
            relief="flat",
            bd=0,
            width=14,
            padx=10,
            pady=10,
            cursor="hand2",
        ).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", self.close_after_reboot_prompt)

    def reboot_now(self) -> None:
        self.log_line("Kompyuter qayta yuklanmoqda...", "warn")
        code, out, err = run("shutdown /r /t 0", 10)
        if code != 0:
            self.log_line(f"Qayta yuklash buyruqida xato: {err or out}", "err")
            messagebox.showerror(APP_TITLE, "Kompyuterni qayta yuklashning imkoni bo'lmadi.")
            return
        self.destroy()

    def close_after_reboot_prompt(self) -> None:
        if self.reboot_dialog and self.reboot_dialog.winfo_exists():
            self.reboot_dialog.destroy()
        self.reboot_dialog = None
        self.destroy()

    def set_printer_summary(self, text: str) -> None:
        self.printer_summary.config(state="normal")
        self.printer_summary.delete("1.0", "end")
        self.printer_summary.insert("end", text)
        self.printer_summary.config(state="disabled")

    def start(self, func) -> None:
        if self.busy:
            self.log_line("Amal bajarilmoqda. Tugashini kuting.", "warn")
            return
        self.busy = True
        threading.Thread(target=self.worker, args=(func,), daemon=True).start()

    def worker(self, func) -> None:
        try:
            self.pending_reboot_prompt = False
            self.set_progress("Tekshirilmoqda", "Jarayon holati", BLUE)
            self.set_status(LOADING_STATUS, YELLOW)
            func()
            self.set_progress("Tayyor", "Jarayon yakunlandi", GREEN)
            self.set_status("Tayyor", GREEN)
        except Exception as exc:
            self.log_line(f"Kutilmagan xato: {exc}", "err")
            self.set_progress("Xato", "Jarayon to'xtadi", RED)
            self.set_status("Xato", RED)
        finally:
            if self.pending_reboot_prompt:
                self.ui.put(("reboot_prompt", ()))
            self.ui.put(("done", ()))

    def startup(self) -> None:
        self.log_line("FixPrint tayyor.", "ok")
        self.log_line(f"Build: {APP_BUILD}", "info")
        self.log_line("Rejim: IP va printer tanlashsiz, faqat ushbu kompyuterni tuzatish.", "info")
        self.start(self.check_persistence_status)
        self.start(self.refresh_printers)

    def check_persistence_status(self) -> None:
        self.log_section("Doimiy himoya holatini tekshirish")
        code, out, _ = ps("Get-ScheduledTask -TaskName 'FixPrint_AutoRepair' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty State", 10)
        if code == 0 and out.strip() in ["Ready", "Running"]:
            self.log_line("Doimiy himoya YOQILGAN (Scheduled Task faol)", "ok")
            self.ui.put(("status", ("Himoya faol", BLUE)))
        else:
            self.log_line("Doimiy himoya O'CHIRILGAN", "dim")

    def enable_persistent_protection(self) -> None:
        self.log_section("Doimiy himoyani yoqish")
        script = r"""
        $taskName = 'FixPrint_AutoRepair'
        $actionScript = {
            $ErrorActionPreference = 'SilentlyContinue'
            $regPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PointAndPrint'
            if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
            $settings = @{
                'RestrictDriverInstallationToAdministrators' = 0
                'TrustedServers' = 0
                'InForest' = 0
                'NoWarningNoElevationOnInstall' = 1
                'UpdatePromptSettings' = 0
                'Restricted' = 0
            }
            foreach ($name in $settings.Keys) {
                New-ItemProperty -Path $regPath -Name $name -PropertyType DWord -Value $settings[$name] -Force | Out-Null
            }

            $pkgPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint'
            if (-not (Test-Path $pkgPath)) { New-Item -Path $pkgPath -Force | Out-Null }
            New-ItemProperty -Path $pkgPath -Name 'PackagePointAndPrintOnly' -PropertyType DWord -Value 0 -Force | Out-Null
            New-ItemProperty -Path $pkgPath -Name 'PackagePointAndPrintServerList' -PropertyType DWord -Value 0 -Force | Out-Null

            $rpcPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Printers\RPC'
            if (-not (Test-Path $rpcPath)) { New-Item -Path $rpcPath -Force | Out-Null }
            New-ItemProperty -Path $rpcPath -Name 'RpcUseNamedPipeProtocol' -PropertyType DWord -Value 1 -Force | Out-Null
            New-ItemProperty -Path $rpcPath -Name 'RpcProtocols' -PropertyType DWord -Value 7 -Force | Out-Null

            $svc = Get-Service -Name Spooler
            if ($svc.Status -ne 'Running') {
                Start-Service -Name Spooler
            }
        }

        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($actionScript.ToString()))
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand $encoded"
        
        $trigger1 = New-ScheduledTaskTrigger -AtStartup
        $trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
        
        $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger1, $trigger2) -Principal $principal -Settings $settings | Out-Null
        Write-Output "OK"
        """
        code, out, err = ps(script, 30)
        if code == 0 and "OK" in out:
            self.log_line("Doimiy himoya yoqildi. GPO o'zgarishlari avtomatik qaytariladi.", "ok")
            self.ui.put(("status", ("Himoya faol", BLUE)))
        else:
            self.log_line(f"Himoyani yoqishda xato: {err or out}", "err")

    def disable_persistent_protection(self) -> None:
        self.log_section("Doimiy himoyani o'chirish")
        code, out, err = ps("Unregister-ScheduledTask -TaskName 'FixPrint_AutoRepair' -Confirm:$false", 15)
        if code == 0:
            self.log_line("Doimiy himoya o'chirildi.", "ok")
            self.ui.put(("status", ("Himoya o'chirilgan", MUTED)))
        else:
            self.log_line(f"Himoyani o'chirishda xato (ehtimol avval yoqilmagan): {err or out}", "dim")

    def apply_printers(self, printers: list[LocalPrinter]) -> None:
        self.printers = printers
        for printer in printers:
            share_path = extract_share_path_from_unc(printer.port) or extract_share_path_from_unc(printer.name)
            if share_path:
                self.candidate_share_paths.add(share_path)
            server = extract_server_from_unc(printer.port) or extract_server_from_unc(printer.name)
            if server:
                self.candidate_servers.add(server)
        if not printers:
            self.ui.put(
                (
                    "summary",
                    (
                        "Printer topilmadi.",
                        YELLOW,
                        "Ushbu kompyuterda o'rnatilgan printer aniqlanmadi.\nPrinter driver yoki printer o'rnatilishi kerak.",
                    ),
                )
            )
            return
        lines = []
        for index, printer in enumerate(printers, start=1):
            lines.append(f"{index}. {printer.name}")
            if printer.driver:
                lines.append(f"   Driver: {printer.driver}")
            if printer.port:
                lines.append(f"   Port: {printer.port}")
        self.ui.put(
            (
                "summary",
                (
                    f"O'rnatilgan printerlar: {len(printers)}",
                    GREEN,
                    "\n".join(lines),
                ),
            )
        )

    def get_candidate_servers(self) -> list[str]:
        servers = set(self.candidate_servers)
        for share_path in self.candidate_share_paths:
            remote = parse_share_path(share_path)
            if remote:
                servers.add(remote.server)
        return sorted(server for server in servers if server)

    def get_candidate_share_paths(self) -> list[str]:
        paths = set(path for path in self.candidate_share_paths if path)
        for printer in self.printers:
            share_path = extract_share_path_from_unc(printer.port) or extract_share_path_from_unc(printer.name)
            if share_path:
                paths.add(share_path)
        return sorted(paths)

    def refresh_printers(self) -> None:
        self.set_progress("Tekshirilmoqda", "Printerlar tekshirilmoqda", BLUE)
        self.log_section("Kompyuter printer holatini tekshirish")
        printers, error = get_local_printers()
        self.apply_printers(printers)
        if printers:
            self.log_line(f"Topilgan lokal printerlar: {len(printers)}", "ok")
            for printer in printers:
                self.log_line(f"  {printer.name} | {printer.driver} | {printer.port}", "dim")
        else:
            self.log_line("Ushbu kompyuterda printer topilmadi.", "warn")
            if error:
                self.log_line(error, "err")
        if not self.pending_reboot_prompt:
            self.set_progress("Tayyor", "Jarayon yakunlandi", GREEN)

    def repair_print_core(self) -> bool:
        self.log_section("Print subsystem tekshirish")
        script = r"""
        $ErrorActionPreference = 'Stop'
        function Key($path) { [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey($path).Close() }
        function Sz($path, $name, $value) {
            $k = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey($path)
            $k.SetValue($name, $value, [Microsoft.Win32.RegistryValueKind]::String)
            $k.Close()
        }
        $base = 'SYSTEM\CurrentControlSet\Control\Print'
        Key "$base\Printers"
        Key "$base\Providers"
        Sz "$base\Providers\Client Side Rendering Print Provider" 'Name' 'win32spl.dll'
        Sz "$base\Providers\Internet Print Provider" 'Name' 'inetpp.dll'
        Sz "$base\Providers\LanMan Print Services" 'Name' 'win32spl.dll'
        Key "$base\Providers\LanMan Print Services\Servers"
        Key "$base\Monitors"
        Sz "$base\Monitors\Local Port" 'Driver' 'localspl.dll'
        Sz "$base\Monitors\Standard TCP/IP Port" 'Driver' 'tcpmon.dll'
        Key "$base\Monitors\Standard TCP/IP Port\Ports"
        if (Test-Path "$env:windir\System32\usbmon.dll") { Sz "$base\Monitors\USB Monitor" 'Driver' 'usbmon.dll' }
        if (Test-Path "$env:windir\System32\FXSMON.DLL") { Sz "$base\Monitors\Microsoft Shared Fax Monitor" 'Driver' 'FXSMON.DLL' }
        Key "$base\Print Processors"
        Sz "$base\Print Processors\winprint" 'Driver' 'winprint.dll'
        Key "$base\Print Processors\winprint\Datatypes"
        Key "$base\Environments\Windows x64\Drivers\Version-3"
        Key "$base\Environments\Windows x64\Drivers\Version-4"
        Sz "$base\Environments\Windows x64\Print Processors\winprint" 'Driver' 'winprint.dll'
        Key "$base\Environments\Windows x64\Print Processors\winprint\Datatypes"
        Write-Output 'OK'
        """
        code, out, _ = ps(script, 45)
        ok = code == 0 and "OK" in out
        self.log_line("Print registry asosiy kalitlari tekshirildi" if ok else "Print registry tekshirishda xato", "ok" if ok else "err")
        return ok

    def registry_fix(self) -> None:
        self.log_section("Registry policy fix")
        commands = [
            r'reg add "HKLM\System\CurrentControlSet\Control\Print" /v RpcAuthnLevelPrivacyEnabled /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcAuthnLevelPrivacyEnabled /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcUseNamedPipeProtocol /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcProtocols /t REG_DWORD /d 7 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v ForceKerberosForRpc /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v Authentication /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v Protocol /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v RestrictDriverInstallationToAdministrators /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v NoWarningNoElevationOnInstall /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v UpdatePromptSettings /t REG_DWORD /d 2 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableWebPnPDownload /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableHTTPPrinting /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableRPCOverTCP /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableBranchOfficeLogging /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v RegisterSpoolerRemoteRpcEndPoint /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\System\CurrentControlSet\Control\Print\Providers\LanMan Print Services\Servers" /v AddPrinterDrivers /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v AllowUserManageForms /t REG_DWORD /d 1 /f',
        ]
        for command in commands:
            code, out, err = run(command, 20)
            value_name = command.split(" /v ")[-1].split(" ")[0]
            self.log_line(f"OK: {value_name}" if code == 0 else f"Xato: {err or out}", "ok" if code == 0 else "err")

    def spooler_fix(self) -> bool:
        self.log_section("Spooler va queue tozalash")
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        Write-Output 'LOG: Spooler startup turi tekshirilmoqda'
        if (Get-Command Set-Service -ErrorAction SilentlyContinue) {{
            Set-Service -Name Spooler -StartupType Automatic
        }}
        Write-Output "LOG: Spooler to'xtatilmoqda"
        Stop-Service -Name Spooler -Force
        Get-Process spoolsv -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 1
        $removed = 0
        $dir = {quote_ps(str(SPOOL_DIR))}
        if (Test-Path $dir) {{
            Get-ChildItem -Path $dir | Where-Object {{ -not $_.PSIsContainer }} | ForEach-Object {{
                Write-Output ("LOG: Queue fayli o'chirildi: " + $_.Name)
                Remove-Item -LiteralPath $_.FullName -Force
                $removed++
            }}
        }}
        Write-Output 'LOG: Spooler qayta ishga tushirilmoqda'
        Start-Service -Name Spooler
        if ((Get-Service -Name Spooler -ErrorAction SilentlyContinue).Status -ne 'Running') {{
            sc.exe start Spooler | Out-Null
            Start-Sleep -Seconds 2
        }}
        if ((Get-Service -Name Spooler -ErrorAction SilentlyContinue).Status -ne 'Running') {{
            net start Spooler | Out-Null
            Start-Sleep -Seconds 2
        }}
        for ($i = 0; $i -lt 60; $i++) {{
            Start-Sleep -Seconds 1
            try {{
                $svc = Get-Service -Name Spooler -ErrorAction Stop
                if ($svc.Status -eq 'Running') {{
                    Write-Output "OK:$removed"
                    exit 0
                }}
            }} catch {{}}
        }}
        Write-Output "FAIL:$removed"
        exit 1
        """
        code, out, _ = ps(script, 60)
        _, messages = parse_script_output(out)
        for message in messages:
            if not message.startswith("OK:") and not message.startswith("FAIL:"):
                self.log_line(message, "dim")
        last = out.splitlines()[-1].strip() if out.strip() else ""
        removed = last.split(":", 1)[1] if ":" in last else "0"
        self.log_line(f"Queue fayllari o'chirildi: {removed}", "ok")
        if code == 0 and last.startswith("OK:"):
            self.log_line("Spooler tayyor", "ok")
            return True
        self.log_line("Spooler javob bermayapti. Windows print subsystem buzilgan bo'lishi mumkin.", "err")
        return False

    def clear_stuck_jobs(self) -> None:
        self.log_section("Printer joblarini tozalash")
        script = r"""
        $count = 0
        try {
            if ((Get-Command Get-PrintJob -ErrorAction SilentlyContinue) -and (Get-Command Remove-PrintJob -ErrorAction SilentlyContinue)) {
                Get-PrintJob -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Output ("LOG: Job o'chirildi: " + $_.PrinterName + " #" + $_.ID)
                    Remove-PrintJob -PrinterName $_.PrinterName -ID $_.ID -ErrorAction SilentlyContinue
                    $count++
                }
            } else {
                Get-WmiObject Win32_PrintJob -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Output ("LOG: Legacy job o'chirildi: " + $_.Name)
                    $_.Delete() | Out-Null
                    $count++
                }
            }
        } catch {}
        Write-Output $count
        """
        code, out, _ = ps(script, 45)
        for line in out.splitlines()[:-1]:
            if line.strip().startswith("LOG:"):
                self.log_line(line.strip()[4:].strip(), "dim")
        count = out.splitlines()[-1].strip() if code == 0 and out.strip() else "0"
        self.log_line(f"Tozalangan joblar: {count}", "ok")

    def repair_core_services(self) -> None:
        self.log_section("Printer network servislarini tiklash")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            ServicesStarted = 0
            ServicesRunning = 0
            FirewallEnabled = 0
            Errors = 0
        }

        foreach ($name in @('Spooler', 'LanmanWorkstation', 'LanmanServer', 'RpcSs', 'DcomLaunch', 'RpcEptMapper')) {
            try {
                Write-Output ("LOG: Servis tekshirilmoqda: " + $name)
                $svc = Get-Service -Name $name -ErrorAction Stop
                if (Get-Command Set-Service -ErrorAction SilentlyContinue) {
                    Set-Service -Name $name -StartupType Automatic -ErrorAction SilentlyContinue
                } else {
                    sc.exe config $name start= auto | Out-Null
                }
                if ($svc.Status -ne 'Running') {
                    Write-Output ("LOG: Servis ishga tushirilmoqda: " + $name)
                    Start-Service -Name $name -ErrorAction SilentlyContinue
                    $summary.ServicesStarted++
                }
                $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
                if ($svc -and $svc.Status -eq 'Running') {
                    Write-Output ("LOG: Servis running: " + $name)
                    $summary.ServicesRunning++
                }
            } catch {
                Write-Output ("LOG: Servis bilan xato: " + $name)
                $summary.Errors++
            }
        }

        try {
            if (Get-Command Get-NetFirewallRule -ErrorAction SilentlyContinue) {
                Write-Output 'LOG: Firewall printer/discovery qoidalari yoqilmoqda'
                $rules = Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object {
                    $_.DisplayGroup -match 'printer|discovery|sharing|smb'
                }
                foreach ($rule in $rules) {
                    Set-NetFirewallRule -Name $rule.Name -Enabled True -ErrorAction SilentlyContinue | Out-Null
                }
                if ($rules) { $summary.FirewallEnabled = @($rules).Count }
            } else {
                Write-Output 'LOG: Netsh orqali File and Printer Sharing yoqilmoqda'
                netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes | Out-Null
                netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes | Out-Null
                $summary.FirewallEnabled = 1
            }
        } catch {
            $summary.Errors++
        }

        try {
            Write-Output 'LOG: Vaqt sinxronizatsiyasi tekshirilmoqda (Kerberos/RPC uchun muhim)'
            w32tm /resync /force 2>$null | Out-Null
            $summary.TimeSynced = 1
        } catch {
            $summary.Errors++
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 90)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"Ishga tushirilgan servislar: {values.get('ServicesStarted', '0')}", "ok")
        self.log_line(f"Running holatdagi servislar: {values.get('ServicesRunning', '0')}", "ok")
        if values.get("FirewallEnabled", "0") != "0":
            self.log_line("Printer, discovery va file sharing firewall qoidalari yoqildi", "ok")
        if values.get("TimeSynced", "0") != "0":
            self.log_line("Vaqt serveri bilan sinxronlashtirildi", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi servis yoki firewall sozlamalarida cheklov bo'lishi mumkin.", "warn")

    def clear_ghost_connections(self) -> None:
        self.log_section("Ghost printer connectionlarni tozalash")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            UserConnectionsRemoved = 0
            MachineConnectionsRemoved = 0
            Errors = 0
        }

        foreach ($path in @(
            'HKCU:\Printers\Connections',
            'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Print\Providers\Client Side Rendering Print Provider\Servers'
        )) {
            try {
                Write-Output ("LOG: User path tekshirildi: " + $path)
                if (Test-Path $path) {
                    Get-ChildItem -Path $path -ErrorAction SilentlyContinue | ForEach-Object {
                        if ($_.PSChildName -match '^,,([^,]+),([^,]+)$') {
                            Write-Output ("HOST:" + $matches[1])
                            Write-Output ("SHARE:\\{0}\{1}" -f $matches[1], $matches[2])
                        }
                        Write-Output ("LOG: User connection o'chirildi: " + $_.PSChildName)
                        Remove-Item -LiteralPath $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue
                        $summary.UserConnectionsRemoved++
                    }
                }
            } catch {
                $summary.Errors++
            }
        }

        foreach ($path in @(
            'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Print\Providers\Client Side Rendering Print Provider\Servers'
        )) {
            try {
                Write-Output ("LOG: Machine path tekshirildi: " + $path)
                if (Test-Path $path) {
                    Get-ChildItem -Path $path -ErrorAction SilentlyContinue | ForEach-Object {
                        Write-Output ("LOG: Machine connection o'chirildi: " + $_.PSChildName)
                        Remove-Item -LiteralPath $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue
                        $summary.MachineConnectionsRemoved++
                    }
                }
            } catch {
                $summary.Errors++
            }
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 60)
        values, messages = parse_script_output(out)
        for message in messages:
            if message.startswith("HOST:"):
                host = message.split(":", 1)[1].strip()
                if host:
                    self.candidate_servers.add(host)
                continue
            if message.startswith("SHARE:"):
                share_path = message.split(":", 1)[1].strip()
                if share_path:
                    self.candidate_share_paths.add(share_path)
                continue
            self.log_line(message, "dim")
        self.log_line(f"User ghost connectionlar tozalandi: {values.get('UserConnectionsRemoved', '0')}", "ok")
        self.log_line(f"Machine ghost connectionlar tozalandi: {values.get('MachineConnectionsRemoved', '0')}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi ghost connection yozuvlari saqlanib qolgan bo'lishi mumkin.", "warn")

    def check_spool_disk_space(self) -> None:
        self.log_section("Spool disk joyi tekshiruvi")
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $dir = {quote_ps(str(SPOOL_DIR))}
        $drive = (Get-Item $dir -ErrorAction SilentlyContinue).PSDrive.Name
        if (-not $drive) {{ $drive = "C" }}
        $vol = Get-PSDrive -Name $drive -ErrorAction SilentlyContinue
        if ($vol) {{
            $freeMb = [math]::Round($vol.Free / 1MB, 0)
            Write-Output "FreeMB=$freeMb"
            Write-Output "Drive=$drive"
        }} else {{
            Write-Output "FreeMB=-1"
        }}
        """
        code, out, _ = ps(script, 20)
        values, _ = parse_script_output(out)
        free_mb = values.get("FreeMB", "-1")
        drive = values.get("Drive", "C")
        try:
            free_mb_int = int(free_mb)
        except ValueError:
            free_mb_int = -1
        if free_mb_int < 0:
            self.log_line("Disk joyini aniqlab bo'lmadi.", "warn")
        elif free_mb_int < 500:
            self.log_line(f"{drive}: diskda joy juda kam qoldi ({free_mb_int} MB) - spooler ishlamasligi mumkin!", "err")
        else:
            self.log_line(f"{drive}: diskda {free_mb_int} MB bo'sh joy mavjud.", "ok")

    def fix_printer_status_and_ports(self) -> None:
        self.log_section("Offline/pauza holatidagi printerlarni tiklash")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            SnmpDisabled = 0
            Unpaused = 0
            Resumed = 0
            Errors = 0
        }
        $hasPrintManagement = [bool](Get-Command Get-Printer -ErrorAction SilentlyContinue)
        if ($hasPrintManagement) {
            $printers = @(Get-Printer -ErrorAction SilentlyContinue)
        } else {
            $printers = @(Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue)
        }

        foreach ($printer in $printers) {
            $name = [string]$printer.Name
            if ($name -match 'fax|onenote|xps|pdf|anydesk') { continue }
            try {
                if ($hasPrintManagement) {
                    if ($printer.PrinterStatus -eq 'Paused') {
                        Write-Output ("LOG: Pauzadan chiqarilmoqda: " + $name)
                        Resume-Printer -Name $name -ErrorAction SilentlyContinue
                        $summary.Unpaused++
                    }
                    $port = $printer.PortName
                    if ($port -and (Get-Command Get-PrinterPort -ErrorAction SilentlyContinue)) {
                        $portObj = Get-PrinterPort -Name $port -ErrorAction SilentlyContinue
                        if ($portObj -and $portObj.SNMPEnabled) {
                            Write-Output ("LOG: SNMP status monitoring o'chirilmoqda: " + $port)
                            Set-PrinterPort -Name $port -SNMPEnabled $false -ErrorAction SilentlyContinue
                            $summary.SnmpDisabled++
                        }
                    }
                } else {
                    $wmiPrinter = Get-WmiObject Win32_Printer -Filter ("Name='{0}'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
                    if ($wmiPrinter -and $wmiPrinter.WorkOffline) {
                        Write-Output ("LOG: Offline rejimi o'chirilmoqda: " + $name)
                        $wmiPrinter.WorkOffline = $false
                        $wmiPrinter.Put() | Out-Null
                        $summary.Resumed++
                    }
                }
            } catch {
                $summary.Errors++
            }
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 45)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"SNMP status monitoring o'chirilgan portlar: {values.get('SnmpDisabled', '0')}", "ok")
        self.log_line(f"Pauzadan chiqarilgan printerlar: {values.get('Unpaused', '0')}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi printer holatlari tekshirilmadi.", "warn")


    def check_dns_resolution(self) -> None:
        servers = self.get_candidate_servers()
        if not servers:
            return
        self.log_section("Print server nomlarini DNS orqali tekshirish")
        entries = "\\n".join(servers)
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $servers = @"
{entries}
"@ -split "`n" | Where-Object {{ $_ -and $_.Trim() }} | Select-Object -Unique

        foreach ($server in $servers) {{
            try {{
                $result = Resolve-DnsName -Name $server -ErrorAction Stop | Select-Object -First 1
                Write-Output ("OK: " + $server + " -> " + $result.IPAddress)
            }} catch {{
                Write-Output ("FAIL: " + $server + " DNS orqali yechilmadi")
            }}
        }}
        """
        code, out, _ = ps(script, 30)
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("OK:"):
                self.log_line(line[3:].strip(), "ok")
            elif line.startswith("FAIL:"):
                self.log_line(line[5:].strip(), "warn")


    def point_and_print_policy_fix(self) -> None:
        """Point and Print Restrictions siyosatini tuzatish.
        
        Xato: 'Установленная на данном компьютере политика не позволяет
        подключение к данной очереди печати.'
        
        Bu metod registry sozlamalarini yozadi va Print Spooler'ni qayta
        ishga tushiradi.
        """
        self.log_section("Point and Print Restrictions siyosatini tuzatish")
        script = r"""
        $ErrorActionPreference = 'Stop'
        $summary = @{
            RegistryKeysSet = 0
            PackageKeysSet = 0
            SpoolerRestarted = 0
            Errors = 0
        }

        # PointAndPrint registry sozlamalari
        $regPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PointAndPrint'
        try {
            if (-not (Test-Path $regPath)) {
                New-Item -Path $regPath -Force | Out-Null
                Write-Output ("LOG: Registry kaliti yaratildi: " + $regPath)
            }

            $settings = [ordered]@{
                'RestrictDriverInstallationToAdministrators' = 0
                'TrustedServers'                             = 0
                'InForest'                                   = 0
                'NoWarningNoElevationOnInstall'               = 1
                'UpdatePromptSettings'                        = 0
                'Restricted'                                  = 0
            }

            foreach ($name in $settings.Keys) {
                New-ItemProperty -Path $regPath -Name $name -PropertyType DWord -Value $settings[$name] -Force | Out-Null
                Write-Output ("LOG: " + $name + " = " + $settings[$name])
                $summary.RegistryKeysSet++
            }
        } catch {
            Write-Output ("LOG: PointAndPrint registry xatosi: " + $_.Exception.Message)
            $summary.Errors++
        }

        # PackagePointAndPrint registry sozlamalari
        $pkgRegPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint'
        try {
            if (-not (Test-Path $pkgRegPath)) {
                New-Item -Path $pkgRegPath -Force | Out-Null
                Write-Output ("LOG: Registry kaliti yaratildi: " + $pkgRegPath)
            }
            New-ItemProperty -Path $pkgRegPath -Name 'PackagePointAndPrintOnly' -PropertyType DWord -Value 0 -Force | Out-Null
            New-ItemProperty -Path $pkgRegPath -Name 'PackagePointAndPrintServerList' -PropertyType DWord -Value 0 -Force | Out-Null
            Write-Output 'LOG: PackagePointAndPrint qiymatlari yozildi'
            $summary.PackageKeysSet = 2
        } catch {
            Write-Output ("LOG: PackagePointAndPrint registry xatosi: " + $_.Exception.Message)
            $summary.Errors++
        }

        # Print Spooler qayta ishga tushirish
        try {
            Write-Output 'LOG: Print Spooler qayta ishga tushirilmoqda'
            Restart-Service -Name Spooler -Force -ErrorAction Stop
            Start-Sleep -Seconds 2
            $svc = Get-Service -Name Spooler -ErrorAction SilentlyContinue
            if ($svc -and $svc.Status -eq 'Running') {
                Write-Output 'LOG: Print Spooler muvaffaqiyatli qayta ishga tushdi'
                $summary.SpoolerRestarted = 1
            } else {
                Write-Output 'LOG: Print Spooler qayta ishga tushmadi'
                $summary.Errors++
            }
        } catch {
            Write-Output ("LOG: Spooler qayta ishga tushirishda xato: " + $_.Exception.Message)
            $summary.Errors++
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 60)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        reg_keys = values.get("RegistryKeysSet", "0")
        pkg_keys = values.get("PackageKeysSet", "0")
        self.log_line(f"PointAndPrint registry qiymatlari yozildi: {reg_keys}", "ok")
        if pkg_keys != "0":
            self.log_line(f"PackagePointAndPrint registry qiymatlari yozildi: {pkg_keys}", "ok")
        if values.get("SpoolerRestarted", "0") == "1":
            self.log_line("Print Spooler muvaffaqiyatli qayta ishga tushdi", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi Point and Print sozlamalarida xato yuz berdi.", "warn")

    def point_and_print_gpo_fix(self) -> None:
        """Domain GPO orqali Point and Print Restrictions siyosatini tarqatish.
        
        Bu faqat Domain Controller yoki RSAT/GroupPolicy moduli o'rnatilgan
        kompyuterlarda ishlaydi. Agar GroupPolicy moduli topilmasa, o'tkazib yuboriladi.
        """
        self.log_section("Domain GPO Point and Print siyosati tekshiruvi")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            GroupPolicyAvailable = 0
            IsDomainJoined = 0
            GpoExists = 0
            GpoCreated = 0
            GpoValuesSet = 0
            Errors = 0
        }

        # Domain a'zoligi tekshirish
        try {
            $computerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
            if ($computerSystem.PartOfDomain) {
                $summary.IsDomainJoined = 1
                Write-Output ("LOG: Kompyuter domen a'zosi: " + $computerSystem.Domain)
            } else {
                Write-Output 'LOG: Kompyuter domenga ulanmagan - GPO qismi o''tkazib yuborildi'
                $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
                exit 0
            }
        } catch {
            Write-Output 'LOG: Domen holatini aniqlab bo''lmadi'
            $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
            exit 0
        }

        # GroupPolicy moduli tekshirish
        if (Get-Module -ListAvailable -Name GroupPolicy) {
            $summary.GroupPolicyAvailable = 1
            Write-Output 'LOG: GroupPolicy moduli mavjud'
        } else {
            Write-Output 'LOG: GroupPolicy moduli topilmadi - RSAT o''rnatilmagan yoki DC emas'  
            Write-Output 'LOG: GPO yaratish o''tkazib yuborildi. Local tuzatish qo''llanildi.'  
            $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
            exit 0
        }

        try {
            Import-Module GroupPolicy -ErrorAction Stop
            $gpoName = 'Printer - PointAndPrint Fix'

            $gpo = Get-GPO -Name $gpoName -ErrorAction SilentlyContinue
            if (-not $gpo) {
                $gpo = New-GPO -Name $gpoName -Comment 'Tarmoq printerlariga ulanish xatosini tuzatish (Point and Print Restrictions) - FixPrint tomonidan yaratildi'
                Write-Output ("LOG: GPO yaratildi: " + $gpoName)
                $summary.GpoCreated = 1
            } else {
                Write-Output ("LOG: Mavjud GPO ishlatilmoqda: " + $gpoName)
                $summary.GpoExists = 1
            }

            $regKey = 'HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PointAndPrint'
            $settings = [ordered]@{
                'RestrictDriverInstallationToAdministrators' = 0
                'TrustedServers'                             = 0
                'InForest'                                   = 0
                'NoWarningNoElevationOnInstall'               = 1
                'UpdatePromptSettings'                        = 0
                'Restricted'                                  = 0
            }

            foreach ($name in $settings.Keys) {
                Set-GPRegistryValue -Name $gpoName -Key $regKey -ValueName $name -Type DWord -Value $settings[$name] | Out-Null
                Write-Output ("LOG: GPO: " + $name + " = " + $settings[$name])
                $summary.GpoValuesSet++
            }

            $pkgRegKey = 'HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint'
            Set-GPRegistryValue -Name $gpoName -Key $pkgRegKey -ValueName 'PackagePointAndPrintOnly' -Type DWord -Value 0 | Out-Null
            Set-GPRegistryValue -Name $gpoName -Key $pkgRegKey -ValueName 'PackagePointAndPrintServerList' -Type DWord -Value 0 | Out-Null
            Write-Output 'LOG: GPO: PackagePointAndPrint qiymatlari yozildi'
            $summary.GpoValuesSet += 2

            Write-Output 'LOG: GPO tayyor. GPMC.msc orqali kerakli OU ga bog''lang'  
            Write-Output 'LOG: Klient kompyuterlarda: gpupdate /force'
        } catch {
            Write-Output ("LOG: GPO yaratish/yangilashda xato: " + $_.Exception.Message)
            $summary.Errors++
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 90)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")

        if values.get("IsDomainJoined", "0") == "0":
            self.log_line("Kompyuter domenga ulanmagan - GPO qismi o'tkazib yuborildi.", "info")
            return

        if values.get("GroupPolicyAvailable", "0") == "0":
            self.log_line("GroupPolicy moduli topilmadi (RSAT o'rnatilmagan). GPO o'tkazib yuborildi.", "warn")
            return

        gpo_values = values.get("GpoValuesSet", "0")
        if values.get("GpoCreated", "0") == "1":
            self.log_line("GPO yaratildi: 'Printer - PointAndPrint Fix'", "ok")
        elif values.get("GpoExists", "0") == "1":
            self.log_line("Mavjud GPO yangilandi: 'Printer - PointAndPrint Fix'", "ok")
        if gpo_values != "0":
            self.log_line(f"GPO registry qiymatlari yozildi: {gpo_values}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("GPO yaratish/yangilashda xato yuz berdi.", "warn")
        else:
            self.log_line("GPO tayyor. GPMC.msc orqali kerakli OU'ga bog'lang.", "info")


    def configure_trusted_print_servers(self) -> None:
        self.log_section("Point and Print cheklovlarini olib tashlash")
        # Eslatma: bu yerda avval "faqat topilgan serverlarga ruxsat" (whitelist)
        # rejimi yoqilardi (Restricted=1, TrustedServers=1). Amalda bu, keyinchalik
        # boshqa/whitelistda yo'q print-serverga ulanishga urinilganda:
        #   "Установленная на данном компьютере политика не позволяет
        #    подключение к данной очереди печати" xatosini keltirib chiqargan.
        # Shuning uchun bu yerda cheklov butunlay o'chiriladi - istalgan
        # print-serverga ulanishga ruxsat beriladi.
        commands = [
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v Restricted /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v TrustedServers /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v InForest /t REG_DWORD /d 0 /f',
            r'reg delete "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v ServerList /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint" /v PackagePointAndPrintOnly /t REG_DWORD /d 0 /f',
            r'reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint" /v PackagePointAndPrintServerList /t REG_DWORD /d 0 /f',
            r'reg delete "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint\ListofServers" /f',
        ]
        for command in commands:
            code, out, err = run(command, 20)
            label = command.split(" /v ")[-1].split(" ")[0] if " /v " in command else command.split("\\")[-1].split(" ")[0]
            if code == 0:
                self.log_line(f"OK: {label}", "ok")
            else:
                self.log_line(f"O'tkazib yuborildi (avval mavjud emas edi): {label}", "dim")
        self.log_line("Point and Print / Package Point and Print cheklovlari o'chirildi.", "ok")

    def repair_server_alias_settings(self) -> None:
        self.log_section("Server alias va print host sozlamalari")
        printers, _ = get_local_printers()
        local_targets = [printer for printer in printers if printer.port and not printer.port.startswith("\\\\") and not is_virtual_printer(printer)]
        if not local_targets:
            self.log_line("Ushbu kompyuterda share qilinadigan lokal printer topilmadi.", "warn")
            return

        commands = [
            r'reg add "HKLM\System\CurrentControlSet\Control\Print" /v DnsOnWire /t REG_DWORD /d 1 /f',
            r'reg add "HKLM\System\CurrentControlSet\Services\LanmanServer\Parameters" /v DisableStrictNameChecking /t REG_DWORD /d 1 /f',
        ]
        for command in commands:
            code, out, err = run(command, 20)
            value_name = command.split(" /v ")[-1].split(" ")[0]
            self.log_line(f"OK: {value_name}" if code == 0 else f"Xato: {value_name} | {err or out}", "ok" if code == 0 else "err")

    def stage_remote_print_drivers(self) -> None:
        self.log_section("Remote printer drayverlarini tayyorlash")
        servers = self.get_candidate_servers()
        if not servers:
            self.log_line("Driver staging uchun server topilmadi.", "warn")
            return

        encoded_entries = "\\n".join(servers)
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{{
            Ready = 0
            Installed = 0
            Errors = 0
        }}

        function Get-DriverCount {{
            if (Get-Command Get-PrinterDriver -ErrorAction SilentlyContinue) {{
                return @((Get-PrinterDriver -ErrorAction SilentlyContinue)).Count
            }}
            return @((Get-WmiObject Win32_PrinterDriver -ErrorAction SilentlyContinue)).Count
        }}

        $servers = @"
{encoded_entries}
"@ -split "`n" | Where-Object {{ $_ -and $_.Trim() }} | Select-Object -Unique

        foreach ($server in $servers) {{
            $printShare = "\\\\$server\\print$"
            Write-Output ("LOG: print$ tekshirildi: " + $printShare)
            if (-not (Test-Path $printShare)) {{
                Write-Output ("LOG: print$ ochilmadi: " + $server)
                $summary.Errors++
                continue
            }}

            $summary.Ready++
            $pattern = "\\\\$server\\print$\\*.inf"
            $before = Get-DriverCount
            $exitCode = -1

            try {{
                $proc = Start-Process -FilePath pnputil.exe -ArgumentList @('/add-driver', $pattern, '/subdirs', '/install') -PassThru -Wait -WindowStyle Hidden
                $exitCode = $proc.ExitCode
            }} catch {{
                $exitCode = -1
            }}

            if ($exitCode -ne 0) {{
                try {{
                    $proc = Start-Process -FilePath pnputil.exe -ArgumentList @('-i', '-a', $pattern) -PassThru -Wait -WindowStyle Hidden
                    $exitCode = $proc.ExitCode
                }} catch {{
                    $exitCode = -1
                }}
            }}

            $after = Get-DriverCount
            if ($exitCode -eq 0) {{
                Write-Output ("LOG: Driver staging bajarildi: " + $server)
                if ($after -gt $before) {{
                    Write-Output ("LOG: Yangi lokal driverlar soni: " + ($after - $before))
                }}
                $summary.Installed++
            }} else {{
                Write-Output ("LOG: Driver staging xatosi: " + $server)
                $summary.Errors++
            }}
        }}

        $summary.GetEnumerator() | ForEach-Object {{ "$($_.Key)=$($_.Value)" }}
        """
        code, out, _ = ps(script, 240)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"print$ ochilgan serverlar: {values.get('Ready', '0')}", "ok")
        self.log_line(f"Driver staging bajarilgan serverlar: {values.get('Installed', '0')}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi serverlardan drayverlarni tayyorlab bo'lmadi.", "warn")

    def create_fallback_local_queues(self) -> None:
        self.log_section("Fallback lokal queue yaratish")
        share_paths = self.get_candidate_share_paths()
        if not share_paths:
            self.log_line("Fallback queue uchun share yo'li topilmadi.", "warn")
            return

        encoded_entries = "\\n".join(share_paths)
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{{
            RemoteInfo = 0
            Created = 0
            Skipped = 0
            MissingDriver = 0
            Errors = 0
        }}

        function Get-CurrentPrinters {{
            if (Get-Command Get-Printer -ErrorAction SilentlyContinue) {{
                return @(Get-Printer -ErrorAction SilentlyContinue)
            }}
            if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {{
                return @(Get-CimInstance Win32_Printer -ErrorAction SilentlyContinue)
            }}
            return @(Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue)
        }}

        function Local-PrinterExists([string]$name, [string]$port) {{
            foreach ($printer in Get-CurrentPrinters) {{
                $pn = if ($printer.PSObject.Properties['Name']) {{ [string]$printer.Name }} else {{ '' }}
                $pp = if ($printer.PSObject.Properties['PortName']) {{ [string]$printer.PortName }} else {{ '' }}
                if ($pn -ieq $name -or $pp -ieq $port) {{ return $true }}
            }}
            return $false
        }}

        function Local-DriverExists([string]$driverName) {{
            if ([string]::IsNullOrWhiteSpace($driverName)) {{ return $false }}
            if (Get-Command Get-PrinterDriver -ErrorAction SilentlyContinue) {{
                return [bool](Get-PrinterDriver -Name $driverName -ErrorAction SilentlyContinue)
            }}
            return [bool](Get-WmiObject Win32_PrinterDriver -ErrorAction SilentlyContinue | Where-Object {{ $_.Name -eq $driverName }} | Select-Object -First 1)
        }}

        function Get-RemotePrinters([string]$server) {{
            if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {{
                try {{ return @(Get-CimInstance Win32_Printer -ComputerName $server -ErrorAction Stop) }} catch {{}}
            }}
            try {{ return @(Get-WmiObject Win32_Printer -ComputerName $server -ErrorAction Stop) }} catch {{}}
            return @()
        }}

        $paths = @"
{encoded_entries}
"@ -split "`n" | Where-Object {{ $_ -and $_.Trim() }} | Select-Object -Unique

        foreach ($sharePath in $paths) {{
            if ($sharePath -notmatch '^\\\\([^\\]+)\\(.+)$') {{
                continue
            }}

            $server = $matches[1]
            $shareName = $matches[2]
            $remotePrinters = @(Get-RemotePrinters $server)
            if (-not $remotePrinters.Count) {{
                Write-Output ("LOG: Remote printer ma'lumoti olinmadi: " + $sharePath)
                $summary.Errors++
                continue
            }}

            $summary.RemoteInfo++
            $remote = $remotePrinters | Where-Object {{
                ([string]$_.ShareName -ieq $shareName) -or
                ([string]$_.Name -ieq $shareName) -or
                ([string]$_.Name -ieq $sharePath)
            }} | Select-Object -First 1

            if (-not $remote) {{
                Write-Output ("LOG: Share topildi, lekin remote printer obyekti mos kelmadi: " + $sharePath)
                $summary.Errors++
                continue
            }}

            $driverName = if ($remote.PSObject.Properties['DriverName']) {{ [string]$remote.DriverName }} else {{ '' }}
            $queueName = $shareName + " (FixPrint)"
            Write-Output ("LOG: Fallback queue tekshirildi: " + $queueName + " | Driver: " + $driverName)

            if (Local-PrinterExists $queueName $sharePath) {{
                Write-Output ("LOG: Fallback queue allaqachon mavjud: " + $queueName)
                $summary.Skipped++
                continue
            }}

            if (-not (Local-DriverExists $driverName)) {{
                Write-Output ("LOG: Lokal driver topilmadi: " + $driverName)
                $summary.MissingDriver++
                continue
            }}

            try {{
                if (Get-Command Add-Printer -ErrorAction SilentlyContinue) {{
                    Add-Printer -Name $queueName -DriverName $driverName -PortName $sharePath -ErrorAction Stop | Out-Null
                }} else {{
                    $printerClass = [WMIClass]'Win32_Printer'
                    $obj = $printerClass.CreateInstance()
                    $obj.DeviceID = $queueName
                    $obj.DriverName = $driverName
                    $obj.PortName = $sharePath
                    $obj.Local = $true
                    $obj.Network = $false
                    $obj.Shared = $false
                    $result = $obj.Put()
                    if (-not $result -or ($result.PSObject.Properties['ReturnValue'] -and $result.ReturnValue -ne 0)) {{
                        throw "WMI queue yaratmadi"
                    }}
                }}
                Start-Sleep -Seconds 2
                if (Local-PrinterExists $queueName $sharePath) {{
                    Write-Output ("LOG: Fallback queue yaratildi: " + $queueName)
                    $summary.Created++
                }} else {{
                    throw "Yaratilgan queue tasdiqlanmadi"
                }}
            }} catch {{
                Write-Output ("LOG: Fallback queue xatosi: " + $queueName + " | " + $_.Exception.Message)
                $summary.Errors++
            }}
        }}

        $summary.GetEnumerator() | ForEach-Object {{ "$($_.Key)=$($_.Value)" }}
        """
        code, out, _ = ps(script, 240)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        if values.get("RemoteInfo", "0") != "0":
            self.log_line(f"Remote printer ma'lumoti o'qilgan sharelar: {values.get('RemoteInfo', '0')}", "ok")
        self.log_line(f"Yaratilgan fallback queue lar: {values.get('Created', '0')}", "ok")
        skipped = values.get("Skipped", "0")
        if skipped != "0":
            self.log_line(f"Avvaldan mavjud fallback queue lar: {skipped}", "ok")
        missing_driver = values.get("MissingDriver", "0")
        if missing_driver != "0":
            self.log_line(f"Lokal driver topilmagan sharelar: {missing_driver}", "warn")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi fallback queue lar yaratilmagan bo'lishi mumkin.", "warn")

    def repair_user_default_registry(self) -> None:
        self.log_section("User printer registry tekshirish")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            LegacyMode = 0
            StaleDeviceRemoved = 0
            Errors = 0
        }

        try {
            $key = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows'
            if (-not (Test-Path $key)) { New-Item -Path $key | Out-Null }
            New-ItemProperty -Path $key -Name LegacyDefaultPrinterMode -PropertyType DWord -Value 1 -Force | Out-Null
            $summary.LegacyMode = 1

            $names = @{}
            foreach ($printer in Get-FixPrintPrinterObjects) {
                if (-not [string]::IsNullOrWhiteSpace($printer.Name)) {
                    $names[$printer.Name.ToLowerInvariant()] = $true
                }
            }

            $deviceValue = (Get-ItemProperty -Path $key -Name Device -ErrorAction SilentlyContinue).Device
            if ($deviceValue) {
                $printerName = ([string]$deviceValue).Split(',')[0].Trim()
                if ($printerName -and -not $names.ContainsKey($printerName.ToLowerInvariant())) {
                    Remove-ItemProperty -Path $key -Name Device -Force -ErrorAction SilentlyContinue
                    Remove-ItemProperty -Path $key -Name UserSelectedDefault -Force -ErrorAction SilentlyContinue
                    Write-Output ("LOG: Eski default yozuvi tozalandi: " + $printerName)
                    $summary.StaleDeviceRemoved++
                } else {
                    Write-Output "LOG: Joriy default printer o'zgartirilmadi"
                }
            } else {
                Write-Output "LOG: Default printer registry yozuvi topilmadi"
            }
        } catch {
            Write-Output ("LOG: User registry xatosi: " + $_.Exception.Message)
            $summary.Errors++
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 45)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        if values.get("LegacyMode", "0") == "1":
            self.log_line("Standart printer qo'lda boshqariladigan (legacy) rejimga o'tkazildi - Windows uni avtomatik almashtirmaydi", "ok")
        removed = values.get("StaleDeviceRemoved", "0")
        if removed != "0":
            self.log_line(f"Eski default registry yozuvi tozalandi: {removed}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("User printer registry qismi to'liq tekshirib bo'linmadi.", "warn")

    def rebuild_network_printers(self) -> None:
        self.log_section("Network printerlarni qayta ulash")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{
            Removed = 0
            Added = 0
            Errors = 0
        }

        function Get-CurrentPrinters {
            if (Get-Command Get-Printer -ErrorAction SilentlyContinue) {
                return @(Get-Printer -ErrorAction SilentlyContinue)
            }
            if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
                return @(Get-CimInstance Win32_Printer -ErrorAction SilentlyContinue)
            }
            return @(Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue)
        }

        $targets = @()
        foreach ($printer in Get-CurrentPrinters) {
            $localName = [string]$printer.Name
            $port = if ($printer.PSObject.Properties['PortName']) { [string]$printer.PortName } else { '' }
            $sharePath = ''
            if ($localName -like '\\*') {
                $sharePath = $localName
            } elseif ($port -like '\\*') {
                $sharePath = $port
            }
            if ($sharePath) {
                $targets += [PSCustomObject]@{ LocalName = $localName; SharePath = $sharePath }
            }
        }

        foreach ($item in $targets) {
            try {
                if ($item.LocalName) {
                    Write-Output ("LOG: Lokal printer olib tashlanmoqda: " + $item.LocalName)
                    if (Get-Command Remove-Printer -ErrorAction SilentlyContinue) {
                        Remove-Printer -Name $item.LocalName -ErrorAction SilentlyContinue
                    } else {
                        (New-Object -ComObject WScript.Network).RemovePrinterConnection($item.LocalName, $true, $true)
                    }
                    $summary.Removed++
                    Start-Sleep -Milliseconds 800
                }
                if ($item.SharePath) {
                    Write-Output ("LOG: Share printer qayta ulanmoqda: " + $item.SharePath)
                    if (Get-Command Add-Printer -ErrorAction SilentlyContinue) {
                        Add-Printer -ConnectionName $item.SharePath -ErrorAction Stop | Out-Null
                    } else {
                        (New-Object -ComObject WScript.Network).AddWindowsPrinterConnection($item.SharePath)
                    }
                    $summary.Added++
                }
            } catch {
                Write-Output ("LOG: Qayta ulash xatosi: " + $_.Exception.Message)
                $summary.Errors++
            }
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        """
        code, out, _ = ps(script, 120)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"Olib tashlangan network printerlar: {values.get('Removed', '0')}", "ok")
        self.log_line(f"Qayta ulangan network printerlar: {values.get('Added', '0')}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi network printerlar qayta ulanmagan bo'lishi mumkin.", "warn")

    def reconnect_discovered_server_shares(self) -> None:
        self.log_section("Topilgan server share printerlarini ulash")
        share_paths = sorted(path for path in self.candidate_share_paths if path)
        if not share_paths:
            servers = sorted(server for server in self.candidate_servers if server)
            if servers:
                self.log_line("Aniq share yo'li topilmadi, faqat serverlar aniqlandi.", "warn")
                for server in servers:
                    self.log_line(f"Server topildi: {server}", "dim")
            else:
                self.log_line("Reconnect uchun share yoki server topilmadi.", "warn")
            return

        encoded_entries = "\\n".join(share_paths)
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{{
            Added = 0
            Skipped = 0
            Errors = 0
        }}

        function Get-CurrentPrinters {{
            if (Get-Command Get-Printer -ErrorAction SilentlyContinue) {{
                return @(Get-Printer -ErrorAction SilentlyContinue)
            }}
            if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {{
                return @(Get-CimInstance Win32_Printer -ErrorAction SilentlyContinue)
            }}
            return @(Get-WmiObject Win32_Printer -ErrorAction SilentlyContinue)
        }}

        function Printer-ExistsByShare([string]$sharePath) {{
            foreach ($printer in Get-CurrentPrinters) {{
                $name = if ($printer.PSObject.Properties['Name']) {{ [string]$printer.Name }} else {{ '' }}
                $port = if ($printer.PSObject.Properties['PortName']) {{ [string]$printer.PortName }} else {{ '' }}
                if ($name -ieq $sharePath -or $port -ieq $sharePath) {{ return $true }}
            }}
            return $false
        }}

        $paths = @"
{encoded_entries}
"@ -split "`n" | Where-Object {{ $_ -and $_.Trim() }} | Select-Object -Unique

        foreach ($sharePath in $paths) {{
            Write-Output ("LOG: Share tekshirildi: " + $sharePath)
            if (Printer-ExistsByShare $sharePath) {{
                Write-Output ("LOG: Allaqachon mavjud: " + $sharePath)
                $summary.Skipped++
                continue
            }}

            try {{
                if (Get-Command Add-Printer -ErrorAction SilentlyContinue) {{
                    Add-Printer -ConnectionName $sharePath -ErrorAction Stop | Out-Null
                }} else {{
                    (New-Object -ComObject WScript.Network).AddWindowsPrinterConnection($sharePath)
                }}
                Start-Sleep -Seconds 2
                if (Printer-ExistsByShare $sharePath) {{
                    Write-Output ("LOG: Ulandi: " + $sharePath)
                    $summary.Added++
                }} else {{
                    throw "Printer connection tasdiqlanmadi"
                }}
            }} catch {{
                Write-Output ("LOG: Ulanmadi: " + $sharePath + " | " + $_.Exception.Message)
                $summary.Errors++
            }}
        }}

        $summary.GetEnumerator() | ForEach-Object {{ "$($_.Key)=$($_.Value)" }}
        """
        code, out, _ = ps(script, 120)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"Topilgan share printerlardan ulanganlari: {values.get('Added', '0')}", "ok")
        skipped = values.get("Skipped", "0")
        if skipped != "0":
            self.log_line(f"Allaqachon mavjud bo'lgan share printerlar: {skipped}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi share printerlar ulanmagan bo'lishi mumkin.", "warn")

    def repair_server_shares(self) -> None:
        self.log_section("Server tomoni printer share sozlamalari")
        printers, _ = get_local_printers()
        local_targets = [printer for printer in printers if printer.port and not printer.port.startswith("\\\\") and not is_virtual_printer(printer)]
        if not local_targets:
            self.log_line("Share uchun mos lokal printer topilmadi.", "warn")
            return

        entries = []
        for printer in local_targets:
            share_name = "".join(ch for ch in printer.name if ch not in '\\/:*?"<>|')
            share_name = (share_name or "Printer")[:31]
            entries.append(f"{printer.name}\t{share_name}")
        encoded_entries = "\\n".join(entries)
        script = f"""
        $ErrorActionPreference = 'SilentlyContinue'
        $summary = @{{
            Shared = 0
            Errors = 0
        }}
        $pairs = @"
{encoded_entries}
"@ -split "`n" | Where-Object {{ $_ -and $_.Trim() }}

        foreach ($line in $pairs) {{
            $parts = $line -split "`t", 2
            if ($parts.Count -lt 2) {{ continue }}
            $printerName = $parts[0]
            $shareName = $parts[1]
            Write-Output ("LOG: Share yoqilmoqda: " + $printerName + " => " + $shareName)
            try {{
                $enabled = $false
                if (Get-Command Get-Printer -ErrorAction SilentlyContinue) {{
                    Set-Printer -Name $printerName -Shared $true -ShareName $shareName -ErrorAction Stop | Out-Null
                    $check = Get-Printer -Name $printerName -ErrorAction SilentlyContinue
                    if ($check -and $check.Shared -and $check.ShareName -eq $shareName) {{
                        $enabled = $true
                    }}
                }} else {{
                    $printer = Get-WmiObject Win32_Printer -Filter ("Name='{{0}}'" -f $printerName.Replace("'", "''")) -ErrorAction SilentlyContinue
                    if ($printer) {{
                        $printer.Shared = $true
                        $printer.ShareName = $shareName
                        $printer.Put() | Out-Null
                        Start-Sleep -Seconds 1
                        $check = Get-WmiObject Win32_Printer -Filter ("Name='{{0}}'" -f $printerName.Replace("'", "''")) -ErrorAction SilentlyContinue
                        if ($check -and $check.Shared -and $check.ShareName -eq $shareName) {{
                            $enabled = $true
                        }}
                    }}
                }}
                if ($enabled) {{
                    Write-Output ("LOG: Share yoqildi: " + $printerName)
                    $summary.Shared++
                }} else {{
                    throw "Share holati tasdiqlanmadi"
                }}
            }} catch {{
                Write-Output ("LOG: Share xatosi: " + $_.Exception.Message)
                $summary.Errors++
            }}
        }}

        $summary.GetEnumerator() | ForEach-Object {{ "$($_.Key)=$($_.Value)" }}
        """
        code, out, _ = ps(script, 120)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")
        self.log_line(f"Share yoqilgan printerlar: {values.get('Shared', '0')}", "ok")
        if values.get("Errors", "0") != "0" or code != 0:
            self.log_line("Ba'zi share sozlamalari server tomonda to'liq qo'llanmagan bo'lishi mumkin.", "warn")

    def repair_709_and_connections(self) -> None:
        self.log_section("0x00000709 va network-printer sozlamalari")
        script = r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $hasPrintManagement = (Test-FixPrintCommand 'Get-Printer') -and (Test-FixPrintCommand 'Get-PrinterPort') -and (Test-FixPrintCommand 'Add-PrinterPort')
        $summary = @{
            StaleUserEntries = 0
            PortsFixed = 0
            LocalQueuesCreated = 0
            Errors = 0
        }

        function Ensure-Key($path) {
            if (-not (Test-Path $path)) { New-Item -Path $path | Out-Null }
        }

        function Port-Exists($name) {
            if (-not $hasPrintManagement) { return $false }
            return [bool](Get-PrinterPort -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $name } | Select-Object -First 1)
        }

        try {
            $printers = @(Get-FixPrintPrinterObjects)
            $names = @{}
            foreach ($printer in $printers) { $names[$printer.Name] = $true }

            foreach ($keyPath in @(
                'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Devices',
                'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\PrinterPorts'
            )) {
                if (Test-Path $keyPath) {
                    $props = (Get-ItemProperty -Path $keyPath).PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' }
                    foreach ($prop in $props) {
                        if (-not $names.ContainsKey($prop.Name)) {
                            Write-Output ("LOG: Eski user yozuvi o'chirildi: " + $prop.Name)
                            Remove-ItemProperty -Path $keyPath -Name $prop.Name -Force
                            $summary.StaleUserEntries++
                        }
                    }
                }
            }
        } catch {
            $summary.Errors++
            $printers = @()
        }

        if ($hasPrintManagement) {
            try {
            foreach ($printer in $printers) {
                if ([string]::IsNullOrWhiteSpace($printer.PortName)) { continue }
                if ($printer.PortName -like '\\*') {
                    if (-not (Port-Exists $printer.PortName)) {
                        Write-Output ("LOG: Port yaratilmoqda: " + $printer.PortName)
                        Add-PrinterPort -Name $printer.PortName -ErrorAction SilentlyContinue
                        if (Port-Exists $printer.PortName) { $summary.PortsFixed++ }
                    }

                    if ($printer.Name -match '^\\\\([^\\]+)\\(.+)$') {
                        $server = $matches[1]
                        $share = $matches[2]
                        $localName = "$share on $server"
                        $exists = Get-Printer -Name $localName -ErrorAction SilentlyContinue
                        if (-not $exists -and -not [string]::IsNullOrWhiteSpace($printer.DriverName)) {
                            Write-Output ("LOG: Lokal queue yaratilmoqda: " + $localName)
                            Add-Printer -Name $localName -DriverName $printer.DriverName -PortName $printer.PortName -ErrorAction SilentlyContinue
                            if (Get-Printer -Name $localName -ErrorAction SilentlyContinue) { $summary.LocalQueuesCreated++ }
                        }
                    }
                }
            }
            } catch {
                $summary.Errors++
            }
        }

        $summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        exit 0
        """
        code, out, _ = ps(script, 90)
        values, messages = parse_script_output(out)
        for message in messages:
            self.log_line(message, "dim")

        self.log_line(f"Eski user printer yozuvlari tozalandi: {values.get('StaleUserEntries', '0')}", "ok")
        self.log_line(f"Network printer portlari tiklandi: {values.get('PortsFixed', '0')}", "ok")
        created = values.get("LocalQueuesCreated", "0")
        if created != "0":
            self.log_line(f"Shared printer uchun lokal queue yaratildi: {created}", "ok")
        errors = values.get("Errors", "0")
        if code != 0 or errors != "0":
            self.log_line("Ba'zi connection sozlamalari tiklanmadi, lekin asosiy repair davom etadi", "warn")

    def full_fix(self) -> None:
        self.log_section("Kompyuterdagi printer muammolarini tuzatish")
        self.candidate_servers.clear()
        self.candidate_share_paths.clear()
        self.set_progress("Tekshirilmoqda", "Disk joyi tekshirilmoqda", BLUE)
        self.check_spool_disk_space()
        self.set_progress("Tekshirilmoqda", "Servislar va firewall sozlanmoqda", BLUE)
        self.repair_core_services()
        self.set_progress("Tekshirilmoqda", "Print subsystem tekshirilmoqda", BLUE)
        self.repair_print_core()
        self.set_progress("Tekshirilmoqda", "Registry sozlamalari yozilmoqda", BLUE)
        self.registry_fix()
        self.set_progress("Tekshirilmoqda", "Point and Print siyosati tuzatilmoqda", BLUE)
        self.point_and_print_policy_fix()
        self.set_progress("Kuting", "Spooler va queue tozalanmoqda", YELLOW)
        spooler_ready = self.spooler_fix()
        if not spooler_ready:
            self.log_line("Spooler to'liq tiklanmadi, ammo qolgan repair davom etadi.", "warn")
        self.set_progress("Tekshirilmoqda", "Ghost connectionlar tozalanmoqda", BLUE)
        self.clear_ghost_connections()
        self.set_progress("Tekshirilmoqda", "Print server DNS tekshirilmoqda", BLUE)
        self.check_dns_resolution()
        self.set_progress("Tekshirilmoqda", "Trusted server siyosatlari yozilmoqda", BLUE)
        self.configure_trusted_print_servers()
        self.set_progress("Tekshirilmoqda", "Server share sozlamalari tiklanmoqda", BLUE)
        self.repair_server_shares()
        self.set_progress("Tekshirilmoqda", "Server alias sozlamalari yozilmoqda", BLUE)
        self.repair_server_alias_settings()
        self.set_progress("Tekshirilmoqda", "Remote drayverlar tayyorlanmoqda", BLUE)
        self.stage_remote_print_drivers()
        self.set_progress("Tekshirilmoqda", "Printer joblari o'chirilmoqda", BLUE)
        self.clear_stuck_jobs()
        self.set_progress("Tekshirilmoqda", "Offline/pauza holatlar tuzatilmoqda", BLUE)
        self.fix_printer_status_and_ports()
        self.set_progress("Tekshirilmoqda", "Connection sozlamalari tiklanmoqda", BLUE)
        self.repair_709_and_connections()
        self.set_progress("Tekshirilmoqda", "User printer registry tiklanmoqda", BLUE)
        self.repair_user_default_registry()
        self.set_progress("Tekshirilmoqda", "Network printerlar qayta ulanmoqda", BLUE)
        self.rebuild_network_printers()
        self.set_progress("Tekshirilmoqda", "Topilgan share printerlar ulanmoqda", BLUE)
        self.reconnect_discovered_server_shares()
        self.set_progress("Tekshirilmoqda", "Fallback queue lar yaratilmoqda", BLUE)
        self.create_fallback_local_queues()
        self.set_progress("Tekshirilmoqda", "Domain GPO tekshirilmoqda", BLUE)
        self.point_and_print_gpo_fix()
        
        if self.use_persistence.get():
            self.set_progress("Tekshirilmoqda", "Doimiy himoya yoqilmoqda", BLUE)
            self.enable_persistent_protection()
        else:
            self.set_progress("Tekshirilmoqda", "Doimiy himoya o'chirilmoqda", BLUE)
            self.disable_persistent_protection()
            
        self.set_progress("Tekshirilmoqda", "Yakuniy tekshiruv bajarilmoqda", BLUE)
        self.refresh_printers()
        self.log_line("Jarayon yakunlandi.", "ok")
        self.pending_reboot_prompt = True


def main() -> int:
    if not is_admin():
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesno(APP_TITLE, "Administrator huquqi kerak.\n\nAdmin sifatida qayta ishga tushirilsinmi?")
        root.destroy()
        if answer:
            relaunch_as_admin()
        return 0
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
