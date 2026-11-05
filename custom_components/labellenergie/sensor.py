"""Capteurs : un jeu d'entités par point de livraison."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .consommation import Conso, debut_mois, fin_mois, periode_du, somme, temperature
from .coordinator import LabellenergieConfigEntry, LabellenergieCoordinator
from .entity import (
    LabellenergieBasculeEntity,
    LabellenergieEntity,
    ajouter_entites_par_pdl,
)
from .factures import (
    TIMEZONE,
    Facture,
    debut_mois_utc,
    total_annee,
    total_glissant,
)
from .pricing import prix_actuel
from .statistiques import async_backfill

UNITE_EUR = "EUR"
UNITE_EUR_KWH = f"{UNITE_EUR}/{UnitOfEnergy.KILO_WATT_HOUR}"


def _date(valeur: str | None) -> date | None:
    try:
        return date.fromisoformat(valeur) if valeur else None
    except ValueError:
        return None


def _plages(offre: dict[str, Any]) -> str | None:
    plages = offre.get("plagesHc")
    return ", ".join(plages) if plages else None


@dataclass(frozen=True, kw_only=True)
class LabellenergieSensorDescription(SensorEntityDescription):
    """Capteur lu directement dans `offreCourante`."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[LabellenergieSensorDescription, ...] = (
    LabellenergieSensorDescription(
        key="abonnement",
        translation_key="abonnement",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=UNITE_EUR,
        suggested_display_precision=2,
        value_fn=lambda offre: offre.get("abonnement"),
    ),
    LabellenergieSensorDescription(
        key="prix_hc",
        translation_key="prix_hc",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UNITE_EUR_KWH,
        suggested_display_precision=5,
        value_fn=lambda offre: offre.get("hc"),
    ),
    LabellenergieSensorDescription(
        key="prix_hp",
        translation_key="prix_hp",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UNITE_EUR_KWH,
        suggested_display_precision=5,
        value_fn=lambda offre: offre.get("hp"),
    ),
    LabellenergieSensorDescription(
        key="prix_base",
        translation_key="prix_base",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UNITE_EUR_KWH,
        suggested_display_precision=5,
        value_fn=lambda offre: offre.get("base"),
    ),
    LabellenergieSensorDescription(
        key="plages_hc",
        translation_key="plages_hc",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_plages,
        attrs_fn=lambda offre: {"plages": offre.get("plagesHc") or []},
    ),
    LabellenergieSensorDescription(
        key="puissance",
        translation_key="puissance",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="kVA",
        value_fn=lambda offre: offre.get("puissance"),
    ),
    LabellenergieSensorDescription(
        key="derniere_modification",
        translation_key="derniere_modification",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda offre: _date(offre.get("lastChange")),
    ),
)

# Identité du point de livraison (lue dans le PDL, pas dans l'offre).
SENSORS_PDL: tuple[LabellenergieSensorDescription, ...] = (
    LabellenergieSensorDescription(
        key="numero_pdl",
        translation_key="numero_pdl",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda pdl: pdl.get("numero"),
    ),
    LabellenergieSensorDescription(
        key="adresse",
        translation_key="adresse",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda pdl: pdl.get("adresse") or None,
    ),
)


def _mois(mois: date) -> str:
    return mois.strftime("%Y-%m")


@dataclass(frozen=True, kw_only=True)
class LabellenergieFactureDescription(SensorEntityDescription):
    """Capteur calculé à partir de l'historique de facturation."""

    value_fn: Callable[[list[Facture], int], float | None]
    attrs_fn: Callable[[list[Facture]], dict[str, Any]] | None = None
    last_reset_fn: Callable[[list[Facture]], datetime] | None = None
    # Importe l'historique dans les statistiques : "mensuel" ou "cumul".
    backfill: str | None = None


_FACTURE = {
    "device_class": SensorDeviceClass.MONETARY,
    "native_unit_of_measurement": UNITE_EUR,
    "suggested_display_precision": 2,
}

