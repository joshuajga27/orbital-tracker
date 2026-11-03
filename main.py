from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from skyfield.api import load, wgs84
from geonamescache import GeonamesCache
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo
import traceback

app = FastAPI(title="API Global de Pases Orbitales")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("1. Cargando datos de satélites y base de datos de ciudades...")
url_activos = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
satelites = load.tle_file(url_activos)
ts = load.timescale()

gc = GeonamesCache()
ciudades_db = gc.get_cities()
tf = TimezoneFinder()

def buscar_coordenadas_local(nombre_ciudad: str):
    nombre_clean = nombre_ciudad.strip().lower()
    for c_id, ciudad_data in ciudades_db.items():
        if ciudad_data['name'].lower() == nombre_clean:
            return ciudad_data['latitude'], ciudad_data['longitude'], f"{ciudad_data['name']}, {ciudad_data['countrycode']}"
    return None, None, None

@app.get("/")
def inicio():
    return {"mensaje": "API activa. Servidor web listo sin bloqueos."}

@app.get("/pases")
def obtener_pases(
    ciudad: str = Query(None, description="Nombre de la ciudad o coordenadas (ej: Tokyo, Madrid, '41.38,2.16')"),
    horas: int = Query(24, description="Rango de horas a calcular"),
    elevacion_minima: float = Query(20.0, description="Grados mínimos sobre el horizonte")
):
    try:
        latitud_final, longitud_final = 41.3879, 2.1699
        nombre_ubicacion = "Barcelona, España (Por defecto)"

        if ciudad:
            # 1. Comprobar si son coordenadas directas (ej: "41.38, 2.16")
            if "," in ciudad and any(char.isdigit() for char in ciudad):
                try:
                    partes = ciudad.split(",")
                    latitud_final = float(partes[0].strip())
                    longitud_final = float(partes[1].strip())
                    nombre_ubicacion = f"Coordenadas: {latitud_final}, {longitud_final}"
                except Exception:
                    return {"error": "Formato de coordenadas inválido. Usa formato: latitud, longitud (ej: 41.38, 2.16)"}
            else:
                # 2. Búsqueda local sin peticiones de red
                lat, lng, nombre_full = buscar_coordenadas_local(ciudad)
                if lat is not None:
                    latitud_final, longitud_final = lat, lng
                    nombre_ubicacion = nombre_full
                else:
                    return {"error": f"No se encontró la ciudad '{ciudad}' en la base de datos local. Prueba ingresando coordenadas (ej: 41.38, 2.16)."}

        zona_destino_str = tf.timezone_at(lat=latitud_final, lng=longitud_final) or "UTC"
        try:
            zona_destino = ZoneInfo(zona_destino_str)
        except Exception:
            zona_destino = ZoneInfo("UTC")

        zona_usuario = ZoneInfo("Europe/Madrid")

        observador = wgs84.latlon(latitud_final, longitud_final, elevation_m=10.0)
        t0 = ts.now()
        t1 = ts.utc(t0.utc_datetime().year, t0.utc_datetime().month, t0.utc_datetime().day + (horas // 24 or 1))

        lista_pases = []

        for sat in satelites:
            try:
                t, events = sat.find_events(observador, t0, t1, altitude_degrees=elevacion_minima)
                for ti, event in zip(t, events):
                    if event == 1:
                        topocentrico = (sat - observador).at(ti)
                        alt, az, distancia = topocentrico.altaz()
                        
                        dt_utc = ti.utc_datetime().replace(tzinfo=ZoneInfo("UTC"))
                        hora_destino = dt_utc.astimezone(zona_destino).strftime('%d/%m/%Y %H:%M:%S')
                        hora_local_usuario = dt_utc.astimezone(zona_usuario).strftime('%d/%m/%Y %H:%M:%S')

                        lista_pases.append({
                            "satelite": sat.name,
                            "hora_ciudad_destino": f"{hora_destino} ({zona_destino_str})",
                            "hora_tu_ubicacion": f"{hora_local_usuario} (Europe/Madrid)",
                            "hora_utc": dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
                            "altura_grados": round(alt.degrees, 1),
                            "distancia_km": round(distancia.km, 0)
                        })
            except Exception:
                continue

        lista_pases.sort(key=lambda x: x["hora_utc"])

        return {
            "consulta": {
                "ubicacion": nombre_ubicacion,
                "zona_horaria": zona_destino_str,
                "latitud": round(latitud_final, 4),
                "longitud": round(longitud_final, 4)
            },
            "total_pases": len(lista_pases),
            "pases": lista_pases[:30]
        }
        
    except Exception as e:
        print("ERROR EN EL SERVIDOR:")
        traceback.print_exc()
        return {"error_interno": str(e)}