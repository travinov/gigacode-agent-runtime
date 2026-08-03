"""Restricted YAML loader with YAML 1.2-style boolean semantics."""

from __future__ import annotations

import re

import yaml


class RuntimeSafeLoader(yaml.SafeLoader):
    """SafeLoader where only true/false are implicit booleans.

    PyYAML otherwise applies YAML 1.1 and silently turns keys such as ``on``
    into ``True``, which breaks the public scenario retry contract.
    """


RuntimeSafeLoader.yaml_implicit_resolvers = {
    first: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:bool"
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
RuntimeSafeLoader.add_implicit_resolver(  # type: ignore[no-untyped-call]
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def safe_load(text: str) -> object:
    return yaml.load(text, Loader=RuntimeSafeLoader)
