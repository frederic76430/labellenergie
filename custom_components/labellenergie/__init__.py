"""Intégration La Belle Énergie : tarifs de l'électricité par point de livraison."""

from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import LabellenergieClient
from .coordinator import LabellenergieConfigEntry, LabellenergieCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LabellenergieConfigEntry) -> bool:
    """Initialise l'intégration à partir d'une entrée de configuration."""
    # Session propre à cette entrée : la session partagée de Home Assistant (et sa
    # réserve de cookies) est commune à toutes les intégrations et à tous les comptes.
    # Réserve de cookies désactivée : le jeton n'est envoyé que par l'en-tête Cookie.
    # Créée pendant l'installation de l'entrée : Home Assistant la ferme au déchargement.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    client = LabellenergieClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    coordinator = LabellenergieCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LabellenergieConfigEntry) -> bool:
    """Décharge l'entrée de configuration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
