"""Uganda tax engine: money, errors, schedules and tax calculations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import total_ordering

CURRENCY = "UGX"
WHOLE_SHILLING = Decimal("1")


class TaxError(Exception):
    """Base class for every error raised by the tax engine."""


class InvalidIncomeError(TaxError):
    """Raised when an income, price or amount is negative or not a number."""


class NoScheduleForDateError(TaxError):
    """Raised when no tax schedule covers the requested date."""


@total_ordering
@dataclass(frozen=True)
class Money:
    """An exact amount of Uganda shillings (UGX), stored as a Decimal.

    Floats are rejected, because binary floating point cannot represent
    most decimal amounts exactly. Arithmetic is exact; call rounded() once
    on a final result to round to whole shillings, halves rounded up.
    """

    amount: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.amount, (float, bool)):
            raise TypeError("Money needs an int, str or Decimal, never a float.")
        try:
            value = Decimal(self.amount)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise TypeError(f"Not a valid amount: {self.amount!r}") from error
        object.__setattr__(self, "amount", value)

    @classmethod
    def zero(cls) -> "Money":
        """Return UGX 0."""
        return cls(Decimal("0"))

    def rounded(self) -> "Money":
        """Return this amount rounded to whole shillings (ROUND_HALF_UP)."""
        return Money(self.amount.quantize(WHOLE_SHILLING, rounding=ROUND_HALF_UP))

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.amount + other.amount)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.amount - other.amount)

    def __mul__(self, factor: "Decimal | int") -> "Money":
        if isinstance(factor, (float, bool)) or not isinstance(factor, (Decimal, int)):
            return NotImplemented
        return Money(self.amount * factor)

    __rmul__ = __mul__

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount < other.amount

    def __repr__(self) -> str:
        return f"Money('{self.amount}', {CURRENCY})"

    def __str__(self) -> str:
        return f"{CURRENCY} {self.rounded().amount:,}"


def _require_non_negative(label: str, amount: Money) -> None:
    """Raise InvalidIncomeError if amount is below zero."""
    if amount < Money.zero():
        raise InvalidIncomeError(f"{label} cannot be negative, got {amount!r}.")


@dataclass(frozen=True)
class TaxBand:
    """One band of a progressive schedule.

    rate applies to the part of income above lower, up to the next band's
    lower limit.
    """

    lower: Money
    rate: Decimal


@dataclass(frozen=True)
class BandSchedule:
    """A dated, progressive monthly PAYE schedule for one residency status."""

    name: str
    resident: bool
    valid_from: date
    valid_to: date | None
    bands: tuple[TaxBand, ...]
    source: str

    def __post_init__(self) -> None:
        lowers = [band.lower for band in self.bands]
        if not lowers or lowers[0] != Money.zero():
            raise ValueError(f"{self.name}: the first band must start at UGX 0.")
        if lowers != sorted(lowers):
            raise ValueError(f"{self.name}: bands must be in ascending order.")

    def covers(self, on: date) -> bool:
        """Return True if this schedule is in force on the given date."""
        return self.valid_from <= on and (self.valid_to is None or on <= self.valid_to)

    def tax_on(self, income: Money) -> Money:
        """Return the unrounded tax on a monthly chargeable income."""
        tax = Money.zero()
        for band, next_band in zip(self.bands, self.bands[1:] + (None,)):
            if not band.lower < income:
                break
            upper = income if next_band is None else min(income, next_band.lower)
            tax = tax + (upper - band.lower) * band.rate
        return tax


def _bands(*pairs: tuple[int, str]) -> tuple[TaxBand, ...]:
    """Build bands from (lower limit in UGX, rate as a string) pairs."""
    return tuple(TaxBand(Money(lower), Decimal(rate)) for lower, rate in pairs)


URA_PAYE_PAGE = ("URA PAYE rates page, https://ura.go.ug/?p=16453 "
                 "(accessed 12 October 2026)")
AMENDMENT_ACT_2026 = ("Income Tax (Amendment) Act 2026, in force from "
                      "1 July 2026 (confirm against URA's notice)")

# The top band of 0.40 is the 30% rate plus the 10% surcharge on monthly
# income above UGX 10,000,000.
PAYE_SCHEDULES = (
    BandSchedule(
        name="Resident, FY 2025/26",
        resident=True,
        valid_from=date(2025, 7, 1),
        valid_to=date(2026, 6, 30),
        bands=_bands((0, "0"), (235_000, "0.10"), (335_000, "0.20"),
                     (410_000, "0.30"), (10_000_000, "0.40")),
        source=URA_PAYE_PAGE,
    ),
    BandSchedule(
        name="Resident, FY 2026/27",
        resident=True,
        valid_from=date(2026, 7, 1),
        valid_to=date(2027, 6, 30),
        bands=_bands((0, "0"), (335_000, "0.20"), (410_000, "0.25"),
                     (485_000, "0.30"), (10_000_000, "0.40")),
        source=AMENDMENT_ACT_2026,
    ),
    BandSchedule(
        name="Non-resident, FY 2025/26 and 2026/27",
        resident=False,
        valid_from=date(2025, 7, 1),
        valid_to=date(2027, 6, 30),
        bands=_bands((0, "0.10"), (335_000, "0.20"), (410_000, "0.30"),
                     (10_000_000, "0.40")),
        source=URA_PAYE_PAGE + "; " + AMENDMENT_ACT_2026,
    ),
)


@dataclass(frozen=True)
class TaxContext:
    """Inputs for a tax calculation. Each Tax reads only the fields it needs."""

    on: date
    gross_pay: Money = Money.zero()
    allowances: Money = Money.zero()
    deductions: Money = Money.zero()
    resident: bool = True


@dataclass(frozen=True)
class TaxResult:
    """The outcome of one tax calculation: what was taxed and the tax due."""

    name: str
    base: Money
    tax: Money
    note: str = ""


class Tax(ABC):
    """Interface shared by every tax in the engine."""

    @abstractmethod
    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Calculate this tax for the given context."""


class PAYE(Tax):
    """Monthly Pay As You Earn, using the schedule in force on ctx.on.

    Chargeable income is gross pay plus allowances minus allowable
    deductions, never below zero. Resident and non-resident rules are
    separate schedules held by this object (composition), not subclasses.
    """

    def __init__(self, schedules: tuple[BandSchedule, ...] = PAYE_SCHEDULES) -> None:
        self.schedules = schedules

    def schedule_for(self, on: date, resident: bool) -> BandSchedule:
        """Return the schedule for this date and residency status.

        Raises:
            NoScheduleForDateError: if no schedule covers the date.
        """
        for schedule in self.schedules:
            if schedule.resident == resident and schedule.covers(on):
                return schedule
        status = "resident" if resident else "non-resident"
        raise NoScheduleForDateError(f"No {status} PAYE schedule covers {on}.")

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return the monthly PAYE due, rounded to whole shillings.

        Raises:
            InvalidIncomeError: if any amount is negative.
            NoScheduleForDateError: if no schedule covers ctx.on.
        """
        for label, amount in (("Gross pay", ctx.gross_pay),
                              ("Allowances", ctx.allowances),
                              ("Deductions", ctx.deductions)):
            _require_non_negative(label, amount)
        chargeable = max(ctx.gross_pay + ctx.allowances - ctx.deductions,
                         Money.zero())
        schedule = self.schedule_for(ctx.on, ctx.resident)
        tax = schedule.tax_on(chargeable).rounded()
        return TaxResult("PAYE", chargeable, tax, schedule.name)