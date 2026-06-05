import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

# ====================== FUNGSI UTAMA ======================
def clean_currency_column(series):
    """
    Membersihkan kolom currency/mata uang menjadi numeric
    Menghandle: Rp 1.000.000, 1,000,000, 1.000.000, dll
    """
    if series.dtype in ['int64', 'float64']:
        return series
    
    # Konversi ke string
    series_str = series.astype(str)
    
    def clean_single_value(x):
        if pd.isna(x) or x == 'nan' or x == 'None' or x == '':
            return 0.0
        
        # Hapus karakter non-digit (selain titik dan koma)
        cleaned = str(x).strip()
        # Hapus semua huruf dan simbol (Rp, $, dll)
        cleaned = ''.join(c for c in cleaned if c.isdigit() or c in ['.', ',', '-'])
        
        if cleaned == '' or cleaned == '-':
            return 0.0
        
        # Handle negatif
        is_negative = cleaned.startswith('-')
        if is_negative:
            cleaned = cleaned[1:]
        
        # Ganti koma dengan titik (untuk desimal)
        cleaned = cleaned.replace(',', '.')
        
        # Hapus titik pemisah ribuan
        if cleaned.count('.') > 1:
            cleaned = cleaned.replace('.', '')
        elif cleaned.count('.') == 1:
            # Biarkan, itu adalah desimal
            pass
        
        try:
            value = float(cleaned)
            if is_negative:
                value = -value
            return value
        except:
            return 0.0
    
    return series_str.apply(clean_single_value)

def pad_npwp(npwp_series):
    """Tambahkan '0' di depan hingga panjang 16 digit"""
    npwp_str = npwp_series.astype(str).str.replace(r'\D+', '', regex=True)
    return npwp_str.str.zfill(16)

def validate_debitur(df):
    """Tambah kolom 'Valid' (True/False) berdasarkan NIK/No Identitas dan NPWP"""
    df = df.copy()
    
    # Bersihkan NIK dan No Identitas (hapus non-digit)
    nik_clean = df['NIK'].astype(str).str.replace(r'\D+', '', regex=True)
    no_id_clean = df['No Identitas'].astype(str).str.replace(r'\D+', '', regex=True)
    
    # Pad NPWP menjadi 16 digit
    npwp_clean = pad_npwp(df['NPWP'])
    npwp_deb_clean = pad_npwp(df['NPWP Debitur'])
    
    # Validasi: NIK == No Identitas ATAU NPWP == NPWP Debitur
    cond1 = (nik_clean == no_id_clean)
    cond2 = (npwp_clean == npwp_deb_clean)
    df['Valid'] = cond1 | cond2
    
    return df

def prepare_numeric_columns(df):
    """
    Siapkan kolom numeric untuk Plafon Awal, Plafon, dan O/S
    """
    df = df.copy()
    
    # Kolom yang perlu dibersihkan
    numeric_cols = ['Plafon Awal', 'Plafon', 'O/S']
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = clean_currency_column(df[col])
    
    return df

