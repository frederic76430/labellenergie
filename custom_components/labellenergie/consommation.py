"""Consommations (HP / HC) et températures : logique pure (sans dépendance à Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

# Codes des périodes tarifaires renvoyés par `data-consommations`.
# Hypothèse vérifiée sur la page « Conso » : 111 = heures pleines, 112 = heures creuses.
# Un code inconnu est compté dans `autres` (et le total reste juste).
CODES_HP = {"111"}
CODES_HC = {"112"}


class Conso(NamedTuple):
    """Consommation d'une période (jour ou mois), en kWh — ou en euros.

    En euros, `autres` contient l'abonnement (clé « abonnement » de la réponse).
    """

    debut: date
    fin: date
    hp: float
    hc: float
    autres: float
    codes: dict[str, float]

    @property
    def total(self) -> float:
        return round(self.hp + self.hc + self.autres, 3)

    @property
    def part_hc(self) -> float | None:
        """Part des heures creuses en %, `None` si rien n'a été consommé."""
        return round(self.hc / self.total * 100, 1) if self.total > 0 else None


def _jour(valeur: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(valeur)).date()
    except (TypeError, ValueError):
        return None


def parse_consommations(data: Any, champ: str = "kWh") -> list[Conso]:
    """`{"consommations": [{"dateDebut", "dateFin", "kWh": {"111": x, "112": y}}]}` → périodes triées."""
    if not isinstance(data, dict):
        return []
    # Certaines réponses sont enveloppées dans {"data": {...}}
    if "consommations" not in data and isinstance(data.get("data"), dict):
        data = data["data"]
    periodes: list[Conso] = []
    for ligne in data.get("consommations") or []:
        if not isinstance(ligne, dict):
            continue
        debut, fin = _jour(ligne.get("dateDebut")), _jour(ligne.get("dateFin"))
        kwh = ligne.get(champ)
        if debut is None or fin is None or not isinstance(kwh, dict):
            continue
        codes = {
            str(k): float(v)
            for k, v in kwh.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        hp = sum(v for k, v in codes.items() if k in CODES_HP)
        hc = sum(v for k, v in codes.items() if k in CODES_HC)
        autres = sum(v for k, v in codes.items() if k not in CODES_HP | CODES_HC)
        periodes.append(Conso(debut, fin, round(hp, 6), round(hc, 6), round(autres, 6), codes))
    return sorted(periodes, key=lambda c: c.debut)


def periode_du(periodes: list[Conso], jour: date) -> Conso | None:
    """Période qui contient `jour`."""
    return next((p for p in periodes if p.debut <= jour <= p.fin), None)


def debut_mois(jour: date, decalage: int = 0) -> date:
    """1er jour du mois de `jour`, décalé de `decalage` mois."""
    index = jour.year * 12 + jour.month - 1 + decalage
    return date(index // 12, index % 12 + 1, 1)


def fin_mois(jour: date) -> date:
    return debut_mois(jour, 1) - timedelta(days=1)


def temperature(temperatures: Any, annee: int, mois: int) -> float | None:
    """Température moyenne du mois (°C) dans `{"2026": {"11": 10.27}}`."""
    try:
        valeur = temperatures[str(annee)][str(mois)]
    except (KeyError, TypeError):
        return None
    return round(float(valeur), 1) if isinstance(valeur, (int, float)) else None


def somme(periodes: list[Conso], debut: date, fin: date) -> Conso | None:
    """Additionne les journées comprises entre `debut` et `fin` (incluses)."""
    jours = [p for p in periodes if p.debut == p.fin and debut <= p.debut <= fin and p.codes]
    if not jours:
        return None
    codes: dict[str, float] = {}
    for j in jours:
        for k, v in j.codes.items():
            codes[k] = round(codes.get(k, 0.0) + v, 6)
    return Conso(
        jours[0].debut,
        jours[-1].fin,
        round(sum(j.hp for j in jours), 4),
        round(sum(j.hc for j in jours), 4),
        round(sum(j.autres for j in jours), 4),
        codes,
    )
