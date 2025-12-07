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

# --- SAYFA AYARLARI (Layout 'wide' yani geniş ekran) ---
st.set_page_config(page_title="Türkiye Geo-Atlas Pro", layout="wide", page_icon="🌍")

# --- BAŞLIK ALANI ---
st.title("🌍 Türkiye Coğrafi Analiz ve Topografya Atlası")
st.markdown("Bu panel; **NASA SRTM** benzeri simülasyonlar, **Mülki İdare Sınırları** ve **Hidrografik Verileri** birleştirerek analiz eder.")

# --- 2. MANUEL GÖLLER (Yedek) ---
MANUEL_GOLLER = {
    "Van Gölü": [(42.3, 38.5), (42.5, 38.3), (43.0, 38.2), (43.3, 38.4), (43.5, 38.7), (43.2, 38.9), (42.8, 38.9)],
    "Tuz Gölü": [(33.3, 38.7), (33.5, 38.5), (33.7, 38.6), (33.7, 39.0), (33.4, 39.1)],
    "Beyşehir Gölü": [(31.4, 37.6), (31.6, 37.6), (31.6, 37.8), (31.4, 37.9)],
    "Eğirdir Gölü": [(30.8, 37.9), (30.9, 37.9), (30.9, 38.2), (30.8, 38.3)],
    "İznik Gölü": [(29.4, 40.4), (29.6, 40.4), (29.6, 40.5), (29.4, 40.5)],
    "Atatürk Barajı": [(38.5, 37.4), (38.8, 37.4), (38.9, 37.6), (38.6, 37.7)],
}

# --- 3. VERİ ÇEKME ---
@st.cache_data
def veri_getir():
    url_cities = "https://raw.githubusercontent.com/alpers/Turkey-Maps-GeoJSON/master/tr-cities.json"
    
    try:
        r = requests.get(url_cities, verify=False, timeout=10)
        gdf_cities = gpd.read_file(io.BytesIO(r.content))
    except Exception as e:
        st.error(f"Veri hatası: {e}")
        return None, None

    gdf_water = None
    try:
        url_water = "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-water-utf8.json"
        r_water = requests.get(url_water, verify=False, timeout=5)
        if r_water.status_code == 200:
            gdf_water = gpd.read_file(io.BytesIO(r_water.content))
    except:
        pass
            
    return gdf_cities, gdf_water

# --- YAN PANEL ---
with st.sidebar:
    st.header("🎛️ Kontrol Merkezi")
    
    with st.spinner("Veri Tabanına Bağlanılıyor..."):
        gdf_cities, gdf_water = veri_getir()
    
    if gdf_cities is None:
        st.stop()

    cols = gdf_cities.columns
    isim_kolonu = 'name' if 'name' in cols else 'NAME'
    
    il_listesi = sorted(gdf_cities[isim_kolonu].unique().tolist())
    il_listesi.insert(0, "TÜM TÜRKİYE")
    
    # Seçim Kutusu
    secilen_yer = st.selectbox("📍 Bölge / İl Seçimi", il_listesi)
    
    st.divider()
    
    st.subheader("Katman Ayarları")
    izohips_goster = st.toggle("İzohips Eğrileri", value=True)
    su_goster = st.toggle("Hidrografya (Su)", value=True)
    sinir_goster = st.toggle("İdari Sınırlar", value=True)
    isim_goster = st.toggle("Yerleşim İsimleri", value=True)
    
    st.divider()
    
    kabartma = st.slider("⛰️ 3D Kabartma Şiddeti", 0.5, 3.0, 1.2)
    
    st.info("Bu panel, anlık olarak sunucu üzerinden render almaktadır.")

if 'seed' not in st.session_state:
    st.session_state.seed = 1923

# --- ZEMİN FONKSİYONU ---
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

# --- ANA ALAN ---

# 1. METRİKLER (Dashboard Havası Verir)
col1, col2, col3, col4 = st.columns(4)

if secilen_yer == "TÜM TÜRKİYE":
    plot_gdf = gdf_cities
    enlem, boylam = "39.0", "35.5"
    alan_bilgisi = "783.562 km²"
else:
    plot_gdf = gdf_cities[gdf_cities[isim_kolonu] == secilen_yer]
    centroid = plot_gdf.geometry.centroid.iloc[0]
    enlem = f"{centroid.y:.2f} K"
    boylam = f"{centroid.x:.2f} D"
    alan_bilgisi = "Hesaplanıyor..."

col1.metric("Seçilen Bölge", secilen_yer)
col2.metric("Merkez Enlem", enlem)
col3.metric("Merkez Boylam", boylam)
col4.metric("Veri Kaynağı", "GitHub/OpenSource")

