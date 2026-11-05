"""Capteur binaire : heure creuse en cours."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import LabellenergieConfigEntry, LabellenergieCoordinator
from .entity import LabellenergieBasculeEntity, LabellenergieEntity, ajouter_entites_par_pdl
from .pricing import prix_actuel

HEURE_CREUSE = BinarySensorEntityDescription(
    key="heure_creuse", translation_key="heure_creuse"
)
CHANGEMENT_TARIF = BinarySensorEntityDescription(
    key="changement_tarif", translation_key="changement_tarif"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LabellenergieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée le capteur « heure creuse en cours » de chaque point de livraison."""

    def _creer(coordinator: LabellenergieCoordinator, numero: str) -> list[Entity]:
        return [
            LabellenergieHeureCreuse(coordinator, numero, HEURE_CREUSE),
            LabellenergieChangementTarif(coordinator, numero, CHANGEMENT_TARIF),
        ]

    ajouter_entites_par_pdl(entry, async_add_entities, _creer)


class LabellenergieHeureCreuse(LabellenergieBasculeEntity, BinarySensorEntity):
    """Actif pendant les heures creuses ; indisponible pour une offre Base."""

    @property
    def is_on(self) -> bool | None:
        if self._pdl is None:
            return None
        return prix_actuel(self._offre, dt_util.now()).heure_creuse

    @property
    def _a_une_valeur(self) -> bool:
        return self.is_on is not None


class LabellenergieChangementTarif(LabellenergieEntity, BinarySensorEntity):
    """Actif quand l'espace client annonce une nouvelle offre ou un nouveau prix."""

    @property
    def is_on(self) -> bool | None:
        pdl = self._pdl
        if pdl is None:
            return None
        return bool(pdl.get("offre_future") or pdl.get("repricing"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        pdl = self._pdl
        if not pdl or not self.is_on:
            return None
        return {"offre_future": pdl.get("offre_future"), "repricing": pdl.get("repricing")}
