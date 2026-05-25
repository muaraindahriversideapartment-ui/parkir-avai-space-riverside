import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import os

# Matikan statistik telemetry
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

# --- 1. SETTINGAN HALAMAN ---
st.set_page_config(page_title="Monitor Parkir Riverside", page_icon="🚗", layout="wide")

st.title("🚗 Webapp Ketersediaan Lot Parkir Real-Time")
st.markdown("---")

# --- 2. FUNGSI KONEKSI DATABASE ---
def Ambil_Data_Sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    
    # KUNCI UTAMA: Ganti baca file jadi baca Streamlit Secrets TOML
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    client = gspread.authorize(creds)
    
    url_sheet = "https://docs.google.com/spreadsheets/d/1e7xfzEg4eq23Q9DKrFtpR3CPe6TZu6caf8VK_kySwMM/edit"
    spreadsheet = client.open_by_url(url_sheet)
    
    log_sheet = spreadsheet.worksheet("Log_Parkir")
    setting_sheet = spreadsheet.worksheet("Setting")
    
    return log_sheet, setting_sheet
try:
    log_sheet, setting_sheet = Ambil_Data_Sheets()
    st.sidebar.success("⚡ Database Connected!")
except Exception as e:
    st.error(f"❌ Gagal Koneksi: {e}")
    st.stop()

# --- 3. LOGIKA HITUNG SLOT AKURAT (PENGURANGAN & PENGEMBALIAN) ---
def hitung_ketersediaan_slot():
    # A. Ambil data kapasitas master dari tab Setting
    settings = setting_sheet.get_all_records()
    kapasitas_dict = {str(row['Area']).upper().strip(): int(row['Kapasitas']) for row in settings if row.get('Area')}
    
    # B. Ambil data log kendaraan
    raw_logs = log_sheet.get_all_values()
    if len(raw_logs) <= 1:
        # Jika log masih kosong, sisa slot = kapasitas awal
        status_parkir = [{"Area": area, "Total Kapasitas": kap, "Terisi": 0, "Sisa Slot": kap} for area, kap in kapasitas_dict.items()]
        return pd.DataFrame(status_parkir), pd.DataFrame()
        
    headers = [str(h).strip() for h in raw_logs[0]]
    rows = raw_logs[1:]
    df = pd.DataFrame(rows, columns=headers)
    
    # C. Data Cleaning super ketat (Mengatasi human error kolom selip/terbalik)
    if 'Status' in df.columns and 'Area' in df.columns:
        df['Status'] = df['Status'].astype(str).str.strip().str.upper()
        df['Area'] = df['Area'].astype(str).str.strip().str.upper()
        
        # Penanganan jika isi kolom Status dan Area tertukar secara tidak sengaja
        def fix_row(row):
            stat = row['Status']
            are = row['Area']
            if are in ['IN', 'OUT', 'MASUK']:
                return pd.Series([are, stat], index=['Status', 'Area'])
            return pd.Series([stat, are], index=['Status', 'Area'])
            
        df[['Status', 'Area']] = df.apply(fix_row, axis=1)
        
        # Seragamkan istilah status kendaraan
        df['Status'] = df['Status'].replace({'MASUK': 'IN', 'OUT': 'OUT'})
        
        # D. HITUNG REAL-TIME KENDARAAN AKTIF (IN belum ada OUT)
        # Kelompokkan berdasarkan Nopol untuk melihat status terakhir kendaraan tersebut
        terisi_dict = {area: 0 for area in kapasitas_dict.keys()}
        
        if 'Nopol' in df.columns:
            df['Nopol'] = df['Nopol'].astype(str).str.strip().str.upper()
            # Cari status paling terakhir/terbaru untuk setiap plat nomor
            df_sorted = df.copy()
            # Pastikan urutan log sesuai urutan input data
            df_sorted = df_sorted.reset_index()
            last_status = df_sorted.groupby('Nopol').last()
            
            # Kendaraan yang status terakhirnya masih 'IN' berarti masih parkir di dalam
            mobil_di_dalam = last_status[last_status['Status'] == 'IN']
            
            for index, row in mobil_di_dalam.iterrows():
                area_mobil = row['Area']
                if area_mobil in terisi_dict:
                    terisi_dict[area_mobil] += 1
    else:
        terisi_dict = {area: 0 for area in kapasitas_dict.keys()}
        
    # E. Gabungkan Kapasitas Master - Jumlah Kendaraan Aktif
    status_parkir = []
    for area, kapasitas in kapasitas_dict.items():
        terisi = terisi_dict.get(area, 0)
        sisa = kapasitas - terisi
        status_parkir.append({
            "Area": area,
            "Total Kapasitas": kapasitas,
            "Terisi": terisi,
            "Sisa Slot": max(0, sisa)
        })
        
    return pd.DataFrame(status_parkir), df