def recap_per_nasabah(df):
    """
    Langkah 2 & 3: Rekap per CIF yang memiliki Valid = True
    """
    # Filter hanya data yang valid
    valid_df = df[df['Valid'] == True].copy()
    
    if valid_df.empty:
        return pd.DataFrame()
    
    # Konversi kolom tanggal ke datetime
    date_cols = ['Tanggal Awal Kredit', 'Tanggal Kondisi', 'Tanggal Restrukturisasi Akhir']
    for col in date_cols:
        if col in valid_df.columns:
            valid_df[col] = pd.to_datetime(valid_df[col], errors='coerce')
    
    # Filter untuk kondisi "Fasilitas Aktif" (case insensitive)
    aktif_mask = valid_df['Kondisi'].astype(str).str.lower().str.strip() == 'fasilitas aktif'
    
    # Gunakan CIF sebagai key pengelompokan
    group_col = 'CIF'
    
    # Pastikan kolom CIF ada
    if group_col not in valid_df.columns:
        st.error(f"Kolom '{group_col}' tidak ditemukan dalam data!")
        return pd.DataFrame()
    
    results = []
    
    for cif, group in valid_df.groupby(group_col):
        # Data dengan kondisi aktif
        aktif_group = group[aktif_mask]
        
        # Ambil nama debitur (ambil nilai pertama dari grup untuk ditampilkan)
        nama_debitur = group['Nama Debitur'].iloc[0] if 'Nama Debitur' in group.columns else cif
        
        # ========== LANGKAH 2 ==========
        # a. Total Plafon Awal (kondisi aktif)
        total_plafon_awal = aktif_group['Plafon Awal'].sum() if not aktif_group.empty else 0
        
        # b. Total Plafon (kondisi aktif)
        total_plafon = aktif_group['Plafon'].sum() if not aktif_group.empty else 0
        
        # c. Total OS (kondisi aktif DAN fasilitas = modal kerja)
        # PERBAIKAN: Gunakan kolom "Fasilitas" bukan "Jenis Kredit"
        if 'Fasilitas' in aktif_group.columns:
            modal_kerja_mask = aktif_group['Fasilitas'].astype(str).str.lower().str.strip() == 'modal kerja'
            total_os = aktif_group.loc[modal_kerja_mask, 'O/S'].sum() if not aktif_group.empty else 0
        else:
            # Fallback jika kolom Fasilitas tidak ada (menggunakan Jenis Kredit)
            st.warning(f"Kolom 'Fasilitas' tidak ditemukan untuk CIF {cif}, menggunakan 'Jenis Kredit' sebagai fallback")
            modal_kerja_mask = aktif_group['Jenis Kredit'].astype(str).str.lower().str.strip() == 'modal kerja'
            total_os = aktif_group.loc[modal_kerja_mask, 'O/S'].sum() if not aktif_group.empty else 0
        
        # d. Pembiayaan terakhir (tanggal terbaru dari fasilitas aktif)
        if not aktif_group.empty:
            tgl_terakhir = aktif_group['Tanggal Awal Kredit'].max()
            pembiayaan_terakhir = tgl_terakhir.strftime('%Y-%m-%d') if pd.notna(tgl_terakhir) else None
        else:
            pembiayaan_terakhir = None
        
        # e. Total fasilitas aktif (jumlah baris dengan kondisi aktif)
        total_fasilitas_aktif = len(aktif_group) if not aktif_group.empty else 0
        
        # ========== LANGKAH 3 ==========
        # a. Kolektibilitas terburuk (dari fasilitas aktif)
        if not aktif_group.empty:
            kol_terburuk_series = aktif_group['Kolektibilitas Terburuk']
            # Konversi ke numeric jika memungkinkan
            try:
                kolektibilitas_terburuk = pd.to_numeric(kol_terburuk_series, errors='coerce').max()
            except:
                kolektibilitas_terburuk = kol_terburuk_series.max()
        else:
            kolektibilitas_terburuk = None
        
        # b. DPD terburuk (dari fasilitas aktif)
        dpd_terburuk = aktif_group['DPD'].max() if not aktif_group.empty else None
        
        # c. History restrukturisasi (tanggal terbaru dari seluruh data, tidak hanya aktif)
        tgl_restru = group['Tanggal Restrukturisasi Akhir'].dropna()
        history_restru = tgl_restru.max().strftime('%Y-%m-%d') if not tgl_restru.empty else None
        
        # d. Hapus buku (tanggal kondisi terbaru dengan status hapus buku)
        hapus_keywords = ['dihapusbukukan', 'hapus buku', 'hapus tagih']
        hapus_mask = group['Kondisi'].astype(str).str.lower().str.contains('|'.join(hapus_keywords), na=False)
        if hapus_mask.any():
            tgl_hapus = group.loc[hapus_mask, 'Tanggal Kondisi'].max()
            hapus_buku = tgl_hapus.strftime('%Y-%m-%d') if pd.notna(tgl_hapus) else None
        else:
            hapus_buku = None
        
        # Simpan hasil rekap untuk nasabah ini
        results.append({
            'CIF': cif,
            'Nama Debitur': nama_debitur,
            # Langkah 2
            'Total Plafon Awal (Fasilitas Aktif)': total_plafon_awal,
            'Total Plafon (Fasilitas Aktif)': total_plafon,
            'Total OS (Aktif & Fasilitas Modal Kerja)': total_os,
            'Pembiayaan Terakhir (Tgl Kredit Aktif Terbaru)': pembiayaan_terakhir,
            'Total Fasilitas Aktif': total_fasilitas_aktif,
            # Langkah 3
            'Kolektibilitas Terburuk (Fasilitas Aktif)': kolektibilitas_terburuk,
            'DPD Terburuk (Fasilitas Aktif)': dpd_terburuk,
            'History Restrukturisasi (Tgl Terbaru)': history_restru,
            'Hapus Buku (Tgl Kondisi Terbaru)': hapus_buku
        })
    
    return pd.DataFrame(results)

