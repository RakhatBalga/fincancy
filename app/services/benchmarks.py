"""Reference spending structure for Kazakhstan (shares of expenses, %).

Approximate shares of household consumption expenditure by broad bucket, based
on the Bureau of National Statistics household budget survey (stat.gov.kz).
We compare *shares of total spending*, not absolute amounts — shares are fair
across income levels, unlike tenge figures.

The bot's categories are granular (продукты, еда вне дома, такси, …), so each is
mapped to a broad bucket and the user's shares are aggregated before comparing.

Numbers are rounded, illustrative reference points — not exact official figures.
Update roughly once a year from the latest published survey.
"""

from __future__ import annotations

# Broad bucket -> approximate share of total household spending (%)
KZ_BUCKET_SHARES: dict[str, float] = {
    "Питание": 48.0,
    "Жильё и ЖКХ": 15.0,
    "Транспорт": 12.0,
    "Связь": 4.0,
    "Здоровье": 7.0,
    "Одежда": 6.0,
    "Развлечения": 5.0,
    "Прочее": 3.0,
}

# Granular category (lowercase) -> broad bucket.
_CATEGORY_TO_BUCKET: dict[str, str] = {
    "продукты": "Питание",
    "еда вне дома": "Питание",
    "жильё": "Жильё и ЖКХ",
    "коммуналка": "Жильё и ЖКХ",
    "транспорт": "Транспорт",
    "такси": "Транспорт",
    "путешествия": "Транспорт",
    "связь и интернет": "Связь",
    "здоровье": "Здоровье",
    "одежда": "Одежда",
    "развлечения": "Развлечения",
    "подписки": "Развлечения",
    "образование": "Прочее",
    "детям": "Прочее",
    "подарки": "Прочее",
    "кредиты и рассрочка": "Прочее",
    "помощь семье": "Прочее",
    "переводы": "Прочее",
    "прочее": "Прочее",
}


def compare_shares(
    user_shares: dict[str, float],
) -> list[tuple[str, float, float]]:
    """Compare a user's category shares against the KZ reference buckets.

    ``user_shares`` maps category name -> percent of the user's spending.
    Categories are aggregated into broad buckets. Returns
    ``[(bucket, user_pct, kz_pct), ...]`` ordered by the size of the gap
    (user − kz) so the biggest deviations come first.
    """
    bucket_pct: dict[str, float] = {b: 0.0 for b in KZ_BUCKET_SHARES}
    for name, pct in user_shares.items():
        bucket = _CATEGORY_TO_BUCKET.get(name.strip().casefold(), "Прочее")
        bucket_pct[bucket] = bucket_pct.get(bucket, 0.0) + pct

    rows = [
        (bucket, bucket_pct.get(bucket, 0.0), kz_pct)
        for bucket, kz_pct in KZ_BUCKET_SHARES.items()
    ]
    rows.sort(key=lambda r: abs(r[1] - r[2]), reverse=True)
    return rows
