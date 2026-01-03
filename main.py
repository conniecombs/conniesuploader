"""Connie's Uploader Ultimate - Main Entry Point

Refactored lightweight entry point that delegates to modular UI components.
Previously a monolithic 1,078-line file, now properly organized.
"""

import customtkinter as ctk
from modules.ui import UploaderApp


def main():
    """Main entry point for the application."""
    # Set appearance and theme before creating app
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    # Create and run the application
    app = UploaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
