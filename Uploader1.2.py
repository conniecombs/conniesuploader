import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext, ttk
from ttkthemes import ThemedTk
import threading
import queue
import requests
from requests.exceptions import JSONDecodeError
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
import os
import mimetypes
import json
import abc
import keyring
import platform
import subprocess
import logging
from pathlib import Path
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import pyperclip
import time
from typing import Dict, Tuple, List, Optional, Any
from urllib.parse import urlparse, parse_qs
import re

# --- Natural sort helper ---
def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

# Constants
class Constants:
    IMX_URL = "https://api.imx.to/v1/upload.php"
    PIX_URL = "https://api.pixhost.to/images"
    PIX_COVERS_URL = "https://api.pixhost.to/covers"  # Added for covers
    PIX_GALLERIES_URL = "https://api.pixhost.to/galleries"
    IMX_LOGIN_URL = "https://imx.to/user/dashboard"
    IMX_GALLERY_ADD_URL = "https://imx.to/user/gallery/add"
    IMX_GALLERY_EDIT_URL = "https://imx.to/user/gallery/edit"
    SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    MAX_FILES_WARNING = 1000
    RETRY_TOTAL = 3
    RETRY_BACKOFF = 1
    RETRY_STATUS = [500, 502, 503, 504]
    
    KEYRING_SERVICE_API = "ImageUploader:imx_api_key"
    KEYRING_SERVICE_USER = "ImageUploader:imx_username"
    KEYRING_SERVICE_PASS = "ImageUploader:imx_password"

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- BaseUploader ---
class BaseUploader(abc.ABC):
    def __init__(self, username: Optional[str], password: Optional[str], file_path: str, monitor_callback: Any):
        self.username = username
        self.password = password
        self.file_path = file_path
        self.basename = os.path.basename(file_path)
        self.mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        self.file_obj = None
        self.monitor_callback = monitor_callback
        self.headers: Dict[str, str] = {}

    def get_monitor(self, fields: Dict[str, Any]) -> MultipartEncoderMonitor:
        encoder = MultipartEncoder(fields=fields)
        monitor = MultipartEncoderMonitor(encoder, self.monitor_callback)
        self.headers['Content-Type'] = monitor.content_type
        return monitor

    @abc.abstractmethod
    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        pass

    @abc.abstractmethod
    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        pass

    def close(self) -> None:
        if self.file_obj:
            self.file_obj.close()

# --- ImxUploader ---
class ImxUploader(BaseUploader):
    def __init__(self, username: Optional[str], api_key: Optional[str], file_path: str, monitor_callback: Any,
                 thumb_size_str: str, gallery_id: Optional[str]):
        super().__init__(username, api_key, file_path, monitor_callback)
        size_to_api_map = {"100": "1", "180": "2", "250": "3", "300": "4", "600": "5", "150": "6"}
        self.thumb_size = size_to_api_map.get(thumb_size_str, "2")
        self.gallery_id = gallery_id

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url = Constants.IMX_URL
        self.headers['X-API-KEY'] = self.password or ""
        fields: Dict[str, Any] = {
            "image": (self.basename, self.file_obj, self.mime_type),
            "format": "json",
            "thumbnail_size": self.thumb_size,
        }
        if self.gallery_id:
            fields["gallery_id"] = self.gallery_id
        monitor = self.get_monitor(fields)
        return url, monitor, self.headers

    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response format: {type(data)}")
        status = data.get("status")
        if status == "success":
            data_obj = data.get("data")
            if not data_obj:
                raise ValueError("Success status, but no 'data' object found.")
            uploaded_url = data_obj.get("image_url")
            th_url = data_obj.get("thumbnail_url")
            if not uploaded_url or not th_url:
                raise ValueError("Success status, but URLs missing.")
            return uploaded_url, th_url
        elif status == "error":
            raise ValueError(data.get("message", "API returned status=error"))
        else:
            raise ValueError("Unknown response format.")

# --- PixhostUploader ---
class PixhostUploader(BaseUploader):
    def __init__(self, file_path: str, monitor_callback: Any, content_type_str: str, thumb_size_str: str,
                 gallery_hash: Optional[str] = None, gallery_upload_hash: Optional[str] = None):
        super().__init__(None, None, file_path, monitor_callback)
        content_map = {"Safe": "0", "Adult": "1"}
        self.content_type = content_map.get(content_type_str, "0")
        valid_thumbs = ["150", "200", "250", "300", "350", "400", "450", "500"]
        self.thumb_size = thumb_size_str if thumb_size_str in valid_thumbs else "200"
        self.gallery_hash = gallery_hash
        self.gallery_upload_hash = gallery_upload_hash

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url = Constants.PIX_URL
        fields: Dict[str, Any] = {
            "img": (self.basename, self.file_obj, self.mime_type),
            "content_type": self.content_type,
            "max_th_size": self.thumb_size,
        }
        if self.gallery_hash:
            fields["gallery_hash"] = self.gallery_hash
        if self.gallery_upload_hash:
            fields["gallery_upload_hash"] = self.gallery_upload_hash
        monitor = self.get_monitor(fields)
        return url, monitor, self.headers

    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response format: {type(data)}")
        uploaded_url = data.get("show_url")
        th_url = data.get("th_url")
        if uploaded_url and th_url:
            return uploaded_url, th_url
        elif "error_msg" in data:
            raise ValueError(f"API Error: {data['error_msg']}")
        else:
            raise ValueError("Missing URLs or error_msg.")

