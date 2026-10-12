"""Decimal-based, schedule-aware tax calculations for the Uganda tax project."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from functools import total_ordering
from typing import ClassVar


ZERO = Decimal("0")
ONE = Decimal("1")
UGX_QUANTUM = Decimal("1")
DEFAULT_TAX_DATE = date(2025, 7, 1)


class TaxError(Exception):
    """Base exception for tax engine validation and schedule errors."""


class InvalidIncomeError(TaxError):
    """Raised when money, income, or tax parameters are invalid."""


class NoScheduleForDateError(TaxError):
    """Raised when no requested tax schedule covers the context date."""


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    """An amount in UGX rounded to whole shillings using ROUND_HALF_UP."""

    amount: Decimal

    def __post_init__(self) -> None:
        """Reject binary floats and normalize valid amounts to whole UGX."""
        if not isinstance(self.amount, Decimal):
            raise InvalidIncomeError(
                "Money must be constructed from decimal.Decimal, never float."
            )
        if not self.amount.is_finite():
            raise InvalidIncomeError("Money must be a finite Decimal value.")
        object.__setattr__(
            self,
            "amount",
            self.amount.quantize(UGX_QUANTUM, rounding=ROUND_HALF_UP),
        )

    def __add__(self, other: Money) -> Money:
        """Add two UGX amounts."""
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.amount + other.amount)

    def __sub__(self, other: Money) -> Money:
        """Subtract one UGX amount from another."""
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.amount - other.amount)

    def __mul__(self, multiplier: Decimal) -> Money:
        """Multiply by a Decimal rate and round the result to whole UGX."""
        if not isinstance(multiplier, Decimal):
            raise InvalidIncomeError("Money can only be multiplied by Decimal.")
        if not multiplier.is_finite():
            raise InvalidIncomeError("Money multiplier must be finite.")
        return Money(self.amount * multiplier)

    def __rmul__(self, multiplier: Decimal) -> Money:
        """Support Decimal rates written before a Money value."""
        return self * multiplier

    def __lt__(self, other: Money) -> bool:
        """Compare two UGX values."""
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount < other.amount

    def __repr__(self) -> str:
        """Return a representation that preserves Decimal precision."""
        return f"Money(Decimal('{self.amount}'))"

    def __str__(self) -> str:
        """Format this amount as whole Uganda shillings."""
        return f"UGX {self.amount:,.0f}"


ZERO_MONEY = Money(ZERO)


class Residency(str, Enum):
    """Tax residence category used to select an individual PAYE schedule."""

    RESIDENT = "resident"
    NON_RESIDENT = "non-resident"


class SupplyType(str, Enum):
    """VAT treatment of an invoice supply."""

    STANDARD_RATED = "standard-rated"
    ZERO_RATED = "zero-rated"
    EXEMPT = "exempt"


class InvoiceDirection(str, Enum):
    """Whether an invoice is a sale or purchase."""

    SALE = "sale"
    PURCHASE = "purchase"


@dataclass(frozen=True, slots=True)
class Invoice:
    """A VAT invoice; amount is exclusive of VAT and in UGX."""

    amount: Money
    supply_type: SupplyType
    direction: InvoiceDirection
    input_vat: Money = ZERO_MONEY

    def __post_init__(self) -> None:
        """Validate VAT invoice amounts and input VAT."""
        if not isinstance(self.amount, Money) or not isinstance(
            self.input_vat, Money
        ):
            raise InvalidIncomeError("Invoice amounts must use Money values.")
        if not isinstance(self.supply_type, SupplyType) or not isinstance(
            self.direction, InvoiceDirection
        ):
            raise InvalidIncomeError(
                "Invoice supply type and direction must use their enums."
            )
        if self.amount.amount < ZERO or self.input_vat.amount < ZERO:
            raise InvalidIncomeError("Invoice amounts cannot be negative.")
        if self.direction is InvoiceDirection.SALE and self.input_vat.amount:
            raise InvalidIncomeError("Sales invoices cannot claim input VAT.")


@dataclass(frozen=True, slots=True)
class TaxContext:
    """Inputs shared by tax calculators; monetary fields are always Money."""

    income: Money
    tax_date: date = DEFAULT_TAX_DATE
    residency: Residency = Residency.RESIDENT
    allowances: Money = ZERO_MONEY
    deductions_before_paye: Money = ZERO_MONEY
    allowable_deductions: Money = ZERO_MONEY
    invoices: tuple[Invoice, ...] = ()
    schedule_version: str = "URA-2025/26"

    def __post_init__(self) -> None:
        """Validate shared context types and non-negative income inputs."""
        for field_name in (
            "income",
            "allowances",
            "deductions_before_paye",
            "allowable_deductions",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Money):
                raise InvalidIncomeError(
                    f"{field_name} must be supplied as a Money value."
                )
            if value.amount < ZERO:
                raise InvalidIncomeError(f"{field_name} cannot be negative.")
        if not isinstance(self.tax_date, date):
            raise InvalidIncomeError("tax_date must be a datetime.date.")
        if not isinstance(self.residency, Residency):
            raise InvalidIncomeError("residency must be a Residency value.")
        if not isinstance(self.invoices, tuple) or any(
            not isinstance(invoice, Invoice) for invoice in self.invoices
        ):
            raise InvalidIncomeError("invoices must be a tuple of Invoice values.")


@dataclass(frozen=True, slots=True)
class TaxResult:
    """A tax amount with an auditable calculation breakdown."""

    name: str
    amount: Money
    breakdown: dict[str, Money | Decimal | str] = field(default_factory=dict)


class Tax(ABC):
    """Abstract base class for tax calculations."""

    @abstractmethod
    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Calculate a tax amount from a validated context."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PAYEBand:
    """A progressive band with a lower bound and base tax at that bound."""

    lower: Decimal
    upper: Decimal | None
    base_tax: Decimal
    marginal_rate: Decimal

    def __post_init__(self) -> None:
        """Validate the thresholds and rates used in the band."""
        values = (self.lower, self.base_tax, self.marginal_rate)
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
            raise InvalidIncomeError("PAYE band values must be finite Decimals.")
        if self.upper is not None and (
            not isinstance(self.upper, Decimal) or not self.upper.is_finite()
        ):
            raise InvalidIncomeError("PAYE upper bound must be a finite Decimal.")
        if self.lower < ZERO or self.base_tax < ZERO:
            raise InvalidIncomeError("PAYE thresholds and base tax cannot be negative.")
        if not ZERO <= self.marginal_rate <= ONE:
            raise InvalidIncomeError("PAYE marginal rate must be between 0 and 1.")
        if self.upper is not None and self.upper <= self.lower:
            raise InvalidIncomeError("PAYE upper bound must exceed its lower bound.")


@dataclass(frozen=True, slots=True)
class PAYESchedule:
    """A versioned monthly schedule, valid only over its stated dates."""

    version: str
    effective_from: date
    effective_to: date
    bands: dict[Residency, tuple[PAYEBand, ...]]
    source_note: str

    def __post_init__(self) -> None:
        """Validate date range and per-residency band configuration."""
        if self.effective_to < self.effective_from:
            raise InvalidIncomeError("PAYE schedule dates are in reverse order.")
        if not self.bands:
            raise InvalidIncomeError("A PAYE schedule needs at least one residency.")
        for residency, bands in self.bands.items():
            if not isinstance(residency, Residency) or not bands:
                raise InvalidIncomeError("PAYE schedules require valid bands.")
            ordered = sorted(bands, key=lambda band: band.lower)
            if tuple(ordered) != bands or bands[0].lower != ZERO:
                raise InvalidIncomeError("PAYE bands must be ordered from zero.")
            if bands[-1].upper is not None:
                raise InvalidIncomeError("The final PAYE band must be open-ended.")
            for previous, current in zip(bands, bands[1:]):
                if previous.upper != current.lower:
                    raise InvalidIncomeError("PAYE bands must be contiguous.")


_FY_2025_START = date(2025, 7, 1)
_FY_2026_END = date(2026, 6, 30)

_URA_RESIDENT_BANDS = (
    PAYEBand(Decimal("0"), Decimal("235000"), ZERO, ZERO),
    PAYEBand(Decimal("235000"), Decimal("335000"), ZERO, Decimal("0.10")),
    PAYEBand(Decimal("335000"), Decimal("410000"), Decimal("10000"), Decimal("0.20")),
    PAYEBand(Decimal("410000"), Decimal("10000000"), Decimal("25000"), Decimal("0.30")),
    PAYEBand(Decimal("10000000"), None, Decimal("2902000"), Decimal("0.40")),
)
_URA_NON_RESIDENT_BANDS = (
    PAYEBand(Decimal("0"), Decimal("335000"), ZERO, Decimal("0.10")),
    PAYEBand(Decimal("335000"), Decimal("410000"), Decimal("33500"), Decimal("0.20")),
    PAYEBand(Decimal("410000"), Decimal("10000000"), Decimal("48500"), Decimal("0.30")),
    PAYEBand(Decimal("10000000"), None, Decimal("2925500"), Decimal("0.40")),
)
_ASSIGNMENT_RESIDENT_BANDS = (
    PAYEBand(Decimal("0"), Decimal("335000"), ZERO, ZERO),
    PAYEBand(Decimal("335000"), Decimal("410000"), ZERO, Decimal("0.20")),
    PAYEBand(Decimal("410000"), Decimal("485000"), Decimal("15000"), Decimal("0.25")),
    PAYEBand(Decimal("485000"), Decimal("10000000"), Decimal("33750"), Decimal("0.30")),
    PAYEBand(Decimal("10000000"), None, Decimal("2888250"), Decimal("0.40")),
)


DEFAULT_PAYE_SCHEDULES: tuple[PAYESchedule, ...] = (
    PAYESchedule(
        version="URA-2025/26",
        effective_from=_FY_2025_START,
        effective_to=_FY_2026_END,
        bands={
            Residency.RESIDENT: _URA_RESIDENT_BANDS,
            Residency.NON_RESIDENT: _URA_NON_RESIDENT_BANDS,
        },
        source_note=(
            "FY2025/26 published annual PAYE bands expressed monthly; "
            "see notebook citations and verify amendments before production."
        ),
    ),
    PAYESchedule(
        version="ASSIGNMENT-2025/26",
        effective_from=_FY_2025_START,
        effective_to=_FY_2026_END,
        bands={
            Residency.RESIDENT: _ASSIGNMENT_RESIDENT_BANDS,
            Residency.NON_RESIDENT: _URA_NON_RESIDENT_BANDS,
        },
        source_note=(
            "Resident bands reproduced from the assignment prompt; this is "
            "not the published FY2025/26 resident statutory schedule."
        ),
    ),
)


class PAYETax(Tax):
    """Calculate monthly PAYE using date- and residency-specific schedules."""

    def __init__(
        self, schedules: tuple[PAYESchedule, ...] = DEFAULT_PAYE_SCHEDULES
    ) -> None:
        """Create a PAYE calculator with one or more versioned schedules."""
        self.schedules = schedules

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Apply the selected progressive schedule after pre-PAYE deductions."""
        matching = [
            schedule
            for schedule in self.schedules
            if schedule.version == ctx.schedule_version
            and schedule.effective_from <= ctx.tax_date <= schedule.effective_to
        ]
        if not matching:
            raise NoScheduleForDateError(
                f"No PAYE schedule '{ctx.schedule_version}' covers "
                f"{ctx.tax_date.isoformat()}."
            )
        schedule = matching[0]
        bands = schedule.bands.get(ctx.residency)
        if bands is None:
            raise NoScheduleForDateError(
                f"Schedule '{schedule.version}' has no {ctx.residency.value} "
                f"PAYE bands."
            )
        gross = ctx.income.amount + ctx.allowances.amount
        taxable = max(gross - ctx.deductions_before_paye.amount, ZERO)
        band = next(
            item
            for item in bands
            if taxable >= item.lower
            and (item.upper is None or taxable <= item.upper)
        )
        raw_tax = band.base_tax + (taxable - band.lower) * band.marginal_rate
        tax = Money(raw_tax)
        return TaxResult(
            name="PAYE",
            amount=tax,
            breakdown={
                "gross_employment_income": Money(gross),
                "deductions_before_paye": ctx.deductions_before_paye,
                "taxable_income": Money(taxable),
                "marginal_rate": band.marginal_rate,
                "schedule_version": schedule.version,
                "schedule_source": schedule.source_note,
            },
        )


