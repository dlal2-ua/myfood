"""Protección básica contra SSRF (sección 20 — importar una receta implica
descargar una URL que el propio usuario da, así que el servidor nunca debe
poder usarse para tocar redes internas: localhost, IPs privadas, el
enlace local de metadatos de nube, etc.).

Solo esquemas http/https; se resuelve el hostname y se rechaza si
CUALQUIER IP resuelta es privada/loopback/enlace-local/reservada/
multicast. `ensure_public_http_url` solo comprueba (se usa al encolar, para dar un error
rápido al usuario); la descarga real usa `resolve_public_ip` y CONECTA a la IP
validada (ver `ai/flows/recipe_import.py::_fetch_html`), validando además cada
salto de una redirección — una página pública podía redirigir a
`http://169.254.169.254/...` y el cliente HTTP la seguía sin comprobar.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(Exception):
    pass


def resolve_public_ip(url: str) -> str:
    """Valida la URL y devuelve la IP pública a la que hay que conectar.

    Quien descargue debe conectar a ESA IP (no volver a resolver el nombre): así
    una respuesta DNS distinta entre la comprobación y la descarga (DNS
    rebinding) no puede llevar la petición a una red interna."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Solo se admiten URLs http/https.")
    if not parsed.hostname:
        raise UnsafeUrlError("La URL no tiene un host válido.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError("No se ha podido resolver ese dominio.") from exc

    safe_ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeUrlError("Esa URL apunta a una red privada o reservada.")
        safe_ips.append(str(ip))
    if not safe_ips:
        raise UnsafeUrlError("No se ha podido resolver ese dominio.")
    return safe_ips[0]


def ensure_public_http_url(url: str) -> None:
    resolve_public_ip(url)
