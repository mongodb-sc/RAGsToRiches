"""Generate synthetic retail banking data and Atlas search indexes.

Creates 50 customers, 100 accounts, household links, joint transactions,
customer-service transcripts, and 20 policy documents. Policy text is
embedded with OpenAI ``text-embedding-3-small`` (or a local hash fallback)
and written to ``knowledge_base``.

MongoDB documentation:
- Vector Search index type: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-type/
- Create embeddings: https://www.mongodb.com/docs/atlas/atlas-vector-search/create-embeddings/
- Atlas Search index mappings: https://www.mongodb.com/docs/atlas/atlas-search/define-field-mappings/
- PyMongo ``SearchIndexModel``: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/atlas-search-index/
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from faker import Faker
from pymongo import ASCENDING
from pymongo.operations import SearchIndexModel

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.agent_memory import ensure_memory_indexes
from app.services.audit_lineage import ensure_audit_indexes
from app.services.database import get_collection, get_database, ping_atlas
from app.services.vector_search import embed_text

FAKER_SEED = 42
CUSTOMER_COUNT = 50
ACCOUNT_COUNT = 100
HOUSEHOLD_COUNT = 15
POLICY_COUNT = 20
TRANSCRIPT_COUNT = 16
JOINT_TRANSACTION_COUNT = 40

ACCOUNT_TYPES = (
    "checking",
    "savings",
    "money_market",
    "cd",
    "brokerage",
)
ACCOUNT_WEIGHTS = (0.38, 0.27, 0.12, 0.13, 0.10)


def _policy_documents() -> list[dict[str, Any]]:
    """Return 20 retail-banking policy documents with governance metadata."""

    return [
        {
            "doc_id": "POL-001",
            "title": "Personal Checking Deposit Account Agreement",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Atlas National Bank Personal Checking accounts are demand deposit accounts. "
                "Deposits become available according to the Funds Availability Policy. "
                "The bank may require two forms of identification when opening an account and "
                "may refuse a deposit that cannot be verified. Interest is not paid on standard "
                "checking unless the product is explicitly advertised as interest-bearing. "
                "Joint owners are jointly and severally liable for overdrafts, fees, and "
                "negative balances. Either owner may close the account or request a stop payment."
            ),
        },
        {
            "doc_id": "POL-002",
            "title": "High-Yield Savings Account Agreement",
            "document_type": "deposit_agreement",
            "product_type": "savings",
            "clearance_level": "public",
            "content": (
                "High-Yield Savings accounts earn a variable annual percentage yield that may "
                "change at any time. Interest is compounded daily and credited monthly. "
                "The bank reserves the right to require seven days' written notice before a "
                "withdrawal. Excessive withdrawals may be limited under federal savings "
                "account rules. The minimum opening deposit is $100. If the collected balance "
                "falls below $100, the account may be converted to a standard savings product."
            ),
        },
        {
            "doc_id": "POL-003",
            "title": "Money Market Account Terms",
            "document_type": "deposit_agreement",
            "product_type": "money_market",
            "clearance_level": "public",
            "content": (
                "Money Market accounts combine check-writing with a tiered interest rate. "
                "Rates increase at collected-balance tiers of $10,000, $50,000, and $100,000. "
                "Checks and ACH debits are limited to six per statement cycle. Additional "
                "third-party transfers may be declined or assessed an excess-activity fee. "
                "The account is not a money market mutual fund and is FDIC-insured to "
                "applicable limits when combined with other deposit balances."
            ),
        },
        {
            "doc_id": "POL-004",
            "title": "Certificate of Deposit Agreement",
            "document_type": "deposit_agreement",
            "product_type": "cd",
            "clearance_level": "public",
            "content": (
                "Certificates of Deposit are time deposits with fixed terms of 3, 6, 12, 24, "
                "or 60 months. Early withdrawal of principal incurs a penalty equal to 90 days "
                "of simple interest for terms of 12 months or less and 180 days of simple "
                "interest for longer terms. Automatically renewable CDs renew at the then-current "
                "rate for the same term unless the owner provides notice during the 10-day "
                "grace period after maturity. IRA CDs follow additional plan documents."
            ),
        },
        {
            "doc_id": "POL-005",
            "title": "Consumer Domestic Wire Transfer Rules",
            "document_type": "wire_rules",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Domestic consumer wires submitted before 3:00 p.m. Eastern Time on a business "
                "day are typically released the same day. Cutoff for same-day processing is "
                "strict; later requests are queued for the next business day. The sender must "
                "provide the beneficiary name, account number, and receiving bank routing "
                "number. Atlas National Bank does not verify that the beneficiary name matches "
                "the account number supplied by the customer. Recalled wires are best-effort "
                "only and may already have been credited by the receiving bank."
            ),
        },
        {
            "doc_id": "POL-006",
            "title": "International Wire Transfer and OFAC Screening",
            "document_type": "wire_rules",
            "product_type": "checking",
            "clearance_level": "internal",
            "content": (
                "International wires require a SWIFT/BIC, beneficiary address, and purpose of "
                "payment. Every outbound and inbound cross-border payment is screened against "
                "OFAC and internal watchlists before release. Hits are escalated to the "
                "Financial Crimes Operations team and may delay funds for several business days. "
                "Correspondent bank fees can be deducted from principal. USD wires sent via "
                "intermediary banks may arrive as a reduced net amount. Agents must never "
                "coach a customer to alter beneficiary data to bypass a screening hit."
            ),
        },
        {
            "doc_id": "POL-007",
            "title": "ACH Origination and Incoming Credit Rules",
            "document_type": "wire_rules",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Incoming ACH credits generally post on the effective date. Same-day ACH "
                "credits received before the last NACHA window may post intra-day. Customers "
                "have 60 days from the statement date to dispute an unauthorized consumer ACH "
                "debit under Regulation E. Business accounts follow NACHA return timeframes "
                "and may have a shorter window. Stop-payment orders on ACH items require the "
                "company name, amount, and approximate date and remain in force for six months."
            ),
        },
        {
            "doc_id": "POL-008",
            "title": "Personal Checking Fee Schedule",
            "document_type": "fee_schedule",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Monthly maintenance is $12 and is waived with a $1,500 average collected "
                "balance or a qualifying direct deposit of $500 or more. Paper statements "
                "are $3 per cycle. Out-of-network ATM withdrawals are $3 plus any operator "
                "surcharge. Official checks are $10. Incoming domestic wires are $15. "
                "Outgoing domestic wires are $25. Overdraft paid-item fees are described in "
                "the Overdraft Privilege Disclosure and are not assessed on accounts opted out "
                "of discretionary overdraft coverage."
            ),
        },
        {
            "doc_id": "POL-009",
            "title": "Savings and Money Market Fee Schedule",
            "document_type": "fee_schedule",
            "product_type": "savings",
            "clearance_level": "public",
            "content": (
                "Standard savings monthly maintenance is $5, waived with a $300 daily balance. "
                "Money Market monthly maintenance is $15, waived with a $10,000 average "
                "collected balance. Excess withdrawal fees are $10 per item after six "
                "third-party transfers in a statement cycle. Incoming wires to savings are "
                "free. Early account closure within 90 days of opening is $25. Printed "
                "interim statements requested in-branch are $5 each."
            ),
        },
        {
            "doc_id": "POL-010",
            "title": "Overdraft Privilege Disclosure",
            "document_type": "fee_schedule",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Overdraft Privilege is a discretionary service, not a line of credit. The "
                "bank may pay or return items that exceed the available balance. A paid-item "
                "overdraft fee of $35 may be assessed per item, with a daily maximum of four "
                "fees. Transactions of $5 or less do not receive an overdraft fee. Continuous "
                "overdraft fees begin on the fifth consecutive calendar day a balance remains "
                "negative. ATM and one-time debit card overdrafts require an affirmative "
                "Reg E opt-in. Customers may opt out at any time in online banking."
            ),
        },
        {
            "doc_id": "POL-011",
            "title": "Electronic Fund Transfer and Online Banking Disclosure",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Online banking, mobile deposit, Zelle-style person-to-person payments, and "
                "debit card transactions are electronic fund transfers covered by Regulation E. "
                "Customers must report an unauthorized transfer within 60 days of the statement "
                "that first reflected the error. Prompt notice of a lost debit card limits "
                "consumer liability to $50 if reported within two business days. Mobile "
                "deposits are subject to extended holds when the item is a new-account "
                "deposit, a large item, or a redeposited check."
            ),
        },
        {
            "doc_id": "POL-012",
            "title": "Debit Card Cardholder Agreement",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Visa debit cards access the primary checking account and any linked overdraft "
                "protection source. Daily point-of-sale limits default to $3,000 and ATM "
                "limits default to $500. The bank may lower limits when fraud scoring is "
                "elevated. PIN-based transactions post faster than signature transactions. "
                "A hold equal to the authorization amount, including hotels and fuel "
                "preauthorizations, reduces available balance until the merchant clears or "
                "the hold expires, typically within three business days."
            ),
        },
        {
            "doc_id": "POL-013",
            "title": "Joint Account Ownership and Survivorship Rules",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "internal",
            "content": (
                "Joint accounts are opened as joint tenants with right of survivorship unless "
                "the signature card specifies tenants in common. Either owner may withdraw all "
                "funds, add a payee, or close the account without the other owner's consent. "
                "A levy, garnishment, or support order against one owner may attach the entire "
                "balance. Upon death of one owner, the surviving owner becomes the sole owner "
                "after presenting a certified death certificate. Household graph links in the "
                "core system must be updated the same day the survivorship change posts."
            ),
        },
        {
            "doc_id": "POL-014",
            "title": "Payable-on-Death Beneficiary Rules",
            "document_type": "deposit_agreement",
            "product_type": "savings",
            "clearance_level": "internal",
            "content": (
                "A payable-on-death (POD) designation transfers the account to named "
                "beneficiaries after the death of the last surviving owner. Beneficiaries have "
                "no access while an owner is living. Changing a POD designation requires a "
                "signed account maintenance form. If all named beneficiaries predecease the "
                "owner and no contingent beneficiary is on file, the balance becomes part of "
                "the owner's estate. Retirement accounts follow plan beneficiary forms rather "
                "than this POD policy."
            ),
        },
        {
            "doc_id": "POL-015",
            "title": "Consumer Privacy Notice and GLBA Data Sharing",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Atlas National Bank collects Social Security numbers, account balances, "
                "transaction history, and device data to service accounts and meet BSA "
                "obligations. Nonpublic personal information is not sold to unaffiliated "
                "marketers. The bank shares data with service providers under confidentiality "
                "agreements and with regulators as required by law. Customers may opt out of "
                "affiliate marketing but cannot opt out of sharing required for fraud, "
                "servicing, or legal process. Tier 1 agents must not read SSN or exact "
                "balance values aloud in an unsecured environment."
            ),
        },
        {
            "doc_id": "POL-016",
            "title": "Customer Identification Program and BSA/AML Procedures",
            "document_type": "wire_rules",
            "product_type": "checking",
            "clearance_level": "restricted",
            "content": (
                "Before an account is opened, CIP requires name, date of birth, street "
                "address, and SSN or other taxpayer identification number. Documentary "
                "verification uses an unexpired government photo ID. Non-documentary checks "
                "include consumer reporting agencies and OFAC. A CIP exception must be "
                "approved by Compliance and documented in the customer transcript. Structured "
                "cash deposits designed to avoid a Currency Transaction Report are a red flag "
                "and must be escalated for Suspicious Activity Report consideration. Do not "
                "tell the customer that a SAR is being filed."
            ),
        },
        {
            "doc_id": "POL-017",
            "title": "Funds Availability Policy Regulation CC",
            "document_type": "deposit_agreement",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Cash, electronic credits, and the first $225 of a check deposit are generally "
                "available on the first business day after the banking day of deposit. "
                "Remaining check funds are available on the second business day. Longer holds "
                "may apply for new accounts under 30 days, deposits over $5,525, redeposited "
                "checks, and repeated overdrafts. Case-by-case holds require a written notice "
                "describing the reason and the day funds will become available. Branches "
                "treat 2:00 p.m. local time as the deposit cutoff."
            ),
        },
        {
            "doc_id": "POL-018",
            "title": "Early Account Closure and Dormancy Fee Policy",
            "document_type": "fee_schedule",
            "product_type": "checking",
            "clearance_level": "public",
            "content": (
                "Accounts closed within 90 days of opening may be assessed a $25 early-closure "
                "fee. An account with no customer-initiated activity for 12 months is "
                "classified as inactive and may lose fee waivers. After 24 months of "
                "inactivity the account is dormant and a $10 quarterly dormancy fee may apply "
                "if permitted by state law. Balances that remain unclaimed after the state "
                "escheatment period are remitted to the state of last known address as "
                "abandoned property."
            ),
        },
        {
            "doc_id": "POL-019",
            "title": "Stop Payment Request Procedures",
            "document_type": "wire_rules",
            "product_type": "checking",
            "clearance_level": "internal",
            "content": (
                "A stop payment on a check is effective for six months and may be renewed. "
                "The customer must provide the account number, check number, exact amount, "
                "and payee. Oral stop payments must be confirmed in writing within 14 days. "
                "A $35 stop-payment fee posts when the request is accepted. The bank is not "
                "liable if the item has already paid or if the description is not precise "
                "enough to identify the item. Cashiers' checks and official checks generally "
                "cannot be stopped except in cases of lost, stolen, or destroyed instruments "
                "after a 90-day waiting period and an indemnity bond."
            ),
        },
        {
            "doc_id": "POL-020",
            "title": "Household Relationship and Relationship-Pricing Policy",
            "document_type": "fee_schedule",
            "product_type": "brokerage",
            "clearance_level": "restricted",
            "content": (
                "Relationship pricing aggregates deposit, CD, and brokerage balances across "
                "a household graph. Combined balances of $100,000 waive checking and savings "
                "maintenance fees for every linked owner. Combined balances of $250,000 "
                "qualify the household for preferred wire fees and a 0.05% CD rate bump. "
                "Joint accounts count once toward household AUM. Agents must not disclose "
                "one household member's exact balances to another member without a recorded "
                "authorization or a documented joint-ownership relationship. Compliance may "
                "review the full household graph, including restricted transcripts."
            ),
        },
    ]


def _chunked_embed(texts: list[str]) -> list[list[float]]:
    """Embed many documents, using one OpenAI batch when a key is present."""

    settings = get_settings()
    if not settings.openai_api_key:
        return [embed_text(text, settings) for text in texts]

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    vectors: list[list[float]] = []
    batch_size = 20
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(list(item.embedding) for item in ordered)
    return vectors


def _split_customers(fake: Faker) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create households first, then assign 50 customers across them."""

    households: list[dict[str, Any]] = []
    remaining = CUSTOMER_COUNT
    sizes: list[int] = []
    for index in range(HOUSEHOLD_COUNT):
        slots_left = HOUSEHOLD_COUNT - index
        if slots_left == 1:
            size = remaining
        else:
            size = max(1, min(4, remaining - (slots_left - 1)))
            if remaining > slots_left:
                size = random.choice([1, 2, 2, 3, 3, 4])
                size = min(size, remaining - (slots_left - 1))
        sizes.append(size)
        remaining -= size

    customers: list[dict[str, Any]] = []
    customer_index = 1
    for household_number, size in enumerate(sizes, start=1):
        household_id = f"HH-{household_number:02d}"
        last_name = fake.last_name()
        member_ids: list[str] = []
        for member_offset in range(size):
            customer_id = f"CUST-{customer_index:04d}"
            member_ids.append(customer_id)
            first_name = fake.first_name()
            customers.append(
                {
                    "customer_id": customer_id,
                    "first_name": first_name,
                    "last_name": last_name if member_offset > 0 or size > 1 else fake.last_name(),
                    "ssn": fake.ssn(),
                    "email": fake.unique.email(),
                    "phone": fake.phone_number(),
                    "date_of_birth": fake.date_of_birth(minimum_age=21, maximum_age=84).isoformat(),
                    "address": {
                        "street": fake.street_address(),
                        "city": fake.city(),
                        "state": fake.state_abbr(),
                        "postal_code": fake.postcode(),
                    },
                    "household_id": household_id,
                    "kyc_status": random.choice(["verified", "verified", "verified", "review"]),
                    "risk_tier": random.choice(["low", "low", "medium", "high"]),
                    "linked_customer_ids": [],
                    "account_ids": [],
                }
            )
            customer_index += 1

        for customer in customers:
            if customer["household_id"] != household_id:
                continue
            customer["linked_customer_ids"] = [
                other["customer_id"]
                for other in customers
                if other["household_id"] == household_id
                and other["customer_id"] != customer["customer_id"]
            ]

        households.append(
            {
                "household_id": household_id,
                "primary_customer_id": member_ids[0],
                "member_ids": member_ids,
                "combined_aum": 0.0,
            }
        )

    return households, customers


