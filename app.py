import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource
import geopandas as gpd
import rasterio
from rasterio.mask import mask
import io
import ssl
import requests
import zipfile
import os
import matplotlib.patheffects as PathEffects

# --- SSL AYARLARI ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
import urllib3
urllib3.disable_warnings()

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Auto-NASA Atlas", layout="wide", page_icon="🛰️")
st.title("🛰️ Tam Otomatik Türkiye Atlası (Canlı Veri)")
st.markdown("""
Bu sistem **dosya yükleme gerektirmez**. Seçtiğiniz bölgenin koordinatlarını hesaplar ve 
**NASA'nın (CGIAR-CSI) sunucularından** ilgili topografya paftasını **otomatik indirip işler.**
""")

# --- ROBOT: NASA VERİSİNİ BUL VE İNDİR ---
@st.cache_data(show_spinner=False)
def nasa_verisi_indir(lat, lon):
    """
    Verilen koordinatın hangi SRTM paftasına (Tile) düştüğünü hesaplar ve indirir.
    NASA SRTM 90m verisi 5x5 derecelik kareler halindedir.
    """
    # 1. Matematiksel Pafta Hesabı (CGIAR Izgara Sistemi)
    # X (Sütun) = (180 + Boylam) / 5 + 1
    # Y (Satır) = (60 - Enlem) / 5 + 1
    x_idx = int((180 + lon) / 5) + 1
    y_idx = int((60 - lat) / 5) + 1
    
    tile_name = f"srtm_{x_idx:02d}_{y_idx:02d}"
    url = f"https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/{tile_name}.zip"
    
    # 2. İndirme İşlemi
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, verify=False, stream=True)
        if r.status_code != 200:
            return None, f"Sunucu hatası: {r.status_code}"
            
        # 3. Zip'i Hafızada Aç
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            # Tif dosyasını bul
            tif_file = [f for f in z.namelist() if f.endswith('.tif')][0]
            # Diske geçici olarak kaydetmek zorundayız (Rasterio bellekten okumayı sevmez)
            temp_filename = f"temp_{tile_name}.tif"
            with open(temp_filename, "wb") as f:
                f.write(z.read(tif_file))
                
        return temp_filename, None
        
    except Exception as e:
        return None, str(e)

# --- VERİ ÇEKME MOTORU (Sınırlar ve Göller) ---
@st.cache_data
def vektorel_veri_getir():
    # Şehirler
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    # Sular
    url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
    
    try:
        r = requests.get(url_cities, verify=False)
        gdf_cities = gpd.read_file(io.BytesIO(r.content))
        
        r_water = requests.get(url_water, verify=False)
        gdf_water = gpd.read_file(io.BytesIO(r_water.content))
        return gdf_cities, gdf_water
    except:
        return None, None

# --- YAN PANEL ---
st.sidebar.header("🎛️ Kontrol Merkezi")

with st.spinner("Sınır verileri yükleniyor..."):
    gdf_cities, gdf_water = vektorel_veri_getir()
    if gdf_cities is None:
        st.error("İnternet bağlantısı yok.")
        st.stop()

# İsim kolonunu bul
cols = gdf_cities.columns
isim_kolonu = 'name' if 'name' in cols else 'NAME'
il_listesi = sorted(gdf_cities[isim_kolonu].unique().tolist())
secilen_yer = st.sidebar.selectbox("📍 Gitmek İstediğiniz İl:", il_listesi)

st.sidebar.divider()
kabartma = st.sidebar.slider("Dağ Efekti", 0.5, 4.0, 1.5)
izohips_var = st.sidebar.checkbox("İzohips", value=True)
su_var = st.sidebar.checkbox("Göller", value=True)

# --- ANA İŞLEM ---
if secilen_yer:
    # 1. Seçilen ilin merkezini ve sınırlarını bul
    il_verisi = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
    bounds = il_verisi.total_bounds # minx, miny, maxx, maxy
    centroid = il_verisi.geometry.centroid.iloc[0]
    
    # Bilgi Mesajı
    durum_kutusu = st.info(f"📡 NASA uydusuna bağlanılıyor... {secilen_yer} için veri indiriliyor...")
    
    # 2. NASA Verisini İndir (Robot Çalışıyor)
    dem_path, error = nasa_verisi_indir(centroid.y, centroid.x)
    
    if error:
        durum_kutusu.error(f"NASA Sunucusu Yanıt Vermedi: {error}")
    else:
        durum_kutusu.success(f"✅ Veri İndirildi! {secilen_yer} topografyası işleniyor...")
        
        # 3. Veriyi Kes ve İşle
        with rasterio.open(dem_path) as src:
            # İlin sınırlarına göre kes (Crop)
            # GeoJSON geometrisini kullanarak maskeleme yapıyoruz
            geoms = il_verisi.geometry.values
            out_image, out_transform = mask(src, geoms, crop=True)
            out_meta = src.meta
            
            # Veriyi düzelt (0 altı değerler ve nodata'yı temizle)
            Z = out_image[0]
            Z = np.where(Z < -100, np.nan, Z) # Hatalı verileri sil
            Z = np.where(Z == src.nodata, np.nan, Z)
            
            # Koordinat sınırlarını güncelle (Kesilen parça için)
            height, width = Z.shape
            minx_c, miny_c = bounds[0], bounds[1]
            maxx_c, maxy_c = bounds[2], bounds[3]
            extent = [minx_c, maxx_c, miny_c, maxy_c]

            # --- ÇİZİM ---
            fig, ax = plt.subplots(figsize=(16, 12))
            ax.set_facecolor('#e6f3ff') # Deniz rengi arka plan

            # A. ZEMİN (NASA Verisi)
            ls = LightSource(azdeg=315, altdeg=45)
            # Nan değerleri (sınır dışı) ş
