FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 HAIC_STATE_DIR=/var/lib/haic
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt && useradd --uid 10001 --create-home app && mkdir -m 0700 /var/lib/haic && chown app:app /var/lib/haic
COPY --chown=root:root districtbrief ./districtbrief
COPY --chown=root:root static ./static
COPY --chown=root:root runtime-packet ./runtime-packet
COPY --chown=root:root candidate-metadata ./candidate-metadata
COPY --chown=root:root RELEASE-MANIFEST.json ./
COPY --chown=root:root tools/ia_language_operator.py ./tools/ia_language_operator.py
COPY --chown=root:root public_app.py wsgi.py gunicorn.conf.py ./
RUN chmod -R a+rX /app && chmod -R go-w /app
USER 10001:10001
EXPOSE 8080
VOLUME ["/var/lib/haic"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=3)"
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:application"]
