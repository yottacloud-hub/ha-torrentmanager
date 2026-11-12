"""Assistant de configuration C411."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    C411AuthError,
    C411Client,
    C411Error,
    QBittorrentAuthError,
    QBittorrentClient,
    QBittorrentError,
)
from .const import (
    CATEGORIES,
    CONF_API_KEY,
    CONF_C411_URL,
    CONF_FEED_CATEGORIES,
    CONF_FEED_INTERVAL,
    CONF_FEED_LIMIT,
    CONF_QB_CATEGORY,
    CONF_QB_INTERVAL,
    CONF_QB_PASSWORD,
    CONF_QB_SAVE_PATH,
    CONF_QB_TAG,
    CONF_QB_URL,
    CONF_QB_USERNAME,
    CONF_QB_VERIFY_SSL,
    CONF_START_PAUSED,
    DEFAULT_C411_URL,
    DEFAULT_FEED_INTERVAL,
    DEFAULT_FEED_LIMIT,
    DEFAULT_QB_INTERVAL,
    DEFAULT_QB_TAG,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def _c411_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_C411_URL, default=defaults.get(CONF_C411_URL, DEFAULT_C411_URL)): URL,
            vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): PASSWORD,
        }
    )


def _qb_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_QB_URL, default=defaults.get(CONF_QB_URL, "http://192.168.1.10:8080")): URL,
            vol.Optional(CONF_QB_USERNAME, default=defaults.get(CONF_QB_USERNAME, "admin")): str,
            vol.Optional(CONF_QB_PASSWORD, default=defaults.get(CONF_QB_PASSWORD, "")): PASSWORD,
            vol.Required(CONF_QB_VERIFY_SSL, default=defaults.get(CONF_QB_VERIFY_SSL, True)): BooleanSelector(),
        }
    )


async def _validate_c411(hass, data: Mapping[str, Any]) -> dict[str, str]:
    client = C411Client(async_get_clientsession(hass), data[CONF_API_KEY], data[CONF_C411_URL])
    try:
        await client.validate()
    except C411AuthError:
        return {"base": "invalid_api_key"}
    except C411Error as err:
        _LOGGER.warning("Connexion C411 impossible : %s", err)
        return {"base": "cannot_connect_c411"}
    return {}


async def _validate_qb(hass, data: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    # Session temporaire, fermée après le test de connexion
    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        connector=aiohttp.TCPConnector(ssl=None if data[CONF_QB_VERIFY_SSL] else False),
    )
    client = QBittorrentClient(
        session, data[CONF_QB_URL], data.get(CONF_QB_USERNAME, ""), data.get(CONF_QB_PASSWORD, "")
    )
    try:
        version = await client.version()
    except QBittorrentAuthError:
        return {"base": "invalid_qb_auth"}, None
    except QBittorrentError as err:
        _LOGGER.warning("Connexion qBittorrent impossible : %s", err)
        return {"base": "cannot_connect_qb"}, None
    finally:
        await session.close()
    return {}, version


class C411ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Assistant en deux étapes : C411 puis qBittorrent."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_C411_URL] = user_input[CONF_C411_URL].rstrip("/")
            errors = await _validate_c411(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_qbittorrent()
        return self.async_show_form(
            step_id="user",
            data_schema=_c411_schema(user_input or {}),
            errors=errors,
            description_placeholders={"integrations_url": f"{DEFAULT_C411_URL}/user/integrations"},
        )

    async def async_step_qbittorrent(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_QB_URL] = user_input[CONF_QB_URL].rstrip("/")
            errors, _version = await _validate_qb(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(
                    title="C411",
                    data=self._data,
                    options={
                        CONF_QB_TAG: DEFAULT_QB_TAG,
                        CONF_FEED_LIMIT: DEFAULT_FEED_LIMIT,
                        CONF_FEED_INTERVAL: DEFAULT_FEED_INTERVAL,
                        CONF_QB_INTERVAL: DEFAULT_QB_INTERVAL,
                        CONF_FEED_CATEGORIES: [],
                        CONF_START_PAUSED: False,
                    },
                )
        return self.async_show_form(
            step_id="qbittorrent", data_schema=_qb_schema(user_input or {}), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Nouvelle clé API C411 et/ou nouveaux identifiants qBittorrent."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**entry.data, **user_input}
            errors = await _validate_c411(self.hass, merged)
            if not errors:
                errors, _ = await _validate_qb(self.hass, merged)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=merged)
        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY, default=entry.data.get(CONF_API_KEY, "")): PASSWORD,
                vol.Optional(CONF_QB_USERNAME, default=entry.data.get(CONF_QB_USERNAME, "")): str,
                vol.Optional(CONF_QB_PASSWORD, default=entry.data.get(CONF_QB_PASSWORD, "")): PASSWORD,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Changer l'adresse de qBittorrent sans tout supprimer."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_QB_URL] = user_input[CONF_QB_URL].rstrip("/")
            merged = {**entry.data, **user_input}
            errors, _ = await _validate_qb(self.hass, merged)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=merged)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_qb_schema(user_input or entry.data), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return C411OptionsFlow()


class C411OptionsFlow(OptionsFlow):
    """Options : flux, qBittorrent, rafraîchissement."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for key in (CONF_FEED_LIMIT, CONF_FEED_INTERVAL, CONF_QB_INTERVAL):
                user_input[key] = int(user_input[key])
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        qb_categories: list[str] = []
        rt = getattr(self.config_entry, "runtime_data", None)
        if rt is not None:
            qb_categories = await rt.qbit.categories()
        cat_options = [SelectOptionDict(value=k, label=f"{v} ({k})") for k, v in CATEGORIES.items()]

        schema = vol.Schema(
            {
                vol.Optional(CONF_FEED_CATEGORIES, default=opts.get(CONF_FEED_CATEGORIES, [])): SelectSelector(
                    SelectSelectorConfig(options=cat_options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_FEED_LIMIT, default=opts.get(CONF_FEED_LIMIT, DEFAULT_FEED_LIMIT)): NumberSelector(
                    NumberSelectorConfig(min=10, max=100, step=10, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Required(CONF_FEED_INTERVAL, default=opts.get(CONF_FEED_INTERVAL, DEFAULT_FEED_INTERVAL)): NumberSelector(
                    NumberSelectorConfig(min=5, max=360, step=5, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_QB_CATEGORY, description={"suggested_value": opts.get(CONF_QB_CATEGORY)}): SelectSelector(
                    SelectSelectorConfig(options=qb_categories, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_QB_SAVE_PATH, description={"suggested_value": opts.get(CONF_QB_SAVE_PATH)}): str,
                vol.Required(CONF_QB_TAG, default=opts.get(CONF_QB_TAG, DEFAULT_QB_TAG)): str,
                vol.Required(CONF_START_PAUSED, default=opts.get(CONF_START_PAUSED, False)): BooleanSelector(),
                vol.Required(CONF_QB_INTERVAL, default=opts.get(CONF_QB_INTERVAL, DEFAULT_QB_INTERVAL)): NumberSelector(
                    NumberSelectorConfig(min=3, max=300, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
