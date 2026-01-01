# Connie's Uploader Ultimate

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![CI Status](https://github.com/conniecombs/GolangVersion/workflows/CI%20-%20Build%20and%20Test/badge.svg)
![Security](https://github.com/conniecombs/GolangVersion/workflows/Security%20Scanning/badge.svg)
![Go Version](https://img.shields.io/badge/Go-1.24.11-00ADD8.svg)
![Python Version](https://img.shields.io/badge/Python-3.11+-3776AB.svg)

A powerful, multi-service image hosting uploader with an intuitive GUI. Upload images to multiple image hosting services with advanced features like batch processing, gallery management, and automatic forum posting.

**🎉 First Official Release (v1.0.0)** - Production-ready with comprehensive CI/CD automation, security fixes, and cross-platform builds.

## Features

### Supported Image Hosts
- **imx.to** - API-based uploads with gallery support
- **pixhost.to** - Fast uploads with gallery management
- **TurboImageHost** - High-performance image hosting
- **vipr.im** - Upload with folder organization
- **ImageBam** - Popular image hosting service

### Key Features
- 🖼️ **Batch Upload** - Upload multiple images simultaneously with configurable thread limits
- 📁 **Gallery Management** - Create and manage galleries across services
- 🎨 **Template System** - Customizable output templates (BBCode, HTML, Markdown)
- 🔄 **Drag & Drop** - Easy file and folder management
- 📋 **Auto-Copy** - Automatically copy formatted output to clipboard
- 🔒 **Secure Credentials** - Password storage using system keyring
- 🌙 **Dark/Light Mode** - System-aware appearance modes
- 📊 **Progress Tracking** - Real-time upload progress with per-file and batch status
- 🎯 **ViperGirls Integration** - Auto-post to saved forum threads
- 🔁 **Retry Failed** - Automatically retry failed uploads
- 🖼️ **Image Previews** - Thumbnail previews in the file list
- 📝 **Execution Log** - Detailed logging for troubleshooting

### Advanced Features
- **Custom Templates** - Create custom BBCode/HTML templates with placeholders
- **Gallery Auto-Creation** - Automatically create one gallery per folder
- **Cover Image Selection** - Choose how many cover images to include
- **Thread-based Uploads** - Configure concurrent upload threads per service
- **Sidecar Architecture** - High-performance Go backend for uploads
- **Central History** - All outputs saved to user directory for backup

## Installation

### Option 1: Download Pre-built Release (Recommended)

**Download the latest release for your platform:**

👉 **[Download v1.0.0](https://github.com/conniecombs/GolangVersion/releases/tag/v1.0.0)**

Available builds:
- **Windows**: `ConniesUploader-windows.zip` (includes `.exe` + SHA256 checksum)
- **Linux**: `ConniesUploader-linux.tar.gz` (includes binary + SHA256 checksum)
- **macOS**: `ConniesUploader-macos.zip` (includes binary + SHA256 checksum)

All releases are:
- ✅ Automatically built and tested via GitHub Actions CI/CD
- ✅ Cryptographically verified with SHA256 checksums
- ✅ Built from audited source code with zero CVEs
- ✅ Cross-platform compatible

**Verify your download (recommended):**
```bash
# Windows (PowerShell)
certutil -hashfile ConniesUploader.exe SHA256

# Linux/macOS
sha256sum ConniesUploader  # or shasum -a 256 ConniesUploader

# Compare with the .sha256 file included in the release
```

### Option 2: Build from Source (Windows)

#### Automated Build
Simply run the included build script:
```batch
build_uploader.bat
```

This script will:
1. Detect your system architecture (32-bit or 64-bit)
2. Download and install Python 3.11 if needed
3. Download and install Go 1.24+ if needed (required for security fixes)
4. Build the Go backend (uploader.exe)
5. Create a Python virtual environment
6. Install all dependencies
7. Build the final executable using PyInstaller

The final executable will be in the `dist` folder.

#### Manual Build

**Prerequisites:**
- Python 3.11+
- Go 1.24.11+ (required - includes critical CVE fixes)

**Steps:**

1. **Clone the repository:**
```bash
git clone https://github.com/conniecombs/GolangVersion.git
cd GolangVersion
```

2. **Build Go backend:**
```bash
# Dependencies are managed via go.mod - no need for manual initialization
go mod download
go build -ldflags="-s -w" -o uploader.exe uploader.go
```

3. **Set up Python environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

4. **Run the application:**
```bash
python main.py
```

### Option 3: Build from Source (Linux/macOS)

**Prerequisites:**
- Python 3.11+
- Go 1.24.11+ (required - includes critical CVE fixes)

**Steps:**

1. **Clone and navigate:**
```bash
git clone https://github.com/conniecombs/GolangVersion.git
cd GolangVersion
```

2. **Build Go backend:**
```bash
# Dependencies are managed via go.mod - no need for manual initialization
go mod download
go build -ldflags="-s -w" -o uploader uploader.go
```

3. **Install Python dependencies:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. **Run:**
```bash
python main.py
```

## Usage

### First-Time Setup

1. **Set Credentials** - Go to `Tools > Set Credentials` and enter your API keys and login credentials for the services you plan to use:
   - **imx.to**: Requires API key (get from imx.to account settings)
   - **Other services**: Username and password

2. **Select Image Host** - Choose your preferred image hosting service from the dropdown

3. **Configure Settings** - Adjust thread limits, thumbnail sizes, and content ratings as needed

### Basic Upload Workflow

1. **Add Images:**
   - Click `File > Add Files` or `File > Add Folder`
   - Drag and drop files/folders directly into the window
   - Each folder becomes a separate upload batch/group

2. **Configure Batch:**
   - Edit the group title (double-click)
   - Select output template (BBCode, HTML, etc.)
   - Optionally select a ViperGirls thread for auto-posting

3. **Start Upload:**
   - Click `Start Upload`
   - Monitor progress in real-time
   - Failed uploads can be retried with `Retry Failed` button

4. **Get Results:**
   - Output files are saved to the `Output` folder
   - If auto-copy is enabled, formatted text is copied to clipboard
   - Click `Open Output Folder` to view generated files

### Gallery Management

Access `Tools > Manage Galleries` to:
- View existing galleries
- Create new galleries
- Set gallery for current uploads

### Template Editor

Access `Tools > Template Editor` to:
- Create custom output templates
- Use placeholders: `{gallery_link}`, `{gallery_name}`, `{viewer}`, `{thumb}`, `{direct}`
- Preview templates with live data

### ViperGirls Integration

1. Set ViperGirls credentials in `Tools > Set Credentials > ViperGirls`
2. Access `Tools > Viper Tools` to:
   - Add thread URLs with custom names
   - Test credentials
3. When uploading, select a thread from the dropdown to auto-post results

### Context Menu Integration (Windows)

Install `Tools > Install Context Menu` to add "Upload with Connie's Uploader" to Windows Explorer right-click menu.

## Configuration

### Settings File
Application settings are stored in `user_settings.json` in the application directory.

### Credentials
Credentials are securely stored in the system keyring (Windows Credential Manager, macOS Keychain, or Linux Secret Service).

### Output Files
- **Output folder**: `./Output/` - Session outputs
- **History folder**: `~/.conniesuploader/history/` - Permanent backup of all outputs

## Architecture

The application uses a hybrid architecture:
- **Python (CustomTkinter)**: Modern GUI interface
- **Go**: High-performance upload backend with worker pools
- **JSON-RPC**: Communication between Python frontend and Go backend via stdin/stdout

This design provides:
- Fast, concurrent uploads
- Responsive UI during heavy operations
- Cross-platform compatibility

## CI/CD & Automation

### Automated Testing & Building

Every commit is automatically:
- ✅ **Built** on Windows, Linux, and macOS
- ✅ **Tested** with Go vet and full test suite
- ✅ **Linted** with golangci-lint and flake8
- ✅ **Security scanned** with multiple tools
- ✅ **Dependency checked** for known vulnerabilities

**GitHub Actions Workflows:**
- **[CI Pipeline](.github/workflows/ci.yml)** - Build, test, and validate on every push/PR
- **[Release Pipeline](.github/workflows/release.yml)** - Automated releases with checksums
- **[Security Scanning](.github/workflows/security.yml)** - Daily vulnerability detection

### Security

**Zero Known Vulnerabilities** - All dependencies are up-to-date and scanned daily:

- **Go 1.24.11** - Latest stable with 9 critical CVE fixes
- **golang.org/x/image v0.23.0** - 4 TIFF vulnerability fixes
- **golang.org/x/net v0.48.0** - HTTP/2 rapid reset protection

**Security Tools:**
- CodeQL analysis (Go & Python)
- gosec (Go security linter)
- Bandit (Python security linter)
- govulncheck (Go CVE database)
- Safety (Python dependency scanner)
- TruffleHog (secret detection)

**Security Features:**
- SHA256 verification for all downloads and releases
- Automated go.sum checksum validation
- Comprehensive error handling (16 upload error checks added)
- Secure credential storage via system keyring
- Path traversal attack prevention
- Input sanitization for all file operations

### Code Quality & Organization

Recent improvements:

**Modular Architecture:**
- `CredentialsManager` - Data-driven credential management with auto-generated UI
- `AutoPoster` - Isolated ViperGirls forum posting logic
- `UploadManager` - Upload orchestration and worker management
- `TemplateManager` - Template system for output formatting
- `SettingsManager` - Persistent configuration management
- `ValidationModule` - Security-focused input validation

**Security Enhancements:**
- Cryptographically secure random generation (`crypto/rand`)
- Path traversal attack prevention
- Input sanitization for file operations
- Secure credential storage via system keyring
- Type hints for critical functions (Python typing module)

**Code Quality:**
- Comprehensive error handling with specific exception types
- Extensive logging via `loguru` for debugging
- Consistent code formatting (`black` for Python, `gofmt` for Go)
- Clear separation of concerns
- Named constants for all configuration values
- Thorough documentation and docstrings

**Performance:**
- Go worker pool (8 concurrent workers) prevents goroutine explosion
- Configurable thread limits per service
- Efficient queue-based UI updates
- Thumbnail generation via Go sidecar
- Batch processing with progress tracking

## Troubleshooting

### Common Issues

**"uploader.exe not found" error:**
- Ensure the Go backend was built successfully
- The `uploader.exe` (or `uploader` on Linux) must be in the same directory as `main.py`

**Upload fails immediately:**
- Check credentials in `Tools > Set Credentials`
- Verify API key is correct for imx.to
- Check execution log: `View > Execution Log`

**Python dependencies error:**
- Ensure all requirements are installed: `pip install -r requirements.txt`
- Try recreating the virtual environment

**Build errors:**
- Ensure Python 3.11+ and Go 1.24.11+ are installed
- Check internet connection for dependency downloads
- Run `go mod download` to fetch dependencies

### Logs
- Runtime logs: `View > Execution Log` in the application
- Crash logs: `crash_log.log` in the application directory

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

**conniecombs** - [GitHub](https://github.com/conniecombs)

## Acknowledgments

- Built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- Go HTML parsing with [goquery](https://github.com/PuerkitoBio/goquery)
- Logging with [loguru](https://github.com/Delgan/loguru)

## Version History

**Latest Release: v1.0.0** - First Official Production Release
- 🎉 Comprehensive CI/CD automation
- 🔒 13 security vulnerabilities fixed (Go 1.24.11 + dependency updates)
- ✅ Cross-platform builds with automated testing
- 📦 Automated release pipeline with SHA256 checksums
- 🛡️ Daily security scanning with multiple tools

See [CHANGELOG.md](CHANGELOG.md) for detailed version history and [Releases](https://github.com/conniecombs/GolangVersion/releases) for downloads.

---

**Note**: This tool is intended for personal use and legitimate content sharing. Users are responsible for complying with the terms of service of all image hosting platforms used.
