"""Integration test for improv_serial over a mocked UART bus.

Drives the improv serial protocol end to end on the host platform:
the fixture wires improv_serial to a uart_mock bus and shadows the wifi
component with a host stub. The test injects improv frames through an API
action and asserts on the framed responses that uart_mock logs as TX lines.

Covered:
  1. Get Current State reports AUTHORIZED
  2. Get Device Info returns the firmware/device info RPC response
  3. Get Wi-Fi Networks returns deduplicated scan results and a terminator
  4. Wi-Fi Settings provisions: saves credentials and reports PROVISIONED
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from .types import APIClientConnectedFactory, RunCompiledFunction

# Improv serial framing (improv_serial_component.h)
IMPROV_HEADER = b"IMPROV"
IMPROV_VERSION = 1
TYPE_RPC = 0x03

# improv::Command values
CMD_GET_CURRENT_STATE = 0x02
CMD_GET_DEVICE_INFO = 0x03
CMD_GET_WIFI_NETWORKS = 0x04
CMD_WIFI_SETTINGS = 0x01


def build_rpc_frame(command: int, data: bytes = b"") -> list[int]:
    """Build a full improv serial frame carrying one RPC command."""
    payload = bytes([command, len(data)]) + data
    frame = IMPROV_HEADER + bytes([IMPROV_VERSION, TYPE_RPC, len(payload)]) + payload
    checksum = sum(frame) & 0xFF
    return list(frame + bytes([checksum]) + b"\n")


def wifi_settings_data(ssid: str, password: str) -> bytes:
    ssid_b = ssid.encode()
    pass_b = password.encode()
    return bytes([len(ssid_b)]) + ssid_b + bytes([len(pass_b)]) + pass_b


def hex_of(text: str) -> str:
    """Colon separated uppercase hex as logged by format_hex_pretty."""
    return ":".join(f"{b:02X}" for b in text.encode())


class LineWaiter:
    """Collects log lines and lets the test await a matching one."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._waiters: list[tuple[Callable[[str], bool], asyncio.Future]] = []

    def callback(self, line: str) -> None:
        self.lines.append(line)
        for predicate, future in self._waiters[:]:
            if not future.done() and predicate(line):
                future.get_loop().call_soon_threadsafe(future.set_result, line)
                self._waiters.remove((predicate, future))

    async def wait_for(
        self, predicate: Callable[[str], bool], timeout: float = 10.0
    ) -> str:
        for line in self.lines:
            if predicate(line):
                return line
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters.append((predicate, future))
        return await asyncio.wait_for(future, timeout)


@pytest.mark.asyncio
async def test_improv_serial_uart(
    yaml_config: str,
    run_compiled: RunCompiledFunction,
    api_client_connected: APIClientConnectedFactory,
) -> None:
    waiter = LineWaiter()

    def tx_lines() -> list[str]:
        return [line for line in waiter.lines if "uart_mock" in line and "TX " in line]

    async with (
        run_compiled(yaml_config, line_callback=waiter.callback),
        api_client_connected() as client,
    ):
        _entities, services = await client.list_entities_services()
        inject = next(s for s in services if s.name == "uart_inject")

        # 1. Get Current State: expect a current-state frame reporting AUTHORIZED
        # (0x02). Frame: IMPROV, version 1, type 1, length 1, state, checksum, \n
        await client.execute_service(
            inject, {"payload": build_rpc_frame(CMD_GET_CURRENT_STATE)}
        )
        await waiter.wait_for(
            lambda line: (
                "uart_mock" in line
                and "TX 12 bytes: 49:4D:50:52:4F:56:01:01:01:02" in line
            )
        )

        # 2. Get Device Info: RPC response payload includes the firmware name
        await client.execute_service(
            inject, {"payload": build_rpc_frame(CMD_GET_DEVICE_INFO)}
        )
        esphome_hex = hex_of("ESPHome")
        await waiter.wait_for(
            lambda line: "uart_mock" in line and "TX " in line and esphome_hex in line
        )

        # 3. Get Wi-Fi Networks: stub scan has TestNet twice (dedup keeps the
        # stronger), OpenNet, and a hidden entry (filtered). Expect one response
        # per visible network plus the empty terminator.
        await client.execute_service(
            inject, {"payload": build_rpc_frame(CMD_GET_WIFI_NETWORKS)}
        )
        await waiter.wait_for(
            lambda line: "uart_mock" in line and hex_of("TestNet") in line
        )
        await waiter.wait_for(
            lambda line: "uart_mock" in line and hex_of("OpenNet") in line
        )
        # Terminator: RPC response payload [0x04, 0x00, 0x00]
        await waiter.wait_for(
            lambda line: "uart_mock" in line and "TX 3 bytes: 04:00:00" in line
        )
        testnet_count = sum(1 for line in tx_lines() if hex_of("TestNet") in line)
        assert testnet_count == 1, (
            f"Duplicate scan entry not deduplicated: {testnet_count} TestNet responses"
        )

        # 4. Wi-Fi Settings: stub connects immediately; expect the credentials
        # saved, the PROVISIONED state frame (0x04), and the settings response
        await client.execute_service(
            inject,
            {
                "payload": build_rpc_frame(
                    CMD_WIFI_SETTINGS, wifi_settings_data("NewNet", "secret123")
                )
            },
        )
        await waiter.wait_for(lambda line: "save_wifi_sta ssid=NewNet" in line)
        await waiter.wait_for(
            lambda line: (
                "uart_mock" in line
                and "TX 12 bytes: 49:4D:50:52:4F:56:01:01:01:04" in line
            )
        )
        # Settings RPC response with no URLs: payload [0x01, 0x00, 0x00]
        await waiter.wait_for(
            lambda line: "uart_mock" in line and "TX 3 bytes: 01:00:00" in line
        )
