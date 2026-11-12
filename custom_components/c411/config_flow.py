"""Assistant de configuration TorrentManager."""

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

from .plex import PlexAuthError, PlexClient, PlexError
from .tmdb import TmdbAuthError, TmdbClient, TmdbError
from .api import (
    C411AuthError,
    C411Client,
    C411Error,
    QBittorrentAuthError,
    QBittorrentClient,
    QBittorrentError,
)
from .const import (
    ACCESS_LEVELS,
    APP_NAME,
    CATEGORIES,
    CONF_BEST_ONLY,
    CONF_HIDE_ADULT,
    CONF_PREF_LANGUAGE,
    CONF_PREF_QUALITY,
    CONF_TMDB_KEY,
    CONF_USER_ACCESS,
    DEFAULT_PREF_LANGUAGE,
    DEFAULT_PREF_QUALITY,
    DEFAULT_USER_ACCESS,
    CONF_CAT_PREFIX,
    CONF_PATH_PREFIX,
    CONF_PLEX_INTERVAL,
    CONF_PLEX_REFRESH_ON_COMPLETE,
    CONF_PLEX_SECTIONS,
    CONF_PLEX_TOKEN,
    CONF_PLEX_URL,
    CONF_PLEX_VERIFY_SSL,
    CONF_SERIES_AUTO,
    CONF_SERIES_ENABLED,
    CONF_SERIES_EXCLUDE,
    CONF_SERIES_FOLLOW_NEW,
    CONF_SERIES_INTERVAL,
    CONF_SERIES_LANGUAGES,
    CONF_SERIES_MAX_GRABS,
    CONF_SERIES_MIN_SEEDERS,
    CONF_SERIES_NEXT_SEASONS,
    CONF_SERIES_NOTIFY_SERVICE,
    CONF_SERIES_NOTIFY,
    CONF_SERIES_PACKS,
    CONF_SERIES_QUALITIES,
    CONF_SERIES_QUALITY,
    CONTENT_TYPES,
    DEFAULT_PLEX_INTERVAL,
    DEFAULT_SERIES_EXCLUDE,
    DEFAULT_SERIES_INTERVAL,
    DEFAULT_SERIES_LANGUAGES,
    DEFAULT_SERIES_MAX_GRABS,
    DEFAULT_SERIES_QUALITIES,
    DEFAULT_SERIES_QUALITY,
    LANGUAGE_GROUPS,
    QUALITIES,
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
                    title=APP_NAME,
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
    """Options, organisées en menu."""

    def _save(self, user_input: dict[str, Any], blank: tuple[str, ...] = ()) -> ConfigFlowResult:
        # Un champ facultatif vidé n'est pas renvoyé par le formulaire : on l'efface explicitement.
        for key in blank:
            user_input.setdefault(key, "")
        for key, value in list(user_input.items()):
            if isinstance(value, float) and value.is_integer():
                user_input[key] = int(value)
        return self.async_create_entry(data={**self.config_entry.options, **user_input})

    async def _qb_categories(self) -> list[str]:
        rt = getattr(self.config_entry, "runtime_data", None)
        if rt is None:
            return []
        try:
            return await rt.qbit.categories()
        except Exception:  # noqa: BLE001
            return []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["general", "display", "folders", "plex", "series"])

    # ---------------------------------------------------------------- général
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(user_input, blank=(CONF_QB_CATEGORY, CONF_QB_SAVE_PATH))

        opts = self.config_entry.options
        qb_categories = await self._qb_categories()
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
        return self.async_show_form(step_id="general", data_schema=schema)

    # ---------------------------------------------------------------- affichage & accès
    async def async_step_display(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_TMDB_KEY) or "").strip()
            user_input[CONF_TMDB_KEY] = key
            if key:
                session = aiohttp.ClientSession()
                try:
                    await TmdbClient(self.hass, session, key).validate()
                except TmdbAuthError:
                    errors["base"] = "invalid_tmdb_key"
                except TmdbError as err:
                    _LOGGER.warning("TMDB injoignable : %s", err)
                    errors["base"] = "cannot_connect_tmdb"
                finally:
                    await session.close()
            if not errors:
                return self._save(user_input, blank=(CONF_TMDB_KEY,))

        opts = {**self.config_entry.options, **(user_input or {})}
        q_options = [SelectOptionDict(value=k, label=v) for k, v in QUALITIES.items()]
        l_options = [SelectOptionDict(value=k, label=v) for k, v in LANGUAGE_GROUPS.items()]
        a_options = [SelectOptionDict(value=k, label=v) for k, v in ACCESS_LEVELS.items()]
        schema = vol.Schema(
            {
                vol.Required(CONF_HIDE_ADULT, default=opts.get(CONF_HIDE_ADULT, True)): BooleanSelector(),
                vol.Required(CONF_BEST_ONLY, default=opts.get(CONF_BEST_ONLY, True)): BooleanSelector(),
                vol.Required(CONF_PREF_QUALITY, default=opts.get(CONF_PREF_QUALITY, DEFAULT_PREF_QUALITY)): SelectSelector(
                    SelectSelectorConfig(options=q_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_PREF_LANGUAGE, default=opts.get(CONF_PREF_LANGUAGE, DEFAULT_PREF_LANGUAGE)): SelectSelector(
                    SelectSelectorConfig(options=l_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_TMDB_KEY, description={"suggested_value": opts.get(CONF_TMDB_KEY)}): PASSWORD,
                vol.Required(CONF_USER_ACCESS, default=opts.get(CONF_USER_ACCESS, DEFAULT_USER_ACCESS)): SelectSelector(
                    SelectSelectorConfig(options=a_options, mode=SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(step_id="display", data_schema=schema, errors=errors)

    # ---------------------------------------------------------------- dossiers
    async def async_step_folders(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        keys = tuple(f"{p}{t}" for t in CONTENT_TYPES for p in (CONF_PATH_PREFIX, CONF_CAT_PREFIX))
        if user_input is not None:
            return self._save(user_input, blank=keys)

        opts = self.config_entry.options
        qb_categories = await self._qb_categories()
        fields: dict[Any, Any] = {}
        for t in CONTENT_TYPES:
            path_key, cat_key = f"{CONF_PATH_PREFIX}{t}", f"{CONF_CAT_PREFIX}{t}"
            fields[vol.Optional(path_key, description={"suggested_value": opts.get(path_key)})] = str
            fields[vol.Optional(cat_key, description={"suggested_value": opts.get(cat_key)})] = SelectSelector(
                SelectSelectorConfig(options=qb_categories, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
            )
        return self.async_show_form(step_id="folders", data_schema=vol.Schema(fields))

    # ---------------------------------------------------------------- Plex
    async def async_step_plex(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"server": ""}
        if user_input is not None:
            url = (user_input.get(CONF_PLEX_URL) or "").strip().rstrip("/")
            user_input[CONF_PLEX_URL] = url
            if url:
                session = aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=None if user_input[CONF_PLEX_VERIFY_SSL] else False)
                )
                try:
                    await PlexClient(session, url, user_input.get(CONF_PLEX_TOKEN, "")).server_name()
                except PlexAuthError:
                    errors["base"] = "invalid_plex_token"
                except PlexError as err:
                    _LOGGER.warning("Connexion Plex impossible : %s", err)
                    errors["base"] = "cannot_connect_plex"
                finally:
                    await session.close()
            if not errors:
                return self._save(user_input, blank=(CONF_PLEX_URL, CONF_PLEX_TOKEN))

        opts = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Optional(CONF_PLEX_URL, description={"suggested_value": opts.get(CONF_PLEX_URL)}): URL,
                vol.Optional(CONF_PLEX_TOKEN, description={"suggested_value": opts.get(CONF_PLEX_TOKEN)}): PASSWORD,
                vol.Required(CONF_PLEX_VERIFY_SSL, default=opts.get(CONF_PLEX_VERIFY_SSL, True)): BooleanSelector(),
                vol.Required(
                    CONF_PLEX_REFRESH_ON_COMPLETE, default=opts.get(CONF_PLEX_REFRESH_ON_COMPLETE, True)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="plex", data_schema=schema, errors=errors, description_placeholders=placeholders
        )

    # ---------------------------------------------------------------- séries
    async def async_step_series(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self.config_entry.options
        if not (opts.get(CONF_PLEX_URL) and opts.get(CONF_PLEX_TOKEN)):
            return self.async_abort(reason="plex_required")
        if user_input is not None:
            return self._save(user_input, blank=(CONF_SERIES_EXCLUDE, CONF_SERIES_NOTIFY_SERVICE))

        sections: list[SelectOptionDict] = []
        rt = getattr(self.config_entry, "runtime_data", None)
        if rt is not None and rt.series is not None:
            try:
                sections = [
                    SelectOptionDict(value=s["key"], label=s["title"])
                    for s in await rt.series.plex.sections() if s["type"] == "show"
                ]
            except PlexError:
                sections = []
        q_options = [SelectOptionDict(value=k, label=v) for k, v in QUALITIES.items()]
        l_options = [SelectOptionDict(value=k, label=v) for k, v in LANGUAGE_GROUPS.items()]
        notify_services = sorted(
            f"notify.{name}" for name in self.hass.services.async_services_for_domain("notify")
            if name not in ("send_message", "persistent_notification")
        )

        def box(min_: int, max_: int, unit: str | None = None) -> NumberSelector:
            cfg = NumberSelectorConfig(min=min_, max=max_, step=1, mode=NumberSelectorMode.BOX)
            if unit:
                cfg["unit_of_measurement"] = unit
            return NumberSelector(cfg)

        schema = vol.Schema(
            {
                vol.Required(CONF_SERIES_ENABLED, default=opts.get(CONF_SERIES_ENABLED, True)): BooleanSelector(),
                vol.Required(CONF_SERIES_AUTO, default=opts.get(CONF_SERIES_AUTO, True)): BooleanSelector(),
                vol.Required(CONF_SERIES_FOLLOW_NEW, default=opts.get(CONF_SERIES_FOLLOW_NEW, True)): BooleanSelector(),
                vol.Optional(CONF_PLEX_SECTIONS, default=opts.get(CONF_PLEX_SECTIONS, [])): SelectSelector(
                    SelectSelectorConfig(options=sections, multiple=True, mode=SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_SERIES_QUALITY, default=opts.get(CONF_SERIES_QUALITY, DEFAULT_SERIES_QUALITY)): SelectSelector(
                    SelectSelectorConfig(options=q_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_SERIES_QUALITIES, default=opts.get(CONF_SERIES_QUALITIES, DEFAULT_SERIES_QUALITIES)): SelectSelector(
                    SelectSelectorConfig(options=q_options, multiple=True, mode=SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_SERIES_LANGUAGES, default=opts.get(CONF_SERIES_LANGUAGES, DEFAULT_SERIES_LANGUAGES)): SelectSelector(
                    SelectSelectorConfig(options=l_options, multiple=True, mode=SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_SERIES_MIN_SEEDERS, default=opts.get(CONF_SERIES_MIN_SEEDERS, 1)): box(0, 100),
                vol.Optional(
                    CONF_SERIES_EXCLUDE,
                    description={"suggested_value": opts.get(CONF_SERIES_EXCLUDE, DEFAULT_SERIES_EXCLUDE)},
                ): str,
                vol.Required(CONF_SERIES_PACKS, default=opts.get(CONF_SERIES_PACKS, True)): BooleanSelector(),
                vol.Required(CONF_SERIES_NEXT_SEASONS, default=opts.get(CONF_SERIES_NEXT_SEASONS, True)): BooleanSelector(),
                vol.Required(CONF_SERIES_MAX_GRABS, default=opts.get(CONF_SERIES_MAX_GRABS, DEFAULT_SERIES_MAX_GRABS)): box(1, 50),
                vol.Required(CONF_SERIES_INTERVAL, default=opts.get(CONF_SERIES_INTERVAL, DEFAULT_SERIES_INTERVAL)): box(10, 720, "min"),
                vol.Required(CONF_PLEX_INTERVAL, default=opts.get(CONF_PLEX_INTERVAL, DEFAULT_PLEX_INTERVAL)): box(10, 1440, "min"),
                vol.Required(CONF_SERIES_NOTIFY, default=opts.get(CONF_SERIES_NOTIFY, True)): BooleanSelector(),
                vol.Optional(
                    CONF_SERIES_NOTIFY_SERVICE,
                    description={"suggested_value": opts.get(CONF_SERIES_NOTIFY_SERVICE)},
                ): SelectSelector(
                    SelectSelectorConfig(options=notify_services, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(step_id="series", data_schema=schema)
