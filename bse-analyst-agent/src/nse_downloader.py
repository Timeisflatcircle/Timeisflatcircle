"""
src/nse_downloader.py
Automated downloader for Indian Annual Reports via NSE India API.
Includes local file caching to skip re-downloading existing files.
"""

import os
import requests
from typing import Optional

class NSEDownloader:
    BASE_HOME = "https://www.nseindia.com"
    API_URL = "https://www.nseindia.com/api/annual-reports"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, download_dir: str = "./data/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._session_initialized = False

    def _init_session(self):
        """Visits NSE homepage to initialize required cookies and session state."""
        try:
            resp = self.session.get(self.BASE_HOME, timeout=15)
            resp.raise_for_status()
            self._session_initialized = True
        except Exception as e:
            print(f"[!] Warning: Could not initialize NSE session cookies: {e}")

    def get_latest_annual_report_url(self, symbol: str) -> Optional[str]:
        """
        Fetches the download URL for the latest annual report for a given NSE ticker.
        e.g., symbol='TCS', 'INFY', 'RELIANCE'
        """
        if not self._session_initialized:
            self._init_session()

        params = {
            "index": "equities",
            "symbol": symbol.upper().strip()
        }
        
        api_headers = {
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports",
            "Accept": "application/json, text/plain, */*"
        }

        try:
            res = self.session.get(self.API_URL, params=params, headers=api_headers, timeout=15)
            if res.status_code in (401, 403):
                self._init_session()
                res = self.session.get(self.API_URL, params=params, headers=api_headers, timeout=15)

            res.raise_for_status()
            data = res.json()
            
            items = data.get("data", [])
            if not items:
                print(f"[!] No annual reports found on NSE for symbol '{symbol}'.")
                return None
            
            latest = items[0]
            file_url = latest.get("fileName")
            if file_url:
                print(f"[+] Found filing for {symbol} ({latest.get('companyName', '')}) - FY: {latest.get('finYear', 'N/A')}")
                return file_url
            
        except Exception as e:
            print(f"[x] Error querying NSE API: {e}")
            return None

    def download_report(self, symbol: str, custom_filename: Optional[str] = None, force_redownload: bool = False) -> Optional[str]:
        """
        Checks if the file is already downloaded. If yes and not empty, skips download.
        Set force_redownload=True if you need to refresh the filing.
        """
        target_filename = custom_filename or f"{symbol.upper()}_latest_annual_report.pdf"
        target_path = os.path.join(self.download_dir, target_filename)

        # 1. Skip download if local file exists and is valid (> 10 KB)
        if os.path.exists(target_path) and os.path.getsize(target_path) > 10 * 1024 and not force_redownload:
            print(f"[✓] File already exists: {target_path}")
            print(f"[*] Skipping download. Using cached report directly for analysis.")
            return target_path

        # 2. Otherwise fetch from NSE
        pdf_url = self.get_latest_annual_report_url(symbol)
        if not pdf_url:
            return None

        print(f"[*] Downloading PDF from: {pdf_url}")
        
        # Use temp file to avoid corrupt/partial writes breaking subsequent runs
        temp_path = f"{target_path}.tmp"
        res = self.session.get(pdf_url, stream=True, timeout=90)
        res.raise_for_status()

        with open(temp_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        # Atomically rename/replace once download completes cleanly
        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(temp_path, target_path)

        print(f"[+] Successfully downloaded: {target_path}")
        return target_path