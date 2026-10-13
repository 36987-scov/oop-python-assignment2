"""Uganda tax engine: money, errors, schedules and tax calculations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
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
    revenue: Money = Money.zero()
    invoices: tuple["Invoice", ...] = ()


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


LST_MONTHS = (7, 8, 9, 10)   # July to October: first four months of the FY


class NSSF(Tax):
    """An NSSF contribution: a fixed share of monthly gross pay, uncapped.

    One class serves both shares, with different rates (5% employee,
    10% employer). Assumption, following the brief: the base is gross pay,
    excluding allowances.
    """

    def __init__(self, rate: Decimal, name: str) -> None:
        self.rate = rate
        self.name = name

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return the contribution on ctx.gross_pay, rounded to shillings."""
        _require_non_negative("Gross pay", ctx.gross_pay)
        return TaxResult(self.name, ctx.gross_pay,
                         (ctx.gross_pay * self.rate).rounded(),
                         f"{self.rate:.0%} of gross pay")


class LocalServiceTax(Tax):
    """Local Service Tax, collected in four equal monthly instalments.

    The annual amount is configurable, because LST bands are set by local
    government and differ by salary band. An instalment of a quarter of the
    annual amount is due in July, August, September and October only.
    """

    def __init__(self, annual_amount: Money) -> None:
        _require_non_negative("Annual LST", annual_amount)
        self.annual_amount = annual_amount

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return this month's LST instalment (zero outside July-October)."""
        if ctx.on.month in LST_MONTHS:
            instalment = (self.annual_amount * Decimal("0.25")).rounded()
            return TaxResult("LST", self.annual_amount, instalment,
                             "instalment, 1 of 4 (Jul-Oct)")
        return TaxResult("LST", self.annual_amount, Money.zero(),
                         "no instalment this month")


@dataclass(frozen=True)
class Payslip:
    """One month's payroll result for one employee."""

    gross_pay: Money
    allowances: Money
    nssf_employee: TaxResult
    lst: TaxResult
    paye: TaxResult
    nssf_employer: TaxResult
    net_pay: Money


class PayrollPipeline:
    """Monthly payroll: NSSF, then LST, then PAYE, then net pay.

    Order of deductions:
    1. NSSF is charged on gross pay and is not deductible for PAYE.
    2. The LST instalment is deducted before PAYE, as it reduces the
       income available for PAYE.
    3. PAYE is charged on gross pay + allowances - LST.
    4. Net pay = gross + allowances - employee NSSF - LST - PAYE.
    The employer's NSSF share is an employer cost, not deducted from pay.
    The pipeline is built from Tax objects (composition), so any part
    can be replaced, for example with a different LST amount.
    """

    def __init__(self, lst_annual: Money = Money.zero(),
                 paye: PAYE | None = None) -> None:
        self.paye = paye or PAYE()
        self.lst = LocalServiceTax(lst_annual)
        self.nssf_employee = NSSF(Decimal("0.05"), "NSSF (employee)")
        self.nssf_employer = NSSF(Decimal("0.10"), "NSSF (employer)")

    def run(self, ctx: TaxContext) -> Payslip:
        """Calculate one month's payslip for the given context."""
        nssf_employee = self.nssf_employee.calculate(ctx)
        nssf_employer = self.nssf_employer.calculate(ctx)
        lst = self.lst.calculate(ctx)
        paye = self.paye.calculate(
            replace(ctx, deductions=ctx.deductions + lst.tax))
        net = (ctx.gross_pay + ctx.allowances
               - nssf_employee.tax - lst.tax - paye.tax)
        return Payslip(ctx.gross_pay, ctx.allowances, nssf_employee, lst,
                       paye, nssf_employer, net)


VAT_STANDARD_RATE = Decimal("0.18")
CORPORATION_TAX_RATE = Decimal("0.30")


class SupplyType(Enum):
    """VAT category of a supply under the Uganda VAT Act."""

    STANDARD = "standard-rated"
    ZERO_RATED = "zero-rated"
    EXEMPT = "exempt"


@dataclass(frozen=True)
class Invoice:
    """A VAT-exclusive invoice amount, either a sale or a purchase.

    for_exempt_use marks a purchase used to make exempt supplies; its
    input VAT cannot be credited.
    """

    amount: Money
    supply: SupplyType
    is_sale: bool
    for_exempt_use: bool = False

    def __post_init__(self) -> None:
        _require_non_negative("Invoice amount", self.amount)


class VAT(Tax):
    """Value Added Tax: output VAT on sales minus creditable input VAT.

    Standard-rated supplies carry 18%, zero-rated 0%, and exempt supplies
    are outside VAT. A negative result is a refund or credit due.
    Simplification: no apportionment for mixed taxable/exempt businesses.
    """

    def __init__(self, standard_rate: Decimal = VAT_STANDARD_RATE) -> None:
        self.rates = {SupplyType.STANDARD: standard_rate,
                      SupplyType.ZERO_RATED: Decimal("0"),
                      SupplyType.EXEMPT: Decimal("0")}

    def _vat_on(self, invoice: Invoice) -> Money:
        return invoice.amount * self.rates[invoice.supply]

    def output_vat(self, invoices: tuple[Invoice, ...]) -> Money:
        """Return VAT charged on sales, rounded to whole shillings."""
        total = Money.zero()
        for invoice in invoices:
            if invoice.is_sale:
                total = total + self._vat_on(invoice)
        return total.rounded()

    def input_vat(self, invoices: tuple[Invoice, ...]) -> Money:
        """Return creditable VAT paid on purchases, rounded to shillings."""
        total = Money.zero()
        for invoice in invoices:
            if not invoice.is_sale and not invoice.for_exempt_use:
                total = total + self._vat_on(invoice)
        return total.rounded()

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return net VAT payable (negative means a refund or credit)."""
        output = self.output_vat(ctx.invoices)
        credit = self.input_vat(ctx.invoices)
        taxable_sales = Money.zero()
        for invoice in ctx.invoices:
            if invoice.is_sale and invoice.supply is not SupplyType.EXEMPT:
                taxable_sales = taxable_sales + invoice.amount
        return TaxResult("VAT", taxable_sales, output - credit,
                         f"output {output}, input {credit}")


class CorporateIncomeTax(Tax):
    """Corporate income tax on chargeable income (revenue - deductions).

    A loss gives zero tax; carrying losses forward is not modelled.
    """

    def __init__(self, rate: Decimal = CORPORATION_TAX_RATE) -> None:
        self.rate = rate

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return corporate income tax due, rounded to whole shillings."""
        _require_non_negative("Revenue", ctx.revenue)
        _require_non_negative("Deductions", ctx.deductions)
        chargeable = max(ctx.revenue - ctx.deductions, Money.zero())
        return TaxResult("Corporate income tax", chargeable,
                         (chargeable * self.rate).rounded(),
                         f"{self.rate:.0%} of chargeable income")        