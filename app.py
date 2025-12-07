import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter
from matplotlib.colors import LightSource
import geopandas as gpd
import rasterio
from rasterio.plot import show
import io
import ssl
import requests
import matplotlib.patheffects as PathEffects
from shapely.geometry import box

# --- 1. GÜVENLİK DUVARINI AŞMA (SSL HACK) ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import urllib3
urllib3.disable_warnings()

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Pro Atlas (Offline Destekli)", layout="wide", page_icon="🛡️")
st.title("🛡️ Türkiye Atlası: Kesintisiz Mod")
st.markdown("""
Bu sistem **akıllı bağlantı** kullanır. Veri sunucularına ulaşılamazsa otomatik olarak **Simülasyon Moduna** geçer.
Asla hata verip kapanmaz.
""")

# --- 2. GÜÇLENDİRİLMİŞ VERİ MOTORU ---
@st.cache_data
def veri_getir_guvenli():
    # Sahte Tarayıcı Kimliği (Robot olmadığımızı kanıtlamak için)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
    }
    
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
    
    gdf_cities = None
    gdf_water = None
    baglanti_durumu = "Online"

    # 1. ŞEHİRLER
    try:
        r = requests.get(url_cities, headers=headers, verify=False, timeout=5)
        if r.status_code == 200:
            gdf_cities = gpd.read_file(io.BytesIO(r.content))
    except:
        baglanti_durumu = "Offline (Şehir Sınırları İndirilemedi)"

    # 2. SULAR
    try:
        r_water = requests.get(url_water, headers=headers, verify=False, timeout=5)
        if r_water.status_code == 200:
            gdf_water = gpd.read_file(io.BytesIO(r_water.content))
    except:
        pass # Su yoksa sorun yok
            
    return gdf_cities, gdf_water, baglanti_durumu

# --- 3. TOPOGRAFYA MOTORLARI ---

def zemin_uret_simulasyon(bounds, seed):
    np.random.seed(seed)
    minx, miny, maxx, maxy = bounds
    width = maxx - minx
    height = maxy - miny
    if width == 0: width = 1
    
    # Yüksek Çözünürlük
    base_res = 600 
    shape = (int(base_res * (height/width)), base_res)
    if shape[0] < 100: shape = (300, 600)
        
    x = np.linspace(0, 1, shape[1])
    y = np.linspace(0, 1, shape[0])
    X, Y = np.meshgrid(x, y)
    
    # Matematiksel Dağlar
    noise = gaussian_filter(np.random.rand(*shape), sigma=6) * 0.7
    detay = gaussian_filter(np.random.rand(*shape), sigma=1) * 0.15
    rampa = X * 0.5 
    
    arazi = noise + detay + rampa
    arazi = (arazi - arazi.min()) / (arazi.max() - arazi.min())
    return arazi

def zemin_uret_gercek(uploaded_file):
    with rasterio.open(uploaded_file) as src:
        out_shape = (int(src.height / 5), int(src.width / 5))
        data = src.read(1, out_shape=out_shape, resampling=5)
        bounds = rasterio.transform.array_bounds(src.height, src.width, src.transform)
        data = np.where(data < -100, 0, data)
        return data, bounds

# --- UYGULAMA AKIŞI ---

# Yan Panel
st.sidebar.header("🎛️ Kontrol Paneli")

# 1. Manuel Dosya Yükleme (Her zaman çalışır)
uploaded_dem = st.sidebar.file_uploader("NASA Dosyası Yükle (.tif)", type=['tif', 'tiff'])

# 2. Verileri İndirmeyi Dene
with st.spinner("Sunuculara bağlanılıyor..."):
    gdf_cities, gdf_water, durum = veri_getir_guvenli()

# Durum Bildirimi
if "Offline" in durum:
    st.warning("⚠️ İnternet verisi çekilemedi. **Simülasyon Modu** devrede.")
    # Veri yoksa manuel liste oluştur (Uygulama çökmesin diye)
    il_listesi = ["TÜM TÜRKİYE", "Adana", "Ankara", "İstanbul", "İzmir"] 
    # Boş bir GeoDataFrame oluştur ki kod hata vermesin
    gdf_cities = gpd.GeoDataFrame() 
