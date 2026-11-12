import pytest
from aiohttp import web

from .fakes import make_c411_app, make_plex_app, make_qbit_app


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    import custom_components.c411.api as api
    monkeypatch.setattr(api, "C411_MIN_REQUEST_INTERVAL", 0)


async def _start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


@pytest.fixture
async def servers(socket_enabled):
    state: dict = {}
    # base est connu après le démarrage : on l'injecte dans l'état partagé
    c_runner, c_base = await _start(make_c411_app(state))
    state["base"] = c_base
    q_runner, q_base = await _start(make_qbit_app(state, v5=True))
    state["qb_base"] = q_base
    p_runner, p_base = await _start(make_plex_app(state))
    state["plex_base"] = p_base
    yield state
    await c_runner.cleanup()
    await q_runner.cleanup()
    await p_runner.cleanup()
