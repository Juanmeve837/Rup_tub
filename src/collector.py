"""
waze_collector.py
=================
Recolector incremental de alertas Waze.
- Opción 1 (Partner Hub)  →  data/waze_partnerhub.json
- Opción 2 (OpenWebNinja) →  data/waze_openwebninja.json  (fallback)

Corre cada 3 horas via GitHub Actions.
Los archivos JSON crecen de forma incremental; nunca se borra data anterior.
"""

import os
import json
import time
import hashlib
import requests
from datetime import datetime, timezone

# ──────────────────────────────────────────────
# CONFIGURACIÓN CENTRAL
# ──────────────────────────────────────────────
CONFIG = {
    "center_lat":       10.39972,
    "center_lon":      -75.51444,
    "search_radius_km": 10,
}

CENTER = f"{CONFIG['center_lat']},{CONFIG['center_lon']}"

# Rutas de salida (relativas a la raíz del repo)
PATH_JSON1 = "data/waze_partnerhub.json"
PATH_JSON2 = "data/waze_openwebninja.json"

# ── Credenciales (leídas desde variables de entorno / secrets) ──
PARTNER_URL = os.getenv(
    "WAZE_PARTNER_URL",
    "https://www.waze.com/row-partnerhub-api/partners/12221294397/"
    "waze-feeds/5b6ed9eb-a68d-4ed5-a4a6-585593c8a8e6?format=1",
)
OPENWEBNINJA_KEY = os.getenv("OPENWEBNINJA_API_KEY", "")
OPENWEBNINJA_URL = "https://api.openwebninja.com/waze/alerts-and-jams"


# ──────────────────────────────────────────────
# UTILIDADES DE PERSISTENCIA
# ──────────────────────────────────────────────

