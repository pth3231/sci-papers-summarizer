import asyncio

from src.services import generator


def test_get_client_returns_same_instance_until_closed():
    generator._client = None
    first = generator.get_client()
    second = generator.get_client()
    assert first is second
    asyncio.run(generator.aclose_client())


def test_aclose_client_resets_singleton():
    generator._client = None
    generator.get_client()
    asyncio.run(generator.aclose_client())
    assert generator._client is None
