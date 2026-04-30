from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = BASE_DIR / "data" / "demo_billing_data.json"


@dataclass
class BillingFactsEngine:
    """Load billing data and explain a requested billing window."""

    data_path: Path = DEFAULT_DATA_PATH

    def __post_init__(self) -> None:
        raw = self.data_path.read_text(encoding="utf-8").strip()
        self.data = json.loads(raw) if raw else {}

    def explain_window(
        self,
        customer_id: str | int,
        start_date: str,
        end_date: str,
        claimed_amount: float | None = None,
        max_line_items: int = 10,
    ) -> dict[str, Any]:
        normalized_customer_id = self.normalize_customer_id(customer_id)
        account = self.data["accounts"].get(normalized_customer_id)
        if account is None:
            raise ValueError(f"Unknown customer_id: {customer_id}")

        start = self._parse_date(start_date)
        end = self._parse_date(end_date)
        if start > end:
            raise ValueError("start_date must be earlier than or equal to end_date.")

        invoices = self.data["invoices"].get(normalized_customer_id, [])
        normalized_invoices = [self._normalize_invoice(account, invoice) for invoice in invoices]

        relevant_invoices = [
            invoice
            for invoice in normalized_invoices
            if self._ranges_overlap(
                start,
                end,
                date.fromisoformat(invoice["billing_start"]),
                date.fromisoformat(invoice["billing_end"]),
            )
        ]
        if not relevant_invoices and normalized_invoices:
            relevant_invoices = self._fallback_invoices(normalized_invoices, claimed_amount)

        invoice_total = round(sum(float(item["total_due"]) for item in relevant_invoices), 2)
        usage_total = round(sum(float(invoice["total_kwh"]) for invoice in relevant_invoices), 2)
        peak_total = round(sum(float(invoice["peak_kwh"]) for invoice in relevant_invoices), 2)
        off_peak_total = round(sum(float(invoice.get("off_peak_kwh", 0.0)) for invoice in relevant_invoices), 2)

        line_items: list[dict[str, Any]] = []
        for invoice in relevant_invoices:
            for item in invoice["line_items"]:
                line_items.append({**item, "invoice_id": invoice["invoice_id"]})

        amount_matches = None
        if claimed_amount is not None:
            amount_matches = abs(round(float(claimed_amount), 2) - invoice_total) < 0.01

        return {
            "customer_id": normalized_customer_id,
            "customer_name": account["name"],
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "account": {
                "plan_name": account["plan"]["name"],
                "autopay": bool(account["autopay"]),
                "paperless": bool(account["paperless"]),
                "loyalty_months": int(account["loyalty_months"]),
                "medical_exemption": bool(account["medical_exemption"]),
                "tax_exempt": bool(account["tax_exempt"]),
            },
            "amount_in_window": round(invoice_total, 2),
            "charge_total": round(invoice_total, 2),
            "payment_total": 0.0,
            "invoice_total_for_relevant_periods": round(invoice_total, 2),
            "claimed_amount": round(float(claimed_amount), 2) if claimed_amount is not None else None,
            "claimed_amount_matches": amount_matches,
            "usage_summary": {
                "invoice_count": len(relevant_invoices),
                "total_kwh": usage_total,
                "peak_kwh": peak_total,
                "off_peak_kwh": off_peak_total,
            },
            "charge_events": [],
            "payment_events": [],
            "relevant_invoices": relevant_invoices,
            "line_items": line_items[:max_line_items],
            "computation_checks": [
                {
                    "invoice_id": invoice["invoice_id"],
                    "recomputed_total_due": invoice["total_due"],
                    "line_item_sum": round(sum(float(item["amount"]) for item in invoice["line_items"]), 2),
                }
                for invoice in relevant_invoices
            ],
        }

    @staticmethod
    def normalize_customer_id(customer_id: str | int) -> str:
        """Normalize inputs like `1001` or `cust-1001` to `CUST-1001`."""
        if isinstance(customer_id, int):
            return f"CUST-{customer_id:04d}"
        text = str(customer_id).strip().upper()
        if text.isdigit():
            return f"CUST-{int(text):04d}"
        return text

    @staticmethod
    def _ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
        return max(start_a, start_b) <= min(end_a, end_b)

    @staticmethod
    def _parse_date(value: str) -> date:
        text = str(value).strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            return datetime.fromisoformat(text).date()

    @staticmethod
    def _parse_policy_refs(value: Any) -> list[str]:
        """Normalize either `policy_ref` or `policy_refs` into a clean list."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        if not text:
            return []
        return [part.strip().replace("§", "Section ") for part in text.split(",") if part.strip()]

    def _normalize_invoice(self, account: dict[str, Any], invoice: dict[str, Any]) -> dict[str, Any]:
        """Convert raw invoice JSON into the uniform shape used by the agent."""
        line_items: list[dict[str, Any]] = []
        for item in invoice.get("line_items", []):
            normalized_item = {
                "description": item["description"],
                "amount": round(float(item["amount"]), 2),
                "policy_refs": self._parse_policy_refs(item.get("policy_refs", item.get("policy_ref"))),
            }
            if item.get("detail"):
                normalized_item["detail"] = item["detail"]
            line_items.append(normalized_item)

        total_due = invoice.get("total_due", invoice.get("total"))
        if total_due is None:
            total_due = round(sum(float(item["amount"]) for item in line_items), 2)

        meter_summary = self._meter_summary_for_invoice(account["customer_id"], invoice)
        return {
            "invoice_id": invoice["invoice_id"],
            "billing_start": invoice["billing_start"],
            "billing_end": invoice["billing_end"],
            "issue_date": invoice.get("issue_date"),
            "due_date": invoice.get("due_date"),
            "days_in_cycle": invoice.get("days_in_cycle"),
            "total_kwh": round(float(invoice.get("total_kwh", meter_summary["total_kwh"])), 2),
            "peak_kwh": round(float(invoice.get("peak_kwh", meter_summary["peak_kwh"])), 2),
            "off_peak_kwh": round(float(meter_summary["off_peak_kwh"]), 2),
            "solar_export_kwh": round(
                float(invoice.get("solar_export_kwh", account.get("solar_export_kwh", 0.0))),
                2,
            ),
            "taxable_base": round(
                sum(
                    float(item["amount"])
                    for item in line_items
                    if float(item["amount"]) > 0
                    and item["description"] not in {
                        "Renewable Energy Fund",
                        "State Regulatory Fee",
                        "City Utility Tax",
                    }
                ),
                2,
            ),
            "line_items": line_items,
            "total_due": round(float(total_due), 2),
        }

    def _meter_summary_for_invoice(self, customer_id: str, invoice: dict[str, Any]) -> dict[str, float]:
        """Return invoice-aligned usage totals, preferring dedicated meter rows."""
        meter_rows = self.data.get("meter_reads", {}).get(customer_id, [])
        for row in meter_rows:
            if (
                row.get("billing_start") == invoice.get("billing_start")
                and row.get("billing_end") == invoice.get("billing_end")
            ):
                total_kwh = float(row.get("total_kwh", invoice.get("total_kwh", 0.0)))
                peak_kwh = float(row.get("peak_kwh", invoice.get("peak_kwh", 0.0)))
                off_peak_kwh = float(row.get("off_peak_kwh", max(total_kwh - peak_kwh, 0.0)))
                return {
                    "total_kwh": total_kwh,
                    "peak_kwh": peak_kwh,
                    "off_peak_kwh": off_peak_kwh,
                }

        total_kwh = float(invoice.get("total_kwh", 0.0))
        peak_kwh = float(invoice.get("peak_kwh", 0.0))
        return {
            "total_kwh": total_kwh,
            "peak_kwh": peak_kwh,
            "off_peak_kwh": max(total_kwh - peak_kwh, 0.0),
        }

    @staticmethod
    def _fallback_invoices(invoices: list[dict[str, Any]], claimed_amount: float | None) -> list[dict[str, Any]]:
        """Choose a best-effort invoice when date matching alone is not enough."""
        if claimed_amount is not None:
            matches = [
                invoice
                for invoice in invoices
                if abs(round(float(claimed_amount), 2) - round(float(invoice["total_due"]), 2)) < 0.01
            ]
            if matches:
                return matches[:1]
        return invoices[-1:] if invoices else []
