# 0314 — Code du service Agenda

Statut : accepté — 22 novembre 2026.

Le service système **Agenda** prend le code `calendar`. DbAdmin renomme la ligne existante
pour conserver son identité, ses connexions et leurs réglages. Le libellé français reste
**Agenda**. Les fonctions MCP `calendar_*` conservent leurs noms.

Si un ancien service fournisseur utilise déjà `calendar`, DbAdmin lui attribue le code
`calendar-provider` ou le premier suffixe disponible. Le fournisseur garde son identité,
son libellé, sa configuration et ses connexions. Sa capacité reste `caldav.calendar` ou
`ical.calendar`, selon sa configuration.
