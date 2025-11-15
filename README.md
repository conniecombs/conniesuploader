# Connie's Uploader v1.0

**Release Date:** November 15, 2025

Welcome to the first major release of Connie's Uploader! This is a cross-platform desktop application built with Python and Tkinter for uploading images to popular hosting services like imx.to and pixhost.to. It provides a user-friendly GUI for batch uploads, progress tracking, gallery management, and output generation in various formats (BBCode, Markdown, HTML).

This release focuses on core functionality, secure credential handling, and essential features for efficient image uploading. The app is designed for users who need to upload multiple images quickly, with options for thumbnails, galleries, and retry mechanisms for failed uploads.

[![https://image.imx.to/u/t/2025/11/15/6g142d.jpg](https://image.imx.to/u/t/2025/11/15/6g142d.jpg)](https://imx.to/i/6g142d)
[![https://image.imx.to/u/t/2025/11/15/6g142e.jpg](https://image.imx.to/u/t/2025/11/15/6g142e.jpg)](https://imx.to/i/6g142e)
[![https://image.imx.to/u/t/2025/11/15/6g142a.jpg](https://image.imx.to/u/t/2025/11/15/6g142a.jpg)](https://imx.to/i/6g142a)

## Key Features
- **Multi-Service Support**: Upload to imx.to (via API key) or pixhost.to with customizable options like content type (Safe/Adult) and thumbnail sizes.
- **Batch Uploads**: Add individual files or entire folders, with support for JPG, JPEG, PNG, GIF, BMP, and WEBP formats. Handles large batches (with warnings for >1000 files).
- **Progress Tracking**: Individual file progress bars, overall progress, and ETA estimates. Visual status indicators (pending, uploading, success, failed).
- **Retry Mechanism**: One-click retry for failed uploads without restarting the entire batch.
- **Gallery Management**:
  - For imx.to: Create new galleries, rename existing ones, and upload directly to a gallery ID. Includes a dedicated Gallery Manager window for login-based operations.
  - For pixhost.to: Optional gallery creation with name, visibility (Public/Private), and automatic finalization after successful uploads.
- **Output Generation**: Automatically generates `upload_results.txt` in BBCode, Markdown, or HTML formats for easy sharing. Optional `links.txt` for full-size URLs (imx.to only).
- **Secure Credential Storage**: Uses `keyring` for storing and auto-filling API keys, usernames, and passwords securely (platform-agnostic).
- **Logging**: Detailed scrollable log pane with copy, select all, and clear options via right-click menu.
- **Theming and UI**: Modern look with ttkthemes (arc theme fallback), resizable window, and scrollable file list. Supports mouse wheel scrolling on all platforms.
- **Cancellation Support**: Stop ongoing uploads gracefully.
- **Cross-Platform**: Tested on Windows, macOS, and Linux.

## Improvements and Technical Details
- **Networking**: Robust HTTP handling with retries (3 attempts with backoff) for server errors (500-504). Multipart uploads with progress monitoring.
- **Layout**: New vertical pane design with settings on the left, file list in the center, and log at the bottom for better usability.
- **Performance**: Multi-threaded uploads (5 threads for imx.to, 3 for pixhost.to) for faster batch processing. Stateful REPL-like environment awareness (though not used in this version).
- **Error Handling**: Graceful handling of API errors, invalid responses, and cancellations. Logs include timestamps and levels.
- **Dependencies**: Relies on standard libraries plus `requests`, `requests-toolbelt`, `ttkthemes`, `keyring`, and others (full list in code). No internet access beyond API calls.

## Bug Fixes
This being the initial release, there are no prior bugs to fix. However, the code includes safeguards against common issues like JSON decode errors, file I/O failures, and platform-specific scrolling behaviors.

## Known Issues
- Large files or slow connections may timeout (current timeout: 300s); consider adjusting in future releases.
- Gallery management for imx.to requires valid login credentials; API key is sufficient for uploads but not for creation/renaming.
- No auto-update mechanism yet—check releases manually.
- Limited to supported image extensions; other file types are ignored.

## Installation
1. Ensure Python 3.12+ is installed.
2. Install dependencies: `pip install tkinter ttkthemes requests requests-toolbelt keyring pyperclip` (plus any missing from the import list).
3. Download `uploader1.0.py` from the release assets.
4. Run: `python uploader1.0.py`.

For development, clone the repo and run directly.

## Acknowledgments
Thanks to the open-source community for libraries like `requests`, `ttkthemes`, and `keyring`. Special shoutout to imx.to and pixhost.to for their APIs.

If you encounter issues or have feature requests, please open an issue on the GitHub repo. Happy uploading!

---

*Download the source code and assets from the release page.*