class NSSFContribution(Tax):
    """Calculate statutory employee and employer NSSF contributions."""

    EMPLOYEE_RATE: ClassVar[Decimal] = Decimal("0.05")
    EMPLOYER_RATE: ClassVar[Decimal] = Decimal("0.10")

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Return employee NSSF as tax amount and employer share separately."""
        gross_pay = ctx.income + ctx.allowances
        employee = gross_pay * self.EMPLOYEE_RATE
        employer = gross_pay * self.EMPLOYER_RATE
        return TaxResult(
            name="NSSF",
            amount=employee,
            breakdown={
                "employee_rate": self.EMPLOYEE_RATE,
                "employer_rate": self.EMPLOYER_RATE,
                "employer_contribution": employer,
                "gross_pay": gross_pay,
            },
        )


class LocalServiceTax(Tax):
    """Apply a configurable monthly Local Service Tax deduction."""

    def __init__(self, monthly_amount: Money = ZERO_MONEY) -> None:
        """Set the monthly deduction; zero is used unless configured."""
        if not isinstance(monthly_amount, Money) or monthly_amount.amount < ZERO:
            raise InvalidIncomeError(
                "Local Service Tax must be a non-negative Money value."
            )
        self.monthly_amount = monthly_amount

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Cap the configured deduction at total monthly employment pay."""
        gross_pay = ctx.income + ctx.allowances
        amount = min(self.monthly_amount.amount, gross_pay.amount)
        return TaxResult(
            name="Local Service Tax",
            amount=Money(amount),
            breakdown={"configured_monthly_amount": self.monthly_amount},
        )


