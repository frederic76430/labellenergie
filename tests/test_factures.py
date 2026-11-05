"""Tests de factures.py (logique pure)."""

from datetime import date, datetime, timezone

from labellenergie.factures import (
    debut_mois_utc,
    parse_factures,
    total_annee,
    total_glissant,
)

# Même forme que la réponse de l'API : clés en chaînes, dans le désordre,
# mois manquants (2025-1 à 2025-7), un mois à 0 (2026-10).
EXEMPLE = {
    "2025": {
        "11": {"total_ttc": 16.0, "total_ht": 13.0},
        "9": {"total_ttc": 13.0, "total_ht": 11.0},
        "12": {"total_ttc": 17.0, "total_ht": 14.0},
        "10": {"total_ttc": 14.0, "total_ht": 12.0},
        "8": {"total_ttc": 25.0, "total_ht": 23.0},
    },
    "2026": {
        "4": {"total_ttc": 20.0, "total_ht": 17.0},
        "10": {"total_ttc": 0.0, "total_ht": 0.0},
        "5": {"total_ttc": 30.0, "total_ht": 25.0},
        "2": {"total_ttc": 10.0, "total_ht": 8.0},
        "9": {"total_ttc": 5.0, "total_ht": 4.0},
        "7": {"total_ttc": 12.0, "total_ht": 10.0},
        "1": {"total_ttc": 11.0, "total_ht": 9.0},
        "3": {"total_ttc": 15.0, "total_ht": 12.0},
        "6": {"total_ttc": 22.0, "total_ht": 18.0},
        "8": {"total_ttc": 8.0, "total_ht": 7.0},
    },
}
TOTAL_2025 = 85.0
TOTAL_2026 = 133.0


def test_tri_chronologique_malgre_cles_en_desordre():
    factures = parse_factures(EXEMPLE)
    mois = [f.mois for f in factures]
    assert mois == sorted(mois)
    assert mois[0] == date(2025, 8, 1)
    assert mois[-1] == date(2026, 10, 1)
    assert len(factures) == 15


def test_cumul():
    factures = parse_factures(EXEMPLE)
    assert factures[0].cumul == 25.0
    assert factures[-1].cumul == TOTAL_2025 + TOTAL_2026
    assert factures[-1].total_ttc == 0.0  # montant nul mais bien pris en compte
    assert factures[-1].total_ht == 0.0
    cumuls = [f.cumul for f in factures]
    assert cumuls == sorted(cumuls)


def test_cumul_arrondi_aux_centimes():
    data = {"2026": {"1": {"total_ttc": 0.1}, "2": {"total_ttc": 0.2}}}
    assert parse_factures(data)[-1].cumul == 0.3  # pas 0.30000000000000004


def test_entrees_illisibles_ignorees():
    data = {
        "2026": {
            "1": {"total_ttc": 10.0},
            "2": {"total_ht": 3.0},  # sans total_ttc
            "3": {"total_ttc": "oops"},
            "4": "pas un dict",
            "13": {"total_ttc": 5.0},  # mois invalide
            "x": {"total_ttc": 5.0},
        },
        "abc": {"1": {"total_ttc": 1.0}},
        "2027": None,
    }
    factures = parse_factures(data)
    assert [(f.mois, f.total_ttc) for f in factures] == [(date(2026, 1, 1), 10.0)]


def test_donnees_vides_ou_invalides():
    assert parse_factures({}) == []
    assert parse_factures(None) == []
    assert parse_factures([]) == []


def test_debut_mois_utc_heure_ete_et_hiver():
    assert debut_mois_utc(date(2026, 7, 1)) == datetime(
        2026, 6, 30, 22, tzinfo=timezone.utc
    )
    assert debut_mois_utc(date(2026, 1, 1)) == datetime(
        2025, 12, 31, 23, tzinfo=timezone.utc
    )


def test_total_annee():
    factures = parse_factures(EXEMPLE)
    assert total_annee(factures, 2025) == TOTAL_2025
    assert total_annee(factures, 2026) == TOTAL_2026
    assert total_annee(factures, 2024) is None
    assert total_annee([], 2026) is None


def test_total_glissant_se_termine_au_dernier_mois_facture():
    total, debut, fin = total_glissant(parse_factures(EXEMPLE))
    assert (debut, fin) == (date(2025, 11, 1), date(2026, 10, 1))
    assert total == 16.0 + 17.0 + TOTAL_2026  # 2025-11, 2025-12, puis tout 2026


def test_total_glissant_a_cheval_sur_deux_annees_et_mois_manquants():
    data = {"2025": {"12": {"total_ttc": 10.0}}, "2026": {"1": {"total_ttc": 5.0}}}
    total, debut, fin = total_glissant(parse_factures(data))
    assert (total, debut, fin) == (15.0, date(2025, 2, 1), date(2026, 1, 1))
    assert total_glissant([]) is None


REPONSE_REELLE = {"data": {"2026": {
    "9": {"facture": ["c715dcc3"], "contributions_et_taxes": 13.04, "abonnement": 11.51, "consommation": 16.19,
          "frais": 0.0, "services": 0, "solde": 0.0, "cheque_energie": 0.0, "total_ttc": 40.74, "total_ht": 33.95, "total_du": 40.74},
    "10": {"facture": ["a506b9f3"], "contributions_et_taxes": 10.494, "abonnement": 11.14, "consommation": -1.81,
           "frais": 0.0, "services": 0, "solde": 0.0, "cheque_energie": 0.0, "total_ttc": 19.82, "total_ht": 16.52, "total_du": 19.82},
    "8": {"facture": ["b7d5279c"], "contributions_et_taxes": 5.858, "abonnement": 4.0, "consommation": 4.89,
          "frais": 0.0, "services": 0, "solde": 0.0, "cheque_energie": 0.0, "total_ttc": 14.75, "total_ht": 12.29, "total_du": 14.75},
}}}


def test_reponse_reelle_avec_detail():
    factures = parse_factures(REPONSE_REELLE)
    assert [f.mois.month for f in factures] == [8, 9, 10]
    assert factures[-1].cumul == 75.31
    octobre = factures[-1].details
    assert octobre["consommation"] == -1.81 and octobre["contributions_et_taxes"] == 10.49
    assert octobre["facture"] == ["a506b9f3"]
    # le détail TTC retombe sur le total
    assert round(octobre["consommation"] + octobre["abonnement"] + octobre["contributions_et_taxes"], 2) == 19.82
