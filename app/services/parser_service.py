"""Parse free-text money messages into structured data via Gemini.

Uses Gemini *controlled generation* (``response_schema`` +
``response_mime_type="application/json"``). This is the Gemini equivalent of
tool/function calling for a guaranteed-valid JSON payload: the model is
constrained to emit exactly the :class:`ParsedTransaction` shape, so we never
have to defensively parse malformed output.

The actual API call (with retries + fallback model) lives in
:mod:`app.services.gemini`.
"""

from __future__ import annotations

import structlog

from app.services import gemini
from app.services.schemas import ParsedTransaction

log = structlog.get_logger(__name__)

_SYSTEM_INSTRUCTION = """
Ты — парсер финансовых операций для казахстанского пользователя.
На вход — одна строка на русском, казахском или смеси. Верни ТОЛЬКО JSON по схеме.

ЗАДАЧА: извлечь сумму, тип операции, категорию и краткое описание.

ПРАВИЛА СУММЫ:
- Валюта по умолчанию — тенге (KZT). Символы ₸, "тг", "тенге" игнорируй как единицу.
- "к"/"k"/"тыс" = тысячи: "5к" → 5000, "1.5к" → 1500.
- "млн"/"м" = миллионы: "1.2млн" → 1200000.
- Пробелы и разделители внутри числа убирай: "1 500", "1,500", "1.500" → 1500.
- amount всегда положительное число. Знак определяет поле type, а не сумму.

ПРАВИЛА ТИПА (type):
- "expense" — трата (по умолчанию, если не сказано иное).
- "income" — доход: зарплата, аванс, перевод "получил/пришло/закинули", кэшбэк, возврат.

ПРАВИЛА КАТЕГОРИИ:
- Выбери ОДНУ категорию из списка ниже. Если явно не подходит ни одна —
  верни короткое название новой категории строчными буквами (1-2 слова).
- Категория и описание — НА КАЗАХСКОМ. Синонимы веди к списку: "кафе",
  "рестораны", "перекус" → "сырттағы тамақ".
- Рассрочка, кредит, взнос по кредиту, погашение долга, ипотека →
  "несие мен бөліп төлеу".
- Регулярная помощь/перевод родственнику (дедушка, мама, родители, семья) →
  "отбасыға көмек". Разовый перевод другому человеку → "аударымдар".
Разрешённые категории (возвращай ИМЕННО эти казахские названия):
["азық-түлік", "сырттағы тамақ", "көлік", "такси", "тұрғын үй", "коммуналдық",
 "байланыс пен интернет", "денсаулық", "киім", "ойын-сауық", "жазылымдар",
 "білім", "балаларға", "сыйлықтар", "саяхат", "несие мен бөліп төлеу",
 "отбасыға көмек", "аударымдар", "басқа", "жалақы", "стипендия", "өзге кіріс"]

ПРАВИЛА ОПИСАНИЯ (description):
- 1-4 слова НА КАЗАХСКОМ, суть операции без суммы.
  "кофе в старбакс 1200" → "кофе".
- Если ничего осмысленного нет — пустая строка.

НЕОДНОЗНАЧНОСТЬ:
- Если суммы в тексте НЕТ или строка не про деньги — верни amount: 0 и confidence: "low".
- confidence: "high" если сумма и смысл однозначны, иначе "low".

КОМАНДЫ ИЗМЕНЕНИЯ (НЕ новая операция!):
- Если сообщение — это просьба ИЗМЕНИТЬ, ПЕРЕКЛАССИФИЦИРОВАТЬ, УДАЛИТЬ или
  ОТМЕНИТЬ уже существующую операцию ("смени X на Y", "поменяй категорию",
  "измени прошлую трату", "переклассифицируй", "исправь предыдущую запись") —
  это НЕ новая транзакция. Верни amount: 0, confidence: "low",
  description: "команда изменения, не операция".
- Создавай новую операцию только если сообщение явно описывает НОВОЕ движение
  денег (потратил/получил/заплатил и т.п.), а не редактирование старой записи.

Не добавляй пояснений, markdown или текста вне JSON.
""".strip()


class ExpenseParseError(RuntimeError):
    """Raised when the model returned no usable transaction."""


class ParserService:
    """Turns free text into a :class:`ParsedTransaction` via Gemini."""

    async def parse(self, text: str) -> ParsedTransaction:
        """Parse ``text`` into a :class:`ParsedTransaction`.

        Raises :class:`ExpenseParseError` if the model cannot extract a
        positive amount. Transient Gemini errors (503/429) are retried
        internally; a persistent failure propagates as the original API error.
        """
        parsed = await gemini.generate_json(
            contents=text,
            schema=ParsedTransaction,
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.0,
        )
        if parsed is None:
            raise ExpenseParseError("model returned no structured output")
        if parsed.amount <= 0:
            raise ExpenseParseError(f"no amount in message: {text!r}")

        log.info(
            "expense_parsed",
            amount=parsed.amount,
            category=parsed.category,
            type=parsed.type.value,
            confidence=parsed.confidence,
        )
        return parsed