SENSORS_FACTURES: tuple[LabellenergieFactureDescription, ...] = (
    LabellenergieFactureDescription(
        key="total_ttc",
        translation_key="total_ttc",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda f, _annee: f[-1].total_ttc,
        attrs_fn=lambda f: {"mois": _mois(f[-1].mois), "total_ht": f[-1].total_ht, **f[-1].details},
        last_reset_fn=lambda f: debut_mois_utc(f[-1].mois),
        backfill="mensuel",
        **_FACTURE,
    ),
    LabellenergieFactureDescription(
        key="cumulative_total_ttc",
        translation_key="cumulative_total_ttc",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda f, _annee: f[-1].cumul,
        attrs_fn=lambda f: {"depuis": _mois(f[0].mois)},
        backfill="cumul",
        **_FACTURE,
    ),
    LabellenergieFactureDescription(
        key="historique_factures",
        translation_key="historique_factures",
        value_fn=lambda f, _annee: len(f),
        attrs_fn=lambda f: {
            "mois": {
                _mois(x.mois): {"total_ttc": x.total_ttc, "total_ht": x.total_ht, **x.details}
                for x in f
            }
        },
    ),
    LabellenergieFactureDescription(
        key="total_annee_passee",
        translation_key="total_annee_passee",
        value_fn=lambda f, annee: total_annee(f, annee - 1),
        **_FACTURE,
    ),
    LabellenergieFactureDescription(
        key="total_annee_en_cours",
        translation_key="total_annee_en_cours",
        value_fn=lambda f, annee: total_annee(f, annee) or 0.0,
        **_FACTURE,
    ),
    LabellenergieFactureDescription(
        key="total_annee_glissante",
        translation_key="total_annee_glissante",
        value_fn=lambda f, _annee: total_glissant(f)[0],
        attrs_fn=lambda f: {
            "mois_debut": _mois(total_glissant(f)[1]),
            "mois_fin": _mois(total_glissant(f)[2]),
        },
        **_FACTURE,
    ),
)

# ---------------------------------------------------------------------------
# Consommation (page « Conso » de l'espace client) et températures
# ---------------------------------------------------------------------------


def _aujourdhui() -> date:
    return dt_util.now().astimezone(TIMEZONE).date()


def _mois_conso(pdl: dict[str, Any], decalage: int) -> Conso | None:
    mois = (pdl.get("consommations") or {}).get("mois")
    return periode_du(mois, debut_mois(_aujourdhui(), decalage)) if mois else None


def _dernier_jour(pdl: dict[str, Any]) -> Conso | None:
    """Dernier jour transmis par Enedis (souvent la veille, parfois l'avant-veille)."""
    jours = (pdl.get("consommations") or {}).get("jours") or []
    # Uniquement de vraies journées : si le site renvoie un mois entier, on ne l'affiche pas.
    connus = [j for j in jours if j.debut == j.fin and j.codes and j.total > 0]
    return connus[-1] if connus else None


def _attrs_periode(c: Conso | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "debut": c.debut.isoformat(),
        "fin": c.fin.isoformat(),
        "hp_kwh": c.hp,
        "hc_kwh": c.hc,
        "part_hc": c.part_hc,
        "codes": c.codes,
    }


def _euros(pdl: dict[str, Any]) -> list[Conso]:
    return (pdl.get("consommations") or {}).get("euros") or []


def _cout_mois(pdl: dict[str, Any], decalage: int) -> Conso | None:
    debut = debut_mois(_aujourdhui(), decalage)
    return somme(_euros(pdl), debut, fin_mois(debut))


def _cout_dernier_jour(pdl: dict[str, Any]) -> Conso | None:
    jours = [j for j in _euros(pdl) if j.debut == j.fin and j.codes]
    return jours[-1] if jours else None


def _attrs_cout(c: Conso | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "debut": c.debut.isoformat(),
        "fin": c.fin.isoformat(),
        "hp_eur": round(c.hp, 2),
        "hc_eur": round(c.hc, 2),
        "abonnement_eur": round(c.autres, 2),
    }


def _historique(pdl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Tous les mois connus : {"2026-10": {"hp_kwh": …, "total_eur": …}, …} (plus récent en dernier)."""
    conso = pdl.get("consommations") or {}
    euros = {c.debut: c for c in conso.get("mois_euros") or []}
    resultat: dict[str, dict[str, Any]] = {}
    for c in conso.get("mois") or []:
        if not c.codes or c.total <= 0:
            continue  # mois avant le contrat
        ligne: dict[str, Any] = {
            "hp_kwh": round(c.hp, 2),
            "hc_kwh": round(c.hc, 2),
            "total_kwh": round(c.total, 2),
            "part_hc": c.part_hc,
        }
        e = euros.get(c.debut)
        if e is not None and e.codes:
            ligne |= {
                "hp_eur": round(e.hp, 2),
                "hc_eur": round(e.hc, 2),
                "abonnement_eur": round(e.autres, 2),
                "total_eur": round(e.total, 2),
            }
        resultat[c.debut.strftime("%Y-%m")] = ligne
    return resultat


def _total_12_mois(pdl: dict[str, Any]) -> float | None:
    """kWh des 12 derniers mois complets (mois en cours exclu)."""
    debut = debut_mois(_aujourdhui(), -12).strftime("%Y-%m")
    fin = debut_mois(_aujourdhui(), -1).strftime("%Y-%m")
    mois = {k: v for k, v in _historique(pdl).items() if debut <= k <= fin}
    return round(sum(v["total_kwh"] for v in mois.values()), 2) if mois else None


@dataclass(frozen=True, kw_only=True)
class LabellenergieConsoDescription(SensorEntityDescription):
    """Capteur calculé à partir des données du PDL (consommation, températures, offre)."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


_KWH = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "suggested_display_precision": 2,
}


