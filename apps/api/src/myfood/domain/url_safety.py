"""Protección básica contra SSRF (sección 20 — importar una receta implica
descargar una URL que el propio usuario da, así que el servidor nunca debe
poder usarse para tocar redes internas: localhost, IPs privadas, el
enlace local de metadatos de nube, etc.).

Solo esquemas http/https; se resuelve el hostname y se rechaza si
CUALQUIER IP resuelta es privada/loopback/enlace-local/reservada/
multicast. Limitación reconocida: esto comprueba la resolución en el
momento de la llamada, no fija la conexión a esa IP exacta — una respuesta
DNS distinta entre esta comprobación y la descarga real (DNS rebinding)
no quedaría cubierta. Para el contexto de esta app (autoalojada, uso
personal/familiar, no multi-inquilino de cara a internet) es una mitigación
proporcionada, no a prueba de balas — documentado aquí en vez de fingir
que sí lo es.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(Exception):
    pass


def ensure_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Solo se admiten URLs http/https.")
    if not parsed.hostname:
        raise UnsafeUrlError("La URL no tiene un host válido.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError("No se ha podido resolver ese dominio.") from exc

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
