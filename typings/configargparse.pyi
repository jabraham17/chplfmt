"""Minimal type stubs for the parts of configargparse that chplfmt uses."""

import argparse
import os
from collections.abc import Callable, Mapping, Sequence
from typing import IO, Any

class ConfigFileParserException(Exception): ...

class ConfigFileParser:
    def parse(self, stream: IO[str]) -> dict[str, Any]: ...

class YAMLConfigFileParser(ConfigFileParser): ...

class TomlConfigParser(ConfigFileParser):
    def __init__(self, sections: Sequence[str]) -> None: ...
    def __call__(self) -> TomlConfigParser: ...

class CompositeConfigParser(ConfigFileParser):
    def __init__(
        self,
        config_parser_types: Sequence[
            type[ConfigFileParser] | Callable[[], ConfigFileParser]
        ],
    ) -> None: ...
    def __call__(self) -> CompositeConfigParser: ...

class ArgumentParser(argparse.ArgumentParser):
    def __init__(
        self,
        *args: Any,
        default_config_files: Sequence[str] = ...,
        config_file_parser_class: ConfigFileParser | type[ConfigFileParser] = ...,
        args_for_setting_config_path: Sequence[str] = ...,
        config_arg_help_message: str = ...,
        **kwargs: Any,
    ) -> None: ...
    def parse_args(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
        config_file_contents: str | None = None,
        env_vars: Mapping[str, str] = os.environ,
    ) -> argparse.Namespace: ...
    def get_possible_config_keys(self, action: argparse.Action) -> list[str]: ...
    def get_command_line_key_for_unknown_config_file_setting(self, key: str) -> str: ...

ArgParser = ArgumentParser
