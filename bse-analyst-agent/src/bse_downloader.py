import os
import requests
from typing import Optional

class BSEDownloader:
    BASE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    BASE_ATTACHMENT_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bseindia.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, download_dir: str = "./data/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def get_latest_annual_report_url(self, scrip_code: str) -> Optional[str]:
        """Queries BSE Corporate Announcement feeds for the latest Annual Report filing."""
        params = {
            "scripcode": scrip_code,
            "strCat": "Annual Report",
            "strPrevDate": "",
            "strType": "C"
        }
        try:
            response = requests.get(self.BASE_API, headers=self.HEADERS, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            table = data.get("Table", [])
            if not table:
                print(f"[!] No filings found under 'Annual Report' for scrip {scrip_code}.")
                return None
            
            # The most recent filing is typically the first record
            latest_record = table[0]
            attachment_file = latest_record.get("ATTACHMENTNAME")
            if attachment_file:
                # BSE links file names to the AttachHis distribution path
                return f"{self.BASE_ATTACHMENT_URL}{attachment_file}"
        except Exception as e:
            print(f"[x] Error querying BSE API: {e}")
            return None

    def download_report(self, scrip_code: str, custom_filename: Optional[str] = None) -> Optional[str]:
        pdf_url = self.get_latest_annual_report_url(scrip_code)
        if not pdf_url:
            return None
        
        target_path = os.path.join(
            self.download_dir, 
            custom_filename or f"{scrip_code}_latest_annual_report.pdf"
        )
        
        print(f"[*] Downloading annual report from: {pdf_url}")
        res = requests.get(pdf_url, headers=self.HEADERS, stream=True, timeout=60)
        res.raise_for_status()
        
        with open(target_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    
        print(f"[+] Download complete: {target_path}")
        return target_path