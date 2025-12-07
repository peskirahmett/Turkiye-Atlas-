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
    RASTERIO_VAR = True
except ImportError:
    RASTERIO_VAR = False

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
    st.warning("⚠️ Sunucuda 'rasterio' yüklü değil. Gerçek TIF yükleme devre dışı, ancak **Simülasyon Modu** çalışıyor.")

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
        out_shape = (int(src.height / 5), int(src.width / 5))
        data = src.read(1, out_shape=out_shape, resampling=5)
        bounds = rasterio.transform.array_bounds(src.height, src.width, src.transform)
        data = np.where(data < -100, 0, data)
        return data, bounds

# --- UYGULAMA AKIŞI ---

# Yan Panel
st.sidebar.header("🎛️ Kontrol Paneli")

# Dosya Yükleyici
uploaded_dem = None
if RASTERIO_VAR:
    uploaded_dem = st.sidebar.file_uploader("NASA .TIF Dosyası (Opsiyonel)", type=['tif', 'tiff'])

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
# Ayarlar
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
    
    if secilen_yer == "TÜM TÜRKİYE":
        plot_gdf = gdf_cities
        title_text = "Türkiye Fiziki Haritası"
    else:
        plot_gdf = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
        title_text = f"{secilen_yer} İli Haritası"

    target_bounds = plot_gdf.total_bounds 

    # --- KARAR MEKANİZMASI ---
    if uploaded_dem is not None and RASTERIO_VAR:
        # GERÇEK MOD
        Z, bounds = zemin_uret_gercek(uploaded_dem)
        if Z is not None:
            extent = [bounds[0], bounds[2], bounds[1], bounds[3]]
            origin_val = 'upper'
            st.success("✅ Gerçek NASA verisi kullanılıyor.")
        else:
            # Hata durumunda Simülasyon
            margin = 0.2
            sim_bounds = [target_bounds[0]-margin, target_bounds[1]-margin, 
                          target_bounds[2]+margin, target_bounds[3]+margin]
            Z, _ = zemin_uret_simulasyon(sim_bounds, st.session_state.seed)
            extent = [sim_bounds[0], sim_bounds[2], sim_bounds[1], sim_bounds[3]]
            origin_val = 'lower'
    else:
        # SİMÜLASYON MODU
        margin = 0.2
        sim_bounds = [target_bounds[0]-margin, target_bounds[1]-margin, 
                      target_bounds[2]+margin, target_bounds[3]+margin]
        Z, _ = zemin_uret_simulasyon(sim_bounds, st.session_state.seed)
        extent = [sim_bounds[0], sim_bounds[2], sim_bounds[1], sim_bounds[3]]
        origin_val = 'lower'

    # 1. Topografya
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
    ax.imshow(rgb, extent=extent, origin=origin_val, zorder=1)

    # Zoom Alanı
    viz_extent = [target_bounds[0]-0.2, target_bounds[2]+0.2, 
                  target_bounds[1]-0.2, target_bounds[3]+0.2]

    # 2. Su
    if su_goster and gdf_water is not None:
        try:
            water_clip = gpd.clip(gdf_water, box(*viz_extent))
            if not water_clip.empty:
                water_clip.plot(ax=ax, color='#1E90FF', alpha=0.9, zorder=2)
        except:
            pass

    # 3. İzohips
    if izohips_goster:
        levels = 25 if uploaded_dem is None else np.arange(0, np.max(Z), 500)
        ax.contour(Z, levels=levels, colors='black', linewidths=0.3, alpha=0.5, 
                   extent=extent, origin=origin_val, zorder=3)

    # 4. Sınırlar
    if sinir_goster:
        if secilen_yer == "TÜM TÜRKİYE":
            gdf_cities.boundary.plot(ax=ax, edgecolor='black', linewidth=0.6, zorder=4)
        else:
            gdf_cities.boundary.plot(ax=ax, edgecolor='gray', linewidth=0.3, alpha=0.5, zorder=4)
            plot_gdf.boundary.plot(ax=ax, edgecolor='black', linewidth=1.5, zorder=5)

    # 5. İsimler
    if isim_goster:
        target = gdf_cities if secilen_yer == "TÜM TÜRKİYE" else plot_gdf
        for idx, row in target.iterrows():
            centroid = row.geometry.centroid
            if (centroid.x > viz_extent[0] and centroid.x < viz_extent[1] and
                centroid.y > viz_extent[2] and centroid.y < viz_extent[3]):
                
                label = row[isim_kolonu]
                fs = 6 if secilen_yer == "TÜM TÜRKİYE" else 11
                txt = ax.text(centroid.x, centroid.y, label, fontsize=fs, ha='center', va='center', 
                        color='black', fontweight='bold', zorder=6)
                txt.set_path_effects([PathEffects.withStroke(linewidth=2, foreground='white')])

    ax.set_xlim(viz_extent[0], viz_extent[1])
    ax.set_ylim(viz_extent[2], viz_extent[3])
    ax.set_aspect('equal')
    ax.set_title(title_text, fontsize=15)
    
    st.pyplot(fig)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches='tight')
    buf.seek(0)
    st.download_button("💾 Resmi İndir", buf, "Harita.png", "image/png")
