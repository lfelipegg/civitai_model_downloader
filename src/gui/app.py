"""
Main application window for the Civitai Model Downloader.
"""

import customtkinter as ctk

from src.gui.download_tab import DownloadTab
from src.gui.history_tab import HistoryTab
from src.services.downloader_service import DownloaderService
from src.services.url_service import UrlService
from src.services.history_service import HistoryService


class App(ctk.CTk):
    """Main application window class."""

    def __init__(self):
        super().__init__()

        self.title("Civitai Model Downloader")
        self.geometry("900x900")

        self.notebook = ctk.CTkTabview(self)
        self.notebook.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        download_frame = self.notebook.add("Downloads")
        history_frame = self.notebook.add("History")

        self.history_service = HistoryService()
        self.download_tab = DownloadTab(
            self,
            download_frame,
            downloader_service=DownloaderService(),
            url_service=UrlService(),
        )
        self.history_tab = HistoryTab(
            self,
            history_frame,
            history_service=self.history_service,
            download_path_getter=self.download_tab.get_download_path,
        )

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        self.download_tab._on_closing()
