"""Constantes de l'intégration La Belle Énergie."""

from datetime import timedelta

DOMAIN = "labellenergie"

MANUFACTURER = "La Belle Énergie"

BASE_URL = "https://espace-client.labellenergie.fr"
API_LOGIN = "/portail/api/custom-token-auth"
API_LISTE_PDL = "/portail/api/v2/espace-client-liste-pdl"
API_INFOS_PDL = "/portail/api/v2/espace-client-pdl-infos"
API_FACTURES = "/portail/api/v2/espace-client/data-factures/{groupe_id}"
API_CONSO = "/portail/api/v2/espace-client/data-consommations/{pdc_contrat_id}"

USER_AGENT = "Mozilla/5.0 (compatible; HomeAssistant-labellenergie/0.1)"

# Le prix actuel (HC/HP) est recalculé localement, sans appel réseau.
# Enedis transmet la consommation de la veille dans la matinée : 4 mises à jour par jour.
UPDATE_INTERVAL = timedelta(hours=6)
NOM_APPAREIL = "labelleenergie"
