"""v1.4.7: MiMo v2.x (the default model) reads images without model.vision: true."""

import pytest

from neovarch import uploads


@pytest.fixture(autouse=True)
def _clean_meta():
    uploads.MODEL_VISION_META.clear()
    yield
    uploads.MODEL_VISION_META.clear()


@pytest.mark.parametrize("model", [
    "oc/mimo-v2.6-flash-free", "mimo/mimo-v2.6-pro", "mimo/mimo-v2.5", "mimo-v2.6-flash", "MiMo-V2.5-Pro",
    "openrouter/xiaomi/mimo-v2.6-flash:free",
])
def test_mimo_v2_is_vision(model):
    assert uploads.supports_vision({}, {"model": model, "provider": "9router"}) is True


def test_explicit_config_still_wins():
    cfg = {"model": {"vision": False}}
    assert uploads.supports_vision(cfg, {"model": "oc/mimo-v2.6-flash-free"}) is False


def test_text_only_model_stays_text():
    assert uploads.supports_vision({}, {"model": "ds/deepseek-v3.2"}) is False


@pytest.mark.parametrize("row,expected", [
    ({"id": "x/a", "input_modalities": ["text", "image"]}, True),
    ({"id": "x/b", "architecture": {"input_modalities": ["text"]}}, False),
    ({"id": "x/c", "architecture": {"modality": "text+image->text"}}, True),
    ({"id": "x/d", "capabilities": {"vision": True}}, True),
    ({"id": "x/e", "capabilities": ["tools", "vision"]}, True),
    ({"id": "x/f", "supports_vision": False}, False),
    ({"id": "x/g", "owned_by": "x"}, None),
])
def test_vision_from_meta(row, expected):
    assert uploads.vision_from_meta(row) is expected


def test_router_models_metadata_enables_unknown_name():
    ep = {"model": "zz/new-omni-1", "provider": "9router"}
    assert uploads.supports_vision({}, ep) is False
    uploads.remember_model_meta([{"id": "zz/new-omni-1", "input_modalities": ["text", "image"]},
                                 {"id": "zz/plain", "input_modalities": ["text"]}, {"id": "zz/unknown"}])
    assert uploads.supports_vision({}, ep) is True
    assert uploads.MODEL_VISION_META == {"zz/new-omni-1": True, "zz/plain": False}
    # metadata only adds: a known vision family is not switched off by a terse listing
    uploads.remember_model_meta([{"id": "oc/mimo-v2.6-flash-free", "input_modalities": ["text"]}])
    assert uploads.supports_vision({}, {"model": "oc/mimo-v2.6-flash-free"}) is True


async def test_catalog_fetch_records_metadata(home, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from neovarch import config as cfgmod
    from neovarch import models as modelsmod

    async def listing(_request):
        return web.json_response({"data": [{"id": "zz/eye", "architecture": {"input_modalities": ["text", "image"]}}]})

    app = web.Application()
    app.router.add_get("/v1/models", listing)
    server = TestServer(app)
    await server.start_server()
    try:
        cfg = cfgmod.load_config()
        cfg.setdefault("router9", {})["url"] = str(server.make_url("/v1"))
        monkeypatch.setenv("NEOVARCH_9ROUTER_URL", str(server.make_url("/v1")))
        cat = modelsmod.ModelCatalog()
        await cat.fetch(cfg, force=True)
        assert uploads.MODEL_VISION_META.get("zz/eye") is True
    finally:
        await server.close()
