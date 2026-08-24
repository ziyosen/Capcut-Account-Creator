import os
import random
import time
import json
import string
import datetime
import argparse
import sys
from playwright.sync_api import sync_playwright
from mailtm import create_temp_email, MailTmError

LINKWEB = "https://www.capcut.com/signup"

# --- HELPER FUNCTIONS (Sama seperti sebelumnya) ---
def get_first_and_remove(filename):
    if not os.path.exists(filename):
        print(f"❌ ERROR: File {filename} tidak ditemukan!")
        return None
    with open(filename, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        print(f"⚠️  INFO: File {filename} sudah kosong!")
        return None
    target_data = lines[0]
    remaining_data = lines[1:]
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(remaining_data))
        if remaining_data:
            f.write('\n')
    return target_data

def generate_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#"
    return ''.join(random.choice(chars) for _ in range(length))

def birthDay_generator():
    day = random.randint(1, 28)
    month = random.randint(1, 12)
    year = random.randint(1980, 2004)
    return f"{day:02d}/{month:02d}/{year}"

def get_month_name(month_num):
    months = {
        "01": "Januari", "02": "Februari", "03": "Maret", "04": "April",
        "05": "Mei", "06": "Juni", "07": "Juli", "08": "Agustus",
        "09": "September", "10": "Oktober", "11": "November", "12": "Desember"
    }
    return months.get(month_num, month_num)

def save_to_json(data, filename="proof.json"):
    existing_data = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = []
    existing_data.append(data)
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
    print(f"💾 Data disimpan ke {filename}")

# --- CORE LOGIC ---
def create_single_account(headless_mode=False, auto_email=False):
    """Fungsi inti untuk membuat 1 akun."""

    mail_client = None

    if auto_email:
        # Mode auto: buat temp email baru via mail.tm API
        try:
            mail_client, gmail = create_temp_email()
            print(f"📧 Auto email (mail.tm): {gmail}")
        except MailTmError as e:
            print(f"❌ Gagal membuat email mail.tm: {e}")
            return False
    else:
        # Mode manual: ambil email dari gmail-list.txt, kalau habis langsung return False biar loop berhenti
        gmail = get_first_and_remove("gmail-list.txt")
        if not gmail:
            print("❌ Stok email habis.")
            return False

    password = generate_password()
    birthday = birthDay_generator()
    day, month, year = birthday.split('/')
    day = str(int(day))
    month_name = get_month_name(month)

    print(f"\n🔹 Memproses: {gmail}")

    with sync_playwright() as p:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--start-maximized",
        ]

        # Gunakan parameter headless dari CLI
        browser = p.chromium.launch(headless=headless_mode, args=args, channel="chrome")

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = context.new_page()

        try:
            page.goto(LINKWEB)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            # --- LOGIKA FILL FORM (flow UI terbaru) ---
            # 1. Pilih daftar dengan alamat email
            page.get_by_text("Lanjutkan dengan alamat email").click()
            page.wait_for_timeout(1000)

            # 2. Input email, lalu klik Lanjutkan
            page.get_by_role("textbox", name="Masukkan alamat email").fill(gmail)
            page.get_by_role("button", name="Lanjutkan", exact=True).click()
            page.wait_for_timeout(1500)

            # 3. Input password, lalu klik Daftar
            page.get_by_role("textbox", name="Masukkan kata sandi").fill(password)
            page.locator("div.lv_sign_in_panel_wide-form").get_by_text("Daftar", exact=True).click()
            page.wait_for_timeout(1500)

            # 4. Input tanggal lahir
            page.get_by_role("textbox", name="Tahun").fill(year)
            page.wait_for_timeout(500)
            page.get_by_text("Bulan", exact=True).click()
            page.get_by_role("option", name=month_name).click()
            page.wait_for_timeout(500)
            page.get_by_text("Hari", exact=True).click()
            page.get_by_role("option", name=day, exact=True).click()

            # 5. Lanjut ke halaman verifikasi kode (OTP)
            # Klik button "Lanjutkan" DI DALAM wrapper, bukan wrapper-nya
            page.locator("div.lv_sign_in_panel_wide-enter-code-wrapper").get_by_text("Lanjutkan", exact=True).click()

            # --- OTP SECTION ---
            print(f"\n📬 OTP dikirim ke {gmail}")

            kode_otp = None
            if mail_client:
                # Mode auto: polling inbox mail.tm sampai OTP masuk
                print("🤖 Mengambil OTP otomatis dari mail.tm...")
                kode_otp = mail_client.wait_for_otp(timeout=120, interval=5)
                if kode_otp:
                    print(f"🔑 OTP diterima otomatis: {kode_otp}")
                else:
                    print("⚠️  OTP tidak masuk dalam 120 detik.")

            if not kode_otp:
                # Mode manual (atau fallback auto): input OTP via CLI
                print("👉 Masukkan OTP di bawah ini:")
                kode_otp = input("🔑 OTP > ")

            # 6. Input kode OTP (klik box kode lalu ketik)
            page.locator("div.verification_code_input-number").first.click()
            page.keyboard.type(kode_otp, delay=100)

            # Setelah OTP benar, otomatis lanjut ke page berikutnya
            page.get_by_text("Buka CapCut").wait_for(state="visible", timeout=30000)

            # --- VERIFIKASI AKUN via API user_info ---
            user_info = {"data": None}

            def _on_response(response):
                if "commerce/v1/subscription/user_info" in response.url and response.request.method == "POST":
                    try:
                        user_info["data"] = response.json()
                    except Exception:
                        pass

            context.on("response", _on_response)

            # 7. Klik "Buka CapCut"
            page.get_by_text("Buka CapCut").click()

            # Tunggu response user_info (maks 30 detik)
            deadline = time.time() + 30
            while time.time() < deadline and user_info["data"] is None:
                page.wait_for_timeout(500)

            data = user_info["data"]
            if not data:
                raise Exception("Verifikasi gagal: response user_info tidak diterima")
            if str(data.get("ret")) != "0" or data.get("errmsg") != "success":
                raise Exception(f"Verifikasi gagal: ret={data.get('ret')} errmsg={data.get('errmsg')}")

            uid = (data.get("data") or {}).get("uid")
            print(f"🪪  Verifikasi sukses. UID: {uid}")

            # Save Data
            account_data = {
                "email": gmail,
                "password": password,
                "birthday": birthday,
                "uid": uid,
                "verified": True,
                "created_at": datetime.datetime.now().isoformat()
            }
            save_to_json(account_data)
            print(f"✅ SUKSES: {gmail}\n")
            return True

        except Exception as e:
            print(f"❌ GAGAL {gmail}: {e}")
            return None  # Akun ini gagal -> lanjut ke akun berikutnya

        finally:
            context.close()
            browser.close()