# ====================== ANTARMUKA STREAMLIT ======================
st.set_page_config(page_title="SLIK Validator & Recap", layout="wide")
st.title("📊 Validasi dan Rekapitulasi Data SLIK")
st.markdown("Upload file SLIK (Excel/CSV) - **untuk file Excel, akan membaca sheet 'Worksheet 1'**")

# Session state
if 'df_now' not in st.session_state:
    st.session_state.df_now = None
if 'recap_now' not in st.session_state:
    st.session_state.recap_now = pd.DataFrame()
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None

# Sidebar untuk upload file
with st.sidebar:
    st.header("📁 Upload File SLIK")
    file_now = st.file_uploader("File SLIK periode SEKARANG (wajib)", type=['xlsx', 'xls', 'csv'])
    if file_now is not None:
        try:
            # Baca file sesuai tipe
            if file_now.name.endswith('.csv'):
                df_raw = pd.read_csv(file_now)
            else:
                df_raw = pd.read_excel(file_now, sheet_name="Worksheet 1")
            
            # Kolom yang diperlukan
            required_cols = ['CIF', 'NIK', 'No Identitas', 'NPWP', 'NPWP Debitur', 'Kondisi', 'Fasilitas', 
                           'Plafon Awal', 'Plafon', 'O/S', 'Kolektibilitas Terburuk', 'DPD', 
                           'Tanggal Awal Kredit', 'Tanggal Kondisi', 'Tanggal Restrukturisasi Akhir']
            
            missing = [col for col in required_cols if col not in df_raw.columns]
            if missing:
                st.error(f"Kolom tidak ditemukan: {missing}")
                st.info(f"Kolom yang diperlukan: {', '.join(required_cols)}")
            else:
                # Simpan raw data untuk debugging
                st.session_state.raw_df = df_raw.copy()
                
                # Bersihkan kolom numeric
                df_cleaned = prepare_numeric_columns(df_raw)
                
                # Validasi debitur
                df_cleaned = validate_debitur(df_cleaned)
                
                # Rekap per CIF (Langkah 2 & 3)
                recap_now = recap_per_nasabah(df_cleaned)
                
                st.session_state.df_now = df_cleaned
                st.session_state.recap_now = recap_now
                st.success("✅ File berhasil diproses!")
                
        except Exception as e:
            st.error(f"Gagal membaca file: {e}")
            st.exception(e)

# ====================== TAB MENU ======================
tab1, tab2, tab3, tab4 = st.tabs(["📋 Langkah 1: Validasi Debitur", "📈 Langkah 2 & 3: Rekapitulasi (by CIF)", "🔍 Debug Info", "ℹ️ Informasi"])

