"""Cliente HTTP único para todas las fuentes.

Centraliza las reglas de buen comportamiento: User-Agent identificable, robots.txt,
pausa mínima por host (nunca en paralelo), reintentos con espera y caché en disco.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import threading
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

REINTENTABLES = {406, 429, 500, 502, 503, 504}


class BloqueadoPorRobots(Exception):
    pass


def _resuelve(host: str, timeout: float) -> bool:
    """getaddrinfo en un hilo aparte: un DNS colgado no debe congelar la corrida."""
    ok = []

    def _resolver():
        try:
            ok.append(bool(socket.getaddrinfo(host, 443)))
        except OSError:
            pass

    hilo = threading.Thread(target=_resolver, daemon=True)
    hilo.start()
    hilo.join(timeout)
    return bool(ok)


class Cliente:
    def __init__(self, config, usar_cache: bool = True):
        h = config["http"]
        self.timeout = h["timeout_s"]
        self.timeout_dns = h.get("timeout_dns_s", 15)
        self._dns_ok: set[str] = set()
        self.pausa = h["pausa_por_host_s"]
        self.espera_reintento = h["espera_reintento_s"]
        self.reintentos = h["reintentos"]
        self.ttl = h["cache_ttl_h"] * 3600
        self.excepciones_robots = h.get("robots_excepciones") or {}
        self.dir_cache: Path = config.ruta("cache") / "http"
        self.dir_cache.mkdir(parents=True, exist_ok=True)
        self.usar_cache = usar_cache
        self.ua = config["proyecto"]["user_agent"]
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = self.ua
        self._ultimo_pedido: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # --- robots.txt ---------------------------------------------------------
    def permitido(self, url: str) -> bool:
        host = urlsplit(url).netloc
        self._verificar_dns(host)
        if host in self.excepciones_robots:
            return True
        if host not in self._robots:
            self._robots[host] = self._leer_robots(url)
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(self.ua, url)

    def _leer_robots(self, url: str):
        p = urlsplit(url)
        rp = urllib.robotparser.RobotFileParser()
        try:
            self._esperar_turno(p.netloc)
            r = self.sesion.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=20)
        except requests.RequestException:
            return None  # sin robots.txt accesible: se permite, como hacen los crawlers estándar
        if r.status_code in (401, 403):
            rp.disallow_all = True
        elif r.status_code >= 400:
            rp.allow_all = True
        else:
            rp.parse(r.text.splitlines())
        return rp

    # --- pedidos -----------------------------------------------------------
    def _verificar_dns(self, host: str):
        if host in self._dns_ok:
            return
        if not _resuelve(host.split(":")[0], self.timeout_dns):
            raise requests.ConnectionError(f"DNS de {host} no respondió en {self.timeout_dns} s")
        self._dns_ok.add(host)

    def _esperar_turno(self, host: str):
        espera = self._ultimo_pedido.get(host, 0) + self.pausa - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._ultimo_pedido[host] = time.monotonic()

    def _clave(self, metodo: str, url: str, datos) -> Path:
        h = hashlib.sha256(json.dumps([metodo, url, datos], sort_keys=True).encode()).hexdigest()[:32]
        return self.dir_cache / h

    def pedir(self, url: str, metodo: str = "GET", datos=None, ttl: float | None = None,
              timeout: float | None = None) -> requests.Response | "RespuestaCache":
        """Devuelve la respuesta (de red o de caché). Lanza excepción si falla tras reintentos."""
        if not self.permitido(url):
            raise BloqueadoPorRobots(f"robots.txt no permite {url}")
        ttl = self.ttl if ttl is None else ttl
        clave = self._clave(metodo, url, datos)
        if self.usar_cache and clave.exists() and time.time() - clave.stat().st_mtime < ttl:
            return RespuestaCache(clave.read_bytes(), url)

        host = urlsplit(url).netloc
        ultimo_error = None
        for intento in range(self.reintentos + 1):
            if intento:
                log.warning("Reintento %d para %s en %d s", intento, host, self.espera_reintento)
                time.sleep(self.espera_reintento)
            self._esperar_turno(host)
            try:
                r = self.sesion.request(metodo, url, data=datos, timeout=timeout or self.timeout)
            except requests.RequestException as e:
                ultimo_error = e
                continue
            if r.status_code in REINTENTABLES:
                ultimo_error = requests.HTTPError(f"HTTP {r.status_code} en {url}", response=r)
                continue
            r.raise_for_status()
            if self.usar_cache:
                clave.write_bytes(r.content)
            return r
        raise ultimo_error


class RespuestaCache:
    """Imita lo mínimo de requests.Response que usan las fuentes."""

    status_code = 200

    def __init__(self, content: bytes, url: str):
        self.content = content
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)
