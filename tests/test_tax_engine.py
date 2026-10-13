"""Tests for src/tax_engine.py: PAYE boundaries, properties and worked examples.

Run from the project folder with:  python -m pytest -v
"""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.tax_engine import (
    PAYE,
    VAT,
    CorporateIncomeTax,
    InvalidIncomeError,
    Invoice,
    Money,
    NoScheduleForDateError,
    PaymentType,
    PayrollPipeline,
    RentalIncomeTax,
    SupplyType,
    TaxContext,
    WithholdingTax,
)

# Reproducibility: Hypothesis generates the same examples on every run.
settings.register_profile("reproducible", derandomize=True, max_examples=300)
settings.load_profile("reproducible")

FY_2026_27 = date(2026, 10, 1)
FY_2025_26 = date(2026, 3, 1)
paye = PAYE()


def paye_on(amount: int, on: date = FY_2026_27, resident: bool = True) -> Money:
    """Return the rounded PAYE on a monthly gross pay."""
    return paye.calculate(TaxContext(on=on, gross_pay=Money(amount),
                                     resident=resident)).tax


# ---------- PAYE band boundaries (brief, section 5) ----------

@pytest.mark.parametrize("income, expected", [
    (335_000, 0),
    (335_001, 0),
    (410_000, 15_000),
    (485_000, 33_750),
    (10_000_000, 2_888_250),
    (10_000_001, 2_888_250),
])
def test_resident_paye_at_band_boundaries(income, expected):
    assert paye_on(income) == Money(expected)


@pytest.mark.parametrize("income, exact", [
    (335_001, "0.20"),            # 20% of the first shilling above 335,000
    (410_001, "15000.25"),        # 25% band starts above 410,000
    (485_001, "33750.30"),        # 30% band starts above 485,000
    (10_000_001, "2888250.40"),   # 30% + 10% surcharge above 10,000,000
])
def test_unrounded_tax_just_above_each_boundary(income, exact):
    schedule = paye.schedule_for(FY_2026_27, resident=True)
    assert schedule.tax_on(Money(income)) == Money(Decimal(exact))


def test_previous_year_and_non_resident_schedules():
    assert paye_on(10_000_000, on=FY_2025_26) == Money(2_902_000)
    assert paye_on(1_000_000, resident=False) == Money(225_500)


def test_paye_errors():
    with pytest.raises(NoScheduleForDateError):
        paye_on(500_000, on=date(2028, 1, 1))
    with pytest.raises(InvalidIncomeError):
        paye_on(-1)


# ---------- Hypothesis properties (brief, section 5) ----------

incomes = st.integers(min_value=0, max_value=50_000_000)
dates = st.sampled_from([FY_2025_26, FY_2026_27])


@given(income=incomes, on=dates, resident=st.booleans())
def test_tax_is_never_negative(income, on, resident):
    assert paye_on(income, on, resident) >= Money.zero()


@given(income=incomes, on=dates, resident=st.booleans())
def test_tax_never_exceeds_income(income, on, resident):
    assert paye_on(income, on, resident) <= Money(income)


@given(a=incomes, b=incomes, on=dates, resident=st.booleans())
def test_tax_is_monotonic_in_income(a, b, on, resident):
    low, high = sorted((a, b))
    assert paye_on(low, on, resident) <= paye_on(high, on, resident)


# ---------- Money ----------

def test_money_is_exact_where_float_is_not():
    assert Money("0.1") + Money("0.2") == Money("0.3")
    assert 0.1 + 0.2 != 0.3


def test_money_operators_and_rounding():
    assert Money("2.5").rounded() == Money(3)          # ROUND_HALF_UP
    assert Money(100) * 3 == Money(300)
    assert Money(1_000) < Money(2_000)
    assert repr(Money(15_000)) == "Money('15000', UGX)"
    with pytest.raises(TypeError):
        Money(0.1)


# ---------- Worked examples verified in the notebook ----------

def test_payroll_order_of_deductions():
    payroll = PayrollPipeline(lst_annual=Money(30_000))
    october = payroll.run(TaxContext(on=date(2026, 10, 1), gross_pay=Money(1_000_000)))
    november = payroll.run(TaxContext(on=date(2026, 11, 1), gross_pay=Money(1_000_000)))
    assert (october.lst.tax, october.paye.tax, october.net_pay) == (
        Money(7_500), Money(186_000), Money(756_500))
    assert (november.lst.tax, november.paye.tax, november.net_pay) == (
        Money(0), Money(188_250), Money(761_750))
    assert october.nssf_employer.tax == Money(100_000)


def test_vat_output_input_and_net():
    invoices = (
        Invoice(Money(1_000_000), SupplyType.STANDARD, is_sale=True),
        Invoice(Money(500_000), SupplyType.ZERO_RATED, is_sale=True),
        Invoice(Money(200_000), SupplyType.EXEMPT, is_sale=True),
        Invoice(Money(400_000), SupplyType.STANDARD, is_sale=False),
        Invoice(Money(100_000), SupplyType.STANDARD, is_sale=False,
                for_exempt_use=True),
    )
    vat = VAT()
    assert vat.output_vat(invoices) == Money(180_000)
    assert vat.input_vat(invoices) == Money(72_000)
    assert vat.calculate(TaxContext(on=FY_2026_27, invoices=invoices)).tax == Money(108_000)


def test_corporate_income_tax_profit_and_loss():
    cit = CorporateIncomeTax()
    assert cit.calculate(TaxContext(on=FY_2026_27, revenue=Money(50_000_000),
                                    deductions=Money(35_000_000))).tax == Money(4_500_000)
    assert cit.calculate(TaxContext(on=FY_2026_27, revenue=Money(10_000_000),
                                    deductions=Money(12_000_000))).tax == Money(0)


def test_withholding_tax_rates_and_threshold():
    fees = WithholdingTax(PaymentType.PROFESSIONAL_FEES)
    goods = WithholdingTax(PaymentType.GOODS_AND_SERVICES)
    assert fees.calculate(TaxContext(on=FY_2026_27, revenue=Money(2_000_000))).tax == Money(120_000)
    assert fees.calculate(TaxContext(on=FY_2026_27, revenue=Money(2_000_000),
                                     resident=False)).tax == Money(300_000)
    assert goods.calculate(TaxContext(on=FY_2026_27, revenue=Money(1_000_000))).tax == Money(0)
    assert goods.calculate(TaxContext(on=FY_2026_27, revenue=Money(1_500_000))).tax == Money(90_000)


def test_rental_income_tax_matches_ura_worked_example():
    assert RentalIncomeTax().calculate(
        TaxContext(on=FY_2026_27, revenue=Money(6_000_000))).tax == Money(381_600)
    assert RentalIncomeTax(individual=False).calculate(
        TaxContext(on=FY_2026_27, revenue=Money(30_000_000),
                   deductions=Money(20_000_000))).tax == Money(4_500_000)