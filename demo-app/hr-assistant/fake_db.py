"""
Fake HR database — realistic data for demo purposes.

Simulates a small Italian company with ~15 employees across 3 departments.
All data is in-memory; no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum


# ── Enums ────────────────────────────────────────────────────────────

class Department(str, Enum):
    ENGINEERING = "Engineering"
    SALES = "Sales"
    HR = "HR"


class ContractType(str, Enum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACTOR = "contractor"


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LeaveType(str, Enum):
    VACATION = "vacation"
    SICK = "sick_leave"
    PERSONAL = "personal_leave"


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class Employee:
    id: str
    name: str
    email: str
    department: Department
    role: str
    manager_id: str | None
    contract_type: ContractType
    hire_date: date
    salary_gross: float  # annual gross
    leave_balance: dict[str, int] = field(default_factory=dict)  # type → remaining days


@dataclass
class LeaveRequest:
    id: str
    employee_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    status: LeaveStatus
    note: str = ""


@dataclass
class AttendanceRecord:
    employee_id: str
    date: date
    check_in: str   # "HH:MM"
    check_out: str   # "HH:MM"
    hours_worked: float
    remote: bool = False


@dataclass
class PayslipSummary:
    employee_id: str
    month: str  # "2025-03"
    gross: float
    net: float
    deductions: float
    bonus: float = 0.0


# ── Seed data ────────────────────────────────────────────────────────

EMPLOYEES: list[Employee] = [
    # Engineering
    Employee("E001", "Marco Bianchi", "marco.bianchi@acme.it", Department.ENGINEERING,
             "CTO", None, ContractType.FULL_TIME, date(2018, 3, 1), 85_000.0,
             {"vacation": 12, "personal_leave": 5, "sick_leave": 10}),
    Employee("E002", "Laura Verdi", "laura.verdi@acme.it", Department.ENGINEERING,
             "Senior Developer", "E001", ContractType.FULL_TIME, date(2019, 9, 15), 55_000.0,
             {"vacation": 18, "personal_leave": 4, "sick_leave": 10}),
    Employee("E003", "Enzo", "enzo@acme.it", Department.ENGINEERING,
             "Developer", "E001", ContractType.FULL_TIME, date(2021, 1, 10), 42_000.0,
             {"vacation": 22, "personal_leave": 5, "sick_leave": 10}),
    Employee("E004", "Giulia Marino", "giulia.marino@acme.it", Department.ENGINEERING,
             "Junior Developer", "E001", ContractType.FULL_TIME, date(2023, 6, 1), 32_000.0,
             {"vacation": 24, "personal_leave": 5, "sick_leave": 10}),
    Employee("E005", "Davide Conti", "davide.conti@acme.it", Department.ENGINEERING,
             "DevOps", "E001", ContractType.CONTRACTOR, date(2022, 11, 1), 48_000.0,
             {"vacation": 15, "personal_leave": 3, "sick_leave": 5}),

    # Sales
    Employee("E006", "Francesca Ricci", "francesca.ricci@acme.it", Department.SALES,
             "Head of Sales", None, ContractType.FULL_TIME, date(2017, 5, 20), 72_000.0,
             {"vacation": 8, "personal_leave": 4, "sick_leave": 10}),
    Employee("E007", "Matteo Ferrari", "matteo.ferrari@acme.it", Department.SALES,
             "Account Manager", "E006", ContractType.FULL_TIME, date(2020, 2, 1), 45_000.0,
             {"vacation": 14, "personal_leave": 5, "sick_leave": 10}),
    Employee("E008", "Sara Colombo", "sara.colombo@acme.it", Department.SALES,
             "Account Manager", "E006", ContractType.FULL_TIME, date(2021, 7, 15), 44_000.0,
             {"vacation": 20, "personal_leave": 5, "sick_leave": 10}),
    Employee("E009", "Luca Gallo", "luca.gallo@acme.it", Department.SALES,
             "Sales Rep", "E006", ContractType.PART_TIME, date(2023, 1, 10), 28_000.0,
             {"vacation": 25, "personal_leave": 3, "sick_leave": 5}),

    # HR
    Employee("E010", "Elena Fontana", "elena.fontana@acme.it", Department.HR,
             "HR Director", None, ContractType.FULL_TIME, date(2016, 8, 1), 68_000.0,
             {"vacation": 6, "personal_leave": 4, "sick_leave": 10}),
    Employee("E011", "Paolo Moretti", "paolo.moretti@acme.it", Department.HR,
             "HR Specialist", "E010", ContractType.FULL_TIME, date(2020, 4, 1), 40_000.0,
             {"vacation": 16, "personal_leave": 5, "sick_leave": 10}),
    Employee("E012", "Chiara Lombardi", "chiara.lombardi@acme.it", Department.HR,
             "Payroll Admin", "E010", ContractType.FULL_TIME, date(2019, 11, 1), 38_000.0,
             {"vacation": 10, "personal_leave": 5, "sick_leave": 10}),
]

LEAVE_REQUESTS: list[LeaveRequest] = [
    LeaveRequest("LR001", "E002", LeaveType.VACATION, date(2025, 4, 14), date(2025, 4, 18),
                 LeaveStatus.PENDING, "Easter vacation"),
    LeaveRequest("LR002", "E003", LeaveType.VACATION, date(2025, 4, 7), date(2025, 4, 11),
                 LeaveStatus.APPROVED, "Ski week"),
    LeaveRequest("LR003", "E004", LeaveType.PERSONAL, date(2025, 3, 28), date(2025, 3, 28),
                 LeaveStatus.APPROVED, "Medical appointment"),
    LeaveRequest("LR004", "E007", LeaveType.VACATION, date(2025, 5, 1), date(2025, 5, 9),
                 LeaveStatus.PENDING, "Trip to Japan"),
    LeaveRequest("LR005", "E008", LeaveType.SICK, date(2025, 3, 24), date(2025, 3, 26),
                 LeaveStatus.APPROVED, "Flu"),
    LeaveRequest("LR006", "E011", LeaveType.VACATION, date(2025, 6, 16), date(2025, 6, 20),
                 LeaveStatus.PENDING, "Cousin's wedding"),
    LeaveRequest("LR007", "E003", LeaveType.VACATION, date(2025, 7, 1), date(2025, 7, 18),
                 LeaveStatus.PENDING, "Summer vacation"),
    LeaveRequest("LR008", "E009", LeaveType.PERSONAL, date(2025, 4, 2), date(2025, 4, 2),
                 LeaveStatus.REJECTED, "Too many absences in this period already"),
]


def _generate_attendance(emp_id: str, start: date, days: int) -> list[AttendanceRecord]:
    """Generate realistic attendance records for the last N working days."""
    records = []
    d = start
    count = 0
    while count < days:
        if d.weekday() < 5:  # Mon-Fri
            remote = count % 3 == 0  # ~33% remote
            check_in = "09:00" if not remote else "08:45"
            check_out = "18:00" if not remote else "17:30"
            hours = 8.0 if not remote else 7.75
            records.append(AttendanceRecord(emp_id, d, check_in, check_out, hours, remote))
            count += 1
        d -= timedelta(days=1)
    return records


ATTENDANCE: list[AttendanceRecord] = []
for emp in EMPLOYEES:
    ATTENDANCE.extend(_generate_attendance(emp.id, date(2025, 3, 26), 20))


def _payslip(emp: Employee, month: str) -> PayslipSummary:
    monthly_gross = round(emp.salary_gross / 13, 2)  # 13 monthly payments
    deductions = round(monthly_gross * 0.33, 2)  # ~33% tax+contributions
    bonus = 500.0 if month.endswith("-12") else 0.0  # December bonus
    net = round(monthly_gross - deductions + bonus, 2)
    return PayslipSummary(emp.id, month, monthly_gross, net, deductions, bonus)


PAYSLIPS: list[PayslipSummary] = []
for emp in EMPLOYEES:
    for m in range(1, 4):  # Jan-Mar 2025
        PAYSLIPS.append(_payslip(emp, f"2025-{m:02d}"))


# ── Query helpers (simulated DB queries) ─────────────────────────────

def get_employee(employee_id: str) -> Employee | None:
    return next((e for e in EMPLOYEES if e.id == employee_id), None)


def get_employee_by_name(name: str) -> Employee | None:
    """Find an employee by name or role (case-insensitive partial match)."""
    name_lower = name.lower()
    # Try name first
    found = next((e for e in EMPLOYEES if name_lower in e.name.lower()), None)
    if found:
        return found
    # Try role (e.g. "CTO", "HR Director")
    return next((e for e in EMPLOYEES if name_lower in e.role.lower()), None)


def get_leave_balance(employee_id: str) -> dict[str, int] | None:
    emp = get_employee(employee_id)
    return emp.leave_balance if emp else None


def get_leave_requests(
    employee_id: str | None = None,
    status: LeaveStatus | None = None,
    department: Department | None = None,
) -> list[LeaveRequest]:
    results = LEAVE_REQUESTS
    if employee_id:
        results = [r for r in results if r.employee_id == employee_id]
    if status:
        results = [r for r in results if r.status == status]
    if department:
        dept_ids = {e.id for e in EMPLOYEES if e.department == department}
        results = [r for r in results if r.employee_id in dept_ids]
    return results


def get_attendance(
    employee_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[AttendanceRecord]:
    results = ATTENDANCE
    if employee_id:
        results = [r for r in results if r.employee_id == employee_id]
    if from_date:
        results = [r for r in results if r.date >= from_date]
    if to_date:
        results = [r for r in results if r.date <= to_date]
    return results


def get_payslips(employee_id: str, month: str | None = None) -> list[PayslipSummary]:
    results = [p for p in PAYSLIPS if p.employee_id == employee_id]
    if month:
        results = [p for p in results if p.month == month]
    return results


def get_team(manager_id: str) -> list[Employee]:
    return [e for e in EMPLOYEES if e.manager_id == manager_id]


def get_department_employees(department: Department) -> list[Employee]:
    return [e for e in EMPLOYEES if e.department == department]


def get_org_chart() -> dict:
    """Returns a nested org chart."""
    top_level = [e for e in EMPLOYEES if e.manager_id is None]
    chart = {}
    for mgr in top_level:
        reports = get_team(mgr.id)
        chart[mgr.name] = {
            "role": mgr.role,
            "department": mgr.department.value,
            "reports": [{"name": r.name, "role": r.role} for r in reports],
        }
    return chart