def load_json_store(path: str) -> dict:
    """
    Carga el archivo JSON acumulativo.
    Estructura del store:
    {
        "meta": { "last_updated": "...", "total_records": N },
        "records": { "<record_id>": { ...alert_data... } }
    }
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Estructura vacía inicial
    return {
        "meta": {
            "created_at":    datetime.now(timezone.utc).isoformat(),
            "last_updated":  None,
            "total_records": 0,
            "source":        path,
        },
        "records": {},
    }


def save_json_store(path: str, store: dict) -> None:
    """Persiste el store en disco, creando el directorio si no existe."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store["meta"]["last_updated"]  = datetime.now(timezone.utc).isoformat()
    store["meta"]["total_records"] = len(store["records"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    print(f"[STORE] ✓ Guardado: {path}  ({store['meta']['total_records']} registros totales)")


def make_record_id(alert: dict) -> str:
    """
    Genera un ID estable para deduplicación.
    Prioridad: uuid del propio objeto → hash de campos clave.
    """
    if alert.get("uuid"):
        return str(alert["uuid"])
    # Fallback: hash de tipo + ubicación + subtipo
    key_str = "|".join([
        str(alert.get("type",    "")),
        str(alert.get("subtype", "")),
        str(round(float(alert.get("location", {}).get("x", 0)), 4)),
        str(round(float(alert.get("location", {}).get("y", 0)), 4)),
    ])
    return hashlib.md5(key_str.encode()).hexdigest()


def merge_alerts(store: dict, new_alerts: list, fetch_ts: str) -> tuple[int, int]:
    """
    Inserta alertas nuevas en el store (sin duplicar por ID).
    Devuelve (nuevas_insertadas, duplicadas_ignoradas).
    """
    inserted = 0
    skipped  = 0
    for alert in new_alerts:
        rid = make_record_id(alert)
        if rid not in store["records"]:
            store["records"][rid] = {
                **alert,
                "_collected_at": fetch_ts,
                "_record_id":    rid,
            }
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


# ──────────────────────────────────────────────
# OPCIÓN 1 — WAZE PARTNER HUB
# ──────────────────────────────────────────────

def fetch_option1() -> list | None:
    """
    Consulta el endpoint oficial del Partner Hub de Waze.
    Devuelve lista de alertas, lista vacía, o None si falla la petición.
    """
    print(f"\n[OPCIÓN 1] Consultando Partner Hub…")
    print(f"[OPCIÓN 1] URL: {PARTNER_URL[:80]}…")
    try:
        r = requests.get(PARTNER_URL, timeout=30)
        r.raise_for_status()
        data = r.json()

        # El feed devuelve {"alerts": [...], "jams": [...], ...}
        alerts = data.get("alerts", [])
        jams   = data.get("jams",   [])

        # Normalizar jams para tener la misma estructura base
        for j in jams:
            j.setdefault("type", "JAM")

        combined = alerts + jams
        print(f"[OPCIÓN 1] ✓ Respuesta OK — {len(alerts)} alertas + {len(jams)} jams")
        return combined

    except requests.exceptions.Timeout:
        print("[OPCIÓN 1] ✗ Timeout")
    except requests.exceptions.HTTPError as e:
        print(f"[OPCIÓN 1] ✗ HTTP {e.response.status_code}: {e}")
    except requests.exceptions.ConnectionError:
        print("[OPCIÓN 1] ✗ Error de conexión")
    except Exception as e:
        print(f"[OPCIÓN 1] ✗ Error inesperado: {e}")
    return None


# ──────────────────────────────────────────────
# OPCIÓN 2 — OPENWEBNINJA (fallback)
# ──────────────────────────────────────────────

def fetch_option2() -> list | None:
    """
    Consulta la API no-oficial OpenWebNinja como fallback.
    Devuelve lista de alertas o None si falla.
    """
    print(f"\n[OPCIÓN 2] Consultando OpenWebNinja (fallback)…")

    if not OPENWEBNINJA_KEY:
        print("[OPCIÓN 2] ✗ OPENWEBNINJA_API_KEY no configurada")
        return None

    params = {
        "max_jams":   0,
        "max_alerts": 200,
        "center":     CENTER,
        "radius":     CONFIG["search_radius_km"],
    }
    headers = {"x-api-key": OPENWEBNINJA_KEY}

    try:
        r = requests.get(OPENWEBNINJA_URL, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        data    = r.json()
        alerts  = data.get("data", {}).get("alerts", [])
        print(f"[OPCIÓN 2] ✓ Respuesta OK — {len(alerts)} alertas")
        return alerts

    except requests.exceptions.Timeout:
        print("[OPCIÓN 2] ✗ Timeout")
    except requests.exceptions.HTTPError as e:
        print(f"[OPCIÓN 2] ✗ HTTP {e.response.status_code}: {e}")
    except requests.exceptions.ConnectionError:
        print("[OPCIÓN 2] ✗ Error de conexión")
    except Exception as e:
        print(f"[OPCIÓN 2] ✗ Error inesperado: {e}")
    return None


# ──────────────────────────────────────────────
# FLUJO PRINCIPAL
# ──────────────────────────────────────────────

def main():
    run_ts = datetime.now(timezone.utc).isoformat()
    print("=" * 60)
    print(f"[RUN] Inicio: {run_ts}")
    print(f"[RUN] Centro: {CENTER}  |  Radio: {CONFIG['search_radius_km']} km")
    print("=" * 60)

    option1_ok = False
    option2_ok = False

    # ── OPCIÓN 1 ─────────────────────────────
    alerts_1 = fetch_option1()

    if alerts_1 is not None:  # None = error de red; [] = respuesta vacía válida
        store1 = load_json_store(PATH_JSON1)
        new1, dup1 = merge_alerts(store1, alerts_1, run_ts)
        save_json_store(PATH_JSON1, store1)
        print(f"[OPCIÓN 1] Nuevos: {new1} | Duplicados ignorados: {dup1}")
        option1_ok = True
    else:
        print("[OPCIÓN 1] Falló — activando fallback Opción 2…")

    # ── OPCIÓN 2 (solo si Opción 1 falló) ────
    if not option1_ok:
        alerts_2 = fetch_option2()

        if alerts_2 is not None:
            store2 = load_json_store(PATH_JSON2)
            new2, dup2 = merge_alerts(store2, alerts_2, run_ts)
            save_json_store(PATH_JSON2, store2)
            print(f"[OPCIÓN 2] Nuevos: {new2} | Duplicados ignorados: {dup2}")
            option2_ok = True
        else:
            print("[OPCIÓN 2] ✗ Falló también. No se guardaron datos en esta ejecución.")

    # ── RESUMEN ───────────────────────────────
    print("\n" + "=" * 60)
    print(f"[RUN] Fin: {datetime.now(timezone.utc).isoformat()}")
    print(f"[RUN] Opción 1: {'✓ OK' if option1_ok else '✗ Falló'}")
    print(f"[RUN] Opción 2: {'✓ OK' if option2_ok else ('⊘ No ejecutada' if option1_ok else '✗ Falló')}")
    print("=" * 60)

    # Exit code 1 si ambas fuentes fallaron (útil para alertas en Actions)
    if not option1_ok and not option2_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
