"""Tests d'intégration avec Home Assistant (nécessite pytest-homeassistant-custom-component)."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.labellenergie.api import ApiError, AuthError, LabellenergieClient  # noqa: E402
from custom_components.labellenergie.const import DOMAIN  # noqa: E402
from custom_components.labellenergie.consommation import parse_consommations  # noqa: E402
from custom_components.labellenergie.factures import parse_factures  # noqa: E402

FACTURES = parse_factures(
    {
        "2025": {"11": {"total_ttc": 16.0}, "12": {"total_ttc": 17.0}},
        "2026": {
            "1": {"total_ttc": 11.0, "total_ht": 9.0},
            "9": {"total_ttc": 5.0},
            "10": {"total_ttc": 0.0, "total_ht": 0.0},
        },
    }
)

CONSO = {
    "mois": parse_consommations({"consommations": [
        {"dateDebut": "2026-08-01T00:00:00", "dateFin": "2026-08-31T23:59:59", "kWh": {}},
        {"dateDebut": "2026-09-01T00:00:00", "dateFin": "2026-09-30T23:59:59", "kWh": {"111": 50.0, "112": 150.0}},
        {"dateDebut": "2026-10-01T00:00:00", "dateFin": "2026-10-31T23:59:59", "kWh": {"112": 8.029, "111": 3.157}},
    ]}),
    "jours": parse_consommations({"consommations": [
        {"dateDebut": "2026-10-13T00:00:00", "dateFin": "2026-10-13T23:59:59", "kWh": {"111": 2.0, "112": 6.0}},
        {"dateDebut": "2026-10-14T00:00:00", "dateFin": "2026-10-14T23:59:59", "kWh": {}},
    ]}),
    "mois_euros": parse_consommations({"consommations": [
        {"dateDebut": "2026-09-01T00:00:00", "dateFin": "2026-09-30T23:59:59", "euros": {"111": 9.5, "112": 22.2, "abonnement": 14.86}},
    ]}, "euros"),
    "euros": parse_consommations({"data": {"consommations": [
        {"dateDebut": "2026-09-30T00:00:00", "dateFin": "2026-09-30T23:59:59", "euros": {"111": 1.0, "112": 1.0, "abonnement": 0.5}},
        {"dateDebut": "2026-10-13T00:00:00", "dateFin": "2026-10-13T23:59:59", "euros": {"112": 0.9609288, "111": 0.13716672, "abonnement": 0.4953797260273972}},
        {"dateDebut": "2026-10-14T00:00:00", "dateFin": "2026-10-14T23:59:59", "euros": {"112": 0.5146986, "111": 0.01604736, "abonnement": 0.4953797260273972}},
    ]}}, "euros"),
}

NUMERO = "12345678901234"
NOM = "labelleenergie - 12 rue des Lilas"
ADRESSE = "Bât. A 12 rue des Lilas, 75000 PARIS"
PDLS = {
    NUMERO: {
        "numero": NUMERO,
        "pdc_contrat_id": "c1",
        "nom": NOM,
        "adresse": ADRESSE,
        "type_compteur": "Compteur Linky",
        "offre": {
            "puissance": 6.0,
            "abonnement": 15.1266,
            "base": None,
            "hp": 0.189,
            "hc": 0.14676,
            "plagesHc": ["1h04 - 7h04", "14h34 - 16h34"],
            "lastChange": "2026-06-25",
        },
        "factures": FACTURES,
        "nom_offre": "Prudence",
        "offre_future": None,
        "repricing": None,
        "consommations": CONSO,
        "temperatures": {"2025": {"10": 13.69}, "2026": {"9": 20.48, "10": 14.73}},
    }
}
PDL_BASE = {
    "numero": "999",
    "pdc_contrat_id": "c2",
    "nom": "labelleenergie - Autre rue",
    "adresse": "Autre rue, 75000 PARIS",
    "type_compteur": "Compteur Linky",
    "offre": {
        "puissance": 9.0,
        "abonnement": 20.0,
        "base": 0.2,
        "hp": None,
        "hc": None,
        "plagesHc": [],
        "lastChange": "2026-01-01",
    },
}


@pytest.fixture(autouse=True)
def _enable(recorder_mock, enable_custom_integrations):
    yield


@pytest.fixture
def get_pdls():
    """Remplace l'appel réseau pendant toute la durée du test (y compris les relances à 24 h)."""
    with patch.object(LabellenergieClient, "async_get_pdls", AsyncMock()) as mock:
        yield mock


