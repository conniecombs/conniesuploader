import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk  # Import ttk for themed widgets
from ttkthemes import ThemedTk  # For better styling
import threading
import queue
import requests
from requests.exceptions import JSONDecodeError
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
import os
import mimetypes
import json
import base64
import abc  # Abstract Base Class
import keyring  # For secure credential storage
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

# Constants
class Constants:
    IMX_URL = "https://api.imx.to/v1/upload.php"
    PIX_URL = "https://api.pixhost.to/images"
    PIX_GALLERIES_URL = "https://api.pixhost.to/galleries"
    IMX_LOGIN_URL = "https://imx.to/user/dashboard"
    IMX_GALLERY_ADD_URL = "https://imx.to/user/gallery/add"
    IMX_GALLERY_EDIT_URL = "https://imx.to/user/gallery/edit"
    SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    MAX_FILES_WARNING = 1000
    RETRY_TOTAL = 3
    RETRY_BACKOFF = 1
    RETRY_STATUS = [500, 502, 503, 504]
    
    # --- ADDED: Keyring Service Names ---
    KEYRING_SERVICE_API = "ImageUploader:imx_api_key"
    KEYRING_SERVICE_USER = "ImageUploader:imx_username"
    KEYRING_SERVICE_PASS = "ImageUploader:imx_password"
    # --- END ADD ---

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- BaseUploader Class ---
class BaseUploader(abc.ABC):
    """Abstract base class for an uploader."""
    def __init__(self, username: Optional[str], password: Optional[str], file_path: str, monitor_callback: Any):
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.file_path: str = file_path
        self.basename: str = os.path.basename(file_path)
        self.mime_type: str = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        self.file_obj: Optional[Any] = None
        self.monitor_callback: Any = monitor_callback
        self.headers: Dict[str, str] = {}

    def get_monitor(self, fields: Dict[str, Any]) -> MultipartEncoderMonitor:
        """Creates a MultipartEncoderMonitor."""
        encoder = MultipartEncoder(fields=fields)
        monitor = MultipartEncoderMonitor(encoder, self.monitor_callback)
        
        self.headers['Content-Type'] = monitor.content_type
        
        return monitor

    @abc.abstractmethod
    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        """Get URL, data, and headers for the request."""
        pass

    @abc.abstractmethod
    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        """Parse the JSON response and return (image_url, thumbnail_url)."""
        pass

    def close(self) -> None:
        """Close the file object."""
        if self.file_obj:
            self.file_obj.close()

# --- ImxUploader Class ---
class ImxUploader(BaseUploader):
    def __init__(self, username: Optional[str], api_key: Optional[str], file_path: str, monitor_callback: Any, 
                 thumb_size_str: str, gallery_id: Optional[str]):
        super().__init__(username, api_key, file_path, monitor_callback)
        size_to_api_map: Dict[str, str] = {"100": "1", "180": "2", "250": "3", "300": "4", "600": "5", "150": "6"}
        self.thumb_size: str = size_to_api_map.get(thumb_size_str, "2")  # Default to 180px
        self.gallery_id: Optional[str] = gallery_id

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url: str = Constants.IMX_URL
        self.headers['X-API-KEY'] = self.password or ""
        
        fields: Dict[str, Any] = {
            "image": (self.basename, self.file_obj, self.mime_type),
            "format": "json",
            "thumbnail_size": self.thumb_size,
        }

        if self.gallery_id:
            fields["gallery_id"] = self.gallery_id
        
        monitor: MultipartEncoderMonitor = self.get_monitor(fields)
        return url, monitor, self.headers

    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response format: {type(data)}")

        status: Optional[str] = data.get("status")
        
        if status == "success":
            data_obj: Optional[Dict[str, str]] = data.get("data")
            if not data_obj:
                raise ValueError("Success status, but no 'data' object found.")
            
            uploaded_url: Optional[str] = data_obj.get("image_url")
            th_url: Optional[str] = data_obj.get("thumbnail_url")
            
            if not uploaded_url or not th_url:
                raise ValueError("Success status, but URLs missing from 'data' object.")
                
            return uploaded_url, th_url
        
        elif status == "error":
            message: str = data.get("message", "API returned status=error")
            raise ValueError(message)
            
        else:
            if "message" in data:
                raise ValueError(f"API Error: {data['message']}")
            raise ValueError("Unknown response format: 'status' key missing or invalid.")

# --- PixhostUploader Class ---
class PixhostUploader(BaseUploader):
    """Uploader for pixhost.to."""
    def __init__(self, file_path: str, monitor_callback: Any, content_type_str: str, thumb_size_str: str, gallery_hash: Optional[str] = None, gallery_upload_hash: Optional[str] = None):
        super().__init__(None, None, file_path, monitor_callback)
        
        content_map: Dict[str, str] = {"Safe": "0", "Adult": "1"}
        self.content_type: str = content_map.get(content_type_str, "0")
        
        valid_thumbs: List[str] = ["150", "200", "250", "300", "350", "400", "450", "500"]
        self.thumb_size: str = thumb_size_str if thumb_size_str in valid_thumbs else "200"

        self.gallery_hash: Optional[str] = gallery_hash
        self.gallery_upload_hash: Optional[str] = gallery_upload_hash

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url: str = Constants.PIX_URL
        
        fields: Dict[str, Any] = {
            "img": (self.basename, self.file_obj, self.mime_type),
            "content_type": self.content_type,
            "max_th_size": self.thumb_size,
        }
        
        if self.gallery_hash:
            fields["gallery_hash"] = self.gallery_hash
        if self.gallery_upload_hash:
            fields["gallery_upload_hash"] = self.gallery_upload_hash
        
        monitor: MultipartEncoderMonitor = self.get_monitor(fields)
        return url, monitor, self.headers

    def parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response format: {type(data)}")

        uploaded_url: Optional[str] = data.get("show_url")
        th_url: Optional[str] = data.get("th_url")

        if uploaded_url and th_url:
            return uploaded_url, th_url
        elif "error_msg" in data:
            raise ValueError(f"API Error: {data['error_msg']}")
        else:
            raise ValueError("Unknown response format: 'show_url'/'th_url' or 'error_msg' missing.")


