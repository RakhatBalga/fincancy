"""Tests for Yahoo analyst forecast parsing."""

from app.services.market_data import YahooFinanceService


def test_parse_analyst_forecast_uses_consensus_and_latest_firms() -> None:
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "financialData": {
                        "targetLowPrice": {"raw": 80},
                        "targetMeanPrice": {"raw": 120},
                        "targetHighPrice": {"raw": 160},
                        "numberOfAnalystOpinions": {"raw": 12},
                        "recommendationKey": "buy",
                    },
                    "upgradeDowngradeHistory": {
                        "history": [
                            {
                                "firm": "Morgan Stanley",
                                "currentPriceTarget": 130,
                                "toGrade": "Overweight",
                            },
                            {
                                "firm": "Morgan Stanley",
                                "currentPriceTarget": 125,
                                "toGrade": "Overweight",
                            },
                            {
                                "firm": "Barclays",
                                "currentPriceTarget": 115,
                                "toGrade": "Buy",
                            },
                        ]
                    },
                }
            ]
        }
    }

    forecast = YahooFinanceService._parse_forecast("TEST", payload)

    assert forecast is not None
    assert forecast.target_mean == 120
    assert forecast.analyst_count == 12
    assert [item.firm for item in forecast.institution_targets] == [
        "Morgan Stanley",
        "Barclays",
    ]
    assert forecast.institution_targets[0].target_price == 130