async def _setup(hass, get_pdls, pdls):
    get_pdls.return_value = pdls
    entry = MockConfigEntry(
        domain=DOMAIN, data={"email": "a@b.fr", "password": "pw"}, unique_id="a@b.fr"
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass, numero, key, domaine="sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(domaine, DOMAIN, f"{numero}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_entites_et_appareil(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T00:30:00+02:00")
    entry = await _setup(hass, get_pdls, deepcopy(PDLS))
    assert entry.state is ConfigEntryState.LOADED

    appareil = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, NUMERO)})
    assert appareil.name == NOM

    assert float(_state(hass, NUMERO, "abonnement").state) == 15.1266
    assert float(_state(hass, NUMERO, "prix_hc").state) == 0.14676
    assert float(_state(hass, NUMERO, "prix_hp").state) == 0.189
    assert _state(hass, NUMERO, "prix_base").state == "unavailable"
    assert _state(hass, NUMERO, "plages_hc").state == "1h04 - 7h04, 14h34 - 16h34"
    assert float(_state(hass, NUMERO, "puissance").state) == 6.0
    assert _state(hass, NUMERO, "derniere_modification").state == "2026-06-25"
    prix = _state(hass, NUMERO, "prix_actuel")
    assert float(prix.state) == 0.189
    assert prix.attributes["unit_of_measurement"] == "EUR/kWh"
    assert _state(hass, NUMERO, "numero_pdl").state == NUMERO
    assert _state(hass, NUMERO, "adresse").state == ADRESSE


async def test_entites_en_diagnostic_sauf_prix_actuel(hass, get_pdls):
    await _setup(hass, get_pdls, deepcopy(PDLS))
    registre = er.async_get(hass)
    categories = {
        e.unique_id.removeprefix(f"{NUMERO}_"): e.entity_category
        for e in registre.entities.values()
        if e.platform == DOMAIN
    }
    assert categories.pop("prix_actuel") is None
    assert categories.pop("heure_creuse") is None
    assert categories.pop("calendrier_hc") is None
    for cle in (
        "total_ttc",
        "cumulative_total_ttc",
        "total_annee_passee",
        "total_annee_en_cours",
        "total_annee_glissante",
        "changement_tarif",
        "part_hc_mois",
        "temperature_mois",
        "cout_mois",
        "cout_mois_precedent",
        "cout_dernier_jour",
        "historique_conso",
        "historique_factures",
        *(f"conso_{p}_{c}" for p in ("mois", "mois_precedent", "dernier_jour") for c in ("hp", "hc", "total")),
    ):
        assert categories.pop(cle) is None
    assert len(categories) == 10  # le capteur binaire et le calendrier n'en font pas partie
    assert set(categories.values()) == {er.EntityCategory.DIAGNOSTIC}


async def test_capteurs_de_facturation(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T12:00:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))

    mensuel = _state(hass, NUMERO, "total_ttc")
    assert float(mensuel.state) == 0.0
    assert mensuel.attributes["mois"] == "2026-10"
    assert mensuel.attributes["total_ht"] == 0.0
    assert mensuel.attributes["last_reset"].startswith("2026-09-30T22:00:00")
    assert mensuel.attributes["unit_of_measurement"] == "EUR"
    assert mensuel.attributes["device_class"] == "monetary"

    assert float(_state(hass, NUMERO, "cumulative_total_ttc").state) == 49.0
    assert float(_state(hass, NUMERO, "total_annee_passee").state) == 33.0
    assert float(_state(hass, NUMERO, "total_annee_en_cours").state) == 16.0
    glissant = _state(hass, NUMERO, "total_annee_glissante")
    assert float(glissant.state) == 49.0
    assert glissant.attributes["mois_debut"] == "2025-11"
    assert glissant.attributes["mois_fin"] == "2026-10"


