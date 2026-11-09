"""llm-on-a-stick: one eval harness, many LLMs. Start poking."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("llm-on-a-stick")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.6.0"
