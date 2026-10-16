# The property register as a container image.
#
#   docker build -t nsm-property-register .
#   docker run --rm -p 127.0.0.1:8000:8000 --env-file .env nsm-property-register
#
# With DATABASE_URL (and the Supabase Storage settings) from --env-file it runs
# on Supabase; without them, on SQLite in /app/data, which a volume keeps:
#   docker run --rm -p 127.0.0.1:8000:8000 -v register-data:/app/data nsm-property-register
#
# The register has no login yet: publish the port on 127.0.0.1 as above, never
# on a public interface.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
# pip is only needed to build the image. Removing it also removes the copies of
# urllib3, msgpack and setuptools code it bundles, which vulnerability scanners
# flag even though the register never runs them.
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
    && pip uninstall --yes --root-user-action=ignore pip

COPY server/ server/
COPY web/ web/
RUN useradd --system --home-dir /app register \
    && mkdir data \
    && chown register data
USER register

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/reference', timeout=4)"]
# Inside the container it must listen on every interface; -p decides who can reach it.
CMD ["python", "-m", "server.app", "--host", "0.0.0.0", "--port", "8000"]
