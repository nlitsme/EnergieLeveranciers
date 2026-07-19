# Batterij Dimensionering en Terugverdientijd Analyse

## Samenvatting

| Parameter | Waarde |
|-----------|--------|
| **Minimale capaciteit** (P5) | 9.0 kWh |
| **Aanbevolen capaciteit** (P50) | **9.0 kWh** |
| **Maximale capaciteit** (P95) | 9.0 kWh |

## Jaarlijks Nachverbruik
- **Totaal nachverbruik/jaar**: 2652 kWh
- **Gemiddeld per nacht**: 7.26 kWh

## Kostenaannames
- **Batterijkosten**: €600/kWh (geïnstalleerd)
- **Energieprijs**: €0.30/kWh
- **Terugleververgoeding**: €0.08/kWh
- **Bespuring per kWh**: €0.22/kWh
- **Rendement (heenu terug)**: 90%
| **Diepte ontlading**: 90% |

## Investeringsanalyse (Aanbevolen capaciteit: 9.0 kWh)

| Item | Waarde |
|------|--------|
| Batterijkosten | €5,382 |
| Jaarlijkse besparing (theoretisch max) | €583 |
| **Terugverdientijd** | **9.2 jaar** |
| Onzekerheidsmarge (±50%) | 4.6 - 13.8 jaar |

## Interpretatie

### Hoe worden de capaciteiten bepaald?
De batterijcapaciteit wordt berekend op basis van de nachtelijk elektriciteitsverbruikverdeling:
- **P5 (Minimaal)**: Dekket 95% van de nachten → kleine batterij, lage dekking
- **P50 (Aanbevolen)**: Dekket de mediaan nacht → balans tussen kost en dekking
- **P95 (Maximaal)**: Dekket 95% van de nachten → grote batterij, hoge dekking

Formule: `Capaciteit = Nachtverbruik_percentiel / (Rendement × Diepte_ontlading)`

### Terugverdientijd
De terugverdientijd is een schatting gebaseerd op:
1. Dagelijkse cyclering van de batterij (365 cycli/jaar)
2. Verschil tussen energietarief en terugleververgoeding
3. Batterijrendement en diepte-ontlading limiet

**Let op**: De ±50% onzekerheidsmarge rekening houdt met:
- Seizoensinvloeden (minder zonne-energie in winter)
- Batterijdegradatie over de jaren
- Veranderende energieprijzen
- Daadwerkelijk gebruikspatroon

### Aanbeveling
Voor een typisch huishouden met een aanbevolen capaciteit van **9.0 kWh**:
- Investeringsbedrag: ~€5,382
- Verwachte terugverdientijd: **9.2 jaar** (bereik: 4.6-13.8 jaar)
- Jaarlijkse besparing: ~€583

*Rapport gegenereerd op: 2026-07-19 19:22*