with tab1:
    if st.session_state.df_now is not None:
        st.subheader("Data SLIK dengan Kolom Validasi")
        
        # Statistik validasi
        col1, col2 = st.columns(2)
        with col1:
            st.metric("✅ Data Valid (True)", f"{st.session_state.df_now['Valid'].sum():,}")
        with col2:
            st.metric("❌ Data Tidak Valid (False)", f"{(~st.session_state.df_now['Valid']).sum():,}")
        
        # Tampilkan data valid
        with st.expander("📋 Data Valid (Valid = True)", expanded=True):
            valid_data = st.session_state.df_now[st.session_state.df_now['Valid'] == True]
            show_cols = ['CIF', 'Nama Debitur', 'NIK', 'NPWP', 'No Identitas', 'NPWP Debitur', 'Valid', 'Kondisi', 'Fasilitas', 'Plafon Awal', 'Plafon', 'O/S']
            available = [c for c in show_cols if c in valid_data.columns]
            if len(valid_data) > 0:
                st.dataframe(valid_data[available], use_container_width=True)
                st.caption(f"Total baris valid: {len(valid_data)} | Unique CIF: {valid_data['CIF'].nunique()}")
            else:
                st.info("Tidak ada data valid")
        
        # Tampilkan data tidak valid
        with st.expander("⚠️ Data Tidak Valid (Valid = False)", expanded=False):
            invalid_data = st.session_state.df_now[st.session_state.df_now['Valid'] == False]
            show_cols = ['CIF', 'Nama Debitur', 'NIK', 'NPWP', 'No Identitas', 'NPWP Debitur', 'Valid', 'Kondisi', 'Fasilitas', 'Plafon Awal', 'Plafon', 'O/S']
            available = [c for c in show_cols if c in invalid_data.columns]
            if len(invalid_data) > 0:
                st.dataframe(invalid_data[available], use_container_width=True)
                st.caption(f"Total baris tidak valid: {len(invalid_data)} | Unique CIF: {invalid_data['CIF'].nunique()}")
            else:
                st.info("Tidak ada data tidak valid")
        
        # Tombol download
        st.subheader("📥 Download Data")
        col1, col2, col3 = st.columns(3)
        
        valid_data = st.session_state.df_now[st.session_state.df_now['Valid'] == True]
        invalid_data = st.session_state.df_now[st.session_state.df_now['Valid'] == False]
        
        with col1:
            if len(valid_data) > 0:
                csv_valid = valid_data.to_csv(index=False).encode('utf-8')
                st.download_button("✅ Download Data Valid (CSV)", csv_valid, "data_valid_slik.csv", "text/csv")
            else:
                st.button("✅ Download Data Valid", disabled=True, help="Tidak ada data valid")
        with col2:
            if len(invalid_data) > 0:
                csv_invalid = invalid_data.to_csv(index=False).encode('utf-8')
                st.download_button("❌ Download Data Tidak Valid (CSV)", csv_invalid, "data_tidak_valid_slik.csv", "text/csv")
            else:
                st.button("❌ Download Data Tidak Valid", disabled=True, help="Tidak ada data tidak valid")
        with col3:
            csv_all = st.session_state.df_now.to_csv(index=False).encode('utf-8')
            st.download_button("📊 Download Semua Data (CSV)", csv_all, "all_data_slik.csv", "text/csv")
        
    else:
        st.info("📁 Silakan upload file SLIK di sidebar kiri untuk memulai.")