def _val(c: Conso | None, champ: str) -> float | None:
    return getattr(c, champ) if c is not None else None


SENSORS_CONSO: tuple[LabellenergieConsoDescription, ...] = (
    # Mois en cours (remis à zéro le 1er : total_increasing)
    *(
        LabellenergieConsoDescription(
            key=f"conso_mois_{champ}",
            translation_key=f"conso_mois_{champ}",
            state_class=SensorStateClass.TOTAL_INCREASING,
            value_fn=lambda pdl, champ=champ: _val(_mois_conso(pdl, 0), champ),
            attrs_fn=lambda pdl: _attrs_periode(_mois_conso(pdl, 0)),
            **_KWH,
        )
        for champ in ("hp", "hc", "total")
    ),
    # Mois précédent (valeur figée)
    *(
        LabellenergieConsoDescription(
            key=f"conso_mois_precedent_{champ}",
            translation_key=f"conso_mois_precedent_{champ}",
            value_fn=lambda pdl, champ=champ: _val(_mois_conso(pdl, -1), champ),
            attrs_fn=lambda pdl: _attrs_periode(_mois_conso(pdl, -1)),
            **_KWH,
        )
        for champ in ("hp", "hc", "total")
    ),
    # Dernier jour connu (J-1 ou J-2 selon Enedis)
    *(
        LabellenergieConsoDescription(
            key=f"conso_dernier_jour_{champ}",
            translation_key=f"conso_dernier_jour_{champ}",
            value_fn=lambda pdl, champ=champ: _val(_dernier_jour(pdl), champ),
            attrs_fn=lambda pdl: _attrs_periode(_dernier_jour(pdl)),
            **_KWH,
        )
        for champ in ("hp", "hc", "total")
    ),
    # Coût calculé par La Belle Énergie (HP + HC + abonnement), jour par jour
    LabellenergieConsoDescription(
        key="cout_mois",
        translation_key="cout_mois",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=UNITE_EUR,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda pdl: _val(_cout_mois(pdl, 0), "total"),
        attrs_fn=lambda pdl: _attrs_cout(_cout_mois(pdl, 0)),
    ),
    LabellenergieConsoDescription(
        key="cout_mois_precedent",
        translation_key="cout_mois_precedent",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=UNITE_EUR,
        suggested_display_precision=2,
        value_fn=lambda pdl: _val(_cout_mois(pdl, -1), "total"),
        attrs_fn=lambda pdl: _attrs_cout(_cout_mois(pdl, -1)),
    ),
    LabellenergieConsoDescription(
        key="cout_dernier_jour",
        translation_key="cout_dernier_jour",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=UNITE_EUR,
        suggested_display_precision=2,
        value_fn=lambda pdl: _val(_cout_dernier_jour(pdl), "total"),
        attrs_fn=lambda pdl: _attrs_cout(_cout_dernier_jour(pdl)),
    ),
    LabellenergieConsoDescription(
        key="historique_conso",
        translation_key="historique_conso",
        **_KWH,
        value_fn=_total_12_mois,
        attrs_fn=lambda pdl: {"mois": _historique(pdl)},
    ),
    LabellenergieConsoDescription(
        key="part_hc_mois",
        translation_key="part_hc_mois",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda pdl: _val(_mois_conso(pdl, 0), "part_hc"),
    ),
    LabellenergieConsoDescription(
        key="temperature_mois",
        translation_key="temperature_mois",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda pdl: temperature(
            pdl.get("temperatures"), _aujourdhui().year, _aujourdhui().month
        ),
        attrs_fn=lambda pdl: {
            "annee_precedente": temperature(
                pdl.get("temperatures"), _aujourdhui().year - 1, _aujourdhui().month
            ),
            "mois_precedent": temperature(
                pdl.get("temperatures"),
                debut_mois(_aujourdhui(), -1).year,
                debut_mois(_aujourdhui(), -1).month,
            ),
            "historique": pdl.get("temperatures") or {},
        },
    ),
    LabellenergieConsoDescription(
        key="nom_offre",
        translation_key="nom_offre",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda pdl: pdl.get("nom_offre"),
        attrs_fn=lambda pdl: {
            "type_offre": (pdl.get("offre") or {}).get("typeOffre"),
            "option": (pdl.get("offre") or {}).get("calendrierLibelle"),
        },
    ),
)

