import gspread
import json
import os
import logging
import threading
import time

logger = logging.getLogger(__name__)


class GSheetData:
    def __init__(self):
        self.gc = self._authenticate()
        self.url = os.environ.get(
            "GOOGLE_SPREADSHEET_URL",
            "https://docs.google.com/spreadsheets/d/1Q281_R_MrEhEIg1PpeXbYgXTakNjrkTFVDhuZbmdLJk/edit?usp=drive_link"
        )
        self.spreadsheet = self.gc.open_by_url(self.url)

        # Lock for thread-safe data access
        self._lock = threading.Lock()

        # Load all sheet data into memory
        self._load_all_data()

        # Start auto-refresh background thread (every 15 minutes)
        self._refresh_interval = 15 * 60  # 15 minutes in seconds
        self._refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
        self._refresh_thread.start()
        logger.info("Auto-refresh started (every 15 minutes).")

    # ─── AUTH ────────────────────────────────────────────────

    def _authenticate(self):
        creds_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
        if creds_str:
            tmp_path = "/tmp/service_account.json"
            with open(tmp_path, "w") as f:
                f.write(creds_str)
            return gspread.service_account(filename=tmp_path)
        else:
            return gspread.service_account()

    # ─── LOAD ALL DATA ──────────────────────────────────────

    def _load_all_data(self):
        """Load all sheets into memory (thread-safe)."""
        profile_rows = self._load_sheet("Profile")
        stock_rows, stock_months = self._load_monthly_sheet("Stock", sub_headers=["RDT", "ACT", "CQ", "PQ"])
        testing_rows, testing_months = self._load_monthly_sheet(
            "Testing", sub_headers=["Testing", "Pf", "Pv", "Mix", "NTG", "Refer"]
        )

        with self._lock:
            self.profile_rows = profile_rows
            self.stock_rows = stock_rows
            self.stock_months = stock_months
            self.testing_rows = testing_rows
            self.testing_months = testing_months

        logger.info(
            f"Loaded: Profile={len(profile_rows)}, "
            f"Stock={len(stock_rows)}, Testing={len(testing_rows)} rows"
        )

    # ─── AUTO REFRESH ───────────────────────────────────────

    def _auto_refresh_loop(self):
        """Background thread that reloads data every 15 minutes."""
        while True:
            time.sleep(self._refresh_interval)
            try:
                logger.info("Auto-refresh: reloading Google Sheet data...")
                # Re-authenticate in case token expired
                self.gc = self._authenticate()
                self.spreadsheet = self.gc.open_by_url(self.url)
                self._load_all_data()
                logger.info("Auto-refresh: data reloaded successfully.")
            except Exception as e:
                logger.error(f"Auto-refresh failed: {e}")

    # ─── LOAD SHEETS ────────────────────────────────────────

    def _load_sheet(self, sheet_name):
        """Load a simple sheet (Profile) with single header row."""
        ws = self.spreadsheet.worksheet(sheet_name)
        data = ws.get_all_values()
        if len(data) < 2:
            return []

        headers = [h.strip() for h in data[0]]
        rows = []
        for row in data[1:]:
            record = {}
            for i, h in enumerate(headers):
                record[h] = row[i].strip() if i < len(row) else ""
            rows.append(record)
        return rows

    def _load_monthly_sheet(self, sheet_name, sub_headers):
        """
        Load Stock / Testing sheets with 2-header-row structure.
        Row 0: Township, RHC, Sub-center, Village Name, January, (empty), (empty), (empty), February, ...
        Row 1: (empty), (empty), (empty), (empty), RDT, ACT, CQ, PQ, RDT, ACT, CQ, PQ, ...
        """
        ws = self.spreadsheet.worksheet(sheet_name)
        data = ws.get_all_values()
        if len(data) < 3:
            return [], {}

        header1 = data[0]  # Month names in row 0
        header2 = data[1]  # Sub-column names in row 1

        # Build column mapping: {(month, sub_header): col_index}
        month_map = {}
        current_month = ""
        months_list = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
            "Yearly Total"
        ]

        for col_idx in range(4, len(header1)):
            h1 = header1[col_idx].strip()
            h2 = header2[col_idx].strip() if col_idx < len(header2) else ""
            if h1 and h1 in months_list:
                current_month = h1
            if current_month and h2:
                month_map[(current_month, h2)] = col_idx

        rows = []
        for row in data[2:]:
            record = {
                "Township": row[0].strip() if len(row) > 0 else "",
                "RHC": row[1].strip() if len(row) > 1 else "",
                "Sub-center": row[2].strip() if len(row) > 2 else "",
                "Village Name": row[3].strip() if len(row) > 3 else "",
                "_raw": row,
            }
            rows.append(record)
        return rows, month_map

    # ─── GETTERS ─────────────────────────────────────────────

    def get_sheet_names(self):
        return ["Profile", "Stock", "Testing"]

    def _get_rows(self, sheet_name):
        with self._lock:
            if sheet_name == "Profile":
                return list(self.profile_rows)
            elif sheet_name == "Stock":
                return list(self.stock_rows)
            elif sheet_name == "Testing":
                return list(self.testing_rows)
        return []

    def get_townships(self, sheet_name):
        rows = self._get_rows(sheet_name)
        seen = set()
        result = []
        for r in rows:
            t = r.get("Township", "")
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def get_rhcs(self, sheet_name, township):
        rows = self._get_rows(sheet_name)
        seen = set()
        result = []
        for r in rows:
            if r.get("Township") == township:
                v = r.get("RHC", "")
                if v and v not in seen:
                    seen.add(v)
                    result.append(v)
        return result

    def get_subcenters(self, sheet_name, township, rhc):
        rows = self._get_rows(sheet_name)
        seen = set()
        result = []
        for r in rows:
            if r.get("Township") == township and r.get("RHC") == rhc:
                v = r.get("Sub-center", "")
                if v and v not in seen:
                    seen.add(v)
                    result.append(v)
        return result

    def get_villages(self, sheet_name, township, rhc, subcenter):
        rows = self._get_rows(sheet_name)
        seen = set()
        result = []
        for r in rows:
            if (r.get("Township") == township and
                r.get("RHC") == rhc and
                r.get("Sub-center") == subcenter):
                v = r.get("Village Name", "")
                if v and v not in seen:
                    seen.add(v)
                    result.append(v)
        return result

    def _find_row(self, rows, township, rhc, subcenter, village):
        for r in rows:
            if (r.get("Township") == township and
                r.get("RHC") == rhc and
                r.get("Sub-center") == subcenter and
                r.get("Village Name") == village):
                return r
        return None

    # ─── PROFILE DATA ───────────────────────────────────────

    def get_profile_data(self, township, rhc, subcenter, village):
        with self._lock:
            row = self._find_row(self.profile_rows, township, rhc, subcenter, village)
        if not row:
            return {}

        phone = row.get("Phone Contant", "") or row.get("Phone Contact", "")
        return {
            "Provider Name": row.get("Provider Name", "N/A"),
            "Phone Contact": phone if phone else "N/A",
            "HH": row.get("HH", "N/A") or "N/A",
            "Pop": row.get("Pop", "N/A") or "N/A",
            "Latitude": row.get("Latitude", "N/A") or "N/A",
            "Longitude": row.get("Longitude", "N/A") or "N/A",
        }

    # ─── STOCK DATA ──────────────────────────────────────────

    def get_stock_data(self, township, rhc, subcenter, village, month):
        with self._lock:
            row = self._find_row(self.stock_rows, township, rhc, subcenter, village)
            stock_months = dict(self.stock_months)
        if not row:
            return {}

        raw = row["_raw"]
        result = {}
        for sub in ["RDT", "ACT", "CQ", "PQ"]:
            col_idx = stock_months.get((month, sub))
            if col_idx is not None and col_idx < len(raw):
                val = raw[col_idx].strip()
                result[sub] = val if val else "-"
            else:
                result[sub] = "-"
        return result

    # ─── TESTING DATA ────────────────────────────────────────

    def get_testing_data(self, township, rhc, subcenter, village, month):
        with self._lock:
            row = self._find_row(self.testing_rows, township, rhc, subcenter, village)
            testing_months = dict(self.testing_months)
        if not row:
            return {}

        raw = row["_raw"]
        result = {}
        for sub in ["Testing", "Pf", "Pv", "Mix", "NTG", "Refer"]:
            col_idx = testing_months.get((month, sub))
            if col_idx is not None and col_idx < len(raw):
                val = raw[col_idx].strip()
                result[sub] = val if val else "-"
            else:
                result[sub] = "-"
        return result

    def get_testing_yearly_total(self, township, rhc, subcenter, village):
        with self._lock:
            row = self._find_row(self.testing_rows, township, rhc, subcenter, village)
            testing_months = dict(self.testing_months)
        if not row:
            return {}

        raw = row["_raw"]
        result = {}
        for sub in ["Testing", "Pf", "Pv", "Mix", "NTG", "Refer"]:
            col_idx = testing_months.get(("Yearly Total", sub))
            if col_idx is not None and col_idx < len(raw):
                val = raw[col_idx].strip()
                result[sub] = val if val else "-"
            else:
                result[sub] = "-"
        return result

    # ─── TOWNSHIP STOCK DASHBOARD ────────────────────────────

    def get_township_stock_totals(self, township):
        """
        Sum RDT/ACT/CQ/PQ for all villages in a township, grouped by month.
        Returns: (monthly_data dict, village_count)
        """
        with self._lock:
            rows = [r for r in self.stock_rows if r.get("Township") == township]
            stock_months = dict(self.stock_months)

        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        subs = ["RDT", "ACT", "CQ", "PQ"]
        result = {}

        for month in months:
            totals = {s: 0 for s in subs}
            has_data = False
            for r in rows:
                raw = r["_raw"]
                for sub in subs:
                    col_idx = stock_months.get((month, sub))
                    if col_idx is not None and col_idx < len(raw):
                        val = raw[col_idx].strip()
                        if val:
                            try:
                                totals[sub] += int(val)
                                has_data = True
                            except ValueError:
                                pass
            if has_data:
                result[month] = totals

        return result, len(rows)

    # ─── TOWNSHIP TEAM TESTING DASHBOARD ─────────────────────

    def get_township_testing_totals(self, township):
        """
        Sum Testing/Pf/Pv/Mix/NTG/Refer for all villages in a township, grouped by month.
        Returns: (monthly_data dict, yearly_totals or None, village_count)
        """
        with self._lock:
            rows = [r for r in self.testing_rows if r.get("Township") == township]
            testing_months = dict(self.testing_months)

        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        subs = ["Testing", "Pf", "Pv", "Mix", "NTG", "Refer"]
        result = {}

        for month in months:
            totals = {s: 0 for s in subs}
            has_data = False
            for r in rows:
                raw = r["_raw"]
                for sub in subs:
                    col_idx = testing_months.get((month, sub))
                    if col_idx is not None and col_idx < len(raw):
                        val = raw[col_idx].strip()
                        if val:
                            try:
                                totals[sub] += int(val)
                                has_data = True
                            except ValueError:
                                pass
            if has_data:
                result[month] = totals

        # Yearly Total
        yearly_totals = {s: 0 for s in subs}
        yearly_has = False
        for r in rows:
            raw = r["_raw"]
            for sub in subs:
                col_idx = testing_months.get(("Yearly Total", sub))
                if col_idx is not None and col_idx < len(raw):
                    val = raw[col_idx].strip()
                    if val:
                        try:
                            yearly_totals[sub] += int(val)
                            yearly_has = True
                        except ValueError:
                            pass

        return result, yearly_totals if yearly_has else None, len(rows)
