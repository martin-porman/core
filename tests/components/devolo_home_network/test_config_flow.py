"""Test the devolo Home Network config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from devolo_plc_api.exceptions.device import DeviceNotFound, DevicePasswordProtected
import pytest

from homeassistant import config_entries
from homeassistant.components.devolo_home_network.const import (
    DOMAIN,
    SERIAL_NUMBER,
    TITLE,
)
from homeassistant.const import CONF_BASE, CONF_IP_ADDRESS, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import configure_integration
from .const import (
    DISCOVERY_INFO,
    DISCOVERY_INFO_CHANGED,
    DISCOVERY_INFO_WRONG_DEVICE,
    IP,
    IP_ALT,
)
from .mock import MockDevice, MockDeviceWrongPassword


async def test_form(hass: HomeAssistant, info: dict[str, Any]) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.devolo_home_network.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_IP_ADDRESS: IP, CONF_PASSWORD: ""},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["result"].unique_id == info[SERIAL_NUMBER]
    assert result2["title"] == info[TITLE]
    assert result2["data"] == {
        CONF_IP_ADDRESS: IP,
        CONF_PASSWORD: "",
    }
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("exception_type", "expected_error"),
    [
        (DeviceNotFound(IP), "cannot_connect"),
        (DevicePasswordProtected, "invalid_auth"),
        (Exception, "unknown"),
    ],
)
async def test_form_error(hass: HomeAssistant, exception_type, expected_error) -> None:
    """Test we handle errors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.devolo_home_network.config_flow.validate_input",
        side_effect=exception_type,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: IP,
            },
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {CONF_BASE: expected_error}


async def test_zeroconf(hass: HomeAssistant) -> None:
    """Test that the zeroconf form is served."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=DISCOVERY_INFO,
    )

    assert result["step_id"] == "zeroconf_confirm"
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"host_name": "test"}

    context = next(
        flow["context"]
        for flow in hass.config_entries.flow.async_progress()
        if flow["flow_id"] == result["flow_id"]
    )

    assert (
        context["title_placeholders"][CONF_NAME]
        == DISCOVERY_INFO.hostname.split(".", maxsplit=1)[0]
    )

    with (
        patch(
            "homeassistant.components.devolo_home_network.async_setup_entry",
            return_value=True,
        ),
        patch(
            "homeassistant.components.devolo_home_network.config_flow.Device",
            new=MockDevice,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )
        await hass.async_block_till_done()

    assert result2["title"] == "test"
    assert result2["data"] == {
        CONF_IP_ADDRESS: IP,
        CONF_PASSWORD: "",
    }
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["result"].unique_id == "1234567890"


async def test_zeroconf_wrong_auth(hass: HomeAssistant) -> None:
    """Test that the zeroconf form asks for password if authorization fails."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=DISCOVERY_INFO,
    )

    assert result["step_id"] == "zeroconf_confirm"
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"host_name": "test"}

    context = next(
        flow["context"]
        for flow in hass.config_entries.flow.async_progress()
        if flow["flow_id"] == result["flow_id"]
    )

    assert (
        context["title_placeholders"][CONF_NAME]
        == DISCOVERY_INFO.hostname.split(".", maxsplit=1)[0]
    )

    with (
        patch(
            "homeassistant.components.devolo_home_network.async_setup_entry",
            return_value=True,
        ),
        patch(
            "homeassistant.components.devolo_home_network.config_flow.Device",
            new=MockDeviceWrongPassword,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {CONF_BASE: "invalid_auth"}

    with (
        patch(
            "homeassistant.components.devolo_home_network.async_setup_entry",
            return_value=True,
        ),
        patch(
            "homeassistant.components.devolo_home_network.config_flow.Device",
            new=MockDevice,
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_PASSWORD: "new-password",
            },
        )
        await hass.async_block_till_done()

    assert result3["type"] is FlowResultType.CREATE_ENTRY


async def test_abort_zeroconf_wrong_device(hass: HomeAssistant) -> None:
    """Test we abort zeroconf for wrong devices."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=DISCOVERY_INFO_WRONG_DEVICE,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "home_control"


@pytest.mark.usefixtures("info")
async def test_abort_if_configured(hass: HomeAssistant) -> None:
    """Test we abort config flow if already configured."""
    entry = configure_integration(hass)

    # Abort on concurrent user flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: IP,
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"

    # Abort on concurrent zeroconf discovery flow
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=DISCOVERY_INFO_CHANGED,
    )
    assert result3["type"] is FlowResultType.ABORT
    assert result3["reason"] == "already_configured"
    assert entry.data[CONF_IP_ADDRESS] == IP_ALT


@pytest.mark.usefixtures("mock_device")
@pytest.mark.usefixtures("mock_zeroconf")
async def test_form_reauth(hass: HomeAssistant) -> None:
    """Test that the reauth confirmation form is served."""
    entry = configure_integration(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["type"] is FlowResultType.FORM

    with (
        patch(
            "homeassistant.components.devolo_home_network.async_setup_entry",
            return_value=True,
        ),
        patch(
            "homeassistant.components.devolo_home_network.config_flow.Device",
            new=MockDeviceWrongPassword,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "test-wrong-password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {CONF_BASE: "invalid_auth"}

    with (
        patch(
            "homeassistant.components.devolo_home_network.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
        patch(
            "homeassistant.components.devolo_home_network.config_flow.Device",
            new=MockDevice,
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "test-right-password"},
        )
        await hass.async_block_till_done()

    assert result3["type"] is FlowResultType.ABORT
    assert result3["reason"] == "reauth_successful"
    assert len(mock_setup_entry.mock_calls) == 1

    await hass.config_entries.async_unload(entry.entry_id)
