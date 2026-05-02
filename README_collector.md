# Waze Alerts Collector — Guía de despliegue

Recolector incremental de alertas Waze que corre cada **3 horas** vía GitHub Actions.

---

## Estructura del proyecto

```
tu-repo/
├── collector.py                          # Script principal
├── data/
│   ├── waze_partnerhub.json              # BD incremental — Opción 1
│   └── waze_openwebninja.json            # BD incremental — Opción 2 (fallback)
└── .github/
    └── workflows/
        └── waze_collector.yml            # Workflow de GitHub Actions
```

---

## Paso a paso para montar en GitHub

### PASO 1 — Crear el repositorio

1. Ve a [github.com/new](https://github.com/new)
2. Dale un nombre (ej: `waze-cartagena-collector`)
3. Déjalo **privado** (contiene credenciales de API)
4. Haz clic en **Create repository**

---

### PASO 2 — Subir los archivos

```bash
# Clona tu nuevo repo vacío
git clone https://github.com/TU_USUARIO/waze-cartagena-collector.git
cd waze-cartagena-collector

# Copia los archivos:
#   collector.py → raíz del repo
#   .github/workflows/waze_collector.yml → en esa ruta exacta

mkdir -p data .github/workflows

# Pega los archivos y luego:
git add .
git commit -m "feat: setup inicial waze collector"
git push
```

---

### PASO 3 — Configurar los Secrets

Los Secrets son variables de entorno **cifradas** que GitHub Actions inyecta al correr el script.

1. Ve a tu repo → **Settings** → **Secrets and variables** → **Actions**
2. Haz clic en **New repository secret** para cada uno:

| Nombre del Secret        | Valor                                                                 | Obligatorio |
|--------------------------|-----------------------------------------------------------------------|-------------|
| `WAZE_PARTNER_URL`       | La URL completa del Partner Hub (la del `?format=1`)                  | Sí          |
| `OPENWEBNINJA_API_KEY`   | Tu API key de OpenWebNinja (`ak_29d1gn2u8dtu3va7l24ap0qj7inshdvuvgeycj8drp96jxy`) | Solo si usas fallback |

> **Nota:** Si la URL del Partner Hub es pública puedes dejarla también hardcodeada en el script como valor por defecto. Los Secrets tienen prioridad sobre el valor por defecto.

---

### PASO 4 — Verificar permisos del workflow

GitHub Actions necesita permiso para hacer `git push`:

1. Ve a **Settings** → **Actions** → **General**
2. Baja hasta **Workflow permissions**
3. Selecciona: ✅ **Read and write permissions**
4. Haz clic en **Save**

---

### PASO 5 — Ejecutar manualmente (prueba)

Antes de esperar 3 horas:

1. Ve a la pestaña **Actions** de tu repo
2. Selecciona **Waze Alerts Collector** en el panel izquierdo
3. Haz clic en **Run workflow** → **Run workflow**
4. Observa los logs en tiempo real

Si todo está bien, verás algo como:
```
[OPCIÓN 1] ✓ Respuesta OK — 12 alertas + 3 jams
[STORE] ✓ Guardado: data/waze_partnerhub.json  (15 registros totales)
[RUN] Opción 1: ✓ OK
```

---

## Estructura de los archivos JSON generados

```json
{
  "meta": {
    "created_at":    "2025-05-02T10:00:00+00:00",
    "last_updated":  "2025-05-02T13:00:00+00:00",
    "total_records": 47,
    "source":        "data/waze_partnerhub.json"
  },
  "records": {
    "uuid-o-hash-único": {
      "uuid":           "abc-123",
      "type":           "WEATHERHAZARD",
      "subtype":        "HAZARD_ON_ROAD_OBJECT",
      "location":       { "x": -75.5144, "y": 10.3997 },
      "pubMillis":      1714640000000,
      "_collected_at":  "2025-05-02T13:00:00+00:00",
      "_record_id":     "abc-123"
    }
  }
}
```

**Puntos clave:**
- `records` es un **diccionario keyed por ID** → inserción O(1) + deduplicación automática
- `_collected_at` marca cuándo fue capturada la alerta
- `_record_id` es el UUID de Waze (si existe) o un hash MD5 de campos clave
- Los registros **nunca se borran** → base de datos histórica

---

## Lógica de fallback

```
┌─────────────────────────────────────────────────┐
│                   collector.py                   │
│                                                  │
│  Intenta Opción 1 (Partner Hub)                  │
│       │                                          │
│       ├── ✓ Responde (con o sin alertas)         │
│       │       └─→ Guarda en waze_partnerhub.json │
│       │                                          │
│       └── ✗ Falla (timeout / HTTP error)         │
│               └─→ Intenta Opción 2 (OpenWebNinja)│
│                       │                          │
│                       ├── ✓ Responde             │
│                       │   └─→ Guarda en          │
│                       │       waze_openwebninja.json│
│                       └── ✗ Falla                │
│                           └─→ Exit code 1 🔴     │
└─────────────────────────────────────────────────┘
```

---

## Frecuencia del cron

El cron `0 */3 * * *` corre en UTC. En hora Colombia (UTC-5):

| UTC  | Colombia |
|------|----------|
| 0:00 | 19:00 día anterior |
| 3:00 | 22:00 |
| 6:00 | 1:00   |
| 9:00 | 4:00   |
| 12:00| 7:00   |
| 15:00| 10:00  |
| 18:00| 13:00  |
| 21:00| 16:00  |

Para ajustar a horario Colombia, puedes cambiar el cron. Por ejemplo solo en horas laborales (7am–7pm COT = 12:00–00:00 UTC):
```yaml
- cron: "0 12,15,18,21,0 * * *"
```

---

## Solución de problemas comunes

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| `403 Forbidden` en Opción 1 | URL del Partner Hub venció | Actualizar `WAZE_PARTNER_URL` en Secrets |
| `401 Unauthorized` en Opción 2 | API Key incorrecta | Verificar `OPENWEBNINJA_API_KEY` |
| El workflow no hace push | Permisos insuficientes | Activar "Read and write" en Settings → Actions |
| JSON crece demasiado | Muchas alertas históricas | Añadir limpieza por fecha en `merge_alerts()` |
| `Exit code 1` en el job | Ambas fuentes fallaron | Revisar logs y conectividad de las APIs |
