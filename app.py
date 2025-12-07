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
from shapely.geometry import Polygon

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
st.title("🇹🇷 Ultimate Türkiye Atlası: Fiziki, Siyasi ve Hidrografik")
st.markdown("Gerçek il sınırları, **GÖLLER (Garantili)**, izohipsler ve renkli topografya.")

# --- 2. MANUEL GÖL VERİTABANI (Yedek Güç) ---
# İnternet çalışmazsa bu koordinatlar devreye girer (Kabaca çizimlerdir)
MANUEL_GOLLER = {
    "Van Gölü": [(42.3, 38.5), (42.5, 38.3), (43.0, 38.2), (43.3, 38.4), (43.5, 38.7), (43.2, 38.9), (42.8, 38.9)],
    "Tuz Gölü": [(33.3, 38.7), (33.5, 38.5), (33.7, 38.6), (33.7, 39.0), (33.4, 39.1)],
    "Beyşehir Gölü": [(31.4, 37.6), (31.6, 37.6), (31.6, 37.8), (31.4, 37.9)],
    "Eğirdir Gölü": [(30.8, 37.9), (30.9, 37.9), (30.9, 38.2), (30.8, 38.3)],
    "İznik Gölü": [(29.4, 40.4), (29.6, 40.4), (29.6, 40.5), (29.4, 40.5)],
    "Atatürk Barajı": [(38.5, 37.4), (38.8, 37.4), (38.9, 37.6), (38.6, 37.7)],
    "Keban Barajı": [(39.3, 38.7), (39.6, 38.7), (39.6, 39.0), (39.2, 38.9)],
}

# --- 3. VERİ ÇEKME ---
@st.cache_data
def veri_getir():
    # Şehirler (Sağlam Kaynak)
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    
    # 1. Şehirleri İndir
    try:
        r = requests.get(url_cities, verify=False, timeout=10)
        gdf_cities = gpd.read_file(io.BytesIO(r.content))
    except Exception as e:
        st.error(f"Şehir verisi indirilemedi: {e}")
        return None, None

    # 2. Suları İndirmeyi Dene (Ama bel bağlama)
    gdf_water = None # Başlangıçta boş
    try:
        url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
        r_water = requests.get(url_water, verify=False, timeout=5)
        if r_water.status_code == 200:
            gdf_water = gpd.read_file(io.BytesIO(r_water.content))
    except:
        pass # Sessizce geç, manuel göller devreye girecek
            
    return gdf_cities, gdf_water

# --- YAN PANEL ---
st.sidebar.header("🎛️ Kontrol Paneli")

with st.spinner("Harita verileri hazırlanıyor..."):
    gdf_cities, gdf_water = veri_getir()
    
    if gdf_cities is None:
        st.stop()

    # Şehir Listesi
    cols = gdf_cities.columns
    if 'name' in cols: isim_kolonu = 'name'
    elif 'NAME' in cols: isim_kolonu = 'NAME'
    else: isim_kolonu = cols[0]
    
    il_listesi = sorted(gdf_cities[isim_kolonu].unique().tolist())
    il_listesi.insert(0, "TÜM TÜRKİYE")
    secilen_yer = st.sidebar.selectbox("Bölge Seçin:", il_listesi)

st.sidebar.markdown("---")
# Ayarlar
izohips_goster = st.sidebar.checkbox("İzohipsleri Göster", value=True)
su_goster = st.sidebar.checkbox("Gölleri Göster", value=True)
sinir_goster = st.sidebar.checkbox("İl Sınırlarını Göster", value=True)
isim_goster = st.sidebar.checkbox("Şehir İsimlerini Yaz", value=True)
kabartma = st.sidebar.slider("3D Dağ Efekti", 0.5, 3.0, 1.2)

if 'seed' not in st.session_state:
    st.session_state.seed = 1923

# --- ZEMİN SİMÜLASYONU ---
def zemin_uret(bounds, seed):
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
    return arazi