with tab2:
    if not st.session_state.recap_now.empty:
        st.subheader("Rekapitulasi Data per CIF (Valid = True)")
        st.caption("📌 **Catatan:** Rekap dilakukan berdasarkan **CIF** yang tervalidasi True di Langkah 1")
        st.caption("- **Langkah 2:** Plafon Awal, Plafon, OS (kondisi aktif & fasilitas modal kerja), Pembiayaan terakhir, Total fasilitas aktif")
        st.caption("- **Langkah 3:** Kolektibilitas terburuk, DPD terburuk, History restrukturisasi, Hapus buku")
        
        # Format currency untuk tampilan
        display_df = st.session_state.recap_now.copy()
        currency_cols = ['Total Plafon Awal (Fasilitas Aktif)', 'Total Plafon (Fasilitas Aktif)', 'Total OS (Aktif & Fasilitas Modal Kerja)']
        for col in currency_cols:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(lambda x: f"Rp {x:,.2f}" if isinstance(x, (int, float)) and pd.notna(x) else "Rp 0")
        
        st.dataframe(display_df, use_container_width=True)
        
        # Statistik ringkasan
        st.subheader("📊 Statistik Ringkasan")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total CIF Valid", len(st.session_state.recap_now))
        
        with col2:
            if 'Total OS (Aktif & Fasilitas Modal Kerja)' in st.session_state.recap_now.columns:
                total_os = st.session_state.recap_now['Total OS (Aktif & Fasilitas Modal Kerja)'].sum()
                st.metric("Total O/S (Seluruh CIF)", f"Rp {total_os:,.2f}")
        
        with col3:
            if 'Total Fasilitas Aktif' in st.session_state.recap_now.columns:
                total_fasilitas = st.session_state.recap_now['Total Fasilitas Aktif'].sum()
                st.metric("Total Fasilitas Aktif", f"{total_fasilitas:,}")
        
        with col4:
            if 'History Restrukturisasi (Tgl Terbaru)' in st.session_state.recap_now.columns:
                nasabah_restru = st.session_state.recap_now['History Restrukturisasi (Tgl Terbaru)'].notna().sum()
                st.metric("CIF dengan Restrukturisasi", nasabah_restru)
        
        # Download rekap
        st.subheader("📥 Download Rekapitulasi")
        csv_recap = st.session_state.recap_now.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Rekap per CIF (CSV)", csv_recap, "recap_slik_per_cif.csv", "text/csv")
        
        # Tampilkan detail per CIF
        with st.expander("🔍 Detail per CIF"):
            selected_cif = st.selectbox("Pilih CIF:", st.session_state.recap_now['CIF'].tolist())
            if selected_cif:
                detail = st.session_state.recap_now[st.session_state.recap_now['CIF'] == selected_cif].iloc[0]
                st.json(detail.to_dict())
        
    else:
        if st.session_state.df_now is not None:
            st.warning("⚠️ Tidak ada data yang valid (semua baris memiliki Valid = False).")
            st.info("Pastikan data memenuhi kriteria: NIK == No Identitas ATAU NPWP (16 digit) == NPWP Debitur (16 digit)")
        else:
            st.info("📁 Silakan upload file SLIK terlebih dahulu di sidebar.")

with tab3:
    if st.session_state.raw_df is not None:
        st.subheader("Informasi Debug - Cek Tipe Data")
        
        # Tampilkan informasi tipe data sebelum cleaning
        st.markdown("### **📊 Sebelum Cleaning**")
        st.write(f"Total baris: {len(st.session_state.raw_df)}")
        st.write(f"Unique CIF: {st.session_state.raw_df['CIF'].nunique()}")
        
        important_cols = ['CIF', 'Plafon Awal', 'Plafon', 'O/S', 'Fasilitas', 'Kondisi']
        available_cols = [col for col in important_cols if col in st.session_state.raw_df.columns]
        
        for col in available_cols:
            st.write(f"**{col}**")
            st.write(f"- Tipe data: {st.session_state.raw_df[col].dtype}")
            sample_val = st.session_state.raw_df[col].iloc[0] if len(st.session_state.raw_df) > 0 else 'N/A'
            st.write(f"- Sample value: {sample_val}")
            if st.session_state.raw_df[col].dtype == 'object':
                # Tampilkan beberapa unique value
                unique_vals = st.session_state.raw_df[col].dropna().unique()[:5]
                st.write(f"- Sample unique values: {list(unique_vals)}")
            st.write("---")
        
        st.markdown("### **✨ Setelah Cleaning**")
        
        for col in available_cols:
            if col in st.session_state.df_now.columns:
                st.write(f"**{col}**")
                st.write(f"- Tipe data: {st.session_state.df_now[col].dtype}")
                sample_val = st.session_state.df_now[col].iloc[0] if len(st.session_state.df_now) > 0 else 'N/A'
                st.write(f"- Sample value: {sample_val}")
                
                # Cek tipe data sebelum formatting
                if col in ['Plafon Awal', 'Plafon', 'O/S']:
                    col_sum = st.session_state.df_now[col].sum()
                    if isinstance(col_sum, (int, float)):
                        st.write(f"- Sum: {col_sum:,.2f}")
                    else:
                        st.write(f"- Sum: {col_sum}")
                st.write("---")
        
        # Tampilkan sample data
        with st.expander("📋 Sample Data (10 baris pertama) - Setelah Cleaning"):
            sample_cols = ['CIF', 'Nama Debitur', 'Kondisi', 'Fasilitas', 'Plafon Awal', 'Plafon', 'O/S', 'Valid']
            available_sample = [c for c in sample_cols if c in st.session_state.df_now.columns]
            if available_sample:
                st.dataframe(st.session_state.df_now[available_sample].head(10))
            else:
                st.info("Tidak ada kolom yang tersedia untuk ditampilkan")
    else:
        st.info("Upload file terlebih dahulu untuk melihat informasi debug.")

