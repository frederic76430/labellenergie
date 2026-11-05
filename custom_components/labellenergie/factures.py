"""Historique de facturation : logique pure (sans dépendance à Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Paris")


class Facture(NamedTuple):
    """Facture d'un mois, avec le cumul des factures jusqu'à ce mois inclus."""

    mois: date  # 1er jour du mois
    total_ttc: float
    total_ht: float | None
    cumul: float
    # Détail TTC : consommation, abonnement, contributions_et_taxes, frais, services,
    # cheque_energie, solde, total_du (+ "facture" : identifiants des factures)
    details: dict[str, Any] = {}


def _nombre(valeur: Any) -> float | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return float(valeur)


def parse_factures(data: Any) -> list[Facture]:
    """`{"2025": {"11": {"total_ttc": ...}}}` → factures triées, cumul calculé.

    Les clés sont des chaînes dans le désordre ; les entrées illisibles ou sans
    `total_ttc` numérique sont ignorées.
    """
    if not isinstance(data, dict):
        return []
    # Le site peut envelopper la réponse dans {"data": {...}}
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    mensuelles: list[tuple[date, float, float | None, dict[str, Any]]] = []
    for annee, mois_data in data.items():
        if not isinstance(mois_data, dict):
            continue
        for mois, facture in mois_data.items():
            try:
                debut = date(int(annee), int(mois), 1)
            except (TypeError, ValueError):
                continue
            total_ttc = _nombre(facture.get("total_ttc")) if isinstance(facture, dict) else None
            if total_ttc is None:
                continue
            details: dict[str, Any] = {
                cle: round(v, 2)
                for cle, val in facture.items()
                if cle not in ("total_ttc", "total_ht") and (v := _nombre(val)) is not None
            }
            if isinstance(facture.get("facture"), list):
                details["facture"] = [str(f) for f in facture["facture"]]
            mensuelles.append((debut, total_ttc, _nombre(facture.get("total_ht")), details))

    factures: list[Facture] = []
    cumul = 0.0
    for debut, total_ttc, total_ht, details in sorted(mensuelles, key=lambda m: m[0]):
        cumul += total_ttc
        factures.append(Facture(debut, total_ttc, total_ht, round(cumul, 2), details))
    return factures


def debut_mois_utc(mois: date) -> datetime:
    """Minuit, heure de Paris, le 1er du mois, en UTC (heure pile exigée par le recorder)."""
    return datetime(mois.year, mois.month, 1, tzinfo=TIMEZONE).astimezone(timezone.utc)


def total_annee(factures: list[Facture], annee: int) -> float | None:
    """Somme des factures de l'année civile ; `None` si aucune facture cette année-là."""
    totaux = [f.total_ttc for f in factures if f.mois.year == annee]
    return round(sum(totaux), 2) if totaux else None


def total_glissant(factures: list[Facture]) -> tuple[float, date, date] | None:
    """Somme des 12 mois se terminant au dernier mois facturé.

    Renvoie (total, premier mois de la fenêtre, dernier mois) ; `None` sans facture.
    """
    if not factures:
        return None
    fin = factures[-1].mois
    index_fin = fin.year * 12 + fin.month - 1
    index_debut = index_fin - 11
    debut = date(index_debut // 12, index_debut % 12 + 1, 1)
    total = sum(f.total_ttc for f in factures if f.mois >= debut)
    return round(total, 2), debut, fin
