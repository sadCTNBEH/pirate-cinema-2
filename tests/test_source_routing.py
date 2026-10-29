import asyncio

def test_yummy_client_disables_environment(monkeypatch):
    import httpx
    from backend.infrastructure.catalog.yummyanime import YummyAnimeProvider
    real_client = httpx.AsyncClient
    captured = {}
    def client(**kwargs):
        captured.update(kwargs)
        return real_client(**kwargs, transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'response':[]})))
    monkeypatch.setenv('HTTPS_PROXY','http://not-used:9999')
    monkeypatch.setattr('backend.infrastructure.catalog.yummyanime.httpx.AsyncClient',client)
    assert asyncio.run(YummyAnimeProvider('public-test').fetch()) == []
    assert captured['trust_env'] is False


def test_torrserver_uses_direct_client(monkeypatch):
    from backend.infrastructure.torrserver import client
    import httpx
    captured={}
    real=httpx.AsyncClient
    def create(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(client.httpx,'AsyncClient',create)
    monkeypatch.setattr(client,'_client',None)
    async def run():
        current=client.get_client()
        await current.aclose()
    asyncio.run(run())
    assert captured['trust_env'] is False
