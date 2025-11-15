import tkinter as tk
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

# Constants
class Constants:
    IMX_URL = "https://api.imx.to/v1/upload.php"
    PIX_URL = "https://api.pixhost.to/images"
    SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    MAX_FILES_WARNING = 1000
    RETRY_TOTAL = 3
    RETRY_BACKOFF = 1
    RETRY_STATUS = [500, 502, 503, 504]

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
    def __init__(self, username: Optional[str], password: Optional[str], file_path: str, monitor_callback: Any, 
                 thumb_size_str: str):
        super().__init__(username, password, file_path, monitor_callback)
        size_to_api_map: Dict[str, str] = {"100": "1", "180": "2", "250": "3", "300": "4", "600": "5", "150": "6"}
        self.thumb_size: str = size_to_api_map.get(thumb_size_str, "2")  # Default to 180px

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url: str = Constants.IMX_URL
        self.headers['X-API-KEY'] = self.password or ""
        
        fields: Dict[str, Any] = {
            "image": (self.basename, self.file_obj, self.mime_type),
            "format": "json",
            "thumbnail_size": self.thumb_size,
        }
        
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
    def __init__(self, file_path: str, monitor_callback: Any, content_type_str: str, thumb_size_str: str):
        super().__init__(None, None, file_path, monitor_callback)
        
        content_map: Dict[str, str] = {"Safe": "0", "Adult": "1"}
        self.content_type: str = content_map.get(content_type_str, "0")
        
        valid_thumbs: List[str] = ["150", "200", "250", "300", "350", "400", "450", "500"]
        self.thumb_size: str = thumb_size_str if thumb_size_str in valid_thumbs else "200"

    def get_request_params(self) -> Tuple[str, MultipartEncoderMonitor, Dict[str, str]]:
        self.file_obj = open(self.file_path, 'rb')
        url: str = Constants.PIX_URL
        
        fields: Dict[str, Any] = {
            "img": (self.basename, self.file_obj, self.mime_type),
            "content_type": self.content_type,
            "max_th_size": self.thumb_size,
        }
        
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
        self.root.title("Connie's Uploader 0.9.6")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

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

        # --- Main Layout (3 Panes) ---
        self.main_paned_window: ttk.PanedWindow = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned_window.pack(fill=tk.BOTH, expand=True)

        # --- Pane 1: Settings (Left) ---
        self.settings_frame: ttk.Frame = ttk.Frame(self.main_paned_window, width=300, padding=15)
        self.settings_frame.columnconfigure(0, weight=1)
        self.settings_frame.rowconfigure(1, weight=1)
        
        # --- Pane 2: File List (Center) ---
        self.file_list_outer_frame: ttk.Frame = ttk.Frame(self.main_paned_window, width=450, padding=(15, 15, 0, 15))
        self.file_list_outer_frame.pack_propagate(False)
        self.file_list_outer_frame.grid_rowconfigure(0, weight=1)
        self.file_list_outer_frame.grid_columnconfigure(0, weight=1)

        # --- Pane 3: Log (Right) ---
        self.log_frame: ttk.Frame = ttk.Frame(self.main_paned_window, width=250, padding=(0, 15, 15, 15))
        self.log_frame.pack_propagate(False)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)

        self.main_paned_window.add(self.settings_frame)
        self.main_paned_window.add(self.file_list_outer_frame)
        self.main_paned_window.add(self.log_frame)
        self.main_paned_window.sashpos(0, 320)
        self.main_paned_window.sashpos(1, 770)

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
        self.imx_password_entry: ttk.Entry = ttk.Entry(self.imx_tab, show="*", width=30)
        self.imx_password_entry.grid(row=0, column=1, pady=10, sticky="ew")
        
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
        
        self.imx_generate_links_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.imx_generate_links_check: ttk.Checkbutton = ttk.Checkbutton(self.imx_options_frame, text="Generate URL File (links.txt)", 
                                                        variable=self.imx_generate_links_var)
        self.imx_generate_links_check.grid(row=2, column=0, columnspan=2, pady=10, sticky="w")

        # --- Pixhost.to Tab Widgets ---
        self.pixhost_tab.columnconfigure(1, weight=1)
        self.pix_options_frame: ttk.Labelframe = ttk.Labelframe(self.pixhost_tab, text="Upload Options", padding=15)
        self.pix_options_frame.grid(row=0, column=0, columnspan=2, pady=15, sticky="ew")
        self.pix_options_frame.columnconfigure(1, weight=1)

        self.pix_content_label: ttk.Label = ttk.Label(self.pix_options_frame, text="Content:")
        self.pix_content_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_content_var: tk.StringVar = tk.StringVar(value="Safe")
        self.pix_content_menu: ttk.Combobox = ttk.Combobox(self.pix_options_frame, textvariable=self.pix_content_var,
                                             values=["Safe", "Adult"], state="readonly", width=15)
        self.pix_content_menu.grid(row=0, column=1, pady=10, sticky="w")

        self.pix_thumb_label: ttk.Label = ttk.Label(self.pix_options_frame, text="Thumbnail:")
        self.pix_thumb_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        self.pix_thumb_var: tk.StringVar = tk.StringVar(value="200")
        self.pix_thumb_menu: ttk.Combobox = ttk.Combobox(self.pix_options_frame, textvariable=self.pix_thumb_var,
                                           values=["150", "200", "250", "300", "350", "400", "450", "500"],
                                           state="readonly", width=15)
        self.pix_thumb_menu.grid(row=1, column=1, pady=10, sticky="w")

        self.pix_cover_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.pix_cover_check: ttk.Checkbutton = ttk.Checkbutton(self.pix_options_frame, text="Use 1st image as 500px cover", variable=self.pix_cover_var)
        self.pix_cover_check.grid(row=2, column=0, columnspan=2, pady=10, sticky="w")

        # --- General Settings (Threads) ---
        self.threads_frame: ttk.Labelframe = ttk.Labelframe(self.settings_frame, text="General", padding=15)
        self.threads_frame.grid(row=2, column=0, pady=15, sticky="ew")
        self.threads_frame.columnconfigure(1, weight=1)
        
        self.threads_label: ttk.Label = ttk.Label(self.threads_frame, text="Threads:")
        self.threads_label.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="w")
        self.threads_var: tk.IntVar = tk.IntVar(value=4)
        self.threads_spinbox: ttk.Spinbox = ttk.Spinbox(self.threads_frame, from_=1, to=10, textvariable=self.threads_var, width=5)
        self.threads_spinbox.grid(row=0, column=1, pady=10, sticky="w")

        self.output_format_label: ttk.Label = ttk.Label(self.threads_frame, text="Output Format:")
        self.output_format_label.grid(row=1, column=0, padx=(0, 10), pady=10, sticky="w")
        self.output_format_var: tk.StringVar = tk.StringVar(value="BBCode")
        self.output_format_menu: ttk.Combobox = ttk.Combobox(self.threads_frame, textvariable=self.output_format_var,
                                                             values=["BBCode", "Markdown", "HTML"], state="readonly", width=15)
        self.output_format_menu.grid(row=1, column=1, pady=10, sticky="w")

        # --- Populate Pane 2: File List ---
        self.file_list_scrollable_frame: ScrollableFrame = ScrollableFrame(self.file_list_outer_frame)
        self.file_list_scrollable_frame.grid(row=0, column=0, sticky="nsew")
        self.file_list_frame: ttk.Frame = self.file_list_scrollable_frame.scrollable_frame
        
        self.no_files_label: ttk.Label = ttk.Label(self.file_list_frame, text="No files selected.", style="Status.TLabel", padding=15)
        self.no_files_label.pack()

        # --- Populate Pane 3: Log ---
        self.log_header: ttk.Label = ttk.Label(self.log_frame, text="Log", style="Header.TLabel")
        self.log_header.grid(row=0, column=0, pady=(0, 15), sticky="w")
        
        self.log_text: scrolledtext.ScrolledText = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, height=10, state=tk.DISABLED, font=("Courier", 10))
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_frame.grid_rowconfigure(1, weight=1)

        # --- Bottom Bar: Controls & Progress ---
        self.bottom_frame: ttk.Frame = ttk.Frame(self.root, padding=15)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.select_files_button: ttk.Button = ttk.Button(self.bottom_frame, text="Select Files", command=self.select_files)
        self.select_files_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.select_folder_button: ttk.Button = ttk.Button(self.bottom_frame, text="Select Folder", command=self.select_folder)
        self.select_folder_button.pack(side=tk.LEFT, padx=10)
        
        self.clear_files_button: ttk.Button = ttk.Button(self.bottom_frame, text="Clear List", command=self.clear_file_list)
        self.clear_files_button.pack(side=tk.LEFT, padx=10)

        self.start_upload_button: ttk.Button = ttk.Button(self.bottom_frame, text="Start Upload", command=self.start_upload)
        self.start_upload_button.pack(side=tk.LEFT, padx=10)

        self.stop_upload_button: ttk.Button = ttk.Button(self.bottom_frame, text="Stop Upload", command=self.stop_upload, state=tk.DISABLED)
        self.stop_upload_button.pack(side=tk.LEFT, padx=10)

        self.generate_bb_button: ttk.Button = ttk.Button(self.bottom_frame, text="Generate Output", command=self.generate_output_file, state=tk.DISABLED)
        self.generate_bb_button.pack(side=tk.LEFT, padx=10)

        self.copy_output_button: ttk.Button = ttk.Button(self.bottom_frame, text="Copy Output", command=self.copy_output, state=tk.DISABLED)
        self.copy_output_button.pack(side=tk.LEFT, padx=10)

        self.open_output_button: ttk.Button = ttk.Button(self.bottom_frame, text="Open Output File", command=self.open_output_file, state=tk.DISABLED)
        self.open_output_button.pack(side=tk.LEFT, padx=10)

        self.progress_bar: ttk.Progressbar = ttk.Progressbar(self.bottom_frame, orient=tk.HORIZONTAL, mode='determinate', style="default.Horizontal.TProgressbar")
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(15, 0))

        self.eta_label: ttk.Label = ttk.Label(self.bottom_frame, text="", style="Status.TLabel")
        self.eta_label.pack(side=tk.RIGHT, padx=(10, 0))

        # --- Right-click context menu for entries ---
        self.make_entry_context_menu(self.imx_password_entry)

        # --- Internal State ---
        self.file_widgets: Dict[str, Dict[str, Any]] = {}
        self.queue: queue.Queue = queue.Queue()
        self.results: List[Tuple[str, Tuple[str, str]]] = []
        self.lock: threading.Lock = threading.Lock()
        self.active_threads: List[threading.Thread] = []
        self.progress_queue: queue.Queue = queue.Queue()
        self.total_files: int = 0
        self.completed_files: int = 0
        self.upload_times: List[float] = []
        self.cancel_event: threading.Event = threading.Event()
        
        # --- Store last settings for retry ---
        self.last_service: Optional[str] = None
        self.last_username: Optional[str] = None
        self.last_password: Optional[str] = None
        self.last_content_var: Optional[tk.StringVar] = None
        self.last_imx_thumb_var: Optional[tk.StringVar] = None
        self.last_pix_thumb_var: Optional[tk.StringVar] = None
        self.last_imx_cover_var: Optional[tk.BooleanVar] = None
        self.last_pix_cover_var: Optional[tk.BooleanVar] = None

        self.load_settings()

        # --- Tooltips ---
        self.create_tooltip(self.imx_thumb_menu, "Select thumbnail size for imx.to uploads")
        self.create_tooltip(self.pix_thumb_menu, "Select thumbnail size for pixhost.to uploads")
        self.create_tooltip(self.threads_spinbox, "Number of concurrent upload threads (1-10)")
        self.create_tooltip(self.output_format_menu, "Format for generated output file")

        # --- Help Menu ---
        self.menu: tk.Menu = tk.Menu(self.root)
        self.root.config(menu=self.menu)
        help_menu: tk.Menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", "Connie's Uploader v0.9.6\nImage uploader for imx.to and pixhost.to"))

    def create_tooltip(self, widget: Any, text: str) -> None:
        """Simple tooltip for widgets."""
        tooltip: tk.Toplevel = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.withdraw()
        label: tk.Label = tk.Label(tooltip, text=text, background="#ffffe0", relief="solid", borderwidth=1, padx=5, pady=3)
        label.pack()

        def show_tooltip(event: Any) -> None:
            x: int = widget.winfo_rootx() + widget.winfo_width() + 10
            y: int = widget.winfo_rooty()
            tooltip.wm_geometry(f"+{x}+{y}")
            tooltip.deiconify()

        def hide_tooltip(event: Any) -> None:
            tooltip.withdraw()

        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def make_entry_context_menu(self, entry_widget: ttk.Entry) -> None:
        """Creates a right-click context menu for an Entry widget."""
        menu: tk.Menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Cut", command=lambda: entry_widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: entry_widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: entry_widget.event_generate("<<Paste>>"))
        
        entry_widget.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))

    def get_keyring_service(self, service_name: str) -> str:
        """Generates a unique service name for keyring."""
        return f"ImageUploaderApp_{service_name}"

    def load_settings(self) -> None:
        """Load settings from settings.json and keyring."""
        if os.path.exists("settings.json"):
            try:
                with open("settings.json", "r") as f:
                    settings: Dict[str, Any] = json.load(f)

                imx: Dict[str, Any] = settings.get("imx.to", {})
                self.imx_thumb_var.set(imx.get("thumb_size", "180"))
                self.imx_cover_var.set(imx.get("cover_image", False))
                self.imx_generate_links_var.set(imx.get("generate_links_file", False))

                pix: Dict[str, Any] = settings.get("pixhost.to", {})
                self.pix_content_var.set(pix.get("content_type", "Safe"))
                self.pix_thumb_var.set(pix.get("thumb_size", "200"))
                self.pix_cover_var.set(pix.get("cover_image", False))

                self.threads_var.set(settings.get("general", {}).get("threads", 4))
                self.output_format_var.set(settings.get("general", {}).get("output_format", "BBCode"))
            except json.JSONDecodeError:
                self.log_message("Error: Could not read settings.json. File might be corrupt.")
            except Exception as e:
                self.log_message(f"Error loading settings: {e}")

        try:
            imx_api_key: Optional[str] = keyring.get_password(self.get_keyring_service("imx.to"), "api_key")
            if imx_api_key:
                self.imx_password_entry.insert(0, imx_api_key)
        except Exception as e:
            self.log_message(f"Could not load API key from keyring: {e}. Please enter manually.")

    def save_settings(self) -> None:
        """Save settings to settings.json and keyring."""
        settings: Dict[str, Any] = {
            "imx.to": {
                "thumb_size": self.imx_thumb_var.get(),
                "cover_image": self.imx_cover_var.get(),
                "generate_links_file": self.imx_generate_links_var.get(),
            },
            "pixhost.to": {
                "content_type": self.pix_content_var.get(),
                "thumb_size": self.pix_thumb_var.get(),
                "cover_image": self.pix_cover_var.get(),
            },
            "general": {
                "threads": self.threads_var.get(),
                "output_format": self.output_format_var.get()
            }
        }
        try:
            with open("settings.json", "w") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            self.log_message(f"Error saving settings: {e}")

        try:
            keyring.set_password(self.get_keyring_service("imx.to"), 
                                 "api_key", 
                                 self.imx_password_entry.get())
        except Exception as e:
            self.log_message(f"Could not save API key to keyring: {e}")

    def on_close(self) -> None:
        """Handle window closing event."""
        if messagebox.askokcancel("Quit", "Do you want to save your settings before quitting?"):
            self.save_settings()
        self.root.destroy()

    def log_message(self, message: str) -> None:
        """Thread-safe logging to the text widget and logger."""
        logger.info(message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def select_files(self) -> None:
        """Open file dialog to select images and add them to the list."""
        file_paths: List[str] = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("All Files", "*.*")]
        )
        if file_paths:
            self.add_files_to_list(file_paths)

    def select_folder(self) -> None:
        """Open folder dialog, scan for images, and add them to the list."""
        folder_path: str = filedialog.askdirectory(title="Select Folder to Scan for Images")
        if folder_path:
            self.log_message(f"Scanning folder: {folder_path}...")
            threading.Thread(target=self.parse_folder, args=(folder_path,), daemon=True).start()

    def parse_folder(self, folder_path: str) -> None:
        """Recursively find all supported images in a folder using pathlib."""
        try:
            path: Path = Path(folder_path)
            image_files: List[str] = [str(p) for p in path.rglob('*') if p.suffix.lower() in Constants.SUPPORTED_EXTENSIONS]
            
            if len(image_files) > Constants.MAX_FILES_WARNING:
                self.root.after(0, lambda: messagebox.showwarning("Warning", f"Found {len(image_files)} files. Large batches may slow down the app."))
            
            if image_files:
                self.log_message(f"Found {len(image_files)} images. Adding to list...")
                self.root.after(0, self.add_files_to_list, image_files)
            else:
                self.log_message(f"No supported images found in {folder_path}.")
        except Exception as e:
            self.log_message(f"Error scanning folder: {e}")

    def add_files_to_list(self, file_paths: List[str]) -> None:
        """Add file widgets to the scrollable file list."""
        if not self.file_widgets:
            self.no_files_label.pack_forget()

        for file_path in file_paths:
            file_path = os.path.realpath(file_path)  # Secure against traversal
            if file_path in self.file_widgets:
                continue

            display_name: str = os.path.basename(file_path)
            
            file_frame: ttk.Frame = ttk.Frame(self.file_list_frame, padding=10)
            file_frame.pack(fill=tk.X, expand=True, pady=5)
            
            file_frame.columnconfigure(1, weight=1)

            status_label: ttk.Label = ttk.Label(file_frame, text="⏳", width=2)
            status_label.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="n")

            name_label: ttk.Label = ttk.Label(file_frame, text=display_name, anchor="w")
            name_label.grid(row=0, column=1, sticky="ew")

            progress: ttk.Progressbar = ttk.Progressbar(file_frame, orient=tk.HORIZONTAL, length=100, mode='determinate', style="default.Horizontal.TProgressbar")
            progress.grid(row=1, column=1, sticky="ew", pady=(5, 0))

            retry_button: ttk.Button = ttk.Button(file_frame, text="Retry", style="Small.TButton", state=tk.DISABLED,
                                      command=lambda p=file_path: self.retry_upload(p))
            retry_button.grid(row=0, column=2, rowspan=2, padx=(10, 0))

            self.file_widgets[file_path] = {
                'frame': file_frame,
                'status_label': status_label,
                'name_label': name_label,
                'progress': progress,
                'retry_button': retry_button,
                'status': 'pending',
                'display_name': display_name
            }

    def clear_file_list(self) -> None:
        """Remove all files from the list and reset state."""
        if not self.file_widgets:
            return
            
        if self.start_upload_button["state"] == tk.DISABLED:
            self.log_message("Cannot clear list while upload is in progress.")
            return

        for path, widgets in self.file_widgets.items():
            widgets['frame'].destroy()
        
        self.file_widgets.clear()
        self.results.clear()
        self.file_list_frame.pack_forget()
        self.file_list_frame.pack(fill='both', expand=True)
        self.no_files_label.pack()
        
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.log_message("File list cleared.")
        self.generate_bb_button.config(state=tk.DISABLED)
        self.copy_output_button.config(state=tk.DISABLED)
        self.open_output_button.config(state=tk.DISABLED)

    def start_upload(self) -> None:
        """Prepare and start the upload process."""
        service: str = self.notebook.tab(self.notebook.select(), "text")
        
        if service == "imx.to":
            username: Optional[str] = None
            password: str = self.imx_password_entry.get()
            if not password:
                messagebox.showerror("Error", "imx.to API Key is required.")
                return
            content_var: Optional[tk.StringVar] = None
        elif service == "pixhost.to":
            username: Optional[str] = None
            password: Optional[str] = None
            content_var: tk.StringVar = self.pix_content_var
        else:
            messagebox.showerror("Error", "Unknown service selected.")
            return

        if not self.file_widgets:
            messagebox.showinfo("No Files", "Please select files to upload first.")
            return
            
        if self.start_upload_button["state"] == tk.DISABLED:
            self.log_message("Upload already in progress.")
            return

        # Clear previous results and reset UI
        self.results.clear()
        self.total_files = 0
        self.completed_files = 0
        self.upload_times.clear()
        self.progress_bar['value'] = 0
        self.progress_bar.config(style="default.Horizontal.TProgressbar")
        self.cancel_event.clear()
        
        is_first: bool = True
        for file_path, widgets in self.file_widgets.items():
            if widgets['status'] != 'success':
                widgets['status'] = 'pending'
                widgets['status_label'].config(text="⏳")
                widgets['progress']['value'] = 0
                widgets['progress'].config(style="default.Horizontal.TProgressbar")
                widgets['retry_button'].config(state=tk.DISABLED)
                
                self.queue.put((file_path, is_first))
                is_first = False
                self.total_files += 1

        if self.total_files == 0:
            self.log_message("All files are already marked as successful. Clear list to re-upload.")
            return

        # Store settings for potential retries
        self.last_service = service
        self.last_username = username
        self.last_password = password
        self.last_content_var = content_var
        self.last_imx_thumb_var = self.imx_thumb_var
        self.last_pix_thumb_var = self.pix_thumb_var
        self.last_imx_cover_var = self.imx_cover_var
        self.last_pix_cover_var = self.pix_cover_var

        self.log_message(f"Starting upload of {self.total_files} files to {service}...")
        self.set_buttons_locked(True)
        self.stop_upload_button.config(state=tk.NORMAL)

        num_threads: int = self.threads_var.get()
        self.active_threads.clear()
        for _ in range(num_threads):
            t: threading.Thread = threading.Thread(target=self.upload_worker, 
                                 args=(service, username, password, content_var, 
                                       self.imx_thumb_var, self.pix_thumb_var, 
                                       self.imx_cover_var, self.pix_cover_var))
            t.daemon = True
            t.start()
            self.active_threads.append(t)

        self.root.after(100, self.update_progress)
        self.root.after(100, self.check_threads)

    def stop_upload(self) -> None:
        """Stop the ongoing upload."""
        self.cancel_event.set()
        self.log_message("Stopping upload...")
        self.stop_upload_button.config(state=tk.DISABLED)

    def set_buttons_locked(self, locked: bool) -> None:
        """Enable or disable buttons during upload."""
        state: str = tk.DISABLED if locked else tk.NORMAL
        self.start_upload_button.config(state=state)
        self.select_files_button.config(state=state)
        self.clear_files_button.config(state=state)
        
        if not locked and self.results:
             self.generate_bb_button.config(state=tk.NORMAL)
             self.copy_output_button.config(state=tk.NORMAL)
             self.open_output_button.config(state=tk.NORMAL)
        else:
             self.generate_bb_button.config(state=tk.DISABLED)
             self.copy_output_button.config(state=tk.DISABLED)
             self.open_output_button.config(state=tk.DISABLED)

    def create_callback(self, file_path: str) -> Any:
        """Create a callback for the MultipartEncoderMonitor."""
        def callback(monitor: MultipartEncoderMonitor) -> None:
            if file_path in self.file_widgets:
                if monitor.len > 0:
                    progress: int = int((monitor.bytes_read / monitor.len) * 100)
                    self.progress_queue.put(('progress', file_path, progress))
        return callback

    def upload_worker(self, service: str, username: Optional[str], password: Optional[str], content_var: Optional[tk.StringVar], 
                      imx_thumb_var: tk.StringVar, pix_thumb_var: tk.StringVar, 
                      imx_cover_var: tk.BooleanVar, pix_cover_var: tk.BooleanVar) -> None:
        """The main worker thread function."""
        session: requests.Session = requests.Session()
        retries: Retry = Retry(total=Constants.RETRY_TOTAL, backoff_factor=Constants.RETRY_BACKOFF, status_forcelist=Constants.RETRY_STATUS)
        session.mount('http://', HTTPAdapter(max_retries=retries))
        session.mount('https://', HTTPAdapter(max_retries=retries))
        
        while not self.queue.empty() and not self.cancel_event.is_set():
            try:
                file_path, is_first_file = self.queue.get(timeout=1)
            except queue.Empty:
                continue

            if file_path not in self.file_widgets:
                self.queue.task_done()
                continue
                
            display_name: str = self.file_widgets[file_path]['display_name']
            
            self.progress_queue.put(('status', file_path, 'uploading'))
            uploader: Optional[BaseUploader] = None
            start_time: float = time.time()
            try:
                thumb_size_to_use: str = ""
                if service == "imx.to":
                    thumb_size_to_use = imx_thumb_var.get()
                    if is_first_file and imx_cover_var.get():
                        thumb_size_to_use = "600"
                elif service == "pixhost.to":
                    thumb_size_to_use = pix_thumb_var.get()
                    if is_first_file and pix_cover_var.get():
                        thumb_size_to_use = "500"
                
                callback: Any = self.create_callback(file_path)
                
                if service == "imx.to":
                    uploader = ImxUploader(username, password, file_path, callback, 
                                           thumb_size_to_use)
                                           
                elif service == "pixhost.to":
                    uploader = PixhostUploader(file_path, callback, 
                                               content_var.get() if content_var else "Safe", 
                                               thumb_size_to_use)
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
                overall_progress: float = (self.completed_files / self.total_files) * 100
                self.progress_bar['value'] = overall_progress
                
                if self.completed_files == self.total_files:
                    if any(w['status'] == 'failed' for w in self.file_widgets.values()):
                        self.progress_bar.config(style="failed.Horizontal.TProgressbar")
                    else:
                        self.progress_bar.config(style="success.Horizontal.TProgressbar")

                # ETA calculation
                if self.upload_times:
                    avg_time: float = sum(self.upload_times) / len(self.upload_times)
                    remaining_files: int = self.total_files - self.completed_files
                    eta_seconds: float = avg_time * remaining_files
                    eta_str: str = f"ETA: {int(eta_seconds // 60)}m {int(eta_seconds % 60)}s" if remaining_files > 0 else ""
                    self.eta_label.config(text=eta_str)

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
                                       self.last_pix_cover_var))
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
            
            if self.total_files > 0 and self.completed_files == self.total_files:
                if any(w['status'] == 'failed' for w in self.file_widgets.values()):
                    self.progress_bar.config(style="failed.Horizontal.TProgressbar")
                else:
                    self.progress_bar.config(style="success.Horizontal.TProgressbar")

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


if __name__ == "__main__":
    try:
        root = ThemedTk(theme="arc")
    except Exception:
        root = tk.Tk()
        
    app = ImageUploader(root)
    root.mainloop()