async def test_totaux_annuels_au_changement_d_annee(
    hass, freezer, get_pdls
):
    freezer.move_to("2027-01-10T12:00:00+01:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    assert float(_state(hass, NUMERO, "total_annee_en_cours").state) == 0.0
    assert float(_state(hass, NUMERO, "total_annee_passee").state) == 16.0
    freezer.move_to("2028-06-01T12:00:00+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    # rafraîchissement 24 h plus tard, deux ans après : plus de facture en 2027
    assert _state(hass, NUMERO, "total_annee_passee").state == "unavailable"
    assert float(_state(hass, NUMERO, "total_annee_en_cours").state) == 0.0


async def test_capteurs_de_facturation_indisponibles_sans_facture(hass, get_pdls):
    pdls = deepcopy(PDLS)
    pdls[NUMERO]["factures"] = []
    await _setup(hass, get_pdls, pdls)
    for cle in (
        "total_ttc",
        "cumulative_total_ttc",
        "total_annee_passee",
        "total_annee_en_cours",
        "total_annee_glissante",
    ):
        assert _state(hass, NUMERO, cle).state == "unavailable"
    # les tarifs restent disponibles
    assert float(_state(hass, NUMERO, "prix_hp").state) == 0.189


async def test_backfill_de_l_historique(hass, get_pdls):
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    await _setup(hass, get_pdls, deepcopy(PDLS))
    await async_wait_recording_done(hass)

    for cle, etat, somme in (
        ("total_ttc", [16.0, 17.0, 11.0, 5.0, 0.0], [16.0, 33.0, 44.0, 49.0, 49.0]),
        ("cumulative_total_ttc", [16.0, 33.0, 44.0, 49.0, 49.0], [16.0, 33.0, 44.0, 49.0, 49.0]),
    ):
        entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{NUMERO}_{cle}")
        stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            dt_util.utc_from_timestamp(0),
            None,
            {entity_id},
            "hour",
            None,
            {"state", "sum"},
        )
        lignes = stats[entity_id]
        assert [round(ligne["state"], 2) for ligne in lignes] == etat, cle
        assert [round(ligne["sum"], 2) for ligne in lignes] == somme, cle
        # un point par mois, au 1er du mois à minuit (heure de Paris)
        debuts = [dt_util.utc_from_timestamp(ligne["start"]).isoformat() for ligne in lignes]
        assert debuts[0].startswith("2025-10-31T23:00") and debuts[-1].startswith("2026-09-30T22:00")


async def test_backfill_une_seule_fois(hass, freezer, get_pdls):
    from homeassistant.components.recorder.statistics import async_import_statistics
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    with patch(
        "custom_components.labellenergie.statistiques.async_import_statistics",
        wraps=async_import_statistics,
    ) as importe:
        entry = await _setup(hass, get_pdls, deepcopy(PDLS))
        await async_wait_recording_done(hass)
        assert importe.call_count == 2  # mensuel + cumul

        # rechargement : les statistiques existent, rien n'est réimporté
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await async_wait_recording_done(hass)
        assert importe.call_count == 2


async def test_prix_actuel_bascule_aux_heures_de_changement(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T00:30:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    assert float(_state(hass, NUMERO, "prix_actuel").state) == 0.189

    for instant, prix, creuse in [
        ("2026-10-15T01:04:00+02:00", 0.14676, True),
        ("2026-10-15T07:04:00+02:00", 0.189, False),
        ("2026-10-15T14:34:00+02:00", 0.14676, True),
        ("2026-10-15T16:34:00+02:00", 0.189, False),
        ("2026-10-16T01:04:00+02:00", 0.14676, True),  # lendemain
    ]:
        freezer.move_to(instant)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        etat = _state(hass, NUMERO, "prix_actuel")
        assert float(etat.state) == prix, instant
        assert etat.attributes["heure_creuse"] is creuse


async def test_capteur_binaire_heure_creuse(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T00:30:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    assert _state(hass, NUMERO, "heure_creuse", "binary_sensor").state == "off"

    for instant, attendu in [
        ("2026-10-15T01:04:00+02:00", "on"),
        ("2026-10-15T07:04:00+02:00", "off"),
        ("2026-10-15T14:34:00+02:00", "on"),
    ]:
        freezer.move_to(instant)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert _state(hass, NUMERO, "heure_creuse", "binary_sensor").state == attendu


async def test_calendrier_heures_creuses(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T00:30:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    cal = _state(hass, NUMERO, "calendrier_hc", "calendar")
    assert cal.state == "off"
    assert cal.attributes["message"] == "Heures creuses"
    # L'attribut est exprimé dans le fuseau configuré de HA, d'où la comparaison d'instants.
    debut = dt_util.parse_datetime(cal.attributes["start_time"]).replace(
        tzinfo=dt_util.get_default_time_zone()
    )
    assert debut == dt_util.parse_datetime("2026-10-15T01:04:00+02:00")

    freezer.move_to("2026-10-15T02:00:00+02:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert _state(hass, NUMERO, "calendrier_hc", "calendar").state == "on"

    reponse = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": _state(hass, NUMERO, "calendrier_hc", "calendar").entity_id,
            "start_date_time": "2026-10-15T00:00:00+02:00",
            "end_date_time": "2026-10-16T00:00:00+02:00",
        },
        blocking=True,
        return_response=True,
    )
    evenements = next(iter(reponse.values()))["events"]
    assert [(e["start"], e["end"]) for e in evenements] == [
        ("2026-10-15T01:04:00+02:00", "2026-10-15T07:04:00+02:00"),
        ("2026-10-15T14:34:00+02:00", "2026-10-15T16:34:00+02:00"),
    ]


async def test_offre_base_sans_bascule(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T00:30:00+02:00")
    await _setup(hass, get_pdls, {"999": deepcopy(PDL_BASE)})
    etat = _state(hass, "999", "prix_actuel")
    assert float(etat.state) == 0.2
    assert etat.attributes["option"] == "base"
    assert _state(hass, "999", "prix_hc").state == "unavailable"
    assert _state(hass, "999", "heure_creuse", "binary_sensor").state == "unavailable"
    assert _state(hass, "999", "calendrier_hc", "calendar").state == "unavailable"


async def test_nouveau_pdl_notifie_et_entites_ajoutees(hass, get_pdls):
    entry = await _setup(hass, get_pdls, deepcopy(PDLS))
    coordinator = entry.runtime_data
    with patch(
        "custom_components.labellenergie.coordinator.persistent_notification.async_create",
        MagicMock(),
    ) as notif:
        get_pdls.return_value = {**deepcopy(PDLS), "999": deepcopy(PDL_BASE)}
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    notif.assert_called_once()
    assert notif.call_args.kwargs["notification_id"] == f"{DOMAIN}_nouveau_pdl_999"
    assert "labelleenergie - Autre rue" in notif.call_args.args[1]
    assert _state(hass, "999", "prix_actuel") is not None


async def test_pas_de_notification_a_la_configuration_initiale(hass, get_pdls):
    with patch(
        "custom_components.labellenergie.coordinator.persistent_notification.async_create",
        MagicMock(),
    ) as notif:
        await _setup(hass, get_pdls, {**deepcopy(PDLS), "999": deepcopy(PDL_BASE)})
    notif.assert_not_called()


async def test_erreur_authentification_declenche_reauth(hass, get_pdls):
    entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@b.fr", "password": "pw"})
    entry.add_to_hass(hass)
    get_pdls.side_effect = AuthError
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(hass.config_entries.flow.async_progress_by_handler(DOMAIN))


async def test_config_flow_ok(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    with (
        patch.object(LabellenergieClient, "async_login", AsyncMock()),
        patch("custom_components.labellenergie.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "Marc@Exemple.fr", "password": "x"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"email": "Marc@Exemple.fr", "password": "x"}
    assert result["result"].unique_id == "marc@exemple.fr"


@pytest.mark.parametrize(
    ("erreur", "cle"),
    [(AuthError, "invalid_auth"), (ApiError, "cannot_connect"), (RuntimeError, "unknown")],
)
async def test_config_flow_erreurs(hass, erreur, cle):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch.object(LabellenergieClient, "async_login", AsyncMock(side_effect=erreur)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "a@b.fr", "password": "x"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": cle}


async def test_consommation_temperature_offre(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T12:00:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))

    assert float(_state(hass, NUMERO, "conso_mois_hp").state) == 3.157
    assert float(_state(hass, NUMERO, "conso_mois_hc").state) == 8.029
    total = _state(hass, NUMERO, "conso_mois_total")
    assert float(total.state) == 11.186
    assert total.attributes["unit_of_measurement"] == "kWh"
    assert total.attributes["state_class"] == "total_increasing"
    assert float(_state(hass, NUMERO, "conso_mois_precedent_total").state) == 200.0
    assert float(_state(hass, NUMERO, "part_hc_mois").state) == 71.8
    # dernier jour = le 13 (le 14 n'est pas encore transmis)
    jour = _state(hass, NUMERO, "conso_dernier_jour_total")
    assert float(jour.state) == 8.0
    assert jour.attributes["debut"] == "2026-10-13"
    temp = _state(hass, NUMERO, "temperature_mois")
    assert float(temp.state) == 14.7
    assert temp.attributes["annee_precedente"] == 13.7
    assert temp.attributes["mois_precedent"] == 20.5
    assert _state(hass, NUMERO, "nom_offre").state == "Prudence"
    assert _state(hass, NUMERO, "changement_tarif", "binary_sensor").state == "off"


async def test_changement_de_tarif_annonce(hass, get_pdls):
    pdls = deepcopy(PDLS)
    pdls[NUMERO]["offre_future"] = {"hp": 0.21, "dateEffet": "2027-02-01"}
    await _setup(hass, get_pdls, pdls)
    etat = _state(hass, NUMERO, "changement_tarif", "binary_sensor")
    assert etat.state == "on"
    assert etat.attributes["offre_future"]["hp"] == 0.21


async def test_consommation_indisponible_si_erreur(hass, get_pdls):
    pdls = deepcopy(PDLS)
    pdls[NUMERO]["consommations"] = {"mois": None, "jours": None}
    await _setup(hass, get_pdls, pdls)
    assert _state(hass, NUMERO, "conso_mois_total").state == "unavailable"
    assert float(_state(hass, NUMERO, "abonnement").state) == 15.1266


async def test_dernier_jour_ignore_une_reponse_mensuelle(hass, freezer, get_pdls):
    """Si la granularité « jour » est ignorée par le site, pas de faux « dernier jour »."""
    freezer.move_to("2026-10-15T12:00:00+02:00")
    pdls = deepcopy(PDLS)
    pdls[NUMERO]["consommations"]["jours"] = pdls[NUMERO]["consommations"]["mois"]
    await _setup(hass, get_pdls, pdls)
    assert _state(hass, NUMERO, "conso_dernier_jour_total").state == "unavailable"
    assert float(_state(hass, NUMERO, "conso_mois_total").state) == 11.186


async def test_couts(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T12:00:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    jour = _state(hass, NUMERO, "cout_dernier_jour")
    assert round(float(jour.state), 2) == 1.03
    assert jour.attributes["abonnement_eur"] == 0.5
    mois = _state(hass, NUMERO, "cout_mois")
    assert round(float(mois.state), 2) == round(0.9609288 + 0.13716672 + 0.5146986 + 0.01604736 + 2 * 0.4953797260273972, 2)
    assert mois.attributes["debut"] == "2026-10-13"
    assert float(_state(hass, NUMERO, "cout_mois_precedent").state) == 2.5


async def test_historique(hass, freezer, get_pdls):
    freezer.move_to("2026-10-15T12:00:00+02:00")
    await _setup(hass, get_pdls, deepcopy(PDLS))
    etat = _state(hass, NUMERO, "historique_conso")
    assert float(etat.state) == 200.0  # septembre seul (octobre en cours exclu)
    mois = etat.attributes["mois"]
    assert list(mois) == ["2026-09", "2026-10"]  # août vide ignoré
    assert mois["2026-09"]["hp_kwh"] == 50.0 and mois["2026-09"]["total_eur"] == 46.56
    assert "total_eur" not in mois["2026-10"]