@dataclass(frozen=True, slots=True)
class PayrollResult:
    """Monthly payroll deductions and take-home pay."""

    gross_pay: Money
    nssf_employee: Money
    nssf_employer: Money
    local_service_tax: Money
    paye: Money
    net_pay: Money


class PayrollCalculator:
    """Compose NSSF, Local Service Tax, and PAYE into a payroll calculation."""

    def __init__(
        self,
        paye: PAYETax | None = None,
        nssf: NSSFContribution | None = None,
        local_service_tax: LocalServiceTax | None = None,
    ) -> None:
        """Accept tax components so payroll rules are independently testable."""
        self.paye = paye if paye is not None else PAYETax()
        self.nssf = nssf if nssf is not None else NSSFContribution()
        self.local_service_tax = (
            local_service_tax
            if local_service_tax is not None
            else LocalServiceTax()
        )

    def calculate(self, ctx: TaxContext) -> PayrollResult:
        """Deduct LST before PAYE; deduct employee NSSF after PAYE is computed."""
        gross_pay = ctx.income + ctx.allowances
        lst_result = self.local_service_tax.calculate(ctx)
        paye_context = replace(
            ctx, deductions_before_paye=lst_result.amount
        )
        paye_result = self.paye.calculate(paye_context)
        nssf_result = self.nssf.calculate(ctx)
        employer_nssf = nssf_result.breakdown["employer_contribution"]
        if not isinstance(employer_nssf, Money):
            raise TaxError("NSSF calculator returned invalid employer contribution.")
        net_pay = (
            gross_pay
            - nssf_result.amount
            - lst_result.amount
            - paye_result.amount
        )
        if net_pay.amount < ZERO:
            raise InvalidIncomeError("Payroll deductions exceed gross pay.")
        return PayrollResult(
            gross_pay=gross_pay,
            nssf_employee=nssf_result.amount,
            nssf_employer=employer_nssf,
            local_service_tax=lst_result.amount,
            paye=paye_result.amount,
            net_pay=net_pay,
        )


