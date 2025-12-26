"""
Backward-compatible import for the main application window.
"""

from .app import App

__all__ = ["App"]


if __name__ == "__main__":
    app = App()
    app.mainloop()