def _build_accounts(
    fake: Faker,
    customers: list[dict[str, Any]],
    households: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create 100 accounts, including joint accounts within a household."""

    accounts: list[dict[str, Any]] = []
    household_members = {item["household_id"]: item["member_ids"] for item in households}
    joint_budget = 28

    for index in range(1, ACCOUNT_COUNT + 1):
        account_id = f"ACCT-{index:04d}"
        owner = customers[(index - 1) % len(customers)]
        owners = [owner["customer_id"]]
        is_joint = False
        if joint_budget > 0 and len(household_members[owner["household_id"]]) > 1:
            partner_ids = [
                member_id
                for member_id in household_members[owner["household_id"]]
                if member_id != owner["customer_id"]
            ]
            if partner_ids:
                owners.append(random.choice(partner_ids))
                is_joint = True
                joint_budget -= 1

        product_type = random.choices(ACCOUNT_TYPES, weights=ACCOUNT_WEIGHTS, k=1)[0]
        balance = round(random.uniform(250, 185_000), 2)
        opened_at = fake.date_time_between(start_date="-8y", end_date="-30d", tzinfo=timezone.utc)
        accounts.append(
            {
                "account_id": account_id,
                "account_type": product_type,
                "product_type": product_type,
                "balance": balance,
                "available_balance": round(balance * random.uniform(0.86, 1.0), 2),
                "owner_ids": owners,
                "household_id": owner["household_id"],
                "status": random.choice(["open", "open", "open", "restricted"]),
                "opened_at": opened_at,
                "interest_rate": round(random.uniform(0.0001, 0.051), 4),
                "is_joint": is_joint,
                "routing_number": "021000021",
                "account_number": f"{random.randint(100000000, 999999999)}",
            }
        )

    accounts_by_owner: dict[str, list[str]] = {customer["customer_id"]: [] for customer in customers}
    household_aum: dict[str, float] = {household["household_id"]: 0.0 for household in households}
    for account in accounts:
        for owner_id in account["owner_ids"]:
            accounts_by_owner[owner_id].append(account["account_id"])
        household_aum[account["household_id"]] += account["balance"]

    for customer in customers:
        customer["account_ids"] = accounts_by_owner[customer["customer_id"]]
    for household in households:
        household["combined_aum"] = round(household_aum[household["household_id"]], 2)

    return accounts


def _build_transactions(fake: Faker, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create recent transfers, including joint-account activity."""

    transactions: list[dict[str, Any]] = []
    joint_accounts = [account for account in accounts if account["is_joint"]]
    now = datetime.now(timezone.utc)

    for index in range(1, JOINT_TRANSACTION_COUNT + 1):
        account = joint_accounts[(index - 1) % len(joint_accounts)] if joint_accounts else random.choice(accounts)
        counterpart = random.choice(accounts)
        txn_type = random.choice(["transfer", "wire", "ach", "deposit", "fee"])
        amount = round(random.uniform(25, 12_500), 2)
        transactions.append(
            {
                "transaction_id": f"TXN-{index:04d}",
                "account_id": account["account_id"],
                "related_account_id": counterpart["account_id"],
                "customer_ids": list(dict.fromkeys(account["owner_ids"] + counterpart["owner_ids"])),
                "amount": amount,
                "type": txn_type,
                "is_joint": bool(account["is_joint"] or len(account["owner_ids"]) > 1),
                "timestamp": now - timedelta(days=random.randint(0, 45), hours=random.randint(0, 20)),
                "description": fake.sentence(nb_words=8),
            }
        )
    return transactions


def _build_transcripts(
    fake: Faker,
    customers: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create restricted customer-service transcripts that contain PII."""

    accounts_by_id = {account["account_id"]: account for account in accounts}
    transcripts: list[dict[str, Any]] = []
    for index, customer in enumerate(customers[:TRANSCRIPT_COUNT], start=1):
        account = accounts_by_id.get(customer["account_ids"][0]) if customer["account_ids"] else None
        balance = account["balance"] if account else 0.0
        account_id = account["account_id"] if account else "ACCT-0000"
        transcripts.append(
            {
                "doc_id": f"TR-{index:03d}",
                "transcript_id": f"TR-{index:03d}",
                "title": f"Service transcript for {customer['first_name']} {customer['last_name']}",
                "customer_id": customer["customer_id"],
                "agent_id": f"AGT-{random.randint(100, 199)}",
                "source": "transcript",
                "document_type": "customer_transcript",
                "product_type": account["product_type"] if account else "checking",
                "clearance_level": "restricted",
                "content": (
                    f"Agent verified SSN {customer['ssn']} for customer {customer['customer_id']}. "
                    f"Caller requested a balance on {account_id}. Posted balance is ${balance:,.2f}. "
                    f"Date of birth on file is {customer['date_of_birth']}. "
                    f"{fake.sentence()} Joint household {customer['household_id']} was reviewed "
                    "for relationship pricing. Agent offered a wire callback after CIP match."
                ),
                "metadata": {
                    "ssn": customer["ssn"],
                    "balance": balance,
                    "account_number": account["account_number"] if account else None,
                    "customer_id": customer["customer_id"],
                    "date_of_birth": customer["date_of_birth"],
                },
            }
        )
    return transcripts


def _build_graph_nodes(
    customers: list[dict[str, Any]],
    households: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project customers, households, accounts, and joint txns into graph nodes."""

    nodes: list[dict[str, Any]] = []

    for household in households:
        connections = list(household["member_ids"])
        household_accounts = [
            account["account_id"]
            for account in accounts
            if account["household_id"] == household["household_id"]
        ]
        connections.extend(household_accounts)
        nodes.append(
            {
                "node_id": household["household_id"],
                "node_type": "household",
                "label": household["household_id"],
                "connections": connections,
                "metadata": {
                    "primary_customer_id": household["primary_customer_id"],
                    "combined_aum": household["combined_aum"],
                    "member_count": len(household["member_ids"]),
                },
            }
        )

    for customer in customers:
        connections = [customer["household_id"], *customer["account_ids"], *customer["linked_customer_ids"]]
        nodes.append(
            {
                "node_id": customer["customer_id"],
                "node_type": "customer",
                "label": f"{customer['first_name']} {customer['last_name']}",
                "connections": connections,
                "metadata": {
                    "ssn": customer["ssn"],
                    "household_id": customer["household_id"],
                    "email": customer["email"],
                    "risk_tier": customer["risk_tier"],
                    "date_of_birth": customer["date_of_birth"],
                    "relationship": "household_member",
                },
            }
        )

    for account in accounts:
        connections = [account["household_id"], *account["owner_ids"]]
        nodes.append(
            {
                "node_id": account["account_id"],
                "node_type": "account",
                "label": f"{account['account_type']} {account['account_id']}",
                "connections": connections,
                "metadata": {
                    "account_type": account["account_type"],
                    "product_type": account["product_type"],
                    "balance": account["balance"],
                    "status": account["status"],
                    "household_id": account["household_id"],
                    "account_number": account["account_number"],
                    "is_joint": account["is_joint"],
                },
            }
        )

    for transaction in transactions:
        if not transaction["is_joint"]:
            continue
        connections = [
            transaction["account_id"],
            transaction.get("related_account_id"),
            *transaction["customer_ids"],
        ]
        nodes.append(
            {
                "node_id": transaction["transaction_id"],
                "node_type": "transaction",
                "label": f"{transaction['type']} {transaction['transaction_id']}",
                "connections": [item for item in connections if item],
                "metadata": {
                    "amount": transaction["amount"],
                    "type": transaction["type"],
                    "is_joint": True,
                    "timestamp": transaction["timestamp"].isoformat(),
                },
            }
        )

    return nodes


def _reset_collections() -> None:
    settings = get_settings()
    database = get_database(settings)
    for name in (
        settings.customers_collection,
        settings.accounts_collection,
        settings.households_collection,
        settings.transactions_collection,
        settings.transcripts_collection,
        settings.knowledge_collection,
        settings.graph_collection,
        settings.session_turns_collection,
        settings.user_memory_collection,
        settings.checkpoints_collection,
        settings.checkpoint_writes_collection,
        settings.audit_logs_collection,
        settings.lineage_collection,
    ):
        database[name].drop()


def _create_classic_indexes() -> None:
    settings = get_settings()
    get_collection(settings.customers_collection).create_index(
        [("customer_id", ASCENDING)], unique=True
    )
    get_collection(settings.accounts_collection).create_index(
        [("account_id", ASCENDING)], unique=True
    )
    get_collection(settings.accounts_collection).create_index([("household_id", ASCENDING)])
    get_collection(settings.households_collection).create_index(
        [("household_id", ASCENDING)], unique=True
    )
    get_collection(settings.graph_collection).create_index(
        [("node_id", ASCENDING)], unique=True
    )
    get_collection(settings.graph_collection).create_index([("connections", ASCENDING)])
    get_collection(settings.knowledge_collection).create_index([("doc_id", ASCENDING)], unique=True)
    get_collection(settings.knowledge_collection).create_index([("clearance_level", ASCENDING)])
    get_collection(settings.knowledge_collection).create_index([("product_type", ASCENDING)])
    ensure_memory_indexes(settings)
    ensure_audit_indexes(settings)
    get_collection(settings.checkpoints_collection).create_index(
        [("thread_id", ASCENDING), ("checkpoint_id", ASCENDING)]
    )


def _create_search_indexes() -> None:
    """Create Atlas Vector Search and Atlas Search indexes on knowledge_base."""

    settings = get_settings()
    collection = get_collection(settings.knowledge_collection, settings)
    existing = {index["name"] for index in collection.list_search_indexes()}

    vector_model = SearchIndexModel(
        name=settings.vector_index_name,
        type="vectorSearch",
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": settings.embedding_dimensions,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "product_type"},
                {"type": "filter", "path": "clearance_level"},
                {"type": "filter", "path": "document_type"},
                {"type": "filter", "path": "source"},
            ]
        },
    )
    text_model = SearchIndexModel(
        name=settings.text_index_name,
        type="search",
        definition={
            "mappings": {
                "dynamic": False,
                "fields": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "product_type": {"type": "token"},
                    "clearance_level": {"type": "token"},
                    "document_type": {"type": "token"},
                    "source": {"type": "token"},
                },
            }
        },
    )

    to_create = []
    if settings.vector_index_name not in existing:
        to_create.append(vector_model)
    if settings.text_index_name not in existing:
        to_create.append(text_model)
    if to_create:
        collection.create_search_indexes(models=to_create)

    _create_memory_vector_index(settings)