else:
    st.success("✅ Sunuculara Bağlandı. Gerçek veriler hazır.")
    cols = gdf_cities.columns
    isim_kolonu = 'name' if 'name' in cols else 'NAME'
    il_listesi = sorted(gdf_cities[isim_kolonu].unique().tolist())
    il_listesi.insert(0, "TÜM TÜRKİYE")

secilen_yer = st.sidebar.selectbox("Bölge Seçin:", il_listesi)

st.sidebar.markdown("---")
kabartma = st.sidebar.slider("Dağ Efekti", 0.5, 3.0, 1.2)
izohips_goster = st.sidebar.checkbox("İzohipsleri Göster", value=True)
sinir_goster = st.sidebar.checkbox("Sınırları Göster", value=True)
su_goster = st.sidebar.checkbox("Gölleri Göster", value=True)
isim_goster = st.sidebar.checkbox("İsimleri Yaz", value=True)

if 'seed' not in st.session_state:
    st.session_state.seed = 1923

# --- ÇİZİM ALANI ---
with st.spinner("Harita render ediliyor..."):
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # Koordinatları Belirle
    bounds = [26.0, 36.0, 45.0, 42.0] # Varsayılan Türkiye Sınırları
    plot_gdf = None

    # Eğer internetten veri geldiyse sınırları güncelle
    if not gdf_cities.empty and secilen_yer != "TÜM TÜRKİYE":
        plot_gdf = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
        if not plot_gdf.empty:
            bounds = plot_gdf.total_bounds
    elif not gdf_cities.empty:
        bounds = gdf_cities.total_bounds

    # --- KARAR MEKANİZMASI ---
    if uploaded_dem is not None:
        # A) GERÇEK DOSYA VARSA
        Z, real_bounds = zemin_uret_gercek(uploaded_dem)
        extent = [real_bounds[0], real_bounds[2], real_bounds[1], real_bounds[3]]
        # Eksenleri gerçek dosyaya göre ayarla
        bounds = real_bounds 
        origin_val = 'upper'
    else:
        # B) DOSYA YOKSA (SİMÜLASYON)
        # Sınırları biraz genişlet
        margin = 0.5
        sim_bounds = [bounds[0]-margin, bounds[1]-margin, bounds[2]+margin, bounds[3]+margin]
        Z = zemin_uret_simulasyon(sim_bounds, st.session_state.seed)
        extent = [sim_bounds[0], sim_bounds[2], sim_bounds[1], sim_bounds[3]]
        origin_val = 'lower'

    # ÇİZİM
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
    ax.imshow(rgb, extent=extent, origin=origin_val, zorder=1)

    # Su (Varsa)
    if su_goster and gdf_water is not None and not gdf_water.empty:
        try:
            gdf_water.plot(ax=ax, color='#1E90FF', alpha=0.9, zorder=2)
        except:
            pass

    # İzohips
    if izohips_goster:
        levels = 25 if uploaded_dem is None else np.arange(0, np.max(Z), 500)
        ax.contour(Z, levels=levels, colors='black', linewidths=0.3, alpha=0.5, 
                   extent=extent, origin=origin_val, zorder=3)

    # Sınırlar (Varsa)
    if sinir_goster and not gdf_cities.empty:
        if secilen_yer == "TÜM TÜRKİYE":
            gdf_cities.boundary.plot(ax=ax, edgecolor='black', linewidth=0.6, zorder=4)
        elif plot_gdf is not None:
            gdf_cities.boundary.plot(ax=ax, edgecolor='gray', linewidth=0.3, alpha=0.5, zorder=4)
            plot_gdf.boundary.plot(ax=ax, edgecolor='black', linewidth=1.5, zorder=5)

    # Ahmet Peşkir
