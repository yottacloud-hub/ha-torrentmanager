"""Capteurs C411 / qBittorrent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import C411ConfigEntry
from .const import CATEGORIES, DOMAIN


@dataclass(frozen=True, kw_only=True)
class QbSensorDescription(SensorEntityDescription):
    """Capteur basé sur les données qBittorrent."""

    value_fn: Callable[[dict[str, Any]], Any]


QB_SENSORS: tuple[QbSensorDescription, ...] = (
    QbSensorDescription(
        key="download_speed",
        translation_key="download_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("dl_speed", 0),
    ),
    QbSensorDescription(
        key="upload_speed",
        translation_key="upload_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("up_speed", 0),
    ),
    QbSensorDescription(
        key="active_downloads",
        translation_key="active_downloads",
        icon="mdi:download",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("downloading", 0),
    ),
    QbSensorDescription(
        key="c411_downloads",
        translation_key="c411_downloads",
        icon="mdi:download-network",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("c411_downloading", 0),
    ),
    QbSensorDescription(
        key="total_torrents",
        translation_key="total_torrents",
        icon="mdi:file-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("count", 0),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: C411ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Création des capteurs."""
    entities: list[SensorEntity] = [LatestReleaseSensor(entry)]
    entities += [QbSensor(entry, desc) for desc in QB_SENSORS]
    entities.append(C411DownloadsListSensor(entry))
    async_add_entities(entities)


def _device(entry: C411ConfigEntry, kind: str) -> DeviceInfo:
    rt = entry.runtime_data
    if kind == "c411":
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_c411")},
            name="C411",
            manufacturer="Community 411",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=rt.c411.base_url,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_qbittorrent")},
        name="qBittorrent",
        manufacturer="qBittorrent",
        sw_version=rt.downloads.version,
        configuration_url=rt.qbit.url,
    )


class LatestReleaseSensor(CoordinatorEntity, SensorEntity):
    """Dernière release publiée sur C411 (attributs : les 10 dernières)."""

    _attr_has_entity_name = True
    _attr_translation_key = "latest_release"
    _attr_icon = "mdi:new-box"
    _unrecorded_attributes = frozenset({"releases"})

    def __init__(self, entry: C411ConfigEntry) -> None:
        super().__init__(entry.runtime_data.feed)
        self._attr_unique_id = f"{entry.entry_id}_latest_release"
        self._attr_device_info = _device(entry, "c411")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or []
        return data[0]["title"][:255] if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or []
        return {
            "count": len(data),
            "releases": [
                {
                    "title": r["title"],
                    "size": r["size"],
                    "category": CATEGORIES.get(r["categories"][0], r["categories"][0])
                    if r["categories"] else None,
                    "seeders": r["seeders"],
                    "published": r["published"],
                    "details_url": r["details_url"],
                    "download_url": r["download_url"],
                }
                for r in data[:10]
            ],
        }


class QbSensor(CoordinatorEntity, SensorEntity):
    """Capteur générique qBittorrent."""

    _attr_has_entity_name = True
    entity_description: QbSensorDescription

    def __init__(self, entry: C411ConfigEntry, description: QbSensorDescription) -> None:
        super().__init__(entry.runtime_data.downloads)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device(entry, "qbittorrent")

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})


class C411DownloadsListSensor(CoordinatorEntity, SensorEntity):
    """Progression des téléchargements venus de C411 (pour les cartes Lovelace)."""

    _attr_has_entity_name = True
    _attr_translation_key = "c411_progress"
    _attr_icon = "mdi:progress-download"
    _unrecorded_attributes = frozenset({"torrents"})

    def __init__(self, entry: C411ConfigEntry) -> None:
        super().__init__(entry.runtime_data.downloads)
        self._attr_unique_id = f"{entry.entry_id}_c411_progress"
        self._attr_device_info = _device(entry, "qbittorrent")

    def _items(self) -> list[dict[str, Any]]:
        return [t for t in (self.coordinator.data or {}).get("torrents", []) if t.get("is_c411")]

    @property
    def native_value(self) -> int:
        return len(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "torrents": [
                {
                    "name": t["name"],
                    "progress": round(float(t["progress"] or 0) * 100, 1),
                    "state": t["state"],
                    "dlspeed": t["dlspeed"],
                    "eta": t["eta"],
                    "size": t["size"],
                }
                for t in self._items()[:15]
            ]
        }
