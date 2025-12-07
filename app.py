import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource
import geopandas as gpd
import rasterio
from rasterio.plot import show
import io
import ssl
import requests
import matplotlib.patheffects as PathEffects
from shapely.geometry import box

# --- 1. GÜVENLİK AYARLARI ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import urllib3
urllib3.disable_warnings()

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="NASA Verili Türkiye Atlası", layout="wide", page_icon="🇹🇷")
st.title("🛰️ Gerçek NASA Verili Türkiye Atlası")
st.markdown("""
Bu sistem, simülasyon kullanmaz. **Doğrudan yüklediğiniz NASA (SRTM/GEBCO) Topografya verisini işler.**
Gerçek dağlar, gerçek ovalar ve gerçek nehir yatakları...
""")

# --- 2. YARDIMCI FONKSİYONLAR ---
@st.cache_data
def sinir_verilerini_getir():
    # İl Sınırları ve Su Kaynakları (İnternetten Çekilir)
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
    
    try:
        r_cities = requests.get(url_cities, verify=False)
        gdf_cities = gpd.read_file(io.BytesIO(r_cities.content))
        
        r_water = requests.get(url_water, verify=False)
        gdf_water = gpd.read_file(io.BytesIO(r_water.content))
        return gdf_cities, gdf_water
    except Exception as e:
        return None, None

def veriyi_isle(uploaded_file):
    # Yüklenen TIF dosyasını Rasterio ile oku
    with rasterio.open(uploaded_file) as src:
        # Veriyi oku (Çok büyükse küçültelim - Downsample)
        # Tüm Türkiye için 1/10 oranında okumak performansı kurtarır
        out_shape = (int(src.height / 5), int(src.width / 5)) 
        data = src.read(1, out_shape=out_shape, resampling=5)
        
        # Dönüşüm matrisini (transform) güncelle
        transform = src.transform * src.transform.scale(
            (src.width / data.shape[1]),
            (src.height / data.shape[0])
        )
        
        # Sınırları al
        bounds = rasterio.transform.array_bounds(src.height, src.width, src.transform)
        
        # Verideki bozuk noktaları (deniz seviyesi altı hataları) düzelt
        data = np.where(data < -100, 0, data) 
        
        return data, bounds, transform

# --- 3. ANA UYGULAMA ---

# YAN PANEL
st.sidebar.header("📂 Veri Yönetimi")

# 1. Dosya Yükleyici
uploaded_dem = st.sidebar.file_uploader("NASA .TIF Dosyasını Yükle", type=['tif', 'tiff'])

st.sidebar.info("""
ℹ️ **Dosyan Yok mu?**
Gerçek veri için "Turkey SRTM" veya "GEBCO Turkey" dosyasını indirmeniz gerekir.
Google'a **"Turkey SRTM 90m Geotiff download"** yazarak bulabilirsiniz veya OpenTopography sitesini kullanabilirsiniz.
""")

# 2. Ayarlar
st.sidebar.divider()
st.sidebar.subheader("Görünüm Ayarları")
kabartma = st.sidebar.slider("Dağ Gölgelendirme (Hillshade)", 0.1, 5.0, 1.5)
izohips_goster = st.sidebar.toggle("İzohipsleri Göster", value=True)
izohips_araligi = st.sidebar.select_slider("İzohips Sıklığı", options=[100, 250, 500, 1000], value=500)
su_goster = st.sidebar.toggle("Gölleri Göster", value=True)
sinir_goster = st.sidebar.toggle("İl Sınırlarını Göster", value=True)
isim_goster = st.sidebar.toggle("Şehir İsimleri", value=True)

# --- ÇİZİM ALANI ---

# Veri Kontrolü
if uploaded_dem is None:
    st.warning("⚠️ Lütfen sol taraftan bir **.TIF (Topografya)** dosyası yükleyin.")
    st.write("Eğer elinizde dosya yoksa, test etmek için küçük bir 'Adana_Hatay.tif' gibi bir dosya bulup yükleyebilirsiniz.")
    # Demo modunu kapattık, kullanıcıdan gerçek veri bekliyoruz.
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Turkey_relief_map.jpg/1280px-Turkey_relief_map.jpg", caption="Örnek: Gerçek veri yüklendiğinde böyle görünecek.")
    st.stop()

# Dosya Yüklendiyse İşlem Başlar
with st.spinner("NASA verileri işleniyor... (Bu işlem dosya boyutuna göre sürebilir)"):
    
    # 1. Topografya Verisini Hazırla
    Z, map_bounds, transform = veriyi_isle(uploaded_dem)
    minx, miny, maxx, maxy = map_bounds
    
    # 2. Vektör Verilerini (Sınır/Su) İndir
    gdf_cities, gdf_water = sinir_verilerini_getir()

    # Çizim Başlıyor
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # --- KATMAN 1: GERÇEK TOPOGRAFYA (Renkli + Gölgeli) ---
    ls = LightSource(azdeg=315, altdeg=45)
    # Renk haritası: 'terrain' (Mavi-Yeşil-Kahve-Beyaz)
    rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
    
    ax.imshow(rgb, extent=[minx, maxx, miny, maxy], origin='upper')

    # --- KATMAN 2: İZOHİPS (Kontür) ---
    if izohips_goster:
        # Veri çok yoğunsa kontür çizmek yavaş olabilir, dikkatli seviye seçimi
        levels = np.arange(0, np.max(Z), izohips_araligi)
        ax.contour(Z, levels=levels, colors='black', linewidths=0.3, alpha=0.5, 
                   extent=[minx, maxx, miny, maxy], origin='upper')

    # --- KATMAN 3: SU (Göller) ---
    if su_goster and gdf_water is not None:
        # Harita sınırlarına göre kes (Hız için)
        bbox = box(minx, miny, maxx, maxy)
        water_clip = gpd.clip(gdf_water, bbox)
        if not water_clip.empty:
            water_clip.plot(ax=ax, color='#1E90FF', alpha=0.9)

    # --- KATMAN 4: SINIRLAR ---
    if sinir_goster and gdf_cities is not None:
        # Arka plandaki tüm iller
        gdf_cities.boundary.plot(ax=ax, edgecolor='black', linewidth=0.5, alpha=0.6)

    # --- KATMAN 5: İSİMLER ---
    if isim_goster and gdf_cities is not None:
        # Sadece harita alanına giren şehirleri yaz
        visible_cities = gpd.clip(gdf_cities, box(minx, miny, maxx, maxy))
        for idx, row in visible_cities.iterrows():
            # Kolon adı bulma
            col_name = 'name' if 'name' in row else 'NAME'
            centroid = row.geometry.centroid
            ax.text(centroid.x, centroid.y, row[col_name], fontsize=9, ha='center', va='center',
                    color='black', fontweight='bold',
                    path_effects=[PathEffects.withStroke(linewidth=2, foreground='white')])

    # Eksen Ayarları
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_title("Topografik Analiz Haritası", fontsize=15)
    ax.set_xlabel("Boylam")
    ax.set_ylabel("Enlem")

    st.pyplot(fig)

    # İndirme Butonu
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches='tight')
    buf.seek(0)
    st.download_button("💾 Haritayı İndir (Yüksek Çözünürlük)", buf, "Gercek_Harita.png", "image/png")