class VAT(Tax):
    """Calculate output VAT, recoverable input VAT, and net VAT payable."""

    RATE: ClassVar[Decimal] = Decimal("0.18")

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Tax standard-rated sales and credit input VAT for taxable purchases."""
        output_vat = ZERO_MONEY
        recoverable_input_vat = ZERO_MONEY
        for invoice in ctx.invoices:
            if invoice.direction is InvoiceDirection.SALE:
                if invoice.supply_type is SupplyType.STANDARD_RATED:
                    output_vat += invoice.amount * self.RATE
            elif (
                invoice.direction is InvoiceDirection.PURCHASE
                and invoice.supply_type is SupplyType.STANDARD_RATED
            ):
                recoverable_input_vat += invoice.input_vat
        net_vat = output_vat - recoverable_input_vat
        return TaxResult(
            name="VAT",
            amount=net_vat,
            breakdown={
                "output_vat": output_vat,
                "recoverable_input_vat": recoverable_input_vat,
                "standard_rate": self.RATE,
            },
        )


class CorporateIncomeTax(Tax):
    """Calculate basic corporate income tax on chargeable income."""

    RATE: ClassVar[Decimal] = Decimal("0.30")

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Apply 30% to revenue less allowable deductions, floored at zero."""
        chargeable_income = max(
            ctx.income.amount - ctx.allowable_deductions.amount, ZERO
        )
        return TaxResult(
            name="Corporate income tax",
            amount=Money(chargeable_income * self.RATE),
            breakdown={
                "revenue": ctx.income,
                "allowable_deductions": ctx.allowable_deductions,
                "chargeable_income": Money(chargeable_income),
                "rate": self.RATE,
            },
        )