# Jalankan kalkulasi data
df_status, df_logs_raw = hitung_ketersediaan_slot()

# --- 4. MENU TAMPILAN WEBAPP ---
menu = st.sidebar.radio("Navigasi Menu", ["📊 Dashboard Monitor", "➕ Input Kendaraan"])

if menu == "📊 Dashboard Monitor":
    st.subheader("Status Ketersediaan Slot Saat Ini (Real-Time)")
    
    if not df_status.empty:
        # PENGATURAN LAYOUT: Kita batasi maksimal 3 kolom per baris agar kotak tidak gepeng vertikal
        max_kolom_per_baris = 3
        for i in range(0, len(df_status), max_kolom_per_baris):
            chunk = df_status.iloc[i:i+max_kolom_per_baris].reset_index(drop=True)
            cols = st.columns(max_kolom_per_baris)
            
            for index, row in chunk.iterrows():
                with cols[index]:
                    # Penentuan warna box berdasarkan sisa slot
                    if row['Sisa Slot'] == 0:
                        st.error(f"### {row['Area']}")
                        st.metric(label="SISA SLOT (PENUH)", value=row['Sisa Slot'], delta=f"Terisi: {row['Terisi']} / Total: {row['Total Kapasitas']}")
                    elif row['Sisa Slot'] <= 5:
                        st.warning(f"### {row['Area']}")
                        st.metric(label="SISA SLOT KRITIS", value=row['Sisa Slot'], delta=f"Terisi: {row['Terisi']} / Total: {row['Total Kapasitas']}")
                    else:
                        st.success(f"### {row['Area']}")
                        st.metric(label="SISA SLOT TERSEDIA", value=row['Sisa Slot'], delta=f"Terisi: {row['Terisi']} / Total: {row['Total Kapasitas']}", delta_color="inverse")
    else:
        st.info("Belum ada data area lokasi di tab Setting lo.")

    st.markdown("---")
    st.subheader("📋 10 Data Log Terakhir Langsung dari Google Sheets")
    if not df_logs_raw.empty:
        st.dataframe(df_logs_raw.tail(10), use_container_width=True)

elif menu == "➕ Input Kendaraan":
    st.subheader("Form Registrasi Masuk / Keluar Kendaraan")
    
    with st.form("form_parkir", clear_on_submit=True):
        plat_nomor = st.text_input("Nomor Polisi (Nopol)", "").strip().upper()
        
        pilihan_area = df_status['Area'].tolist() if not df_status.empty else ["P1 (T1)", "P2 (T2)"]
        area_pilihan = st.selectbox("Pilih Area Parkir", pilihan_area)
        status = st.selectbox("Status Kendaraan", ["IN", "OUT"])
        
        submit_btn = st.form_submit_button("Simpan ke Google Sheets")
        
        if submit_btn:
            if plat_nomor == "":
                st.error("Wajib isi nomor polisi kendaraan!")
            else:
                waktu_sekarang = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                
                # URUTAN KOLOM: Timestamp | Nopol | Status | Area
                row_baru = [waktu_sekarang, plat_nomor, status, area_pilihan]
                
                try:
                    log_sheet.append_row(row_baru)
                    st.success(f"✅ Berhasil mencatat {plat_nomor} [{status}] di area {area_pilihan}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal kirim data: {e}")
