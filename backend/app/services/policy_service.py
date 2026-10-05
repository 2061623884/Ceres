"""The guide and Mercury share the same simulated store policy rows."""

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models.order import AfterSalesPolicy


def initialize_policies(db: Session) -> None:
    from mercury.seed import POLICIES

    db.execute(insert(AfterSalesPolicy).values([
        {"policy_id": policy_id, "category": category, "title": title,
         "content": content, "keywords": keywords}
        for policy_id, category, title, content, keywords in POLICIES
    ]).on_conflict_do_nothing(index_elements=["policy_id"]))


def search_policies(db: Session, query: str) -> dict:
    from mercury.policy import rank_policies

    rows = db.query(AfterSalesPolicy).order_by(AfterSalesPolicy.policy_id).all()
    policies = rank_policies([
        {field: getattr(row, field) for field in
         ("policy_id", "category", "title", "content", "keywords")}
        for row in rows
    ], query, None, 3)
    return {"kind": "policy", "status": "completed", "policies": policies,
            "empty": not policies, "business_data_mode": "demo"}
