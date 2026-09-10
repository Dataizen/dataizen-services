# Image outil « terrain » : fabrique une tuile relief PMTiles (terrain-RGB, encodage
# mapbox) pour une commune, depuis le MNT RGE ALTI de la Géoplateforme IGN, et la
# publie comme ressource CKAN. Chaîne : WMS GeoTIFF -> fillnodata (rasterio) ->
# gdalwarp 3857 -> rio-rgbify -> pmtiles convert -> CKAN. Tout tourne ici.
#
# Versions épinglées : rio-rgbify 0.4.0 exige rasterio 1.3.x + numpy<2, et son
# mbtiler.py appelle transform_bounds avec densify_pts=0 (plante « densify_pts must
# be at least 2 » en sortie géographique), corrigé par sed. Base python 3.11 stable.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      gdal-bin libexpat1 curl ca-certificates jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "numpy<2" "rasterio==1.3.6" "rio-rgbify==0.4.0" "pyproj>=3.6"
RUN sed -i "s/densify_pts=0/densify_pts=21/" \
      /usr/local/lib/python3.11/site-packages/rio_rgbify/mbtiler.py

ARG PMTILES_VER=1.28.0
RUN arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64) A=x86_64;; arm64) A=arm64;; *) A="$arch";; esac; \
    curl -sL "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VER}/go-pmtiles_${PMTILES_VER}_Linux_${A}.tar.gz" \
      | tar xz -C /usr/local/bin pmtiles && chmod +x /usr/local/bin/pmtiles

COPY gen-terrain.sh /usr/local/bin/gen-terrain.sh
RUN chmod +x /usr/local/bin/gen-terrain.sh
ENTRYPOINT ["/usr/local/bin/gen-terrain.sh"]