# --- ANA ÇİZİM ---
with st.spinner("Harita oluşturuluyor..."):
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # Arka planı MAVİ yap (Deniz efekti için)
    ax.set_facecolor('#cceeff') # Açık deniz mavisi

    if secilen_yer == "TÜM TÜRKİYE":
        plot_gdf = gdf_cities
        title_text = "Türkiye Fiziki, İdari ve Hidrografik Haritası"
    else:
        plot_gdf = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
        title_text = f"{secilen_yer} İli Detaylı Haritası"

    bounds = plot_gdf.total_bounds
    margin = 0.5
    viz_extent = [bounds[0]-margin, bounds[2]+margin, bounds[1]-margin, bounds[3]+margin]

    # 1. ZEMİN (Dağlar)
    # Zemini sadece Türkiye sınırları içinde göster (Maskeleme taklidi)
    Z = zemin_uret(bounds, st.session_state.seed)
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
    
    # Haritayı çiz
    ax.imshow(rgb, extent=[bounds[0], bounds[2], bounds[1], bounds[3]], origin='lower', zorder=2)

    # 2. GÖLLER (ÇİFTE KONTROL)
    if su_goster:
        # A) İnternetten inen veri varsa onu kullan
        if gdf_water is not None:
             gdf_water.plot(ax=ax, color='#1E90FF', alpha=1.0, zorder=3)
        
        # B) Yoksa MANUEL GÖLLERİ çiz (Garanti Yöntem)
        else:
            for gol_adi, coords in MANUEL_GOLLER.items():
                poly = Polygon(coords)
                # Sadece harita sınırları içindeyse çiz
                if poly.centroid.x > viz_extent[0] and poly.centroid.x < viz_extent[1]:
                    gpd.GeoSeries([poly]).plot(ax=ax, color='#1E90FF', edgecolor='blue', zorder=3)
                    # Göl adını yaz (sadece büyük haritada)
                    if secilen_yer == "TÜM TÜRKİYE":
                        ax.text(poly.centroid.x, poly.centroid.y, gol_adi, fontsize=6, 
                                color='white', ha='center', fontweight='bold', zorder=4,
                                path_effects=[PathEffects.withStroke(linewidth=2, foreground='blue')])

    # 3. İZOHİPS
    if izohips_goster:
        ax.contour(Z, levels=25, colors='black', linewidths=0.4, alpha=0.5, 
                   extent=[bounds[0], bounds[2], bounds[1], bounds[3]], zorder=4)

    # 4. SINIRLAR
    if sinir_goster:
        if secilen_yer == "TÜM TÜRKİYE":
            gdf_cities.boundary.plot(ax=ax, edgecolor='black', linewidth=0.7, zorder=5)
        else:
            gdf_cities.boundary.plot(ax=ax, edgecolor='gray', linewidth=0.3, alpha=0.5, zorder=5)
            plot_gdf.boundary.plot(ax=ax, edgecolor='black', linewidth=2.0, zorder=6)

    # 5. İSİMLER
    if isim_goster:
        target = gdf_cities if secilen_yer == "TÜM TÜRKİYE" else plot_gdf
        for idx, row in target.iterrows():
            centroid = row.geometry.centroid
            label = row[isim_kolonu]
            if (centroid.x > viz_extent[0] and centroid.x < viz_extent[1] and
                centroid.y > viz_extent[2] and centroid.y < viz_extent[3]):
                
                fs = 6 if secilen_yer == "TÜM TÜRKİYE" else 12
                txt = ax.text(centroid.x, centroid.y, label, fontsize=fs, ha='center', va='center', 
                        color='black', fontweight='bold', zorder=7)
                txt.set_path_effects([PathEffects.withStroke(linewidth=2, foreground='white')])

    ax.set_title(title_text, fontsize=18)
    ax.set_xlim(viz_extent[0], viz_extent[1])
    ax.set_ylim(viz_extent[2], viz_extent[3])
    ax.set_aspect('equal')
    ax.set_xlabel("Boylam")
    ax.set_ylabel("Enlem")

    st.pyplot(fig)
    
    # İndirme Butonu
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches='tight', facecolor='#cceeff')
    buf.seek(0)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.download_button(
            label="💾 Haritayı İndir (HD)",
            data=buf,
            file_name=f"Turkiye_Haritasi_{secilen_yer}.png",
            mime="image/png"
        )
