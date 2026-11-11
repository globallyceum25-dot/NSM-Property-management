# The property register as a container image.
#
#   docker build -t nsm-property-register .
#   docker run --rm -p 127.0.0.1:8000:8000 --env-file .env nsm-property-register
#
# With DATABASE_URL (and the Supabase Storage settings) from --env-file it runs
# on Supabase; without them, on SQLite in /app/data, which a volume keeps:
#   docker run --rm -p 127.0.0.1:8000:8000 -v register-data:/app/data nsm-property-register
#
# Everyone signs in. On first start the log prints a one-time setup code for
# creating the first Super Admin at /login; or set REGISTER_ADMIN_EMAIL,
# REGISTER_ADMIN_PASSWORD (and REGISTER_ADMIN_NAME) to create it at start-up.
# Behind HTTPS, set REGISTER_SECURE_COOKIES=1. Publish the port on 127.0.0.1
# as above and put a TLS proxy in front, rather than serving plain HTTP publicly.
FROM python:3.13-slim

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
