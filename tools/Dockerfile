# GNavi maps-build tools — xuất pack bản đồ theo tỉnh / cả nước
#
#   docker build -t gnavi-extract ./tools
#   docker run --rm -m 4g -v "%cd%:/data" gnavi-extract /app/roads.py ...
#
FROM python:3.11-slim-bookworm

COPY requirements.txt /tmp/requirements.txt
RUN apt-get update \
 && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
ENV PYTHONPATH=/app

COPY requirements.txt /app/
COPY lib /app/lib
COPY regions /app/regions
COPY roads /app/roads
COPY routing /app/routing
COPY search /app/search
COPY regions.py roads.py routing.py search.py traffic_lights.py \
     enhance_speed_limit.py enhance_spds.py /app/

WORKDIR /data
ENTRYPOINT ["python"]
CMD ["/app/roads.py", "--help"]