# --- PixhostCoverUploader (Added for proper cover handling) ---
class PixhostCoverUploader(BaseUploader):
    def __init__(self, file_path: str, monitor_callback: Any, content_type_str: str,
                 gallery_hash: Optional[str] = None, gallery_upload_hash: Optional[str] = None):
        super().__init__(None, None, file_path, monitor_callback)
        content_map = {"Safe": "0", "Adult": "1"}
        self.content_type = content_map.get(content_type_str, "0")
        self.gallery_hash = gallery_hash
        self.gallery_upload_hash = gallery_upload_hash

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url = Constants.PIX_COVERS_URL
        fields: Dict[str, Any] = {
            "img_left": (self.basename, self.file_obj, self.mime_type),
            "content_type": self.content_type,
        }
        if self.gallery_hash:
            fields["gallery_hash"] = self.gallery_hash
        if self.gallery_upload_hash:
            fields["gallery_upload_hash"] = self.gallery_upload_hash
        monitor = self.get_monitor(fields)
        return url, monitor, self.headers

    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response format: {type(data)}")
        uploaded_url = data.get("show_url")
        th_url = data.get("th_url")
        if uploaded_url and th_url:
            return uploaded_url, th_url
        elif "error_msg" in data:
            raise ValueError(f"API Error: {data['error_msg']}")
        else:
            raise ValueError("Missing URLs or error_msg.")

# --- ScrollableFrame ---
class ScrollableFrame(ttk.Frame):
    def __init__(self, container: Any, *args: Any, **kwargs: Any):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, background="#f8f9fa")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event: Any) -> None:
        if self.canvas.winfo_containing(event.x_root, event.y_root) == self.canvas:
            if platform.system() == 'Windows':
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif platform.system() == 'Darwin':
                self.canvas.yview_scroll(int(-1 * event.delta), "units")
            else:
                if event.num == 4:
                    self.canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    self.canvas.yview_scroll(1, "units")

