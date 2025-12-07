import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter
from matplotlib.colors import LightSource
import geopandas as gpd
import io
import ssl
import requests
import matplotlib.patheffects as PathEffects
from shapely.geometry import box

# --- KÜTÜPHANE KONTROLÜ (HATA ÖNLEYİCİ) ---
try:
    import rasterio
    from rasterio.plot import show
    RASTERIO_VAR = True
except ImportError:
    RASTERIO_VAR = False  # Kütüphane yoksa not al, ama çökme!

# --- 1. SSL AYARLARI ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import urllib3
urllib3.disable_warnings()

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="PRO Türkiye Atlası", layout="wide", page_icon="🇹🇷")
st.title("🇹🇷 Ultimate Türkiye Atlası: Hibrit Mod")

# Durum Bildirimi
if not RASTERIO_VAR:
    st.warning("⚠️ Sunucu 'rasterio' kütüphanesini yükleyemedi. **Gerçek TIF yükleme modu devre dışı.** Ancak Simülasyon Modu (Gerçek sınırlar ve göllerle) sorunsuz çalışıyor.")
else:
    st.success("✅ Tüm sistemler aktif (Rasterio Yüklü).")

st.markdown("""
Bu sistem **akıllı modda** çalışır:
1. **Otomatik:** Açılışta gerçek sınırlar ve göller ile matematiksel topografyayı birleştirir.
2. **Profesyonel:** (Aktifse) Sol taraftan `.tif` dosyası yüklerseniz gerçek NASA verisine geçer.
""")

# --- 2. VERİ ÇEKME MOTORU ---
@st.cache_data
def veri_getir():
    # İl Sınırları
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    # Su Kaynakları
    url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
    
    gdf_cities = None
    gdf_water = None

    try:
        r = requests.get(url_cities, verify=False, timeout=10)
        gdf_cities = gpd.read_file(io.BytesIO(r.content))
    except:
        pass

    try:
        r_water = requests.get(url_water, verify=False, timeout=10)
        gdf_water = gpd.read_file(io.BytesIO(r_water.content))
    except:
        pass
            
    return gdf_cities, gdf_water

# --- 3. TOPOGRAFYA MOTORLARI ---

# A) Simülasyon Motoru (Otomatik Mod İçin)
def zemin_uret_simulasyon(bounds, seed):
    np.random.seed(seed)
    minx, miny, maxx, maxy = bounds
    width = maxx - minx
    height = maxy - miny
    if width == 0: width = 1
    
    base_res = 800 
    shape = (int(base_res * (height/width)), base_res)
    if shape[0] < 100: shape = (400, 800)
        
    x = np.linspace(0, 1, shape[1])
    y = np.linspace(0, 1, shape[0])
    X, Y = np.meshgrid(x, y)
    
    noise = gaussian_filter(np.random.rand(*shape), sigma=7) * 0.7
    detay = gaussian_filter(np.random.rand(*shape), sigma=1) * 0.15
    rampa = X * 0.5 
    
    arazi = noise + detay + rampa
    arazi = (arazi - arazi.min()) / (arazi.max() - arazi.min())
    return arazi, shape

# B) Gerçek Veri Motoru (Dosya Yüklenirse)
def zemin_uret_gercek(uploaded_file):
    if not RASTERIO_VAR:
        return None, None
        
    with rasterio.open(uploaded_file) as src:
        # Performans için veriyi küçülterek oku (1/5 oranında)
        out_shape = (int(src.height / 5), int(src.width / 5))
        data = src.read(1, out_shape=out_shape, resampling=5)
        
        # Sınırları al
        bounds = rasterio.transform.array_bounds(src.height, src.width, src.transform)
        
        # Hatalı verileri düzelt
        data = np.where(data < -100, 0, data)
        return data, bounds

# --- UYGULAMA AKIŞI ---

# Yan Panel
st.sidebar.header("🎛️ Kontrol Paneli")

# Dosya Yükleyici (Sadece kütüphane varsa göster)
uploaded_dem = None
if RASTERIO_VAR:
    uploaded_dem = st.sidebar.file_uploader("NASA .TIF Dosyası (Opsiyonel)", type=['tif', 'tiff'])
else:
    st.sidebar.error("Gerçek dosya yükleme modülü (Rasterio) sunucuda eksik.")

# Verileri İndir
with st.spinner("Harita verileri yükleniyor..."):
    gdf_cities, gdf_water = veri_getir()

if gdf_cities is None:
    st.error("Veri indirilemedi.")
    st.stop()

# Bölge Seçimi
cols = gdf_cities.columns
if 'name' in cols: isim_kolonu = 'name'
elif 'NAME' in cols: isim_kolonu = 'NAME'
else: isim_kolonu = cols[0]

il_listesi = sorted(gdf_cities[isim_kolonu].unique().tolist())
il_listesi.insert(0, "TÜM TÜRKİYE")
secilen_yer = st.sidebar.selectbox("Bölge Seçin:", il_listesi)

st.sidebar.markdown("---")
kabartma = st.sidebar.slider("Dağ Efekti", 0.5, 3.0, 1.2)
izohips_goster = st.sidebar.checkbox("İzohipsleri Göster", value=True)
sinir_goster = st.sidebar.checkbox("Sınırları Göster", value=True)
su_goster = st.sidebar.checkbox("Gölleri Göster