def _create_memory_vector_index(settings) -> None:
    """Create Atlas Vector Search on ``user_memory.embedding`` filtered by customer."""

    collection = get_collection(settings.user_memory_collection, settings)
    existing = {index["name"] for index in collection.list_search_indexes()}
    if settings.memory_vector_index_name in existing:
        return
    try:
        collection.create_search_indexes(
            models=[
                SearchIndexModel(
                    name=settings.memory_vector_index_name,
                    type="vectorSearch",
                    definition={
                        "fields": [
                            {
                                "type": "vector",
                                "path": "embedding",
                                "numDimensions": settings.embedding_dimensions,
                                "similarity": "cosine",
                            },
                            {"type": "filter", "path": "customer_id"},
                            {"type": "filter", "path": "clearance_level"},
                        ]
                    },
                )
            ]
        )
    except Exception as exc:  # noqa: BLE001 — M0 clusters cap search indexes
        print(f"Skipping {settings.memory_vector_index_name}: {exc}")


def _user_memory_facts() -> list[dict[str, Any]]:
    """Return durable customer preferences and history used by long-term memory."""

    return [
        {
            "memory_id": "MEM-0001",
            "customer_id": "CUST-0001",
            "fact": "Customer prefers email alerts over SMS for wire and ACH notifications.",
            "clearance_level": "public",
            "memory_source": "preference_center",
        },
        {
            "memory_id": "MEM-0002",
            "customer_id": "CUST-0001",
            "fact": "User applied for an auto loan in August 2026 and asked to be contacted only after 5 p.m.",
            "clearance_level": "restricted",
            "memory_source": "lending_desk",
        },
        {
            "memory_id": "MEM-0003",
            "customer_id": "CUST-0001",
            "fact": "Household HH-01 uses a joint checking account for recurring mortgage payments.",
            "clearance_level": "internal",
            "memory_source": "relationship_review",
        },
        {
            "memory_id": "MEM-0004",
            "customer_id": "CUST-0001",
            "fact": "Customer requested a 30-day travel notice for Europe starting 2026-09-10.",
            "clearance_level": "public",
            "memory_source": "card_services",
        },
        {
            "memory_id": "MEM-0005",
            "customer_id": "CUST-0002",
            "fact": "Customer prefers paperless statements and declined overdraft protection.",
            "clearance_level": "public",
            "memory_source": "preference_center",
        },
        {
            "memory_id": "MEM-0006",
            "customer_id": "CUST-0002",
            "fact": "Customer inquired about a HELOC in July 2026 against the household primary residence.",
            "clearance_level": "restricted",
            "memory_source": "lending_desk",
        },
        {
            "memory_id": "MEM-0007",
            "customer_id": "CUST-0003",
            "fact": "Customer is the primary caregiver on the household and must approve large wires.",
            "clearance_level": "internal",
            "memory_source": "relationship_review",
        },
        {
            "memory_id": "MEM-0008",
            "customer_id": "CUST-0003",
            "fact": "Customer asked to receive fraud alerts by push notification, not email.",
            "clearance_level": "public",
            "memory_source": "preference_center",
        },
    ]