PRIX_ACTUEL = SensorEntityDescription(
    key="prix_actuel",
    translation_key="prix_actuel",
    native_unit_of_measurement=UNITE_EUR_KWH,
    suggested_display_precision=5,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LabellenergieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs de chaque point de livraison."""

    def _creer(coordinator: LabellenergieCoordinator, numero: str) -> list[Entity]:
        return [
            *(LabellenergieSensor(coordinator, numero, d) for d in SENSORS),
            *(LabellenergieFacture(coordinator, numero, d) for d in SENSORS_FACTURES),
            *(LabellenergiePdlSensor(coordinator, numero, d) for d in SENSORS_PDL),
            *(LabellenergieConsoSensor(coordinator, numero, d) for d in SENSORS_CONSO),
            LabellenergiePrixActuel(coordinator, numero, PRIX_ACTUEL),
        ]

    ajouter_entites_par_pdl(entry, async_add_entities, _creer)


class LabellenergieSensor(LabellenergieEntity, SensorEntity):
    """Valeur lue dans `offreCourante`."""

    entity_description: LabellenergieSensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._offre)

    @property
    def _a_une_valeur(self) -> bool:
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attrs_fn
        return attrs_fn(self._offre) if attrs_fn else None


class LabellenergiePdlSensor(LabellenergieSensor):
    """Valeur lue dans le PDL lui-même (numéro, adresse)."""

    @property
    def native_value(self) -> Any:
        pdl = self._pdl
        return self.entity_description.value_fn(pdl) if pdl else None


class LabellenergiePrixActuel(LabellenergieBasculeEntity, SensorEntity):
    """Prix du kWh en vigueur, recalculé uniquement aux bascules HC/HP."""

    @property
    def native_value(self) -> float | None:
        if self._pdl is None:
            return None
        return prix_actuel(self._offre, dt_util.now()).prix

    @property
    def _a_une_valeur(self) -> bool:
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._pdl is None:
            return None
        courant = prix_actuel(self._offre, dt_util.now())
        return {"heure_creuse": courant.heure_creuse, "option": courant.option}


class LabellenergieFacture(LabellenergieEntity, SensorEntity):
    """Montants payés, calculés sur l'historique des factures mensuelles."""

    entity_description: LabellenergieFactureDescription
    _backfill_demande = False

    @property
    def _factures(self) -> list[Facture]:
        pdl = self._pdl
        return (pdl.get("factures") if pdl else None) or []

    @property
    def native_value(self) -> float | None:
        factures = self._factures
        if not factures:
            return None
        annee = dt_util.now().astimezone(TIMEZONE).year
        return self.entity_description.value_fn(factures, annee)

    @property
    def _a_une_valeur(self) -> bool:
        return self.native_value is not None

    @property
    def last_reset(self) -> datetime | None:
        fn = self.entity_description.last_reset_fn
        factures = self._factures
        return fn(factures) if fn and factures else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        factures = self._factures
        return fn(factures) if fn and factures and self.native_value is not None else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_backfill()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Les factures ont pu manquer au démarrage (erreur réseau) : on réessaie.
        if not self._backfill_demande:
            self.hass.async_create_task(self._async_backfill())
        super()._handle_coordinator_update()

    async def _async_backfill(self) -> None:
        mode = self.entity_description.backfill
        factures = self._factures
        if mode is None or not factures or self._backfill_demande:
            return
        self._backfill_demande = True
        await async_backfill(
            self.hass, self.entity_id, factures, cumulatif=mode == "cumul"
        )


class LabellenergieConsoSensor(LabellenergieEntity, SensorEntity):
    """Consommation HP/HC, température du mois, nom de l'offre."""

    entity_description: LabellenergieConsoDescription

    @property
    def native_value(self) -> Any:
        pdl = self._pdl
        return self.entity_description.value_fn(pdl) if pdl else None

    @property
    def _a_une_valeur(self) -> bool:
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        pdl = self._pdl
        return fn(pdl) if fn and pdl else None
