Here is a full GitHub README.md file for your Python program.

-----

# Connie's Uploader (v0.9.6)

A multi-threaded Python GUI application for batch uploading images to `imx.to` and `pixhost.to`. This tool is built with Tkinter and provides per-file progress, retry functionality, and automatic output generation in multiple formats.

## 📋 Features

  * **Batch Uploading**: Select individual files or an entire folder (scanned recursively).
  * **Multi-threaded**: Upload multiple images concurrently with a configurable number of threads.
  * **Supported Hosts**:
      * `imx.to` (with API Key)
      * `pixhost.to`
  * **Detailed Progress**: An overall progress bar and individual progress bars for each file.
  * **Error Handling**: Failed uploads are clearly marked (❌) and can be retried individually.
  * **Output Generation**: Automatically creates `upload_results.txt` with formatted links.
  * **Multiple Formats**: Supports **BBCode**, **Markdown**, and **HTML** output.
  * **Convenience Tools**:
      * "Copy Output" button to copy links to the clipboard.
      * "Open Output File" button to open the results file.
  * **Secure Storage**: Uses the system's `keyring` (like Windows Credential Manager or macOS Keychain) to securely store your `imx.to` API key.
  * **Settings File**: Saves your preferences (thumbnail size, threads, etc.) to a `settings.json` file.
  * **Cross-Platform**: Built with Python and Tkinter, making it compatible with Windows, macOS, and Linux.

## 🚀 Installation

Follow these steps to get the application running on your local machine.

### 1\. Prerequisites

  * **Python 3.6+**: Ensure you have Python installed. You can download it from [python.org](https://www.python.org/).
  * **Tkinter**: This is included with Python on Windows and macOS. On Linux, you may need to install it separately:
    ```bash
    # For Debian/Ubuntu-based systems
    sudo apt-get install python3-tk
    ```

### 2\. Get the Code

You can either download the `uploader0.9.7.py` file directly or clone this repository:

```bash
git clone https://github.com/your-username/connies-uploader.git
cd connies-uploader
```

### 3\. Install Dependencies

This script relies on several third-party Python packages. You can install them all using `pip`:

```bash
pip install requests requests-toolbelt ttkthemes keyring pyperclip
```

### 4\. Run the Application

Once the dependencies are installed, you can run the application from your terminal:

```bash
python uploader0.9.7.py
```

-----

## 💡 How to Use

1.  **Launch the App**: Run the script as shown in the installation instructions.
2.  **Configure Service**:
      * Click the `imx.to` or `pixhost.to` tab in the "Settings" pane.
      * **For imx.to**: Enter your API key. It will be securely saved in your system's keyring for future use.
      * **For pixhost.to**: No API key is required.
      * Adjust options like **Thumbnail Size** or **Content Type** to your preference.
3.  **Configure General Settings**:
      * Set the number of **Threads** (e.g., `4`) for concurrent uploads.
      * Choose your desired **Output Format** (BBCode, Markdown, or HTML).
4.  **Add Files**:
      * Click **Select Files** to add one or more images.
      * Click **Select Folder** to scan an entire directory (and its subdirectories) for supported image files (`.jpg`, `.png`, `.gif`, etc.).
5.  **Start Upload**:
      * Click the **Start Upload** button.
      * You will see the per-file status icons change from ⏳ (pending) to ⬆️ (uploading), and finally to ✅ (success) or ❌ (failed).
      * The overall progress bar at the bottom will track the entire batch.
6.  **Get Output**:
      * When the upload is complete, the app automatically generates an `upload_results.txt` file in the same directory.
      * Click **Copy Output** to copy the formatted text directly to your clipboard.
      * Click **Open Output File** to view `upload_results.txt` in your default text editor.

-----

## 🔧 Configuration

  * **`settings.json`**: This file is created automatically to save your non-sensitive preferences, such as thumbnail size, thread count, and window layout.
  * **API Key (Keyring)**: Your `imx.to` API key is **not** stored in `settings.json`. It is securely stored in your operating system's native credential manager (like Windows Credential Manager, macOS Keychain, or Linux Secret Service) for maximum security.

## 📦 Dependencies

This project is built using the following Python libraries:

  * `requests` (for making HTTP requests)
  * `requests-toolbelt` (for the upload monitor and progress)
  * `ttkthemes` (for the "arc" theme and styling)
  * `keyring` (for secure credential storage)
  * `pyperclip` (for "Copy to Clipboard" functionality)

## ⚖️ License

This project is licensed under the MIT License.