def seed_user_memory() -> int:
    """Upsert long-term memory facts and ensure the memory vector index exists."""

    settings = get_settings()
    facts = _user_memory_facts()
    embeddings = _chunked_embed([item["fact"] for item in facts])
    collection = get_collection(settings.user_memory_collection, settings)
    now = datetime.now(timezone.utc)
    for fact, embedding in zip(facts, embeddings, strict=True):
        document = {
            **fact,
            "content": fact["fact"],
            "title": f"Memory for {fact['customer_id']}",
            "source": "user_memory",
            "document_type": "customer_memory",
            "created_at": now,
            "metadata": {"memory_source": fact["memory_source"]},
            "embedding": embedding,
        }
        collection.replace_one({"memory_id": fact["memory_id"]}, document, upsert=True)
    ensure_memory_indexes(settings)
    ensure_audit_indexes(settings)
    _create_memory_vector_index(settings)
    return len(facts)


def seed() -> dict[str, int]:
    """Load synthetic banking data, embeddings, and search indexes into Atlas."""

    settings = get_settings()
    health = ping_atlas()
    if not health.get("ok"):
        raise RuntimeError(f"Cannot reach Atlas: {health.get('error')}")

    random.seed(FAKER_SEED)
    fake = Faker()
    Faker.seed(FAKER_SEED)

    households, customers = _split_customers(fake)
    accounts = _build_accounts(fake, customers, households)
    transactions = _build_transactions(fake, accounts)
    transcripts = _build_transcripts(fake, customers, accounts)
    policies = _policy_documents()[:POLICY_COUNT]
    graph_nodes = _build_graph_nodes(customers, households, accounts, transactions)

    knowledge_docs = []
    for policy in policies:
        knowledge_docs.append(
            {
                **policy,
                "source": "knowledge_base",
                "metadata": {
                    "document_type": policy["document_type"],
                    "product_type": policy["product_type"],
                    "clearance_level": policy["clearance_level"],
                },
            }
        )
    for transcript in transcripts:
        knowledge_docs.append(
            {
                "doc_id": transcript["doc_id"],
                "title": transcript["title"],
                "content": transcript["content"],
                "document_type": transcript["document_type"],
                "product_type": transcript["product_type"],
                "clearance_level": transcript["clearance_level"],
                "source": "transcript",
                "customer_id": transcript["customer_id"],
                "metadata": transcript["metadata"],
            }
        )

    print(f"Embedding {len(knowledge_docs)} knowledge documents...")
    embeddings = _chunked_embed(
        [f"{doc['title']}\n\n{doc['content']}" for doc in knowledge_docs]
    )
    for document, embedding in zip(knowledge_docs, embeddings, strict=True):
        document["embedding"] = embedding

    _reset_collections()
    get_collection(settings.households_collection).insert_many(households)
    get_collection(settings.customers_collection).insert_many(customers)
    get_collection(settings.accounts_collection).insert_many(accounts)
    get_collection(settings.transactions_collection).insert_many(transactions)
    get_collection(settings.transcripts_collection).insert_many(transcripts)
    get_collection(settings.knowledge_collection).insert_many(knowledge_docs)
    get_collection(settings.graph_collection).insert_many(graph_nodes)
    _create_classic_indexes()
    _create_search_indexes()
    memory_count = seed_user_memory()

    counts = {
        "households": len(households),
        "customers": len(customers),
        "accounts": len(accounts),
        "transactions": len(transactions),
        "transcripts": len(transcripts),
        "knowledge_base": len(knowledge_docs),
        "graph_nodes": len(graph_nodes),
        "user_memory": memory_count,
    }
    print("Seed complete:", counts)
    print(
        "Vector and text indexes are building in Atlas. "
        "$vectorSearch is available after the kb_vector_index status is READY."
    )
    return counts


if __name__ == "__main__":
    if "--memory-only" in sys.argv:
        count = seed_user_memory()
        print(f"Seeded {count} user_memory facts and ensured indexes.")
    else:
        seed()