# 2. SEKMELER (Daha Düzenli Görünüm)
tab1, tab2, tab3 = st.tabs(["🗺️ Harita Görünümü", "📊 Veri Analizi", "ℹ️ Hakkında"])

with tab1:
    with st.spinner("Yüksek çözünürlüklü harita oluşturuluyor..."):
        fig, ax = plt.subplots(figsize=(16, 9))
        ax.set_facecolor('#cceeff')

        bounds = plot_gdf.total_bounds
        margin = 0.5
        viz_extent = [bounds[0]-margin, bounds[2]+margin, bounds[1]-margin, bounds[3]+margin]

        # ZEMİN
        Z = zemin_uret(bounds, st.session_state.seed)
        ls = LightSource(azdeg=315, altdeg=45)
        rgb = ls.shade(Z, cmap=plt.cm.terrain, vert_exag=kabartma, blend_mode='overlay')
        ax.imshow(rgb, extent=[bounds[0], bounds[2], bounds[1], bounds[3]], origin='lower', zorder=2)

        # SU KATMANI
        if su_goster:
            if gdf_water is not None:
                 gdf_water.plot(ax=ax, color='#1E90FF', alpha=1.0, zorder=3)
            else:
                for gol_adi, coords in MANUEL_GOLLER.items():
                    poly = Polygon(coords)
                    if poly.centroid.x > viz_extent[0] and poly.centroid.x < viz_extent[1]:
                        gpd.GeoSeries([poly]).plot(ax=ax, color='#1E90FF', edgecolor='blue', zorder=3)

        # İZOHİPS
        if izohips_goster:
            ax.contour(Z, levels=25, colors='black', linewidths=0.3, alpha=0.4, 
                       extent=[bounds[0], bounds[2], bounds[1], bounds[3]], zorder=4)

        # SINIRLAR
        if sinir_goster:
            if secilen_yer == "TÜM TÜRKİYE":
                gdf_cities.boundary.plot(ax=ax, edgecolor='black', linewidth=0.5, zorder=5)
            else:
                gdf_cities.boundary.plot(ax=ax, edgecolor='gray', linewidth=0.3, alpha=0.5, zorder=5)
                plot_gdf.boundary.plot(ax=ax, edgecolor='black', linewidth=1.5, zorder=6)

        # İSİMLER
        if isim_goster:
            target = gdf_cities if secilen_yer == "TÜM TÜRKİYE" else plot_gdf
            for idx, row in target.iterrows():
                centroid = row.geometry.centroid
                label = row[isim_kolonu]
                if (centroid.x > viz_extent[0] and centroid.x < viz_extent[1] and
                    centroid.y > viz_extent[2] and centroid.y < viz_extent[3]):
                    
                    fs = 6 if secilen_yer == "TÜM TÜRKİYE" else 11
                    txt = ax.text(centroid.x, centroid.y, label, fontsize=fs, ha='center', va='center', 
                            color='black', fontweight='bold', zorder=7)
                    txt.set_path_effects([PathEffects.withStroke(linewidth=2, foreground='white')])

        ax.set_xlim(viz_extent[0], viz_extent[1])
        ax.set_ylim(viz_extent[2], viz_extent[3])
        ax.set_aspect('equal')
        # Eksenleri kapatıp daha temiz bir görünüm yapalım
        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)

        st.pyplot(fig)

        # İndirme Butonu
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=300, bbox_inches='tight', facecolor='#cceeff')
        buf.seek(0)
        st.download_button(
            label="💾 Yüksek Kaliteli PNG Olarak İndir",
            data=buf,
            file_name=f"Atlas_{secilen_yer}.png",
            mime="image/png",
            use_container_width=True
        )

with tab2:
    st.subheader(f"📊 {secilen_yer} - Coğrafi Veri Seti")
    st.write("Bu bölümde, haritanın oluşturulmasında kullanılan ham verileri inceleyebilirsiniz.")
    
    # Veri Çerçevesini Göster (Tablo halinde)
    st.dataframe(plot_gdf.drop(columns='geometry'), use_container_width=True)
    
    st.info("Bu veriler GeoJSON formatından çekilerek Pandas DataFrame formatına dönüştürülmüştür.")

with tab3:
    st.subheader("Proje Hakkında")
    st.markdown("""
    Bu proje, Python kütüphaneleri kullanılarak geliştirilmiş interaktif bir atlas uygulamasıdır.
    
    **Kullanılan Teknolojiler:**
    * **Streamlit:** Web Arayüzü
    * **GeoPandas:** Coğrafi Veri İşleme
    * **Matplotlib:** Harita Çizimi
    * **SciPy:** Topografya Simülasyonu
    
    **Geliştirici:** (Senin Adın)
    """)
