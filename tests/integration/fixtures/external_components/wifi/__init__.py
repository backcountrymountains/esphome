"""Host-only stub of the wifi component for integration tests.

Shadows the real wifi component so components that depend on wifi (for example
improv_serial) can build and run on the host platform. Provides fake scan
results and a fake connect flow; see wifi_component.h for behavior.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PASSWORD, CONF_SSID, CONF_USE_ADDRESS
from esphome.types import ConfigType

CODEOWNERS = ["@esphome/tests"]

wifi_ns = cg.esphome_ns.namespace("wifi")
WiFiComponent = wifi_ns.class_("WiFiComponent", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(WiFiComponent),
        cv.Optional(CONF_SSID): cv.string,
        cv.Optional(CONF_PASSWORD): cv.string,
        # Read by StorageJSON via CORE.address whenever a wifi block exists
        cv.Optional(CONF_USE_ADDRESS, default="localhost"): cv.string,
    }
).extend(cv.COMPONENT_SCHEMA)


def check_placeholder_credentials(config: ConfigType) -> None:
    """Compile-time hook the esphome CLI imports from the wifi module; no-op here."""


async def to_code(config: ConfigType) -> None:
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add_define("USE_WIFI")