# --- Helper Class: ScrollableFrame ---
class ScrollableFrame(ttk.Frame):
    """
    A pure TTK scrollable frame that resizes with its content.
    - Put widgets into the 'self.scrollable_frame' attribute.
    """
    def __init__(self, container: Any, *args: Any, **kwargs: Any):
        super().__init__(container, *args, **kwargs)
        self.canvas: tk.Canvas = tk.Canvas(self, borderwidth=0, background="#f8f9fa")
        self.scrollbar: ttk.Scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame: ttk.Frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

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

# --- Main Application Class ---
class ImageUploader:
    def __init__(self, root: Any):
        self.root: Any = root
        self.root.title("Connie's Uploader 1.0")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # --- ADDED: Load credentials on init ---
        self.loaded_imx_user = keyring.get_password(Constants.KEYRING_SERVICE_USER, "username")
        self.loaded_imx_pass = keyring.get_password(Constants.KEYRING_SERVICE_PASS, "password")
        loaded_api_key = keyring.get_password(Constants.KEYRING_SERVICE_API, "api_key")
        # --- END ADD ---

        # --- Style Configuration ---
        self.style: ttk.Style = ttk.Style()
        try:
            self.root.set_theme("arc")
        except:
            pass
        
        self.style.configure("TProgressbar", thickness=12, background="#007bff")
        self.style.configure("default.Horizontal.TProgressbar", background="#007bff")
        self.style.configure("success.Horizontal.TProgressbar", background="#00FF00")
        self.style.configure("failed.Horizontal.TProgressbar", background="#dc3545")
        
        self.style.configure("Header.TLabel", font=("Helvetica", 14, "bold"), foreground="#343a40")
        self.style.configure("Status.TLabel", font=("Helvetica", 10), foreground="#6c757d")
        self.style.configure("Small.TButton", padding=(4, 4), font=("Helvetica", 10))
        self.style.configure("TLabel", font=("Helvetica", 11))
        self.style.configure("TEntry", font=("Helvetica", 11))
        self.style.configure("TCombobox", font=("Helvetica", 11))
        self.style.configure("TCheckbutton", font=("Helvetica", 11))
        self.style.configure("TButton", font=("Helvetica", 11), padding=6)

        # --- MODIFIED: New Vertical Layout ---
        self.main_vertical_pane = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        self.main_vertical_pane.pack(fill=tk.BOTH, expand=True)

        self.top_frame = ttk.Frame(self.main_vertical_pane)
        self.top_horizontal_pane = ttk.PanedWindow(self.top_frame, orient=tk.HORIZONTAL)
        self.top_horizontal_pane.pack(fill=tk.BOTH, expand=True)

        # --- Pane 1: Settings (Left) ---
        self.settings_frame: ttk.Frame = ttk.Frame(self.top_horizontal_pane, width=300, padding=15)
        self.settings_frame.columnconfigure(0, weight=1)
        self.settings_frame.rowconfigure(1, weight=1)
        
        # --- Pane 2: File List (Center) ---
        self.file_list_outer_frame: ttk.Frame = ttk.Frame(self.top_horizontal_pane, width=450, padding=(15, 15, 0, 15))
        self.file_list_outer_frame.pack_propagate(False)
        self.file_list_outer_frame.grid_rowconfigure(0, weight=1)
        self.file_list_outer_frame.grid_columnconfigure(0, weight=1)
        
        self.top_horizontal_pane.add(self.settings_frame)
        self.top_horizontal_pane.add(self.file_list_outer_frame)
        self.top_horizontal_pane.sashpos(0, 320)

        # --- Pane 3: Log (Bottom) ---
        self.log_frame: ttk.Frame = ttk.Frame(self.main_vertical_pane, height=150, padding=(15, 15, 15, 15))
        self.log_frame.pack_propagate(False)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
        
        self.main_vertical_pane.add(self.top_frame)
        self.main_vertical_pane.add(self.log_frame)
        self.main_vertical_pane.sashpos(0, 500)
        # --- END LAYOUT MODIFICATION ---

        # --- Populate Pane 1: Settings ---
        self.settings_header: ttk.Label = ttk.Label(self.settings_frame, text="Settings", style="Header.TLabel")
        self.settings_header.grid(row=0, column=0, pady=(0, 15), sticky="w")
        
        self.notebook: ttk.Notebook = ttk.Notebook(self.settings_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.imx_tab: ttk.Frame = ttk.Frame(self.notebook, padding=15)
        self.pixhost_tab: ttk.Frame = ttk.Frame(self.notebook, padding=15)
        
        self.notebook.add(self.imx_tab, text="imx.to")
        self.notebook.add(self.pixhost_tab, text="pixhost.to")

        # --- imx.to Tab Widgets ---
        self.imx_tab.columnconfigure(1, weight=1)
        self.imx_api_label: ttk.Label = ttk.Label(self.imx_tab, text="API Key:")
        self.imx_api_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.imx_api_key_entry: ttk.Entry = ttk.Entry(self.imx_tab, show="*", width=30)
        self.imx_api_key_entry.grid(row=0, column=1, pady=10, sticky="ew")
        # --- ADDED: Populate API Key from keyring ---
        if loaded_api_key:
            self.imx_api_key_entry.insert(0, loaded_api_key)
        
        self.imx_options_frame: ttk.Labelframe = ttk.Labelframe(self.imx_tab, text="Upload Options", padding=15)
        self.imx_options_frame.grid(row=1, column=0, columnspan=2, pady=15, sticky="ew")
        self.imx_options_frame.columnconfigure(1, weight=1)

        self.imx_thumb_label: ttk.Label = ttk.Label(self.imx_options_frame, text="Thumbnail:")
        self.imx_thumb_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.imx_thumb_var: tk.StringVar = tk.StringVar(value="180")
        self.imx_thumb_menu: ttk.Combobox = ttk.Combobox(self.imx_options_frame, textvariable=self.imx_thumb_var,
                                                       values=["100", "150", "180", "250", "300", "600"],
                                                       state="readonly", width=15)
        self.imx_thumb_menu.grid(row=0, column=1, pady=10, sticky="w")

        self.imx_cover_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.imx_cover_check: ttk.Checkbutton = ttk.Checkbutton(self.imx_options_frame, text="Use 1st image as 600px cover", variable=self.imx_cover_var)
        self.imx_cover_check.grid(row=1, column=0, columnspan=2, pady=10, sticky="w")

        self.imx_generate_links_var = tk.BooleanVar(value=False)
        self.imx_generate_links_check = ttk.Checkbutton(self.imx_options_frame, text="Generate links.txt (full URLs)", variable=self.imx_generate_links_var)
        self.imx_generate_links_check.grid(row=2, column=0, columnspan=2, pady=10, sticky="w")

        self.imx_gallery_upload_label = ttk.Label(self.imx_options_frame, text="Upload to Gallery ID:")
        self.imx_gallery_upload_label.grid(row=3, column=0, padx=(0, 10), pady=10, sticky="w")
        self.imx_gallery_upload_entry = ttk.Entry(self.imx_options_frame, width=15)
        self.imx_gallery_upload_entry.grid(row=3, column=1, pady=10, sticky="w")

        # --- pixhost.to Tab Widgets ---
        self.pixhost_tab.columnconfigure(1, weight=1)

        self.pix_options_frame = ttk.Labelframe(self.pixhost_tab, text="Upload Options", padding=15)
        self.pix_options_frame.grid(row=0, column=0, columnspan=2, pady=15, sticky="ew")
        self.pix_options_frame.columnconfigure(1, weight=1)

        self.pix_content_label = ttk.Label(self.pix_options_frame, text="Content Type:")
        self.pix_content_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_content_var = tk.StringVar(value="Safe")
        self.pix_content_menu = ttk.Combobox(self.pix_options_frame, textvariable=self.pix_content_var,
                                             values=["Safe", "Adult"], state="readonly", width=15)
        self.pix_content_menu.grid(row=0, column=1, pady=10, sticky="w")

        self.pix_thumb_label = ttk.Label(self.pix_options_frame, text="Thumbnail:")
        self.pix_thumb_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_thumb_var = tk.StringVar(value="200")
        self.pix_thumb_menu = ttk.Combobox(self.pix_options_frame, textvariable=self.pix_thumb_var,
                                           values=["150", "200", "250", "300", "350", "400", "450", "500"],
                                           state="readonly", width=15)
        self.pix_thumb_menu.grid(row=1, column=1, pady=10, sticky="w")

        self.pix_create_gallery_var = tk.BooleanVar(value=False)
        self.pix_create_gallery_check = ttk.Checkbutton(self.pix_options_frame, text="Create Gallery", variable=self.pix_create_gallery_var)
        self.pix_create_gallery_check.grid(row=2, column=0, columnspan=2, pady=10, sticky="w")

        self.pix_gallery_name_label = ttk.Label(self.pix_options_frame, text="Gallery Name:")
        self.pix_gallery_name_label.grid(row=3, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_gallery_name_entry = ttk.Entry(self.pix_options_frame, width=30)
        self.pix_gallery_name_entry.grid(row=3, column=1, pady=10, sticky="ew")

        self.pix_gallery_visibility_label = ttk.Label(self.pix_options_frame, text="Visibility:")
        self.pix_gallery_visibility_label.grid(row=4, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_gallery_visibility_var = tk.StringVar(value="Public")
        self.pix_gallery_visibility_menu = ttk.Combobox(self.pix_options_frame, textvariable=self.pix_gallery_visibility_var,
                                                        values=["Public", "Private"], state="readonly", width=15)
        self.pix_gallery_visibility_menu.grid(row=4, column=1, pady=10, sticky="w")

        # --- Populate Pane 2: File List ---
        self.file_list_scrollable = ScrollableFrame(self.file_list_outer_frame)
        self.file_list_scrollable.pack(fill=tk.BOTH, expand=True)

        self.file_list_frame = self.file_list_scrollable.scrollable_frame
        self.file_list_frame.columnconfigure(0, weight=1)

        self.file_widgets: Dict[str, Dict[str, Any]] = {}

        # Overall Progress Bar
        self.progress_bar = ttk.Progressbar(self.file_list_outer_frame, style="default.Horizontal.TProgressbar", orient="horizontal", length=400, mode="determinate")
        self.progress_bar.pack(pady=10, fill="x")

        self.eta_label = ttk.Label(self.file_list_outer_frame, text="", style="Status.TLabel")
        self.eta_label.pack(pady=5)

        # --- Populate Pane 3: Log ---
        self.log_text = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, state='normal', height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.bind("<KeyPress>", lambda e: "break")
        
        self.log_context_menu = tk.Menu(self.log_text, tearoff=0)
        self.log_context_menu.add_command(label="Copy", command=self._log_copy)
        self.log_context_menu.add_command(label="Select All", command=self._log_select_all)
        self.log_context_menu.add_separator()
        self.log_context_menu.add_command(label="Clear Log", command=self.clear_log)
        self.log_text.bind("<Button-3>", self._show_log_context_menu)
        
        # --- ADDED: Bind to tab changes ---
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        
        # --- Buttons at Bottom of Settings Frame ---
        self.buttons_frame = ttk.Frame(self.settings_frame)
        self.buttons_frame.grid(row=2, column=0, pady=15, sticky="ew")

        # --- MOVED: Variable definition to before it's used ---
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
                                               values=["BBCode", "Markdown", "HTML"], state="readonly", width=10)
        self.output_format_menu.pack(fill="x", padx=5, pady=3)

        self.open_output_button = ttk.Button(self.buttons_frame, text="Open Output", command=self.open_output_file, state=tk.DISABLED)
        self.open_output_button.pack(fill="x", padx=5, pady=3)

        self.copy_output_button = ttk.Button(self.buttons_frame, text="Copy Output", command=self.copy_output, state=tk.DISABLED)
        self.copy_output_button.pack(fill="x", padx=5, pady=3)
        
        # --- ADDED: Create gallery manager button (hidden by default) ---
        self.open_gallery_manager_button = ttk.Button(self.buttons_frame, text="Open Gallery Manager...", command=self.open_gallery_manager)
        # --- END ADD ---

        # Initialize variables
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
        self.gallery_manager_window = None

        self.root.after(100, self.update_progress)
        self.log_message("Log initialized.")
        
        self.on_tab_changed(None)

    def _show_log_context_menu(self, event):
        self.log_context_menu.post(event.x_root, event.y_root)

    def _log_copy(self):
        try:
            self.log_text.event_generate("<<Copy>>")
        except tk.TclError:
            pass

    def _log_select_all(self):
        self.log_text.tag_add(tk.SEL, "1.0", tk.END)

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def on_tab_changed(self, event):
        """Show or hide host-specific buttons based on the selected tab."""
        selected_tab_text = self.notebook.tab(self.notebook.select(), "text")
        
        if selected_tab_text == "imx.to":
            self.open_gallery_manager_button.pack(fill="x", padx=5, pady=3)
        else:
            self.open_gallery_manager_button.pack_forget()

    def open_gallery_manager(self):
        if self.gallery_manager_window and self.gallery_manager_window.winfo_exists():
            self.gallery_manager_window.lift()
            return

        self.gallery_manager_window = tk.Toplevel(self.root)
        self.gallery_manager_window.title("imx.to Gallery Manager")
        self.gallery_manager_window.transient(self.root)
        
        manager_frame = ttk.Frame(self.gallery_manager_window, padding=15)
        manager_frame.pack(fill="both", expand=True)
        manager_frame.columnconfigure(1, weight=1)

        create_frame = ttk.Labelframe(manager_frame, text="Create Gallery", padding=15)
        create_frame.grid(row=0, column=0, columnspan=2, pady=10, sticky="ew")
        create_frame.columnconfigure(1, weight=1)

        username_label = ttk.Label(create_frame, text="Username:")
        username_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.gallery_manager_username_entry = ttk.Entry(create_frame, width=30)
        self.gallery_manager_username_entry.grid(row=0, column=1, pady=10, sticky="ew")
        # --- ADDED: Populate username from keyring ---
        if self.loaded_imx_user:
            self.gallery_manager_username_entry.insert(0, self.loaded_imx_user)

        password_label = ttk.Label(create_frame, text="Password:")
        password_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        self.gallery_manager_password_entry = ttk.Entry(create_frame, show="*", width=30)
        self.gallery_manager_password_entry.grid(row=1, column=1, pady=10, sticky="ew")
        # --- ADDED: Populate password from keyring ---
        if self.loaded_imx_pass:
            self.gallery_manager_password_entry.insert(0, self.loaded_imx_pass)

        gallery_name_label = ttk.Label(create_frame, text="Gallery Name:")
        gallery_name_label.grid(row=2, column=0, padx=(0, 10), pady=10, sticky="w")
        self.gallery_manager_gallery_name_entry = ttk.Entry(create_frame, width=30)
        self.gallery_manager_gallery_name_entry.grid(row=2, column=1, pady=10, sticky="ew")

        create_button = ttk.Button(create_frame, text="Create Gallery", command=self.create_imx_gallery)
        create_button.grid(row=4, column=0, columnspan=2, pady=10, sticky="ew")
        
        rename_frame = ttk.Labelframe(manager_frame, text="Rename Gallery", padding=15)
        rename_frame.grid(row=1, column=0, columnspan=2, pady=10, sticky="ew")
        rename_frame.columnconfigure(1, weight=1)

        gallery_id_label = ttk.Label(rename_frame, text="Gallery ID:")
        gallery_id_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.gallery_manager_gallery_id_entry = ttk.Entry(rename_frame, width=30)
        self.gallery_manager_gallery_id_entry.grid(row=0, column=1, pady=10, sticky="ew")

        new_name_label = ttk.Label(rename_frame, text="New Name:")
        new_name_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        self.gallery_manager_new_name_entry = ttk.Entry(rename_frame, width=30)
        self.gallery_manager_new_name_entry.grid(row=1, column=1, pady=10, sticky="ew")

        rename_button = ttk.Button(rename_frame, text="Rename Gallery", command=self.rename_imx_gallery)
        rename_button.grid(row=2, column=0, columnspan=2, pady=10, sticky="ew")

    def create_imx_gallery(self):
        username = self.gallery_manager_username_entry.get().strip()
        password = self.gallery_manager_password_entry.get()
        gallery_name = self.gallery_manager_gallery_name_entry.get().strip() or "Untitled Gallery"
        
        if not username or not password:
            messagebox.showerror("Error", "Username/email and password are required.", parent=self.gallery_manager_window)
            return

        session = requests.Session()
        
        login_data = {
            "usr_email": username,
            "pwd": password,
            "remember": "1",
            "doLogin": "Login"
        }
        
        try:
            login_response = session.post("https://imx.to/login.php", data=login_data, allow_redirects=True, timeout=10)
            
            if login_response.url != "https://imx.to/user/dashboard":
                self.log_message(f"Login failed: Did not redirect to dashboard. URL: {login_response.url}")
                messagebox.showerror("Login Failed", "Invalid credentials or login blocked.", parent=self.gallery_manager_window)
                return
            
            if "Welcome" not in login_response.text and username not in login_response.text:
                self.log_message("Login failed: User not found in dashboard.")
                messagebox.showerror("Login Failed", "Could not verify login. Check credentials.", parent=self.gallery_manager_window)
                return

            self.log_message("Login successful.")
            
        except requests.exceptions.RequestException as e:
            self.log_message(f"Login network error: {e}")
            messagebox.showerror("Network Error", f"Failed to connect: {e}", parent=self.gallery_manager_window)
            return

        create_data = {
            "gallery_name": gallery_name,
            "submit_new_gallery": "Add"
        }
        
        try:
            response = session.post(Constants.IMX_GALLERY_ADD_URL, data=create_data, allow_redirects=True)
            
            if "manage" not in response.url or "id=" not in response.url:
                self.log_message(f"Gallery creation failed: No redirect to manage page. URL: {response.url}")
                messagebox.showerror("Error", "Failed to create gallery. Check name or permissions.", parent=self.gallery_manager_window)
                return

            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(response.url)
            query = parse_qs(parsed.query)
            gallery_id = query.get("id", [None])[0]
            
            if not gallery_id:
                messagebox.showerror("Error", "Gallery created but ID not found.", parent=self.gallery_manager_window)
                return

            gallery_url = f"https://imx.to/g/{gallery_id}"
            messagebox.showinfo("Success", f"Gallery created!\nID: {gallery_id}\nURL: {gallery_url}", parent=self.gallery_manager_window)
            self.log_message(f"Gallery created: {gallery_url}")

            self.imx_gallery_upload_entry.delete(0, tk.END)
            self.imx_gallery_upload_entry.insert(0, gallery_id)

        except Exception as e:
            self.log_message(f"Gallery creation error: {e}")
            messagebox.showerror("Error", f"Failed to create gallery: {e}", parent=self.gallery_manager_window)

    def rename_imx_gallery(self):
        username = self.gallery_manager_username_entry.get().strip()
        password = self.gallery_manager_password_entry.get()
        gallery_id = self.gallery_manager_gallery_id_entry.get().strip()
        new_name = self.gallery_manager_new_name_entry.get().strip()

        if not all([username, password, gallery_id, new_name]):
            messagebox.showerror("Error", "All fields are required.", parent=self.gallery_manager_window)
            return

        session = requests.Session()

        login_data = {
            "usr_email": username,
            "pwd": password,
            "remember": "1",
            "doLogin": "Login"
        }

        try:
            login_response = session.post("https://imx.to/login.php", data=login_data, allow_redirects=True)
            if login_response.url != "https://imx.to/user/dashboard":
                messagebox.showerror("Login Failed", "Invalid credentials.", parent=self.gallery_manager_window)
                return
            self.log_message("Login successful for rename.")
        except:
            messagebox.showerror("Error", "Login failed during rename.", parent=self.gallery_manager_window)
            return

        rename_data = {
            "id": gallery_id,
            "gallery_name": new_name,
            "submit_new_gallery_name": "Rename Gallery"
        }

        try:
            response = session.post(Constants.IMX_GALLERY_EDIT_URL, data=rename_data)
            
            if response.status_code == 200 and new_name in response.text:
                messagebox.showinfo("Success", f"Gallery {gallery_id} renamed to '{new_name}'", parent=self.gallery_manager_window)
                self.log_message(f"Renamed gallery {gallery_id} → {new_name}")
            else:
                messagebox.showerror("Error", "Rename failed. Check Gallery ID.", parent=self.gallery_manager_window)
        except Exception as e:
            messagebox.showerror("Error", f"Request failed: {e}", parent=self.gallery_manager_window)

    def add_files(self):
        files = filedialog.askopenfilenames(filetypes=[("Images", "*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
        if files:
            self.add_to_list(files)

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            files = []
            for root, _, filenames in os.walk(folder):
                for filename in filenames:
                    if filename.lower().endswith(Constants.SUPPORTED_EXTENSIONS):
                        files.append(os.path.join(root, filename))
            if files:
                if len(files) > Constants.MAX_FILES_WARNING:
                    if not messagebox.askyesno("Warning", f"You are adding {len(files)} files. This may be slow. Continue?"):
                        return
                self.add_to_list(files)

    def add_to_list(self, files: List[str]):
        for file_path in files:
            if file_path in self.file_widgets:
                continue
            display_name = os.path.basename(file_path)
            
            frame = ttk.Frame(self.file_list_frame)
            frame.pack(fill="x", pady=2) 
            
            frame.columnconfigure(1, weight=1)

            status_label = ttk.Label(frame, text="⏳", width=3)
            status_label.grid(row=0, column=0, padx=5, sticky="w")

            name_label = ttk.Label(frame, text=display_name, anchor="w")
            name_label.grid(row=0, column=1, padx=5, sticky="ew")

            progress = ttk.Progressbar(frame, style="default.Horizontal.TProgressbar", orient="horizontal", length=100, mode="determinate")
            progress.grid(row=0, column=2, padx=5, sticky="e")

            retry_button = ttk.Button(frame, text="Retry", style="Small.TButton", command=lambda fp=file_path: self.retry_upload(fp), state=tk.DISABLED)
            retry_button.grid(row=0, column=3, padx=5, sticky="e")

            self.file_widgets[file_path] = {
                'frame': frame,
                'status_label': status_label,
                'name_label': name_label,
                'progress': progress,
                'retry_button': retry_button,
                'display_name': display_name,
                'status': 'pending'
            }

        self.total_files = len(self.file_widgets)
        self.completed_files = 0
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.eta_label.config(text="")

    def clear_list(self):
        for widgets in self.file_widgets.values():
            widgets['frame'].destroy()
        self.file_widgets = {}
        self.total_files = 0
        self.completed_files = 0
        self.progress_bar['value'] = 0
        self.eta_label.config(text="")
        self.results = []
        self.open_output_button.config(state=tk.DISABLED)
        self.copy_output_button.config(state=tk.DISABLED)

    def start_upload(self):
        if not self.file_widgets:
            messagebox.showwarning("No Files", "Add files to upload.")
            return

        service = self.notebook.tab(self.notebook.select(), "text")
        imx_gallery_id: Optional[str] = None
        
        if service == "imx.to":
            api_key = self.imx_api_key_entry.get()
            if not api_key:
                messagebox.showerror("Error", "API Key required for imx.to.")
                return
            username = None
            password = api_key
            content_var = None
            thumb_size_var = self.imx_thumb_var
            cover_var = self.imx_cover_var
            imx_gallery_id = self.imx_gallery_upload_entry.get().strip() or None
        else:
            username = None
            password = None
            content_var = self.pix_content_var
            thumb_size_var = self.pix_thumb_var
            cover_var = None

        # Save state for retries
        self.last_service = service
        self.last_username = username
        self.last_password = password
        self.last_content_var = content_var
        self.last_imx_thumb_var = self.imx_thumb_var
        self.last_pix_thumb_var = self.pix_thumb_var
        self.last_imx_cover_var = self.imx_cover_var
        self.last_pix_cover_var = None
        self.last_imx_gallery_id = imx_gallery_id

        self.gallery_hash = None
        self.gallery_upload_hash = None
        self.gallery_url = None

        self.results = []
        self.completed_files = 0
        self.upload_times = []
        self.cancel_event.clear()
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.eta_label.config(text="")

        # Handle Gallery Creation for pixhost.to
        if service == "pixhost.to" and self.pix_create_gallery_var.get():
            try:
                headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8", "Accept": "application/json"}
                content_map = {"Safe": "0", "Adult": "1"}
                data = {
                    "title": self.pix_gallery_name_entry.get() or "Untitled Gallery",
                    "content_type": content_map[self.pix_content_var.get()],
                    "visibility": "public" if self.pix_gallery_visibility_var.get() == "Public" else "private"
                }
                response = requests.post(Constants.PIX_GALLERIES_URL, headers=headers, data=data)
                response.raise_for_status()
                json_data = response.json()
                self.gallery_hash = json_data["hash"]
                self.gallery_upload_hash = json_data["upload_hash"]
                self.gallery_url = json_data["show_url"]
                self.log_message(f"Gallery created: {self.gallery_url}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create gallery: {str(e)}")
                return

        self.set_buttons_locked(True)
        self.stop_upload_button.config(state=tk.NORMAL)

        num_threads = 5 if service == "imx.to" else 3

        for i, file_path in enumerate(self.file_widgets.keys()):
            self.queue.put((file_path, i == 0))

        for _ in range(num_threads):
            t = threading.Thread(target=self.upload_worker, 
                                 args=(service, username, password, content_var,
                                       self.imx_thumb_var, self.pix_thumb_var,
                                       self.imx_cover_var, None,
                                       self.gallery_hash, self.gallery_upload_hash,
                                       imx_gallery_id))
            t.daemon = True
            t.start()
            self.active_threads.append(t)

        self.root.after(100, self.check_threads)

    def stop_upload(self):
        self.cancel_event.set()
        self.log_message("Upload cancellation requested.")
        self.set_buttons_locked(False)
        self.stop_upload_button.config(state=tk.DISABLED)

    def set_buttons_locked(self, locked: bool):
        state = tk.DISABLED if locked else tk.NORMAL
        self.add_files_button.config(state=state)
        self.add_folder_button.config(state=state)
        self.clear_list_button.config(state=state)
        self.start_upload_button.config(state=state)
        self.notebook.state(['disabled'] if locked else ['!disabled'])

    def log_message(self, message: str):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def upload_worker(self, service: str, username: Optional[str], password: Optional[str], content_var: Any, 
                      imx_thumb_var: Any, pix_thumb_var: Any, imx_cover_var: Any, pix_cover_var: Any, 
                      gallery_hash: Optional[str], gallery_upload_hash: Optional[str],
                      imx_gallery_id: Optional[str]):
        session = requests.Session()
        retries = Retry(total=Constants.RETRY_TOTAL, backoff_factor=Constants.RETRY_BACKOFF, status_forcelist=Constants.RETRY_STATUS)
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        while not self.queue.empty() and not self.cancel_event.is_set():
            file_path, is_first_file = self.queue.get()

            with self.lock:
                widgets = self.file_widgets[file_path]
                widgets['status'] = 'uploading'
                self.progress_queue.put(('status', file_path, 'uploading'))

            display_name = widgets['display_name']
            start_time = time.time()

            uploader = None
            try:
                def callback(monitor: MultipartEncoderMonitor):
                    if self.cancel_event.is_set():
                        raise ValueError("Upload cancelled")
                    progress = (monitor.bytes_read / monitor.len) * 100
                    self.progress_queue.put(('progress', file_path, progress))

                if service == "imx.to":
                    thumb_size_to_use = imx_thumb_var.get()
                    uploader = ImxUploader(username, password, file_path, callback, 
                                           thumb_size_to_use, imx_gallery_id)
                elif service == "pixhost.to":
                    thumb_size_to_use = pix_thumb_var.get()
                    uploader = PixhostUploader(file_path, callback, 
                                               content_var.get() if content_var else "Safe", 
                                               thumb_size_to_use, gallery_hash, gallery_upload_hash)
                else:
                    raise ValueError("Unknown service")

                url, data_monitor, headers = uploader.get_request_params()
                
                response: requests.Response = session.post(url, headers=headers, data=data_monitor, timeout=300)
                response.raise_for_status()
                
                try:
                    json_data: Dict[str, Any] = response.json()
                except JSONDecodeError:
                    if service == "pixhost.to" and response.text:
                         raise ValueError(f"API Error: {response.text[:100]}...")
                    raise ValueError(f"Invalid JSON response: {response.text[:100]}...")

                uploaded_url, th_url = uploader.parse_response(json_data)

                with self.lock:
                    self.results.append((file_path, (uploaded_url, th_url)))
                    self.log_message(f"Uploaded {display_name}: {uploaded_url}")
                    self.progress_queue.put(('status', file_path, 'success'))
                    self.upload_times.append(time.time() - start_time)

            except requests.exceptions.RequestException as e:
                with self.lock:
                    error_msg: str = f"Error uploading {display_name}: {e}"
                    if e.response is not None:
                        error_msg += f" (Details: {e.response.text})"
                    self.log_message(error_msg)
                    self.progress_queue.put(('status', file_path, 'failed'))
                    
            except Exception as e:
                with self.lock:
                    self.log_message(f"Failed to upload {display_name}: {str(e)}")
                    self.progress_queue.put(('status', file_path, 'failed'))
                    
            finally:
                if uploader:
                    uploader.close()
                self.queue.task_done()

    def update_progress(self) -> None:
        """GUI update loop for progress bars and statuses."""
        try:
            while not self.progress_queue.empty():
                msg_type, file_path, value = self.progress_queue.get_nowait()
                
                if file_path not in self.file_widgets:
                    continue
                
                widgets: Dict[str, Any] = self.file_widgets[file_path]

                if msg_type == 'progress':
                    if widgets['status'] == 'uploading':
                        widgets['progress']['value'] = value
                
                elif msg_type == 'status':
                    widgets['status'] = value
                    if value == 'uploading':
                        widgets['status_label'].config(text="⬆️")
                        widgets['progress'].config(style="default.Horizontal.TProgressbar")
                        widgets['retry_button'].config(state=tk.DISABLED)
                    elif value == 'success':
                        widgets['status_label'].config(text="✅")
                        widgets['progress']['value'] = 100
                        widgets['progress'].config(style="success.Horizontal.TProgressbar")
                        widgets['retry_button'].config(state=tk.DISABLED)
                        self.completed_files += 1
                    elif value == 'failed':
                        widgets['status_label'].config(text="❌")
                        widgets['progress']['value'] = 100
                        widgets['progress'].config(style="failed.Horizontal.TProgressbar")
                        widgets['retry_button'].config(state=tk.NORMAL)
                        self.completed_files += 1
            
            if self.total_files > 0:
                total_progress_sum = sum(w['progress']['value'] for w in self.file_widgets.values())
                overall_progress = total_progress_sum / self.total_files
                self.progress_bar['value'] = overall_progress
                
                if self.completed_files == self.total_files:
                    if any(w['status'] == 'failed' for w in self.file_widgets.values()):
                        self.progress_bar.config(style="failed.Horizontal.TProgressbar")
                    else:
                        self.progress_bar.config(style="success.Horizontal.TProgressbar")
                
                if self.upload_times and self.completed_files < self.total_files:
                    avg_time: float = sum(self.upload_times) / len(self.upload_times)
                    remaining_files: int = self.total_files - self.completed_files
                    eta_seconds: float = avg_time * remaining_files
                    eta_str: str = f"ETA: {int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                    self.eta_label.config(text=eta_str)
                else:
                    self.eta_label.config(text="")

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.update_progress)

    def retry_upload(self, file_path: str) -> None:
        """Queue a single failed file for retry."""
        if file_path not in self.file_widgets:
            return
        
        widgets: Dict[str, Any] = self.file_widgets[file_path]
        
        widgets['status_label'].config(text="⏳")
        widgets['progress']['value'] = 0
        widgets['progress'].config(style="default.Horizontal.TProgressbar")
        widgets['retry_button'].config(state=tk.DISABLED)
        widgets['status'] = 'pending'
        
        all_files_in_order: List[str] = list(self.file_widgets.keys())
        is_first_file: bool = (all_files_in_order[0] == file_path) if all_files_in_order else False
        
        self.queue.put((file_path, is_first_file))
        self.log_message(f"Retrying {widgets['display_name']}...")
        
        if self.completed_files > 0:
            self.completed_files -= 1
        self.progress_bar.config(style="default.Horizontal.TProgressbar")

        self.active_threads = [t for t in self.active_threads if t.is_alive()]
        if not self.active_threads:
            self.log_message("No active workers. Starting one for retry.")
            
            self.set_buttons_locked(True)
            self.stop_upload_button.config(state=tk.NORMAL)
            
            t: threading.Thread = threading.Thread(target=self.upload_worker, 
                                     args=(self.last_service, 
                                           self.last_username, 
                                           self.last_password, 
                                           self.last_content_var, 
                                           self.last_imx_thumb_var,
                                           self.last_pix_thumb_var,
                                           self.last_imx_cover_var,
                                           self.last_pix_cover_var,
                                           self.gallery_hash,
                                           self.gallery_upload_hash,
                                           self.last_imx_gallery_id))
            t.daemon = True
            t.start()
            self.active_threads.append(t)
            
            self.root.after(100, self.check_threads)

    def check_threads(self) -> None:
        """Check if all worker threads have finished."""
        self.active_threads = [t for t in self.active_threads if t.is_alive()]
        
        if not self.active_threads and self.queue.empty():
            self.log_message("All uploads finished.")
            self.set_buttons_locked(False)
            self.stop_upload_button.config(state=tk.DISABLED)
            
            if self.gallery_hash and self.gallery_upload_hash and not self.cancel_event.is_set():
                if not any(w['status'] == 'failed' for w in self.file_widgets.values()):
                    try:
                        url = f"{Constants.PIX_GALLERIES_URL}/{self.gallery_hash}/finalize"
                        headers = {
                            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                            "Accept": "application/json"
                        }
                        data = {"gallery_upload_hash": self.gallery_upload_hash}
                        response = requests.post(url, headers=headers, data=data)
                        response.raise_for_status()
                        self.log_message("Gallery finalized successfully.")
                    except Exception as e:
                        self.log_message(f"Failed to finalize gallery: {str(e)}")
                else:
                    self.log_message("Gallery not finalized due to upload failures.")

            if self.results:
                self.generate_output_file()
        else:
            self.root.after(100, self.check_threads)

    def generate_output_file(self) -> None:
        """Generate output file based on selected format and potentially a links file."""
        if not self.results:
            self.log_message("No successful uploads to generate file.")
            return

        sorted_results: List[Tuple[str, Tuple[str, str]]] = []
        for file_path in self.file_widgets.keys():
            found_result: Optional[Tuple[str, Tuple[str, str]]] = next((r for r in self.results if r[0] == file_path), None)
            if found_result:
                sorted_results.append(found_result)
        
        if not sorted_results:
            self.log_message("No matching results found in file list.")
            return
            
        valid_results: List[Tuple[str, Tuple[str, str]]] = [r for r in sorted_results if r[1] and r[1][0] and r[1][1]]
        if not valid_results:
            self.log_message("No valid URLs found in results.")
            return

        output_format: str = self.output_format_var.get()
        output_filename: str = "upload_results.txt"
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                if self.gallery_url:
                    f.write(f"Gallery URL: {self.gallery_url}\n\n")
                if output_format == "BBCode":
                    f.write("[center]\n")
                    content: str = ' '.join(f"[url={uploaded_url}][img]{th_url}[/img][/url]" 
                                          for _, (uploaded_url, th_url) in valid_results)
                    f.write(content)
                    f.write("\n[/center]\n")
                elif output_format == "Markdown":
                    content = '\n'.join(f"[![{th_url}]({th_url})]({uploaded_url})" 
                                        for _, (uploaded_url, th_url) in valid_results)
                    f.write(content)
                elif output_format == "HTML":
                    content = '\n'.join(f'<a href="{uploaded_url}"><img src="{th_url}" alt="Image"></a>' 
                                        for _, (uploaded_url, th_url) in valid_results)
                    f.write(content)
            
            self.log_message(f"Successfully generated {output_filename} in {output_format} format")
            self.open_output_button.config(state=tk.NORMAL)
            self.copy_output_button.config(state=tk.NORMAL)
            
            if self.last_service == "imx.to" and self.imx_generate_links_var.get():
                self.generate_links_file(valid_results)

        except Exception as e:
            self.log_message(f"Error generating output file: {e}")

    def generate_links_file(self, valid_results: List[Tuple[str, Tuple[str, str]]]) -> None:
        """Generates a separate links.txt file with one full-size URL per line."""
        output_filename: str = "links.txt"
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                for _, (uploaded_url, _) in valid_results:
                    f.write(f"{uploaded_url}\n")
            self.log_message(f"Successfully generated {output_filename}")
        except Exception as e:
            self.log_message(f"Error generating {output_filename}: {e}")

    def copy_output(self) -> None:
        """Copy the generated output to clipboard."""
        output_filename: str = "upload_results.txt"
        if not os.path.exists(output_filename):
            self.log_message(f"Error: {output_filename} not found.")
            return

        try:
            with open(output_filename, "r", encoding="utf-8") as f:
                pyperclip.copy(f.read())
            self.log_message("Output copied to clipboard.")
        except Exception as e:
            self.log_message(f"Error copying to clipboard: {e}")

    def open_output_file(self) -> None:
        """Open the generated output file with the default system editor."""
        output_filename: str = "upload_results.txt"
        if not os.path.exists(output_filename):
            self.log_message(f"Error: {output_filename} not found.")
            return

        try:
            if platform.system() == "Windows":
                os.startfile(output_filename)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", output_filename])
            else:
                subprocess.Popen(["xdg-open", output_filename])
        except Exception as e:
            self.log_message(f"Error opening file: {e}")

    def on_close(self):
        """Handle window close – ask for confirmation and stop uploads."""
        if messagebox.askokcancel(
            "Quit",
            "Do you really want to quit?\nAny running uploads will be stopped."
        ):
            self.stop_upload()  # set cancel flag for all worker threads
            
            # --- ADDED: Save credentials to keyring on exit ---
            try:
                # Save API key
                keyring.set_password(Constants.KEYRING_SERVICE_API, "api_key", self.imx_api_key_entry.get())
                
                # Save gallery credentials ONLY if the window has been opened
                if self.gallery_manager_window and self.gallery_manager_window.winfo_exists():
                    keyring.set_password(Constants.KEYRING_SERVICE_USER, "username", self.gallery_manager_username_entry.get())
                    keyring.set_password(Constants.KEYRING_SERVICE_PASS, "password", self.gallery_manager_password_entry.get())
                elif self.loaded_imx_user: 
                    # If window was never opened, save the values we loaded on startup
                    keyring.set_password(Constants.KEYRING_SERVICE_USER, "username", self.loaded_imx_user)
                    keyring.set_password(Constants.KEYRING_SERVICE_PASS, "password", self.loaded_imx_pass)
                
                self.log_message("Credentials saved.")
            except Exception as e:
                self.log_message(f"Warning: Could not save credentials to keyring. {e}")
            # --- END ADD ---

            if self.gallery_manager_window:
                self.gallery_manager_window.destroy()
            self.root.destroy()  # close the Tk window


if __name__ == "__main__":
    try:
        root = ThemedTk(theme="arc")
    except Exception:
        root = tk.Tk()
        
    app = ImageUploader(root)
    root.mainloop()
