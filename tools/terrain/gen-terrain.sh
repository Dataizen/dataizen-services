#!/usr/bin/env bash
# Fabrique la tuile relief PMTiles d'une commune (terrain-RGB mapbox) depuis le MNT
# RGE ALTI de la Géoplateforme IGN, et la publie comme ressource CKAN. Idempotent :
# rejoué, il remplace la ressource en place (même id, l'URL terrain_url ne change pas).
#
# Usage : gen-terrain.sh <insee> <org> <ckan_url> <ckan_token> [resolution_m]
#   insee        code INSEE de la commune (ex. 91471)
#   org          organisation CKAN propriétaire du jeu (ex. paris-saclay)
#   ckan_url     ex. https://data.core.dataizen.eu
#   ckan_token   jeton d'API CKAN (droits d'écriture sur l'organisation)
#   resolution_m résolution du MNT en mètres (défaut 5 ; 1 = natif, plus lourd)
#
# Sortie (dernière ligne) : TERRAIN_URL=<url de téléchargement de la ressource PMTiles>
set -euo pipefail

INSEE="${1:?insee requis}"
ORG="${2:?org requise}"
CKAN="${3:?ckan_url requis}"
TOKEN="${4:?ckan_token requis}"
RES="${5:-5}"

echo "== $(date -Is) relief commune $INSEE (org $ORG, résolution ${RES} m)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT; cd "$WORK"

# 1. contour + nom de la commune (Découpage administratif)
curl -sf "https://geo.api.gouv.fr/communes/${INSEE}?geometry=contour&format=geojson&fields=nom,contour" -o commune.geojson
NOM="$(python3 -c "import json;print(json.load(open('commune.geojson'))['properties']['nom'])")"
echo "commune : $NOM"

# 2. emprise WGS84 -> Lambert-93, dimensions en pixels à la résolution demandée.
#    IGN WMS limite la taille : on plafonne à 9000 px (sinon on dégrade la résolution).
read MINX MINY MAXX MAXY W H BW BS BE BN RES < <(python3 - "$RES" <<'PY'
import json, sys
from pyproj import Transformer
res = float(sys.argv[1])
gj = json.load(open('commune.geojson'))
def coords(g):
    t = g['type']; c = g['coordinates']
    if t == 'Polygon': rings = c
    elif t == 'MultiPolygon': rings = [r for poly in c for r in poly]
    else: rings = []
    for ring in rings:
        for x, y in ring:
            yield x, y
lons = [x for x, y in coords(gj['geometry'])]; lats = [y for x, y in coords(gj['geometry'])]
minlon, maxlon, minlat, maxlat = min(lons), max(lons), min(lats), max(lats)
tr = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform
xs, ys = [], []
for lon, lat in [(minlon,minlat),(maxlon,minlat),(maxlon,maxlat),(minlon,maxlat)]:
    x, y = tr(lon, lat); xs.append(x); ys.append(y)
minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
w = (maxx-minx); h = (maxy-miny)
px_w, px_h = int(round(w/res)), int(round(h/res))
cap = 9000
if max(px_w, px_h) > cap:
    res = res * max(px_w, px_h) / cap
    px_w, px_h = int(round(w/res)), int(round(h/res))
print(f"{minx:.2f} {miny:.2f} {maxx:.2f} {maxy:.2f} {px_w} {px_h} "
      f"{minlon:.6f} {minlat:.6f} {maxlon:.6f} {maxlat:.6f} {res:.2f}")
PY
)
CLON="$(python3 -c "print(round(($BW+$BE)/2,6))")"
CLAT="$(python3 -c "print(round(($BS+$BN)/2,6))")"
echo "emprise L93 : $MINX,$MINY,$MAXX,$MAXY  ->  ${W}x${H} px (${RES} m)"

# 3. MNT GeoTIFF 32 bits (WMS raster Géoplateforme, RGE ALTI haute résolution)
echo "téléchargement du MNT RGE ALTI..."
curl -sf --max-time 600 -o dem.tif \
  "https://data.geopf.fr/wms-r/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES&STYLES=&CRS=EPSG:2154&FORMAT=image/geotiff&WIDTH=${W}&HEIGHT=${H}&BBOX=${MINX},${MINY},${MAXX},${MAXY}"

