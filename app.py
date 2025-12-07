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
from shapely.geometry import box

# --- 1. SSL GÜVENLİK AYARLARI ---
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
**NASA (CGIAR-CSI) sunucularından** ilgili topografya paftasını **otomatik indirip işler.**
*(Not: Sunucular bazen yavaş yanıt verebilir, lütfen sabırlı olun.)*
""")

# --- 2. ROBOT: NASA VERİSİNİ BUL VE İNDİR ---
@st.cache_data(show_spinner=False)
def nasa_verisi_indir(lat, lon):
    """
    Verilen koordinatın hangi SRTM paftasına (Tile) düştüğünü hesaplar ve indirir.
    Formül: CGIAR-CSI 5x5 derece ızgarası.
    """
    try:
        # 1. Matematiksel Pafta Hesabı
        x_idx = int((180 + lon) / 5) + 1
        y_idx = int((60 - lat) / 5) + 1
        
        tile_name = f"srtm_{x_idx:02d}_{y_idx:02d}"
        # CGIAR-CSI Resmi Sunucusu
        url = f"https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/{tile_name}.zip"
        
        # 2. İndirme (Stream modunda)
        headers = {'User-Agent': 'Mozilla/5.0'}
        # verify=False ile SSL hatasını geçiyoruz
        r = requests.get(url, headers=headers, verify=False, stream=True, timeout=30)
        
        if r.status_code != 200:
            return None, f"Sunucu hatası (Kod: {r.status_code}). Link: {url}"
            
        # 3. Zip'i Hafızada Aç ve Kaydet
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            # Tif dosyasını bul
            tif_list = [f for f in z.namelist() if f.endswith('.tif')]
            if not tif_list:
                return None, "Zip içinden TIF dosyası çıkmadı."
            
            tif_file = tif_list[0]
            temp_filename = f"temp_{tile_name}.tif"
            
            # Eğer daha önce indirdiysek tekrar indirme
            if not os.path.exists(temp_filename):
                with open(temp_filename, "wb") as f:
                    f.write(z.read(tif_file))
                
        return temp_filename, None
        
    except Exception as e:
        return None, str(e)

# --- 3. VEKTÖR VERİLERİ (Sınır/Su) ---
@st.cache_data
def vektorel_veri_getir():
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
    
    try:
        r = requests.get(url_cities, verify=False)
        gdf_cities = gpd.read_file(io.BytesIO(r.content))
    except:
        return None, None

    try:
        r_w = requests.get(url_water, verify=False)
        gdf_water = gpd.read_file(io.BytesIO(r_w.content))
    except:
        gdf_water = None
            
    return gdf_cities, gdf_water

# --- YAN PANEL ---
st.sidebar.header("🎛️ Kontrol Merkezi")

with st.spinner("Sınır verileri yükleniyor..."):
    gdf_cities, gdf_water = vektorel_veri_getir()
    if gdf_cities is None:
        st.error("İnternet bağlantısı yok veya GitHub'a erişilemiyor.")
        st.stop()

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
    # 1. Seçilen ilin merkezini bul
    il_verisi = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
    bounds = il_verisi.total_bounds
    centroid = il_verisi.geometry.centroid.iloc[0]
    
    durum_kutusu = st.info(f"📡 NASA uydusuna bağlanılıyor... {secilen_yer} için veri aranıyor...")
    
    # 2. OTOMATİK İNDİRME
    dem_path, error = nasa_verisi_indir(centroid.y, centroid.x)
    
    if error:
        durum_kutusu.error(f"NASA Sunucusu Meşgul: {error}")
        st.warning("Alternatif: Sol menüden manuel dosya yüklemeyi deneyebilirsiniz.")
    else:
        durum_kutusu.success(f"✅ Başarılı! {secilen_yer} verisi işleniyor...")
        
        # 3. Haritayı Çiz
        with rasterio.open(dem_path) as src:
            # İlin sınırlarına göre kes
            geoms = il_verisi.geometry.values
            out_image, out_transform = mask(src, geoms, crop=True)
            
            Z = out_image[0]
            # Hatalı verileri temizle
            Z = np.where(Z < -100, np.nan, Z)
            Z = np.where(Z == src.nodata, np.nan, Z)
            
            # Yeni koordinat sınırları
            minx_c, miny_c = bounds[0], bounds[1]
            maxx_c, maxy_c = bounds[2], bounds[3]
            extent = [minx_c, maxx_c, miny_c, maxy_c]

            fig, ax = plt.subplots(figsize=(16, 12))
            # Arka planı deniz mavisi yap (Veri olmayan yerler deniz görünsün)
            ax.set_facecolor('#e6f3ff')

            # A. Topografya
            ls = LightSource(azdeg=315, altdeg=45)
            rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
            ax.imshow(rgb, extent=extent, origin='upper', zorder=1)

            # B. Su
            if su_var and gdf_water is not None:
                water_clip = gpd.clip(gdf_water, box(*bounds))
                if not water_clip.empty:
                    water_clip.plot(ax=ax, color='#1E90FF', alpha=0.9, zorder=2)

            # C. İzohips
            if izohips_var:
                Z_clean = np.nan_to_num(Z, nan=0)
                # Max yüksekliğe göre aralık belirle
                max_h = np.nanmax(Z)
                step = 500 if max_h > 2000 else 250
                levels = np.arange(0, max_h, step)
                
                if len(levels) > 0:
                    ax.contour(Z_clean, levels=levels, colors='black', linewidths=0.3, alpha=0.5, 
                            extent=extent, origin='upper', zorder=3)

            # D. Sınırlar
            il_verisi.boundary.plot(ax=ax, edgecolor='black', linewidth=2, zorder=4)

            # E. İsim
            ax.text(centroid.x, centroid.y, secilen_yer, fontsize=15, ha='center', va='center',
                    color='black', fontweight='bold', zorder=5,
                    path_effects=[PathEffects.withStroke(linewidth=3, foreground='white')])

            ax.set_title(f"{secilen_yer} Topografik Haritası (NASA SRTM)", fontsize=18)
            ax.set_aspect('equal')
            
            st.pyplot(fig)
            
            # İndirme
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=300, bbox_inches='tight')
            buf.seek(0)
            st.download_button("💾 Resmi İndir", buf, f"{secilen_yer}_Topo.png", "image/png")
