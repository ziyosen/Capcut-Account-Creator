

import re
import time
import random
import string

import requests

API_BASE = "https://api.mail.tm"


class MailTmError(Exception):
    """Error khusus untuk kegagalan komunikasi dengan API mail.tm."""
    pass


class MailTmClient:
    def __init__(self, timeout=15, max_retries=3):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.timeout = timeout
        self.max_retries = max_retries
        self.address = None
        self.password = None
        self.token = None
        self.account_id = None

    # --- INTERNAL REQUEST DENGAN RETRY (handle rate limit 429) ---
    def _request(self, method, path, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        url = f"{API_BASE}{path}"
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 429:  # rate limited
                    wait = 3 * attempt
                    print(f"⚠️  mail.tm rate limit, retry {attempt}/{self.max_retries} dalam {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    raise MailTmError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
                return resp.json() if resp.content else {}
            except requests.RequestException as e:
                last_error = e
                wait = 2 * attempt
                print(f"⚠️  Koneksi mail.tm gagal ({e}), retry {attempt}/{self.max_retries}...")
                time.sleep(wait)
        raise MailTmError(f"Gagal request {method} {path}: {last_error or 'rate limit'}")

    @staticmethod
    def _collection(data):
        """Normalize response: bisa plain JSON array atau hydra:member (JSON-LD)."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("hydra:member", [])
        return []

    # --- 1. AMBIL DOMAIN AKTIF ---
    def get_domain(self):
        data = self._request("GET", "/domains")
        domains = [d["domain"] for d in self._collection(data) if d.get("isActive")]
        if not domains:
            raise MailTmError("Tidak ada domain aktif di mail.tm")
        return domains[0]

    # --- 2. BUAT AKUN EMAIL ACAK ---
    def create_account(self):
        domain = self.get_domain()
        username = "cc" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self.address = f"{username}@{domain}"
        self.password = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        data = self._request(
            "POST", "/accounts",
            json={"address": self.address, "password": self.password},
        )
        self.account_id = data.get("id")
        return self.address

    # --- 3. DAPATKAN BEARER TOKEN (sesuai docs: POST /token) ---
    def authenticate(self):
        if not self.address or not self.password:
            raise MailTmError("Buat akun dulu sebelum autentikasi")
        data = self._request(
            "POST", "/token",
            json={"address": self.address, "password": self.password},
        )
        self.token = data.get("token")
        if not self.token:
            raise MailTmError("Token tidak diterima dari mail.tm")
        # Dipakai sebagai "Authorization: Bearer TOKEN" di setiap request berikutnya
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        return self.token

    # --- 4. LIST PESAN MASUK ---
    def list_messages(self):
        data = self._request("GET", "/messages")
        return self._collection(data)

    # --- 5. BACA DETAIL SATU PESAN ---
    def get_message(self, message_id):
        return self._request("GET", f"/messages/{message_id}")

    def _extract_otp(self, message, pattern):
        """Cari kode OTP di intro/text/html pesan."""
        haystacks = [message.get("intro") or "", message.get("text") or ""]
        html = message.get("html") or []
        if isinstance(html, list):
            haystacks.extend(str(h) for h in html)
        else:
            haystacks.append(str(html))
        for hay in haystacks:
            m = re.search(pattern, hay)
            if m:
                return m.group(1)
        return None

    # --- POLLING INBOX SAMPAI OTP MASUK ---
    def wait_for_otp(self, pattern=r"\b(\d{6})\b", timeout=120, interval=5):
        """
        Poll inbox sampai ada email yang mengandung kode OTP (default: 6 digit).
        Return kode OTP (string) atau None jika timeout.
        """
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                messages = self.list_messages()
            except MailTmError as e:
                print(f"⚠️  Gagal cek inbox: {e}")
                messages = []
            for msg in messages:
                try:
                    full = self.get_message(msg["id"])
                except MailTmError as e:
                    print(f"⚠️  Gagal baca pesan: {e}")
                    continue
                otp = self._extract_otp(full, pattern)
                if otp:
                    return otp
            remaining = int(deadline - time.time())
            if remaining > 0:
                print(f"⏳ Menunggu OTP... (cek ke-{attempt}, sisa {remaining}s)")
                time.sleep(min(interval, remaining))
        return None


def create_temp_email():
    """
    Helper singkat: buat akun mail.tm baru + autentikasi.
    Return (client, email_address).
    """
    client = MailTmClient()
    email = client.create_account()
    client.authenticate()
    return client, email


if __name__ == "__main__":
    # Tes manual: python mailtm.py
    client, email = create_temp_email()
    print(f"✅ Email dibuat: {email}")
    print(f"🔑 Password    : {client.password}")
    print(f"🎟️  Token       : {client.token[:30]}...")
    print("📬 Inbox:")
    for m in client.list_messages():
        print(f"  - {m.get('from', {}).get('address')}: {m.get('subject')}")
