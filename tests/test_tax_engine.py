"""Unit and property-based tests for the Uganda tax engine."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.tax_engine import (
    CorporateIncomeTax,
    FlatWithholdingTax,
    Invoice,
    InvoiceDirection,
    InvalidIncomeError,
    LocalServiceTax,
    Money,
    NSSFContribution,
    NoScheduleForDateError,
    PAYETax,
    PayrollCalculator,
    Residency,
    SupplyType,
    Tax,
    TaxContext,
    TaxPlanner,
    VAT,
)


TAX_DATE = date(2025, 10, 1)


def money(amount: str | int) -> Money:
    """Build a Money value without introducing a binary float."""
    return Money(Decimal(str(amount)))


def context(
    income: str | int,
    *,
    residency: Residency = Residency.RESIDENT,
    schedule_version: str = "ASSIGNMENT-2025/26",
    **kwargs: object,
) -> TaxContext:
    """Build a common PAYE context for the FY2025/26 tests."""
    return TaxContext(
        income=money(income),
        tax_date=TAX_DATE,
        residency=residency,
        schedule_version=schedule_version,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("income", "expected_tax"),
    [
        (335_000, 0),
        (335_001, 0),
        (410_000, 15_000),
        (485_000, 33_750),
        (10_000_000, 2_888_250),
        (10_000_001, 2_888_250),
    ],
)
def test_assignment_paye_boundaries(income: int, expected_tax: int) -> None:
    result = PAYETax().calculate(context(income))

    assert result.amount == money(expected_tax)


def test_assignment_paye_rounds_fractional_shilling_half_up() -> None:
    result = PAYETax().calculate(context(335_003))

    assert result.amount == money(1)


def test_official_reference_schedule_supports_both_residencies() -> None:
    paye = PAYETax()

    resident = paye.calculate(
        context(335_000, schedule_version="URA-2025/26")
    )
    non_resident = paye.calculate(
        context(
            335_000,
            residency=Residency.NON_RESIDENT,
            schedule_version="URA-2025/26",
        )
    )

    assert resident.amount == money(10_000)
    assert non_resident.amount == money(33_500)


def test_paye_rejects_dates_without_a_configured_schedule() -> None:
    outdated_context = TaxContext(
        income=money(500_000),
        tax_date=date(2026, 7, 1),
        schedule_version="URA-2025/26",
    )

    with pytest.raises(NoScheduleForDateError, match="covers"):
        PAYETax().calculate(outdated_context)


@given(income=st.integers(min_value=0, max_value=500_000_000))
@settings(max_examples=150)
def test_paye_is_never_negative(income: int) -> None:
    result = PAYETax().calculate(context(income))

    assert result.amount.amount >= Decimal("0")


@given(
    lower=st.integers(min_value=0, max_value=100_000_000),
    increase=st.integers(min_value=0, max_value=100_000_000),
)
@settings(max_examples=150)
def test_paye_is_monotonic_in_income(lower: int, increase: int) -> None:
    paye = PAYETax()
    first = paye.calculate(context(lower)).amount
    second = paye.calculate(context(lower + increase)).amount

    assert first <= second


@given(income=st.integers(min_value=0, max_value=500_000_000))
@settings(max_examples=150)
def test_paye_never_exceeds_income(income: int) -> None:
    result = PAYETax().calculate(context(income))

    assert result.amount <= money(income)


def test_money_uses_decimal_and_explicit_rounding() -> None:
    assert money("1.5") == money(2)
    assert money("1.4") == money(1)
    assert money(10) + money(5) == money(15)
    assert money(10) * Decimal("0.15") == money(2)
    assert Decimal("0.15") * money(10) == money(2)
    assert money(10) < money(11)
    assert repr(money(10)) == "Money(Decimal('10'))"

    with pytest.raises(InvalidIncomeError, match="Decimal"):
        Money(1.1)  # type: ignore[arg-type]

    with pytest.raises(InvalidIncomeError, match="only be multiplied by Decimal"):
        money(10) * 0.15  # type: ignore[operator]

    with pytest.raises(FrozenInstanceError):
        money(10).amount = Decimal("11")  # type: ignore[misc]


def test_tax_is_an_abstract_base_class() -> None:
    with pytest.raises(TypeError):
        Tax()  # type: ignore[abstract]


def test_payroll_applies_lst_before_paye_and_nssf_separately() -> None:
    calculator = PayrollCalculator(
        local_service_tax=LocalServiceTax(money(10_000))
    )
    payroll = calculator.calculate(context(500_000))

    assert payroll.gross_pay == money(500_000)
    assert payroll.local_service_tax == money(10_000)
    assert payroll.paye == money(35_250)
    assert payroll.nssf_employee == money(25_000)
    assert payroll.nssf_employer == money(50_000)
    assert payroll.net_pay == money(429_750)


def test_nssf_contributions_use_five_and_ten_percent() -> None:
    result = NSSFContribution().calculate(context(1_000_000))

    assert result.amount == money(50_000)
    assert result.breakdown["employer_contribution"] == money(100_000)


def test_local_service_tax_is_configurable_and_capped_at_pay() -> None:
    result = LocalServiceTax(money(20_000)).calculate(context(10_000))

    assert result.amount == money(10_000)


def test_vat_handles_standard_zero_rated_and_exempt_invoices() -> None:
    invoices = (
        Invoice(
            amount=money(1_000),
            supply_type=SupplyType.STANDARD_RATED,
            direction=InvoiceDirection.SALE,
        ),
        Invoice(
            amount=money(500),
            supply_type=SupplyType.ZERO_RATED,
            direction=InvoiceDirection.SALE,
        ),
        Invoice(
            amount=money(300),
            supply_type=SupplyType.EXEMPT,
            direction=InvoiceDirection.SALE,
        ),
        Invoice(
            amount=money(500),
            supply_type=SupplyType.STANDARD_RATED,
            direction=InvoiceDirection.PURCHASE,
            input_vat=money(90),
        ),
        Invoice(
            amount=money(200),
            supply_type=SupplyType.EXEMPT,
            direction=InvoiceDirection.PURCHASE,
            input_vat=money(36),
        ),
    )
    result = VAT().calculate(
        TaxContext(income=money(0), invoices=invoices)
    )

    assert result.breakdown["output_vat"] == money(180)
    assert result.breakdown["recoverable_input_vat"] == money(90)
    assert result.amount == money(90)


def test_vat_net_amount_can_be_a_credit() -> None:
    invoices = (
        Invoice(
            amount=money(500),
            supply_type=SupplyType.STANDARD_RATED,
            direction=InvoiceDirection.PURCHASE,
            input_vat=money(90),
        ),
    )
    result = VAT().calculate(
        TaxContext(income=money(0), invoices=invoices)
    )

    assert result.amount == money(-90)


def test_invoice_rejects_input_vat_on_a_sale() -> None:
    with pytest.raises(InvalidIncomeError, match="Sales invoices"):
        Invoice(
            amount=money(100),
            supply_type=SupplyType.STANDARD_RATED,
            direction=InvoiceDirection.SALE,
            input_vat=money(18),
        )


def test_corporate_income_tax_uses_revenue_less_deductions() -> None:
    result = CorporateIncomeTax().calculate(
        TaxContext(
            income=money(10_000_000),
            allowable_deductions=money(4_000_000),
        )
    )

    assert result.breakdown["chargeable_income"] == money(6_000_000)
    assert result.amount == money(1_800_000)


def test_corporate_income_tax_floors_losses_at_zero() -> None:
    result = CorporateIncomeTax().calculate(
        TaxContext(
            income=money(1_000_000),
            allowable_deductions=money(2_000_000),
        )
    )

    assert result.breakdown["chargeable_income"] == money(0)
    assert result.amount == money(0)


def test_tax_planner_compares_salary_and_dividend_scenarios() -> None:
    planner = TaxPlanner(
        payroll=PayrollCalculator(
            local_service_tax=LocalServiceTax(money(5_000))
        )
    )
    salary = planner.salary_scenario("Salary", context(2_000_000))
    dividend = planner.dividend_scenario(
        name="Dividend",
        gross_dividend=money(2_000_000),
        tax_date=TAX_DATE,
        withholding_tax=FlatWithholdingTax(
            Decimal("0.15"), name="Dividend withholding tax"
        ),
    )

    comparison = planner.compare(salary, dividend)

    assert dividend.net == money(1_700_000)
    assert comparison.preferred_scenario in {"Salary", "Dividend"}
    assert comparison.net_difference.amount >= Decimal("0")