# 4. comblement des trous (rasterio.fill) puis reprojection Web Mercator (gdalwarp)
python3 - <<'PY'
import rasterio, numpy as np
from rasterio.fill import fillnodata
with rasterio.open('dem.tif') as src:
    arr = src.read(1).astype('float32'); prof = src.profile
    nod = src.nodata
    valid = np.ones(arr.shape, 'uint8') if nod is None else (arr != nod).astype('uint8')
    # marque aussi les valeurs aberrantes (hors [-500, 5000] m) comme à combler
    valid[(arr < -500) | (arr > 5000)] = 0
    if valid.min() == 0:
        arr = fillnodata(arr, mask=valid, max_search_distance=30)
    prof.update(dtype='float32', count=1, nodata=None)
    with rasterio.open('filled.tif', 'w', **prof) as dst:
        dst.write(arr, 1)
print('MNT', arr.shape, 'min %.1f max %.1f' % (float(arr.min()), float(arr.max())))
PY
gdalwarp -q -overwrite -t_srs EPSG:3857 -r bilinear -dstnodata 0 filled.tif dem3857.tif

# 5. terrain-RGB (encodage mapbox : base -10000, intervalle 0,1 m), pyramide z10-15
rm -f terrain.mbtiles
rio rgbify -b -10000 -i 0.1 -j 4 --min-z 10 --max-z 15 --format png dem3857.tif terrain.mbtiles

# 6. métadonnées mbtiles (encodage mapbox + emprise WGS84), indispensables au client
python3 - "$NOM" "$BW,$BS,$BE,$BN" "$CLON,$CLAT" <<'PY'
import sqlite3, sys
nom, bounds, center = sys.argv[1], sys.argv[2], sys.argv[3]
c = sqlite3.connect("terrain.mbtiles")
c.execute("CREATE TABLE IF NOT EXISTS metadata(name text, value text)")
c.execute("DELETE FROM metadata")
meta = {"name": f"relief-{nom}", "format": "png", "minzoom": "10", "maxzoom": "15",
        "bounds": bounds, "center": f"{center},13", "type": "baselayer", "encoding": "mapbox",
        "description": f"MNT RGE ALTI {nom}, terrain-RGB mapbox, base -10000, intervalle 0.1 m"}
for k, v in meta.items():
    c.execute("INSERT INTO metadata(name,value) VALUES(?,?)", (k, v))
c.commit(); c.close()
PY

# 7. conversion PMTiles
rm -f terrain.pmtiles
pmtiles convert terrain.mbtiles terrain.pmtiles >/dev/null
SIZE="$(stat -c%s terrain.pmtiles)"
echo "PMTiles : $SIZE octets"

# 8. publication CKAN (jeu par commune, ressource PMTiles remplacée en place)
SLUG="relief-terrain-${INSEE}"
api() { curl -sf -H "Authorization: ${TOKEN}" "${CKAN}/api/3/action/$1" "${@:2}"; }
NOTES="Relief 3D (tuiles PMTiles terrain-RGB, encodage mapbox) de la commune de ${NOM} (${INSEE}), généré depuis le MNT RGE ALTI de la Géoplateforme IGN (couche ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES). À utiliser dans le champ Relief (terrain_url) d'une carte du portail. Résolution du MNT : ${RES} m."
# jeu (création idempotente)
if ! api package_show "--get" --data-urlencode "id=${SLUG}" >/dev/null 2>&1; then
  api package_create -H 'Content-Type: application/json' -d "$(python3 -c "import json,sys;print(json.dumps({'name':sys.argv[1],'title':'Relief terrain '+sys.argv[2],'owner_org':sys.argv[3],'notes':sys.argv[4],'license_id':'lov2','extras':[{'key':'theme','value':'Territoire et occupation des sols'}]}))" "$SLUG" "$NOM" "$ORG" "$NOTES")" >/dev/null
else
  api package_patch -H 'Content-Type: application/json' -d "$(python3 -c "import json,sys;print(json.dumps({'id':sys.argv[1],'notes':sys.argv[2]}))" "$SLUG" "$NOTES")" >/dev/null || true
fi
# ressource PMTiles : remplacement en place si elle existe, sinon création
RID="$(api package_show "--get" --data-urlencode "id=${SLUG}" | python3 -c "import sys,json;rs=[r['id'] for r in json.load(sys.stdin)['result']['resources'] if (r.get('format') or '').upper()=='PMTILES'];print(rs[0] if rs else '')")"
if [ -n "$RID" ]; then
  api resource_update -F id="$RID" -F upload=@terrain.pmtiles -F format=PMTiles >/dev/null
else
  RID="$(api resource_create -F package_id="$SLUG" -F name="Relief ${NOM} (PMTiles terrain-RGB)" -F format=PMTiles -F upload=@terrain.pmtiles | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['id'])")"
fi
URL="${CKAN}/dataset/${SLUG}/resource/${RID}/download/terrain.pmtiles"
echo "== $(date -Is) terminé : ressource ${RID}"
echo "TERRAIN_URL=${URL}"