# --- ENTRY POINT UTAMA (CLI HANDLER) ---
def main():
    # 1. Definisi Argumen CLI
    parser = argparse.ArgumentParser(description="CapCut Auto Register CLI Tool")

    # Argumen Jumlah Akun (-n atau --number)
    parser.add_argument(
        '-n', '--number',
        type=int,
        default=1,
        help='Jumlah akun yang ingin dibuat (Default: 1)'
    )

    # Argumen Headless (--headless)
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Jalankan browser di background (tidak terlihat)'
    )

    # Argumen Auto Email (--auto)
    parser.add_argument(
        '--auto',
        action='store_true',
        help='Auto email via mail.tm (tidak perlu gmail-list.txt) + OTP otomatis'
    )

    # Parsing argumen
    args = parser.parse_args()

    print("="*50)
    print(f"🤖 CAPCUT BOT STARTED")
    print(f"🎯 Target: {args.number} Akun")
    print(f"👻 Mode Headless: {'ON' if args.headless else 'OFF'}")
    print(f"📧 Auto Email (mail.tm): {'ON' if args.auto else 'OFF'}")
    print("="*50)

    # 2. Loop sesuai jumlah permintaan
    sukses = 0
    for i in range(args.number):
        print(f"\n🔄 Proses Akun ke-{i+1} dari {args.number}")

        try:
            result = create_single_account(headless_mode=args.headless, auto_email=args.auto)
            if result is None:
                # Akun ini gagal, lanjut ke akun berikutnya
                continue
            if result:
                sukses += 1
            else:
                # Fatal: stok email habis / gagal buat email mail.tm
                print("⚠️ Proses dihentikan.")
                break
        except KeyboardInterrupt:
            print("\n\n🛑 Script dihentikan oleh User (Ctrl+C)")
            sys.exit(0)

    print("\n" + "="*50)
    print(f"🏁 SELESAI. Total Berhasil: {sukses}/{args.number}")
    print("="*50)

if __name__ == "__main__":
    main()