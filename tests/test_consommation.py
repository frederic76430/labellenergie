"""Tests de la lecture des consommations (sans Home Assistant)."""

from datetime import date

from custom_components.labellenergie.consommation import (
    somme,
    debut_mois,
    fin_mois,
    parse_consommations,
    periode_du,
    temperature,
)

# Réponse réelle de data-consommations (novembre 2026, granularité mois)
NOVEMBRE = {
    "consommations": [
        {
            "dateDebut": "2026-11-01T00:00:00",
            "dateFin": "2026-11-30T23:59:59",
            "kWh": {"112": 8.029, "111": 3.157},
        }
    ],
    "granularite": "month",
    "estime": {"estime": False, "dateDebutFine": None},
}


def test_hp_hc_total():
    (c,) = parse_consommations(NOVEMBRE)
    assert (c.debut, c.fin) == (date(2026, 11, 1), date(2026, 11, 30))
    assert c.hp == 3.157 and c.hc == 8.029 and c.autres == 0
    assert c.total == 11.186
    assert c.part_hc == 71.8


def test_code_inconnu_compte_dans_le_total():
    (c,) = parse_consommations(
        {"consommations": [{"dateDebut": "2026-10-01T00:00:00", "dateFin": "2026-10-31T23:59:59",
                            "kWh": {"111": 1.0, "112": 2.0, "999": 0.5}}]}
    )
    assert c.autres == 0.5 and c.total == 3.5


def test_entrees_illisibles_ignorees():
    assert parse_consommations(None) == []
    assert parse_consommations({"consommations": [{"dateDebut": "x"}, "texte", {}]}) == []


def test_periodes_triees_et_recherche():
    data = {"consommations": [
        {"dateDebut": "2026-11-01T00:00:00", "dateFin": "2026-11-30T23:59:59", "kWh": {"111": 1}},
        {"dateDebut": "2026-10-01T00:00:00", "dateFin": "2026-10-31T23:59:59", "kWh": {"111": 2}},
    ]}
    periodes = parse_consommations(data)
    assert [p.debut.month for p in periodes] == [10, 11]
    assert periode_du(periodes, date(2026, 10, 15)).hp == 2
    assert periode_du(periodes, date(2026, 12, 1)) is None


def test_mois():
    assert debut_mois(date(2026, 1, 15), -1) == date(2025, 12, 1)
    assert debut_mois(date(2026, 12, 3), 1) == date(2027, 1, 1)
    assert fin_mois(date(2026, 2, 10)) == date(2026, 2, 28)


def test_temperature():
    t = {"2026": {"11": 10.267391304347827}}
    assert temperature(t, 2026, 11) == 10.3
    assert temperature(t, 2025, 11) is None
    assert temperature(None, 2026, 11) is None


def test_reponse_enveloppee_dans_data():
    (c,) = parse_consommations({"data": NOVEMBRE})
    assert c.total == 11.186


def test_euros_reels_et_somme():
    data = {"data": {"consommations": [
        {"dateDebut": "2026-11-01T00:00:00", "dateFin": "2026-11-01T23:59:59",
         "euros": {"112": 1.1898978, "111": 0.60311328, "abonnement": 0.4953797260273972}},
        {"dateDebut": "2026-11-02T00:00:00", "dateFin": "2026-11-02T23:59:59",
         "euros": {"111": 0.14060544, "112": 1.36344, "abonnement": 0.4953797260273972}},
    ], "granularite": "day"}}
    jours = parse_consommations(data, "euros")
    assert round(jours[0].hp / 0.19104, 3) == 3.157  # = kWh HP du 1er novembre
    total = somme(jours, date(2026, 11, 1), date(2026, 11, 30))
    assert round(total.total, 2) == 4.29
    assert round(total.autres, 2) == 0.99