# --- Main Application ---
class ImageUploader:
    def __init__(self, root: Any):
        self.root = root
        self.root.title("Connie's Uploader 1.2")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Log window
        self.log_window: Optional[tk.Toplevel] = None
        self.log_text: Optional[scrolledtext.ScrolledText] = None
        self.log_cache: List[str] = []
        self.log_context_menu: Optional[tk.Menu] = None

        # Menu bar
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)
        self.view_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="View", menu=self.view_menu)
        self.view_menu.add_command(label="Show Log", command=self.toggle_log_window)

        # Load credentials
        self.loaded_imx_user = keyring.get_password(Constants.KEYRING_SERVICE_USER, "username")
        self.loaded_imx_pass = keyring.get_password(Constants.KEYRING_SERVICE_PASS, "password")
        loaded_api_key = keyring.get_password(Constants.KEYRING_SERVICE_API, "api_key")

        # Style
        self.style = ttk.Style()
        try:
            self.root.set_theme("arc")
        except:
            pass
        self.style.configure("default.Horizontal.TProgressbar", thickness=12, background="#007bff")
        self.style.configure("success.Horizontal.TProgressbar", thickness=12, background="#28a745")
        self.style.configure("failed.Horizontal.TProgressbar", thickness=12, background="#dc3545")
        self.style.configure("Header.TLabel", font=("Helvetica", 14, "bold"), foreground="#343a40")
        self.style.configure("Status.TLabel", font=("Helvetica", 10), foreground="#6c757d")
        self.style.configure("Small.TButton", padding=(4, 4), font=("Helvetica", 10))
        self.style.configure("TLabel", font=("Helvetica", 11))
        self.style.configure("TEntry", font=("Helvetica", 11))
        self.style.configure("TCombobox", font=("Helvetica", 11))
        self.style.configure("TCheckbutton", font=("Helvetica", 11))
        self.style.configure("TButton", font=("Helvetica", 11), padding=6)

        # Layout
        self.top_frame = ttk.Frame(self.root)
        self.top_horizontal_pane = ttk.PanedWindow(self.top_frame, orient=tk.HORIZONTAL)
        self.top_horizontal_pane.pack(fill=tk.BOTH, expand=True)
        self.top_frame.pack(fill=tk.BOTH, expand=True)

        # Settings Frame
        self.settings_frame = ttk.Frame(self.top_horizontal_pane, width=300, padding=15)
        self.settings_frame.columnconfigure(0, weight=1)
        self.settings_frame.rowconfigure(1, weight=1)

        # File List Frame
        self.file_list_outer_frame = ttk.Frame(self.top_horizontal_pane, width=450, padding=(15, 15, 0, 15))
        self.file_list_outer_frame.pack_propagate(False)
        self.file_list_outer_frame.grid_rowconfigure(0, weight=1)
        self.file_list_outer_frame.grid_columnconfigure(0, weight=1)

        self.top_horizontal_pane.add(self.settings_frame)
        self.top_horizontal_pane.add(self.file_list_outer_frame)
        self.top_horizontal_pane.sashpos(0, 320)

        # Settings Header
        self.settings_header = ttk.Label(self.settings_frame, text="Settings", style="Header.TLabel")
        self.settings_header.grid(row=0, column=0, pady=(0, 15), sticky="w")
        self.notebook = ttk.Notebook(self.settings_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.imx_tab = ttk.Frame(self.notebook, padding=15)
        self.pixhost_tab = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.imx_tab, text="imx.to")
        self.notebook.add(self.pixhost_tab, text="pixhost.to")

        # ---------- imx.to Tab ----------
        self.imx_tab.columnconfigure(1, weight=1)
        self.imx_tab.rowconfigure(1, weight=1)

        # API Key
        ttk.Label(self.imx_tab, text="API Key:").grid(row=0, column=0, padx=(0,10), pady=10, sticky="w")
        self.imx_api_key_entry = ttk.Entry(self.imx_tab, show="*", width=30)
        self.imx_api_key_entry.grid(row=0, column=1, pady=10, sticky="ew")
        if loaded_api_key:
            self.imx_api_key_entry.insert(0, loaded_api_key)

        # Upload Options Frame
        self.imx_options_frame = ttk.Labelframe(self.imx_tab, text="Upload Options", padding=15)
        self.imx_options_frame.grid(row=1, column=0, columnspan=2, pady=15, sticky="nsew")
        self.imx_options_frame.columnconfigure(1, weight=1)

        # ---- Gallery Manager (top) ----
        self.open_gallery_manager_button = ttk.Button(self.imx_options_frame, text="Open Gallery Manager...", command=self.open_gallery_manager)
        self.open_gallery_manager_button.grid(row=0, column=0, columnspan=2, pady=(0,8), sticky="ew")

        # Thumbnail
        ttk.Label(self.imx_options_frame, text="Thumbnail:").grid(row=1, column=0, padx=(0,10), pady=8, sticky="w")
        self.imx_thumb_var = tk.StringVar(value="180")
        ttk.Combobox(self.imx_options_frame, textvariable=self.imx_thumb_var,
                     values=["100","150","180","250","300","600"], state="readonly", width=15).grid(row=1, column=1, pady=8, sticky="w")

        # Use first image as cover
        self.imx_cover_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.imx_options_frame, text="Use first image as 600px cover", variable=self.imx_cover_var).grid(row=2, column=0, columnspan=2, pady=8, sticky="w")

        # Generate links.txt
        self.imx_generate_links_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.imx_options_frame, text="Generate links.txt (full URLs)", variable=self.imx_generate_links_var).grid(row=3, column=0, columnspan=2, pady=8, sticky="w")

        # Upload to Gallery ID
        ttk.Label(self.imx_options_frame, text="Upload to Gallery ID:").grid(row=4, column=0, padx=(0,10), pady=8, sticky="w")
        self.imx_gallery_upload_entry = ttk.Entry(self.imx_options_frame, width=15)
        self.imx_gallery_upload_entry.grid(row=4, column=1, pady=8, sticky="w")

        # Threads
        ttk.Label(self.imx_options_frame, text="Threads:").grid(row=5, column=0, padx=(0,10), pady=8, sticky="w")
        self.imx_threads_var = tk.IntVar(value=5)
        ttk.Spinbox(self.imx_options_frame, from_=1, to=15, textvariable=self.imx_threads_var, width=5).grid(row=5, column=1, pady=8, sticky="w")

        # ---------- pixhost.to Tab ----------
        self.pixhost_tab.columnconfigure(1, weight=1)
        self.pixhost_tab.rowconfigure(0, weight=1)

        self.pix_options_frame = ttk.Labelframe(self.pixhost_tab, text="Upload Options", padding=15)
        self.pix_options_frame.grid(row=0, column=0, columnspan=2, pady=15, sticky="nsew")
        self.pix_options_frame.columnconfigure(1, weight=1)

        # Content Type
        ttk.Label(self.pix_options_frame, text="Content Type:").grid(row=0, column=0, padx=(0,10), pady=8, sticky="w")
        self.pix_content_var = tk.StringVar(value="Safe")
        ttk.Combobox(self.pix_options_frame, textvariable=self.pix_content_var,
                     values=["Safe","Adult"], state="readonly", width=15).grid(row=0, column=1, pady=8, sticky="w")

        # Thumbnail
        ttk.Label(self.pix_options_frame, text="Thumbnail:").grid(row=1, column=0, padx=(0,10), pady=8, sticky="w")
        self.pix_thumb_var = tk.StringVar(value="200")
        ttk.Combobox(self.pix_options_frame, textvariable=self.pix_thumb_var,
                     values=["150","200","250","300","350","400","450","500"], state="readonly", width=15).grid(row=1, column=1, pady=8, sticky="w")

        # Use first image as cover
        self.pix_cover_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.pix_options_frame, text="Use first image as cover", variable=self.pix_cover_var).grid(row=2, column=0, columnspan=2, pady=8, sticky="w")

        # Generate links.txt
        self.pix_generate_links_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.pix_options_frame, text="Generate links.txt (full URLs)", variable=self.pix_generate_links_var).grid(row=3, column=0, columnspan=2, pady=8, sticky="w")

        # Create Gallery
        self.pix_create_gallery_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.pix_options_frame, text="Create Gallery", variable=self.pix_create_gallery_var).grid(row=4, column=0, columnspan=2, pady=8, sticky="w")

        # Gallery Name
        ttk.Label(self.pix_options_frame, text="Gallery Name:").grid(row=5, column=0, padx=(0,10), pady=8, sticky="w")
        self.pix_gallery_name_entry = ttk.Entry(self.pix_options_frame, width=30)
        self.pix_gallery_name_entry.grid(row=5, column=1, pady=8, sticky="ew")

        # Visibility (kept in UI but not used in API call, as unsupported)
        ttk.Label(self.pix_options_frame, text="Visibility:").grid(row=6, column=0, padx=(0,10), pady=8, sticky="w")
        self.pix_gallery_visibility_var = tk.StringVar(value="Public")
        ttk.Combobox(self.pix_options_frame, textvariable=self.pix_gallery_visibility_var,
                     values=["Public","Private"], state="readonly", width=15).grid(row=6, column=1, pady=8, sticky="w")

        # Threads
        ttk.Label(self.pix_options_frame, text="Threads:").grid(row=7, column=0, padx=(0,10), pady=8, sticky="w")
        self.pix_threads_var = tk.IntVar(value=3)
        ttk.Spinbox(self.pix_options_frame, from_=1, to=15, textvariable=self.pix_threads_var, width=5).grid(row=7, column=1, pady=8, sticky="w")

        # File List
        self.file_list_scrollable = ScrollableFrame(self.file_list_outer_frame)
        self.file_list_scrollable.pack(fill=tk.BOTH, expand=True)
        self.file_list_frame = self.file_list_scrollable.scrollable_frame
        self.file_list_frame.columnconfigure(0, weight=1)
        self.file_widgets: Dict[str, Dict[str, Any]] = {}
        self.file_order: List[str] = []

        self.progress_bar = ttk.Progressbar(self.file_list_outer_frame, style="default.Horizontal.TProgressbar",
                                            orient="horizontal", length=400, mode="determinate")
        self.progress_bar.pack(pady=10, fill="x")
        self.eta_label = ttk.Label(self.file_list_outer_frame, text="", style="Status.TLabel")
        self.eta_label.pack(pady=5)

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # ---------- Buttons Frame (must be created BEFORE any reference) ----------
        self.buttons_frame = ttk.Frame(self.settings_frame)
        self.buttons_frame.grid(row=2, column=0, pady=15, sticky="ew")
        self.output_format_var = tk.StringVar(value="BBCode")

        self.add_files_button = ttk.Button(self.buttons_frame, text="Add Files", command=self.add_files)
        self.add_files_button.pack(fill="x", padx=5, pady=3)

        self.add_folder_button = ttk.Button(self.buttons_frame, text="Add Folder", command=self.add_folder)
        self.add_folder_button.pack(fill="x", padx=5, pady=3)

        self.clear_list_button = ttk.Button(self.buttons_frame, text="Clear List", command=self.clear_list)
        self.clear_list_button.pack(fill="x", padx=5, pady=3)

        self.start_upload_button = ttk.Button(self.buttons_frame, text="Start Upload", command=self.start_upload)
        self.start_upload_button.pack(fill="x", padx=5, pady=3)

        self.stop_upload_button = ttk.Button(self.buttons_frame, text="Stop Upload", command=self.stop_upload, state=tk.DISABLED)
        self.stop_upload_button.pack(fill="x", padx=5, pady=3)

        self.output_format_menu = ttk.Combobox(self.buttons_frame, textvariable=self.output_format_var,
                                               values=["BBCode","Markdown","HTML"], state="readonly", width=10)
        self.output_format_menu.pack(fill="x", padx=5, pady=3)

        self.open_output_button = ttk.Button(self.buttons_frame, text="Open Output", command=self.open_output_file, state=tk.DISABLED)
        self.open_output_button.pack(fill="x", padx=5, pady=3)

        self.copy_output_button = ttk.Button(self.buttons_frame, text="Copy Output", command=self.copy_output, state=tk.DISABLED)
        self.copy_output_button.pack(fill="x", padx=5, pady=3)

        # State
        self.total_files = 0
        self.completed_files = 0
        self.upload_times = []
        self.queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.lock = threading.Lock()
        self.active_threads = []
        self.results = []
        self.cancel_event = threading.Event()
        self.gallery_hash = None
        self.gallery_upload_hash = None
        self.gallery_url = None
        self.last_service = None
        self.last_username = None
        self.last_password = None
        self.last_content_var = None
        self.last_imx_thumb_var = None
        self.last_pix_thumb_var = None
        self.last_imx_cover_var = None
        self.last_pix_cover_var = None
        self.last_imx_gallery_id: Optional[str] = None
        self.last_gen_links_var = None
        self.gallery_manager_window = None

        self.root.after(100, self.update_progress)
        self.log_message("Log initialized.")
        self.on_tab_changed(None)

    # -------------------------------------------------------------------------
    # UI Helper Methods
    # -------------------------------------------------------------------------
    def on_close(self):
        if messagebox.askokcancel("Quit", "Do you really want to quit?\nAny running uploads will be stopped."):
            self.stop_upload()
            try:
                keyring.set_password(Constants.KEYRING_SERVICE_API, "api_key", self.imx_api_key_entry.get())
                if self.gallery_manager_window and self.gallery_manager_window.winfo_exists():
                    keyring.set_password(Constants.KEYRING_SERVICE_USER, "username", self.gallery_manager_username_entry.get())
                    keyring.set_password(Constants.KEYRING_SERVICE_PASS, "password", self.gallery_manager_password_entry.get())
                elif self.loaded_imx_user:
                    keyring.set_password(Constants.KEYRING_SERVICE_USER, "username", self.loaded_imx_user)
                    keyring.set_password(Constants.KEYRING_SERVICE_PASS, "password", self.loaded_imx_pass)
                self.log_message("Credentials saved.")
            except Exception as e:
                self.log_message(f"Warning: Could not save credentials: {e}")
            if self.gallery_manager_window:
                self.gallery_manager_window.destroy()
            if self.log_window:
                self.log_window.destroy()
            self.root.destroy()

    def toggle_log_window(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Event Log")
        self.log_window.geometry("700x300")
        self.log_window.protocol("WM_DELETE_WINDOW", self.on_log_window_close)

        frame = ttk.Frame(self.log_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='normal')
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.bind("<KeyPress>", lambda e: "break")

        self.log_context_menu = tk.Menu(self.log_text, tearoff=0)
        self.log_context_menu.add_command(label="Copy", command=self._log_copy)
        self.log_context_menu.add_command(label="Select All", command=self._log_select_all)
        self.log_context_menu.add_separator()
        self.log_context_menu.add_command(label="Clear Log", command=self.clear_log)
        self.log_text.bind("<Button-3>", self._show_log_context_menu)

        for line in self.log_cache:
            self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    def on_log_window_close(self):
        if self.log_window:
            self.log_window.destroy()
        self.log_window = None
        self.log_text = None
        self.log_context_menu = None

    def _show_log_context_menu(self, event):
        if self.log_context_menu:
            self.log_context_menu.post(event.x_root, event.y_root)

    def _log_copy(self):
        if self.log_text:
            try:
                self.log_text.event_generate("<<Copy>>")
            except tk.TclError:
                pass

    def _log_select_all(self):
        if self.log_text:
            self.log_text.tag_add(tk.SEL, "1.0", tk.END)

    def clear_log(self):
        if self.log_text and self.log_text.winfo_exists():
            try:
                self.log_text.delete("1.0", tk.END)
            except tk.TclError:
                pass
        self.log_cache = []
        self.log_message("Log cleared.")

    def log_message(self, message: str):
        line = f"{message}\n"
        self.log_cache.append(line)
        if self.log_window and self.log_window.winfo_exists() and self.log_text:
            try:
                self.log_text.insert(tk.END, line)
                self.log_text.see(tk.END)
            except tk.TclError:
                print(line, end="")
        else:
            print(line, end="")

    def on_tab_changed(self, event):
        sel = self.notebook.tab(self.notebook.select(), "text")
        # The button is now part of the imx_options_frame (grid) – no pack/forget needed
        pass

    # -------------------------------------------------------------------------
    # Gallery Manager (imx.to)
    # -------------------------------------------------------------------------
    def open_gallery_manager(self):
        if self.gallery_manager_window and self.gallery_manager_window.winfo_exists():
            self.gallery_manager_window.lift()
            return
        self.gallery_manager_window = tk.Toplevel(self.root)
        self.gallery_manager_window.title("imx.to Gallery Manager")
        self.gallery_manager_window.transient(self.root)
        mgr = ttk.Frame(self.gallery_manager_window, padding=15)
        mgr.pack(fill="both", expand=True)
        mgr.columnconfigure(1, weight=1)

        # Create
        cf = ttk.Labelframe(mgr, text="Create Gallery", padding=15)
        cf.grid(row=0, column=0, columnspan=2, pady=10, sticky="ew")
        cf.columnconfigure(1, weight=1)

        ttk.Label(cf, text="Username:").grid(row=0, column=0, padx=(0,10), pady=10, sticky="w")
        self.gallery_manager_username_entry = ttk.Entry(cf, width=30)
        self.gallery_manager_username_entry.grid(row=0, column=1, pady=10, sticky="ew")
        if self.loaded_imx_user:
            self.gallery_manager_username_entry.insert(0, self.loaded_imx_user)

        ttk.Label(cf, text="Password:").grid(row=1, column=0, padx=(0,10), pady=10, sticky="w")
        self.gallery_manager_password_entry = ttk.Entry(cf, show="*", width=30)
        self.gallery_manager_password_entry.grid(row=1, column=1, pady=10, sticky="ew")
        if self.loaded_imx_pass:
            self.gallery_manager_password_entry.insert(0, self.loaded_imx_pass)

        ttk.Label(cf, text="Gallery Name:").grid(row=2, column=0, padx=(0,10), pady=10, sticky="w")
        self.gallery_manager_gallery_name_entry = ttk.Entry(cf, width=30)
        self.gallery_manager_gallery_name_entry.grid(row=2, column=1, pady=10, sticky="ew")

        ttk.Button(cf, text="Create Gallery", command=self.create_imx_gallery).grid(row=4, column=0, columnspan=2, pady=10, sticky="ew")

        # Rename
        rf = ttk.Labelframe(mgr, text="Rename Gallery", padding=15)
        rf.grid(row=1, column=0, columnspan=2, pady=10, sticky="ew")
        rf.columnconfigure(1, weight=1)

        ttk.Label(rf, text="Gallery ID:").grid(row=0, column=0, padx=(0,10), pady=10, sticky="w")
        self.gallery_manager_gallery_id_entry = ttk.Entry(rf, width=30)
        self.gallery_manager_gallery_id_entry.grid(row=0, column=1, pady=10, sticky="ew")

        ttk.Label(rf, text="New Name:").grid(row=1, column=0, padx=(0,10), pady=10, sticky="w")
        self.gallery_manager_new_name_entry = ttk.Entry(rf, width=30)
        self.gallery_manager_new_name_entry.grid(row=1, column=1, pady=10, sticky="ew")

        ttk.Button(rf, text="Rename Gallery", command=self.rename_imx_gallery).grid(row=2, column=0, columnspan=2, pady=11, sticky="ew")

    def create_imx_gallery(self):
        username = self.gallery_manager_username_entry.get().strip()
        password = self.gallery_manager_password_entry.get()
        name = self.gallery_manager_gallery_name_entry.get().strip() or "Untitled Gallery"
        if not username or not password:
            messagebox.showerror("Error", "Username and password required.", parent=self.gallery_manager_window)
            return
        session = requests.Session()
        login_data = {"usr_email": username, "pwd": password, "remember": "1", "doLogin": "Login"}
        try:
            r = session.post("https://imx.to/login.php", data=login_data, allow_redirects=True, timeout=10)
            if r.url != "https://imx.to/user/dashboard":
                messagebox.showerror("Login Failed", "Invalid credentials.", parent=self.gallery_manager_window)
                return
            self.log_message("Login successful.")
        except Exception as e:
            messagebox.showerror("Network Error", f"{e}", parent=self.gallery_manager_window)
            return

        data = {"gallery_name": name, "submit_new_gallery": "Add"}
        try:
            resp = session.post(Constants.IMX_GALLERY_ADD_URL, data=data, allow_redirects=True)
            if "id=" not in resp.url:
                messagebox.showerror("Error", "Failed to create gallery.", parent=self.gallery_manager_window)
                return
            gid = parse_qs(urlparse(resp.url).query).get("id", [None])[0]
            url = f"https://imx.to/g/{gid}"
            messagebox.showinfo("Success", f"Gallery created!\nID: {gid}\nURL: {url}", parent=self.gallery_manager_window)
            self.log_message(f"Gallery created: {url}")
            self.imx_gallery_upload_entry.delete(0, tk.END)
            self.imx_gallery_upload_entry.insert(0, gid)
        except Exception as e:
            messagebox.showerror("Error", f"{e}", parent=self.gallery_manager_window)

    def rename_imx_gallery(self):
        username = self.gallery_manager_username_entry.get().strip()
        password = self.gallery_manager_password_entry.get()
        gid = self.gallery_manager_gallery_id_entry.get().strip()
        new_name = self.gallery_manager_new_name_entry.get().strip()
        if not all([username, password, gid, new_name]):
            messagebox.showerror("Error", "All fields required.", parent=self.gallery_manager_window)
            return
        session = requests.Session()
        login_data = {"usr_email": username, "pwd": password, "remember": "1", "doLogin": "Login"}
        try:
            r = session.post("https://imx.to/login.php", data=login_data, allow_redirects=True)
            if r.url != "https://imx.to/user/dashboard":
                messagebox.showerror("Login Failed", "Invalid credentials.", parent=self.gallery_manager_window)
                return
        except:
            messagebox.showerror("Error", "Login failed.", parent=self.gallery_manager_window)
            return
        data = {"id": gid, "gallery_name": new_name, "submit_new_gallery_name": "Rename Gallery"}
        try:
            resp = session.post(Constants.IMX_GALLERY_EDIT_URL, data=data)
            if resp.status_code == 200 and new_name in resp.text:
                messagebox.showinfo("Success", f"Gallery {gid} renamed to '{new_name}'", parent=self.gallery_manager_window)
                self.log_message(f"Renamed gallery {gid} → {new_name}")
            else:
                messagebox.showerror("Error", "Rename failed.", parent=self.gallery_manager_window)
        except Exception as e:
            messagebox.showerror("Error", f"{e}", parent=self.gallery_manager_window)

    # -------------------------------------------------------------------------
    # File handling
    # -------------------------------------------------------------------------
    def add_files(self):
        files = filedialog.askopenfilenames(filetypes=[("Images", "*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
        if files:
            self.add_to_list(files)

    def add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        files = []
        for entry in os.scandir(folder):
            if entry.is_file() and entry.name.lower().endswith(Constants.SUPPORTED_EXTENSIONS):
                files.append(entry.path)
        for root, _, names in os.walk(folder):
            if root == folder:
                continue
            for n in names:
                if n.lower().endswith(Constants.SUPPORTED_EXTENSIONS):
                    files.append(os.path.join(root, n))
        if not files:
            messagebox.showinfo("No images", "No supported images found.")
            return
        files.sort(key=lambda p: [natural_sort_key(part) for part in os.path.split(p)])
        if len(files) > Constants.MAX_FILES_WARNING:
            if not messagebox.askyesno("Large folder", f"Adding {len(files)} files – continue?"):
                return
        self.add_to_list(files)

    def add_to_list(self, files: List[str]):
        for fp in files:
            if fp in self.file_widgets:
                continue
            frame = ttk.Frame(self.file_list_frame)
            frame.pack(fill="x", pady=2)
            frame.columnconfigure(1, weight=1)
            status = ttk.Label(frame, text="Pending", width=3)
            status.grid(row=0, column=0, padx=5, sticky="w")
            name = ttk.Label(frame, text=os.path.basename(fp), anchor="w")
            name.grid(row=0, column=1, padx=5, sticky="ew")
            prog = ttk.Progressbar(frame, style="default.Horizontal.TProgressbar", orient="horizontal", length=100, mode="determinate")
            prog.grid(row=0, column=2, padx=5, sticky="e")
            retry = ttk.Button(frame, text="Retry", style="Small.TButton",
                               command=lambda p=fp: self.retry_upload(p), state=tk.DISABLED)
            retry.grid(row=0, column=3, padx=5, sticky="e")
            self.file_widgets[fp] = {
                'frame': frame, 'status_label': status, 'name_label': name,
                'progress': prog, 'retry_button': retry, 'display_name': os.path.basename(fp), 'status': 'pending'
            }
            self.file_order.append(fp)
        self.total_files = len(self.file_widgets)
        self.completed_files = 0
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.eta_label.config(text="")

    def clear_list(self):
        for w in self.file_widgets.values():
            w['frame'].destroy()
        self.file_widgets.clear()
        self.file_order.clear()
        self.total_files = self.completed_files = 0
        self.progress_bar['value'] = 0
        self.eta_label.config(text="")
        self.results.clear()
        self.open_output_button.config(state=tk.DISABLED)
        self.copy_output_button.config(state=tk.DISABLED)

    # -------------------------------------------------------------------------
    # Upload logic
    # -------------------------------------------------------------------------
    def start_upload(self):
        if not self.file_widgets:
            messagebox.showwarning("No Files", "Add files first.")
            return
        service = self.notebook.tab(self.notebook.select(), "text")
        imx_gallery_id: Optional[str] = None

        if service == "imx.to":
            api_key = self.imx_api_key_entry.get()
            if not api_key:
                messagebox.showerror("Error", "API Key required for imx.to.")
                return
            username = password = api_key
            content_var = None
            thumb_var = self.imx_thumb_var
            cover_var = self.imx_cover_var
            gen_links_var = self.imx_generate_links_var
            imx_gallery_id = self.imx_gallery_upload_entry.get().strip() or None
            threads = self.imx_threads_var.get()
        else:
            username = password = None
            content_var = self.pix_content_var
            thumb_var = self.pix_thumb_var
            cover_var = self.pix_cover_var
            gen_links_var = self.pix_generate_links_var
            threads = self.pix_threads_var.get()

        # Store last used settings
        self.last_service = service
        self.last_username = username
        self.last_password = password
        self.last_content_var = content_var
        self.last_imx_thumb_var = self.imx_thumb_var
        self.last_pix_thumb_var = self.pix_thumb_var
        self.last_imx_cover_var = self.imx_cover_var
        self.last_pix_cover_var = self.pix_cover_var
        self.last_imx_gallery_id = imx_gallery_id
        self.last_gen_links_var = gen_links_var

        self.gallery_hash = self.gallery_upload_hash = self.gallery_url = None
        self.results.clear()
        self.completed_files = 0
        self.upload_times.clear()
        self.cancel_event.clear()
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.eta_label.config(text="")

        # pixhost gallery creation
        if service == "pixhost.to" and self.pix_create_gallery_var.get():
            try:
                headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8", "Accept": "application/json"}
                data = {
                    "gallery_name": self.pix_gallery_name_entry.get() or "Untitled Gallery"  # Corrected from "title"
                    # Removed "content_type" and "visibility" as unsupported
                }
                r = requests.post(Constants.PIX_GALLERIES_URL, headers=headers, data=data)
                r.raise_for_status()
                j = r.json()
                self.gallery_hash = j["gallery_hash"]
                self.gallery_upload_hash = j["gallery_upload_hash"]
                self.gallery_url = j["gallery_url"]  # Corrected from "show_url"
                self.log_message(f"Gallery created: {self.gallery_url}")
            except Exception as e:
                messagebox.showerror("Error", f"Gallery creation failed: {e}")
                return

        self.set_buttons_locked(True)
        self.stop_upload_button.config(state=tk.NORMAL)

        for i, fp in enumerate(self.file_order):
            self.queue.put((fp, i == 0))
        for _ in range(threads):
            t = threading.Thread(target=self.upload_worker,
                                 args=(service, username, password, content_var,
                                       self.imx_thumb_var, self.pix_thumb_var,
                                       self.imx_cover_var, self.pix_cover_var,
                                       self.gallery_hash, self.gallery_upload_hash,
                                       imx_gallery_id, cover_var, gen_links_var))
            t.daemon = True
            t.start()
            self.active_threads.append(t)
        self.root.after(100, self.check_threads)

    def stop_upload(self):
        self.cancel_event.set()
        self.log_message("Cancellation requested.")
        self.set_buttons_locked(False)
        self.stop_upload_button.config(state=tk.DISABLED)

    def set_buttons_locked(self, locked: bool):
        state = tk.DISABLED if locked else tk.NORMAL
        self.add_files_button.config(state=state)
        self.add_folder_button.config(state=state)
        self.clear_list_button.config(state=state)
        self.start_upload_button.config(state=state)
        self.notebook.state(['disabled'] if locked else ['!disabled'])

    def upload_worker(self, service: str, username: Optional[str], password: Optional[str],
                      content_var: Any, imx_thumb_var: Any, pix_thumb_var: Any,
                      imx_cover_var: Any, pix_cover_var: Any,
                      gallery_hash: Optional[str], gallery_upload_hash: Optional[str],
                      imx_gallery_id: Optional[str], cover_var: Any, gen_links_var: Any):
        session = requests.Session()
        retries = Retry(total=Constants.RETRY_TOTAL, backoff_factor=Constants.RETRY_BACKOFF,
                        status_forcelist=Constants.RETRY_STATUS)
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))

        while not self.queue.empty() and not self.cancel_event.is_set():
            file_path, is_first = self.queue.get()
            with self.lock:
                widgets = self.file_widgets[file_path]
                widgets['status'] = 'uploading'
                self.progress_queue.put(('status', file_path, 'uploading'))
            start = time.time()

            def callback(monitor):
                if self.cancel_event.is_set():
                    raise ValueError("Cancelled")
                prog = (monitor.bytes_read / monitor.len) * 100
                self.progress_queue.put(('progress', file_path, prog))

            try:
                if service == "imx.to":
                    thumb = imx_thumb_var.get()
                    if is_first and cover_var.get():
                        thumb = "600"
                    uploader = ImxUploader(username, password, file_path, callback, thumb, imx_gallery_id)
                else:  # pixhost.to
                    if is_first and cover_var.get():
                        uploader = PixhostCoverUploader(file_path, callback, content_var.get(), gallery_hash, gallery_upload_hash)
                    else:
                        thumb = pix_thumb_var.get()
                        uploader = PixhostUploader(file_path, callback, content_var.get(), thumb, gallery_hash, gallery_upload_hash)
                url, monitor, headers = uploader.get_request_params()
                r = session.post(url, headers=headers, data=monitor, timeout=300)
                r.raise_for_status()
                data = r.json()
                img_url, th_url = uploader.parse_response(data)
                with self.lock:
                    self.results.append((file_path, (img_url, th_url)))
                    self.log_message(f"Uploaded {widgets['display_name']}: {img_url}")
                    self.progress_queue.put(('status', file_path, 'success'))
                    self.upload_times.append(time.time() - start)
            except Exception as e:
                with self.lock:
                    self.log_message(f"Failed {widgets['display_name']}: {e}")
                    self.progress_queue.put(('status', file_path, 'failed'))
            finally:
                if 'uploader' in locals():
                    uploader.close()
                self.queue.task_done()

    def update_progress(self):
        try:
            while not self.progress_queue.empty():
                typ, fp, val = self.progress_queue.get_nowait()
                if fp not in self.file_widgets:
                    continue
                w = self.file_widgets[fp]
                if typ == 'progress' and w['status'] == 'uploading':
                    w['progress']['value'] = val
                elif typ == 'status':
                    w['status'] = val
                    if val == 'uploading':
                        w['status_label'].config(text="Uploading")
                        w['progress'].config(style="default.Horizontal.TProgressbar")
                        w['retry_button'].config(state=tk.DISABLED)
                    elif val == 'success':
                        w['status_label'].config(text="Success")
                        w['progress']['value'] = 100
                        w['progress'].config(style="success.Horizontal.TProgressbar")
                        w['retry_button'].config(state=tk.DISABLED)
                        self.completed_files += 1
                    elif val == 'failed':
                        w['status_label'].config(text="Failed")
                        w['progress']['value'] = 100
                        w['progress'].config(style="failed.Horizontal.TProgressbar")
                        w['retry_button'].config(state=tk.NORMAL)
                        self.completed_files += 1

            if self.total_files:
                overall = sum(w['progress']['value'] for w in self.file_widgets.values()) / self.total_files
                self.progress_bar['value'] = overall
                if self.completed_files == self.total_files:
                    self.progress_bar.config(style="success.Horizontal.TProgressbar" if all(
                        w['status'] == 'success' for w in self.file_widgets.values()) else "failed.Horizontal.TProgressbar")
                if self.upload_times and self.completed_files < self.total_files:
                    avg = sum(self.upload_times) / len(self.upload_times)
                    eta = avg * (self.total_files - self.completed_files)
                    self.eta_label.config(text=f"ETA: {int(eta//60)}m {int(eta%60)}s")
                else:
                    self.eta_label.config(text="")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.update_progress)

    def retry_upload(self, fp: str):
        if fp not in self.file_widgets:
            return
        w = self.file_widgets[fp]
        w['status_label'].config(text="Pending")
        w['progress']['value'] = 0
        w['progress'].config(style="default.Horizontal.TProgressbar")
        w['retry_button'].config(state=tk.DISABLED)
        w['status'] = 'pending'
        is_first = self.file_order and self.file_order[0] == fp
        self.queue.put((fp, is_first))
        self.log_message(f"Retrying {w['display_name']}...")
        if self.completed_files:
            self.completed_files -= 1
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        if not any(t.is_alive() for t in self.active_threads):
            self.set_buttons_locked(True)
            self.stop_upload_button.config(state=tk.NORMAL)
            t = threading.Thread(target=self.upload_worker,
                                 args=(self.last_service, self.last_username, self.last_password,
                                       self.last_content_var, self.last_imx_thumb_var,
                                       self.last_pix_thumb_var, self.last_imx_cover_var,
                                       self.last_pix_cover_var, self.gallery_hash,
                                       self.gallery_upload_hash, self.last_imx_gallery_id,
                                       self.last_imx_cover_var if self.last_service == "imx.to" else self.last_pix_cover_var,
                                       self.last_gen_links_var))
            t.daemon = True
            t.start()
            self.active_threads.append(t)
            self.root.after(100, self.check_threads)

    def check_threads(self):
        self.active_threads = [t for t in self.active_threads if t.is_alive()]
        if not self.active_threads and self.queue.empty():
            self.log_message("All uploads finished.")
            self.set_buttons_locked(False)
            self.stop_upload_button.config(state=tk.DISABLED)
            if self.gallery_hash and self.gallery_upload_hash and not self.cancel_event.is_set():
                if not any(w['status'] == 'failed' for w in self.file_widgets.values()):
                    try:
                        url = f"{Constants.PIX_GALLERIES_URL}/{self.gallery_hash}/finalize"
                        data = {"gallery_upload_hash": self.gallery_upload_hash}
                        r = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data)
                        r.raise_for_status()
                        self.log_message("Gallery finalized.")
                    except Exception as e:
                        self.log_message(f"Finalize failed: {e}")
                else:
                    self.log_message("Gallery not finalized (failures).")
            if self.results:
                self.generate_output_file()
        else:
            self.root.after(100, self.check_threads)

    # -------------------------------------------------------------------------
    # Output generation
    # -------------------------------------------------------------------------
    def generate_output_file(self):
        if not self.results:
            self.log_message("No successful uploads.")
            return
        sorted_res = [(fp, next((r[1] for r in self.results if r[0] == fp), (None, None)))
                      for fp in self.file_order]
        valid = [r for r in sorted_res if r[1][0] and r[1][1]]
        if not valid:
            self.log_message("No valid URLs.")
            return

        fmt = self.output_format_var.get()
        out_file = "upload_results.txt"
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                if self.gallery_url:
                    f.write(f"Gallery URL: {self.gallery_url}\n\n")
                if fmt == "BBCode":
                    f.write("[center]\n")
                    f.write(' '.join(f"[url={img}][img]{th}[/img][/url]" for _, (img, th) in valid))
                    f.write("\n[/center]\n")
                elif fmt == "Markdown":
                    f.write('\n'.join(f"[![{th}]({th})]({img})" for _, (img, th) in valid))
                elif fmt == "HTML":
                    f.write('\n'.join(f'<a href="{img}"><img src="{th}" alt="Image"></a>' for _, (img, th) in valid))
            self.log_message(f"Generated {out_file} ({fmt})")
            self.open_output_button.config(state=tk.NORMAL)
            self.copy_output_button.config(state=tk.NORMAL)

            # links.txt if requested
            gen_links = ((self.last_service == "imx.to" and self.imx_generate_links_var.get()) or
                         (self.last_service == "pixhost.to" and self.pix_generate_links_var.get()))
            if gen_links:
                with open("links.txt", "w", encoding="utf-8") as f:
                    for _, (img, _) in valid:
                        f.write(f"{img}\n")
                self.log_message("Generated links.txt")
        except Exception as e:
            self.log_message(f"Output error: {e}")

    def copy_output(self):
        if not os.path.exists("upload_results.txt"):
            self.log_message("upload_results.txt missing.")
            return
        try:
            with open("upload_results.txt", "r", encoding="utf-8") as f:
                pyperclip.copy(f.read())
            self.log_message("Copied to clipboard.")
        except Exception as e:
            self.log_message(f"Copy error: {e}")

    def open_output_file(self):
        if not os.path.exists("upload_results.txt"):
            self.log_message("upload_results.txt missing.")
            return
        try:
            if platform.system() == "Windows":
                os.startfile("upload_results.txt")
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "upload_results.txt"])
            else:
                subprocess.Popen(["xdg-open", "upload_results.txt"])
        except Exception as e:
            self.log_message(f"Open error: {e}")

if __name__ == "__main__":
    try:
        root = ThemedTk(theme="arc")
    except Exception:
        root = tk.Tk()
    app = ImageUploader(root)
    root.mainloop()