class FlatWithholdingTax(Tax):
    """Apply a configured flat withholding rate, used for planner examples."""

    def __init__(self, rate: Decimal, name: str = "Withholding tax") -> None:
        """Create a flat-rate tax; callers supply the rate explicitly."""
        if not isinstance(rate, Decimal) or not ZERO <= rate <= ONE:
            raise InvalidIncomeError("Withholding rate must be a Decimal from 0 to 1.")
        self.rate = rate
        self.name = name

    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Calculate withholding on gross income."""
        amount = ctx.income * self.rate
        return TaxResult(
            name=self.name,
            amount=amount,
            breakdown={"gross_income": ctx.income, "rate": self.rate},
        )


@dataclass(frozen=True, slots=True)
class TaxScenario:
    """A scenario's gross amount, net amount, and named deductions."""

    name: str
    gross: Money
    net: Money
    deductions: dict[str, Money]


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    """Comparison of two after-tax scenarios."""

    first: TaxScenario
    second: TaxScenario
    preferred_scenario: str
    net_difference: Money


class TaxPlanner:
    """Compare after-tax salary and dividend scenarios."""

    def __init__(self, payroll: PayrollCalculator | None = None) -> None:
        """Use an injected payroll pipeline or construct the default one."""
        self.payroll = payroll if payroll is not None else PayrollCalculator()

    def salary_scenario(
        self, name: str, ctx: TaxContext
    ) -> TaxScenario:
        """Calculate a salary scenario using the composed payroll pipeline."""
        result = self.payroll.calculate(ctx)
        return TaxScenario(
            name=name,
            gross=result.gross_pay,
            net=result.net_pay,
            deductions={
                "NSSF employee": result.nssf_employee,
                "Local Service Tax": result.local_service_tax,
                "PAYE": result.paye,
            },
        )

    @staticmethod
    def dividend_scenario(
        name: str,
        gross_dividend: Money,
        tax_date: date,
        withholding_tax: FlatWithholdingTax,
    ) -> TaxScenario:
        """Calculate a dividend scenario using its explicitly supplied WHT."""
        ctx = TaxContext(
            income=gross_dividend,
            tax_date=tax_date,
            schedule_version="not-applicable",
        )
        withholding = withholding_tax.calculate(ctx)
        return TaxScenario(
            name=name,
            gross=gross_dividend,
            net=gross_dividend - withholding.amount,
            deductions={withholding.name: withholding.amount},
        )

    @staticmethod
    def compare(
        first: TaxScenario, second: TaxScenario
    ) -> ScenarioComparison:
        """Report which scenario has the greater net amount and the difference."""
        if first.net < second.net:
            preferred = second.name
            difference = second.net - first.net
        else:
            preferred = first.name
            difference = first.net - second.net
        return ScenarioComparison(
            first=first,
            second=second,
            preferred_scenario=preferred,
            net_difference=difference,
        )
