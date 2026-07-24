"""SQLAlchemy ORM models for transactions and personal assets."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TransactionType(str, enum.Enum):
    """Direction of money movement."""

    expense = "expense"
    income = "income"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KZT")
    # Declared monthly income; enables the 50/30/20 advice. NULL until set.
    monthly_income: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Living situation, asked once on /start: True = free (with parents/family),
    # False = pays for it themselves, NULL = not answered yet. Used so the AI's
    # hypothetical budget doesn't invent rent/food money the user doesn't spend.
    housing_is_free: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    food_is_free: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    debt_balance: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    debt_annual_rate: Mapped[float | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    obligation_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    risk_tolerance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    official_salary_monthly: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    official_stipend_monthly: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    mortgage_payment_limit_percent: Mapped[float | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    salary_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_weekend_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stipend_timing: Mapped[str | None] = mapped_column(String(64), nullable=True)
    financial_cycle_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    installment_balance_primary: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    installment_balance_secondary: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    installment_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    installment_august_payment: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    installment_september_payment: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    installment_kaspi_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    installment_halyk_monthly_payment: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    installment_halyk_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    installment_kaspi_schedule: Mapped[list[dict[str, int]] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    budgets: Mapped[list[Budget]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    investment_positions: Mapped[list[InvestmentPosition]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    deposits: Mapped[list[Deposit]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    financial_goals: Mapped[list[FinancialGoal]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    broker_account: Mapped[BrokerAccount | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    stock_sales: Mapped[list[StockSale]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 50/30/20 bucket: "needs" | "wants" (income categories stay NULL).
    group_type: Mapped[str | None] = mapped_column(String(16), nullable=True)

    user: Mapped[User] = relationship(back_populates="categories")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")
    budgets: Mapped[list[Budget]] = relationship(back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped[User] = relationship(back_populates="transactions")
    category: Mapped[Category] = relationship(back_populates="transactions")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "month", name="uq_budget_user_category_month"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    monthly_limit: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    # First day of the budget month, e.g. "2026-07-01" — stored as "YYYY-MM".
    month: Mapped[str] = mapped_column(String(7), nullable=False)

    user: Mapped[User] = relationship(back_populates="budgets")
    category: Mapped[Category] = relationship(back_populates="budgets")


class InvestmentPosition(Base):
    """A stock lot tracked in shares and average USD purchase price."""

    __tablename__ = "investment_positions"
    __table_args__ = (
        Index("ix_investment_positions_user_symbol", "user_id", "symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    average_price_usd: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="investment_positions")


class Deposit(Base):
    """A bank deposit or cash balance included in net worth."""

    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    annual_rate: Mapped[float | None] = mapped_column(Numeric(7, 3), nullable=True)
    interest_started_on: Mapped[date] = mapped_column(
        Date, server_default=func.current_date(), nullable=False
    )
    interest_months_accrued: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="deposits")


class FinancialGoal(Base):
    """A savings target with a manually tracked current amount."""

    __tablename__ = "financial_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    current_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    financing_program: Mapped[str | None] = mapped_column(String(40), nullable=True)
    down_payment_percent: Mapped[float | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    loan_annual_rate: Mapped[float | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    loan_term_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="financial_goals")


class BrokerAccount(Base):
    """Cumulative broker metrics and uninvested USD cash."""

    __tablename__ = "broker_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    cash_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    realized_pnl_usd: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reported_total_pnl_usd: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    reported_total_pnl_percent: Mapped[float | None] = mapped_column(
        Numeric(8, 3), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="broker_account")


class StockSale(Base):
    """An immutable realized stock sale used for the P/L history."""

    __tablename__ = "stock_sales"
    __table_args__ = (Index("ix_stock_sales_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    average_buy_price_usd: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    sell_price_usd: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    realized_pnl_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="stock_sales")