with tab4:
    st.subheader("ℹ️ Penjelasan Kriteria dan Proses")
    
    st.markdown("""
    ### **Langkah 1 – Validasi Debitur**
    
    Kolom `Valid` akan bernilai **True** jika memenuhi salah satu kondisi:
    - **NIK** == **No Identitas** (setelah dibersihkan dari karakter non-digit)
    - **ATAU** **NPWP** (setelah di-padding menjadi 16 digit) == **NPWP Debitur** (setelah di-padding menjadi 16 digit)
    
    > **Padding NPWP:** NPWP asli akan ditambahkan angka '0' di depan hingga mencapai 16 digit.  
    > Contoh: `123456789012345` → `0123456789012345`
    
    ### **Langkah 2 – Rekapitulasi per CIF (Valid = True)**
    
    Perhitungan dilakukan **per CIF** (hanya untuk CIF yang memiliki Valid = True):
    
    | Metrik | Syarat |
    |--------|--------|
    | **Total Plafon Awal** | Kondisi = "Fasilitas Aktif" |
    | **Total Plafon** | Kondisi = "Fasilitas Aktif" |
    | **Total O/S** | Kondisi = "Fasilitas Aktif" **DAN** Fasilitas = "Modal Kerja" |
    | **Pembiayaan Terakhir** | Tanggal Awal Kredit terbaru dari fasilitas aktif |
    | **Total Fasilitas Aktif** | Jumlah baris dengan Kondisi = "Fasilitas Aktif" |
    
    ### **Langkah 3 – Rekapitulasi Lanjutan (per CIF Valid)**
    
    | Metrik | Syarat / Keterangan |
    |--------|---------------------|
    | **Kolektibilitas Terburuk** | Nilai tertinggi dari fasilitas aktif |
    | **DPD Terburuk** | Nilai tertinggi dari fasilitas aktif |
    | **History Restrukturisasi** | Tanggal terbaru dari kolom Tanggal Restrukturisasi Akhir |
    | **Hapus Buku** | Tanggal kondisi terbaru dengan kata: "dihapusbukukan", "hapus buku", "hapus tagih" |
    
    ### **Kriteria Perhitungan OS (Outstanding)**
    
    **Sumber data:** Kolom `O/S`
    
    **Filter yang diterapkan:**
    1. `Kondisi` = "Fasilitas Aktif"
    2. `Fasilitas` = "Modal Kerja"
    
    > **Catatan Penting:** OS hanya dihitung jika kedua kondisi di atas terpenuhi secara bersamaan (AND)
    
    ### **Perubahan dari sebelumnya**
    
    - **Sebelumnya:** Menggunakan kolom `Jenis Kredit` = "Modal Kerja"
    - **Sekarang:** Menggunakan kolom `Fasilitas` = "Modal Kerja" ✅ (sesuai permintaan)
    
    ### **Fitur Debug (Tab 3)**
    
    Gunakan tab Debug untuk melihat:
    - Tipe data sebelum dan setelah cleaning
    - Contoh nilai unik dari kolom-kolom penting (termasuk kolom `Fasilitas`)
    - Hasil konversi numeric (sum)
    - Unique CIF count
    """)

st.markdown("---")
st.caption("✅ SLIK Processor - Validasi & Rekapitulasi Data SLIK per CIF | Langkah 1 s/d 3")
st.caption("📌 **Kriteria OS:** Kondisi='Fasilitas Aktif' AND Fasilitas='Modal Kerja'")
