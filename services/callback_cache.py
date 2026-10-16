
from collections import OrderedDict
from copy import deepcopy
import secrets


MAX_CACHE_ITEMS = 5000

_repository_cache: OrderedDict[str, str] = OrderedDict()
_release_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()
_readme_cache: OrderedDict[
    str, tuple[str, str, str | None]
] = OrderedDict()
_search_cache: OrderedDict[str, list[dict]] = OrderedDict()

_repository_search_cache: OrderedDict[str, str] = OrderedDict()
_repository_token_by_name: dict[str, str] = {}


def _store(cache: OrderedDict, value) -> str:
    """Store a value and return a short, unique token."""
    token = secrets.token_urlsafe(6)

    while token in cache:
        token = secrets.token_urlsafe(6)

    cache[token] = value
    cache.move_to_end(token)

    while len(cache) > MAX_CACHE_ITEMS:
        expired_token, expired_value = cache.popitem(last=False)

        if cache is _repository_cache:
            full_name = expired_value

            if _repository_token_by_name.get(full_name) == expired_token:
                _repository_token_by_name.pop(full_name, None)

            _repository_search_cache.pop(expired_token, None)

        elif cache is _search_cache:
            expired_links = [
                repo_token
                for repo_token, search_token
                in _repository_search_cache.items()
                if search_token == expired_token
            ]

            for repo_token in expired_links:
                _repository_search_cache.pop(repo_token, None)

    return token


def _get(cache: OrderedDict, token: str):
    """Retrieve a cached value and refresh its LRU position."""
    value = cache.get(token)

    if value is not None:
        cache.move_to_end(token)

    return value


def store_repository(full_name: str) -> str:
    existing_token = _repository_token_by_name.get(full_name)

    if (
        existing_token
        and _repository_cache.get(existing_token) == full_name
    ):
        _repository_cache.move_to_end(existing_token)
        return existing_token

    token = _store(_repository_cache, full_name)
    _repository_token_by_name[full_name] = token
    return token


def get_repository(token: str) -> str | None:
    return _get(_repository_cache, token)


def store_release(full_name: str, tag: str) -> str:
    return _store(_release_cache, (full_name, tag))


def get_release(token: str) -> tuple[str, str] | None:
    return _get(_release_cache, token)


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
    return _get(_readme_cache, token)


def store_search_results(repositories: list[dict]) -> str:
    """Cache the complete result list for use across all pages."""
    return _store(_search_cache, deepcopy(repositories))


def get_search_results(token: str) -> list[dict] | None:
    """Return cached results without exposing the cache's internal list."""
    repositories = _get(_search_cache, token)

    if repositories is None:
        return None

    return deepcopy(repositories)


def link_repository_to_search(
    repository_token: str,
    search_token: str,
) -> None:
    if repository_token not in _repository_cache:
        return

    if search_token not in _search_cache:
        return

    _repository_search_cache[repository_token] = search_token
    _repository_search_cache.move_to_end(repository_token)

    while len(_repository_search_cache) > MAX_CACHE_ITEMS:
        _repository_search_cache.popitem(last=False)


def get_repository_search(repository_token: str) -> str | None:
    search_token = _repository_search_cache.get(repository_token)

    if search_token is None:
        return None

    if repository_token not in _repository_cache:
        _repository_search_cache.pop(repository_token, None)
        return None

    if search_token not in _search_cache:
        _repository_search_cache.pop(repository_token, None)
        return None

    _repository_search_cache.move_to_end(repository_token)
    return search_token
