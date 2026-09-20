"""`_fetch_html` (importación de recetas) ante SSRF por redirección y DNS rebinding.

Antes seguía redirecciones con `follow_redirects=True` sin comprobar el destino: una
página pública podía redirigir al servidor a `http://169.254.169.254/...` (metadatos de
nube) o a cualquier red interna. Ahora se valida cada salto y se conecta a la IP ya
validada. Se usa `httpx.MockTransport` (sin red) y se simula la resolución de nombres."""

import httpx
import pytest

from myfood.ai.flows import recipe_import as flow
from myfood.domain.url_safety import UnsafeUrlError
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio

_PUBLIC = {"recetas.example": "93.184.216.34", "otra.example": "93.184.216.35"}


def _fake_resolve(url: str) -> str:
    host = httpx.URL(url).host
    if host in _PUBLIC:
        return _PUBLIC[host]
    raise UnsafeUrlError("Esa URL apunta a una red privada o reservada.")


@pytest.fixture
def requests_seen(monkeypatch):
    seen: list[httpx.Request] = []
    monkeypatch.setattr(flow, "resolve_public_ip", _fake_resolve)
    return seen


def _install(monkeypatch, seen, handler):
    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        flow.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(_handler), **kwargs),
    )


async def test_a_plain_page_is_fetched_from_the_validated_ip_with_the_original_host(
    monkeypatch, requests_seen
):
    _install(monkeypatch, requests_seen, lambda r: httpx.Response(200, text="<html>ok</html>"))

    html = await flow._fetch_html("https://recetas.example/tortilla?x=1")

    assert html == "<html>ok</html>"
    (request,) = requests_seen
    # Conecta a la IP validada, no al nombre (anti DNS rebinding)...
    assert request.url.host == "93.184.216.34"
    assert request.url.path == "/tortilla"
    # ...pero conserva el Host original y el SNI para que el certificado se verifique.
    assert request.headers["host"] == "recetas.example"
    assert request.extensions["sni_hostname"] == "recetas.example"


async def test_a_redirect_to_another_public_host_is_followed_and_revalidated(
    monkeypatch, requests_seen
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "recetas.example":
            return httpx.Response(302, headers={"location": "https://otra.example/final"})
        return httpx.Response(200, text="<html>final</html>")

    _install(monkeypatch, requests_seen, handler)

    assert await flow._fetch_html("https://recetas.example/start") == "<html>final</html>"
    assert [r.headers["host"] for r in requests_seen] == ["recetas.example", "otra.example"]


@pytest.mark.parametrize(
    "target",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/api/admin/ai/credential",
        "http://interno.lan/",
    ],
)
async def test_a_redirect_to_an_internal_address_is_refused_before_any_request_to_it(
    monkeypatch, requests_seen, target
):
    _install(
        monkeypatch,
        requests_seen,
        lambda r: httpx.Response(302, headers={"location": target}),
    )

    with pytest.raises(AppError) as exc_info:
        await flow._fetch_html("https://recetas.example/start")

    assert exc_info.value.code == "UNSAFE_URL"
    # Solo se llegó a pedir la primera página: al destino interno no se conectó.
    assert len(requests_seen) == 1


async def test_a_relative_redirect_is_resolved_against_the_current_page(
    monkeypatch, requests_seen
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/viejo":
            return httpx.Response(301, headers={"location": "/nuevo"})
        return httpx.Response(200, text="<html>nuevo</html>")

    _install(monkeypatch, requests_seen, handler)

    assert await flow._fetch_html("https://recetas.example/viejo") == "<html>nuevo</html>"
    assert requests_seen[1].url.path == "/nuevo"
    assert requests_seen[1].headers["host"] == "recetas.example"


async def test_a_redirect_loop_gives_up_with_a_clear_error(monkeypatch, requests_seen):
    _install(
        monkeypatch,
        requests_seen,
        lambda r: httpx.Response(302, headers={"location": "https://recetas.example/otra"}),
    )

    with pytest.raises(AppError) as exc_info:
        await flow._fetch_html("https://recetas.example/inicio")

    assert exc_info.value.code == "RECIPE_FETCH_FAILED"
    assert len(requests_seen) == flow._MAX_REDIRECTS + 1


async def test_the_first_url_is_also_validated_at_fetch_time(monkeypatch, requests_seen):
    """La comprobación al encolar y la descarga en el worker ocurren en momentos
    distintos: el destino se vuelve a validar al descargar."""
    _install(monkeypatch, requests_seen, lambda r: httpx.Response(200, text="x"))

    with pytest.raises(AppError) as exc_info:
        await flow._fetch_html("http://10.0.0.5/receta")

    assert exc_info.value.code == "UNSAFE_URL"
    assert requests_seen == []
