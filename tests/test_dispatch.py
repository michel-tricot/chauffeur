from dataclasses import dataclass

import pytest

from chauffeur.dispatch import CommandRegistry


@dataclass
class Args:
    x: int
    y: int


@dataclass
class Sum:
    total: int


@pytest.mark.asyncio
async def test_dataclass_params_and_result():
    reg = CommandRegistry()

    @reg.command()
    async def add(params: Args) -> Sum:
        return Sum(total=params.x + params.y)

    reply = await reg.dispatch({"id": "1", "command": "add", "params": {"x": 2, "y": 3}})
    assert reply == {"id": "1", "result": {"total": 5}}


@pytest.mark.asyncio
async def test_sync_handler_and_dict_params():
    reg = CommandRegistry()

    @reg.command("echo")
    def echo(params: dict):
        return params

    reply = await reg.dispatch({"id": "2", "command": "echo", "params": {"a": 1}})
    assert reply == {"id": "2", "result": {"a": 1}}


@pytest.mark.asyncio
async def test_no_param_handler():
    reg = CommandRegistry()

    @reg.command
    def ping():
        return "pong"

    reply = await reg.dispatch({"id": "3", "command": "ping"})
    assert reply["result"] == "pong"


@pytest.mark.asyncio
async def test_unknown_command():
    reg = CommandRegistry()
    reply = await reg.dispatch({"id": "4", "command": "nope"})
    assert reply["error"]["type"] == "UnknownCommand"


@pytest.mark.asyncio
async def test_invalid_params_reports_cleanly():
    reg = CommandRegistry()

    @reg.command()
    def add(params: Args) -> int:
        return params.x

    reply = await reg.dispatch({"id": "5", "command": "add", "params": {"x": 1}})
    assert reply["error"]["type"] == "InvalidParams"


@pytest.mark.asyncio
async def test_handler_exception_becomes_error_reply():
    reg = CommandRegistry()

    @reg.command()
    def boom(params: dict):
        raise KeyError("missing")

    reply = await reg.dispatch({"id": "6", "command": "boom", "params": {}})
    assert reply["error"]["type"] == "KeyError"


def test_duplicate_registration_rejected():
    reg = CommandRegistry()

    @reg.command("dup")
    def one():
        return 1

    with pytest.raises(ValueError, match="already registered"):

        @reg.command("dup")
        def two():
            return 2


def test_bad_schema_rejected_at_registration():
    reg = CommandRegistry()

    with pytest.raises(Exception):

        @reg.command()
        def bad(params: "BadParams"):
            return params


@dataclass
class BadParams:
    raw: bytes
