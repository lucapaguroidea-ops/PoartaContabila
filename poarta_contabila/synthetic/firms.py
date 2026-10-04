"""Invented firms and partners: five CO.DiT profiles that differ where the paths do.

Every CUI is built from an invented body plus its check digit (``cui_is_valid``); IBANs use
the non-existent bank code ``AAAA`` with a correct check pair. Nothing names a real firm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from poarta_contabila.types import cui_is_valid

_CUI_KEY = "753217532"
AS_OF = "2026-01-01"


def with_check(body: int) -> str:
    """The CUI whose digits before the check digit are *body*."""
    digits = str(body).zfill(9)
    total = sum(int(d) * int(k) for d, k in zip(digits, _CUI_KEY, strict=True))
    check = total * 10 % 11
    cui = f"{body}{0 if check == 10 else check}"
    assert cui_is_valid(cui), cui
    return cui


def iban(account: str) -> str:
    """An invented RO IBAN: bank code ``AAAA`` (no such bank) and *account* (16 characters)."""
    bban = f"AAAA{account.upper():0>16}"[:20]
    digits = "".join(str(int(c, 36)) for c in bban + "RO00")
    return f"RO{98 - int(digits) % 97:02d}{bban}"


@dataclass(frozen=True)
class Party:
    """A partner: a RO firm (``cui``) or one from abroad (``vat_id``, no CUI)."""

    key: str
    name: str
    analytic: str  # the SAGA analytic it posts to, e.g. 401.00003
    cui: str | None = None
    vat_id: str | None = None
    country: str = "RO"
    vat_payer: bool = True

    @property
    def tax_id(self) -> str:
        if self.cui is None:
            return self.vat_id or ""
        return f"RO{self.cui}" if self.vat_payer else self.cui

    @property
    def short(self) -> str:
        return "".join(w for w in self.name.split() if w not in ("SRL", "SA", "GMBH"))[:16]


Profile = Literal["platitor", "incasare", "neplatitor", "abroad", "bonuri"]


@dataclass(frozen=True)
class Firm:
    key: Profile
    cui: str
    name: str
    folder: str
    axes: dict[str, str]
    suppliers: tuple[Party, ...]
    customers: tuple[Party, ...]
    foreign: tuple[Party, ...] = ()
    foreign_customers: tuple[Party, ...] = ()
    bank_account: str = "5121.01"
    cash_account: str = "5311"
    book_of_record: Literal["saga", "nextup"] = "saga"
    opening: dict[str, int] = field(default_factory=dict)  # account → cents (+debit/−credit)

    @property
    def iban(self) -> str:
        return iban(f"{self.cui}0001")

    @property
    def vat_payer(self) -> bool:
        return self.axes.get("tva") == "tva_platitor"

    @property
    def la_incasare(self) -> bool:
        return self.axes.get("exig") == "tva_la_incasare"

    @property
    def header(self) -> str:
        """The firm line of a SAGA export (``read_firm_cui`` reads the c.f.)."""
        cf = f"RO{self.cui}" if self.vat_payer else self.cui
        return f"{self.name}   c.f. {cf}   r.c. J00/{self.cui[-3:]}/2021"

    def party(self, key: str) -> Party:
        for p in (*self.suppliers, *self.customers, *self.foreign, *self.foreign_customers):
            if p.key == key:
                return p
        raise KeyError(f"{self.key} has no partner {key!r}")

    def tenant(self) -> dict[str, Any]:
        """The body of ``PUT /tenants/{cui}``."""
        return {
            "cui": self.cui,
            "name": self.name,
            "saga_firm_folder": self.folder,
            "book_of_record": self.book_of_record,
            "data_class": "synthetic",
            "bank_accounts": {self.iban: self.bank_account},
        }

    def codit(self) -> dict[str, Any]:
        """The body of ``PUT /codit/{cui}/{period}``: every axis confirmed, invented source."""
        return {
            "axes": {
                k: {"value": v, "certainty": "confirmed", "as_of": AS_OF, "source": "synthetic"}
                for k, v in self.axes.items()
            }
        }


def _ro(n: int, name: str, role: str, *, vat_payer: bool = True) -> Party:
    root = "401" if role == "supplier" else "4111"
    return Party(
        key=f"{role[0]}{n}",
        name=name,
        analytic=f"{root}.{n:05d}",
        cui=with_check(2001000 + 10 * (1 if role == "supplier" else 2) + n),
        vat_payer=vat_payer,
    )


def _foreign(n: int, name: str, country: str, vat_id: str) -> Party:
    return Party(
        key=f"x{n}", name=name, analytic=f"401.{90 + n:05d}", vat_id=vat_id, country=country
    )


SUPPLIERS = (
    _ro(1, "FURNIZOR ALFA SRL", "supplier"),
    _ro(2, "FURNIZOR BETA SRL", "supplier"),
    _ro(3, "FURNIZOR GAMA SRL", "supplier"),
    _ro(4, "FURNIZOR DELTA SRL", "supplier", vat_payer=False),
)
CUSTOMERS = (
    _ro(1, "CLIENT ALFA SRL", "customer"),
    _ro(2, "CLIENT BETA SRL", "customer"),
    _ro(3, "CLIENT GAMA SRL", "customer"),
)
FOREIGN = (
    _foreign(1, "EXEMPLU SOFTWARE GMBH", "DE", "DE000000001"),
    _foreign(2, "MODELO SERVICIOS SL", "ES", "ESX0000001X"),
)
FOREIGN_CUSTOMERS = (
    Party(
        key="y1",
        name="EXEMPLU RETAIL BV",
        analytic="4111.00091",
        vat_id="NL000000001B01",
        country="NL",
    ),
)
_OPENING = {"5121.01": 2_500_000, "1012": -20_000, "117": -2_480_000}


def _firm(n: int, key: Profile, name: str, axes: dict[str, str], **kw: Any) -> Firm:
    return Firm(
        key=key,
        cui=with_check(100100 + n),
        name=name,
        folder=f"{n:04d}",
        axes=axes,
        suppliers=kw.pop("suppliers", SUPPLIERS),
        customers=kw.pop("customers", CUSTOMERS),
        opening=kw.pop("opening", dict(_OPENING)),
        **kw,
    )


FIRMS: dict[str, Firm] = {
    f.key: f
    for f in (
        _firm(
            1,
            "platitor",
            "SINTETIC ALFA SRL",
            {
                "forma": "srl",
                "impozit": "profit_16",
                "tva": "tva_platitor",
                "exig": "tva_exig_livrare",
                "employees": "has",
                "cross_border": "none",
            },
        ),
        _firm(
            2,
            "incasare",
            "SINTETIC BETA SRL",
            {
                "forma": "srl",
                "impozit": "micro_1",
                "tva": "tva_platitor",
                "exig": "tva_la_incasare",
                "employees": "none",
                "cross_border": "none",
            },
        ),
        _firm(
            3,
            "neplatitor",
            "SINTETIC GAMA SRL",
            {
                "forma": "srl",
                "impozit": "micro_1",
                "tva": "tva_neplatitor",
                "employees": "none",
                "cross_border": "inbound_eu_services",
            },
            foreign=FOREIGN[:1],
        ),
        _firm(
            4,
            "abroad",
            "SINTETIC DELTA SRL",
            {
                "forma": "srl",
                "impozit": "profit_16",
                "tva": "tva_platitor",
                "exig": "tva_exig_livrare",
                "employees": "has",
                "cross_border": "mixed",
            },
            foreign=FOREIGN,
            foreign_customers=FOREIGN_CUSTOMERS,
        ),
        _firm(
            5,
            "bonuri",
            "SINTETIC EPSILON SRL",
            {
                "forma": "srl",
                "impozit": "micro_1",
                "tva": "tva_platitor",
                "exig": "tva_exig_livrare",
                "employees": "has",
                "cross_border": "none",
            },
        ),
    )
}


def firm(key: str, *, book_of_record: Literal["saga", "nextup"] = "saga") -> Firm:
    """One of :data:`FIRMS`; ``book_of_record="nextup"`` is the same firm kept in NextUp."""
    f = FIRMS[key]
    if book_of_record == f.book_of_record:
        return f
    from dataclasses import replace

    # a firm of its own (another CUI): one firm-period has one book of record (LAW L8)
    n = int(f.folder)
    return replace(
        f,
        cui=with_check(100200 + n),
        name=f.name.replace(" SRL", " NX SRL"),
        folder=f"{200 + n:04d}",
        book_of_record=book_of_record,
        axes={**f.axes, "book_of_record": "nextup"},
    )
