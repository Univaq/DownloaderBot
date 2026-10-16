
from collections import OrderedDict
import secrets


MAX_CACHE_ITEMS = 5000

_repository_cache: OrderedDict[str, str] = OrderedDict()
_release_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()
_readme_cache: OrderedDict[
    str, tuple[str, str, str | None]
] = OrderedDict()
_search_cache: OrderedDict[str, list[dict]] = OrderedDict()
_repository_search_cache: dict[str, str] = {}
_repository_token_by_name: dict[str, str] = {}

def _store(
    cache: OrderedDict,
    value,
) -> str:
    token = secrets.token_urlsafe(6)

    while token in cache:
        token = secrets.token_urlsafe(6)

    cache[token] = value
    cache.move_to_end(token)

    while len(cache) > MAX_CACHE_ITEMS:
        cache.popitem(last=False)

    return token


def store_repository(full_name: str) -> str:
    existing_token = _repository_token_by_name.get(full_name)

    if existing_token and _repository_cache.get(existing_token) == full_name:
        _repository_cache.move_to_end(existing_token)
        return existing_token

    token = _store(_repository_cache, full_name)
    _repository_token_by_name[full_name] = token
    return token


def get_repository(token: str) -> str | None:
    return _repository_cache.get(token)


def store_release(full_name: str, tag: str) -> str:
    return _store(_release_cache, (full_name, tag))


def get_release(token: str) -> tuple[str, str] | None:
    return _release_cache.get(token)


def store_readme(
    full_name: str,
    path: str,
    download_url: str | None,
) -> str:
    return _store(
        _readme_cache,
        (full_name, path, download_url),
    )


def get_readme(
    token: str,
) -> tuple[str, str, str | None] | None:
    return _readme_cache.get(token)

def store_search_results(repositories: list[dict]) -> str:
    token = _store(_search_cache, repositories)
    return token


def get_search_results(token: str) -> list[dict] | None:
    results = _search_cache.get(token)

    if results is None:
        return None

    _search_cache.move_to_end(token)
    return results


def link_repository_to_search(
    repository_token: str,
    search_token: str,
) -> None:
    _repository_search_cache[repository_token] = search_token

    while len(_repository_search_cache) > MAX_CACHE_ITEMS:
        oldest_token = next(iter(_repository_search_cache))
        del _repository_search_cache[oldest_token]


def get_repository_search(repository_token: str) -> str | None:
    return _repository_search_cache.get(repository_token)